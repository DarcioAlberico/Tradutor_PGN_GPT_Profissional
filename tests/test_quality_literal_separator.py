from tradutor_pgn.review_quality import evaluate_translation_quality
from tradutor_pgn.database import initialize_database, reevaluate_quality_warnings, save_translation


def separator_warnings(original, translated):
    return [warning for warning in evaluate_translation_quality(original, translated)
            if "separador de lote" in warning.lower()]


def test_preserved_literal_separator_is_not_flagged():
    assert separator_warnings("first ||| second", "primeiro ||| segundo") == []


def test_added_or_lost_separator_is_flagged():
    assert separator_warnings("first", "primeiro ||| segundo")
    assert separator_warnings("first ||| second", "primeiro segundo")


def test_multiple_separators_require_matching_count():
    assert separator_warnings("one ||| two ||| three", "um ||| dois ||| três") == []
    assert separator_warnings("one ||| two ||| three", "um ||| dois")


def test_reevaluation_updates_cached_warning_without_changing_text(tmp_path):
    conn = initialize_database(str(tmp_path / "cache.db"))
    try:
        save_translation(conn.cursor(), "first ||| second", "primeiro ||| segundo", "pt", "en")
        conn.execute("UPDATE comments SET quality_warning = 1")
        conn.commit()
        stats = reevaluate_quality_warnings(conn)
        row = conn.execute("SELECT original_comment, translated_comment, quality_warning FROM comments").fetchone()
        assert row == ("first ||| second", "primeiro ||| segundo", 0)
        assert stats["changed"] == 1
    finally:
        conn.close()
