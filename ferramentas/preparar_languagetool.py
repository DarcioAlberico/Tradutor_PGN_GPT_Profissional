"""Prepare the offline sidecar at build time, never from application startup.

fetch -> runtime -> smoke -> validate. Archives are content addressed, staging
and rollback stay beside build/vendor, and only reduced runtime resources ship.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, BinaryIO, TYPE_CHECKING
import urllib.request
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET
import zipfile

if TYPE_CHECKING:
    from tradutor_pgn.writing_types import WritingIssue


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "recursos/languagetool-lock.json"
VENDOR = ROOT / "build/vendor"
CACHE = ROOT / "build/vendor-cache"
MANIFEST = "vendor-manifest.json"
SHIP = {"runtime", "languagetool", "LICENSES", "languagetool-lock.json", "sbom.json", "license-audit.json"}
LICENSES = ("LanguageTool-LGPL-2.1.txt", "Eclipse-Temurin-GPL2-Classpath.txt", "Eclipse-Temurin-NOTICE.txt")
HOSTS = {"languagetool.org", "github.com", "release-assets.githubusercontent.com"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _https(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("official HTTPS URL required")


def load_lock(path: Path = LOCK) -> dict[str, Any]:
    lock: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for name, version in (("languagetool", "6.6"), ("jdk", "17.0.20.1+1")):
        package = lock["packages"][name]
        _https(package["url"])
        if not re.fullmatch(r"[0-9a-f]{64}", package["sha256"]):
            raise ValueError("literal SHA-256 required")
        if package["version"] != version or "latest" in package["url"].lower():
            raise ValueError("exact approved version required")
        _safe_path(package["root"])
        for expected in package["expected"]:
            _safe_path(expected)
    return lock


class _SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(url: str) -> BinaryIO:
    _https(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SecureRedirect())
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120)


def download(package: dict[str, Any], cache: Path) -> Path:
    _https(package["url"])
    digest = package["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("literal SHA-256 required")
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        raise ValueError("symlink cache")
    target = cache / (digest + ".zip")
    if target.is_symlink():
        raise ValueError("symlink cache entry")
    if target.is_file() and sha256(target) == digest:
        return target
    with tempfile.NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with _open_url(package["url"]) as response:
                shutil.copyfileobj(response, stream, 1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if sha256(temporary) != digest:
            raise ValueError("download SHA-256 mismatch")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    parts = name.rstrip("/").split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
    if (not parts or path.is_absolute() or "\\" in name
            or any(p in ("", ".", "..") or p.endswith((" ", "."))
                   or any(ord(c) < 32 or c in ':*?<>|"' for c in p)
                   or p.split(".")[0].upper() in reserved for p in parts)):
        raise ValueError(f"unsafe archive path: {name}")
    return path


def extract_zip(archive: Path, destination: Path, package: dict[str, Any]) -> None:
    """Validate every member before creating a fresh extraction directory."""
    if sha256(archive) != package["sha256"]:
        raise ValueError("archive SHA-256 mismatch")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if len(members) > 50_000 or sum(p.file_size for p in members) > 2_000_000_000:
            raise ValueError("archive extraction budget exceeded")
        seen: set[str] = set()
        files: set[str] = set()
        for entry in members:
            path = _safe_path(entry.filename)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            key = str(path).casefold()
            if (path.parts[0] != package["root"] or key in seen
                    or mode not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError("archive root, collision or special file")
            seen.add(key)
            if not entry.is_dir():
                files.add("/".join(path.parts[1:]))
        if not set(package["expected"]) <= files:
            raise ValueError("archive missing expected files")
        if destination.exists() or destination.is_symlink():
            raise ValueError("extraction requires a fresh destination")
        destination.mkdir(parents=True)
        try:
            for entry in members:
                relative = PurePosixPath(entry.filename).parts[1:]
                if not relative:
                    continue
                target = destination.joinpath(*relative)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(entry) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        except BaseException:
            shutil.rmtree(destination)
            raise


def publish(staged: Path, current: Path) -> None:
    """Same-volume rename with rollback; callers hold the build lock."""
    if staged.is_symlink() or current.is_symlink():
        raise ValueError("symlink publication")
    backup = current.with_name(current.name + ".backup-" + uuid.uuid4().hex)
    existed = current.exists()
    if existed:
        os.replace(current, backup)
    try:
        os.replace(staged, current)
    except BaseException:
        if existed:
            os.replace(backup, current)
        raise
    if existed:
        shutil.rmtree(backup)


def _inventory(root: Path, *, shipped_only: bool = True) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("symlink/junction in prepared resources")
        if path.is_file() and (not shipped_only or relative.parts[0] in SHIP):
            files[relative.as_posix()] = sha256(path)
    return files


def write_manifest(root: Path) -> None:
    (root / MANIFEST).write_text(json.dumps({"schema": 1, "files": _inventory(root)}, indent=2) + "\n", encoding="utf-8")


def required_files(lock: dict[str, Any]) -> list[str]:
    return ["runtime/bin/java.exe", "runtime/lib/modules", "runtime/legal/java.base/LICENSE",
            "languagetool/server.properties", "languagetool/logback.xml", "languagetool-lock.json", "sbom.json", "license-audit.json",
            *("LICENSES/" + name for name in LICENSES),
            *("languagetool/" + name for name in lock["packages"]["languagetool"]["expected"])]


def validate_bundle(root: Path, *, allow_jdk: bool = False, release: bool = True, application: bool = False) -> None:
    lock = load_lock()
    permitted = SHIP | {MANIFEST} | ({"jdk", "source-manifest.json", "measurements.json", "modules.txt"} if allow_jdk else set())
    extras = set(p.name for p in root.iterdir()) - permitted
    if extras and (not application or {"jdk", "jmods", "cache", "logs", "corpus", "dados"} & extras):
        raise ValueError("unexpected bundle entries")
    for name in required_files(lock):
        if not (root / name).is_file():
            raise ValueError(f"missing bundle resource: {name}")
    if (root / "languagetool-lock.json").read_bytes() != LOCK.read_bytes():
        raise ValueError("bundle lock mismatch")
    actual = _inventory(root)
    expected = json.loads((root / MANIFEST).read_text(encoding="utf-8"))["files"]
    if actual != expected:
        raise ValueError("bundle checksum mismatch")
    audit = json.loads((root / "license-audit.json").read_text(encoding="utf-8"))
    if release and (audit.get("unresolved") != [] or audit.get("artifacts") != license_artifacts(root)):
        raise ValueError("incomplete license audit; see license-audit.json")
    forbidden = {"jdk", "jmods", "include", "cache", "logs", "corpus", "dados", "backups", "javac.exe", "jdeps.exe", "jlink.exe", "chaves-api.json"}
    for name in actual:
        path = PurePosixPath(name)
        if forbidden.intersection(p.lower() for p in path.parts) or path.suffix.lower() in {".db", ".log", ".pgn"}:
            raise ValueError(f"forbidden bundle resource: {name}")


def bundle_datas(vendor: Path = VENDOR) -> list[tuple[str, str]]:
    """PyInstaller data destinations match Task 4's resource resolver."""
    validate_bundle(vendor, allow_jdk=True)
    return [(str(vendor / name), str(PurePosixPath(name).parent))
            for name in [*_inventory(vendor), MANIFEST]]


def validate_distribution(dist: Path) -> None:
    if {p.name for p in dist.iterdir()} != {"PGN_Tradutor_Pro.exe", "_internal"}:
        raise ValueError("unexpected application distribution entries")
    validate_bundle(dist / "_internal", application=True)


def fetch(vendor: Path = VENDOR, cache: Path = CACHE) -> None:
    lock = load_lock()
    vendor.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=vendor.parent, prefix="vendor-fetch-") as work:
        staged = Path(work) / "vendor"
        staged.mkdir()
        for name, package in lock["packages"].items():
            archive = download(package, cache)
            extract_zip(archive, staged / name, package)
        shutil.copytree(ROOT / "LICENSES", staged / "LICENSES")
        shutil.copyfile(LOCK, staged / "languagetool-lock.json")
        (staged / "languagetool/server.properties").write_text("skipLoggingChecks=true\nskipLoggingRuleMatches=true\ncacheSize=0\nmaxCheckThreads=1\npipelineCaching=false\n", encoding="ascii")
        (staged / "languagetool/logback.xml").write_text('<configuration><root level="OFF"/></configuration>\n', encoding="ascii")
        (staged / "source-manifest.json").write_text(json.dumps(_inventory(staged, shipped_only=False), indent=2), encoding="utf-8")
        publish(staged, vendor)


def isolated_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ) if source is None else source
    denied = {"JAVA_HOME", "JRE_HOME", "CLASSPATH", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}
    env = {key: value for key, value in source.items() if key.upper() not in denied and not key.upper().endswith("_PROXY")}
    env["PATH"] = ""
    return env


def runtime_commands(vendor: Path, output: Path, modules: str) -> tuple[list[str], list[str]]:
    server = vendor / "languagetool/languagetool-server.jar"
    cp = os.pathsep.join((".", "libs/*"))
    # Recurse from server + unpacked language classes on the classpath. Passing
    # modular jars as roots makes jdeps resolve optional module descriptors
    # (MariaDB -> waffle.jna) that are not used by this classpath application.
    return ([str(vendor / "jdk/bin/jdeps.exe"), "--ignore-missing-deps", "--multi-release", "17", "--print-module-deps", "--recursive", "--class-path", cp, server.name, "."],
            [str(vendor / "jdk/bin/jlink.exe"), "--module-path", str(vendor / "jdk/jmods"), "--add-modules", modules,
             "--strip-debug", "--no-header-files", "--no-man-pages", "--compress=2", "--output", str(output)])


def check_measurements(measurements: dict[str, Any]) -> None:
    if measurements["startup_seconds"] > 10 or measurements["peak_rss_bytes"] > 1_000_000_000:
        raise ValueError("prototype exceeds startup/RAM budget; release decision required")


def check_smoke_issues(issues: tuple[WritingIssue, ...]) -> None:
    if not any(issue.rule_id == "GENERAL_NUMBER_AGREEMENT_ERRORS"
               and issue.category == "NOMINAL_AGREEMENT"
               and issue.original == "cavalos branco"
               and "cavalos brancos" in issue.suggestions for issue in issues):
        raise ValueError("pt-BR smoke produced no expected agreement diagnostic")


def _rss(pid: int, *, peak: bool = False) -> int:
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise OSError("cannot sample JVM RSS")
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not query(handle, ctypes.byref(counters), counters.cb):
            raise OSError("cannot read JVM RSS")
        return int(counters.PeakWorkingSetSize if peak else counters.WorkingSetSize)
    finally:
        kernel.CloseHandle(handle)


def smoke(vendor: Path = VENDOR) -> dict[str, Any]:
    """Real owned process and transport, PATH empty, proxies/Java injection removed.

    Uses the Task 4 loopback ownership checks before sending any synthetic text.
    No Internet operation occurs in this command; all requests use that adapter.
    """
    if sys.platform != "win32":
        raise ValueError("release smoke requires Windows x64")
    sys.path.insert(0, str(ROOT))
    from tradutor_pgn.languagetool_process import LanguageToolProcess
    from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter

    measurements: dict[str, Any] = {"system_java_on_path": False, "network": "owned IPv4 loopback only"}
    def spawn(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        kwargs["env"] = isolated_environment(kwargs["env"])
        return subprocess.Popen(command, **kwargs)
    process = LanguageToolProcess(resource_resolver=lambda name: vendor / name, process_factory=spawn, startup_timeout=30)
    stopped = threading.Event()
    samples: list[int] = []
    def sample() -> None:
        while not stopped.wait(0.02):
            pid = process.pid
            if pid is not None:
                try:
                    samples.append(_rss(pid))
                except OSError:
                    pass  # process may exit between PID snapshot and OpenProcess
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        start = time.perf_counter()
        url = process.start()
        measurements["startup_seconds"] = time.perf_counter() - start
        if not process.owns_listener():
            raise ValueError("sidecar ownership lost")
        pid = process.pid
        assert pid is not None
        measurements["cold_rss_bytes"] = _rss(pid)
        adapter = LanguageToolLocalAdapter(process=process, timeout=30)
        try:
            start = time.perf_counter()
            issues = adapter.check("Os cavalos branco.", frozenset())
            measurements["first_analysis_seconds"] = time.perf_counter() - start
            measurements["ready_for_first_result_seconds"] = measurements["startup_seconds"] + measurements["first_analysis_seconds"]
            check_smoke_issues(issues)
            start = time.perf_counter()
            check_smoke_issues(adapter.check("Os cavalos branco.", frozenset()))
            measurements["warm_analysis_seconds"] = time.perf_counter() - start
            measurements["warm_rss_bytes"] = _rss(pid)
            measurements["peak_rss_bytes"] = _rss(pid, peak=True)
            measurements["diagnostics"] = len(issues)
            measurements["rules"] = sorted({issue.rule_id for issue in issues})
        finally:
            adapter.shutdown()
        measurements["peak_rss_bytes"] = max([*samples, measurements["cold_rss_bytes"], measurements["warm_rss_bytes"], measurements["peak_rss_bytes"]])
        measurements["resource_bytes"] = {name: sum(p.stat().st_size for p in (vendor / name).rglob("*") if p.is_file()) for name in ("runtime", "languagetool")}
        measurements["endpoint"] = url.rsplit(":", 1)[0]  # never record a reusable port
        (vendor / "measurements.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
        check_measurements(measurements)
        return measurements
    finally:
        stopped.set()
        sampler.join(timeout=1)
        process.shutdown()


DICTIONARY_SUFFIXES = {".dict", ".dic", ".aff"}


def license_artifacts(vendor: Path) -> dict[str, str]:
    return {path.relative_to(vendor).as_posix(): sha256(path)
            for path in sorted((vendor / "languagetool").rglob("*"))
            if path.is_file() and path.suffix.lower() in DICTIONARY_SUFFIXES | {".jar"}}


def sbom(vendor: Path) -> None:
    """Preserve primary evidence; a POM declaration is not a redistribution audit.

    Shaded POMs belong to nested components, never to the containing JAR. Missing
    and inherited licenses stay unknown. No network is used or guessed license
    expression emitted. This inventory deliberately blocks release until source
    availability and dictionary-specific terms have been reviewed.
    """
    components: list[dict[str, Any]] = []
    audit: dict[str, Any] = {"schema": 1, "artifacts": license_artifacts(vendor),
                             "jars": [], "dictionaries": [], "native_files": [], "runtime_notices": [],
                             "unresolved": ["Corresponding source availability and dictionary-specific redistribution terms require review."]}
    ns = {"p": "http://maven.apache.org/POM/4.0.0"}
    for jar in sorted((vendor / "languagetool").rglob("*.jar")):
        relative = jar.relative_to(vendor).as_posix()
        record: dict[str, Any] = {"path": relative, "sha256": sha256(jar), "poms": [], "notices": []}
        nested = []
        with zipfile.ZipFile(jar) as zipped:
            if "META-INF/MANIFEST.MF" in zipped.namelist():
                manifest = re.sub(r"\r?\n ", "", zipped.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace"))
                record["manifest_fields"] = {key: value.strip() for line in manifest.splitlines()
                                             if ":" in line for key, value in [line.split(":", 1)]
                                             if key in {"Bundle-License", "Bundle-Version", "Implementation-Version", "Automatic-Module-Name", "Implementation-Title", "Specification-Version"}}
            for name in sorted(zipped.namelist()):
                if name.endswith("/"):
                    continue
                entry_path = _safe_path(name)
                is_pom = name.endswith(("pom.xml", "pom.properties"))
                is_notice = re.match(r"(?i)(licen[cs]es?|notices?|copying|copyrights?|readme|authors?)([._-]|$)", entry_path.name)
                if is_pom or is_notice:
                    output = vendor / "LICENSES/embedded" / relative / Path(*entry_path.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(zipped.read(name))
                    if is_notice:
                        record["notices"].append({"path": name, "sha256": sha256(output)})
                if name.endswith("pom.xml"):
                    pom = ET.fromstring(zipped.read(name))
                    ns = {"p": pom.tag[1:].split("}")[0] if pom.tag.startswith("{") else ""}
                    def field(key: str) -> str:
                        return pom.findtext("p:" + key, default="", namespaces=ns)
                    declarations = [{"name": item.findtext("p:name", default="", namespaces=ns),
                                     "url": item.findtext("p:url", default="", namespaces=ns),
                                     "comments": item.findtext("p:comments", default="", namespaces=ns)}
                                    for item in pom.findall("p:licenses/p:license", ns)]
                    parent = pom.find("p:parent", ns)
                    parent_id = {} if parent is None else {key: parent.findtext("p:" + key, default="", namespaces=ns)
                                                          for key in ("groupId", "artifactId", "version")}
                    metadata = {"path": name, "group": field("groupId"), "name": field("artifactId"),
                                "version": field("version"), "parent": parent_id, "license_declarations": declarations}
                    record["poms"].append(metadata)
                    component: dict[str, Any] = {"type": "library", "name": metadata["name"] or name,
                                                 "properties": [{"name": "evidence-pom", "value": relative + "!/" + name}]}
                    for key in ("group", "version"):
                        if metadata[key] and "${" not in metadata[key]:
                            component[key] = metadata[key]
                    if declarations:
                        component["licenses"] = [{"license": {"name": item["name"]}} for item in declarations if item["name"]]
                    else:
                        audit["unresolved"].append(relative + "!/" + name + ": absent or inherited license declaration")
                    nested.append(component)
                if entry_path.suffix.lower() in DICTIONARY_SUFFIXES:
                    data = zipped.read(name)
                    audit["dictionaries"].append({"path": relative + "!/" + name, "sha256": hashlib.sha256(data).hexdigest()})
                if re.search(r"(?i)\.(dll|so(?:\.\d+)*|dylib|jnilib|exe|a)$", entry_path.name):
                    native = {"path": relative + "!/" + name, "sha256": hashlib.sha256(zipped.read(name)).hexdigest()}
                    audit["native_files"].append(native)
                    nested.append({"type": "file", "name": native["path"], "hashes": [{"alg": "SHA-256", "content": native["sha256"]}]})
        if not record["poms"]:
            audit["unresolved"].append(relative + ": no embedded Maven license declaration; inspect notices/upstream")
        audit["jars"].append(record)
        component = {"type": "file", "name": relative, "bom-ref": relative,
                     "hashes": [{"alg": "SHA-256", "content": record["sha256"]}]}
        if nested:
            component["components"] = nested
        components.append(component)
    for path in sorted((vendor / "languagetool").rglob("*")):
        if path.is_file() and path.suffix.lower() in DICTIONARY_SUFFIXES:
            relative = path.relative_to(vendor).as_posix()
            audit["dictionaries"].append({"path": relative, "sha256": sha256(path)})
            components.append({"type": "file", "name": relative, "hashes": [{"alg": "SHA-256", "content": sha256(path)}]})
    for path in sorted((vendor / "runtime/legal").rglob("*")):
        if path.is_file():
            audit["runtime_notices"].append({"path": path.relative_to(vendor).as_posix(), "sha256": sha256(path)})
    for name, package in load_lock()["packages"].items():
        components.append({"type": "application", "name": name + " (upstream build input)", "version": package["version"],
                           "properties": [{"name": "upstream-archive-sha256", "value": package["sha256"]}],
                           "externalReferences": [{"type": "distribution", "url": package["url"]},
                                                  {"type": "vcs", "url": package["source"]}]})
    if (vendor / "runtime/lib/modules").is_file():
        components.append({"type": "application", "name": "Eclipse Temurin jlink runtime",
                           "version": load_lock()["packages"]["jdk"]["version"],
                           "hashes": [{"alg": "SHA-256", "content": sha256(vendor / "runtime/lib/modules")}],
                           "properties": [{"name": "complete-runtime-tree-hashes", "value": MANIFEST},
                                          {"name": "license-evidence", "value": "runtime/legal/ and LICENSES/; redistribution review incomplete"}]})
    if (vendor / "LICENSES/LanguageTool-6.6-evidence.json").is_file():
        audit["additional_primary_evidence"] = "LICENSES/LanguageTool-6.6-evidence.json"
    for name, value in (("license-audit.json", audit), ("sbom.json", {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": components})):
        (vendor / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def preserve_evidence(staged: Path, build: Path) -> None:
    output = build / "languagetool-prototype-evidence"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("measurements.json", "sbom.json", "license-audit.json", "modules.txt"):
        if (staged / name).is_file():
            shutil.copyfile(staged / name, output / name)


def runtime(vendor: Path = VENDOR) -> None:
    if sys.platform != "win32":
        raise ValueError("runtime generation requires Windows x64")
    sources = json.loads((vendor / "source-manifest.json").read_text(encoding="utf-8"))
    if any(not (vendor / name).is_file() or sha256(vendor / name) != digest for name, digest in sources.items()):
        raise ValueError("prepared source checksum mismatch; run fetch")
    with tempfile.TemporaryDirectory(dir=vendor.parent, prefix="vendor-runtime-") as work:
        staged = Path(work) / "vendor"
        shutil.copytree(vendor, staged, ignore=shutil.ignore_patterns("runtime", MANIFEST, "measurements.json", "sbom.json"))
        jdeps, _ = runtime_commands(staged, staged / "runtime", "")
        result = subprocess.run(jdeps, check=True, capture_output=True, text=True, env=isolated_environment(), cwd=staged / "languagetool")
        modules = result.stdout.strip().splitlines()[-1]
        if not re.fullmatch(r"[a-z0-9.,]+", modules):
            raise ValueError("unexpected jdeps output")
        # Reflection/service providers used by JNA, encodings and HTTPS providers.
        modules = ",".join(sorted(set(modules.split(",")) | {"jdk.unsupported", "jdk.charsets", "jdk.crypto.ec"}))
        _, jlink = runtime_commands(staged, staged / "runtime", modules)
        subprocess.run(jlink, check=True, env=isolated_environment())
        (staged / "modules.txt").write_text(modules + "\n", encoding="ascii")
        sbom(staged)
        try:
            smoke(staged)  # a failed measurement/smoke never replaces known-good vendor
        finally:
            preserve_evidence(staged, vendor.parent)
            if (staged / "measurements.json").exists():
                shutil.copyfile(staged / "measurements.json", vendor.parent / "languagetool-prototype-measurements.json")
        write_manifest(staged)
        validate_bundle(staged, allow_jdk=True, release=False)
        publish(staged, vendor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "runtime", "smoke", "validate"))
    parser.add_argument("--vendor", type=Path, default=VENDOR)
    args = parser.parse_args()
    vendor = args.vendor.resolve()
    if args.command in {"smoke", "validate"}:
        validate_bundle(vendor, allow_jdk=vendor == VENDOR.resolve(), release=args.command == "validate")
        if args.command == "smoke":
            print(json.dumps(smoke(vendor), indent=2))
        return 0
    # Exclusive creation makes simultaneous fetch/runtime fail before mutation.
    vendor.parent.mkdir(parents=True, exist_ok=True)
    guard = vendor.parent / ".languagetool-build.lock"
    guard.open("x").close()
    try:
        (fetch if args.command == "fetch" else runtime)(vendor)
    finally:
        guard.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
