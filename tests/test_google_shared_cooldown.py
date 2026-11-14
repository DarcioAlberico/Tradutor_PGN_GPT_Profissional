import subprocess
import sqlite3
import sys
import threading
import time

import pytest

from tradutor_pgn.google_cooldown import GoogleCooldown


def test_cooldown_persists_and_never_shortens(tmp_path):
    path = tmp_path / 'cooldown.db'
    first = GoogleCooldown(path)
    first.defer(90, now=1000)
    GoogleCooldown(path).defer(10, now=1001)
    assert GoogleCooldown(path).remaining(now=1002) == 88


def test_cooldown_updates_are_shared_between_processes(tmp_path):
    path = tmp_path / 'cooldown.db'
    script = (
        'import sys; from tradutor_pgn.google_cooldown import GoogleCooldown; '
        'GoogleCooldown(sys.argv[1]).defer(float(sys.argv[2]), now=1000)'
    )
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path), str(delay)])
                 for delay in (9, 35, 17, 26)]
    assert [process.wait(timeout=20) for process in processes] == [0, 0, 0, 0]
    assert GoogleCooldown(path).remaining(now=1000) == 35


def test_wait_can_be_cancelled_without_sleeping_for_deadline(tmp_path):
    store = GoogleCooldown(tmp_path / 'cooldown.db')
    store.defer(60)
    flag = threading.Event()
    flag.set()
    started = time.monotonic()
    assert store.wait(flag) is False
    assert time.monotonic() - started < 1


def test_corrupt_state_does_not_report_safe_to_send(tmp_path):
    path = tmp_path / 'cooldown.db'
    path.write_bytes(b'not sqlite')
    with pytest.raises(sqlite3.DatabaseError):
        GoogleCooldown(path).remaining()


def test_cancellation_during_database_check_does_not_allow_send(tmp_path):
    store = GoogleCooldown(tmp_path / 'cooldown.db')
    flag = threading.Event()

    def reserve():
        flag.set()
        return 0

    store.reserve = reserve
    assert store.wait(flag) is False
