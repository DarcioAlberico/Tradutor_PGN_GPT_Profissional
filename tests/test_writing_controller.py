"""Worker delivery contracts; gates keep races deterministic without Tk."""

from dataclasses import replace
import threading
import time

import pytest

from tradutor_pgn.writing_assistant import PortugueseWritingAssistant
from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
from tradutor_pgn.languagetool_process import LanguageToolProcess
from tradutor_pgn.writing_controller import WritingController
from tradutor_pgn.writing_types import AssistantStatus, WritingIssue, WritingRequest


class Spelling:
    def __init__(self):
        self.calls = []
        self.threads = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def analyze(self, request, protected):
        self.calls.append(request.text)
        self.threads.append(threading.get_ident())
        if len(self.calls) == 1:
            self.entered.set()
            assert self.release.wait(3), "test must release analysis"
        return (WritingIssue("", "TYPO", "SPELLING", 0, len(request.text), request.text,
                             "Grafia", "Confira", ("correta",), "error", "test", request.text_version),)


def wait_result(controller):
    events = []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        events.extend(controller.poll())
        if any(event.kind in {"result", "error"} for event in events):
            return events
        time.sleep(0.001)
    pytest.fail("analysis did not finish")


def test_only_latest_pending_request_runs_and_poll_delivers_on_caller_thread():
    provider = Spelling()
    controller = WritingController(PortugueseWritingAssistant(spelling_adapter=provider), window_id="one")
    try:
        controller.submit(WritingRequest("primeira", 1, "pt"), record_id="a")
        assert provider.entered.wait(3)
        for version in range(2, 20):
            controller.submit(WritingRequest(f"texto{version}", version, "pt"), record_id="a")
        provider.release.set()
        events = wait_result(controller)
        results = [event for event in events if event.kind == "result"]
        assert provider.calls == ["primeira", "texto19"]
        assert len(results) == 1 and results[0].result.text_version == 19
        assert results[0].context.window_id == "one" and results[0].context.record_id == "a"
        assert all(thread != threading.get_ident() for thread in provider.threads)
        assert controller.poll() == ()
    finally:
        provider.release.set()
        controller.shutdown()


@pytest.mark.parametrize("change", ["record", "language", "text", "cancel"])
def test_navigation_and_cancellation_reject_old_same_version_results(change):
    provider = Spelling()
    controller = WritingController(PortugueseWritingAssistant(spelling_adapter=provider))
    try:
        request = WritingRequest("anterior", 1, "pt")
        controller.submit(request, record_id="old")
        assert provider.entered.wait(3)
        if change == "cancel":
            controller.cancel_context()
        next_request = replace(request, text="seguinte" if change in {"text", "cancel"} else "anterior",
                               target_language="pt-BR" if change == "language" else "pt")
        controller.submit(next_request, record_id="new" if change == "record" else "old")
        provider.release.set()
        events = wait_result(controller)
        results = [event for event in events if event.kind == "result"]
        assert len(results) == 1
        assert results[0].result.issues[0].original == next_request.text
        assert results[0].context.record_id == ("new" if change == "record" else "old")
        assert results[0].context.target_language == next_request.target_language
    finally:
        provider.release.set()
        controller.shutdown()


def test_two_windows_share_service_but_closing_one_does_not_close_other():
    provider = Spelling()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider)
    one, two = WritingController(assistant, window_id="one"), WritingController(assistant, window_id="two")
    try:
        one.submit(WritingRequest("primeira", 1, "pt"))
        assert provider.entered.wait(3)
        two.submit(WritingRequest("segunda", 1, "pt"))
        events = wait_result(two)
        assert [event.result.issues[0].original for event in events if event.kind == "result"] == ["segunda"]
        assert all(event.context.window_id == "two" for event in events)
        one.shutdown()
        provider.release.set()
        assert one.poll() == ()
        two.submit(WritingRequest("terceira", 2, "pt"))
        assert any(event.kind == "result" and event.result.mode == "spelling_only" for event in wait_result(two))
        with pytest.raises(RuntimeError):
            one.submit(WritingRequest("fechada", 2, "pt"))
    finally:
        provider.release.set()
        one.shutdown()
        two.shutdown()
        assistant.shutdown()


def test_unexpected_error_is_safe_and_does_not_resubmit():
    class BrokenAssistant:
        calls = 0

        def analyze(self, request):
            self.calls += 1
            raise RuntimeError(request.text)

        def status(self):
            return AssistantStatus("failed", "unavailable")

    assistant = BrokenAssistant()
    controller = WritingController(assistant)
    try:
        controller.submit(WritingRequest("segredo", 1, "pt"))
        events = wait_result(controller)
        errors = [event for event in events if event.kind == "error"]
        assert len(errors) == 1 and errors[0].diagnostic
        assert "segredo" not in errors[0].diagnostic
        assert assistant.calls == 1
        assert controller.poll() == ()
    finally:
        controller.shutdown()


def test_shutdown_drops_pending_and_late_delivery_without_waiting_for_worker():
    provider = Spelling()
    controller = WritingController(PortugueseWritingAssistant(spelling_adapter=provider))
    try:
        controller.submit(WritingRequest("ativa", 1, "pt"))
        assert provider.entered.wait(3)
        controller.submit(WritingRequest("pendente", 2, "pt"))
        controller.shutdown()
        controller.shutdown()
        assert controller.poll() == ()
        provider.release.set()
        # Test-only join: controller.shutdown itself must return while blocked.
        controller._executor.shutdown(wait=True)
        assert controller.poll() == ()
        assert provider.calls == ["ativa"]
    finally:
        provider.release.set()
        controller.shutdown()


@pytest.mark.parametrize("state", ["starting", "restarting"])
def test_poll_reports_transient_sidecar_state_and_keeps_restart_flag(state):
    entered, release = threading.Event(), threading.Event()

    class Grammar:
        current = AssistantStatus(state, "spelling_only", restart_attempted=state == "restarting")

        def analyze(self, request, protected):
            entered.set()
            assert release.wait(3)
            self.current = AssistantStatus("ready", "full", restart_attempted=state == "restarting")
            return ()

        def status(self):
            return self.current

    provider = Spelling()
    provider.release.set()
    controller = WritingController(PortugueseWritingAssistant(spelling_adapter=provider, grammar_adapter=Grammar()))
    try:
        controller.submit(WritingRequest("palavra", 1, "pt", grammar_enabled=True))
        assert entered.wait(3)
        assert [event.status.state for event in controller.poll() if event.kind == "status"] == [state]
        release.set()
        events = wait_result(controller)
        completed = [event.status for event in events if event.kind == "status" and event.status.state == "ready"]
        assert len(completed) == 1 and completed[0].mode == "full"
        assert completed[0].restart_attempted == (state == "restarting")
    finally:
        release.set()
        controller.shutdown()


def test_real_process_owns_single_restart_then_fallback_without_controller_loop(tmp_path):
    resources = []

    def missing_resource(relative):
        resources.append(relative)
        return tmp_path / relative

    process = LanguageToolProcess(resource_resolver=missing_resource)
    provider = Spelling()
    provider.release.set()
    assistant = PortugueseWritingAssistant(spelling_adapter=provider,
                                           grammar_adapter=LanguageToolLocalAdapter(process=process))
    controller = WritingController(assistant)
    try:
        for version in (1, 2):
            controller.submit(WritingRequest(f"palavra{version}", version, "pt", grammar_enabled=True))
            events = wait_result(controller)
            results = [event.result for event in events if event.kind == "result"]
            assert len(results) == 1 and results[0].mode == "spelling_only"
            assert results[0].diagnostic and len(results[0].issues) == 1
            assert any(event.status.restart_attempted for event in events if event.kind == "status")
        assert resources.count("runtime/bin/java.exe") == 2
        assert provider.calls == ["palavra1", "palavra2"]
        assert controller.poll() == ()
    finally:
        controller.shutdown()
        assistant.shutdown()


def test_cancel_without_resubmit_discards_late_error():
    entered, release = threading.Event(), threading.Event()

    class Failing:
        def analyze(self, request):
            entered.set()
            assert release.wait(3)
            raise RuntimeError("private text")

        def status(self):
            return AssistantStatus("failed", "unavailable")

    controller = WritingController(Failing())
    try:
        controller.submit(WritingRequest("palavra", 1, "pt"))
        assert entered.wait(3)
        controller.cancel_context()
        release.set()
        controller._executor.submit(lambda: None).result(timeout=3)
        assert controller.poll() == ()
    finally:
        release.set()
        controller.shutdown()


def test_new_submit_discards_completed_events_before_the_next_poll():
    provider = Spelling()
    provider.release.set()
    controller = WritingController(PortugueseWritingAssistant(spelling_adapter=provider))
    try:
        controller.submit(WritingRequest("anterior", 1, "pt"))
        # A barrier queues after completion/callback, without consuming events.
        controller._executor.submit(lambda: None).result(timeout=3)
        controller.submit(WritingRequest("seguinte", 1, "pt"))
        events = wait_result(controller)
        assert [event.result.issues[0].original for event in events if event.kind == "result"] == ["seguinte"]
    finally:
        controller.shutdown()
