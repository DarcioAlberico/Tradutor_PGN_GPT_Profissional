import subprocess
import sys
import threading

import pytest

from tradutor_pgn.google_cooldown import GoogleCooldown


def test_sliding_minute_and_day_limits_persist_between_instances(tmp_path):
    path = tmp_path / 'quota.db'
    control = GoogleCooldown(path)
    control.configure_limits(2, 3)
    assert control.reserve(now=1000) == 0
    assert GoogleCooldown(path).reserve(now=1001) == 0
    assert control.reserve(now=1002) == 58
    assert control.reserve(now=1060) == 0
    assert control.reserve(now=1120) == 86280
    assert control.reserve(now=87400) == 0


def test_concurrent_processes_cannot_exceed_shared_minute_quota(tmp_path):
    path = tmp_path / 'quota.db'
    GoogleCooldown(path).configure_limits(1, 100)
    script = (
        'import sys; from tradutor_pgn.google_cooldown import GoogleCooldown; '
        'print(GoogleCooldown(sys.argv[1]).reserve(now=1000))'
    )
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(5)]
    outputs = [process.communicate(timeout=20) for process in processes]
    assert all(process.returncode == 0 for process in processes), outputs
    results = sorted(float(output[0]) for output in outputs)
    assert results == [0, 60, 60, 60, 60]


def test_limit_changes_preserve_existing_reservations(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(3, 10)
    assert control.reserve(now=1000) == 0
    control.configure_limits(1, 10)
    assert GoogleCooldown(control.path).reserve(now=1001) == 59


@pytest.mark.parametrize(('minute', 'day'), [(0, 5), (True, 5), (601, 1000), (2, 0), (2, 100001)])
def test_invalid_limits_are_rejected_without_changing_current_values(tmp_path, minute, day):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(10, 100)
    with pytest.raises(ValueError):
        control.configure_limits(minute, day)
    assert control.get_limits() == (10, 100)


def test_cancellation_does_not_reserve_a_request(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 1)
    flag = threading.Event()
    flag.set()
    assert control.wait(flag) is False
    assert control.reserve(now=1000) == 0


@pytest.mark.parametrize('jump', [(-100, 1001), (90000, 1001)])
def test_clock_jumps_preserve_history_conservatively(tmp_path, jump):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 10)
    assert control.reserve(now=1000, monotonic_now=1000) == 0
    assert control.reserve(now=jump[0], monotonic_now=jump[1]) == 60
    assert control.reserve(now=1001, monotonic_now=1002) == 60


def test_wall_clock_is_sampled_after_opening_database(tmp_path, monkeypatch):
    from tradutor_pgn import google_cooldown
    control = GoogleCooldown(tmp_path / 'quota.db')
    opened = [False]
    original = control._connect

    def connect():
        connection = original()
        opened[0] = True
        return connection

    def now():
        assert opened[0], 'time sampled before waiting for database'
        return 1000

    monkeypatch.setattr(control, '_connect', connect)
    monkeypatch.setattr(google_cooldown.time, 'time', now)
    assert control.reserve() == 0


def test_small_forward_clock_drift_does_not_release_quota_early(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 10)
    assert control.reserve(now=1000, monotonic_now=1000) == 0
    assert control.reserve(now=1004, monotonic_now=1001) == 59
    assert control.reserve(now=1008, monotonic_now=1002) == 60


def test_reboot_preserves_recent_reservations_conservatively(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 10)
    assert control.reserve(now=1000, monotonic_now=5000) == 0
    assert control.reserve(now=90000, monotonic_now=10) == 60


def test_reboot_preserves_existing_cooldown_conservatively(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.defer(30, now=1000)
    assert control.reserve(now=90000, monotonic_now=10) == 30


def test_reboot_with_backward_wall_clock_preserves_recent_reservations(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.configure_limits(1, 10)
    assert control.reserve(now=1000, monotonic_now=5000) == 0
    assert control.reserve(now=900, monotonic_now=10) == 60


def test_expired_cooldown_does_not_reappear_after_clock_rollback(tmp_path):
    control = GoogleCooldown(tmp_path / 'quota.db')
    control.defer(30, now=1000)
    assert control.reserve(now=1100, monotonic_now=1100) == 0
    assert control.reserve(now=900, monotonic_now=1101) == 0


def test_wait_reports_limit_once_and_remains_cancellable(tmp_path, monkeypatch):
    control = GoogleCooldown(tmp_path / 'quota.db')
    monkeypatch.setattr(control, 'remaining', lambda: 0)
    waits = iter([2, 1, 0])
    monkeypatch.setattr(control, 'reserve', lambda: next(waits))
    messages = []

    class Flag:
        def is_set(self):
            return False

        def wait(self, _delay):
            return False

    assert control.wait(Flag(), on_wait=lambda: messages.append('waiting')) is True
    assert messages == ['waiting']


def test_daily_limit_wait_can_be_cancelled_instead_of_immediate_failure(tmp_path, monkeypatch):
    control = GoogleCooldown(tmp_path / 'quota.db')
    monkeypatch.setattr(control, 'remaining', lambda: 0)
    monkeypatch.setattr(control, 'reserve', lambda: 7200)
    waits = []

    class Flag:
        def is_set(self):
            return False

        def wait(self, delay):
            waits.append(delay)
            return True

    assert control.wait(Flag()) is False
    assert waits == [1]
