"""Optional vendor integration: marker retention with a positive leak control.

These are characterization tests: passing means known retention is reproduced,
not that the privacy prerequisite is satisfied. The graph scan includes the
Language static speller but excludes JVM execution infrastructure. It cannot
prove erasure of garbage, OS page files or every JVM root.
"""

from pathlib import Path
import os
import re
import subprocess
import sys
import uuid

import pytest

from tradutor_pgn.languagetool_process import LanguageToolProcess, resource_path


BASE_PACKAGES = (
    "java.lang", "java.util", "java.util.concurrent", "java.util.concurrent.atomic",
    "java.util.concurrent.locks", "java.util.regex", "java.util.stream", "java.util.zip",
    "java.util.jar", "java.io", "java.lang.ref", "java.nio", "java.nio.charset", "java.net",
    "java.math", "java.text", "java.time", "java.nio.file.attribute", "sun.nio.cs", "sun.nio.fs", "sun.net.www",
    "sun.net.www.protocol.http", "sun.net.www.protocol.https", "sun.net.www.protocol.jar",
    "sun.net.www.protocol.file", "sun.util.locale", "jdk.internal.misc", "jdk.internal.ref",
)


def test_production_pool_stays_disabled_without_suppressing_grammar(tmp_path):
    for relative in ("runtime/bin/java.exe", "languagetool/languagetool-server.jar"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    manager = LanguageToolProcess(resource_resolver=lambda relative: tmp_path / relative)
    try:
        command, _cwd = manager._command(12345)
        config = Path(command[command.index("--config") + 1])
        properties = config.read_text(encoding="ascii").splitlines()
        assert "pipelineCaching=false" in properties
        assert "cacheSize=0" in properties
        assert "maxCheckThreads=1" in properties
        assert "skipLoggingChecks=true" in properties
        assert "skipLoggingRuleMatches=true" in properties
        assert not any(line.startswith("disabledRuleIds=") for line in properties)
    finally:
        manager.shutdown()
    assert not config.parent.exists()


@pytest.fixture(scope="module")
def privacy_probe(tmp_path_factory):
    java = resource_path("jdk/bin/java.exe")
    compiler = resource_path("jdk/bin/javac.exe")
    server = resource_path("languagetool/languagetool-server.jar")
    runtime = resource_path("runtime/bin/java.exe")
    if sys.platform != "win32" or not all(path.is_file() for path in (java, compiler, server, runtime)):
        pytest.skip("requires the prepared Windows LT 6.6 vendor and its build JDK")
    root = tmp_path_factory.mktemp("lt-pool-privacy")
    classpath = ";".join((str(root), str(server), str(server.parent / "libs/*")))
    source = Path(__file__).parent / "fixtures/PoolPrivacyProbe.java"
    compiled = subprocess.run([str(compiler), "-encoding", "UTF-8", "-cp", classpath,
                               "-d", str(root), str(source)], capture_output=True, timeout=30)
    exit_code = compiled.returncode
    assert exit_code == 0, "privacy probe did not compile"
    opens = [argument for package in BASE_PACKAGES
             for argument in ("--add-opens", f"java.base/{package}=ALL-UNNAMED")]
    for module, package in (("java.logging", "java.util.logging"),
                            ("java.management", "javax.management"), ("java.xml", "org.xml.sax.helpers")):
        opens.extend(("--add-opens", f"{module}/{package}=ALL-UNNAMED"))
    return java, classpath, opens


def run_probe(privacy_probe, config, logging, cwd, secret, *, initial_only=False):
    java, classpath, opens = privacy_probe
    command = [str(java), "-Xmx1024m", f"-Dlogback.configurationFile={logging}",
               "-XX:-CreateCoredumpOnCrash", f"-XX:ErrorFile={os.devnull}", *opens,
               "-cp", classpath, "org.languagetool.server.PoolPrivacyProbe", str(config)]
    if initial_only:
        command.append("initial-only")
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH"}}
    completed = subprocess.run(
        command, input=(secret + "\n").encode(), capture_output=True, cwd=cwd, timeout=120, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    # Avoid pytest assertion introspection displaying CompletedProcess or its
    # streams if a future broken vendor includes a request in an error.
    exit_code = completed.returncode
    has_stderr = bool(completed.stderr)
    leaked_stdout = secret.encode() in completed.stdout
    assert exit_code == 0, "privacy probe failed"
    assert not has_stderr, "unexpected vendor stderr"
    assert not leaked_stdout, "request marker appeared in vendor stdout"
    rows = re.findall(rb"(\w+) visited=(\d+) matches=(\d+) inaccessible=(\d+) pool_matches=(\d+)", completed.stdout)
    paths = re.findall(rb"^retained_path=([\w.$\[\]]+)\r?$", completed.stdout, re.MULTILINE)
    return rows, paths


@pytest.mark.parametrize("variant", ["production", "pooled", "pooled_without_spelling"])
def test_vendor_pool_privacy_precondition_with_positive_retention_controls(privacy_probe, tmp_path, variant):
    manager = LanguageToolProcess()
    secret = "pgnsentinela" + uuid.uuid4().hex
    try:
        command, _cwd = manager._command(12345)
        config = Path(command[command.index("--config") + 1])
        logging = config.parent / "logback.xml"
        if variant != "production":
            properties = config.read_text(encoding="ascii").replace("pipelineCaching=false", "pipelineCaching=true")
            properties += "maxPipelinePoolSize=1\n"
            if variant == "pooled_without_spelling":
                properties += "disabledRuleIds=MORFOLOGIK_RULE_PT_BR\n"
            config.write_text(properties, encoding="ascii")
        rows, paths = run_probe(privacy_probe, config, logging, tmp_path, secret)
        print(variant + " " + "; ".join(
            f"{label.decode()}:visited={int(visited)},matches={int(matches)},pool={int(pool_matches)},inaccessible={int(inaccessible)}"
            for label, visited, matches, inaccessible, pool_matches in rows
        ))
        assert len(rows) == 5, "incomplete privacy snapshots"
        assert [label.decode() for label, *_ in rows] == [
            "before", "after_check", "after_empty_check", "after_disabled_rules", "after_restored_rules",
        ], "unexpected snapshot order"
        # Finding known retained buffers is an existence proof. Inaccessible
        # fields elsewhere limit negative claims; they cannot negate a hit.
        # Report their count and do not pretend this is an exhaustive scan.
        assert all(int(visited) > 0 for _label, visited, *_rest in rows), "empty graph scan"
        assert int(rows[0][2]) == 0
        if variant == "pooled":
            assert int(rows[1][2]) >= 2, "positive control did not detect retained speller buffers"
            assert int(rows[2][2]) >= 2, "empty check unexpectedly cleared the positive control"
        elif variant == "production":
            assert all(int(pool_matches) == 0 for *_rest, pool_matches in rows), "disabled pool retained a request marker"
        # Grammar suggestion filters use Language.spellingRules, a static
        # speller independent of the disabled top-level spelling rule and pool.
        assert int(rows[3][2]) >= 2, "positive control missed grammar-filter retention"
        assert int(rows[4][2]) >= 2, "restoring rules unexpectedly cleared retained buffers"
        assert any(b".Speller.byteBuffer." in path for path in paths), "missing retained byte buffer control"
        assert any(b".Speller.charBuffer." in path for path in paths), "missing retained char buffer control"
        if variant == "production":
            # subprocess.run has waited for the previous JVM to exit. Reuse
            # its marker to check a freshly initialized JVM, not a new marker
            # that could hide persisted state from the previous process.
            fresh, fresh_paths = run_probe(privacy_probe, config, logging, tmp_path, secret, initial_only=True)
            assert len(fresh) == 1 and fresh[0][0] == b"before"
            assert int(fresh[0][1]) > 0 and int(fresh[0][2]) == 0 and int(fresh[0][3]) == 0
            assert not fresh_paths
            print("production_fresh_jvm:matches=0,inaccessible=0")
        # Watch scratch cwd and private configuration for text/log artifacts.
        # This does not inventory every directory writable by the JVM.
        assert not list(tmp_path.iterdir())
        assert {path.name for path in config.parent.iterdir()} == {"server.properties", "logback.xml"}
        assert all(secret not in path.read_text() for path in config.parent.iterdir())
    finally:
        manager.shutdown()
    assert not config.parent.exists()
