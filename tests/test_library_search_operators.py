from pathlib import Path

from tradutor_pgn.translation_library import LibraryBundle, search_bundles


def samples():
    return [
        LibraryBundle(Path('Primeiro'), 'ready', source_language='en', target_language='pt', provider='libretranslate', created_at='2026-11-16T12:00:00+00:00'),
        LibraryBundle(Path('Segundo'), 'legacy', source_language='es', target_language='pt', provider='google', created_at='2026-10-01T12:00:00+00:00'),
        LibraryBundle(Path('Terceiro'), 'invalid'),
    ]


def test_search_source_operator_is_exact_and_combines_with_text():
    items = samples()
    assert search_bundles(items, 'origem:en primeiro') == [items[0]]
    assert search_bundles(items, 'origem:en segundo') == []
    assert search_bundles(items, 'origem:?') == [items[2]]


def test_search_target_operator_combines_with_existing_facet():
    items = samples()
    assert search_bundles(items, 'destino:pt', source='es') == [items[1]]
    assert search_bundles(items, 'destino:?') == [items[2]]


def test_search_provider_operator_is_case_insensitive_and_exact():
    items = samples()
    assert search_bundles(items, 'motor:LibreTranslate') == [items[0]]
    assert search_bundles(items, 'motor:google') == [items[1]]
    assert search_bundles(items, 'motor:?') == [items[2]]


def test_search_status_operator_accepts_portuguese_and_unknown_is_safe():
    items = samples()
    assert search_bundles(items, 'situação:com-manifesto') == [items[0]]
    assert search_bundles(items, 'situacao:sem-manifesto') == [items[1]]
    assert search_bundles(items, 'situacao:invalido') == [items[2]]
    assert search_bundles(items, 'situacao:inexistente') == []


def test_search_date_operator_supports_comparisons_and_unknown():
    items = samples()
    assert search_bundles(items, 'data:2026-11-16') == [items[0]]
    assert search_bundles(items, 'data:>=2026-11-01') == [items[0]]
    assert search_bundles(items, 'data:<2026-11-01') == [items[1]]
    assert search_bundles(items, 'data:?') == [items[2]]
    assert search_bundles(items, 'data:2026-99-01') == []

def test_operators_combine_and_contradictions_return_no_results():
    items = samples()
    assert search_bundles(items, 'origem:en destino:pt motor:libretranslate situacao:com-manifesto data:>=2026-11-01 data:<=2026-11-30') == [items[0]]
    assert search_bundles(items, 'origem:en origem:es') == []
    assert search_bundles(items, 'origem:en', source='es') == []


def test_invalid_dates_do_not_match_and_unknown_date_is_explicit():
    items = samples()
    assert search_bundles(items, 'data:>=2026-02-30') == []
    assert search_bundles(items, 'data:palavra') == []
    assert search_bundles(items, 'data:? destino:pt') == []


def test_search_remains_case_and_accent_insensitive():
    items = samples()
    assert search_bundles(items, 'SITUA\u00c7\u00c3O:INV\u00c1LIDO') == [items[2]]

def test_search_name_operator_restricts_to_folder_name():
    items = samples()
    assert search_bundles(items, 'nome:prime') == [items[0]]
    assert search_bundles(items, 'nome:google') == []


def test_search_original_filename_operator_and_missing():
    items = [LibraryBundle(Path('a'), 'ready', original=Path('Abertura Inglesa.pgn')),
             LibraryBundle(Path('b'), 'legacy')]
    assert search_bundles(items, 'original:inglesa') == [items[0]]
    assert search_bundles(items, 'original:?') == [items[1]]


def test_search_translated_filename_operator_and_missing():
    items = [LibraryBundle(Path('a'), 'ready', translated=Path('Abertura-BR.pgn')),
             LibraryBundle(Path('b'), 'legacy')]
    assert search_bundles(items, 'traduzido:-br') == [items[0]]
    assert search_bundles(items, 'traduzido:?') == [items[1]]


def test_search_language_operator_matches_either_side():
    items = samples()
    assert search_bundles(items, 'idioma:pt') == items[:2]
    assert search_bundles(items, 'idioma:en') == [items[0]]
    assert search_bundles(items, 'idioma:?') == [items[2]]


def test_search_date_can_match_year_or_month():
    items = samples()
    assert search_bundles(items, 'data:2026') == items[:2]
    assert search_bundles(items, 'data:2026-10') == [items[1]]
    assert search_bundles(items, 'data:2026-99') == []
    assert search_bundles(items, 'data:>=2026-10') == []
