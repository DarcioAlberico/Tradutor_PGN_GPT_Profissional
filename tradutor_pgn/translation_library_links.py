"""Vínculos locais entre pacotes e ocorrências do banco de traduções."""
from dataclasses import dataclass
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import UUID


@dataclass(frozen=True)
class ReviewLink:
    source_file: str
    source_language: str
    target_language: str


@dataclass(frozen=True)
class ReviewResolution:
    status: str
    link: ReviewLink | None = None


@dataclass(frozen=True)
class ReviewProgress:
    status: str
    total: int | None = None
    verified: int | None = None
    pending: int | None = None


def bundle_review_progress(database_path, directory):
    """Conta comentários distintos do vínculo, sem gravar dados de revisão."""
    from .database import get_review_status_counts
    from .translation_library import _read_manifest_bytes

    resolution = resolve_bundle_review(database_path, directory)
    if resolution.status != "ready" or resolution.link is None:
        return ReviewProgress(resolution.status)
    link = resolution.link
    try:
        manifest_path = Path(directory) / "manifesto.json"
        manifest_before = _read_manifest_bytes(manifest_path)
        bundle_id = json.loads(manifest_before.decode("utf-8"))["bundle_id"]
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            if resolve_link(connection, bundle_id) != link:
                return ReviewProgress("unavailable")
            counts = get_review_status_counts(
                connection.cursor(), link.target_language,
                source_language=link.source_language, source_file=link.source_file,
            )
        if manifest_before != _read_manifest_bytes(manifest_path):
            return ReviewProgress("unavailable")
        if not counts["total"]:
            return ReviewProgress("no_occurrences")
        return ReviewProgress("ready", counts["total"], counts["verified"], counts["pending"])
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return ReviewProgress("unavailable")


def _validated_id(value):
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("identificador inválido") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("identificador inválido")
    return value


def register_link(connection, bundle_id, source_file, source_language, target_language):
    """Registra vínculo imutável na transação do chamador."""
    bundle_id = _validated_id(bundle_id)
    connection.execute("CREATE TABLE IF NOT EXISTS library_bundle_links ("
                       "bundle_id TEXT PRIMARY KEY, source_file TEXT NOT NULL, "
                       "source_language TEXT NOT NULL, target_language TEXT NOT NULL)")
    connection.execute("INSERT INTO library_bundle_links "
                       "(bundle_id, source_file, source_language, target_language) VALUES (?, ?, ?, ?)",
                       (bundle_id, source_file, source_language or "", target_language))


def resolve_link(connection, bundle_id):
    """Consulta sem criar tabelas; bancos anteriores não têm vínculo."""
    bundle_id = _validated_id(bundle_id)
    table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_bundle_links'").fetchone()
    if table is None:
        return None
    row = connection.execute("SELECT source_file, source_language, target_language "
                             "FROM library_bundle_links WHERE bundle_id=?", (bundle_id,)).fetchone()
    return ReviewLink(*row) if row else None


def resolve_bundle_review(database_path, directory):
    """Localiza origem por identificador, integridade e ocorrências do par."""
    from .translation_library import _legacy_bundle, _manifest_bundle, _read_manifest_bytes, verify_bundle
    from .app_config import LANGUAGE_NAMES

    directory = Path(directory)
    try:
        if directory.is_symlink() or not directory.is_dir():
            return ReviewResolution("unavailable")
        manifest_path = directory / "manifesto.json"
        if not manifest_path.exists() and not manifest_path.is_symlink():
            bundle = _legacy_bundle(directory)
            return _find_compatible_review(database_path, bundle) if bundle.status == "legacy" else ReviewResolution("unlinked")
        if verify_bundle(directory).status != "verified":
            return ReviewResolution("integrity")
        bundle = _manifest_bundle(directory)
        manifest = json.loads(_read_manifest_bytes(manifest_path).decode("utf-8"))
        bundle_id = manifest.get("bundle_id")
        if not bundle_id:
            return _find_compatible_review(database_path, bundle)
        _validated_id(bundle_id)
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            link = resolve_link(conn, bundle_id)
            if link is None:
                return _find_compatible_review(database_path, bundle)
            if (bundle.status != "ready" or link.target_language != bundle.target_language or
                    link.source_language != (bundle.source_language or "") or
                    link.target_language not in LANGUAGE_NAMES or
                    (link.source_language and link.source_language not in LANGUAGE_NAMES)):
                return ReviewResolution("unlinked")
            found = conn.execute(
                "SELECT 1 FROM occurrences o JOIN comments c ON c.id=o.comment_id "
                "WHERE o.source_file=? AND c.source_language=? AND c.target_language=? LIMIT 1",
                (link.source_file, link.source_language, link.target_language),
            ).fetchone()
        return ReviewResolution("ready", link) if found else ReviewResolution("no_occurrences")
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return ReviewResolution("unavailable")


def _find_compatible_review(database_path, bundle):
    """Compara originais, sem gravar nem alegar que são a mesma execução."""
    from .translation_library import _hash_file, _read_manifest_bytes, _signature, verify_bundle
    from .app_config import LANGUAGE_NAMES

    try:
        original = bundle.original
        if original is None or bundle.directory.is_symlink():
            return ReviewResolution("unavailable")
        manifest_path = bundle.directory / "manifesto.json"
        manifest_before = _read_manifest_bytes(manifest_path) if bundle.status == "ready" else None
        if manifest_before is not None and verify_bundle(bundle.directory).status != "verified":
            return ReviewResolution("integrity")
        original_before = _signature(original)
        original_hash = _hash_file(original)
        if _signature(original) != original_before:
            return ReviewResolution("unavailable")
        if manifest_before is not None:
            manifest = json.loads(manifest_before.decode("utf-8"))
            if original_hash != manifest["files"]["original"]["sha256"]:
                return ReviewResolution("integrity")
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT o.source_file, c.source_language, c.target_language "
                "FROM occurrences o JOIN comments c ON c.id=o.comment_id"
            )
            candidates = []
            for filename, source, target in rows:
                if not isinstance(filename, str) or Path(filename).name.casefold() != original.name.casefold():
                    continue
                if target not in LANGUAGE_NAMES or (source and source not in LANGUAGE_NAMES):
                    continue
                if bundle.status == "ready" and (target != bundle.target_language or source != (bundle.source_language or "")):
                    continue
                candidates.append(ReviewLink(filename, source or "", target))
                if len(candidates) > 100:
                    return ReviewResolution("ambiguous")
        signatures = {}
        matching = []
        for candidate in candidates:
            path = Path(candidate.source_file)
            if path not in signatures:
                signature = _signature(path)
                digest = _hash_file(path)
                if _signature(path) != signature:
                    return ReviewResolution("unavailable")
                signatures[path] = (signature, digest)
            if signatures[path][1] == original_hash:
                matching.append(candidate)
        if (_signature(original) != original_before or
                any(_signature(path) != signature for path, (signature, _) in signatures.items()) or
                (manifest_before is not None and _read_manifest_bytes(manifest_path) != manifest_before)):
            return ReviewResolution("unavailable")
        if len(matching) > 1:
            return ReviewResolution("ambiguous")
        return ReviewResolution("compatible", matching[0]) if matching else ReviewResolution("unlinked")
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return ReviewResolution("unavailable")
