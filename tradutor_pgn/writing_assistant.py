"""Offline writing analysis independent of editors and provider internals.

Analysis belongs on a worker thread: the default loader shares the existing
per-process dictionary cache. UI callers can keep using request_dictionary's
asynchronous warm-up. No failure is presented as a successful empty analysis.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
import hashlib
import json
import threading
from typing import Protocol
import unicodedata

from . import prose_spellcheck
from .languagetool_client import EXPECTED_VERSION, LanguageToolLocalAdapter
from .personal_dictionary import PersonalDictionary
from .writing_protection import ProtectedText, protect_text, restore_issue_offsets
from .writing_types import AssistantMode, AssistantStatus, WritingIssue, WritingRequest, WritingResult


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


def _narrow_replacement_span(issue: WritingIssue) -> WritingIssue:
    """Remove only context shared byte-for-byte by every replacement.

    Changes remain whole Unicode words (including combining marks). Never
    choose one alternative's narrower span at the expense of another, or
    turn repetitions/punctuation into zero-width/deletion-only diagnostics.
    Protection and provider offsets must be checked before AND after this.
    """
    if (issue.category in {"SPELLING", "REPEATED_WORD", "PUNCTUATION"}
            or not issue.suggestions or issue.original in issue.suggestions):
        return issue
    original, suggestions = issue.original, issue.suggestions
    start, limit = 0, min(len(value) for value in (original, *suggestions))
    while start < limit and all(value[start] == original[start] for value in suggestions):
        start += 1
    suffix = 0
    while suffix < limit - start and all(value[-suffix - 1] == original[-suffix - 1] for value in suggestions):
        suffix += 1
    end = len(original) - suffix

    def word(char: str) -> bool:
        return char.isalnum() or unicodedata.category(char).startswith("M") or char in "_-'’"

    while start > 0 and word(original[start - 1]):
        start -= 1
    while end < len(original) and word(original[end]):
        end += 1
    suffix = len(original) - end
    replacements = tuple(value[start:len(value) - suffix] for value in suggestions)
    if (start >= end or not original[start:end].strip() or any(not value for value in replacements)
            or any(original[:start] + value + original[end:] != full
                   for value, full in zip(replacements, suggestions))):
        return issue
    return replace(issue, issue_id="", start=issue.start + start, end=issue.start + end,
                   original=original[start:end], suggestions=replacements)


def _agreement_alternatives(issue: WritingIssue) -> tuple[WritingIssue, int]:
    """Agreement cannot be repaired solely by changing punctuation.

    Keep punctuation when a replacement ALSO changes morphology. Compare
    exact Unicode code points after removing only punctuation/whitespace;
    symbols, accents and case remain significant. This is not rule-ID tuning.
    """
    if issue.category not in {"NOMINAL_AGREEMENT", "VERBAL_AGREEMENT"}:
        return issue, 0

    def content(value: str) -> str:
        return "".join(char for char in value if not char.isspace() and not unicodedata.category(char).startswith("P"))

    def punctuation(value: str) -> str:
        return "".join(char for char in value if unicodedata.category(char).startswith("P"))

    original_content, original_punctuation = content(issue.original), punctuation(issue.original)
    suggestions = tuple(value for value in issue.suggestions
                        if content(value) != original_content or punctuation(value) == original_punctuation)
    dropped = len(issue.suggestions) - len(suggestions)
    return (replace(issue, suggestions=suggestions) if dropped else issue), dropped


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

    @property
    def cache_revision(self) -> str:
        """Observe external vocabulary edits without retaining words in keys."""
        words = sorted({_key(word) for word in self._personal_dictionary.list_words()})
        return hashlib.sha256(json.dumps(["spylls-v1", words], ensure_ascii=True).encode("ascii")).hexdigest()

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
            # Masking can split a compound into new words (cor-de-rosa with
            # rosa protected becomes cor-de). Keep original token boundaries
            # and discard the whole token on any protected overlap.
            tokens = (
                token for token in _tokens(request.text)
                if _key(token[2]) not in known
                and not any(interval.start < token[1] and token[0] < interval.end
                            for interval in protected.ranges)
            )
            candidates = prose_spellcheck.spelling_candidates(
                request.text, dictionary, tokens=tokens,
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
        grammar_adapter: WritingAdapter | None = None,
        protector: Callable[[WritingRequest], ProtectedText] = protect_text,
        cache_capacity: int = 128,
    ) -> None:
        if type(cache_capacity) is not int or cache_capacity < 0:
            raise ValueError("cache_capacity must be a non-negative integer")
        self._spelling = spelling_adapter if spelling_adapter is not None else SpyllsAdapter()
        self._grammar = grammar_adapter if grammar_adapter is not None else LanguageToolLocalAdapter()
        self._protect = protector
        self._status = AssistantStatus("stopped", "unavailable")
        self._closed = False
        self._grammar_activity_lock = threading.Lock()
        self._active_grammar_checks = 0
        self._cache_lock = threading.RLock()
        self._cache: OrderedDict[tuple[int, str], WritingResult] = OrderedDict()
        self._cache_capacity = cache_capacity
        self._cache_epoch = 0
        self._normalization_counts: dict[str, int] = {}
        self._cache_revisions: dict[str, str | int] = {
            "glossary": 0, "vocabulary": 0, "rules": 0, "providers": 0,
        }

    def set_cache_revisions(self, **revisions: str | int) -> None:
        """Publish glossary/vocabulary/rules/providers revisions on settings edits.

        Request values also belong to the key. Revisions invalidate entries
        when a data source changes without changing that request's fields.
        """
        if any(name not in self._cache_revisions or type(value) not in {str, int}
               for name, value in revisions.items()):
            raise ValueError("invalid writing cache revision")
        with self._cache_lock:
            if any(self._cache_revisions[name] != value for name, value in revisions.items()):
                self._cache_revisions.update(revisions)
                self.invalidate_cache()

    def invalidate_cache(self) -> None:
        """Clear memory only; an old in-flight check cannot refill this epoch."""
        with self._cache_lock:
            self._cache_epoch += 1
            self._cache.clear()

    def normalization_counts(self) -> dict[str, int]:
        """Process-local aggregate diagnostics; no issue/text/offset retained."""
        with self._cache_lock:
            return self._normalization_counts.copy()

    def _cache_key(self, request: WritingRequest) -> tuple[int, str] | None:
        if not self._cache_capacity:
            return None
        try:
            provider_revisions = [
                [type(adapter).__module__, type(adapter).__qualname__,
                 str(getattr(adapter, "cache_revision", "v1"))]
                for adapter in (self._spelling, self._grammar)
            ]
        except Exception:
            # A vocabulary read error must reach normal analysis and produce
            # its visible unavailable result, never reuse an earlier success.
            return None
        with self._cache_lock:
            epoch, revisions = self._cache_epoch, self._cache_revisions.copy()
        payload = [
            "writing-v1", EXPECTED_VERSION, provider_revisions, revisions,
            request.text, request.target_language, request.source_text,
            sorted(request.glossary_terms), sorted(request.session_ignored_words),
            sorted(request.disabled_rule_ids), request.grammar_enabled,
        ]
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True).encode("ascii")).hexdigest()
        return epoch, digest

    def analyze(self, request: WritingRequest) -> WritingResult:
        with self._cache_lock:
            if self._closed:
                return WritingResult(request.text_version, (), "unavailable", "Assistente de escrita encerrado.")
        key = self._cache_key(request)
        with self._cache_lock:
            cached = self._cache.get(key) if key is not None else None
            if cached is not None and key is not None and not self._closed:
                grammar_status = self._grammar_status() if request.grammar_enabled else None
                # A cached full response cannot hide a later sidecar failure.
                if grammar_status is None or grammar_status.mode == "full":
                    self._cache.move_to_end(key)
                    result = replace(cached, text_version=request.text_version, issues=tuple(
                        replace(issue, text_version=request.text_version) for issue in cached.issues
                    ))
                    self._status = AssistantStatus("ready", result.mode, result.diagnostic,
                                                   grammar_status.restart_attempted if grammar_status else False)
                    return result
        result = self._analyze_uncached(request)
        current_key = self._cache_key(request) if key is not None else None
        with self._cache_lock:
            if self._closed:
                return WritingResult(request.text_version, (), "unavailable", "Assistente de escrita encerrado.")
            if (key is not None and key == current_key and result.mode != "unavailable"
                    and not result.diagnostic):
                self._cache[key] = result
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_capacity:
                    self._cache.popitem(last=False)
        return result

    def _analyze_uncached(self, request: WritingRequest) -> WritingResult:
        if self._closed:
            return self._unavailable(request, "Assistente de escrita encerrado.")
        try:
            protected = self._protect(request)
            candidates = self._spelling.analyze(request, protected)
        except SpellingUnavailable as error:
            return self._unavailable(request, str(error))
        except Exception:
            return self._unavailable(request, "Ortografia indisponível: falha no motor local.")
        with self._cache_lock:
            if self._closed:
                return self._unavailable(request, "Assistente de escrita encerrado.")
        mode: AssistantMode = "spelling_only"
        diagnostic = ""
        if request.grammar_enabled:
            with self._grammar_activity_lock:
                self._active_grammar_checks += 1
            try:
                # The spelling adapter alone applies the complete personal,
                # session and dictionary acceptance policy. Grammar must not
                # reintroduce typos that that policy already accepted.
                candidates += tuple(issue for issue in self._grammar.analyze(request, protected)
                                    if issue.category != "SPELLING")
                mode = "full"
            except Exception:
                # Provider exceptions can contain the complete request/response.
                # Preserve spelling and use only this fixed local diagnostic.
                diagnostic = "Concordância indisponível; somente ortografia."
            finally:
                with self._grammar_activity_lock:
                    self._active_grammar_checks -= 1
        issues: dict[tuple[object, ...], WritingIssue] = {}
        for candidate in candidates:
            if candidate.rule_id in request.disabled_rule_ids:
                continue
            issue = restore_issue_offsets(candidate, protected)
            if issue is None:
                continue
            if issue.state == "active":
                # Reject the provider's complete protected/stale span first;
                # trimming must never rescue an unsafe diagnostic. Restore
                # again from projection coordinates after narrowing.
                candidate, dropped = _agreement_alternatives(candidate)
                if dropped:
                    with self._cache_lock:
                        self._normalization_counts[candidate.category] = self._normalization_counts.get(candidate.category, 0) + dropped
                issue = restore_issue_offsets(_narrow_replacement_span(candidate), protected)
                if issue is None:
                    continue
            issue.validate_for(request)
            # Collapse repeated spelling spans; keep distinct grammar reasons.
            key = ((issue.start, issue.end, issue.category, issue.state) if issue.category == "SPELLING"
                   else (issue.start, issue.end, issue.category, issue.rule_id, issue.provider, issue.state))
            issues.setdefault(key, issue)
        ordered = tuple(sorted(issues.values(), key=lambda issue: (
            issue.start, issue.end, issue.category, issue.rule_id, issue.provider,
        )))
        grammar_status = self._grammar_status() if request.grammar_enabled else None
        with self._cache_lock:
            if not self._closed:
                self._status = AssistantStatus("ready", mode, diagnostic,
                                               grammar_status.restart_attempted if grammar_status else False)
        return WritingResult(request.text_version, ordered, mode, diagnostic)

    def _unavailable(self, request: WritingRequest, diagnostic: str) -> WritingResult:
        with self._cache_lock:
            if not self._closed:
                self._status = AssistantStatus("failed", "unavailable", diagnostic)
        return WritingResult(request.text_version, (), "unavailable", diagnostic)

    def status(self) -> AssistantStatus:
        with self._cache_lock:
            if self._closed:
                return AssistantStatus("stopped", "unavailable")
            with self._grammar_activity_lock:
                grammar_active = self._active_grammar_checks > 0
            if grammar_active or self._status.mode == "full":
                grammar_status = self._grammar_status()
                if grammar_status is not None:
                    if grammar_active and grammar_status.state in {"starting", "restarting"}:
                        return AssistantStatus(grammar_status.state, "spelling_only", grammar_status.diagnostic,
                                               grammar_status.restart_attempted)
                    if self._status.mode == "full" and grammar_status.mode != "full":
                        self._status = AssistantStatus(grammar_status.state, "spelling_only",
                                                       "Concordância indisponível; somente ortografia.",
                                                       grammar_status.restart_attempted)
            return self._status

    def _grammar_status(self) -> AssistantStatus | None:
        status = getattr(self._grammar, "status", None)
        return status() if callable(status) else None

    def shutdown(self) -> None:
        with self._cache_lock:
            if self._closed:
                return
            self._closed = True
            self.invalidate_cache()
            self._status = AssistantStatus("stopped", "unavailable")
        shutdown = getattr(self._grammar, "shutdown", None)
        if callable(shutdown):
            shutdown()
