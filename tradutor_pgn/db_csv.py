import csv

from .database import (
    initialize_database,
    save_translation,
    set_translation_verified_by_id,
)
from .db_backup import create_database_backup


def _parse_verified(value):
    if value is None:
        return False
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "sim",
        "ok",
        "verified",
        "verificada",
        "verificado",
    }


def _fetch_comment_id(cursor, original_comment, target_language):
    row = cursor.execute(
        """
        SELECT id
        FROM comments
        WHERE original_comment = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, target_language),
    ).fetchone()
    return row[0] if row else None


def _read_translation_csv_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        required = {"original_comment", "translated_comment", "target_language"}
        missing = sorted(required - fieldnames)
        if missing:
            raise ValueError("CSV sem colunas obrigatorias: " + ", ".join(missing))
        return list(reader)


def _normalize_import_row(row):
    return {
        "original_comment": (row.get("original_comment") or "").strip(),
        "translated_comment": (row.get("translated_comment") or "").strip(),
        "target_language": (row.get("target_language") or "").strip(),
        "verified": _parse_verified(row.get("verified")),
    }


def _empty_import_stats(backup_path=None):
    return {
        "total_rows": 0,
        "inserted": 0,
        "filled_empty": 0,
        "unchanged": 0,
        "skipped": 0,
        "verified_applied": 0,
        "backup_path": backup_path,
    }


def _existing_translation(cursor, original_comment, target_language):
    return cursor.execute(
        """
        SELECT translated_comment
        FROM comments
        WHERE original_comment = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, target_language),
    ).fetchone()


def analyze_translations_csv_import(db_path, csv_path):
    csv_rows = _read_translation_csv_rows(csv_path)
    stats = _empty_import_stats()

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            row = _normalize_import_row(raw_row)
            original = row["original_comment"]
            translated = row["translated_comment"]
            target_language = row["target_language"]

            if not original or not translated or not target_language:
                stats["skipped"] += 1
                continue

            existing = _existing_translation(cursor, original, target_language)
            if existing is None:
                stats["inserted"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
                continue

            existing_translation = existing[0]
            if existing_translation is None or existing_translation == "":
                stats["filled_empty"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
            else:
                stats["unchanged"] += 1
    finally:
        conn.close()

    return stats


def import_translations_from_csv(
    db_path,
    csv_path,
    create_backup=True,
    backup_dir=None,
):
    csv_rows = _read_translation_csv_rows(csv_path)

    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    stats = _empty_import_stats(backup_path)

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            row = _normalize_import_row(raw_row)
            original = row["original_comment"]
            translated = row["translated_comment"]
            target_language = row["target_language"]

            if not original or not translated or not target_language:
                stats["skipped"] += 1
                continue

            save_status = save_translation(
                cursor,
                original,
                translated,
                target_language,
            )
            if save_status == "inserted":
                stats["inserted"] += 1
            elif save_status == "filled_empty":
                stats["filled_empty"] += 1
            else:
                stats["unchanged"] += 1

            if save_status in {"inserted", "filled_empty"} and row["verified"]:
                comment_id = _fetch_comment_id(cursor, original, target_language)
                if comment_id is not None:
                    stats["verified_applied"] += set_translation_verified_by_id(
                        cursor,
                        comment_id,
                        True,
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return stats
