"""Global aggregate metrics: real SQLite, contention, failure isolation and editor actions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import multiprocessing
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest


def test_daily_aggregation_has_no_payload_columns_or_values_and_is_global(tmp_path, monkeypatch):
    from tradutor_pgn.writing_metrics import WritingMetrics

    monkeypatch.setenv("PGN_TRADUTOR_DATA", str(tmp_path / "global"))
    writer = WritingMetrics()
    for _ in range(3):
        assert writer.record(category="SPELLING", rule_id="SPELLING_UNKNOWN_WORD", action="aplicada", day="2026-10-30")
    assert writer.record(category="SPELLING", rule_id="SPELLING_UNKNOWN_WORD", action="ignorada_sessao", day="2026-10-30")
    assert writer.record(category="VERBAL_AGREEMENT", rule_id="GENERAL_VERB_AGREEMENT_ERRORS", action="aplicada", day="2026-10-29")
    assert writer.path == tmp_path / "global/writing-metrics.db"
    with sqlite3.connect(writer.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert [row[1] for row in connection.execute("PRAGMA table_info(daily_counts)")] == [
            "day", "category", "rule_id", "action", "count",
        ]
        assert connection.execute("SELECT count FROM daily_counts WHERE day='2026-10-30' AND action='aplicada'").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM daily_counts").fetchone() == (3,)
    assert not list(tmp_path.glob("**/*book*"))


def _record_many(path, count):
    from tradutor_pgn.writing_metrics import WritingMetrics

    writer = WritingMetrics(path)
    return sum(writer.record(category="GRAMMAR", rule_id="RULE", action="aplicada", day="2026-10-30") for _ in range(count))


def test_concurrent_windows_and_processes_do_not_lose_increments(tmp_path):
    path = str(tmp_path / "writing-metrics.db")
    with ThreadPoolExecutor(max_workers=5) as executor:
        thread_successes = sum(executor.map(lambda _: _record_many(path, 12), range(5)))
    assert thread_successes > 0
    context = multiprocessing.get_context("spawn")
    with context.Pool(2) as pool:
        process_successes = sum(pool.starmap(_record_many, [(path, 12)] * 2))
    assert process_successes > 0
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count FROM daily_counts").fetchall() == [(thread_successes + process_successes,)]


@pytest.mark.parametrize("kwargs", [
    {"category": "private user text"}, {"rule_id": "private user text"},
    {"rule_id": "RULE\nsecret"}, {"action": "correction payload"}, {"day": "2026-02-30"},
    {"rule_id": "REGRA_É"}, {"rule_id": "RΕGRA_7"}, {"rule_id": "R" * 129},
])
def test_invalid_metadata_is_dropped_before_any_file_is_created(tmp_path, kwargs):
    from tradutor_pgn.writing_metrics import WritingMetrics

    writer = WritingMetrics(tmp_path / "writing-metrics.db")
    values = {"category": "SPELLING", "rule_id": "SPELLING_UNKNOWN_WORD", "action": "aplicada", "day": "2026-10-30", **kwargs}
    assert writer.record(**values) is False
    assert not writer.path.exists()


@pytest.mark.parametrize("failure", ["directory", "corrupt", "future", "extra_column", "locked"])
def test_storage_failures_are_quiet_and_never_escape(tmp_path, caplog, failure):
    from tradutor_pgn.writing_metrics import WritingMetrics

    path = tmp_path / "writing-metrics.db"
    lock = None
    if failure == "directory":
        path.mkdir()
    elif failure == "corrupt":
        path.write_bytes(b"PRIVATE TEXT NOT A DATABASE")
    elif failure == "future":
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA user_version=99")
    elif failure == "extra_column":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE daily_counts(day,category,rule_id,action,count,text)")
            connection.execute("PRAGMA user_version=1")
    elif failure == "locked":
        lock = sqlite3.connect(path)
        lock.execute("BEGIN EXCLUSIVE")
    try:
        assert WritingMetrics(path, timeout=.01).record(category="SPELLING", rule_id="RULE", action="aplicada") is False
    finally:
        if lock is not None:
            lock.close()
    assert caplog.text == ""


def test_default_date_is_a_day_without_timestamp(tmp_path):
    from tradutor_pgn.writing_metrics import WritingMetrics

    writer = WritingMetrics(tmp_path / "writing-metrics.db")
    assert writer.record(category="GRAMMAR", rule_id="RULE", action="regra_desativada")
    with sqlite3.connect(writer.path) as connection:
        assert connection.execute("SELECT day FROM daily_counts").fetchone() == (date.today().isoformat(),)


def test_bounded_background_recorder_never_waits_for_slow_storage_and_survives_failure(tmp_path):
    from tradutor_pgn.writing_metrics import MetricsRecorder, WritingMetrics

    entered, release = threading.Event(), threading.Event()

    class SlowStorage(WritingMetrics):
        calls = 0

        def record(self, **values):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(3)
                raise OSError("private payload")
            return super().record(**values)

    writer = SlowStorage(tmp_path / "writing-metrics.db")
    recorder = MetricsRecorder(writer, capacity=1)
    try:
        assert recorder.submit(category="GRAMMAR", rule_id="RULE", action="aplicada")
        assert entered.wait(3)
        started = time.perf_counter()
        assert recorder.submit(category="GRAMMAR", rule_id="RULE", action="aplicada")
        assert recorder.submit(category="GRAMMAR", rule_id="RULE", action="aplicada") is False
        assert time.perf_counter() - started < .2
    finally:
        release.set()
        recorder.close(timeout=3)
    assert recorder.submit(category="GRAMMAR", rule_id="RULE", action="aplicada") is False
    with sqlite3.connect(writer.path) as connection:
        assert connection.execute("SELECT count FROM daily_counts").fetchone() == (1,)


@pytest.fixture
def editor_case():
    import test_editor_windows as windows
    from gui_harness import DISPLAY

    if not DISPLAY:
        pytest.skip("Tk display unavailable")
    case = windows.WritingEditorTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()
        case.doCleanups()


def test_real_editor_records_applied_and_ignored_actions_without_passing_text(tmp_path, monkeypatch, editor_case):
    from tradutor_pgn import writing_metrics

    writer = writing_metrics.WritingMetrics(tmp_path / "global/writing-metrics.db")
    recorder = writing_metrics.MetricsRecorder(writer)
    monkeypatch.setattr(writing_metrics, "_recorder", recorder)
    case = editor_case
    try:
        issue = case.ready()
        case.editor.apply_issue(issue, "erro")
        assert case.editor.draft_text() == "erro errao"
        assert case.editor.state.dirty
        case.editor.ignore_once(case.ready())
    finally:
        recorder.close(timeout=3)
    with sqlite3.connect(writer.path) as connection:
        assert connection.execute("SELECT category,rule_id,action,count FROM daily_counts ORDER BY action").fetchall() == [
            ("SPELLING", "SPELLING_UNKNOWN_WORD", "aplicada", 1),
            ("SPELLING", "SPELLING_UNKNOWN_WORD", "ignorada_uma_vez", 1),
        ]
    assert b"errao" not in writer.path.read_bytes()
    with sqlite3.connect(case.db_path) as connection:
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name='daily_counts'").fetchall()


def test_real_editor_metric_exception_cannot_break_apply_or_undo(monkeypatch, editor_case):
    from tradutor_pgn import edit_window

    def broken(**metadata):
        raise OSError("private payload")

    monkeypatch.setattr(edit_window, "record_writing_action", broken)
    case = editor_case
    case.editor.apply_issue(case.ready(), "erro")
    assert case.editor.draft_text() == "erro errao" and case.editor.state.dirty
    case.editor.undo_translation()
    assert case.editor.draft_text() == "errao errao"


def test_editor_drops_invalid_rule_metadata_before_logging_or_persisting(tmp_path, monkeypatch, caplog):
    from tradutor_pgn import edit_window

    monkeypatch.setenv("PGN_TRADUTOR_DATA", str(tmp_path))
    issue = SimpleNamespace(category="GRAMMAR", rule_id="PRIVATE USER PAYLOAD")
    with caplog.at_level("INFO", logger="tradutor_pgn.edit_window"):
        edit_window.TranslationEditor._record_writing_action(object(), issue, "aplicada")
    assert caplog.text == ""
    assert not list(tmp_path.iterdir())
