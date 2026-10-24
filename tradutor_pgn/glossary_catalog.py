"""Authoritative glossary records and SQLite catalog V2."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
import threading
import time
from typing import Callable, Literal, Sequence
from uuid import UUID, uuid4

from .app_config import LANGUAGE_NAMES

from .glossary_types import (
    GLOSSARY_PRIORITY_DEFAULT,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_SCOPE_ALL,
    _rule_type_alias,
    _normalize_rule_type,
    normalize_glossary_priority,
    normalize_glossary_scope,
    normalize_glossary_text,
)


@dataclass(frozen=True)
class GlossaryEntry:
    """An immutable catalog record; stable_id survives edits and reordering."""

    stable_id: str
    original_text: str
    replacement_text: str
    rule_type: str = GLOSSARY_RULE_SUGGESTION
    scope: str = GLOSSARY_SCOPE_ALL
    priority: int = GLOSSARY_PRIORITY_DEFAULT
    position: int = 0
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Entry revision must be a positive integer.")
        object.__setattr__(self, "original_text", normalize_glossary_text(self.original_text))
        object.__setattr__(self, "replacement_text", normalize_glossary_text(self.replacement_text))
        object.__setattr__(self, "rule_type", _normalize_rule_type(self.rule_type))
        object.__setattr__(self, "scope", normalize_glossary_scope(self.scope))
        object.__setattr__(self, "priority", normalize_glossary_priority(self.priority))


@dataclass(frozen=True)
class CatalogSnapshot:
    """One immutable read of the entries and their catalog revision."""

    entries: tuple[GlossaryEntry, ...]
    catalog_revision: int
    default_scope: str = GLOSSARY_SCOPE_ALL

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True)
class MutationResult:
    """Committed state, with an optional changed entry and mirror warning."""

    snapshot: CatalogSnapshot
    entry: GlossaryEntry | None = None
    mirror_pending: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class ExportResult:
    path: str
    catalog_revision: int
    mirror_pending: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class ImportRow:
    line_number: int
    status: Literal["new", "duplicate", "conflict", "invalid"]
    source: tuple
    entry: GlossaryEntry | None = None
    message: str = ""


@dataclass(frozen=True)
class ImportPreview:
    rows: tuple[ImportRow, ...]
    catalog_revision: int


@dataclass(frozen=True)
class ImportResult:
    snapshot: CatalogSnapshot
    preview: ImportPreview
    inserted_count: int
    mirror_pending: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class BackupResult:
    path: str
    catalog_revision: int


@dataclass(frozen=True)
class RestoreResult:
    snapshot: CatalogSnapshot
    mirror_pending: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class GlossaryEntryDraft:
    original_text: str
    replacement_text: str
    rule_type: str = GLOSSARY_RULE_SUGGESTION
    scope: str = GLOSSARY_SCOPE_ALL
    priority: int = GLOSSARY_PRIORITY_DEFAULT


@dataclass(frozen=True)
class GlossaryEntryChanges:
    original_text: str | None = None
    replacement_text: str | None = None
    rule_type: str | None = None
    scope: str | None = None
    priority: int | None = None


LegacyGlossaryEntry = tuple[str, str, str, int, str]


@dataclass(frozen=True)
class MigrationDuplicate:
    first_position: int
    duplicate_position: int
    identity: tuple[str, str, str, str]


@dataclass(frozen=True)
class MigrationReport:
    migrated: bool
    imported_count: int
    duplicates: tuple[MigrationDuplicate, ...] = ()
    backup_paths: tuple[str, ...] = ()
    mirror_pending: bool = False
    warning: str | None = None


class GlossaryConflictError(Exception):
    """An entry or catalog changed since the caller obtained its snapshot."""

    def __init__(
        self,
        stable_id: str | None,
        expected_revision: int,
        current_revision: int | None,
        current_entry: GlossaryEntry | None = None,
    ) -> None:
        self.stable_id = stable_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        self.current_entry = current_entry
        super().__init__(
            f"Glossary revision conflict for {stable_id or 'catalog'}: "
            f"expected {expected_revision}, current {current_revision}."
        )


class GlossaryDuplicateError(Exception):
    """The complete canonical identity is already present in the catalog."""


def canonical_identity(entry: GlossaryEntry | tuple) -> tuple[str, str, str, str]:
    """Full identity, also accepting legacy (text, text, phase, priority, scope)."""
    if isinstance(entry, GlossaryEntry):
        original, replacement, phase, scope = (
            entry.original_text, entry.replacement_text, entry.rule_type, entry.scope
        )
    else:
        original, replacement = entry[:2]
        phase = entry[2] if len(entry) >= 3 else GLOSSARY_RULE_SUGGESTION
        scope = entry[4] if len(entry) >= 5 else GLOSSARY_SCOPE_ALL
    return (
        normalize_glossary_text(original),
        normalize_glossary_text(replacement),
        _normalize_rule_type(phase),
        normalize_glossary_scope(scope),
    )


def _validated_scope(value) -> str:
    scope = normalize_glossary_scope(value)
    codes = scope.split(">") if scope else []
    if len(codes) > 2 or any(code and code not in LANGUAGE_NAMES for code in codes):
        raise ValueError(f"Unknown glossary scope: {scope!r}.")
    return scope


CATALOG_SCHEMA_VERSION = 1
CATALOG_BUSY_TIMEOUT_MS = 5000
_ENTRY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS glossary_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stable_id TEXT NOT NULL UNIQUE,
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
        original_text TEXT NOT NULL,
        replacement_text TEXT NOT NULL,
        rule_type TEXT NOT NULL DEFAULT 'suggestion'
            CHECK (rule_type IN ('suggestion', 'cleanup', 'automatic')),
        priority INTEGER NOT NULL DEFAULT 0,
        scope TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""
_METADATA_SCHEMA = """
    CREATE TABLE IF NOT EXISTS glossary_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
"""

_access_locks: dict[str, threading.RLock] = {}
_access_guard = threading.Lock()
_access_depth = threading.local()


@contextmanager
def _catalog_access(db_path: str):
    """Serialize catalog connections and replacement across threads/processes.

    The sidecar is stable across os.replace. SQLite alone cannot protect the
    interval after closing our connections and before replacing the database.
    """
    # db_path was resolved by the catalog constructor. Do not touch the
    # database file before acquiring the lock: Windows path resolution may
    # briefly open a handle which prevents another thread's os.replace.
    key = os.path.normcase(os.path.abspath(db_path))
    with _access_guard:
        lock = _access_locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=CATALOG_BUSY_TIMEOUT_MS / 1000):
        raise sqlite3.OperationalError("Glossary catalog is busy.")
    depths = getattr(_access_depth, "paths", None)
    if depths is None:
        depths = _access_depth.paths = {}
    depth = depths.get(key, 0)
    handle = None
    locked = False
    try:
        if not depth:
            handle = open(key + ".lock", "a+b")
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + CATALOG_BUSY_TIMEOUT_MS / 1000
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise sqlite3.OperationalError("Glossary catalog is busy.") from exc
                    time.sleep(0.01)
        depths[key] = depth + 1
        yield
    finally:
        if depth:
            depths[key] = depth
        else:
            depths.pop(key, None)
        if handle is not None:
            try:
                if locked:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        lock.release()


class _CatalogConnection(sqlite3.Connection):
    """Hold the replacement lock until this owned connection is closed."""

    access = None

    def close(self):
        try:
            super().close()
        finally:
            if self.access is not None:
                access, self.access = self.access, None
                access.__exit__(None, None, None)


class GlossaryCatalog:
    """Own the V2 schema and read entries with their matching global revision.

    Connections are short lived and owned by each operation. Initialization is
    explicit; reads never create a catalog or consult the legacy text/cache.
    """

    def __init__(self, db_path: str, mirror_path: str | None = None):
        self.db_path = str(db_path)
        self._access_key = str(Path(db_path).resolve())
        self.mirror_path = mirror_path

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        access = _catalog_access(self._access_key)
        access.__enter__()
        try:
            path = Path(self.db_path).resolve().as_uri()
            conn = sqlite3.connect(
                f"{path}?mode={'rwc' if create else 'rw'}",
                uri=True,
                timeout=CATALOG_BUSY_TIMEOUT_MS / 1000,
                factory=_CatalogConnection,
            )
            conn.access = access
        except BaseException:
            access.__exit__(None, None, None)
            raise
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {CATALOG_BUSY_TIMEOUT_MS}")
        except BaseException:
            conn.close()
            raise
        return conn

    def initialize(self) -> ExportResult | None:
        """Create the V2 schema once, preserving all existing records/revisions."""
        Path(self.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect(create=True)) as conn, conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_ENTRY_SCHEMA)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_canonical_identity
                ON glossary_entries(original_text, replacement_text, rule_type, scope)
                """
            )
            conn.execute(_METADATA_SCHEMA)
            conn.executemany(
                "INSERT OR IGNORE INTO glossary_metadata (key, value) VALUES (?, ?)",
                (("schema_version", str(CATALOG_SCHEMA_VERSION)), ("catalog_revision", "1")),
            )
            self._ensure_default_scope(conn)
        if self.mirror_path is not None and self._migration_completed():
            return self.export_legacy()
        return self.retry_pending_mirror()

    @staticmethod
    def _metadata(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT value FROM glossary_metadata WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO glossary_metadata (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _ensure_default_scope(self, conn: sqlite3.Connection) -> None:
        """Upgrade old V2 metadata using only a verified canonical mirror."""
        if self._metadata(conn, "default_scope") is not None:
            return
        scope = GLOSSARY_SCOPE_ALL
        if self.mirror_path is not None:
            try:
                contents = Path(self.mirror_path).read_bytes()
                if hashlib.sha256(contents).hexdigest() == self._metadata(conn, "legacy_mirror_hash"):
                    from .glossario import _read_default_scope

                    scope = _validated_scope(_read_default_scope(contents.decode("utf-8"), self.mirror_path))
            except (OSError, UnicodeError, SyntaxError, ValueError):
                pass
        self._set_metadata(conn, "default_scope", scope)

    def export_legacy(self, path: str | None = None) -> ExportResult:
        """Publish the newest committed snapshot without replacing external edits."""
        target = Path(path or self.mirror_path or "")
        if not str(target) or target == Path("."):
            raise ValueError("Legacy mirror path is required.")
        self._require_separate_file(str(target), allow_mirror=True)
        canonical = self.mirror_path is not None and target.resolve() == Path(self.mirror_path).resolve()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if canonical:
                self._ensure_default_scope(conn)
            snapshot = self._snapshot(conn)
            known_hash = self._metadata(conn, "legacy_mirror_hash")
            try:
                actual_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
                if canonical and ((known_hash is not None and actual_hash != known_hash) or (
                    known_hash is None and actual_hash is not None
                )):
                    warning = "Espelho legado divergente; revisão externa preservada."
                    self._set_metadata(conn, "mirror_pending", "1")
                    self._set_metadata(conn, "mirror_error", warning)
                    return ExportResult(str(target), snapshot.catalog_revision, True, warning)

                # Import is local to keep the catalog independent of the legacy parser.
                from .glossario import _serialize_entries

                entries = [
                    (e.original_text, e.replacement_text, e.rule_type, e.priority, e.scope)
                    for e in snapshot.entries
                ]
                contents = _serialize_entries(entries, default_scope=snapshot.default_scope).encode("utf-8")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, prefix=f".{target.name}.",
                        delete=False,
                    ) as stage:
                        temporary = Path(stage.name)
                        stage.write(contents)
                        stage.flush()
                        os.fsync(stage.fileno())
                    # Detect an edit made while preparing the temporary file.
                    latest_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
                    if latest_hash != actual_hash:
                        warning = "Espelho legado divergente; revisão externa preservada."
                        if canonical:
                            self._set_metadata(conn, "mirror_pending", "1")
                            self._set_metadata(conn, "mirror_error", warning)
                        return ExportResult(str(target), snapshot.catalog_revision, True, warning)
                    os.replace(temporary, target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                if canonical:
                    self._set_metadata(conn, "legacy_mirror_hash", hashlib.sha256(contents).hexdigest())
                    self._set_metadata(conn, "mirror_pending", "0")
                    self._set_metadata(conn, "mirror_error", "")
                return ExportResult(str(target), snapshot.catalog_revision)
            except OSError as exc:
                warning = f"Espelho legado pendente ({type(exc).__name__})."
                if canonical:
                    self._set_metadata(conn, "mirror_pending", "1")
                    self._set_metadata(conn, "mirror_error", warning)
                return ExportResult(str(target), snapshot.catalog_revision, True, warning)

    def retry_pending_mirror(self) -> ExportResult | None:
        if self.mirror_path is None:
            return None
        with closing(self._connect()) as conn:
            pending = self._metadata(conn, "mirror_pending")
        return self.export_legacy() if pending == "1" else None

    def _committed_result(
        self, snapshot: CatalogSnapshot, entry: GlossaryEntry | None = None,
    ) -> MutationResult:
        if self.mirror_path is None:
            return MutationResult(snapshot, entry)
        try:
            mirror = self.export_legacy()
        except (sqlite3.Error, OSError) as exc:
            warning = f"Espelho legado pendente ({type(exc).__name__})."
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._set_metadata(conn, "mirror_pending", "1")
                    self._set_metadata(conn, "mirror_error", warning)
            except (sqlite3.Error, OSError):
                # The mutation already committed mirror_pending with its data.
                # A lock must not turn that success into an apparent failure.
                pass
            return MutationResult(snapshot, entry, True, warning)
        return MutationResult(snapshot, entry, mirror.mirror_pending, mirror.warning)

    def list_entries(self) -> CatalogSnapshot:
        """Read a coherent snapshot ordered by the stored presentation position."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN")
            return self._snapshot(conn)

    @staticmethod
    def _snapshot(conn: sqlite3.Connection) -> CatalogSnapshot:
        row = conn.execute(
            "SELECT value FROM glossary_metadata WHERE key = 'catalog_revision'"
        ).fetchone()
        if row is None:
            raise ValueError("Glossary catalog has no catalog_revision.")
        rows = conn.execute(
            """
            SELECT stable_id, original_text, replacement_text, rule_type, scope,
                   priority, position, revision, created_at, updated_at
            FROM glossary_entries ORDER BY position, id
            """
        ).fetchall()
        return CatalogSnapshot(
            entries=tuple(GlossaryEntry(**dict(entry)) for entry in rows),
            catalog_revision=int(row[0]),
            default_scope=GlossaryCatalog._metadata(conn, "default_scope") or GLOSSARY_SCOPE_ALL,
        )

    @staticmethod
    def _preview_import(entries: Sequence[LegacyGlossaryEntry], snapshot: CatalogSnapshot) -> ImportPreview:
        identities = {canonical_identity(entry) for entry in snapshot.entries}
        replacements = {}
        for original, replacement, phase, scope in identities:
            replacements.setdefault((original, phase, scope), set()).add(replacement)
        rows = []
        for line_number, raw in enumerate(entries, 1):
            source = tuple(raw) if isinstance(raw, (tuple, list)) else (raw,)
            try:
                prepared, _ = GlossaryCatalog._prepare_legacy([raw])
                entry = prepared[0]
                priority = raw[3] if len(raw) >= 4 else 0
                if priority not in (None, "") and (
                    isinstance(priority, bool) or str(int(priority)) != str(priority).strip()
                ):
                    raise ValueError("Prioridade precisa ser um número inteiro.")
                if not all(isinstance(value, str) for value in raw[:2]):
                    raise ValueError("Original e substituição precisam ser textos.")
                if not entry.original_text or (not entry.replacement_text and entry.rule_type != GLOSSARY_RULE_CLEANUP):
                    raise ValueError("Original ou substituição vazios.")
            except (ValueError, TypeError, IndexError) as exc:
                rows.append(ImportRow(line_number, "invalid", source, message=str(exc)))
                continue
            identity = canonical_identity(entry)
            original, replacement, phase, scope = identity
            group = (original, phase, scope)
            if identity in identities:
                status = "duplicate"
            elif group in replacements and replacement not in replacements[group]:
                status = "conflict"
            else:
                status = "new"
                identities.add(identity)
                replacements.setdefault(group, set()).add(replacement)
            rows.append(ImportRow(line_number, status, source, entry))
        return ImportPreview(tuple(rows), snapshot.catalog_revision)

    def preview_import(self, entries: Sequence[LegacyGlossaryEntry]) -> ImportPreview:
        """Classify every source row without changing the catalog."""
        return self._preview_import(entries, self.list_entries())

    def import_entries(
        self, entries: Sequence[LegacyGlossaryEntry], mode: Literal["append"],
        expected_catalog_revision: int,
    ) -> ImportResult:
        """Append only new identities in one transaction matching the preview."""
        if mode != "append":
            raise ValueError("Only append import is supported.")
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_catalog_revision(conn, expected_catalog_revision)
            snapshot = self._snapshot(conn)
            preview = self._preview_import(entries, snapshot)
            accepted = [row.entry for row in preview.rows if row.status == "new"]
            for offset, entry in enumerate(accepted, len(snapshot.entries)):
                self._insert_legacy_entry(conn, GlossaryEntry(
                    stable_id=entry.stable_id, original_text=entry.original_text,
                    replacement_text=entry.replacement_text, rule_type=entry.rule_type,
                    priority=entry.priority, scope=entry.scope, position=offset,
                ))
            if accepted:
                self._increment_catalog_revision(conn)
            snapshot = self._snapshot(conn)
        result = self._committed_result(snapshot) if accepted else MutationResult(snapshot)
        return ImportResult(snapshot, preview, len(accepted), result.mirror_pending, result.warning)

    def _require_separate_file(self, path: str, *, allow_mirror: bool = False) -> Path:
        target = Path(path).resolve()
        protected = [Path(self.db_path + suffix).resolve() for suffix in ("", "-wal", "-shm", ".lock")]
        if self.mirror_path is not None and not allow_mirror:
            protected.append(Path(self.mirror_path).resolve())
        for source in protected:
            if target == source or (target.exists() and source.exists() and target.samefile(source)):
                raise ValueError("Destination must be separate from the catalog and its mirror/sidecars.")
        return target

    @staticmethod
    def _copy_database(source: str, target: Path) -> None:
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(target)) as copied:
                original.backup(copied)

    @staticmethod
    def _validate_backup(conn: sqlite3.Connection) -> CatalogSnapshot:
        if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("Glossary backup failed SQLite integrity check.")
        objects = conn.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if {tuple(row) for row in objects} != {
            ("table", "glossary_entries"), ("table", "glossary_metadata"),
            ("index", "idx_glossary_canonical_identity"),
        }:
            raise ValueError("Incompatible glossary backup schema objects.")

        def normalize_schema(sql):
            return " ".join(sql.split()).replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE")

        for name, expected in (("glossary_entries", _ENTRY_SCHEMA), ("glossary_metadata", _METADATA_SCHEMA)):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            if normalize_schema(sql) != normalize_schema(expected):
                raise ValueError("Incompatible glossary backup table schema or constraints.")
        indexes = {}
        for index in conn.execute("PRAGMA index_list(glossary_entries)"):
            # The name is database data; quote it as an SQL string literal.
            quoted = index[1].replace("'", "''")
            fields = tuple(row[2] for row in conn.execute(f"PRAGMA index_info('{quoted}')"))
            if index[2] and not index[4]:
                indexes[index[1]] = fields
        if indexes.get("idx_glossary_canonical_identity") != (
            "original_text", "replacement_text", "rule_type", "scope"
        ) or ("stable_id",) not in indexes.values():
            raise ValueError("Incompatible glossary backup identity indexes.")
        if GlossaryCatalog._metadata(conn, "schema_version") != str(CATALOG_SCHEMA_VERSION):
            raise ValueError("Incompatible glossary backup version.")
        snapshot = GlossaryCatalog._snapshot(conn)
        if snapshot.catalog_revision < 1:
            raise ValueError("Invalid glossary backup catalog revision.")
        GlossaryCatalog._validate_migration(conn, len(snapshot.entries))
        raw_rows = conn.execute("SELECT * FROM glossary_entries ORDER BY position, id").fetchall()
        for raw, entry in zip(raw_rows, snapshot.entries):
            UUID(entry.stable_id)
            if not entry.original_text or (not entry.replacement_text and entry.rule_type != GLOSSARY_RULE_CLEANUP):
                raise ValueError("Invalid glossary backup text.")
            if any(raw[field] != getattr(entry, field) for field in (
                "original_text", "replacement_text", "rule_type", "scope", "priority",
            )) or not isinstance(raw["revision"], int) or not isinstance(raw["priority"], int):
                raise ValueError("Invalid glossary backup entry values.")
        scope = snapshot.default_scope
        if scope != _validated_scope(scope):
            raise ValueError("Invalid glossary backup default scope.")
        return snapshot

    def backup(self, destination: str) -> BackupResult:
        """Publish a consistent SQLite backup, including committed WAL data."""
        target = self._require_separate_file(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.backup-", delete=False) as temp:
            stage = Path(temp.name)
        try:
            with closing(self._connect()) as source:
                with closing(sqlite3.connect(stage)) as copied:
                    source.backup(copied)
                    copied.row_factory = sqlite3.Row
                    snapshot = self._validate_backup(copied)
                    copied.execute("PRAGMA journal_mode = DELETE")
            with stage.open("r+b") as contents:
                os.fsync(contents.fileno())
            os.replace(stage, target)
            return BackupResult(str(target), snapshot.catalog_revision)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(stage) + suffix).unlink(missing_ok=True)

    def restore(self, backup_path: str, expected_catalog_revision: int) -> RestoreResult:
        """Validate a staged backup, then replace after CAS with no open owned handles."""
        source = self._require_separate_file(backup_path)
        target = Path(self.db_path).resolve()
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.restore-", delete=False) as temp:
            stage = Path(temp.name)
        try:
            self._copy_database(str(source), stage)
            with closing(sqlite3.connect(stage)) as restored:
                restored.row_factory = sqlite3.Row
                backup_snapshot = self._validate_backup(restored)
                restored.execute("PRAGMA journal_mode = DELETE")
            with _catalog_access(self._access_key):
                with closing(self._connect()) as current, current:
                    current.execute("BEGIN IMMEDIATE")
                    self._require_catalog_revision(current, expected_catalog_revision)
                    snapshot = self._snapshot(current)
                    mirror_hash = self._metadata(current, "legacy_mirror_hash")
                revision = max(
                    snapshot.catalog_revision, backup_snapshot.catalog_revision,
                    *(entry.revision for entry in snapshot.entries),
                    *(entry.revision for entry in backup_snapshot.entries),
                ) + 1
                with closing(sqlite3.connect(stage)) as restored, restored:
                    restored.execute("BEGIN IMMEDIATE")
                    self._set_metadata(restored, "catalog_revision", str(revision))
                    self._set_metadata(restored, "default_scope", backup_snapshot.default_scope)
                    self._set_metadata(restored, "migration_completed", "1")
                    # All old per-entry tokens must fail, including IDs which
                    # disappeared after this backup and are now reintroduced.
                    restored.execute("UPDATE glossary_entries SET revision = ?", (revision,))
                    restored.execute("DELETE FROM glossary_metadata WHERE key='legacy_mirror_hash'")
                    if mirror_hash is not None:
                        self._set_metadata(restored, "legacy_mirror_hash", mirror_hash)
                    self._set_metadata(restored, "mirror_pending", "1" if self.mirror_path else "0")
                    self._set_metadata(restored, "mirror_error", "")
                with closing(sqlite3.connect(stage)) as restored:
                    restored.row_factory = sqlite3.Row
                    staged_snapshot = self._snapshot(restored)
                    restored.execute("PRAGMA journal_mode = WAL")
                # Checkpoint and leave DELETE mode before closing the last
                # owned connection: no WAL belonging to the old inode survives.
                with closing(self._connect()) as current:
                    checkpoint = current.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint[0]:
                        raise sqlite3.OperationalError("Glossary catalog has active readers.")
                    current.execute("PRAGMA journal_mode = DELETE")
                try:
                    with stage.open("r+b") as contents:
                        os.fsync(contents.fileno())
                    os.replace(stage, target)
                except BaseException:
                    # Publication failed: keep the original catalog's WAL
                    # behavior as well as its data and revisions.
                    with closing(self._connect()) as current:
                        current.execute("PRAGMA journal_mode = WAL")
                    raise
                # The staged image already carries WAL mode and the result.
                # No post-publication read may turn this success into failure.
                result = self._committed_result(staged_snapshot)
                return RestoreResult(result.snapshot, result.mirror_pending, result.warning)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(stage) + suffix).unlink(missing_ok=True)

    @staticmethod
    def _entry(conn: sqlite3.Connection, stable_id: str) -> GlossaryEntry | None:
        row = conn.execute(
            """SELECT stable_id, original_text, replacement_text, rule_type, scope,
                      priority, position, revision, created_at, updated_at
               FROM glossary_entries WHERE stable_id = ?""", (stable_id,),
        ).fetchone()
        return GlossaryEntry(**dict(row)) if row is not None else None

    @staticmethod
    def _require_catalog_revision(conn: sqlite3.Connection, expected: int) -> None:
        row = conn.execute(
            "SELECT value FROM glossary_metadata WHERE key = 'catalog_revision'"
        ).fetchone()
        current = int(row[0]) if row is not None else None
        if current != expected:
            raise GlossaryConflictError(None, expected, current)

    @staticmethod
    def _require_entry_revision(
        conn: sqlite3.Connection, stable_id: str, expected: int,
    ) -> GlossaryEntry:
        current = GlossaryCatalog._entry(conn, stable_id)
        if current is None or current.revision != expected:
            raise GlossaryConflictError(
                stable_id, expected, current.revision if current else None, current,
            )
        return current

    def _increment_catalog_revision(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE glossary_metadata SET value = CAST(value AS INTEGER) + 1 "
            "WHERE key = 'catalog_revision'"
        )
        if self.mirror_path is not None:
            # Persist recovery before committing, even if export cannot connect.
            self._set_metadata(conn, "mirror_pending", "1")

    @staticmethod
    def _compact_positions(conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id FROM glossary_entries ORDER BY position, id").fetchall()
        conn.executemany(
            "UPDATE glossary_entries SET position = ? WHERE id = ?",
            ((position, row[0]) for position, row in enumerate(rows)),
        )

    def add(self, draft: GlossaryEntryDraft, expected_catalog_revision: int) -> MutationResult:
        """Append a new entry only when the caller's catalog snapshot is current."""
        candidate = GlossaryEntry(
            stable_id=str(uuid4()), original_text=draft.original_text,
            replacement_text=draft.replacement_text, rule_type=draft.rule_type,
            scope=draft.scope, priority=draft.priority,
        )
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_catalog_revision(conn, expected_catalog_revision)
            position = conn.execute("SELECT COUNT(*) FROM glossary_entries").fetchone()[0]
            try:
                conn.execute(
                    """INSERT INTO glossary_entries
                       (stable_id, original_text, replacement_text, rule_type,
                        scope, priority, position, revision)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                    (candidate.stable_id, candidate.original_text, candidate.replacement_text,
                     candidate.rule_type, candidate.scope, candidate.priority, position),
                )
            except sqlite3.IntegrityError as exc:
                raise GlossaryDuplicateError(canonical_identity(candidate)) from exc
            self._increment_catalog_revision(conn)
            result = MutationResult(self._snapshot(conn), self._entry(conn, candidate.stable_id))
        return self._committed_result(result.snapshot, result.entry)

    def update(
        self, stable_id: str, expected_revision: int, changes: GlossaryEntryChanges,
    ) -> MutationResult:
        """Edit precisely one matching ID/revision; other entries may change concurrently."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            old = self._require_entry_revision(conn, stable_id, expected_revision)
            values = {
                name: getattr(changes, name) if getattr(changes, name) is not None else getattr(old, name)
                for name in ("original_text", "replacement_text", "rule_type", "scope", "priority")
            }
            candidate = GlossaryEntry(
                stable_id=stable_id, position=old.position, revision=old.revision,
                created_at=old.created_at, updated_at=old.updated_at, **values,
            )
            try:
                cursor = conn.execute(
                    """UPDATE glossary_entries SET original_text = ?, replacement_text = ?,
                       rule_type = ?, scope = ?, priority = ?, revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                       WHERE stable_id = ? AND revision = ?""",
                    (candidate.original_text, candidate.replacement_text, candidate.rule_type,
                     candidate.scope, candidate.priority, stable_id, expected_revision),
                )
            except sqlite3.IntegrityError as exc:
                raise GlossaryDuplicateError(canonical_identity(candidate)) from exc
            if cursor.rowcount != 1:
                self._require_entry_revision(conn, stable_id, expected_revision)
                raise GlossaryConflictError(stable_id, expected_revision, None)
            self._increment_catalog_revision(conn)
            result = MutationResult(self._snapshot(conn), self._entry(conn, stable_id))
        return self._committed_result(result.snapshot, result.entry)

    def delete(self, stable_id: str, expected_revision: int) -> MutationResult:
        """Remove exactly the requested revision and close the position gap."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            old = self._require_entry_revision(conn, stable_id, expected_revision)
            cursor = conn.execute(
                "DELETE FROM glossary_entries WHERE stable_id = ? AND revision = ?",
                (stable_id, expected_revision),
            )
            if cursor.rowcount != 1:
                self._require_entry_revision(conn, stable_id, expected_revision)
                raise GlossaryConflictError(stable_id, expected_revision, None)
            self._compact_positions(conn)
            self._increment_catalog_revision(conn)
            result = MutationResult(self._snapshot(conn), old)
        return self._committed_result(result.snapshot, result.entry)

    def deduplicate(self, expected_catalog_revision: int) -> MutationResult:
        """Keep the first full identity of a current snapshot and compact order."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_catalog_revision(conn, expected_catalog_revision)
            seen: set[tuple[str, str, str, str]] = set()
            normalize: list[GlossaryEntry] = []
            rows = conn.execute(
                """SELECT stable_id, original_text, replacement_text, rule_type, scope,
                          priority, position, revision, created_at, updated_at
                   FROM glossary_entries ORDER BY position, id"""
            ).fetchall()
            fields = ("original_text", "replacement_text", "rule_type", "scope", "priority")
            for row in rows:
                entry = GlossaryEntry(**dict(row))
                identity = canonical_identity(entry)
                if identity in seen:
                    conn.execute(
                        "DELETE FROM glossary_entries WHERE stable_id = ?", (entry.stable_id,)
                    )
                else:
                    seen.add(identity)
                    if any(row[field] != getattr(entry, field) for field in fields):
                        normalize.append(entry)
            for entry in normalize:
                conn.execute(
                    """UPDATE glossary_entries
                       SET original_text = ?, replacement_text = ?, rule_type = ?,
                           scope = ?, priority = ?, revision = revision + 1,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE stable_id = ? AND revision = ?""",
                    (entry.original_text, entry.replacement_text, entry.rule_type,
                     entry.scope, entry.priority, entry.stable_id, entry.revision),
                )
            self._compact_positions(conn)
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_canonical_identity
                   ON glossary_entries(original_text, replacement_text, rule_type, scope)"""
            )
            self._increment_catalog_revision(conn)
            result = MutationResult(self._snapshot(conn))
        return self._committed_result(result.snapshot)

    @staticmethod
    def _backup_file(source: Path, *, database: bool = False) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        base = source.with_name(f"{source.name}.{stamp}.bak")
        attempt = 0
        while True:
            target = base if attempt == 0 else base.with_name(f"{base.name}.{attempt}")
            try:
                with target.open("xb"):
                    pass
                break
            except FileExistsError:
                attempt += 1
        try:
            if database:
                with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
                    with closing(sqlite3.connect(target)) as backup:
                        original.backup(backup)
            else:
                with source.open("rb") as original, target.open("wb") as backup:
                    shutil.copyfileobj(original, backup)
            return str(target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _prepare_legacy(entries: Sequence[LegacyGlossaryEntry]) -> tuple[list[GlossaryEntry], tuple[MigrationDuplicate, ...]]:
        prepared = []
        duplicates = []
        seen = {}
        known = set(LANGUAGE_NAMES)
        for source_position, raw in enumerate(entries, 1):
            if not isinstance(raw, (tuple, list)) or not 2 <= len(raw) <= 5:
                raise ValueError(f"Invalid legacy glossary entry at position {source_position}.")
            phase = raw[2] if len(raw) >= 3 else None
            if phase is not None and str(phase).strip() and _rule_type_alias(phase) is None:
                raise ValueError(f"Unknown legacy rule type at position {source_position}: {phase!r}.")
            scope = normalize_glossary_scope(raw[4] if len(raw) >= 5 else None)
            codes = scope.split(">") if scope else []
            if any(code and code not in known for code in codes) or len(codes) > 2:
                raise ValueError(f"Unknown legacy scope at position {source_position}: {scope!r}.")
            entry = GlossaryEntry(
                stable_id=str(uuid4()), original_text=raw[0], replacement_text=raw[1],
                rule_type=phase, scope=scope,
                priority=raw[3] if len(raw) >= 4 else GLOSSARY_PRIORITY_DEFAULT,
                position=len(prepared),
            )
            identity = canonical_identity(entry)
            if identity in seen:
                duplicates.append(MigrationDuplicate(seen[identity], source_position, identity))
            else:
                seen[identity] = source_position
                prepared.append(entry)
        return prepared, tuple(duplicates)

    @staticmethod
    def _insert_legacy_entry(conn: sqlite3.Connection, entry: GlossaryEntry) -> None:
        conn.execute(
            """INSERT INTO glossary_entries
               (stable_id, original_text, replacement_text, rule_type, priority,
                scope, position, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.stable_id, entry.original_text, entry.replacement_text,
             entry.rule_type, entry.priority, entry.scope, entry.position, entry.revision),
        )

    @staticmethod
    def _validate_migration(conn: sqlite3.Connection, expected: int) -> None:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Migrated glossary failed SQLite integrity check.")
        rows = conn.execute(
            "SELECT original_text, replacement_text, rule_type, scope, position "
            "FROM glossary_entries ORDER BY position, id"
        ).fetchall()
        if len(rows) != expected or [row[4] for row in rows] != list(range(expected)):
            raise ValueError("Migrated glossary count or positions are invalid.")
        if len({tuple(row[:4]) for row in rows}) != expected:
            raise ValueError("Migrated glossary contains duplicate identities.")
        known = set(LANGUAGE_NAMES)
        for row in rows:
            if _rule_type_alias(row[2]) != row[2]:
                raise ValueError("Migrated glossary contains an invalid rule type.")
            scope = row[3]
            codes = scope.split(">") if scope else []
            if scope != normalize_glossary_scope(scope) or len(codes) > 2 or any(
                code and code not in known for code in codes
            ):
                raise ValueError("Migrated glossary contains an invalid scope.")

    def _migration_completed(self) -> bool:
        if not Path(self.db_path).exists():
            return False
        with closing(self._connect()) as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not {"glossary_entries", "glossary_metadata"} <= tables:
                raise ValueError("Incompatible glossary catalog schema.")
            version = conn.execute(
                "SELECT value FROM glossary_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version is None or version[0] != str(CATALOG_SCHEMA_VERSION):
                raise ValueError("Incompatible glossary catalog version.")
            marker = conn.execute(
                "SELECT value FROM glossary_metadata WHERE key = 'migration_completed'"
            ).fetchone()
            return marker is not None and marker[0] == "1"

    def migrate_legacy(
        self,
        load_entries: Callable[[], Sequence[LegacyGlossaryEntry]],
        legacy_db_path: str | None = None,
    ) -> MigrationReport:
        """Import the legacy text once, after recoverable backups and before commit."""
        if self.mirror_path is None:
            raise ValueError("Legacy text path is required for migration backups.")
        source = Path(self.mirror_path)
        if self._migration_completed():
            return MigrationReport(migrated=False, imported_count=0)
        if not source.is_file():
            raise FileNotFoundError(f"Legacy glossary text is missing: {source}")

        backup_paths = [self._backup_file(source)]
        if legacy_db_path is not None and Path(legacy_db_path).exists():
            backup_paths.append(self._backup_file(Path(legacy_db_path), database=True))

        backed_up_text = Path(backup_paths[0]).read_bytes()
        from .glossario import _read_default_scope

        default_scope = _validated_scope(_read_default_scope(backed_up_text.decode("utf-8"), str(source)))
        entries, duplicates = self._prepare_legacy(load_entries())
        destination = Path(self.db_path)
        new_catalog = not destination.exists()
        if new_catalog:
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = destination.with_name(f".{destination.name}.migration-{uuid4().hex}.db")
            catalog = GlossaryCatalog(str(stage), self.mirror_path)
        else:
            stage = None
            catalog = self
        try:
            catalog.initialize()
            with closing(catalog._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                marker = conn.execute(
                    "SELECT value FROM glossary_metadata WHERE key = 'migration_completed'"
                ).fetchone()
                if marker is not None and marker[0] == "1":
                    return MigrationReport(migrated=False, imported_count=0)
                if conn.execute("SELECT COUNT(*) FROM glossary_entries").fetchone()[0]:
                    raise ValueError("Unmarked catalog already contains glossary entries.")
                for entry in entries:
                    self._insert_legacy_entry(conn, entry)
                self._validate_migration(conn, len(entries))
                if source.read_bytes() != backed_up_text:
                    raise ValueError("Legacy glossary text changed during migration.")
                conn.execute(
                    "INSERT INTO glossary_metadata (key, value) VALUES ('migration_completed', '1')"
                )
                self._set_metadata(conn, "legacy_mirror_hash", hashlib.sha256(backed_up_text).hexdigest())
                self._set_metadata(conn, "default_scope", default_scope)
                self._set_metadata(conn, "mirror_pending", "1")
            if stage is not None:
                with closing(catalog._connect()) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                try:
                    os.link(stage, destination)
                except FileExistsError:
                    if self._migration_completed():
                        return MigrationReport(migrated=False, imported_count=0)
                    raise FileExistsError(f"Catalog appeared during migration: {destination}")
            mirror = self.export_legacy()
            return MigrationReport(
                True, len(entries), duplicates, tuple(backup_paths),
                mirror.mirror_pending, mirror.warning,
            )
        finally:
            if stage is not None:
                for suffix in ("", "-wal", "-shm", ".lock"):
                    Path(str(stage) + suffix).unlink(missing_ok=True)
