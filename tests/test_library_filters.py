from pathlib import Path

from tradutor_pgn.translation_library import LibraryBundle, search_bundles


def test_filters_combine_with_search_and_status():
    items = [LibraryBundle(Path("livro"), "ready", source_language="en", target_language="pt", provider="google"),
             LibraryBundle(Path("outro"), "ready", source_language="es", target_language="pt", provider="modelo"),
             LibraryBundle(Path("legado"), "legacy")]
    assert search_bundles(items, "livro", "ready", source="en", target="pt", provider="google") == [items[0]]
    assert search_bundles(items, source="es", provider="google") == []
    assert search_bundles(items, source="", target="", provider="") == [items[2]]
    assert search_bundles(items, target="pt") == items[:2]
