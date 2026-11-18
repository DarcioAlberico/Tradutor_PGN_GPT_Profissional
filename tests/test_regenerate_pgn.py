from pathlib import Path
from unittest.mock import patch
import sqlite3

from tradutor_pgn.database import initialize_database, record_occurrences, resolve_comment_ids, save_translation
from tradutor_pgn.translation_library_links import register_link
from tradutor_pgn.translation_output import publish_translation_bundle
from tradutor_pgn.regenerate_pgn import regenerate_bundle


def fixture_package(tmp_path, source_text='[Event "Livro"]\n\n1. e4 {hello} e5 {world} *\n'):
    source = tmp_path / "livro.pgn"
    source.write_text(source_text, encoding="utf-8")
    output = tmp_path / "saida"
    def generate(path):
        Path(path).write_text("versão anterior", encoding="utf-8")
        return True
    bundle = publish_translation_bundle(str(source), "pt", str(output), generate, source_language="en")
    db = tmp_path / "cache.db"
    conn = initialize_database(str(db))
    for original, translation in (("hello", "olá revisado"), ("world", "mundo revisado")):
        save_translation(conn.cursor(), original, translation, "pt", "en")
    ids = resolve_comment_ids(conn.cursor(), "pt", ["hello", "world"], "en")
    record_occurrences(conn.cursor(), str(source), [(1, 1, 1, "hello"), (2, 1, 2, "world")], ids)
    register_link(conn, bundle.bundle_id, str(source), "en", "pt")
    conn.commit()
    conn.close()
    return db, bundle, output


def test_regenerates_saved_corrections_in_new_bundle(tmp_path):
    db, old, root = fixture_package(tmp_path)
    original = Path(old.translated_path).read_bytes()
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "published" and result.missing == 0
    assert Path(result.bundle_dir) != Path(old.bundle_dir)
    assert Path(old.translated_path).read_bytes() == original
    text = Path(result.translated_path).read_text(encoding="utf-8")
    assert "{olá revisado}" in text and "{mundo revisado}" in text
    assert '[Event "Livro"]' in text and "1. e4" in text


def test_regeneration_uses_latest_saved_edit_for_same_language_pair(tmp_path):
    from tradutor_pgn.database import update_translation_by_id
    db, old, root = fixture_package(tmp_path)
    with sqlite3.connect(db) as conn:
        identifier = resolve_comment_ids(conn.cursor(), "pt", ["hello"], "en")["hello"]
        update_translation_by_id(conn.cursor(), identifier, "correção mais recente", history_action="edit")
        save_translation(conn.cursor(), "hello", "outro idioma", "pt", "fr")
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "published"
    content = Path(result.translated_path).read_text(encoding="utf-8")
    assert "{correção mais recente}" in content and "outro idioma" not in content


def test_refuses_package_with_modified_original(tmp_path):
    db, old, root = fixture_package(tmp_path)
    Path(old.original_path).write_text("alterado", encoding="utf-8")
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "unavailable"
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_missing_translation_prevents_regeneration(tmp_path):
    db, old, root = fixture_package(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE comments SET translated_comment = '' WHERE original_comment = 'world'")
    first = regenerate_bundle(db, old.bundle_dir, root)
    assert first.status == "missing" and first.missing == 1
    assert first.missing_examples == ("world",)
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_whitespace_only_translation_is_not_considered_complete(tmp_path):
    db, old, root = fixture_package(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE comments SET translated_comment = '   ' WHERE original_comment = 'world'")
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "missing" and result.missing == 1
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_missing_examples_are_bounded_without_losing_total(tmp_path):
    extra = " ".join("{" + ("x" * 200 if i == 0 else f"missing{i}") + "}" for i in range(8))
    db, old, root = fixture_package(tmp_path, f'[Event "Livro"]\n\n1. e4 {{hello}} e5 {{world}} {extra} *\n')
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "missing" and result.missing == 8
    assert len(result.missing_examples) == 5
    assert len(result.missing_examples[0]) == 140 and result.missing_examples[0].endswith("…")


def test_unsupported_semicolon_comment_prevents_regeneration(tmp_path):
    source = '[Event "Livro"]\n\n1. e4 {hello} ; texto não suportado\ne5 {world} *\n'
    db, old, root = fixture_package(tmp_path, source)
    result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "unsupported" and result.unsupported == 1
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_regeneration_never_calls_network(tmp_path):
    db, old, root = fixture_package(tmp_path)
    with patch("requests.sessions.Session.request", side_effect=AssertionError("não deve usar rede")):
        result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "published"


def test_generated_package_keeps_review_link_for_later_regeneration(tmp_path):
    db, old, root = fixture_package(tmp_path)
    first = regenerate_bundle(db, old.bundle_dir, root)
    assert first.link_saved is True
    second = regenerate_bundle(db, first.bundle_dir, root)
    assert second.status == "published" and second.link_saved


def test_cancelled_regeneration_does_not_publish(tmp_path):
    db, old, root = fixture_package(tmp_path)
    result = regenerate_bundle(db, old.bundle_dir, root, should_cancel=lambda: True)
    assert result.status == "canceled"
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_cancel_signal_reaches_package_resolution(tmp_path):
    from tradutor_pgn import regenerate_pgn
    from tradutor_pgn.translation_library_links import ReviewResolution
    db, old, root = fixture_package(tmp_path)
    checks = iter([False, True])
    def resolve(_db, _path, *, should_cancel):
        assert should_cancel()
        return ReviewResolution("canceled")
    with patch.object(regenerate_pgn, "resolve_bundle_review", side_effect=resolve):
        result = regenerate_bundle(db, old.bundle_dir, root, should_cancel=lambda: next(checks))
    assert result.status == "canceled"
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_reading_original_can_be_cancelled_between_blocks(tmp_path):
    import pytest
    from tradutor_pgn.regenerate_pgn import _read_original
    from tradutor_pgn.translation_output import _PublicationCanceled
    source = tmp_path / "grande.pgn"
    source.write_bytes(b"x" * (3 * 1024 * 1024))
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 2
    with pytest.raises(_PublicationCanceled):
        _read_original(source, cancel)
    assert calls == 2


def test_cancel_during_legacy_matching_is_not_reported_as_integrity_failure(tmp_path):
    from tradutor_pgn.translation_library import IntegrityVerificationCanceled
    from tradutor_pgn.translation_library_links import resolve_bundle_review
    db, old, root = fixture_package(tmp_path)
    legacy = root / "livro-BR-antigo"
    legacy.mkdir()
    (legacy / "livro.pgn").write_bytes(Path(old.original_path).read_bytes())
    (legacy / "livro-BR-antigo.pgn").write_text("anterior", encoding="utf-8")
    with patch("tradutor_pgn.translation_library._hash_file", side_effect=IntegrityVerificationCanceled):
        result = resolve_bundle_review(db, legacy, should_cancel=lambda: False)
    assert result.status == "canceled"


def test_legacy_package_requires_confirmation_of_compatible_work(tmp_path):
    db, old, root = fixture_package(tmp_path)
    legacy = root / "livro-BR-antigo"
    legacy.mkdir()
    (legacy / "livro.pgn").write_bytes(Path(old.original_path).read_bytes())
    (legacy / "livro-BR-antigo.pgn").write_text("versão antiga", encoding="utf-8")
    found = regenerate_bundle(db, legacy, root)
    assert found.status == "compatible" and found.link is not None
    assert len([p for p in root.iterdir() if p.is_dir()]) == 2
    result = regenerate_bundle(db, legacy, root, confirmed_link=found.link)
    assert result.status == "published" and result.link_saved
    assert "{olá revisado}" in Path(result.translated_path).read_text(encoding="utf-8")


def test_compatible_match_is_rechecked_before_generation(tmp_path):
    db, old, root = fixture_package(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM library_bundle_links")
    found = regenerate_bundle(db, old.bundle_dir, root)
    assert found.status == "compatible"
    Path(found.link.source_file).write_text("origem modificada", encoding="utf-8")
    result = regenerate_bundle(db, old.bundle_dir, root, confirmed_link=found.link)
    assert result.status != "published"


def test_source_changed_after_read_does_not_publish(tmp_path):
    from tradutor_pgn import regenerate_pgn
    db, old, root = fixture_package(tmp_path)
    original_load = regenerate_pgn.load_translation_cache
    def load_and_modify(*args, **kwargs):
        result = original_load(*args, **kwargs)
        Path(old.original_path).write_text("alteração concorrente", encoding="utf-8")
        return result
    with patch.object(regenerate_pgn, "load_translation_cache", side_effect=load_and_modify):
        result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status != "published"
    assert len([p for p in root.iterdir() if p.is_dir()]) == 1


def test_output_retained_when_review_link_cannot_be_saved(tmp_path):
    db, old, root = fixture_package(tmp_path)
    with patch("tradutor_pgn.regenerate_pgn.register_link", side_effect=sqlite3.OperationalError("bloqueado")):
        result = regenerate_bundle(db, old.bundle_dir, root)
    assert result.status == "published" and result.link_saved is False
    assert Path(result.translated_path).exists()


def test_uses_requested_output_bom_without_changing_original(tmp_path):
    db, old, root = fixture_package(tmp_path)
    before = Path(old.original_path).read_bytes()
    result = regenerate_bundle(db, old.bundle_dir, root, use_bom=True)
    assert result.status == "published"
    assert Path(result.translated_path).read_bytes().startswith(b"\xef\xbb\xbf")
    assert Path(old.original_path).read_bytes() == before
