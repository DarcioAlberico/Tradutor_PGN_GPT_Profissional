"""Shared glossary values and pure legacy-compatible normalization.

This module has no persistence or adapter dependencies, so the catalog and the
legacy text adapter can use precisely the same phase, priority and scope rules.
"""

GLOSSARY_RULE_SUGGESTION = "suggestion"
GLOSSARY_RULE_CLEANUP = "cleanup"
GLOSSARY_RULE_AUTOMATIC = "automatic"
GLOSSARY_RULE_TYPES = (
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_AUTOMATIC,
)
GLOSSARY_PRIORITY_DEFAULT = 0

# Scope names the TARGET language or the complete source>target pair. Empty
# means all pairs; '*' is its explicit spelling in a file with a default scope.
GLOSSARY_SCOPE_ALL = ""
GLOSSARY_SCOPE_ANY = "*"
GLOSSARY_SCOPE_SEPARATOR = ">"
GLOSSARY_SCOPE_VARIABLES = {"escopo", "escopo_padrao", "scope", "default_scope"}

GLOSSARY_RULE_TYPE_ALIASES = {
    "sugestao": GLOSSARY_RULE_SUGGESTION,
    "sugestão": GLOSSARY_RULE_SUGGESTION,
    "sugestões": GLOSSARY_RULE_SUGGESTION,
    "suggestion": GLOSSARY_RULE_SUGGESTION,
    "limpeza": GLOSSARY_RULE_CLEANUP,
    "limpar": GLOSSARY_RULE_CLEANUP,
    "cleanup": GLOSSARY_RULE_CLEANUP,
    "clean": GLOSSARY_RULE_CLEANUP,
    "auto": GLOSSARY_RULE_AUTOMATIC,
    "automatica": GLOSSARY_RULE_AUTOMATIC,
    "automática": GLOSSARY_RULE_AUTOMATIC,
    "automatico": GLOSSARY_RULE_AUTOMATIC,
    "automático": GLOSSARY_RULE_AUTOMATIC,
    "automatic": GLOSSARY_RULE_AUTOMATIC,
}


def _rule_type_alias(value):
    """Return the recognized canonical phase, or None for an unknown value."""
    texto = "" if value is None else str(value).strip()
    if not texto:
        return None
    canonico = GLOSSARY_RULE_TYPE_ALIASES.get(texto.casefold(), texto)
    return canonico if canonico in GLOSSARY_RULE_TYPES else None


def _normalize_rule_type(rule_type):
    """Preserve the legacy suggestion default, including unknown phases."""
    return _rule_type_alias(rule_type) or GLOSSARY_RULE_SUGGESTION


def normalize_glossary_priority(value):
    """Integer priority, or zero for absent, boolean or invalid input."""
    if isinstance(value, bool) or value is None:
        return GLOSSARY_PRIORITY_DEFAULT
    try:
        return int(value)
    except (TypeError, ValueError):
        return GLOSSARY_PRIORITY_DEFAULT


def normalize_glossary_scope(value):
    """Canonical scope; unknown language codes stay restricted, never global."""
    texto = "" if value is None else str(value).strip()
    if not texto or texto == GLOSSARY_SCOPE_ANY:
        return GLOSSARY_SCOPE_ALL
    if GLOSSARY_SCOPE_SEPARATOR in texto:
        origem, destino = texto.split(GLOSSARY_SCOPE_SEPARATOR, 1)
        origem = origem.strip()
        destino = destino.strip()
        if origem == GLOSSARY_SCOPE_ANY:
            origem = ""
        if destino == GLOSSARY_SCOPE_ANY:
            destino = ""
        if not origem and not destino:
            return GLOSSARY_SCOPE_ALL
        return f"{origem}{GLOSSARY_SCOPE_SEPARATOR}{destino}"
    return texto


def normalize_glossary_text(value):
    """Trim text ends without changing case or internal whitespace."""
    return "" if value is None else str(value).strip()
