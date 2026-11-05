"""Real Unicode indices survive masking, including protected-span rejection."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

from hypothesis import example, given, settings, strategies as st
import pytest

from tradutor_pgn.writing_protection import protect_text, restore_issue_offsets
from tradutor_pgn.writing_types import WritingIssue, WritingRequest


def projected_issue(protected, start, end, category="SPELLING", **changes):
    values = dict(
        issue_id="", rule_id="TEST", category=category, start=start, end=end,
        original=protected.projected_text[start:end], message="Verifique.",
        explanation="", suggestions=("correção",), severity="error",
        provider="test", text_version=protected.text_version,
    )
    values.update(changes)
    return WritingIssue(**values)


@pytest.mark.parametrize("fragment,kind", [
    ("Cd4", "notation"), ("13.", "move_number"),
    ("[%eval +0.35]", "annotation"), ("[%custom payload]", "annotation"),
    ("[%clk 0:05:30]", "annotation"), ("[%cal Ra1h8]", "annotation"),
    ("[%csl Gd4]", "annotation"), ("$5", "nag"), ("!?", "nag"),
    ("O-O-O", "notation"), ("0-0", "notation"), ("e8=D+", "notation"),
    ("C×d4+", "notation"), ("h4-h5", "notation"),
    ("https://example.org/a?q=1", "url"),
    ("autor@example.org", "email"), ("motor_v2", "identifier"),
])
def test_technical_fragments_are_masked_without_moving_offsets(fragment, kind):
    text = "🙂 ação " + fragment + " fim"
    protected = protect_text(WritingRequest(text, 7, "pt"))
    start, end = 7, 7 + len(fragment)
    assert protected.original_text == text
    assert len(protected.projected_text) == len(text)
    assert protected.projected_text[start:end] == " " * len(fragment)
    assert any(r.kind == kind and r.start <= start and r.end >= end for r in protected.ranges)
    assert protected.index_map[end] == end
    assert restore_issue_offsets(projected_issue(protected, start, end), protected) is None


@pytest.mark.parametrize("url", [
    "https://[2001:db8::1]/recurso",
    "https://example.org/author's/report",
    "https://example.org/entry_(chess)",
])
@pytest.mark.parametrize("opening,closing", [
    ("", ""), ("(", ")"), ("[", "]"), ("<", ">"),
    ("'", "'"), ('"', '"'), ("{", "}"),
])
def test_complete_urls_are_protected_with_external_delimiters_separate(url, opening, closing):
    text = f"🙂 Consulte {opening}{url}{closing}, depois."
    protected = protect_text(WritingRequest(text, 1, "pt"))
    start = text.index(url)
    end = start + len(url)
    assert [(r.start, r.end) for r in protected.ranges if r.kind == "url"] == [(start, end)]
    assert protected.projected_text == text[:start] + " " * len(url) + text[end:]
    for index in range(start, end):
        assert restore_issue_offsets(projected_issue(protected, index, index + 1), protected) is None
    if opening:
        assert restore_issue_offsets(projected_issue(protected, start - 1, start, "PUNCTUATION"),
                                     protected) is not None
        assert restore_issue_offsets(projected_issue(protected, end, end + 1, "PUNCTUATION"),
                                     protected) is not None


def test_adjacent_move_number_and_san_are_both_protected():
    protected = protect_text(WritingRequest("Após 13.Cd4 a posição é ativa.", 1, "pt"))
    assert protected.projected_text[5:11] == "      "
    assert restore_issue_offsets(projected_issue(protected, 5, 11), protected) is None
    assert protected.projected_text[12:] == "a posição é ativa."


def test_prose_question_and_exclamation_remain_visible_but_san_annotations_are_protected():
    protected = protect_text(WritingRequest("É bom? Sim! Após Cd4!? fica claro.", 1, "pt"))
    assert protected.projected_text == "É bom? Sim! Após       fica claro."
    assert restore_issue_offsets(projected_issue(protected, 5, 6, "PUNCTUATION"), protected)
    assert restore_issue_offsets(projected_issue(protected, 10, 11, "PUNCTUATION"), protected)


def test_names_from_source_and_multiword_glossary_use_whole_word_boundaries():
    text = "Kasparov vê a Defesa Índia do Rei e Kasparoviano."
    request = WritingRequest(text, 1, "pt", source_text="Kasparov played well.",
                             glossary_terms=frozenset({"defesa índia do rei"}))
    protected = protect_text(request)
    assert protected.projected_text == "         vê a                     e Kasparoviano."
    assert {(r.kind, text[r.start:r.end]) for r in protected.ranges} == {
        ("source_name", "Kasparov"), ("glossary", "Defesa Índia do Rei"),
    }


@pytest.mark.parametrize("token", ["d'Alembert", "kasparov", "bispo"])
def test_all_source_vocabulary_is_protected_without_capitalization_heuristics(token):
    text = f"🙂 {token} permanece."
    protected = protect_text(WritingRequest(text, 1, "pt", source_text=f"Sobre {token}."))
    end = 2 + len(token)
    assert protected.projected_text == "🙂 " + " " * len(token) + " permanece."
    assert any(r.kind == "source_name" and (r.start, r.end) == (2, end)
               for r in protected.ranges)
    assert restore_issue_offsets(projected_issue(protected, 2, end), protected) is None
    assert protected.index_map[end] == end


def test_normalization_maps_back_to_real_decomposed_unicode_and_casefold_expansions():
    text = "🙂 ac\u0327a\u0303o STRASSE São"
    protected = protect_text(WritingRequest(text, 2, "pt", source_text="São agrees.",
                             glossary_terms=frozenset({"ação", "Straße"})))
    assert [(r.start, r.end, r.kind) for r in protected.ranges] == [
        (2, 8, "glossary"), (9, 16, "glossary"), (17, 20, "source_name"),
    ]
    assert len(protected.projected_text) == 20
    assert protected.index_map == tuple(range(21))


def test_mask_preserves_line_breaks_and_is_immutable():
    protected = protect_text(WritingRequest("[%custom x\r\ny]\nerro", 1, "pt"))
    assert protected.projected_text == "          \r\n  \nerro"
    with pytest.raises(FrozenInstanceError):
        protected.projected_text = "changed"


def test_restoration_preserves_unicode_span_and_rejects_stale_or_inconsistent_input():
    protected = protect_text(WritingRequest("🙂 ação posiçao após Cd4", 3, "pt"))
    item = projected_issue(protected, 7, 14)
    restored = restore_issue_offsets(item, protected)
    assert restored is not None
    assert (restored.start, restored.end, restored.original) == (7, 14, "posiçao")
    assert restore_issue_offsets(replace(item, text_version=4), protected) is None
    assert restore_issue_offsets(replace(item, original="xxxxxxx"), protected) is None
    assert restore_issue_offsets(replace(item, start=30, end=37), protected) is None


def test_issue_crossing_any_protected_range_is_discarded():
    protected = protect_text(WritingRequest("boa Cd4 posição", 1, "pt"))
    assert restore_issue_offsets(projected_issue(protected, 0, 10), protected) is None
    assert restore_issue_offsets(projected_issue(protected, 3, 5), protected) is None
    assert restore_issue_offsets(projected_issue(protected, 7, 15), protected) is not None


def test_only_exact_grammatical_glossary_conflict_is_retained_as_suppressed():
    protected = protect_text(WritingRequest("a contra-jogo ativo", 1, "pt",
                             glossary_terms=frozenset({"contra-jogo"})))
    grammar = projected_issue(protected, 2, 13, "NOMINAL_AGREEMENT")
    restored = restore_issue_offsets(grammar, protected)
    assert restored is not None
    assert (restored.original, restored.state) == ("contra-jogo", "suppressed_by_glossary")
    assert restore_issue_offsets(replace(grammar, category="SPELLING"), protected) is None
    assert restore_issue_offsets(projected_issue(protected, 0, 13, "GRAMMAR"), protected) is None


def test_glossary_overlap_never_overrides_technical_protection():
    protected = protect_text(WritingRequest("Cd4", 1, "pt", glossary_terms=frozenset({"Cd4"})))
    assert restore_issue_offsets(projected_issue(protected, 0, 3, "GRAMMAR"), protected) is None


@st.composite
def text_and_span(draw):
    text = draw(st.text(min_size=1, max_size=80))
    start = draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = draw(st.integers(min_value=start + 1, max_value=len(text)))
    return text, start, end


@settings(max_examples=200, deadline=None)
@given(text_and_span())
@example(("🙂 ac\u0327a\u0303o erro", 9, 13))
def test_unicode_round_trip_never_returns_an_out_of_bounds_or_changed_span(case):
    text, start, end = case
    protected = protect_text(WritingRequest(text, 1, "pt"))
    restored = restore_issue_offsets(projected_issue(protected, start, end), protected)
    assert len(protected.projected_text) == len(text)
    if restored is not None:
        assert 0 <= restored.start < restored.end <= len(text)
        assert restored.original == text[start:end]
        assert (restored.start, restored.end) == (start, end)
    if not any(r.start < end and start < r.end for r in protected.ranges):
        assert restored is not None


@settings(max_examples=200, deadline=None)
@given(prefix=st.text(max_size=40), suffix=st.text(max_size=40))
@example(prefix="🙂 ac\u0327a\u0303o", suffix="fim")
def test_unicode_around_an_annotation_retains_both_sides_and_rejects_crossing(prefix, suffix):
    text = prefix + " [%eval +0.35] " + suffix
    protected = protect_text(WritingRequest(text, 2, "pt"))
    start = len(prefix) + 1
    end = start + 13
    assert protected.projected_text[start:end] == " " * 13
    assert restore_issue_offsets(projected_issue(protected, start - 1, end + 1), protected) is None
    assert protected.index_map[start] == start
    assert protected.index_map[end] == end


def test_corpus_is_versioned_complete_and_has_real_disjoint_offsets():
    corpus = json.loads((Path(__file__).parent / "fixtures" / "portuguese_writing_corpus.json")
                        .read_text(encoding="utf-8"))
    assert corpus["schema_version"] == 1
    cases = corpus["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert "TA-004" in {case["id"] for case in cases}
    categories = set()
    for case in cases:
        assert set(case) == {"id", "text", "source_text", "glossary_terms",
                             "expected_issues", "forbidden_ranges", "notes"}
        request = WritingRequest(case["text"], 1, "pt", case["source_text"],
                                 frozenset(case["glossary_terms"]))
        protected = protect_text(request)
        for expected in case["expected_issues"]:
            categories.add(expected["category"])
            start, end = expected["start"], expected["end"]
            assert 0 <= start < end <= len(request.text)
            assert request.text[start:end] == expected["original"]
            assert not any(r["start"] < end and start < r["end"]
                           for r in case["forbidden_ranges"])
        for forbidden in case["forbidden_ranges"]:
            start, end = forbidden["start"], forbidden["end"]
            assert 0 <= start < end <= len(request.text)
            assert request.text[start:end] == forbidden["original"]
            assert all(any(r.start <= i < r.end for r in protected.ranges)
                       for i in range(start, end))
    assert categories == {"SPELLING", "NOMINAL_AGREEMENT", "VERBAL_AGREEMENT",
                          "REPEATED_WORD", "PUNCTUATION"}
