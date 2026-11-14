
from tradutor_pgn.database import initialize_database, record_occurrences, resolve_comment_ids, save_translation
from tradutor_pgn.translation_library_links import resolve_bundle_review


def seed(conn, path, source="en", target="pt"):
    save_translation(conn.cursor(), "hello", "olá", target, source)
    ids = resolve_comment_ids(conn.cursor(), target, ["hello"], source)
    record_occurrences(conn.cursor(), str(path), [(1, 1, 1, "hello")], ids)
    conn.commit()


def test_old_package_finds_unique_compatible_original_without_writing(tmp_path):
    source = tmp_path / "obras" / "livro.pgn"
    source.parent.mkdir()
    source.write_text("[Event Original]", encoding="utf8")
    bundle = tmp_path / "biblioteca" / "livro-BR"
    bundle.mkdir(parents=True)
    (bundle / "livro.pgn").write_bytes(source.read_bytes())
    (bundle / "livro-BR.pgn").write_text("translated", encoding="utf8")
    database = tmp_path / "cache.db"
    conn = initialize_database(str(database))
    seed(conn, source)
    conn.close()
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    result = resolve_bundle_review(database, bundle)
    assert result.status == "compatible"
    assert (result.link.source_file, result.link.source_language, result.link.target_language) == (str(source), "en", "pt")
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == before


def test_identical_files_in_different_paths_are_ambiguous(tmp_path):
    source = tmp_path / "a" / "livro.pgn"
    source.parent.mkdir()
    source.write_text("original", encoding="utf8")
    second = tmp_path / "b" / "livro.pgn"
    second.parent.mkdir()
    second.write_bytes(source.read_bytes())
    bundle = tmp_path / "livro-BR"
    bundle.mkdir()
    (bundle / "livro.pgn").write_bytes(source.read_bytes())
    (bundle / "livro-BR.pgn").write_text("traduzido", encoding="utf8")
    database = tmp_path / "cache.db"
    conn = initialize_database(str(database))
    seed(conn, source)
    seed(conn, second)
    conn.close()
    result = resolve_bundle_review(database, bundle)
    assert result.status == "ambiguous" and result.link is None


def test_old_package_without_matching_original_is_not_linked(tmp_path):
    bundle = tmp_path / "livro-BR"
    bundle.mkdir()
    (bundle / "livro.pgn").write_text("original", encoding="utf8")
    (bundle / "livro-BR.pgn").write_text("translated", encoding="utf8")
    database = tmp_path / "cache.db"
    conn = initialize_database(str(database))
    conn.close()
    assert resolve_bundle_review(database, bundle).status == "unlinked"


def test_missing_candidate_does_not_allow_uncertain_match(tmp_path):
    source = tmp_path / "a" / "livro.pgn"
    source.parent.mkdir()
    source.write_text("original", encoding="utf8")
    missing = tmp_path / "b" / "livro.pgn"
    missing.parent.mkdir()
    missing.write_text("original", encoding="utf8")
    bundle = tmp_path / "livro-BR"
    bundle.mkdir()
    (bundle / "livro.pgn").write_bytes(source.read_bytes())
    (bundle / "livro-BR.pgn").write_text("translated", encoding="utf8")
    database = tmp_path / "cache.db"
    conn = initialize_database(str(database))
    seed(conn, source)
    seed(conn, missing)
    conn.close()
    missing.unlink()
    assert resolve_bundle_review(database, bundle).status == "unavailable"


def test_different_original_content_is_not_a_match(tmp_path):
    source = tmp_path / "a" / "livro.pgn"
    source.parent.mkdir()
    source.write_text("versão diferente", encoding="utf8")
    bundle = tmp_path / "livro-BR"
    bundle.mkdir()
    (bundle / "livro.pgn").write_text("original", encoding="utf8")
    (bundle / "livro-BR.pgn").write_text("translated", encoding="utf8")
    database = tmp_path / "cache.db"
    conn = initialize_database(str(database))
    seed(conn, source)
    conn.close()
    assert resolve_bundle_review(database, bundle).status == "unlinked"
