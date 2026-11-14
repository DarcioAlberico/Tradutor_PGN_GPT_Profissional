from pathlib import Path

import pytest

from tradutor_pgn.translation_library import LibraryBundle, bundle_summary, review_percentage, search_bundles, sort_bundles


def bundles():
    return [LibraryBundle(Path("b"), "ready", source_language="en", target_language="pt", provider="motor", failed_comments=2),
            LibraryBundle(Path("a"), "ready", failed_comments=0), LibraryBundle(Path("c"), "legacy")]


def test_filter_by_failure_state_preserves_unknown():
    items = bundles()
    assert search_bundles(items, failures="with") == items[:1]
    assert search_bundles(items, failures="without") == [items[1]]
    assert search_bundles(items, failures="unknown") == [items[2]]
    assert search_bundles(items, source="en", failures="with") == items[:1]
    assert search_bundles(items, source="en", failures="without") == []
    with pytest.raises(ValueError):
        search_bundles(items, failures="invalid")


def test_order_by_failure_count_keeps_unknown_last():
    items = bundles()
    assert sort_bundles(items, "failures_desc") == [items[0], items[1], items[2]]
    assert sort_bundles(items, "failures_asc") == [items[1], items[0], items[2]]


def test_summary_contains_known_metadata_not_content_or_hash():
    text = bundle_summary(bundles()[0])
    assert "b" in text and "en" in text and "pt" in text and "motor" in text
    assert "2" in text and "falha" in text.lower()
    assert "Não informado" in bundle_summary(bundles()[2])
    assert "sha256" not in text.lower()


def test_percentage_does_not_round_incomplete_review_to_one_hundred():
    assert review_percentage(199, 200) == 99
    assert review_percentage(3, 3) == 100
    assert review_percentage(0, 0) == 0
