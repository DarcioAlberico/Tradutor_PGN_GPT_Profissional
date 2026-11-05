"""Local spelling-stage measurements; JSON contains only IDs and aggregates.

uv run python ferramentas/medir_sugestoes_progressivas.py --include-baseline
Neither initial detections nor bounded prefixes are a linguistic release gate.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import statistics
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferramentas.avaliar_corretor_portugues import (  # noqa: E402
    DEFAULT_CORPUS, _request, benchmark_assistant, create_assistant, percentile95,
)
from tradutor_pgn.prose_spellcheck import load_dictionary  # noqa: E402
from tradutor_pgn.spelling_suggestions_process import SpellingSuggestionService, SuggestionSnapshot  # noqa: E402
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant  # noqa: E402
from tradutor_pgn.writing_types import WritingRequest, WritingResult  # noqa: E402


class _Initial:
    def __init__(self, assistant: PortugueseWritingAssistant) -> None:
        self.assistant = assistant

    def analyze(self, request: WritingRequest) -> WritingResult:
        return self.assistant.analyze_initial(request)


def measure(*, repeats: int, include_baseline: bool, budget_ms: float = 3000) -> dict[str, Any]:
    payload = DEFAULT_CORPUS.read_bytes()
    corpus = json.loads(payload)
    dictionary = load_dictionary("pt")
    if dictionary is None:
        raise RuntimeError("dictionary unavailable")
    assistant = create_assistant()
    process = SpellingSuggestionService(suggestion_timeout=budget_ms / 1000)
    report: dict[str, Any] = {
        "corpus_sha256": hashlib.sha256(payload).hexdigest(), "repeats": repeats,
        "suggestion_cpu_budget_ms": budget_ms, "startup_budget_ms": 10000,
        "maximum_children": 1, "maximum_pending": 8, "maximum_token_codepoints": 128,
    }
    try:
        if include_baseline:
            report["legacy_complete"] = benchmark_assistant(corpus, assistant, mode="spelling", repeats=repeats)
        initial = benchmark_assistant(corpus, _Initial(assistant), mode="spelling", repeats=repeats)
        for size in initial["sizes"].values():
            del size["target_met"]
        report["initial_detection_stage_only"] = initial
        rows = []
        selected = [(case["id"], item.original) for case in corpus["cases"]
                    for item in assistant.analyze_initial(_request(case, "spelling")).issues
                    if item.category == "SPELLING"]
        # The same first yield, direct vs a warm single thread, isolates the
        # scheduling overhead without exploring the known expensive tail.
        direct, threaded = [], []
        with ThreadPoolExecutor(max_workers=1) as executor:
            for _ in range(repeats):
                for _, word in selected:
                    started = time.perf_counter()
                    next(iter(dictionary.suggest(word)), None)
                    direct.append((time.perf_counter() - started) * 1000)
                    started = time.perf_counter()
                    executor.submit(next, iter(dictionary.suggest(word)), None).result()
                    threaded.append((time.perf_counter() - started) * 1000)
        report["in_process_first_yield"] = {
            "samples": len(direct), "direct_p95_ms": percentile95(direct),
            "thread_p95_ms": percentile95(threaded), "thread_cancellation_is_hard_bound": False,
        }

        def sample(case_id: str, word: str) -> dict[str, Any]:
            done = threading.Event()
            first: list[float] = []
            final: list[SuggestionSnapshot] = []
            warm = process._process is not None and process._process.is_alive()
            started = time.perf_counter()

            def receive(snapshot: SuggestionSnapshot) -> None:
                if snapshot.suggestions and not first:
                    first.append((time.perf_counter() - started) * 1000)
                if snapshot.state not in {"loading", "pending", "partial"}:
                    final.append(snapshot)
                    done.set()

            process.submit("measurement", word, receive)
            if not done.wait(15):
                raise RuntimeError("bounded sample did not finish")
            return {"case_id": case_id, "warm_child_at_submit": warm,
                    "first_option_ms": first[0] if first else None,
                    "terminal_ms": (time.perf_counter() - started) * 1000,
                    "terminal_state": final[-1].state, "option_count": len(final[-1].suggestions)}

        # This reviewed typo has five quick suggestions: the next sample can
        # measure a reused, dictionary-warm child as well as cold replacements.
        report["process_cold_warmup"] = sample("spelling-accent-warmup", "peao")
        for _ in range(repeats):
            for case_id, word in selected:
                rows.append(sample(case_id, word))
        report["bounded_process_samples"] = rows
        report["bounded_process_summary"] = {
            "samples": len(rows), "with_first": sum(row["first_option_ms"] is not None for row in rows),
            "first_option_p95_ms": percentile95([row["first_option_ms"] for row in rows
                                                if row["first_option_ms"] is not None]),
            "terminal_p95_ms": percentile95([row["terminal_ms"] for row in rows]),
            "timeouts": sum(row["terminal_state"] == "timed_out" for row in rows),
            "first_option_with_initial_startup_p95_ms": percentile95([
                report["process_cold_warmup"]["first_option_ms"],
                *[row["first_option_ms"] for row in rows if row["first_option_ms"] is not None],
            ]),
        }
        for warm in (False, True):
            values = [row["first_option_ms"] for row in rows if row["first_option_ms"] is not None
                      and row["warm_child_at_submit"] is warm]
            report["bounded_process_summary"]["warm" if warm else "cold"] = {
                "samples": len(values), "min_ms": min(values) if values else None,
                "median_ms": statistics.median(values) if values else None,
                "max_ms": max(values) if values else None,
                "p95_ms": percentile95(values) if values else None,
            }
        by_id = dict(selected)
        started = time.perf_counter()
        first_ready, finished = threading.Event(), threading.Event()
        pair: dict[str, dict[str, Any]] = {owner: {} for owner in ("one", "two")}
        resources = {"peak_children": 0, "peak_pending": 0}

        def observer(owner: str, snapshot: SuggestionSnapshot) -> None:
            elapsed = (time.perf_counter() - started) * 1000
            resources["peak_children"] = max(resources["peak_children"], len(multiprocessing.active_children()))
            if snapshot.suggestions:
                pair[owner].setdefault("first_option_ms", elapsed)
                if owner == "one":
                    first_ready.set()
            if snapshot.state not in {"loading", "partial", "pending"}:
                pair[owner].update(terminal_ms=elapsed, terminal_state=snapshot.state,
                                   option_count=len(snapshot.suggestions))
                if all("terminal_state" in row for row in pair.values()):
                    finished.set()

        process.submit("one", by_id["TA-004"], lambda snapshot: observer("one", snapshot))
        if not first_ready.wait(12):
            raise RuntimeError("missing first window prefix")
        second_submitted_ms = (time.perf_counter() - started) * 1000
        for _ in range(30):
            process.submit("two", by_id["spelling-accent"], lambda snapshot: observer("two", snapshot))
            resources["peak_pending"] = max(resources["peak_pending"], len(process._pending))
        if not finished.wait(15):
            raise RuntimeError("two-window sequence did not finish")
        pair["two"]["first_option_after_submit_ms"] = pair["two"]["first_option_ms"] - second_submitted_ms
        report["two_window_fifo_burst"] = {"owners": pair, "second_owner_submissions": 30, **resources}
        return report
    finally:
        process.shutdown()
        process._thread.join(3)
        assistant.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-baseline", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--budget-ms", type=float, default=3000)
    parser.add_argument("--output", type=Path, default=ROOT / "build/reports/spelling-progressive.json")
    args = parser.parse_args()
    try:
        if args.repeats < 1:
            raise ValueError("positive repeats required")
        report = measure(repeats=args.repeats, include_baseline=args.include_baseline, budget_ms=args.budget_ms)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 0
    except Exception:
        print(json.dumps({"failed": True, "diagnostic": "progressive_measurement_failed_no_payload"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
