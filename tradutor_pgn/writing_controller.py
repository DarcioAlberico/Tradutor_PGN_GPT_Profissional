"""One active check and one latest pending check per editor, without Tk.

Call submit/cancel/poll from the UI thread. Workers only enqueue immutable
events; poll is the sole delivery point. Closing an editor never closes the
application's shared assistant. The application owns service shutdown.
"""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import threading
from typing import Literal, Protocol
import uuid

from .writing_assistant import PortugueseWritingAssistant
from .writing_types import AssistantStatus, WritingRequest, WritingResult


class AnalysisService(Protocol):
    def analyze(self, request: WritingRequest) -> WritingResult: ...
    def status(self) -> AssistantStatus: ...


_shared_lock = threading.Lock()
_shared_assistant: PortugueseWritingAssistant | None = None


def get_shared_writing_assistant() -> PortugueseWritingAssistant:
    """Application service, created lazily; construction never starts Java."""
    global _shared_assistant
    with _shared_lock:
        if _shared_assistant is None:
            _shared_assistant = PortugueseWritingAssistant()
        return _shared_assistant


def shutdown_shared_writing_assistant() -> None:
    """Application exit only; may wait for the owned sidecar, so use a worker."""
    with _shared_lock:
        assistant = _shared_assistant
    if assistant is not None:
        assistant.shutdown()


@dataclass(frozen=True)
class WritingContext:
    window_id: str
    record_id: str
    target_language: str


@dataclass(frozen=True)
class WritingEvent:
    kind: Literal["status", "result", "error"]
    context: WritingContext
    text_version: int
    text_digest: str
    status: AssistantStatus | None = None
    result: WritingResult | None = None
    diagnostic: str = ""


@dataclass(frozen=True)
class _Work:
    generation: int
    context: WritingContext
    request: WritingRequest
    digest: str

    def event(self, kind: Literal["status", "result", "error"], *,
              status: AssistantStatus | None = None, result: WritingResult | None = None,
              diagnostic: str = "") -> WritingEvent:
        return WritingEvent(kind, self.context, self.request.text_version, self.digest,
                            status, result, diagnostic)


class WritingController:
    def __init__(self, assistant: AnalysisService | None = None, *, window_id: str | None = None) -> None:
        self._assistant = assistant if assistant is not None else get_shared_writing_assistant()
        self._window_id = window_id if window_id is not None else uuid.uuid4().hex
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="writing-analysis")
        self._lock = threading.RLock()
        self._generation = 0
        self._active: _Work | None = None
        self._pending: _Work | None = None
        self._latest: _Work | None = None
        self._events: deque[WritingEvent] = deque()
        self._last_status: AssistantStatus | None = None
        self._closed = False

    def submit(self, request: WritingRequest, *, record_id: str = "") -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Writing controller is closed")
            self._generation += 1
            work = _Work(self._generation,
                         WritingContext(self._window_id, record_id, request.target_language),
                         request, hashlib.sha256(request.text.encode("utf-8")).hexdigest())
            self._latest = work
            self._events.clear()
            self._last_status = None
            if self._active is None:
                self._start(work)
            else:
                self._pending = work

    def _start(self, work: _Work) -> None:
        self._active = work
        future = self._executor.submit(self._assistant.analyze, work.request)
        future.add_done_callback(lambda done: self._finished(work, done))

    def _finished(self, work: _Work, future: Future[WritingResult]) -> None:
        try:
            result = future.result()
            result.validate_for(work.request)
            status = AssistantStatus("failed" if result.mode == "unavailable" else "ready",
                                     result.mode, result.diagnostic,
                                     self._assistant.status().restart_attempted)
            event = work.event("result", result=result)
        except Exception:
            diagnostic = "Análise indisponível: falha no assistente local."
            status = AssistantStatus("failed", "unavailable", diagnostic)
            event = work.event("error", diagnostic=diagnostic)
        with self._lock:
            self._active = None
            if self._closed:
                return
            if self._latest is work:
                self._events.append(work.event("status", status=status))
                self._events.append(event)
                self._last_status = status
            pending, self._pending = self._pending, None
            if pending is not None:
                self._start(pending)

    def poll(self) -> tuple[WritingEvent, ...]:
        """Drain current-context events. Safe after cancel or window destruction."""
        with self._lock:
            work = self._latest
            if self._closed or work is None:
                return ()
            # Only grammar's global lifecycle is observable while working.
            # Completed status is derived from this request's own result.
            if self._active is work and work.request.grammar_enabled:
                status = self._assistant.status()
                if status != self._last_status:
                    self._events.append(work.event("status", status=status))
                    self._last_status = status
            events = tuple(self._events)
            self._events.clear()
            return events

    def cancel_context(self) -> None:
        """Logical cancellation; an in-flight provider is never interrupted."""
        with self._lock:
            self._generation += 1
            self._latest = self._pending = None
            self._events.clear()
            self._last_status = None

    def shutdown(self) -> None:
        """Stop this editor immediately, preserving the shared application service."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.cancel_context()
            self._executor.shutdown(wait=False, cancel_futures=True)
