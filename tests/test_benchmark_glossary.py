import json
import subprocess
import sys

import pytest

from benchmarks import glossary_matching
from tradutor_pgn.glossario import apply_automatic_substitutions


def test_synthetic_rules_have_matches_and_known_result():
    rules, text, expected = glossary_matching.make_case(8)
    assert len(rules) == 8
    assert len({rule[0] for rule in rules}) == 8
    assert apply_automatic_substitutions(text, rules) == expected
    assert expected != text


def test_invalid_rules_count_fails():
    with pytest.raises(ValueError):
        glossary_matching.make_case(0)


def test_unicode_case_preserves_expected_result():
    rules, text, expected = glossary_matching.make_case(8, unicode_text=True)
    assert "café" in text
    assert apply_automatic_substitutions(text, rules) == expected


def test_cli_reports_cold_and_following_runs():
    process = subprocess.run(
        [sys.executable, "-m", "benchmarks.glossary_matching", "--rule-counts", "20", "--samples", "2"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    report = json.loads(process.stdout)
    result = report["results"][0]
    assert result["rules"] == 20
    assert result["cold_seconds"] > 0
    assert len(result["durations_seconds"]) == 2
    assert result["median_seconds"] > 0
    assert result["peak_python_bytes"] > 0
    assert result["following_cache_hits"] >= 2
    assert result["following_cache_misses"] == 0
    assert report["environment"]["python"]
