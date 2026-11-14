from unittest.mock import patch

import pytest

from tradutor_pgn import glossario


@pytest.mark.parametrize("pattern", ["ix", "ik", "is", "ixy", "kıs", "x.i", "i\n"])
@pytest.mark.parametrize("text", ["İx", "ıK", "İſ", "ſı", "Kıſ", "Café e bispo", "İ\u0307X", "\u0130\nx"])
def test_unicode_prefilter_matches_regex_reference(pattern, text):
    import re
    regex = re.compile(re.escape(pattern), re.IGNORECASE)
    expected = []
    position = 0
    while position <= len(text):
        match = regex.search(text, position)
        if match is None:
            break
        start, end = match.span()
        if glossario._has_safe_match_boundary(text, start, end, pattern):
            expected.append((start, end))
            position = end if end > start else start + 1
        else:
            position = start + 1
    assert glossario.find_glossary_matches(text, pattern) == expected


def test_absent_ascii_pattern_in_accented_text_skips_compilation():
    with patch.object(glossario, "_compiled_glossary_pattern", side_effect=AssertionError("regex desnecessária")):
        assert glossario.find_glossary_matches("O peão está protegido", "bispo") == []


def test_every_unicode_character_matching_ascii_letters_survives_normalization():
    import re
    matcher = re.compile(r"[a-z]", re.IGNORECASE)
    for codepoint in range(0x110000):
        character = chr(codepoint)
        if matcher.fullmatch(character):
            normalized = character.casefold().replace("\u0307", "").replace("ı", "i")
            for letter in "abcdefghijklmnopqrstuvwxyz":
                if re.fullmatch(letter, character, re.IGNORECASE):
                    assert letter in normalized, (letter, codepoint)
