"""Validação das preferências da biblioteca."""

from . import settings


def parse_preferences(value):
    value = value if isinstance(value, dict) else {}
    def choice(key, options, default):
        candidate = value.get(key)
        return candidate if isinstance(candidate, str) and candidate in options else default
    def facet(key):
        candidate = value.get(key)
        return candidate if isinstance(candidate, str) and len(candidate) <= 200 else None
    return {
        "status": choice("status", {"ready", "legacy", "incomplete", "invalid"}, None),
        "order": choice("order", {"name", "reverse_name", "recent", "oldest", "failures_asc", "failures_desc"}, "name"),
        "failures": choice("failures", {"with", "without", "unknown"}, None),
        "source": facet("source"), "target": facet("target"), "provider": facet("provider"),
    }


def save_preferences(value, *, path=None):
    path = settings.default_settings_path() if path is None else path
    with settings._UPDATE_LOCK, settings._settings_process_lock(path):
        data = settings.read_settings_strict(path)
        section = data.get("translation_library", {})
        if not isinstance(section, dict):
            raise ValueError("Preferências da biblioteca inválidas")
        section.update(parse_preferences(value))
        data["translation_library"] = section
        settings.save_settings(data, path)
