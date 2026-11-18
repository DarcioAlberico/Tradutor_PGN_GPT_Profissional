from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from tradutor_pgn.glossary_editor import GlossaryEditor, glossary_filter_indices, sort_glossary_indices


def test_priority_filter_composes_with_type_and_scope():
    entries = [("a", "x", "automatic", -3, "pt"),
               ("b", "y", "automatic", 0, "pt"),
               ("c", "z", "automatic", 2, "pt"),
               ("d", "w", "suggestion", 2, "")]
    assert glossary_filter_indices(entries, priority_filter="positive", rule_type="automatic") == [2]
    assert glossary_filter_indices(entries, priority_filter="zero") == [1]
    assert glossary_filter_indices(entries, priority_filter="negative", scope_filter="specific") == [0]


def test_plain_search_does_not_compute_diagnostics():
    entries = [("rook", "torre", "automatic", 0, "pt")]
    with patch("tradutor_pgn.glossary_editor.glossary_entry_warnings", side_effect=AssertionError("diagnóstico desnecessário")):
        assert glossary_filter_indices(entries, "rook") == [0]


def test_search_finds_glossary_entries_without_accents():
    entries = [("exchange variation", "variante das trocas", "suggestion"),
               ("king's bishop", "bispo do rei", "automatic")]
    assert glossary_filter_indices(entries, "AUTOMATICA bispo") == [1]


def test_multiple_words_can_span_original_and_translation():
    entries = [("exchange variation", "variante das trocas", "suggestion"),
               ("another variation", "outro lance", "suggestion")]
    assert glossary_filter_indices(entries, "trocas exchange") == [0]


def test_search_can_match_rule_scope_and_type_together():
    entries = [("rook", "torre", "automatic", 0, "en>pt"),
               ("rook", "torre", "automatic", 0, "en>es")]
    assert glossary_filter_indices(entries, "automatica en>pt") == [0]


def test_type_facet_combines_with_search_and_existing_diagnostics():
    entries = [("rook", "torre", "automatic"), ("rook", "castelo", "suggestion")]
    diagnostics = [[], ["Mesmo original com substituição diferente."]]
    assert glossary_filter_indices(entries, "rook", "Todas", diagnostics, rule_type="automatic") == [0]
    assert glossary_filter_indices(entries, "rook", "Conflitos", diagnostics, rule_type="suggestion") == [1]


def test_priority_sort_is_stable_in_both_directions():
    entries = [("a", "x", "suggestion", 0), ("b", "y", "automatic", 4),
               ("c", "z", "automatic", 4), ("d", "w", "automatic", -2)]
    assert sort_glossary_indices(entries, range(4), "Maior prioridade") == [1, 2, 0, 3]
    assert sort_glossary_indices(entries, range(4), "Menor prioridade") == [3, 0, 1, 2]


def test_scope_facet_combines_with_type_and_search():
    entries = [("rook", "torre", "automatic", 0, ""),
               ("rook", "torre", "automatic", 0, "en>pt"),
               ("rook", "torre", "suggestion", 0, "pt")]
    assert glossary_filter_indices(entries, "rook", rule_type="automatic", scope_filter="global") == [0]
    assert glossary_filter_indices(entries, "rook", rule_type="automatic", scope_filter="specific") == [1]


def test_clear_all_filters_keeps_the_selected_draft():
    variables = [SimpleNamespace(set=Mock()) for _ in range(5)]
    editor = SimpleNamespace(search_text=variables[0], filter_segment=variables[1],
                             type_filter_text=variables[2], scope_filter_text=variables[3], priority_filter_text=variables[4],
                             state=SimpleNamespace(page_index=4, selected_id="keep"), apply_filter=Mock())
    GlossaryEditor.clear_all_filters(editor)
    assert [v.set.call_args.args[0] for v in variables] == ["", "Todas", "Todos os tipos", "Todos os escopos", "Todas as prioridades"]
    assert editor.state.page_index == 0 and editor.state.selected_id == "keep"
    editor.apply_filter.assert_called_once()


def test_language_facet_matches_current_pair_without_guessing_unknown_origin():
    entries = [("a", "x", "automatic", 0, ""), ("b", "y", "automatic", 0, "en>pt"),
               ("c", "z", "automatic", 0, "fr>pt"), ("d", "w", "automatic", 0, "pt")]
    assert glossary_filter_indices(entries, scope_filter="compatible", source_language="en", target_language="pt") == [0, 1, 3]
    assert glossary_filter_indices(entries, scope_filter="compatible", source_language=None, target_language="pt") == [0, 3]


def test_changing_languages_refreshes_an_active_pair_filter():
    editor = SimpleNamespace(scope_filter_text=SimpleNamespace(get=lambda: "Compatíveis com o par atual"),
                             restart_at_first_page=Mock())
    GlossaryEditor.refresh_pair_filter(editor)
    editor.restart_at_first_page.assert_called_once()
