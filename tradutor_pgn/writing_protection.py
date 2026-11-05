"""Protect domain text with a length-preserving, code-point projection.

``index_map[i]`` maps a projection boundary to an original-text boundary,
including the final boundary. Masking currently preserves every code point, so
the map is the identity. Providers using UTF-16 must convert to code points
before constructing issues. A masked interval never becomes an editable issue.
"""

from dataclasses import dataclass, replace
import re
from typing import Literal
import unicodedata

from .annotation_mask import COMMAND_TAG_RE, PLAYER_PAIR_RE
from .chess_notation import _all_known_letters, _move_pattern
from .glossary_types import normalize_glossary_text
from .prose_spellcheck import NOTATION_RE, TOKEN_RE, source_vocabulary
from .writing_types import WritingIssue, WritingRequest


ProtectionKind = Literal[
    "annotation", "notation", "move_number", "nag", "url", "email",
    "identifier", "source_name", "glossary",
]


@dataclass(frozen=True, order=True)
class ProtectedRange:
    start: int
    end: int
    kind: ProtectionKind


@dataclass(frozen=True)
class ProtectedText:
    original_text: str
    projected_text: str
    index_map: tuple[int, ...]
    ranges: tuple[ProtectedRange, ...]
    text_version: int


_MOVES = _move_pattern(_all_known_letters())
_CASTLING = re.compile(r"(?<!\w)(?:O-O(?:-O)?|0-0(?:-0)?)[+#]?(?!\w)")
_MOVE_NUMBER = re.compile(r"(?<!\w)\d+\.(?:\.\.)?")
_NAG = re.compile(r"\$\d+|(?<![\w!?])[!?]{1,2}(?![!?])|[±∓∞⩲⩱]")
_URL = re.compile(
    r"(?:https?://|ftp://|www\.)(?:\[[^\s<>\[\]{}\"]+\]|[^\s<>\[\]{}\"])+",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_IDENTIFIER = re.compile(r"(?<!\w)\w+(?:_\w+)+(?!\w)", re.UNICODE)


def _normalized_projection(text: str) -> tuple[str, list[int], list[int]]:
    """Normalize for matching only, remembering each source cluster's extent.

    A base plus its combining marks can shrink under NFC, and casefold can
    expand a character (ß → ss). Neither operation changes the displayed text.
    """
    chunks: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    start = 0
    while start < len(text):
        end = start + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        value = unicodedata.normalize("NFC", text[start:end]).casefold()
        chunks.append(value)
        starts.extend([start] * len(value))
        ends.extend([end] * len(value))
        start = end
    return "".join(chunks), starts, ends


def _word_character(char: str) -> bool:
    return char.isalnum() or char == "_" or unicodedata.category(char).startswith("M")


def _term_ranges(
    text: str, terms: frozenset[str], kind: ProtectionKind,
) -> list[ProtectedRange]:
    normalized, starts, ends = _normalized_projection(text)
    found = []
    for term in sorted(terms):
        needle = unicodedata.normalize("NFC", normalize_glossary_text(term)).casefold()
        if not needle:
            continue
        position = 0
        while (position := normalized.find(needle, position)) >= 0:
            end = position + len(needle)
            # Do not select a portion of a Unicode expansion or of a word.
            complete_clusters = (
                (position == 0 or starts[position - 1] != starts[position])
                and (end == len(normalized) or ends[end - 1] != ends[end])
            )
            left = position == 0 or not (_word_character(needle[0])
                                       and _word_character(normalized[position - 1]))
            right = end == len(normalized) or not (_word_character(needle[-1])
                                                 and _word_character(normalized[end]))
            if complete_clusters and left and right:
                found.append(ProtectedRange(starts[position], ends[end - 1], kind))
            position += 1
    return found


def protect_text(request: WritingRequest) -> ProtectedText:
    """Mask notation, technical fragments, source vocabulary and glossary phrases.

    Source vocabulary uses the existing spelling filter without capitalization
    heuristics, preserving names and shared tokens accepted by that filter.
    Its intervals retain the ``source_name`` kind for compatibility.
    Overlapping typed ranges are retained so glossary diagnostics cannot bypass
    simultaneous technical protection.
    """
    text = request.text
    ranges = []
    patterns: tuple[tuple[re.Pattern[str], ProtectionKind], ...] = (
        (COMMAND_TAG_RE, "annotation"), (_MOVES, "notation"),
        (_CASTLING, "notation"), (_MOVE_NUMBER, "move_number"), (_NAG, "nag"),
        (_URL, "url"), (_EMAIL, "email"), (_IDENTIFIER, "identifier"),
        (PLAYER_PAIR_RE, "source_name"),
    )
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if kind == "url":
                # IPv6 brackets and internal apostrophes belong to the URL;
                # surrounding prose punctuation and quotes do not.
                address = match.group().rstrip(".,;:!?")
                while address.endswith(")") and address.count(")") > address.count("("):
                    address = address[:-1].rstrip(".,;:!?")
                if text[start - 1:start] == "'" and address.endswith("'"):
                    address = address[:-1]
                end = start + len(address)
            ranges.append(ProtectedRange(start, end, kind))
            if kind == "notation":
                suffix = re.match(r"[!?]{1,2}", text[end:])
                if suffix:
                    ranges.append(ProtectedRange(end, end + suffix.end(), "nag"))
    for match in TOKEN_RE.finditer(text):
        if NOTATION_RE.fullmatch(match.group()):
            ranges.append(ProtectedRange(*match.span(), "notation"))
    source = unicodedata.normalize("NFC", request.source_text)
    vocabulary = frozenset(source_vocabulary(source))
    ranges.extend(_term_ranges(text, vocabulary, "source_name"))
    ranges.extend(_term_ranges(text, request.glossary_terms, "glossary"))
    ordered = tuple(sorted(set(ranges)))
    projected = list(text)
    for interval in ordered:
        for index in range(interval.start, interval.end):
            if projected[index] not in "\r\n":
                projected[index] = " "
    return ProtectedText(text, "".join(projected), tuple(range(len(text) + 1)),
                         ordered, request.text_version)


def restore_issue_offsets(issue: WritingIssue, protected: ProtectedText) -> WritingIssue | None:
    """Map a provider issue to real text, discarding stale/protected spans.

    An exact grammatical match on a glossary phrase is retained only as a
    diagnostic with ``suppressed_by_glossary``. All other protected overlaps,
    including partial/crossing glossary overlaps, are discarded.
    """
    if issue.text_version != protected.text_version:
        return None
    if issue.end > len(protected.projected_text):
        return None
    if protected.projected_text[issue.start:issue.end] != issue.original:
        return None
    start, end = protected.index_map[issue.start], protected.index_map[issue.end]
    overlaps = [interval for interval in protected.ranges
                if interval.start < end and start < interval.end]
    state = issue.state
    if overlaps:
        if issue.category == "SPELLING" or any(
            interval.kind != "glossary" or interval.start != start or interval.end != end
            for interval in overlaps
        ):
            return None
        state = "suppressed_by_glossary"
    return replace(issue, issue_id="", start=start, end=end,
                   original=protected.original_text[start:end], state=state)
