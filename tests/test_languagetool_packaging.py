"""Release boundaries use tiny real archives; unit tests never fetch Java."""
import hashlib
import io
import json
from pathlib import Path
import stat
import zipfile
from types import SimpleNamespace

import pytest

from ferramentas import preparar_languagetool as packaging


def archive(*names):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zipped:
        for name in names:
            zipped.writestr(name, b"payload")
    return data.getvalue()


def package(data):
    return {
        "url": "https://languagetool.org/download/fixed.zip",
        "sha256": hashlib.sha256(data).hexdigest(),
        "root": "tool", "expected": ["server.jar"],
    }


def test_lock_rejects_untrusted_or_unpinned_sources(tmp_path):
    lock = json.loads(packaging.LOCK.read_text(encoding="utf-8"))
    lock["packages"]["languagetool"]["url"] = "http://languagetool.org/download/tool.zip"
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="HTTPS"):
        packaging.load_lock(path)


def test_lock_rejects_nonliteral_checksum(tmp_path):
    lock = json.loads(packaging.LOCK.read_text(encoding="utf-8"))
    lock["packages"]["jdk"]["sha256"] = "latest"
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="SHA-256"):
        packaging.load_lock(path)


def test_valid_cache_works_without_network(tmp_path):
    data = archive("tool/server.jar")
    spec = package(data)
    cached = tmp_path / (spec["sha256"] + ".zip")
    cached.write_bytes(data)
    assert packaging.download(spec, tmp_path) == cached


def test_wrong_hash_leaves_no_published_download(tmp_path, monkeypatch):
    data = archive("tool/server.jar")
    monkeypatch.setattr(packaging, "_open_url", lambda url: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="SHA-256"):
        packaging.download(package(data), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_partial_download_removes_temp_and_preserves_cache(tmp_path, monkeypatch):
    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise OSError("connection lost")
    (tmp_path / "other.zip").write_bytes(b"keep")
    monkeypatch.setattr(packaging, "_open_url", lambda url: Interrupted())
    with pytest.raises(OSError):
        packaging.download(package(b"expected"), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["other.zip"]


@pytest.mark.parametrize("name", ["../escape", "tool/../../escape", "/absolute", "C:/escape", "tool/..\\escape", "tool/file:stream", "tool/CON", "tool/trailing."])
def test_zip_rejects_windows_path_escape_before_writing(tmp_path, name):
    zipped = tmp_path / "source.zip"
    zipped.write_bytes(archive("tool/server.jar", name))
    target = tmp_path / "target"
    with pytest.raises(ValueError):
        packaging.extract_zip(zipped, target, package(zipped.read_bytes()))
    assert not target.exists()
    assert not (tmp_path / "escape").exists()


def test_zip_rejects_symlinks_and_case_collisions(tmp_path):
    for symlink in (True, False):
        path = tmp_path / "source.zip"
        with zipfile.ZipFile(path, "w") as zipped:
            zipped.writestr("tool/server.jar", b"payload")
            info = zipfile.ZipInfo("tool/link" if symlink else "tool/SERVER.jar")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16 if symlink else 0
            zipped.writestr(info, b"../outside")
        with pytest.raises(ValueError):
            packaging.extract_zip(path, tmp_path / "target", package(path.read_bytes()))
    assert not (tmp_path / "target").exists()


def test_failed_extraction_preserves_previous_vendor(tmp_path):
    previous = tmp_path / "vendor"
    previous.mkdir()
    (previous / "known-good").write_bytes(b"keep")
    broken = tmp_path / "broken.zip"
    broken.write_bytes(archive("tool/not-the-server"))
    with pytest.raises(ValueError, match="expected"):
        packaging.extract_zip(broken, previous, package(broken.read_bytes()))
    assert (previous / "known-good").read_bytes() == b"keep"


def test_publication_rolls_back_when_rename_fails(tmp_path, monkeypatch):
    current, staged = tmp_path / "vendor", tmp_path / "staged"
    current.mkdir()
    staged.mkdir()
    (current / "old").write_bytes(b"old")
    (staged / "new").write_bytes(b"new")
    replace = packaging.os.replace
    def fail_once(source, target):
        if Path(source) == staged:
            raise OSError("locked destination")
        return replace(source, target)
    monkeypatch.setattr(packaging.os, "replace", fail_once)
    with pytest.raises(OSError):
        packaging.publish(staged, current)
    assert (current / "old").read_bytes() == b"old"
    assert not (current / "new").exists()


def bundle(tmp_path):
    root = tmp_path / "bundle"
    lock = packaging.load_lock()
    for name in packaging.required_files(lock):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"program data")
    (root / "languagetool-lock.json").write_bytes(packaging.LOCK.read_bytes())
    (root / "sbom.json").write_text('{}')
    (root / "license-audit.json").write_text(json.dumps({"unresolved": [], "artifacts": packaging.license_artifacts(root)}))
    packaging.write_manifest(root)
    return root


def test_complete_bundle_validates_without_jdk(tmp_path):
    packaging.validate_bundle(bundle(tmp_path))


@pytest.mark.parametrize("missing", ["runtime/bin/java.exe", "languagetool/libs/portuguese-pos-dict.jar", "LICENSES/LanguageTool-LGPL-2.1.txt", "languagetool/server.properties"])
def test_bundle_fails_closed_when_a_required_resource_is_missing(tmp_path, missing):
    root = bundle(tmp_path)
    (root / missing).unlink()
    with pytest.raises(ValueError):
        packaging.validate_bundle(root)


@pytest.mark.parametrize("extra", ["runtime/bin/javac.exe", "jdk/bin/java.exe", "languagetool/logs/check.log", "languagetool/chaves-api.json", "languagetool/cache/user.bin", "corpus/private.txt"])
def test_bundle_rejects_user_material_and_full_jdk_even_with_manifest(tmp_path, extra):
    root = bundle(tmp_path)
    file = root / extra
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"must not ship")
    packaging.write_manifest(root)
    with pytest.raises(ValueError):
        packaging.validate_bundle(root)


def test_bundle_rejects_changed_file_after_preparation(tmp_path):
    root = bundle(tmp_path)
    (root / "runtime/bin/java.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        packaging.validate_bundle(root)


def test_jlink_uses_pinned_tools_and_classpath(tmp_path):
    commands = packaging.runtime_commands(tmp_path / "vendor", tmp_path / "runtime", "java.base,java.xml")
    jdeps, jlink = commands
    assert Path(jdeps[0]) == tmp_path / "vendor/jdk/bin/jdeps.exe"
    assert "--ignore-missing-deps" in jdeps
    assert jdeps[jdeps.index("--multi-release") + 1] == "17"
    assert jlink[jlink.index("--add-modules") + 1] == "java.base,java.xml"
    assert {"--strip-debug", "--no-header-files", "--no-man-pages", "--compress=2"} <= set(jlink)


def test_smoke_environment_contains_no_system_java_or_network_proxy():
    env = packaging.isolated_environment({"PATH": "C:/java/bin", "JAVA_HOME": "C:/java", "JAVA_TOOL_OPTIONS": "-agentlib:evil", "HTTP_PROXY": "http://external", "SystemRoot": "C:/Windows"})
    assert env["PATH"] == ""
    assert "JAVA_HOME" not in env
    assert "JAVA_TOOL_OPTIONS" not in env
    assert "HTTP_PROXY" not in env
    assert env["SystemRoot"] == "C:/Windows"


@pytest.mark.parametrize("startup,rss", [(10.01, 1), (1, 1_000_000_001)])
def test_measurement_gate_rejects_slow_or_large_sidecar(startup, rss):
    with pytest.raises(ValueError, match="prototype"):
        packaging.check_measurements({"startup_seconds": startup, "peak_rss_bytes": rss})


def test_smoke_requires_real_agreement_with_expected_span_and_correction():
    issue = SimpleNamespace(rule_id="GENERAL_NUMBER_AGREEMENT_ERRORS", category="NOMINAL_AGREEMENT",
                            original="cavalos branco", suggestions=("cavalos brancos",))
    packaging.check_smoke_issues((issue,))


@pytest.mark.parametrize("changes", [
    {"rule_id": "MORFOLOGIK_RULE_PT_BR", "category": "SPELLING"},
    {"original": "Os"}, {"suggestions": ("unrelated",)},
])
def test_smoke_rejects_spelling_or_unrelated_diagnostics(changes):
    values = dict(rule_id="GENERAL_NUMBER_AGREEMENT_ERRORS", category="NOMINAL_AGREEMENT",
                  original="cavalos branco", suggestions=("cavalos brancos",))
    values.update(changes)
    with pytest.raises(ValueError, match="agreement"):
        packaging.check_smoke_issues((SimpleNamespace(**values),))


@pytest.mark.parametrize("namespace", ['xmlns="http://maven.apache.org/POM/4.0.0"', ''])
def test_sbom_preserves_shaded_dependency_licenses_without_assigning_them_to_whole_jar(tmp_path, namespace):
    root = tmp_path / "vendor"
    (root / "languagetool/libs").mkdir(parents=True)
    jar = root / "languagetool/libs/shaded.jar"
    with zipfile.ZipFile(jar, "w") as zipped:
        zipped.writestr("META-INF/maven/dep/lib/pom.xml", f'''
          <project {namespace}><groupId>dep</groupId>
          <artifactId>lib</artifactId><version>1</version><licenses><license>
          <name>MIT</name></license></licenses></project>''')
        zipped.writestr("META-INF/LICENSE", "Copyright Holder. MIT license text.")
        zipped.writestr("org/languagetool/resource/ast/hunspell/LICENSES-en.txt", "Dictionary license evidence")
        zipped.writestr("org/languagetool/resource/pt/spelling/pt-BR.dict", b"dictionary")
        zipped.writestr("native/libhunspell.dll", b"native transitive dependency")
    packaging.sbom(root)
    bom = json.loads((root / "sbom.json").read_text(encoding="utf-8"))
    shipped = next(c for c in bom["components"] if c["name"].endswith("shaded.jar"))
    assert "licenses" not in shipped
    assert shipped["components"][0]["licenses"] == [{"license": {"name": "MIT"}}]
    assert (root / "LICENSES/embedded/languagetool/libs/shaded.jar/META-INF/LICENSE").read_text() == "Copyright Holder. MIT license text."
    assert (root / "LICENSES/embedded/languagetool/libs/shaded.jar/org/languagetool/resource/ast/hunspell/LICENSES-en.txt").read_text() == "Dictionary license evidence"
    audit = json.loads((root / "license-audit.json").read_text(encoding="utf-8"))
    assert audit["unresolved"]  # a declared MIT dependency does not license its container/data
    assert any("pt-BR.dict" in item["path"] for item in audit["dictionaries"])
    assert audit["native_files"] == [{"path": "languagetool/libs/shaded.jar!/native/libhunspell.dll", "sha256": hashlib.sha256(b"native transitive dependency").hexdigest()}]


def test_bundle_rejects_incomplete_license_review(tmp_path):
    root = bundle(tmp_path)
    (root / "license-audit.json").write_text('{"unresolved": ["dictionary source license"]}')
    packaging.write_manifest(root)
    with pytest.raises(ValueError, match="license audit"):
        packaging.validate_bundle(root)


def test_pyinstaller_data_contains_only_validated_shipping_resources(tmp_path):
    root = bundle(tmp_path)
    (root / "jdk/bin").mkdir(parents=True)
    (root / "jdk/bin/javac.exe").write_bytes(b"build tool")
    data = packaging.bundle_datas(root)
    assert (str(root / "runtime/bin/java.exe"), "runtime/bin") in data
    assert (str(root / "vendor-manifest.json"), ".") in data
    assert not any("jdk" in Path(source).relative_to(root).parts for source, _ in data)
    (root / "LICENSES/LanguageTool-LGPL-2.1.txt").unlink()
    with pytest.raises(ValueError, match="resource"):
        packaging.bundle_datas(root)


def test_distribution_validation_keeps_application_files_but_verifies_sidecar(tmp_path):
    root = bundle(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "PGN_Tradutor_Pro.exe").write_bytes(b"application")
    root.rename(dist / "_internal")
    (dist / "_internal/application.pyc").write_bytes(b"python bytecode")
    packaging.validate_distribution(dist)
    (dist / "_internal/languagetool/languagetool-server.jar").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        packaging.validate_distribution(dist)


def test_failed_prototype_keeps_measurements_sbom_audit_and_modules(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    for name in ("measurements.json", "sbom.json", "license-audit.json", "modules.txt"):
        (staged / name).write_text(name)
    packaging.preserve_evidence(staged, tmp_path / "build")
    assert (tmp_path / "build/languagetool-prototype-evidence/measurements.json").read_text() == "measurements.json"
    assert (tmp_path / "build/languagetool-prototype-evidence/sbom.json").read_text() == "sbom.json"
    assert (tmp_path / "build/languagetool-prototype-evidence/license-audit.json").read_text() == "license-audit.json"
    assert (tmp_path / "build/languagetool-prototype-evidence/modules.txt").read_text() == "modules.txt"


def test_sbom_identifies_the_generated_runtime_by_its_actual_modules_hash(tmp_path):
    (tmp_path / "runtime/lib").mkdir(parents=True)
    (tmp_path / "runtime/lib/modules").write_bytes(b"jlinked modules")
    packaging.sbom(tmp_path)
    bom = json.loads((tmp_path / "sbom.json").read_text(encoding="utf-8"))
    runtime = next(c for c in bom["components"] if c["name"] == "Eclipse Temurin jlink runtime")
    assert runtime["hashes"] == [{"alg": "SHA-256", "content": hashlib.sha256(b"jlinked modules").hexdigest()}]


def test_cli_releases_build_lock_after_failed_fetch(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["prepare", "fetch", "--vendor", str(tmp_path / "vendor")])
    def fail(vendor):
        raise ValueError("incomplete source")
    monkeypatch.setattr(packaging, "fetch", fail)
    with pytest.raises(ValueError, match="incomplete source"):
        packaging.main()
    assert not (tmp_path / ".languagetool-build.lock").exists()
