"""Recriação local de um pacote usando as traduções já salvas."""
from contextlib import closing
from dataclasses import dataclass
import json
import hashlib
import io
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .database import load_translation_cache
from .pgn_utils import detect_encoding_from_bytes, extract_comments_from_content, generate_translated_pgn
from .translation_library import _legacy_bundle, _manifest_bundle, _read_manifest_bytes, verify_bundle
from .translation_library_links import ReviewLink, register_link, resolve_bundle_review, resolve_link
from .translation_output import _PublicationCanceled, publish_translation_bundle, source_sha256


def _read_original(path, should_cancel):
    digest = hashlib.sha256()
    with path.open("rb") as source, io.BytesIO() as buffer:
        while True:
            if should_cancel():
                raise _PublicationCanceled()
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            buffer.write(chunk)
        return buffer.getvalue(), digest.hexdigest()


@dataclass(frozen=True)
class RegenerationResult:
    status: str
    missing: int = 0
    bundle_dir: str | None = None
    translated_path: str | None = None
    link_saved: bool = False
    link: ReviewLink | None = None
    unsupported: int = 0
    missing_examples: tuple[str, ...] = ()


def regenerate_bundle(database_path, directory, output_root, *, should_cancel=None, use_bom=False, wrap_columns=0,
                      confirmed_link=None):
    """Usa uma fotografia do banco e publica nova versão sem chamadas de rede."""
    canceled = should_cancel or (lambda: False)
    if canceled():
        return RegenerationResult("canceled")
    try:
        resolution = resolve_bundle_review(database_path, directory, should_cancel=canceled)
        if resolution.status == "canceled":
            return RegenerationResult("canceled")
        if resolution.status == "compatible" and resolution.link is not None and confirmed_link is None:
            return RegenerationResult("compatible", link=resolution.link)
        if (resolution.link is None or resolution.status not in ("ready", "compatible") or
                (resolution.status == "compatible" and resolution.link != confirmed_link)):
            return RegenerationResult("unavailable")
        directory = Path(directory)
        manifest_path = directory / "manifesto.json"
        has_manifest = manifest_path.exists() or manifest_path.is_symlink()
        manifest_before = _read_manifest_bytes(manifest_path) if has_manifest else None
        if has_manifest:
            integrity = verify_bundle(directory, should_cancel=canceled)
            if integrity.status == "canceled":
                return RegenerationResult("canceled")
            if integrity.status != "verified" or _read_manifest_bytes(manifest_path) != manifest_before:
                return RegenerationResult("unavailable")
            bundle = _manifest_bundle(directory)
            manifest = json.loads(manifest_before.decode("utf-8"))
            source_hash = manifest["files"]["original"]["sha256"]
        else:
            bundle = _legacy_bundle(directory)
            manifest = None
            source_hash = None
        if bundle.status not in ("ready", "legacy") or bundle.original is None:
            return RegenerationResult("unavailable")
        link = resolution.link
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            conn.execute("BEGIN")
            if resolution.status == "ready" and resolve_link(conn, manifest["bundle_id"]) != link:
                return RegenerationResult("unavailable")
            raw, actual_hash = _read_original(bundle.original, canceled)
            if source_hash is not None and actual_hash != source_hash:
                return RegenerationResult("unavailable")
            if resolution.status == "compatible":
                if (Path(link.source_file).name.casefold() != bundle.original.name.casefold() or
                        source_sha256(link.source_file, canceled) != actual_hash):
                    return RegenerationResult("unavailable")
                occurrence = conn.execute(
                    "SELECT 1 FROM occurrences o JOIN comments c ON c.id=o.comment_id "
                    "WHERE o.source_file=? AND c.source_language=? AND c.target_language=? LIMIT 1",
                    (link.source_file, link.source_language, link.target_language)).fetchone()
                if occurrence is None:
                    return RegenerationResult("unavailable")
            source_hash = actual_hash
            encoding = detect_encoding_from_bytes(raw)
            content = raw.decode(encoding, errors="replace")
            del raw
            info = extract_comments_from_content(content)
            if info["semicolon_comments"]:
                return RegenerationResult("unsupported", unsupported=info["semicolon_comments"])
            comments = list(dict.fromkeys(info["comments"]))
            cache = load_translation_cache(conn.cursor(), link.target_language, comments,
                                           source_language=link.source_language)
            cache = {key: value for key, value in cache.items() if isinstance(value, str) and value.strip()}
        missing = 0
        examples = []
        for comment in comments:
            if comment not in cache:
                missing += 1
                if len(examples) < 5:
                    examples.append(comment if len(comment) <= 140 else comment[:139] + "…")
        if canceled():
            return RegenerationResult("canceled")
        if missing:
            return RegenerationResult("missing", missing=missing, missing_examples=tuple(examples))
        if manifest_before is not None and _read_manifest_bytes(manifest_path) != manifest_before:
            return RegenerationResult("unavailable")
        if manifest_before is None and (manifest_path.exists() or _legacy_bundle(directory) != bundle):
            return RegenerationResult("unavailable")
        flag = SimpleNamespace(is_set=canceled)
        def generate(path):
            return generate_translated_pgn(str(bundle.original), path, cache, info["positions"],
                                           use_bom=use_bom, wrap_columns=wrap_columns,
                                           content=content, encoding=encoding, cancel_flag=flag)
        result = publish_translation_bundle(str(bundle.original), link.target_language, str(output_root), generate,
                                            is_canceled=canceled, expected_source_sha256=source_hash,
                                            source_language=link.source_language)
        if result.status != "published":
            return RegenerationResult(result.status, missing=missing)
        link_saved = False
        try:
            writable = Path(database_path).resolve().as_uri() + "?mode=rw"
            with closing(sqlite3.connect(writable, uri=True, timeout=2)) as conn:
                register_link(conn, result.bundle_id, link.source_file, link.source_language, link.target_language)
                conn.commit()
                link_saved = True
        except (sqlite3.Error, OSError, ValueError):
            pass
        return RegenerationResult("published", missing, result.bundle_dir, result.translated_path, link_saved)
    except _PublicationCanceled:
        return RegenerationResult("canceled")
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return RegenerationResult("unavailable")
