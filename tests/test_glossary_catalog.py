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
        self.assertEqual(Path(report.backup_paths[0]).read_bytes(), self.text_path.read_bytes())
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
