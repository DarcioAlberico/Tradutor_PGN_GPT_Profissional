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
