"""Authoritative glossary records and SQLite catalog V2."""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
from typing import Callable, Sequence
from uuid import uuid4

from .app_config import LANGUAGE_NAMES

from .glossary_types import (
    GLOSSARY_PRIORITY_DEFAULT,
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


CATALOG_SCHEMA_VERSION = 1
CATALOG_BUSY_TIMEOUT_MS = 5000


class GlossaryCatalog:
    """Own the V2 schema and read entries with their matching global revision.

    Connections are short lived and owned by each operation. Initialization is
    explicit; reads never create a catalog or consult the legacy text/cache.
    """

    def __init__(self, db_path: str, mirror_path: str | None = None):
        self.db_path = str(db_path)
        self.mirror_path = mirror_path

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        path = Path(self.db_path).resolve().as_uri()
        conn = sqlite3.connect(
            f"{path}?mode={'rwc' if create else 'rw'}",
            uri=True,
            timeout=CATALOG_BUSY_TIMEOUT_MS / 1000,
        )
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
            conn.execute(
                """
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
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_glossary_canonical_identity
                ON glossary_entries(original_text, replacement_text, rule_type, scope)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS glossary_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.executemany(
                "INSERT OR IGNORE INTO glossary_metadata (key, value) VALUES (?, ?)",
                (("schema_version", str(CATALOG_SCHEMA_VERSION)), ("catalog_revision", "1")),
            )
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

    def export_legacy(self, path: str | None = None) -> ExportResult:
        """Publish the newest committed snapshot without replacing external edits."""
        target = Path(path or self.mirror_path or "")
        if not str(target) or target == Path("."):
            raise ValueError("Legacy mirror path is required.")
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._snapshot(conn)
            known_hash = self._metadata(conn, "legacy_mirror_hash")
            try:
                actual_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
                if (known_hash is not None and actual_hash != known_hash) or (
                    known_hash is None and actual_hash is not None
                ):
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
                contents = _serialize_entries(entries).encode("utf-8")
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
                        self._set_metadata(conn, "mirror_pending", "1")
                        self._set_metadata(conn, "mirror_error", warning)
                        return ExportResult(str(target), snapshot.catalog_revision, True, warning)
                    os.replace(temporary, target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                self._set_metadata(conn, "legacy_mirror_hash", hashlib.sha256(contents).hexdigest())
                self._set_metadata(conn, "mirror_pending", "0")
                self._set_metadata(conn, "mirror_error", "")
                return ExportResult(str(target), snapshot.catalog_revision)
            except OSError as exc:
                warning = f"Espelho legado pendente ({type(exc).__name__})."
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
        )

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
                for suffix in ("", "-wal", "-shm"):
                    Path(str(stage) + suffix).unlink(missing_ok=True)
