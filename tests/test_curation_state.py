from tradutor_pgn import curation_state
import pytest
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import threading


def test_ignoring_and_restoring_is_scoped_to_work_and_language_pair(tmp_path):
    settings = str(tmp_path / "settings.json")
    a = curation_state.candidate_key("livro.pgn", "en", "pt", "rook", "torre")
    other_file = curation_state.candidate_key("outro.pgn", "en", "pt", "rook", "torre")
    other_pair = curation_state.candidate_key("livro.pgn", "en", "es", "rook", "torre")
    curation_state.set_ignored(a, True, path=settings)
    assert curation_state.ignored_keys(path=settings) == {a}
    assert a != other_file and a != other_pair
    assert "rook" not in (tmp_path / "settings.json").read_text(encoding="utf8")
    curation_state.set_ignored(a, False, path=settings)
    assert curation_state.ignored_keys(path=settings) == set()


def test_repeated_ignore_is_idempotent(tmp_path):
    path = str(tmp_path / "settings.json")
    key = curation_state.candidate_key("a.pgn", None, "pt", "a", "b")
    curation_state.set_ignored(key, True, path=path)
    curation_state.set_ignored(key, True, path=path)
    assert curation_state.ignored_keys(path=path) == {key}


def test_invalid_settings_are_reported_without_modifying_them(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{corrompido", encoding="utf8")
    with pytest.raises(ValueError):
        curation_state.ignored_keys(path=str(path))
    assert path.read_text(encoding="utf8") == "{corrompido"


def test_ignoring_does_not_recover_or_replace_a_corrupt_settings_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{corrompido", encoding="utf8")
    key = curation_state.candidate_key("a.pgn", "en", "pt", "a", "b")
    with pytest.raises(ValueError):
        curation_state.set_ignored(key, True, path=str(path))
    assert path.read_text(encoding="utf8") == "{corrompido"
    assert not list(tmp_path.glob("settings.json.corrompido-*"))


def test_concurrent_decisions_preserve_every_candidate(tmp_path):
    path = str(tmp_path / "settings.json")
    keys = [curation_state.candidate_key("a.pgn", "en", "pt", str(i), "palavra") for i in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda key: curation_state.set_ignored(key, True, path=path), keys))
    assert curation_state.ignored_keys(path) == set(keys)


def test_ignore_preserves_other_settings_sections(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drafts": {"work": "texto pendente"}, "theme": "dark"}), encoding="utf8")
    key = curation_state.candidate_key("a.pgn", "en", "pt", "a", "b")
    curation_state.set_ignored(key, True, path=str(path))
    actual = json.loads(path.read_text(encoding="utf8"))
    assert actual["drafts"] == {"work": "texto pendente"}
    assert actual["theme"] == "dark"


def test_restoring_multiple_candidates_preserves_unrelated_decisions(tmp_path):
    path = str(tmp_path / "settings.json")
    keys = [curation_state.candidate_key(f"{i}.pgn", "en", "pt", "rook", "torre") for i in range(3)]
    for key in keys:
        curation_state.set_ignored(key, True, path=path)
    curation_state.restore_ignored(keys[:2], path=path)
    assert curation_state.ignored_keys(path) == {keys[2]}


def test_separate_processes_preserve_simultaneous_decisions(tmp_path):
    path = str(tmp_path / "settings.json")
    keys = [curation_state.candidate_key("a.pgn", "en", "pt", str(i), "x") for i in range(4)]
    code = "from tradutor_pgn.curation_state import set_ignored; import sys; set_ignored(sys.argv[2], True, path=sys.argv[1])"
    processes = [subprocess.Popen([sys.executable, "-c", code, path, key]) for key in keys]
    try:
        assert all(p.wait(timeout=15) == 0 for p in processes)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert curation_state.ignored_keys(path) == set(keys)


def test_candidate_guard_blocks_ignored_and_serializes_concurrent_decisions(tmp_path):
    path = str(tmp_path / "settings.json")
    key = curation_state.candidate_key("a.pgn", "en", "pt", "a", "b")
    entered = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with curation_state.available_candidate(key, path=path):
            def ignore():
                entered.set()
                curation_state.set_ignored(key, True, path=path)
            future = pool.submit(ignore)
            assert entered.wait(2)
            assert not future.done()
        future.result(timeout=5)
    with pytest.raises(curation_state.CandidateIgnored):
        with curation_state.available_candidate(key, path=path):
            pass


def test_candidate_guard_releases_lock_when_rule_creation_fails(tmp_path):
    path = str(tmp_path / "settings.json")
    key = curation_state.candidate_key("a.pgn", "en", "pt", "a", "b")
    with pytest.raises(RuntimeError):
        with curation_state.available_candidate(key, path=path):
            raise RuntimeError("falha de catálogo")
    curation_state.set_ignored(key, True, path=path)
    assert key in curation_state.ignored_keys(path)
