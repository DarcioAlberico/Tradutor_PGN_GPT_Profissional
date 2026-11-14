from tradutor_pgn.google_cooldown import GoogleCooldown
from tradutor_pgn.translation_api import RequestPacer


def test_reservation_reports_quota_cooldown_and_overlap(tmp_path):
    control = GoogleCooldown(tmp_path / "control.db")
    control.configure_limits(1, 100)
    assert control.reserve(now=1000) == 0
    quota = control.reserve(now=1001)
    assert quota == 59 and quota.reason == "quota"
    control.defer(30, now=1001)
    both = control.reserve(now=1002)
    assert both == 58 and both.reason == "both"
    fresh = GoogleCooldown(tmp_path / "cooldown.db")
    fresh.defer(30, now=1061)
    cooldown = fresh.reserve(now=1062)
    assert cooldown == 29 and cooldown.reason == "cooldown"


def test_cancelled_wait_records_elapsed_time_by_reason(tmp_path, monkeypatch):
    control = GoogleCooldown(tmp_path / "control.db")
    control.configure_limits(1, 100)
    assert control.reserve() == 0
    times = iter([10.0, 10.25])
    monkeypatch.setattr("tradutor_pgn.google_cooldown.time.monotonic", lambda: next(times))
    monkeypatch.setattr(control, "reserve", lambda: type("Delay", (float,), {"reason": "quota"})(20))
    class Flag:
        def is_set(self): return False
        def wait(self, delay): return True
    observed = []
    assert not control.wait(Flag(), on_delay=lambda reason, seconds: observed.append((reason, seconds)))
    assert observed == [("quota", 0.25)]


def test_metrics_accept_separate_wait_categories():
    metrics = RequestPacer().metrics
    metrics.record_wait("quota", 1.5)
    metrics.record_wait("cooldown", 2.0)
    metrics.record_wait("both", 0.5)
    assert (metrics.quota_wait_seconds, metrics.cooldown_wait_seconds, metrics.overlap_wait_seconds) == (1.5, 2.0, 0.5)


def test_pacer_collects_the_reason_reported_by_shared_control(tmp_path, monkeypatch):
    from tradutor_pgn.google_cooldown import ReservationDelay

    control = GoogleCooldown(tmp_path / "control.db")
    delays = iter([ReservationDelay(0.01, "both"), 0.0])
    monkeypatch.setattr(control, "reserve", lambda: next(delays))
    pacer = RequestPacer(shared_cooldown=control)
    assert pacer.wait_shared(None, None)
    assert pacer.metrics.overlap_wait_seconds > 0
    assert pacer.metrics.quota_wait_seconds == 0
    assert pacer.metrics.cooldown_wait_seconds == 0
