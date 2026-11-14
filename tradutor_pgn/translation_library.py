"""Leitura local e não destrutiva dos pacotes de tradução."""
from __future__ import annotations

import json
import hashlib
import re
import unicodedata
import os
import stat
import time
import math
from bisect import insort
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

MAX_MANIFEST_BYTES = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")
_STAGING_NAME = re.compile(r"^\..+\.tmp-.+$")


@dataclass(frozen=True)
class StagingEntry:
    name: str
    age_seconds: float


@dataclass(frozen=True)
class StagingInspection:
    total: int
    entries: tuple[StagingEntry, ...]
    min_age_seconds: float = 86400
    future_count: int = 0


class StagingInspectionCanceled(Exception):
    """A inspeção foi cancelada; nenhum resultado parcial é apresentado."""


def inspect_staging_directories(root, *, now=None, min_age_seconds=86400, max_entries=20, should_cancel=None):
    """Lista temporários antigos sem abri-los; idade não comprova abandono."""
    if (not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 0
            or not isinstance(min_age_seconds, (int, float)) or isinstance(min_age_seconds, bool)
            or not math.isfinite(min_age_seconds) or min_age_seconds < 0):
        raise ValueError("Limites de inspeção inválidos")
    if should_cancel is not None and should_cancel():
        raise StagingInspectionCanceled()
    now = time.time() if now is None else now
    entries = []
    total = 0
    future_count = 0
    try:
        iterator = os.scandir(root)
    except FileNotFoundError:
        return StagingInspection(0, (), min_age_seconds)
    with iterator as entries_iterator:
        for item in entries_iterator:
            if should_cancel is not None and should_cancel():
                raise StagingInspectionCanceled()
            if not _STAGING_NAME.fullmatch(item.name):
                continue
            info = item.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                continue
            age = now - info.st_mtime
            if age < 0:
                future_count += 1
                continue
            if age >= min_age_seconds and age >= 0:
                total += 1
                if max_entries:
                    key = (-age, item.name.casefold(), item.name)
                    if len(entries) < max_entries or key < entries[-1][0]:
                        insort(entries, (key, StagingEntry(item.name, age)), key=lambda pair: pair[0])
                        if len(entries) > max_entries:
                            entries.pop()
    return StagingInspection(total, tuple(entry for _, entry in entries), min_age_seconds, future_count)


def format_staging_inspection(result):
    age = result.min_age_seconds
    threshold = f"{int(age // 3600)} hora(s)" if age >= 3600 and age % 3600 == 0 else f"{age:g} segundo(s)"
    lines = [f"{result.total} pasta(s) temporária(s) com pelo menos {threshold}."]
    for entry in result.entries:
        name = entry.name.replace("\r", " ").replace("\n", " ")
        if len(name) > 100:
            name = name[:99] + "…"
        lines.append(f"• {name} — {int(entry.age_seconds // 3600)} h")
    remaining = result.total - len(result.entries)
    if remaining:
        lines.append(f"Outras {remaining} pasta(s) não exibidas.")
    if result.future_count:
        lines.append(f"{result.future_count} pasta(s) com data futura não puderam ser classificadas por idade.")
    lines.append("A idade não comprova abandono: uma tradução pode estar ativa. Nada foi removido.")
    return "\n".join(lines)


@dataclass(frozen=True)
class LibraryBundle:
    directory: Path
    status: str
    original: Path | None = None
    translated: Path | None = None
    source_language: str | None = None
    target_language: str | None = None
    provider: str | None = None
    created_at: str | None = None
    failed_comments: int | None = None


@dataclass(frozen=True)
class IntegrityResult:
    status: str
    original_ok: bool | None = None
    translation_ok: bool | None = None


class IntegrityVerificationCanceled(Exception):
    """A verificação foi interrompida sem produzir resultado parcial."""


def _check_integrity_canceled(should_cancel):
    if should_cancel is not None and should_cancel():
        raise IntegrityVerificationCanceled()


def _hash_file(path, should_cancel=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            _check_integrity_canceled(should_cancel)
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _signature(path):
    if path.is_symlink():
        raise OSError("link simbólico")
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_manifest_bytes(path):
    if path.is_symlink():
        raise OSError("link simbólico")
    with path.open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("manifesto excede limite")
    return data


def verify_bundle(directory, *, should_cancel=None):
    """Compara hashes sem alterar arquivos; não autentica sua procedência."""
    directory = Path(directory)
    try:
        _check_integrity_canceled(should_cancel)
        if directory.is_symlink() or not directory.is_dir():
            return IntegrityResult("unavailable")
        manifest_path = directory / "manifesto.json"
        manifest_before = _read_manifest_bytes(manifest_path)
        bundle = _manifest_bundle(directory)
        if bundle.status != "ready":
            return IntegrityResult("unavailable")
        data = json.loads(manifest_before.decode("utf-8"))
        original, translation = bundle.original, bundle.translated
        if (data["files"]["original"]["path"] != original.name or
                data["files"]["translation"]["path"] != translation.name):
            return IntegrityResult("changed")
        before = (_signature(original), _signature(translation))
        if should_cancel is None:
            original_hash = _hash_file(original)
            translation_hash = _hash_file(translation)
        else:
            original_hash = _hash_file(original, should_cancel)
            translation_hash = _hash_file(translation, should_cancel)
            _check_integrity_canceled(should_cancel)
        if (manifest_before != _read_manifest_bytes(manifest_path) or
                before != (_signature(original), _signature(translation))):
            return IntegrityResult("changed")
        original_ok = original_hash == data["files"]["original"]["sha256"]
        translation_ok = translation_hash == data["files"]["translation"]["sha256"]
        return IntegrityResult("verified" if original_ok and translation_ok else "mismatch",
                               original_ok, translation_ok)
    except IntegrityVerificationCanceled:
        return IntegrityResult("canceled")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return IntegrityResult("unavailable")


def _valid_name(value):
    if not isinstance(value, str) or not value or value in (".", ".."):
        return False
    windows = PureWindowsPath(value)
    return ("/" not in value and "\\" not in value and ":" not in value and not windows.drive
            and not windows.root and Path(value).suffix.lower() == ".pgn")


def _manifest_bundle(directory):
    try:
        manifest_path = directory / "manifesto.json"
        if manifest_path.is_symlink():
            raise ValueError("symlink")
        with manifest_path.open("rb") as stream:
            payload = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError("oversized")
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("schema")
        files = data["files"]
        names = []
        for kind in ("original", "translation"):
            entry = files[kind]
            name, digest = entry["path"], entry["sha256"]
            if not _valid_name(name) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
                raise ValueError("file")
            names.append(name)
        if names[0].casefold() == names[1].casefold():
            raise ValueError("same file")
        paths = [directory / name for name in names]
        if any(path.is_symlink() or not path.is_file() for path in paths):
            return LibraryBundle(directory, "incomplete")
        source, target, provider, created = (data.get(key) for key in
                                            ("source_language", "target_language", "execution_provider", "created_at_utc"))
        if any(value is not None and not isinstance(value, str) for value in (source, target, provider, created)):
            raise ValueError("metadata")
        if not target or not created:
            raise ValueError("metadata")
        failed_comments = data.get("failed_comments")
        if failed_comments is not None and (type(failed_comments) is not int or failed_comments < 0):
            raise ValueError("failed comments")
        parsed = datetime.fromisoformat(created)
        if parsed.tzinfo is None:
            raise ValueError("timezone")
        return LibraryBundle(directory, "ready", paths[0], paths[1], source, target, provider, created, failed_comments)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return LibraryBundle(directory, "invalid")


def _legacy_bundle(directory):
    try:
        files = [path for path in directory.iterdir()
                 if path.suffix.lower() == ".pgn" and not path.is_symlink() and path.is_file()]
        translated = [path for path in files if path.stem.casefold() == directory.name.casefold()]
        if len(files) == 2 and len(translated) == 1:
            original = next(path for path in files if path != translated[0])
            return LibraryBundle(directory, "legacy", original, translated[0])
    except OSError:
        pass
    return LibraryBundle(directory, "incomplete")


def list_bundles(root):
    """Lista pacotes em um nível, sem ler o conteúdo dos PGNs nem modificá-los."""
    root = Path(root)
    try:
        directories = [path for path in root.iterdir()
                       if not path.is_symlink() and path.is_dir()
                       and not (path.name.startswith(".") and ".tmp-" in path.name)]
    except FileNotFoundError:
        return []
    result = []
    for directory in sorted(directories, key=lambda p: (p.name.casefold(), p.name)):
        manifest = directory / "manifesto.json"
        result.append(_manifest_bundle(directory) if manifest.exists() or manifest.is_symlink() else _legacy_bundle(directory))
    return result


def search_bundles(bundles, query="", status=None, *, source=None, target=None, provider=None, failures=None):
    """Filtra pelo nome da pasta, idioma ou motor, preservando a ordem recebida."""
    if failures not in (None, "with", "without", "unknown"):
        raise ValueError("filtro de falhas desconhecido")
    def searchable(value):
        return "".join(c for c in unicodedata.normalize("NFD", value.casefold())
                       if unicodedata.category(c) != "Mn")

    terms = searchable(query).split()
    return [bundle for bundle in bundles
            if (status is None or bundle.status == status)
            and (source is None or (bundle.source_language or "") == source)
            and (target is None or (bundle.target_language or "") == target)
            and (provider is None or (bundle.provider or "") == provider)
            and (failures is None or
                 (failures == "unknown" and bundle.failed_comments is None) or
                 (failures == "with" and bundle.failed_comments is not None and bundle.failed_comments > 0) or
                 (failures == "without" and bundle.failed_comments == 0))
            and all(any(term in searchable(value) for value in
                        (bundle.directory.name, bundle.source_language or "",
                         bundle.target_language or "", bundle.provider or ""))
                    for term in terms)]


def sort_bundles(bundles, order="name"):
    """Ordena por nome ou instante; datas ausentes permanecem no fim."""
    if order not in ("name", "recent", "oldest", "failures_asc", "failures_desc"):
        raise ValueError("ordenação desconhecida")
    items = sorted(bundles, key=lambda item: (item.directory.name.casefold(), item.directory.name))
    if order == "name":
        return items
    if order in ("failures_asc", "failures_desc"):
        return sorted(items, key=lambda item: (
            item.failed_comments is None,
            -(item.failed_comments or 0) if order == "failures_desc" else (item.failed_comments or 0),
        ))

    def sort_key(item):
        try:
            date = datetime.fromisoformat(item.created_at)
            if date.tzinfo is None:
                raise ValueError("data sem fuso")
            seconds = (date.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
            return False, -seconds if order == "recent" else seconds
        except (ValueError, TypeError, OverflowError):
            return True, 0

    return sorted(items, key=sort_key)


def review_percentage(verified, total):
    """Arredonda para baixo para não indicar 100% antes da conclusão."""
    return verified * 100 // total if total else 0


def bundle_summary(bundle):
    """Resumo local sem caminhos absolutos, conteúdo ou hashes."""
    statuses = {"ready": "Com manifesto", "legacy": "Sem manifesto",
                "incomplete": "Incompleto", "invalid": "Manifesto inválido"}
    failure_text = str(bundle.failed_comments) if bundle.failed_comments is not None else "Não informado"
    return "\n".join((
        f"Pacote: {bundle.directory.name}",
        f"Situação: {statuses.get(bundle.status, 'Desconhecida')}",
        f"Origem: {bundle.source_language or 'Não informado'}",
        f"Destino: {bundle.target_language or 'Não informado'}",
        f"Motor da execução: {bundle.provider or 'Não informado'}",
        f"Data: {bundle.created_at or 'Não informado'}",
        f"Falhas na geração: {failure_text}",
    ))
