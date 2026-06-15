import re
import random
import time

import requests

from .app_config import MAX_TRANSLATE_CHARS


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


def translate_text_chunk(text: str, target_language: str, log_message=None, session=None):
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_language,
        "dt": "t",
        "q": text,
    }
    http_client = session or requests

    for attempt in range(1, 4):
        try:
            response = http_client.get(url, params=params, timeout=30)

            if response.status_code == 200:
                result = response.json()
                return ''.join(s[0] for s in result[0] if s and s[0])

            if response.status_code not in {429, 500, 502, 503, 504}:
                if log_message:
                    log_message(f"[ERRO API] Codigo HTTP {response.status_code}")
                return None

            if log_message:
                log_message(f"[ERRO API] Codigo HTTP {response.status_code}; tentativa {attempt}/3")

        except requests.RequestException as e:
            if log_message:
                log_message(f"[ERRO API] {e}; tentativa {attempt}/3")
        except Exception as e:
            if log_message:
                log_message(f"[ERRO API] Resposta inesperada: {e}")
            return None

        if attempt < 3:
            time.sleep(random.uniform(0.3, 2.2))

    return None


def translate_text(
    text: str,
    target_language: str,
    log_message=None,
    cancel_flag=None,
    session=None,
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
        )
        if translated is None:
            return None
        translated_chunks.append(translated)

    return " ".join(part.strip() for part in translated_chunks if part.strip())
