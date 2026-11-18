from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from contextlib import nullcontext

from tradutor_pgn.glossary_catalog import GlossaryConflictError
from tradutor_pgn.repeated_edits_window import RepeatedEditsWindow
from tradutor_pgn import repeated_edits_window


def window(item=None, target="pt"):
    editor = SimpleNamespace(
        current_item=lambda: item or {"old": "rook", "new": "torre"},
        snapshot=SimpleNamespace(catalog_revision=7), source_language="en", target_language=target, source_file="work.pgn",
        catalog=SimpleNamespace(add=Mock(return_value=SimpleNamespace(warning=None))),
        notify_glossary_change=Mock(), refresh=Mock(), win=object(),
    )
    editor.candidate_available = lambda candidate: RepeatedEditsWindow.candidate_available(editor, candidate)
    return editor


@pytest.fixture(autouse=True)
def isolated_decisions():
    with patch("tradutor_pgn.repeated_edits_window.ignored_keys", return_value=set()), \
         patch("tradutor_pgn.repeated_edits_window.available_candidate", side_effect=lambda *_args: nullcontext()):
        yield


def test_create_suggestion_uses_pair_scope_and_does_not_apply_to_database():
    editor = window()
    with patch("tradutor_pgn.repeated_edits_window.messagebox.showinfo"):
        RepeatedEditsWindow.create_suggestion_rule(editor)
    draft, revision = editor.catalog.add.call_args.args
    assert (draft.original_text, draft.replacement_text, draft.rule_type, draft.scope) == (
        "rook", "torre", "suggestion", "en>pt")
    assert revision == 7
    editor.notify_glossary_change.assert_called_once()
    editor.refresh.assert_called_once_with(keep=("rook", "torre"))


def test_create_suggestion_refuses_an_unspecified_target():
    editor = window(target=None)
    with patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"):
        RepeatedEditsWindow.create_suggestion_rule(editor)
    editor.catalog.add.assert_not_called()


def test_concurrent_catalog_change_does_not_create_suggestion():
    editor = window()
    editor.catalog.add.side_effect = GlossaryConflictError(None, 7, 8)
    with patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"):
        RepeatedEditsWindow.create_suggestion_rule(editor)
    editor.notify_glossary_change.assert_not_called()


def test_automatic_rule_also_refuses_missing_target():
    editor = window(target=None)
    with patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"), \
         patch("tradutor_pgn.repeated_edits_window.preview_automatic_rule_impact") as preview:
        RepeatedEditsWindow.create_automatic_rule(editor)
    preview.assert_not_called()
    editor.catalog.add.assert_not_called()


def test_candidate_filter_searches_without_accents_and_shows_uncovered_rules():
    items = [
        {"old": "bispo", "new": "peão", "rule_produces": None},
        {"old": "torre", "new": "peão", "rule_produces": "peão"},
        {"old": "rei", "new": "peão", "rule_produces": "rei"},
    ]
    result = repeated_edits_window.filter_candidates(items, "PEAO", uncovered_only=True)
    assert [item["old"] for item in result] == ["bispo", "rei"]


def test_candidate_filter_applies_minimum_frequency_with_search():
    items = [{"old": "rook", "new": "torre", "count": 2},
             {"old": "rook", "new": "castelo", "count": 8},
             {"old": "bishop", "new": "bispo", "count": 12}]
    assert [i["new"] for i in repeated_edits_window.filter_candidates(items, "rook", minimum_count=5)] == ["castelo"]


def test_candidate_search_includes_displayed_rule_label():
    items = [{"old": "rook", "new": "torre", "rule_label": "automática"},
             {"old": "rook", "new": "castelo", "rule_label": "sugestão"}]
    assert [i["new"] for i in repeated_edits_window.filter_candidates(items, "rook automatica")] == ["torre"]
    assert [i["new"] for i in repeated_edits_window.filter_candidates(items, "sugestao")] == ["castelo"]


def test_candidate_search_shortcut_moves_focus_to_search():
    search = SimpleNamespace(focus_set=Mock())
    editor = SimpleNamespace(search_entry=search)
    assert RepeatedEditsWindow.focus_search(editor) == "break"
    search.focus_set.assert_called_once()


def test_candidate_page_shortcuts_respect_bounds_and_do_not_render_when_empty():
    editor = SimpleNamespace(page_index=0, page_count=3, apply_candidate_filter=Mock())
    assert RepeatedEditsWindow.page_shortcut(editor, "first") == "break"
    editor.apply_candidate_filter.assert_not_called()
    assert RepeatedEditsWindow.page_shortcut(editor, "last") == "break"
    assert editor.page_index == 2
    editor.apply_candidate_filter.assert_called_once_with(retain_selection=False)
    editor.page_count = 0
    editor.apply_candidate_filter.reset_mock()
    RepeatedEditsWindow.page_shortcut(editor, "first")
    editor.apply_candidate_filter.assert_not_called()


def test_select_candidate_shortcut_navigates_inside_and_between_pages():
    editor = SimpleNamespace(items=["a", "b"], selected=0, page_index=0, page_count=2, select=Mock())
    def change_page(delta):
        editor.page_index += delta
        editor.items = ["c"] if delta > 0 else ["a", "b"]
        editor.selected = 0
    editor.change_page = Mock(side_effect=change_page)
    assert RepeatedEditsWindow.select_candidate_shortcut(editor, -1) == "break"
    editor.select.assert_not_called()
    RepeatedEditsWindow.select_candidate_shortcut(editor, 1)
    editor.select.assert_called_once_with(1)
    editor.selected = 1
    RepeatedEditsWindow.select_candidate_shortcut(editor, 1)
    assert editor.page_index == 1
    RepeatedEditsWindow.select_candidate_shortcut(editor, -1)
    assert editor.page_index == 0
    assert editor.select.call_args.args == (1,)


def test_selected_candidate_is_scrolled_into_view():
    canvas = SimpleNamespace(bbox=lambda _: (0, 0, 200, 1000), canvasy=lambda _: 0,
                             winfo_height=lambda: 100, yview_moveto=Mock())
    button = SimpleNamespace(winfo_y=lambda: 400, winfo_height=lambda: 30)
    editor = SimpleNamespace(selected=0, buttons=[button], rows_frame=SimpleNamespace(_parent_canvas=canvas))
    RepeatedEditsWindow._reveal_selected(editor)
    canvas.yview_moveto.assert_called_once_with(0.33)


def test_ignored_candidates_are_hidden_by_default_and_can_be_shown():
    items = [{"old": "rook", "new": "torre", "rule_produces": None, "ignored": True},
             {"old": "bishop", "new": "bispo", "rule_produces": None, "ignored": False}]
    assert [item["old"] for item in repeated_edits_window.filter_candidates(items)] == ["bishop"]
    assert len(repeated_edits_window.filter_candidates(items, show_ignored=True)) == 2
    assert [item["old"] for item in repeated_edits_window.filter_candidates(items, only_ignored=True)] == ["rook"]
    assert repeated_edits_window.filter_candidates(items, "bishop", only_ignored=True) == []


def test_copy_candidate_copies_only_selected_pair():
    clipboard = SimpleNamespace(clipboard_clear=Mock(), clipboard_append=Mock())
    editor = SimpleNamespace(current_item=lambda: {"old": "rook", "new": "torre"}, win=clipboard)
    RepeatedEditsWindow.copy_candidate(editor)
    clipboard.clipboard_clear.assert_called_once()
    clipboard.clipboard_append.assert_called_once_with("rook → torre")


def test_copy_shortcut_invokes_copy_once_and_stops_event():
    editor = SimpleNamespace(copy_candidate=Mock())
    assert RepeatedEditsWindow.copy_candidate_shortcut(editor) == "break"
    editor.copy_candidate.assert_called_once()


def test_candidate_pagination_exposes_items_beyond_the_first_40():
    candidates = list(range(85))
    page, index, pages = repeated_edits_window.candidate_page(candidates, 1)
    assert page == list(range(40, 80))
    assert (index, pages) == (1, 3)
    page, index, pages = repeated_edits_window.candidate_page(candidates, 99)
    assert page == list(range(80, 85)) and (index, pages) == (2, 3)


def test_restore_all_only_targets_ignored_candidates_from_this_list():
    editor = SimpleNamespace(
        all_items=[{"old": "a", "new": "b", "ignored": True},
                   {"old": "c", "new": "d", "ignored": False}],
        source_file="work.pgn", source_language="en", target_language="pt",
        ignored_available=True, refresh=Mock(), win=object(),
        search_var=SimpleNamespace(get=lambda: ""), uncovered_var=SimpleNamespace(get=lambda: False),
        frequency_var=SimpleNamespace(get=lambda: "Todas as frequências"),
    )
    with patch("tradutor_pgn.repeated_edits_window.restore_ignored") as restore:
        RepeatedEditsWindow.restore_all_ignored(editor)
    assert len(restore.call_args.args[0]) == 1
    editor.refresh.assert_called_once()


def test_bulk_restore_respects_search_and_uncovered_filter_across_pages():
    items = [{"old": f"term{i}", "new": "novo", "ignored": True, "rule_produces": None}
             for i in range(60)]
    items += [{"old": "term-other", "new": "novo", "ignored": True, "rule_produces": "novo"},
              {"old": "not-matching", "new": "novo", "ignored": True, "rule_produces": None}]
    editor = SimpleNamespace(all_items=items, source_file="work.pgn", source_language="en", target_language="pt",
                             ignored_available=True, refresh=Mock(), win=object(),
                             search_var=SimpleNamespace(get=lambda: "term"), uncovered_var=SimpleNamespace(get=lambda: True),
                             frequency_var=SimpleNamespace(get=lambda: "Todas as frequências"))
    with patch("tradutor_pgn.repeated_edits_window.restore_ignored") as restore:
        RepeatedEditsWindow.restore_all_ignored(editor)
    assert len(restore.call_args.args[0]) == 60
    editor.refresh.assert_called_once()


def test_bulk_restore_respects_minimum_frequency():
    items = [{"old": "rook", "new": "torre", "count": 3, "ignored": True},
             {"old": "bishop", "new": "bispo", "count": 10, "ignored": True}]
    editor = SimpleNamespace(all_items=items, source_file="work.pgn", source_language="en", target_language="pt",
                             ignored_available=True, refresh=Mock(), win=object(),
                             search_var=SimpleNamespace(get=lambda: ""), uncovered_var=SimpleNamespace(get=lambda: False),
                             frequency_var=SimpleNamespace(get=lambda: "Ao menos 10 ocorrências"))
    with patch("tradutor_pgn.repeated_edits_window.restore_ignored") as restore:
        RepeatedEditsWindow.restore_all_ignored(editor)
    assert restore.call_args.args[0] == [repeated_edits_window.candidate_key("work.pgn", "en", "pt", "bishop", "bispo")]


def test_an_ignored_candidate_cannot_be_created_from_a_stale_window():
    editor = window()
    editor.source_file = "work.pgn"
    key = repeated_edits_window.candidate_key("work.pgn", "en", "pt", "rook", "torre")
    with patch("tradutor_pgn.repeated_edits_window.ignored_keys", return_value={key}), \
         patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"):
        RepeatedEditsWindow.create_suggestion_rule(editor)
    editor.catalog.add.assert_not_called()


def test_automatic_creation_rechecks_curadoria_after_the_preview():
    editor = window()
    editor.win = SimpleNamespace(winfo_exists=lambda: True)
    editor.app = object()
    key = repeated_edits_window.candidate_key("work.pgn", "en", "pt", "rook", "torre")
    def preview(_app, _entry, *, parent, on_decision):
        on_decision(True)
    with patch("tradutor_pgn.repeated_edits_window.ignored_keys", side_effect=[set(), {key}]), \
         patch("tradutor_pgn.repeated_edits_window.preview_automatic_rule_impact", side_effect=preview), \
         patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"):
        RepeatedEditsWindow.create_automatic_rule(editor)
    editor.catalog.add.assert_not_called()


def test_suggestion_is_not_created_if_candidate_becomes_ignored_before_commit():
    editor = window()
    from tradutor_pgn.curation_state import CandidateIgnored
    with patch("tradutor_pgn.repeated_edits_window.available_candidate", side_effect=CandidateIgnored()), \
         patch("tradutor_pgn.repeated_edits_window.messagebox.showwarning"):
        RepeatedEditsWindow.create_suggestion_rule(editor)
    editor.catalog.add.assert_not_called()


def test_candidates_can_be_sorted_by_comments_or_alphabetically():
    items = [{"old": "torre", "new": "x", "count": 10, "lines": 2},
             {"old": "bispo", "new": "y", "count": 5, "lines": 4},
             {"old": "peão", "new": "z", "count": 5, "lines": 4}]
    assert [i["old"] for i in repeated_edits_window.sort_candidates(items, "Mais comentários")] == ["bispo", "peão", "torre"]
    assert [i["old"] for i in repeated_edits_window.sort_candidates(items, "Ordem alfabética")] == ["bispo", "peão", "torre"]
    assert items[0]["old"] == "torre"


def test_candidates_can_show_rare_changes_first():
    items = [{"old": "torre", "new": "x", "count": 10, "lines": 2},
             {"old": "bispo", "new": "y", "count": 5, "lines": 4},
             {"old": "peão", "new": "z", "count": 5, "lines": 3}]
    assert [i["old"] for i in repeated_edits_window.sort_candidates(items, "Menor frequência")] == ["peão", "bispo", "torre"]
    assert [i["old"] for i in repeated_edits_window.sort_candidates(items, "Menos comentários")] == ["torre", "peão", "bispo"]
