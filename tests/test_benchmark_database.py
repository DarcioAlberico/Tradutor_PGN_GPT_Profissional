import json
import subprocess
import sys

import pytest

from benchmarks import translation_database


def test_small_database_exercises_real_cache_and_search(tmp_path):
    result = translation_database.measure(tmp_path / "cache.db", 250, 2)
    assert result["rows"] == 250
    assert result["subset_requested"] == 100
    for name in ("full_cache", "subset_cache", "search"):
        metric = result["measurements"][name]
        assert len(metric["durations_seconds"]) == 2
        assert metric["median_seconds"] > 0
        assert metric["p95_seconds"] >= metric["median_seconds"]
        assert metric["peak_python_bytes"] > 0


def test_cli_emits_valid_json_for_small_case():
    result = subprocess.run([sys.executable, "-m", "benchmarks.translation_database", "--rows", "150", "--samples", "1"],
                            capture_output=True, text=True, check=True, timeout=30)
    report = json.loads(result.stdout)
    assert report["environment"]["python"]
    assert report["results"][0]["rows"] == 150


def test_existing_database_is_never_overwritten(tmp_path):
    path = tmp_path / "existing.db"
    path.write_bytes(b"existing user data")
    with pytest.raises(FileExistsError):
        translation_database.measure(path, 10, 1)
    assert path.read_bytes() == b"existing user data"
