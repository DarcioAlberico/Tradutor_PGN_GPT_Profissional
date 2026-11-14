from types import SimpleNamespace
from unittest.mock import Mock, patch

from tradutor_pgn.glossary_editor import GlossaryEditor
from tradutor_pgn.db_tools import format_promotion_preview


def test_automatic_scope_and_priority_changes_request_impact_analysis():
    editor = SimpleNamespace(form_baseline={"orig": "rook", "new": "torre",
                                             "type": "automatic", "priority": 0, "scope": "pt"})
    assert GlossaryEditor.promotes_to_automatic(editor, "rook", "torre", "automatic", 5, "pt")
    assert GlossaryEditor.promotes_to_automatic(editor, "rook", "torre", "automatic", 0, "en>pt")
    assert not GlossaryEditor.promotes_to_automatic(editor, "rook", "torre", "automatic", 0, "pt")


def test_impact_explanation_discloses_that_competing_rules_are_not_simulated():
    message = format_promotion_preview(("rook", "torre", "automatic", 0, "pt"),
                                       {"changed": 0, "scanned": 1})
    assert "isolad" in message.lower()
    assert "concorr" in message.lower()


def test_impact_explanation_identifies_scope_and_priority():
    message = format_promotion_preview(("rook", "torre", "automatic", 7, "en>pt"),
                                       {"changed": 2, "scanned": 10})
    assert "en>pt" in message
    assert "7" in message


def test_prioritizing_automatic_conflict_requires_impact_confirmation():
    editor = SimpleNamespace(
        state=SimpleNamespace(selected_index=0, conflicts={0: {"pattern": "rook"}}, dirty=False,
                              entries=[("rook", "torre", "automatic", 0, "pt")]),
        require_selected_record=lambda: ("id", 1),
        catalog=SimpleNamespace(update=Mock()),
        show_message=Mock(), finish_mutation=Mock(), win=object(),
        measure_promotion_then=Mock(),
    )
    with patch("tradutor_pgn.glossary_editor.promote_glossary_rule",
               return_value=[("rook", "torre", "automatic", 1, "pt")]), \
         patch("tradutor_pgn.glossary_editor.messagebox.askyesno", return_value=True):
        GlossaryEditor.promote_this_rule(editor)
    editor.measure_promotion_then.assert_called_once()
    editor.catalog.update.assert_not_called()
