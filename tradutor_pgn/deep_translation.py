"""Adaptador do Google oferecido pela biblioteca deep-translator."""
import time
from types import FunctionType, SimpleNamespace

import requests
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TooManyRequests

from .translation_api import split_text_for_translation


def timed_google_translator(source, target):
    """Use the library parser with a request timeout local to this instance.

    deep-translator 1.11.4 does not expose a timeout. Rebind its method to
    an isolated globals dictionary so other threads and libraries are untouched.
    """
    client = GoogleTranslator(source=source, target=target)
    original = GoogleTranslator.translate
    namespace = dict(original.__globals__)
    namespace["requests"] = SimpleNamespace(
        get=lambda *args, **kwargs: requests.get(*args, timeout=30, **kwargs)
    )
    bounded = FunctionType(original.__code__, namespace, original.__name__,
                           original.__defaults__, original.__closure__)
    client.translate = bounded.__get__(client, type(client))
    return client


class DeepTranslatorAdapter:
    def __init__(self, source_language, target_language):
        self.client = timed_google_translator(source_language or "auto", target_language)
        self._last_request_finished = None

    def translate(self, text, log_message=None, cancel_flag=None, pacer=None):
        result = []
        for chunk in split_text_for_translation(text, max_chars=4999):
            if cancel_flag is not None and cancel_flag.is_set():
                return None
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
            try:
                translated = self.client.translate(chunk)
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
                self._last_request_finished = time.monotonic()
            if not isinstance(translated, str) or not translated.strip():
                return None
            if pacer is not None:
                pacer.record_success()
            result.append(translated.strip())
        return " ".join(result)
