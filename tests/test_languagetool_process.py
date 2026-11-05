"""Lifecycle tests launch actual small Python children in place of the JVM."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
import requests

from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter, LanguageToolUnavailable
from tradutor_pgn.languagetool_process import LanguageToolProcess, _listener_owned, resource_path


CHILD = '''
import json, os, sys, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs
mode, marker, port = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
count = int(marker.read_text()) + 1 if marker.exists() else 1
marker.write_text(str(count))
print("child stdout must be discarded", flush=True)
print("child stderr must be discarded", file=sys.stderr, flush=True)
if mode == "exit":
    sys.exit(2)
if mode == "hang":
    time.sleep(60)
if mode == "short_lived":
    timer = threading.Timer(3, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if data.get("text"):
            print(data["text"], flush=True)
            print(data["text"], file=sys.stderr, flush=True)
        if data.get("text") and (mode == "crash_always" or mode == "crash_first" and count == 1):
            os._exit(3)
        if mode == "slow_health":
            checks = marker.with_suffix(".checks")
            checks.write_text(str(int(checks.read_text()) + 1 if checks.exists() else 1))
            time.sleep(0.75)
        payload = {"software": {"name": "LanguageTool", "version": "99" if mode == "version" else "6.6"},
                   "language": {"code": "pt-BR"}, "matches": []}
        if mode in {"drip_body", "drip_headers"}:
            body = json.dumps(payload).encode()
            headers = b"HTTP/1.0 200 OK\\r\\nContent-Length: " + str(len(body)).encode() + b"\\r\\n\\r\\n"
            if mode == "drip_headers":
                for byte in headers:
                    self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.04)
                self.wfile.write(body)
            else:
                self.wfile.write(headers)
                for byte in body:
                    self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.02)
            return
        self.send_response(503 if mode == "unhealthy" else 200)
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())
    def log_message(self, *_args):
        pass
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "resources"
    (root / "runtime/bin").mkdir(parents=True)
    (root / "runtime/bin/java.exe").touch()
    (root / "languagetool/libs").mkdir(parents=True)
    (root / "languagetool/languagetool-server.jar").touch()
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    marker = tmp_path / "starts"
    children = []
    commands = []

    def make(mode="ready", **options):
        def launch(command, **kwargs):
            commands.append((command, kwargs, Path(command[command.index("--config") + 1]).read_text()))
            child = subprocess.Popen(
                # Windows venv python.exe is a launcher whose descendant owns
                # the socket. Use the real interpreter, as java.exe will be.
                [getattr(sys, "_base_executable", sys.executable), "-u", str(script), mode, str(marker), command[command.index("--port") + 1]],
                **kwargs,
            )
            children.append(child)
            return child

        health_options = {} if options.pop("default_health", False) else {"health_timeout": 0.1}
        return LanguageToolProcess(
            resource_resolver=lambda relative: root / relative,
            process_factory=launch, startup_timeout=options.pop("startup_timeout", 1.5),
            poll_interval=0.02, **health_options, **options,
        )

    yield make, marker, commands, children, root
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)


def test_start_validates_owned_listener_health_and_reuses_child(runtime, capfd, monkeypatch):
    make, marker, commands, _children, root = runtime
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "unsafe")
    manager = make()
    assert manager.status().state == "stopped"
    url = manager.start()
    assert url.startswith("http://127.0.0.1:")
    assert manager.status().mode == "full" and manager.status().state == "ready"
    assert manager.start() == url and marker.read_text() == "1"
    command, kwargs, config = commands[0]
    assert command[0] == str(root / "runtime/bin/java.exe")
    assert "-Xms64m" in command and "-Xmx512m" in command
    assert "org.languagetool.server.HTTPServer" in command
    assert str(root / "languagetool/languagetool-server.jar") in command[command.index("-cp") + 1]
    assert "--public" not in command and "--allow-origin" not in command and "--verbose" not in command
    assert "skipLoggingChecks=true" in config and "skipLoggingRuleMatches=true" in config
    assert kwargs["stdout"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.DEVNULL
    assert "JAVA_TOOL_OPTIONS" not in kwargs["env"] and kwargs.get("shell", False) is False
    manager.shutdown()
    assert capfd.readouterr() == ("", "")


def test_startup_waits_for_cold_pipeline_without_repeated_short_health_requests(runtime):
    make, marker, _commands, _children, _root = runtime
    manager = make("slow_health", startup_timeout=3, default_health=True)
    try:
        manager.start()
        assert manager.status().mode == "full"
        assert marker.with_suffix(".checks").read_text() == "1"
    finally:
        manager.shutdown()


@pytest.mark.parametrize("mode", ["drip_headers", "drip_body"])
def test_owned_server_dripping_cannot_extend_startup_wall_clock_budget(runtime, mode):
    make, _marker, _commands, children, _root = runtime
    manager = make(mode, startup_timeout=0.65, default_health=True)
    before = time.monotonic()
    try:
        with pytest.raises(LanguageToolUnavailable):
            manager.start()
        assert time.monotonic() - before < 1.25
        assert manager.pid is None
        assert all(child.poll() is not None for child in children)
    finally:
        manager.shutdown()


def test_repeated_unhealthy_probes_cannot_extend_the_total_startup_deadline(runtime, monkeypatch):
    from tradutor_pgn import languagetool_process as lifecycle
    make, _marker, _commands, children, _root = runtime
    class Clock:
        now = 0.0
        def advance(self, seconds):
            self.now += seconds
    clock = Clock()
    def unhealthy(deadline):
        clock.advance(deadline - clock.now)
        raise LanguageToolUnavailable("unhealthy")
    manager = make(startup_timeout=0.65)
    monkeypatch.setattr(manager, "_owned", lambda: True)
    monkeypatch.setattr(manager, "_check_health", unhealthy)
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(lifecycle.time, "sleep", clock.advance)
    with pytest.raises(LanguageToolUnavailable):
        manager.start()
    assert clock.now <= 0.65
    assert all(child.poll() is not None for child in children)
    manager.shutdown()


def test_busy_port_is_skipped_without_sending_health_or_killing_owner(runtime):
    make, marker, _commands, _children, _root = runtime
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        busy = occupied.getsockname()[1]
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            available = free.getsockname()[1]
        ports = iter((busy, available))
        manager = make(port_allocator=lambda: next(ports))
        try:
            assert manager.start() == f"http://127.0.0.1:{available}"
            assert marker.read_text() == "1"
        finally:
            manager.shutdown()
        assert occupied.getsockname()[1] == busy


@pytest.mark.parametrize("mode", ["hang", "exit", "unhealthy", "version"])
def test_startup_failure_has_safe_diagnostic_and_no_live_child(runtime, mode):
    make, _marker, _commands, children, _root = runtime
    manager = make(mode, startup_timeout=0.35)
    before = time.monotonic()
    with pytest.raises(LanguageToolUnavailable):
        manager.start()
    assert time.monotonic() - before < 2
    assert manager.status().mode == "spelling_only" and manager.status().diagnostic
    assert all(child.poll() is not None for child in children)
    manager.shutdown()


def test_healthy_foreign_listener_cannot_impersonate_live_child(runtime, monkeypatch):
    make, _marker, _commands, children, _root = runtime
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"software": {"name": "LanguageTool", "version": "6.6"},
                                         "language": {"code": "pt-BR"}, "matches": []}).encode())

        def log_message(self, *_args):
            pass

    # Occupy the selected port AFTER the manager releases its reservation,
    # while the child is alive. A port+healthcheck-only manager accepts this.
    manager = make("hang", startup_timeout=0.25)
    original_factory = manager._process_factory
    servers = []
    threads = []

    def racing_launch(command, **kwargs):
        child = original_factory(command, **kwargs)
        server = ThreadingHTTPServer(("127.0.0.1", int(command[command.index("--port") + 1])), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        return child

    monkeypatch.setattr(manager, "_process_factory", racing_launch)
    try:
        with pytest.raises(LanguageToolUnavailable):
            manager.start()
        assert received == []
        assert all(child.poll() is not None for child in children)
        # The unrelated listener (this pytest process) is still alive.
        assert servers[0].fileno() >= 0 and os.getpid() != manager.pid
    finally:
        manager.shutdown()
        for server, thread in zip(servers, threads):
            server.shutdown()
            server.server_close()
            thread.join()


def test_crashed_check_restarts_exactly_once_and_can_recover(runtime):
    make, marker, _commands, children, _root = runtime
    manager = make("crash_first")
    adapter = LanguageToolLocalAdapter(process=manager, timeout=0.2)
    try:
        assert adapter.check("segredo", frozenset()) == ()
        assert marker.read_text() == "2"
        assert manager.status().mode == "full" and manager.status().restart_attempted
        assert children[0].poll() is not None
    finally:
        adapter.shutdown()


def test_check_discards_child_payload_output_and_config_contains_no_text(runtime, capfd):
    make, _marker, commands, _children, _root = runtime
    manager = make()
    adapter = LanguageToolLocalAdapter(process=manager)
    secret = "comentário privado exclusivo do usuário"
    try:
        assert adapter.check(secret, frozenset()) == ()
        command = commands[0][0]
        config_dir = Path(command[command.index("--config") + 1]).parent
        assert all(secret not in path.read_text() for path in config_dir.iterdir())
    finally:
        adapter.shutdown()
    assert capfd.readouterr() == ("", "")
    assert not config_dir.exists()


def test_second_failure_latches_session_fallback_without_launch_loop(runtime):
    make, marker, _commands, children, _root = runtime
    manager = make("crash_always")
    adapter = LanguageToolLocalAdapter(process=manager, timeout=0.2)
    for _ in range(3):
        with pytest.raises(LanguageToolUnavailable) as error:
            adapter.check("segredo", frozenset())
        assert "segredo" not in str(error.value)
    assert marker.read_text() == "2"
    assert manager.status().mode == "spelling_only"
    assert manager.status().state == "failed" and manager.status().restart_attempted
    assert all(child.poll() is not None for child in children)
    adapter.shutdown()


def test_death_after_health_is_detected_before_text_is_sent(runtime):
    make, marker, _commands, children, _root = runtime
    manager = make()
    manager.start()
    children[0].kill()
    children[0].wait(timeout=3)
    assert manager.status().state == "failed"
    adapter = LanguageToolLocalAdapter(process=manager)
    try:
        assert adapter.check("texto", frozenset()) == ()
        assert marker.read_text() == "2"
    finally:
        adapter.shutdown()


def test_restart_once_exhaustion_and_shutdown_are_idempotent(runtime):
    make, marker, _commands, children, _root = runtime
    manager = make()
    manager.start()
    manager.restart_once()
    assert marker.read_text() == "2"
    with pytest.raises(LanguageToolUnavailable):
        manager.restart_once()
    assert all(child.poll() is not None for child in children)
    manager.shutdown()
    manager.shutdown()
    assert manager.status().state == "stopped"
    with pytest.raises(LanguageToolUnavailable):
        manager.start()


def test_missing_bundled_runtime_never_uses_system_java(runtime):
    make, _marker, commands, _children, root = runtime
    (root / "runtime/bin/java.exe").unlink()
    manager = make()
    with pytest.raises(LanguageToolUnavailable):
        manager.start()
    assert commands == []
    manager.shutdown()


def test_resource_path_uses_vendor_source_and_meipass(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert resource_path("runtime/bin/java.exe").parts[-5:] == ("build", "vendor", "runtime", "bin", "java.exe")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_path("runtime/bin/java.exe") == tmp_path / "runtime/bin/java.exe"


def test_status_publishes_starting_without_waiting_for_startup(runtime, monkeypatch):
    make, _marker, _commands, _children, _root = runtime
    manager = make("hang", startup_timeout=0.4)
    errors = []
    launched = threading.Event()
    original_factory = manager._process_factory

    def launch(command, **kwargs):
        child = original_factory(command, **kwargs)
        launched.set()
        return child

    monkeypatch.setattr(manager, "_process_factory", launch)

    def start():
        try:
            manager.start()
        except LanguageToolUnavailable as error:
            errors.append(error)

    worker = threading.Thread(target=start)
    worker.start()
    assert launched.wait(timeout=2)
    before = time.monotonic()
    status = manager.status()
    elapsed = time.monotonic() - before
    worker.join(timeout=3)
    manager.shutdown()
    assert status.state == "starting"
    assert elapsed < 0.1
    assert errors and not worker.is_alive()


def test_interpreter_exit_cleans_its_own_child_without_explicit_shutdown(runtime, tmp_path):
    _make, _marker, _commands, _children, root = runtime
    host = tmp_path / "host.py"
    output = tmp_path / "owned-child.json"
    repo = Path(__file__).resolve().parent.parent
    host.write_text(f'''
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, {str(repo)!r})
from tradutor_pgn.languagetool_process import LanguageToolProcess
root = Path({str(root)!r})
def launch(command, **kwargs):
    return subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-u",
        {str(tmp_path / "child.py")!r}, "short_lived", {str(tmp_path / "exit-starts")!r}, command[-1]], **kwargs)
manager = LanguageToolProcess(resource_resolver=lambda part: root / part, process_factory=launch)
url = manager.start()
Path({str(output)!r}).write_text(json.dumps([int(url.rsplit(":", 1)[1]), manager.pid]))
''', encoding="utf-8")
    completed = subprocess.run([sys.executable, str(host)], capture_output=True, timeout=5)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    port, pid = json.loads(output.read_text())
    assert not _listener_owned(port, pid), "normal interpreter exit left its own server running"


def test_listener_replaced_between_pid_check_and_tcp_connect_never_receives_text(runtime):
    make, marker, _commands, children, _root = runtime
    manager = make()
    received = []
    servers = []
    threads = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"software": {"name": "LanguageTool", "version": "6.6"},
                                         "language": {"code": "pt-BR"}, "matches": []}).encode())

        def log_message(self, *_args):
            pass

    class RacingSession(requests.Session):
        switched = False

        def post(self, url, **kwargs):
            if not self.switched:
                self.switched = True
                children[0].kill()
                children[0].wait(timeout=3)
                server = ThreadingHTTPServer(("127.0.0.1", int(url.split(":")[2].split("/")[0])), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                servers.append(server)
                threads.append(thread)
            return super().post(url, **kwargs)

    adapter = LanguageToolLocalAdapter(process=manager, session=RacingSession())
    try:
        assert adapter.check("comentário privado", frozenset()) == ()
        assert received == [], "a foreign service received text after a successful earlier PID check"
        assert marker.read_text() == "2" and manager.status().restart_attempted
    finally:
        adapter.shutdown()
        for server, thread in zip(servers, threads):
            server.shutdown()
            server.server_close()
            thread.join()
