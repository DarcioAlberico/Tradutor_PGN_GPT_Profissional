from .db_history import record_comment_history


def fetch_translation_by_id(cursor, comment_id):
    return cursor.execute("""
        SELECT original_comment, translated_comment, created_at, updated_at, verified_at
        FROM comments
        WHERE id = ?
    """, (comment_id,)).fetchone()


def update_translation_by_id(
    cursor,
    comment_id,
    translated_comment,
    mark_verified=False,
    history_action=None,
):
    existing = cursor.execute(
        """
        SELECT translated_comment, verified
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    previous_translation, previous_verified = existing
    previous_verified = 1 if previous_verified == 1 else 0
    new_verified = 1 if mark_verified else previous_verified

    if previous_translation == translated_comment and previous_verified == new_verified:
        return 0

    if history_action is None:
        translation_changed = previous_translation != translated_comment
        status_changed = previous_verified != new_verified
        if translation_changed and status_changed:
            history_action = "edit_verify"
        elif translation_changed:
            history_action = "edit"
        elif new_verified == 1:
            history_action = "verify"
        else:
            history_action = "status"

    cursor.execute("""
        UPDATE comments
        SET translated_comment = ?,
            verified = CASE WHEN ? THEN 1 ELSE verified END,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE verified_at END
        WHERE id = ?
    """, (
        translated_comment,
        1 if mark_verified else 0,
        1 if mark_verified else 0,
        comment_id,
    ))
    changed_rows = cursor.rowcount
    if changed_rows:
        record_comment_history(
            cursor,
            comment_id,
            history_action,
            previous_translation,
            translated_comment,
            previous_verified,
            new_verified,
        )
    return changed_rows


def set_translation_verified_by_id(cursor, comment_id, verified=True):
    existing = cursor.execute(
        """
        SELECT translated_comment, verified
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    translation, previous_verified = existing
    previous_verified = 1 if previous_verified == 1 else 0
    new_verified = 1 if verified else 0
    if previous_verified == new_verified:
        return 0

    cursor.execute("""
        UPDATE comments
        SET verified = ?,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id = ?
    """, (1 if verified else 0, 1 if verified else 0, comment_id))
    changed_rows = cursor.rowcount
    if changed_rows:
        record_comment_history(
            cursor,
            comment_id,
            "verify" if verified else "mark_pending",
            translation,
            translation,
            previous_verified,
            new_verified,
        )
    return changed_rows
