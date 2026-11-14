from unittest.mock import patch
import re

import pytest

from tradutor_pgn import glossario


def reference(text, orig):
    if not text or not orig:
        return []
    flags = re.IGNORECASE if orig == orig.lower() else 0
    pattern = re.compile(re.escape(orig), flags)
    results = []
    position = 0
    while position <= len(text):
        match = pattern.search(text, position)
        if match is None:
            break
        start, end = match.span()
        if glossario._has_safe_match_boundary(text, start, end, orig):
            results.append((start, end))
            position = end if end > start else start + 1
        else:
            position = start + 1
    return results


@pytest.mark.parametrize("text", ["BISPO e bispo", "bispos bishop", "İ i ı I K K ſ S", "ação AÇÃO", "de de de", "a.b a+b", "", "Peão\nBISPO"])
@pytest.mark.parametrize("pattern", ["bispo", "BISPO", "i", "k", "s", "ação", "Ação", "de de", ".", "+", "", "Peão", "İ"])
def test_prefilter_matches_original_regex_semantics(text, pattern):
    assert glossario.find_glossary_matches(text, pattern) == reference(text, pattern)


def test_absent_ascii_pattern_avoids_regex_compilation():
    with patch.object(glossario, "_compiled_glossary_pattern", side_effect=AssertionError("unnecessary regex")):
        assert glossario.find_glossary_matches("Jogada do bispo", "cavalo") == []
        assert glossario.find_glossary_matches("Jogada do peão", "BISPO") == []


def test_unicode_ignorecase_specials_remain_matched():
    assert glossario.find_glossary_matches("İ ı K ſ", "i") == [(0, 1), (2, 3)]
    assert glossario.find_glossary_matches("İ ı K ſ", "k") == [(4, 5)]
    assert glossario.find_glossary_matches("İ ı K ſ", "s") == [(6, 7)]
