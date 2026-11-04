"""Worker delivery contracts; gates keep races deterministic without Tk."""

from dataclasses import replace
import threading
import time

import pytest

from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpellingUnavailable
from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
from tradutor_pgn.languagetool_process import LanguageToolProcess
from tradutor_pgn.writing_controller import WritingController
from tradutor_pgn.writing_types import AssistantStatus, WritingIssue, WritingRequest
from tradutor_pgn.spelling_suggestions_process import SuggestionSnapshot


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


class ProgressiveService:
    def __init__(self):
        self.callbacks = []
        self.cancelled = []
        self.revision = (0, "initial")

    def suggestion_revision(self):
        return self.revision

    def analyze(self, request):
        raise AssertionError("interactive controller must prefer initial analysis")

    def analyze_initial(self, request):
        from tradutor_pgn.writing_types import WritingResult
        issue = WritingIssue("", "SPELLING_UNKNOWN_WORD", "SPELLING", 0, len(request.text), request.text,
                             "Grafia", "Confira", (), "error", "spylls", request.text_version,
                             suggestions_state="pending")
        return WritingResult(request.text_version, (issue,), "spelling_only")

    def request_suggestions(self, request, issue, *, owner, emit):
        self.callbacks.append(emit)

    def cancel_suggestions(self, owner):
        self.cancelled.append(owner)

    def status(self):
        return AssistantStatus("ready", "spelling_only")


def test_initial_result_and_suggestion_prefixes_have_same_context_and_occurrence():
    service = ProgressiveService()
    controller = WritingController(service, window_id="one")
    try:
        controller.submit(WritingRequest("posiçao", 4, "pt"), record_id="record")
        initial = next(event for event in wait_result(controller) if event.kind == "result")
        issue = initial.result.issues[0]
        assert issue.suggestions_state == "pending"
        controller.request_suggestions(issue)
        deadline = time.monotonic() + 3
        while not service.callbacks and time.monotonic() < deadline:
            time.sleep(.001)
        assert service.callbacks
        service.callbacks[-1](SuggestionSnapshot(("posição",), "partial"))
        updated = [event for event in controller.poll() if event.kind == "result"][-1]
        assert updated.context == initial.context and updated.text_digest == initial.text_digest
        assert updated.result.issues[0].issue_id == issue.issue_id
        assert updated.result.issues[0].suggestions == ("posição",)
        service.callbacks[-1](SuggestionSnapshot(("posição", "posições"), "complete"))
        assert [event for event in controller.poll() if event.kind == "result"][-1].result.issues[0].suggestions == (
            "posição", "posições",
        )
    finally:
        controller.shutdown()


def test_retry_accepts_the_ui_snapshot_while_a_new_prefix_is_queued():
    service = ProgressiveService()
    controller = WritingController(service)
    try:
        controller.submit(WritingRequest("posiçao", 4, "pt"))
        issue = next(event.result.issues[0] for event in wait_result(controller) if event.kind == "result")
        controller.request_suggestions(issue)
        deadline = time.monotonic() + 3
        while not service.callbacks and time.monotonic() < deadline:
            time.sleep(.001)
        service.callbacks[-1](SuggestionSnapshot(("posição",), "timed_out"))
        # The callback enriched controller state; Tk still holds its previous
        # snapshot until the next poll. Occurrence identity remains valid.
        controller.request_suggestions(issue, retry=True)
        while len(service.callbacks) < 2 and time.monotonic() < deadline:
            time.sleep(.001)
        assert len(service.callbacks) == 2
    finally:
        controller.shutdown()


def test_selection_bursts_keep_only_one_pending_preparation():
    entered, release = threading.Event(), threading.Event()
    class SlowPreparation(ProgressiveService):
        def request_suggestions(self, request, issue, *, owner, emit):
            entered.set()
            assert release.wait(3)
            super().request_suggestions(request, issue, owner=owner, emit=emit)
    service = SlowPreparation()
    controller = WritingController(service)
    try:
        controller.submit(WritingRequest("posiçao", 4, "pt"))
        issue = next(event.result.issues[0] for event in wait_result(controller) if event.kind == "result")
        controller.request_suggestions(issue)
        assert entered.wait(3)
        for _ in range(50):
            controller.request_suggestions(issue, retry=True)
        assert controller._executor._work_queue.qsize() <= 1
    finally:
        release.set()
        controller.shutdown()


def test_revision_is_transported_and_rechecked_when_already_queued_events_are_polled():
    service = ProgressiveService()
    controller = WritingController(service)
    try:
        controller.submit(WritingRequest("posiçao", 4, "pt"))
        initial = next(event for event in wait_result(controller) if event.kind == "result")
        issue = initial.result.issues[0]
        controller.request_suggestions(issue)
        deadline = time.monotonic() + 3
        while not service.callbacks and time.monotonic() < deadline:
            time.sleep(.001)
        service.callbacks[-1](SuggestionSnapshot(("posição",), "partial"))
        service.revision = (1, "changed-after-enqueue")
        events = controller.poll()
        assert not any(event.result and event.result.issues[0].suggestions for event in events)
        assert issue.revision == initial.revision == (0, "initial")
        assert not controller.is_current_issue(issue)
    finally:
        controller.shutdown()


@pytest.mark.parametrize("change", ["cancel", "submit", "close", "selection"])
def test_old_suggestion_callbacks_cannot_publish_after_context_or_selection_changes(change):
    service = ProgressiveService()
    controller = WritingController(service)
    try:
        controller.submit(WritingRequest("posiçao", 1, "pt"), record_id="old")
        issue = next(event.result.issues[0] for event in wait_result(controller) if event.kind == "result")
        controller.request_suggestions(issue)
        deadline = time.monotonic() + 3
        while not service.callbacks and time.monotonic() < deadline:
            time.sleep(.001)
        callback = service.callbacks[-1]
        if change == "close":
            controller.shutdown()
        elif change == "submit":
            controller.submit(WritingRequest("outra", 1, "pt"), record_id="new")
            wait_result(controller)
        elif change == "selection":
            controller.cancel_suggestions()
        else:
            controller.cancel_context()
        controller.poll()
        callback(SuggestionSnapshot(("posição",), "complete"))
        assert controller.poll() == ()
        assert service.cancelled
    finally:
        controller.shutdown()


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


@pytest.mark.parametrize("other_mode", ["unavailable", "spelling_only", "full"])
@pytest.mark.parametrize("grammar_enabled, own_mode", [(True, "full"), (False, "spelling_only")])
def test_poll_never_attributes_other_windows_completed_status_to_active_request(
    other_mode, grammar_enabled, own_mode,
):
    entered, release = threading.Event(), threading.Event()

    class SpellingByWindow:
        def analyze(self, request, protected):
            if request.text == "janela A":
                entered.set()
                assert release.wait(3), "test must release window A"
            elif other_mode == "unavailable":
                raise SpellingUnavailable("DIAGNOSTICO_DA_JANELA_B")
            return ()

    class Grammar:
        def analyze(self, request, protected):
            return ()

        def status(self):
            return AssistantStatus("ready", "full")

    assistant = PortugueseWritingAssistant(spelling_adapter=SpellingByWindow(), grammar_adapter=Grammar())
    one, two = WritingController(assistant, window_id="A"), WritingController(assistant, window_id="B")
    try:
        one.submit(WritingRequest("janela A", 10, "pt", grammar_enabled=grammar_enabled), record_id="registro A")
        assert entered.wait(3)
        two.submit(WritingRequest("janela B", 20, "pt", grammar_enabled=other_mode == "full"),
                   record_id="registro B")
        other_events = wait_result(two)
        assert all(event.context.window_id == "B" and event.text_version == 20 for event in other_events)
        assert [event.result.mode for event in other_events if event.kind == "result"] == [other_mode]

        # B has completed while A is still in spelling: its status is not A's.
        assert one.poll() == ()
        release.set()
        own_events = wait_result(one)
        assert all(event.context.window_id == "A" and event.context.record_id == "registro A"
                   and event.text_version == 10 for event in own_events)
        assert [event.status for event in own_events if event.kind == "status"] == [
            AssistantStatus("ready", own_mode),
        ]
        assert [event.result.mode for event in own_events if event.kind == "result"] == [own_mode]
    finally:
        release.set()
        one.shutdown()
        two.shutdown()
        one._executor.shutdown(wait=True)
        two._executor.shutdown(wait=True)
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
