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
