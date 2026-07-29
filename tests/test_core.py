import csv
import io
import os
import re
import sqlite3
import sys
import types
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from tradutor_pgn import database, glossario, settings
from tradutor_pgn.app_config import (
    DATABASE_BACKUP_KEEP_COUNT,
    DATABASE_BACKUP_MAX_TOTAL_MB,
    GLOSSARY_BACKUP_KEEP_COUNT,
    LOG_KEEP_COUNT,
    MAX_TRANSLATE_CHARS,
)
from tradutor_pgn.database import (
    FTS_TABLE,
    SCHEMA_VERSION,
    SEARCH_MODE_SUBSTRING,
    SEARCH_MODE_TERMS,
    SOURCE_LANGUAGE_UNKNOWN,
    adopt_unknown_source_language,
    build_fts_match_query,
    clear_all_translations,
    fts_index_ready,
    AutomaticRulesCanceled,
    apply_automatic_translation_updates,
    backfill_quality_warnings,
    count_from_status_counts,
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
    build_glossary_lookup,
    order_rules_by_specificity,
    GLOSSARY_PRIORITY_DEFAULT,
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    add_glossary_entry,
    glossary_entry_priority,
    promote_glossary_rule,
    rule_priority,
    normalize_glossary_priority,
    add_to_glossary,
    analyze_glossary_csv_import,
    apply_automatic_substitutions,
    apply_all_substitutions,
    apply_substitution,
    clean_comment_for_translation,
    deduplicate_glossary_entries,
    delete_glossary_entry,
    delete_glossary_entry_by_pair,
    glossary_entry_pair,
    case_adjusted_replacement,
    export_glossary_csv,
    find_glossary_entry_index,
    read_glossary_csv,
    import_glossary_csv,
    initialize_glossary_database,
    find_glossary_matches,
    find_glossary_suggestions,
    load_glossary_entries,
    load_glossary_entry_details,
    load_glossary_entry_details_from_db,
    load_glossary_entries_from_db,
    load_cleanup_substitutions,
    load_automatic_substitutions,
    load_interactive_substitutions,
    load_substitutions,
    rebuild_glossary_database,
    restore_glossary_from_backup,
    save_glossary_entries,
    sync_glossary_database,
    update_glossary_entry,
    update_glossary_entry_by_entry,
    validate_glossary_entry,
)
from tradutor_pgn.pgn_utils import (
    BATCH_MAX_CHARS,
    collect_pgn_files,
    create_comment_batches,
    detect_encoding,
    extract_comments_from_file,
    generate_translated_pgn,
    is_generated_pgn,
    join_comments_for_batch,
    split_batch_translation,
    translated_output_path,
)
from tradutor_pgn.pgn_spellcheck import (
    collect_spellcheck_pgn_files,
    normalize_pgn_metadata_content,
    normalize_pgn_metadata_file,
    normalize_pgn_metadata_path,
    normalized_output_path,
    PGN_TAG_RE,
    SUPPORTED_TAGS,
    parse_spelling_file,
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
from tradutor_pgn import app_config
from tradutor_pgn.background_task import BackgroundTask, TaskCanceled
from tradutor_pgn.chess_notation import (
    PIECE_LETTERS,
    extract_moves,
    fix_move_notation,
    supports_notation,
)
from tradutor_pgn.confirm_dialog import CONFIRMATION_WORD, confirmation_accepted
from tradutor_pgn.db_tools import (
    analyze_database_automatic_rules,
    analyze_translations_csv_import,
    apply_database_automatic_rules,
    create_database_backup,
    export_translations_to_csv,
    format_automatic_rule_examples,
    format_quality_stats,
    import_translations_from_csv,
    restore_database_from_backup,
)
from tradutor_pgn.editor_common import (
    clamp_geometry,
    clamp_page,
    local_index_for_offset,
    page_count,
    page_of_offset,
    page_offset,
    preview,
    row_index_for_id,
)
from tradutor_pgn.editor_text import find_text_ranges, replace_all_text, replace_text_range
from tradutor_pgn.edit_window import safe_geometry
from tradutor_pgn.glossary_editor import safe_geometry as glossary_safe_geometry
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
    update_settings,
)
from tradutor_pgn import pgn_utils
from tradutor_pgn.translation_api import split_text_for_translation, translate_text
from tradutor_pgn import translation_api
from tradutor_pgn import (
    app_actions,
    db_tools,
    editor_common,
    editor_widgets,
    failed_runs,
    translation_worker,
    window_utils,
)
from tradutor_pgn import backup_retention
from tradutor_pgn.backup_retention import (
    backup_timestamp,
    is_backup_of_family,
    prune_backups,
    prune_database_backups,
    prune_glossary_backups,
    select_backups_to_delete,
    uniqueness_suffix,
)
from tradutor_pgn.glossario import (
    clear_glossary_error,
    create_glossary_backup,
    last_glossary_error,
    report_glossary_error,
    set_glossary_error_handler,
)


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


_GLOSSARY_SANDBOX = None


def setUpModule():
    """Impede que qualquer teste escreva no glossario real do projeto.

    `glossario._default_substitutions_path()` deriva o caminho de
    `sys.argv[0]`. Sob `python -m unittest`, `sys.argv[0]` e a string
    `'python.exe -m unittest'` — sem barra nenhuma —, entao
    `os.path.dirname(os.path.abspath(...))` resolve para o DIRETORIO ATUAL. Como
    a suite roda da raiz do projeto, o caminho padrao aponta para o
    `Substituicoes.txt` de verdade, com as milhares de regras do usuario.

    Hoje nenhum teste chama essas funcoes sem passar um caminho, mas basta um
    esquecimento para uma execucao da suite apagar entradas do glossario real,
    silenciosamente e sem relacao aparente com o teste que falhou. Redirecionar
    o padrao para um diretorio temporario elimina a categoria inteira.
    """
    global _GLOSSARY_SANDBOX
    _GLOSSARY_SANDBOX = tempfile.TemporaryDirectory(prefix="glossario-sandbox-")
    base = Path(_GLOSSARY_SANDBOX.name)
    glossario._default_substitutions_path = lambda: str(base / "Substituicoes.txt")
    glossario._default_glossary_db_path = lambda: str(base / "glossario.db")
    settings.default_settings_path = lambda: str(base / "settings.json")


def tearDownModule():
    if _GLOSSARY_SANDBOX is not None:
        _GLOSSARY_SANDBOX.cleanup()


class DefaultPathSafetyTests(unittest.TestCase):
    def test_default_glossary_path_is_never_the_real_project_file(self):
        # Se esta protecao cair, um teste distraido apaga o glossario do usuario.
        caminho = Path(glossario._default_substitutions_path()).resolve()
        projeto = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        self.assertNotEqual(caminho, projeto.resolve())
        self.assertIn("glossario-sandbox-", str(caminho))


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
        batches = create_comment_batches(["a" * 2000, "b" * 2000, "c"], max_chars=3800)

        self.assertEqual(batches, [["a" * 2000], ["b" * 2000, "c"]])

        chunks = split_text_for_translation("A. " * 2000, max_chars=100)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))

    def test_batch_limit_stays_below_api_split_limit(self):
        # Garantia B1: um lote nunca pode ser grande a ponto de a camada de API
        # dividi-lo, porque o corte pode cair no meio do separador " ||| ".
        self.assertLess(BATCH_MAX_CHARS, MAX_TRANSLATE_CHARS)

        comments = ["a" * 900 for _ in range(40)]
        for batch in create_comment_batches(comments):
            self.assertLessEqual(
                len(join_comments_for_batch(batch)),
                MAX_TRANSLATE_CHARS,
            )

    def test_batch_round_trip_splits_back_into_same_number_of_parts(self):
        comments = ["First comment.", "Second one!", "Terceiro: com acento."]
        joined = join_comments_for_batch(comments)

        self.assertEqual(split_batch_translation(joined, len(comments)), comments)

        # Contagem divergente deve recusar o alinhamento em vez de adivinhar.
        self.assertIsNone(split_batch_translation(joined, len(comments) + 1))

        # O tradutor costuma mexer nos espacos ao redor do separador.
        self.assertEqual(
            split_batch_translation("um|||dois ||| tres", 3),
            ["um", "dois", "tres"],
        )

    def test_encoding_detection_reads_whole_file_not_just_a_sample(self):
        # Garantias E1/E2: um PGN com dezenas de milhares de linhas ASCII e
        # acentos so no fim nao pode ser detectado como ascii.
        filler = "".join(
            f'[Event "Open"]\n[White "Smith"]\n[Round "{i}"]\n\n'
            f'1. e4 e5 {{Quiet move}} 1-0\n\n'
            for i in range(1, 1200)
        )
        tail = '[Event "Final"]\n[White "Garcia, Jose"]\n\n1. d4 {Posicao dificil} 1-0\n'
        tail = tail.replace("Garcia, Jose", "García, José")
        tail = tail.replace("Posicao dificil", "Posição difícil")
        text = filler + tail

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for label, encoding in (("cp1252", "cp1252"), ("utf8", "utf-8")):
                pgn = tmp_path / f"grande_{label}.pgn"
                pgn.write_bytes(text.encode(encoding))
                self.assertGreater(pgn.stat().st_size, 65536)

                detected = detect_encoding(str(pgn))
                self.assertNotEqual(detected, "ascii")

                info = extract_comments_from_file(str(pgn))
                joined = " ".join(info["comments"])
                self.assertNotIn("�", joined)
                self.assertIn("Posição difícil", joined)

    def test_utf16_pgn_is_read_as_text_and_not_as_nul_separated_bytes(self):
        """Garantia E4: UTF-16 escapava de E1/E2/E3.

        Um PGN em UTF-16-LE com texto ASCII e uma letra e um `\\x00`
        alternados — e `\\x00` E ASCII valido. Entao E2 concluia "e tudo ASCII,
        adoto UTF-8" e cada comentario saia com um NUL entre cada letra. Esse
        texto vira a CHAVE DE CACHE, entao o erro nao ficava so na tela: era
        gravado no `traducoes.db` para sempre.

        O caso com BOM funcionava, mas por sorte: quem acertava era o `chardet`,
        que e um import opcional. Por isso cada caso e conferido tambem com ele
        ausente.
        """
        comentarios = ["O bispo domina a diagonal", "Posição difícil para as pretas"]
        conteudo = (
            '[Event "Torneio"]\n[White "Gonçalves, João"]\n\n'
            f"1. e4 {{{comentarios[0]}}} e5 2. Nf3 {{{comentarios[1]}}} 1-0\n"
        )
        codificacoes = [
            ("utf-8", "utf-8"),
            ("utf-8-sig", "utf-8-sig"),
            ("cp1252", "cp1252"),
            ("utf-16", "utf-16"),        # com BOM
            ("utf-16-le", "utf-16-le"),  # sem BOM: o caso que quebrava
            ("utf-16-be", "utf-16-be"),  # sem BOM
            ("utf-32", "utf-32"),
        ]

        chardet_original = pgn_utils.chardet
        try:
            for com_chardet in (True, False):
                pgn_utils.chardet = chardet_original if com_chardet else None
                rotulo = "com chardet" if com_chardet else "sem chardet"

                with tempfile.TemporaryDirectory() as tmp:
                    for nome, encoding in codificacoes:
                        pgn = Path(tmp) / f"{nome}.pgn"
                        pgn.write_bytes(conteudo.encode(encoding))

                        detectada = detect_encoding(str(pgn))
                        lidos = extract_comments_from_file(str(pgn))["comments"]

                        self.assertEqual(
                            lidos,
                            comentarios,
                            f"{nome} ({rotulo}) foi lido como {detectada}",
                        )
                        self.assertNotIn(
                            "\x00",
                            " ".join(lidos),
                            f"{nome} ({rotulo}) trouxe NUL para dentro do texto",
                        )
                        self.assertNotIn("�", " ".join(lidos))
        finally:
            pgn_utils.chardet = chardet_original

    def test_a_detected_encoding_always_decodes_the_whole_file(self):
        """Garantia E4: nada e adotado sem decodificar o arquivo inteiro.

        O palpite do `chardet` era devolvido no escuro, enquanto o fallback logo
        abaixo (`cp1252`, `latin-1`) so aceitava o que decodificava. Quando o
        palpite erra, `errors='replace'` injeta `U+FFFD` no texto lido — e esse
        texto e o que `generate_translated_pgn` grava de volta, contrariando G2.

        Aqui o `chardet` e substituido por um que responde com confianca alta uma
        codificacao que nao da conta do arquivo. Sem a verificacao, este teste
        falha com `U+FFFD` no comentario.
        """

        class ChardetMentiroso:
            @staticmethod
            def detect(_raw):
                # cp1254 (turco) nao define os bytes 0x81, 0x8D, 0x8F, 0x90, 0x9D.
                return {"encoding": "cp1254", "confidence": 0.99}

        conteudo = '[Event "Torneio"]\n\n1. e4 {Posição difícil} 1-0\n'
        bruto = conteudo.encode("cp1252") + b"\x81\x90"

        chardet_original = pgn_utils.chardet
        try:
            pgn_utils.chardet = ChardetMentiroso
            with tempfile.TemporaryDirectory() as tmp:
                pgn = Path(tmp) / "suspeito.pgn"
                pgn.write_bytes(bruto)

                detectada = detect_encoding(str(pgn))
                self.assertNotEqual(detectada, "cp1254")
                bruto.decode(detectada)  # levanta se a escolha nao decodificar

                lidos = extract_comments_from_file(str(pgn))["comments"]
                self.assertNotIn("�", " ".join(lidos))
        finally:
            pgn_utils.chardet = chardet_original

    def test_generated_pgn_preserves_accents_of_large_source(self):
        # Garantia G2: nenhum caractere pode virar U+FFFD no arquivo de saida.
        filler = "".join(
            f'[Event "Open"]\n[White "Smith"]\n[Round "{i}"]\n\n'
            f'1. e4 e5 {{Quiet move}} 1-0\n\n'
            for i in range(1, 1200)
        )
        tail = (
            '[Event "Torneio"]\n'
            '[White "Gonçalves, João"]\n'
            '[Site "São Paulo"]\n\n'
            '1. d4 {Posição difícil} 1-0\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "torneio.pgn"
            pgn.write_bytes((filler + tail).encode("cp1252"))

            info = extract_comments_from_file(str(pgn))
            translated_map = {c: c for c in info["comments"]}
            output = tmp_path / "saida.pgn"

            self.assertTrue(
                generate_translated_pgn(
                    str(pgn), str(output), translated_map, info["positions"]
                )
            )

            raw = output.read_bytes()
            written = raw.decode(detect_encoding(str(output)))
            self.assertNotIn("�", written)
            self.assertIn("Gonçalves, João", written)
            self.assertIn("São Paulo", written)
            self.assertIn("Posição difícil", written)

    def test_spelling_file_normalizes_only_pgn_metadata_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            spelling = Path(tmp) / "spelling.ssp"
            spelling.write_text(
                '@PLAYER "., -_*"\n'
                '%Prefix "GM " ""\n'
                'Speelman, Jonathan S #GM ENG [2600]\n'
                '  = Speelman, J S\n'
                'Aaberg, Anton #IM SWE [2323]\n'
                '  = Aberg, Anton\n'
                '@SITE "., -_()"\n'
                'London\n'
                '  = Londres\n'
                '@EVENT ",. -_"\n'
                'World Championship\n'
                '  = WCh\n'
                '@ROUND ""\n'
                '1\n'
                '  = 1.0\n',
                encoding="utf-8",
            )
            spelling_data = parse_spelling_file(str(spelling))
            content = (
                '[Event "WCh"]\n'
                '[Site "Londres"]\n'
                '[Round "1.0"]\n'
                '[White "GM Aberg, Anton"]\n'
                '[Black "J. S. Speelman"]\n\n'
                '1. e4 {GM Aberg, Anton should stay in comment} e5\n'
            )

            updated, changes = normalize_pgn_metadata_content(content, spelling_data)

            self.assertIn('[Event "World Championship"]', updated)
            self.assertIn('[Site "London"]', updated)
            self.assertIn('[Round "1"]', updated)
            self.assertIn('[White "Aaberg, Anton"]', updated)
            self.assertIn('[Black "Speelman, Jonathan S"]', updated)
            self.assertIn("{GM Aberg, Anton should stay in comment}", updated)
            self.assertEqual(
                [change["tag"] for change in changes],
                ["Event", "Site", "Round", "White", "Black"],
            )

    def test_spelling_normalization_writes_norm_output_only_when_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[White "Aberg, Anton"]\n'
                '[Black "Known Player"]\n\n'
                "1. e4 e5\n",
                encoding="utf-8",
            )
            spelling_data = {
                "PLAYER": {
                    "entries": {
                        "aberganton": "Aaberg, Anton",
                        "knownplayer": "Known Player",
                    },
                    "ignore_chars": "., -_*",
                    "prefix_rules": [],
                    "suffix_rules": [],
                }
            }

            result = normalize_pgn_metadata_file(str(pgn), spelling_data)

            self.assertTrue(result["changed"])
            self.assertTrue(result["output_file"].endswith("-NORM.pgn"))
            output_text = Path(result["output_file"]).read_text(encoding="utf-8")
            self.assertIn('[White "Aaberg, Anton"]', output_text)
            self.assertTrue(
                normalized_output_path(str(tmp_path / "done-NORM.pgn")).endswith(
                    "done-NORM-novo.pgn"
                )
            )

            files, skipped = collect_spellcheck_pgn_files(str(tmp_path), process_subdirs=False)
            self.assertIn(str(pgn), files)
            self.assertNotIn(result["output_file"], files)
            self.assertEqual(skipped, 1)


class TranslationApiTests(unittest.TestCase):
    def test_translate_text_uses_provided_session(self):
        class FakeResponse:
            status_code = 200

            def json(self):
                return [[["Ola", "Hello"]]]

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, params=None, timeout=None):
                self.calls.append((url, params, timeout))
                return FakeResponse()

        session = FakeSession()

        result = translate_text("Hello", "pt", session=session)

        self.assertEqual(result, "Ola")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["q"], "Hello")
        self.assertEqual(session.calls[0][2], 30)


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
            # `fetch_export_rows` devolve o cursor, nao uma lista: o exportador
            # escreve linha a linha e nao precisa do banco inteiro na memoria.
            self.assertEqual(list(fetch_export_rows(cursor)), [])
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

    def test_apply_database_automatic_rules_updates_existing_translations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            backup_dir = tmp_path / "backups"

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "orig 1", "A rainha venceu com mate", "pt")
            save_translation(cursor, "orig 2", "As rainhas ficaram", "pt")
            save_translation(cursor, "orig 3", "A rainha venceu", "en")
            verified_id = cursor.execute(
                """
                SELECT id
                FROM comments
                WHERE original_comment = ?
                """,
                ("orig 1",),
            ).fetchone()[0]
            set_translation_verified_by_id(cursor, verified_id, True)
            conn.commit()
            conn.close()

            preview = analyze_database_automatic_rules(
                str(db_path),
                target_language="pt",
                automatic_rules=[
                    ("rainha", "dama"),
                    ("mate", "xeque-mate"),
                ],
            )
            self.assertEqual(preview["rules"], 2)
            self.assertEqual(preview["scanned"], 2)
            self.assertEqual(preview["changed"], 1)
            self.assertEqual(len(preview["examples"]), 1)
            self.assertEqual(preview["examples"][0]["id"], verified_id)
            self.assertEqual(
                preview["examples"][0]["previous_translation"],
                "A rainha venceu com mate",
            )
            self.assertEqual(
                preview["examples"][0]["new_translation"],
                "A dama venceu com xeque-mate",
            )
            self.assertIn(
                "A dama venceu com xeque-mate",
                format_automatic_rule_examples(preview["examples"]),
            )

            stats = apply_database_automatic_rules(
                str(db_path),
                target_language="pt",
                automatic_rules=[
                    ("rainha", "dama"),
                    ("mate", "xeque-mate"),
                ],
                backup_dir=str(backup_dir),
            )

            self.assertEqual(stats["changed"], 1)
            self.assertEqual(stats["unchanged"], 1)
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
                history = fetch_comment_history(cursor=conn.cursor(), comment_id=verified_id)
            finally:
                conn.close()

            self.assertEqual(rows["orig 1"], ("A dama venceu com xeque-mate", 1))
            self.assertEqual(rows["orig 2"], ("As rainhas ficaram", 0))
            self.assertEqual(rows["orig 3"], ("A rainha venceu", 0))
            self.assertEqual(history[0][1], "automatic_rules")
            self.assertEqual(history[0][2], "A rainha venceu com mate")
            self.assertEqual(history[0][3], "A dama venceu com xeque-mate")
            self.assertEqual(history[0][4], 1)
            self.assertEqual(history[0][5], 1)

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
                {"total": 5, "pending": 4, "verified": 1, "warnings": 0},
            )
            self.assertEqual(
                get_review_status_counts(cursor, "pt", search_text="orig 4"),
                {"total": 1, "pending": 0, "verified": 1, "warnings": 0},
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
                {"total": 5, "pending": 5, "verified": 0, "warnings": 0},
            )
            conn.close()


class AutomaticRulesSinglePassTests(unittest.TestCase):
    """Item 2.7: uma passagem para aplicar, com progresso e cancelamento.

    `apply_automatic_translation_updates` comecava chamando
    `analyze_automatic_translation_updates` — que percorre a tabela inteira
    aplicando as regras — e so entao percorria tudo de novo para gravar. Com a
    previa que a interface ja calcula, um clique custava tres passagens: 38,1 s
    no banco real, com a janela travada.
    """

    REGRAS = [("rainha", "dama"), ("torre", "roque")]

    def _semear(self, db_path, linhas=40):
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        for indice in range(linhas):
            # Metade muda, metade nao: separa "varreu" de "alterou".
            texto = "A rainha avanca" if indice % 2 == 0 else "O bispo avanca"
            save_translation(cursor, f"orig {indice}", texto, "pt")
        conn.commit()
        conn.close()
        return linhas

    def _contador(self):
        """Envolve a aplicacao de regras contando quantas vezes ela roda."""
        chamadas = []

        def contando(texto, regras):
            chamadas.append(texto)
            return apply_all_substitutions(texto, regras)

        return chamadas, contando

    def test_applying_runs_the_rules_once_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            linhas = self._semear(db_path)
            chamadas, contando = self._contador()

            conn = initialize_database(str(db_path))
            try:
                stats = apply_automatic_translation_updates(
                    conn.cursor(),
                    self.REGRAS,
                    contando,
                    target_language="pt",
                )
                conn.commit()
            finally:
                conn.close()

        self.assertEqual(stats["scanned"], linhas)
        self.assertEqual(stats["changed"], linhas // 2)
        self.assertEqual(
            len(chamadas),
            linhas,
            "as regras foram aplicadas mais de uma vez por linha: "
            "a passagem de analise voltou para dentro da de escrita",
        )

    def test_applying_reports_progress_and_keeps_the_totals_honest(self):
        progresso = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            linhas = self._semear(db_path)

            conn = initialize_database(str(db_path))
            try:
                stats = apply_automatic_translation_updates(
                    conn.cursor(),
                    self.REGRAS,
                    apply_all_substitutions,
                    target_language="pt",
                    progress_callback=lambda feito, total: progresso.append((feito, total)),
                )
                conn.commit()
            finally:
                conn.close()

        self.assertTrue(progresso)
        self.assertEqual(progresso[0], (0, linhas))
        self.assertEqual(progresso[-1], (linhas, linhas))
        self.assertTrue(
            all(0 <= feito <= total == linhas for feito, total in progresso),
            f"progresso incoerente: {progresso}",
        )
        self.assertEqual(stats["scanned"], linhas)

    def test_canceling_leaves_the_database_untouched(self):
        """Cancelar no meio nao pode deixar metade das traducoes alteradas."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            self._semear(db_path, linhas=600)

            def antes():
                conn = sqlite3.connect(str(db_path))
                try:
                    return dict(
                        conn.execute(
                            "SELECT id, translated_comment FROM comments"
                        ).fetchall()
                    )
                finally:
                    conn.close()

            original = antes()

            vistas = {"n": 0}

            def cancelar_depois_de_algumas():
                vistas["n"] += 1
                return vistas["n"] > 1  # cancela cedo, com escritas ja feitas

            with self.assertRaises(AutomaticRulesCanceled):
                apply_database_automatic_rules(
                    str(db_path),
                    target_language="pt",
                    automatic_rules=self.REGRAS,
                    backup_dir=str(tmp_path / "backups"),
                    should_cancel=cancelar_depois_de_algumas,
                )

            self.assertEqual(
                antes(),
                original,
                "o rollback devia ter desfeito as alteracoes ja gravadas",
            )


class FailedRunRecordTests(unittest.TestCase):
    """Roadmap 7.3: guardar quem falhou para reprocessar so isso.

    Antes, terminada uma execucao com falhas, a unica saida era reprocessar tudo:
    os acertos voltavam pelo cache (rapido, mas nao de graca) e as falhas eram
    reencontradas por varredura da pasta inteira.
    """

    def test_a_clean_run_has_no_record_at_all(self):
        """Registro vazio nao existe: o certo e nao haver registro."""
        self.assertIsNone(failed_runs.build_failed_run_record("pt", [], 0))
        self.assertIsNone(failed_runs.build_failed_run_record("pt", ["a.pgn"], 0))
        self.assertIsNone(failed_runs.build_failed_run_record("pt", [], 3))

    def test_the_record_keeps_the_language_of_the_failed_run(self):
        registro = failed_runs.build_failed_run_record("en", ["b.pgn", "a.pgn"], 7)
        self.assertEqual(registro["target_language"], "en")
        self.assertEqual(registro["files"], ["a.pgn", "b.pgn"])
        self.assertEqual(registro["failed_count"], 7)

    def test_duplicated_files_are_counted_once(self):
        registro = failed_runs.build_failed_run_record("pt", ["a.pgn", "a.pgn"], 2)
        self.assertEqual(registro["files"], ["a.pgn"])

    def test_a_truncated_record_is_refused(self):
        """O JSON e editavel a mao e sobrevive a versoes do programa.

        Um registro quebrado nao pode virar um reprocessamento de lista vazia,
        que terminaria em "Concluido" sem ter feito nada.
        """
        for ruim in (
            None,
            {},
            "texto",
            {"files": [], "target_language": "pt"},
            {"files": ["a.pgn"]},
            {"files": ["a.pgn"], "target_language": ""},
            {"target_language": "pt"},
        ):
            with self.subTest(registro=ruim):
                self.assertIsNone(failed_runs.normalize_failed_run_record(ruim))

    def test_files_removed_from_disk_are_separated(self):
        presentes, ausentes = failed_runs.split_existing_files(
            ["existe.pgn", "sumiu.pgn"],
            exists=lambda caminho: caminho == "existe.pgn",
        )
        self.assertEqual(presentes, ["existe.pgn"])
        self.assertEqual(ausentes, ["sumiu.pgn"])

    def test_the_description_warns_about_missing_files(self):
        registro = failed_runs.build_failed_run_record(
            "pt", ["existe.pgn", "sumiu.pgn"], 4
        )
        texto = failed_runs.describe_failed_run(
            registro, exists=lambda caminho: caminho == "existe.pgn"
        )
        self.assertIn("4 comentario(s)", texto)
        self.assertIn("existe.pgn", texto)
        self.assertIn("nao estao mais no disco", texto)

    def test_the_description_says_when_nothing_is_left(self):
        registro = failed_runs.build_failed_run_record("pt", ["sumiu.pgn"], 1)
        texto = failed_runs.describe_failed_run(registro, exists=lambda _c: False)
        self.assertIn("Nenhum arquivo da lista existe mais", texto)

    def test_saving_does_not_erase_other_settings(self):
        """Garantia R4: os rascunhos de traducao vivem no mesmo arquivo."""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({"editor_drafts": {"x": "rascunho"}}, path)

            registro = failed_runs.build_failed_run_record("pt", ["a.pgn"], 2)
            failed_runs.save_failed_run(registro, path)

            disco = settings.load_settings(path)
            self.assertEqual(disco["editor_drafts"], {"x": "rascunho"})
            self.assertEqual(failed_runs.load_failed_run(path), registro)

            failed_runs.clear_failed_run(path)
            self.assertIsNone(failed_runs.load_failed_run(path))
            self.assertEqual(
                settings.load_settings(path)["editor_drafts"], {"x": "rascunho"}
            )


class CallbackErrorReportingTests(unittest.TestCase):
    """Roadmap 6.2 / garantia C3: erro de lock nao pode virar traceback invisivel.

    Sob `pythonw` nao ha console. Ate aqui, um `sqlite3.OperationalError` no
    editor sumia sem deixar rastro e a gravacao apenas nao acontecia — sem
    mensagem, sem log, sem nada que o usuario pudesse notar.
    """

    def test_a_lock_says_what_to_do_about_it(self):
        titulo, mensagem = window_utils.describe_callback_error(
            sqlite3.OperationalError("database is locked")
        )
        self.assertEqual(titulo, window_utils.DATABASE_BUSY_TITLE)
        self.assertIn("traducao em andamento", mensagem)
        self.assertIn("Nada foi gravado", mensagem)
        self.assertIn("tente de novo", mensagem.lower())

    def test_another_database_error_is_not_disguised_as_a_lock(self):
        titulo, mensagem = window_utils.describe_callback_error(
            sqlite3.OperationalError("no such column: foo")
        )
        self.assertEqual(titulo, window_utils.DATABASE_ERROR_TITLE)
        self.assertIn("no such column", mensagem)

    def test_any_other_error_still_reaches_the_user(self):
        titulo, mensagem = window_utils.describe_callback_error(ValueError("xyz"))
        self.assertEqual(titulo, window_utils.UNEXPECTED_ERROR_TITLE)
        self.assertIn("ValueError", mensagem)
        self.assertIn("xyz", mensagem)

    def _reporter(self, relogio):
        raiz = types.SimpleNamespace()
        dialogos = []
        logs = []
        handler = window_utils.install_callback_error_reporter(
            raiz,
            log_message=logs.append,
            show_error=lambda titulo, msg: dialogos.append((titulo, msg)),
            now=lambda: relogio[0],
        )
        return raiz, handler, dialogos, logs

    def dispara(self, handler, exc):
        try:
            raise exc
        except type(exc):
            handler(type(exc), exc, sys.exc_info()[2])

    def test_the_handler_is_installed_on_the_root(self):
        raiz, handler, _dialogos, _logs = self._reporter([0.0])
        self.assertIs(raiz.report_callback_exception, handler)

    def test_a_burst_of_the_same_error_opens_one_dialog(self):
        """Um callback periodico que falha sempre nao pode encher a tela."""
        relogio = [0.0]
        _raiz, handler, dialogos, logs = self._reporter(relogio)

        for _ in range(5):
            relogio[0] += 0.1
            self.dispara(handler, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(dialogos), 1)
        self.assertEqual(len(logs), 10, "toda ocorrencia vai para o log")

    def test_trying_again_later_warns_again(self):
        """A supressao contem rajada; nao pode calar quem tentou de novo."""
        relogio = [0.0]
        _raiz, handler, dialogos, _logs = self._reporter(relogio)

        self.dispara(handler, sqlite3.OperationalError("database is locked"))
        relogio[0] += window_utils.ERROR_DIALOG_REPEAT_SECONDS + 0.1
        self.dispara(handler, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(dialogos), 2)

    def test_a_different_error_is_never_suppressed(self):
        relogio = [0.0]
        _raiz, handler, dialogos, _logs = self._reporter(relogio)

        self.dispara(handler, sqlite3.OperationalError("database is locked"))
        self.dispara(handler, ValueError("outra coisa"))

        self.assertEqual(len(dialogos), 2)

    def test_the_traceback_goes_to_the_log(self):
        _raiz, handler, _dialogos, logs = self._reporter([0.0])
        self.dispara(handler, ValueError("xyz"))

        texto = "\n".join(logs)
        self.assertIn("Traceback", texto)
        self.assertIn("ValueError", texto)

    def test_a_failing_dialog_does_not_replace_the_original_error(self):
        """O relator de erros nao pode ser a proxima fonte de erro."""
        raiz = types.SimpleNamespace()
        logs = []

        def explode(*_args):
            raise RuntimeError("sem display")

        handler = window_utils.install_callback_error_reporter(
            raiz, log_message=logs.append, show_error=explode
        )
        self.dispara(handler, ValueError("xyz"))
        self.assertTrue(logs)


def com_prioridade(entries, priority=GLOSSARY_PRIORITY_DEFAULT):
    """Entradas de tres campos como o arquivo as devolve: com a prioridade.

    A entrada detalhada ganhou um quarto campo no item 1.5 parte 2. Nos testes
    cujo assunto nao e a prioridade, escrever `, 0` em cada tupla so acrescenta
    ruido — mas apagar o campo da comparacao esconderia uma prioridade mexida
    por engano. Este helper diz explicitamente qual prioridade se espera.
    """
    return [
        (orig, new, rule_type, priority) for orig, new, rule_type in entries
    ]


class SynchronousProgress:
    """Substitui `run_with_progress` rodando o trabalho na hora.

    O `run_with_progress` de verdade abre um `CTkToplevel` e sobe uma thread que
    so devolve o resultado por `root.after` — o que exige display e um
    `mainloop()` rodando. Os testes abaixo verificam a ORQUESTRACAO das
    operacoes de banco (o que e chamado, em que ordem, o que acontece ao
    cancelar), e nada disso e sobre a thread.

    O substituto e fiel no que importa: chama o trabalho com um
    `BackgroundTask` de verdade e despacha para `on_success`/`on_error`/
    `on_cancel` pelo mesmo criterio do original. E registra cada chamada, que e
    o que permite exigir que uma operacao passe por aqui — se alguem devolver o
    trabalho para dentro do callback do Tk, a lista fica vazia.
    """

    def __init__(self, cancelar=False):
        self.chamadas = []
        self.cancelar = cancelar

    def install(self, testcase, modulo):
        testcase.addCleanup(setattr, modulo, "run_with_progress", modulo.run_with_progress)
        modulo.run_with_progress = self

    def __call__(
        self,
        parent,
        title,
        work,
        on_success=None,
        on_error=None,
        on_cancel=None,
        message="Processando...",
        allow_cancel=True,
    ):
        self.chamadas.append({"title": title, "message": message, "allow_cancel": allow_cancel})

        task = BackgroundTask()
        if self.cancelar:
            task.cancel()

        try:
            resultado = work(task)
        except TaskCanceled:
            if on_cancel is not None:
                on_cancel(None)
            return task
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            return task

        destino = on_cancel if task.cancelado() else on_success
        if destino is not None:
            destino(resultado)
        return task

    def titles(self):
        return [c["title"] for c in self.chamadas]


class CsvImportSingleReadTests(unittest.TestCase):
    """Roadmap 2.10: previa e aplicacao leem o CSV uma vez so.

    O ganho obvio e nao ler duas vezes. O que importa mais e o outro: relendo, o
    usuario confirma numeros calculados sobre um arquivo e a gravacao acontece
    sobre outro, se ele mudar no intervalo. Por isso os testes exercem essa
    janela, e nao so contam leituras.
    """

    CABECALHO = "original_comment,translated_comment,target_language,verified\n"

    def escreve_csv(self, path, linhas):
        path.write_text(
            self.CABECALHO + "".join(f"{o},{t},pt,0\n" for o, t in linhas),
            encoding="utf-8",
        )

    def test_the_apply_uses_the_rows_the_preview_showed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            csv_path = base / "entrada.csv"
            initialize_database(str(db_path)).close()
            self.escreve_csv(csv_path, [("alfa", "um"), ("beta", "dois")])

            linhas = db_tools._read_translation_csv_rows(str(csv_path))
            preview = analyze_translations_csv_import(
                str(db_path), str(csv_path), csv_rows=linhas
            )

            # O arquivo muda entre a confirmacao e a gravacao.
            self.escreve_csv(csv_path, [("gama", "tres")] * 40)

            stats = import_translations_from_csv(
                str(db_path),
                str(csv_path),
                create_backup=False,
                csv_rows=linhas,
            )

            self.assertEqual(preview["inserted"], 2)
            self.assertEqual(stats["inserted"], preview["inserted"])
            self.assertEqual(stats["total_rows"], preview["total_rows"])

            conn = initialize_database(str(db_path))
            gravados = {
                row[0]
                for row in conn.execute(
                    "SELECT original_comment FROM comments"
                ).fetchall()
            }
            conn.close()
            self.assertEqual(gravados, {"alfa", "beta"}, "gravou o CSV trocado")

    def test_the_ui_flow_reads_the_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            csv_path = base / "entrada.csv"
            initialize_database(str(db_path)).close()
            self.escreve_csv(csv_path, [("alfa", "um"), ("beta", "dois")])

            leituras = []
            original = db_tools._read_translation_csv_rows

            def contando(caminho):
                leituras.append(caminho)
                return original(caminho)

            app = types.SimpleNamespace(
                output_db=str(db_path), translation_cache={}, root=None
            )
            patches = [
                (db_tools, "_read_translation_csv_rows", contando),
                (db_tools, "filedialog", types.SimpleNamespace(
                    askopenfilename=lambda **_kw: str(csv_path))),
                (db_tools, "messagebox", types.SimpleNamespace(
                    askyesno=lambda *_a, **_kw: True,
                    showinfo=lambda *_a, **_kw: None,
                    showerror=lambda *_a, **_kw: None)),
            ]
            for modulo, nome, novo in patches:
                self.addCleanup(setattr, modulo, nome, getattr(modulo, nome))
                setattr(modulo, nome, novo)

            # A importacao passou a rodar fora da thread do Tk (item 2.11), e
            # `run_with_progress` precisa de display e `mainloop`. O que este
            # teste afirma — quantas vezes o CSV e lido — nao mudou.
            SynchronousProgress().install(self, db_tools)
            db_tools.import_csv(app)

            self.assertEqual(len(leituras), 1, f"o CSV foi lido {len(leituras)} vezes")

    def test_the_glossary_import_applies_the_previewed_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            glossary = base / "Substituicoes.txt"
            csv_path = base / "regras.csv"
            save_glossary_entries(
                [("rook", "torre", "suggestion")], str(glossary), create_backup=False
            )
            csv_path.write_text(
                "original,replacement\nqueen,dama\nbishop,bispo\n", encoding="utf-8"
            )

            preview = analyze_glossary_csv_import(str(glossary), str(csv_path))
            csv_path.write_text(
                "original,replacement\nknight,cavalo\n", encoding="utf-8"
            )

            stats = import_glossary_csv(
                str(glossary),
                str(csv_path),
                backup_dir=str(base / "backups"),
                analysis=preview,
            )

            entradas = load_glossary_entry_details(str(glossary), deduplicate=False)
            pares = {(orig, new) for orig, new, _tipo, _prio in entradas}
            self.assertEqual(stats["inserted"], 2)
            self.assertIn(("queen", "dama"), pares)
            self.assertIn(("bishop", "bispo"), pares)
            self.assertNotIn(("knight", "cavalo"), pares, "importou o CSV trocado")

    def test_reading_is_still_automatic_when_no_rows_are_given(self):
        """Quem chama sem a previa continua funcionando como antes."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            csv_path = base / "entrada.csv"
            initialize_database(str(db_path)).close()
            self.escreve_csv(csv_path, [("alfa", "um")])

            self.assertEqual(
                analyze_translations_csv_import(str(db_path), str(csv_path))["inserted"],
                1,
            )
            self.assertEqual(
                import_translations_from_csv(
                    str(db_path), str(csv_path), create_backup=False
                )["inserted"],
                1,
            )


class RestrictedTranslationCacheTests(unittest.TestCase):
    """Roadmap 2.9: carregar so os comentarios que a execucao vai consultar.

    Carregar o idioma inteiro trazia 195 mil traducoes (74 MB) para traduzir uma
    pasta com algumas centenas de comentarios. O worker so pergunta ao cache por
    comentarios que extraiu dos arquivos, entao o resto nunca foi consultado.
    """

    def banco(self, quantos=12):
        """Banco de teste que se fecha ANTES de o diretorio ser removido.

        A ordem importa e custou um diagnostico errado: no Windows um arquivo
        SQLite aberto nao pode ser apagado, entao um teste que falhe antes do
        `close` estoura na limpeza e o `PermissionError` aparece NO LUGAR da
        falha de verdade. `addCleanup` roda em ordem inversa, entao o diretorio
        e registrado primeiro e a conexao depois.
        """
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)

        cur = conn.cursor()
        for i in range(quantos):
            save_translation(cur, f"original {i}", f"traducao {i}", "pt")
        save_translation(cur, "outro idioma", "otra", "en")
        # Uma traducao vazia: o cache nunca deve trazer o que nao foi traduzido.
        save_translation(cur, "sem traducao", "", "pt")
        conn.commit()
        return cur

    def test_it_brings_exactly_the_requested_translations(self):
        cur = self.banco()
        self.assertEqual(
            load_translation_cache(cur, "pt", ["original 3", "original 7"]),
            {"original 3": "traducao 3", "original 7": "traducao 7"},
        )

    def test_the_restricted_load_agrees_with_the_full_one(self):
        """O criterio que importa: mesma resposta, para o que foi pedido."""
        cur = self.banco()
        completo = load_translation_cache(cur, "pt")
        pedidos = ["original 0", "original 5", "sem traducao", "nao existe"]
        restrito = load_translation_cache(cur, "pt", pedidos)

        for comentario in pedidos:
            with self.subTest(comentario=comentario):
                self.assertEqual(restrito.get(comentario), completo.get(comentario))

    def test_it_never_brings_another_language(self):
        cur = self.banco()
        self.assertEqual(load_translation_cache(cur, "pt", ["outro idioma"]), {})

    def test_an_untranslated_comment_is_not_in_the_cache(self):
        """Senao o worker daria por traduzido o que esta vazio."""
        cur = self.banco()
        self.assertEqual(load_translation_cache(cur, "pt", ["sem traducao"]), {})

    def test_asking_for_nothing_returns_nothing(self):
        cur = self.banco()
        self.assertEqual(load_translation_cache(cur, "pt", []), {})

    def test_repeated_comments_are_asked_only_once(self):
        """O mesmo comentario aparece em varios arquivos."""
        cur = self.banco()
        pedidos = ["original 1"] * 50 + ["original 2"]
        self.assertEqual(
            load_translation_cache(cur, "pt", pedidos),
            {"original 1": "traducao 1", "original 2": "traducao 2"},
        )

    def test_it_survives_more_comments_than_sqlite_accepts_as_parameters(self):
        """O limite de parametros do SQLite: sem os lotes, isto e um erro.

        Nao e um limite teorico — uma pasta com alguns milhares de comentarios
        distintos passa dele com folga.
        """
        quantos = database.CACHE_LOOKUP_CHUNK * 3 + 7
        cur = self.banco(quantos=quantos)
        pedidos = [f"original {i}" for i in range(quantos)]

        # O que esta sob teste sao os lotes, entao o atalho da carga completa
        # sai do caminho: com ele, pedir a tabela inteira nunca chegaria ao `IN`.
        anterior = database.CACHE_FULL_LOAD_RATIO
        database.CACHE_FULL_LOAD_RATIO = 2.0
        self.addCleanup(setattr, database, "CACHE_FULL_LOAD_RATIO", anterior)

        class CursorQueConta:
            def __init__(self, real):
                self.real = real
                self.consultas = 0

            def execute(self, *a, **k):
                self.consultas += 1
                return self.real.execute(*a, **k)

            def fetchall(self):
                return self.real.fetchall()

        contador = CursorQueConta(cur)
        cache = load_translation_cache(contador, "pt", pedidos)

        self.assertEqual(len(cache), quantos)
        self.assertEqual(cache["original 0"], "traducao 0")
        self.assertEqual(cache[f"original {quantos - 1}"], f"traducao {quantos - 1}")

        # A contagem e o que prova os lotes. O limite de parametros do SQLite
        # moderno e 32766, entao 2.707 numa consulta so passaria — e o teste nao
        # veria a falta dos lotes ate alguem rodar num SQLite antigo (limite 999)
        # ou processar uma pasta bem maior.
        lotes = -(-quantos // database.CACHE_LOOKUP_CHUNK)   # divisao para cima
        # A consulta extra e o `COUNT` que decide entre carga restrita e
        # completa: acima de `CACHE_RATIO_CHECK_MINIMUM` ele sempre roda.
        self.assertEqual(
            contador.consultas, lotes + 1, "os comentarios nao foram em lotes"
        )
        self.assertLessEqual(quantos / lotes, database.CACHE_LOOKUP_CHUNK)

    def test_a_large_slice_falls_back_to_loading_everything(self):
        """Acima do limite, procurar um a um sai mais caro que ler tudo.

        Errar a escolha nao produz resultado errado — as duas cargas respondem o
        mesmo para o que foi pedido —, so um tempo pior. Por isso o teste afirma
        a decisao, e nao o conteudo.
        """
        cur = self.banco(quantos=100)
        total = 101  # 100 traduzidos + "sem traducao"

        # O piso e a razao sao regras distintas. Aqui interessa a razao, entao o
        # piso sai do caminho: com ele valendo, um banco de 101 linhas nunca
        # chegaria a consultar o tamanho da tabela.
        anterior = database.CACHE_RATIO_CHECK_MINIMUM
        database.CACHE_RATIO_CHECK_MINIMUM = 0
        self.addCleanup(setattr, database, "CACHE_RATIO_CHECK_MINIMUM", anterior)

        self.assertTrue(
            database._full_load_is_cheaper(cur, "pt", total),
            "pedir a tabela inteira tinha de cair na carga completa",
        )
        self.assertTrue(
            database._full_load_is_cheaper(cur, "pt", int(total * 0.6)),
            "acima da fracao limite tambem",
        )
        self.assertFalse(
            database._full_load_is_cheaper(cur, "pt", int(total * 0.2)),
            "um pedido pequeno nunca deve carregar tudo",
        )

    def test_the_fallback_still_answers_what_was_asked(self):
        """Caindo na carga completa, o que foi pedido continua certo.

        Ela devolve um superconjunto — o idioma inteiro —, e isso e proposital:
        o contrato e "contem os pedidos que existem", nao "contem so os pedidos".
        """
        cur = self.banco(quantos=100)
        anterior = database.CACHE_RATIO_CHECK_MINIMUM
        database.CACHE_RATIO_CHECK_MINIMUM = 0
        self.addCleanup(setattr, database, "CACHE_RATIO_CHECK_MINIMUM", anterior)

        cache = load_translation_cache(cur, "pt", [f"original {i}" for i in range(90)])
        for i in range(90):
            self.assertEqual(cache[f"original {i}"], f"traducao {i}")

        # E a prova de que o atalho foi mesmo tomado: veio o que ninguem pediu.
        self.assertIn(
            "original 95", cache, "a carga completa nao foi usada acima do limite"
        )

    def test_a_small_request_never_pays_for_the_count(self):
        """Abaixo do minimo nem se pergunta o tamanho da tabela.

        Consultar custa ~10 ms; a carga restrita de ate 1800 comentarios custa
        ~26 ms. Gastar 10 ms para decidir seria quase metade do trabalho.
        """

        class CursorQueRecusa:
            def execute(self, *_a, **_k):
                raise AssertionError("consultou o tamanho da tabela sem precisar")

        self.assertFalse(
            database._full_load_is_cheaper(
                CursorQueRecusa(), "pt", database.CACHE_RATIO_CHECK_MINIMUM - 1
            )
        )


class SharedEditorWidgetsTests(unittest.TestCase):
    """Roadmap 3.2: as pecas que os dois editores usavam em copia.

    `save_window_section` e a que importa: ela implementa a garantia R4 —
    gravar SO a secao desta janela, relendo o disco antes. Enquanto existiam
    duas copias, corrigir uma e esquecer a outra reproduzia exatamente o defeito
    que R4 existe para impedir, e sem quebrar nada na hora: o usuario e que
    perdia um rascunho depois.

    Nao precisa de Tk: `window=None` e `sashes=()` cobrem a parte que mexe no
    disco, que e a arriscada.
    """

    def test_it_writes_only_its_own_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings(
                {"editor_drafts": {"x": "rascunho"}, "editor": {"font_size": 9}}, path
            )
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            local = {"glossary_editor": {"sort": "antiga"}}
            editor_widgets.save_window_section(
                local, "glossary_editor", {"sort": "Original A-Z"}
            )

            disco = settings.load_settings(path)
            self.assertEqual(disco["glossary_editor"]["sort"], "Original A-Z")
            self.assertEqual(disco["editor_drafts"], {"x": "rascunho"}, "apagou rascunhos")
            self.assertEqual(disco["editor"], {"font_size": 9}, "apagou a outra janela")

    def test_it_rereads_the_disk_instead_of_writing_its_snapshot(self):
        """O caso concreto que R4 descreve: a outra janela gravou nesse meio-tempo."""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            # Snapshot que esta janela carregou na abertura: ainda sem rascunhos.
            local = settings.load_settings(path)
            # A outra janela grava um rascunho DEPOIS disso.
            settings.save_settings({"editor_drafts": {"y": "novo"}}, path)

            editor_widgets.save_window_section(local, "editor", {"font_size": 14})

            disco = settings.load_settings(path)
            self.assertEqual(
                disco["editor_drafts"],
                {"y": "novo"},
                "gravou o snapshot antigo por cima do que a outra janela escreveu",
            )
            self.assertEqual(disco["editor"]["font_size"], 14)

    def test_a_corrupted_section_is_replaced_and_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({"editor": "isto nao e um dicionario"}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            editor_widgets.save_window_section({}, "editor", {"font_size": 12})
            self.assertEqual(settings.load_settings(path)["editor"], {"font_size": 12})

    def test_the_local_snapshot_stays_coherent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            settings.save_settings({}, path)
            self.addCleanup(setattr, settings, "default_settings_path",
                            settings.default_settings_path)
            settings.default_settings_path = lambda: path

            local = {}
            editor_widgets.save_window_section(local, "editor", {"font_size": 20})
            self.assertEqual(local["editor"]["font_size"], 20)

    def test_the_sash_limits_keep_a_panel_reachable(self):
        """A decisao de onde colocar o divisor, sem abrir janela.

        Uma posicao gravada numa tela grande deixaria o painel fora da janela
        numa tela menor, e nao haveria como traze-lo de volta a nao ser apagando
        as configuracoes na mao.
        """
        self.assertEqual(editor_common.clamped_sash_position(400, 360, 520), 400)
        self.assertEqual(editor_common.clamped_sash_position(9999, 360, 520), 520)
        self.assertEqual(editor_common.clamped_sash_position(10, 360, 520), 360)
        self.assertEqual(editor_common.clamped_sash_position(600, 520), 600, "sem teto")

    def test_a_position_that_was_never_saved_is_refused(self):
        for valor in (None, 0, -5, "480", 12.5, True):
            with self.subTest(valor=valor):
                self.assertIsNone(editor_common.clamped_sash_position(valor, 360, 520))

    def test_a_disk_failure_does_not_propagate(self):
        """A chamada acontece ao fechar a janela: falhar ali nao pode derrubar nada."""
        self.addCleanup(setattr, settings, "update_settings", settings.update_settings)
        self.addCleanup(setattr, editor_widgets, "update_settings",
                        editor_widgets.update_settings)

        def explode(_mutator, _path=None):
            raise OSError("disco cheio")

        editor_widgets.update_settings = explode
        local = {}
        editor_widgets.save_window_section(local, "editor", {"font_size": 11})
        self.assertEqual(local["editor"]["font_size"], 11, "o snapshot local continua")


class FullTextSearchTests(unittest.TestCase):
    """Roadmap 2.8 / garantia R8: busca por termos indexada, `LIKE` preservado.

    `LIKE '%termo%'` tem curinga a esquerda e nenhum indice o atende, entao com
    busca ativa cada interacao varria a tabela. O FTS5 resolve isso, mas ao
    preco de uma semantica diferente — casa palavra inteira. Por isso as duas
    formas convivem: nenhuma substitui a outra.
    """

    LINHAS = [
        ("O bispo domina a diagonal", "El alfil domina la diagonal"),
        ("A torre entra na coluna aberta", "La torre entra en la columna"),
        ("Traducao com acento: proximo", "Tradução com acento: próximo"),
        ("Somente acentuado: ameaça", "Sólo acentuado: amenaza"),
        ("O cavalo salta", "El caballo salta"),
    ]

    def banco(self, tmp):
        conn = initialize_database(str(Path(tmp) / "cache.db"))
        cur = conn.cursor()
        for original, traduzido in self.LINHAS:
            save_translation(cur, original, traduzido, "pt")
        conn.commit()
        return conn, cur

    def busca(self, cur, texto, modo=SEARCH_MODE_TERMS):
        return sorted(
            row[1]
            for row in fetch_review_rows(cur, "pt", search_text=texto, search_mode=modo)
        )

    # ------------------------------------------------ a expressao enviada ao FTS

    def test_the_query_is_built_from_whole_words(self):
        self.assertEqual(build_fts_match_query("bispo"), '"bispo"')
        self.assertEqual(build_fts_match_query("torre coluna"), '"torre" "coluna"')
        self.assertEqual(build_fts_match_query("  espacos   demais "), '"espacos" "demais"')

    def test_a_trailing_star_becomes_a_prefix_query(self):
        """E o que devolve o casamento parcial que o `LIKE` dava de graca."""
        self.assertEqual(build_fts_match_query("bisp*"), '"bisp"*')
        self.assertEqual(build_fts_match_query("bisp* torre"), '"bisp"* "torre"')

    def test_fts_operators_are_neutralized(self):
        """Sem isto, uma busca comum viraria erro de sintaxe no meio da navegacao.

        `AND`, `-`, `(`, `"` e `:` sao operadores do FTS5. Um usuario que digite
        `bispo (branco)` nao esta pedindo uma expressao booleana.
        """
        self.assertEqual(build_fts_match_query('bispo "branco"'), '"bispo" "branco"')
        self.assertEqual(build_fts_match_query("bispo (branco)"), '"bispo" "branco"')
        self.assertEqual(build_fts_match_query("a AND b"), '"a" "AND" "b"')
        self.assertEqual(build_fts_match_query("coluna: aberta"), '"coluna" "aberta"')

    def test_a_query_with_nothing_to_match_is_none(self):
        for vazio in ("", "   ", None, "((", "-- ::"):
            with self.subTest(entrada=vazio):
                self.assertIsNone(build_fts_match_query(vazio))

    # ------------------------------------------------ as duas semanticas

    def test_terms_match_whole_words_and_substring_matches_pieces(self):
        """A diferenca entre os dois modos, lado a lado.

        E a razao de os dois existirem: `bisp` so acha "bispo" por trecho, e
        exigir que o usuario saiba escrever `bisp*` para toda busca parcial
        seria trocar um custo por outro.
        """
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)

            self.assertEqual(self.busca(cur, "bispo"), ["O bispo domina a diagonal"])
            self.assertEqual(self.busca(cur, "bisp"), [], "termo casa palavra inteira")
            self.assertEqual(self.busca(cur, "bisp*"), ["O bispo domina a diagonal"])
            self.assertEqual(
                self.busca(cur, "bisp", SEARCH_MODE_SUBSTRING),
                ["O bispo domina a diagonal"],
                "o `LIKE` continua achando o trecho",
            )
            conn.close()

    def test_the_search_covers_both_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            self.assertEqual(self.busca(cur, "caballo"), ["O cavalo salta"])
            self.assertEqual(self.busca(cur, "cavalo"), ["O cavalo salta"])
            conn.close()

    def test_accents_are_folded(self):
        """`remove_diacritics 2`: num corpus em portugues isso decide muita busca.

        A palavra tem de existir SO na forma acentuada. Se a versao sem acento
        estiver em qualquer das duas colunas, a busca acha por ela e o teste
        passa mesmo com a dobra desligada — foi o que a verificacao por mutacao
        mostrou sobre a primeira versao deste teste.
        """
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            self.assertNotIn(
                "ameaca",
                " ".join(o + " " + t for o, t in self.LINHAS),
                "a forma sem acento nao pode existir em lugar nenhum",
            )
            self.assertEqual(
                self.busca(cur, "ameaca"),
                ["Somente acentuado: ameaça"],
                "buscar sem acento tem de achar a palavra acentuada",
            )
            self.assertEqual(self.busca(cur, "ameaça"), ["Somente acentuado: ameaça"])
            conn.close()

    def test_several_terms_are_all_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            self.assertEqual(
                self.busca(cur, "torre coluna"), ["A torre entra na coluna aberta"]
            )
            self.assertEqual(self.busca(cur, "torre cavalo"), [])
            conn.close()

    # ------------------------------------------------ o indice acompanha a tabela

    def test_the_index_follows_updates_and_deletes(self):
        """O ponto fragil do "external content": quem sincroniza sao os gatilhos.

        Sem o comando `'delete'` com os valores antigos, os termos de uma linha
        removida ficam no indice e a busca passa a devolver linhas que nao
        existem mais — um resultado errado, nao um erro.
        """
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            alvo = cur.execute(
                "SELECT id FROM comments WHERE original_comment = ?",
                ("O bispo domina a diagonal",),
            ).fetchone()[0]

            update_translation_by_id(cur, alvo, "El caballo salta agora", False)
            conn.commit()
            self.assertEqual(self.busca(cur, "alfil"), [], "termo antigo sobreviveu")
            self.assertEqual(self.busca(cur, "agora"), ["O bispo domina a diagonal"])

            cur.execute("DELETE FROM comments WHERE id = ?", (alvo,))
            conn.commit()
            self.assertEqual(self.busca(cur, "bispo"), [], "linha removida ainda aparece")

            # O indice PRECISA ser inspecionado direto. A consulta normal cruza
            # com `comments`, entao uma entrada orfa fica invisivel por ela — e o
            # `integrity-check` do FTS5 tambem nao acusa este caso (verificado).
            # Sem esta linha, remover o comando `'delete'` do gatilho passaria
            # despercebido ate o indice encher de lixo.
            orfas = cur.execute(
                f"SELECT count(*) FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
                ('"agora"',),
            ).fetchone()[0]
            self.assertEqual(orfas, 0, "os termos da linha removida ficaram no indice")
            conn.close()

    def test_the_index_is_built_for_a_database_that_already_had_rows(self):
        """A migracao popula o indice com o que ja estava no banco."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "antigo.db")
            conn, cur = self.banco(tmp)
            conn.close()

            # Simula um banco de versao anterior: sem indice e sem os gatilhos.
            conn = sqlite3.connect(str(Path(tmp) / "cache.db"))
            conn.execute(f"DROP TABLE {FTS_TABLE}")
            for gatilho in ("insert", "delete", "update"):
                conn.execute(f"DROP TRIGGER comments_fts_{gatilho}")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            conn.close()

            conn = initialize_database(str(Path(tmp) / "cache.db"))
            cur = conn.cursor()
            self.assertEqual(self.busca(cur, "bispo"), ["O bispo domina a diagonal"])
            conn.close()

    # ------------------------------------------------ degradacao

    def test_without_the_index_the_search_still_works(self):
        """Sem FTS5 o programa nao pode parar: cai no `LIKE` e continua correto."""
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            cur.execute(f"DROP TABLE {FTS_TABLE}")
            conn.commit()

            self.assertFalse(fts_index_ready(cur))
            self.assertEqual(
                self.busca(cur, "bispo"),
                ["O bispo domina a diagonal"],
                "sem indice a busca por termos tinha de cair no LIKE",
            )
            conn.close()

    def test_a_query_with_no_usable_term_falls_back_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            # `((` nao tem termo nenhum: vai pelo LIKE, e nao acha nada.
            self.assertEqual(self.busca(cur, "(("), [])
            conn.close()

    def test_the_two_modes_agree_when_the_term_is_a_whole_word(self):
        """Contraprova: onde as semanticas coincidem, o resultado tem de coincidir."""
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            for termo in ("bispo", "torre", "cavalo", "salta", "inexistente"):
                with self.subTest(termo=termo):
                    self.assertEqual(
                        self.busca(cur, termo, SEARCH_MODE_TERMS),
                        self.busca(cur, termo, SEARCH_MODE_SUBSTRING),
                    )
            conn.close()

    def test_counting_and_paging_agree_with_the_rows(self):
        """O modo tem de valer nas tres consultas, senao a paginacao mente."""
        with tempfile.TemporaryDirectory() as tmp:
            conn, cur = self.banco(tmp)
            # `torr` e escolhido de proposito: por termo nao casa nada (palavra
            # inteira) e por trecho casa "torre". Com um termo em que os dois
            # modos concordam, uma consulta que ignorasse o modo passaria.
            esperado = {SEARCH_MODE_TERMS: 0, SEARCH_MODE_SUBSTRING: 1}
            for modo, quantas in esperado.items():
                with self.subTest(modo=modo):
                    total = count_review_rows(
                        cur, "pt", search_text="torr", search_mode=modo
                    )
                    pagina = fetch_review_rows_page(
                        cur, "pt", limit=100, offset=0,
                        search_text="torr", search_mode=modo,
                    )
                    resumo = get_review_status_counts(
                        cur, "pt", search_text="torr", search_mode=modo
                    )
                    self.assertEqual(total, quantas, "a contagem nao respeitou o modo")
                    self.assertEqual(len(pagina), quantas, "a pagina nao respeitou o modo")
                    self.assertEqual(resumo["total"], quantas, "o resumo nao respeitou o modo")
            conn.close()


class StatusCountReuseTests(unittest.TestCase):
    """Roadmap 2.8: o total do filtro sai do resumo, sem uma segunda varredura.

    `get_review_status_counts` e `count_review_rows` varriam a mesma tabela com o
    mesmo `WHERE` a cada interacao do editor, e a segunda pedia um numero que a
    primeira ja tinha separado por status. Com busca ativa isso custa ~100 ms por
    troca de pagina, porque `LIKE '%termo%'` nao usa indice.

    O risco de reaproveitar e silencioso: os dois criterios vivem em lugares
    diferentes (`_review_where` e os `CASE` da agregada) e podem divergir sem que
    nada quebre na tela — a lista so passa a paginar pelo numero errado. Por isso
    o teste compara os dois caminhos em vez de conferir constantes.
    """

    FILTROS = ("all", "pending", "verified", "warnings")

    def _dataset(self, cursor):
        # Traducao igual ao original => aviso de qualidade; diferente => sem.
        save_translation(cursor, "alfa original", "alfa original", "pt")
        save_translation(cursor, "beta original", "beta original", "pt")
        save_translation(cursor, "gama original", "uma traducao bem diferente", "pt")
        save_translation(cursor, "delta original", "outra traducao diferente", "pt")
        save_translation(cursor, "alfa em outro idioma", "seja la o que for", "en")
        cursor.execute(
            "UPDATE comments SET verified = 1 WHERE original_comment IN (?, ?)",
            ("beta original", "gama original"),
        )

    def test_every_filter_total_matches_a_dedicated_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "cache.db"))
            cursor = conn.cursor()
            self._dataset(cursor)
            conn.commit()

            # Sem busca, com busca que acha, e com busca que nao acha nada — os
            # tres caminhos que o editor produz.
            for busca in ("", "original", "alfa", "inexistente"):
                resumo = get_review_status_counts(cursor, "pt", busca)
                for filtro in self.FILTROS:
                    with self.subTest(busca=busca, filtro=filtro):
                        self.assertEqual(
                            count_from_status_counts(resumo, filtro),
                            count_review_rows(
                                cursor, "pt", search_text=busca, status_filter=filtro
                            ),
                        )
            conn.close()

    def test_the_dataset_exercises_every_filter(self):
        """Sem isto, o teste acima passaria comparando zeros."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "cache.db"))
            cursor = conn.cursor()
            self._dataset(cursor)
            conn.commit()

            resumo = get_review_status_counts(cursor, "pt")
            for filtro in self.FILTROS:
                self.assertGreater(
                    count_from_status_counts(resumo, filtro),
                    0,
                    f"o filtro {filtro!r} nao tem nenhuma linha para comparar",
                )
            conn.close()

    def test_only_unverified_reads_the_pending_total(self):
        resumo = {"total": 9, "pending": 7, "verified": 2, "warnings": 3}
        self.assertEqual(count_from_status_counts(resumo, only_unverified=True), 7)
        self.assertEqual(count_from_status_counts(resumo), 9)

    def test_an_unknown_filter_falls_back_instead_of_guessing(self):
        """O chamador precisa saber que o resumo nao serve, e nao receber zero."""
        resumo = {"total": 9, "pending": 7, "verified": 2, "warnings": 3}
        self.assertIsNone(count_from_status_counts(resumo, "filtro-que-nao-existe"))


class QualityWarningColumnTests(unittest.TestCase):
    """A coluna quality_warning e um cache; o perigo e ela ficar obsoleta."""

    def _flags(self, cursor):
        return dict(
            cursor.execute(
                "SELECT id, quality_warning FROM comments ORDER BY id"
            ).fetchall()
        )

    def _recalculado(self, cursor):
        return {
            row_id: (1 if evaluate_translation_quality(orig, trans) else 0)
            for row_id, orig, trans in cursor.execute(
                "SELECT id, original_comment, translated_comment FROM comments ORDER BY id"
            ).fetchall()
        }

    def test_column_stays_in_sync_across_every_write_path(self):
        longo = "White plays a very strong move on the kingside " * 2
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "cache.db"))
            cursor = conn.cursor()

            # 1. insercao: uma com aviso (chaves), uma sem
            save_translation(cursor, "White plays", "As brancas jogam", "pt")
            save_translation(cursor, "Black plays", "Contem {chaves}", "pt")
            # 2. linha vazia depois preenchida
            save_translation(cursor, longo, "", "pt")
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[2], 1)  # chaves -> aviso

            # 3. preenchimento de vazia com traducao curta demais -> aviso
            save_translation(cursor, longo, "curta", "pt")
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[3], 1)

            # 4. edicao manual que RESOLVE o aviso
            update_translation_by_id(cursor, 2, "Sem chaves agora")
            conn.commit()
            self.assertEqual(self._flags(cursor)[2], 0)
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # 5. edicao manual que CRIA um aviso
            update_translation_by_id(cursor, 1, "{quebrado}")
            conn.commit()
            self.assertEqual(self._flags(cursor)[1], 1)
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # 6. verificar nao mexe no texto, entao nao pode mexer no flag
            antes = self._flags(cursor)
            set_translation_verified_by_id(cursor, 1, True)
            conn.commit()
            self.assertEqual(self._flags(cursor), antes)

            # 7. regras automaticas em massa
            apply_automatic_translation_updates(
                cursor,
                [("{quebrado}", "consertado")],
                apply_automatic_substitutions,
                target_language="pt",
            )
            conn.commit()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))
            self.assertEqual(self._flags(cursor)[1], 0)

            conn.close()

    def test_backfill_fills_legacy_rows_and_counts_match_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            conn = initialize_database(db_path)
            cursor = conn.cursor()
            for i in range(30):
                trans = "Contem {chaves}" if i % 3 == 0 else f"Traducao boa {i}"
                save_translation(cursor, f"Original number {i}", trans, "pt")
            conn.commit()

            # Simula uma base antiga: coluna existe mas esta toda NULL.
            cursor.execute("UPDATE comments SET quality_warning = NULL")
            cursor.execute("PRAGMA user_version = 0")
            conn.commit()
            conn.close()

            # Reabrir dispara a migracao e o backfill.
            conn = initialize_database(db_path)
            cursor = conn.cursor()
            self.assertEqual(self._flags(cursor), self._recalculado(cursor))

            # A contagem em SQL tem de bater com a avaliacao em Python.
            esperado = len(
                filter_quality_warning_rows(fetch_review_rows(cursor, "pt"))
            )
            self.assertEqual(
                count_review_rows(cursor, "pt", status_filter="warnings"),
                esperado,
            )
            self.assertEqual(
                get_review_status_counts(cursor, "pt")["warnings"],
                esperado,
            )

            # E a pagina do filtro so pode trazer linhas que realmente tem aviso.
            pagina = fetch_review_rows_page(
                cursor, "pt", limit=100, offset=0, status_filter="warnings"
            )
            self.assertTrue(pagina)
            self.assertTrue(all(row_has_quality_warning(row) for row in pagina))
            self.assertEqual(len(pagina), esperado)
            conn.close()

    def test_migration_runs_once_and_is_skipped_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            conn = initialize_database(db_path)
            conn.close()

            conn = initialize_database(db_path)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            # Nada a preencher numa base ja migrada.
            self.assertEqual(backfill_quality_warnings(conn), 0)
            conn.close()


class EditorCommonTests(unittest.TestCase):
    """Logica das janelas de edicao, agora testavel sem abrir uma janela."""

    def test_page_count_and_clamp(self):
        self.assertEqual(page_count(0, 100), 0)
        self.assertEqual(page_count(1, 100), 1)
        self.assertEqual(page_count(100, 100), 1)
        self.assertEqual(page_count(101, 100), 2)
        self.assertEqual(page_count(250, 100), 3)
        # Defensivo: nao pode estourar com tamanho de pagina invalido.
        self.assertEqual(page_count(10, 0), 0)
        self.assertEqual(page_count(-5, 100), 0)

        # Depois de excluir/filtrar, a pagina atual pode ficar alem do fim.
        self.assertEqual(clamp_page(5, 250, 100), 2)
        self.assertEqual(clamp_page(0, 250, 100), 0)
        self.assertEqual(clamp_page(-3, 250, 100), 0)
        self.assertEqual(clamp_page(7, 0, 100), 0)

    def test_offsets_round_trip(self):
        self.assertEqual(page_offset(0, 100), 0)
        self.assertEqual(page_offset(3, 100), 300)
        self.assertEqual(page_offset(-1, 100), 0)

        self.assertEqual(page_of_offset(0, 100), 0)
        self.assertEqual(page_of_offset(99, 100), 0)
        self.assertEqual(page_of_offset(100, 100), 1)
        self.assertEqual(page_of_offset(250, 100), 2)

        for offset in (0, 1, 99, 100, 101, 999):
            pagina = page_of_offset(offset, 100)
            self.assertLessEqual(page_offset(pagina, 100), offset)
            self.assertLess(offset - page_offset(pagina, 100), 100)

    def test_local_index_is_clamped_to_the_page_actually_returned(self):
        # Caso normal.
        self.assertEqual(local_index_for_offset(250, 100, 100), 50)
        # A pagina veio menor do que o esperado (o banco mudou no meio):
        # o indice tem de ser limitado, nao estourar IndexError depois.
        self.assertEqual(local_index_for_offset(250, 100, 10), 9)
        # Pagina vazia.
        self.assertIsNone(local_index_for_offset(250, 100, 0))

    def test_clamp_geometry_fits_saved_window_into_current_screen(self):
        # Cabe: preservado.
        self.assertEqual(
            clamp_geometry("1200x700+100+50", 1920, 1080, 1120, 680),
            "1200x700+100+50",
        )
        # Posicao negativa salva num monitor que nao existe mais.
        self.assertEqual(
            clamp_geometry("1360x705+-71+28", 1920, 1080, 1120, 680),
            "1360x705+0+28",
        )
        # Maior que a tela atual: encolhe e reposiciona.
        self.assertEqual(
            clamp_geometry("3000x2000+500+400", 1920, 1080, 1120, 680),
            "1920x1080+0+0",
        )
        # Menor que o minimo da janela: cresce.
        self.assertEqual(
            clamp_geometry("300x200+10+10", 1920, 1080, 1120, 680),
            "1120x680+10+10",
        )
        # Formato desconhecido passa intacto.
        self.assertEqual(clamp_geometry("zoomed", 1920, 1080, 1120, 680), "zoomed")
        self.assertIsNone(clamp_geometry(None, 1920, 1080, 1120, 680))

    def test_preview_collapses_whitespace_and_truncates(self):
        self.assertEqual(preview("  varios   espacos \n aqui "), "varios espacos aqui")
        self.assertEqual(preview("", 10), "")
        self.assertIsNotNone(preview(None))
        self.assertEqual(preview("abcdefghij", 10), "abcdefghij")
        self.assertEqual(preview("abcdefghijk", 10), "abcdefg...")
        self.assertLessEqual(len(preview("x" * 500, 54)), 54)

    def test_both_editors_share_the_same_geometry_logic(self):
        # As duas janelas so devem divergir no tamanho minimo.
        janela = FakeWindow(1920, 1080)
        self.assertEqual(
            safe_geometry(janela, "300x200+10+10"),
            clamp_geometry("300x200+10+10", 1920, 1080, 1120, 680),
        )
        self.assertEqual(
            glossary_safe_geometry(janela, "300x200+10+10"),
            clamp_geometry("300x200+10+10", 1920, 1080, 1040, 640),
        )


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

    def test_concurrent_windows_do_not_erase_each_others_settings(self):
        # Garantia R4: cada janela carrega seu proprio snapshot na abertura.
        # Se cada uma gravasse o snapshot inteiro, a ultima apagaria o que a
        # outra escreveu depois — inclusive rascunhos nao salvos.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "settings.json")
            save_settings({"editor": {"font_size": 12}}, path)

            # As duas janelas abrem e leem o disco.
            janela_traducoes = load_settings(path)
            janela_glossario = load_settings(path)

            # O editor de traducoes salva um rascunho.
            set_editor_draft(
                janela_traducoes, "/db.sqlite", "pt", 7, "meu rascunho", "original"
            )
            update_settings(
                lambda disk: set_editor_draft(
                    disk, "/db.sqlite", "pt", 7, "meu rascunho", "original"
                ),
                path,
            )

            # Depois o editor de glossario salva as SUAS preferencias, a partir
            # de um snapshot que nao conhece o rascunho.
            janela_glossario["glossary_editor"] = {"filter": "todos"}

            def apply(disk):
                disk.setdefault("glossary_editor", {}).update({"filter": "todos"})

            update_settings(apply, path)

            gravado = load_settings(path)
            self.assertEqual(gravado["glossary_editor"]["filter"], "todos")
            # O rascunho tem de sobreviver.
            draft = get_editor_draft(gravado, "/db.sqlite", "pt", 7, "original")
            self.assertIsNotNone(draft)
            self.assertEqual(draft["text"], "meu rascunho")
            # E a preferencia original tambem.
            self.assertEqual(gravado["editor"]["font_size"], 12)

    def test_settings_write_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = tmp_path / "settings.json"
            save_settings({"editor": {"font_size": 14}}, str(path))

            self.assertTrue(path.exists())
            self.assertEqual(list(tmp_path.glob("*.tmp")), [])
            self.assertEqual(load_settings(str(path))["editor"]["font_size"], 14)

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
    def setUp(self):
        """Silencia TODO o `messagebox` do worker, `showerror` inclusive.

        Cada teste ja silenciava o dialogo do caminho que exercitava, mas nenhum
        cobria o `showerror` — e `run_translation` tem um `except Exception` que
        cai justamente nele. Resultado: qualquer falha inesperada abria um
        dialogo modal de verdade (o `FakeRoot.after` executa na hora) e a suite
        **travava em vez de falhar**.

        Descoberto verificando uma mutacao do item 2.9: quebrado o cache, o teste
        "sem chamada de API" levantava `AssertionError`, o worker capturava, e a
        execucao parava para sempre esperando alguem clicar em OK.
        """
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

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

    def test_run_translation_reports_failed_comments_instead_of_silent_success(self):
        # Garantia T2: uma falha parcial nao pode ser apresentada como sucesso.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {White seizes the center} e5 {Black responds}\n",
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            dialogs = []

            original_translate_text = translation_worker.translate_text
            original_showinfo = translation_worker.messagebox.showinfo
            original_showwarning = translation_worker.messagebox.showwarning
            try:
                def flaky_translate(text, *_args, **_kwargs):
                    if "|||" in text:
                        # Desalinhamento (resposta com 1 parte para 2
                        # comentarios): e o que leva ao fallback individual.
                        #
                        # Antes este teste devolvia `None` aqui, que tambem caia
                        # no fallback. Com B3 nao cai mais: `None` significa que
                        # a API nao respondeu, e reprocessar comentario a
                        # comentario nesse caso era justamente o defeito. O que
                        # o teste verifica — T2, falha parcial nao vira sucesso
                        # limpo — nao mudou; mudou como se chega ao fallback.
                        return "As brancas tomam o centro"
                    if "White seizes" in text:
                        return "As brancas tomam o centro"
                    return None  # o segundo comentario falha

                translation_worker.translate_text = flaky_translate
                translation_worker.messagebox.showinfo = (
                    lambda title, msg, *a, **k: dialogs.append(("info", title, msg))
                )
                translation_worker.messagebox.showwarning = (
                    lambda title, msg, *a, **k: dialogs.append(("warning", title, msg))
                )

                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text
                translation_worker.messagebox.showinfo = original_showinfo
                translation_worker.messagebox.showwarning = original_showwarning

            # O usuario precisa ser avisado, nao receber um "Concluido" limpo.
            self.assertEqual(len(dialogs), 1)
            kind, title, message = dialogs[0]
            self.assertEqual(kind, "warning")
            self.assertIn("falha", title.lower())
            self.assertIn("Falharam: 1", message)

            # O log precisa registrar a falha e nomear o arquivo afetado.
            log = "\n".join(app.logs)
            self.assertIn("[FALHA]", log)
            self.assertIn("Comentarios que falharam: 1", log)
            self.assertIn("game.pgn", log)

            # Garantia T3: o comentario que falhou fica no idioma original.
            output_text = (tmp_path / "game-BR.pgn").read_text(encoding="utf-8")
            self.assertIn("{As brancas tomam o centro}", output_text)
            self.assertIn("{Black responds}", output_text)

    def test_run_translation_reports_clean_success_when_nothing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n1. e4 {White starts}\n',
                encoding="utf-8",
            )

            app = FakeApp(tmp_path / "cache.db")
            dialogs = []

            original_translate_text = translation_worker.translate_text
            original_showinfo = translation_worker.messagebox.showinfo
            original_showwarning = translation_worker.messagebox.showwarning
            try:
                translation_worker.translate_text = lambda text, *a, **k: "As brancas comecam"
                translation_worker.messagebox.showinfo = (
                    lambda title, msg, *a, **k: dialogs.append(("info", title, msg))
                )
                translation_worker.messagebox.showwarning = (
                    lambda title, msg, *a, **k: dialogs.append(("warning", title, msg))
                )

                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text
                translation_worker.messagebox.showinfo = original_showinfo
                translation_worker.messagebox.showwarning = original_showwarning

            self.assertEqual([d[0] for d in dialogs], ["info"])
            self.assertIn("Falharam: 0", dialogs[0][2])

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

    def test_run_translation_applies_automatic_rules_after_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {White wins the queen}\n",
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            original_translate_text = translation_worker.translate_text
            original_showinfo = translation_worker.messagebox.showinfo
            original_cleanup = translation_worker.load_cleanup_substitutions
            original_automatic = translation_worker.load_automatic_substitutions
            try:
                translation_worker.translate_text = lambda *_args, **_kwargs: "As brancas ganham a rainha"
                translation_worker.messagebox.showinfo = lambda *_args, **_kwargs: None
                translation_worker.load_cleanup_substitutions = lambda: []
                translation_worker.load_automatic_substitutions = lambda: [
                    ("rainha", "dama"),
                ]

                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text
                translation_worker.messagebox.showinfo = original_showinfo
                translation_worker.load_cleanup_substitutions = original_cleanup
                translation_worker.load_automatic_substitutions = original_automatic

            output = tmp_path / "game-BR.pgn"
            output_text = output.read_text(encoding="utf-8")
            self.assertIn("{As brancas ganham a dama}", output_text)

            conn = initialize_database(str(db_path))
            try:
                rows = conn.execute(
                    """
                    SELECT original_comment, translated_comment
                    FROM comments
                    """
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(
                rows,
                [("White wins the queen", "As brancas ganham a dama")],
            )


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
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )
            self.assertEqual(
                load_glossary_entry_details_from_db(str(glossary_db)),
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_SUGGESTION),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
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
                com_prioridade([
                    ("mate threat", "ameaca de mate", GLOSSARY_RULE_CLEANUP),
                    ("== EndSquare ==", "", GLOSSARY_RULE_CLEANUP),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                    ("queen", "dama", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

            export_glossary_csv(str(csv_path), path=str(glossary))
            self.assertIn(
                "original,replacement,type,priority",
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
            self.assertEqual(load_automatic_substitutions(str(glossary)), [])
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

    def test_automatic_rules_are_loaded_and_applied_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("file", "coluna"),
                    ("rainha", "dama", GLOSSARY_RULE_AUTOMATIC),
                    ("mate", "xeque-mate", GLOSSARY_RULE_AUTOMATIC),
                ],
                str(glossary),
                create_backup=False,
            )

            self.assertEqual(load_substitutions(str(glossary)), [("file", "coluna")])
            self.assertEqual(
                load_automatic_substitutions(str(glossary)),
                [("rainha", "dama"), ("mate", "xeque-mate")],
            )
            self.assertEqual(
                load_interactive_substitutions(str(glossary)),
                [
                    ("file", "coluna"),
                    ("rainha", "dama"),
                    ("mate", "xeque-mate"),
                ],
            )
            self.assertEqual(
                apply_automatic_substitutions(
                    "A rainha ameaca mate, mas rainhas ficam.",
                    load_automatic_substitutions(str(glossary)),
                ),
                "A dama ameaca xeque-mate, mas rainhas ficam.",
            )
            self.assertEqual(
                apply_automatic_substitutions(
                    "Cavaleiro CAVALEIRO cavaleiro.",
                    [("cavaleiro", "cavalo")],
                ),
                "Cavalo CAVALO cavalo.",
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
        # Garantia S3: as sugestoes vem da mais especifica para a mais generica,
        # que e a ordem em que serao aplicadas. Assim uma regra curta nao consome
        # o trecho que uma regra longa pretendia casar, e o corte por
        # max_suggestions descarta as genericas, nao as especificas.
        self.assertEqual(
            find_glossary_suggestions(text, substitutions),
            [
                (", as brancas joga", ", as brancas jogam"),
                ("brancas joga", "brancas jogam"),
                ("branca", "brancas"),
                ("for", "para"),
            ],
        )
        self.assertEqual(find_glossary_matches("Cavaleiro", "cavaleiro"), [(0, 9)])
        self.assertEqual(
            find_glossary_suggestions("Cavaleiro ativo", [("cavaleiro", "cavalo")]),
            [("cavaleiro", "cavalo")],
        )
        self.assertEqual(apply_substitution("forma for", "for", "para"), "forma para")
        self.assertEqual(apply_substitution("forma", "for", "para"), "forma")
        self.assertEqual(
            apply_all_substitutions("forma for branca", [("for", "para"), ("branca", "brancas")]),
            "forma para brancas",
        )

    def test_specific_rule_wins_over_generic_rule_regardless_of_file_order(self):
        # Garantia S3: a regra curta nao pode consumir o texto que a longa casaria.
        rules = [
            ("verificação", "xeque"),
            ("da verificação intermediária", "do xeque intermediário"),
        ]
        text = "Ele saiu da verificação intermediária com vantagem."

        self.assertEqual(
            apply_all_substitutions(text, rules),
            "Ele saiu do xeque intermediário com vantagem.",
        )
        # Inverter a ordem no arquivo nao pode mudar o resultado.
        self.assertEqual(
            apply_all_substitutions(text, list(reversed(rules))),
            "Ele saiu do xeque intermediário com vantagem.",
        )

        # Caso real do glossario: 'Cavaleiros' nao pode encobrir a regra completa.
        chess_rules = [
            ("Cavaleiros", "Cavalos"),
            ("Jogo dos Três Cavaleiros", "Partida dos Três Cavalos"),
        ]
        self.assertEqual(
            apply_all_substitutions("Jogo dos Três Cavaleiros é classico", chess_rules),
            "Partida dos Três Cavalos é classico",
        )

        # Quem precisar da ordem literal do arquivo continua podendo pedi-la.
        self.assertEqual(
            apply_all_substitutions(text, rules, order_by_specificity=False),
            "Ele saiu da xeque intermediária com vantagem.",
        )

    def test_replaced_text_is_frozen_against_contradictory_rules(self):
        # Caso real do glossario: duas regras que se desfazem uma a outra.
        rules = [
            ("Rei das brancas estão", "Rei das brancas está"),
            ("brancas está", "brancas estão"),
        ]
        # A regra especifica entrega o que declarou; a generica nao reverte.
        self.assertEqual(
            apply_all_substitutions("Rei das brancas estão", rules),
            "Rei das brancas está",
        )
        # E o resultado nao depende da ordem em que foram digitadas no arquivo.
        self.assertEqual(
            apply_all_substitutions("Rei das brancas estão", list(reversed(rules))),
            "Rei das brancas está",
        )
        # A regra generica continua valendo onde a especifica nao alcanca.
        self.assertEqual(
            apply_all_substitutions("As brancas está bem", rules),
            "As brancas estão bem",
        )
        # O encadeamento antigo continua disponivel para quem precisar.
        self.assertEqual(
            apply_all_substitutions(
                "Rei das brancas estão", rules, protect_replacements=False
            ),
            "Rei das brancas estão",
        )

    def test_ordering_cache_never_changes_the_result(self):
        """Item 2.10: a ordenacao virou memorizada — nao pode mudar nada.

        S3 depende inteiramente desta ordem. Um cache que devolva a lista errada,
        ou que se deixe corromper por quem mutar o resultado, quebra a garantia
        de forma dificil de perceber: as regras continuam sendo aplicadas, so que
        na ordem errada.
        """
        regras = [
            ("verificacao", "xeque"),
            ("da verificacao intermediaria", "do xeque intermediario"),
            ("torre", "roque"),
            ("rei", "rei"),
        ]
        outras = [("a", "b"), ("ccc", "d")]

        esperado = [
            ("da verificacao intermediaria", "do xeque intermediario"),
            ("verificacao", "xeque"),
            ("torre", "roque"),
            ("rei", "rei"),
        ]
        self.assertEqual(order_rules_by_specificity(regras), esperado)
        # Segunda chamada: agora vem do cache.
        self.assertEqual(order_rules_by_specificity(regras), esperado)
        # Uma lista diferente nao pode receber o resultado da anterior.
        self.assertEqual(
            order_rules_by_specificity(outras),
            [("ccc", "d"), ("a", "b")],
        )
        self.assertEqual(order_rules_by_specificity(regras), esperado)

        # Mutar o resultado nao pode contaminar a proxima chamada.
        devolvido = order_rules_by_specificity(regras)
        devolvido.append(("intruso", "x"))
        devolvido[0] = ("trocado", "y")
        self.assertEqual(order_rules_by_specificity(regras), esperado)

        # Uma lista com o MESMO conteudo, mas objeto diferente, e equivalente.
        self.assertEqual(order_rules_by_specificity(list(regras)), esperado)

        # E o conteudo e o que decide: mudar uma regra muda a ordem.
        # O padrao precisa ser mais longo que os 28 caracteres de
        # "da verificacao intermediaria" para assumir o primeiro lugar.
        mais_longa = ("uma regra com o padrao bem mais longo que os outros", "x")
        alteradas = list(regras)
        alteradas[2] = mais_longa
        self.assertGreater(len(mais_longa[0]), len("da verificacao intermediaria"))
        self.assertEqual(order_rules_by_specificity(alteradas)[0], mais_longa)

    def test_order_rules_by_specificity_is_stable_for_equal_lengths(self):
        rules = [("aa", "1"), ("bb", "2"), ("cccc", "3"), ("dd", "4")]
        self.assertEqual(
            order_rules_by_specificity(rules),
            [("cccc", "3"), ("aa", "1"), ("bb", "2"), ("dd", "4")],
        )

    def test_glossary_matches_never_overlap(self):
        # Garantia S1: nenhum caractere fora de um match pode desaparecer.
        for text, orig, new, expected in (
            ("de de de", "de de", "de", "de de"),
            ("com com com", "com com", "com", "com com"),
            ("em em em", "em em", "em", "em em"),
        ):
            matches = find_glossary_matches(text, orig)
            for (_, first_end), (second_start, _) in zip(matches, matches[1:]):
                self.assertLessEqual(first_end, second_start)
            self.assertEqual(apply_all_substitutions(text, [(orig, new)]), expected)

        # Duas ocorrencias realmente separadas continuam sendo substituidas.
        self.assertEqual(
            apply_all_substitutions("de de x de de", [("de de", "de")]),
            "de x de",
        )

    def test_glossary_matching_survives_characters_whose_lowercase_grows(self):
        # Garantia S2: len('İ'.lower()) == 2; os indices tem de ser do texto original.
        self.assertEqual(len("İ".lower()), 2)

        text = "İstanbul rook attack"
        matches = find_glossary_matches(text, "rook")
        self.assertEqual(len(matches), 1)
        start, end = matches[0]
        self.assertEqual(text[start:end], "rook")
        self.assertEqual(
            apply_all_substitutions(text, [("rook", "torre")]),
            "İstanbul torre attack",
        )

        # Regra que comeca com caractere nao-alfanumerico nao pode comer vizinhos.
        self.assertEqual(
            apply_all_substitutions("İ a -fileira, ok", [("-fileira", "-coluna")]),
            "İ a -coluna, ok",
        )

    def test_delete_by_pair_removes_the_chosen_entry_even_with_duplicates(self):
        # Garantia S6: excluir por indice quebra quando a lista exibida e
        # deduplicada e a exclusao opera sobre a lista completa do arquivo.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("a", "b"), ("a", "b"), ("king", "rei"), ("queen", "dama")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            def pares(deduplicate):
                return [
                    glossary_entry_pair(entry)
                    for entry in load_glossary_entry_details(
                        str(glossary), deduplicate=deduplicate, prefer_db=False
                    )
                ]

            # A duplicata faz as duas listas terem tamanhos diferentes: e a
            # condicao que provocava a exclusao errada.
            self.assertEqual(len(pares(False)), 4)
            self.assertEqual(len(pares(True)), 3)

            result = delete_glossary_entry_by_pair(
                "king", "rei", str(glossary), backup_dir=None
            )
            self.assertIsNotNone(result)
            self.assertEqual(result["removed"], ("king", "rei"))

            restante = pares(False)
            self.assertNotIn(("king", "rei"), restante)
            # Nada mais pode ter sumido junto.
            self.assertEqual(restante, [("a", "b"), ("a", "b"), ("queen", "dama")])

            # Par inexistente nao altera o arquivo e sinaliza com None.
            self.assertIsNone(
                delete_glossary_entry_by_pair(
                    "nao", "existe", str(glossary), backup_dir=None
                )
            )
            self.assertEqual(pares(False), restante)

    def test_entries_are_stored_without_edge_whitespace(self):
        # Um espaco no fim do padrao e consumido pelo casamento mas nao devolvido
        # pela substituicao, colando duas palavras no texto final.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary_db = tmp_path / "glossario.db"

            save_glossary_entries(
                [("rook", "torre")],
                str(glossary),
                create_backup=False,
                db_path=str(glossary_db),
            )

            add_glossary_entry(
                " a-coluna ", " coluna a ", str(glossary), backup_dir=None
            )

            pares = [
                glossary_entry_pair(entry)
                for entry in load_glossary_entry_details(
                    str(glossary), deduplicate=False, prefer_db=False
                )
            ]
            self.assertIn(("a-coluna", "coluna a"), pares)
            for orig, new in pares:
                self.assertEqual(orig, orig.strip())
                self.assertEqual(new, new.strip())

            # E o efeito pratico: a regra normalizada nao cola as palavras.
            self.assertEqual(
                apply_all_substitutions(
                    "na a-coluna aberta", [("a-coluna", "coluna a")]
                ),
                "na coluna a aberta",
            )
            # Comportamento antigo, para deixar o defeito explicito no teste.
            self.assertEqual(
                apply_all_substitutions(
                    "na a-coluna aberta", [(" a-coluna ", " coluna a")]
                ),
                "na coluna aaberta",
            )

    def test_validation_lookup_matches_full_scan(self):
        # O indice existe por desempenho; nao pode mudar o resultado.
        entries = [
            ("rook", "torre"),
            ("Rook", "Torre"),
            ("pawn", "peão"),
            ("rook", "torre de rei"),
            ("queen", "dama"),
        ]
        lookup = build_glossary_lookup(entries)

        casos = [
            ("rook", "torre"),          # duplicata exata
            ("rook", "outra coisa"),    # mesmo original, substituicao diferente
            ("queen", "dama"),          # duplicata
            ("bishop", "bispo"),        # inedito
            ("Rook", "Torre"),          # sensivel a caixa
            ("", "vazio"),              # original vazio
        ]
        for orig, new in casos:
            for current_index in (None, 0, 3):
                self.assertEqual(
                    validate_glossary_entry(
                        orig, new, entries, current_index=current_index
                    ),
                    validate_glossary_entry(
                        orig,
                        new,
                        current_index=current_index,
                        existing_lookup=lookup,
                    ),
                    f"divergiu em {orig!r}->{new!r} (current_index={current_index})",
                )

    def test_csv_import_analysis_detects_duplicates_within_the_same_file(self):
        # A deduplicacao interna passou a usar um set; o resultado tem de ser
        # o mesmo de antes, inclusive para linhas repetidas dentro do CSV.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre")],
                str(glossary),
                create_backup=False,
                db_path=str(tmp_path / "glossario.db"),
            )

            csv_path = tmp_path / "import.csv"
            csv_path.write_text(
                "original,replacement,type\n"
                "rook,torre,suggestion\n"          # ja existe -> duplicata
                "knight,cavalo,suggestion\n"       # nova
                "knight,cavalo,suggestion\n"       # repetida no proprio CSV
                "bishop,,suggestion\n"             # invalida
                "pawn,peão,suggestion\n",          # nova
                encoding="utf-8-sig",
            )

            stats = analyze_glossary_csv_import(str(glossary), str(csv_path))
            self.assertEqual(stats["total_rows"], 5)
            self.assertEqual(stats["inserted"], 2)
            self.assertEqual(stats["duplicates"], 2)
            self.assertEqual(stats["invalid"], 1)
            self.assertEqual(
                [(o, n) for o, n, _t, _p in stats["entries"]],
                [("knight", "cavalo"), ("pawn", "peão")],
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


class DatabaseToolsBackgroundTests(unittest.TestCase):
    """Item 2.11: backup, restauracao e CSV saem do callback do Tk.

    O `background_task` foi criado em 2.7 e ficou servindo so a aplicacao de
    regras automaticas. Estas quatro operacoes continuavam rodando dentro do
    proprio callback do botao: sem progresso, sem cancelamento e com a janela
    parada — o backup do banco real leva 0,4 s, mas a exportacao do CSV leva
    1,1 s e a importacao depende do tamanho do arquivo.

    O que estes testes fixam nao e o tempo: e que a operacao PASSA pela thread
    de trabalho e que desistir no meio nao deixa lixo para tras.
    """

    LINHAS = 1200

    def _semear(self, db_path, linhas=None):
        linhas = self.LINHAS if linhas is None else linhas
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        for indice in range(linhas):
            save_translation(cursor, f"orig {indice}", f"trad {indice}", "pt")
        conn.commit()
        conn.close()
        return linhas

    def _app(self, db_path):
        return types.SimpleNamespace(
            output_db=str(db_path), translation_cache={}, root=None
        )

    def _silencia_dialogos(self):
        vistos = []
        self.addCleanup(setattr, db_tools, "messagebox", db_tools.messagebox)
        db_tools.messagebox = types.SimpleNamespace(
            askyesno=lambda titulo, msg, **_kw: vistos.append(("askyesno", titulo)) or True,
            showinfo=lambda titulo, msg, **_kw: vistos.append(("info", titulo)),
            showerror=lambda titulo, msg, **_kw: vistos.append(("error", titulo)),
        )
        return vistos

    def _escolhe_arquivo(self, caminho):
        self.addCleanup(setattr, db_tools, "filedialog", db_tools.filedialog)
        db_tools.filedialog = types.SimpleNamespace(
            asksaveasfilename=lambda **_kw: str(caminho),
            askopenfilename=lambda **_kw: str(caminho),
        )

    # ------------------------------------------------ as quatro saem da UI

    def test_the_four_operations_go_through_the_worker_thread(self):
        """O item inteiro em um teste: nenhuma delas trabalha no callback.

        Devolver qualquer uma para dentro do callback do Tk nao quebra nada
        visivel — ela continua funcionando, so que travando a janela. Por isso a
        exigencia e explicita: cada uma tem de ter passado pelo
        `run_with_progress`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path, 20)
            csv_path = base / "saida.csv"
            self._silencia_dialogos()
            app = self._app(db_path)

            progresso = SynchronousProgress()
            progresso.install(self, db_tools)

            self._escolhe_arquivo(csv_path)
            db_tools.export_csv(app)
            db_tools.backup_database(app)
            db_tools.import_csv(app)                  # previa + aplicacao

            backup = next(iter((base / "backups").glob("*.db")))
            self._escolhe_arquivo(backup)
            db_tools.restore_database(app)

            self.assertEqual(
                progresso.titles(),
                [
                    "Exportar CSV",
                    "Backup do Banco de Dados",
                    "Importar CSV",
                    "Importar CSV",
                    "Restaurar Banco de Dados",
                ],
            )

    def test_restoring_does_not_offer_a_cancel_it_cannot_honor(self):
        """Interromper a copia deixaria o banco de trabalho pela metade.

        Oferecer o botao e ignora-lo seria pior do que nao oferecer: o usuario
        clicaria achando que parou, e a copia seguiria substituindo o banco.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path, 10)
            backup = create_database_backup(str(db_path), backup_dir=str(base / "b"))

            self._silencia_dialogos()
            self._escolhe_arquivo(backup)
            progresso = SynchronousProgress()
            progresso.install(self, db_tools)

            db_tools.restore_database(self._app(db_path))

            self.assertEqual([c["allow_cancel"] for c in progresso.chamadas], [False])

    # ------------------------------------------------ exportacao

    def test_exporting_reports_progress_and_writes_every_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            linhas = self._semear(db_path)
            destino = base / "saida.csv"

            # Bloco pequeno para haver mais de um: com o de producao (5.000) as
            # 1.200 linhas sairiam numa tacada e o teste nao veria a progressao.
            self.addCleanup(setattr, db_tools, "EXPORT_CHUNK", db_tools.EXPORT_CHUNK)
            db_tools.EXPORT_CHUNK = 500

            progresso = []
            escritas = export_translations_to_csv(
                str(db_path), str(destino), progress_callback=lambda f, t: progresso.append((f, t))
            )

            self.assertEqual(escritas, linhas)
            with open(destino, encoding="utf-8-sig", newline="") as f:
                gravadas = list(csv.reader(f))
            self.assertEqual(len(gravadas), linhas + 1, "faltou o cabecalho ou uma linha")
            self.assertEqual(gravadas[0], db_tools.EXPORT_CSV_HEADERS)

            self.assertTrue(progresso, "nenhum progresso reportado")
            self.assertEqual(progresso[0], (0, linhas), "o total nao foi anunciado no inicio")
            self.assertEqual(progresso[-1], (linhas, linhas))

    def test_canceling_the_export_leaves_no_half_written_file(self):
        """Um CSV cortado no meio abre, tem cabecalho e linhas validas.

        Deixa-lo em disco depois de um "Cancelar" seria oferecer um arquivo que
        mente sobre o que tem — e o usuario nao teria como saber.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path)
            destino = base / "saida.csv"

            with self.assertRaises(TaskCanceled):
                export_translations_to_csv(
                    str(db_path), str(destino), should_cancel=lambda: True
                )

            self.assertFalse(destino.exists(), "o CSV pela metade ficou em disco")

    # ------------------------------------------------ backup

    def test_backing_up_reports_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path)

            progresso = []
            caminho = create_database_backup(
                str(db_path),
                backup_dir=str(base / "backups"),
                progress_callback=lambda f, t: progresso.append((f, t)),
            )

            self.assertTrue(Path(caminho).exists())
            self.assertTrue(progresso, "a copia nao reportou progresso nenhum")
            feito, total = progresso[-1]
            self.assertEqual(feito, total, "a ultima medida nao fecha em 100%")

    def test_canceling_the_backup_removes_the_partial_copy(self):
        """Senao o proximo "Restaurar backup" ofereceria o arquivo incompleto."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path)
            backup_dir = base / "backups"

            with self.assertRaises(TaskCanceled):
                create_database_backup(
                    str(db_path), backup_dir=str(backup_dir), should_cancel=lambda: True
                )

            self.assertEqual(
                list(backup_dir.glob("*.db")), [], "sobrou um backup incompleto"
            )

    # ------------------------------------------------ restauracao

    def test_restoring_reports_progress_by_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path, 10)
            backup = create_database_backup(str(db_path), backup_dir=str(base / "b"))

            self._semear(db_path, 5)  # o banco muda depois da copia
            progresso = []
            resultado = restore_database_from_backup(
                str(db_path),
                backup,
                safety_backup_dir=str(base / "seguranca"),
                progress_callback=lambda f, t: progresso.append((f, t)),
            )

            self.assertTrue(Path(resultado["safety_backup_path"]).exists())
            self.assertEqual(progresso, [(0, 3), (1, 3), (2, 3), (3, 3)])

    # ------------------------------------------------ importacao

    def test_canceling_the_import_leaves_the_database_untouched(self):
        """Cancelar faz `rollback`: nada aplicado, nao metade aplicado."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            initialize_database(str(db_path)).close()
            csv_path = base / "entrada.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f)
                escritor.writerow(["original_comment", "translated_comment", "target_language"])
                for indice in range(600):
                    escritor.writerow([f"orig {indice}", f"trad {indice}", "pt"])

            # Desiste depois do primeiro bloco: com `True` desde o inicio, a
            # primeira checagem acontece na linha 200 e o teste nao provaria que
            # o que ja tinha sido gravado foi desfeito.
            chamadas = []

            def desiste():
                chamadas.append(1)
                return len(chamadas) > 1

            with self.assertRaises(TaskCanceled):
                import_translations_from_csv(
                    str(db_path),
                    str(csv_path),
                    create_backup=False,
                    should_cancel=desiste,
                )

            conn = initialize_database(str(db_path))
            total = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
            conn.close()
            self.assertEqual(total, 0, "o cancelamento deixou linhas gravadas")

    def test_importing_reports_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            initialize_database(str(db_path)).close()
            csv_path = base / "entrada.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f)
                escritor.writerow(["original_comment", "translated_comment", "target_language"])
                for indice in range(450):
                    escritor.writerow([f"orig {indice}", f"trad {indice}", "pt"])

            progresso = []
            stats = import_translations_from_csv(
                str(db_path),
                str(csv_path),
                create_backup=False,
                progress_callback=lambda f, t: progresso.append((f, t)),
            )

            self.assertEqual(stats["inserted"], 450)
            self.assertIn((450, 450), progresso, "o fim nao foi reportado")
            self.assertTrue(
                all(total == 450 for _feito, total in progresso),
                "o total mudou no meio do caminho",
            )

    # ------------------------------------------------ o cancelamento vira cancelamento

    def test_canceling_the_automatic_rules_is_not_reported_as_an_error(self):
        """`AutomaticRulesCanceled` chegava ao `run_with_progress` como falha.

        `database.py` nao pode conhecer o `background_task` — aquele modulo
        importa Tk, e manter o banco livre disso e o que permite testa-lo sem
        display. Sem a traducao no meio, quem clicava em "Cancelar" durante
        "Aplicar automaticas" recebia um dialogo de ERRO dizendo que a operacao
        falhou, e nao a confirmacao de que nada foi alterado.

        Passa pelo fluxo de verdade, e nao pelo `_cancelable` direto: o que
        pode se perder e a chamada, nao o helper.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "cache.db"
            self._semear(db_path, 10)

            vistos = self._silencia_dialogos()
            SynchronousProgress().install(self, db_tools)

            self.addCleanup(
                setattr, db_tools, "load_automatic_substitutions",
                db_tools.load_automatic_substitutions,
            )
            db_tools.load_automatic_substitutions = lambda: [("rainha", "dama")]

            self.addCleanup(
                setattr, db_tools, "analyze_database_automatic_rules",
                db_tools.analyze_database_automatic_rules,
            )

            def desistiu(*_a, **_kw):
                raise AutomaticRulesCanceled()

            db_tools.analyze_database_automatic_rules = desistiu

            recebidos = []
            db_tools.apply_automatic_rules_to_database(
                self._app(db_path), on_finish=recebidos.append
            )

            self.assertEqual(
                [tipo for tipo, _titulo in vistos],
                ["info"],
                f"o cancelamento nao virou aviso de cancelamento: {vistos}",
            )
            self.assertEqual(recebidos, [None])


def _stamp(moment):
    return moment.strftime("%Y%m%d-%H%M%S")


class BackupRetentionSelectionTests(unittest.TestCase):
    """Politica de retencao de `backups/` (roadmap 1.2). Funcoes puras."""

    NOW = datetime(2026, 7, 25, 12, 0, 0)

    def _glossary_names(self, count, start=None, step=timedelta(minutes=1)):
        """`count` backups do glossario, do mais novo para o mais velho."""
        start = start or self.NOW
        return [
            f"Substituicoes-{_stamp(start - step * index)}.txt"
            for index in range(count)
        ]

    def test_backup_timestamp_reads_the_name_not_the_mtime(self):
        self.assertEqual(
            backup_timestamp("Substituicoes-20260725-143012.txt"),
            datetime(2026, 7, 25, 14, 30, 12),
        )
        self.assertEqual(
            backup_timestamp("traducoes-backup-20260725-143012-2.db"),
            datetime(2026, 7, 25, 14, 30, 12),
        )
        self.assertEqual(
            backup_timestamp("/qualquer/pasta/Substituicoes-20260725-143012.txt"),
            datetime(2026, 7, 25, 14, 30, 12),
        )

    def test_backup_timestamp_rejects_names_without_a_valid_stamp(self):
        for name in [
            "Substituicoes.txt",
            "anotacoes.txt",
            "Substituicoes-2026072-143012.txt",
            # No formato certo, mas nao e uma data: mes 13, e hora 99.
            "Substituicoes-20261325-143012.txt",
            "Substituicoes-20260725-996012.txt",
        ]:
            with self.subTest(name=name):
                self.assertIsNone(backup_timestamp(name))

    def test_family_filter_separates_glossary_from_database(self):
        glossary = "Substituicoes-20260725-143012.txt"
        database = "traducoes-backup-20260725-143012.db"

        self.assertTrue(is_backup_of_family(glossary, "Substituicoes-", ".txt"))
        self.assertFalse(is_backup_of_family(glossary, "traducoes-backup-", ".db"))
        self.assertTrue(is_backup_of_family(database, "traducoes-backup-", ".db"))
        self.assertFalse(is_backup_of_family(database, "Substituicoes-", ".txt"))

    def test_family_filter_ignores_files_without_a_stamp(self):
        # Um arquivo que o usuario tenha deixado em backups/ nao pertence a
        # familia nenhuma, mesmo casando com prefixo e extensao.
        self.assertFalse(
            is_backup_of_family("Substituicoes-antigo.txt", "Substituicoes-", ".txt")
        )

    def test_count_rule_keeps_only_the_newest(self):
        names = self._glossary_names(10)
        doomed = select_backups_to_delete(
            names, keep_count=4, max_age_days=None, now=self.NOW
        )

        self.assertEqual(sorted(doomed), sorted(names[4:]))
        survivors = [name for name in names if name not in doomed]
        self.assertEqual(survivors, names[:4])

    def test_count_rule_is_a_no_op_below_the_limit(self):
        names = self._glossary_names(4)
        self.assertEqual(
            select_backups_to_delete(
                names, keep_count=30, max_age_days=None, now=self.NOW
            ),
            [],
        )

    def test_age_rule_deletes_the_old_ones(self):
        # 0d, 30d, 60d, 90d, 120d, 150d de idade. Corte em 45 dias.
        names = self._glossary_names(6, step=timedelta(days=30))
        doomed = select_backups_to_delete(
            names,
            keep_count=None,
            max_age_days=45,
            keep_minimum=0,
            now=self.NOW,
        )

        self.assertEqual(sorted(doomed), sorted(names[2:]))

    def test_age_rule_never_empties_the_folder(self):
        """Piso `keep_minimum`: uma pasta parada ha meses mantem os mais novos.

        Sem o piso, abrir o programa depois de um ano sem uso apagaria todos os
        backups existentes antes de criar o primeiro novo.
        """
        names = self._glossary_names(6, step=timedelta(days=30))
        doomed = select_backups_to_delete(
            names,
            keep_count=None,
            max_age_days=1,
            keep_minimum=3,
            now=self.NOW,
        )

        self.assertEqual(sorted(doomed), sorted(names[3:]))
        self.assertEqual([name for name in names if name not in doomed], names[:3])

    def test_protected_backup_survives_any_limit(self):
        names = self._glossary_names(5)
        newest = names[0]
        doomed = select_backups_to_delete(
            names,
            keep_count=1,
            max_age_days=1,
            keep_minimum=0,
            now=self.NOW + timedelta(days=400),
            protected=(newest,),
        )

        self.assertNotIn(newest, doomed)
        self.assertEqual(sorted(doomed), sorted(names[1:]))

    def test_protected_path_matches_by_basename(self):
        names = self._glossary_names(3)
        doomed = select_backups_to_delete(
            names,
            keep_count=1,
            max_age_days=None,
            now=self.NOW,
            protected=(f"/outra/pasta/{names[2]}",),
        )

        self.assertEqual(doomed, [names[1]])

    def test_undated_files_are_never_selected(self):
        names = self._glossary_names(3) + ["anotacoes.txt", "Substituicoes.txt"]
        doomed = select_backups_to_delete(
            names, keep_count=1, max_age_days=None, now=self.NOW
        )

        self.assertNotIn("anotacoes.txt", doomed)
        self.assertNotIn("Substituicoes.txt", doomed)

    def test_same_second_backups_are_ordered_by_the_uniqueness_suffix(self):
        """`_unique_path` desempata com "-1", "-2", na ordem de criacao.

        Comparar os nomes como texto inverteria os tres: "." e maior que "-",
        entao o arquivo SEM sufixo (o primeiro criado, o mais antigo) passaria
        por mais novo e sobreviveria no lugar do mais recente.
        """
        stamp = _stamp(self.NOW)
        oldest = f"Substituicoes-{stamp}.txt"
        middle = f"Substituicoes-{stamp}-1.txt"
        newest = f"Substituicoes-{stamp}-2.txt"

        self.assertEqual(uniqueness_suffix(oldest), 0)
        self.assertEqual(uniqueness_suffix(newest), 2)

        doomed = select_backups_to_delete(
            [oldest, middle, newest], keep_count=1, max_age_days=None, now=self.NOW
        )

        self.assertEqual(sorted(doomed), sorted([oldest, middle]))


class BackupRetentionDiskTests(unittest.TestCase):
    """`prune_backups` e a integracao com quem cria os backups."""

    NOW = datetime(2026, 7, 25, 12, 0, 0)

    def _seed(self, directory, name, content="x"):
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_prune_removes_only_the_requested_family(self):
        """O bug que a separacao por familia evita.

        `backups/` guarda as copias do glossario e do banco juntas. Sem o
        filtro, salvar o glossario 30 vezes levaria todos os backups do banco
        junto — perda de dados numa operacao que so mexia em texto.
        """
        with tempfile.TemporaryDirectory() as tmp:
            glossary = [
                self._seed(
                    tmp,
                    f"Substituicoes-{_stamp(self.NOW - timedelta(minutes=i))}.txt",
                )
                for i in range(5)
            ]
            database = [
                self._seed(
                    tmp,
                    f"traducoes-backup-{_stamp(self.NOW - timedelta(minutes=i))}.db",
                )
                for i in range(5)
            ]
            manual = self._seed(tmp, "leia-me.txt")

            removed = prune_glossary_backups(
                tmp, "Substituicoes", keep_count=2, max_age_days=None, now=self.NOW
            )

            self.assertEqual(len(removed), 3)
            self.assertTrue(all(path.exists() for path in database))
            self.assertTrue(manual.exists())
            self.assertTrue(all(path.exists() for path in glossary[:2]))
            self.assertFalse(any(path.exists() for path in glossary[2:]))

    def test_prune_tolerates_a_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "backups")
            self.assertEqual(prune_backups(missing, "Substituicoes-", ".txt"), [])

    def test_prune_ignores_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / f"Substituicoes-{_stamp(self.NOW)}.txt"
            nested.mkdir()

            removed = prune_backups(
                tmp, "Substituicoes-", ".txt", keep_count=1, max_age_days=None
            )

            self.assertEqual(removed, [])
            self.assertTrue(nested.exists())

    def test_create_glossary_backup_applies_retention_and_keeps_the_new_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', 'b')]\n", encoding="utf-8")
            backup_dir = tmp_path / "backups"
            backup_dir.mkdir()

            # Datas recentes, para isolar a regra de quantidade da de idade.
            recent = datetime.now()
            seeded = [
                self._seed(
                    backup_dir,
                    f"Substituicoes-{_stamp(recent - timedelta(minutes=i + 1))}.txt",
                )
                for i in range(35)
            ]

            created = Path(
                create_glossary_backup(str(glossary), backup_dir=str(backup_dir))
            )

            survivors = sorted(backup_dir.glob("Substituicoes-*.txt"))
            self.assertEqual(len(survivors), GLOSSARY_BACKUP_KEEP_COUNT)
            self.assertTrue(created.exists())
            # Ficaram o novo e os 29 mais recentes; sairam os 6 mais velhos.
            self.assertTrue(all(path.exists() for path in seeded[:29]))
            self.assertFalse(any(path.exists() for path in seeded[29:]))

    def test_create_glossary_backup_can_skip_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', 'b')]\n", encoding="utf-8")
            backup_dir = tmp_path / "backups"
            backup_dir.mkdir()
            old = self._seed(backup_dir, "Substituicoes-20200101-000000.txt")

            create_glossary_backup(
                str(glossary), backup_dir=str(backup_dir), prune=False
            )

            self.assertTrue(old.exists())

    def test_restore_does_not_prune_the_backup_being_restored(self):
        """A limpeza roda entre o backup de seguranca e a leitura da origem.

        Sem proteger o arquivo escolhido, restaurar um backup antigo poderia
        apaga-lo no exato instante anterior a le-lo.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "Substituicoes.txt"
            glossary.write_text(
                "substituicoes = [('current', 'atual')]\n", encoding="utf-8"
            )
            backup_dir = tmp_path / "backups"
            backup_dir.mkdir()

            chosen = backup_dir / "Substituicoes-20200101-000000.txt"
            chosen.write_text(
                "substituicoes = [('backup', 'copia')]\n", encoding="utf-8"
            )

            result = restore_glossary_from_backup(
                str(glossary),
                str(chosen),
                safety_backup_dir=str(backup_dir),
                timestamp="20260101-120000",
            )

            self.assertTrue(chosen.exists())
            self.assertTrue(Path(result["safety_backup_path"]).exists())
            self.assertEqual(load_glossary_entries(str(glossary)), [("backup", "copia")])

    def test_database_backup_retention_does_not_touch_glossary_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "traducoes.db"
            conn = initialize_database(str(db_path))
            conn.close()
            backup_dir = tmp_path / "backups"
            backup_dir.mkdir()

            recent = datetime.now()
            glossary_backups = [
                self._seed(
                    backup_dir,
                    f"Substituicoes-{_stamp(recent - timedelta(minutes=i + 1))}.txt",
                )
                for i in range(5)
            ]
            seeded = [
                self._seed(
                    backup_dir,
                    f"traducoes-backup-{_stamp(recent - timedelta(minutes=i + 1))}.db",
                )
                for i in range(15)
            ]

            create_database_backup(str(db_path), backup_dir=str(backup_dir))

            self.assertEqual(
                len(list(backup_dir.glob("traducoes-backup-*.db"))),
                DATABASE_BACKUP_KEEP_COUNT,
            )
            self.assertTrue(all(path.exists() for path in glossary_backups))
            self.assertTrue(all(path.exists() for path in seeded[:9]))


class StartupCleanupTests(unittest.TestCase):
    """Item 1.4: a retencao precisa alcancar o que ja esta no disco.

    `prune_glossary_backups` so era chamada de dentro de `create_glossary_backup`
    — isto e, como efeito de criar um backup novo. Enquanto ninguem salvasse o
    glossario, nada era avaliado: dois dias depois de a politica existir, a pasta
    do projeto ainda tinha 663 arquivos e 228 MB.
    """

    def _criar(self, pasta, nome, dias_atras=0):
        carimbo = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y%m%d-%H%M%S")
        # Carimbos distintos por arquivo, para a ordenacao ser deterministica.
        caminho = pasta / nome.format(carimbo=carimbo)
        caminho.write_text("x", encoding="utf-8")
        return caminho

    def test_startup_cleanup_reaches_files_nobody_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            backups = base / "backups"
            logs = base / "logs"
            backups.mkdir()
            logs.mkdir()

            # Mais backups de glossario que o limite, todos ja existentes: e o
            # cenario que a chamada antiga nunca alcancava.
            for dia in range(GLOSSARY_BACKUP_KEEP_COUNT + 12):
                self._criar(backups, "Substituicoes-{carimbo}.txt", dias_atras=dia)
            for dia in range(DATABASE_BACKUP_KEEP_COUNT + 5):
                self._criar(backups, "traducoes-backup-{carimbo}.db", dias_atras=dia)
            for dia in range(6):
                self._criar(logs, "traducao-{carimbo}.log", dias_atras=dia)

            # Arquivos que o usuario colocou ali: nao tem carimbo, nao saem.
            (backups / "anotacoes.txt").write_text("meu", encoding="utf-8")
            (logs / "importante.log").write_text("meu", encoding="utf-8")
            # E o formato ANTIGO de nome de log, que tambem nao deve ser tocado.
            antigo = logs / "traducao_20250101_120000.log"
            antigo.write_text("antigo", encoding="utf-8")

            removidos = app_actions.prune_generated_files(str(base))

            self.assertEqual(len(removidos["glossario"]), 12)
            self.assertEqual(len(removidos["banco"]), 5)
            self.assertEqual(removidos["logs"], [], "6 logs estao abaixo do limite")

            restantes = {p.name for p in backups.iterdir()}
            self.assertIn("anotacoes.txt", restantes)
            self.assertEqual(
                sum(1 for n in restantes if n.startswith("Substituicoes-")),
                GLOSSARY_BACKUP_KEEP_COUNT,
            )
            self.assertEqual(
                sum(1 for n in restantes if n.startswith("traducoes-backup-")),
                DATABASE_BACKUP_KEEP_COUNT,
            )

            logs_restantes = {p.name for p in logs.iterdir()}
            self.assertIn("importante.log", logs_restantes)
            self.assertIn(
                antigo.name,
                logs_restantes,
                "log no formato antigo nao casa com o padrao e nao pode ser removido",
            )

    def test_logs_above_the_limit_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            logs = base / "logs"
            logs.mkdir()
            (base / "backups").mkdir()

            for dia in range(LOG_KEEP_COUNT + 7):
                self._criar(logs, "traducao-{carimbo}.log", dias_atras=dia)

            removidos = app_actions.prune_generated_files(str(base))

            self.assertEqual(len(removidos["logs"]), 7)
            self.assertEqual(len(list(logs.iterdir())), LOG_KEEP_COUNT)

    def test_missing_folders_are_not_an_error(self):
        """Primeira execucao: nem `backups/` nem `logs/` existem ainda."""
        with tempfile.TemporaryDirectory() as tmp:
            removidos = app_actions.prune_generated_files(tmp)
        self.assertEqual(removidos, {"glossario": [], "banco": [], "logs": []})

    def test_the_new_log_name_matches_the_retention_pattern(self):
        """O nome gerado por `start_translation` precisa casar com a politica.

        Se o formato do nome e o do `_TIMESTAMP_RE` divergirem, a retencao de
        logs vira silenciosamente um no-op — o modo de falha mais chato
        possivel, porque tudo continua "funcionando".
        """
        nome = f"traducao-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        self.assertTrue(is_backup_of_family(nome, "traducao-", ".log"))
        self.assertIsNotNone(backup_timestamp(nome))

        antigo = f"traducao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.assertFalse(
            is_backup_of_family(antigo, "traducao-", ".log"),
            "o formato antigo precisa continuar fora do alcance da limpeza",
        )


class GlossaryErrorChannelTests(unittest.TestCase):
    """Garantia S5: falha de carga do glossario chega ate a interface."""

    def setUp(self):
        self.reported = []
        self.previous = set_glossary_error_handler(self.reported.append)
        self.addCleanup(set_glossary_error_handler, self.previous)
        self.addCleanup(clear_glossary_error)
        clear_glossary_error()

    def test_malformed_file_reports_instead_of_failing_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")

            entries = call_quietly(load_substitutions, str(glossary))

            self.assertEqual(entries, [])
            self.assertEqual(len(self.reported), 1)
            self.assertIn("Substituicoes.txt", self.reported[0])
            self.assertIn("NÃO serão aplicadas", self.reported[0])
            self.assertEqual(last_glossary_error(), self.reported[0])

    def test_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "Substituicoes.txt")

            self.assertEqual(call_quietly(load_substitutions, missing), [])
            self.assertEqual(len(self.reported), 1)
            self.assertIn("não encontrado", self.reported[0].lower())

    def test_successful_load_clears_the_previous_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")
            call_quietly(load_substitutions, str(glossary))
            self.assertIsNotNone(last_glossary_error())

            glossary.write_text("substituicoes = [('a', 'b')]\n", encoding="utf-8")
            self.assertEqual(
                call_quietly(load_substitutions, str(glossary)), [("a", "b")]
            )
            self.assertIsNone(last_glossary_error())

    def test_a_broken_handler_never_escapes(self):
        def explode(_message):
            raise RuntimeError("handler quebrado")

        set_glossary_error_handler(explode)
        # Nao pode levantar: reportar um erro nao pode virar um erro pior.
        call_quietly(report_glossary_error, "falha de teste")
        self.assertEqual(last_glossary_error(), "falha de teste")

    def test_without_a_handler_the_message_is_still_recorded(self):
        set_glossary_error_handler(None)
        call_quietly(report_glossary_error, "sem interface")
        self.assertEqual(last_glossary_error(), "sem interface")


class GlossaryFailureUiTests(unittest.TestCase):
    """O handler que a janela principal registra (`app_actions`)."""

    def setUp(self):
        self.app = FakeApp(":memory:")
        shown = []
        self.shown = shown

        class FakeMessagebox:
            @staticmethod
            def showerror(title, message, **kwargs):
                shown.append((title, message))

        previous = app_actions.messagebox
        app_actions.messagebox = FakeMessagebox
        self.addCleanup(setattr, app_actions, "messagebox", previous)

    def test_failure_reaches_both_the_log_and_a_dialog(self):
        app_actions.report_glossary_failure(self.app, "arquivo quebrado")

        self.assertTrue(any("arquivo quebrado" in line for line in self.app.logs))
        self.assertEqual(len(self.shown), 1)
        self.assertIn("arquivo quebrado", self.shown[0][1])

    def test_the_same_failure_opens_only_one_dialog(self):
        """A carga se repete a cada recarga; um modal por vez travaria o uso."""
        for _ in range(5):
            app_actions.report_glossary_failure(self.app, "arquivo quebrado")

        self.assertEqual(len(self.shown), 1)
        self.assertEqual(
            len([line for line in self.app.logs if "arquivo quebrado" in line]), 5
        )

    def test_a_different_failure_opens_a_new_dialog(self):
        app_actions.report_glossary_failure(self.app, "primeira falha")
        app_actions.report_glossary_failure(self.app, "segunda falha")

        self.assertEqual(len(self.shown), 2)

    def test_startup_load_degrades_instead_of_killing_the_window(self):
        """Sem isso, um `Substituicoes.txt` quebrado impedia o programa de abrir."""

        def explode():
            raise ValueError("arquivo invalido")

        previous = app_actions.load_interactive_substitutions
        app_actions.load_interactive_substitutions = explode
        self.addCleanup(
            setattr, app_actions, "load_interactive_substitutions", previous
        )
        previous_handler = set_glossary_error_handler(
            lambda message: app_actions.report_glossary_failure(self.app, message)
        )
        self.addCleanup(set_glossary_error_handler, previous_handler)

        entries = call_quietly(app_actions.load_interactive_glossary, self.app)

        self.assertEqual(entries, [])
        self.assertEqual(len(self.shown), 1)
        self.assertIn("arquivo invalido", self.shown[0][1])


class GlossaryEntryLocationTests(unittest.TestCase):
    """Roadmap 3.4 / garantia S6: operar pela entrada, nao pela posicao."""

    ENTRIES = [
        ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
        ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
        ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
    ]

    def _write(self, directory, entries):
        path = Path(directory) / "Substituicoes.txt"
        save_glossary_entries(entries, str(path), create_backup=False, sync_db=False)
        return path

    def test_finds_the_entry_regardless_of_position(self):
        self.assertEqual(
            find_glossary_entry_index(self.ENTRIES, ("queen", "dama", "suggestion")),
            1,
        )

    def test_missing_entry_returns_none(self):
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("bishop", "bispo", "suggestion"))
        )

    def test_type_participates_in_the_match(self):
        # Mesmo par, tipo diferente: nao e a mesma entrada.
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("pawn", "peao", "suggestion"))
        )
        self.assertEqual(
            find_glossary_entry_index(
                self.ENTRIES, ("pawn", "peao", "suggestion"), match_type=False
            ),
            2,
        )

    def test_it_finds_what_the_write_normalized(self):
        """A gravacao tira os espacos das pontas; a busca tem de saber disso.

        Apareceu ao cobrir `save_as_new` do editor de glossario: com
        `"  bishop  "` no formulario, a entrada ia para o arquivo como
        `"bishop"` e `locate_saved_entry` nao a reencontrava — a entrada recem
        gravada ficava sem selecao, sem erro nenhum. A docstring de
        `locate_saved_entry` ja afirmava que os dois lados eram normalizados; e
        que nao eram.
        """
        self.assertEqual(
            find_glossary_entry_index(
                self.ENTRIES, ("  queen  ", "  dama  ", "suggestion")
            ),
            1,
        )
        # Do outro lado tambem: uma entrada nao normalizada na lista.
        self.assertEqual(
            find_glossary_entry_index(
                [("  rook  ", "torre ", GLOSSARY_RULE_SUGGESTION)],
                ("rook", "torre", "suggestion"),
            ),
            0,
        )
        # E normalizar nao pode fazer o par casar com quem ele nao e.
        self.assertIsNone(
            find_glossary_entry_index(self.ENTRIES, ("qu een", "dama", "suggestion"))
        )

    def test_hint_decides_between_exact_duplicates(self):
        """Com duplicatas identicas, vale a que estava na tela."""
        entries = [
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
            ("x", "y", GLOSSARY_RULE_SUGGESTION),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        alvo = ("a", "b", GLOSSARY_RULE_SUGGESTION)

        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=2), 2)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=0), 0)
        # Palpite invalido ou apontando para outra coisa: cai na busca.
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=1), 0)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint=99), 0)
        self.assertEqual(find_glossary_entry_index(entries, alvo, index_hint="nao"), 0)

    def test_update_by_entry_survives_an_external_insertion(self):
        """O bug do item 3.4, reproduzido.

        A janela guarda a posicao de "queen" (1) no carregamento. O outro
        editor insere uma regra no inicio do arquivo. Salvar por posicao
        gravaria por cima de "queen" — que agora esta em 2 — destruindo a
        entrada vizinha sem aviso.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            posicao_no_carregamento = 1

            # Alteracao externa: uma entrada nova no inicio do arquivo.
            deslocado = [("bishop", "bispo", GLOSSARY_RULE_SUGGESTION)] + list(
                self.ENTRIES
            )
            save_glossary_entries(
                deslocado, str(path), create_backup=False, sync_db=False
            )

            result = update_glossary_entry_by_entry(
                ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
                "queen",
                "rainha",
                path=str(path),
                index_hint=posicao_no_carregamento,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertIsNotNone(result)
            self.assertEqual(result["index"], 2)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade([
                    ("bishop", "bispo", GLOSSARY_RULE_SUGGESTION),
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("queen", "rainha", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_positional_update_is_what_used_to_corrupt_the_neighbour(self):
        """Contraprova: a funcao antiga, no mesmo cenario, grava na errada."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            deslocado = [("bishop", "bispo", GLOSSARY_RULE_SUGGESTION)] + list(
                self.ENTRIES
            )
            save_glossary_entries(
                deslocado, str(path), create_backup=False, sync_db=False
            )

            update_glossary_entry(
                1,
                "queen",
                "rainha",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            entradas = load_glossary_entry_details(str(path), deduplicate=False)
            # "rook" foi destruida e "queen" continua intacta: a entrada errada.
            self.assertEqual(entradas[1], ("queen", "rainha", GLOSSARY_RULE_SUGGESTION, 0))
            self.assertIn(("queen", "dama", GLOSSARY_RULE_SUGGESTION, 0), entradas)
            self.assertNotIn(("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0), entradas)

    def test_update_by_entry_refuses_when_the_entry_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)
            sem_queen = [e for e in self.ENTRIES if e[0] != "queen"]
            save_glossary_entries(
                sem_queen, str(path), create_backup=False, sync_db=False
            )

            result = update_glossary_entry_by_entry(
                ("queen", "dama", GLOSSARY_RULE_SUGGESTION),
                "queen",
                "rainha",
                path=str(path),
                index_hint=1,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertIsNone(result)
            # Nada foi gravado: o arquivo continua exatamente como estava.
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(sem_queen),
            )

    def test_update_by_entry_normalizes_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            result = update_glossary_entry_by_entry(
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                "  rook  ",
                "  torre alta  ",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(result["index"], 0)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False)[0],
                ("rook", "torre alta", GLOSSARY_RULE_SUGGESTION, 0),
            )

    def test_update_by_entry_keeps_the_type_when_none_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            update_glossary_entry_by_entry(
                ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                "pawn",
                "peao livre",
                path=str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False)[2],
                ("pawn", "peao livre", GLOSSARY_RULE_AUTOMATIC, 0),
            )

    def test_delete_by_pair_can_target_the_type_and_the_duplicate(self):
        entries = [
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
            ("a", "b", GLOSSARY_RULE_AUTOMATIC),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, entries)

            removed = delete_glossary_entry_by_pair(
                "a",
                "b",
                path=str(path),
                rule_type=GLOSSARY_RULE_SUGGESTION,
                index_hint=2,
                backup_dir=str(Path(tmp) / "backups"),
            )

            self.assertEqual(removed["index"], 2)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(entries[:2]),
            )

    def test_delete_by_pair_without_a_type_still_matches_only_the_pair(self):
        """Comportamento antigo preservado para quem so conhece o par."""
        entries = [
            ("x", "y", GLOSSARY_RULE_AUTOMATIC),
            ("a", "b", GLOSSARY_RULE_SUGGESTION),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, entries)

            removed = delete_glossary_entry_by_pair(
                "x", "y", path=str(path), backup_dir=str(Path(tmp) / "backups")
            )

            self.assertEqual(removed["index"], 0)
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(entries[1:]),
            )

    def test_delete_by_pair_returns_none_for_a_missing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, self.ENTRIES)

            self.assertIsNone(
                delete_glossary_entry_by_pair(
                    "bishop",
                    "bispo",
                    path=str(path),
                    backup_dir=str(Path(tmp) / "backups"),
                )
            )
            self.assertEqual(
                load_glossary_entry_details(str(path), deduplicate=False),
                com_prioridade(self.ENTRIES),
            )


class GlossaryPriorityTests(unittest.TestCase):
    """Item 1.5 parte 2 / garantia S10: a prioridade decide antes do comprimento.

    A queixa do item era que a especificidade e derivada do texto: para adiantar
    uma regra era preciso alongar o padrao — mudar o que ela casa para mudar
    quando ela roda. Com a prioridade a intencao e declarada.
    """

    def test_priority_beats_length(self):
        curta = ("torre", "roque", 5)
        longa = ("torre da dama", "torre longa")

        ordem = order_rules_by_specificity([longa, curta])

        self.assertEqual(ordem[0], curta, "o comprimento venceu a prioridade")

    def test_without_priority_nothing_changes(self):
        """Prioridade zero e o caso de praticamente todas as regras."""
        curta = ("torre", "roque")
        longa = ("torre da dama", "torre longa")

        self.assertEqual(order_rules_by_specificity([curta, longa]), [longa, curta])

    def test_a_negative_priority_pushes_the_rule_back(self):
        adiada = ("torre da dama", "torre longa", -1)
        normal = ("torre", "roque")

        self.assertEqual(order_rules_by_specificity([adiada, normal]), [normal, adiada])

    def test_equal_priority_falls_back_to_length_then_file_order(self):
        regras = [
            ("bispo", "alfil", 2),
            ("bispo de casas claras", "alfil claro", 2),
            ("dama", "rainha", 2),
        ]

        ordem = order_rules_by_specificity(regras)

        self.assertEqual(ordem[0], regras[1], "o comprimento nao desempatou")
        self.assertEqual(ordem[1:], [regras[0], regras[2]], "a ordem do arquivo nao desempatou")

    def test_the_ordering_cache_notices_a_change_of_priority(self):
        """Duas listas com os mesmos pares e prioridades diferentes.

        A chave do cache era so os pares. Sem a prioridade nela, a segunda lista
        receberia a ordem da primeira: as regras continuariam sendo aplicadas,
        so que na ordem errada — sem erro nenhum, que e o pior modo de falhar.
        """
        sem = [("torre", "roque"), ("torre da dama", "torre longa")]
        com = [("torre", "roque", 5), ("torre da dama", "torre longa")]

        primeira = order_rules_by_specificity(sem)
        segunda = order_rules_by_specificity(com)

        self.assertEqual(primeira[0], sem[1])
        self.assertEqual(segunda[0], com[0], "o cache devolveu a ordem da outra lista")

    def test_the_priority_changes_what_the_text_receives(self):
        """A prova de que a ordem importa: o texto sai diferente."""
        sem = [("torre", "roque"), ("torre da dama", "torre longa")]
        com = [("torre", "roque", 5), ("torre da dama", "torre longa")]

        self.assertEqual(apply_all_substitutions("a torre da dama", sem), "a torre longa")
        self.assertEqual(apply_all_substitutions("a torre da dama", com), "a roque da dama")

    # ------------------------------------------------ o valor em si

    def test_anything_that_is_not_an_integer_becomes_the_default(self):
        """O arquivo e o CSV sao editaveis a mao e sobrevivem a versoes.

        Uma prioridade escrita como `"alta"` nao pode virar excecao no meio da
        carga do glossario — isso desligaria as 7 mil regras por causa de uma.
        """
        for valor in (None, "", "alta", "1.5", [], {}, True, False):
            with self.subTest(valor=valor):
                self.assertEqual(normalize_glossary_priority(valor), 0)

        self.assertEqual(normalize_glossary_priority("3"), 3)
        self.assertEqual(normalize_glossary_priority(" -2 "), -2)
        self.assertEqual(normalize_glossary_priority(7), 7)

    def test_a_plain_pair_still_has_a_priority(self):
        self.assertEqual(rule_priority(("a", "b")), 0)
        self.assertEqual(rule_priority(("a", "b", 4)), 4)

    # ------------------------------------------------ persistencia

    def test_the_file_only_writes_the_field_when_there_is_one(self):
        """7 mil linhas nao podem ganhar `, 0` por causa de quatro decisoes."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC, 0),
                    ("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3),
                ],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            texto = path.read_text(encoding="utf-8")
            self.assertIn("('rook', 'torre'),", texto)
            self.assertIn("('pawn', 'peao', 'automatic'),", texto)
            self.assertIn("('queen', 'dama', 'suggestion', 3),", texto)

    def test_a_file_from_before_this_version_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            path.write_text(
                "substituicoes = [\n"
                "    ('rook', 'torre'),\n"
                "    ('pawn', 'peao', 'automatic'),\n"
                "]\n",
                encoding="utf-8",
            )

            entradas = load_glossary_entry_details(str(path), prefer_db=False)

            self.assertEqual(
                entradas,
                com_prioridade([
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_the_priority_survives_the_round_trip_through_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            do_banco = load_glossary_entry_details_from_db(str(db_path))
            self.assertEqual(do_banco, [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)])

    def test_a_database_from_the_previous_schema_is_rebuilt(self):
        """O `ALTER TABLE` sozinho seria uma armadilha.

        A coluna nova entra com o padrao para todas as regras, e o `mtime` do
        arquivo nao mudou para acusar: o banco continuaria valendo como cache e
        as prioridades do arquivo seriam lidas como zero.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            # Um banco gravado pela versao anterior: sem a marca de esquema.
            conn = initialize_glossary_database(str(db_path))
            conn.execute("DELETE FROM glossary_metadata WHERE key = 'schema_version'")
            conn.execute("UPDATE glossary_entries SET priority = 0")
            conn.commit()
            conn.close()

            entradas = load_glossary_entry_details(str(path), db_path=str(db_path))

            self.assertEqual(
                glossary_entry_priority(entradas[0]), 3, "leu a prioridade do cache velho"
            )

    def _clonar(self, origem, destino):
        """O que um `git clone` faz com os dois arquivos, e so isso.

        Copia o conteudo para outra pasta e da ao `Substituicoes.txt` uma data
        nova — o git nao guarda `mtime`, entao o arquivo baixado tem sempre a
        hora do checkout, e nunca a de quem o gravou.
        """
        destino.mkdir(parents=True, exist_ok=True)
        for nome in ("Substituicoes.txt", "glossario.db"):
            (destino / nome).write_bytes((origem / nome).read_bytes())
        outra_data = os.path.getmtime(origem / "Substituicoes.txt") + 86400
        os.utime(destino / "Substituicoes.txt", (outra_data, outra_data))

    def test_the_cached_index_survives_a_clone(self):
        """A razao de versionar o `glossario.db` (ROADMAP 3.7).

        As marcas antigas nao sobreviviam ao clone: o `source_path` era absoluto,
        entao mudar de pasta ja bastava para divergir, e o `source_mtime` era a
        data do arquivo, que o checkout reescreve. As duas acusavam diferenca
        onde nao havia, e o cache versionado era descartado e reconstruido em
        toda maquina — o oposto do que versiona-lo pretende.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "original"
            original.mkdir()
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(original / "Substituicoes.txt"),
                create_backup=False,
                db_path=str(original / "glossario.db"),
            )

            clone = base / "outra-pasta" / "projeto"
            self._clonar(original, clone)

            self.assertFalse(
                glossario._glossary_database_needs_sync(
                    str(clone / "Substituicoes.txt"), str(clone / "glossario.db")
                ),
                "o cache clonado foi descartado: as marcas nao viajaram",
            )

            # E o conteudo continua certo, com a prioridade que so o cache valido
            # entrega sem reconstruir.
            entradas = load_glossary_entry_details(
                str(clone / "Substituicoes.txt"), db_path=str(clone / "glossario.db")
            )
            self.assertEqual(glossary_entry_priority(entradas[0]), 3)

    def test_a_changed_glossary_still_invalidates_the_cache(self):
        """A outra metade: a marca nova nao pode ser frouxa.

        Trocar o `mtime` pelo hash so vale se o hash ainda acusar o que o `mtime`
        acusava. Sem esta, "nunca reconstruir" passaria no teste de cima.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            self.assertFalse(
                glossario._glossary_database_needs_sync(str(path), str(db_path))
            )

            path.write_text(
                "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
            )

            self.assertTrue(
                glossario._glossary_database_needs_sync(str(path), str(db_path)),
                "o glossario mudou e o cache continuou valendo",
            )

    def test_rewriting_the_same_content_does_not_invalidate_the_cache(self):
        """O ganho de lado do hash, que o `mtime` nao dava.

        A gravacao do glossario e atomica (arquivo temporario + troca), entao o
        `mtime` muda mesmo quando o conteudo e identico — e o cache era refeito
        por nada. O hash olha o que importa.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "Substituicoes.txt"
            db_path = base / "glossario.db"
            save_glossary_entries(
                [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                db_path=str(db_path),
            )

            conteudo = path.read_bytes()
            path.write_bytes(conteudo)
            futuro = os.path.getmtime(path) + 3600
            os.utime(path, (futuro, futuro))

            self.assertFalse(
                glossario._glossary_database_needs_sync(str(path), str(db_path)),
                "reconstruiu por causa da data, com o conteudo igual",
            )

    def test_the_csv_carries_the_priority_and_tolerates_its_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            csv_path = base / "glossario.csv"
            entradas = [
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0),
                ("queen", "dama", GLOSSARY_RULE_AUTOMATIC, 2),
            ]
            export_glossary_csv(str(csv_path), entradas)

            self.assertEqual(read_glossary_csv(str(csv_path)), entradas)

            # Um CSV de tres colunas — de antes desta versao, ou montado numa
            # planilha — continua importavel.
            antigo = base / "antigo.csv"
            antigo.write_text(
                "original,replacement,type\r\nrook,torre,suggestion\r\n",
                encoding="utf-8-sig",
            )
            self.assertEqual(
                read_glossary_csv(str(antigo)),
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0)],
            )

    def test_saving_a_new_priority_finds_the_entry_to_update(self):
        """A prioridade nao entra na identidade da entrada, de proposito.

        O editor localiza a linha pelo estado que exibiu quando ela foi
        selecionada, e mudar a prioridade e justamente uma das coisas que
        "Salvar" faz. Se ela contasse na comparacao, salvar uma prioridade nova
        nunca encontraria a entrada a atualizar.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            # A entrada JA TEM prioridade, e e esse o caso que importa: com uma
            # entrada em zero, um criterio que comparasse a prioridade acertaria
            # por coincidencia, porque a linha-base tambem vale zero.
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 3)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            resultado = update_glossary_entry_by_entry(
                # O editor identifica a linha pelo que exibiu — sem prioridade.
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                "rook",
                "torre",
                str(path),
                backup_dir=str(Path(tmp) / "backups"),
                priority=5,
            )

            self.assertIsNotNone(resultado, "nao achou a entrada para atualizar")
            entradas = load_glossary_entry_details(str(path), prefer_db=False)
            self.assertEqual(entradas, [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 5)])

    def test_locating_an_entry_ignores_the_priority(self):
        """O mesmo, direto na funcao — e o que a promocao tambem depende.

        Depois de "Priorizar esta" a regra fica com prioridade 1 e a janela
        precisa reencontra-la pelo par e pelo tipo para manter a selecao. Com a
        prioridade na comparacao, a busca falha e o formulario e limpo.
        """
        entradas = [("torre", "castle", GLOSSARY_RULE_SUGGESTION, 1)]

        self.assertEqual(
            find_glossary_entry_index(entradas, ("torre", "castle", GLOSSARY_RULE_SUGGESTION)),
            0,
        )

    def test_updating_without_an_opinion_keeps_the_priority(self):
        """Quem chama sem falar de prioridade nao pode zerar a que existia."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 6)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            update_glossary_entry(
                0,
                "rook",
                "torre alta",
                str(path),
                backup_dir=str(Path(tmp) / "backups"),
            )

            entradas = load_glossary_entry_details(str(path), prefer_db=False)
            self.assertEqual(glossary_entry_priority(entradas[0]), 6)

    def test_adding_the_same_rule_with_another_priority_is_not_a_new_rule(self):
        """Senao a insercao criaria duas linhas identicas disputando entre si —
        exatamente o problema que a prioridade existe para resolver."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Substituicoes.txt"
            save_glossary_entries(
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION)],
                str(path),
                create_backup=False,
                sync_db=False,
            )

            resultado = add_glossary_entry(
                "rook", "torre", str(path), rule_type=GLOSSARY_RULE_SUGGESTION, priority=9
            )

            self.assertEqual(resultado["status"], "unchanged")
            self.assertEqual(
                len(load_glossary_entry_details(str(path), prefer_db=False)), 1
            )


class GlossaryPromotionTests(unittest.TestCase):
    """`promote_glossary_rule`: resolver o conflito sem apagar nada."""

    ENTRIES = [
        ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
        ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
    ]

    def test_promoting_the_loser_makes_it_win_without_removing_anything(self):
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)

        self.assertEqual(len(promovidas), 3, "a promocao removeu alguma regra")
        self.assertEqual(glossary_entry_priority(promovidas[2]), 1)
        self.assertEqual(glossary_entry_priority(promovidas[0]), 0, "mexeu na outra")

        conflitos = glossario.glossary_conflicts(promovidas)
        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 2)

    def test_the_promotion_reaches_the_text(self):
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)
        regras = [
            (orig, new, prio)
            for orig, new, _tipo, prio in promovidas
        ]

        self.assertEqual(apply_all_substitutions("a torre", self.ENTRIES), "a rook")
        self.assertEqual(apply_all_substitutions("a torre", regras), "a castle")

    def test_promoting_the_winner_changes_nothing(self):
        self.assertIsNone(promote_glossary_rule(list(self.ENTRIES), 0))

    def test_promoting_a_rule_without_conflict_changes_nothing(self):
        self.assertIsNone(promote_glossary_rule(list(self.ENTRIES), 1))

    def test_the_decision_can_be_reversed(self):
        """E a diferenca em relacao a "Manter esta": nada foi perdido."""
        promovidas = promote_glossary_rule(list(self.ENTRIES), 2)
        de_volta = promote_glossary_rule(promovidas, 0)

        self.assertIsNotNone(de_volta, "a decisao anterior nao pode ser revista")
        self.assertEqual(glossary_entry_priority(de_volta[0]), 2)
        conflitos = glossario.glossary_conflicts(de_volta)
        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 0)


class GlossaryConflictTests(unittest.TestCase):
    """Roadmap 1.5 / garantia S9: em cada conflito, qual regra esta valendo.

    Dois padroes identicos empatam em comprimento, entao `order_rules_by_specificity`
    desempata pela ordem do arquivo e o congelamento de S4 impede a segunda de
    rever o trecho: vence quem foi digitado primeiro. A interface nao dizia isso,
    e as duas regras apareciam lado a lado com o mesmo aspecto.
    """

    def aplicada(self, rules, texto):
        """A substituicao que o programa de fato produz para `texto`."""
        return apply_all_substitutions(texto, rules)

    def vencedores(self, entradas):
        """Os indices que a janela anuncia como vencedores, em todo contexto."""
        conflitos = glossario.glossary_conflicts(entradas)
        return {
            contexto["winner"]
            for info in conflitos.values()
            for contexto in info["contexts"]
        }

    def test_the_announcement_follows_a_change_in_the_application_order(self):
        """A prova de que o criterio e um so, e nao dois que hoje coincidem.

        Os outros testes desta classe exigem que anuncio e aplicacao concordem —
        e concordariam tambem com **duas copias** do mesmo criterio, que era o
        estado anterior. O que separa os dois casos e mexer no criterio uma vez
        so e exigir que os dois lados virem juntos.

        A inversao usada aqui e do desempate por ordem do arquivo, que e
        justamente o termo que decide entre padroes identicos. Com o criterio
        duplicado, `order_rules_by_specificity` obedeceria e `glossary_conflicts`
        continuaria anunciando o antigo vencedor — a divergencia que a SPEC
        listava como limite conhecido.
        """
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
        ]
        regras = [(orig, new) for orig, new, _tipo in entradas]

        # Linha de base: vence a primeira do arquivo, e o texto recebe 'rook'.
        self.assertEqual(self.vencedores(entradas), {0})
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a rook avanca")

        original = glossario._rule_sort_key

        def desempate_invertido(rule, position):
            prioridade, comprimento, posicao = original(rule, position)
            return (prioridade, comprimento, -posicao)

        # O cache guarda a ordem, nao o criterio: sem limpa-lo, a aplicacao
        # devolveria a ordem calculada antes da troca e o teste passaria por
        # motivo errado.
        def restaurar():
            glossario._rule_sort_key = original
            glossario._ordered_rules_cache.clear()

        self.addCleanup(restaurar)
        glossario._rule_sort_key = desempate_invertido
        glossario._ordered_rules_cache.clear()

        self.assertEqual(
            self.vencedores(entradas),
            {1},
            "o anuncio nao seguiu o criterio da aplicacao: ha uma copia dele",
        )
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a castle avanca")

    def test_the_announced_winner_is_the_one_actually_applied(self):
        """O teste central: o que o editor anuncia e o que o texto recebe.

        Anunciar um vencedor que nao e o aplicado seria pior do que nao anunciar
        nada, entao a afirmacao e verificada contra `apply_all_substitutions`, e
        nao contra outra copia da mesma regra de ordenacao.
        """
        for posicao_vencedora, regras in enumerate(
            [
                [("torre", "rook"), ("torre", "castle")],
                [("torre", "castle"), ("torre", "rook")],
            ]
        ):
            with self.subTest(ordem=posicao_vencedora):
                entradas = [
                    (orig, new, GLOSSARY_RULE_SUGGESTION) for orig, new in regras
                ]
                conflitos = glossario.glossary_conflicts(entradas)

                self.assertEqual(sorted(conflitos), [0, 1])
                for info in conflitos.values():
                    for contexto in info["contexts"]:
                        self.assertEqual(contexto["winner"], 0)

                # A ordem do arquivo decide: invertida, o resultado muda junto.
                esperado = regras[0][1]
                self.assertEqual(self.aplicada(regras, "a torre avanca"), f"a {esperado} avanca")

    def test_the_announced_winner_follows_the_priority_too(self):
        """A mesma exigencia, agora com a prioridade no meio (garantia S10).

        E aqui que um criterio duplicado se paga caro: `glossary_conflicts`
        decide o vencedor por conta propria, e se ele divergir de
        `order_rules_by_specificity` a janela anuncia uma regra e o texto recebe
        outra. Por isso a afirmacao continua sendo verificada contra
        `apply_all_substitutions`.
        """
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION, 0),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION, 2),
        ]
        conflitos = glossario.glossary_conflicts(entradas)

        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 1, "a ordem do arquivo venceu")

        regras = [(orig, new, prio) for orig, new, _tipo, prio in entradas]
        self.assertEqual(self.aplicada(regras, "a torre avanca"), "a castle avanca")

        # E a mensagem acompanha: quem perde continua sendo avisado.
        self.assertIn("nunca é aplicada", glossario.describe_glossary_conflict(entradas, 0, conflitos))
        self.assertNotIn("nunca é aplicada", glossario.describe_glossary_conflict(entradas, 1, conflitos))

    def test_the_loser_is_told_it_never_applies(self):
        entradas = [
            ("as Pretas", "das pretas", GLOSSARY_RULE_AUTOMATIC),
            ("as Pretas", "as pretas", GLOSSARY_RULE_AUTOMATIC),
        ]
        conflitos = glossario.glossary_conflicts(entradas)

        vencedora = glossario.describe_glossary_conflict(entradas, 0, conflitos)
        perdedora = glossario.describe_glossary_conflict(entradas, 1, conflitos)

        self.assertIn("vence esta regra", vencedora)
        self.assertNotIn("nunca é aplicada", vencedora)
        self.assertIn("#1", perdedora)
        self.assertIn("das pretas", perdedora)
        self.assertIn("nunca é aplicada", perdedora)

        # Uma regra automatica e carregada em dois contextos (as automaticas e as
        # sugestoes do editor) e vence nos dois. Nomear os dois seria repetir a
        # mesma frase com rotulos diferentes.
        self.assertNotIn("regras automáticas", vencedora)

    def test_a_rule_that_loses_in_the_editor_can_still_win_elsewhere(self):
        """O caso real de `'/\\'`, e o erro que ele pegou.

        A regra automatica vem depois da de sugestao, entao perde no editor, que
        carrega as duas. Mas na aplicacao das regras automaticas ela e a unica
        daquele padrao — e la ela e aplicada. Dizer "nunca e aplicada" seria
        falso, e era o que a primeira versao desta mensagem dizia.
        """
        entradas = [
            ("/\\", "com a ideia de", GLOSSARY_RULE_SUGGESTION),
            ("/\\", "Com a ideia de", GLOSSARY_RULE_AUTOMATIC),
        ]
        conflitos = glossario.glossary_conflicts(entradas)
        automatica = glossario.describe_glossary_conflict(entradas, 1, conflitos)

        self.assertIn("regras automáticas", automatica)
        self.assertIn("sugestões do editor", automatica)
        self.assertNotIn("nunca é aplicada", automatica)

        # E a contraprova pelo comportamento, nao pela mensagem.
        pares = [(orig, new) for orig, new, _tipo in entradas]
        self.assertEqual(self.aplicada(pares, "1. e4 /\\"), "1. e4 com a ideia de")
        so_automaticas = glossario.filter_glossary_entries_by_type(
            entradas, GLOSSARY_RULE_AUTOMATIC
        )
        self.assertEqual(self.aplicada(so_automaticas, "1. e4 /\\"), "1. e4 Com a ideia de")

    def test_exact_duplicates_are_not_a_conflict(self):
        """Duplicata e redundancia, nao disputa — e ja tem aviso proprio."""
        entradas = [
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_rules_never_loaded_together_do_not_conflict(self):
        """Limpeza roda antes da API; sugestao, no editor. Nunca no mesmo texto."""
        entradas = [
            ("torre", "", GLOSSARY_RULE_CLEANUP),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_keeping_one_rule_removes_only_the_rules_that_competed(self):
        entradas = [
            ("torre", "", GLOSSARY_RULE_CLEANUP),
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
            ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
        ]
        restantes = glossario.resolve_glossary_conflict(entradas, 2)

        self.assertEqual(
            restantes,
            [
                ("torre", "", GLOSSARY_RULE_CLEANUP),
                ("torre", "castle", GLOSSARY_RULE_SUGGESTION),
                ("dama", "queen", GLOSSARY_RULE_SUGGESTION),
            ],
            "a regra de limpeza nunca competiu e nao pode sair junto",
        )
        # Resolvido de verdade: o glossario que sobra nao tem mais disputa.
        self.assertEqual(glossario.glossary_conflicts(restantes), {})

    def test_resolving_a_rule_without_conflict_writes_nothing(self):
        entradas = [("torre", "rook", GLOSSARY_RULE_SUGGESTION)]
        self.assertIsNone(glossario.resolve_glossary_conflict(entradas, 0))
        self.assertEqual(glossario.describe_glossary_conflict(entradas, 0), "")

    def test_the_real_glossary_has_no_undecided_conflict(self):
        """O `Substituicoes.txt` versionado nao tem disputa pendente.

        Eram dois conflitos quando 1.5 foi aberto e quatro quando ele foi
        resolvido — dois entraram no meio do caminho, sem que ninguem notasse,
        porque nada os vigiava. Os quatro foram decididos (ver ROADMAP 1.5); este
        teste existe para que o quinto quebre a suite em vez de aparecer numa
        medicao daqui a um ano.

        Falhar aqui nao e defeito de codigo: e uma regra nova disputando um
        padrao com uma antiga. A saida diz quais sao, e a decisao e de quem
        editou o glossario — o botao "Manter esta" resolve cada uma.
        """
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        entradas = load_glossary_entry_details(str(path), deduplicate=False)
        conflitos = glossario.glossary_conflicts(entradas)

        relatorio = "\n".join(
            "  " + glossario.describe_glossary_conflict(entradas, index, conflitos)
            for index in sorted(conflitos)
        )
        self.assertEqual(
            conflitos,
            {},
            f"conflito novo no glossario, decida qual regra fica:\n{relatorio}",
        )


class RowIndexForIdTests(unittest.TestCase):
    """Roadmap 3.3: reencontrar a linha pelo id apos a lista ser recarregada."""

    ROWS = [
        (10, "orig a", "trad a", 0),
        (11, "orig b", "trad b", 0),
        (12, "orig c", "trad c", 1),
    ]

    def test_finds_the_row_by_id(self):
        self.assertEqual(row_index_for_id(self.ROWS, 10), 0)
        self.assertEqual(row_index_for_id(self.ROWS, 11), 1)
        self.assertEqual(row_index_for_id(self.ROWS, 12), 2)

    def test_the_id_wins_over_the_fallback(self):
        # E o ponto do item 3.3: a posicao antiga esta errada, o id nao.
        self.assertEqual(row_index_for_id(self.ROWS, 12, fallback=0), 2)

    def test_reload_that_drops_a_row_keeps_the_target(self):
        """O cenario exato do bug.

        A lista tinha [A, B, C] e o clique foi em B (posicao 1). Gravar removeu
        A do filtro "Avisos QA", entao a lista virou [B, C] e a posicao 1 agora
        e C. Pelo id, B continua sendo B.
        """
        antes = self.ROWS
        clicada = 1
        alvo = antes[clicada][0]

        depois = [row for row in antes if row[0] != 10]

        self.assertEqual(depois[clicada][0], 12, "a posicao antiga aponta para C")
        self.assertEqual(row_index_for_id(depois, alvo, fallback=clicada), 0)

    def test_missing_id_falls_back_to_the_neighbour(self):
        self.assertEqual(row_index_for_id(self.ROWS, 999, fallback=1), 1)

    def test_fallback_is_clamped_to_the_current_list(self):
        # A lista encolheu entre o clique e a leitura.
        self.assertEqual(row_index_for_id(self.ROWS[:2], 999, fallback=5), 1)
        self.assertEqual(row_index_for_id(self.ROWS, 999, fallback=-3), 0)

    def test_empty_list_has_nothing_to_select(self):
        self.assertIsNone(row_index_for_id([], 10, fallback=0))
        self.assertIsNone(row_index_for_id([], None))

    def test_none_id_uses_the_fallback(self):
        self.assertEqual(row_index_for_id(self.ROWS, None, fallback=2), 2)
        self.assertEqual(row_index_for_id(self.ROWS, None, fallback=99), 2)

    def test_first_match_wins(self):
        duplicadas = [(7, "a", "b", 0), (7, "c", "d", 0)]
        self.assertEqual(row_index_for_id(duplicadas, 7), 0)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("resposta nao e JSON")
        return self._payload


class FakeSession:
    """Devolve respostas roteirizadas e conta as requisicoes."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self.script.pop(0) if self.script else FakeResponse(200, [[["", ""]]])
        if isinstance(item, Exception):
            raise item
        return item


class RetryBackoffTests(unittest.TestCase):
    """Roadmap 7.2: a espera entre tentativas cresce, e reage a 429.

    Era `random.uniform(0.3, 2.2)` fixo entre as tres tentativas. Contra 429 isso
    e quase o mesmo que nao esperar: se o servidor pediu para desacelerar, a
    terceira tentativa chegava tao cedo quanto a primeira.

    O jitter e sorteado, entao comparar duas esperas reais seria instavel — as
    faixas de tentativas vizinhas se sobrepoem. Aqui o fator e fixado; a
    integracao logo abaixo confere que a espera real cai dentro da faixa.
    """

    def espera(self, attempt, status=None, jitter=1.0):
        return translation_api.retry_delay_seconds(attempt, status, jitter=jitter)

    def test_the_wait_doubles_at_each_attempt(self):
        base = translation_api.RETRY_BASE_SECONDS
        self.assertEqual(self.espera(1, 503), base)
        self.assertEqual(self.espera(2, 503), base * 2)
        self.assertEqual(self.espera(3, 503), base * 4)

    def test_a_rate_limit_waits_longer_than_a_server_error(self):
        """429 e 5xx tem causas diferentes e merecem esperas diferentes."""
        for attempt in (1, 2, 3):
            with self.subTest(attempt=attempt):
                self.assertGreater(self.espera(attempt, 429), self.espera(attempt, 503))

    def test_the_wait_is_capped(self):
        self.assertEqual(
            self.espera(40, 429), translation_api.RETRY_MAX_SECONDS
        )

    def test_a_network_error_uses_the_server_error_pace(self):
        """Sem resposta nao ha status; a espera nao pode virar zero nem explodir."""
        self.assertEqual(self.espera(1, None), translation_api.RETRY_BASE_SECONDS)

    def test_the_jitter_is_multiplicative(self):
        """Duas execucoes que tomem 429 juntas precisam se espalhar em proporcao.

        Um jitter aditivo de fracoes de segundo nao separa esperas de 8 s; um
        multiplicativo separa.
        """
        cheio = self.espera(3, 429, jitter=None)
        alvo = min(
            translation_api.RETRY_BASE_429_SECONDS * 4,
            translation_api.RETRY_MAX_SECONDS,
        )
        menor, maior = translation_api.RETRY_JITTER
        self.assertGreaterEqual(cheio, alvo * menor)
        self.assertLessEqual(cheio, alvo * maior)


class RequestPacerTests(unittest.TestCase):
    """Roadmap 7.2: o intervalo normal reage ao que a API responde.

    O retry conserta a requisicao que falhou, nao a causa: esgotadas as
    tentativas o comentario falha igual. Um 429 e o unico sinal confiavel de que
    o ritmo esta alto demais, e o intervalo das requisicoes SEGUINTES e o unico
    lugar onde esse sinal pode ser usado.
    """

    def pacer(self, **kwargs):
        return translation_api.RequestPacer(**kwargs)

    def test_at_rest_it_behaves_exactly_like_before(self):
        """Sem 429, o intervalo e o sorteio de sempre — multiplicador 1."""
        pacer = self.pacer()
        self.assertEqual(pacer.multiplier, 1.0)
        menor, maior = pacer.base_range
        for _ in range(50):
            self.assertGreaterEqual(pacer.next_delay(), menor)
            self.assertLessEqual(pacer.next_delay(), maior)

    def test_the_first_rate_limit_lifts_the_pace_off_the_floor(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        self.assertEqual(pacer.multiplier, pacer.first_multiplier)
        self.assertGreater(pacer.next_delay(), min(pacer.base_range))

    def test_repeated_rate_limits_keep_slowing_down_up_to_a_ceiling(self):
        pacer = self.pacer()
        anteriores = []
        for _ in range(10):
            pacer.record_rate_limited()
            anteriores.append(pacer.multiplier)

        self.assertEqual(anteriores[1], anteriores[0] * pacer.growth)
        self.assertEqual(anteriores[-1], pacer.maximum, "sem teto, o ritmo some")
        self.assertEqual(sorted(anteriores), anteriores, "o ritmo nunca acelera aqui")

    def test_a_clean_streak_is_needed_before_speeding_up_again(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        alto = pacer.multiplier

        for _ in range(pacer.clean_streak - 1):
            pacer.record_success()
        self.assertEqual(pacer.multiplier, alto, "acelerou antes da sequencia limpa")

        pacer.record_success()
        self.assertEqual(pacer.multiplier, max(1.0, alto * pacer.decay))

    def test_a_rate_limit_resets_the_clean_streak(self):
        """Meia sequencia limpa seguida de 429 nao pode contar como progresso."""
        pacer = self.pacer()
        pacer.record_rate_limited()
        for _ in range(pacer.clean_streak - 1):
            pacer.record_success()

        pacer.record_rate_limited()
        alto = pacer.multiplier
        pacer.record_success()
        self.assertEqual(pacer.multiplier, alto)

    def test_the_pace_never_goes_below_the_original_interval(self):
        pacer = self.pacer()
        pacer.record_rate_limited()
        for _ in range(pacer.clean_streak * 40):
            pacer.record_success()

        self.assertEqual(pacer.multiplier, 1.0)
        self.assertLessEqual(pacer.next_delay(), max(pacer.base_range))


class TranslateTextChunkTests(unittest.TestCase):
    """Retry/backoff da camada de rede (item 5 do ROADMAP).

    Nenhum destes testes toca a rede: a sessao HTTP e injetada.
    """

    OK_PAYLOAD = [[["Bom dia", "Good morning"], [" mundo", " world"]]]

    def setUp(self):
        # O backoff real dorme ate 2,2 s por tentativa — 4,4 s por teste que
        # esgota as tentativas. Aqui so registramos que dormiu.
        #
        # `translation_api.time` E o modulo padrao, entao isto troca
        # `time.sleep` globalmente enquanto o teste roda. E aceitavel porque a
        # suite e sequencial e o `addCleanup` devolve o original mesmo se o
        # teste falhar no meio.
        self.sleeps = []
        self.previous_sleep = translation_api.time.sleep
        translation_api.time.sleep = self.sleeps.append
        self.addCleanup(
            setattr, translation_api.time, "sleep", self.previous_sleep
        )
        self.logs = []

    def translate(self, script, text="Good morning world"):
        session = FakeSession(script)
        result = translation_api.translate_text_chunk(
            text, "pt", self.logs.append, session=session
        )
        return result, session

    def test_success_joins_the_segments(self):
        result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)])

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(self.sleeps, [], "nao dorme quando acerta de primeira")

    def test_request_carries_only_the_text(self):
        """Garantia W1: nada alem do texto a traduzir sai daqui."""
        _result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)], "abc")

        params = session.calls[0]["params"]
        self.assertEqual(params["q"], "abc")
        self.assertEqual(params["tl"], "pt")
        self.assertEqual(set(params) - {"client", "sl", "tl", "dt", "q"}, set())

    def test_the_declared_source_language_goes_in_the_request(self):
        """`sl=auto` faz o endpoint adivinhar a partir do texto.

        Um comentario curto de xadrez — "Ng5!", "Bien jugado" — e pouco texto
        para adivinhar, e o palpite errado produz uma traducao errada sem erro
        nenhum. Dito o idioma, ele para de tentar.
        """
        session = FakeSession([FakeResponse(200, self.OK_PAYLOAD)])
        translation_api.translate_text_chunk(
            "abc", "pt", self.logs.append, session=session, source_language="es"
        )

        self.assertEqual(session.calls[0]["params"]["sl"], "es")

    def test_without_a_declared_source_it_still_asks_for_detection(self):
        """O padrao continua sendo o que o programa sempre fez."""
        _result, session = self.translate([FakeResponse(200, self.OK_PAYLOAD)], "abc")

        self.assertEqual(session.calls[0]["params"]["sl"], "auto")

    def test_the_source_language_survives_the_split_into_chunks(self):
        """Um comentario longo vira varias requisicoes, e todas sao do mesmo PGN.

        Perder o idioma entre a primeira e a segunda daria metade da traducao
        com o idioma declarado e metade adivinhada.
        """
        session = FakeSession([FakeResponse(200, self.OK_PAYLOAD) for _ in range(10)])
        texto = ("Frase. " * 2000).strip()
        self.assertGreater(len(split_text_for_translation(texto)), 1)

        translation_api.translate_text(
            texto, "pt", session=session, source_language="it"
        )

        self.assertTrue(session.calls)
        self.assertEqual(
            {chamada["params"]["sl"] for chamada in session.calls}, {"it"}
        )

    def test_empty_segments_are_skipped(self):
        payload = [[["Um", "One"], None, ["", ""], [" dois", " two"]]]
        result, _session = self.translate([FakeResponse(200, payload)])

        self.assertEqual(result, "Um dois")

    def test_retryable_status_is_retried_three_times(self):
        result, session = self.translate([FakeResponse(503) for _ in range(3)])

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 3)
        # Dorme entre as tentativas, nao depois da ultima.
        self.assertEqual(len(self.sleeps), 2)

    def test_retryable_then_success(self):
        result, session = self.translate(
            [FakeResponse(429), FakeResponse(200, self.OK_PAYLOAD)]
        )

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(len(self.sleeps), 1)

    def test_every_retryable_status_is_retried(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.sleeps.clear()
                result, session = self.translate(
                    [FakeResponse(status), FakeResponse(200, self.OK_PAYLOAD)]
                )
                self.assertEqual(result, "Bom dia mundo")
                self.assertEqual(len(session.calls), 2)

    def test_other_statuses_fail_immediately(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.sleeps.clear()
                result, session = self.translate([FakeResponse(status)])
                self.assertIsNone(result)
                self.assertEqual(len(session.calls), 1, "nao pode insistir")
                self.assertEqual(self.sleeps, [])

    def test_network_error_is_retried(self):
        result, session = self.translate(
            [
                translation_api.requests.RequestException("timeout"),
                translation_api.requests.RequestException("timeout"),
                FakeResponse(200, self.OK_PAYLOAD),
            ]
        )

        self.assertEqual(result, "Bom dia mundo")
        self.assertEqual(len(session.calls), 3)

    def test_network_error_exhausted_returns_none(self):
        result, session = self.translate(
            [translation_api.requests.RequestException("timeout") for _ in range(3)]
        )

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 3)
        self.assertTrue(any("tentativa 3/3" in line for line in self.logs))

    def test_unexpected_payload_fails_without_retrying(self):
        """Uma resposta 200 ilegivel nao melhora tentando de novo."""
        result, session = self.translate([FakeResponse(200, raise_on_json=True)])

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(any("inesperada" in line.lower() for line in self.logs))

    def test_failure_is_always_logged(self):
        """Garantia T2: falha nunca passa em silencio."""
        self.translate([FakeResponse(500) for _ in range(3)])
        self.assertTrue(self.logs)
        self.assertTrue(all("[ERRO API]" in line for line in self.logs))

    def test_each_wait_falls_inside_its_attempt_window(self):
        """A espera real e sorteada, mas dentro da faixa daquela tentativa."""
        self.translate([FakeResponse(503) for _ in range(3)])

        self.assertEqual(len(self.sleeps), 2)
        menor, maior = translation_api.RETRY_JITTER
        for indice, dormiu in enumerate(self.sleeps):
            attempt = indice + 1
            alvo = min(
                translation_api.RETRY_BASE_SECONDS * (2 ** indice),
                translation_api.RETRY_MAX_SECONDS,
            )
            with self.subTest(tentativa=attempt):
                self.assertGreaterEqual(dormiu, alvo * menor)
                self.assertLessEqual(dormiu, alvo * maior)

    def test_a_rate_limit_slows_the_following_requests(self):
        """O 429 precisa sair daqui e mudar o ritmo, nao so a proxima tentativa."""
        pacer = translation_api.RequestPacer()
        session = FakeSession([FakeResponse(429), FakeResponse(200, self.OK_PAYLOAD)])

        resultado = translation_api.translate_text_chunk(
            "Good morning world", "pt", self.logs.append, session=session, pacer=pacer
        )

        self.assertEqual(resultado, "Bom dia mundo")
        self.assertEqual(pacer.rate_limited, 1)
        self.assertGreater(pacer.multiplier, 1.0)

    def test_a_server_error_does_not_change_the_pace(self):
        """503 e problema do servidor, nao ritmo alto demais. Sao coisas distintas."""
        pacer = translation_api.RequestPacer()
        session = FakeSession([FakeResponse(503), FakeResponse(200, self.OK_PAYLOAD)])

        translation_api.translate_text_chunk(
            "Good morning world", "pt", self.logs.append, session=session, pacer=pacer
        )

        self.assertEqual(pacer.rate_limited, 0)
        self.assertEqual(pacer.multiplier, 1.0)

    def test_an_unreadable_200_does_not_count_as_a_clean_request(self):
        """Uma 200 ilegivel nao e sinal de que o ritmo esta bom."""
        pacer = translation_api.RequestPacer()
        pacer.record_rate_limited()
        pacer.clean_run = pacer.clean_streak - 1

        translation_api.translate_text_chunk(
            "x",
            "pt",
            self.logs.append,
            session=FakeSession([FakeResponse(200, raise_on_json=True)]),
            pacer=pacer,
        )

        self.assertEqual(pacer.clean_run, pacer.clean_streak - 1)

    def test_the_pacer_is_optional(self):
        """A camada de rede continua utilizavel sem ele."""
        resultado, _session = self.translate([FakeResponse(200, self.OK_PAYLOAD)])
        self.assertEqual(resultado, "Bom dia mundo")

    def test_works_without_a_logger(self):
        session = FakeSession([FakeResponse(404)])
        self.assertIsNone(
            translation_api.translate_text_chunk("x", "pt", None, session=session)
        )


class TranslateTextTests(unittest.TestCase):
    """A camada acima: divisao em partes e cancelamento."""

    def setUp(self):
        self.previous = translation_api.translate_text_chunk
        self.addCleanup(
            setattr, translation_api, "translate_text_chunk", self.previous
        )

    def test_one_failed_chunk_fails_the_whole_text(self):
        """Garantia T3: nao se monta uma traducao pela metade."""
        chamadas = []

        def fake(chunk, _lang, _log=None, session=None, pacer=None, source_language=""):
            chamadas.append(chunk)
            return None if len(chamadas) == 2 else "ok"

        translation_api.translate_text_chunk = fake
        texto = ("Frase. " * 2000).strip()
        self.assertGreater(len(split_text_for_translation(texto)), 1)

        self.assertIsNone(translation_api.translate_text(texto, "pt"))

    def test_cancel_flag_stops_before_the_next_request(self):
        chamadas = []
        flag = threading.Event()

        def fake(chunk, _lang, _log=None, session=None, pacer=None, source_language=""):
            chamadas.append(chunk)
            flag.set()
            return "ok"

        translation_api.translate_text_chunk = fake
        texto = ("Frase. " * 2000).strip()

        self.assertIsNone(
            translation_api.translate_text(texto, "pt", cancel_flag=flag)
        )
        self.assertEqual(len(chamadas), 1, "parou apos o primeiro pedaco")


class CaseAdjustedReplacementTests(unittest.TestCase):
    """Propagacao de caixa do texto encontrado para a substituicao."""

    def test_all_caps_matched_text_uppercases_the_replacement(self):
        self.assertEqual(case_adjusted_replacement("ROOK", "torre"), "TORRE")

    def test_leading_capital_capitalizes_the_replacement(self):
        self.assertEqual(case_adjusted_replacement("Rook", "torre"), "Torre")

    def test_lowercase_is_left_alone(self):
        self.assertEqual(case_adjusted_replacement("rook", "torre"), "torre")

    def test_only_the_first_letter_changes(self):
        # Nao pode virar "Torre Alta": a substituicao decide o resto.
        self.assertEqual(case_adjusted_replacement("Rook", "torre alta"), "Torre alta")

    def test_a_single_capital_letter_counts_as_all_caps(self):
        self.assertEqual(case_adjusted_replacement("R", "torre"), "TORRE")

    def test_text_without_letters_does_not_change_anything(self):
        # Sem letras nao ha caixa a propagar; decidir por "tudo maiusculo"
        # transformaria "1-0" em substituicao gritada.
        self.assertEqual(case_adjusted_replacement("1-0", "vitoria"), "vitoria")
        self.assertEqual(case_adjusted_replacement("...", "reticencias"), "reticencias")

    def test_leading_symbol_uses_the_first_letter(self):
        self.assertEqual(case_adjusted_replacement("-Rook", "torre"), "Torre")
        self.assertEqual(case_adjusted_replacement("-rook", "torre"), "torre")

    def test_mixed_case_is_left_alone(self):
        self.assertEqual(case_adjusted_replacement("rOOk", "torre"), "torre")

    def test_empty_inputs_are_safe(self):
        self.assertEqual(case_adjusted_replacement("", "torre"), "torre")
        self.assertEqual(case_adjusted_replacement("ROOK", ""), "")
        self.assertIsNone(case_adjusted_replacement("ROOK", None))

    def test_accented_letters_follow_the_same_rule(self):
        self.assertEqual(case_adjusted_replacement("ÁRVORE", "tree"), "TREE")
        self.assertEqual(case_adjusted_replacement("Árvore", "tree"), "Tree")


class ReadGlossaryCsvTests(unittest.TestCase):
    """Leitura do CSV de importacao do glossario."""

    def write_csv(self, directory, content, encoding="utf-8-sig"):
        path = Path(directory) / "entrada.csv"
        path.write_text(content, encoding=encoding, newline="")
        return str(path)

    def test_reads_the_exported_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp,
                "original,replacement,type\r\nrook,torre,suggestion\r\npawn,peao,automatic\r\n",
            )

            self.assertEqual(
                read_glossary_csv(path),
                com_prioridade([
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC),
                ]),
            )

    def test_round_trip_with_the_exporter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "saida.csv")
            entries = [
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION),
                ("pawn", "peão", GLOSSARY_RULE_AUTOMATIC),
            ]
            export_glossary_csv(path, entries)

            self.assertEqual(read_glossary_csv(path), com_prioridade(entries))

    def test_accepts_the_portuguese_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "Original,Substituição,Tipo\r\nrook,torre,limpeza\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_CLEANUP, 0)]
            )

    def test_headers_are_matched_ignoring_case_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "  ORIGINAL ,  Replacement  \r\nrook,torre\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0)]
            )

    def test_missing_type_column_defaults_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,replacement\r\nrook,torre\r\n")

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0)]
            )

    def test_unknown_type_falls_back_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement,type\r\nrook,torre,inventado\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0)]
            )

    def test_values_are_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\n  rook  ,  torre  \r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0)]
            )

    def test_missing_required_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,tipo\r\nrook,suggestion\r\n")

            with self.assertRaises(ValueError):
                read_glossary_csv(path)

    def test_empty_file_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_glossary_csv(self.write_csv(tmp, "")), [])

    def test_header_only_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,replacement,type\r\n")
            self.assertEqual(read_glossary_csv(path), [])

    def test_bom_does_not_leak_into_the_first_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\nrook,torre\r\n", encoding="utf-8-sig"
            )
            # Sem tratar o BOM, o primeiro campo viria como "﻿original" e a
            # coluna obrigatoria pareceria ausente.
            self.assertEqual(len(read_glossary_csv(path)), 1)

    def test_accents_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\ncheck,xeque à descoberta\r\n"
            )

            self.assertEqual(read_glossary_csv(path)[0][1], "xeque à descoberta")


class WorkerFallbackHarness:
    """Roda `run_translation` com a rede substituida por uma funcao do teste.

    Fica separado do `TestCase` porque duas classes precisam dele (B2 e C3) e
    herdar de uma classe de teste faria os testes da outra rodarem duas vezes.
    """

    PGN = (
        '[Event "Test"]\n\n'
        "1. e4 {First comment here} e5 {Second comment here} "
        "2. Nf3 {Third comment here}\n"
    )
    COMMENTS = ["First comment here", "Second comment here", "Third comment here"]

    def run_worker(self, tmp_path, translate):
        pgn = tmp_path / "game.pgn"
        pgn.write_text(self.PGN, encoding="utf-8")
        app = FakeApp(tmp_path / "cache.db")

        originals = (
            translation_worker.translate_text,
            translation_worker.messagebox.showinfo,
            translation_worker.messagebox.showwarning,
        )
        try:
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            translation_worker.messagebox.showwarning = lambda *_a, **_k: None
            translation_worker.run_translation(app, str(pgn), "pt", False)
        finally:
            (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            ) = originals

        return app, pgn

    def stored(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return dict(
                conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()


class FailedRunWorkerTests(unittest.TestCase):
    """Roadmap 7.3: o worker anota o que ficou devendo, e reprocessa so isso."""

    PGN_A = '[Event "A"]\n\n1. e4 {Comentario do arquivo A} e5\n'
    PGN_B = '[Event "B"]\n\n1. d4 {Comentario do arquivo B} d5\n'

    def roda(self, tmp_path, translate, only_files=None, cancelar=False):
        app = FakeApp(tmp_path / "cache.db")
        if cancelar:
            app.cancel_flag.set()

        originais = (
            translation_worker.translate_text,
            translation_worker.messagebox.showinfo,
            translation_worker.messagebox.showwarning,
        )
        try:
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            translation_worker.messagebox.showwarning = lambda *_a, **_k: None
            translation_worker.run_translation(
                app, str(tmp_path), "pt", False, only_files=only_files
            )
        finally:
            (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            ) = originais
        return app

    def escreve_pgns(self, tmp_path):
        (tmp_path / "a.pgn").write_text(self.PGN_A, encoding="utf-8")
        (tmp_path / "b.pgn").write_text(self.PGN_B, encoding="utf-8")
        return str(tmp_path / "a.pgn"), str(tmp_path / "b.pgn")

    def so_o_arquivo_a_falha(self, text, *_args, **_kwargs):
        return None if "arquivo A" in text else f"[{text}]"

    def test_the_cache_holds_only_what_these_files_need(self):
        """Roadmap 2.9: o worker nao traz o idioma inteiro para a memoria.

        Nada quebra se ele trouxer — o resultado e o mesmo —, so que carrega
        195 mil traducoes (74 MB) para processar uma pasta com algumas dezenas.
        Por isso o teste olha o CONTEUDO do cache, e nao a saida da traducao.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.escreve_pgns(tmp_path)

            # Traducoes de outros arquivos, que esta execucao nao vai consultar.
            conn = initialize_database(str(tmp_path / "cache.db"))
            cur = conn.cursor()
            for i in range(50):
                save_translation(cur, f"comentario de outro arquivo {i}", f"t{i}", "pt")
            conn.commit()
            conn.close()

            app = self.roda(tmp_path, lambda text, *_a, **_k: f"[{text}]")

            intrusos = [
                chave for chave in app.translation_cache
                if chave.startswith("comentario de outro arquivo")
            ]
            self.assertEqual(
                intrusos, [], "o cache trouxe traducoes que estes arquivos nao usam"
            )
            self.assertIn("Comentario do arquivo A", app.translation_cache)

    def test_a_run_with_failures_records_only_the_guilty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            caminho_a, _caminho_b = self.escreve_pgns(tmp_path)

            self.roda(tmp_path, self.so_o_arquivo_a_falha)

            registro = failed_runs.load_failed_run()
            self.assertIsNotNone(registro, "nada foi anotado")
            self.assertEqual(registro["files"], [caminho_a])
            self.assertEqual(registro["target_language"], "pt")
            self.assertEqual(registro["failed_count"], 1)

    def test_a_clean_run_erases_a_previous_record(self):
        """Senao o botao ofereceria para sempre uma lista ja resolvida."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.escreve_pgns(tmp_path)

            self.roda(tmp_path, self.so_o_arquivo_a_falha)
            self.assertIsNotNone(failed_runs.load_failed_run())

            self.roda(tmp_path, lambda text, *_a, **_k: f"[{text}]")
            self.assertIsNone(failed_runs.load_failed_run())

    def test_a_run_canceled_midway_does_not_replace_the_record(self):
        """Os arquivos ainda nao visitados nao foram avaliados.

        Gravar a lista parcial por cima da anterior perderia o que ela ja sabia.

        O cancelamento acontece **no meio**, com um arquivo ja traduzido — que e
        o caso que importa. Cancelar antes de comecar nao exerce nada: o worker
        retorna na primeira checagem e nem chega perto do registro. Foi o que a
        verificacao por mutacao mostrou sobre a primeira versao deste teste.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.escreve_pgns(tmp_path)

            self.roda(tmp_path, self.so_o_arquivo_a_falha)
            antes = failed_runs.load_failed_run()
            self.assertIsNotNone(antes)

            app = FakeApp(tmp_path / "cache.db")

            def cancela_no_meio(text, *_args, **_kwargs):
                app.cancel_flag.set()
                return f"[{text}]"

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            )
            try:
                translation_worker.translate_text = cancela_no_meio
                translation_worker.messagebox.showinfo = lambda *_a, **_k: None
                translation_worker.messagebox.showwarning = lambda *_a, **_k: None
                translation_worker.run_translation(app, str(tmp_path), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showinfo,
                    translation_worker.messagebox.showwarning,
                ) = originais

            self.assertTrue(
                any("cancelada" in linha.lower() for linha in app.logs),
                "a execucao precisava ter sido cancelada de verdade",
            )
            self.assertEqual(failed_runs.load_failed_run(), antes)

    def test_only_files_leaves_the_other_files_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            caminho_a, _caminho_b = self.escreve_pgns(tmp_path)
            pedidos = []

            def translate(text, *_args, **_kwargs):
                pedidos.append(text)
                return f"[{text}]"

            self.roda(tmp_path, translate, only_files=[caminho_a])

            juntos = " ".join(pedidos)
            self.assertIn("arquivo A", juntos)
            self.assertNotIn("arquivo B", juntos, "abriu um arquivo que nao devia nada")

    def test_reprocessing_the_recorded_file_clears_the_record(self):
        """O ciclo completo: falhou, foi anotado, reprocessou, sumiu da lista."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.escreve_pgns(tmp_path)

            self.roda(tmp_path, self.so_o_arquivo_a_falha)
            registro = failed_runs.load_failed_run()
            self.assertIsNotNone(registro)

            self.roda(
                tmp_path,
                lambda text, *_a, **_k: f"[{text}]",
                only_files=registro["files"],
            )

            self.assertIsNone(failed_runs.load_failed_run())

    def test_a_generated_output_name_is_not_filtered_out_of_the_retry(self):
        """`collect_pgn_files` descarta nomes com sufixo de idioma.

        Um PGN de origem que por acaso se chame "algo-BR.pgn" sairia da lista
        justamente por ter falhado antes. A lista explicita nao passa por esse
        filtro.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            caminho = tmp_path / "estudo-BR.pgn"
            caminho.write_text(self.PGN_A, encoding="utf-8")
            pedidos = []

            def translate(text, *_args, **_kwargs):
                pedidos.append(text)
                return f"[{text}]"

            self.roda(tmp_path, translate, only_files=[str(caminho)])

            self.assertTrue(pedidos, "o arquivo foi descartado pelo filtro de sufixo")


class BatchFallbackTests(WorkerFallbackHarness, unittest.TestCase):
    """Garantia B2: desalinhamento do lote -> traducao individual.

    Era o ultimo caminho do worker sem teste. E o que impede o pior defeito
    possivel do programa: atribuir a traducao de um comentario a outro.
    """

    def test_misaligned_batch_falls_back_to_one_by_one(self):
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                # Devolve MENOS partes que o esperado: o lote esta desalinhado.
                return "so uma parte"
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)

            gravadas = self.stored(tmp_path / "cache.db")

        # Cada comentario recebeu a SUA traducao, nao a de outro.
        for comentario in self.COMMENTS:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")

        # Uma requisicao do lote + uma por comentario.
        self.assertEqual(len(chamadas), 1 + len(self.COMMENTS))
        self.assertTrue(any(" ||| " in c for c in chamadas), "o lote foi tentado")
        self.assertTrue(
            any("individualmente" in linha for linha in app.logs),
            "a queda para o modo individual devia aparecer no log",
        )

    def test_extra_parts_also_trigger_the_fallback(self):
        """Partes a mais e tao desalinhado quanto partes a menos."""

        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"parte{i}" for i in range(len(self.COMMENTS) + 2))
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        for comentario in self.COMMENTS:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")

    def test_aligned_batch_does_not_fall_back(self):
        """Contraprova: alinhado, resolve tudo numa requisicao so."""
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                partes = text.split(" ||| ")
                return " ||| ".join(f"[{p}]" for p in partes)
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        for comentario in self.COMMENTS:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")
        self.assertEqual(len(chamadas), 1, "nao devia traduzir de novo um por um")
        self.assertFalse(any("individualmente" in linha for linha in app.logs))

    def test_failure_in_the_fallback_keeps_the_original_text(self):
        """Garantias T2/T3: o que falhou fica no idioma original e e reportado."""

        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return "desalinhado"
            if text == "Second comment here":
                return None
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, pgn = self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")
            gerado = list(tmp_path.glob("*-BR.pgn"))
            self.assertTrue(gerado, "o PGN traduzido devia ter sido gerado")
            # Lido aqui dentro: o diretorio temporario some ao sair do `with`.
            conteudo = gerado[0].read_text(encoding="utf-8")

        self.assertNotIn("Second comment here", gravadas)
        self.assertEqual(gravadas.get("First comment here"), "[First comment here]")
        self.assertIn("{Second comment here}", conteudo, "o que falhou fica no original")
        self.assertIn("{[First comment here]}", conteudo)
        self.assertTrue(any("ATENCAO" in linha for linha in app.logs))


def escrita_disponivel(db_path, espera_ms=2000):
    """True se OUTRA conexao consegue pegar o lock de escrita agora.

    `BEGIN IMMEDIATE` + `ROLLBACK`: pega o lock e devolve sem alterar nada. E a
    pergunta que o editor faz implicitamente toda vez que grava uma traducao
    enquanto o worker esta rodando.

    A espera curta e proposital. Em producao o `busy_timeout` e 30 s; aqui, uma
    regressao que volte a segurar o lock deve falhar em 2 s, e nao arrastar o
    teste por meio minuto.
    """
    conn = sqlite3.connect(str(db_path), timeout=espera_ms / 1000)
    try:
        conn.execute(f"PRAGMA busy_timeout = {espera_ms}")
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


class ConcurrentDatabaseAccessTests(unittest.TestCase):
    """Garantia C3: o editor nunca e bloqueado pelo worker.

    Toda a suite roda uma coisa de cada vez, e por isso nao encostava nesta
    classe de defeito: o editor e o worker usam o MESMO `traducoes.db`, cada um
    com sua conexao.

    O que trava e a ESCRITA, nao a leitura. Duas conexoes nunca escrevem ao mesmo
    tempo — nem em WAL —, entao uma transacao aberta no worker bloqueia o
    "Salvar" do editor pelos 30 s do `busy_timeout` e depois falha. O caso real
    esta em `FallbackTransactionTests`, que reproduz o cenario ponta a ponta.

    A leitura simultanea, testada aqui, e a metade barata do problema: mesmo sem
    WAL o leitor so espera durante o commit do escritor. Os testes desta classe
    fixam o modo do arquivo e o fato de que ler durante uma escrita aberta
    funciona — nao pretendem provar que sem WAL isso quebraria, porque nao
    quebraria de forma confiavel.
    """

    def _semear(self, db_path):
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        for indice in range(20):
            save_translation(cursor, f"comentario {indice}", f"traducao {indice}", "pt")
        conn.commit()
        conn.close()

    def _com_escrita_aberta(self, db_path, durante, abrir=None):
        """Roda `durante()` enquanto uma thread mantem uma escrita aberta.

        Reproduz o estado do worker: transacao de escrita iniciada e ainda nao
        comitada. O `durante()` roda na thread principal, como o callback do Tk.

        `abrir` existe por causa da contraprova: `initialize_database` forca WAL
        em toda conexao, e o `journal_mode` e propriedade do ARQUIVO. Usa-lo do
        lado escritor desfaria o `PRAGMA journal_mode = DELETE` que a
        contraprova acabou de aplicar, e o cenario antigo nunca seria
        reproduzido.
        """
        if abrir is None:
            abrir = lambda caminho: initialize_database(str(caminho))

        pronto = threading.Event()
        solte = threading.Event()
        falha = []

        def escritor():
            try:
                conn = abrir(db_path)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO comments (original_comment, translated_comment,"
                    " target_language) VALUES ('novo', 'novo', 'pt')"
                )
                pronto.set()
                solte.wait(30)
                conn.commit()
                conn.close()
            except Exception as exc:  # pragma: no cover - falha de infra do teste
                falha.append(exc)
                pronto.set()

        thread = threading.Thread(target=escritor)
        thread.start()
        try:
            self.assertTrue(pronto.wait(30), "a escrita concorrente nao comecou")
            self.assertFalse(falha, f"a thread escritora falhou: {falha}")
            return durante()
        finally:
            solte.set()
            thread.join(30)

    def test_open_database_puts_the_file_in_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "cache.db"))
            try:
                modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                conn.close()
        self.assertEqual(modo.lower(), "wal")

    def test_the_editor_reads_while_the_worker_holds_an_open_write(self):
        """O caso real: clicar numa linha do editor durante uma traducao."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)

            def leitura_do_editor():
                leitor = initialize_database(str(db_path))
                # Producao espera 30 s antes de desistir. Aqui a espera e curta
                # para que uma regressao falhe rapido, em vez de travar a suite.
                leitor.execute("PRAGMA busy_timeout = 2000")
                comeco = time.perf_counter()
                try:
                    linhas = fetch_review_rows_page(leitor.cursor(), "pt", limit=10)
                finally:
                    leitor.close()
                return len(linhas), time.perf_counter() - comeco

            quantas, decorrido = self._com_escrita_aberta(db_path, leitura_do_editor)

        self.assertEqual(quantas, 10)
        self.assertLess(
            decorrido,
            1.0,
            "a leitura devia ser imediata, nao esperar pelo lock do worker",
        )

    def test_a_second_writer_is_blocked_no_matter_the_journal_mode(self):
        """O mecanismo que C3 tem de contornar, fixado como teste.

        E facil supor que WAL resolve tudo. Nao resolve isto: WAL desacopla
        leitor de escritor, nunca escritor de escritor. Enquanto o worker
        mantiver transacao aberta, o "Salvar" do editor espera e falha — e a
        unica saida e o worker nao manter a transacao aberta.

        Se este teste um dia passar a falhar, e porque alguem mudou o modo do
        banco achando que isso dispensa o commit por comentario do worker. Nao
        dispensa.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)

            modo = initialize_database(str(db_path))
            try:
                self.assertEqual(
                    modo.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                    "wal",
                    "o cenario abaixo vale justamente COM o WAL ligado",
                )
            finally:
                modo.close()

            livre = self._com_escrita_aberta(
                db_path,
                lambda: escrita_disponivel(db_path, espera_ms=500),
            )

        self.assertFalse(
            livre,
            "escritor concorrente devia ser barrado mesmo em WAL",
        )


class ApiFailureTests(WorkerFallbackHarness, unittest.TestCase):
    """Garantia B3: falha da API nao e desalinhamento, e nao se trata igual.

    O fallback individual era acionado pelas duas causas. Quando a causa era a
    API nao responder, ele repetia comentario a comentario uma requisicao que ja
    tinha gastado 3 tentativas — e cada repeticao gastava outras 3, com ate 30 s
    de timeout cada. Um lote de 40 comentarios contra um endpoint pendurado
    levava perto de uma hora para terminar com os 40 falhando do mesmo jeito.
    """

    def test_a_batch_the_api_did_not_answer_is_not_retried_one_by_one(self):
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            return None  # a API nao respondeu

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")
            gerados = list(tmp_path.glob("*-BR.pgn"))

        # UMA requisicao (a do lote), e nao uma por comentario.
        self.assertEqual(
            len(chamadas),
            1,
            f"a API foi chamada {len(chamadas)} vezes; devia ser so a do lote",
        )
        self.assertIn(" ||| ", chamadas[0])

        # T2/T3: nada inventado, tudo contabilizado e dito.
        self.assertEqual(gravadas, {})
        self.assertTrue(
            any("[FALHA] A API nao respondeu" in linha for linha in app.logs),
            "a falha da chamada precisa aparecer no log — era o unico caminho mudo",
        )
        self.assertTrue(any("ATENCAO" in linha for linha in app.logs))
        self.assertFalse(
            gerados,
            "sem nenhuma traducao, nao ha PGN de saida a gerar",
        )
        self.assertTrue(
            any("Nenhum arquivo de saida foi gerado" in linha for linha in app.logs),
            "mandar 'reprocesse os arquivos gerados' sem arquivo gerado e mentira",
        )

    def test_misalignment_still_falls_back_one_by_one(self):
        """B2 nao mudou: se a resposta VEIO, o fallback continua valendo."""
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                return "so uma parte"
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        self.assertEqual(len(chamadas), 1 + len(self.COMMENTS))
        for comentario in self.COMMENTS:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")
        self.assertTrue(any("individualmente" in linha for linha in app.logs))

    def test_the_circuit_breaker_stops_after_consecutive_dead_batches(self):
        """Sem disjuntor, um endpoint fora arrasta a execucao por horas."""
        pgn_longo = '[Event "Test"]\n\n'
        comentarios = []
        for indice in range(12):
            # Comentarios grandes o bastante para render varios lotes.
            texto = f"Comment number {indice} " + "x" * (BATCH_MAX_CHARS // 2)
            comentarios.append(texto)
            pgn_longo += f"{indice + 1}. e4 {{{texto}}} "

        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            return None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pgn = tmp_path / "game.pgn"
            pgn.write_text(pgn_longo, encoding="utf-8")
            app = FakeApp(tmp_path / "cache.db")

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            )
            try:
                translation_worker.translate_text = translate
                translation_worker.messagebox.showinfo = lambda *_a, **_k: None
                translation_worker.messagebox.showwarning = lambda *_a, **_k: None
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showinfo,
                    translation_worker.messagebox.showwarning,
                ) = originais

        self.assertGreater(
            len(comentarios),
            translation_worker.MAX_CONSECUTIVE_FAILED_BATCHES,
            "o PGN precisa render mais lotes que o limite do disjuntor",
        )
        self.assertEqual(
            len(chamadas),
            translation_worker.MAX_CONSECUTIVE_FAILED_BATCHES,
            "parou depois do limite, e nao no fim da lista",
        )
        self.assertTrue(any("[ABORTADO]" in linha for linha in app.logs))
        self.assertTrue(
            any("INTERROMPIDA" in linha for linha in app.logs),
            "o resumo precisa dizer que a execucao nao terminou normalmente",
        )


class FallbackTransactionTests(WorkerFallbackHarness, unittest.TestCase):
    """Garantia C3: o fallback individual nao segura o lock atravessando a rede.

    O primeiro `save_translation` do fallback abre a transacao de escrita. Antes,
    o `commit` so vinha no fim do lote — entao a transacao atravessava TODAS as
    chamadas de rede restantes. Num lote de 40 comentarios a ~1 s por
    requisicao, sao mais de 40 s de lock retido, acima do `busy_timeout` de 30 s
    do editor.
    """

    def test_the_individual_fallback_never_holds_a_write_across_the_network(self):
        sondas = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"

            def translate(text, *_args, **_kwargs):
                if " ||| " in text:
                    return "desalinhado"
                # Este ponto E a chamada de rede. Se o worker estiver segurando
                # a transacao aqui, o editor esta travado agora.
                sondas.append((text, escrita_disponivel(db_path)))
                return f"[{text}]"

            self.run_worker(tmp_path, translate)
            gravadas = self.stored(db_path)

        # As sondas depois da primeira sao as que importam: nelas ja houve pelo
        # menos uma gravacao, entao a transacao estaria aberta.
        self.assertEqual(len(sondas), len(self.COMMENTS))
        travadas = [texto for texto, livre in sondas if not livre]
        self.assertEqual(
            travadas,
            [],
            "o banco estava travado durante a chamada de rede destes comentarios",
        )
        # E o fallback continua fazendo o que B2 exige.
        for comentario in self.COMMENTS:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")


class BackupSizeBudgetTests(unittest.TestCase):
    """Terceira regra da retencao: teto de ESPACO, nao de contagem.

    Contar arquivos so limita disco quando eles tem tamanho parecido. As copias
    do banco eram de 7 MB em junho e de 107 MB em julho: as mesmas 10 copias que
    a contagem permite passaram a valer mais de 1 GB sem nenhum limite mudar.
    """

    NOW = datetime(2026, 7, 28, 12, 0, 0)
    MB = 1024 * 1024

    def _names(self, count, step=timedelta(hours=1)):
        """`count` backups do banco, do mais novo para o mais velho."""
        return [
            f"traducoes-backup-{_stamp(self.NOW - step * index)}.db"
            for index in range(count)
        ]

    def _select(self, names, sizes_mb, budget_mb, keep_minimum=3, **kwargs):
        sizes = {name: mb * self.MB for name, mb in zip(names, sizes_mb)}
        return select_backups_to_delete(
            names,
            keep_count=None,
            max_age_days=None,
            keep_minimum=keep_minimum,
            now=self.NOW,
            max_total_bytes=budget_mb * self.MB,
            sizes=sizes,
            **kwargs,
        )

    def test_nothing_is_dropped_below_the_budget(self):
        names = self._names(4)
        self.assertEqual(self._select(names, [107, 104, 9, 7], budget_mb=400), [])

    def test_the_oldest_go_until_it_fits(self):
        """Guarda o maior conjunto de copias RECENTES que cabe no teto."""
        names = self._names(6)
        # 110+110+107 = 327 cabe; somar 104 daria 431 e estoura.
        doomed = self._select(names, [110, 110, 107, 104, 9, 7], budget_mb=400)

        self.assertEqual(sorted(doomed), sorted(names[3:]))

    def test_the_kept_set_really_fits(self):
        names = self._names(6)
        sizes = [110, 110, 107, 104, 9, 7]
        doomed = self._select(names, sizes, budget_mb=400)

        mantidos = [
            tamanho
            for nome, tamanho in zip(names, sizes)
            if nome not in doomed
        ]
        self.assertLessEqual(sum(mantidos), 400, "o que sobrou nao cabe no teto")

    def test_the_floor_wins_over_the_budget(self):
        """Um banco maior que o teto nao pode deixar o usuario sem backup.

        Com copias de 500 MB e teto de 400, a primeira ja estoura. O piso de
        `keep_minimum` garante que as tres mais novas ficam mesmo assim.
        """
        names = self._names(5)
        doomed = self._select(names, [500] * 5, budget_mb=400, keep_minimum=3)

        self.assertEqual(sorted(doomed), sorted(names[3:]))
        self.assertNotIn(names[0], doomed)

    def test_a_single_oversized_backup_survives(self):
        names = self._names(1)
        self.assertEqual(self._select(names, [900], budget_mb=400), [])

    def test_the_new_copy_is_never_dropped_by_the_budget(self):
        names = self._names(5)
        doomed = self._select(
            names, [500] * 5, budget_mb=1, keep_minimum=0, protected=(names[0],)
        )

        self.assertNotIn(names[0], doomed)

    def test_without_a_budget_the_rule_is_off(self):
        names = self._names(6)
        sizes = {name: 500 * self.MB for name in names}
        self.assertEqual(
            select_backups_to_delete(
                names,
                keep_count=None,
                max_age_days=None,
                now=self.NOW,
                max_total_bytes=None,
                sizes=sizes,
            ),
            [],
        )

    def test_without_sizes_the_rule_is_off(self):
        """Sem os tamanhos nao da para decidir — e chutar seria apagar demais."""
        names = self._names(6)
        self.assertEqual(
            select_backups_to_delete(
                names,
                keep_count=None,
                max_age_days=None,
                now=self.NOW,
                max_total_bytes=1,
                sizes=None,
            ),
            [],
        )

    def test_count_and_budget_compose(self):
        names = self._names(6)
        sizes = {name: 50 * self.MB for name in names}
        doomed = select_backups_to_delete(
            names,
            keep_count=4,
            max_age_days=None,
            keep_minimum=0,
            now=self.NOW,
            max_total_bytes=120 * self.MB,
            sizes=sizes,
        )

        # A contagem tira as duas mais velhas; o teto (120 MB = 2 copias de 50
        # cabem, a terceira estoura) tira mais uma.
        self.assertEqual(sorted(doomed), sorted(names[2:]))


class DatabaseBackupBudgetOnDiskTests(unittest.TestCase):
    """`prune_database_backups` medindo arquivos de verdade."""

    NOW = datetime(2026, 7, 28, 12, 0, 0)

    def _seed(self, directory, name, size_bytes):
        path = Path(directory) / name
        path.write_bytes(b"\0" * size_bytes)
        return path

    def test_the_budget_frees_space_and_keeps_the_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivos = [
                self._seed(
                    tmp,
                    f"traducoes-backup-{_stamp(self.NOW - timedelta(hours=i))}.db",
                    200_000,
                )
                for i in range(6)
            ]

            removidos = prune_database_backups(
                tmp,
                "traducoes",
                keep_count=None,
                max_age_days=None,
                keep_minimum=0,
                now=self.NOW,
                max_total_bytes=500_000,   # cabem duas de 200 KB; a terceira estoura
            )

            self.assertEqual(len(removidos), 4)
            self.assertTrue(all(p.exists() for p in arquivos[:2]))
            self.assertFalse(any(p.exists() for p in arquivos[2:]))

    def test_the_glossary_family_is_not_measured_or_touched(self):
        """O teto e so do banco: o glossario continua so na contagem."""
        with tempfile.TemporaryDirectory() as tmp:
            glossario_backups = [
                self._seed(
                    tmp,
                    f"Substituicoes-{_stamp(self.NOW - timedelta(hours=i))}.txt",
                    400_000,
                )
                for i in range(5)
            ]
            banco = [
                self._seed(
                    tmp,
                    f"traducoes-backup-{_stamp(self.NOW - timedelta(hours=i))}.db",
                    400_000,
                )
                for i in range(5)
            ]

            prune_database_backups(
                tmp,
                "traducoes",
                keep_count=None,
                max_age_days=None,
                keep_minimum=0,
                now=self.NOW,
                max_total_bytes=500_000,
            )

            self.assertTrue(
                all(p.exists() for p in glossario_backups),
                "a limpeza do banco nao pode tocar os backups do glossario",
            )
            self.assertEqual(sum(1 for p in banco if p.exists()), 1)

    def test_the_default_budget_is_applied(self):
        """Sem passar `max_total_bytes`, o teto do config tem de valer.

        A primeira versao deste teste so conferia que a constante era positiva e
        que uma pasta vazia nao removia nada — e passava igual com a producao
        certa e com o `setdefault` do teto REMOVIDO. Um teste que passa dos dois
        jeitos nao protege nada.

        O que faltava era sair do valor padrao: encher 400 MB de arquivo e
        inviavel, entao o teto e que desce ate o cenario.
        """
        with tempfile.TemporaryDirectory() as tmp:
            arquivos = [
                self._seed(
                    tmp,
                    f"traducoes-backup-{_stamp(self.NOW - timedelta(hours=i))}.db",
                    200_000,
                )
                for i in range(5)
            ]

            anterior = backup_retention.DATABASE_BACKUP_MAX_TOTAL_MB
            backup_retention.DATABASE_BACKUP_MAX_TOTAL_MB = 500_000 / (1024 * 1024)
            self.addCleanup(
                setattr,
                backup_retention,
                "DATABASE_BACKUP_MAX_TOTAL_MB",
                anterior,
            )

            removidos = backup_retention.prune_database_backups(
                tmp,
                "traducoes",
                keep_count=None,
                max_age_days=None,
                keep_minimum=0,
                now=self.NOW,
            )

            self.assertEqual(len(removidos), 3, "o teto padrao nao foi aplicado")
            self.assertTrue(all(p.exists() for p in arquivos[:2]))


# PGN com tudo o que a normalizacao NAO pode tocar: variantes aninhadas,
# comentarios contendo nomes que o dicionario corrigiria numa tag, NAGs,
# avaliacoes e uma tag fora da lista das cinco suportadas.
PGN_COMPLETO = (
    '[Event "WCh"]\n'
    '[Site "Londres"]\n'
    '[Round "1.0"]\n'
    '[White "GM Aberg, Anton"]\n'
    '[Black "J. S. Speelman"]\n'
    '[Result "1-0"]\n'
    '[ECO "B76"]\n'
    '[Annotator "GM Aberg, Anton"]\n'
    '\n'
    '1. e4 c5 {GM Aberg, Anton comenta aqui} 2. Nf3 d6 $1 3. d4 cxd4\n'
    '4. Nxd4 Nf6 (4... g6 5. Nc3 {Londres seria trocada se fosse tag} Bg7\n'
    '(5... a6 6. Be3 $14) 6. Be3) 5. Nc3 g6 $6 {J. S. Speelman aqui tambem}\n'
    '6. Be3 Bg7 1-0\n'
)

def _movetext(texto):
    """So as linhas de lance: tudo o que nao e cabecalho nem linha em branco."""
    return [
        linha
        for linha in texto.splitlines()
        if linha.strip() and not linha.lstrip().startswith("[")
    ]


def _tags(texto):
    return dict(
        re.findall(r'^\[(\w+)\s+"(.*)"\]', texto, flags=re.MULTILINE)
    )


class SupportedTagsSingleSourceTests(unittest.TestCase):
    """A lista de tags corrigidas tem de existir em UM lugar so.

    `SUPPORTED_TAGS` diz em que secao do spelling.ssp cada tag procura, e
    `PGN_TAG_RE` decide que linhas sao candidatas. Enquanto a lista estava
    escrita nos dois, divergir falhava em silencio e em duas direcoes opostas:

    - so no dict: o regex nunca casava a linha, e a tag nova simplesmente nao
      era corrigida — sem erro, sem aviso;
    - so no regex: `SUPPORTED_TAGS[tag_name]` levantava `KeyError` e derrubava
      a normalizacao de qualquer PGN que tivesse aquela tag.

    Este teste falha nos dois casos, porque compara o que o regex ACEITA com o
    que o dict declara, em vez de conferir o texto do padrao.
    """

    OUTRAS_TAGS = [
        "Annotator",
        "Result",
        "ECO",
        "WhiteElo",
        "BlackElo",
        "Date",
        "TimeControl",
        "Opening",
    ]

    def _casa(self, tag):
        return bool(PGN_TAG_RE.match(f'[{tag} "valor"]'))

    def test_the_regex_accepts_exactly_the_declared_tags(self):
        aceitas = {tag for tag in SUPPORTED_TAGS if self._casa(tag)}
        self.assertEqual(
            aceitas,
            set(SUPPORTED_TAGS),
            "ha tag declarada em SUPPORTED_TAGS que o regex nao reconhece",
        )

    def test_the_regex_accepts_nothing_else(self):
        for tag in self.OUTRAS_TAGS:
            with self.subTest(tag=tag):
                self.assertNotIn(tag, SUPPORTED_TAGS)
                self.assertFalse(
                    self._casa(tag),
                    f"o regex aceita {tag!r}, que nao esta em SUPPORTED_TAGS — "
                    "isso vira KeyError na normalizacao",
                )

    def test_every_declared_tag_has_a_usable_section(self):
        """A secao apontada tem de ser uma das que o spelling.ssp define."""
        self.assertEqual(
            {secao for secao in SUPPORTED_TAGS.values()} - {"PLAYER", "SITE", "EVENT", "ROUND"},
            set(),
        )


class NormalizePgnMetadataPathTests(unittest.TestCase):
    """`normalize_pgn_metadata_path`: o ponto de entrada do "Normalizar PGN".

    Era a maior lacuna de cobertura do pacote depois do `background_task`: a
    funcao inteira (45 linhas) sem um unico teste, embora seja o que o botao
    chama. Os testes que existiam paravam uma camada abaixo, no conteudo e no
    arquivo unico.
    """

    def _spelling_file(self, directory):
        """Um `spelling.ssp` de verdade, para exercitar a carga do arquivo."""
        path = Path(directory) / "spelling.ssp"
        path.write_text(
            '@PLAYER "., -_*"\n'
            '%Prefix "GM " ""\n'
            "Aaberg, Anton\n"
            "  = Aberg, Anton\n"
            "Speelman, Jonathan S\n"
            "  = J. S. Speelman\n"
            '@SITE "., -_()"\n'
            "London\n"
            "  = Londres\n"
            '@EVENT ",. -_"\n'
            "World Championship\n"
            "  = WCh\n"
            '@ROUND ""\n'
            "1\n"
            "  = 1.0\n",
            encoding="utf-8",
        )
        return str(path)

    def _write(self, directory, nome, conteudo=PGN_COMPLETO):
        path = Path(directory) / nome
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(conteudo, encoding="utf-8")
        return path

    # ---------------- garantia N1 ----------------

    def test_only_the_five_tags_change(self):
        """Garantia N1, no nivel do arquivo gerado."""
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
            antes, depois = _tags(PGN_COMPLETO), _tags(saida)

            self.assertEqual(
                {t for t in antes if antes[t] != depois[t]},
                {"Event", "Site", "Round", "White", "Black"},
            )
            self.assertEqual(depois["Result"], "1-0")
            self.assertEqual(depois["ECO"], "B76")
            self.assertEqual(
                depois["Annotator"],
                "GM Aberg, Anton",
                "Annotator nao esta entre as tags suportadas",
            )

    def test_moves_variations_and_comments_are_byte_identical(self):
        """A outra metade da N1: nada abaixo do cabecalho pode mudar.

        O PGN de teste tem os mesmos nomes DENTRO de comentarios e uma variante
        aninhada citando "Londres" — se a normalizacao escapasse do cabecalho,
        e ali que apareceria.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
            self.assertEqual(_movetext(saida), _movetext(PGN_COMPLETO))
            self.assertIn("{GM Aberg, Anton comenta aqui}", saida)
            self.assertIn("{Londres seria trocada se fosse tag}", saida)
            self.assertIn("(5... a6 6. Be3 $14)", saida)
            self.assertIn("$1", saida)
            self.assertIn("$6", saida)

    def test_the_original_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            antes = pgn.read_bytes()

            normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(pgn.read_bytes(), antes)

    # ---------------- orquestracao ----------------

    def test_a_single_file_is_counted_and_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = self._write(tmp, "jogo.pgn")
            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["files"], 1)
            self.assertEqual(stats["changed_files"], 1)
            self.assertEqual(stats["unchanged_files"], 0)
            self.assertEqual(stats["changes"], 5)
            self.assertEqual(len(stats["outputs"]), 1)
            self.assertTrue(stats["outputs"][0].endswith("-NORM.pgn"))

    def test_a_file_without_corrections_produces_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            limpo = '[White "Nome Desconhecido"]\n\n1. e4 e5 1-0\n'
            pgn = self._write(tmp, "limpo.pgn", limpo)

            stats = normalize_pgn_metadata_path(
                str(pgn), spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["changed_files"], 0)
            self.assertEqual(stats["unchanged_files"], 1)
            self.assertEqual(stats["outputs"], [])
            self.assertEqual(list(Path(tmp).glob("*-NORM.pgn")), [])

    def test_a_directory_processes_every_pgn(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a.pgn")
            self._write(tmp, "b.pgn")
            spelling = self._spelling_file(tmp)

            stats = normalize_pgn_metadata_path(tmp, spelling_path=spelling)

            self.assertEqual(stats["files"], 2)
            self.assertEqual(stats["changed_files"], 2)
            self.assertEqual(len(stats["outputs"]), 2)

    def test_subdirectories_obey_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "raiz.pgn")
            self._write(tmp, os.path.join("sub", "dentro.pgn"))
            spelling = self._spelling_file(tmp)

            raso = normalize_pgn_metadata_path(
                tmp, process_subdirs=False, spelling_path=spelling
            )
            fundo = normalize_pgn_metadata_path(
                tmp, process_subdirs=True, spelling_path=spelling
            )

            self.assertEqual(raso["files"], 1)
            self.assertEqual(fundo["files"], 2)

    def test_already_normalized_files_are_skipped(self):
        """Sem isso, reprocessar uma pasta geraria `-NORM-NORM`, e assim por diante."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            self._write(tmp, "jogo-NORM.pgn")
            spelling = self._spelling_file(tmp)

            stats = normalize_pgn_metadata_path(tmp, spelling_path=spelling)

            self.assertEqual(stats["files"], 1)
            self.assertEqual(stats["skipped_normalized"], 1)

    def test_a_missing_dictionary_fails_loudly(self):
        """Sem o dicionario nao ha o que corrigir — e seguir calado
        produziria uma copia identica com cara de "normalizada".

        A mensagem faz parte do que se exige, e nao e preciosismo: sem a guarda
        explicita o `parse_spelling_file` levanta `FileNotFoundError` do mesmo
        jeito, ao tentar abrir o arquivo. Conferir so o TIPO deixa o teste
        passar com a guarda removida — foi o que aconteceu na primeira versao.
        O que distingue os dois casos e o texto: um nomeia o `spelling.ssp` e o
        outro e o erro cru do `open()`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            ausente = str(Path(tmp) / "nao-existe.ssp")

            with self.assertRaises(FileNotFoundError) as capturado:
                normalize_pgn_metadata_path(tmp, spelling_path=ausente)

            self.assertIn("spelling.ssp nao encontrado", str(capturado.exception))
            self.assertIn(ausente, str(capturado.exception))

    def test_progress_goes_from_zero_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            for nome in ("a.pgn", "b.pgn", "c.pgn", "d.pgn"):
                self._write(tmp, nome)
            avancos = []

            normalize_pgn_metadata_path(
                tmp,
                spelling_path=self._spelling_file(tmp),
                progress_callback=avancos.append,
            )

            self.assertEqual(len(avancos), 4)
            self.assertEqual(avancos, sorted(avancos), "o progresso nao pode voltar")
            self.assertAlmostEqual(avancos[-1], 1.0)

    def test_an_empty_folder_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = normalize_pgn_metadata_path(
                tmp, spelling_path=self._spelling_file(tmp)
            )

            self.assertEqual(stats["files"], 0)
            self.assertEqual(stats["outputs"], [])

    def test_the_log_names_each_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "jogo.pgn")
            self._write(tmp, "limpo.pgn", '[White "Nome Desconhecido"]\n\n1. e4 1-0\n')
            linhas = []

            normalize_pgn_metadata_path(
                tmp,
                spelling_path=self._spelling_file(tmp),
                log_message=linhas.append,
            )

            texto = "\n".join(linhas)
            self.assertIn("jogo.pgn", texto)
            self.assertIn("limpo.pgn", texto)
            self.assertIn("sem alteracoes", texto)


class ApplyAutomaticRulesFlowTests(unittest.TestCase):
    """O caminho completo de "Aplicar automaticas".

    So o ramo de CANCELAMENTO tinha teste. O fluxo principal — analisar,
    confirmar, aplicar, relatar — era o maior bloco sem cobertura de
    `db_tools` (56 linhas), justamente na operacao em que os itens 2.7 e 2.11
    mais mexeram.

    A operacao tem quatro saidas distintas e cada uma decide coisas diferentes:
    o que o usuario ve, o que vai para `on_finish` e se o banco e tocado.
    """

    def _semear(self, db_path, linhas=6):
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        for indice in range(linhas):
            # Metade casa com a regra, metade nao: separa "varreu" de "alterou".
            texto = "A rainha avanca" if indice % 2 == 0 else "O bispo avanca"
            save_translation(cursor, f"orig {indice}", texto, "pt")
        conn.commit()
        conn.close()
        return linhas

    def _traducoes(self, db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return sorted(
                linha[0]
                for linha in conn.execute(
                    "SELECT translated_comment FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()

    def _app(self, db_path, cache=None):
        return types.SimpleNamespace(
            output_db=str(db_path),
            translation_cache={} if cache is None else cache,
            root=None,
        )

    def _dialogos(self, confirmar=True):
        vistos = []
        self.addCleanup(setattr, db_tools, "messagebox", db_tools.messagebox)
        db_tools.messagebox = types.SimpleNamespace(
            askyesno=lambda t, m, **_kw: (vistos.append(("askyesno", t, m)), confirmar)[1],
            showinfo=lambda t, m, **_kw: vistos.append(("info", t, m)),
            showerror=lambda t, m, **_kw: vistos.append(("error", t, m)),
        )
        return vistos

    def _regras(self, regras=(("rainha", "dama"),)):
        self.addCleanup(
            setattr, db_tools, "load_automatic_substitutions",
            db_tools.load_automatic_substitutions,
        )
        db_tools.load_automatic_substitutions = lambda: list(regras)

    def _rodar(self, db_path, **kwargs):
        SynchronousProgress().install(self, db_tools)
        recebidos = []
        db_tools.apply_automatic_rules_to_database(
            self._app(db_path, kwargs.pop("cache", None)),
            on_finish=recebidos.append,
            **kwargs,
        )
        return recebidos

    # ------------------------------------------------ o caminho feliz

    def test_confirming_rewrites_the_matching_rows_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._regras()
            vistos = self._dialogos(confirmar=True)

            recebidos = self._rodar(db_path)

            traducoes = self._traducoes(db_path)
            self.assertEqual(traducoes.count("A dama avanca"), 3)
            self.assertEqual(
                traducoes.count("O bispo avanca"), 3, "linha sem regra foi mexida"
            )
            self.assertNotIn("A rainha avanca", traducoes)

            self.assertEqual(len(recebidos), 1)
            self.assertIsNotNone(recebidos[0], "o resultado devia chegar em on_finish")
            self.assertEqual(recebidos[0]["changed"], 3)

            self.assertEqual(
                [tipo for tipo, _t, _m in vistos],
                ["askyesno", "info"],
                "esperava confirmacao e depois o resumo",
            )

    def test_the_stale_memory_cache_is_dropped(self):
        """Sem isso o worker reusaria a traducao ANTERIOR as regras.

        `translation_cache` guarda `{original: traduzido}` da execucao. Depois
        de reescrever as traducoes no banco, o que esta em memoria e a versao
        velha — e o cache tem precedencia sobre o banco.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._regras()
            self._dialogos(confirmar=True)
            cache = {"orig 0": "A rainha avanca"}

            self._rodar(db_path, cache=cache)

            self.assertEqual(cache, {}, "o cache em memoria ficou desatualizado")

    # ------------------------------------------------ as saidas sem escrita

    def test_declining_the_confirmation_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            antes = self._traducoes(db_path)
            self._regras()
            vistos = self._dialogos(confirmar=False)

            recebidos = self._rodar(db_path)

            self.assertEqual(self._traducoes(db_path), antes)
            self.assertEqual(recebidos, [None])
            self.assertEqual([tipo for tipo, _t, _m in vistos], ["askyesno"])

    def test_nothing_to_change_reports_the_scope_and_skips_the_question(self):
        """Aqui `on_finish` recebe a PREVIA, e nao `None`.

        A assimetria e proposital: "nada a fazer" e um resultado, e nao uma
        desistencia — quem chamou pode querer os numeros da varredura.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._regras([("inexistente", "outra")])
            vistos = self._dialogos()

            recebidos = self._rodar(db_path)

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["info"])
            self.assertEqual(len(recebidos), 1)
            self.assertIsNotNone(recebidos[0])
            self.assertEqual(recebidos[0]["changed"], 0)
            self.assertGreater(recebidos[0]["scanned"], 0)

    def test_without_automatic_rules_it_stops_before_touching_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._regras([])
            vistos = self._dialogos()

            progresso = SynchronousProgress()
            progresso.install(self, db_tools)
            recebidos = []
            db_tools.apply_automatic_rules_to_database(
                self._app(db_path), on_finish=recebidos.append
            )

            self.assertEqual(recebidos, [None])
            self.assertEqual([tipo for tipo, _t, _m in vistos], ["info"])
            self.assertIn("Nenhuma regra automatica", vistos[0][2])
            self.assertEqual(
                progresso.chamadas, [], "nem chegou a abrir a barra de progresso"
            )

    def test_a_broken_glossary_becomes_an_error_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            antes = self._traducoes(db_path)
            vistos = self._dialogos()

            self.addCleanup(
                setattr, db_tools, "load_automatic_substitutions",
                db_tools.load_automatic_substitutions,
            )

            def explode():
                raise ValueError("Substituicoes.txt malformado")

            db_tools.load_automatic_substitutions = explode

            recebidos = []
            db_tools.apply_automatic_rules_to_database(
                self._app(db_path), on_finish=recebidos.append
            )

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["error"])
            self.assertIn("malformado", vistos[0][2])
            self.assertEqual(recebidos, [None])
            self.assertEqual(self._traducoes(db_path), antes)

    def test_a_failure_while_writing_is_reported_and_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            self._regras()
            vistos = self._dialogos(confirmar=True)

            self.addCleanup(
                setattr, db_tools, "apply_database_automatic_rules",
                db_tools.apply_database_automatic_rules,
            )

            def falha(*_a, **_kw):
                raise sqlite3.OperationalError("database is locked")

            db_tools.apply_database_automatic_rules = falha

            recebidos = self._rodar(db_path)

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["askyesno", "error"])
            self.assertEqual(recebidos, [None])

    # ------------------------------------------------ escopo

    def test_the_language_scope_reaches_the_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._semear(db_path)
            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "outro idioma", "A rainha avanca", "en")
            conn.commit()
            conn.close()

            self._regras()
            self._dialogos(confirmar=True)

            self._rodar(db_path, target_language="pt")

            conn = sqlite3.connect(str(db_path))
            try:
                em_ingles = conn.execute(
                    "SELECT translated_comment FROM comments WHERE target_language = 'en'"
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(
                em_ingles, "A rainha avanca", "o escopo de idioma nao foi respeitado"
            )


class ShowDatabaseStatsTests(unittest.TestCase):
    """O botao "Estatisticas". A funcao inteira estava sem teste.

    E so leitura, mas e um relatorio: numero errado aqui nao quebra nada e
    engana em silencio. O que se exige e que os totais batam com o banco e que
    a contagem por idioma nao se misture.
    """

    def _montar(self, db_path):
        """Tres pares de idiomas, com o aviso QA num deles so.

        A origem de cada linha e escolhida para que o relatorio SEPARE os pares:
        se as tres traducoes em pt tivessem a mesma origem, agrupar pelo par e
        agrupar so pelo destino dariam o mesmo texto, e o teste passaria
        igualmente com as duas producoes.
        """
        conn = initialize_database(str(db_path))
        cursor = conn.cursor()
        save_translation(cursor, "orig pt 1", "traducao boa", "pt", "en")
        save_translation(cursor, "orig pt 2", "outra traducao boa", "pt", "en")
        # Traducao identica ao original => aviso de qualidade. Origem nao
        # informada, que e o par que as 201 mil linhas do banco real herdaram.
        save_translation(cursor, "repetido igual", "repetido igual", "pt")
        save_translation(cursor, "orig en 1", "english one", "en")
        save_translation(cursor, "orig en 2", "english two", "en")
        cursor.execute(
            "UPDATE comments SET verified = 1 WHERE original_comment = 'orig pt 1'"
        )
        conn.commit()
        conn.close()

    def _mostrar(self, db_path):
        vistos = []
        self.addCleanup(setattr, db_tools, "messagebox", db_tools.messagebox)
        db_tools.messagebox = types.SimpleNamespace(
            showinfo=lambda t, m, **_kw: vistos.append(("info", t, m)),
            showerror=lambda t, m, **_kw: vistos.append(("error", t, m)),
        )
        db_tools.show_db_stats(types.SimpleNamespace(output_db=str(db_path)))
        return vistos

    def test_the_totals_match_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            vistos = self._mostrar(db_path)

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["info"])
            msg = vistos[0][2]
            self.assertIn("Total de traducoes armazenadas: 5", msg)
            self.assertIn("Verificadas: 1", msg)
            self.assertIn("Pendentes: 4", msg)

    def test_each_language_pair_is_counted_on_its_own(self):
        """Duas traducoes em pt vindas do ingles e uma vinda de origem nao dita.

        Somadas pelo destino seriam "pt: 3"; o relatorio precisa mostrar as duas
        linhas separadas, senao o par que o usuario escolheu declarar desaparece
        no total.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            msg = self._mostrar(db_path)[0][2]

            self.assertIn("- Inglês -> pt: 2 | verificadas: 1 | pendentes: 1", msg)
            self.assertIn("- Não informado -> pt: 1 | verificadas: 0 | pendentes: 1", msg)
            self.assertIn("- Não informado -> en: 2 | verificadas: 0 | pendentes: 2", msg)
            self.assertNotIn("- pt: 3", msg)

    def test_the_quality_warning_is_counted_in_the_right_pair(self):
        """O aviso e da linha sem origem declarada.

        Nem o par `Inglês -> pt` (mesmo destino, outra origem) nem
        `Não informado -> en` (mesma origem, outro destino) podem herda-lo — e
        sao justamente esses dois que um agrupamento pela metade confundiria.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            msg = self._mostrar(db_path)[0][2]

            def linha(prefixo):
                return next(l for l in msg.splitlines() if l.strip().startswith(prefixo))

            self.assertTrue(
                linha("- Não informado -> pt:").rstrip().endswith("QA: 1"),
                linha("- Não informado -> pt:"),
            )
            self.assertTrue(
                linha("- Inglês -> pt:").rstrip().endswith("QA: 0"),
                linha("- Inglês -> pt:"),
            )
            self.assertTrue(
                linha("- Não informado -> en:").rstrip().endswith("QA: 0"),
                linha("- Não informado -> en:"),
            )

    def test_an_empty_database_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vazio.db"
            initialize_database(str(db_path)).close()

            vistos = self._mostrar(db_path)

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["info"])
            self.assertIn("Total de traducoes armazenadas: 0", vistos[0][2])

    def test_a_broken_database_becomes_an_error_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            quebrado = Path(tmp) / "nao-e-banco.db"
            quebrado.write_bytes(b"isto nao e um banco sqlite" * 100)

            vistos = self._mostrar(quebrado)

            self.assertEqual([tipo for tipo, _t, _m in vistos], ["error"])
            self.assertIn("Nao foi possivel acessar", vistos[0][2])

            # E o arquivo NAO pode ficar preso: ver o teste abaixo.
            quebrado.unlink()

    def test_a_broken_database_does_not_stay_locked(self):
        """Encontrado escrevendo o teste acima, que nao conseguia apagar o tmp.

        `initialize_database` abre a conexao e so depois roda o PRAGMA. Num
        banco corrompido o PRAGMA levanta, a excecao sobe sem a conexao nunca
        ter sido devolvida — quem chamou nao tem o que fechar — e o arquivo fica
        preso ate o coletor de lixo passar.

        O efeito para o usuario e o pior possivel: o programa avisa que nao
        conseguiu ler o banco e, ao mesmo tempo, impede que ele seja substituido
        pelo backup. Atinge todo chamador de `initialize_database`, e nao so
        este.
        """
        with tempfile.TemporaryDirectory() as tmp:
            quebrado = Path(tmp) / "nao-e-banco.db"
            quebrado.write_bytes(b"isto nao e um banco sqlite" * 100)

            with self.assertRaises(sqlite3.DatabaseError):
                initialize_database(str(quebrado))

            # Sem a correcao isto levanta PermissionError no Windows.
            quebrado.unlink()
            self.assertFalse(quebrado.exists())

    def test_the_connection_is_released(self):
        """O `finally` fecha a conexao mesmo no caminho de sucesso.

        Ficar com ela aberta prenderia o banco enquanto a janela vivesse — e o
        editor e o worker disputam o mesmo arquivo (garantia C3).
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)
            self._mostrar(db_path)

            # Se a leitura tivesse deixado conexao aberta, esta escrita
            # exclusiva falharia.
            conn = sqlite3.connect(str(db_path), timeout=0.5)
            try:
                conn.execute("BEGIN EXCLUSIVE")
                conn.execute(
                    "UPDATE comments SET verified = 1 WHERE target_language = 'pt'"
                )
                conn.commit()
            finally:
                conn.close()


# ===========================================================================
# Idioma de origem: schema, migracao, adocao e filtro
# ===========================================================================


def _schema3_database(db_path):
    """Um banco no schema 3 — o que existia antes de a origem entrar na chave.

    Escrito a mao, e nao gerado pelo programa: o ponto do teste e que a migracao
    receba exatamente a tabela antiga, com a UNIQUE antiga e sem a coluna nova.
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_comment TEXT,
            translated_comment TEXT,
            target_language TEXT,
            verified INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            verified_at TEXT,
            quality_warning INTEGER,
            UNIQUE(original_comment, target_language)
        );
        CREATE TABLE comment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            previous_translation TEXT,
            new_translation TEXT,
            previous_verified INTEGER,
            new_verified INTEGER,
            created_at TEXT
        );
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()


class SourceLanguageSchemaTests(unittest.TestCase):
    """A coluna `source_language` e a chave nova da tabela `comments`."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        return Path(sandbox.name) / "cache.db"

    def test_the_same_comment_from_two_languages_is_two_rows(self):
        """O ponto do item: a origem faz parte da identidade da traducao.

        "Nada" em espanhol e "Nada" em portugues sao o mesmo texto e traducoes
        diferentes. Com a chave antiga, a segunda execucao encontrava a linha da
        primeira e devolvia a traducao da outra lingua como se fosse dela.
        """
        conn = initialize_database(str(self.banco()))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        self.assertEqual(save_translation(cur, "Nada", "Nothing", "en", "es"), "inserted")
        self.assertEqual(save_translation(cur, "Nada", "Anything", "en", "pt"), "inserted")
        conn.commit()

        self.assertEqual(
            cur.execute(
                "SELECT source_language, translated_comment FROM comments ORDER BY id"
            ).fetchall(),
            [("es", "Nothing"), ("pt", "Anything")],
        )

    def test_the_same_pair_twice_is_still_one_row(self):
        """A chave nova nao pode virar uma licenca para duplicar."""
        conn = initialize_database(str(self.banco()))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        save_translation(cur, "Nada", "Nothing", "en", "es")
        self.assertEqual(
            save_translation(cur, "Nada", "Outra coisa", "en", "es"), "unchanged"
        )
        conn.commit()

        self.assertEqual(cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 1)

    def test_the_unknown_source_is_an_empty_string_and_not_null(self):
        """Num indice UNIQUE, todo NULL e distinto de qualquer outro.

        Com `NULL` no lugar da string vazia, a chave deixaria de valer para as
        linhas legadas — e a mesma execucao repetida inseriria tudo de novo, sem
        erro nenhum. E o motivo de a coluna ser `NOT NULL DEFAULT ''`.
        """
        conn = initialize_database(str(self.banco()))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        save_translation(cur, "the rook", "a torre", "pt")
        save_translation(cur, "the rook", "outra", "pt")
        conn.commit()

        linhas = cur.execute("SELECT source_language FROM comments").fetchall()
        self.assertEqual(linhas, [(SOURCE_LANGUAGE_UNKNOWN,)])
        self.assertEqual(SOURCE_LANGUAGE_UNKNOWN, "")

    def test_migrating_keeps_the_ids_and_marks_the_source_unknown(self):
        """Os ids sao o que faz o indice FTS sobreviver a reconstrucao.

        `comments_fts` e indexado por `rowid`. Se a copia renumerasse as linhas,
        cada entrada do indice passaria a apontar para o texto de outra linha e a
        busca devolveria resultados errados — sem erro, sem aviso.
        """
        db_path = self.banco()
        _schema3_database(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.executemany(
            "INSERT INTO comments (id, original_comment, translated_comment,"
            " target_language, verified, quality_warning) VALUES (?, ?, ?, ?, ?, 0)",
            [
                (7, "the rook", "a torre", "pt", 1),
                (9, "the bishop", "o bispo", "pt", 0),
            ],
        )
        conn.commit()
        conn.close()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)

        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(
            conn.execute(
                "SELECT id, original_comment, source_language, verified"
                " FROM comments ORDER BY id"
            ).fetchall(),
            [(7, "the rook", "", 1), (9, "the bishop", "", 0)],
        )

    def test_migrating_leaves_the_search_index_pointing_at_the_right_rows(self):
        db_path = self.banco()
        _schema3_database(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.executemany(
            "INSERT INTO comments (id, original_comment, translated_comment,"
            " target_language, verified, quality_warning) VALUES (?, ?, ?, ?, 0, 0)",
            [(3, "the rook", "a torre", "pt"), (11, "the bishop", "o bispo", "pt")],
        )
        conn.commit()
        conn.close()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        if not fts_index_ready(cur):
            self.skipTest("SQLite sem FTS5")

        achados = cur.execute(
            "SELECT id, original_comment FROM comments WHERE id IN"
            f" (SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?)",
            ('"bispo"',),
        ).fetchall()
        self.assertEqual(achados, [(11, "the bishop")])

    def test_migrating_replaces_the_old_unique_constraint(self):
        """Sem trocar a restricao, a linha do espanhol nao caberia na tabela."""
        db_path = self.banco()
        _schema3_database(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO comments (id, original_comment, translated_comment,"
            " target_language, verified, quality_warning) VALUES (1, 'Nada',"
            " 'Nothing', 'en', 0, 0)"
        )
        conn.commit()
        conn.close()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        self.assertEqual(save_translation(cur, "Nada", "Anything", "en", "pt"), "inserted")
        conn.commit()
        self.assertEqual(cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2)


class AdoptUnknownSourceLanguageTests(unittest.TestCase):
    """As 201.607 linhas que o banco real ja tinha nao podem ser pagas de novo.

    Elas ficaram com origem "nao informada" na migracao. Sem a adocao, a primeira
    execucao que declarasse "estes PGN estao em espanhol" nao acharia nenhuma
    delas no cache e mandaria tudo de volta para a API.
    """

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_it_labels_the_rows_of_the_comments_asked_for(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt")
        save_translation(cur, "the bishop", "o bispo", "pt")
        conn.commit()

        adotadas = adopt_unknown_source_language(cur, "pt", "en", ["the rook"])
        conn.commit()

        self.assertEqual(adotadas, 1)
        self.assertEqual(
            cur.execute(
                "SELECT original_comment, source_language FROM comments ORDER BY id"
            ).fetchall(),
            [("the rook", "en"), ("the bishop", "")],
        )

    def test_a_row_that_already_declares_another_source_is_left_alone(self):
        """Adotar so alcanca quem nao tinha idioma nenhum.

        Reetiquetar uma linha que ja diz "veio do espanhol" seria apagar uma
        declaracao do usuario com outra.
        """
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "Nada", "Nothing", "en", "es")
        conn.commit()

        self.assertEqual(adopt_unknown_source_language(cur, "en", "pt", ["Nada"]), 0)
        conn.commit()
        self.assertEqual(
            cur.execute("SELECT source_language FROM comments").fetchall(), [("es",)]
        )

    def test_adopting_into_an_occupied_pair_keeps_both_rows(self):
        """A adocao pode esbarrar na propria chave, e ai ela nao acontece.

        Se ja existe (mesmo comentario, mesma origem, mesmo destino), promover a
        linha sem rotulo criaria uma duplicata. `UPDATE OR IGNORE` deixa as duas
        como estao em vez de derrubar a execucao inteira com um IntegrityError.
        """
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "Nada", "Nothing (antiga)", "en")
        save_translation(cur, "Nada", "Nothing (espanhol)", "en", "es")
        conn.commit()

        adopt_unknown_source_language(cur, "en", "es", ["Nada"])
        conn.commit()

        self.assertEqual(
            sorted(
                cur.execute(
                    "SELECT source_language, translated_comment FROM comments"
                ).fetchall()
            ),
            [("", "Nothing (antiga)"), ("es", "Nothing (espanhol)")],
        )

    def test_detecting_automatically_adopts_nothing(self):
        """Detectar nao e uma declaracao, entao nao ha o que registrar."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt")
        conn.commit()

        self.assertEqual(adopt_unknown_source_language(cur, "pt", "", ["the rook"]), 0)
        self.assertEqual(
            cur.execute("SELECT source_language FROM comments").fetchall(), [("",)]
        )

    def test_it_survives_more_comments_than_sqlite_accepts_as_parameters(self):
        conn = self.banco()
        cur = conn.cursor()
        quantos = database.CACHE_LOOKUP_CHUNK * 2 + 5
        for i in range(quantos):
            save_translation(cur, f"original {i}", f"traducao {i}", "pt")
        conn.commit()

        adotadas = adopt_unknown_source_language(
            cur, "pt", "en", [f"original {i}" for i in range(quantos)]
        )
        conn.commit()

        self.assertEqual(adotadas, quantos)
        self.assertEqual(
            cur.execute(
                "SELECT COUNT(*) FROM comments WHERE source_language = 'en'"
            ).fetchone()[0],
            quantos,
        )


class TranslationCacheByLanguagePairTests(unittest.TestCase):
    """O cache e do PAR, e nao so do destino."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "Nada", "Nothing", "en", "es")
        save_translation(cur, "Nada", "Anything", "en", "pt")
        save_translation(cur, "the rook", "a torre", "pt")
        conn.commit()
        return cur

    def test_each_source_gets_its_own_translation(self):
        cur = self.banco()
        self.assertEqual(
            load_translation_cache(cur, "en", ["Nada"], source_language="es"),
            {"Nada": "Nothing"},
        )
        self.assertEqual(
            load_translation_cache(cur, "en", ["Nada"], source_language="pt"),
            {"Nada": "Anything"},
        )

    def test_a_declared_source_never_reuses_the_unlabelled_row(self):
        """Nao por economia, por correcao.

        A linha sem rotulo pode ter vindo de qualquer lingua. Entrega-la a uma
        execucao que declarou espanhol e exatamente o engano entre linguas que o
        filtro existe para impedir — e a adocao e o caminho legitimo de
        aproveita-la, porque ela passa pela declaracao do usuario.
        """
        cur = self.banco()
        self.assertEqual(
            load_translation_cache(cur, "pt", ["the rook"], source_language="en"), {}
        )
        self.assertEqual(
            load_translation_cache(cur, "pt", ["the rook"]), {"the rook": "a torre"}
        )

    def test_the_full_load_is_restricted_to_the_pair_too(self):
        """O atalho de carregar tudo nao pode ser um jeito de furar o filtro."""
        cur = self.banco()
        self.assertEqual(
            load_translation_cache(cur, "en", source_language="es"), {"Nada": "Nothing"}
        )


class ReviewFilterBySourceLanguageTests(unittest.TestCase):
    """O filtro de origem do editor, na camada de consulta."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        save_translation(cur, "la torre", "a torre", "pt", "es")
        save_translation(cur, "antiga", "traducao antiga", "pt")
        conn.commit()
        return cur

    def originais(self, linhas):
        return sorted(linha[1] for linha in linhas)

    def test_none_means_every_source(self):
        cur = self.banco()
        self.assertEqual(
            self.originais(fetch_review_rows(cur, "pt", source_language=None)),
            ["antiga", "la torre", "the bishop", "the rook"],
        )

    def test_a_language_brings_only_that_pair(self):
        cur = self.banco()
        self.assertEqual(
            self.originais(fetch_review_rows(cur, "pt", source_language="en")),
            ["the bishop", "the rook"],
        )

    def test_the_empty_string_is_a_source_and_not_the_absence_of_a_filter(self):
        """A distincao de que o filtro inteiro depende.

        `None` nao filtra; `""` filtra pelas linhas cuja origem ninguem
        declarou. Tratar os dois como a mesma coisa faria "Nao informado" mostrar
        a tabela toda — e nas 201 mil linhas do banco real isso passaria
        despercebido, porque quase tudo esta nesse balde.
        """
        cur = self.banco()
        self.assertEqual(
            self.originais(fetch_review_rows(cur, "pt", source_language="")),
            ["antiga"],
        )

    def test_the_counts_follow_the_same_filter_as_the_page(self):
        """Senao a lista pagina por um numero que nao e o dela.

        E a mesma armadilha do item 2.8: os dois criterios vivem em consultas
        diferentes e divergir nao quebra nada visivel.
        """
        cur = self.banco()
        for origem, esperado in [(None, 4), ("en", 2), ("es", 1), ("", 1)]:
            with self.subTest(origem=origem):
                resumo = get_review_status_counts(cur, "pt", source_language=origem)
                self.assertEqual(resumo["total"], esperado)
                self.assertEqual(
                    count_review_rows(cur, "pt", source_language=origem), esperado
                )
                self.assertEqual(
                    len(
                        fetch_review_rows_page(
                            cur, "pt", limit=100, offset=0, source_language=origem
                        )
                    ),
                    esperado,
                )

    def test_the_offset_of_a_row_is_within_its_own_filter(self):
        cur = self.banco()
        linhas = fetch_review_rows(cur, "pt", source_language="en")
        segundo = linhas[1][0]
        self.assertEqual(
            get_review_row_offset(cur, "pt", segundo, source_language="en"), 1
        )
        # Com a origem errada a linha simplesmente nao esta na lista.
        self.assertIsNone(get_review_row_offset(cur, "pt", segundo, source_language="es"))

    def test_verifying_exact_matches_stays_inside_the_pair(self):
        """"a torre" existe nas duas origens, com originais diferentes.

        Marcar a do ingles nao pode dar por revisada a do espanhol: sao textos
        que o usuario nem viu, na tela que ele abriu para nao misturar linguas.
        """
        cur = self.banco()
        do_ingles = cur.execute(
            "SELECT id FROM comments WHERE original_comment = 'the rook'"
        ).fetchone()[0]

        set_exact_translation_matches_verified(cur, do_ingles)

        self.assertEqual(
            cur.execute(
                "SELECT original_comment, verified FROM comments"
                " WHERE translated_comment = 'a torre' ORDER BY id"
            ).fetchall(),
            [("the rook", 1), ("la torre", 0)],
        )


class ClearAllTranslationsTests(unittest.TestCase):
    """O "Zerar Traduções", na camada do banco."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        update_translation_by_id(
            cur,
            cur.execute("SELECT id FROM comments ORDER BY id").fetchone()[0],
            "a torre revisada",
        )
        conn.commit()
        return conn

    def test_it_reports_how_many_rows_it_removed(self):
        conn = self.banco()
        self.assertEqual(clear_all_translations(conn), 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 0)

    def test_the_history_goes_with_the_translations(self):
        """Historico de traducoes que nao existem mais nao e historico de nada."""
        conn = self.banco()
        self.assertGreater(
            conn.execute("SELECT COUNT(*) FROM comment_history").fetchone()[0], 0
        )
        clear_all_translations(conn)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM comment_history").fetchone()[0], 0
        )

    def test_the_database_is_usable_right_after(self):
        """Zerar nao pode deixar o banco sem schema: o proximo uso e uma gravacao."""
        conn = self.banco()
        clear_all_translations(conn)

        cur = conn.cursor()
        self.assertEqual(
            save_translation(cur, "novo", "novo traduzido", "pt", "en"), "inserted"
        )
        conn.commit()
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_the_search_index_is_emptied_too(self):
        """Um indice com termos de linhas apagadas devolve o que nao existe."""
        conn = self.banco()
        cur = conn.cursor()
        if not fts_index_ready(cur):
            self.skipTest("SQLite sem FTS5")

        clear_all_translations(conn)

        self.assertEqual(
            conn.execute(
                f"SELECT COUNT(*) FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
                ('"torre"',),
            ).fetchone()[0],
            0,
        )


class TypedConfirmationTests(unittest.TestCase):
    """A regra do dialogo que exige digitar a palavra.

    Pura e separada da janela de proposito: e ela que decide se algo e apagado, e
    testa-la nao pode exigir abrir um `Toplevel`.
    """

    def test_the_word_releases_the_action(self):
        self.assertTrue(confirmation_accepted(CONFIRMATION_WORD))

    def test_case_and_surrounding_space_do_not_matter(self):
        """Quem digitou DELETE decidiu tanto quanto quem digitou delete."""
        for texto in ["DELETE", " delete ", "Delete", "\tdelete\n"]:
            with self.subTest(texto=texto):
                self.assertTrue(confirmation_accepted(texto))

    def test_anything_else_does_not(self):
        for texto in ["", None, "del", "deletes", "apagar", "sim", "s"]:
            with self.subTest(texto=texto):
                self.assertFalse(confirmation_accepted(texto))

    def test_a_yes_never_passes_for_the_word(self):
        """O ponto do dialogo e nao ser um Sim a um clique de distancia."""
        self.assertFalse(confirmation_accepted("sim"))
        self.assertFalse(confirmation_accepted("yes"))
        self.assertFalse(confirmation_accepted("ok"))

# ===========================================================================
# O idioma de origem no caminho da traducao
# ===========================================================================


class WorkerSourceLanguageTests(unittest.TestCase):
    """O que a execucao faz com o idioma que o usuario declarou."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "cache.db"

    def escreve_pgn(self, nome="game.pgn", comentario="El alfil domina"):
        pgn = self.base / nome
        pgn.write_text(
            f'[Event "Test"]\n\n1. e4 {{{comentario}}}\n', encoding="utf-8"
        )
        return pgn

    def falso_translate(self, resposta="O bispo domina"):
        """Captura o que chegou a camada de rede, sem tocar nela."""
        recebidos = []

        def falso(text, target_language, *_a, **kwargs):
            recebidos.append(
                {
                    "text": text,
                    "target_language": target_language,
                    "source_language": kwargs.get("source_language"),
                }
            )
            return resposta

        original = translation_worker.translate_text
        translation_worker.translate_text = falso
        self.addCleanup(setattr, translation_worker, "translate_text", original)
        return recebidos

    def linhas(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                "SELECT original_comment, translated_comment, source_language,"
                " target_language FROM comments ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    def test_the_declared_source_reaches_the_api(self):
        """`sl=auto` faz o endpoint adivinhar a partir de um comentario curto."""
        recebidos = self.falso_translate()
        pgn = self.escreve_pgn()

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )

        self.assertEqual([r["source_language"] for r in recebidos], ["es"])

    def test_detecting_automatically_still_sends_nothing(self):
        """O padrao continua sendo o comportamento que o programa sempre teve."""
        recebidos = self.falso_translate()
        pgn = self.escreve_pgn()

        translation_worker.run_translation(FakeApp(self.db_path), str(pgn), "pt", False)

        self.assertEqual([r["source_language"] for r in recebidos], [""])

    def test_the_translation_is_stored_under_the_declared_pair(self):
        self.falso_translate()
        pgn = self.escreve_pgn()

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )

        self.assertEqual(
            self.linhas(), [("El alfil domina", "O bispo domina", "es", "pt")]
        )

    def test_the_same_comment_in_two_source_languages_is_translated_twice(self):
        """A prova de que a chave nova vale ponta a ponta.

        O mesmo texto vindo de dois idiomas rende duas chamadas de API e duas
        linhas. Com a chave antiga, a segunda execucao acharia a primeira no
        cache e escreveria a traducao do espanhol num PGN italiano.
        """
        recebidos = self.falso_translate()
        pgn = self.escreve_pgn(comentario="Nada")

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "en", False, source_language="es"
        )
        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "en", False, source_language="it"
        )

        self.assertEqual([r["source_language"] for r in recebidos], ["es", "it"])
        self.assertEqual(
            [linha[2] for linha in self.linhas()], ["es", "it"]
        )

    def test_the_cache_already_in_the_database_is_adopted_and_not_paid_again(self):
        """O que impede a mudanca de chave de cobrar as 201.607 linhas de novo.

        As traducoes gravadas antes desta versao ficaram sem idioma de origem. A
        primeira execucao que declara um idioma as adota — nenhuma chamada de
        API — em vez de encontrar o cache vazio e mandar tudo para a rede.
        """
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "El alfil domina", "O bispo domina", "pt")
        conn.commit()
        conn.close()

        recebidos = self.falso_translate()
        pgn = self.escreve_pgn()
        app = FakeApp(self.db_path)

        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="es"
        )

        self.assertEqual(recebidos, [], "a API foi chamada para algo que ja estava no banco")
        self.assertEqual(
            self.linhas(), [("El alfil domina", "O bispo domina", "es", "pt")]
        )
        self.assertIn("marcadas como 'es'", "\n".join(app.logs))

    def test_adopting_does_not_touch_a_row_of_another_declared_source(self):
        """Adotar so alcanca quem nao tinha idioma nenhum — nem no worker."""
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "El alfil domina", "O bispo domina", "pt", "it")
        conn.commit()
        conn.close()

        recebidos = self.falso_translate("O alfil domina")
        pgn = self.escreve_pgn()

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )

        self.assertEqual(len(recebidos), 1, "a linha do italiano foi reaproveitada")
        self.assertEqual(
            sorted(self.linhas()),
            [
                ("El alfil domina", "O alfil domina", "es", "pt"),
                ("El alfil domina", "O bispo domina", "it", "pt"),
            ],
        )

    def test_a_failed_run_records_the_pair_it_was_translating(self):
        original = translation_worker.translate_text
        translation_worker.translate_text = lambda *_a, **_k: None
        self.addCleanup(setattr, translation_worker, "translate_text", original)

        pgn = self.escreve_pgn()
        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )

        registro = failed_runs.load_failed_run()
        self.assertIsNotNone(registro)
        self.assertEqual(registro["source_language"], "es")
        self.assertEqual(registro["target_language"], "pt")


class FailedRunSourceLanguageTests(unittest.TestCase):
    """O registro de falhas guarda o par, e le registros antigos sem ele."""

    def test_the_record_carries_the_source_language(self):
        registro = failed_runs.build_failed_run_record(
            "pt", ["/a/b.pgn"], 3, source_language="es"
        )
        self.assertEqual(registro["source_language"], "es")

    def test_a_record_from_an_older_version_is_still_usable(self):
        """Descartar uma lista de falhas boa por causa de um campo novo seria
        transformar uma compatibilidade em perda de trabalho."""
        antigo = {
            "target_language": "pt",
            "files": ["/a/b.pgn"],
            "failed_count": 2,
            "when": "2026-07-27T10:00:00",
        }
        normalizado = failed_runs.normalize_failed_run_record(antigo)
        self.assertIsNotNone(normalizado)
        self.assertEqual(normalizado["source_language"], "")

    def test_the_description_names_the_pair(self):
        registro = failed_runs.build_failed_run_record(
            "pt", ["/a/b.pgn"], 3, source_language="es"
        )
        self.assertIn("es -> pt", failed_runs.describe_failed_run(registro, lambda _p: True))


# ===========================================================================
# Zerar o banco de traducoes e zerar o glossario
# ===========================================================================


class ResetToolsTestCase(unittest.TestCase):
    """Base das duas ferramentas destrutivas.

    O `ask_typed_confirmation` e substituido por uma funcao que registra o que
    foi perguntado e devolve o que o teste mandar. A regra que ele aplica ja tem
    teste proprio (`TypedConfirmationTests`); o que interessa aqui e o que
    acontece ANTES e DEPOIS da resposta.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.dialogos = []
        original_messagebox = db_tools.messagebox
        db_tools.messagebox = types.SimpleNamespace(
            showinfo=lambda t, m, **_k: self.dialogos.append(("info", t, m)),
            showerror=lambda t, m, **_k: self.dialogos.append(("error", t, m)),
            askyesno=lambda t, m, **_k: True,
        )
        self.addCleanup(setattr, db_tools, "messagebox", original_messagebox)

        self.perguntas = []
        self.resposta = True
        original_ask = db_tools.ask_typed_confirmation
        db_tools.ask_typed_confirmation = self.perguntar
        self.addCleanup(setattr, db_tools, "ask_typed_confirmation", original_ask)

        # As tarefas de fundo rodam na hora: o que esta sob teste e a
        # orquestracao, e a thread ja tem teste proprio em test_background_task.
        original_run = db_tools.run_with_progress
        db_tools.run_with_progress = self.rodar_sincrono
        self.addCleanup(setattr, db_tools, "run_with_progress", original_run)

    def perguntar(self, _parent, titulo, mensagem, **_kwargs):
        self.perguntas.append((titulo, mensagem))
        return self.resposta

    def rodar_sincrono(self, _parent, _titulo, work, on_success=None, **_kwargs):
        resultado = work(BackgroundTask())
        if on_success is not None:
            on_success(resultado)

    def app_falso(self, db_path):
        return types.SimpleNamespace(
            output_db=str(db_path),
            root=None,
            translation_cache={"the rook": "a torre"},
            glossary_substitutions=[],
            glossary_change_callbacks=[],
            log_message=lambda _m: None,
        )


class ResetTranslationsTests(ResetToolsTestCase):
    def banco(self):
        db_path = self.base / "traducoes.db"
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        conn.commit()
        conn.close()
        return db_path

    def backups(self):
        pasta = self.base / "backups"
        return sorted(p.name for p in pasta.glob("*.db")) if pasta.exists() else []

    def linhas(self, db_path):
        conn = initialize_database(str(db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        finally:
            conn.close()

    def test_the_backup_is_taken_before_the_question(self):
        """E a unica forma de voltar atras, e o custo dela e 0,4 s.

        Deixa-la para depois do "Apagar" significaria que uma falha entre a
        confirmacao e a copia apaga tudo sem rede. O pior caso desta ordem e uma
        copia a mais para quem desistiu, e a retencao cuida dela.
        """
        db_path = self.banco()
        self.resposta = False

        db_tools.reset_translations(self.app_falso(db_path))

        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(len(self.perguntas), 1)
        self.assertIn(self.backups()[0], self.perguntas[0][1])

    def test_saying_no_leaves_the_database_alone(self):
        db_path = self.banco()
        self.resposta = False

        db_tools.reset_translations(self.app_falso(db_path))

        self.assertEqual(self.linhas(db_path), 2)

    def test_saying_yes_empties_it(self):
        db_path = self.banco()

        db_tools.reset_translations(self.app_falso(db_path))

        self.assertEqual(self.linhas(db_path), 0)
        self.assertIn("info", [tipo for tipo, _t, _m in self.dialogos])

    def test_the_in_memory_cache_goes_with_it(self):
        """O cache tem precedencia sobre o banco.

        Deixado como estava, a proxima traducao reaproveitaria exatamente o que o
        usuario acabou de mandar apagar — e sem tocar no banco, entao nada
        apareceria como erro.
        """
        db_path = self.banco()
        app = self.app_falso(db_path)

        db_tools.reset_translations(app)

        self.assertEqual(app.translation_cache, {})

    def test_the_cache_survives_a_no(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        self.resposta = False

        db_tools.reset_translations(app)

        self.assertEqual(app.translation_cache, {"the rook": "a torre"})

    def test_an_empty_database_is_not_worth_asking_about(self):
        db_path = self.base / "vazio.db"
        initialize_database(str(db_path)).close()

        db_tools.reset_translations(self.app_falso(db_path))

        self.assertEqual(self.perguntas, [])
        self.assertEqual(self.backups(), [], "nem backup de um banco vazio")

    def test_the_question_says_how_many_rows_are_at_stake(self):
        db_path = self.banco()
        self.resposta = False

        db_tools.reset_translations(self.app_falso(db_path))

        self.assertIn("2 tradução(ões)", self.perguntas[0][1])


class ResetGlossaryTests(ResetToolsTestCase):
    def glossario_com(self, entradas):
        path = self.base / "Substituicoes.txt"
        save_glossary_entries(
            entradas, path=str(path), create_backup=False, sync_db=False
        )
        original = glossario._default_substitutions_path
        glossario._default_substitutions_path = lambda: str(path)
        self.addCleanup(
            setattr, glossario, "_default_substitutions_path", original
        )
        return path

    def test_saying_no_leaves_every_rule_in_place(self):
        path = self.glossario_com([("rook", "torre"), ("queen", "dama")])
        app = self.app_falso(self.base / "traducoes.db")
        app.glossary_substitutions = [("rook", "torre"), ("queen", "dama")]
        self.resposta = False

        db_tools.reset_glossary(app)

        self.assertEqual(len(load_glossary_entries(str(path), prefer_db=False)), 2)
        self.assertEqual(len(app.glossary_substitutions), 2)

    def test_saying_yes_empties_the_file(self):
        path = self.glossario_com([("rook", "torre"), ("queen", "dama")])
        app = self.app_falso(self.base / "traducoes.db")
        app.glossary_substitutions = [("rook", "torre"), ("queen", "dama")]

        db_tools.reset_glossary(app)

        self.assertEqual(load_glossary_entries(str(path), prefer_db=False), [])
        self.assertEqual(app.glossary_substitutions, [])

    def test_the_backup_comes_before_the_question(self):
        self.glossario_com([("rook", "torre")])
        app = self.app_falso(self.base / "traducoes.db")
        self.resposta = False

        db_tools.reset_glossary(app)

        copias = sorted((self.base / "backups").glob("Substituicoes-*.txt"))
        self.assertEqual(len(copias), 1)
        self.assertIn(copias[0].name, self.perguntas[0][1])
        # E ela contem as regras de antes, que e o unico jeito de voltar.
        self.assertIn("rook", copias[0].read_text(encoding="utf-8"))

    def test_only_one_backup_is_left_behind(self):
        """A gravacao tambem sabe fazer backup; duas copias identicas na pasta
        fariam a retencao descartar uma versao antiga de verdade para caber."""
        self.glossario_com([("rook", "torre")])
        app = self.app_falso(self.base / "traducoes.db")

        db_tools.reset_glossary(app)

        self.assertEqual(len(list((self.base / "backups").glob("Substituicoes-*.txt"))), 1)

    def test_the_open_windows_are_told(self):
        """Um editor aberto continuaria oferecendo sugestoes de regras que
        acabaram de deixar de existir."""
        self.glossario_com([("rook", "torre")])
        app = self.app_falso(self.base / "traducoes.db")
        avisos = []
        app.glossary_change_callbacks = [avisos.append]

        db_tools.reset_glossary(app)

        self.assertEqual(avisos, [[]])

# ===========================================================================
# Letras das pecas: correcao ancorada no comentario original
# ===========================================================================


class ChessNotationTableTests(unittest.TestCase):
    """A tabela de letras, antes de qualquer correcao depender dela."""

    def test_every_language_the_program_offers_has_letters(self):
        """Um idioma no seletor e fora da tabela e uma correcao que nao roda."""
        for _nome, codigo in app_config.LANGUAGES:
            with self.subTest(idioma=codigo):
                self.assertTrue(supports_notation(codigo))

    def test_no_language_uses_the_same_letter_for_two_pieces(self):
        """A inversao `letra -> peca` precisa ser uma bijecao.

        Com duas pecas na mesma letra, ler o original vira adivinhacao — e o
        russo e exatamente o caso que quase estraga isto: Rei (Король) e Cavalo
        (Конь) comecam com a mesma letra, e a notacao usa `Кр` no rei para
        desempatar. Uma tabela com `К` nos dois tornaria todo lance de rei um
        lance de cavalo.
        """
        for idioma, letras in PIECE_LETTERS.items():
            with self.subTest(idioma=idioma):
                self.assertEqual(
                    len(set(letras.values())),
                    len(letras),
                    f"{idioma} repete uma letra: {letras}",
                )

    def test_every_language_names_the_same_five_pieces(self):
        esperado = {"K", "Q", "R", "B", "N"}
        for idioma, letras in PIECE_LETTERS.items():
            with self.subTest(idioma=idioma):
                self.assertEqual(set(letras), esperado)

    def test_the_russian_king_takes_two_letters(self):
        """Fixado porque e o unico caso multi-letra, e o que exige a alternancia
        do regex ir da letra mais longa para a mais curta."""
        self.assertEqual(PIECE_LETTERS["ru"]["K"], "Кр")
        self.assertEqual(PIECE_LETTERS["ru"]["N"], "К")


class FixMoveNotationTests(unittest.TestCase):
    """A correcao das letras dos lances (ROADMAP 10)."""

    def corrige(self, original, traduzido, origem="en", destino="pt"):
        return fix_move_notation(original, traduzido, origem, destino)

    def test_the_aliasing_that_no_sequence_of_rules_can_solve(self):
        """O caso que originou o item, e a razao de ele nao ser glossario.

        `K -> R` e `R -> T` aplicados em sequencia destroem a informacao: depois
        da primeira regra, os `R` que vieram de `K` sao indistinguiveis dos que
        ja eram `R`, e a segunda transforma os dois em `T`. Numa passagem so,
        ancorado no original, os dois chegam certos.
        """
        texto, quantos = self.corrige(
            "The king plays Kf1 and the rook Rf8 holds.",
            "O rei joga Kf1 e a torre Rf8 segura.",
        )

        self.assertEqual(texto, "O rei joga Rf1 e a torre Tf8 segura.")
        self.assertEqual(quantos, 2)

    def test_the_sequential_mutation_would_turn_both_into_the_same_piece(self):
        """A contraprova, escrita como o defeito se manifestaria.

        Sem ela, o teste acima passaria igualmente com uma implementacao que so
        acertasse por acaso — e "as duas letras ficam diferentes" e uma
        exigencia mais forte do que "o texto bate".
        """
        texto, _ = self.corrige(
            "Kf1 and Rf8.", "Kf1 e Rf8."
        )

        rei, torre = texto.split(" e ")
        self.assertNotEqual(rei[0], torre[0], f"as duas pecas viraram a mesma: {texto}")

    def test_a_move_the_translator_already_translated_is_left_correct(self):
        """O tradutor e inconstante: as vezes traduz o lance, as vezes nao.

        Os dois casos aparecem no MESMO comentario aqui, que e como a queixa
        chegou. Olhando so a traducao, o `Rf1` traduzido e o `Rxe4+` nao
        traduzido tem a mesma cara e significados diferentes.
        """
        texto, quantos = self.corrige(
            "The king goes Kf1 and the rook Rxe4+ wins.",
            "O rei vai Rf1 e a torre Rxe4+ ganha.",
        )

        self.assertEqual(texto, "O rei vai Rf1 e a torre Txe4+ ganha.")
        self.assertEqual(quantos, 1, "so o lance que estava errado conta")

    def test_applying_it_twice_changes_nothing_the_second_time(self):
        """Idempotente: o texto ja corrigido e o texto certo."""
        uma, _ = self.corrige(
            "Kf1 and Rxe4+ and Nf3.", "Kf1 e Rxe4+ e Nf3."
        )
        duas, quantos = self.corrige("Kf1 and Rxe4+ and Nf3.", uma)

        self.assertEqual(duas, uma)
        self.assertEqual(quantos, 0)

    def test_the_promotion_letter_is_translated_too(self):
        texto, quantos = self.corrige(
            "Promotion e8=Q is decisive.", "A promocao e8=Q e decisiva."
        )

        self.assertEqual(texto, "A promocao e8=D e decisiva.")
        self.assertEqual(quantos, 1)

    def test_captures_disambiguators_and_check_survive_untouched(self):
        """So a letra da peca muda; o resto do lance sai do proprio texto."""
        texto, _ = self.corrige(
            "After Nbd7, Qxh5+ and Rae1#, white wins.",
            "Depois de Nbd7, Qxh5+ e Rae1#, as brancas ganham.",
        )

        self.assertEqual(texto, "Depois de Cbd7, Dxh5+ e Tae1#, as brancas ganham.")

    def test_pawn_moves_and_castling_are_never_touched(self):
        """Nao tem letra de peca, entao sao iguais em todas as linguas.

        Mexer neles seria mexer em texto que nao tem o que corrigir — e `e4` e
        `O-O` aparecem com muito mais frequencia que qualquer lance de peca.
        """
        original = "After e4 exd5 and O-O, the position is equal."
        traduzido = "Depois de e4 exd5 e O-O, a posicao esta igual."

        texto, quantos = self.corrige(original, traduzido)

        self.assertEqual(texto, traduzido)
        self.assertEqual(quantos, 0)

    def test_annotation_marks_stay_glued_to_the_move(self):
        texto, _ = self.corrige("Kf1!? and Rf1?! are ideas.", "Kf1!? e Rf1?! sao ideias.")

        self.assertEqual(texto, "Rf1!? e Tf1?! sao ideias.")

    def test_the_same_square_with_two_pieces_is_resolved_by_order(self):
        """A ancora empata quando duas pecas vao para a mesma casa.

        `Rf1` (Torre) e `Kf1` (Rei) tem a mesma ancora `f1`, entao ela sozinha
        nao decide. O desempate e a ORDEM, que o tradutor preserva: ele traduz o
        texto, nao o reordena.
        """
        texto, _ = self.corrige(
            "Both Rf1 and Kf1 are playable.", "Tanto Rf1 quanto Kf1 sao jogaveis."
        )

        self.assertEqual(texto, "Tanto Tf1 quanto Rf1 sao jogaveis.")

    def test_an_ambiguous_anchor_with_a_different_count_is_left_alone(self):
        """Sem pareamento seguro, nao se inventa um.

        O original tem dois lances para `f1` e a traducao so um: nao ha como
        saber qual deles sobreviveu. Deixar como esta e o pior resultado
        possivel desta funcao, e e de proposito — corrigir para o lance errado
        seria pior do que nao corrigir.
        """
        texto, quantos = self.corrige(
            "Both Rf1 and Kf1 are playable.", "Tanto Rf1 quanto ... sao jogaveis."
        )

        self.assertEqual(texto, "Tanto Rf1 quanto ... sao jogaveis.")
        self.assertEqual(quantos, 0)

    def test_a_move_that_is_not_in_the_original_is_left_alone(self):
        """Nao ha contra o que conferi-lo, e conferir e a unica coisa que a
        funcao sabe fazer."""
        texto, quantos = self.corrige("Only Kf1.", "Apenas Kf1, e talvez Rb7.")

        self.assertEqual(texto, "Apenas Rf1, e talvez Rb7.")
        self.assertEqual(quantos, 1)

    def test_a_repeated_move_is_fixed_everywhere_it_appears(self):
        texto, _ = self.corrige("Nf3 again: Nf3.", "Cf3 de novo: Nf3.")

        self.assertEqual(texto, "Cf3 de novo: Cf3.")

    def test_the_two_letter_russian_king_is_read_before_the_knight(self):
        """`К` (Cavalo) e prefixo de `Кр` (Rei).

        Na alternancia ingenua o cavalo casaria primeiro e todo lance de rei
        sairia como lance de cavalo com um `р` sobrando. E o mesmo cuidado que a
        BOM de UTF-32 exige (garantia E4), pelo mesmo motivo.
        """
        texto, _ = fix_move_notation("Kf1 then Nf3.", "Kf1 depois Nf3.", "en", "ru")

        self.assertEqual(texto, "Крf1 depois Кf3.")

    def test_it_reads_a_russian_original_back(self):
        texto, _ = fix_move_notation("Крf1 и Кf3.", "Kf1 e Nf3.", "ru", "pt")

        self.assertEqual(texto, "Rf1 e Cf3.")

    def test_it_works_between_two_non_english_languages(self):
        """O ingles nao e especial: o problema e de qualquer par cujas letras
        divirjam. Do espanhol para o alemao, as cinco mudam."""
        texto, _ = fix_move_notation(
            "El rey Rf1, la torre Txe4, el alfil Ag5.",
            "Der Konig Rf1, der Turm Txe4, der Laufer Ag5.",
            "es",
            "de",
        )

        self.assertEqual(texto, "Der Konig Kf1, der Turm Txe4, der Laufer Lg5.")

    def test_english_notation_is_recognised_even_in_a_pair_without_english(self):
        """O tradutor as vezes devolve a notacao inglesa de qualquer jeito.

        Num par espanhol -> portugues, `K` e `N` nao pertencem a nenhum dos dois
        alfabetos. Varrendo a traducao so com as letras dos dois idiomas em jogo,
        esse `Kf1` nem seria reconhecido como lance — e ficaria como esta, que e
        exatamente o defeito que a correcao veio consertar.
        """
        texto, quantos = fix_move_notation(
            "El rey Rf1 y el caballo Cf3.", "O rei Kf1 e o cavalo Nf3.", "es", "pt"
        )

        self.assertEqual(texto, "O rei Rf1 e o cavalo Cf3.")
        self.assertEqual(quantos, 2)

    def test_the_original_is_read_only_in_the_declared_alphabet(self):
        """A outra metade da assimetria, e a que nao pode ceder.

        Na traducao a letra e ruido; no original ela e a informacao. Aqui o
        original esta em ingles e diz `Rf8` — Torre. Lido com um alfabeto
        generoso, `R` tambem seria Rei (pt/es/fr/it) e a correcao teria de
        escolher; lido no alfabeto declarado, nao ha o que escolher.
        """
        texto, _ = self.corrige("The rook Rf8 holds.", "A torre Rf8 segura.")

        self.assertEqual(texto, "A torre Tf8 segura.")

    def test_a_move_the_declared_alphabet_cannot_explain_is_not_an_anchor(self):
        """O `A` do alfil nao existe em ingles.

        Num original declarado como ingles, `Ag5` nao e um lance que o idioma
        explique — pode ser qualquer coisa. Aceita-lo como ancora faria a
        correcao afirmar uma peca que ela nao tem como saber, e e por isso que
        `extract_moves` filtra pelo alfabeto declarado.
        """
        self.assertEqual(
            [m.group(0) for m in extract_moves("Kf1 and Ag5.", "en")], ["Kf1"]
        )

        texto, quantos = self.corrige("Kf1 and Ag5.", "Rf1 e Ag5.")

        self.assertEqual(texto, "Rf1 e Ag5.", "o lance inexplicavel foi mexido")
        self.assertEqual(quantos, 0)

    def test_a_bare_pawn_move_in_the_translation_is_never_rewritten(self):
        """A guarda que impede a correcao de inventar uma peca.

        O original tem um so lance para a casa `f1`, o rei. Se lances de peao
        entrassem como candidatos, o `f1` solto da traducao teria a mesma ancora
        e receberia o `Rf1` do rei — um lance de peao viraria lance de rei, e o
        texto ganharia uma peca que nao estava la.
        """
        texto, quantos = self.corrige(
            "The king plays Kf1.", "O rei joga Kf1, e o peao vai a f1."
        )

        self.assertEqual(texto, "O rei joga Rf1, e o peao vai a f1.")
        self.assertEqual(quantos, 1)

    def test_a_move_glued_to_the_end_of_a_word_is_not_a_move(self):
        """A fronteira da esquerda, fixada com um caso sintetico de proposito.

        Texto real que dispare isto e justamente o que nao da para enumerar — um
        erro de digitacao, uma colagem na importacao, um PGN mal formado. O que
        se protege e a fronteira: sem ela, qualquer sequencia terminada em letra
        de peca mais casa vira alvo de reescrita no meio de uma palavra.
        """
        texto, quantos = self.corrige("The rook Rf8 holds.", "A torreRf8 segura.")

        self.assertEqual(texto, "A torreRf8 segura.")
        self.assertEqual(quantos, 0)

    def test_languages_that_share_the_letters_change_nothing(self):
        """Espanhol e portugues so divergem no bispo; o resto ja esta certo."""
        texto, quantos = fix_move_notation(
            "El rey Rf1 y la torre Txe4.", "O rei Rf1 e a torre Txe4.", "es", "pt"
        )

        self.assertEqual(texto, "O rei Rf1 e a torre Txe4.")
        self.assertEqual(quantos, 0)

    def test_without_a_declared_source_language_nothing_is_corrected(self):
        """E a ligacao com o seletor de origem, e ela e deliberada.

        Sem saber em que alfabeto o original esta, `R` pode ser Rei ou Torre — e
        corrigir a partir de um palpite seria trocar um erro do tradutor por um
        erro do programa. Declarar o idioma e o que liga a correcao.
        """
        texto, quantos = self.corrige("Kf1 and Rf8.", "Kf1 e Rf8.", origem="")

        self.assertEqual(texto, "Kf1 e Rf8.")
        self.assertEqual(quantos, 0)

    def test_the_same_language_on_both_sides_is_a_no_op(self):
        texto, quantos = self.corrige("Kf1.", "Kf1.", origem="en", destino="en")

        self.assertEqual(texto, "Kf1.")
        self.assertEqual(quantos, 0)

    def test_an_unknown_language_is_a_no_op(self):
        texto, quantos = self.corrige("Kf1.", "Kf1.", origem="en", destino="ja")

        self.assertEqual(texto, "Kf1.")
        self.assertEqual(quantos, 0)

    def test_text_without_moves_comes_back_identical(self):
        texto, quantos = self.corrige(
            "A quiet positional comment.", "Um comentario posicional tranquilo."
        )

        self.assertEqual(texto, "Um comentario posicional tranquilo.")
        self.assertEqual(quantos, 0)

    def test_letters_inside_words_are_not_moves(self):
        """`Ke5` dentro de uma palavra nao e lance, e a fronteira e o que separa.

        Sem ela, qualquer palavra que por acaso tenha uma letra de peca seguida
        de casa viraria alvo de correcao — no meio de um comentario em prosa.
        """
        original = "The plan Kf1 works. Rebe5x is not a move."
        traduzido = "O plano Kf1 funciona. Rebe5x nao e um lance."

        texto, quantos = self.corrige(original, traduzido)

        self.assertEqual(texto, "O plano Rf1 funciona. Rebe5x nao e um lance.")
        self.assertEqual(quantos, 1)

    def test_an_empty_side_is_a_no_op(self):
        self.assertEqual(self.corrige("", "Kf1."), ("Kf1.", 0))
        self.assertEqual(self.corrige("Kf1.", ""), ("", 0))


class WorkerMoveNotationTests(unittest.TestCase):
    """A correcao no caminho de verdade: antes de gravar no banco."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "cache.db"

    COMENTARIO = "The king goes Kf1 and the rook Rxe4+ wins."

    def traduz_com(self, resposta):
        original = translation_worker.translate_text
        translation_worker.translate_text = lambda *_a, **_k: resposta
        self.addCleanup(setattr, translation_worker, "translate_text", original)

    def roda(self, resposta, source_language="en"):
        pgn = self.base / "game.pgn"
        pgn.write_text(
            f'[Event "T"]\n\n1. e4 {{{self.COMENTARIO}}}\n', encoding="utf-8"
        )
        self.traduz_com(resposta)
        app = FakeApp(self.db_path)
        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language=source_language
        )
        return app, pgn

    def gravado(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                "SELECT translated_comment FROM comments"
            ).fetchone()[0]
        finally:
            conn.close()

    def test_the_corrected_text_is_what_reaches_the_database(self):
        """"Antes de gravar" e o pedido, e o banco e onde ele se verifica."""
        self.roda("O rei vai Kf1 e a torre Rxe4+ ganha.")

        self.assertEqual(self.gravado(), "O rei vai Rf1 e a torre Txe4+ ganha.")

    def test_the_generated_pgn_carries_the_same_text(self):
        """O PGN e o banco saem da mesma variavel; se divergissem, o arquivo
        entregue ao usuario teria os lances errados e o banco os certos."""
        _app, pgn = self.roda("O rei vai Kf1 e a torre Rxe4+ ganha.")

        saida = pgn.with_name("game-BR.pgn").read_text(encoding="utf-8")
        self.assertIn("{O rei vai Rf1 e a torre Txe4+ ganha.}", saida)

    def test_without_a_declared_source_the_worker_stores_what_came_back(self):
        """Contraprova do teste acima: e o idioma declarado que liga a correcao."""
        self.roda("O rei vai Kf1 e a torre Rxe4+ ganha.", source_language="")

        self.assertEqual(self.gravado(), "O rei vai Kf1 e a torre Rxe4+ ganha.")

    def test_the_run_reports_how_many_moves_it_fixed(self):
        app, _pgn = self.roda("O rei vai Kf1 e a torre Rxe4+ ganha.")

        self.assertIn("Lances com a letra da peca corrigida: 2", "\n".join(app.logs))

    def test_it_says_when_it_is_off_and_why(self):
        app, _pgn = self.roda("O rei vai Kf1.", source_language="")

        self.assertIn("Correcao de lances desligada", "\n".join(app.logs))

    def test_the_individual_fallback_corrects_too(self):
        """O caminho do fallback (garantia B2) grava pelo seu proprio ponto.

        Sao dois `save_translation` no worker, e corrigir so num deles daria uma
        execucao em que o resultado depende de a rede ter respondido alinhado —
        o pior tipo de inconsistencia, porque aparece so as vezes.
        """
        pgn = self.base / "dois.pgn"
        pgn.write_text(
            '[Event "T"]\n\n1. e4 {The king goes Kf1.} e5 {The rook Rxe4+ wins.}\n',
            encoding="utf-8",
        )

        def desalinhado(texto, *_a, **_k):
            # Uma resposta que NAO devolve o separador force o caminho individual.
            if " ||| " in texto:
                return "resposta sem separador nenhum"
            return texto.replace("The king goes", "O rei vai").replace(
                "The rook", "A torre"
            ).replace("wins", "ganha")

        original = translation_worker.translate_text
        translation_worker.translate_text = desalinhado
        self.addCleanup(setattr, translation_worker, "translate_text", original)

        app = FakeApp(self.db_path)
        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="en"
        )

        conn = initialize_database(str(self.db_path))
        try:
            gravados = [
                linha[0]
                for linha in conn.execute(
                    "SELECT translated_comment FROM comments ORDER BY id"
                )
            ]
        finally:
            conn.close()

        self.assertIn("O rei vai Rf1.", gravados)
        self.assertIn("A torre Txe4+ ganha.", gravados)

if __name__ == "__main__":
    unittest.main()
