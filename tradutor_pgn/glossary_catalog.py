"""Authoritative glossary records and SQLite catalog V2."""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .glossary_types import (
    GLOSSARY_PRIORITY_DEFAULT,
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_SCOPE_ALL,
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

    def initialize(self) -> None:
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

    def list_entries(self) -> CatalogSnapshot:
        """Read a coherent snapshot ordered by the stored presentation position."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN")
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
