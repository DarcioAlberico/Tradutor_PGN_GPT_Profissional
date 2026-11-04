"""The real assistant/controller seam keeps suggestion jobs contextual and private."""

from dataclasses import replace
import os
import threading
import time
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

from tradutor_pgn.personal_dictionary import PersonalDictionary
from tradutor_pgn.spelling_suggestions_process import SuggestionSnapshot
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpyllsAdapter
from tradutor_pgn.writing_controller import WritingController
from tradutor_pgn.writing_types import WritingIssue, WritingRequest, WritingRevisionChanged


class Dictionary:
    def lookup(self, word):
        return False

    def suggest(self, word):
        raise AssertionError("interactive initial detection must never suggest in-process")


class ControlledSuggestions:
    def __init__(self):
        self.submitted = []
        self.callbacks = []
        self.closed = False

    def submit(self, owner, word, callback):
        self.submitted.append((owner, word, threading.get_ident()))
        self.callbacks.append(callback)

    def cancel(self, owner):
        pass

    def shutdown(self):
        self.closed = True


def assistant(tmp_path):
    vocabulary = PersonalDictionary(tmp_path / "personal.json")
    suggestions = ControlledSuggestions()
    service = PortugueseWritingAssistant(spelling_adapter=SpyllsAdapter(
        dictionary_loader=lambda language: Dictionary(), personal_dictionary=vocabulary,
    ), suggestion_service=suggestions)
    return service, suggestions, vocabulary


@pytest.mark.parametrize("revision", ["cache", "personal", "close"])
def test_revision_or_shutdown_drops_inflight_prefixes(tmp_path, revision):
    service, suggestions, vocabulary = assistant(tmp_path)
    request = WritingRequest("posiçao", 2, "pt-BR")
    updates = []
    try:
        issue = service.analyze_initial(request).issues[0]
        service.request_suggestions(request, issue, owner="one", emit=updates.append)
        assert suggestions.submitted[0][1] == "posiçao"
        if revision == "cache":
            service.invalidate_cache()
        elif revision == "personal":
            vocabulary.add("posiçao")
        else:
            service.shutdown()
        suggestions.callbacks[-1](SuggestionSnapshot(("posição",), "partial"))
        assert updates == []
    finally:
        service.shutdown()


@pytest.mark.parametrize("kind", ["source", "glossary", "notation", "stale"])
def test_forged_protected_or_stale_occurrence_never_sends_token_to_worker(tmp_path, kind):
    service, suggestions, _ = assistant(tmp_path)
    word = "Cd4" if kind == "notation" else "posiçao"
    request = WritingRequest(word, 2, "pt-BR", source_text=word if kind == "source" else "",
                             glossary_terms=frozenset({word}) if kind == "glossary" else frozenset())
    issue = WritingIssue("", "SPELLING_UNKNOWN_WORD", "SPELLING", 0, len(word), word, "", "", (),
                         "error", "spylls", 1 if kind == "stale" else 2, suggestions_state="pending")
    try:
        service.request_suggestions(request, issue, owner="one", emit=lambda update: None)
        assert suggestions.submitted == []
    finally:
        service.shutdown()


def test_two_controllers_prepare_on_workers_and_do_not_mix_occurrences(tmp_path):
    service, suggestions, _ = assistant(tmp_path)
    one, two = WritingController(service), WritingController(service)

    def result(controller):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            for event in controller.poll():
                if event.kind == "result":
                    return event.result
            time.sleep(.001)
        pytest.fail("result missing")

    try:
        request = WritingRequest("posiçao [%eval secret]", 1, "pt-BR")
        one.submit(request, record_id="one")
        two.submit(replace(request, text="outra [%eval secret]"), record_id="two")
        first, second = result(one).issues[0], result(two).issues[0]
        one.request_suggestions(first)
        two.request_suggestions(second)
        deadline = time.monotonic() + 3
        while len(suggestions.submitted) < 2 and time.monotonic() < deadline:
            time.sleep(.001)
        assert {item[1] for item in suggestions.submitted} == {"posiçao", "outra"}
        assert all(item[2] != threading.get_ident() for item in suggestions.submitted)
        for (_, word, _), callback in zip(suggestions.submitted, suggestions.callbacks):
            callback(SuggestionSnapshot(("posição" if word == "posiçao" else "outras",), "complete"))
        assert result(one).issues[0].suggestions == ("posição",)
        one.shutdown()
        assert result(two).issues[0].suggestions == ("outras",)
        assert not suggestions.closed
    finally:
        one.shutdown()
        two.shutdown()
        service.shutdown()


def test_vocabulary_edit_before_selection_prevents_obsolete_token_job(tmp_path):
    service, suggestions, vocabulary = assistant(tmp_path)
    request = WritingRequest("posiçao", 2, "pt-BR")
    try:
        issue = service.analyze_initial(request).issues[0]
        vocabulary.add("posiçao")
        service.request_suggestions(request, issue, owner="one", emit=lambda update: None)
        assert suggestions.submitted == []
    finally:
        service.shutdown()


def test_spawned_frozen_worker_diverts_before_gui_import_or_main(monkeypatch):
    class SpawnDiverted(Exception):
        pass

    def divert():
        raise SpawnDiverted

    monkeypatch.setitem(sys.modules, "multiprocessing", SimpleNamespace(freeze_support=divert))
    monkeypatch.setitem(sys.modules, "customtkinter", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "tradutor_pgn.app", SimpleNamespace(PGNTranslatorApp=object))
    with pytest.raises(SpawnDiverted):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "PGN_Tradutor_Pro.py"), run_name="__main__")


def wait_result(controller):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        for event in controller.poll():
            if event.kind == "result":
                return event.result
        time.sleep(.001)
    pytest.fail("result missing")


def test_worker_commit_guard_never_makes_other_editor_wait_for_revision(tmp_path):
    service, _, _ = assistant(tmp_path)
    one, two = WritingController(service), WritingController(service)
    entered, release = threading.Event(), threading.Event()
    try:
        request = WritingRequest("posiçao", 2, "pt-BR")
        one.submit(request)
        two.submit(request)
        first, second = wait_result(one).issues[0], wait_result(two).issues[0]
        def hold_commit():
            with service.guard_revision(first.revision):
                entered.set()
                release.wait(1)
        holder = threading.Thread(target=hold_commit)
        holder.start()
        assert entered.wait(3)
        started = time.monotonic()
        assert not two.is_current_issue(second)
        assert time.monotonic() - started < .1
        started = time.monotonic()
        with pytest.raises(WritingRevisionChanged):
            with two.guard_issue(second):
                pytest.fail("a busy commit cannot authorize an action")
        assert time.monotonic() - started < .1
        started = time.monotonic()
        service.status()
        assert time.monotonic() - started < .1
    finally:
        release.set()
        if "holder" in locals():
            holder.join(3)
        one.shutdown()
        two.shutdown()
        service.shutdown()


def test_guard_read_failure_refuses_mutation_without_exposing_exception_payload(tmp_path, monkeypatch):
    service, _, vocabulary = assistant(tmp_path)
    try:
        issue = service.analyze_initial(WritingRequest("posiçao", 2, "pt-BR")).issues[0]
        def cannot_read():
            raise PermissionError("private-vocabulary-payload")
        monkeypatch.setattr(vocabulary, "content_revision", cannot_read)
        with pytest.raises(WritingRevisionChanged) as error:
            with service.guard_revision(issue.revision):
                pytest.fail("a failed vocabulary read cannot authorize mutation")
        assert "private-vocabulary-payload" not in str(error.value)
    finally:
        service.shutdown()


@pytest.mark.parametrize("edit", ["writer", "inplace", "atomic", "cache", "rules", "glossary"])
def test_queued_prefix_is_revoked_at_delivery_and_old_issue_cannot_apply(tmp_path, edit):
    service, suggestions, vocabulary = assistant(tmp_path)
    vocabulary.add("posiçax")  # Same UTF-8 length as the accepted word below.
    one, two = WritingController(service), WritingController(service)
    try:
        request = WritingRequest("posiçao [%eval secret]", 2, "pt-BR")
        one.submit(request, record_id="one")
        two.submit(request, record_id="two")
        first, second = wait_result(one).issues[0], wait_result(two).issues[0]
        one.request_suggestions(first)
        two.request_suggestions(second)
        deadline = time.monotonic() + 3
        while len(suggestions.callbacks) < 2 and time.monotonic() < deadline:
            time.sleep(.001)
        for callback in suggestions.callbacks:
            callback(SuggestionSnapshot(("posição",), "partial"))
        assert one._events and two._events  # Prefixes have already crossed emit.
        if edit == "writer":
            PersonalDictionary(vocabulary.path).add("posiçao")
        elif edit in {"inplace", "atomic"}:
            before = vocabulary.path.stat()
            raw = vocabulary.path.read_bytes()
            updated = raw.replace("posiçax".encode(), "posiçao".encode())
            assert updated != raw and len(updated) == len(raw)
            if edit == "atomic":
                replacement = vocabulary.path.with_suffix(".replacement")
                replacement.write_bytes(updated)
                os.replace(replacement, vocabulary.path)
            else:
                vocabulary.path.write_bytes(updated)  # External writer ignores the lock.
            os.utime(vocabulary.path, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert vocabulary.path.stat().st_mtime_ns == before.st_mtime_ns
        elif edit == "cache":
            service.invalidate_cache()
        else:
            service.set_cache_revisions(**{edit: "updated"})
        for controller, old in ((one, first), (two, second)):
            events = controller.poll()
            assert not any(event.kind == "result" and event.result.issues[0].suggestions
                           for event in events if event.result and event.result.issues)
            assert not controller.is_current_issue(old)
            fresh = wait_result(controller)
            if edit in {"writer", "inplace", "atomic"}:
                assert fresh.issues == ()
            else:
                assert fresh.issues[0].revision != old.revision
    finally:
        one.shutdown()
        two.shutdown()
        service.shutdown()
