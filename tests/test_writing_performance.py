"""Loose CI regression ceilings; actual machine p95s belong in replay reports."""

from dataclasses import replace
import json
import threading
import time

import pytest

from gui_harness import GuiTestCase
from ferramentas.avaliar_corretor_portugues import benchmark_assistant, create_assistant, percentile95
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant
from tradutor_pgn.writing_controller import WritingController
from tradutor_pgn.writing_types import WritingRequest, WritingResult


def test_machine_percentile_uses_nearest_rank_and_rejects_empty_samples():
    assert percentile95(list(range(1, 21))) == 19
    assert percentile95([2, 9, 3]) == 9
    with pytest.raises(ValueError):
        percentile95([])


def test_benchmark_separates_sizes_per_line_and_comment_and_counts_failures(monkeypatch):
    from ferramentas import avaliar_corretor_portugues as evaluator

    clock = iter([0, .01, 1, 1.10, 2, 2.80])
    monkeypatch.setattr(evaluator.time, "perf_counter", lambda: next(clock))
    lines = []

    class Service:
        def analyze(self, request):
            lines.append(request.text.count("\n") + 1)
            return WritingResult(request.text_version, (), "full" if len(lines) < 3 else "spelling_only")

    corpus = {"cases": [{"id": "one", "text": "Uma posição.", "expected_issues": []}]}
    report = benchmark_assistant(corpus, Service(), mode="full", repeats=1)
    assert lines == [1, 10, 50]
    assert report["sizes"]["small"]["p95_ms_per_comment"] == 10
    assert report["sizes"]["medium"]["p95_ms_per_line"] == pytest.approx(10)
    assert report["sizes"]["large"]["failed"] == 1
    assert report["sizes"]["large"]["target_met"] is False
    assert "Uma posição" not in json.dumps(report)


def test_real_warm_spelling_has_loose_catastrophic_regression_ceiling():
    assistant = create_assistant()
    request = WritingRequest("As pretas têm uma posição ativa depois de 13.Cd4.", 1, "pt-BR")
    try:
        assert assistant.analyze(request).mode == "spelling_only"  # dictionary warm-up excluded
        durations = []
        for version in range(2, 12):
            started = time.perf_counter()
            result = assistant.analyze(replace(request, text_version=version))
            durations.append((time.perf_counter() - started) * 1000)
            assert not result.issues
        # Product target is 20ms; CI merely detects a catastrophic regression.
        assert percentile95(durations) < 2000
    finally:
        assistant.shutdown()


def test_large_batch_reuses_only_bounded_cached_results():
    class Counting:
        def __init__(self):
            self.calls = 0

        def analyze(self, request, protected):
            self.calls += 1
            return ()

    provider = Counting()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider, cache_capacity=4)
    try:
        requests = [WritingRequest(f"linha {index}", index, "pt") for index in range(80)]
        for request in requests:
            assistant.analyze(request)
        for request in requests[-4:]:
            assistant.analyze(request)
        assert provider.calls == 80
        assistant.analyze(requests[0])
        assert provider.calls == 81  # oldest result evicted; no corpus-sized cache
    finally:
        assistant.shutdown()


class BackgroundAnalysisTests(GuiTestCase):
    def test_cpu_bound_first_suggestion_is_isolated_from_real_tk_heartbeat(self):
        from test_spelling_suggestions_process import controlled_worker
        from tradutor_pgn.spelling_suggestions_process import SpellingSuggestionService
        from tradutor_pgn.writing_assistant import SpyllsAdapter

        class Dictionary:
            def lookup(self, word):
                return False

            def suggest(self, word):
                raise AssertionError("suggestions must run in the isolated child")

        service = SpellingSuggestionService(worker_target=controlled_worker, suggestion_timeout=.35)
        assistant = PortugueseWritingAssistant(spelling_adapter=SpyllsAdapter(
            dictionary_loader=lambda language: Dictionary()), suggestion_service=service)
        controller = WritingController(assistant)
        try:
            controller.submit(WritingRequest("cpu-first", 1, "pt-BR"))
            result = None
            deadline = time.monotonic() + 8
            while result is None and time.monotonic() < deadline:
                for event in controller.poll():
                    if event.kind == "result":
                        result = event.result
                self.pump()
                time.sleep(.001)
            self.assertIsNotNone(result)
            controller.request_suggestions(result.issues[0])
            beats = []
            def beat():
                beats.append(time.monotonic())
                if result.issues[0].suggestions_state != "timed_out":
                    self.root.after(10, beat)
            beat()
            while result.issues[0].suggestions_state != "timed_out" and time.monotonic() < deadline:
                for event in controller.poll():
                    if event.kind == "result":
                        result = event.result
                self.pump()
                time.sleep(.001)
            self.assertEqual(result.issues[0].suggestions_state, "timed_out")
            self.assertEqual(result.issues[0].suggestions, ())
            self.assertGreater(len(beats), 10)
            self.assertLess(max(b - a for a, b in zip(beats, beats[1:])), .15)
        finally:
            controller.shutdown()
            assistant.shutdown()
            service._thread.join(8)
            self.assertFalse(service._thread.is_alive())

    def test_large_comment_worker_does_not_block_tk_or_publish_old_result(self):
        entered, release = threading.Event(), threading.Event()
        threads, versions = [], []

        class SlowGrammar:
            def analyze(self, request, protected):
                threads.append(threading.get_ident())
                versions.append(request.text_version)
                entered.set()
                if not release.wait(4):
                    raise RuntimeError("analysis was not released")
                return ()

        class Spelling:
            def analyze(self, request, protected):
                return ()

        assistant = PortugueseWritingAssistant(spelling_adapter=Spelling(), grammar_adapter=SlowGrammar(), cache_capacity=4)
        controller = WritingController(assistant)
        try:
            started = time.perf_counter()
            controller.submit(WritingRequest("Uma posição ativa.\n" * 2000, 1, "pt-BR", grammar_enabled=True))
            assert time.perf_counter() - started < .5
            assert entered.wait(3)
            for version in range(2, 40):
                controller.submit(WritingRequest("Uma posição ativa.", version, "pt-BR", grammar_enabled=True))
            heartbeats = []
            for index in range(10):
                self.root.after(0, lambda value=index: heartbeats.append(value))
                self.pump()
            assert heartbeats == list(range(10))
            assert versions == [1]  # provider is still blocked; Tk continued
            release.set()
            results = []
            deadline = time.monotonic() + 4
            while not results and time.monotonic() < deadline:
                self.pump()
                results.extend(event for event in controller.poll() if event.kind == "result")
                time.sleep(.001)
            assert versions == [1, 39]
            assert len(results) == 1 and results[0].result.text_version == 39
            assert all(ident != threading.get_ident() for ident in threads)
        finally:
            release.set()
            controller.shutdown()
            controller._executor.shutdown(wait=True, cancel_futures=True)
            assistant.shutdown()


def test_benchmark_failure_sets_nonzero_replay_exit_without_payload(tmp_path, monkeypatch):
    from ferramentas import avaliar_corretor_portugues as evaluator

    class Service:
        def analyze(self, request):
            return WritingResult(request.text_version, (), "spelling_only")

        def shutdown(self):
            pass

    monkeypatch.setattr(evaluator, "create_assistant", Service)
    monkeypatch.setattr(evaluator, "benchmark_assistant", lambda *args, **kwargs: {
        "sizes": {"small": {"failed": 1, "target_met": False}},
    })
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"schema_version": 1, "cases": []}), encoding="utf-8")
    assert evaluator.main(["--mode", "spelling", "--corpus", str(corpus_path),
                           "--output-dir", str(tmp_path / "reports"), "--benchmark-repeats", "1"]) == 1
