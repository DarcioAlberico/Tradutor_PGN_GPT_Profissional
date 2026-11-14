"""Adaptador do Google oferecido pela biblioteca deep-translator."""
import time
from types import FunctionType, SimpleNamespace

import requests
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TooManyRequests

from .translation_api import (
    MAX_SERVER_WAIT_SECONDS,
    RequestPacer,
    parse_retry_after,
    split_text_for_translation,
    wait_for_server_delay,
)


class _ServerThrottle(Exception):
    def __init__(self, status, retry_after):
        self.status = status
        self.retry_after = retry_after


class _SharedWaitStopped(Exception):
    pass


def timed_google_translator(source, target):
    """Use the library parser with a request timeout local to this instance.

    deep-translator 1.11.4 does not expose a timeout. Rebind its method to
    an isolated globals dictionary so other threads and libraries are untouched.
    """
    client = GoogleTranslator(source=source, target=target)
    client._before_http = None
    client._metrics = None
    original = GoogleTranslator.translate
    namespace = dict(original.__globals__)
    def get(*args, **kwargs):
        if client._before_http is not None and not client._before_http():
            raise _SharedWaitStopped()
        if client._metrics is not None:
            client._metrics.record_attempt(len(kwargs.get("params", {}).get("q", "")))
        response = requests.get(*args, timeout=30, **kwargs)
        if client._metrics is not None:
            client._metrics.record_status(response.status_code)
        if response.status_code in (403, 429, 503):
            try:
                headers = getattr(response, "headers", {})
                raise _ServerThrottle(response.status_code, headers.get("Retry-After"))
            finally:
                response.close()
        return response

    namespace["requests"] = SimpleNamespace(get=get)
    bounded = FunctionType(original.__code__, namespace, original.__name__,
                           original.__defaults__, original.__closure__)
    client.translate = bounded.__get__(client, type(client))
    return client


class DeepTranslatorAdapter:
    """Uma instância por execução sequencial; não compartilhe entre threads.

    O cliente da biblioteca altera parâmetros internos a cada chamada. O
    controlador de ritmo também pertence ao mesmo worker e não coordena
    chamadas concorrentes nem processos diferentes.
    """

    def __init__(self, source_language, target_language):
        self.client = timed_google_translator(source_language or "auto", target_language)
        self._last_request_finished = None
        self._retry_control = RequestPacer()

    def translate(self, text, log_message=None, cancel_flag=None, pacer=None):
        result = []
        controls = (self._retry_control,) if pacer is None else (self._retry_control, pacer)
        for chunk in split_text_for_translation(text, max_chars=4999):
            if cancel_flag is not None and cancel_flag.is_set():
                return None
            if any(control.retry_after_blocked for control in controls):
                return None
            remaining = max(0.0, max(control.retry_after_not_before for control in controls) - time.monotonic())
            if remaining and wait_for_server_delay(remaining, cancel_flag):
                return None
            for control in controls:
                control.retry_after_not_before = 0.0
            if self._last_request_finished is not None and pacer is not None:
                elapsed = time.monotonic() - self._last_request_finished
                delay = max(0.0, pacer.next_delay() - elapsed)
                if delay:
                    if cancel_flag is not None and hasattr(cancel_flag, "wait"):
                        if cancel_flag.wait(delay):
                            return None
                    else:
                        time.sleep(delay)
            if cancel_flag is not None and cancel_flag.is_set():
                return None
            self.client._before_http = (
                None if pacer is None else lambda: pacer.wait_shared(cancel_flag, log_message)
            )
            self.client._metrics = None if pacer is None else pacer.metrics
            try:
                translated = self.client.translate(chunk)
            except _SharedWaitStopped:
                return None
            except _ServerThrottle as exc:
                if exc.status == 429 and pacer is not None:
                    pacer.record_rate_limited()
                delay = parse_retry_after(exc.retry_after)
                if pacer is not None and (exc.status in (403, 429) or delay is not None):
                    minimum = 300.0 if exc.status == 403 else 30.0 if exc.status == 429 else 0.0
                    if not pacer.defer_shared(max(delay or 0.0, minimum), log_message):
                        return None
                if delay is not None:
                    for control in controls:
                        if delay > MAX_SERVER_WAIT_SECONDS:
                            control.retry_after_blocked = True
                        else:
                            control.retry_after_not_before = time.monotonic() + delay
                if log_message:
                    log_message(f"[ERRO deep-translator] Servidor temporariamente indisponível (HTTP {exc.status}).")
                return None
            except TooManyRequests:
                if pacer is not None:
                    pacer.record_rate_limited()
                if log_message:
                    log_message("[ERRO deep-translator] Limite de requisicoes atingido.")
                return None
            except Exception as exc:
                if log_message:
                    log_message(f"[ERRO deep-translator] Falha na tradução ({type(exc).__name__}).")
                return None
            finally:
                self.client._before_http = None
                self.client._metrics = None
                self._last_request_finished = time.monotonic()
            if not isinstance(translated, str) or not translated.strip():
                return None
            if pacer is not None:
                pacer.record_success()
            result.append(translated.strip())
        return " ".join(result)
