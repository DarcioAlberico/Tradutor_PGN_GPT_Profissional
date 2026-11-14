import threading
import time
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from tradutor_pgn import api_keys
from tradutor_pgn.api_keys import save_api_key, stored_key_state


@pytest.mark.parametrize("contents", ["{quebrado", "[]", "[" * 3000 + "]" * 3000])
def test_saving_key_refuses_to_overwrite_unreadable_key_file(tmp_path, contents):
    path = tmp_path / "chaves.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(OSError):
        save_api_key("openai", "secret-value", str(path))
    assert path.read_text(encoding="utf-8") == contents


def test_damaged_key_file_is_reported_as_unreadable(tmp_path):
    path = tmp_path / "chaves.json"
    path.write_text("{quebrado", encoding="utf-8")
    assert stored_key_state("openai", str(path)) == "ilegivel"


def test_concurrent_key_updates_keep_both_providers(tmp_path):
    path = str(tmp_path / "chaves.json")
    read = api_keys._read_file
    entered = threading.Event()

    def delayed_read(*args, **kwargs):
        result = read(*args, **kwargs)
        entered.set()
        time.sleep(0.2)
        return result

    with patch.object(api_keys, "_read_file", delayed_read):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save_api_key, "openai", "openai-secret", path)
            assert entered.wait(2)
            second = pool.submit(save_api_key, "deepseek", "deepseek-secret", path)
            first.result()
            second.result()
    assert api_keys.load_api_key("openai", path=path) == "openai-secret"
    assert api_keys.load_api_key("deepseek", path=path) == "deepseek-secret"


def test_key_write_failure_cleans_temporary_and_preserves_old_file(tmp_path):
    path = tmp_path / "chaves.json"
    save_api_key("openai", "first-secret", str(path))
    before = path.read_bytes()
    with patch("tradutor_pgn.api_keys.json.dump", side_effect=OSError("disco cheio")):
        with pytest.raises(OSError):
            save_api_key("deepseek", "second-secret", str(path))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_two_processes_can_save_different_keys_without_losing_either(tmp_path):
    path = str(tmp_path / "chaves.json")
    ready = tmp_path / "ready"
    code = """
import sys, time
from pathlib import Path
from tradutor_pgn import api_keys
original = api_keys._read_file
def delayed(*args, **kwargs):
    data = original(*args, **kwargs)
    Path(sys.argv[2]).write_text('ready')
    time.sleep(0.5)
    return data
api_keys._read_file = delayed
api_keys.save_api_key('openai', 'first-secret', sys.argv[1])
"""
    first = subprocess.Popen([sys.executable, "-c", code, path, str(ready)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        save_api_key("deepseek", "second-secret", path)
        assert first.wait(timeout=10) == 0
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()
    assert api_keys.load_api_key("openai", path=path) == "first-secret"
    assert api_keys.load_api_key("deepseek", path=path) == "second-secret"
