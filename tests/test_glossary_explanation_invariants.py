from itertools import product

from tradutor_pgn.glossary_engine import explain_substitutions
from tradutor_pgn.glossario import apply_all_substitutions, find_glossary_matches


def test_explanations_reconstruct_output_and_blocked_ranges_across_inputs():
    rulesets = [
        [("rook", "torre"), ("white rook", "torre branca")],
        [("rook", "torre", 2), ("white rook", "torre branca", 0)],
        [("rook", "torre"), ("rook", "castelo")],
        [("♞", ""), ("rook", "torre")],
    ]
    tokens = ("rook", "white rook", "♞", "other")
    for pieces in product(tokens, repeat=3):
        text = " ".join(pieces)
        for rules in rulesets:
            result = explain_substitutions(text, rules, include_suppressed=True)
            assert result.text == apply_all_substitutions(text, rules)
            cursor = 0
            rebuilt = []
            for match in sorted(result.matches, key=lambda match: match.start):
                assert cursor <= match.start < match.end <= len(text)
                assert text[match.start:match.end] == match.matched
                rebuilt.extend((text[cursor:match.start], match.replacement))
                cursor = match.end
            rebuilt.append(text[cursor:])
            assert "".join(rebuilt) == result.text
            for blocked in result.suppressed:
                assert (blocked.start, blocked.end) in find_glossary_matches(text, blocked.pattern)
                assert blocked.start < blocked.winner.end and blocked.winner.start < blocked.end
                assert blocked.winner.order < len(rules)
