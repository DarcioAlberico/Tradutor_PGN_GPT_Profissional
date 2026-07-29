import re
import random
import time

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


def retry_delay_seconds(attempt, status_code=None, jitter=None):
    """Espera antes da tentativa seguinte, exponencial e com jitter.

    `attempt` comeca em 1. `jitter` aceita um fator fixo, para teste.
    """
    base = RETRY_BASE_429_SECONDS if status_code == 429 else RETRY_BASE_SECONDS
    alvo = min(base * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
    fator = random.uniform(*RETRY_JITTER) if jitter is None else jitter
    return alvo * fator


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
        base_range=TRANSLATION_REQUEST_DELAY_SECONDS,
        first_multiplier=PACE_FIRST_MULTIPLIER,
        growth=PACE_GROWTH,
        maximum=PACE_MAX_MULTIPLIER,
        decay=PACE_DECAY,
        clean_streak=PACE_CLEAN_STREAK,
    ):
        self.base_range = base_range
        self.first_multiplier = first_multiplier
        self.growth = growth
        self.maximum = maximum
        self.decay = decay
        self.clean_streak = clean_streak
        self.multiplier = 1.0
        self.clean_run = 0
        self.rate_limited = 0

    def record_rate_limited(self):
        """A API reclamou do ritmo: desacelera e zera a sequencia limpa."""
        self.rate_limited += 1
        self.clean_run = 0
        alvo = max(self.multiplier * self.growth, self.first_multiplier)
        self.multiplier = min(alvo, self.maximum)

    def record_success(self):
        """Uma requisicao passou. So acelera depois de uma sequencia limpa."""
        if self.multiplier <= 1.0:
            return
        self.clean_run += 1
        if self.clean_run >= self.clean_streak:
            self.clean_run = 0
            self.multiplier = max(1.0, self.multiplier * self.decay)

    def next_delay(self):
        return random.uniform(*self.base_range) * self.multiplier


def split_text_for_translation(text: str, max_chars=MAX_TRANSLATE_CHARS):
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
    log_message=None,
    session=None,
    pacer=None,
    source_language="",
):
    """Traduz um trecho. `source_language` vazio mantem o `sl=auto` de sempre.

    Declarar o idioma de origem nao e so metadado: `sl=auto` faz o endpoint
    adivinhar a partir do texto, e um comentario curto de xadrez — "Ng5!", "Bien
    jugado" — e pouco texto para adivinhar. Dito o idioma, ele para de tentar.
    """
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
        status_code = None
        try:
            response = http_client.get(url, params=params, timeout=30)
            status_code = response.status_code

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
                # Desacelera as requisicoes SEGUINTES, nao so esta. Repetir esta
                # tres vezes e depois voltar ao ritmo antigo so produz o proximo
                # 429.
                pacer.record_rate_limited()

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
            time.sleep(retry_delay_seconds(attempt, status_code))

    return None


def translate_text(
    text: str,
    target_language: str,
    log_message=None,
    cancel_flag=None,
    session=None,
    pacer=None,
    source_language="",
):
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
        )
        if translated is None:
            return None
        translated_chunks.append(translated)

    return " ".join(part.strip() for part in translated_chunks if part.strip())
