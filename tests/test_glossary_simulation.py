import pytest
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from tradutor_pgn import glossary_engine
from tradutor_pgn.glossary_editor import GlossaryEditor
from tradutor_pgn.database import initialize_database, save_translation


def test_simulation_cancels_within_a_single_comment():
    from tradutor_pgn import glossario
    rules = [(f"term{i:04}", "outro", "automatic", 0, "pt") for i in range(400)]
    item = glossary_engine.SimulationItem("nenhuma ocorrência", "en", "pt")
    original = glossario.find_glossary_matches
    calls = 0
    def track(*args):
        nonlocal calls
        calls += 1
        return original(*args)
    with patch.object(glossario, "find_glossary_matches", side_effect=track):
        with pytest.raises(glossary_engine.SimulationCanceled):
            glossary_engine.simulate_rule_change([item], rules, [], should_cancel=lambda: calls > 0)
    assert 0 < calls < len(rules)


def test_simulation_with_cancellation_signal_preserves_result():
    samples = [glossary_engine.SimulationItem("rook and rook", "en", "pt")]
    rules = [("rook", "torre", "automatic", 0, "pt")]
    expected = glossary_engine.simulate_rule_change(samples, [], rules)
    assert glossary_engine.simulate_rule_change(samples, [], rules, should_cancel=lambda: False) == expected


def test_cancelled_simulation_does_not_consume_rule_inputs():
    def rules():
        raise AssertionError("regras não devem ser consumidas após cancelamento")
        yield
    with pytest.raises(glossary_engine.SimulationCanceled):
        glossary_engine.simulate_rule_change([], rules(), [], should_cancel=lambda: True)


def test_simulation_compares_competing_rules_with_real_priority():
    samples = [glossary_engine.SimulationItem("rook", "en", "pt")]
    before = [("rook", "torre", "automatic", 0, "pt"),
              ("rook", "castelo", "automatic", 1, "pt")]
    after = [("rook", "torre", "automatic", 2, "pt"), before[1]]
    result = glossary_engine.simulate_rule_change(samples, before, after)
    assert (result.scanned, result.changed) == (1, 1)
    assert (result.examples[0].before, result.examples[0].after) == ("castelo", "torre")


def test_simulation_respects_language_scope_and_limits_examples():
    samples = (glossary_engine.SimulationItem("rook", "en", target) for target in ("pt", "es", "pt"))
    after = [("rook", "torre", "automatic", 0, "en>pt")]
    result = glossary_engine.simulate_rule_change(samples, [], after, max_examples=1)
    assert (result.scanned, result.changed, result.unchanged) == (3, 2, 1)
    assert len(result.examples) == 1
    assert result.examples[0].item.target_language == "pt"


def test_cancelled_simulation_does_not_return_partial_results():
    samples = [glossary_engine.SimulationItem("rook", "en", "pt")]
    with pytest.raises(glossary_engine.SimulationCanceled):
        glossary_engine.simulate_rule_change(samples, [], [], should_cancel=lambda: True)


def test_simulation_refuses_missing_target_language():
    samples = [glossary_engine.SimulationItem("rook", "en", None)]
    with pytest.raises(ValueError, match="destino"):
        glossary_engine.simulate_rule_change(samples, [], [])


def test_editor_compares_draft_with_existing_automatic_rules():
    entries = [("rook", "torre", "automatic", 0, "pt"),
               ("rook", "castelo", "automatic", 1, "pt")]
    editor = SimpleNamespace(
        current_pair=lambda: ("rook", "torre"), current_rule_type=lambda: "automatic",
        current_priority=lambda: 2, current_scope=lambda: "pt",
        preview_languages=lambda: ("en", "pt"), test_text_var=SimpleNamespace(get=lambda: "rook"),
        state=SimpleNamespace(entries=entries, selected_index=0), win=object(),
    )
    def run(_parent, _title, work, on_success=None, **_kwargs):
        task = SimpleNamespace(cancelado=lambda: False)
        on_success(work(task))

    with patch("tradutor_pgn.glossary_editor.run_with_progress", side_effect=run), \
         patch("tradutor_pgn.glossary_editor.messagebox.showinfo") as dialog:
        GlossaryEditor.compare_draft_preview(editor)
    message = dialog.call_args.args[1]
    assert "castelo" in message and "torre" in message
    assert "semente" in message.lower()
    assert entries[0][3] == 0


def test_simulation_handles_zero_example_limit_without_losing_count():
    samples = [glossary_engine.SimulationItem("rook", "en", "pt")]
    result = glossary_engine.simulate_rule_change(samples, [], [("rook", "torre", "automatic", 0, "pt")],
                                                  max_examples=0)
    assert (result.scanned, result.changed, result.examples) == (1, 1, ())


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_simulation_rejects_invalid_example_limits(limit):
    with pytest.raises(ValueError):
        glossary_engine.simulate_rule_change([], [], [], max_examples=limit)


def test_database_simulation_is_read_only_and_excludes_verified_rows(tmp_path):
    path = tmp_path / "cache.db"
    conn = initialize_database(str(path))
    save_translation(conn.cursor(), "a", "rook", "pt", "en")
    save_translation(conn.cursor(), "b", "rook", "pt", "en")
    conn.execute("UPDATE comments SET verified = 1 WHERE original_comment = 'b'")
    conn.commit()
    conn.close()
    original = path.read_bytes()
    after = [("rook", "torre", "automatic", 0, "en>pt")]
    result = glossary_engine.simulate_database_rule_change(path, [], after)
    assert (result.scanned, result.changed) == (1, 1)
    assert result.examples[0].item.reference is not None
    assert path.read_bytes() == original


def test_editor_can_compare_draft_against_pending_database_translations():
    entries = [("rook", "torre", "automatic", 0, "pt")]
    editor = SimpleNamespace(
        current_pair=lambda: ("rook", "castelo"), current_rule_type=lambda: "automatic",
        current_priority=lambda: 0, current_scope=lambda: "pt", preview_languages=lambda: ("en", "pt"),
        test_text_var=SimpleNamespace(get=lambda: ""), state=SimpleNamespace(entries=entries, selected_index=0),
        app=SimpleNamespace(output_db="cache.db"), win=object(),
    )
    result = glossary_engine.SimulationResult(3, 2, 1, ())
    def run(_parent, _title, work, on_success=None, **_kwargs):
        on_success(work(SimpleNamespace(cancelado=lambda: False, report=lambda *_: None)))
    with patch("tradutor_pgn.glossary_editor.run_with_progress", side_effect=run), \
         patch("tradutor_pgn.glossary_editor.simulate_database_rule_change", return_value=result) as simulate, \
         patch("tradutor_pgn.glossary_editor.messagebox.showinfo") as dialog:
        GlossaryEditor.compare_draft_preview(editor, database=True)
    assert simulate.call_args.kwargs["target_language"] == "pt"
    assert simulate.call_args.kwargs["source_language"] == "en"
    assert "2" in dialog.call_args.args[1] and "3" in dialog.call_args.args[1]


def test_database_simulation_respects_pair_and_does_not_create_missing_database(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        glossary_engine.simulate_database_rule_change(missing, [], [])
    assert not missing.exists()
    path = tmp_path / "cache.db"
    conn = initialize_database(str(path))
    for original, source, target in [("a", "en", "pt"), ("b", "fr", "pt"), ("c", "en", "es")]:
        save_translation(conn.cursor(), original, "rook", target, source)
    conn.commit()
    conn.close()
    rule = [("rook", "torre", "automatic", 0, "en>pt")]
    result = glossary_engine.simulate_database_rule_change(path, [], rule, target_language="pt", source_language="en")
    assert (result.scanned, result.changed) == (1, 1)


def test_comparison_message_limits_large_examples():
    before = "x" * 10000
    after = "y" * 10000
    text = glossary_engine.format_simulation_examples(
        glossary_engine.SimulationResult(1, 1, 0, (glossary_engine.SimulationExample(
            glossary_engine.SimulationItem("x", "en", "pt"), before, after),))
    )
    assert len(text) < 1000
    assert "…" in text


def test_database_examples_show_comment_id_and_language_pair():
    item = glossary_engine.SimulationItem("rook", "en", "pt", 42)
    result = glossary_engine.SimulationResult(1, 1, 0, (glossary_engine.SimulationExample(item, "rook", "torre"),))
    text = glossary_engine.format_simulation_examples(result)
    assert "42" in text and "en" in text and "pt" in text


def test_database_simulation_can_be_cancelled_without_changing_data(tmp_path):
    path = tmp_path / "cache.db"
    conn = initialize_database(str(path))
    save_translation(conn.cursor(), "a", "rook", "pt", "en")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(glossary_engine.SimulationCanceled):
        glossary_engine.simulate_database_rule_change(path, [], [], should_cancel=lambda: True)
    assert path.read_bytes() == before
