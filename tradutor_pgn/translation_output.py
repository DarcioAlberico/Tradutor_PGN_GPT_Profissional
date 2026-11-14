"""Publicação transacional dos pacotes produzidos por uma tradução."""

from __future__ import annotations

import os
import hashlib
import json
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from .pgn_utils import translated_bundle_paths
from . import __version__
from .settings import SettingsLockCanceled, _settings_lock_handle


BundleStatus = Literal["published", "failed", "canceled"]
COPY_CHUNK_SIZE = 1024 * 1024
_BUNDLE_PUBLICATION_LOCK = threading.Lock()


class _PublicationCanceled(Exception):
    pass


@contextmanager
def _publication_thread_lock(is_canceled):
    """A espera por outra thread permanece cancelável."""
    while True:
        if is_canceled is not None and is_canceled():
            raise _PublicationCanceled()
        if _BUNDLE_PUBLICATION_LOCK.acquire(timeout=0.1):
            break
    try:
        if is_canceled is not None and is_canceled():
            raise _PublicationCanceled()
        yield
    finally:
        _BUNDLE_PUBLICATION_LOCK.release()


@dataclass(frozen=True)
class TranslationBundleResult:
    status: BundleStatus
    bundle_dir: str | None = None
    original_path: str | None = None
    translated_path: str | None = None
    error: Exception | None = None
    bundle_id: str | None = None


def source_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_source_snapshot(source_path: str, destination: Path) -> str:
    digest = hashlib.sha256()
    with open(source_path, "rb") as source, open(destination, "wb") as target:
        for chunk in iter(lambda: source.read(COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
            target.write(chunk)
    shutil.copystat(source_path, destination)
    return digest.hexdigest()


def publish_translation_bundle(
    input_file: str,
    target_language: str,
    output_root: str,
    generate: Callable[[str], bool],
    is_canceled: Callable[[], bool] | None = None,
    expected_source_sha256: str | None = None,
    source_language: str | None = None,
    provider: str | None = None,
    failed_comments: int | None = None,
) -> TranslationBundleResult:
    """Publica original e tradução juntos, sem expor pacote parcial."""
    staging_dir: Path | None = None

    try:
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        if failed_comments is not None and (type(failed_comments) is not int or failed_comments < 0):
            raise ValueError("contagem inválida de falhas")
        bundle_dir, original_path, translated_path = translated_bundle_paths(
            input_file, target_language, output_root
        )
        final_dir = Path(bundle_dir)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{final_dir.name}.tmp-", dir=str(root))
        )
        staged_original = staging_dir / Path(original_path).name
        staged_translation = staging_dir / Path(translated_path).name

        generated = generate(str(staged_translation))
        if not generated:
            status: BundleStatus = (
                "canceled" if is_canceled is not None and is_canceled() else "failed"
            )
            return TranslationBundleResult(status=status)
        if is_canceled is not None and is_canceled():
            return TranslationBundleResult(status="canceled")
        copied_sha256 = _copy_source_snapshot(input_file, staged_original)
        if expected_source_sha256 and copied_sha256 != expected_source_sha256:
            raise OSError("O arquivo de origem foi alterado durante a tradução")
        if is_canceled is not None and is_canceled():
            return TranslationBundleResult(status="canceled")
        translated_sha256 = source_sha256(str(staged_translation))
        bundle_id = str(uuid4())
        manifest = {
            "schema_version": 1,
            "bundle_id": bundle_id,
            "application_version": __version__,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_language": source_language or None,
            "target_language": target_language,
            "execution_provider": provider or None,
            "failed_comments": failed_comments,
            "files": {
                "original": {"path": staged_original.name, "sha256": copied_sha256},
                "translation": {"path": staged_translation.name, "sha256": translated_sha256},
            },
        }
        with (staging_dir / "manifesto.json").open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if is_canceled is not None and is_canceled():
            return TranslationBundleResult(status="canceled")
        # A geração pode durar horas: só a escolha final do nome e a publicação
        # precisam ser serializadas entre instâncias do programa.
        with _publication_thread_lock(is_canceled), _settings_lock_handle(str(root / ".publicacao"), should_cancel=is_canceled):
            final_name, final_original, final_translation = translated_bundle_paths(
                input_file, target_language, output_root
            )
            final_dir = Path(final_name)
            target_original = staging_dir / Path(final_original).name
            target_translation = staging_dir / Path(final_translation).name
            if (target_original, target_translation) != (staged_original, staged_translation):
                # Os novos nomes podem cruzar com os antigos. Uma subpasta
                # temporária evita sobrescrever qualquer um dos dois arquivos.
                with tempfile.TemporaryDirectory(prefix=".renomear-", dir=str(staging_dir)) as temp:
                    saved_original, saved_translation = Path(temp) / "original", Path(temp) / "translation"
                    os.replace(staged_original, saved_original)
                    os.replace(staged_translation, saved_translation)
                    os.replace(saved_original, target_original)
                    os.replace(saved_translation, target_translation)
                staged_original, staged_translation = target_original, target_translation
                manifest["files"]["original"]["path"] = staged_original.name
                manifest["files"]["translation"]["path"] = staged_translation.name
                with (staging_dir / "manifesto.json").open("w", encoding="utf-8", newline="\n") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            if is_canceled is not None and is_canceled():
                return TranslationBundleResult(status="canceled")
            os.replace(staging_dir, final_dir)
        return TranslationBundleResult(
            status="published",
            bundle_dir=str(final_dir),
            original_path=str(final_dir / staged_original.name),
            translated_path=str(final_dir / staged_translation.name),
            bundle_id=bundle_id,
        )
    except (_PublicationCanceled, SettingsLockCanceled):
        return TranslationBundleResult(status="canceled")
    except Exception as exc:
        return TranslationBundleResult(status="failed", error=exc)
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
