import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tradutor_pgn import __version__
from tradutor_pgn.translation_output import publish_translation_bundle


def test_published_manifest_describes_exact_files_and_metadata(tmp_path):
    source = tmp_path / "livro.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("traduzido", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(tmp_path / "saida"), generate,
                                        source_language="en", provider="modelo:teste")
    assert result.status == "published"
    directory = Path(result.bundle_dir)
    manifest = json.loads((directory / "manifesto.json").read_text(encoding="utf8"))
    assert manifest["schema_version"] == 1
    assert manifest["application_version"] == __version__
    assert manifest["source_language"] == "en"
    assert manifest["target_language"] == "pt"
    assert manifest["execution_provider"] == "modelo:teste"
    assert manifest["created_at_utc"].endswith("+00:00")
    for key, actual in (("original", result.original_path), ("translation", result.translated_path)):
        entry = manifest["files"][key]
        assert entry["path"] == Path(actual).name
        assert entry["sha256"] == hashlib.sha256(Path(actual).read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(manifest)


def test_manifest_write_failure_keeps_no_partial_bundle(tmp_path):
    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    with patch("tradutor_pgn.translation_output.json.dump", side_effect=OSError("disk error")):
        result = publish_translation_bundle(str(source), "pt", str(root), generate)
    assert result.status == "failed"
    assert isinstance(result.error, OSError)
    assert not list(root.iterdir())


def test_manifest_default_metadata_is_explicitly_unknown(tmp_path):
    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(tmp_path / "out"), generate)
    manifest = json.loads((Path(result.bundle_dir) / "manifesto.json").read_text(encoding="utf8"))
    assert manifest["source_language"] is None
    assert manifest["execution_provider"] is None


def test_cancel_after_manifest_write_publishes_nothing(tmp_path):
    source = tmp_path / "source.pgn"
    source.write_text("original", encoding="utf8")
    root = tmp_path / "out"
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    checks = iter([False, False, True])
    result = publish_translation_bundle(str(source), "pt", str(root), generate,
                                        is_canceled=lambda: next(checks))
    assert result.status == "canceled"
    assert not list(root.iterdir())
