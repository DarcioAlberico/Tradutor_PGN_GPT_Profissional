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
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import add_to_glossary, load_substitutions
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


if __name__ == "__main__":
    unittest.main()
