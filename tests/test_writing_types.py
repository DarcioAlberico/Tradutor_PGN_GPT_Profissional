"""The public boundary rejects stale/invalid spans and retains immutable data."""

from dataclasses import FrozenInstanceError, asdict, replace
import json

import pytest

from tradutor_pgn.writing_types import (
    AssistantStatus,
    WritingIssue,
    WritingRequest,
    WritingResult,
)


def issue(**changes):
    values = dict(
        issue_id="", rule_id="SPELL", category="SPELLING", start=2, end=6,
        original="erro", message="Verifique a palavra.", explanation="Grafia.",
        suggestions=("certo",), severity="error", provider="test", text_version=3,
    )
    values.update(changes)
    return WritingIssue(**values)


def test_request_and_nested_collections_are_immutable():
    words = {"peão"}
    request = WritingRequest("🙂 erro", 3, "pt", glossary_terms=words)
    words.add("bispo")
    assert request.glossary_terms == frozenset({"peão"})
    assert isinstance(request.session_ignored_words, frozenset)
    with pytest.raises(FrozenInstanceError):
        request.text = "mudou"


def test_issue_and_result_freeze_input_collections_and_limit_suggestions():
    suggestions = ["um", "dois", "três", "quatro", "cinco", "seis"]
    item = issue(suggestions=suggestions)
    suggestions.clear()
    assert item.suggestions == ("um", "dois", "três", "quatro", "cinco")
    items = [item]
    result = WritingResult(3, items, "full")
    items.clear()
    assert result.issues == (item,)
    with pytest.raises(FrozenInstanceError):
        item.start = 0


@pytest.mark.parametrize("version", [-1, 1.5, True, "3", None])
def test_rejects_invalid_text_versions(version):
    with pytest.raises(ValueError):
        WritingRequest("texto", version, "pt")
    with pytest.raises(ValueError):
        issue(text_version=version)
    with pytest.raises(ValueError):
        WritingResult(version, (), "full")


@pytest.mark.parametrize("changes", [
    {"category": "STYLE"}, {"severity": "fatal"}, {"state": "hidden"},
    {"start": -1}, {"end": 2}, {"start": True}, {"end": 6.5},
    {"original": "longer"}, {"suggestions": [1]},
])
def test_rejects_invalid_issue_values(changes):
    with pytest.raises(ValueError):
        issue(**changes)


def test_issue_validation_uses_real_unicode_text_and_version():
    request = WritingRequest("🙂 erro!", 3, "pt")
    issue().validate_for(request)
    for invalid in [issue(start=5, end=9), issue(original="xxxx"), issue(text_version=4)]:
        with pytest.raises(ValueError):
            invalid.validate_for(request)


def test_issue_id_is_stable_across_versions_and_distinguishes_occurrences():
    first = issue()
    assert first.issue_id
    assert first.issue_id == issue().issue_id
    assert first.issue_id == issue(message="Outra explicação", suggestions=()).issue_id
    assert first.issue_id != issue(start=8, end=12).issue_id
    assert first.issue_id == issue(text_version=4).issue_id
    assert first.issue_id != issue(rule_id="OTHER").issue_id
    assert first.issue_id != issue(category="GRAMMAR").issue_id


def test_result_rejects_mixed_versions_and_validates_spans_against_request():
    with pytest.raises(ValueError):
        WritingResult(4, (issue(),), "full")
    result = WritingResult(3, (issue(),), "spelling_only")
    result.validate_for(WritingRequest("🙂 erro", 3, "pt"))
    with pytest.raises(ValueError):
        result.validate_for(WritingRequest("curto", 3, "pt"))
    with pytest.raises(ValueError):
        result.validate_for(WritingRequest("🙂 erro", 4, "pt"))


def test_status_and_public_values_are_json_serializable():
    status = AssistantStatus("ready", "spelling_only", "", False)
    assert json.loads(json.dumps(asdict(status)))["mode"] == "spelling_only"
    assert json.loads(json.dumps(asdict(issue())))["category"] == "SPELLING"
    with pytest.raises(ValueError):
        replace(status, state="full")
    with pytest.raises(ValueError):
        replace(status, mode="ready")
    with pytest.raises(ValueError):
        WritingResult(3, (), "unknown")
