"""Contracts for the authoritative glossary catalog, independent of the UI."""

from dataclasses import FrozenInstanceError, replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

from tradutor_pgn import app_paths, glossario, glossary_types
from tradutor_pgn import glossary_catalog
from tradutor_pgn.glossary_catalog import (
    CatalogSnapshot,
    GlossaryEntry,
    canonical_identity,
)


class GlossaryCatalogModelTests(unittest.TestCase):
    def setUp(self):
        self.entry = GlossaryEntry(
            stable_id="c30fb6dc-3e96-44a0-a431-0cde074f659e",
            original_text="knight",
            replacement_text="cavalo",
            rule_type="suggestion",
            scope="pt",
            priority=0,
            position=0,
            revision=1,
            created_at="2026-10-23 12:00:00",
            updated_at="2026-10-23 12:00:00",
        )

    def test_phase_and_scope_are_part_of_identity(self):
        self.assertEqual(
            canonical_identity(self.entry), ("knight", "cavalo", "suggestion", "pt")
        )
        self.assertNotEqual(
            canonical_identity(self.entry),
            canonical_identity(replace(self.entry, rule_type="cleanup")),
        )
        self.assertNotEqual(
            canonical_identity(self.entry),
            canonical_identity(replace(self.entry, scope="it")),
        )

    def test_priority_position_and_persistent_identity_do_not_change_identity(self):
        changed = replace(
            self.entry,
            priority=9,
            position=100,
            stable_id="c366297f-57ba-4474-aea6-59f596ec146b",
            revision=2,
        )
        self.assertEqual(canonical_identity(self.entry), canonical_identity(changed))

    def test_text_ends_aliases_and_scope_are_normalized(self):
        entry = replace(
            self.entry,
            original_text=" \tKnight fork\n",
            replacement_text=" garfo de cavalo  ",
            rule_type=" Automático ",
            scope=" en > pt ",
        )
        self.assertEqual(entry.original_text, "Knight fork")
        self.assertEqual(entry.replacement_text, "garfo de cavalo")
        self.assertEqual(entry.rule_type, "automatic")
        self.assertEqual(entry.scope, "en>pt")
        self.assertEqual(
            canonical_identity(entry),
            ("Knight fork", "garfo de cavalo", "automatic", "en>pt"),
        )

    def test_legacy_tuple_uses_the_same_identity_and_defaults(self):
        self.assertEqual(
            canonical_identity((" knight ", "cavalo\t", "sugestão", 17, " pt ")),
            ("knight", "cavalo", "suggestion", "pt"),
        )
        self.assertEqual(
            canonical_identity(("a", "b", "", 7, "*")),
            ("a", "b", "suggestion", ""),
        )
        self.assertEqual(canonical_identity(("a", "b")), ("a", "b", "suggestion", ""))

    def test_text_comparison_preserves_case_and_internal_spaces(self):
        self.assertNotEqual(
            canonical_identity(self.entry),
            canonical_identity(replace(self.entry, original_text="Knight")),
        )
        self.assertEqual(
            canonical_identity((" a  b ", " c  d ")),
            ("a  b", "c  d", "suggestion", ""),
        )

    def test_snapshot_exposes_persistent_identity_and_revision_immutably(self):
        source = [self.entry]
        snapshot = CatalogSnapshot(entries=source, catalog_revision=3)
        source.clear()
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].stable_id, "c30fb6dc-3e96-44a0-a431-0cde074f659e")
        self.assertEqual(snapshot.entries[0].revision, 1)
        self.assertEqual(snapshot.catalog_revision, 3)
        self.assertIsInstance(snapshot.entries, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.entries[0].revision = 2
        with self.assertRaises(FrozenInstanceError):
            snapshot.catalog_revision = 4

    def test_entry_revision_must_be_positive(self):
        with self.assertRaises(ValueError):
            replace(self.entry, revision=0)

    def test_legacy_adapter_reexports_shared_normalizers(self):
        for name in (
            "_normalize_rule_type", "_rule_type_alias", "normalize_glossary_text",
            "normalize_glossary_priority", "normalize_glossary_scope",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(glossario, name), getattr(glossary_types, name))


class GlossaryCatalogSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "nested" / "glossario-v2.db")

    def catalog(self):
        return glossary_catalog.GlossaryCatalog(self.db_path)

    def insert_entry(self, conn, stable_id, **changes):
        fields = dict(
            stable_id=stable_id, original_text="knight", replacement_text="cavalo",
            rule_type="suggestion", scope="pt", priority=0, position=0, revision=1,
        )
        fields.update(changes)
        conn.execute(
            f"INSERT INTO glossary_entries ({', '.join(fields)}) "
            f"VALUES ({', '.join('?' for _ in fields)})",
            tuple(fields.values()),
        )

    def test_default_path_uses_v2_filename_and_configured_data_directory(self):
        with patch.dict(os.environ, {app_paths.DATA_DIR_ENV: self.tmp.name}):
            self.assertEqual(
                app_paths.glossary_catalog_path(),
                str(Path(self.tmp.name) / "glossario-v2.db"),
            )
        self.assertEqual(glossario.GLOSSARY_DB_FILENAME, "glossario.db")

    def test_initialize_creates_empty_revision_one_catalog_with_wal_and_timeout(self):
        catalog = self.catalog()
        self.assertIsNone(catalog.initialize())
        self.assertTrue(Path(self.db_path).is_file())
        snapshot = catalog.list_entries()
        self.assertEqual(snapshot.entries, ())
        self.assertEqual(snapshot.catalog_revision, 1)
        with closing(catalog._connect()) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            metadata = dict(conn.execute("SELECT key, value FROM glossary_metadata"))
            self.assertEqual(metadata["catalog_revision"], "1")
            self.assertIn("schema_version", metadata)

    def test_stable_id_is_required_unique_text_and_revision_is_positive(self):
        self.catalog().initialize()
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {row[1]: row for row in conn.execute("PRAGMA table_info(glossary_entries)")}
            self.assertEqual(columns["stable_id"][2:4], ("TEXT", 1))
            self.assertEqual(columns["revision"][4], "1")
            self.insert_entry(conn, "c30fb6dc-3e96-44a0-a431-0cde074f659e")
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_entry(conn, None, original_text="rook")
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_entry(conn, "c30fb6dc-3e96-44a0-a431-0cde074f659e", original_text="rook")
            for revision in (0, -1, None):
                with self.subTest(revision=revision), self.assertRaises(sqlite3.IntegrityError):
                    self.insert_entry(conn, "c366297f-57ba-4474-aea6-59f596ec146b", original_text="rook", revision=revision)

    def test_unique_identity_includes_phase_scope_and_preserves_text_case(self):
        self.catalog().initialize()
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.insert_entry(conn, "one")
            self.insert_entry(conn, "two", scope="it")
            self.insert_entry(conn, "three", rule_type="cleanup")
            self.insert_entry(conn, "four", original_text="Knight")
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert_entry(conn, "five", priority=9, position=8)
            identity_columns = []
            for index in conn.execute("PRAGMA index_list(glossary_entries)").fetchall():
                if index[2]:
                    identity_columns.append(tuple(
                        row[2] for row in conn.execute("SELECT * FROM pragma_index_info(?)", (index[1],))
                    ))
            self.assertIn(("original_text", "replacement_text", "rule_type", "scope"), identity_columns)

    def test_list_returns_full_records_in_position_order_without_resetting_state(self):
        catalog = self.catalog()
        catalog.initialize()
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.insert_entry(conn, "c366297f-57ba-4474-aea6-59f596ec146b", position=1, scope="it", priority=7, revision=4)
            self.insert_entry(conn, "c30fb6dc-3e96-44a0-a431-0cde074f659e", position=0)
            conn.execute("UPDATE glossary_metadata SET value = '9' WHERE key = 'catalog_revision'")
            conn.commit()
        catalog.initialize()
        snapshot = self.catalog().list_entries()
        self.assertEqual(snapshot.catalog_revision, 9)
        self.assertEqual([entry.position for entry in snapshot.entries], [0, 1])
        self.assertEqual(snapshot.entries[0].stable_id, "c30fb6dc-3e96-44a0-a431-0cde074f659e")
        self.assertEqual(snapshot.entries[1].revision, 4)
        self.assertEqual(snapshot.entries[1].scope, "it")
        self.assertEqual(snapshot.entries[1].priority, 7)
        self.assertTrue(snapshot.entries[1].created_at)
        self.assertTrue(snapshot.entries[1].updated_at)

    def test_reading_uninitialized_catalog_does_not_create_database(self):
        with self.assertRaises((sqlite3.OperationalError, FileNotFoundError)):
            self.catalog().list_entries()
        self.assertFalse(Path(self.db_path).exists())


class GlossaryCatalogMutationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = glossary_catalog.GlossaryCatalog(str(Path(self.tmp.name) / "glossario-v2.db"))
        self.catalog.initialize()

    def draft(self, original="knight", replacement="cavalo", **changes):
        return glossary_catalog.GlossaryEntryDraft(
            original_text=original, replacement_text=replacement, **changes
        )


class GlossaryCatalogMirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "Substituicoes.txt"
        self.catalog = glossary_catalog.GlossaryCatalog(
            str(self.root / "glossario-v2.db"), str(self.path)
        )
        self.catalog.initialize()

    def metadata(self):
        with closing(self.catalog._connect()) as conn:
            return dict(conn.execute("SELECT key, value FROM glossary_metadata"))

    def test_committed_mutations_export_latest_snapshot_and_leave_no_temp_file(self):
        first = self.catalog.add(glossary_catalog.GlossaryEntryDraft("rook", "torre"), 1)
        second = self.catalog.add(glossary_catalog.GlossaryEntryDraft(
            "queen", "dama", rule_type="automatic", scope="pt", priority=3
        ), 2)
        self.assertFalse(second.mirror_pending)
        self.assertEqual(
            glossario._load_glossary_entry_details_from_file(str(self.path)),
            [("rook", "torre", "suggestion", 0, ""),
             ("queen", "dama", "automatic", 3, "pt")],
        )
        self.assertEqual(self.metadata()["mirror_pending"], "0")
        self.assertEqual(list(self.root.glob(".Substituicoes.txt.*")), [])
        self.catalog.update(first.entry.stable_id, 1,
                            glossary_catalog.GlossaryEntryChanges(replacement_text="castelo"))
        self.catalog.delete(second.entry.stable_id, 1)
        self.assertEqual(glossario._load_glossary_entry_details_from_file(str(self.path)),
                         [("rook", "castelo", "suggestion", 0, "")])

    def test_replace_failure_keeps_committed_catalog_and_retries_on_initialize(self):
        real_replace = os.replace
        with patch.object(glossary_catalog.os, "replace", side_effect=OSError("secret-path")):
            result = self.catalog.add(glossary_catalog.GlossaryEntryDraft("rook", "torre"), 1)
        self.assertEqual(result.snapshot, self.catalog.list_entries())
        self.assertTrue(result.mirror_pending)
        self.assertNotIn("secret-path", result.warning or "")
        self.assertEqual(self.metadata()["mirror_pending"], "1")
        self.assertNotIn("secret-path", self.metadata()["mirror_error"])
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.glob(".Substituicoes.txt.*")), [])
        with patch.object(glossary_catalog.os, "replace", wraps=real_replace):
            self.catalog.initialize()
        self.assertEqual(self.metadata()["mirror_pending"], "0")
        self.assertEqual(glossario._load_glossary_entry_details_from_file(str(self.path)),
                         [("rook", "torre", "suggestion", 0, "")])

    def test_external_edit_after_migration_is_warned_and_preserved(self):
        self.path.write_text("substituicoes = [('old', 'antigo')]\n", encoding="utf-8")
        self.catalog.migrate_legacy(
            lambda: glossario._load_glossary_entry_details_from_file(str(self.path)),
        )
        self.path.write_text("substituicoes = [('external', 'externo')]\n", encoding="utf-8")
        result = self.catalog.add(glossary_catalog.GlossaryEntryDraft("new", "novo"), 1)
        self.assertTrue(result.mirror_pending)
        self.assertIn("diverg", (result.warning or "").lower())
        self.assertIn("external", self.path.read_text(encoding="utf-8"))
        reopening = self.catalog.initialize()
        self.assertIn("external", self.path.read_text(encoding="utf-8"))
        self.assertIn("diverg", (reopening.warning or "").lower())
        self.assertEqual([entry.original_text for entry in self.catalog.list_entries().entries],
                         ["old", "new"])

    def test_connection_failure_after_commit_returns_warning_and_recovers_on_startup(self):
        for persistent_failure in (False, True):
            with self.subTest(persistent_failure=persistent_failure):
                real_connect = self.catalog._connect
                connection_count = 0
                revision = self.catalog.list_entries().catalog_revision

                def connect_after_commit(**kwargs):
                    nonlocal connection_count
                    connection_count += 1
                    if connection_count == 2 or (persistent_failure and connection_count > 2):
                        raise sqlite3.OperationalError("secret-path: unable to open database")
                    return real_connect(**kwargs)

                with patch.object(self.catalog, "_connect", side_effect=connect_after_commit):
                    result = self.catalog.add(
                        glossary_catalog.GlossaryEntryDraft(f"rook-{revision}", "torre"), revision
                    )

                self.assertEqual(result.snapshot, self.catalog.list_entries())
                self.assertTrue(result.mirror_pending)
                self.assertTrue(result.warning)
                self.assertNotIn("secret-path", result.warning)
                self.assertEqual(self.metadata()["mirror_pending"], "1")
                if not persistent_failure:
                    self.assertEqual(self.metadata()["mirror_error"], result.warning)
                reopening = glossary_catalog.GlossaryCatalog(self.catalog.db_path, str(self.path))
                reopening.initialize()
                self.assertEqual(self.metadata()["mirror_pending"], "0")
                exported = glossario._load_glossary_entries_from_file(str(self.path))
                self.assertIn((f"rook-{revision}", "torre"), exported)

    def test_real_write_lock_after_commit_returns_warning_and_recovers_on_startup(self):
        self.catalog.add(glossary_catalog.GlossaryEntryDraft("rook", "torre"), 1)
        original_contents = self.path.read_bytes()
        real_export = self.catalog.export_legacy
        with closing(sqlite3.connect(self.catalog.db_path)) as blocker:
            def export_with_write_lock():
                blocker.execute("BEGIN IMMEDIATE")
                return real_export()

            try:
                with patch.object(glossary_catalog, "CATALOG_BUSY_TIMEOUT_MS", 0), patch.object(
                    self.catalog, "export_legacy", side_effect=export_with_write_lock
                ):
                    result = self.catalog.add(
                        glossary_catalog.GlossaryEntryDraft("queen", "dama"), 2
                    )
                self.assertTrue(result.mirror_pending)
                self.assertTrue(result.warning)
                self.assertEqual(result.snapshot, self.catalog.list_entries())
                self.assertEqual(self.path.read_bytes(), original_contents)
                self.assertEqual(self.metadata()["mirror_pending"], "1")
            finally:
                blocker.rollback()

        reopening = glossary_catalog.GlossaryCatalog(self.catalog.db_path, str(self.path))
        reopening.initialize()
        self.assertEqual(self.metadata()["mirror_pending"], "0")
        self.assertEqual(glossario._load_glossary_entries_from_file(str(self.path)),
                         [("rook", "torre"), ("queen", "dama")])

    def test_edit_between_migration_commit_and_export_is_not_overwritten(self):
        self.path.write_text("substituicoes = [('old', 'antigo')]\n", encoding="utf-8")
        original_export = glossary_catalog.GlossaryCatalog.export_legacy

        def edit_then_export(catalog, path=None):
            self.path.write_text("substituicoes = [('external', 'externo')]\n", encoding="utf-8")
            return original_export(catalog, path)

        with patch.object(glossary_catalog.GlossaryCatalog, "export_legacy", edit_then_export):
            self.catalog.migrate_legacy(
                lambda: glossario._load_glossary_entry_details_from_file(str(self.path)),
            )
        self.assertIn("external", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.metadata()["mirror_pending"], "1")

class GlossaryCatalogMutationTests(GlossaryCatalogMutationFixture):
    def test_add_creates_uuid_initial_revision_and_increments_catalog_once(self):
        result = self.catalog.add(self.draft(" knight ", " cavalo ", scope=" pt "), 1)
        entry = result.entry
        self.assertEqual(str(UUID(entry.stable_id)), entry.stable_id)
        self.assertEqual((entry.original_text, entry.replacement_text, entry.scope),
                         ("knight", "cavalo", "pt"))
        self.assertEqual((entry.position, entry.revision, result.snapshot.catalog_revision), (0, 1, 2))
        self.assertEqual(result.snapshot, self.catalog.list_entries())

    def test_add_rejects_stale_catalog_and_full_identity_duplicate(self):
        first = self.catalog.add(self.draft(), 1)
        with self.assertRaises(glossary_catalog.GlossaryConflictError) as conflict:
            self.catalog.add(self.draft("rook", "torre"), 1)
        self.assertEqual((conflict.exception.stable_id, conflict.exception.expected_revision,
                          conflict.exception.current_revision), (None, 1, 2))
        with self.assertRaises(glossary_catalog.GlossaryDuplicateError):
            self.catalog.add(self.draft(" knight ", " cavalo ", priority=9), 2)
        self.assertEqual(self.catalog.list_entries(), first.snapshot)

    def test_update_targets_id_and_revision_and_preserves_id(self):
        first = self.catalog.add(self.draft(), 1).entry
        other = self.catalog.add(self.draft("rook", "torre"), 2).entry
        result = self.catalog.update(
            first.stable_id, 1,
            glossary_catalog.GlossaryEntryChanges(replacement_text=" corcel ", priority=7),
        )
        self.assertEqual((result.entry.stable_id, result.entry.revision, result.entry.replacement_text,
                          result.entry.priority, result.snapshot.catalog_revision),
                         (first.stable_id, 2, "corcel", 7, 4))
        self.assertEqual(result.entry.created_at, first.created_at)
        self.assertEqual(result.snapshot.entries[1], other)
        with self.assertRaises(glossary_catalog.GlossaryConflictError) as conflict:
            self.catalog.update(first.stable_id, 1,
                                glossary_catalog.GlossaryEntryChanges(replacement_text="errado"))
        self.assertEqual(conflict.exception.current_entry, result.entry)
        self.assertEqual(self.catalog.list_entries(), result.snapshot)

    def test_update_duplicate_identity_rolls_back_without_revision_increment(self):
        first = self.catalog.add(self.draft(), 1).entry
        second = self.catalog.add(self.draft("rook", "torre"), 2).entry
        before = self.catalog.list_entries()
        with self.assertRaises(glossary_catalog.GlossaryDuplicateError):
            self.catalog.update(second.stable_id, 1, glossary_catalog.GlossaryEntryChanges(
                original_text="knight", replacement_text="cavalo"
            ))
        self.assertEqual(self.catalog.list_entries(), before)
        self.assertEqual(self.catalog.list_entries().entries[0].stable_id, first.stable_id)

    def test_delete_requires_matching_revision_and_compacts_positions(self):
        first = self.catalog.add(self.draft(), 1).entry
        second = self.catalog.add(self.draft("rook", "torre"), 2).entry
        third = self.catalog.add(self.draft("bishop", "bispo"), 3).entry
        with self.assertRaises(glossary_catalog.GlossaryConflictError):
            self.catalog.delete(second.stable_id, 2)
        self.assertEqual(self.catalog.list_entries().catalog_revision, 4)
        result = self.catalog.delete(second.stable_id, 1)
        self.assertEqual(result.entry.stable_id, second.stable_id)
        self.assertEqual(result.snapshot.catalog_revision, 5)
        self.assertEqual([(entry.stable_id, entry.position) for entry in result.snapshot.entries],
                         [(first.stable_id, 0), (third.stable_id, 1)])


class GlossaryCatalogConcurrencyTests(GlossaryCatalogMutationTests):
    def test_separate_instances_can_edit_different_entries_from_old_snapshot(self):
        first = self.catalog.add(self.draft(), 1).entry
        second = self.catalog.add(self.draft("rook", "torre"), 2).entry
        other = glossary_catalog.GlossaryCatalog(self.catalog.db_path)
        one = self.catalog.update(first.stable_id, 1,
                                  glossary_catalog.GlossaryEntryChanges(priority=1))
        two = other.update(second.stable_id, 1,
                           glossary_catalog.GlossaryEntryChanges(priority=2))
        self.assertEqual((one.snapshot.catalog_revision, two.snapshot.catalog_revision), (4, 5))
        self.assertEqual([(entry.priority, entry.revision) for entry in two.snapshot.entries],
                         [(1, 2), (2, 2)])

    def test_same_entry_conflict_does_not_overwrite_or_delete(self):
        entry = self.catalog.add(self.draft(), 1).entry
        other = glossary_catalog.GlossaryCatalog(self.catalog.db_path)
        updated = self.catalog.update(entry.stable_id, 1,
                                      glossary_catalog.GlossaryEntryChanges(priority=8))
        for action in (
            lambda: other.update(entry.stable_id, 1, glossary_catalog.GlossaryEntryChanges(priority=3)),
            lambda: other.delete(entry.stable_id, 1),
        ):
            with self.assertRaises(glossary_catalog.GlossaryConflictError) as conflict:
                action()
            self.assertEqual(conflict.exception.current_entry, updated.entry)
        self.assertEqual(other.list_entries(), updated.snapshot)

    def test_deduplicate_uses_complete_identity_and_rejects_stale_snapshot(self):
        self.catalog.add(self.draft(scope="pt"), 1)
        self.catalog.add(self.draft(scope="it"), 2)
        self.catalog.add(self.draft(scope="pt", rule_type="cleanup"), 3)
        with closing(sqlite3.connect(self.catalog.db_path)) as conn:
            conn.execute("DROP INDEX idx_glossary_canonical_identity")
            conn.execute("""INSERT INTO glossary_entries
                (stable_id, original_text, replacement_text, rule_type, scope, priority, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("duplicate", "knight", "cavalo", "suggestion", "pt", 9, 7))
        before = self.catalog.list_entries()
        with self.assertRaises(glossary_catalog.GlossaryConflictError):
            self.catalog.deduplicate(3)
        self.assertEqual(self.catalog.list_entries(), before)
        result = self.catalog.deduplicate(4)
        self.assertEqual(result.snapshot.catalog_revision, 5)
        self.assertEqual([(entry.rule_type, entry.scope, entry.position) for entry in result.snapshot.entries],
                         [("suggestion", "pt", 0), ("suggestion", "it", 1), ("cleanup", "pt", 2)])
        self.assertEqual(result.snapshot.entries[0].priority, 0)

    def test_deduplicate_persists_normalized_survivor_before_restoring_unique_index(self):
        with closing(sqlite3.connect(self.catalog.db_path)) as conn, conn:
            conn.execute("DROP INDEX idx_glossary_canonical_identity")
            conn.executemany(
                """INSERT INTO glossary_entries
                   (stable_id, original_text, replacement_text, rule_type, scope, position)
                   VALUES (?, ?, ?, 'suggestion', ?, ?)""",
                [
                    ("raw-first", " knight ", " cavalo ", " pt ", 0),
                    ("normalized-second", "knight", "cavalo", "pt", 1),
                ],
            )
        result = self.catalog.deduplicate(1)
        self.assertEqual([(entry.stable_id, entry.revision, entry.position)
                          for entry in result.snapshot.entries], [("raw-first", 2, 0)])
        self.assertEqual(result.snapshot.catalog_revision, 2)
        with closing(sqlite3.connect(self.catalog.db_path)) as conn:
            stored = conn.execute(
                "SELECT original_text, replacement_text, scope FROM glossary_entries"
            ).fetchone()
        self.assertEqual(stored, ("knight", "cavalo", "pt"))
        with self.assertRaises(glossary_catalog.GlossaryDuplicateError):
            self.catalog.add(self.draft(scope="pt"), 2)


class GlossaryCatalogMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.text_path = self.root / "Substituicoes.txt"
        self.db_path = self.root / "glossario-v2.db"
        self.cache_path = self.root / "glossario.db"

    def catalog(self):
        return glossary_catalog.GlossaryCatalog(str(self.db_path), str(self.text_path))

    def write_text(self, body):
        self.text_path.write_text(body, encoding="utf-8")

    def migrate(self):
        return glossario.migrate_legacy_glossary(
            path=str(self.text_path), catalog_path=str(self.db_path),
            legacy_db_path=str(self.cache_path),
        )

    def test_migration_keeps_order_details_and_first_of_complete_duplicates(self):
        self.write_text("""escopo = 'pt'\nsubstituicoes = [
    ('Knight', 'Cavalo', 'suggestion', 7),
    ('Knight', 'Cavalo', 'suggestion', 2, 'it'),
    ('Knight', 'Cavalo', 'cleanup', 3),
    ('Knight', 'Cavalo', 'suggestion', 99),
    ('Rook', 'Torre', 'automatic', 4, '*'),
]\n""")
        with closing(sqlite3.connect(self.cache_path)) as cache, cache:
            cache.execute("CREATE TABLE old_rules (original TEXT)")
            cache.execute("INSERT INTO old_rules VALUES ('Cache only')")

        original_text = self.text_path.read_bytes()
        report = self.migrate()

        entries = self.catalog().list_entries().entries
        self.assertTrue(report.migrated)
        self.assertEqual(report.imported_count, 4)
        self.assertEqual(
            [(e.original_text, e.replacement_text, e.rule_type, e.priority, e.scope, e.position)
             for e in entries],
            [
                ("Knight", "Cavalo", "suggestion", 7, "pt", 0),
                ("Knight", "Cavalo", "suggestion", 2, "it", 1),
                ("Knight", "Cavalo", "cleanup", 3, "pt", 2),
                ("Rook", "Torre", "automatic", 4, "", 3),
            ],
        )
        self.assertEqual([e.revision for e in entries], [1] * 4)
        self.assertEqual(len({e.stable_id for e in entries}), 4)
        self.assertEqual(
            [(d.first_position, d.duplicate_position, d.identity) for d in report.duplicates],
            [(1, 4, ("Knight", "Cavalo", "suggestion", "pt"))],
        )
        self.assertEqual(len(report.backup_paths), 2)
        self.assertEqual(Path(report.backup_paths[0]).read_bytes(), original_text)
        self.assertEqual(
            glossario._load_glossary_entry_details_from_file(str(self.text_path)),
            [
                ("Knight", "Cavalo", "suggestion", 7, "pt"),
                ("Knight", "Cavalo", "suggestion", 2, "it"),
                ("Knight", "Cavalo", "cleanup", 3, "pt"),
                ("Rook", "Torre", "automatic", 4, ""),
            ],
        )
        with closing(sqlite3.connect(report.backup_paths[1])) as backup:
            self.assertEqual(backup.execute("SELECT original FROM old_rules").fetchone()[0], "Cache only")

    def test_missing_text_does_not_create_catalog_or_consult_cache(self):
        with closing(sqlite3.connect(self.cache_path)) as cache, cache:
            cache.execute("CREATE TABLE old_rules (original TEXT)")
            cache.execute("INSERT INTO old_rules VALUES ('Cache only')")
        with self.assertRaises(FileNotFoundError):
            self.migrate()
        self.assertFalse(self.db_path.exists())
        self.assertEqual(list(self.root.glob("*.bak*")), [])

    def test_invalid_text_leaves_only_backup_and_no_catalog(self):
        self.write_text("substituicoes = {'not': 'a list'}\n")
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertFalse(self.db_path.exists())
        self.assertEqual(len(list(self.root.glob("Substituicoes.txt.*.bak*"))), 1)

    def test_second_backup_failure_aborts_before_writing_v2(self):
        self.write_text("substituicoes = [('a', 'b')]\n")
        with closing(sqlite3.connect(self.cache_path)) as cache, cache:
            cache.execute("CREATE TABLE old_rules (original TEXT)")
        original = glossary_catalog.GlossaryCatalog._backup_file

        def fail_cache(source, *, database=False):
            if database:
                raise OSError("backup unavailable")
            return original(source, database=database)

        with patch.object(glossary_catalog.GlossaryCatalog, "_backup_file", side_effect=fail_cache):
            with self.assertRaisesRegex(OSError, "backup unavailable"):
                self.migrate()
        self.assertFalse(self.db_path.exists())
        self.assertEqual(len(list(self.root.glob("Substituicoes.txt.*.bak*"))), 1)

    def test_insertion_error_rolls_back_and_removes_new_partial_catalog(self):
        self.write_text("substituicoes = [('a', 'b'), ('c', 'd')]\n")
        original = glossary_catalog.GlossaryCatalog._insert_legacy_entry
        calls = 0

        def interrupted(conn, entry):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected insertion failure")
            original(conn, entry)

        with patch.object(glossary_catalog.GlossaryCatalog, "_insert_legacy_entry", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "injected insertion failure"):
                self.migrate()
        self.assertFalse(self.db_path.exists())
        self.assertEqual(list(self.root.glob(".*migration*")), [])

    def test_repeat_preserves_ids_and_does_not_read_changed_legacy_text(self):
        self.write_text("substituicoes = [('a', 'b')]\n")
        first = self.migrate()
        ids = [entry.stable_id for entry in self.catalog().list_entries().entries]
        self.write_text("substituicoes = [('else', 'changed')]\n")

        repeated = self.migrate()

        self.assertFalse(repeated.migrated)
        self.assertEqual(repeated.backup_paths, ())
        self.assertEqual([entry.stable_id for entry in self.catalog().list_entries().entries], ids)
        self.assertEqual(len(list(self.root.glob("Substituicoes.txt.*.bak*"))), 1)
        self.assertTrue(first.migrated)

    def test_existing_empty_catalog_rolls_back_all_rows_and_marker(self):
        self.write_text("substituicoes = [('a', 'b'), ('c', 'd')]\n")
        catalog = self.catalog()
        catalog.initialize()
        original = glossary_catalog.GlossaryCatalog._insert_legacy_entry
        calls = 0

        def interrupted(conn, entry):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected insertion failure")
            original(conn, entry)

        with patch.object(glossary_catalog.GlossaryCatalog, "_insert_legacy_entry", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "injected insertion failure"):
                self.migrate()
        self.assertEqual(catalog.list_entries().entries, ())
        with closing(catalog._connect()) as conn:
            marker = conn.execute(
                "SELECT value FROM glossary_metadata WHERE key = 'migration_completed'"
            ).fetchone()
        self.assertIsNone(marker)

    def test_incompatible_existing_v2_file_is_preserved(self):
        self.write_text("substituicoes = [('a', 'b')]\n")
        with closing(sqlite3.connect(self.db_path)) as alien, alien:
            alien.execute("CREATE TABLE unrelated (value TEXT)")
            alien.execute("INSERT INTO unrelated VALUES ('keep me')")

        with self.assertRaisesRegex(ValueError, "Incompatible glossary catalog"):
            self.migrate()

        with closing(sqlite3.connect(self.db_path)) as alien:
            self.assertEqual(alien.execute("SELECT value FROM unrelated").fetchone()[0], "keep me")
            tables = [row[0] for row in alien.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertNotIn("glossary_entries", tables)

    def test_text_change_after_backup_aborts_instead_of_importing_unbacked_data(self):
        self.write_text("substituicoes = [('original', 'first')]\n")
        original = glossary_catalog.GlossaryCatalog._backup_file

        def change_after_backup(source, *, database=False):
            backup = original(source, database=database)
            if not database:
                self.write_text("substituicoes = [('changed', 'second')]\n")
            return backup

        with patch.object(glossary_catalog.GlossaryCatalog, "_backup_file", side_effect=change_after_backup):
            with self.assertRaisesRegex(ValueError, "changed during migration"):
                self.migrate()
        self.assertFalse(self.db_path.exists())

    def test_concurrent_initial_migrations_publish_once_and_preserve_winner_id(self):
        self.write_text("substituicoes = [('a', 'b')]\n")
        rendezvous = threading.Barrier(2)
        validate = glossary_catalog.GlossaryCatalog._validate_migration

        def wait_before_publication(conn, expected):
            validate(conn, expected)
            rendezvous.wait(timeout=10)

        with patch.object(
            glossary_catalog.GlossaryCatalog, "_validate_migration",
            side_effect=wait_before_publication,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(self.migrate) for _ in range(2)]
                reports = [future.result(timeout=20) for future in futures]

        self.assertEqual(sorted(report.migrated for report in reports), [False, True])
        entries = self.catalog().list_entries().entries
        self.assertEqual(len(entries), 1)
        stable_id = entries[0].stable_id
        self.assertEqual([entry.stable_id for entry in self.catalog().list_entries().entries], [stable_id])
