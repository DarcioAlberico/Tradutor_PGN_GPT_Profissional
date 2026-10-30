"""Replay the reviewed synthetic corpus locally; reports never contain payload.

Run from source: uv run python ferramentas/avaliar_corretor_portugues.py --mode full
The real runtime in build/vendor is diagnostic only: no release gate is bypassed.
"""

from collections.abc import Callable, Sequence
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any, Protocol, get_args

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradutor_pgn.languagetool_client import EXPECTED_VERSION  # noqa: E402
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpyllsAdapter  # noqa: E402
from tradutor_pgn.writing_protection import protect_text  # noqa: E402
from tradutor_pgn.writing_types import IssueCategory, WritingIssue, WritingRequest, WritingResult  # noqa: E402

DEFAULT_CORPUS = ROOT / "tests/fixtures/portuguese_writing_corpus.json"


class Assistant(Protocol):
    def analyze(self, request: WritingRequest) -> WritingResult: ...


class _EmptyVocabulary:
    def list_words(self) -> list[str]:
        return []


def create_assistant() -> PortugueseWritingAssistant:
    """Reproducible baselines ignore user preferences and personal vocabulary."""
    return PortugueseWritingAssistant(
        spelling_adapter=SpyllsAdapter(personal_dictionary=_EmptyVocabulary()), cache_capacity=0,
    )


def _request(case: dict[str, Any], mode: str) -> WritingRequest:
    return WritingRequest(case["text"], 1, "pt-BR", source_text=case.get("source_text", ""),
                          glossary_terms=frozenset(case.get("glossary_terms", ())), grammar_enabled=mode == "full")


def _counts(expected: int, presented: int, true_positives: int) -> dict[str, Any]:
    return {"expected": expected, "presented": presented, "true_positives": true_positives,
            "false_positives": presented - true_positives, "misses": expected - true_positives,
            "precision": true_positives / presented if presented else None,
            "recall": true_positives / expected if expected else None}


def _matches(issue: WritingIssue, gold: dict[str, Any]) -> bool:
    return (issue.start == gold["start"] and issue.end == gold["end"]
            and issue.original == gold["original"] and issue.category == gold["category"]
            and bool(set(issue.suggestions).intersection(gold["suggestions"])))


def evaluate_corpus(corpus: dict[str, Any], assistant: Assistant, *, mode: str) -> dict[str, Any]:
    """Strict one-to-one gold matches, including at least one editorial correction.

    An incorrect correction is both a false positive and a miss. Duplicate
    diagnostics cannot inflate recall. Unavailable/fallback requests stay in
    denominators and are separately reported. Suppressed issues are not errors
    presented to users. Reports list only case IDs, rule IDs and aggregates.
    """
    if mode not in {"spelling", "full"} or corpus.get("schema_version") != 1:
        raise ValueError("unsupported evaluation mode or corpus schema")
    categories = get_args(IssueCategory)
    totals = {category: [0, 0, 0] for category in categories}
    cases: list[dict[str, Any]] = []
    protected_violations = failed_cases = spelling_expected = spelling_with_suggestions = 0
    seen: set[str] = set()
    normalization_counts: Callable[[], dict[str, int]] = getattr(assistant, "normalization_counts", lambda: {})
    normalization_before = normalization_counts()
    for case in corpus["cases"]:
        case_id = case["id"]
        if not isinstance(case_id, str) or case_id in seen:
            raise ValueError("corpus IDs must be unique strings")
        seen.add(case_id)
        request = _request(case, mode)
        gold = [item for item in case["expected_issues"] if mode == "full" or item["category"] == "SPELLING"]
        for item in gold:
            if request.text[item["start"]:item["end"]] != item["original"]:
                raise ValueError("invalid corpus gold span")
            totals[item["category"]][0] += 1
        failed = False
        try:
            result = assistant.analyze(request)
            result.validate_for(request)
            failed = result.mode != ("full" if mode == "full" else "spelling_only") or bool(result.diagnostic)
            issues = [issue for issue in result.issues if issue.state == "active"]
        except Exception:
            # Exceptions may contain user text. Never serialize/log them.
            issues, failed = [], True
        failed_cases += int(failed)
        protected = protect_text(request)
        forbidden = [(item["start"], item["end"]) for item in case.get("forbidden_ranges", ())]
        forbidden.extend((item.start, item.end) for item in protected.ranges)
        remaining = list(gold)
        false_rules, true_rules = [], []
        violations = 0
        for issue in issues:
            totals[issue.category][1] += 1
            unsafe = any(start < issue.end and issue.start < end for start, end in forbidden)
            violations += int(unsafe)
            match = next((item for item in remaining if _matches(issue, item)), None) if not unsafe else None
            if match is None:
                false_rules.append(issue.rule_id)
            else:
                remaining.remove(match)
                totals[issue.category][2] += 1
                true_rules.append(issue.rule_id)
        for item in gold:
            if item["category"] == "SPELLING":
                spelling_expected += 1
                spelling_with_suggestions += int(any(
                    issue.category == "SPELLING" and issue.start == item["start"] and issue.end == item["end"]
                    and issue.suggestions for issue in issues
                ))
        protected_violations += violations
        cases.append({"id": case_id, "expected": len(gold), "presented": len(issues),
                      "true_positive_rule_ids": sorted(true_rules), "false_positive_rule_ids": sorted(false_rules),
                      "missed_categories": sorted(item["category"] for item in remaining),
                      "protected_violations": violations, "failed": failed})
    by_category = {category: _counts(*values) for category, values in totals.items()}
    overall = _counts(*(sum(values[index] for values in totals.values()) for index in range(3)))
    coverage = spelling_with_suggestions / spelling_expected if spelling_expected else None
    ta004 = next((case for case in cases if case["id"] == "TA-004"), None)
    acceptance = bool(mode == "full" and ta004 and not ta004["missed_categories"]
                      and not ta004["false_positive_rule_ids"] and not ta004["failed"])
    stable = bool(mode == "full" and overall["precision"] is not None and overall["precision"] >= .95
                  and overall["recall"] is not None and overall["recall"] >= .80
                  and coverage is not None and coverage >= .95
                  and protected_violations == 0 and failed_cases == 0 and acceptance)
    discarded = {category: count - normalization_before.get(category, 0)
                 for category, count in normalization_counts().items()
                 if count > normalization_before.get(category, 0)}
    return {"schema_version": 1, "mode": mode, "case_count": len(cases), "overall": overall,
            "by_category": by_category, "protected_violations": protected_violations, "failed_cases": failed_cases,
            "spelling_suggestions": {"expected": spelling_expected, "with_suggestions": spelling_with_suggestions,
                                     "coverage": coverage},
            "discarded_punctuation_only_agreement_alternatives": discarded,
            "gate": {"precision_minimum": .95, "recall_minimum": .80, "spelling_suggestions_minimum": .95,
                     "ta004_literal": acceptance, "stable": stable, "grammar_enabled_default": False}, "cases": cases}


def percentile95(values: Sequence[float]) -> float:
    """Nearest rank: with n < 20 this is the maximum; no population inference."""
    if not values:
        raise ValueError("percentile requires samples")
    return sorted(values)[math.ceil(.95 * len(values)) - 1]


def benchmark_assistant(corpus: dict[str, Any], assistant: Assistant, *, mode: str, repeats: int) -> dict[str, Any]:
    """Cache-disabled caller; sizes are 1, 10 and 50 lines in one comment."""
    if repeats < 1:
        raise ValueError("benchmark repeats must be positive")
    reports: dict[str, Any] = {}
    for label, lines in (("small", 1), ("medium", 10), ("large", 50)):
        samples: list[float] = []
        failures = 0
        # Include correct/ambiguous text, typos, Unicode, grammar and protection
        # in each size. Repeating the same request still invokes providers.
        for _ in range(repeats):
            for case in corpus["cases"]:
                request = _request({**case, "text": "\n".join([case["text"]] * lines)}, mode)
                started = time.perf_counter()
                try:
                    result = assistant.analyze(request)
                    failures += int(result.mode != ("full" if mode == "full" else "spelling_only") or bool(result.diagnostic))
                except Exception:
                    failures += 1
                samples.append((time.perf_counter() - started) * 1000)
        p95 = percentile95(samples)
        reports[label] = {"samples": len(samples), "lines_per_comment": lines, "failed": failures,
                          "p95_ms_per_comment": p95, "p95_ms_per_line": p95 / lines,
                          "target_met": failures == 0 and (p95 / lines <= 20 if mode == "spelling" else p95 <= 500)}
    return {"method": "nearest_rank", "cache_capacity": 0, "repeats": repeats, "sizes": reports,
            "platform": platform.system(), "python": platform.python_version(),
            "note": "Warm local samples; OS disk cache retained. Machine report, not a CI latency gate."}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Portuguese writing baseline: {report['mode']}", "",
             "Strict spans/categories and at least one gold correction; no text, suggestions or offsets exported.", "",
             "| Category | Expected | Presented | TP | FP | Misses | Precision | Recall |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for category, counts in [("overall", report["overall"]), *report["by_category"].items()]:
        cells = [str(counts[key]) if counts[key] is not None else "n/a" for key in
                 ("expected", "presented", "true_positives", "false_positives", "misses", "precision", "recall")]
        lines.append("| " + " | ".join([category, *cells]) + " |")
    lines.extend(["", f"Protected violations: {report['protected_violations']}; failed cases: {report['failed_cases']}.",
                  f"Linguistic gate stable: {report['gate']['stable']}; TA-004 literal: {report['gate']['ta004_literal']}.",
                  "Discarded punctuation-only agreement alternatives by category: "
                  + json.dumps(report["discarded_punctuation_only_agreement_alternatives"]) + ".",
                  "Concordance remains experimental; default false. Release/licensing gates are independent.", "",
                  "Case details (IDs only):", "", "```json", json.dumps(report["cases"], indent=2), "```", ""])
    if "benchmark" in report:
        lines.extend(["Machine benchmarks (nearest-rank p95, warm, no assistant cache):", "", "```json",
                      json.dumps(report["benchmark"], indent=2), "```", ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("spelling", "full"), required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/reports")
    parser.add_argument("--benchmark-repeats", type=int, default=0)
    args = parser.parse_args(argv)
    raw = args.corpus.read_bytes()
    corpus = json.loads(raw)
    assistant = create_assistant()
    try:
        report = evaluate_corpus(corpus, assistant, mode=args.mode)
        report["corpus_sha256"] = hashlib.sha256(raw).hexdigest()
        report["providers"] = {"spelling": "Spylls/VERO", "grammar": EXPECTED_VERSION if args.mode == "full" else None}
        if args.benchmark_repeats:
            report["benchmark"] = benchmark_assistant(corpus, assistant, mode=args.mode, repeats=args.benchmark_repeats)
    finally:
        assistant.shutdown()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / f"portuguese-writing-{args.mode}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"mode": args.mode, "overall": report["overall"], "gate": report["gate"],
                      "protected_violations": report["protected_violations"], "failed_cases": report["failed_cases"]}))
    # A completed experimental baseline is useful even below quality targets;
    # inability to run a provider is a failing replay, never silent success.
    benchmark_failed = any(size["failed"] for size in report.get("benchmark", {}).get("sizes", {}).values())
    return 1 if report["failed_cases"] or benchmark_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
