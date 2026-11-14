from pathlib import Path

from tradutor_pgn.translation_library import LibraryBundle, sort_bundles


def test_date_sort_uses_real_instants_and_keeps_unknown_last():
    later = LibraryBundle(Path("b"), "ready", created_at="2026-01-01T12:00:00+00:00")
    earlier = LibraryBundle(Path("a"), "ready", created_at="2026-01-01T13:00:00+02:00")
    unknown = LibraryBundle(Path("c"), "legacy")
    assert sort_bundles([unknown, earlier, later], "recent") == [later, earlier, unknown]
    assert sort_bundles([unknown, later, earlier], "oldest") == [earlier, later, unknown]
    assert sort_bundles([unknown, later, earlier], "name") == [earlier, later, unknown]
