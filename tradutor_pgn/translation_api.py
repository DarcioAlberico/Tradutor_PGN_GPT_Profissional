from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Protocol

import requests

from .app_config import (
    MAX_TRANSLATE_CHARS,
    PACE_CLEAN_STREAK,
    PACE_DECAY,
    PACE_FIRST_MULTIPLIER,
    PACE_GROWTH,
    PACE_MAX_MULTIPLIER,
    TRANSLATION_REQUEST_DELAY_SECONDS,
)
from .google_cooldown import GoogleCooldown



# O nome do motor, como vai para o registro de execucoes (garantia Z5). Hoje ha
# um so; o provedor de 28.7 grava o seu, e "Reverter execucao" e o que permite
# trocar de motor sem medo.
TRANSLATION_PROVIDER = "google-gtx"

MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Espera entre tentativas. Era constante com jitter (`random.uniform(0.3, 2.2)`),
# o que contra 429 e quase o mesmo que nao esperar: se o servidor pediu para
# desacelerar, a terceira tentativa chegava tao cedo quanto a primeira.
RETRY_BASE_SECONDS = 0.6
# 429 e o servidor dizendo que o ritmo esta alto demais; 5xx e problema
# passageiro dele. Sao causas diferentes e merecem esperas diferentes.
RETRY_BASE_429_SECONDS = 2.0
RETRY_MAX_SECONDS = 20.0
# Jitter multiplicativo, nao aditivo: duas execucoes que tomem 429 ao mesmo tempo
# precisam se espalhar em proporcao a espera, senao voltam juntas.
RETRY_JITTER = (0.5, 1.5)
MAX_SERVER_WAIT_SECONDS = 3600.0

# Os dois "objetos" que o worker entrega a camada de rede, pelo que eles FAZEM
# e nao pelo que sao (ROADMAP 28.11, tipos): qualquer coisa que se chame com
# uma string serve de log, e qualquer coisa com `is_set()` serve de flag — o
# `threading.Event` do app e o `SimpleNamespace` dos testes.
LogMessage = Callable[[str], object]


class CancelFlag(Protocol):
    def is_set(self) -> bool: ...


def retry_delay_seconds(
    attempt: int, status_code: int | None = None, jitter: float | None = None
) -> float:
    """Espera antes da tentativa seguinte, exponencial e com jitter.

    `attempt` comeca em 1. `jitter` aceita um fator fixo, para teste.
    """
    base = RETRY_BASE_429_SECONDS if status_code == 429 else RETRY_BASE_SECONDS
    alvo = min(base * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
    fator = random.uniform(*RETRY_JITTER) if jitter is None else jitter
    return alvo * fator


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Retorna segundos do cabeçalho HTTP, ou None para um valor inválido."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        value = value.lstrip('0') or '0'
        return float('inf') if len(value) > 15 else float(int(value))
    try:
        moment = parsedate_to_datetime(value)
        if moment.tzinfo is None:
            return None
        return max(0.0, moment.timestamp() - (time.time() if now is None else now))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def wait_for_server_delay(delay: float, cancel_flag: CancelFlag | None) -> bool:
    """Aguarda; retorna True se o usuário cancelou durante a espera."""
    if cancel_flag is None:
        time.sleep(delay)
        return False
    wait = getattr(cancel_flag, "wait", None)
    if callable(wait):
        return bool(wait(delay))
    remaining = delay
    while remaining > 0:
        if cancel_flag.is_set():
            return True
        interval = min(0.25, remaining)
        time.sleep(interval)
        remaining -= interval
    return cancel_flag.is_set()


@dataclass
class GoogleRequestMetrics:
    attempts: int = 0
    characters: int = 0
    forbidden: int = 0
    rate_limited: int = 0
    shared_wait_seconds: float = 0.0
    quota_wait_seconds: float = 0.0
    cooldown_wait_seconds: float = 0.0
    overlap_wait_seconds: float = 0.0

    def record_wait(self, reason: str | None, seconds: float) -> None:
        if reason == "quota":
            self.quota_wait_seconds += seconds
        elif reason == "cooldown":
            self.cooldown_wait_seconds += seconds
        elif reason == "both":
            self.overlap_wait_seconds += seconds

    def record_attempt(self, characters: int) -> None:
        self.attempts += 1
        self.characters += characters

    def record_status(self, status: int) -> None:
        self.forbidden += int(status == 403)
        self.rate_limited += int(status == 429)


class RequestPacer:
    """Intervalo entre requisicoes que reage ao que a API responde.

    O endpoint e publico e nao oficial, e o intervalo normal foi sendo reduzido
    para render mais — o que tambem aumenta a chance de 429. O retry nao cobre
    isso: ele resolve a requisicao que falhou, nao a causa. Um 429 e o unico
    sinal confiavel de que o ritmo esta alto demais, entao ele multiplica o
    intervalo de todas as requisicoes seguintes.

    Sobe rapido e desce devagar. Em repouso o comportamento e identico ao de
    antes: multiplicador 1, e o sorteio no intervalo de sempre.
    """

    def __init__(
        self,
        base_range: tuple[float, float] = TRANSLATION_REQUEST_DELAY_SECONDS,
        first_multiplier: float = PACE_FIRST_MULTIPLIER,
        growth: float = PACE_GROWTH,
        maximum: float = PACE_MAX_MULTIPLIER,
        decay: float = PACE_DECAY,
        clean_streak: int = PACE_CLEAN_STREAK,
        shared_cooldown: GoogleCooldown | None = None,
    ) -> None:
        self.base_range = base_range
        self.first_multiplier = first_multiplier
        self.growth = growth
        self.maximum = maximum
        self.decay = decay
        self.clean_streak = clean_streak
        self.multiplier = 1.0
        self.clean_run = 0
        self.rate_limited = 0
        self.retry_after_blocked = False
        self.retry_after_not_before = 0.0
        self.shared_cooldown = shared_cooldown
        self.metrics = GoogleRequestMetrics()

    def wait_shared(self, cancel_flag: CancelFlag | None, log_message: LogMessage | None) -> bool:
        if self.shared_cooldown is None:
            return True
        started = time.monotonic()
        try:
            if isinstance(self.shared_cooldown, GoogleCooldown):
                def announce() -> None:
                    if log_message:
                        log_message("[API] Aguardando limite de requisições; você pode cancelar.")
                allowed = self.shared_cooldown.wait(cancel_flag, on_wait=announce, on_delay=self.metrics.record_wait)
            else:
                allowed = self.shared_cooldown.wait(cancel_flag)
        except Exception:
            # A mensagem da exceção pode conter o caminho de dados do usuário.
            self.retry_after_blocked = True
            if log_message:
                log_message("[ERRO API] Não foi possível verificar o controle compartilhado de espera.")
            return False
        finally:
            self.metrics.shared_wait_seconds += max(0.0, time.monotonic() - started)
        if cancel_flag is not None and cancel_flag.is_set():
            return False
        if not allowed and log_message:
            log_message("[AVISO API] Limite ou pausa do serviço ainda ativo; tente novamente mais tarde.")
        return allowed

    def defer_shared(self, seconds: float, log_message: LogMessage | None) -> bool:
        if self.shared_cooldown is None:
            return True
        try:
            self.shared_cooldown.defer(seconds)
        except Exception:
            self.retry_after_blocked = True
            if log_message:
                log_message("[ERRO API] Não foi possível salvar o controle compartilhado de espera.")
            return False
        return True

    def record_rate_limited(self) -> None:
        """A API reclamou do ritmo: desacelera e zera a sequencia limpa."""
        self.rate_limited += 1
        self.clean_run = 0
        alvo = max(self.multiplier * self.growth, self.first_multiplier)
        self.multiplier = min(alvo, self.maximum)

    def record_success(self) -> None:
        """Uma requisicao passou. So acelera depois de uma sequencia limpa."""
        if self.multiplier <= 1.0:
            return
        self.clean_run += 1
        if self.clean_run >= self.clean_streak:
            self.clean_run = 0
            self.multiplier = max(1.0, self.multiplier * self.decay)

    def next_delay(self) -> float:
        return random.uniform(*self.base_range) * self.multiplier


def split_text_for_translation(text: str, max_chars: int = MAX_TRANSLATE_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""
    parts = re.split(r'(?<=[.!?;:])\s+', text)

    for part in parts:
        if not part:
            continue

        if len(part) > max_chars:
            if current:
                chunks.append(current)
                current = ""

            for start in range(0, len(part), max_chars):
                chunks.append(part[start:start + max_chars])
            continue

        candidate = part if not current else f"{current} {part}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    return chunks


def translate_text_chunk(
    text: str,
    target_language: str,
    log_message: LogMessage | None = None,
    session: requests.Session | None = None,
    pacer: RequestPacer | None = None,
    source_language: str = "",
    cancel_flag: CancelFlag | None = None,
) -> str | None:
    """Traduz um trecho. `source_language` vazio mantem o `sl=auto` de sempre.

    Declarar o idioma de origem nao e so metadado: `sl=auto` faz o endpoint
    adivinhar a partir do texto, e um comentario curto de xadrez — "Ng5!", "Bien
    jugado" — e pouco texto para adivinhar. Dito o idioma, ele para de tentar.

    **`cancel_flag` alcanca o laco de tentativas** (ROADMAP 22.13). Esta funcao
    nem recebia o flag: `translate_text` o conferia so ENTRE chunks, e o laco de
    tres tentativas dormia em `time.sleep` sem olhar cancelamento nenhum. Com o
    timeout real de 30 s por tentativa, a janela em que "Cancelar" nao tem efeito
    chega a ~93 s por chunk contra um endpoint que pendura a conexao — que e
    justamente o cenario em que mais se clica Cancelar. Reproduzido com sessao
    falsa: flag ligado durante a primeira tentativa, e as tres rodaram mesmo
    assim.

    Conferido em dois pontos, e os dois sao necessarios: antes de cada tentativa
    (senao o cancelamento durante a espera ainda dispara a requisicao seguinte) e
    antes de cada espera (senao espera-se 1,5 s para depois desistir). A
    requisicao EM VOO continua inevitavel — quem a interromperia seria o timeout
    do `requests`, e ele ja esta em 30 s.

    Devolve `None` ao cancelar, que e o que os chamadores ja tratam como "nao
    traduziu": para eles, cancelado e falha sao o mesmo caminho.
    """
    def cancelado() -> bool:
        return cancel_flag is not None and cancel_flag.is_set()

    if cancelado():
        return None
    if pacer is not None and pacer.retry_after_blocked:
        return None
    if pacer is not None:
        remaining = max(0.0, pacer.retry_after_not_before - time.monotonic())
        if remaining:
            if wait_for_server_delay(remaining, cancel_flag) or cancelado():
                return None
        pacer.retry_after_not_before = 0.0

    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": source_language or "auto",
        "tl": target_language,
        "dt": "t",
        "q": text,
    }
    http_client = session or requests

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if cancelado():
            return None
        if pacer is not None and not pacer.wait_shared(cancel_flag, log_message):
            return None
        if cancelado():
            return None
        status_code = None
        server_wait = None
        try:
            if pacer is not None:
                pacer.metrics.record_attempt(len(text))
            response = http_client.get(url, params=params, timeout=30)
            status_code = response.status_code
            if pacer is not None:
                pacer.metrics.record_status(status_code)

            if status_code == 403 and pacer is not None:
                retry_after = parse_retry_after(getattr(response, "headers", {}).get("Retry-After"))
                if not pacer.defer_shared(max(300.0, retry_after or 0.0), log_message):
                    return None

            if status_code == 200:
                result = response.json()
                traduzido = ''.join(s[0] for s in result[0] if s and s[0])
                # So depois de a resposta ser lida com sucesso: uma 200 ilegivel
                # nao e sinal de que o ritmo esta bom.
                if pacer is not None:
                    pacer.record_success()
                return traduzido

            if status_code not in RETRYABLE_STATUS:
                if log_message:
                    log_message(f"[ERRO API] Codigo HTTP {status_code}")
                return None

            if status_code == 429 and pacer is not None:
                # Desacelera as próximas requisições, inclusive se a espera
                # solicitada for longa demais para continuar esta execução.
                pacer.record_rate_limited()

            headers = getattr(response, "headers", {})
            server_wait = parse_retry_after(headers.get("Retry-After"))
            if pacer is not None and (status_code == 429 or server_wait is not None):
                shared_wait = max(server_wait or 0.0, 30.0 if status_code == 429 else 0.0)
                if not pacer.defer_shared(shared_wait, log_message):
                    return None
            if server_wait is not None:
                if server_wait > MAX_SERVER_WAIT_SECONDS:
                    if pacer is not None:
                        pacer.retry_after_blocked = True
                    if log_message:
                        log_message("[ERRO API] Espera solicitada muito longa; novas tentativas interrompidas nesta execução.")
                    return None
                if pacer is not None:
                    pacer.retry_after_not_before = time.monotonic() + server_wait

            if log_message:
                log_message(
                    f"[ERRO API] Codigo HTTP {status_code}; "
                    f"tentativa {attempt}/{MAX_ATTEMPTS}"
                )

        except requests.RequestException as e:
            if log_message:
                log_message(f"[ERRO API] {e}; tentativa {attempt}/{MAX_ATTEMPTS}")
        except Exception as e:
            if log_message:
                log_message(f"[ERRO API] Resposta inesperada: {e}")
            return None

        if attempt < MAX_ATTEMPTS:
            if cancelado():
                return None
            delay = retry_delay_seconds(attempt, status_code)
            if server_wait is not None:
                delay = max(delay, server_wait)
            if wait_for_server_delay(delay, cancel_flag):
                return None
            if server_wait is not None and pacer is not None:
                pacer.retry_after_not_before = 0.0

    return None


def translate_text(
    text: str,
    target_language: str,
    log_message: LogMessage | None = None,
    cancel_flag: CancelFlag | None = None,
    session: requests.Session | None = None,
    pacer: RequestPacer | None = None,
    source_language: str = "",
) -> str | None:
    chunks = split_text_for_translation(text)
    if len(chunks) > 1 and log_message:
        log_message(f"Comentario longo dividido em {len(chunks)} partes.")

    translated_chunks = []
    for chunk in chunks:
        if cancel_flag is not None and cancel_flag.is_set():
            return None

        translated = translate_text_chunk(
            chunk,
            target_language,
            log_message,
            session=session,
            pacer=pacer,
            source_language=source_language,
            # O flag ATRAVESSA (ROADMAP 22.13). A conferencia acima cobre a
            # fronteira entre chunks; sem passa-lo adiante, um comentario de um
            # chunk so — a maioria — nao tinha nenhuma.
            cancel_flag=cancel_flag,
        )
        if translated is None:
            return None
        translated_chunks.append(translated)

    return " ".join(part.strip() for part in translated_chunks if part.strip())
