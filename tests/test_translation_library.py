import json
from pathlib import Path

import pytest

from tradutor_pgn.translation_library import LibraryScanCanceled, list_bundles, search_bundles
from tradutor_pgn.translation_output import publish_translation_bundle


def make_bundle(tmp_path):
    source = tmp_path / "livro.pgn"
    source.write_text("original", encoding="utf8")
    def generate(path):
        Path(path).write_text("translated", encoding="utf8")
        return True
    root = tmp_path / "biblioteca"
    result = publish_translation_bundle(str(source), "pt", str(root), generate,
                                        source_language="en", provider="google-gtx")
    return root, Path(result.bundle_dir)


def test_list_reads_new_and_legacy_without_altering_files(tmp_path):
    root, bundle = make_bundle(tmp_path)
    legacy = root / "outro-BR"
    legacy.mkdir()
    (legacy / "outro.pgn").write_text("original", encoding="utf8")
    (legacy / "outro-BR.pgn").write_text("translated", encoding="utf8")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    items = list_bundles(root)
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after
    new = next(item for item in items if item.directory == bundle)
    old = next(item for item in items if item.directory == legacy)
    assert (new.status, new.source_language, new.target_language, new.provider) == ("ready", "en", "pt", "google-gtx")
    assert new.original.name == "livro.pgn" and new.translated.name == "livro-BR.pgn"
    assert old.status == "legacy" and old.target_language is None
    assert old.original.name == "outro.pgn" and old.translated.name == "outro-BR.pgn"
    assert [item.directory.name for item in search_bundles(items, "LIVRO")] == [bundle.name]
    assert [item.directory.name for item in search_bundles(items, status="legacy")] == [legacy.name]


@pytest.mark.parametrize("bad_path", ["../out.pgn", "C:\\out.pgn", "/out.pgn", "sub/file.pgn", "sub\\file.pgn", "file.pgn:stream.pgn", ".", ""])
def test_unsafe_manifest_paths_are_rejected(tmp_path, bad_path):
    root, bundle = make_bundle(tmp_path)
    file = bundle / "manifesto.json"
    manifest = json.loads(file.read_text(encoding="utf8"))
    manifest["files"]["original"]["path"] = bad_path
    file.write_text(json.dumps(manifest), encoding="utf8")
    item = list_bundles(root)[0]
    assert item.status == "invalid" and item.original is None and item.translated is None


def test_invalid_and_incomplete_packages_are_reported_and_staging_ignored(tmp_path):
    root, bundle = make_bundle(tmp_path)
    (bundle / "manifesto.json").write_text("{broken", encoding="utf8")
    missing = root / "missing-BR"
    missing.mkdir()
    (missing / "missing-BR.pgn").write_text("translated", encoding="utf8")
    (root / ".missing.tmp-abcd").mkdir()
    statuses = {item.directory.name: item.status for item in list_bundles(root)}
    assert statuses == {bundle.name: "invalid", "missing-BR": "incomplete"}


def test_missing_library_is_empty_without_creating_directory(tmp_path):
    path = tmp_path / "missing"
    assert list_bundles(path) == []
    assert not path.exists()


def test_library_scan_cancellation_never_returns_a_partial_list(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 3
    with pytest.raises(LibraryScanCanceled):
        list_bundles(tmp_path, should_cancel=cancel)
    assert calls == 3


@pytest.mark.parametrize("mutation", ["version", "hash", "missing_file", "metadata"])
def test_invalid_metadata_and_missing_files_do_not_hide_other_bundles(tmp_path, mutation):
    root, bundle = make_bundle(tmp_path)
    file = bundle / "manifesto.json"
    manifest = json.loads(file.read_text(encoding="utf8"))
    if mutation == "version":
        manifest["schema_version"] = 99
    elif mutation == "hash":
        manifest["files"]["original"]["sha256"] = "bad"
    elif mutation == "metadata":
        manifest["execution_provider"] = {"unexpected": "object"}
    else:
        (bundle / manifest["files"]["original"]["path"]).unlink()
    file.write_text(json.dumps(manifest), encoding="utf8")
    other = root / "other-BR"
    other.mkdir()
    (other / "other.pgn").write_text("source", encoding="utf8")
    (other / "other-BR.pgn").write_text("translation", encoding="utf8")
    statuses = {item.directory.name: item.status for item in list_bundles(root)}
    assert statuses[bundle.name] == ("incomplete" if mutation == "missing_file" else "invalid")
    assert statuses[other.name] == "legacy"


def test_manifest_rejects_link_to_outside_bundle(tmp_path):
    root, bundle = make_bundle(tmp_path)
    file = bundle / "manifesto.json"
    manifest = json.loads(file.read_text(encoding="utf8"))
    link = bundle / "link.pgn"
    try:
        link.symlink_to(tmp_path / "livro.pgn")
    except (OSError, NotImplementedError):
        pytest.skip("criação de links simbólicos indisponível")
    manifest["files"]["original"]["path"] = link.name
    file.write_text(json.dumps(manifest), encoding="utf8")
    assert list_bundles(root)[0].status == "incomplete"
