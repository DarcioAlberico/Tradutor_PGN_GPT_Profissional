"""Quality scoring and safe provider-context normalization, without payload output."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tradutor_pgn.writing_assistant import PortugueseWritingAssistant
from tradutor_pgn.writing_types import WritingIssue, WritingRequest, WritingResult


CORPUS = Path(__file__).parent / "fixtures/portuguese_writing_corpus.json"


class EmptySpelling:
    def analyze(self, request, protected):
        return ()


def grammar_result(text, original, suggestions, category="VERBAL_AGREEMENT", **kwargs):
    request = WritingRequest(text, 3, "pt-BR", grammar_enabled=True, **kwargs)
    start = text.index(original)

    class Grammar:
        def analyze(self, request, protected):
            return (WritingIssue("", "GENERAL_VERB_AGREEMENT_ERRORS", category, start,
                                 start + len(original), protected.projected_text[start:start + len(original)],
                                 "Concordância", "Concordância", suggestions, "warning", "languagetool", 3),)

    assistant = PortugueseWritingAssistant(spelling_adapter=EmptySpelling(), grammar_adapter=Grammar())
    return request, assistant.analyze(request)


@pytest.mark.parametrize("text,original,suggestions,want", [
    ("As pretas tem uma posição.", "As pretas tem", ("As pretas têm",), (10, 13, "tem", ("têm",))),
    ("🙂 As pretas tem uma posição.", "As pretas tem", ("As pretas têm",), (12, 15, "tem", ("têm",))),
    ("As peça brancas.", "As peça", ("As peças",), (3, 7, "peça", ("peças",))),
    ("As ação", "As ação", ("As ações",), (3, 9, "ação", ("ações",))),
    ("A posição está ativo.", "A posição está ativo", ("A posição está ativa",),
     (15, 20, "ativo", ("ativa",))),
    ("🙂 A ação está ativo.", "A ação está ativo", ("A ação está ativa",),
     (16, 21, "ativo", ("ativa",))),
    ("O cavalo ocupam o centro.", "O cavalo ocupam", ("O cavalo ocupa",), (9, 15, "ocupam", ("ocupa",))),
    ("As pretas tem uma posição.", "As pretas tem uma", ("As pretas têm uma", "As pretas tinham uma"),
     (10, 13, "tem", ("têm", "tinham"))),
    ("As peça brancas.", "As peça brancas", ("As peças brancas", "As peças branca"),
     (3, 15, "peça brancas", ("peças brancas", "peças branca"))),
])
def test_common_context_is_removed_at_unicode_word_boundaries(text, original, suggestions, want):
    request, result = grammar_result(text, original, suggestions)
    issue, = result.issues
    assert (issue.start, issue.end, issue.original, issue.suggestions) == want
    issue.validate_for(request)
    for before, after in zip(suggestions, issue.suggestions):
        start = text.index(original)
        assert text[:issue.start] + after + text[issue.end:] == text[:start] + before + text[start + len(original):]


@pytest.mark.parametrize("original,suggestions,category", [
    ("está está", ("está",), "REPEATED_WORD"),
    (",,", (",",), "PUNCTUATION"),
    ("tem", (), "VERBAL_AGREEMENT"),
    ("As pretas tem", ("As pretas tem", "As pretas têm"), "VERBAL_AGREEMENT"),
    ("As pretas tem", ("As pretas têm", "As brancas têm"), "VERBAL_AGREEMENT"),
])
def test_ambiguous_or_non_word_edits_keep_a_reconstructable_span(original, suggestions, category):
    request, result = grammar_result(original, original, suggestions, category)
    issue, = result.issues
    issue.validate_for(request)
    for before, after in zip(suggestions, issue.suggestions):
        assert request.text[:issue.start] + after + request.text[issue.end:] == before
    if category in {"REPEATED_WORD", "PUNCTUATION"} or not suggestions or original in suggestions:
        assert (issue.original, issue.suggestions) == (original, suggestions)


@pytest.mark.parametrize("text,original,kwargs", [
    ("Cd4 As pretas tem", "Cd4 As pretas tem", {}),
    ("As pretas tem", "As pretas tem", {"glossary_terms": frozenset({"pretas"})}),
    ("Kasparov tem", "Kasparov tem", {"source_text": "Kasparov"}),
])
def test_trimming_cannot_rescue_a_provider_span_crossing_protected_text(text, original, kwargs):
    _, result = grammar_result(text, original, (original.replace("tem", "têm"),), **kwargs)
    assert result.issues == ()


def test_normalization_does_not_bypass_stale_versions_or_wrong_provider_text():
    request = WritingRequest("As pretas tem", 3, "pt-BR", grammar_enabled=True)

    class InvalidGrammar:
        def analyze(self, request, protected):
            valid = WritingIssue("", "TEST", "VERBAL_AGREEMENT", 0, 13, request.text,
                                 "Concordância", "Concordância", ("As pretas têm",), "warning", "test", 3)
            return (replace(valid, text_version=2), replace(valid, original="As brancas te"))

    assistant = PortugueseWritingAssistant(spelling_adapter=EmptySpelling(), grammar_adapter=InvalidGrammar())
    assert assistant.analyze(request).issues == ()


@pytest.mark.parametrize("category", ["VERBAL_AGREEMENT", "NOMINAL_AGREEMENT"])
def test_agreement_rejects_only_punctuation_only_alternatives_and_counts_category(category):
    request = WritingRequest("As pretas tem", 3, "pt-BR", grammar_enabled=True)

    class Grammar:
        def analyze(self, request, protected):
            return (WritingIssue("", "TEST", category, 0, 13, request.text, "", "",
                                 ("As pretas têm", "As pretas, tem"), "warning", "test", 3),)

    assistant = PortugueseWritingAssistant(spelling_adapter=EmptySpelling(), grammar_adapter=Grammar())
    issue, = assistant.analyze(request).issues
    assert (issue.start, issue.end, issue.original, issue.suggestions) == (10, 13, "tem", ("têm",))
    assert assistant.normalization_counts() == {category: 1}
    assistant.analyze(replace(request, text_version=4))
    assert assistant.normalization_counts() == {category: 1}  # cache hit is not new provider evidence


def test_punctuation_plus_morphology_alternative_and_non_agreement_punctuation_are_retained():
    for category, suggestions in [
        ("VERBAL_AGREEMENT", ("As pretas têm", "As pretas, têm")),
        ("GRAMMAR", ("As pretas têm", "As pretas, tem")),
    ]:
        request, result = grammar_result("As pretas tem", "As pretas tem", suggestions, category)
        issue, = result.issues
        for full, replacement in zip(suggestions, issue.suggestions):
            assert request.text[:issue.start] + replacement + request.text[issue.end:] == full
        assert len(issue.suggestions) == 2


def test_evaluator_counts_exact_spans_categories_suggestions_and_duplicate_predictions():
    from ferramentas.avaliar_corretor_portugues import evaluate_corpus

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    case = corpus["cases"][0]

    class Predictions:
        def analyze(self, request):
            good = WritingIssue("", "VERB", "VERBAL_AGREEMENT", 10, 13, "tem", "", "", ("têm",),
                                "warning", "test", request.text_version)
            wrong_suggestion = WritingIssue("", "SPELL", "SPELLING", 18, 25, "posiçao", "", "", ("posições",),
                                            "error", "test", request.text_version)
            return WritingResult(request.text_version, (good, good, wrong_suggestion), "full")

    report = evaluate_corpus({"schema_version": 1, "cases": [case]}, Predictions(), mode="full")
    assert report["overall"] == {"expected": 2, "presented": 3, "true_positives": 1,
                                  "false_positives": 2, "misses": 1, "precision": 1 / 3, "recall": 0.5}
    assert report["gate"]["stable"] is False
    assert report["cases"][0]["false_positive_rule_ids"] == ["SPELL", "VERB"]
    assert report["spelling_suggestions"]["coverage"] == 1.0
    serialized = json.dumps(report)
    for private in (case["text"], "posiçao", "posições", '"start"', '"end"', '"suggestions"'):
        assert private not in serialized


def test_evaluator_flags_forbidden_spans_even_if_prediction_matches_gold():
    from ferramentas.avaliar_corretor_portugues import evaluate_corpus

    case = {"id": "protected", "text": "Cd4", "source_text": "", "glossary_terms": [],
            "expected_issues": [], "forbidden_ranges": [{"start": 0, "end": 3}]}

    class Predictions:
        def analyze(self, request):
            issue = WritingIssue("", "BAD", "GRAMMAR", 0, 3, "Cd4", "", "", ("Cd5",), "warning", "test", 1)
            return WritingResult(1, (issue,), "full")

    report = evaluate_corpus({"schema_version": 1, "cases": [case]}, Predictions(), mode="full")
    assert report["protected_violations"] == 1
    assert report["gate"]["stable"] is False


def test_evaluator_spelling_scope_keeps_full_gate_unmet_and_failures_visible():
    from ferramentas.avaliar_corretor_portugues import evaluate_corpus

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    class Broken:
        def analyze(self, request):
            raise RuntimeError(request.text)

    report = evaluate_corpus(corpus, Broken(), mode="spelling")
    assert report["overall"]["expected"] == 4
    assert report["overall"]["recall"] == 0
    assert report["failed_cases"] == len(corpus["cases"])
    assert report["gate"]["stable"] is False


def test_real_spylls_baseline_is_independent_of_personal_vocabulary():
    from ferramentas.avaliar_corretor_portugues import create_assistant, evaluate_corpus

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assistant = create_assistant()
    try:
        report = evaluate_corpus(corpus, assistant, mode="spelling")
    finally:
        assistant.shutdown()
    # The productive-prefix suggestion now resolves the fourth reviewed
    # spelling occurrence without changing corpus expectations.
    assert report["overall"]["true_positives"] == 4
    assert report["overall"]["false_positives"] == 0
    assert report["overall"]["misses"] == 0
    assert report["protected_violations"] == report["failed_cases"] == 0


@pytest.mark.parametrize("rule_id,invalid", [
    ("UNKNOWN_RULE_7", False),
    ("request_text", True),
    ("REGRA_É", True),
    ("RΕGRA_7", True),  # Greek epsilon must not impersonate an ASCII ID.
    ("RULE\nPRIVATE_PAYLOAD", True),
    ("R" * 129, True),
])
def test_real_parser_assistant_replay_exports_only_valid_rule_ids(
    tmp_path, monkeypatch, caplog, capsys, rule_id, invalid,
):
    from ferramentas import avaliar_corretor_portugues as evaluator
    from tradutor_pgn.languagetool_client import _issues

    text = "🙂 Informação particular."
    rule_id = text if rule_id == "request_text" else rule_id

    def match(identifier):
        return {"offset": 3, "length": 10, "message": text, "shortMessage": text,
                "replacements": [{"value": "Informações"}],
                "rule": {"id": identifier, "description": text, "issueType": "grammar",
                         "category": {"id": "GRAMMAR"}}}

    class ParsedGrammar:
        def analyze(self, request, protected):
            # Exercise the production parser, including its UTF-16 conversion.
            # A valid issue before a malicious ID must not permit partial success.
            matches = [match("UNKNOWN_RULE_7"), match(rule_id)] if invalid else [match(rule_id)]
            return _issues({"software": {"name": "LanguageTool", "version": "6.6"},
                            "language": {"code": "pt-BR"}, "matches": matches},
                           protected.projected_text, frozenset(), request.text_version)

    assistant = PortugueseWritingAssistant(spelling_adapter=EmptySpelling(), grammar_adapter=ParsedGrammar())
    monkeypatch.setattr(evaluator, "create_assistant", lambda: assistant)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"schema_version": 1, "cases": [{
        "id": "rule-metadata", "text": text, "expected_issues": [{
            "start": 2, "end": 12, "original": "Informação", "category": "GRAMMAR",
            "suggestions": ["Informações"],
        }], "forbidden_ranges": [],
    }]}), encoding="utf-8")
    output = tmp_path / "reports"
    exit_code = evaluator.main(["--mode", "full", "--corpus", str(corpus_path), "--output-dir", str(output)])
    report = json.loads((output / "portuguese-writing-full.json").read_text(encoding="utf-8"))
    markdown = (output / "portuguese-writing-full.md").read_text(encoding="utf-8")
    exported = json.dumps(report, ensure_ascii=False) + markdown + capsys.readouterr().out + caplog.text
    for private in (text, "Informação", "Informações"):
        assert private not in exported
    if invalid:
        assert rule_id not in exported
    assert exit_code == int(invalid)
    assert report["failed_cases"] == int(invalid)
    assert report["overall"]["presented"] == int(not invalid)
    assert report["overall"]["misses"] == int(invalid)
    assert report["cases"][0]["true_positive_rule_ids"] == ([] if invalid else ["UNKNOWN_RULE_7"])
    assert report["cases"][0]["false_positive_rule_ids"] == []
    if invalid:
        assert report["gate"]["stable"] is False
