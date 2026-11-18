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


def test_search_accepts_displayed_language_names_and_codes():
    bundle = LibraryBundle(Path("Livro"), "ready", source_language="en", target_language="pt", provider="google")
    assert search_bundles([bundle], "portugues ingles") == [bundle]
    assert search_bundles([bundle], "português en google") == [bundle]
    assert search_bundles([bundle], "francês") == []
    unknown = LibraryBundle(Path("Outro"), "legacy")
    assert search_bundles([unknown], "portugues") == []


def test_search_can_find_displayed_package_status():
    invalid = LibraryBundle(Path("Livro A"), "invalid")
    legacy = LibraryBundle(Path("Livro B"), "legacy")
    assert search_bundles([invalid, legacy], "manifesto invalido") == [invalid]
    assert search_bundles([invalid, legacy], "sem manifesto") == [legacy]


def test_search_finds_dates_shown_in_cards():
    dated = LibraryBundle(Path("Livro"), "ready", created_at="2026-11-14T15:30:00+00:00")
    undated = LibraryBundle(Path("Outro"), "legacy")
    assert search_bundles([dated, undated], "2026-11") == [dated]
    assert search_bundles([dated, undated], "2026-11-14") == [dated]
    assert search_bundles([dated, undated], "14/11/2026") == [dated]
    assert search_bundles([dated, undated], "15:30") == []


def test_invalid_or_missing_date_is_not_guessed():
    bundle = LibraryBundle(Path("Livro"), "ready", created_at="2026-99-99T12:00:00Z")
    assert search_bundles([bundle], "99/99/2026") == []


def test_search_finds_original_and_translated_file_names_without_paths():
    bundle = LibraryBundle(Path("pacote"), "ready", original=Path("privado/original-da-obra.pgn"),
                           translated=Path("privado/traduzido-final.pgn"))
    assert search_bundles([bundle], "original-da-obra") == [bundle]
    assert search_bundles([bundle], "traduzido-final") == [bundle]
    assert search_bundles([bundle], "privado") == []


def test_search_finds_generation_failure_count_without_guessing_unknown():
    failed = LibraryBundle(Path("Livro"), "ready", failed_comments=3)
    none = LibraryBundle(Path("Outro"), "ready", failed_comments=0)
    unknown = LibraryBundle(Path("Antigo"), "legacy")
    assert search_bundles([failed, none, unknown], "falhas geracao 3") == [failed]
    assert search_bundles([failed, none, unknown], "falhas geracao 0") == [none]
    assert search_bundles([unknown], "falhas") == []


def test_exact_failure_search_does_not_match_numbers_in_other_fields():
    wanted = LibraryBundle(Path("Livro"), "ready", failed_comments=3)
    wrong = LibraryBundle(Path("Livro 3"), "ready", failed_comments=0)
    unknown = LibraryBundle(Path("Livro 3 antigo"), "legacy")
    assert search_bundles([wanted, wrong, unknown], "livro falhas:3") == [wanted]
    assert search_bundles([wanted, wrong, unknown], "falhas:0") == [wrong]
    assert search_bundles([wanted, wrong, unknown], "falhas:3", failures="without") == []
    assert search_bundles([wanted, wrong, unknown], "falhas:3 falhas:0") == []
    assert search_bundles([wanted, wrong, unknown], "falhas:0003") == [wanted]
    assert search_bundles([wanted], "falhas:" + "9" * 5000) == []


def test_unknown_failure_search_distinguishes_unknown_from_zero():
    zero = LibraryBundle(Path("Livro"), "ready", failed_comments=0)
    unknown = LibraryBundle(Path("Livro antigo"), "legacy")
    assert search_bundles([zero, unknown], "livro falhas:?") == [unknown]
    assert search_bundles([zero, unknown], "falhas:? falhas:0") == []
    assert search_bundles([zero, unknown], "falhas:?", failures="without") == []


def test_failure_range_search_combines_limits_and_excludes_unknown():
    items = [LibraryBundle(Path(f"Livro-{i}"), "ready", failed_comments=i) for i in (0, 2, 5, 10)]
    unknown = LibraryBundle(Path("Livro antigo"), "legacy")
    assert search_bundles(items + [unknown], "falhas:>=2 falhas:<10") == items[1:3]
    assert search_bundles(items, "falhas:>2 falhas:<=10") == items[2:]
    assert search_bundles(items + [unknown], "falhas:>=0") == items
    assert search_bundles(items, "falhas:>" + "9" * 5000) == []
