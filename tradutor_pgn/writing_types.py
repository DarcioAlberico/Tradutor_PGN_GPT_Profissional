"""Immutable public values for the offline Portuguese writing assistant.

Offsets count Python Unicode code points, never UTF-16 units or encoded bytes.
An issue validates its own shape at construction; ``validate_for`` additionally
checks the complete request before displaying or applying a suggestion.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Literal, get_args
import unicodedata

from .spelling_suggestions_process import SuggestionState


IssueCategory = Literal[
    "SPELLING", "NOMINAL_AGREEMENT", "VERBAL_AGREEMENT", "GRAMMAR",
    "PUNCTUATION", "REPEATED_WORD",
]
AssistantMode = Literal["full", "spelling_only", "unavailable"]
AssistantState = Literal["stopped", "starting", "ready", "restarting", "failed"]
IssueState = Literal["active", "suppressed_by_glossary"]
IssueSeverity = Literal["error", "warning"]


def _version(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("text_version must be a non-negative integer")


def make_issue_id(
    provider: str, rule_id: str, category: IssueCategory,
    start: int, end: int, original: str,
) -> str:
    """Stable occurrence identity, independent of messages and text versions."""
    payload = json.dumps(
        [provider, rule_id, category, start, end, unicodedata.normalize("NFC", original)],
        ensure_ascii=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class WritingRequest:
    text: str
    text_version: int
    target_language: str
    source_text: str = ""
    glossary_terms: frozenset[str] = frozenset()
    session_ignored_words: frozenset[str] = frozenset()
    disabled_rule_ids: frozenset[str] = frozenset()
    grammar_enabled: bool = False

    def __post_init__(self) -> None:
        _version(self.text_version)
        if not all(isinstance(value, str) for value in (
            self.text, self.target_language, self.source_text,
        )):
            raise ValueError("request text and language must be strings")
        for name in ("glossary_terms", "session_ignored_words", "disabled_rule_ids"):
            value = frozenset(getattr(self, name))
            if not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must contain strings")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class WritingIssue:
    issue_id: str
    rule_id: str
    category: IssueCategory
    start: int
    end: int
    original: str
    message: str
    explanation: str
    suggestions: tuple[str, ...]
    severity: IssueSeverity
    provider: str
    text_version: int
    state: IssueState = "active"
    suggestions_state: SuggestionState = "complete"

    def __post_init__(self) -> None:
        _version(self.text_version)
        if self.category not in get_args(IssueCategory):
            raise ValueError("invalid issue category")
        if self.severity not in get_args(IssueSeverity):
            raise ValueError("invalid issue severity")
        if self.state not in get_args(IssueState):
            raise ValueError("invalid issue state")
        if self.suggestions_state not in get_args(SuggestionState):
            raise ValueError("invalid suggestions state")
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("issue offsets must be integer code-point indices")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("issue span must be non-empty and non-negative")
        if not isinstance(self.original, str) or len(self.original) != self.end - self.start:
            raise ValueError("original must match the issue span length")
        suggestions = tuple(self.suggestions)
        if not all(isinstance(item, str) for item in suggestions):
            raise ValueError("suggestions must contain strings")
        object.__setattr__(self, "suggestions", suggestions[:5])
        if not self.issue_id:
            object.__setattr__(self, "issue_id", make_issue_id(
                self.provider, self.rule_id, self.category,
                self.start, self.end, self.original,
            ))

    def validate_for(self, request: WritingRequest) -> None:
        """Reject stale occurrences and spans that do not match the real text."""
        if self.text_version != request.text_version:
            raise ValueError("issue text_version does not match request")
        if self.end > len(request.text) or request.text[self.start:self.end] != self.original:
            raise ValueError("issue span does not match request text")


@dataclass(frozen=True)
class WritingResult:
    text_version: int
    issues: tuple[WritingIssue, ...]
    mode: AssistantMode
    diagnostic: str = ""

    def __post_init__(self) -> None:
        _version(self.text_version)
        if self.mode not in get_args(AssistantMode):
            raise ValueError("invalid assistant mode")
        issues = tuple(self.issues)
        if any(not isinstance(item, WritingIssue) or item.text_version != self.text_version
               for item in issues):
            raise ValueError("result issues must share text_version")
        object.__setattr__(self, "issues", issues)

    def validate_for(self, request: WritingRequest) -> None:
        if self.text_version != request.text_version:
            raise ValueError("result text_version does not match request")
        for item in self.issues:
            item.validate_for(request)


@dataclass(frozen=True)
class AssistantStatus:
    state: AssistantState
    mode: AssistantMode
    diagnostic: str = ""
    restart_attempted: bool = False

    def __post_init__(self) -> None:
        if self.state not in get_args(AssistantState):
            raise ValueError("invalid assistant state")
        if self.mode not in get_args(AssistantMode):
            raise ValueError("invalid assistant mode")
