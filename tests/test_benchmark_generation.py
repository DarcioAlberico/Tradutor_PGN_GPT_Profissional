import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from benchmarks import pgn_generation


def test_small_generation_measures_and_preserves_expected_bytes(tmp_path):
    result = pgn_generation.measure(tmp_path, 4096, 2)
    assert result["input_bytes"] >= 4096
    assert result["comments"] > 1
    assert len(result["durations_seconds"]) == 2
    assert result["median_seconds"] > 0
    assert result["peak_python_bytes"] > 0
    assert not list(tmp_path.iterdir())


def test_corrupted_output_is_detected(tmp_path):
    def corrupt(_input, output, *_args, **_kwargs):
        from pathlib import Path
        Path(output).write_bytes(b"incorrect")
        return True
    with patch.object(pgn_generation, "generate_translated_pgn", side_effect=corrupt):
        with pytest.raises(RuntimeError, match="diverge"):
            pgn_generation.measure(tmp_path, 100, 1)
    assert not list(tmp_path.iterdir())


def test_existing_files_are_not_touched(tmp_path):
    existing = tmp_path / "input.pgn"
    existing.write_bytes(b"conteudo existente")
    pgn_generation.measure(tmp_path, 100, 1)
    assert existing.read_bytes() == b"conteudo existente"
    assert list(tmp_path.iterdir()) == [existing]


def test_cli_returns_json():
    result = subprocess.run([sys.executable, "-m", "benchmarks.pgn_generation", "--sizes-mib", "1", "--samples", "1"],
                            capture_output=True, text=True, check=True, timeout=30)
    report = json.loads(result.stdout)
    assert report["results"][0]["input_bytes"] >= 1024 * 1024
    assert report["environment"]["python"]
