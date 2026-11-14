"""Estado local das decisões de curadoria."""

import hashlib
import json
import os
import re
from contextlib import contextmanager

from . import settings as settings_store

_SECTION = "curation_ignored_v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class CandidateIgnored(Exception):
    """Uma decisão anterior impede a criação da regra."""


def candidate_key(source_file, source_language, target_language, old, new):
    if not source_file or not target_language or not old or not new:
        raise ValueError("Obra, destino e os dois textos são obrigatórios")
    value = [os.path.normcase(os.path.abspath(os.fspath(source_file))),
             source_language or "", target_language, old, new]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read_keys(settings):
    value = settings.get(_SECTION, [])
    if not isinstance(value, list) or any(not isinstance(k, str) or not _HASH.fullmatch(k) for k in value):
        raise ValueError("A lista de decisões de curadoria está inválida")
    return set(value)


def _load_strict(path):
    return settings_store.read_settings_strict(path)


def ignored_keys(path=None):
    return _read_keys(_load_strict(path or settings_store.default_settings_path()))


@contextmanager
def available_candidate(key, *, path=None):
    """Impede uma decisão simultânea até a gravação da regra terminar."""
    if not isinstance(key, str) or not _HASH.fullmatch(key):
        raise ValueError("Candidato inválido")
    path = path or settings_store.default_settings_path()
    with settings_store._UPDATE_LOCK, settings_store._settings_process_lock(path):
        if key in _read_keys(_load_strict(path)):
            raise CandidateIgnored()
        yield


def set_ignored(key, ignored, *, path=None):
    _change_ignored([key], ignored, path=path)


def restore_ignored(keys, *, path=None):
    """Restaura apenas as decisões identificadas, em uma atualização atômica."""
    _change_ignored(keys, False, path=path)


def _change_ignored(keys, ignored, *, path=None):
    keys = list(keys)
    if not isinstance(ignored, bool) or any(not isinstance(k, str) or not _HASH.fullmatch(k) for k in keys):
        raise ValueError("Decisão de curadoria inválida")

    path = path or settings_store.default_settings_path()
    with settings_store._UPDATE_LOCK, settings_store._settings_process_lock(path):
        settings = _load_strict(path)
        stored = _read_keys(settings)
        if ignored:
            stored.update(keys)
        else:
            stored.difference_update(keys)
        settings[_SECTION] = sorted(stored)
        settings_store.save_settings(settings, path)
