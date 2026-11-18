from types import SimpleNamespace
from unittest.mock import patch

from tradutor_pgn.glossary_editor import GlossaryEditor
from tradutor_pgn.glossary_engine import SimulationItem, format_simulation_summary, simulate_rule_change


def test_impact_counts_language_pairs_independently():
    items = [SimulationItem('rook', 'en', 'pt'), SimulationItem('rook', 'fr', 'pt'),
             SimulationItem('knight', 'en', 'pt'), SimulationItem('rook', None, 'pt')]
    result = simulate_rule_change(items, [], [('rook', 'torre', 'automatic', 0, 'en>pt')])
    assert [(item.source_language, item.target_language, item.scanned, item.changed)
            for item in result.pairs] == [('en', 'pt', 2, 1), ('fr', 'pt', 1, 0), (None, 'pt', 1, 0)]


def test_summary_reports_percentage_without_rounding_incomplete_to_100():
    result = simulate_rule_change([SimulationItem('rook', 'en', 'pt')] * 999 +
                                  [SimulationItem('knight', 'en', 'pt')], [],
                                  [('rook', 'torre', 'automatic', 0, 'en>pt')], max_examples=0)
    summary = format_simulation_summary(result)
    assert '99%' in summary and '100%' not in summary


def test_summary_distinguishes_empty_input_from_no_changes():
    assert 'Nenhuma' in format_simulation_summary(simulate_rule_change([], [], []))
    summary = format_simulation_summary(simulate_rule_change([SimulationItem('rook', 'en', 'pt')], [], []))
    assert '0 de 1' in summary


def test_summary_reports_how_many_examples_are_not_shown():
    result = simulate_rule_change([SimulationItem('rook', 'en', 'pt')] * 3, [],
                                  [('rook', 'torre', 'automatic', 0, 'pt')], max_examples=1)
    assert '2' in format_simulation_summary(result) and len(result.examples) == 1


def test_nonautomatic_draft_is_explained_in_comparison_dialog():
    editor = SimpleNamespace(
        current_pair=lambda: ('rook', 'torre'), current_rule_type=lambda: 'suggestion',
        current_priority=lambda: 0, current_scope=lambda: 'pt', preview_languages=lambda: ('en', 'pt'),
        test_text_var=SimpleNamespace(get=lambda: 'rook'),
        state=SimpleNamespace(entries=[], selected_index=None), win=object(),
    )
    def run(_parent, _title, work, on_success=None, **kwargs):
        on_success(work(SimpleNamespace(cancelado=lambda: False)))
    with patch('tradutor_pgn.glossary_editor.run_with_progress', side_effect=run), \
         patch('tradutor_pgn.glossary_editor.messagebox.showinfo') as dialog:
        GlossaryEditor.compare_draft_preview(editor)
    assert 'não é automática' in dialog.call_args.args[1]


def test_changing_automatic_to_suggestion_still_shows_removal_impact():
    before = [('rook', 'torre', 'automatic', 0, 'en>pt')]
    after = [('rook', 'torre', 'suggestion', 0, 'en>pt')]
    result = simulate_rule_change([SimulationItem('rook', 'en', 'pt')], before, after)
    assert result.changed == 1
    assert (result.examples[0].before, result.examples[0].after) == ('torre', 'rook')


def test_summary_limits_pair_rows_and_reports_omitted_pairs():
    items = [SimulationItem('rook', f'lang{i}', 'pt') for i in range(12)]
    summary = format_simulation_summary(simulate_rule_change(items, [], []))
    assert 'Mais 2 par(es)' in summary
    assert 'lang10' not in summary
