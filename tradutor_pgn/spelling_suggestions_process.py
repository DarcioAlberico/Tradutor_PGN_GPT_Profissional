"""Bounded, token-only Spylls work in one disposable, application-owned child.

The coordinator never calls Tk. JSON bytes are size/schema checked on both
sides; multiprocessing's pickle-based receive API is deliberately not used.
Only this child's process handle is terminated on cancellation or deadline.
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import multiprocessing
from multiprocessing.process import BaseProcess
from multiprocessing.reduction import ForkingPickler
import queue
import threading
import time
from typing import Literal, Protocol
import unicodedata
import uuid


SuggestionState = Literal["pending", "loading", "partial", "complete", "timed_out", "unavailable", "cancelled", "busy"]
MAX_TOKEN_LENGTH = 128
MAX_MESSAGE_BYTES = 8192
MAX_SUGGESTION_LENGTH = 512
_child_slot = threading.BoundedSemaphore(1)


class MessageConnection(Protocol):
    def send_bytes(self, buf: bytes) -> None: ...
    def recv_bytes(self, maxlength: int) -> bytes: ...
    def poll(self, timeout: float = 0) -> bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class SuggestionSnapshot:
    suggestions: tuple[str, ...]
    state: SuggestionState


def _send(connection: MessageConnection, message: dict[str, object]) -> None:
    payload = json.dumps(message, ensure_ascii=True).encode("ascii")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("oversized spelling message")
    connection.send_bytes(payload)


def _receive(connection: MessageConnection) -> dict[str, object]:
    message = json.loads(connection.recv_bytes(MAX_MESSAGE_BYTES))
    if not isinstance(message, dict):
        raise ValueError("invalid spelling message")
    return message


def _suggestion_worker(connection: MessageConnection) -> None:
    """Spawn entry point. No text, exception, or suggestion is logged/written."""
    from .prose_spellcheck import load_dictionary, writing_suggestion_candidates

    try:
        dictionary = load_dictionary("pt")
        if dictionary is None:
            return
        _send(connection, {"kind": "ready"})
        while True:
            command = _receive(connection)
            word, request_id = command.get("word"), command.get("request_id")
            if (set(command) != {"word", "request_id", "language"}
                    or command.get("language") != "pt" or not isinstance(word, str)
                    or not 0 < len(word) <= MAX_TOKEN_LENGTH
                    or not isinstance(request_id, str) or len(request_id) != 32):
                return
            values: list[str] = []
            iterator = iter(writing_suggestion_candidates(word, dictionary))
            for value in iterator:
                if not isinstance(value, str) or not 0 < len(value) <= MAX_SUGGESTION_LENGTH:
                    return
                if value not in values:
                    values.append(value)
                    _send(connection, {"kind": "suggestion", "request_id": request_id, "value": value})
                    if len(values) == 5:
                        break
            _send(connection, {"kind": "complete", "request_id": request_id})
            value = ""
            # Never retain a completed token/generator as an idle-worker cache.
            del iterator, values, word, request_id, command
    except Exception:
        # Provider exceptions can carry the token; EOF is the sole diagnostic.
        pass
    finally:
        connection.close()


@dataclass
class _Task:
    owner: str
    word: str
    callback: Callable[[SuggestionSnapshot], None]
    cancelled: threading.Event = field(default_factory=threading.Event)
    values: tuple[str, ...] = ()


class SpellingSuggestionService:
    """One active child, a bounded fair queue, and latest-only work per owner.

    Deadlines cover startup separately (10s) and suggestion work (3s).
    A stalled first yield has the same hard budget as a stalled tail. Timeouts
    preserve already received prefixes and require an explicit caller retry.
    """

    def __init__(self, *, startup_timeout: float = 10, suggestion_timeout: float = 3,
                 max_pending: int = 8,
                 worker_target: Callable[[MessageConnection], None] = _suggestion_worker) -> None:
        if startup_timeout <= 0 or suggestion_timeout <= 0 or type(max_pending) is not int or max_pending < 1:
            raise ValueError("invalid spelling resource budget")
        self._startup_timeout = startup_timeout
        self._suggestion_timeout = suggestion_timeout
        self._max_pending = max_pending
        self._worker_target = worker_target
        self._condition = threading.Condition()
        self._pending: OrderedDict[str, _Task] = OrderedDict()
        self._active: _Task | None = None
        self._closed = False
        self._process: BaseProcess | None = None
        self._owns_child_slot = False
        self._child_stopped = threading.Event()
        self._child_stopped.set()
        self._connection: MessageConnection | None = None
        self._messages: queue.Queue[dict[str, object] | None] = queue.Queue(maxsize=1)
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._thread = threading.Thread(target=self._coordinate, name="spelling-suggestions", daemon=True)
        self._thread.start()

    def submit(self, owner: str, word: str, callback: Callable[[SuggestionSnapshot], None]) -> None:
        word = unicodedata.normalize("NFC", word)
        if not word or len(word) > MAX_TOKEN_LENGTH:
            self._deliver(_Task(owner, "", callback), (), "unavailable")
            return
        rejected: SuggestionState | None = None
        with self._condition:
            if self._closed:
                rejected = "unavailable"
            elif owner not in self._pending and len(self._pending) >= self._max_pending:
                rejected = "busy"
            else:
                if self._active is not None and self._active.owner == owner:
                    self._active.cancelled.set()
                previous = self._pending.get(owner)
                if previous is not None:
                    previous.cancelled.set()
                # Assignment preserves an owner's FIFO place during bursts.
                self._pending[owner] = _Task(owner, word, callback)
                self._condition.notify()
        if rejected is not None:
            self._deliver(_Task(owner, "", callback), (), rejected)

    def cancel(self, owner: str) -> None:
        with self._condition:
            if self._active is not None and self._active.owner == owner:
                self._active.cancelled.set()
            pending = self._pending.pop(owner, None)
            if pending is not None:
                pending.cancelled.set()
            self._condition.notify()

    def shutdown(self) -> None:
        """Nonblocking on Tk; the coordinator terminates and joins its child."""
        with self._condition:
            self._closed = True
            if self._active is not None:
                self._active.cancelled.set()
            self._pending.clear()
            self._condition.notify()

    @staticmethod
    def _deliver(task: _Task, values: tuple[str, ...], state: SuggestionState) -> None:
        task.values = values
        try:
            task.callback(SuggestionSnapshot(values, state))
        except Exception:
            # A caller failure must not kill the shared coordinator or leak text.
            pass

    def _coordinate(self) -> None:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._closed or bool(self._pending))
                    if self._closed:
                        return
                    _, task = self._pending.popitem(last=False)
                    self._active = task
                try:
                    self._run(task)
                except Exception:
                    self._stop_child()
                    self._deliver(task, task.values, "unavailable")
                finally:
                    with self._condition:
                        self._active = None
                    task.word = ""
                    del task
        finally:
            self._stop_child()

    def _stop_child(self) -> None:
        process, self._process = self._process, None
        connection, self._connection = self._connection, None
        self._reader_stop.set()
        if process is not None and process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(.5)
            if process.is_alive():
                process.kill()
                process.join(.5)
            # Refuse another child if an OS failure left this one alive.
            if process.is_alive():
                self._process, self._connection = process, connection
                with self._condition:
                    self._closed = True
                    self._pending.clear()
                raise RuntimeError("spelling child did not stop")
        if connection is not None:
            connection.close()
        self._child_stopped.set()
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.join(.5)
            if reader.is_alive():
                # Refuse new readers/children when an OS read did not unblock.
                with self._condition:
                    self._closed = True
                    self._pending.clear()
                self._reader = reader
                return
        self._release_slot()

    def _release_slot(self) -> None:
        with self._condition:
            if self._owns_child_slot:
                self._owns_child_slot = False
                _child_slot.release()

    def _read_until(self, task: _Task, deadline: float) -> dict[str, object] | None:
        while not task.cancelled.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = self._messages.get(timeout=min(.01, remaining))
            except queue.Empty:
                if self._process is None or not self._process.is_alive():
                    raise RuntimeError("spelling child stopped") from None
                continue
            if message is None:
                raise RuntimeError("spelling IPC unavailable")
            return message
        return None

    def _read_messages(self, connection: MessageConnection, stop: threading.Event,
                       messages: queue.Queue[dict[str, object] | None]) -> None:
        # A partial frame can block recv_bytes even after poll. The coordinator
        # keeps enforcing its deadline while this one reader waits; terminating
        # the owned writer releases the read. The mailbox is bounded to one.
        try:
            while not stop.is_set():
                try:
                    if not connection.poll(.01):
                        continue
                    message = _receive(connection)
                except Exception:
                    message = None
                while not stop.is_set():
                    try:
                        messages.put(message, timeout=.01)
                        break
                    except queue.Full:
                        pass
                if message is None:
                    return
                message = None
        finally:
            # A failed OS read must not permit an unlimited series of readers.
            if self._closed and self._child_stopped.is_set():
                self._release_slot()

    def _ensure_child(self, task: _Task) -> bool:
        if self._process is not None and self._process.is_alive():
            return True
        self._stop_child()
        # Windows creates the OS child before serializing its target. Reject
        # unsupported injected callables first, avoiding an unowned bootstrap
        # child if Process.start raises before it publishes the process handle.
        # This serializes trusted local code only, never user text or IPC data.
        ForkingPickler.dumps(self._worker_target)
        deadline = time.monotonic() + self._startup_timeout
        while not task.cancelled.is_set():
            if _child_slot.acquire(timeout=min(.01, max(0, deadline - time.monotonic()))):
                self._owns_child_slot = True
                self._child_stopped.clear()
                break
            if time.monotonic() >= deadline:
                self._deliver(task, (), "unavailable")
                return False
        if not self._owns_child_slot:
            self._deliver(task, (), "cancelled")
            return False
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=self._worker_target, args=(child,), daemon=True)
        self._connection, self._process = parent, process
        try:
            process.start()
        finally:
            child.close()
        self._messages = queue.Queue(maxsize=1)
        self._reader_stop = threading.Event()
        self._reader = threading.Thread(target=self._read_messages,
                                        args=(parent, self._reader_stop, self._messages),
                                        name="spelling-ipc", daemon=True)
        self._reader.start()
        message = self._read_until(task, deadline)
        if message != {"kind": "ready"}:
            self._stop_child()
            self._deliver(task, (), "cancelled" if task.cancelled.is_set() else "unavailable")
            return False
        return True

    def _run(self, task: _Task) -> None:
        self._deliver(task, (), "loading")
        if not self._ensure_child(task):
            return
        if task.cancelled.is_set():
            self._stop_child()
            self._deliver(task, (), "cancelled")
            return
        request_id = uuid.uuid4().hex
        connection = self._connection
        if connection is None:
            raise RuntimeError("missing spelling connection")
        _send(connection, {"request_id": request_id, "word": task.word, "language": "pt"})
        deadline = time.monotonic() + self._suggestion_timeout
        values: tuple[str, ...] = ()
        while True:
            message = self._read_until(task, deadline)
            if message is None:
                self._stop_child()
                self._deliver(task, values, "cancelled" if task.cancelled.is_set() else "timed_out")
                return
            if message.get("request_id") != request_id:
                raise ValueError("mismatched spelling reply")
            if message == {"kind": "complete", "request_id": request_id}:
                self._deliver(task, values, "complete")
                return
            value = message.get("value")
            if (set(message) != {"kind", "request_id", "value"} or message.get("kind") != "suggestion"
                    or not isinstance(value, str) or not 0 < len(value) <= MAX_SUGGESTION_LENGTH):
                raise ValueError("invalid spelling reply")
            if value not in values:
                if len(values) >= 5:
                    raise ValueError("too many spelling alternatives")
                values += (value,)
                self._deliver(task, values, "partial")


_shared_lock = threading.Lock()
_shared_service: SpellingSuggestionService | None = None


def get_shared_spelling_suggestions() -> SpellingSuggestionService:
    global _shared_service
    with _shared_lock:
        if _shared_service is None or _shared_service._closed:
            _shared_service = SpellingSuggestionService()
        return _shared_service


def shutdown_shared_spelling_suggestions() -> None:
    global _shared_service
    with _shared_lock:
        service, _shared_service = _shared_service, None
    if service is not None:
        service.shutdown()


def cancel_shared_spelling_suggestions(owner: str) -> None:
    with _shared_lock:
        service = _shared_service
    if service is not None:
        service.cancel(owner)
