"""Best-effort global daily aggregates. No text, offsets or suggestions accepted.

The UI enqueues only validated primitive metadata in a bounded queue. SQLite
transactions serialize increments across windows and processes. Storage errors,
queue overflow and shutdown may lose metrics; they never delay editorial work.
"""

import atexit
from contextlib import closing
from datetime import date
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
from typing import get_args

from .app_paths import data_path
from .writing_types import IssueCategory

METRICS_FILENAME = "writing-metrics.db"
_ACTIONS = frozenset({"aplicada", "aplicada_lote", "ignorada_uma_vez", "ignorada_sessao", "vocabulario", "regra_desativada"})
_RULE_ID = re.compile(r"[A-Z][A-Z0-9_]{0,127}", re.ASCII)
_COLUMNS = ("day", "category", "rule_id", "action", "count")


def _metadata(category: str, rule_id: str, action: str, day: str | None) -> dict[str, str]:
    if (category not in get_args(IssueCategory) or action not in _ACTIONS
            or not isinstance(rule_id, str) or _RULE_ID.fullmatch(rule_id) is None):
        raise ValueError("invalid writing metric metadata")
    day = date.today().isoformat() if day is None else day
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid writing metric day")
    return {"category": category, "rule_id": rule_id, "action": action, "day": day}


def is_valid_writing_action(*, category: str, rule_id: str, action: str) -> bool:
    """Gate metadata-only logging as well as asynchronous persistence."""
    try:
        _metadata(category, rule_id, action, None)
        return True
    except Exception:
        return False


class WritingMetrics:
    """One connection per short transaction; no book DB dependency or migration."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, timeout: float = 1.0) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("invalid writing metrics timeout")
        self.path = Path(path if path is not None else data_path(METRICS_FILENAME)).resolve()
        self.timeout = timeout

    @staticmethod
    def _prepare(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if version == 0 and not tables:
            connection.execute("""CREATE TABLE daily_counts (
                day TEXT NOT NULL, category TEXT NOT NULL, rule_id TEXT NOT NULL,
                action TEXT NOT NULL, count INTEGER NOT NULL CHECK(count > 0),
                PRIMARY KEY(day, category, rule_id, action)) WITHOUT ROWID""")
            connection.execute("PRAGMA user_version=1")
        elif version != 1 or tables != {"daily_counts"}:
            raise ValueError("unsupported writing metric schema")
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(daily_counts)"))
        if columns != _COLUMNS:
            raise ValueError("unexpected writing metric columns")

    def record(self, *, category: str, rule_id: str, action: str, day: str | None = None) -> bool:
        try:
            values = _metadata(category, rule_id, action, day)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=self.timeout)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._prepare(connection)
                connection.execute("""INSERT INTO daily_counts(day,category,rule_id,action,count)
                    VALUES(:day,:category,:rule_id,:action,1)
                    ON CONFLICT(day,category,rule_id,action) DO UPDATE SET count=count+1""", values)
            return True
        except Exception:
            # SQLite/OS diagnostics can contain paths or values. No payload log.
            return False


class MetricsRecorder:
    """Bounded, nonblocking submission and one owned daemon storage worker."""

    def __init__(self, writer: WritingMetrics, *, capacity: int = 256) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("metrics queue capacity must be positive")
        self._writer = writer
        self._queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._worker = threading.Thread(target=self._run, name="writing-metrics", daemon=True)
        self._worker.start()

    def submit(self, *, category: str, rule_id: str, action: str) -> bool:
        try:
            values = _metadata(category, rule_id, action, None)
            with self._lock:
                if self._closed.is_set():
                    return False
                self._queue.put_nowait(values)
            return True
        except Exception:
            return False

    def _run(self) -> None:
        while not self._closed.is_set() or not self._queue.empty():
            try:
                values = self._queue.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                self._writer.record(**values)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def close(self, *, timeout: float = .2) -> None:
        with self._lock:
            self._closed.set()
        self._worker.join(timeout=timeout)


_recorder: MetricsRecorder | None = None
_recorder_lock = threading.Lock()


def record_writing_action(*, category: str, rule_id: str, action: str) -> bool:
    """UI bridge: accept metadata only, never a WritingIssue or book identifier."""
    global _recorder
    try:
        _metadata(category, rule_id, action, None)
        with _recorder_lock:
            if _recorder is None:
                _recorder = MetricsRecorder(WritingMetrics())
                atexit.register(_recorder.close)
            recorder = _recorder
        return recorder.submit(category=category, rule_id=rule_id, action=action)
    except Exception:
        return False
