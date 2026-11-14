from pathlib import Path

from tradutor_pgn.database import initialize_database, record_occurrences, resolve_comment_ids, save_translation, set_translation_verified_by_id
from tradutor_pgn.translation_library_links import bundle_review_progress, register_link
from tradutor_pgn.translation_output import publish_translation_bundle


def create_linked(tmp_path):
    original = tmp_path / "livro.pgn"
    original.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("traduzido", encoding="utf8")
        return True
    bundle = publish_translation_bundle(str(original), "pt", str(tmp_path / "out"), generate, source_language="en")
    db = tmp_path / "cache.db"
    conn = initialize_database(str(db))
    register_link(conn, bundle.bundle_id, str(original), "en", "pt")
    for text in ("hello", "world"):
        save_translation(conn.cursor(), text, text, "pt", "en")
    ids = resolve_comment_ids(conn.cursor(), "pt", ["hello", "world"], "en")
    record_occurrences(conn.cursor(), str(original), [(1, 1, 1, "hello"), (2, 1, 2, "hello"), (3, 1, 3, "world")], ids)
    set_translation_verified_by_id(conn.cursor(), ids["hello"], True)
    conn.commit()
    conn.close()
    return db, Path(bundle.bundle_dir), Path(bundle.translated_path)


def test_progress_counts_distinct_comments_and_is_read_only(tmp_path):
    db, bundle, _ = create_linked(tmp_path)
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    progress = bundle_review_progress(db, bundle)
    assert (progress.status, progress.total, progress.verified, progress.pending) == ("ready", 2, 1, 1)
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == before


def test_invalid_integrity_is_not_reported_as_zero_progress(tmp_path):
    db, bundle, translated = create_linked(tmp_path)
    translated.write_text("alterado", encoding="utf8")
    progress = bundle_review_progress(db, bundle)
    assert progress.status == "integrity"
    assert progress.total is None


def test_progress_reflects_subsequent_review_changes(tmp_path):
    db, bundle, _ = create_linked(tmp_path)
    conn = initialize_database(str(db))
    ids = resolve_comment_ids(conn.cursor(), "pt", ["world"], "en")
    set_translation_verified_by_id(conn.cursor(), ids["world"], True)
    conn.commit()
    conn.close()
    progress = bundle_review_progress(db, bundle)
    assert (progress.total, progress.verified, progress.pending) == (2, 2, 0)


def test_unlinked_package_does_not_fabricate_progress(tmp_path):
    db, bundle, _ = create_linked(tmp_path)
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(str(db))) as conn:
        conn.execute("DELETE FROM library_bundle_links")
        conn.commit()
    progress = bundle_review_progress(db, bundle)
    assert progress.status == "compatible"
    assert progress.total is None and progress.verified is None
