from .db_history import record_comment_history


def load_translation_cache(cursor, target_language):
    cursor.execute(
        """
        SELECT original_comment, translated_comment
        FROM comments
        WHERE target_language = ?
          AND translated_comment IS NOT NULL
          AND translated_comment <> ''
        ORDER BY id
        """,
        (target_language,)
    )
    return {orig: trans for orig, trans in cursor.fetchall()}


def save_translation(cursor, original_comment, translated_comment, target_language):
    """
    Salva uma tradução no cache.

    Retorna:
    - inserted: linha nova criada.
    - filled_empty: linha existente vazia/nula preenchida.
    - unchanged: já havia tradução preenchida e nada foi sobrescrito.
    """
    existing_row = cursor.execute(
        """
        SELECT id, translated_comment
        FROM comments
        WHERE original_comment = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, target_language)
    ).fetchone()

    if existing_row is None:
        cursor.execute(
            """
            INSERT INTO comments (
                original_comment,
                translated_comment,
                target_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (original_comment, translated_comment, target_language)
        )
        return "inserted" if cursor.rowcount else "unchanged"

    row_id, existing_translation = existing_row
    if existing_translation is None or existing_translation == "":
        cursor.execute(
            """
            UPDATE comments
            SET translated_comment = ?,
                verified = 0,
                updated_at = CURRENT_TIMESTAMP,
                verified_at = NULL
            WHERE id = ?
            """,
            (translated_comment, row_id)
        )
        if cursor.rowcount:
            record_comment_history(
                cursor,
                row_id,
                "fill_empty",
                existing_translation,
                translated_comment,
                0,
                0,
            )
        return "filled_empty" if cursor.rowcount else "unchanged"

    return "unchanged"
