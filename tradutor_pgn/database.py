import sqlite3


def open_database(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_database(db_path):
    conn = open_database(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_comment TEXT,
        translated_comment TEXT,
        target_language TEXT,
        verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        verified_at TEXT,
        UNIQUE(original_comment, target_language)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        previous_translation TEXT,
        new_translation TEXT,
        previous_verified INTEGER,
        new_verified INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(comment_id) REFERENCES comments(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("PRAGMA table_info(comments)")
    cols = [row[1] for row in cursor.fetchall()]

    if "verified" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN verified INTEGER DEFAULT 0")
        conn.commit()
    if "created_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN created_at TEXT")
        cursor.execute("UPDATE comments SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        conn.commit()
    if "updated_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN updated_at TEXT")
        cursor.execute("UPDATE comments SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        conn.commit()
    if "verified_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN verified_at TEXT")
        cursor.execute("""
            UPDATE comments
            SET verified_at = CASE WHEN verified = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE verified_at IS NULL
        """)
        conn.commit()

    cursor.execute("""
        UPDATE comments
        SET verified = CASE WHEN verified = 1 THEN 1 ELSE 0 END
        WHERE verified IS NULL OR verified NOT IN (0, 1)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_target_language
        ON comments(target_language)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_review_queue
        ON comments(target_language, verified, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comment_history_comment
        ON comment_history(comment_id, id)
    """)

    conn.commit()
    return conn


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

def get_database_stats(cursor):
    total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]

    per_language = cursor.execute("""
        SELECT
            target_language,
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0)
        FROM comments
        GROUP BY target_language
    """).fetchall()

    verified_total, pending_total = cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0)
        FROM comments
    """).fetchone()

    return {
        "total": total,
        "verified_total": verified_total,
        "pending_total": pending_total,
        "per_language": per_language,
    }


def fetch_export_rows(cursor):
    return cursor.execute("""
        SELECT
            original_comment,
            translated_comment,
            target_language,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        ORDER BY id
    """).fetchall()


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


def fetch_translation_by_id(cursor, comment_id):
    return cursor.execute("""
        SELECT original_comment, translated_comment, created_at, updated_at, verified_at
        FROM comments
        WHERE id = ?
    """, (comment_id,)).fetchone()


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
