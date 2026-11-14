import json
import subprocess
import sys

import pytest

from benchmarks import pgn_extraction
from tradutor_pgn.pgn_utils import extract_comment_texts_from_file


def test_corpus_contains_complete_games_and_known_comments(tmp_path):
    path = tmp_path / "synthetic.pgn"
    expected, actual_size = pgn_extraction.write_corpus(path, 1024)
    result = extract_comment_texts_from_file(str(path))
    assert actual_size >= 1024
    assert path.stat().st_size == actual_size
    assert len(result["comments"]) == expected
    assert expected > 1


def test_p95_is_nearest_rank_and_rejects_empty_samples():
    assert pgn_extraction.percentile95([5, 1, 4, 2, 3]) == 5
    with pytest.raises(ValueError):
        pgn_extraction.percentile95([])


@pytest.mark.parametrize("arguments", [["--samples", "0"], ["--sizes-mib", "0"]])
def test_cli_rejects_invalid_measurement_sizes(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.pgn_extraction", *arguments],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


def test_cli_outputs_machine_readable_results():
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.pgn_extraction", "--sizes-mib", "1", "--samples", "1"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    report = json.loads(result.stdout)
    assert report["environment"]["python"]
    run = report["results"][0]
    assert run["size_bytes"] >= 1024 * 1024
    assert run["comments"] > 0
    assert run["median_seconds"] > 0
    assert run["p95_seconds"] >= run["median_seconds"]
    assert run["peak_python_bytes"] > 0
    assert run["samples"] == 1
