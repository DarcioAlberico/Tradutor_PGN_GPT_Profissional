"""Offline writing analysis independent of editors and provider internals.

Analysis belongs on a worker thread: the default loader shares the existing
per-process dictionary cache. UI callers can keep using request_dictionary's
asynchronous warm-up. No failure is presented as a successful empty analysis.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Protocol
import unicodedata

from . import prose_spellcheck
from .personal_dictionary import PersonalDictionary
from .writing_protection import ProtectedText, protect_text, restore_issue_offsets
from .writing_types import AssistantStatus, WritingIssue, WritingRequest, WritingResult


class SpellingUnavailable(RuntimeError):
    """A safe diagnostic for a provider that could not complete analysis."""


class PersonalVocabulary(Protocol):
    def list_words(self) -> list[str]: ...


class WritingAdapter(Protocol):
    def analyze(self, request: WritingRequest, protected: ProtectedText) -> tuple[WritingIssue, ...]: ...


def _key(word: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", word).casefold())


def _dictionary_language(language: str) -> str:
    normalized = language.strip().lower().replace("_", "-")
    return "pt" if normalized in {"pt", "pt-br"} else normalized


def _tokens(text: str) -> Iterator[tuple[int, int, str]]:
    """Historical word boundaries, including a word's Unicode combining marks.

    Keep original spans; only dictionary queries are normalized to NFC.
    """
    index = 0
    while index < len(text):
        if not text[index].isalnum():
            index += 1
            continue
        start = index
        index += 1
        while index < len(text):
            char = text[index]
            if char.isalnum() or unicodedata.category(char).startswith("M"):
                index += 1
            elif char in "-'’" and index + 1 < len(text) and text[index + 1].isalnum():
                index += 2
            else:
                break
        yield start, index, text[start:index]


class _NfcDictionary:
    def __init__(self, dictionary: prose_spellcheck.SpellingDictionary) -> None:
        self._dictionary = dictionary

    def lookup(self, word: str) -> bool:
        return self._dictionary.lookup(unicodedata.normalize("NFC", word))

    def suggest(self, word: str) -> Iterable[str]:
        return self._dictionary.suggest(unicodedata.normalize("NFC", word))


class SpyllsAdapter:
    """Adapt the measured spelling filter to actionable, versioned issues."""

    def __init__(
        self, *,
        dictionary_loader: Callable[[str], prose_spellcheck.SpellingDictionary | None] = prose_spellcheck.load_dictionary,
        personal_dictionary: PersonalVocabulary | None = None,
    ) -> None:
        self._load_dictionary = dictionary_loader
        self._personal_dictionary = personal_dictionary if personal_dictionary is not None else PersonalDictionary()

    def analyze(self, request: WritingRequest, protected: ProtectedText) -> tuple[WritingIssue, ...]:
        language = _dictionary_language(request.target_language)
        if language not in prose_spellcheck.DICTIONARY_NAMES:
            raise SpellingUnavailable("Ortografia indisponível: idioma sem dicionário local.")
        if protected.original_text != request.text or protected.text_version != request.text_version:
            raise SpellingUnavailable("Ortografia indisponível: projeção de texto divergente.")
        try:
            dictionary = self._load_dictionary(language)
        except Exception:
            raise SpellingUnavailable("Ortografia indisponível: falha ao carregar dicionário pt-BR.") from None
        if dictionary is None:
            raise SpellingUnavailable("Ortografia indisponível: dicionário pt-BR ausente.")
        dictionary = _NfcDictionary(dictionary)
        try:
            known = {_key(word) for word in self._personal_dictionary.list_words()}
        except Exception:
            raise SpellingUnavailable("Ortografia indisponível: falha ao ler vocabulário pessoal.") from None
        known.update(_key(word) for word in request.session_ignored_words)
        # Source and glossary phrases are already masked by protect_text.
        # Include their vocabulary to retain the historical multiword glossary
        # filter, which accepted each token on a replacement's right-hand side.
        known.update(_key(word) for word in prose_spellcheck.source_vocabulary(
            unicodedata.normalize("NFC", request.source_text)
        ))
        known.update(_key(word) for word in prose_spellcheck.glossary_vocabulary(
            ("", unicodedata.normalize("NFC", term)) for term in request.glossary_terms
        ))
        try:
            tokens = (token for token in _tokens(protected.projected_text) if _key(token[2]) not in known)
            candidates = prose_spellcheck.spelling_candidates(
                protected.projected_text, dictionary, tokens=tokens,
            )
            issues = []
            replacements: dict[str, tuple[str, ...]] = {}
            for start, end, original in candidates:
                if original not in replacements:
                    replacements[original] = prose_spellcheck.spelling_suggestions(original, dictionary)
                issues.append(WritingIssue(
                    issue_id="", rule_id="SPELLING_UNKNOWN_WORD", category="SPELLING",
                    start=start, end=end, original=original,
                    message="Palavra não reconhecida pelo dicionário pt-BR.",
                    explanation="Confira a grafia ou adicione a palavra ao vocabulário pessoal.",
                    suggestions=replacements[original], severity="error", provider="spylls",
                    text_version=request.text_version,
                ))
            return tuple(issues)
        except Exception:
            raise SpellingUnavailable("Ortografia indisponível: falha na consulta ao dicionário pt-BR.") from None


class PortugueseWritingAssistant:
    """Protect, validate and normalize provider results behind one small seam."""

    def __init__(
        self, *, spelling_adapter: WritingAdapter | None = None,
        protector: Callable[[WritingRequest], ProtectedText] = protect_text,
    ) -> None:
        self._spelling = spelling_adapter if spelling_adapter is not None else SpyllsAdapter()
        self._protect = protector
        self._status = AssistantStatus("stopped", "unavailable")

    def analyze(self, request: WritingRequest) -> WritingResult:
        try:
            protected = self._protect(request)
            candidates = self._spelling.analyze(request, protected)
        except SpellingUnavailable as error:
            return self._unavailable(request, str(error))
        except Exception:
            return self._unavailable(request, "Ortografia indisponível: falha no motor local.")
        issues: dict[tuple[object, ...], WritingIssue] = {}
        for candidate in candidates:
            if candidate.rule_id in request.disabled_rule_ids:
                continue
            issue = restore_issue_offsets(candidate, protected)
            if issue is None:
                continue
            issue.validate_for(request)
            key = (issue.start, issue.end, issue.category, issue.rule_id, issue.provider, issue.state)
            issues.setdefault(key, issue)
        ordered = tuple(sorted(issues.values(), key=lambda issue: (
            issue.start, issue.end, issue.category, issue.rule_id, issue.provider,
        )))
        diagnostic = "Concordância indisponível; somente ortografia." if request.grammar_enabled else ""
        self._status = AssistantStatus("ready", "spelling_only", diagnostic)
        return WritingResult(request.text_version, ordered, "spelling_only", diagnostic)

    def _unavailable(self, request: WritingRequest, diagnostic: str) -> WritingResult:
        self._status = AssistantStatus("failed", "unavailable", diagnostic)
        return WritingResult(request.text_version, (), "unavailable", diagnostic)

    def status(self) -> AssistantStatus:
        return self._status

    def shutdown(self) -> None:
        self._status = AssistantStatus("stopped", "unavailable")
