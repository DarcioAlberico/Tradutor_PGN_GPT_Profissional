import json
from pathlib import Path
from unittest.mock import patch

from tradutor_pgn.translation_library import verify_bundle
from tradutor_pgn.translation_output import publish_translation_bundle


def published(tmp_path):
    source = tmp_path / "livro.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("tradução", encoding="utf8")
        return True
    result = publish_translation_bundle(str(source), "pt", str(tmp_path / "out"), generate)
    return Path(result.bundle_dir), Path(result.original_path), Path(result.translated_path)


def test_verifies_exact_bytes_without_altering_files(tmp_path):
    directory, original, translated = published(tmp_path)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = verify_bundle(directory)
    assert result.status == "verified"
    assert result.original_ok and result.translation_ok
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert original.exists() and translated.exists()


def test_reports_which_file_changed(tmp_path):
    directory, _original, translated = published(tmp_path)
    translated.write_text("alterado", encoding="utf8")
    result = verify_bundle(directory)
    assert result.status == "mismatch"
    assert result.original_ok is True and result.translation_ok is False


def test_legacy_and_missing_files_cannot_be_verified(tmp_path):
    legacy = tmp_path / "old"
    legacy.mkdir()
    assert verify_bundle(legacy).status == "unavailable"
    directory, original, _translated = published(tmp_path)
    original.unlink()
    assert verify_bundle(directory).status == "unavailable"


def test_manifest_changed_during_verification_is_not_reported_valid(tmp_path):
    directory, _original, _translated = published(tmp_path)
    import tradutor_pgn.translation_library as library
    original_hash = library._hash_file
    def modify(path):
        value = original_hash(path)
        manifest = directory / "manifesto.json"
        data = json.loads(manifest.read_text(encoding="utf8"))
        data["execution_provider"] = "alterado"
        manifest.write_text(json.dumps(data), encoding="utf8")
        return value
    with patch.object(library, "_hash_file", side_effect=modify):
        assert verify_bundle(directory).status == "changed"


def test_file_changed_during_verification_is_not_reported_valid(tmp_path):
    directory, original, _translated = published(tmp_path)
    import tradutor_pgn.translation_library as library
    original_hash = library._hash_file
    def modify(path):
        value = original_hash(path)
        if path == original:
            path.write_text("alteração concorrente", encoding="utf8")
        return value
    with patch.object(library, "_hash_file", side_effect=modify):
        assert verify_bundle(directory).status == "changed"


def test_read_error_cannot_be_reported_as_valid(tmp_path):
    directory, _original, _translated = published(tmp_path)
    with patch("tradutor_pgn.translation_library._hash_file", side_effect=OSError("disco indisponível")):
        assert verify_bundle(directory).status == "unavailable"


def test_verification_can_be_cancelled_before_reading(tmp_path):
    directory, _original, _translated = published(tmp_path)
    assert verify_bundle(directory, should_cancel=lambda: True).status == "canceled"


def test_verification_can_be_cancelled_during_file_read(tmp_path):
    directory, original, _translated = published(tmp_path)
    original.write_bytes(b"x" * (3 * 1024 * 1024))
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 4
    assert verify_bundle(directory, should_cancel=cancel).status == "canceled"
    assert calls == 4
