from pathlib import Path

from tradutor_pgn.translation_library import LibraryBundle, search_bundles


def test_library_search_finds_accented_names_without_typing_accents():
    bundle = LibraryBundle(Path("Aberturas e estratégias"), "legacy")
    assert search_bundles([bundle], "estrategias") == [bundle]
    assert search_bundles([bundle], "ESTRATÉGIAS") == [bundle]


def test_search_accepts_words_in_any_order_and_across_metadata():
    bundle = LibraryBundle(Path("Aberturas e estratégias"), "ready",
                           source_language="en", target_language="pt", provider="deepseek")
    assert search_bundles([bundle], "deepseek aberturas pt") == [bundle]
    assert search_bundles([bundle], "deepseek finais") == []
