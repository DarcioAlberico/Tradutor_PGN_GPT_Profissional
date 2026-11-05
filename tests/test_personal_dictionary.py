"""Persistence and process isolation of the global personal vocabulary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tradutor_pgn.personal_dictionary import DictionaryLockTimeout, PersonalDictionary


def test_missing_file_and_default_global_location(tmp_path, monkeypatch):
    monkeypatch.setenv("PGN_TRADUTOR_DATA", str(tmp_path))
    dictionary = PersonalDictionary()
    assert dictionary.load() == []
    assert not dictionary.contains("xadrez")
    assert dictionary.add("Capablanca")
    assert json.loads((tmp_path / "vocabulario-pessoal.json").read_text("utf-8")) == {
        "schema_version": 1, "words": ["Capablanca"],
    }


def test_normalized_comparison_preserves_first_spelling_and_sorted_display(tmp_path):
    path = tmp_path / "words.json"
    dictionary = PersonalDictionary(path)
    assert dictionary.add("Zugzwang")
    assert dictionary.add("Ac\u0327a\u0303o")
    assert dictionary.add("Straße")
    assert dictionary.contains("AÇÃO")
    assert dictionary.contains("STRASSE")
    before = path.read_bytes()
    assert not dictionary.add("ação")
    assert path.read_bytes() == before
    assert dictionary.list_words() == ["Ac\u0327a\u0303o", "Straße", "Zugzwang"]
    assert PersonalDictionary(path).load() == ["Ac\u0327a\u0303o", "Straße", "Zugzwang"]


@pytest.mark.parametrize("word", ["", " ", "\t\n"])
@pytest.mark.parametrize("method", ["add", "remove", "contains"])
def test_empty_words_are_rejected_without_creating_dictionary(tmp_path, word, method):
    path = tmp_path / "words.json"
    with pytest.raises(ValueError):
        getattr(PersonalDictionary(path), method)(word)
    assert not path.exists()


def test_instances_reread_before_mutations_and_reads(tmp_path):
    path = tmp_path / "words.json"
    first, second = PersonalDictionary(path), PersonalDictionary(path)
    first.load()
    second.load()
    assert first.add("Capablanca")
    assert second.add("Nimzowitsch")
    assert first.contains("nimzowitsch")
    assert first.remove("CAPABLANCA")
    assert not second.remove("Capablanca")
    assert second.list_words() == ["Nimzowitsch"]


@pytest.mark.parametrize("raw", [b"{broken", b"\xff", b"[]", b'{"schema_version":1,"words":[3]}'])
def test_corruption_is_recoverable_and_original_is_preserved(tmp_path, raw, caplog):
    path = tmp_path / "words.json"
    path.write_bytes(raw)
    dictionary = PersonalDictionary(path)
    assert dictionary.load() == []
    assert path.read_bytes() == raw
    assert dictionary.add("Alekhine")
    assert dictionary.load() == ["Alekhine"]
    backups = list(tmp_path.glob("words.json.corrompido-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert caplog.records


def test_future_schema_cannot_be_overwritten(tmp_path):
    path = tmp_path / "words.json"
    original = b'{"schema_version":2,"words":["future"]}'
    path.write_bytes(original)
    with pytest.raises(ValueError, match="schema"):
        PersonalDictionary(path).add("Alekhine")
    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["dump", "replace"])
def test_failure_before_publication_keeps_original_and_cleans_temp(tmp_path, monkeypatch, operation):
    path = tmp_path / "words.json"
    dictionary = PersonalDictionary(path)
    dictionary.add("Tal")
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(f"tradutor_pgn.personal_dictionary.{'json' if operation == 'dump' else 'os'}.{operation}", fail)
        with pytest.raises(OSError, match="publication failed"):
            dictionary.add("Botvinnik")
    assert path.read_bytes() == before
    assert dictionary.list_words() == ["Tal"]
    assert not list(tmp_path.glob("*.tmp"))


def test_unreadable_dictionary_does_not_get_replaced(tmp_path, monkeypatch):
    path = tmp_path / "words.json"
    dictionary = PersonalDictionary(path)
    dictionary.add("Tal")
    before = path.read_bytes()
    original = Path.read_bytes

    def denied(self):
        if self == path:
            raise PermissionError("denied")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", denied)
        with pytest.raises(PermissionError):
            dictionary.add("Botvinnik")
    assert path.read_bytes() == before


def test_backup_failure_leaves_corrupt_original_untouched(tmp_path, monkeypatch):
    path = tmp_path / "words.json"
    raw = b"{broken"
    path.write_bytes(raw)

    def denied(*args, **kwargs):
        raise PermissionError("backup denied")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", denied)
        with pytest.raises(PermissionError, match="backup denied"):
            PersonalDictionary(path).add("Tal")
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob("*.tmp"))


def test_load_validates_normalizes_and_returns_independent_snapshots(tmp_path):
    path = tmp_path / "words.json"
    path.write_text(json.dumps({
        "schema_version": 1, "words": ["Zugzwang", "A\u00e7\u00e3o", "ac\u0327a\u0303o", "Tal"],
    }), encoding="utf-8-sig")
    dictionary = PersonalDictionary(path)
    loaded = dictionary.load()
    assert loaded == ["A\u00e7\u00e3o", "Tal", "Zugzwang"]
    loaded.clear()
    assert dictionary.list_words() == ["A\u00e7\u00e3o", "Tal", "Zugzwang"]


_CONCURRENT_WRITER = """
import sys, time
from pathlib import Path
from tradutor_pgn.personal_dictionary import PersonalDictionary
path, start, label = sys.argv[1:]
deadline = time.monotonic() + 15
while not Path(start).exists():
    if time.monotonic() > deadline:
        raise TimeoutError('parent did not start writers')
    time.sleep(0.01)
dictionary = PersonalDictionary(path)
for number in range(20):
    dictionary.add(f'{label}-{number:02}')
for number in range(0, 20, 2):
    dictionary.remove(f'{label}-{number:02}')
"""


def test_simultaneous_process_mutations_preserve_both_writers_words(tmp_path):
    path, start = tmp_path / "words.json", tmp_path / "start"
    dictionary = PersonalDictionary(path)
    dictionary.add("Tal")
    root = Path(__file__).resolve().parents[1]
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", _CONCURRENT_WRITER, str(path), str(start), label],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root,
            env={**os.environ, "PYTHONPATH": str(root)},
        ) for label in ("A", "B")
    ]
    try:
        start.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, (stdout, stderr)
        assert dictionary.load() == [
            "A-01", "A-03", "A-05", "A-07", "A-09", "A-11", "A-13", "A-15", "A-17", "A-19",
            "B-01", "B-03", "B-05", "B-07", "B-09", "B-11", "B-13", "B-15", "B-17", "B-19",
            "Tal",
        ]
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


_HOLDING_WRITER = """
import os, sys, time
from pathlib import Path
from tradutor_pgn.personal_dictionary import PersonalDictionary
path, ready, release = map(Path, sys.argv[1:])
original = os.replace
def paused_replace(source, target):
    ready.touch()
    deadline = time.monotonic() + 15
    while not release.exists():
        if time.monotonic() > deadline:
            raise TimeoutError('parent did not release writer')
        time.sleep(0.01)
    original(source, target)
os.replace = paused_replace
PersonalDictionary(path).add('Capablanca')
"""


def test_process_lock_survives_atomic_replace_and_times_out(tmp_path):
    path, ready, release = (tmp_path / name for name in ("words.json", "ready", "release"))
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLDING_WRITER, str(path), str(ready), str(release)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        # A distinct process owns the lock while its JSON still does not exist.
        dictionary = PersonalDictionary(path.parent / "." / path.name, lock_timeout=0.1)
        with pytest.raises(DictionaryLockTimeout, match="lock"):
            dictionary.add("Nimzowitsch")
        assert not path.exists()
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert dictionary.add("Nimzowitsch")
        assert dictionary.load() == ["Capablanca", "Nimzowitsch"]
        assert (tmp_path / "words.json.lock").exists()
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        process.communicate()
