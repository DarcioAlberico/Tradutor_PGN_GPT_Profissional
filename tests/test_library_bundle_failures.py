import json
from pathlib import Path

import pytest

from tradutor_pgn.translation_library import list_bundles
from tradutor_pgn.translation_output import publish_translation_bundle


def create(tmp_path, failed=None):
    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("traduzido", encoding="utf8")
        return True
    return publish_translation_bundle(str(source), "pt", str(tmp_path / "out"), generate, failed_comments=failed)


def test_failed_count_is_stored_and_visible_to_library(tmp_path):
    result = create(tmp_path, 3)
    manifest = json.loads((Path(result.bundle_dir) / "manifesto.json").read_text(encoding="utf8"))
    assert manifest["failed_comments"] == 3
    assert list_bundles(tmp_path / "out")[0].failed_comments == 3


def test_unknown_count_remains_unknown_and_old_manifests_work(tmp_path):
    result = create(tmp_path)
    manifest_path = Path(result.bundle_dir) / "manifesto.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    assert manifest["failed_comments"] is None
    del manifest["failed_comments"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    bundle = list_bundles(tmp_path / "out")[0]
    assert bundle.status == "ready" and bundle.failed_comments is None


@pytest.mark.parametrize("invalid", [-1, True, 1.5, "3"])
def test_invalid_count_is_rejected_without_publishing(tmp_path, invalid):
    result = create(tmp_path, invalid)
    assert result.status == "failed"
    assert not list((tmp_path / "out").iterdir())


def test_invalid_count_in_external_manifest_is_not_trusted(tmp_path):
    result = create(tmp_path, 0)
    manifest_path = Path(result.bundle_dir) / "manifesto.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["failed_comments"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    assert list_bundles(tmp_path / "out")[0].status == "invalid"
