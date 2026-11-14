"""Conversões de interface que preservam escopos avançados do glossário."""
import unicodedata

from .app_config import LANGUAGE_NAMES
from .glossary_types import normalize_glossary_scope


def normalize_search_text(value):
    if value.isascii():
        return value.casefold()
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold())
                   if unicodedata.category(c) != "Mn")


def scope_to_codes(raw):
    scope = normalize_glossary_scope(raw)
    if not scope:
        return "", ""
    parts = scope.split(">")
    if len(parts) == 1:
        source, target = "", parts[0]
    elif len(parts) == 2:
        source, target = parts
    else:
        return None
    if (source and source not in LANGUAGE_NAMES) or (target and target not in LANGUAGE_NAMES):
        return None
    return source, target


def scope_from_codes(source, target):
    if (source and source not in LANGUAGE_NAMES) or (target and target not in LANGUAGE_NAMES):
        raise ValueError("Idioma desconhecido")
    if source:
        return f"{source}>{target}"
    return target or "*"


def describe_scope(raw):
    codes = scope_to_codes(raw)
    if codes is None:
        return "Escopo personalizado: confira o campo avançado."
    source, target = codes
    if not source and not target:
        return "Aplica-se a todos os idiomas."
    source_label = LANGUAGE_NAMES.get(source, "qualquer origem")
    target_label = LANGUAGE_NAMES.get(target, "qualquer destino")
    return f"Aplica-se a {source_label} → {target_label}."
