"""Owned local JVM lifecycle; the sole owner of retry and session fallback.

The retained Popen handle owns termination. Before health checks and requests,
the OS TCP table must attribute the loopback listener to that live child. A
healthy service on a chosen port alone cannot establish process identity.
"""

from collections.abc import Callable
import atexit
import ctypes
import http.client
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, TypeVar

from .languagetool_client import LanguageToolUnavailable, _issues
from .writing_types import AssistantStatus


_T = TypeVar("_T")
_FALLBACK = "Concordância indisponível; somente ortografia."


def resource_path(relative: str) -> Path:
    """Match Task 8's source build/vendor and PyInstaller onedir layout."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base is not None else Path(__file__).resolve().parent.parent / "build/vendor"
    return root / relative


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _listener_owned(port: int, pid: int) -> bool:
    """Fail closed if ownership is unavailable. No shell or optional package.

    Windows is the supported release target. Linux /proc is also supported for
    the unit-test gate. IPv4 wildcard/public listeners never pass this check.
    """
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            size = wintypes.DWORD(0)
            query = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
            # TCP_TABLE_OWNER_PID_LISTENER (3), IPv4 (AF_INET).
            if query(None, ctypes.byref(size), False, socket.AF_INET, 3, 0) not in (0, 122):
                return False
            buffer = ctypes.create_string_buffer(size.value)
            if query(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0) != 0:
                return False
            raw = buffer.raw
            count = struct.unpack_from("<I", raw)[0]
            for index in range(count):
                state, address, local_port, _remote, _remote_port, owner = struct.unpack_from("<6I", raw, 4 + 24 * index)
                if (state == 2 and owner == pid
                        and socket.ntohs(local_port & 0xFFFF) == port
                        and struct.pack("<I", address) == socket.inet_aton("127.0.0.1")):
                    return True
            return False
        if sys.platform.startswith("linux"):
            inodes = set()
            for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
                row = line.split()
                address, local_port_hex = row[1].split(":")
                if row[3] == "0A" and address == "0100007F" and int(local_port_hex, 16) == port:
                    inodes.add(f"socket:[{row[9]}]")
            return any(os.readlink(fd) in inodes for fd in Path(f"/proc/{pid}/fd").iterdir())
    except (OSError, ValueError, struct.error):
        return False
    return False


class LanguageToolProcess:
    """Start lazily on a worker, serialize checks and own at most one retry.

    An ephemeral private directory holds configuration only, never user text.
    stdout/stderr are discarded; logging is disabled in LT and its backend.
    Call shutdown only when the shared application service is closing.
    """

    def __init__(
        self, *, resource_resolver: Callable[[str], Path] = resource_path,
        process_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        port_allocator: Callable[[], int] = _free_port,
        startup_timeout: float = 10.0, health_timeout: float = 5.0, poll_interval: float = 0.05,
    ) -> None:
        if min(startup_timeout, health_timeout, poll_interval) <= 0:
            raise ValueError("process timeouts must be positive")
        self._resource = resource_resolver
        self._process_factory = process_factory
        self._allocate_port = port_allocator
        self._startup_timeout = startup_timeout
        self._health_timeout = health_timeout
        self._poll_interval = poll_interval
        self._lock = threading.RLock()
        self._child: subprocess.Popen[bytes] | None = None
        self._config_dir: tempfile.TemporaryDirectory[str] | None = None
        self._port: int | None = None
        self._started = False
        self._restarted = False
        self._disabled = False
        self._closed = False
        self._exit_registered = False
        self._status = AssistantStatus("stopped", "spelling_only")

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._child.pid if self._child is not None else None

    def _owned(self) -> bool:
        child, port = self._child, self._port
        return (child is not None and child.poll() is None and port is not None
                and _listener_owned(port, child.pid) and child.poll() is None)

    def owns_listener(self) -> bool:
        """The HTTP transport revalidates the child after TCP connection."""
        with self._lock:
            return self._owned()

    def _set_failed(self) -> None:
        self._status = AssistantStatus("failed", "spelling_only", _FALLBACK, self._restarted)

    def _stop_child(self) -> None:
        child, self._child = self._child, None
        self._port = None
        if child is not None:
            # Popen retains the Windows process handle, so even PID reuse never
            # targets a foreign instance. No PID/port-based kill is performed.
            if child.poll() is None:
                try:
                    child.terminate()
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=1)
                except ProcessLookupError:
                    pass
            else:
                child.wait()
        if self._config_dir is not None:
            self._config_dir.cleanup()
            self._config_dir = None

    def _command(self, port: int) -> tuple[list[str], Path]:
        java = self._resource("runtime/bin/java.exe")
        server = self._resource("languagetool/languagetool-server.jar")
        if not java.is_file() or not server.is_file():
            raise LanguageToolUnavailable("Concordância indisponível: runtime local ausente.")
        self._config_dir = tempfile.TemporaryDirectory(prefix="pgn-languagetool-")
        private = Path(self._config_dir.name)
        config = private / "server.properties"
        config.write_text(
            "skipLoggingChecks=true\nskipLoggingRuleMatches=true\n"
            "cacheSize=0\nmaxCheckThreads=1\npipelineCaching=false\n",
            encoding="ascii",
        )
        logging = private / "logback.xml"
        logging.write_text('<configuration><root level="OFF"/></configuration>', encoding="ascii")
        classpath = os.pathsep.join((str(server), str(server.parent / "libs/*")))
        return [
            str(java), "-Xms64m", "-Xmx512m", f"-Dlogback.configurationFile={logging}",
            "-XX:-CreateCoredumpOnCrash", f"-XX:ErrorFile={os.devnull}",
            "-cp", classpath, "org.languagetool.server.HTTPServer",
            "--config", str(config), "--port", str(port),
        ], server.parent

    def _start_new(self) -> str:
        self._started = True
        self._status = AssistantStatus(
            "restarting" if self._restarted else "starting", "spelling_only", "", self._restarted,
        )
        try:
            # Reserve before launch to skip occupied candidates. Java cannot
            # inherit this socket: release just before spawn, then verify PID
            # ownership to close the substitution risk from that bind race.
            for _ in range(3):
                port = self._allocate_port()
                if type(port) is not int or not 1 <= port <= 65535:
                    raise LanguageToolUnavailable(_FALLBACK)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
                    if sys.platform == "win32":
                        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    try:
                        reservation.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                    command, cwd = self._command(port)
                break
            else:
                raise LanguageToolUnavailable(_FALLBACK)
            env = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH"}}
            self._child = self._process_factory(
                command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if not self._exit_registered:
                atexit.register(self.shutdown)
                self._exit_registered = True
            self._port = port
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + self._startup_timeout
            while time.monotonic() < deadline:
                if self._child.poll() is not None:
                    raise LanguageToolUnavailable(_FALLBACK)
                if self._owned():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    # The first pt-BR check initializes its pipeline. Short
                    # read timeouts created repeated server work during that
                    # warmup; give one check time while bounding every retry
                    # by the remaining total startup budget.
                    try:
                        self._check_health(min(deadline, time.monotonic() + self._health_timeout))
                        if self._owned() and time.monotonic() <= deadline:
                            self._status = AssistantStatus("ready", "full", "", self._restarted)
                            return url
                    except LanguageToolUnavailable:
                        pass
                time.sleep(min(self._poll_interval, max(0, deadline - time.monotonic())))
            raise LanguageToolUnavailable(_FALLBACK)
        except Exception:
            self._set_failed()
            self._stop_child()
            raise LanguageToolUnavailable(_FALLBACK) from None

    def _check_health(self, deadline: float) -> None:
        """One empty-text probe with an absolute budget, including HTTP framing.

        Socket read timeouts alone reset on each byte. Put the deadline below
        HTTPResponse's buffered header/chunk parsing so a dripping owned server
        cannot extend startup. No background worker or watchdog is left behind.
        """
        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("startup health deadline")
            return budget

        class BudgetReader(io.RawIOBase):
            def __init__(self, connection: socket.socket) -> None:
                super().__init__()
                self.connection = connection

            def readable(self) -> bool:
                return True

            def readinto(self, buffer: Any) -> int:
                self.connection.settimeout(remaining())
                return self.connection.recv_into(buffer)

        try:
            if self._port is None:
                raise LanguageToolUnavailable(_FALLBACK)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(remaining())
                connection.connect(("127.0.0.1", self._port))
                if not self._owned():
                    raise LanguageToolUnavailable(_FALLBACK)
                body = b"text=&language=pt-BR"
                request = (f"POST /v2/check HTTP/1.1\r\nHost: 127.0.0.1:{self._port}\r\n"
                           f"Content-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(body)}\r\n"
                           "Connection: close\r\n\r\n").encode("ascii") + body
                connection.settimeout(remaining())
                connection.sendall(request)
                response = http.client.HTTPResponse(connection)
                # HTTPResponse has not read anything yet. Replace its default
                # buffered file with one that reapplies the remaining budget
                # before every recv, including inside readline/read_chunked.
                assert response.fp is not None
                response.fp.close()
                response.fp = io.BufferedReader(BudgetReader(connection))
                try:
                    response.begin()
                    if response.status != 200:
                        raise LanguageToolUnavailable(_FALLBACK)
                    payload = response.read(1_048_577)
                    if len(payload) > 1_048_576:
                        raise LanguageToolUnavailable(_FALLBACK)
                    _issues(json.loads(payload), "", frozenset(), 0)
                    remaining()
                finally:
                    response.close()
        except (OSError, ValueError, KeyError, TypeError, IndexError, http.client.HTTPException):
            raise LanguageToolUnavailable(_FALLBACK) from None

    def start(self) -> str:
        with self._lock:
            if self._closed or self._disabled:
                raise LanguageToolUnavailable(_FALLBACK)
            if self._status.mode == "full" and self._owned():
                return f"http://127.0.0.1:{self._port}"
            if self._started:
                self._set_failed()
                raise LanguageToolUnavailable(_FALLBACK)
            return self._start_new()

    def restart_once(self) -> str:
        with self._lock:
            if self._closed or self._disabled or self._restarted:
                self._disabled = True
                self._set_failed()
                self._stop_child()
                raise LanguageToolUnavailable(_FALLBACK)
            self._restarted = True
            self._stop_child()
            try:
                return self._start_new()
            except LanguageToolUnavailable:
                self._disabled = True
                raise

    def execute(self, operation: Callable[[str], _T]) -> _T:
        """Run a local check with exactly one recovery for the entire session."""
        with self._lock:
            if self._closed or self._disabled:
                raise LanguageToolUnavailable(_FALLBACK)
            try:
                url = self.start()
                if not self._owned():
                    raise LanguageToolUnavailable(_FALLBACK)
                return operation(url)
            except LanguageToolUnavailable:
                pass
            try:
                url = self.restart_once()
                if not self._owned():
                    raise LanguageToolUnavailable(_FALLBACK)
                return operation(url)
            except LanguageToolUnavailable:
                self._disabled = True
                self._set_failed()
                self._stop_child()
                raise LanguageToolUnavailable(_FALLBACK) from None

    def status(self) -> AssistantStatus:
        # Read immutable snapshots without the analysis/startup lock: a UI
        # polling status must never wait for Java or an HTTP timeout.
        status, child = self._status, self._child
        if status.mode == "full" and (child is None or child.poll() is not None):
            return AssistantStatus("failed", "spelling_only", _FALLBACK, status.restart_attempted)
        return status

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_child()
            if self._exit_registered:
                atexit.unregister(self.shutdown)
                self._exit_registered = False
            self._status = AssistantStatus("stopped", "spelling_only", "", self._restarted)
