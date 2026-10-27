"""Global personal vocabulary with atomic publication and process-safe mutations.

The adjacent lock file is permanent: replacing the JSON or unlinking a lock
must never give two writers different lock identities. Reads consult the disk
so other instances' additions and removals are immediately visible.
"""

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import sys
import time
import unicodedata
import uuid

from .app_paths import data_path


PERSONAL_DICTIONARY_FILENAME = "vocabulario-pessoal.json"
_LOGGER = logging.getLogger(__name__)


class DictionaryLockTimeout(TimeoutError):
    """Another writer did not release the personal dictionary in time."""


def _key(word: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", word).casefold())


def _validate_word(word: str) -> None:
    if not isinstance(word, str) or not word.strip():
        raise ValueError("personal dictionary words must be non-empty strings")


class PersonalDictionary:
    def __init__(
        self, path: str | os.PathLike[str] | None = None, *, lock_timeout: float = 5.0,
    ) -> None:
        if not math.isfinite(lock_timeout) or lock_timeout < 0:
            raise ValueError("lock_timeout must be finite and non-negative")
        self.path = Path(path if path is not None else data_path(PERSONAL_DICTIONARY_FILENAME)).resolve()
        self.lock_timeout = lock_timeout

    def _read(self) -> tuple[dict[str, str], bytes | None]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}, None
        # Permission and other I/O failures propagate; treating them as empty
        # would let the next write erase the previous vocabulary.
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict) and type(data.get("schema_version")) is int:
            if data["schema_version"] != 1:
                raise ValueError("unsupported personal dictionary schema_version")
            words = data.get("words")
            if isinstance(words, list) and all(isinstance(word, str) and word.strip() for word in words):
                result: dict[str, str] = {}
                for word in words:
                    result.setdefault(_key(word), word)
                return result, None
        _LOGGER.warning("Personal dictionary is corrupt: %s; original will be preserved before recovery", self.path)
        return {}, raw

    def load(self) -> list[str]:
        """Read a validated snapshot; missing/corrupt vocabulary is empty."""
        words, _ = self._read()
        return sorted(words.values(), key=lambda word: (_key(word), word))

    def list_words(self) -> list[str]:
        return self.load()

    def contains(self, word: str) -> bool:
        _validate_word(word)
        words, _ = self._read()
        return _key(word) in words

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+b") as lock_file:
            if sys.platform == "win32":
                import msvcrt

                if lock_file.seek(0, os.SEEK_END) == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()

                def acquire() -> None:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

                def release() -> None:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                def acquire() -> None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                def release() -> None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    acquire()
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise DictionaryLockTimeout(f"Timed out acquiring personal dictionary lock: {lock_path}") from exc
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            try:
                yield
            finally:
                release()

    def _publish(self, words: dict[str, str], corrupt: bytes | None) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(
                    {"schema_version": 1, "words": sorted(words.values(), key=lambda word: (_key(word), word))},
                    file, ensure_ascii=False, indent=2,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            if corrupt is not None:
                backup = self.path.with_name(f"{self.path.name}.corrompido-{uuid.uuid4().hex}")
                # Copy instead of moving: even a failed replace leaves the
                # original at its original path as well as the recovery copy.
                backup.write_bytes(corrupt)
                _LOGGER.warning("Corrupt personal dictionary preserved at %s", backup)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def add(self, word: str) -> bool:
        """Persist a word, preserving the first spelling; report changes."""
        _validate_word(word)
        with self._locked():
            words, corrupt = self._read()
            if _key(word) in words:
                return False
            words[_key(word)] = word
            self._publish(words, corrupt)
        return True

    def remove(self, word: str) -> bool:
        """Remove all equivalent spellings without losing concurrent additions."""
        _validate_word(word)
        with self._locked():
            words, corrupt = self._read()
            if words.pop(_key(word), None) is None:
                return False
            self._publish(words, corrupt)
        return True
