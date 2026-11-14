from tradutor_pgn.glossario import apply_all_substitutions
from tradutor_pgn import glossary_engine
from tradutor_pgn.glossary_engine import explain_substitutions
from tradutor_pgn.glossary_editor import GlossaryEditor
from types import SimpleNamespace
from unittest.mock import patch


def test_explanation_reports_effective_rule_and_case_adjusted_replacement():
    rules = [("white rook", "torre branca", 2), ("rook", "torre", 0)]
    result = explain_substitutions("White rook and rook", rules)
    assert result.text == apply_all_substitutions("White rook and rook", rules)
    assert [(m.pattern, m.matched, m.replacement) for m in result.matches] == [
        ("white rook", "White rook", "Torre branca"), ("rook", "rook", "torre")
    ]


def test_explanation_never_counts_a_rule_suppressed_by_a_previous_match():
    result = explain_substitutions("white rook", [("white rook", "torre branca"), ("rook", "torre")])
    assert result.text == "torre branca"
    assert [m.pattern for m in result.matches] == ["white rook"]


def test_explanation_preserves_repeated_occurrences():
    result = explain_substitutions("rook rook", [("rook", "torre")])
    assert len(result.matches) == 2
    assert result.text == "torre torre"


def test_editor_reports_rules_and_occurrences_in_all_rules_preview():
    captured = []
    editor = SimpleNamespace(
        test_text_var=SimpleNamespace(get=lambda: "rook rook bishop"),
        state=SimpleNamespace(entries=[]),
        btn_preview_details=SimpleNamespace(configure=lambda **_kwargs: None),
        preview_rules=lambda _entries: [("rook", "torre"), ("bishop", "bispo")],
        set_preview_text=lambda text, status=None: captured.append((text, status)),
    )
    GlossaryEditor.apply_all_to_preview(editor)
    assert captured[0][0] == "torre torre bispo"
    assert "3" in captured[0][1] and "2" in captured[0][1]


def test_formatted_explanation_shows_applied_rules_and_limits_length():
    result = explain_substitutions("rook rook bishop", [("rook", "torre", 1), ("bishop", "bispo")])
    report = glossary_engine.format_explanation(result, max_rules=1)
    assert "rook" in report and "torre" in report
    assert "2" in report
    assert "1 regra" in report.lower()


def test_editor_can_show_the_rules_used_in_preview():
    result = explain_substitutions("rook", [("rook", "torre")])
    editor = SimpleNamespace(preview_explanation=result, preview_explanation_context=("rook", [("rook", "torre")]), win=object())
    def run(_parent, _title, work, on_success=None, **_kwargs):
        on_success(work(SimpleNamespace(cancelado=lambda: False)))
    with patch("tradutor_pgn.glossary_editor.run_with_progress", side_effect=run), \
         patch("tradutor_pgn.glossary_editor.messagebox.showinfo") as dialog:
        GlossaryEditor.show_preview_explanation(editor)
    assert "rook" in dialog.call_args.args[1]
    assert "torre" in dialog.call_args.args[1]
    assert "bloqueadas" in dialog.call_args.args[1].lower()


def test_explanation_dialog_truncates_very_long_rules():
    source, target = "x" * 5000, "y" * 5000
    report = glossary_engine.format_explanation(explain_substitutions(source, [(source, target)]))
    assert len(report) < 500
    assert "…" in report


def test_explanation_identifies_overlapping_rule_suppressed_by_priority():
    result = explain_substitutions("white rook", [("white rook", "torre branca", 0),
                                                  ("rook", "torre", 2)], include_suppressed=True)
    assert result.text == "white torre"
    assert len(result.suppressed) == 1
    blocked = result.suppressed[0]
    assert (blocked.pattern, blocked.matched, blocked.start, blocked.end) == ("white rook", "white rook", 0, 10)
    assert blocked.winner.pattern == "rook" and blocked.reason == "prioridade"
    report = glossary_engine.format_explanation(result)
    assert "2 > 0" in report


def test_explanation_identifies_specificity_and_original_unicode_positions():
    result = explain_substitutions("♞ white rook", [("rook", "torre"), ("white rook", "torre branca")],
                                   include_suppressed=True)
    assert result.text == "♞ torre branca"
    blocked = result.suppressed[0]
    assert (blocked.start, blocked.end, blocked.reason) == (8, 12, "especificidade")


def test_explanation_distinguishes_stable_order_on_equal_priority_and_length():
    result = explain_substitutions("rook", [("rook", "torre"), ("rook", "castelo")], include_suppressed=True)
    assert result.suppressed[0].reason == "ordem"
    assert result.suppressed[0].winner.configured_replacement == "torre"
    report = glossary_engine.format_explanation(result)
    assert "castelo" in report and "torre" in report


def test_suppressed_matches_are_bounded_and_reported_as_incomplete():
    result = explain_substitutions("rook rook", [("rook", "torre"), ("rook", "castelo")],
                                   include_suppressed=True, max_suppressed=1)
    assert len(result.suppressed) == 1 and result.truncated
    report = glossary_engine.format_explanation(result)
    assert "ordem" in report.lower() and "limit" in report.lower()


def test_suppressed_analysis_can_be_cancelled():
    with __import__("pytest").raises(glossary_engine.SimulationCanceled):
        explain_substitutions("rook", [("rook", "torre"), ("rook", "castelo")],
                              include_suppressed=True, should_cancel=lambda: True)


def test_detailed_explanation_shows_actual_occurrence_and_output_case():
    result = explain_substitutions("White rook", [("white rook", "torre branca")], include_suppressed=True)
    report = glossary_engine.format_explanation(result)
    assert "White rook" in report and "Torre branca" in report
    assert "1–10" in report


def test_cancelled_explanation_does_not_read_rules():
    class UnexpectedRules:
        def __len__(self):
            raise AssertionError("regras não devem ser lidas após cancelamento")
    with __import__("pytest").raises(glossary_engine.SimulationCanceled):
        explain_substitutions("rook", UnexpectedRules(), include_suppressed=True, should_cancel=lambda: True)


def test_explanation_can_cancel_during_rule_application():
    checks = iter([False, True])
    with patch("tradutor_pgn.glossario.find_glossary_matches", side_effect=AssertionError("não deve casar")):
        with __import__("pytest").raises(glossary_engine.SimulationCanceled):
            explain_substitutions("rook", [("other", "outro")], include_suppressed=True,
                                  should_cancel=lambda: next(checks))
