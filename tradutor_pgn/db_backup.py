import sqlite3
from datetime import datetime
from pathlib import Path

from .database import initialize_database


def _unique_backup_path(backup_dir, stem, timestamp):
    base_name = f"{stem}-backup-{timestamp}.db"
    backup_path = backup_dir / base_name
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{stem}-backup-{timestamp}-{suffix}.db"
        suffix += 1
    return backup_path


def create_database_backup(db_path, backup_dir=None, timestamp=None):
    source_path = Path(db_path)
    if backup_dir is None:
        backup_dir = source_path.parent / "backups"
    else:
        backup_dir = Path(backup_dir)

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = _unique_backup_path(backup_dir, source_path.stem, timestamp)

    source_conn = initialize_database(str(source_path))
    target_conn = sqlite3.connect(str(backup_path))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    return str(backup_path)


def validate_restore_source(backup_path):
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup nao encontrado: {backup_path}")

    conn = sqlite3.connect(str(backup_path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Backup invalido: integrity_check retornou {integrity}")

        has_comments = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'comments'
            """
        ).fetchone()
        if has_comments is None:
            raise ValueError("Backup invalido: tabela comments nao encontrada")
    finally:
        conn.close()


def restore_database_from_backup(db_path, backup_path, safety_backup_dir=None):
    target_path = Path(db_path)
    backup_path = Path(backup_path)
    if target_path.resolve() == backup_path.resolve():
        raise ValueError("O backup selecionado e o banco atual sao o mesmo arquivo")

    validate_restore_source(backup_path)
    safety_backup_path = create_database_backup(
        target_path,
        backup_dir=safety_backup_dir,
    )

    source_conn = sqlite3.connect(str(backup_path))
    target_conn = sqlite3.connect(str(target_path))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    migrated_conn = initialize_database(str(target_path))
    try:
        integrity = migrated_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Banco restaurado invalido: integrity_check retornou {integrity}")
    finally:
        migrated_conn.close()

    return {
        "restored_path": str(target_path),
        "safety_backup_path": safety_backup_path,
    }
