import pytest

from tradutor_pgn.glossary_engine import SimulationCanceled
from tradutor_pgn.glossary_rule_inspector import analyze_rule, format_rule_impact


def test_explains_phase_without_promising_automatic_suggestions():
    result = analyze_rule(('rook', 'torre', 'suggestion', 0, '*'), [], None, 'rook', 'en', 'pt')
    text = format_rule_impact(result)
    assert 'sugestão' in text.lower() and 'não é aplicada automaticamente' in text.lower()
    assert 'prévia interativa' in text.lower()


def test_scope_is_checked_against_pair_and_unknown_target_is_not_assumed():
    draft = ('rook', 'torre', 'automatic', 0, 'en>pt')
    assert analyze_rule(draft, [], None, 'rook', 'en', 'pt').scope_status == 'compatible'
    outside = analyze_rule(draft, [], None, 'rook', 'fr', 'pt')
    assert outside.scope_status == 'outside' and outside.isolated == 'rook'
    unknown = analyze_rule(draft, [], None, 'rook', 'en', None)
    assert unknown.scope_status == 'unknown' and unknown.after is None


def test_priority_is_explained_without_claiming_the_draft_wins():
    result = analyze_rule(('rook', 'torre', 'automatic', 3, 'pt'), [], None, 'rook', 'en', 'pt')
    text = format_rule_impact(result)
    assert 'prioridade 3' in text.lower() and 'precedência' in text.lower()


def test_isolated_cleanup_uses_real_whitespace_normalization_and_square_expansion():
    cleanup = analyze_rule(('rook', 'torre', 'cleanup', 0, 'pt'), [], None, '  rook   rook  ', 'en', 'pt')
    assert cleanup.isolated == 'torre torre'
    assert 'normaliza espaços' in format_rule_impact(cleanup).lower()
    square = analyze_rule(('@casa@-torre', 'torre de @casa@', 'automatic', 0, 'pt'), [], None, 'e4-torre', 'en', 'pt')
    assert square.isolated == 'torre de e4'


def test_comparison_uses_competing_rule_priority_and_reports_blocking():
    existing = [('rook', 'castelo', 'automatic', 10, 'pt')]
    draft = ('rook', 'torre', 'automatic', 0, 'pt')
    result = analyze_rule(draft, existing, None, 'rook', 'en', 'pt')
    assert result.before == result.after == 'castelo'
    assert result.isolated == 'torre'
    assert 'bloqueada' in format_rule_impact(result)


def test_invalid_priority_and_empty_sample_do_not_simulate():
    invalid = analyze_rule(('rook', 'torre', 'automatic', None, 'pt'), [], None, 'rook', 'en', 'pt')
    assert invalid.after is None and 'prioridade inválida' in format_rule_impact(invalid).lower()
    empty = analyze_rule(('rook', 'torre', 'automatic', 0, 'pt'), [], None, '', 'en', 'pt')
    assert empty.after is None and 'texto de teste' in format_rule_impact(empty).lower()


def test_cancellation_discards_result():
    with pytest.raises(SimulationCanceled):
        analyze_rule(('rook', 'torre', 'automatic', 0, 'pt'), [], None, 'rook', 'en', 'pt', should_cancel=lambda: True)
