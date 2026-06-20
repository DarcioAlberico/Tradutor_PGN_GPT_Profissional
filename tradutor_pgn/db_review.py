def _review_where(target_language, only_unverified=False, search_text="", status_filter=None):
    clauses = ["target_language = ?"]
    params = [target_language]

    if status_filter is None:
        status_filter = "pending" if only_unverified else "all"

    if status_filter == "pending":
        clauses.append("verified <> 1")
    elif status_filter == "verified":
        clauses.append("verified = 1")

    search_text = (search_text or "").strip()
    if search_text:
        clauses.append("(original_comment LIKE ? OR translated_comment LIKE ?)")
        pattern = f"%{search_text}%"
        params.extend([pattern, pattern])

    return " AND ".join(clauses), params


def fetch_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
    )
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        WHERE {where_sql}
        ORDER BY id
    """, params).fetchall()


def count_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
    )
    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql}
    """, params).fetchone()[0]


def get_review_status_counts(cursor, target_language, search_text=""):
    where_sql, params = _review_where(
        target_language,
        search_text=search_text,
        status_filter="all",
    )
    total, pending, verified = cursor.execute(f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0)
        FROM comments
        WHERE {where_sql}
    """, params).fetchone()
    return {
        "total": total,
        "pending": pending,
        "verified": verified,
    }


def fetch_review_rows_page(
    cursor,
    target_language,
    only_unverified=False,
    limit=100,
    offset=0,
    search_text="",
    status_filter=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
    )
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        WHERE {where_sql}
        ORDER BY id
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()


def get_review_row_offset(
    cursor,
    target_language,
    comment_id,
    only_unverified=False,
    search_text="",
    status_filter=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
    )
    row = cursor.execute(f"""
        SELECT id
        FROM comments
        WHERE {where_sql} AND id = ?
    """, params + [comment_id]).fetchone()

    if row is None:
        return None

    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql} AND id < ?
    """, params + [comment_id]).fetchone()[0]
