import json
import sqlite3
from pathlib import Path

from tradutor_pgn.translation_library_links import register_link, resolve_link
from tradutor_pgn.translation_output import publish_translation_bundle


def test_manifest_has_random_identifier_and_link_roundtrips(tmp_path):
    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(tmp_path / "out"), generate,
                                        source_language="en", provider="google")
    manifest = json.loads((Path(result.bundle_dir) / "manifesto.json").read_text(encoding="utf8"))
    assert result.bundle_id == manifest["bundle_id"]
    assert str(source) not in json.dumps(manifest)
    connection = sqlite3.connect(":memory:")
    register_link(connection, result.bundle_id, str(source), "en", "pt")
    link = resolve_link(connection, result.bundle_id)
    assert (link.source_file, link.source_language, link.target_language) == (str(source), "en", "pt")
    assert resolve_link(connection, "e3d6b602-7f2a-4fd9-b516-5c15c7b3a67e") is None
    connection.close()


def test_link_is_immutable_and_invalid_ids_are_rejected():
    connection = sqlite3.connect(":memory:")
    bundle_id = "e3d6b602-7f2a-4fd9-b516-5c15c7b3a67e"
    register_link(connection, bundle_id, "first.pgn", "", "pt")
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        register_link(connection, bundle_id, "second.pgn", "en", "it")
    assert resolve_link(connection, bundle_id).source_file == "first.pgn"
    with pytest.raises(ValueError):
        register_link(connection, "not-a-uuid", "first.pgn", "en", "pt")
    connection.close()


def test_reading_a_database_without_links_does_not_create_tables():
    connection = sqlite3.connect(":memory:")
    assert resolve_link(connection, "e3d6b602-7f2a-4fd9-b516-5c15c7b3a67e") is None
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    connection.close()


def test_review_resolves_only_a_verified_link_with_matching_occurrences(tmp_path):
    from tradutor_pgn.database import initialize_database, record_occurrences, resolve_comment_ids, save_translation
    from tradutor_pgn.translation_library_links import resolve_bundle_review

    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(tmp_path / "out"), generate,
                                        source_language="en")
    db_path = tmp_path / "cache.db"
    conn = initialize_database(str(db_path))
    register_link(conn, result.bundle_id, str(source), "en", "pt")
    conn.commit()
    assert resolve_bundle_review(db_path, result.bundle_dir).status == "no_occurrences"
    save_translation(conn.cursor(), "hello", "olá", "pt", "en")
    ids = resolve_comment_ids(conn.cursor(), "pt", ["hello"], "en")
    record_occurrences(conn.cursor(), str(source), [(1, 1, 1, "hello")], ids)
    conn.commit()
    conn.close()
    resolved = resolve_bundle_review(db_path, result.bundle_dir)
    assert resolved.status == "ready" and resolved.link.source_file == str(source)
    other_db = initialize_database(str(tmp_path / "other.db"))
    other_db.close()
    assert resolve_bundle_review(tmp_path / "other.db", result.bundle_dir).status == "unlinked"
    manifest_path = Path(result.bundle_dir) / "manifesto.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["source_language"] = "es"
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    assert resolve_bundle_review(db_path, result.bundle_dir).status == "unlinked"
    manifest["source_language"] = "en"
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    Path(result.translated_path).write_text("alterado", encoding="utf8")
    assert resolve_bundle_review(db_path, result.bundle_dir).status == "integrity"
