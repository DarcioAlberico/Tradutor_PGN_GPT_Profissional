"""Inspeção agregada de uma cópia temporária dos dados, sem escrita no acervo."""

import json
import os
import fnmatch
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .app_paths import TRANSLATIONS_FOLDER
from .glossary_catalog import GlossaryCatalog
from .settings import SETTINGS_FILENAME
from .translation_library import list_bundles


def _signature(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _database_status(path, required_tables, *, glossary=False):
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "inaccessible"
    try:
        with tempfile.TemporaryDirectory(prefix="pgn-data-check-") as tmp:
            target = Path(tmp) / "snapshot.db"
            paths = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
            before = [_signature(item) for item in paths]
            if before[1] is not None and before[1][0] > 0:
                return "inaccessible"
            for item, suffix, signature in zip(paths, ("", "-wal", "-shm"), before):
                if signature is not None:
                    if item.is_symlink():
                        return "inaccessible"
                    shutil.copyfile(item, str(target) + suffix)
            if before != [_signature(item) for item in paths]:
                return "inaccessible"
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
                    return "invalid"
                for table in required_tables:
                    if not conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone():
                        return "invalid"
                if glossary:
                    GlossaryCatalog._validate_backup(conn)
                else:
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(comments)")}
                    if not {"id", "original_comment", "translated_comment", "source_language",
                            "target_language", "verified"}.issubset(columns):
                        return "invalid"
                return "ok"
    except (sqlite3.DatabaseError, ValueError, TypeError):
        return "invalid"
    except OSError:
        return "inaccessible"


def _settings_status(path):
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "inaccessible"
    try:
        with path.open(encoding="utf-8-sig") as source:
            data = json.load(source)
        return "ok" if isinstance(data, dict) else "invalid"
    except (UnicodeError, ValueError, RecursionError):
        return "invalid"
    except OSError:
        return "inaccessible"


def verify_data(data_dir):
    """Verifica cópias temporárias e devolve apenas estados e contagens.

    A cópia de um banco em uso pode mudar entre leituras; para recuperação
    confiável, feche o programa e teste uma cópia completa do acervo.
    """
    root = Path(data_dir)
    backup_counts = {"valid": 0, "invalid": 0, "inaccessible": 0, "candidates": [],
                     "candidates_omitted": 0,
                     "by_type": {kind: {"valid": 0, "invalid": 0, "inaccessible": 0}
                                 for kind in ("translations", "glossary")}}
    backup_directory = "ok"
    warnings = [
        "Feche o programa antes de copiar os dados; um WAL com dados impede a validação segura.",
        "Cópias temporárias podem permanecer após interrupção abrupta; proteja a pasta temporária do usuário.",
        "Integridade e tabelas mínimas não garantem que um backup seja restaurável ou compatível.",
        "Chaves protegidas podem não funcionar em outra conta ou outro computador.",
    ]
    try:
        backup_dir = root / "backups"
        patterns = (
            ("traducoes-backup-*.db", ("comments",), False, "translations"),
            ("glossario-v2-*.db", ("glossary_entries", "glossary_metadata"), True, "glossary"),
        )
        with os.scandir(backup_dir) as entries:
            paths = [Path(entry.path) for entry in entries
                     if entry.is_symlink() or entry.is_file(follow_symlinks=False)]
        for pattern, tables, glossary, kind in patterns:
            for path in paths:
                if not fnmatch.fnmatch(path.name, pattern):
                    continue
                status = _database_status(path, tables, glossary=glossary)
                category = {"ok": "valid", "missing": "inaccessible"}.get(status, status)
                backup_counts[category] += 1
                backup_counts["by_type"][kind][category] += 1
                if status == "ok" and re.fullmatch(
                    r"(?:traducoes-backup|glossario-v2)-[0-9-]+\.db", path.name
                ):
                    backup_counts["candidates"].append(path.name)
        backup_counts["candidates"].sort(reverse=True)
        backup_counts["candidates_omitted"] = max(0, len(backup_counts["candidates"]) - 20)
        backup_counts["candidates"] = backup_counts["candidates"][:20]
    except FileNotFoundError:
        backup_directory = "missing"
    except OSError:
        backup_directory = "inaccessible"
        warnings.append("Não foi possível listar todos os backups.")
    count = 0
    translations_directory = "ok"
    packages = None
    try:
        translations = root / TRANSLATIONS_FOLDER
        translations.stat()
        directory_before = _signature(translations)
        def on_error(_error):
            nonlocal translations_directory
            translations_directory = "inaccessible"
            warning = "Não foi possível listar todas as traduções."
            if warning not in warnings:
                warnings.append(warning)

        for _directory, _subdirs, files in os.walk(translations, onerror=on_error):
            count += sum(name.lower().endswith(".pgn") for name in files)
        if translations_directory == "ok":
            bundles = list_bundles(translations)
            if _signature(translations) != directory_before:
                raise OSError("A pasta mudou durante a leitura")
            packages = {status: sum(bundle.status == status for bundle in bundles)
                        for status in ("ready", "legacy", "incomplete", "invalid")}
    except FileNotFoundError:
        translations_directory = "missing"
    except OSError:
        translations_directory = "inaccessible"
        warnings.append("Não foi possível listar todas as traduções.")
    return {
        "database": _database_status(root / "traducoes.db", ("comments",)),
        "glossary": _database_status(
            root / "glossario-v2.db", ("glossary_entries", "glossary_metadata"), glossary=True
        ),
        "settings": _settings_status(root / SETTINGS_FILENAME),
        "backups": backup_counts,
        "backup_directory": backup_directory,
        "translations": count,
        "translations_directory": translations_directory,
        "packages": packages,
        "warnings": warnings,
    }
