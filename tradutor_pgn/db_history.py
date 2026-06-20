def record_comment_history(
    cursor,
    comment_id,
    action,
    previous_translation,
    new_translation,
    previous_verified,
    new_verified,
):
    cursor.execute(
        """
        INSERT INTO comment_history (
            comment_id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            comment_id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
        ),
    )
    return cursor.lastrowid


def fetch_comment_history(cursor, comment_id, limit=50):
    return cursor.execute(
        """
        SELECT
            id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
            created_at
        FROM comment_history
        WHERE comment_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (comment_id, limit),
    ).fetchall()
