"""Real spawned workers exercise cancellation and the bounded IPC boundary."""

import json
import os
import threading
import time
import unicodedata

import pytest

from tradutor_pgn.spelling_suggestions_process import SpellingSuggestionService


def _send(connection, **message):
    connection.send_bytes(json.dumps(message).encode("utf-8"))


def controlled_worker(connection):
    _send(connection, kind="ready")
    while True:
        try:
            command = json.loads(connection.recv_bytes(8192))
        except EOFError:
            return
        request_id, word = command["request_id"], command["word"]
        if word == "crash":
            os._exit(7)
        if word == "malformed":
            connection.send_bytes(b"not json")
            continue
        if word == "huge":
            connection.send_bytes(b"x" * 9000)
            continue
        if word == "no-first":
            time.sleep(30)
        if word == "cpu-first":
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                pass
        values = ("posição", "posição", "posições", "oposição", "posicional", "posiciona", "six")
        unique = []
        for value in values:
            _send(connection, kind="suggestion", request_id=request_id, value=value)
            if word == "tail":
                time.sleep(30)
            time.sleep(.002)
            if value not in unique:
                unique.append(value)
            if len(unique) == 5:
                break
        _send(connection, kind="complete", request_id=request_id)


def never_ready_worker(connection):
    time.sleep(30)


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("bounded suggestion work did not finish")
        time.sleep(.002)


def close_service(service):
    service.shutdown()
    service._thread.join(8)
    assert not service._thread.is_alive()


def service(**kwargs):
    return SpellingSuggestionService(worker_target=controlled_worker, startup_timeout=5,
                                     suggestion_timeout=.15, **kwargs)


def test_prefix_is_delivered_before_tail_and_hard_deadline_stops_owned_child():
    worker = service()
    updates = []
    try:
        worker.submit("one", "tail", updates.append)
        wait_until(lambda: any(update.suggestions for update in updates))
        process = worker._process
        assert process is not None and process.is_alive()
        assert updates[-1].suggestions == ("posição",)
        wait_until(lambda: updates[-1].state == "timed_out")
        assert updates[-1].suggestions == ("posição",)
        wait_until(lambda: not process.is_alive())
    finally:
        close_service(worker)


def test_real_process_ranking_deduplication_and_five_option_limit():
    worker = service()
    updates = []
    try:
        worker.submit("one", "normal", updates.append)
        wait_until(lambda: updates and updates[-1].state == "complete")
        assert updates[-1].suggestions == ("posição", "posições", "oposição", "posicional", "posiciona")
        prefixes = [update.suggestions for update in updates if update.state == "partial"]
        assert prefixes[0] == ("posição",)
        assert all(prefixes[index + 1][:len(prefix)] == prefix for index, prefix in enumerate(prefixes[:-1]))
    finally:
        close_service(worker)


@pytest.mark.parametrize("word", ["no-first", "cpu-first", "crash", "malformed", "huge"])
def test_no_first_yield_crash_and_untrusted_ipc_are_bounded_and_can_retry(word):
    worker = service()
    updates, retry = [], []
    try:
        worker.submit("one", word, updates.append)
        expected = "timed_out" if word in {"no-first", "cpu-first"} else "unavailable"
        wait_until(lambda: updates and updates[-1].state == expected)
        assert updates[-1].suggestions == ()
        worker.submit("one", "normal", retry.append)
        wait_until(lambda: retry and retry[-1].state == "complete")
        assert retry[-1].suggestions[0] == "posição"
    finally:
        close_service(worker)


def test_startup_deadline_and_shutdown_do_not_wait_on_the_calling_thread():
    worker = SpellingSuggestionService(worker_target=never_ready_worker,
                                      startup_timeout=.1, suggestion_timeout=.1)
    updates = []
    try:
        started = time.monotonic()
        worker.submit("one", "normal", updates.append)
        assert time.monotonic() - started < .1
        wait_until(lambda: updates and updates[-1].state == "unavailable")
        worker.submit("one", "normal", updates.append)
        wait_until(lambda: worker._process is not None)
        process = worker._process
        started = time.monotonic()
        worker.shutdown()
        assert time.monotonic() - started < .1
        worker._thread.join(8)
        assert not worker._thread.is_alive() and not process.is_alive()
    finally:
        close_service(worker)


def test_two_owners_are_fifo_and_bursts_replace_only_own_pending_work():
    worker = service(max_pending=2)
    first, second, final, busy = [], [], [], []
    try:
        worker.submit("one", "tail", first.append)
        wait_until(lambda: first and first[-1].suggestions)
        process = worker._process
        worker.submit("two", "normal", second.append)
        for _ in range(30):
            worker.submit("three", "normal", final.append)
        worker.submit("four", "normal", busy.append)
        assert busy[-1].state == "busy"
        assert process.is_alive() and first[-1].state == "partial"
        assert len(worker._pending) == 2
        wait_until(lambda: second and second[-1].state == "complete")
        wait_until(lambda: final and final[-1].state == "complete")
        assert first[-1].state == "timed_out"
        assert sum(update.state == "complete" for update in final) == 1
    finally:
        close_service(worker)


def test_cancelling_active_owner_releases_slot_but_cancelling_another_owner_does_not():
    worker = service()
    first, second = [], []
    try:
        worker.submit("one", "no-first", first.append)
        wait_until(lambda: first and first[-1].state == "loading")
        worker.submit("two", "normal", second.append)
        worker.cancel("two")
        worker.cancel("one")
        wait_until(lambda: first[-1].state == "cancelled")
        assert not any(update.state == "complete" for update in second)
        worker.submit("two", "normal", second.append)
        wait_until(lambda: second and second[-1].state == "complete")
    finally:
        close_service(worker)


def test_oversized_tokens_do_not_start_a_process_or_leak_payload_on_failure():
    worker = service()
    updates = []
    try:
        worker.submit("one", "secret" * 1000, updates.append)
        assert updates[-1].state == "unavailable"
        assert updates[-1].suggestions == () and worker._process is None
        assert "secret" not in repr(updates)
    finally:
        close_service(worker)


def test_failed_spawn_is_visible_without_killing_coordinator(monkeypatch):
    from multiprocessing.context import SpawnProcess
    starts = []
    original = SpawnProcess.start

    def observe_start(process):
        starts.append(process)
        original(process)

    monkeypatch.setattr(SpawnProcess, "start", observe_start)
    worker = SpellingSuggestionService(worker_target=lambda connection: None)
    updates = []
    try:
        worker.submit("one", "normal", updates.append)
        wait_until(lambda: updates and updates[-1].state == "unavailable")
        assert worker._thread.is_alive()
        assert starts == []  # Windows must not create a child before target validation.
    finally:
        close_service(worker)


def test_replacing_shared_service_during_async_shutdown_never_overlaps_children():
    from tradutor_pgn import spelling_suggestions_process as process_module
    one, two = service(), service()
    first, second = [], []
    try:
        one.submit("one", "tail", first.append)
        wait_until(lambda: first and first[-1].suggestions)
        owned = one._process
        # Model a new service requested while the previous one's asynchronous
        # cleanup is still pending. Even independent owners share the OS slot.
        two.submit("two", "normal", second.append)
        wait_until(lambda: second and second[-1].state == "loading")
        assert process_module._child_slot.acquire(blocking=False) is False
        one.shutdown()
        wait_until(lambda: second and second[-1].state == "complete")
        assert not owned.is_alive()
    finally:
        close_service(one)
        close_service(two)


def test_an_incomplete_ipc_receive_cannot_bypass_the_deadline(monkeypatch):
    from tradutor_pgn import spelling_suggestions_process as process_module
    entered, release = threading.Event(), threading.Event()
    original = process_module._receive

    def incomplete_read(connection):
        message = original(connection)
        if message.get("kind") == "suggestion":
            entered.set()
            release.wait(3)
        return message

    monkeypatch.setattr(process_module, "_receive", incomplete_read)
    worker = service()
    updates = []
    try:
        worker.submit("one", "tail", updates.append)
        assert entered.wait(5)
        started = time.monotonic()
        wait_until(lambda: updates and updates[-1].state in {"timed_out", "unavailable"}, timeout=1.5)
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        close_service(worker)


def test_real_spylls_sequences_match_legacy_for_accents_compounds_and_nfd():
    from tradutor_pgn.prose_spellcheck import load_dictionary, spelling_suggestions
    dictionary = load_dictionary("pt")
    assert dictionary is not None
    words = ("posiçao", "peao", "contra-jogo", "posic\u0327ao")
    expected = [spelling_suggestions(unicodedata.normalize("NFC", word), dictionary) for word in words]
    worker = SpellingSuggestionService(suggestion_timeout=5)
    try:
        for word, ranked in zip(words, expected):
            updates = []
            worker.submit("one", word, updates.append)
            wait_until(lambda: updates and updates[-1].state in {"complete", "timed_out", "unavailable"}, timeout=12)
            assert updates[-1].state == "complete"
            assert updates[-1].suggestions == ranked
    finally:
        close_service(worker)
