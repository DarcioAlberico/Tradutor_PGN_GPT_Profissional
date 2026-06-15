import io
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tradutor_pgn.database import (
    count_review_rows,
    fetch_comment_history,
    fetch_export_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_translation_by_id,
    get_review_row_offset,
    get_review_status_counts,
    get_database_stats,
    initialize_database,
    load_translation_cache,
    save_translation,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    add_glossary_entry,
    add_to_glossary,
    analyze_glossary_csv_import,
    apply_all_substitutions,
    apply_substitution,
    clean_comment_for_translation,
    deduplicate_glossary_entries,
    delete_glossary_entry,
    export_glossary_csv,
    import_glossary_csv,
    initialize_glossary_database,
    find_glossary_matches,
    find_glossary_suggestions,
    load_glossary_entries,
    load_glossary_entry_details,
    load_glossary_entry_details_from_db,
    load_glossary_entries_from_db,
    load_cleanup_substitutions,
    load_substitutions,
    rebuild_glossary_database,
    restore_glossary_from_backup,
    save_glossary_entries,
    sync_glossary_database,
    update_glossary_entry,
    validate_glossary_entry,
)
from tradutor_pgn.pgn_utils import (
    collect_pgn_files,
    create_comment_batches,
    extract_comments_from_file,
    generate_translated_pgn,
    is_generated_pgn,
    translated_output_path,
)
from tradutor_pgn.review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    filter_quality_warning_rows,
    find_first_quality_warning,
    row_has_quality_warning,
    summarize_quality_warnings,
)
from tradutor_pgn.db_tools import (
    analyze_translations_csv_import,
    create_database_backup,
    format_quality_stats,
    import_translations_from_csv,
    restore_database_from_backup,
)
from tradutor_pgn.editor_text import find_text_ranges, replace_all_text, replace_text_range
from tradutor_pgn.edit_window import safe_geometry
from tradutor_pgn.glossary_editor import (
    build_glossary_diagnostics,
    glossary_counts,
    glossary_filter_indices,
    sort_glossary_indices,
)
from tradutor_pgn.settings import (
    clear_editor_draft,
    get_editor_draft,
    load_settings,
    save_settings,
    set_editor_draft,
)
from tradutor_pgn.translation_api import split_text_for_translation
from tradutor_pgn import translation_worker


def call_quietly(func, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


class FakeRoot:
    def after(self, _delay, callback=None):
        if callback is not None:
            callback()


class FakeProgress:
    def __init__(self):
        self.value = 0

    def set(self, value):
        self.value = value


class FakeWindow:
    def __init__(self, width=1920, height=1080):
        self.width = width
        self.height = height

    def winfo_screenwidth(self):
        return self.width

    def winfo_screenheight(self):
        return self.height


class FakeApp:
    def __init__(self, db_path):
        self.output_db = str(db_path)
        self.translation_cache = {}
        self.pause_flag = threading.Event()
        self.cancel_flag = threading.Event()
        self.root = FakeRoot()
        self.progress = FakeProgress()
        self.is_processing = True
        self.logs = []
        self.reset_called = False

    def log_message(self, message):
        self.logs.append(message)

    def _reset_buttons(self):
        self.reset_called = True


class PgnUtilsTests(unittest.TestCase):
    def test_extract_and_generate_translated_pgn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {White starts. Strong move} e5 {Black replies}\n",
                encoding="utf-8",
            )

            info = extract_comments_from_file(str(pgn))

            self.assertEqual(
                info["comments"],
                ["White starts. Strong move", "Black replies"],
            )

            output = translated_output_path(str(pgn), "pt")
            self.assertTrue(output.endswith("game-BR.pgn"))
            self.assertFalse(is_generated_pgn(str(pgn)))
            self.assertTrue(is_generated_pgn(str(tmp_path / "game-BR.pgn")))

            generated = generate_translated_pgn(
                str(pgn),
                output,
                {
                    "White starts. Strong move": "White begins. Good move",
                    "Black replies": "Black answers",
                },
                info["positions"],
            )

            self.assertTrue(generated)
            output_text = Path(output).read_text(encoding="utf-8")
            self.assertIn("{White begins. Good move}", output_text)
            self.assertIn("{Black answers}", output_text)

            files, skipped = collect_pgn_files(str(tmp_path), process_subdirs=False)
            self.assertIn(str(pgn), files)
            self.assertEqual(skipped, 1)

    def test_batches_and_translation_chunks_respect_limits(self):
        batches = create_comment_batches(["a" * 2000, "b" * 2000, "c"])

        self.assertEqual(batches, [["a" * 2000], ["b" * 2000, "c"]])

        chunks = split_text_for_translation("A. " * 2000, max_chars=100)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))


class EditorTextTests(unittest.TestCase):
    def test_find_text_ranges_respects_case_option(self):
        self.assertEqual(find_text_ranges("Mate mate MATE", "mate"), [(0, 4), (5, 9), (10, 14)])
        self.assertEqual(
            find_text_ranges("Mate mate MATE", "mate", case_sensitive=True),
            [(5, 9)],
        )
        self.assertEqual(find_text_ranges("abc", ""), [])

    def test_replace_text_range_clamps_offsets(self):
        self.assertEqual(replace_text_range("abcdef", 2, 4, "XX"), "abXXef")
        self.assertEqual(replace_text_range("abcdef", -5, 2, "X"), "Xcdef")
        self.assertEqual(replace_text_range("abcdef", 4, 99, "X"), "abcdX")

    def test_replace_all_text_returns_count(self):
        self.assertEqual(
            replace_all_text("Knight knight KNIGHT", "knight", "N"),
            ("N N N", 3),
        )
        self.assertEqual(
            replace_all_text("Knight knight", "Knight", "N", case_sensitive=True),
            ("N knight", 1),
        )
        self.assertEqual(replace_all_text("abc", "x", "y"), ("abc", 0))


class DatabaseTests(unittest.TestCase):
    def test_database_initialization_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()

            self.assertEqual(get_database_stats(cursor)["total"], 0)
            self.assertEqual(fetch_export_rows(cursor), [])
            self.assertEqual(fetch_review_rows(cursor, "pt"), [])

            self.assertEqual(save_translation(cursor, "orig", "trans", "pt"), "inserted")
            self.assertEqual(save_translation(cursor, "orig", "new", "pt"), "unchanged")
            conn.commit()

            self.assertEqual(load_translation_cache(cursor, "pt"), {"orig": "trans"})
            conn.close()

    def test_database_backup_creates_valid_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            backup_dir = tmp_path / "backups"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "orig", "trans", "pt")
            conn.commit()
            conn.close()

            first_backup = Path(
                create_database_backup(
                    str(db_path),
                    backup_dir=str(backup_dir),
                    timestamp="20260101-120000",
                )
            )
            second_backup = Path(
                create_database_backup(
                    str(db_path),
                    backup_dir=str(backup_dir),
                    timestamp="20260101-120000",
                )
            )

            self.assertTrue(first_backup.exists())
            self.assertTrue(second_backup.exists())
            self.assertNotEqual(first_backup, second_backup)

            backup_conn = sqlite3.connect(str(first_backup))
            try:
                rows = backup_conn.execute(
                    """
                    SELECT original_comment, translated_comment, target_language
                    FROM comments
                    """
                ).fetchall()
                self.assertEqual(rows, [("orig", "trans", "pt")])
                self.assertEqual(
                    backup_conn.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                backup_conn.close()

    def test_import_translations_from_csv_adds_only_missing_or_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            csv_path = tmp_path / "translations.csv"
            backup_dir = tmp_path / "backups"

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "existing orig", "existing trans", "pt")
            cursor.execute(
                """
                INSERT INTO comments (original_comment, translated_comment, target_language)
                VALUES (?, ?, ?)
                """,
                ("empty orig", "", "pt"),
            )
            conn.commit()
            conn.close()

            csv_path.write_text(
                "original_comment,translated_comment,target_language,verified\n"
                "new orig,new trans,pt,1\n"
                "existing orig,imported trans,pt,1\n"
                "empty orig,filled trans,pt,1\n"
                ",skip me,pt,0\n"
                "missing trans,,pt,0\n",
                encoding="utf-8-sig",
            )

            preview = analyze_translations_csv_import(str(db_path), str(csv_path))
            self.assertEqual(preview["total_rows"], 5)
            self.assertEqual(preview["inserted"], 1)
            self.assertEqual(preview["filled_empty"], 1)
            self.assertEqual(preview["unchanged"], 1)
            self.assertEqual(preview["skipped"], 2)
            self.assertEqual(preview["verified_applied"], 2)
            self.assertIsNone(preview["backup_path"])
            self.assertFalse(backup_dir.exists())

            stats = import_translations_from_csv(
                str(db_path),
                str(csv_path),
                backup_dir=str(backup_dir),
            )

            self.assertEqual(stats["total_rows"], 5)
            self.assertEqual(stats["inserted"], 1)
            self.assertEqual(stats["filled_empty"], 1)
            self.assertEqual(stats["unchanged"], 1)
            self.assertEqual(stats["skipped"], 2)
            self.assertEqual(stats["verified_applied"], 2)
            self.assertTrue(Path(stats["backup_path"]).exists())

            conn = initialize_database(str(db_path))
            try:
                rows = {
                    row[0]: (row[1], row[2])
                    for row in conn.execute(
                        """
                        SELECT original_comment, translated_comment, verified
                        FROM comments
                        ORDER BY original_comment
                        """
                    ).fetchall()
                }
            finally:
                conn.close()

            self.assertEqual(rows["existing orig"], ("existing trans", 0))
            self.assertEqual(rows["new orig"], ("new trans", 1))
            self.assertEqual(rows["empty orig"], ("filled trans", 1))
            self.assertNotIn("", rows)
            self.assertNotIn("missing trans", rows)

    def test_database_restore_replaces_current_database_and_keeps_safety_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_db = tmp_path / "current.db"
            restore_source = tmp_path / "restore-source.db"
            safety_dir = tmp_path / "safety"

            current_conn = initialize_database(str(current_db))
            current_cursor = current_conn.cursor()
            save_translation(current_cursor, "current orig", "current trans", "pt")
            current_conn.commit()
            current_conn.close()

            source_conn = initialize_database(str(restore_source))
            source_cursor = source_conn.cursor()
            save_translation(source_cursor, "backup orig", "backup trans", "pt")
            source_conn.commit()
            source_conn.close()

            result = restore_database_from_backup(
                str(current_db),
                str(restore_source),
                safety_backup_dir=str(safety_dir),
            )

            self.assertTrue(Path(result["safety_backup_path"]).exists())

            restored_conn = sqlite3.connect(str(current_db))
            try:
                rows = restored_conn.execute(
                    """
                    SELECT original_comment, translated_comment
                    FROM comments
                    ORDER BY id
                    """
                ).fetchall()
                self.assertEqual(rows, [("backup orig", "backup trans")])
            finally:
                restored_conn.close()

            safety_conn = sqlite3.connect(result["safety_backup_path"])
            try:
                rows = safety_conn.execute(
                    """
                    SELECT original_comment, translated_comment
                    FROM comments
                    ORDER BY id
                    """
                ).fetchall()
                self.assertEqual(rows, [("current orig", "current trans")])
            finally:
                safety_conn.close()

    def test_save_translation_fills_existing_empty_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO comments (original_comment, translated_comment, target_language)
                VALUES (?, ?, ?)
                """,
                ("orig", "", "pt"),
            )

            self.assertEqual(save_translation(cursor, "orig", "trans", "pt"), "filled_empty")
            conn.commit()
            self.assertEqual(load_translation_cache(cursor, "pt"), {"orig": "trans"})
            row = fetch_review_rows_page(cursor, "pt", limit=1, offset=0)[0]
            history = fetch_comment_history(cursor, row[0])
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0][1], "fill_empty")
            self.assertEqual(history[0][2], "")
            self.assertEqual(history[0][3], "trans")
            conn.close()

    def test_review_history_timestamps_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()

            self.assertEqual(save_translation(cursor, "orig", "trans", "pt"), "inserted")
            conn.commit()

            row = fetch_review_rows_page(cursor, "pt", limit=1, offset=0)[0]
            self.assertEqual(len(row), 7)
            self.assertIsNotNone(row[4])
            self.assertIsNotNone(row[5])
            self.assertIsNone(row[6])

            comment_id = row[0]
            self.assertEqual(fetch_comment_history(cursor, comment_id), [])
            self.assertEqual(
                update_translation_by_id(cursor, comment_id, "trans revisada", True),
                1,
            )
            conn.commit()

            detail = fetch_translation_by_id(cursor, comment_id)
            self.assertEqual(detail[1], "trans revisada")
            self.assertIsNotNone(detail[2])
            self.assertIsNotNone(detail[3])
            self.assertIsNotNone(detail[4])

            reviewed = fetch_review_rows_page(cursor, "pt", limit=1, offset=0)[0]
            self.assertEqual(reviewed[3], 1)
            self.assertIsNotNone(reviewed[6])
            history = fetch_comment_history(cursor, comment_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0][1], "edit_verify")
            self.assertEqual(history[0][2], "trans")
            self.assertEqual(history[0][3], "trans revisada")
            self.assertEqual(history[0][4], 0)
            self.assertEqual(history[0][5], 1)

            self.assertEqual(
                update_translation_by_id(cursor, comment_id, "trans revisada", True),
                0,
            )
            conn.commit()
            self.assertEqual(len(fetch_comment_history(cursor, comment_id)), 1)

            self.assertEqual(set_translation_verified_by_id(cursor, comment_id, False), 1)
            conn.commit()

            pending = fetch_review_rows_page(cursor, "pt", limit=1, offset=0)[0]
            self.assertEqual(pending[3], 0)
            self.assertIsNone(pending[6])
            history = fetch_comment_history(cursor, comment_id)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0][1], "mark_pending")
            self.assertEqual(history[0][4], 1)
            self.assertEqual(history[0][5], 0)

            self.assertEqual(
                update_translation_by_id(
                    cursor,
                    comment_id,
                    "trans",
                    history_action="restore",
                ),
                1,
            )
            conn.commit()

            detail = fetch_translation_by_id(cursor, comment_id)
            self.assertEqual(detail[1], "trans")
            history = fetch_comment_history(cursor, comment_id)
            self.assertEqual(len(history), 3)
            self.assertEqual(history[0][1], "restore")
            self.assertEqual(history[0][2], "trans revisada")
            self.assertEqual(history[0][3], "trans")
            conn.close()

    def test_exact_translation_matches_can_be_verified_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()

            save_translation(cursor, "orig 1", "mesma traducao", "pt")
            save_translation(cursor, "orig 2", "mesma traducao", "pt")
            save_translation(cursor, "orig 3", "outra traducao", "pt")
            save_translation(cursor, "orig 4", "mesma traducao", "en")
            save_translation(cursor, "orig 5", "", "pt")
            conn.commit()

            source_id = cursor.execute(
                "SELECT id FROM comments WHERE original_comment = ?",
                ("orig 1",),
            ).fetchone()[0]
            self.assertEqual(
                update_translation_by_id(cursor, source_id, "mesma traducao", True),
                1,
            )
            self.assertEqual(set_exact_translation_matches_verified(cursor, source_id), 1)
            conn.commit()

            rows = cursor.execute(
                """
                SELECT original_comment, verified
                FROM comments
                ORDER BY original_comment
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("orig 1", 1),
                    ("orig 2", 1),
                    ("orig 3", 0),
                    ("orig 4", 0),
                    ("orig 5", 0),
                ],
            )

            propagated_id = cursor.execute(
                "SELECT id FROM comments WHERE original_comment = ?",
                ("orig 2",),
            ).fetchone()[0]
            history = fetch_comment_history(cursor, propagated_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0][1], "verify_exact_match")
            self.assertEqual(history[0][4], 0)
            self.assertEqual(history[0][5], 1)
            self.assertEqual(set_exact_translation_matches_verified(cursor, source_id), 0)
            conn.close()

    def test_save_translation_works_with_legacy_table_without_unique_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                """
                CREATE TABLE comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_comment TEXT,
                    translated_comment TEXT,
                    target_language TEXT
                )
                """
            )
            conn.commit()
            conn.close()

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()

            self.assertEqual(save_translation(cursor, "orig", "trans", "pt"), "inserted")
            self.assertEqual(save_translation(cursor, "orig", "new", "pt"), "unchanged")
            conn.commit()

            self.assertEqual(load_translation_cache(cursor, "pt"), {"orig": "trans"})
            conn.close()

    def test_review_rows_can_be_counted_and_paged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            for index in range(5):
                save_translation(cursor, f"orig {index}", f"trans {index}", "pt")
            cursor.execute(
                "UPDATE comments SET verified = 1 WHERE original_comment = ?",
                ("orig 4",),
            )
            conn.commit()

            self.assertEqual(count_review_rows(cursor, "pt"), 5)
            self.assertEqual(count_review_rows(cursor, "pt", only_unverified=True), 4)
            self.assertEqual(count_review_rows(cursor, "pt", status_filter="pending"), 4)
            self.assertEqual(count_review_rows(cursor, "pt", status_filter="verified"), 1)
            self.assertEqual(
                get_review_status_counts(cursor, "pt"),
                {"total": 5, "pending": 4, "verified": 1},
            )
            self.assertEqual(
                get_review_status_counts(cursor, "pt", search_text="orig 4"),
                {"total": 1, "pending": 0, "verified": 1},
            )
            self.assertEqual(count_review_rows(cursor, "pt", search_text="orig 1"), 1)
            self.assertEqual(
                [row[1] for row in fetch_review_rows_page(cursor, "pt", limit=2, offset=0)],
                ["orig 0", "orig 1"],
            )
            self.assertEqual(
                [row[3] for row in fetch_review_rows_page(cursor, "pt", limit=5, offset=0)],
                [0, 0, 0, 0, 1],
            )
            self.assertEqual(
                [row[1] for row in fetch_review_rows_page(cursor, "pt", limit=2, offset=2)],
                ["orig 2", "orig 3"],
            )
            self.assertEqual(
                [row[1] for row in fetch_review_rows_page(cursor, "pt", limit=2, offset=4)],
                ["orig 4"],
            )
            self.assertEqual(
                [
                    row[1]
                    for row in fetch_review_rows_page(
                        cursor,
                        "pt",
                        limit=10,
                        offset=0,
                        search_text="trans 3",
                    )
                ],
                ["orig 3"],
            )
            self.assertEqual(
                fetch_review_rows_page(
                    cursor,
                    "pt",
                    only_unverified=True,
                    limit=10,
                    offset=0,
                    search_text="orig 4",
                ),
                [],
            )
            self.assertEqual(get_review_row_offset(cursor, "pt", 1), 0)
            self.assertEqual(get_review_row_offset(cursor, "pt", 3), 2)
            self.assertIsNone(get_review_row_offset(cursor, "pt", 5, only_unverified=True))
            self.assertEqual(
                get_review_row_offset(cursor, "pt", 5, status_filter="verified"),
                0,
            )
            self.assertEqual(
                get_review_row_offset(cursor, "pt", 4, search_text="trans 3"),
                0,
            )
            self.assertEqual(set_translation_verified_by_id(cursor, 5, False), 1)
            conn.commit()
            self.assertEqual(count_review_rows(cursor, "pt", status_filter="verified"), 0)
            self.assertEqual(count_review_rows(cursor, "pt", status_filter="pending"), 5)
            self.assertEqual(
                get_review_status_counts(cursor, "pt"),
                {"total": 5, "pending": 5, "verified": 0},
            )
            conn.close()


class SettingsTests(unittest.TestCase):
    def test_safe_geometry_clamps_negative_saved_position(self):
        self.assertEqual(
            safe_geometry(FakeWindow(), "1360x705+-71+28"),
            "1360x705+0+28",
        )
        self.assertEqual(
            safe_geometry(FakeWindow(width=1000, height=700), "1360x900+50+-20"),
            "1000x700+0+0",
        )

    def test_settings_round_trip_and_invalid_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            data = {
                "editor": {
                    "font_size": 15,
                    "status_filter": "Pendentes",
                    "geometry": "1180x720+10+20",
                    "main_sash_y": 260,
                    "bottom_sash_x": 760,
                }
            }

            save_settings(data, str(settings_path))
            self.assertEqual(load_settings(str(settings_path)), data)

            settings_path.write_text("{invalid", encoding="utf-8")
            self.assertEqual(load_settings(str(settings_path)), {})
            self.assertEqual(load_settings(str(Path(tmp) / "missing.json")), {})

    def test_editor_drafts_are_scoped_and_base_checked(self):
        settings = {}

        self.assertTrue(
            set_editor_draft(
                settings,
                "cache.db",
                "pt",
                10,
                "draft text",
                "saved text",
                updated_at="2026-01-01 12:00:00",
            )
        )

        draft = get_editor_draft(settings, "cache.db", "pt", 10, "saved text")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["text"], "draft text")
        self.assertEqual(draft["base_translation"], "saved text")
        self.assertEqual(draft["updated_at"], "2026-01-01 12:00:00")

        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "new saved"))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "en", 10, "saved text"))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 11, "saved text"))

        self.assertTrue(clear_editor_draft(settings, "cache.db", "pt", 10))
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "saved text"))
        self.assertFalse(clear_editor_draft(settings, "cache.db", "pt", 10))

    def test_editor_draft_matching_saved_text_clears_existing_draft(self):
        settings = {}
        self.assertTrue(
            set_editor_draft(settings, "cache.db", "pt", 10, "draft", "saved")
        )
        self.assertTrue(
            set_editor_draft(settings, "cache.db", "pt", 10, "saved", "saved")
        )
        self.assertIsNone(get_editor_draft(settings, "cache.db", "pt", 10, "saved"))


class EncodingTests(unittest.TestCase):
    def test_python_sources_do_not_contain_common_mojibake(self):
        project_root = Path(__file__).resolve().parents[1]
        source_paths = [
            project_root / "PGN_Tradutor_Pro.py",
            *sorted((project_root / "tradutor_pgn").glob("*.py")),
            project_root / "tests" / "test_core.py",
        ]
        suspicious_patterns = {
            "a_agudo": "\u00c3\u00a1",
            "e_agudo": "\u00c3\u00a9",
            "i_agudo": "\u00c3\u00ad",
            "o_agudo": "\u00c3\u00b3",
            "u_agudo": "\u00c3\u00ba",
            "a_til": "\u00c3\u00a3",
            "o_til": "\u00c3\u00b5",
            "cedilha": "\u00c3\u00a7",
            "double_encoded": "\u00c3\u0192",
            "nbsp_or_marker": "\u00c2",
        }
        failures = []

        for path in source_paths:
            text = path.read_text(encoding="utf-8")
            for name, pattern in suspicious_patterns.items():
                if pattern in text:
                    failures.append(f"{path.relative_to(project_root)}: {name}")

        self.assertEqual(failures, [])


class ReviewQualityTests(unittest.TestCase):
    def test_review_quality_warnings(self):
        self.assertEqual(evaluate_translation_quality("Original", ""), ["Tradução vazia."])
        self.assertIn(
            "Tradução igual ao original.",
            evaluate_translation_quality("Same text", "same text"),
        )
        self.assertIn(
            "Contém chaves { } que podem interferir no comentário PGN.",
            evaluate_translation_quality("Original text", "Texto com {chave}"),
        )
        self.assertIn(
            "Tradução muito curta em relação ao original.",
            evaluate_translation_quality("a" * 80, "curta"),
        )
        self.assertIn(
            "Tradução muito longa em relação ao original.",
            evaluate_translation_quality("a" * 40, "b" * 120),
        )
        self.assertEqual(evaluate_translation_quality("Checkmate threat", "Ameaça de mate"), [])

    def test_find_first_quality_warning(self):
        rows = [
            (1, "Checkmate threat", "Ameaça de mate", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
        ]

        found = find_first_quality_warning(rows)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 1)
        self.assertEqual(found[1][0], 2)
        self.assertIn("Tradução igual ao original.", found[2])

        found = find_first_quality_warning(rows, start_index=2)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 2)
        self.assertEqual(found[1][0], 3)
        self.assertEqual(found[2], ["Tradução vazia."])

        self.assertIsNone(find_first_quality_warning(rows, start_index=3))

    def test_quality_warning_row_filter(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
            (4, "Original text", "Texto com {chave}", 1),
        ]

        self.assertFalse(row_has_quality_warning(rows[0]))
        self.assertTrue(row_has_quality_warning(rows[1]))
        self.assertEqual([row[0] for row in filter_quality_warning_rows(rows)], [2, 3, 4])

    def test_quality_report_rows(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original text", "Texto com {chave}", 1),
        ]

        report = build_quality_report_rows(rows, "pt")

        self.assertEqual(
            QUALITY_REPORT_HEADERS,
            [
                "id",
                "target_language",
                "status",
                "warning_count",
                "warnings",
                "original_comment",
                "translated_comment",
            ],
        )
        self.assertEqual(len(report), 2)
        self.assertEqual(report[0][0], 2)
        self.assertEqual(report[0][1], "pt")
        self.assertEqual(report[0][2], "pending")
        self.assertEqual(report[0][3], 1)
        self.assertIn("igual ao original", report[0][4])
        self.assertEqual(report[1][0], 3)
        self.assertEqual(report[1][2], "verified")
        self.assertIn("chaves", report[1][4])

    def test_quality_summary(self):
        rows = [
            (1, "Original", "Traducao boa", 0),
            (2, "Same text", "same text", 0),
            (3, "Original", "", 0),
            (4, "Original text", "Texto com {chave}", 1),
        ]

        summary = summarize_quality_warnings(rows)

        self.assertEqual(summary["total_rows"], 4)
        self.assertEqual(summary["warning_rows"], 3)
        self.assertEqual(summary["pending_warning_rows"], 2)
        self.assertEqual(summary["verified_warning_rows"], 1)
        self.assertEqual(summary["warning_total"], 3)
        self.assertEqual(len(summary["warning_counts"]), 3)
        self.assertTrue(
            format_quality_stats(summary, "  ").startswith("  Com avisos QA: 3")
        )


class TranslationWorkerTests(unittest.TestCase):
    def test_run_translation_uses_cache_and_generates_pgn_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {White starts} e5 {Black replies}\n",
                encoding="utf-8",
            )

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "White starts", "As brancas começam", "pt")
            save_translation(cursor, "Black replies", "As pretas respondem", "pt")
            conn.commit()
            conn.close()

            app = FakeApp(db_path)

            original_translate_text = translation_worker.translate_text
            original_showinfo = translation_worker.messagebox.showinfo
            try:
                def fail_translate(*_args, **_kwargs):
                    raise AssertionError("API should not be called for cached comments")

                translation_worker.translate_text = fail_translate
                translation_worker.messagebox.showinfo = lambda *_args, **_kwargs: None

                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text
                translation_worker.messagebox.showinfo = original_showinfo

            output = tmp_path / "game-BR.pgn"
            self.assertTrue(output.exists())
            output_text = output.read_text(encoding="utf-8")
            self.assertIn("{As brancas começam}", output_text)
            self.assertIn("{As pretas respondem}", output_text)
            self.assertEqual(app.progress.value, 1)
            self.assertFalse(app.is_processing)
            self.assertTrue(app.reset_called)

    def test_run_translation_applies_cleanup_rules_before_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {== EndSquare ==} e5 {White == EndSquare == starts}\n",
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            translated_inputs = []
            original_translate_text = translation_worker.translate_text
            original_showinfo = translation_worker.messagebox.showinfo
            original_cleanup = translation_worker.load_cleanup_substitutions
            try:
                def fake_translate(text, *_args, **_kwargs):
                    translated_inputs.append(text)
                    return f"PT:{text}"

                translation_worker.translate_text = fake_translate
                translation_worker.messagebox.showinfo = lambda *_args, **_kwargs: None
                translation_worker.load_cleanup_substitutions = lambda: [
                    ("== EndSquare ==", ""),
                ]

                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text
                translation_worker.messagebox.showinfo = original_showinfo
                translation_worker.load_cleanup_substitutions = original_cleanup

            self.assertEqual(translated_inputs, ["White starts"])
            output = tmp_path / "game-BR.pgn"
            output_text = output.read_text(encoding="utf-8")
            self.assertIn("{}", output_text)
            self.assertIn("{PT:White starts}", output_text)

            conn = initialize_database(str(db_path))
            try:
                rows = conn.execute(
                    """
                    SELECT original_comment, translated_comment
                    FROM comments
                    ORDER BY original_comment
                    """
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(rows, [("White == EndSquare == starts", "PT:White starts")])


class GlossaryTests(unittest.TestCase):
    def test_load_and_append_glossary_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text(
                "substituicoes = [\n"
                "    ('foo', 'bar'),\n"
                "]\n",
                encoding="utf-8",
            )

            self.assertEqual(call_quietly(load_substitutions, str(glossary)), [("foo", "bar")])
            self.assertTrue(add_to_glossary("baz", "qux", str(glossary)))
            self.assertIn(("baz", "qux"), call_quietly(load_substitutions, str(glossary)))

    def test_load_glossary_accepts_accented_variable_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text(
                "substituições = [\n"
                "    ('mate threat', 'ameaça de mate'),\n"
                "]\n",
                encoding="utf-8",
            )

            self.assertEqual(
                call_quietly(load_substitutions, str(glossary)),
                [("mate threat", "ameaça de mate")],
            )

    def test_save_glossary_entries_creates_backup_and_persists_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            backup_dir = tmp_path / "backups"
            glossary.write_text(
                "substituicoes = [\n"
                "    ('old', 'entry'),\n"
                "]\n",
                encoding="utf-8",
            )

            result = save_glossary_entries(
                [("mate threat", "ameaça de mate"), ("bad move", "lance ruim")],
                str(glossary),
                backup_dir=str(backup_dir),
                timestamp="20260101-120000",
            )

            backup_path = Path(result["backup_path"])
            self.assertTrue(backup_path.exists())
            self.assertIn("('old', 'entry')", backup_path.read_text(encoding="utf-8"))
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("mate threat", "ameaça de mate"), ("bad move", "lance ruim")],
            )

    def test_glossary_crud_operations_update_persistent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("foo", "bar"), ("bad move", "lance ruim")],
                str(glossary),
                create_backup=False,
            )

            update_stats = update_glossary_entry(
                1,
                "good move",
                "bom lance",
                str(glossary),
                timestamp="20260101-120000",
            )
            self.assertEqual(update_stats["status"], "updated")
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("foo", "bar"), ("good move", "bom lance")],
            )

            delete_stats = delete_glossary_entry(
                0,
                str(glossary),
                timestamp="20260101-120001",
            )
            self.assertEqual(delete_stats["removed"], ("foo", "bar"))
            self.assertEqual(load_glossary_entries(str(glossary)), [("good move", "bom lance")])

            add_stats = add_glossary_entry(
                "zugzwang",
                "zugzwang",
                str(glossary),
                timestamp="20260101-120002",
            )
            self.assertEqual(add_stats["status"], "inserted")
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [("good move", "bom lance"), ("zugzwang", "zugzwang")],
            )

            unchanged_stats = add_glossary_entry("zugzwang", "zugzwang", str(glossary))
            self.assertEqual(unchanged_stats["status"], "unchanged")

    def test_glossary_rule_types_are_persisted_without_breaking_pair_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"
            csv_path = tmp_path / "glossario.csv"

            save_glossary_entries(
                [
                    ("mate threat", "ameaca de mate"),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            self.assertEqual(
                load_glossary_entries(str(glossary), db_path=str(glossary_db)),
                [
                    ("mate threat", "ameaca de mate"),
                    ("== EndSquare ==", ""),
                    ("rainha", "dama"),
                ],
            )
            self.assertEqual(
                load_glossary_entry_details(str(glossary), db_path=str(glossary_db)),
                [
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ],
            )
            self.assertEqual(
                load_glossary_entry_details_from_db(str(glossary_db)),
                [
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ],
            )

            add_glossary_entry(
                "queen",
                "dama",
                str(glossary),
                rule_type="automatica",
            )
            update_glossary_entry(
                0,
                "mate threat",
                "ameaca de mate",
                str(glossary),
                rule_type=GLOSSARY_RULE_CLEANUP,
            )
            self.assertEqual(
                load_glossary_entry_details(str(glossary), prefer_db=False),
                [
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_CLEANUP),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                    ("queen", "dama", GLOSSARY_RULE_AUTOMATIC),
                ],
            )

            export_glossary_csv(str(csv_path), path=str(glossary))
            self.assertIn(
                "original,replacement,type",
                csv_path.read_text(encoding="utf-8-sig"),
            )

    def test_cleanup_rules_are_separate_from_suggestions_and_allow_empty_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("rainha", "dama"),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("== StartSquare ==", "", GLOSSARY_RULE_CLEANUP),
                ],
                str(glossary),
                create_backup=False,
            )

            self.assertEqual(load_substitutions(str(glossary)), [("rainha", "dama")])
            self.assertEqual(
                load_cleanup_substitutions(str(glossary)),
                [("== EndSquare ==", ""), ("== StartSquare ==", "")],
            )
            self.assertNotIn(
                "Texto de substituição vazio.",
                validate_glossary_entry(
                    "== EndSquare ==",
                    "",
                    rule_type=GLOSSARY_RULE_CLEANUP,
                ),
            )
            self.assertEqual(
                clean_comment_for_translation(
                    "White plays == StartSquare == e4 == EndSquare ==",
                    load_cleanup_substitutions(str(glossary)),
                ),
                "White plays e4",
            )
            self.assertEqual(
                clean_comment_for_translation(
                    "== StartSquare == == EndSquare ==",
                    load_cleanup_substitutions(str(glossary)),
                ),
                "",
            )

    def test_glossary_validation_and_deduplication(self):
        entries = [
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça direta"),
        ]

        self.assertEqual(
            deduplicate_glossary_entries(entries),
            [("mate threat", "ameaça de mate"), ("mate threat", "ameaça direta")],
        )
        self.assertIn(
            "Entrada duplicada.",
            validate_glossary_entry(
                "mate threat",
                "ameaça de mate",
                entries,
                current_index=2,
            ),
        )
        self.assertIn(
            "Mesmo original com substituição diferente.",
            validate_glossary_entry("mate threat", "outra", entries),
        )
        self.assertIn("Texto original vazio.", validate_glossary_entry("", "x"))
        self.assertIn(
            "Entradas não podem conter quebras de linha.",
            validate_glossary_entry("a\nb", "x"),
        )

    def test_glossary_suggestions_respect_word_boundaries(self):
        substitutions = [
            ("for", "para"),
            ("branca", "brancas"),
            ("brancas joga", "brancas jogam"),
            (", as brancas joga", ", as brancas jogam"),
        ]
        text = "; as brancas jogaram de forma consistente."

        self.assertEqual(find_glossary_matches(text, "for"), [])
        self.assertEqual(find_glossary_matches(text, "branca"), [])
        self.assertEqual(find_glossary_matches(text, "brancas joga"), [])
        self.assertEqual(find_glossary_suggestions(text, substitutions), [])

        text = "for branca brancas joga, as brancas joga"
        self.assertEqual(
            find_glossary_suggestions(text, substitutions),
            [
                ("for", "para"),
                ("branca", "brancas"),
                ("brancas joga", "brancas jogam"),
                (", as brancas joga", ", as brancas jogam"),
            ],
        )
        self.assertEqual(apply_substitution("forma for", "for", "para"), "forma para")
        self.assertEqual(apply_substitution("forma", "for", "para"), "forma")
        self.assertEqual(
            apply_all_substitutions("forma for branca", [("for", "para"), ("branca", "brancas")]),
            "forma para brancas",
        )

    def test_glossary_is_independent_from_translation_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            db_path = tmp_path / "traducoes.db"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("knight fork", "garfo de cavalo")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )
            conn = initialize_database(str(db_path))
            conn.close()
            db_path.unlink()

            self.assertFalse(db_path.exists())
            self.assertTrue(glossary_db.exists())
            self.assertEqual(
                load_glossary_entries(str(glossary), db_path=str(glossary_db)),
                [("knight fork", "garfo de cavalo")],
            )
            self.assertEqual(
                load_glossary_entries_from_db(str(glossary_db)),
                [("knight fork", "garfo de cavalo")],
            )

    def test_glossary_database_can_be_rebuilt_and_loaded_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("pin", "cravada"), ("fork", "garfo")],
                str(glossary),
                create_backup=False,
                sync_db=False,
            )
            self.assertFalse(glossary_db.exists())

            stats = rebuild_glossary_database(str(glossary), str(glossary_db))
            self.assertEqual(stats["synced"], 2)
            self.assertEqual(
                load_glossary_entries_from_db(str(glossary_db)),
                [("pin", "cravada"), ("fork", "garfo")],
            )

            sync_glossary_database(
                [("skewer", "raio x")],
                db_path=str(glossary_db),
                source_path=str(glossary),
            )
            self.assertEqual(load_glossary_entries_from_db(str(glossary_db)), [("skewer", "raio x")])

            conn = initialize_glossary_database(str(glossary_db))
            try:
                indexes = {
                    row[1]
                    for row in conn.execute("PRAGMA index_list(glossary_entries)").fetchall()
                }
            finally:
                conn.close()
            self.assertIn("idx_glossary_original", indexes)
            self.assertIn("idx_glossary_replacement", indexes)

    def test_glossary_editor_filters_and_counts_large_lists(self):
        entries = [
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça de mate"),
            ("mate threat", "ameaça direta"),
            ("", "vazio"),
            ("fork", "fork"),
        ]
        diagnostics = build_glossary_diagnostics(entries)

        self.assertEqual(
            glossary_counts(entries, diagnostics),
            {"total": 5, "duplicates": 2, "conflicts": 3, "invalid": 5},
        )
        self.assertEqual(
            glossary_filter_indices(entries, "mate", "Todas", diagnostics),
            [0, 1, 2],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "", "Duplicadas", diagnostics),
            [0, 1],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "", "Conflitos", diagnostics),
            [0, 1, 2],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "fork", "Inválidas", diagnostics),
            [4],
        )
        self.assertEqual(sort_glossary_indices(entries, [2, 0, 4], "Original A-Z"), [4, 0, 2])
        self.assertEqual(
            sort_glossary_indices(entries, [0, 2, 4], "Maior original"),
            [0, 2, 4],
        )

    def test_glossary_csv_export_import_preview_and_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            csv_path = tmp_path / "glossario.csv"
            backup_dir = tmp_path / "backups"

            save_glossary_entries(
                [("mate threat", "ameaça de mate"), ("fork", "garfo")],
                str(glossary),
                create_backup=False,
            )

            export_stats = export_glossary_csv(str(csv_path), path=str(glossary))
            self.assertEqual(export_stats["exported"], 2)
            self.assertIn("original,replacement", csv_path.read_text(encoding="utf-8-sig"))

            csv_path.write_text(
                "original,replacement\n"
                "mate threat,ameaça de mate\n"
                "fork,garfo duplo\n"
                "pin,cravada\n"
                ",sem original\n"
                "skewer,\n",
                encoding="utf-8-sig",
            )

            preview = analyze_glossary_csv_import(str(glossary), str(csv_path))
            self.assertEqual(preview["total_rows"], 5)
            self.assertEqual(preview["inserted"], 1)
            self.assertEqual(preview["duplicates"], 1)
            self.assertEqual(preview["conflicts"], 1)
            self.assertEqual(preview["invalid"], 2)
            self.assertEqual(preview["skipped"], 4)

            stats = import_glossary_csv(
                str(glossary),
                str(csv_path),
                backup_dir=str(backup_dir),
                timestamp="20260101-120000",
            )
            self.assertEqual(stats["inserted"], 1)
            self.assertTrue(Path(stats["backup_path"]).exists())
            self.assertEqual(
                load_glossary_entries(str(glossary)),
                [
                    ("mate threat", "ameaça de mate"),
                    ("fork", "garfo"),
                    ("pin", "cravada"),
                ],
            )

    def test_restore_glossary_from_backup_replaces_file_and_keeps_safety_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            backup = tmp_path / "backup.txt"
            safety_dir = tmp_path / "safety"

            save_glossary_entries([("current", "atual")], str(glossary), create_backup=False)
            save_glossary_entries([("backup", "copia")], str(backup), create_backup=False)

            result = restore_glossary_from_backup(
                str(glossary),
                str(backup),
                safety_backup_dir=str(safety_dir),
                timestamp="20260101-120000",
            )

            self.assertTrue(Path(result["safety_backup_path"]).exists())
            self.assertEqual(load_glossary_entries(str(glossary)), [("backup", "copia")])
            self.assertEqual(
                load_glossary_entries(result["safety_backup_path"]),
                [("current", "atual")],
            )


if __name__ == "__main__":
    unittest.main()
