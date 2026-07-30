import csv
import io
import json
import xml.etree.ElementTree as ET
import os
import re
import sqlite3
import sys
import types
import tempfile
import threading
import time
import unittest
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from tradutor_pgn import database, glossario, settings
from tradutor_pgn.app_config import (
    DATABASE_BACKUP_KEEP_COUNT,
    LANGUAGES,
    DATABASE_BACKUP_MAX_TOTAL_MB,
    GLOSSARY_BACKUP_KEEP_COUNT,
    LOG_KEEP_COUNT,
    MAX_TRANSLATE_CHARS,
)
from tradutor_pgn.database import (
    FTS_TABLE,
    OCCURRENCES_TABLE,
    REVIEW_STATUS_DOUBT,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    ORDER_BY_ID,
    ORDER_BY_OCCURRENCE,
    QUALITY_VERSION_KEY,
    QualityReevaluationCanceled,
    MoveNotationCanceled,
    SCHEMA_VERSION,
    analyze_move_notation_updates,
    apply_move_notation_updates,
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
    count_adoptable_unknown_source,
    count_from_status_counts,
    count_review_rows,
    count_words_by_pair,
    escape_like_pattern,
    fetch_comment_history,
    fetch_comment_occurrences,
    fetch_exact_translation_match_candidates,
    fetch_export_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_review_status_by_id,
    fetch_translation_by_id,
    get_daily_review_activity,
    get_db_metadata,
    get_file_progress,
    get_quality_heuristics_version,
    get_review_row_offset,
    get_review_status_counts,
    get_database_stats,
    initialize_database,
    list_occurrence_files,
    load_translation_cache,
    overwrite_translation_by_id,
    quality_heuristics_are_current,
    reads_in_occurrence_order,
    record_occurrences,
    reevaluate_quality_warnings,
    resolve_comment_ids,
    save_translation,
    set_review_status_by_id,
    set_db_metadata,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    VersionedRules,
    build_glossary_lookup,
    order_rules_by_specificity,
    versioned_rules,
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
    load_suggestion_substitutions,
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
from tradutor_pgn.word_count import add_word_counts, count_words, total_word_counts
from tradutor_pgn.editor_text import diff_spans
from tradutor_pgn.background_task import TaskCanceled
from tradutor_pgn.pgn_utils import (
    BATCH_MAX_CHARS,
    batch_index_groups,
    collect_pgn_files,
    comment_reading_context,
    count_semicolon_comments,
    create_comment_batches,
    detect_encoding,
    detect_encoding_from_bytes,
    extract_comment_texts,
    extract_comment_texts_from_file,
    extract_comments_from_content,
    extract_comments_from_file,
    flatten_comment,
    generate_translated_pgn,
    read_pgn_text,
    is_generated_pgn,
    join_comments_for_batch,
    split_batch_translation,
    strip_generated_suffix,
    translated_output_path,
    wrap_pgn_comment,
)
from tradutor_pgn.pgn_spellcheck import (
    SPELLING_DB_FILENAME,
    build_spelling_index,
    close_spelling_data,
    collect_spellcheck_pgn_files,
    correct_spelling_value,
    default_spelling_db_path,
    escape_pgn_tag_value,
    is_normalized_pgn,
    iter_spelling_records,
    load_spelling_data,
    spelling_index_is_stale,
    unescape_pgn_tag_value,
    normalize_pgn_metadata_content,
    normalize_pgn_metadata_file,
    normalize_pgn_metadata_path,
    normalized_output_path,
    PGN_TAG_RE,
    SUPPORTED_TAGS,
    parse_spelling_file,
)
from tradutor_pgn.review_quality import (
    QUALITY_HEURISTICS_VERSION,
    QUALITY_REPORT_HEADERS,
    eval_symbols,
    build_quality_report_rows,
    evaluate_translation_quality,
    filter_quality_warning_rows,
    find_first_quality_warning,
    row_has_quality_warning,
    row_language_pair,
    summarize_quality_warnings,
)
from tradutor_pgn import app_config
from tradutor_pgn.annotation_mask import mask_annotations, restore_annotations
from tradutor_pgn.background_task import BackgroundTask, TaskCanceled
from tradutor_pgn.chess_notation import (
    PIECE_LETTERS,
    extract_moves,
    move_anchors,
    fix_move_notation,
    supports_notation,
)
from tradutor_pgn import chess_terms
from tradutor_pgn.chess_terms import (
    find_suspect_terms,
    load_suspect_terms,
    suspect_terms_for,
)
from tradutor_pgn.confirm_dialog import CONFIRMATION_WORD, confirmation_accepted
from tradutor_pgn.db_tools import (
    analyze_database_automatic_rules,
    analyze_translations_csv_import,
    apply_database_automatic_rules,
    create_database_backup,
    export_translations_to_csv,
    format_automatic_rule_examples,
    format_import_preview,
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
from tradutor_pgn.edit_window import format_propagation_confirmation, safe_geometry
from tradutor_pgn.glossary_editor import safe_geometry as glossary_safe_geometry
from tradutor_pgn.glossary_editor import (
    build_glossary_diagnostics,
    glossary_counts,
    glossary_filter_indices,
    sort_glossary_indices,
)
from tradutor_pgn.failed_runs import load_failed_run
from tradutor_pgn.settings import (
    MAIN_WINDOW_DEFAULTS,
    MAIN_WINDOW_KEY,
    read_main_window_settings,
    write_main_window_settings,
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
    pgn_spellcheck,
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
    # A semente tambem sai do caminho, e por uma razao diferente: ela EXISTE no
    # repositorio e e mesclada em toda carga de regras (garantia S15), entao um
    # teste que compara a lista de regras exata veria a terminologia embutida
    # junto. Quem quer exercitar a semente passa `seed_path` explicitamente —
    # ver `SeedGlossaryTests`.
    glossario._default_seed_path = lambda: str(base / "semente-inexistente.txt")


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
            # Dez campos: os sete que o editor le por posicao, o par de idiomas
            # (ROADMAP 16.1) e o bit de aviso (ROADMAP 19, item 4). Os tres
            # acrescimos entraram DEPOIS dos sete, cada um depois do anterior — se
            # qualquer um tivesse entrado no meio, os carimbos abaixo passariam a
            # ser lidos da coluna errada, e e por isso que este teste conta os
            # campos.
            self.assertEqual(len(row), 10)
            self.assertIsNotNone(row[4])
            self.assertIsNotNone(row[5])
            self.assertIsNone(row[6])
            self.assertEqual((row[7], row[8]), ("", "pt"))
            self.assertEqual(row[9], 0)

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
                {
                    "total": 5,
                    "pending": 4,
                    "verified": 1,
                    "warnings": 0,
                    # Recortes das pendentes (ROADMAP 19, item 12). A comparacao e do
                    # dicionario INTEIRO de proposito: uma chave nova que a lista nao
                    # soubesse ler deixaria um filtro paginando pelo total errado.
                    "rejected": 0,
                    "doubt": 0,
                },
            )
            self.assertEqual(
                get_review_status_counts(cursor, "pt", search_text="orig 4"),
                {
                    "total": 1,
                    "pending": 0,
                    "verified": 1,
                    "warnings": 0,
                    "rejected": 0,
                    "doubt": 0,
                },
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
                {
                    "total": 5,
                    "pending": 5,
                    "verified": 0,
                    "warnings": 0,
                    "rejected": 0,
                    "doubt": 0,
                },
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


def com_prioridade(entries, priority=GLOSSARY_PRIORITY_DEFAULT, scope=""):
    """Entradas de tres campos como o arquivo as devolve: com prioridade e escopo.

    A entrada detalhada ganhou um quarto campo no item 1.5 parte 2 e um quinto na
    secao 15. Nos testes cujo assunto nao e nenhum dos dois, escrever `, 0, ""`
    em cada tupla so acrescenta ruido — mas apagar os campos da comparacao
    esconderia um deles mexido por engano. Este helper diz explicitamente o que
    se espera nos dois.
    """
    return [
        (orig, new, rule_type, priority, scope) for orig, new, rule_type in entries
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
            pares = {(orig, new) for orig, new, _tipo, _prio, _escopo in entradas}
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
                translation_worker.load_cleanup_substitutions = lambda **_kw: [
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
            # Garantia X2: o comentario esvaziado pela limpeza sai do arquivo
            # inteiro, sem deixar um `{}` pontilhando o movetext. Este assert
            # ja protegeu o comportamento antigo (`assertIn`), trocado de
            # proposito no ROADMAP 13.4.
            self.assertNotIn("{}", output_text)
            self.assertIn("1. e4 e5", output_text)
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
                translation_worker.load_cleanup_substitutions = lambda **_kw: []
                translation_worker.load_automatic_substitutions = lambda **_kw: [
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

        # `conflicts` conta 2, e nao 3: a duplicata exata (#2) nao e conflito —
        # a vencedora produz exatamente o que ela queria, e o aviso dela e
        # "Entrada duplicada". Era 3 porque a avaliacao antiga bastava "ha duas
        # substituicoes distintas no grupo" e arrastava a duplicata junto,
        # contra o que a propria garantia S9 dizia. Com S12 a pergunta passou a
        # ser por regra: "o que a vencedora produz AQUI e diferente do que esta
        # regra queria?" (ROADMAP 14.4)
        self.assertEqual(
            glossary_counts(entries, diagnostics),
            {"total": 5, "duplicates": 2, "conflicts": 2, "invalid": 5},
        )
        self.assertEqual(
            glossary_filter_indices(entries, "mate", "Todas", diagnostics),
            [0, 1, 2],
        )
        self.assertEqual(
            glossary_filter_indices(entries, "", "Duplicadas", diagnostics),
            [0, 1],
        )
        # A duplicata exata (#2) fica fora de "Conflitos" pelo mesmo motivo da
        # contagem acima: a vencedora produz exatamente o que ela queria. Ela
        # continua em "Duplicadas", que e o aviso dela.
        self.assertEqual(
            glossary_filter_indices(entries, "", "Conflitos", diagnostics),
            [0, 2],
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
            db_tools.load_automatic_substitutions = lambda **_kw: [("rainha", "dama")]

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

        def explode(**_kwargs):
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
            self.assertEqual(
            entradas[1], ("queen", "rainha", GLOSSARY_RULE_SUGGESTION, 0, "")
        )
            self.assertIn(("queen", "dama", GLOSSARY_RULE_SUGGESTION, 0, ""), entradas)
            self.assertNotIn(("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""), entradas)

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
                ("rook", "torre alta", GLOSSARY_RULE_SUGGESTION, 0, ""),
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
                ("pawn", "peao livre", GLOSSARY_RULE_AUTOMATIC, 0, ""),
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
                    ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""),
                    ("pawn", "peao", GLOSSARY_RULE_AUTOMATIC, 0, ""),
                    ("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3, ""),
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
            self.assertEqual(do_banco, [("queen", "dama", GLOSSARY_RULE_SUGGESTION, 3, "")])

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
                ("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, ""),
                ("queen", "dama", GLOSSARY_RULE_AUTOMATIC, 2, ""),
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
                [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")],
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
            self.assertEqual(entradas, [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 5, "")])

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
            for orig, new, _tipo, prio, _e in promovidas
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
            ("torre", "rook", GLOSSARY_RULE_SUGGESTION, 0, ""),
            ("torre", "castle", GLOSSARY_RULE_SUGGESTION, 2, ""),
        ]
        conflitos = glossario.glossary_conflicts(entradas)

        for info in conflitos.values():
            for contexto in info["contexts"]:
                self.assertEqual(contexto["winner"], 1, "a ordem do arquivo venceu")

        regras = [(orig, new, prio) for orig, new, _tipo, prio, _e in entradas]
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
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_CLEANUP, 0, "")]
            )

    def test_headers_are_matched_ignoring_case_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "  ORIGINAL ,  Replacement  \r\nrook,torre\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_missing_type_column_defaults_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(tmp, "original,replacement\r\nrook,torre\r\n")

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_unknown_type_falls_back_to_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement,type\r\nrook,torre,inventado\r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
            )

    def test_values_are_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_csv(
                tmp, "original,replacement\r\n  rook  ,  torre  \r\n"
            )

            self.assertEqual(
                read_glossary_csv(path), [("rook", "torre", GLOSSARY_RULE_SUGGESTION, 0, "")]
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
        db_tools.load_automatic_substitutions = lambda **_kw: list(regras)

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

            def explode(**_kwargs):
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
    """O relatorio de "Estatisticas". A funcao inteira estava sem teste.

    E so leitura, mas e um relatorio: numero errado aqui nao quebra nada e
    engana em silencio. O que se exige e que os totais batam com o banco e que
    a contagem por idioma nao se misture.

    Desde o item 7 da secao 19 o relatorio e montado em DUAS partes: uma que le o
    banco fora da thread do Tk (`collect_database_stats`) e uma pura que formata o
    texto (`format_database_stats`). Os testes atacam as duas juntas, sem janela e
    sem `messagebox` — o que antes precisava interceptar um dialogo.
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

    def _relatorio(self, db_path):
        """O texto do relatorio, pelo mesmo caminho que a janela usa."""
        return db_tools.format_database_stats(
            db_tools.collect_database_stats(str(db_path))
        )

    def test_the_totals_match_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            msg = self._relatorio(db_path)

            self.assertIn("Total de traducoes armazenadas: 5", msg)
            self.assertIn("Verificadas: 1", msg)
            self.assertIn("Pendentes: 4", msg)

    def test_the_word_counts_reach_the_report(self):
        """Numeros de VERDADE, e nao so a presenca das linhas: a mutacao que zerava
        a contagem na coleta sobrevivia a um teste que so procurava o rotulo
        (ROADMAP 19, item 6).

        As cinco linhas de `_montar` somam 14 palavras de original e 11 de traducao;
        a unica verificada — `orig pt 1` -> `traducao boa` — tem 2.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            stats = db_tools.collect_database_stats(str(db_path))
            msg = db_tools.format_database_stats(stats)

            self.assertEqual(stats["words"]["original"], 14)
            self.assertEqual(stats["words"]["translated"], 11)
            self.assertEqual(stats["words"]["verified"], 2)
            self.assertEqual(stats["words"]["pending"], 9)
            self.assertIn("Palavras no original: 14", msg)
            self.assertIn("Palavras verificadas: 2", msg)
            # E por par, que e o recorte com que se orca um trabalho: as duas linhas
            # de `Inglês -> pt` tem 6 palavras de original e 5 de traducao.
            self.assertIn("palavras: 6 no original, 5 na traducao", msg)

    def test_each_language_pair_is_counted_on_its_own(self):
        """Duas traducoes em pt vindas do ingles e uma vinda de origem nao dita.

        Somadas pelo destino seriam "pt: 3"; o relatorio precisa mostrar as duas
        linhas separadas, senao o par que o usuario escolheu declarar desaparece
        no total.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            msg = self._relatorio(db_path)

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

            msg = self._relatorio(db_path)

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

            msg = self._relatorio(db_path)

            self.assertIn("Total de traducoes armazenadas: 0", msg)
            self.assertIn("Palavras no original: 0", msg)

    def test_the_progress_of_each_work_is_shown(self):
        """ROADMAP 18: "faltam 120 comentarios do capitulo 7".

        O numero por par de idiomas nunca respondeu isso — ele soma todos os PGN
        ja processados no mesmo balde.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)
            conn = initialize_database(str(db_path))
            cur = conn.cursor()
            arquivo = str(Path(tmp) / "cap07.pgn")
            record_occurrences(
                cur,
                arquivo,
                [(1, 1, 1, "orig pt 1"), (2, 1, 4, "orig pt 2")],
                resolve_comment_ids(cur, "pt", ["orig pt 1", "orig pt 2"], "en"),
            )
            conn.commit()
            conn.close()

            msg = self._relatorio(db_path)

            self.assertIn("Por arquivo de origem (obra):", msg)
            self.assertIn(
                "- cap07.pgn: 2 posicoes | 2 comentarios | verificadas: 1 (50%)"
                " | pendentes: 1 | QA: 0",
                msg,
            )

    def test_a_bank_with_no_occurrence_says_why_the_block_is_empty(self):
        """O estado de todo banco recem-migrado.

        Um bloco em branco leva a conclusao errada — "o programa nao registrou" —
        quando a verdade e que as linhas ja gravadas nao tinham de onde tirar
        procedencia, e a ganham ao reprocessar o PGN.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            self._montar(db_path)

            msg = self._relatorio(db_path)

            self.assertIn("Nenhum arquivo registrado ainda", msg)
            self.assertIn("processar o PGN de novo", msg)

    def test_the_work_list_is_cut_and_says_so(self):
        """O resumo e um `messagebox`: 200 capitulos dariam um dialogo mais alto
        que a tela, e as linhas de cima — as que o usuario leu primeiro — sairiam
        da tela sem aviso."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            conn = initialize_database(str(db_path))
            cur = conn.cursor()
            save_translation(cur, "um", "T um", "pt", "en")
            conn.commit()
            ids = resolve_comment_ids(cur, "pt", ["um"], "en")
            quantos = db_tools.FILE_PROGRESS_LIMIT + 3
            for indice in range(quantos):
                record_occurrences(
                    cur,
                    str(Path(tmp) / f"cap{indice:03d}.pgn"),
                    [(1, 1, 1, "um")],
                    ids,
                )
            conn.commit()
            conn.close()

            msg = self._relatorio(db_path)

            self.assertEqual(msg.count(".pgn:"), db_tools.FILE_PROGRESS_LIMIT)
            self.assertIn("... e mais 3 arquivo(s).", msg)

    def test_a_broken_database_raises_for_the_error_callback(self):
        """O dialogo de erro passou a ser do `run_with_progress` (item 7): a
        coleta LEVANTA, e quem exibe e o `on_error`. Testar a excecao e mais
        forte do que interceptar o dialogo — ela e o que a thread devolve."""
        with tempfile.TemporaryDirectory() as tmp:
            quebrado = Path(tmp) / "nao-e-banco.db"
            quebrado.write_bytes(b"isto nao e um banco sqlite" * 100)

            with self.assertRaises(sqlite3.DatabaseError):
                db_tools.collect_database_stats(str(quebrado))

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
            self._relatorio(db_path)

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

    def test_a_capture_written_with_the_multiplication_sign_is_still_a_move(self):
        """`N×d4` aparece em material publicado e chega assim aos comentarios.

        Medido no banco real: 198 capturas escritas com `×` e 7 com `:`, contra
        4.316 com `x`. As 205 primeiras nao eram nem reconhecidas como lance,
        entao passavam sem correcao — o defeito mais silencioso possivel, porque
        o lance simplesmente nao existia para a funcao.
        """
        texto, quantos = self.corrige(
            "Instead of 12. N×d4 the rook R×e4 wins.",
            "Em vez de 12. Nxd4 a torre Rxe4 ganha.",
        )

        self.assertEqual(texto, "Em vez de 12. Cxd4 a torre Txe4 ganha.")
        self.assertEqual(quantos, 2)

    def test_the_capture_mark_of_the_translation_is_the_one_that_stays(self):
        """O corpo do lance sai da TRADUCAO, e nao do original.

        Uma regra automatica do glossario do usuario converte `×` em `x`, entao
        o original guarda `N×d4` e a traducao chega com `Nxd4`. Reescrevendo com
        o corpo do original, a correcao devolveria o `×` ao texto — desfazendo
        em silencio uma decisao tomada no glossario. O teste exige as duas
        direcoes, porque so uma delas passaria por acaso.
        """
        do_original, _ = self.corrige(
            "The rook R×e4 wins.", "A torre Rxe4 ganha."
        )
        self.assertEqual(do_original, "A torre Txe4 ganha.", "o × voltou ao texto")

        da_traducao, _ = self.corrige(
            "The rook Rxe4 wins.", "A torre R×e4 ganha."
        )
        self.assertEqual(da_traducao, "A torre T×e4 ganha.", "o × da traducao sumiu")

    def test_a_translation_without_the_piece_letter_gains_nothing(self):
        """A funcao substitui; ela nao acrescenta.

        Se a traducao perdeu a letra da peca, inserir uma seria afirmar um lance
        que o texto traduzido nao tem — e a garantia e que o pior resultado
        possivel e deixar como esta.
        """
        texto, quantos = self.corrige("The queen Qe8=Q wins.", "A dama e8=Q ganha.")

        self.assertNotIn("De8=", texto)
        self.assertEqual(quantos, 0)

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
        """A guarda que impede a correcao de inventar uma peca."""
        texto, quantos = self.corrige(
            "The king plays Kf1.", "O rei joga Kf1, e o peao vai a f1."
        )

        self.assertEqual(texto, "O rei joga Rf1, e o peao vai a f1.")
        self.assertEqual(quantos, 1)

    def test_a_bare_pawn_move_does_not_count_as_a_rival_for_the_anchor(self):
        """O caso em que ignorar o peao decide se ALGO e corrigido.

        Com a ancora `f1` disputada por duas pecas, o pareamento exige que os
        dois lados tenham a mesma contagem. Um `f1` solto na traducao entrando
        como candidato faria tres contra dois — e ai **nada** e corrigido, nem os
        dois lances que estavam certos para corrigir.

        O teste anterior nao distinguia isto: com uma ancora so, a guarda de
        forma ja barrava a troca do peao e o resultado saia igual dos dois
        jeitos.
        """
        texto, quantos = self.corrige(
            "Both Rf1 and Kf1 are playable.",
            "Tanto Rf1 quanto Kf1 sao jogaveis; a casa f1 e chave.",
        )

        self.assertEqual(texto, "Tanto Tf1 quanto Rf1 sao jogaveis; a casa f1 e chave.")
        self.assertEqual(quantos, 2)

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

# ===========================================================================
# Corrigir os lances das traducoes ja gravadas
# ===========================================================================


class LabelEveryUnknownRowTests(unittest.TestCase):
    """`comments=None`: rotular tudo de um destino, e nao so o de uma execucao.

    A adocao nasceu presa a uma execucao de traducao, entao uma linha so era
    rotulada quando o comentario dela reaparecia num PGN. Para as 201.607 linhas
    legadas isso significaria nunca.
    """

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_it_labels_every_unlabelled_row_of_the_target(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt")
        save_translation(cur, "the bishop", "o bispo", "pt")
        save_translation(cur, "the knight", "le cavalier", "fr")
        conn.commit()

        rotuladas = adopt_unknown_source_language(cur, "pt", "en", None)
        conn.commit()

        self.assertEqual(rotuladas, 2)
        self.assertEqual(
            sorted(
                cur.execute(
                    "SELECT target_language, source_language FROM comments"
                ).fetchall()
            ),
            [("fr", ""), ("pt", "en"), ("pt", "en")],
        )

    def test_it_still_leaves_a_declared_source_alone(self):
        """A regra nao muda por rotular em massa."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "Nada", "Nothing", "en", "es")
        save_translation(cur, "the rook", "a torre", "en")
        conn.commit()

        self.assertEqual(adopt_unknown_source_language(cur, "en", "pt", None), 1)
        conn.commit()
        self.assertEqual(
            sorted(cur.execute("SELECT source_language FROM comments").fetchall()),
            [("es",), ("pt",)],
        )

    def test_an_empty_list_is_not_the_same_as_no_list(self):
        """`[]` e "nao ha comentarios nesta execucao"; `None` e "todos".

        Confundi-los faria uma execucao sem comentario nenhum rotular a tabela
        inteira — e o `if not comments` ingenuo faz exatamente isso.
        """
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt")
        conn.commit()

        self.assertEqual(adopt_unknown_source_language(cur, "pt", "en", []), 0)
        self.assertEqual(
            cur.execute("SELECT source_language FROM comments").fetchone()[0], ""
        )


class MoveNotationInDatabaseTests(unittest.TestCase):
    """A correcao de lances sobre o que ja esta gravado (ROADMAP 11)."""

    def banco(self, linhas=None):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        self.db_path = Path(sandbox.name) / "cache.db"
        conn = initialize_database(str(self.db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        for original, traduzido, origem in linhas or [
            ("The king plays Kf1.", "O rei joga Kf1.", "en"),
            ("The rook Rf8 holds.", "A torre Rf8 segura.", "en"),
            ("A quiet move.", "Um lance tranquilo.", "en"),
        ]:
            save_translation(cur, original, traduzido, "pt", origem)
        conn.commit()
        return conn

    def traducoes(self):
        conn = initialize_database(str(self.db_path))
        try:
            return {
                orig: trad
                for orig, trad in conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                )
            }
        finally:
            conn.close()

    def test_the_preview_counts_without_writing_anything(self):
        """O usuario confirma sabendo quantas linhas serao reescritas, e a
        previa nao pode ser o que as reescreve."""
        conn = self.banco()
        antes = self.traducoes()

        stats = analyze_move_notation_updates(
            conn.cursor(), "en", "pt", fix_move_notation
        )

        self.assertEqual(stats["scanned"], 3)
        self.assertEqual(stats["changed"], 2, "o rei e a torre mudam; o lance nenhum, nao")
        self.assertEqual(stats["moves"], 2)
        self.assertEqual(self.traducoes(), antes, "a previa gravou")

    def test_applying_rewrites_only_the_wrong_letters(self):
        conn = self.banco()

        stats = apply_move_notation_updates(
            conn.cursor(), "en", "pt", fix_move_notation
        )
        conn.commit()

        self.assertEqual(stats["changed"], 2)
        self.assertEqual(
            self.traducoes(),
            {
                "The king plays Kf1.": "O rei joga Rf1.",
                "The rook Rf8 holds.": "A torre Tf8 segura.",
                "A quiet move.": "Um lance tranquilo.",
            },
        )

    def test_the_quality_warning_is_reevaluated(self):
        """Garantia R6: a coluna e derivada do texto, e o texto mudou.

        Aqui a correcao faz a traducao virar identica ao original — que e um
        aviso de qualidade. Deixar a coluna como estava faria a contagem do
        editor divergir do que a avaliacao em Python diria das mesmas linhas.
        """
        # O bispo e a unica peca cuja letra e a mesma em ingles e em portugues,
        # entao corrigir `Ag5` para `Bg5` deixa a traducao IGUAL ao original —
        # que e um aviso de qualidade que nao existia antes da correcao.
        conn = self.banco([("Bg5", "Ag5", "en")])
        cur = conn.cursor()
        self.assertEqual(
            cur.execute("SELECT quality_warning FROM comments").fetchone()[0], 0
        )

        apply_move_notation_updates(cur, "en", "pt", fix_move_notation)
        conn.commit()

        linha = cur.execute(
            "SELECT translated_comment, quality_warning FROM comments"
        ).fetchone()
        self.assertEqual(linha[0], "Bg5")
        self.assertEqual(linha[1], 1, "o aviso novo nao foi recalculado")

    def test_every_change_is_in_the_history(self):
        """Garantia R2. Isto reescreve texto que o usuario pode ter revisado a
        mao, entao ele precisa poder ver o que era e voltar atras."""
        conn = self.banco()
        cur = conn.cursor()

        apply_move_notation_updates(cur, "en", "pt", fix_move_notation)
        conn.commit()

        registros = cur.execute(
            "SELECT action, previous_translation, new_translation FROM comment_history"
            " ORDER BY id"
        ).fetchall()
        self.assertEqual(
            registros,
            [
                ("move_notation", "O rei joga Kf1.", "O rei joga Rf1."),
                ("move_notation", "A torre Rf8 segura.", "A torre Tf8 segura."),
            ],
        )

    def test_a_verified_row_stays_verified(self):
        """Corrigir a letra de um lance nao desfaz a revisao humana do resto.

        Rebaixar milhares de linhas para "pendente" devolveria ao usuario um
        trabalho que ele ja fez.
        """
        conn = self.banco()
        cur = conn.cursor()
        cur.execute("UPDATE comments SET verified = 1")
        conn.commit()

        apply_move_notation_updates(cur, "en", "pt", fix_move_notation)
        conn.commit()

        self.assertEqual(
            cur.execute("SELECT COUNT(*) FROM comments WHERE verified = 1").fetchone()[0],
            3,
        )

    def test_rows_of_another_pair_are_not_touched(self):
        conn = self.banco(
            [
                ("The rook Rf8 holds.", "A torre Rf8 segura.", "en"),
                ("La torre Tf8 aguanta.", "A torre Rf8 segura.", "es"),
            ]
        )

        apply_move_notation_updates(conn.cursor(), "en", "pt", fix_move_notation)
        conn.commit()

        conn2 = initialize_database(str(self.db_path))
        try:
            linhas = dict(
                conn2.execute(
                    "SELECT source_language, translated_comment FROM comments"
                )
            )
        finally:
            conn2.close()
        self.assertEqual(linhas["en"], "A torre Tf8 segura.")
        self.assertEqual(linhas["es"], "A torre Rf8 segura.", "a linha do espanhol mudou")

    def test_a_row_that_could_not_be_labelled_is_still_corrected(self):
        """O caso que faz a aplicacao precisar do mesmo escopo da previa.

        A rotulagem usa `UPDATE OR IGNORE`: uma linha sem rotulo cujo par de
        destino ja esta ocupado permanece como "origem nao informada". Se a
        correcao olhasse so o par declarado, essa linha ficaria com os lances
        errados para sempre — e ela e indistinguivel das outras na tela.
        """
        conn = self.banco(
            [
                ("The rook Rf8 holds.", "A torre Tf8 segura.", "en"),
                # Mesmo original, sem rotulo: a rotulagem vai esbarrar na chave.
                ("The rook Rf8 holds.", "A torre Rf8 segura.", ""),
            ]
        )
        cur = conn.cursor()

        adopt_unknown_source_language(cur, "pt", "en", None)
        apply_move_notation_updates(cur, "en", "pt", fix_move_notation)
        conn.commit()

        linhas = sorted(
            cur.execute(
                "SELECT source_language, translated_comment FROM comments"
            ).fetchall()
        )
        self.assertEqual(
            linhas,
            [("", "A torre Tf8 segura."), ("en", "A torre Tf8 segura.")],
            "a linha que nao pode ser rotulada ficou com o lance errado",
        )

    def test_cancelling_raises_instead_of_finishing_halfway(self):
        """Precisa de mais de 200 linhas, e a primeira versao nao tinha.

        A desistencia e checada a cada 200 linhas — o mesmo ritmo das regras
        automaticas, para nao pagar uma chamada de callback por linha. Com oito
        linhas o teste passava com o cancelamento arrancado do codigo, porque a
        checagem nunca chegava a acontecer.
        """
        # Os comentarios precisam ser DISTINTOS: a chave da tabela e o texto, e
        # repetir a lista so produziria as mesmas 64 linhas.
        conn = self.banco(
            [
                (
                    f"Line {n}: the rook R{coluna}{fila} holds.",
                    f"Linha {n}: a torre R{coluna}{fila} segura.",
                    "en",
                )
                for n in range(4)
                for coluna in "abcdefgh"
                for fila in range(1, 9)
            ]
        )

        with self.assertRaises(MoveNotationCanceled):
            apply_move_notation_updates(
                conn.cursor(), "en", "pt", fix_move_notation,
                should_cancel=lambda: True,
            )

    def test_it_reports_progress(self):
        conn = self.banco()
        relatos = []

        analyze_move_notation_updates(
            conn.cursor(), "en", "pt", fix_move_notation,
            progress_callback=lambda feito, total: relatos.append((feito, total)),
        )

        self.assertTrue(relatos)
        self.assertEqual(relatos[0], (0, 3))
        self.assertEqual(relatos[-1], (3, 3))


class FixMoveNotationToolTests(unittest.TestCase):
    """A ferramenta inteira: rotular, corrigir, backup e desistencia."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "traducoes.db"

        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        # Sem idioma de origem, que e o estado das linhas anteriores a versao.
        save_translation(cur, "The king plays Kf1.", "O rei joga Kf1.", "pt")
        save_translation(cur, "The rook Rf8 holds.", "A torre Rf8 segura.", "pt")
        conn.commit()
        conn.close()

        self.dialogos = []
        self.confirma = True
        original = db_tools.messagebox
        db_tools.messagebox = types.SimpleNamespace(
            showinfo=lambda t, m, **_k: self.dialogos.append(("info", t, m)),
            showerror=lambda t, m, **_k: self.dialogos.append(("error", t, m)),
            askyesno=lambda t, m, **_k: (
                self.dialogos.append(("askyesno", t, m)) or self.confirma
            ),
        )
        self.addCleanup(setattr, db_tools, "messagebox", original)

        original_run = db_tools.run_with_progress
        db_tools.run_with_progress = self.rodar_sincrono
        self.addCleanup(setattr, db_tools, "run_with_progress", original_run)

    def rodar_sincrono(self, _parent, _titulo, work, on_success=None, on_cancel=None, **_kw):
        try:
            resultado = work(BackgroundTask())
        except TaskCanceled:
            if on_cancel is not None:
                on_cancel(None)
            return
        if on_success is not None:
            on_success(resultado)

    def app_falso(self):
        return types.SimpleNamespace(
            output_db=str(self.db_path),
            root=None,
            translation_cache={"The king plays Kf1.": "O rei joga Kf1."},
            log_message=lambda _m: None,
        )

    def linhas(self):
        conn = initialize_database(str(self.db_path))
        try:
            return {
                orig: (trad, origem)
                for orig, trad, origem in conn.execute(
                    "SELECT original_comment, translated_comment, source_language"
                    " FROM comments"
                )
            }
        finally:
            conn.close()

    def test_it_labels_and_corrects_in_one_go(self):
        """As duas coisas sao a mesma decisao do usuario, tomada uma vez.

        Enquanto as linhas estiverem como "origem nao informada" elas nao
        pertencem a par nenhum, e a correcao — que precisa saber o que `R`
        significa no original — nao teria como alcanca-las.
        """
        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        self.assertEqual(
            self.linhas(),
            {
                "The king plays Kf1.": ("O rei joga Rf1.", "en"),
                "The rook Rf8 holds.": ("A torre Tf8 segura.", "en"),
            },
        )

    def test_saying_no_leaves_everything_as_it_was(self):
        self.confirma = False

        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        self.assertEqual(
            self.linhas(),
            {
                "The king plays Kf1.": ("O rei joga Kf1.", ""),
                "The rook Rf8 holds.": ("A torre Rf8 segura.", ""),
            },
            "recusar nao pode nem rotular",
        )

    def test_a_backup_is_created_before_writing(self):
        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        copias = list((self.base / "backups").glob("traducoes-backup-*.db"))
        self.assertEqual(len(copias), 1)
        self.assertIn(copias[0].name, self.dialogos[-1][2])

    def test_the_in_memory_cache_goes_with_it(self):
        """Ele guarda o texto de ANTES e tem precedencia sobre o banco: a
        proxima traducao reescreveria os lances errados no PGN gerado."""
        app = self.app_falso()

        db_tools.fix_move_notation_in_database(app, "en", "pt")

        self.assertEqual(app.translation_cache, {})

    def test_detecting_is_refused_with_a_reason(self):
        """Sem saber se o `R` do original e Rei ou Torre, corrigir seria chutar."""
        db_tools.fix_move_notation_in_database(self.app_falso(), "", "pt")

        self.assertEqual([t for t, _tt, _m in self.dialogos], ["info"])
        self.assertIn("Detectar", self.dialogos[0][2])
        self.assertEqual(
            self.linhas()["The rook Rf8 holds."][0], "A torre Rf8 segura."
        )

    def test_nothing_to_do_says_so_without_asking(self):
        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")
        self.dialogos.clear()

        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        self.assertEqual([t for t, _tt, _m in self.dialogos], ["info"])
        self.assertIn("Nenhuma tradução precisa", self.dialogos[0][2])

    def test_the_preview_shows_what_will_change(self):
        self.confirma = False

        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        pergunta = next(m for t, _tt, m in self.dialogos if t == "askyesno")
        self.assertIn("Inglês -> pt", pergunta)
        self.assertIn("Traducoes que serao alteradas: 2", pergunta)
        self.assertIn("A torre Rf8 segura.", pergunta)
        self.assertIn("A torre Tf8 segura.", pergunta)

    def test_the_preview_says_how_many_rows_will_be_labeled(self):
        """A parte irreversivel, que a previa nao dizia (ROADMAP 17.5).

        Corrigir reescreve texto, e o backup desfaz; rotular declara de que
        idioma veio o acervo inteiro. Num banco com 200 mil linhas legadas, esse
        "Sim" era dado sem que o numero tivesse aparecido em lugar nenhum — ele
        so era dito no dialogo de RESULTADO, depois de feito.
        """
        self.confirma = False

        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        pergunta = next(m for t, _tt, m in self.dialogos if t == "askyesno")
        self.assertIn("serao rotuladas como 'en': 2", pergunta)

    def test_the_result_and_the_preview_say_the_same_number(self):
        """Duas consultas em dois lugares nao quebram nada visivel — elas so
        discordam (a licao dos itens 2.8, 3.6 e 11.1)."""
        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        pergunta = next(m for t, _tt, m in self.dialogos if t == "askyesno")
        resultado = next(m for t, _tt, m in self.dialogos if t == "info")
        self.assertIn("serao rotuladas como 'en': 2", pergunta)
        self.assertIn("rotuladas como 'en': 2", resultado)

    def test_with_nothing_to_label_the_line_is_not_shown(self):
        """Um "0 linhas serao rotuladas" fixo faria o usuario procurar um
        problema que nao existe — o mesmo criterio das linhas de lances e de
        comentarios ';' no resumo do worker."""
        # Primeira passada rotula tudo; a segunda nao tem mais o que rotular.
        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "The queen Qd8 waits.", "A dama Qd8 espera.", "pt", "en")
        conn.commit()
        conn.close()
        self.dialogos.clear()

        db_tools.fix_move_notation_in_database(self.app_falso(), "en", "pt")

        pergunta = next(m for t, _tt, m in self.dialogos if t == "askyesno")
        self.assertIn("Traducoes que serao alteradas: 1", pergunta)
        self.assertNotIn("rotuladas", pergunta)

# ===========================================================================
# A janela principal lembra o que foi escolhido
# ===========================================================================


class MainWindowSettingsTests(unittest.TestCase):
    """A leitura e a gravacao das escolhas, sem abrir janela.

    A parte que da para errar aqui e a validacao: o arquivo e JSON editavel a
    mao e sobrevive a versoes do programa, entao ele pode trazer qualquer coisa.
    """

    IDIOMAS = {"pt", "en", "es"}

    def test_an_empty_file_gives_the_defaults(self):
        self.assertEqual(
            read_main_window_settings({}, self.IDIOMAS), MAIN_WINDOW_DEFAULTS
        )

    def test_it_reads_back_what_was_stored(self):
        guardado = {
            MAIN_WINDOW_KEY: {
                "source_language": "en",
                "target_language": "es",
                "process_subdirs": False,
                "source_path": "C:/partidas",
            }
        }
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS),
            {
                "source_language": "en",
                "target_language": "es",
                "process_subdirs": False,
                "source_path": "C:/partidas",
            },
        )

    def test_detect_survives_next_to_a_non_default_target(self):
        """A string vazia e "Detectar", uma escolha legitima.

        O que este teste protege e a SECAO: guardar "Detectar" nao pode fazer o
        resto dela ser descartado. Ele **nao** distingue tratar a string vazia
        como valor de trata-la como ausente — o padrao tambem e vazio, entao as
        duas leituras dao no mesmo. Isso esta dito no codigo, junto da guarda.
        """
        guardado = {MAIN_WINDOW_KEY: {"source_language": "", "target_language": "es"}}
        valores = read_main_window_settings(guardado, self.IDIOMAS)

        self.assertEqual(valores["source_language"], "")
        self.assertEqual(valores["target_language"], "es")

    def test_a_language_the_program_no_longer_offers_falls_back(self):
        """Um seletor nao pode ficar num estado que ele nao sabe exibir."""
        guardado = {
            MAIN_WINDOW_KEY: {"source_language": "ja", "target_language": "ja"}
        }
        valores = read_main_window_settings(guardado, self.IDIOMAS)

        self.assertEqual(valores["source_language"], "")
        self.assertEqual(valores["target_language"], "pt")

    def test_junk_of_the_wrong_type_falls_back(self):
        guardado = {
            MAIN_WINDOW_KEY: {
                "source_language": 7,
                "target_language": None,
                "process_subdirs": "sim",
                "source_path": ["/a"],
            }
        }
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS), MAIN_WINDOW_DEFAULTS
        )

    def test_a_section_that_is_not_a_dict_falls_back(self):
        self.assertEqual(
            read_main_window_settings({MAIN_WINDOW_KEY: "nada"}, self.IDIOMAS),
            MAIN_WINDOW_DEFAULTS,
        )

    def test_a_path_that_no_longer_exists_is_still_offered(self):
        """Pode ser um pendrive que ainda nao foi plugado.

        Apagar o caminho por isso seria pior do que oferece-lo: quem valida a
        existencia e o "Iniciar Traducao", que ja o fazia e diz o que houve.
        """
        guardado = {MAIN_WINDOW_KEY: {"source_path": "E:/nao-existe/partidas"}}
        self.assertEqual(
            read_main_window_settings(guardado, self.IDIOMAS)["source_path"],
            "E:/nao-existe/partidas",
        )

    def test_writing_does_not_touch_the_editor_drafts(self):
        """Garantia R4, e e o motivo de a gravacao passar por `update_settings`.

        Os rascunhos das janelas de edicao vivem no MESMO arquivo. Gravar o
        snapshot inteiro daqui apagaria o que elas escreveram desde que este
        processo abriu — e o usuario so descobriria ao perder uma edicao.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            save_settings(
                {
                    "editor_drafts": {"chave": {"text": "rascunho vivo"}},
                    "editor": {"font_size": 15},
                },
                caminho,
            )

            write_main_window_settings({"source_language": "en"}, caminho)

            disco = load_settings(caminho)
            self.assertEqual(
                disco["editor_drafts"], {"chave": {"text": "rascunho vivo"}}
            )
            self.assertEqual(disco["editor"], {"font_size": 15})
            self.assertEqual(disco[MAIN_WINDOW_KEY]["source_language"], "en")

    def test_writing_twice_keeps_the_fields_it_was_not_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            write_main_window_settings(
                {"source_language": "en", "target_language": "pt"}, caminho
            )
            write_main_window_settings({"source_path": "C:/x"}, caminho)

            guardado = load_settings(caminho)[MAIN_WINDOW_KEY]
            self.assertEqual(guardado["source_language"], "en")
            self.assertEqual(guardado["source_path"], "C:/x")

class SettingsWithBomTests(unittest.TestCase):
    """Um BOM no arquivo de configuracoes apagava a memoria inteira do programa.

    O arquivo e JSON editavel a mao, e o Bloco de Notas do Windows grava UTF-8
    **com BOM**. Lido como `utf-8`, o `json.load` levanta, o `except` devolve
    `{}` e o programa segue como se nao houvesse configuracao nenhuma — e a
    proxima gravacao escreve um arquivo novo sem nada. Nada avisa.

    Encontrado conferindo o executavel antes de publicar a v0.2.1: as escolhas
    da janela principal nao voltavam, e a causa nao era a janela.
    """

    def arquivo(self, conteudo, com_bom):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        bruto = json.dumps(conteudo).encode("utf-8")
        caminho.write_bytes((b"\xef\xbb\xbf" if com_bom else b"") + bruto)
        return str(caminho)

    def test_a_file_with_a_bom_is_read_and_not_discarded(self):
        caminho = self.arquivo({"editor": {"font_size": 15}}, com_bom=True)

        self.assertEqual(load_settings(caminho), {"editor": {"font_size": 15}})

    def test_a_file_without_a_bom_still_works(self):
        caminho = self.arquivo({"editor": {"font_size": 15}}, com_bom=False)

        self.assertEqual(load_settings(caminho), {"editor": {"font_size": 15}})

    def test_the_drafts_survive_a_bom(self):
        """Garantia R4 pela porta dos fundos.

        O que R4 protege e o rascunho nao salvo de uma janela contra a gravacao
        de outra. De nada adianta se um caractere invisivel no inicio do arquivo
        faz o programa inteiro esquecer que ele existe.
        """
        caminho = self.arquivo(
            {"editor_drafts": {"chave": {"text": "nao salvo", "base_translation": ""}}},
            com_bom=True,
        )

        self.assertIn("chave", load_settings(caminho).get("editor_drafts", {}))

    def test_the_failed_run_list_survives_a_bom(self):
        """Garantia T4: a lista do "Reprocessar Falhas" mora no mesmo arquivo."""
        caminho = self.arquivo(
            {
                "failed_translation": {
                    "target_language": "pt",
                    "files": ["/a/b.pgn"],
                    "failed_count": 3,
                }
            },
            com_bom=True,
        )

        registro = load_failed_run(caminho)
        self.assertIsNotNone(registro)
        self.assertEqual(registro["files"], ["/a/b.pgn"])

    def test_writing_never_adds_a_bom(self):
        """Aceita-se o BOM na leitura; nao se escreve um.

        Gravar com BOM funcionaria com esta leitura e quebraria qualquer outro
        leitor de JSON — e o arquivo existe para ser editavel a mao.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")
            save_settings({"editor": {"font_size": 12}}, caminho)

            self.assertFalse(Path(caminho).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_a_round_trip_through_a_bom_keeps_everything(self):
        """O caminho completo: le com BOM, grava uma secao, o resto continua la.

        E o cenario que perde dado de verdade — ler devolvendo `{}` e depois
        gravar por cima e o que torna a perda definitiva.
        """
        caminho = self.arquivo(
            {
                "editor_drafts": {"chave": {"text": "nao salvo"}},
                "editor": {"font_size": 15},
            },
            com_bom=True,
        )

        write_main_window_settings({"source_language": "en"}, caminho)

        disco = load_settings(caminho)
        self.assertEqual(disco["editor_drafts"], {"chave": {"text": "nao salvo"}})
        self.assertEqual(disco["editor"], {"font_size": 15})
        self.assertEqual(disco[MAIN_WINDOW_KEY]["source_language"], "en")

    def test_a_file_that_is_not_json_at_all_still_degrades_to_empty(self):
        """A tolerancia ao BOM nao pode virar tolerancia a lixo.

        Um arquivo corrompido continua devolvendo `{}` — o programa abre com os
        padroes em vez de nao abrir.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        caminho.write_bytes(b"\xef\xbb\xbf isto nao e json {{{")

        self.assertEqual(load_settings(str(caminho)), {})

    def test_bytes_that_are_not_utf8_degrade_to_empty(self):
        """Nem toda falha de leitura e de JSON: um arquivo binario levanta
        `UnicodeDecodeError`, que precisa ser tratado junto."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "settings.json"
        caminho.write_bytes(b"\xff\xfe\x00\x00 lixo binario")

        self.assertEqual(load_settings(str(caminho)), {})


class CommandAnnotationInMovesTests(unittest.TestCase):
    """As anotacoes `[%...]` nao sao lances (ROADMAP 13.1).

    Os codigos de cor do Lichess (R, G, Y, B) colidem com letras de peca:
    `Ra1h8` dentro de `[%cal ...]` tem a forma exata de um lance de Torre, e a
    correcao reescrevia a seta vermelha como `Ta1h8` — deterministicamente,
    porque o original e a fonte da ancora e o pareamento nunca falha. A
    ferramenta em massa do banco passa por estas mesmas funcoes, entao a
    exclusao daqui cobre as duas portas.
    """

    def test_cal_arrow_color_is_not_rewritten(self):
        texto, quantos = fix_move_notation(
            "[%cal Ra1h8] good plan", "[%cal Ra1h8] bom plano", "en", "pt"
        )
        self.assertEqual(texto, "[%cal Ra1h8] bom plano")
        self.assertEqual(quantos, 0)

    def test_csl_circle_color_is_not_rewritten(self):
        texto, quantos = fix_move_notation(
            "[%csl Rd4] weak square", "[%csl Rd4] casa fraca", "en", "pt"
        )
        self.assertEqual(texto, "[%csl Rd4] casa fraca")
        self.assertEqual(quantos, 0)

    def test_real_move_beside_annotation_is_still_fixed(self):
        """A exclusao nao pode desligar a correcao: o lance de verdade que
        divide o comentario com a anotacao continua sendo conferido."""
        texto, quantos = fix_move_notation(
            "[%cal Rd4d8,Ge2e4] with Kf1 next",
            "[%cal Rd4d8,Ge2e4] com Kf1 a seguir",
            "en",
            "pt",
        )
        self.assertEqual(texto, "[%cal Rd4d8,Ge2e4] com Rf1 a seguir")
        self.assertEqual(quantos, 1)

    def test_extract_moves_ignores_annotation_payload(self):
        """No ORIGINAL a anotacao viraria uma ancora esperada falsa — o outro
        lado do mesmo defeito."""
        lances = [
            m.group(0) for m in extract_moves("[%cal Rd4d8] and Rd1 wins", "en")
        ]
        self.assertEqual(lances, ["Rd1"])


class FlattenDecimalTests(unittest.TestCase):
    """O achatamento nao insere espaco entre digitos (ROADMAP 13.2).

    `[%eval +0.35]` virava `[%eval +0. 35]` ANTES de qualquer traducao, e o
    texto quebrado era tres coisas ao mesmo tempo: a chave de cache, o que ia
    para a API e o que voltava ao PGN gerado.
    """

    def test_eval_annotation_survives(self):
        self.assertEqual(flatten_comment("[%eval +0.35]"), "[%eval +0.35]")

    def test_decimal_in_prose_survives(self):
        self.assertEqual(flatten_comment("2.5 pawns up"), "2.5 pawns up")
        self.assertEqual(flatten_comment("v1.2.3 fixed it"), "v1.2.3 fixed it")

    def test_sentence_spacing_is_still_normalized(self):
        """O que o achatamento sempre fez continua feito — inclusive depois de
        numero de lance, onde o que segue o ponto e letra, nao digito."""
        self.assertEqual(flatten_comment("End.Next"), "End. Next")
        self.assertEqual(flatten_comment("ok!Next"), "ok! Next")
        self.assertEqual(flatten_comment("14.Bxf7+ wins"), "14. Bxf7+ wins")


class DecimalKeyMigrationTests(unittest.TestCase):
    """A migracao 4 -> 5 reachata as chaves gravadas pelo achatamento antigo.

    Roda UMA vez, e a unica vez importa: corrigido o achatamento, um
    `digito. digito` gravado dali em diante e um espaco que estava no PGN do
    usuario, e colapsa-lo seria reescrever texto dele (ROADMAP 13.2).
    """

    def test_spaced_decimal_key_is_collapsed_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            conn = initialize_database(db)
            cursor = conn.cursor()
            save_translation(cursor, "eval of 0. 35 here", "aval de 0,35", "pt", "en")
            conn.commit()
            conn.execute("PRAGMA user_version = 4")
            conn.commit()
            conn.close()

            conn = initialize_database(db)
            try:
                chaves = [
                    r[0]
                    for r in conn.execute("SELECT original_comment FROM comments")
                ]
                self.assertEqual(chaves, ["eval of 0.35 here"])
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
            finally:
                conn.close()

    def test_collapsed_twin_already_present_leaves_old_row_alone(self):
        """Quando a chave colapsada ja existe no par, a linha antiga fica como
        esta: fundir seria destruir uma traducao para desduplicar um cache."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            conn = initialize_database(db)
            cursor = conn.cursor()
            save_translation(cursor, "score 1. 5 raw", "antiga", "pt", "en")
            save_translation(cursor, "score 1.5 raw", "nova", "pt", "en")
            conn.commit()
            conn.execute("PRAGMA user_version = 4")
            conn.commit()
            conn.close()

            conn = initialize_database(db)
            try:
                chaves = sorted(
                    r[0]
                    for r in conn.execute("SELECT original_comment FROM comments")
                )
                self.assertEqual(chaves, ["score 1. 5 raw", "score 1.5 raw"])
            finally:
                conn.close()

    def test_spaced_decimal_written_after_upgrade_is_user_text(self):
        """Reabrir um banco ja migrado nao pode colapsar nada: o espaco deixou
        de ser assinatura do achatamento antigo no momento da correcao."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "t.db")
            conn = initialize_database(db)
            cursor = conn.cursor()
            save_translation(cursor, "raw 0. 5 from source", "cru", "pt", "en")
            conn.commit()
            conn.close()

            conn = initialize_database(db)
            try:
                chaves = [
                    r[0]
                    for r in conn.execute("SELECT original_comment FROM comments")
                ]
                self.assertEqual(chaves, ["raw 0. 5 from source"])
            finally:
                conn.close()


class AnnotationMaskTests(unittest.TestCase):
    """Mascara e restauracao verificada das anotacoes (ROADMAP 13.3)."""

    def test_roundtrip_is_byte_for_byte(self):
        original = "Good move [%cal Ra1h8] here [%clk 0:05:30] end"
        mascarado, tokens = mask_annotations(original)
        self.assertNotIn("[%", mascarado)
        restaurado, ok = restore_annotations(mascarado, tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, original)

    def test_translator_spacing_around_sentinel_is_tolerated(self):
        _, tokens = mask_annotations("[%cal Ra1h8] x [%clk 0:05:30]")
        restaurado, ok = restore_annotations("⟦ 1 ⟧ y ⟦0⟧", tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, "[%clk 0:05:30] y [%cal Ra1h8]")

    def test_missing_sentinel_is_detected(self):
        _, tokens = mask_annotations("[%cal Ra1h8] and [%eval +0.35]")
        _, ok = restore_annotations("so sobrou ⟦0⟧", tokens)
        self.assertFalse(ok)

    def test_duplicated_sentinel_is_detected(self):
        _, tokens = mask_annotations("[%cal Ra1h8]")
        _, ok = restore_annotations("⟦0⟧ de novo ⟦0⟧", tokens)
        self.assertFalse(ok)

    def test_sentinel_leaked_from_neighbour_is_detected(self):
        """Um sentinela num comentario que nao mascarou nada e vazamento de
        outro comentario do lote — o rastro de um separador comido."""
        _, ok = restore_annotations("vazou ⟦3⟧ aqui", [])
        self.assertFalse(ok)

    def test_text_without_annotations_passes_untouched(self):
        mascarado, tokens = mask_annotations("um comentario comum")
        self.assertEqual(mascarado, "um comentario comum")
        self.assertEqual(tokens, [])
        restaurado, ok = restore_annotations("um comentario comum", tokens)
        self.assertTrue(ok)
        self.assertEqual(restaurado, "um comentario comum")


class WorkerAnnotationMaskTests(unittest.TestCase):
    """A mascara de ponta a ponta no worker (garantia X1)."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

    def test_annotations_cross_translation_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {Good move [%cal Ra1h8] with [%eval +0.35] score}\n",
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            payloads = []
            original_translate_text = translation_worker.translate_text
            try:
                def fake_translate(text, *_args, **_kwargs):
                    payloads.append(text)
                    return (
                        text.replace("Good move", "Bom lance")
                        .replace("with", "com")
                        .replace("score", "de aval")
                    )

                translation_worker.translate_text = fake_translate
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text

            # O que foi para a API nao continha anotacao nenhuma (X1: a
            # mascara protege exatamente o trecho que a API poderia mutilar).
            self.assertTrue(payloads)
            for payload in payloads:
                self.assertNotIn("[%", payload)

            esperado = "Bom lance [%cal Ra1h8] com [%eval +0.35] de aval"
            conn = initialize_database(str(db_path))
            try:
                gravado = conn.execute(
                    "SELECT translated_comment FROM comments"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(gravado, esperado)

            output_text = (tmp_path / "game-BR.pgn").read_text(encoding="utf-8")
            self.assertIn("{" + esperado + "}", output_text)

    def test_lost_sentinel_becomes_reported_failure(self):
        """Se a traducao comeu um sentinela, gravar seria guardar uma anotacao
        corrompida com cara de certa: o comentario conta como falha e fica no
        idioma original (T2/T3)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n'
                "1. e4 {Good move [%cal Ra1h8] indeed}\n",
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            original_translate_text = translation_worker.translate_text
            try:
                def fake_translate(text, *_args, **_kwargs):
                    return "Bom lance sem sentinela nenhum"

                translation_worker.translate_text = fake_translate
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original_translate_text

            self.assertTrue(
                any("[FALHA] Anotacoes [%...]" in log for log in app.logs)
            )
            self.assertTrue(
                any("Comentarios que falharam: 1" in log for log in app.logs)
            )

            conn = initialize_database(str(db_path))
            try:
                total = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(total, 0)
            self.assertFalse((tmp_path / "game-BR.pgn").exists())


class EmptyCleanupSpanRemovalTests(unittest.TestCase):
    """O comentario esvaziado pela limpeza sai do arquivo (garantia X2)."""

    def test_empty_translation_removes_span_and_one_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            conteudo = '[Event "T"]\n\n1. e4 {junk} e5 {keep} 2. Nf3\n'
            entrada.write_text(conteudo, encoding="utf-8")
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            ok = generate_translated_pgn(
                str(entrada),
                str(saida),
                {"junk": "", "keep": "fica"},
                posicoes,
            )
            self.assertTrue(ok)
            texto = saida.read_text(encoding="utf-8")
            self.assertNotIn("{}", texto)
            self.assertIn("1. e4 e5", texto)
            self.assertIn("{fica}", texto)

    def test_adjacent_spans_do_not_eat_each_other(self):
        """`{a}{b}` colados: o espaco vizinho que sai e so espaco — nunca o
        comeco do span seguinte."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_text(
                '[Event "T"]\n\n1. e4 {junk}{keep} e5\n', encoding="utf-8"
            )
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada), str(saida), {"junk": "", "keep": "fica"}, posicoes
            )
            texto = saida.read_text(encoding="utf-8")
            self.assertIn("1. e4{fica} e5", texto)
            self.assertNotIn("{}", texto)


class SemicolonCommentTests(unittest.TestCase):
    """Comentarios `;` sao contados e anunciados (garantia X3)."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: True)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

    def test_count_skips_tags_and_brace_contents(self):
        conteudo = (
            '[Event "a;b"]\n'
            "\n"
            "1. e4 ; melhor lance\n"
            "e5 {com ; dentro} 2. Nf3 ; outra nota\n"
            "3. Bb5 sem nada\n"
        )
        self.assertEqual(count_semicolon_comments(conteudo), 2)

    def test_multiline_brace_does_not_join_neighbours(self):
        conteudo = "1. e4 ; um\n{quebra\nde linha} 2. d4 ; dois\n"
        self.assertEqual(count_semicolon_comments(conteudo), 2)

    def test_pgn_with_only_semicolon_comments_is_announced(self):
        """Antes, um PGN anotado so com `;` terminava em "nenhum comentario
        encontrado" — o programa parecia nao ter funcionado."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n1. e4 ; melhor lance\ne5 ; resposta\n',
                encoding="utf-8",
            )

            app = FakeApp(db_path)
            translation_worker.run_translation(app, str(pgn), "pt", False)

            self.assertTrue(
                any("2 comentario(s) no formato ';'" in log for log in app.logs)
            )
            self.assertTrue(
                any(
                    "que o programa nao traduz" in log
                    for log in app.logs
                )
            )

    def test_mixed_file_reports_ignored_count_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "cache.db"
            pgn = tmp_path / "game.pgn"
            pgn.write_text(
                '[Event "Test"]\n\n1. e4 {White starts} e5 ; nota\n',
                encoding="utf-8",
            )

            conn = initialize_database(str(db_path))
            cursor = conn.cursor()
            save_translation(cursor, "White starts", "As brancas comecam", "pt")
            conn.commit()
            conn.close()

            app = FakeApp(db_path)
            translation_worker.run_translation(app, str(pgn), "pt", False)

            self.assertTrue(
                any(
                    "Comentarios ';' ignorados (nao suportado): 1" in log
                    for log in app.logs
                )
            )


class OutputFidelityTests(unittest.TestCase):
    """Fim de linha preservado e BOM opcional na saida (ROADMAP 13.6)."""

    def test_crlf_input_stays_crlf_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(
                b'[Event "T"]\r\n\r\n1. e4 {White starts} e5\r\n'
            )
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada),
                str(saida),
                {"White starts": "As brancas comecam"},
                posicoes,
            )
            raw = saida.read_bytes()
            self.assertEqual(
                raw,
                b'[Event "T"]\r\n\r\n1. e4 {As brancas comecam} e5\r\n',
            )

    def test_lf_input_stays_lf_even_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(b'[Event "T"]\n\n1. e4 {White starts} e5\n')
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            saida = tmp_path / "out.pgn"
            generate_translated_pgn(
                str(entrada),
                str(saida),
                {"White starts": "As brancas comecam"},
                posicoes,
            )
            raw = saida.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertIn(b"{As brancas comecam}\n", raw.replace(b" e5", b""))

    def test_bom_option_prefixes_utf8_output(self):
        """Um PGN ASCII cuja traducao introduz acentos sai UTF-8; sem BOM o
        ChessBase do Windows le ANSI e exibe mojibake. A opcao existe para
        esse consumidor — e desligada nada muda."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entrada = tmp_path / "in.pgn"
            entrada.write_bytes(b'[Event "T"]\n\n1. e4 {White starts} e5\n')
            posicoes = extract_comments_from_file(str(entrada))["positions"]

            com_bom = tmp_path / "bom.pgn"
            generate_translated_pgn(
                str(entrada),
                str(com_bom),
                {"White starts": "Tradução com acento"},
                posicoes,
                use_bom=True,
            )
            self.assertTrue(com_bom.read_bytes().startswith(b"\xef\xbb\xbf"))

            sem_bom = tmp_path / "sem.pgn"
            generate_translated_pgn(
                str(entrada),
                str(sem_bom),
                {"White starts": "Tradução com acento"},
                posicoes,
            )
            self.assertFalse(sem_bom.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_read_output_settings_validates_types_for_output(self):
        padrao = {"utf8_bom": False, "wrap_columns": 0}
        self.assertEqual(settings.read_output_settings({}), padrao)
        self.assertEqual(
            settings.read_output_settings({"output": {"utf8_bom": True}}),
            dict(padrao, utf8_bom=True),
        )
        # Tipo errado cai no padrao: o arquivo e editavel a mao.
        self.assertEqual(
            settings.read_output_settings({"output": {"utf8_bom": "yes"}}),
            padrao,
        )
        self.assertEqual(settings.read_output_settings({"output": "lixo"}), padrao)

    def test_the_wrap_width_is_validated(self):
        """A requebra e um numero de colunas, e o arquivo e editavel a mao
        (ROADMAP 19, item 13)."""
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": 80}})["wrap_columns"],
            80,
        )
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": 0}})["wrap_columns"],
            0,
        )
        # `True` E um int em Python: sem a checagem de bool, um `true` no arquivo
        # requebraria em UMA coluna — uma palavra por linha.
        self.assertEqual(
            settings.read_output_settings({"output": {"wrap_columns": True}})["wrap_columns"],
            0,
        )
        # E o mesmo acidente escrito com numero.
        for invalido in (1, 19, -80, "80", 12.5):
            self.assertEqual(
                settings.read_output_settings(
                    {"output": {"wrap_columns": invalido}}
                )["wrap_columns"],
                0,
                invalido,
            )


class CaseShadowConflictTests(unittest.TestCase):
    """Conflito por diferenca de caixa (garantia S12, ROADMAP 14.4).

    Uma regra escrita toda em minusculas casa sem diferenciar caixa, entao ela
    engole a versao capitalizada que venha depois. O detector agrupava por
    padrao EXATO: `'black'` e `'Black'` eram padroes diferentes, e a janela
    mostrava as duas lado a lado sem dizer que a segunda estava morta.
    """

    def test_lowercase_rule_shadows_the_capitalized_one(self):
        entradas = [("black", "pretas"), ("Black", "as pretas")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertEqual(sorted(conflitos), [0, 1])
        mensagem = glossario.describe_glossary_conflict(entradas, 1, conflitos)
        self.assertIn("nunca é aplicada", mensagem)
        self.assertIn("'pretas'", mensagem)

    def test_case_sensitive_first_leaves_both_alive(self):
        """A relacao nao e simetrica. Com a de caixa fixa na frente, cada uma
        pega o seu: `Black` o texto capitalizado, `black` o resto."""
        entradas = [("Black", "as pretas"), ("black", "pretas")]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_capitalization_propagation_is_not_a_conflict(self):
        """O caso que domina o glossario real (166 das 210): a vencedora ja
        produz o que a morta queria, porque a substituicao propaga a
        capitalizacao do texto encontrado. E redundancia, nao conflito."""
        entradas = [
            ("as pretas deve", "as pretas devem"),
            ("As pretas deve", "As pretas devem"),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_the_middle_rule_can_be_alive_and_the_last_dead(self):
        """Com tres variantes o vencedor e por REGRA, e nao do grupo: a
        primeira de caixa fixa vive, a insensivel vive, e o que vem depois dela
        morre."""
        entradas = [("Black", "x"), ("black", "y"), ("BLACK", "z")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertNotIn(0, conflitos)
        self.assertIn(2, conflitos)
        self.assertEqual(conflitos[2]["contexts"][0]["winner"], 1)

    def test_priority_revives_the_shadowed_rule(self):
        """A saida nao destrutiva: a prioridade poe a capitalizada na frente e
        as duas passam a valer (garantia S10)."""
        entradas = [("black", "pretas"), ("Black", "as pretas", "suggestion", 1)]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_keeping_a_rule_also_removes_the_exact_duplicate(self):
        """`group` nao e o conjunto em disputa: a duplicata exata nao e conflito
        (a vencedora produz o mesmo que ela), mas continua engolindo quem vem
        depois. Fora do grupo, "Manter esta" deixaria a escolhida morta."""
        entradas = [("x", "a"), ("x", "a"), ("x", "b")]
        conflitos = glossario.glossary_conflicts(entradas)

        self.assertEqual(conflitos[2]["group"], [0, 1, 2])
        mantidas = glossario.resolve_glossary_conflict(entradas, 2, conflitos)
        self.assertEqual(mantidas, [("x", "b")])
        self.assertEqual(glossario.glossary_conflicts(mantidas), {})

    def test_a_cleanup_rule_is_not_dragged_into_the_group(self):
        entradas = [("x", "a"), ("x", "b"), ("x", "c", "cleanup")]
        conflitos = glossario.glossary_conflicts(entradas)
        self.assertEqual(conflitos[0]["group"], [0, 1])


class UnknownRuleTypeTests(unittest.TestCase):
    """Tipo de regra desconhecido avisa (garantia S13, ROADMAP 14.6)."""

    def test_masculine_and_short_aliases_are_understood(self):
        """Faltavam, e sao o erro mais facil de cometer: a regra virava
        sugestao, deixava de rodar depois da API, e nada avisava."""
        for escrito in ("automático", "automatico", "auto", "AUTOMÁTICO"):
            with self.subTest(escrito=escrito):
                self.assertEqual(
                    glossario._normalize_rule_type(escrito),
                    glossario.GLOSSARY_RULE_AUTOMATIC,
                )
        self.assertEqual(
            glossario._normalize_rule_type("clean"), glossario.GLOSSARY_RULE_CLEANUP
        )

    def test_unknown_values_are_listed_once_each(self):
        desconhecidos = glossario.unknown_rule_types(
            [
                ("a", "b", "automático"),
                ("c", "d", "xyz"),
                ("e", "f", "xyz"),
                ("g", "h", "zzz"),
                ("i", "j"),
            ]
        )
        self.assertEqual(desconhecidos, ["xyz", "zzz"])

    def test_loading_a_file_with_a_bad_type_warns_and_degrades(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n"
            "    ('rook', 'torre', 'automatico'),\n"
            "    ('queen', 'dama', 'perto'),\n"
            "]\n",
            encoding="utf-8",
        )

        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        entradas = glossario.load_glossary_entry_details(
            str(caminho), prefer_db=False
        )

        # Degrada, como S5 manda: uma regra torta nao desliga as outras.
        self.assertEqual(
            [(o, n, t) for o, n, t, _p, _e in entradas],
            [
                ("rook", "torre", glossario.GLOSSARY_RULE_AUTOMATIC),
                ("queen", "dama", glossario.GLOSSARY_RULE_SUGGESTION),
            ],
        )
        # ...mas avisa, uma vez, dizendo qual valor nao foi entendido.
        self.assertEqual(len(avisos), 1)
        self.assertIn("'perto'", avisos[0])
        self.assertNotIn("automatico", avisos[0])


class SquarePlaceholderTests(unittest.TestCase):
    """O placeholder de casa (ROADMAP 14.7).

    1.235 das 7.105 regras enumeravam casas a mao, e a enumeracao manual tem o
    defeito de toda enumeracao manual: buracos. Sete familias paravam em 56
    regras — faltava a fileira 3 inteira.
    """

    def test_one_rule_becomes_sixty_four(self):
        regras = glossario.expand_square_placeholder(
            ("@casa@-torre", "torre de @casa@")
        )
        self.assertEqual(len(regras), 64)
        self.assertIn(("a1-torre", "torre de a1"), regras)
        self.assertIn(("e3-torre", "torre de e3"), regras)
        self.assertIn(("h8-torre", "torre de h8"), regras)

    def test_a_rule_without_the_placeholder_is_untouched(self):
        self.assertEqual(
            glossario.expand_square_placeholder(("rook", "torre")),
            [("rook", "torre")],
        )

    def test_priority_survives_the_expansion(self):
        regras = glossario.expand_square_placeholder(("@casa@ x", "y @casa@", 3))
        self.assertEqual(regras[0], ("a1 x", "y a1", 3))

    def test_the_original_decides_the_expansion(self):
        """Sem placeholder no original nao ha o que resolver: expandir daria 64
        regras iguais para um padrao unico, mudando o que a regra casa."""
        self.assertEqual(
            glossario.expand_square_placeholder(("torre", "torre de @casa@")),
            [("torre", "torre de @casa@")],
        )

    def test_loading_expands_and_the_editor_still_sees_one_entry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n"
            "    ('@casa@-torre', 'torre de @casa@'),\n"
            "]\n",
            encoding="utf-8",
        )

        entradas = glossario.load_glossary_entry_details(str(caminho), prefer_db=False)
        self.assertEqual(len(entradas), 1, "o editor edita a linha com o placeholder")

        regras = glossario.load_suggestion_substitutions(str(caminho))
        self.assertEqual(len(regras), 64)
        self.assertEqual(
            glossario.apply_all_substitutions("o e3-torre domina", regras),
            "o torre de e3 domina",
        )

    def test_the_real_glossary_uses_the_placeholder(self):
        """O colapso aconteceu: o arquivo versionado nao volta a enumerar casas.

        Falhar aqui significa que alguem reescreveu uma familia casa a casa —
        1.203 linhas de volta, com os buracos de volta junto.
        """
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        entradas = glossario.load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        com_placeholder = [
            orig
            for orig, _new, _tipo, _prio, _escopo in entradas
            if glossario.GLOSSARY_SQUARE_PLACEHOLDER in orig
        ]
        self.assertGreaterEqual(len(com_placeholder), 20)

        casa_literal = re.compile(r"\b[a-h][1-8]\b")
        enumeradas = [
            orig
            for orig, _new, _tipo, _prio, _escopo in entradas
            if casa_literal.search(orig)
        ]
        # Sobram so as 28 automaticas de peao, que ficaram literais de proposito
        # para nao mudar o tipo de 91 padroes (ROADMAP 14.7).
        self.assertLessEqual(len(enumeradas), 40)


class LanguageScopeTests(unittest.TestCase):
    """Escopo de idioma por regra (garantia S11, ROADMAP 15.1).

    O glossario era global: as regras que corrigem portugues rodavam sobre a
    traducao para o italiano tambem, e `('movimento', 'lance')` transformava
    `il movimento` em `il lance`.
    """

    def test_the_scope_names_the_target(self):
        self.assertTrue(glossario.scope_matches("pt", "en", "pt"))
        self.assertFalse(glossario.scope_matches("pt", "en", "it"))
        self.assertTrue(glossario.scope_matches("", "en", "it"), "sem escopo vale sempre")

    def test_the_pair_form_requires_both(self):
        self.assertTrue(glossario.scope_matches("en>pt", "en", "pt"))
        self.assertFalse(glossario.scope_matches("en>pt", "es", "pt"))

    def test_a_pair_scope_does_not_match_an_undeclared_source(self):
        """Em "Detectar" nao ha como afirmar que o original esta em ingles, e
        aplicar seria um palpite — a mesma escolha da correcao de lances (P3)."""
        self.assertFalse(glossario.scope_matches("en>pt", "", "pt"))

    def test_no_declared_pair_filters_nothing(self):
        """O comportamento de antes desta versao, e o que mantem de pe todo
        chamador que nao passa idioma."""
        self.assertTrue(glossario.scope_matches("pt", None, None))

    def test_star_and_empty_mean_the_same(self):
        self.assertEqual(glossario.normalize_glossary_scope("*"), "")
        self.assertEqual(glossario.normalize_glossary_scope(None), "")
        self.assertEqual(glossario.normalize_glossary_scope(" pt "), "pt")

    def test_the_portuguese_rule_no_longer_reaches_italian(self):
        """O dano medido que abriu a secao 15, agora com o escopo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "escopo = 'pt'\n"
            "substituicoes = [\n"
            "    ('movimento', 'lance', 'automatic'),\n"
            "    ('\\u00d7', 'x', 'automatic', 0, '*'),\n"
            "]\n",
            encoding="utf-8",
        )

        para_it = load_automatic_substitutions(
            str(caminho), source_language="en", target_language="it"
        )
        para_pt = load_automatic_substitutions(
            str(caminho), source_language="en", target_language="pt"
        )

        self.assertEqual(
            glossario.apply_all_substitutions("Il movimento della torre", para_it),
            "Il movimento della torre",
        )
        self.assertEqual(
            glossario.apply_all_substitutions("O movimento da torre", para_pt),
            "O lance da torre",
        )
        # A regra de notacao e global de proposito: `×` nao e portugues.
        self.assertEqual(
            glossario.apply_all_substitutions("N×d4", para_it), "Nxd4"
        )

    def test_a_file_without_the_declaration_behaves_exactly_as_before(self):
        """Retrocompatibilidade: sem `escopo`, toda regra vale para todo par."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
        )

        self.assertEqual(glossario.glossary_default_scope(str(caminho)), "")
        for destino in ("pt", "it", "ru"):
            with self.subTest(destino=destino):
                regras = load_suggestion_substitutions(
                    str(caminho), source_language="en", target_language=destino
                )
                self.assertEqual(regras, [("rook", "torre")])

    def test_the_declaration_is_one_line_and_the_rules_inherit_it(self):
        """O argumento do formato: declarar uma vez em vez de escrever `, 'pt'`
        em cinco mil e setecentas regras, que seria um diff do arquivo inteiro."""
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("×", "x", "automatic", 0, ""),
            ("bishop", "alfiere", "suggestion", 0, "it"),
        ]
        texto = glossario._serialize_entries(entradas, default_scope="pt")

        self.assertIn("escopo = 'pt'", texto)
        # Herda: o campo nao aparece.
        self.assertIn("    ('rook', 'torre'),\n", texto)
        # Discorda: aparece, e `'*'` e como se escreve "todo par".
        self.assertIn("('×', 'x', 'automatic', 0, '*'),", texto)
        self.assertIn("('bishop', 'alfiere', 'suggestion', 0, 'it'),", texto)

    def test_the_round_trip_through_the_file_preserves_every_scope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("×", "x", "automatic", 0, ""),
            ("bishop", "alfiere", "suggestion", 0, "it"),
        ]
        caminho.write_text(
            glossario._serialize_entries(entradas, default_scope="pt"),
            encoding="utf-8",
        )

        relidas = load_glossary_entry_details(
            str(caminho), deduplicate=False, prefer_db=False
        )
        self.assertEqual(relidas, entradas)

    def test_saving_an_entry_keeps_the_file_declaration(self):
        """Sem isto, a primeira gravacao pela janela apagaria o `escopo = 'pt'` e
        as milhares de regras portuguesas voltariam a ser globais."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "escopo = 'pt'\nsubstituicoes = [\n    ('rook', 'torre'),\n]\n",
            encoding="utf-8",
        )

        glossario.add_glossary_entry("queen", "dama", path=str(caminho))

        texto = caminho.read_text(encoding="utf-8")
        self.assertIn("escopo = 'pt'", texto)
        relidas = load_glossary_entry_details(
            str(caminho), deduplicate=False, prefer_db=False
        )
        self.assertEqual(
            relidas,
            [
                ("rook", "torre", "suggestion", 0, "pt"),
                ("queen", "dama", "suggestion", 0, "pt"),
            ],
            "a entrada nova herda o padrao do arquivo",
        )

    def test_the_scope_survives_the_round_trip_through_the_database(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "glossario.db"
        sync_glossary_database(
            [("rook", "torre", "suggestion", 0, "pt")], db_path=str(db)
        )
        self.assertEqual(
            load_glossary_entry_details_from_db(str(db)),
            [("rook", "torre", "suggestion", 0, "pt")],
        )

    def test_the_csv_carries_the_scope_and_tolerates_its_absence(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        csv_path = Path(tmp.name) / "g.csv"
        glossario.export_glossary_csv(
            str(csv_path), entries=[("rook", "torre", "suggestion", 0, "pt")]
        )
        self.assertEqual(
            glossario.read_glossary_csv(str(csv_path)),
            [("rook", "torre", "suggestion", 0, "pt")],
        )

        sem_coluna = Path(tmp.name) / "antigo.csv"
        sem_coluna.write_text(
            "original,replacement\nrook,torre\n", encoding="utf-8"
        )
        self.assertEqual(
            glossario.read_glossary_csv(str(sem_coluna)),
            [("rook", "torre", "suggestion", 0, "")],
        )

    def test_rules_for_different_targets_do_not_conflict(self):
        """Elas nunca sao carregadas juntas, entao acusa-las de conflito seria
        descrever uma briga que nao acontece."""
        entradas = [
            ("rook", "torre", "suggestion", 0, "pt"),
            ("rook", "tour", "suggestion", 0, "fr"),
        ]
        self.assertEqual(glossario.glossary_conflicts(entradas), {})

    def test_an_unscoped_rule_still_conflicts_with_a_scoped_one(self):
        """Escopo vazio cruza com todos: a regra global alcanca o par da outra."""
        entradas = [
            ("rook", "torre", "suggestion", 0, ""),
            ("rook", "tour", "suggestion", 0, "fr"),
        ]
        self.assertEqual(sorted(glossario.glossary_conflicts(entradas)), [0, 1])

    def test_an_unknown_scope_language_warns_instead_of_going_global(self):
        """Degradar para "vale para todos" espalharia a regra em vez de
        limita-la, que e o oposto do que a intencao diz."""
        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name) / "Substituicoes.txt"
        caminho.write_text(
            "substituicoes = [\n    ('rook', 'torre', 'suggestion', 0, 'ptt'),\n]\n",
            encoding="utf-8",
        )

        entradas = load_glossary_entry_details(str(caminho), prefer_db=False)
        self.assertEqual(glossario.glossary_entry_scope(entradas[0]), "ptt")
        self.assertTrue(any("ptt" in aviso for aviso in avisos))
        # E ela nao casa par nenhum: fica muda, e o aviso e o que a denuncia.
        self.assertEqual(
            load_suggestion_substitutions(
                str(caminho), source_language="en", target_language="pt"
            ),
            [],
        )

    def test_the_real_glossary_declares_the_portuguese_scope(self):
        """O acervo versionado esta escopado. Falhar aqui significa que o
        `escopo = 'pt'` saiu do arquivo, e as milhares de regras portuguesas
        voltaram a alcancar as traducoes para os outros seis idiomas."""
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            self.skipTest("Substituicoes.txt nao esta neste checkout")

        self.assertEqual(glossario.glossary_default_scope(str(path)), "pt")

        entradas = load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        escopos = {glossario.glossary_entry_scope(e) for e in entradas}
        self.assertEqual(escopos, {"pt", ""}, "so 'pt' e as globais de notacao")

        # As globais sao notacao, e nao lingua: nenhuma delas tem letra acentuada
        # nem palavra portuguesa.
        globais = [
            glossario.glossary_entry_pair(e)[0]
            for e in entradas
            if not glossario.glossary_entry_scope(e)
        ]
        self.assertLessEqual(len(globais), 25)
        self.assertIn("×", globais)


class SeedGlossaryTests(unittest.TestCase):
    """O dicionario-semente (garantia S15, ROADMAP 15.2)."""

    def seed_path(self):
        return (
            Path(__file__).resolve().parent.parent
            / "tradutor_pgn"
            / "Substituicoes-semente.txt"
        )

    def test_the_seed_ships_with_the_program(self):
        caminho = self.seed_path()
        self.assertTrue(caminho.exists(), "a semente vem com o programa")
        entradas = glossario.load_seed_entries(str(caminho))
        self.assertGreater(len(entradas), 100)

    def test_every_seed_rule_is_scoped_and_a_suggestion(self):
        """Sem escopo, uma regra da semente para o italiano alcancaria o
        portugues — o defeito que a secao 15 existe para fechar. E `suggestion`
        porque a semente e um palpite generico sobre a terminologia de quem usa.
        """
        for entry in glossario.load_seed_entries(str(self.seed_path())):
            orig, _new = glossario.glossary_entry_pair(entry)
            with self.subTest(orig=orig):
                self.assertTrue(glossario.glossary_entry_scope(entry))
                self.assertEqual(
                    glossario.glossary_entry_type(entry),
                    glossario.GLOSSARY_RULE_SUGGESTION,
                )

    def test_no_seed_scope_names_an_unknown_language(self):
        entradas = glossario.load_seed_entries(str(self.seed_path()))
        self.assertEqual(glossario.unknown_scope_languages(entradas), [])

    def test_the_seed_gives_terminology_to_a_language_that_had_none(self):
        """Cinco idiomas tinham ZERO regras. Agora tem o nucleo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vazio = Path(tmp.name) / "Substituicoes.txt"
        vazio.write_text("substituicoes = []\n", encoding="utf-8")

        for destino, esperado in (("it", "alfiere"), ("de", "Läufer"), ("ru", "слон")):
            with self.subTest(destino=destino):
                regras = load_interactive_substitutions(
                    str(vazio),
                    source_language="en",
                    target_language=destino,
                    seed_path=str(self.seed_path()),
                )
                self.assertIn(("bishop", esperado), [(r[0], r[1]) for r in regras])

    def test_the_user_rule_always_wins(self):
        """Garantia S15: para o mesmo padrao no mesmo escopo, a semente sai."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n"
            "    ('bishop', 'o meu bispo', 'suggestion', 0, 'it'),\n"
            "]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        para_bishop = [r[1] for r in regras if r[0] == "bishop"]
        self.assertEqual(para_bishop, ["o meu bispo"])

    def test_an_unscoped_user_rule_also_beats_the_seed(self):
        """Uma decisao que vale para todo par vence a semente do par especifico:
        o usuario disse "sempre assim", e a semente e o palpite."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n    ('bishop', 'sempre assim'),\n]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        self.assertEqual([r[1] for r in regras if r[0] == "bishop"], ["sempre assim"])

    def test_the_seed_yields_on_a_case_difference_too(self):
        """A licao de S12: uma semente em minusculas engoliria a versao
        capitalizada do usuario sem que nada dissesse."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n"
            "    ('Bishop', 'O Meu Bispo', 'suggestion', 0, 'it'),\n"
            "]\n",
            encoding="utf-8",
        )

        regras = load_interactive_substitutions(
            str(do_usuario),
            source_language="en",
            target_language="it",
            seed_path=str(self.seed_path()),
        )
        self.assertEqual(
            [(r[0], r[1]) for r in regras if r[0].casefold() == "bishop"],
            [("Bishop", "O Meu Bispo")],
        )

    def test_a_broken_seed_does_not_stop_the_user_glossary(self):
        """A semente e conveniencia: um defeito nela nao pode desligar o
        glossario de quem usa. Mas tambem nao pode ser silencioso — ela vem com
        o programa, entao o defeito e nosso."""
        avisos = []
        glossario.set_glossary_error_handler(avisos.append)
        self.addCleanup(glossario.set_glossary_error_handler, None)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        quebrada = Path(tmp.name) / "semente.txt"
        quebrada.write_text("isto nao e python {{{", encoding="utf-8")
        do_usuario = Path(tmp.name) / "Substituicoes.txt"
        do_usuario.write_text(
            "substituicoes = [\n    ('rook', 'torre'),\n]\n", encoding="utf-8"
        )

        entradas = load_glossary_entry_details(str(do_usuario), prefer_db=False)
        regras = glossario._seed_rules_for(
            entradas,
            {glossario.GLOSSARY_RULE_SUGGESTION},
            source_language="en",
            target_language="pt",
            seed_path=str(quebrada),
        )
        self.assertEqual(regras, [])
        self.assertTrue(any("semente" in aviso for aviso in avisos))


class CuratedGlossaryTests(unittest.TestCase):
    """O que a curadoria da secao 14 corrigiu no `Substituicoes.txt` real.

    Cada asserto fixa uma decisao de xadrez, nao uma linha de codigo: sem
    isto, a proxima edicao do glossario pode desfazer a correcao sem que nada
    acuse.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / "Substituicoes.txt"
        if not path.exists():  # pragma: no cover - checkout sem o glossario
            raise unittest.SkipTest("Substituicoes.txt nao esta neste checkout")
        cls.entradas = glossario.load_glossary_entry_details(
            str(path), deduplicate=False, prefer_db=False
        )
        cls.por_padrao = {}
        for orig, new, tipo, prio, _escopo in cls.entradas:
            cls.por_padrao.setdefault(orig, []).append((new, tipo, prio))

    def substituicoes(self, padrao):
        return [new for new, _tipo, _prio in self.por_padrao.get(padrao, [])]

    def test_the_evaluation_symbols_name_the_right_side(self):
        """`=/+` (⩱) e vantagem das PRETAS. O arquivo dava a mesma leitura para
        ele e para `+/=`, entao metade das avaliacoes saia invertida."""
        self.assertEqual(
            self.substituicoes("=/+"), ["com leve superioridade para as pretas"]
        )
        self.assertEqual(
            self.substituicoes("+/="), ["as brancas têm leve superioridade"]
        )
        self.assertEqual(
            self.substituicoes("-+"), ["com vantagem decisiva das pretas"]
        )
        self.assertEqual(
            self.substituicoes("+-"), ["com vantagem decisiva das brancas"]
        )

    def test_castling_is_a_noun_and_back_rank_is_the_last_one(self):
        self.assertEqual(self.substituicoes("castling"), ["roque"])
        self.assertEqual(self.substituicoes("back rank"), ["última fila"])
        self.assertEqual(self.substituicoes("back-rank"), ["última fila"])

    def test_the_rules_that_broke_portuguese_are_gone(self):
        """Medidas, nao supostas: cada uma corrompeu uma frase de teste real.

        As que o relatorio inicial acusava e a fronteira de palavra protegia
        (`the`, `if`, `with`, `by`) ficaram — nenhuma delas e palavra
        portuguesa, e nenhuma corrompeu frase nenhuma.
        """
        for padrao in ("for", "por", "#", "luz", "negro"):
            with self.subTest(padrao=padrao):
                self.assertEqual(self.por_padrao.get(padrao, []), [])

    def test_rank_and_file_are_not_inverted_anymore(self):
        """As genericas convertiam toda 'fileira' em 'coluna'; as precisas
        alcancam so o que vem depois de uma letra de coluna."""
        self.assertEqual(self.por_padrao.get("-fileira", []), [])
        self.assertEqual(self.substituicoes("e-fileira"), ["coluna e"])

    def test_the_junk_deletion_rules_are_cleanup(self):
        """Apagar lixo de conversao e trabalho de limpeza: roda antes da API, e
        assim para de pagar traducao de lixo (garantia S14)."""
        delecoes = [
            (orig, tipo)
            for orig, new, tipo, _prio, _escopo in self.entradas
            if not new
        ]
        self.assertTrue(delecoes)
        for orig, tipo in delecoes:
            with self.subTest(orig=orig):
                self.assertEqual(tipo, glossario.GLOSSARY_RULE_CLEANUP)

    def test_no_rule_returns_what_it_found(self):
        for orig, new, _tipo, _prio, _escopo in self.entradas:
            if orig:
                with self.subTest(orig=orig):
                    self.assertNotEqual(orig, new)

    def test_the_priority_field_is_finally_in_use(self):
        """A prioridade existia desde o item 1.5 e nunca havia sido usada em
        regra nenhuma das 7.105. A que a usa e `('Black', 'as pretas')`, que
        estava morta: o artigo e gramatica, e a prioridade a revive sem apagar
        a concorrente."""
        priorizadas = [
            (orig, new, prio)
            for orig, new, _tipo, prio, _escopo in self.entradas
            if prio != glossario.GLOSSARY_PRIORITY_DEFAULT
        ]
        self.assertIn(("Black", "as pretas", 1), priorizadas)


# ===========================================================================
# Secao 17 — guardas e navegacao: onde o programa errava em silencio
# ===========================================================================


class LikeEscapeTests(unittest.TestCase):
    """Buscar `[%eval` no modo "Trecho" devolvia lixo (ROADMAP 17.8).

    O `LIKE` era montado sem `ESCAPE`, entao `%` e `_` do texto digitado viravam
    curinga — e a busca mais natural do dominio e uma tag de comando, que COMECA
    com `%`.
    """

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = Path(sandbox.name) / "cache.db"
        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "Boa jogada [%eval +0.35]", "Boa jogada [%eval +0.35]", "pt")
        save_translation(cur, "Erro de calculo aqui", "Erro de calculo aqui", "pt")
        save_translation(cur, "Ameaca dupla no centro", "Ameaca dupla no centro", "pt")
        conn.commit()
        return cur

    def busca(self, cur, texto):
        return [
            linha[1]
            for linha in fetch_review_rows(
                cur, "pt", search_text=texto, search_mode=SEARCH_MODE_SUBSTRING
            )
        ]

    def test_the_escape_helper_neutralizes_the_three_characters(self):
        self.assertEqual(escape_like_pattern("100%"), "100\\%")
        self.assertEqual(escape_like_pattern("a_b"), "a\\_b")
        self.assertEqual(escape_like_pattern("[%eval"), "[\\%eval")

    def test_the_backslash_is_escaped_first(self):
        """Escapando `%` antes da barra, as barras recem-inseridas seriam
        escapadas de novo e o padrao passaria a procurar a propria barra."""
        self.assertEqual(escape_like_pattern("\\%"), "\\\\\\%")

    def test_searching_for_a_command_tag_finds_only_it(self):
        """O bug: `[%eval` casava `[` + qualquer coisa + `eval`."""
        cur = self.banco()
        self.assertEqual(self.busca(cur, "[%eval"), ["Boa jogada [%eval +0.35]"])

    def test_a_lone_percent_no_longer_matches_everything(self):
        cur = self.banco()
        self.assertEqual(self.busca(cur, "%"), ["Boa jogada [%eval +0.35]"])

    def test_the_underscore_is_literal_too(self):
        cur = self.banco()
        self.assertEqual(self.busca(cur, "a_b"), [])

    def test_ordinary_searches_keep_working(self):
        cur = self.banco()
        self.assertEqual(self.busca(cur, "calculo"), ["Erro de calculo aqui"])

    def test_counting_and_listing_agree_under_the_escape(self):
        """A contagem e a lista usam o mesmo `WHERE`; escapar em um so faria a
        paginacao andar por um numero que a tela nao mostra (garantia R5)."""
        cur = self.banco()
        for texto in ("[%eval", "%", "a_b", "calculo"):
            with self.subTest(texto=texto):
                self.assertEqual(
                    count_review_rows(
                        cur, "pt", search_text=texto, search_mode=SEARCH_MODE_SUBSTRING
                    ),
                    len(self.busca(cur, texto)),
                )


class BulkVerificationPreviewTests(unittest.TestCase):
    """Garantia V1: a verificacao em massa diz o que vai marcar, por original."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = Path(sandbox.name) / "cache.db"
        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()
        # O caso que doi: duas frases diferentes com a MESMA traducao curta, uma
        # delas errada. Verificar a legitima marcava a errada junto.
        save_translation(cur, "Draw.", "Empate.", "pt", "en")
        save_translation(cur, "Checkmate.", "Empate.", "pt", "en")
        save_translation(cur, "Tablas.", "Empate.", "pt", "es")
        save_translation(cur, "Good move.", "Bom lance.", "pt", "en")
        conn.commit()
        return cur

    def id_de(self, cur, original):
        return cur.execute(
            "SELECT id FROM comments WHERE original_comment = ?", (original,)
        ).fetchone()[0]

    def test_the_candidates_name_the_other_originals(self):
        cur = self.banco()
        candidatas = fetch_exact_translation_match_candidates(
            cur, self.id_de(cur, "Draw.")
        )
        self.assertEqual([orig for _id, orig in candidatas], ["Checkmate."])

    def test_the_candidates_never_include_the_open_row(self):
        """Ela e marcada pela acao direta do usuario; contar a escolha dele junto
        com as consequencias dela faria o numero dizer uma coisa a mais."""
        cur = self.banco()
        row_id = self.id_de(cur, "Draw.")
        self.assertNotIn(
            row_id, [i for i, _o in fetch_exact_translation_match_candidates(cur, row_id)]
        )

    def test_the_candidates_stay_inside_the_pair(self):
        """`Tablas.` tem a mesma traducao, e vem do espanhol (garantia R9)."""
        cur = self.banco()
        candidatas = fetch_exact_translation_match_candidates(
            cur, self.id_de(cur, "Draw.")
        )
        self.assertNotIn("Tablas.", [orig for _id, orig in candidatas])

    def test_a_translation_that_repeats_nowhere_has_no_candidates(self):
        cur = self.banco()
        self.assertEqual(
            fetch_exact_translation_match_candidates(cur, self.id_de(cur, "Good move.")),
            [],
        )

    def test_an_empty_translation_propagates_to_nothing(self):
        cur = self.banco()
        save_translation(cur, "Sem traducao ainda.", "", "pt", "en")
        self.assertEqual(
            fetch_exact_translation_match_candidates(
                cur, self.id_de(cur, "Sem traducao ainda.")
            ),
            [],
        )

    def test_only_ids_restricts_what_is_written(self):
        """Os ids sao os que a previa mostrou: uma linha gravada pelo worker
        enquanto o dialogo esta aberto nao entra — o usuario nao a viu.

        A linha aberta (`Draw.`) tambem fica de fora, e nao por descuido: quem a
        verifica e o `update_translation_by_id` do editor, na acao direta do
        usuario, antes de esta propagacao ser sequer oferecida.
        """
        cur = self.banco()
        origem = self.id_de(cur, "Draw.")
        save_translation(cur, "Remis.", "Empate.", "pt", "en")
        aprovadas = [self.id_de(cur, "Checkmate.")]

        self.assertEqual(
            set_exact_translation_matches_verified(cur, origem, only_ids=aprovadas), 1
        )
        self.assertEqual(
            dict(
                cur.execute(
                    "SELECT original_comment, verified FROM comments"
                    " WHERE translated_comment = 'Empate.' AND source_language = 'en'"
                ).fetchall()
            ),
            {"Draw.": 0, "Checkmate.": 1, "Remis.": 0},
        )

    def test_without_only_ids_the_whole_pair_is_verified(self):
        """A chamada sem previa mantem o comportamento de sempre, a linha aberta
        inclusive: usada assim, excluir-la deixaria o par metade verificado."""
        cur = self.banco()

        self.assertEqual(
            set_exact_translation_matches_verified(cur, self.id_de(cur, "Draw.")), 2
        )
        self.assertEqual(
            dict(
                cur.execute(
                    "SELECT original_comment, verified FROM comments"
                    " WHERE translated_comment = 'Empate.' AND source_language = 'en'"
                ).fetchall()
            ),
            {"Draw.": 1, "Checkmate.": 1},
        )

    def test_an_empty_approval_writes_nothing(self):
        cur = self.banco()
        self.assertEqual(
            set_exact_translation_matches_verified(
                cur, self.id_de(cur, "Draw."), only_ids=[]
            ),
            0,
        )

    def test_the_message_shows_the_originals_and_not_just_a_count(self):
        """"N iguais" descreve as traducoes, e por isso nao alarmava ninguem: o
        que esta sendo dado por revisado sao N originais diferentes."""
        texto = format_propagation_confirmation(
            "Empate.", [(7, "Checkmate."), (9, "Resign.")]
        )
        self.assertIn("2 original(is) diferente(s)", texto)
        self.assertIn("Checkmate.", texto)
        self.assertIn("Resign.", texto)
        self.assertIn("Empate.", texto)

    def test_the_message_caps_the_list_and_says_how_many_are_left(self):
        candidatas = [(i, f"Original {i}") for i in range(20)]
        texto = format_propagation_confirmation("Igual.", candidatas, limit=3)
        self.assertIn("Original 0", texto)
        self.assertNotIn("Original 9", texto)
        self.assertIn("mais 17", texto)


class MoveNotationLabelPreviewTests(unittest.TestCase):
    """A previa de "Corrigir Lances" escondia a parte irreversivel (17.5)."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = Path(sandbox.name) / "cache.db"
        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        return conn

    def test_it_counts_the_rows_without_a_source_language(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The rook Rf8.", "A torre Rf8.", "pt")
        save_translation(cur, "The king Kf1.", "O rei Kf1.", "pt")
        save_translation(cur, "Ja rotulada.", "Ja rotulada.", "pt", "en")
        save_translation(cur, "Outro destino.", "Outro destino.", "en")
        conn.commit()

        self.assertEqual(count_adoptable_unknown_source(cur, "pt", "en"), 2)

    def test_a_row_that_would_collide_is_not_counted(self):
        """O `UPDATE OR IGNORE` pula a linha cuja adocao esbarraria na chave. Um
        teto no lugar do numero exato seria pior que nenhum numero: e uma
        confirmacao que nao tem volta."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "Mesmo texto.", "Traducao legada.", "pt")
        save_translation(cur, "Mesmo texto.", "Traducao declarada.", "pt", "en")
        save_translation(cur, "Texto sozinho.", "Sozinho.", "pt")
        conn.commit()

        self.assertEqual(count_adoptable_unknown_source(cur, "pt", "en"), 1)
        # E o numero bate com o que a adocao de verdade faz.
        self.assertEqual(adopt_unknown_source_language(cur, "pt", "en", None), 1)

    def test_detecting_labels_nothing(self):
        """"Detectar automaticamente" nao e uma declaracao."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "Sem origem.", "Sem origem.", "pt")
        conn.commit()

        self.assertEqual(count_adoptable_unknown_source(cur, "pt", ""), 0)

    def test_the_analysis_reports_the_label_count(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The rook Rf8 holds.", "A torre Rf8 segura.", "pt")
        conn.commit()

        stats = analyze_move_notation_updates(
            cur, "en", "pt", fix_move_notation
        )
        self.assertEqual(stats["labeled"], 1)

    def test_without_the_legacy_rows_in_scope_nothing_is_labeled(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The rook Rf8 holds.", "A torre Rf8 segura.", "pt")
        conn.commit()

        stats = analyze_move_notation_updates(
            cur, "en", "pt", fix_move_notation, include_unknown=False
        )
        self.assertEqual(stats["labeled"], 0)


class BackupDoesNotMigrateTests(unittest.TestCase):
    """Um backup copia o que esta la, como esta (ROADMAP 17.6).

    `create_database_backup` abria a origem com `initialize_database`, que roda a
    migracao de schema e o backfill: o "backup de seguranca" pre-restauracao
    ALTERAVA o banco de trabalho antes de copia-lo. Se a migracao fosse a causa
    do problema que o usuario quer desfazer, nao havia mais volta.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "traducoes.db"
        _schema3_database(self.db_path)

    def versao(self, path):
        conn = sqlite3.connect(str(path))
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    def colunas(self, path):
        conn = sqlite3.connect(str(path))
        try:
            return [row[1] for row in conn.execute("PRAGMA table_info(comments)")]
        finally:
            conn.close()

    def test_the_source_is_left_in_the_schema_it_was(self):
        create_database_backup(str(self.db_path))

        self.assertEqual(self.versao(self.db_path), 3)
        self.assertNotIn("source_language", self.colunas(self.db_path))

    def test_the_copy_is_the_old_schema_too(self):
        """Migrar a copia seria igualmente errado: o backup deixaria de ser o
        estado que o usuario quer poder recuperar."""
        backup_path = create_database_backup(str(self.db_path))

        self.assertEqual(self.versao(backup_path), 3)
        self.assertNotIn("source_language", self.colunas(backup_path))

    def test_the_journal_mode_of_the_source_is_not_changed_either(self):
        """`open_database` grava `WAL` no arquivo. Ler para copiar nao precisa
        disso, e um backup nao pode reconfigurar o original."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = delete")
        conn.close()

        create_database_backup(str(self.db_path))

        conn = sqlite3.connect(str(self.db_path))
        try:
            modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(modo.lower(), "delete")

    def test_the_content_still_arrives_in_the_copy(self):
        """A defesa contra "nao migrar" virar "nao copiar"."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO comments (original_comment, translated_comment,"
            " target_language) VALUES (?, ?, ?)",
            ("the rook", "a torre", "pt"),
        )
        conn.commit()
        conn.close()

        backup_path = create_database_backup(str(self.db_path))

        conn = sqlite3.connect(backup_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                ).fetchall(),
                [("the rook", "a torre")],
            )
        finally:
            conn.close()

    def test_restoring_still_migrates_the_restored_database(self):
        """A migracao continua acontecendo onde ela deve: no banco de trabalho,
        depois da restauracao. So o backup e que nao a provoca."""
        backup_path = create_database_backup(str(self.db_path), prune=False)
        alvo = self.base / "trabalho.db"
        _schema3_database(alvo)

        restore_database_from_backup(str(alvo), backup_path)

        self.assertEqual(self.versao(alvo), SCHEMA_VERSION)
        self.assertIn("source_language", self.colunas(alvo))


class TranslationCsvOverwriteTests(unittest.TestCase):
    """O CSV era somente-exportacao na pratica (ROADMAP 17.7).

    Exportar, corrigir 300 traducoes na planilha e importar nao fazia NADA: a
    gravacao respeita T1, entao toda linha voltava como "Sem alteracao".
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "traducoes.db"

        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "The rook", "a torre errada", "pt", "en")
        save_translation(cur, "The king", "o rei", "pt", "en")
        conn.commit()
        conn.close()

    def csv_com(self, linhas):
        caminho = self.base / "traducoes.csv"
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["original_comment", "translated_comment", "source_language",
                 "target_language", "verified"]
            )
            writer.writerows(linhas)
        return str(caminho)

    def linhas(self):
        conn = initialize_database(str(self.db_path))
        try:
            return {
                orig: (trad, verificada)
                for orig, trad, verificada in conn.execute(
                    "SELECT original_comment, translated_comment, verified FROM comments"
                )
            }
        finally:
            conn.close()

    def historico(self, original):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                """
                SELECT h.action, h.previous_translation, h.new_translation
                FROM comment_history h
                JOIN comments c ON c.id = h.comment_id
                WHERE c.original_comment = ?
                ORDER BY h.id
                """,
                (original,),
            ).fetchall()
        finally:
            conn.close()

    # ------------------------------------------------------------- a previa

    def test_the_preview_counts_what_the_default_mode_would_skip(self):
        caminho = self.csv_com(
            [
                ["The rook", "a torre", "en", "pt", ""],
                ["The king", "o rei", "en", "pt", ""],
                ["The bishop", "o bispo", "en", "pt", ""],
            ]
        )

        preview_stats = analyze_translations_csv_import(str(self.db_path), caminho)

        self.assertEqual(preview_stats["inserted"], 1)
        self.assertEqual(preview_stats["unchanged"], 2)
        self.assertEqual(preview_stats["overwritable"], 1, "so 'The rook' difere")

    def test_the_preview_says_how_many_of_them_are_verified(self):
        """Sobrescrever uma linha revisada apaga revisao humana — a unica parte
        desta operacao que o backup nao devolve de graca."""
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        set_translation_verified_by_id(
            cur,
            cur.execute(
                "SELECT id FROM comments WHERE original_comment = 'The rook'"
            ).fetchone()[0],
            True,
        )
        conn.commit()
        conn.close()

        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])
        preview_stats = analyze_translations_csv_import(str(self.db_path), caminho)

        self.assertEqual(preview_stats["overwritable_verified"], 1)

    def test_the_preview_text_names_the_difference(self):
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])
        texto = format_import_preview(
            analyze_translations_csv_import(str(self.db_path), caminho)
        )

        self.assertIn("DIFEREM", texto)
        self.assertIn("1 traducao(oes)", texto)

    def test_with_nothing_to_overwrite_the_text_says_t1_holds(self):
        caminho = self.csv_com([["The rook", "a torre errada", "en", "pt", ""]])
        texto = format_import_preview(
            analyze_translations_csv_import(str(self.db_path), caminho)
        )

        self.assertIn("nao serao sobrescritas", texto)
        self.assertNotIn("DIFEREM", texto)

    # ------------------------------------------------------- a importacao

    def test_by_default_nothing_is_overwritten(self):
        """T1 continua sendo o padrao: sobrescrever passa a ser uma decisao."""
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])

        stats = import_translations_from_csv(
            str(self.db_path), caminho, backup_dir=str(self.base / "backups")
        )

        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(stats["overwritten"], 0)
        self.assertEqual(self.linhas()["The rook"][0], "a torre errada")

    def test_asking_to_overwrite_writes_the_corrected_text(self):
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])

        stats = import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(stats["overwritten"], 1)
        self.assertEqual(stats["unchanged"], 0)
        self.assertEqual(self.linhas()["The rook"][0], "a torre")

    def test_identical_text_is_not_an_overwrite(self):
        """Num CSV exportado e corrigido em parte, o igual e a grande maioria:
        contar essas linhas inflaria o numero do dialogo."""
        caminho = self.csv_com([["The king", "o rei", "en", "pt", ""]])

        stats = import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(stats["overwritten"], 0)
        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(self.historico("The king"), [])

    def test_overwriting_records_the_history(self):
        """Garantia R2: o usuario precisa poder ver o que a importacao passou
        por cima e voltar atras."""
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])

        import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(
            self.historico("The rook"),
            [("csv_overwrite", "a torre errada", "a torre")],
        )

    def test_overwriting_reevaluates_the_quality_warning(self):
        """Garantia R6: o texto mudou, e a coluna materializada nao pode
        divergir do que a avaliacao em Python diria."""
        caminho = self.csv_com([["The rook", "The rook", "en", "pt", ""]])

        import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        conn = initialize_database(str(self.db_path))
        try:
            aviso = conn.execute(
                "SELECT quality_warning FROM comments WHERE original_comment = 'The rook'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(aviso, 1, "traducao igual ao original e um aviso QA")

    def test_overwriting_sends_the_row_back_to_pending(self):
        """A revisao era do texto anterior. Manter a marca sobre um texto que
        ninguem leu e o que R9 e V1 existem para impedir."""
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        set_translation_verified_by_id(
            cur,
            cur.execute(
                "SELECT id FROM comments WHERE original_comment = 'The rook'"
            ).fetchone()[0],
            True,
        )
        conn.commit()
        conn.close()

        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])
        import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(self.linhas()["The rook"], ("a torre", 0))

    def test_the_csv_can_say_the_overwritten_row_is_verified(self):
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", "1"]])

        stats = import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(self.linhas()["The rook"], ("a torre", 1))
        self.assertEqual(stats["verified_applied"], 1)

    def test_a_verified_flag_alone_promotes_an_existing_row(self):
        """A outra metade do beco: o `verified` editado na planilha era
        descartado em silencio porque so linhas inseridas ou preenchidas o
        recebiam."""
        caminho = self.csv_com([["The king", "o rei", "en", "pt", "1"]])

        stats = import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(self.linhas()["The king"], ("o rei", 1))
        self.assertEqual(stats["verified_applied"], 1)
        self.assertEqual(stats["unchanged"], 1, "promover nao e sobrescrever")

    def test_a_missing_verified_column_never_demotes_anything(self):
        """Um CSV montado a mao nao tem a coluna, e a ausencia dela nao e uma
        afirmacao de que nada foi revisado."""
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        set_translation_verified_by_id(
            cur,
            cur.execute(
                "SELECT id FROM comments WHERE original_comment = 'The king'"
            ).fetchone()[0],
            True,
        )
        conn.commit()
        conn.close()

        caminho = self.base / "sem-coluna.csv"
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["original_comment", "translated_comment", "source_language",
                 "target_language"]
            )
            writer.writerow(["The king", "o rei", "en", "pt"])

        import_translations_from_csv(
            str(self.db_path),
            str(caminho),
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertEqual(self.linhas()["The king"], ("o rei", 1))

    def test_the_preview_counts_the_promotions_the_overwrite_mode_would_do(self):
        caminho = self.csv_com([["The king", "o rei", "en", "pt", "1"]])

        preview_stats = analyze_translations_csv_import(str(self.db_path), caminho)

        self.assertEqual(preview_stats["verified_on_existing"], 1)
        self.assertEqual(
            preview_stats["verified_applied"], 0, "no padrao, nada e aplicado"
        )

    def test_a_backup_comes_before_the_overwrite(self):
        caminho = self.csv_com([["The rook", "a torre", "en", "pt", ""]])

        stats = import_translations_from_csv(
            str(self.db_path),
            caminho,
            backup_dir=str(self.base / "backups"),
            overwrite_existing=True,
        )

        self.assertTrue(Path(stats["backup_path"]).exists())
        conn = sqlite3.connect(stats["backup_path"])
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT translated_comment FROM comments"
                    " WHERE original_comment = 'The rook'"
                ).fetchone()[0],
                "a torre errada",
                "o backup tem de ter o texto de ANTES",
            )
        finally:
            conn.close()

    def test_the_row_level_overwrite_refuses_identical_text(self):
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        row_id = cur.execute(
            "SELECT id FROM comments WHERE original_comment = 'The king'"
        ).fetchone()[0]

        self.assertEqual(overwrite_translation_by_id(cur, row_id, "o rei"), 0)
        self.assertEqual(overwrite_translation_by_id(cur, row_id, "o rei novo"), 1)
        conn.close()

    def test_the_row_level_overwrite_on_a_missing_id_writes_nothing(self):
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        self.assertEqual(overwrite_translation_by_id(cur, 999999, "qualquer"), 0)
        conn.close()


class GeneratedSuffixWithCollisionTests(unittest.TestCase):
    """`game-BR-2.pgn` nao era reconhecido como gerado (ROADMAP 17.10).

    Confirmado: a terceira execucao sobre a mesma pasta pegava aquele arquivo
    como ENTRADA, traduzia portugues para portugues e produzia
    `game-BR-2-BR.pgn` — e cada execucao seguinte acrescentava mais um.
    """

    def test_the_collision_suffix_is_stripped(self):
        self.assertEqual(strip_generated_suffix("game-BR"), "game")
        self.assertEqual(strip_generated_suffix("game-BR-2"), "game")
        self.assertEqual(strip_generated_suffix("game-BR-17"), "game")

    def test_a_generated_file_with_a_collision_suffix_is_recognized(self):
        for nome in ("game-BR-2.pgn", "game-EN-3.pgn", "partida-br-2.pgn"):
            with self.subTest(nome=nome):
                self.assertTrue(is_generated_pgn(nome))

    def test_an_ordinary_numbered_name_is_left_alone(self):
        """`torneio-2.pgn` e um arquivo do usuario: nao tem sufixo de idioma."""
        self.assertEqual(strip_generated_suffix("torneio-2"), "torneio-2")
        self.assertFalse(is_generated_pgn("torneio-2.pgn"))
        self.assertFalse(is_generated_pgn("game-2.pgn"))

    def test_the_scan_of_a_folder_skips_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("game.pgn", "game-BR.pgn", "game-BR-2.pgn"):
                (base / nome).write_text("[Event \"T\"]\n", encoding="utf-8")

            arquivos, ignorados = collect_pgn_files(str(base), False)

            self.assertEqual([os.path.basename(a) for a in arquivos], ["game.pgn"])
            self.assertEqual(ignorados, 2)

    def test_the_normalizer_recognizes_its_own_collision_output(self):
        for nome in ("game-NORM.pgn", "game-NORM-2.pgn", "game-norm-3.pgn"):
            with self.subTest(nome=nome):
                self.assertTrue(is_normalized_pgn(nome))
        self.assertFalse(is_normalized_pgn("game-2.pgn"))

    def test_the_normalizer_scan_skips_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("game.pgn", "game-NORM.pgn", "game-NORM-2.pgn"):
                (base / nome).write_text("[Event \"T\"]\n", encoding="utf-8")

            arquivos, ignorados = collect_spellcheck_pgn_files(str(base), False)

            self.assertEqual([os.path.basename(a) for a in arquivos], ["game.pgn"])
            self.assertEqual(ignorados, 2)

    def test_the_output_name_of_a_collision_input_does_not_grow(self):
        with tempfile.TemporaryDirectory() as tmp:
            entrada = os.path.join(tmp, "game-BR-2.pgn")
            Path(entrada).write_text("[Event \"T\"]\n", encoding="utf-8")
            self.assertEqual(
                os.path.basename(translated_output_path(entrada, "pt")), "game-BR.pgn"
            )


class SpellingSectionMergeTests(unittest.TestCase):
    """Uma secao repetida no `spelling.ssp` APAGAVA a anterior (ROADMAP 17.10).

    Era uma atribuicao onde devia ser merge — e o jeito natural de acrescentar
    nomes ao arquivo e criar um segundo bloco `@PLAYER` no fim.
    """

    def arquivo(self, texto):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "spelling.ssp"
        caminho.write_text(texto, encoding="utf-8")
        return str(caminho)

    def test_a_repeated_section_adds_instead_of_replacing(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            "=Garry Kasparov\n"
            '@PLAYER ""\n'
            "Karpov, Anatoly\n"
            "=Anatoly Karpov\n"
        )

        secoes = parse_spelling_file(caminho)

        entradas = secoes["PLAYER"]["entries"]
        self.assertIn("kasparov, garry", entradas)
        self.assertIn("karpov, anatoly", entradas)

    def test_the_first_block_still_wins_a_repeated_key(self):
        """Dentro de um bloco o primeiro a definir a chave vence
        (`setdefault`); entre blocos vale a mesma regra."""
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            '@PLAYER ""\n'
            "KASPAROV, GARRY JR\n"
            "=Kasparov, Garry\n"
        )

        entradas = parse_spelling_file(caminho)["PLAYER"]["entries"]

        self.assertEqual(entradas["kasparov, garry"], "Kasparov, Garry")

    def test_affix_rules_of_both_blocks_survive(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            '%Prefix "Van " "van "\n'
            '@PLAYER ""\n'
            '%Suffix " Jr" " Jr."\n'
        )

        secao = parse_spelling_file(caminho)["PLAYER"]

        self.assertEqual(secao["prefix_rules"], [("Van ", "van ")])
        self.assertEqual(secao["suffix_rules"], [(" Jr", " Jr.")])

    def test_different_sections_stay_separate(self):
        caminho = self.arquivo(
            '@PLAYER ""\n'
            "Kasparov, Garry\n"
            '@SITE ""\n'
            "Linares\n"
        )

        secoes = parse_spelling_file(caminho)

        self.assertIn("kasparov, garry", secoes["PLAYER"]["entries"])
        self.assertIn("linares", secoes["SITE"]["entries"])
        self.assertNotIn("linares", secoes["PLAYER"]["entries"])


class PgnTagValueEscapingTests(unittest.TestCase):
    """O valor corrigido era inserido sem re-escapar aspas (ROADMAP 17.10)."""

    def test_the_two_helpers_are_inverses(self):
        for valor in ('O"Kelly', "barra\\aqui", 'os dois \\ e "', "sem nada"):
            with self.subTest(valor=valor):
                self.assertEqual(
                    unescape_pgn_tag_value(escape_pgn_tag_value(valor)), valor
                )

    def test_a_quote_in_the_canonical_value_does_not_break_the_tag(self):
        """`[White "O"Kelly"]` deixa de ser uma tag valida, e o dano aparece no
        ChessBase de quem abre o arquivo, nao aqui."""
        dados = {
            "PLAYER": {
                "entries": {"okelly": 'O"Kelly'},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        saida, mudancas = normalize_pgn_metadata_content(
            '[White "OKelly"]\n', dados
        )

        self.assertEqual(len(mudancas), 1)
        self.assertEqual(saida, '[White "O\\"Kelly"]\n')
        # E o resultado volta a ser lido como o nome com aspas.
        self.assertEqual(
            unescape_pgn_tag_value(PGN_TAG_RE.match(saida.rstrip("\n")).group(3)),
            'O"Kelly',
        )

    def test_an_escaped_value_in_the_file_is_compared_unescaped(self):
        """O dicionario fala na forma que se escreve; o arquivo, na escapada.
        Comparar sem desescapar fazia o nome com aspas nunca casar."""
        dados = {
            "PLAYER": {
                "entries": {'o"kelly': 'O\'Kelly, Albéric'},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        _saida, mudancas = normalize_pgn_metadata_content(
            '[White "O\\"Kelly"]\n', dados
        )

        self.assertEqual([m["new"] for m in mudancas], ["O'Kelly, Albéric"])

    def test_a_value_without_quotes_comes_out_byte_for_byte(self):
        dados = {
            "PLAYER": {
                "entries": {"kasparov": "Kasparov, Garry"},
                "ignore_chars": "",
                "prefix_rules": [],
                "suffix_rules": [],
            }
        }

        saida, _mudancas = normalize_pgn_metadata_content(
            '[White "Kasparov"]\n[Black "Karpov"]\n', dados
        )

        self.assertEqual(saida, '[White "Kasparov, Garry"]\n[Black "Karpov"]\n')


class NormalizerPartialFailureTests(unittest.TestCase):
    """Uma falha num arquivo derrubava o lote inteiro (ROADMAP 17.10)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.spelling = self.base / "spelling.ssp"
        self.spelling.write_text(
            '@PLAYER ""\nKasparov, Garry\n=Kasparov\n', encoding="utf-8"
        )

        for nome in ("a.pgn", "b.pgn", "c.pgn"):
            (self.base / nome).write_text(
                '[White "Kasparov"]\n\n1. e4 *\n', encoding="utf-8"
            )

    def rodar(self, quebrar=None):
        original = pgn_spellcheck.normalize_pgn_metadata_file

        def falso(input_file, spelling_data, **kwargs):
            if quebrar and os.path.basename(input_file) == quebrar:
                raise OSError("permissao negada")
            return original(input_file, spelling_data, **kwargs)

        pgn_spellcheck.normalize_pgn_metadata_file = falso
        self.addCleanup(
            setattr, pgn_spellcheck, "normalize_pgn_metadata_file", original
        )
        self.logs = []
        return normalize_pgn_metadata_path(
            str(self.base),
            spelling_path=str(self.spelling),
            log_message=self.logs.append,
        )

    def test_the_other_files_are_still_normalized(self):
        stats = self.rodar(quebrar="b.pgn")

        self.assertEqual(stats["changed_files"], 2)
        self.assertEqual([f["file"] for f in stats["failed"]].__len__(), 1)
        self.assertTrue(os.path.basename(stats["failed"][0]["file"]) == "b.pgn")

    def test_the_reason_reaches_the_log(self):
        self.rodar(quebrar="b.pgn")

        self.assertTrue(
            any("permissao negada" in linha for linha in self.logs),
            f"o motivo nao apareceu no log: {self.logs}",
        )

    def test_the_progress_still_reaches_the_end(self):
        valores = []
        original = pgn_spellcheck.normalize_pgn_metadata_file

        def falso(input_file, spelling_data, **kwargs):
            if os.path.basename(input_file) == "a.pgn":
                raise OSError("disco cheio")
            return original(input_file, spelling_data, **kwargs)

        pgn_spellcheck.normalize_pgn_metadata_file = falso
        self.addCleanup(
            setattr, pgn_spellcheck, "normalize_pgn_metadata_file", original
        )

        normalize_pgn_metadata_path(
            str(self.base),
            spelling_path=str(self.spelling),
            progress_callback=valores.append,
        )

        self.assertEqual(valores[-1], 1.0)

    def test_a_clean_run_reports_no_failures(self):
        stats = self.rodar()

        self.assertEqual(stats["failed"], [])
        self.assertEqual(stats["changed_files"], 3)


class BatchSizedOnWhatIsSentTests(unittest.TestCase):
    """B1 media o texto CRU e enviava o LIMPO (ROADMAP 17.10).

    A folga de 200 caracteres segurava na pratica; era acoplamento, nao
    garantia. Estourar o limite faz a camada de API dividir por sentenca, e o
    corte pode cair no meio de um `|||`.
    """

    def test_the_index_groups_match_the_batches(self):
        comentarios = ["a" * 100, "b" * 100, "c" * 100]
        grupos = batch_index_groups(comentarios, max_chars=250)
        lotes = create_comment_batches(comentarios, max_chars=250)

        self.assertEqual(
            [[comentarios[i] for i in grupo] for grupo in grupos], lotes
        )

    def test_a_comment_larger_than_the_limit_is_its_own_group(self):
        comentarios = ["curto", "x" * 500, "outro"]
        self.assertEqual(
            batch_index_groups(comentarios, max_chars=100), [[0], [1], [2]]
        )

    def test_an_empty_list_has_no_groups(self):
        self.assertEqual(batch_index_groups([]), [])

    def test_the_separator_is_counted_between_items(self):
        """Dois de 50 com o separador de 5 nao cabem em 100."""
        comentarios = ["a" * 50, "b" * 50]
        self.assertEqual(batch_index_groups(comentarios, max_chars=100), [[0], [1]])
        self.assertEqual(batch_index_groups(comentarios, max_chars=110), [[0, 1]])


class GlossaryErrorWithoutConsoleTests(unittest.TestCase):
    """Garantia S5 sob `pythonw` (ROADMAP 17.9).

    `report_glossary_error` fazia `print(...)` ANTES de chamar o handler da
    interface — e sob `pythonw` / PyInstaller windowed `sys.stdout` e `None`,
    entao o `print` levantava e o handler nunca rodava. A funcao que existe para
    tornar a falha visivel era a unica que quebrava no empacotado, que e
    exatamente onde nao ha console para ler o erro.
    """

    def setUp(self):
        self.reported = []
        self.previous = set_glossary_error_handler(self.reported.append)
        self.addCleanup(set_glossary_error_handler, self.previous)
        self.addCleanup(clear_glossary_error)
        clear_glossary_error()

    def sem_console(self):
        """Simula o `pythonw`: `sys.stdout` e `None`, e nao um arquivo fechado."""
        self.addCleanup(setattr, sys, "stdout", sys.stdout)
        sys.stdout = None

    def test_the_message_reaches_the_interface_without_a_console(self):
        self.sem_console()

        report_glossary_error("glossario quebrado")

        self.assertEqual(self.reported, ["glossario quebrado"])
        self.assertEqual(last_glossary_error(), "glossario quebrado")

    def test_a_load_failure_still_degrades_and_reports(self):
        """O caminho de verdade: carregar um arquivo quebrado devolve lista vazia
        E avisa, com ou sem console."""
        self.sem_console()
        with tempfile.TemporaryDirectory() as tmp:
            glossary = Path(tmp) / "Substituicoes.txt"
            glossary.write_text("substituicoes = [('a', ", encoding="utf-8")

            self.assertEqual(load_substitutions(str(glossary)), [])

        self.assertEqual(len(self.reported), 1)
        self.assertIn("Substituicoes.txt", self.reported[0])

    def test_a_closed_stdout_is_survived_too(self):
        """Um `stdout` fechado (pipe rompido) levanta `ValueError`, e tambem nao
        pode ser o motivo de o usuario nao ser avisado."""
        fechado = io.StringIO()
        fechado.close()
        self.addCleanup(setattr, sys, "stdout", sys.stdout)
        sys.stdout = fechado

        report_glossary_error("com stdout fechado")

        self.assertEqual(self.reported, ["com stdout fechado"])

    def test_adding_an_entry_that_fails_does_not_raise_without_a_console(self):
        """O mesmo `print` cru estava no `except` de `add_to_glossary`: sob
        `pythonw` ele transformava "nao consegui gravar a regra" num
        `AttributeError` no meio do popup do editor."""
        self.sem_console()
        with tempfile.TemporaryDirectory() as tmp:
            # Um diretorio no lugar do arquivo: a gravacao falha, e a funcao
            # precisa devolver False em vez de levantar.
            caminho = Path(tmp) / "Substituicoes.txt"
            caminho.mkdir()

            self.assertFalse(add_to_glossary("rook", "torre", path=str(caminho)))

    def test_with_a_console_the_message_is_printed(self):
        """Contraprova: a guarda nao pode ter calado o log de quem tem console."""
        saida = io.StringIO()
        with redirect_stdout(saida):
            report_glossary_error("com console")

        self.assertIn("com console", saida.getvalue())


class PreferDbIsHonoredTests(unittest.TestCase):
    """`prefer_db=False` era ignorado quando `db_path` era passado (17.10).

    O argumento explicito do chamador perdia para a conveniencia interna: quem
    pedia "leia o arquivo texto, nao o indice" recebia o indice em silencio.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.arquivo = self.base / "Substituicoes.txt"
        self.arquivo.write_text(
            "substituicoes = [('rook', 'torre')]\n", encoding="utf-8"
        )
        self.indice = self.base / "glossario.db"
        # O indice existe e diz OUTRA coisa: e assim que da para saber de qual
        # dos dois a resposta veio.
        rebuild_glossary_database(str(self.arquivo), str(self.indice))
        self.arquivo.write_text(
            "substituicoes = [('queen', 'dama')]\n", encoding="utf-8"
        )

    def test_the_file_is_read_when_the_index_is_refused(self):
        entradas = load_glossary_entries(
            str(self.arquivo), prefer_db=False, db_path=str(self.indice)
        )

        self.assertEqual(entradas, [("queen", "dama")])

    def test_the_details_loader_honors_it_too(self):
        entradas = load_glossary_entry_details(
            str(self.arquivo), prefer_db=False, db_path=str(self.indice)
        )

        self.assertEqual([orig for orig, *_resto in entradas], ["queen"])

    def test_the_index_is_still_used_when_it_is_asked_for(self):
        """Contraprova: sem `prefer_db=False`, passar o indice continua usando-o
        (e a sincronizacao o traz em dia)."""
        entradas = load_glossary_entries(
            str(self.arquivo), db_path=str(self.indice)
        )

        self.assertEqual(entradas, [("queen", "dama")])

    def test_the_index_is_not_even_touched(self):
        """Nao basta a resposta bater: o indice nao pode ser aberto nem
        reconstruido, senao `prefer_db=False` ainda pagaria o custo dele."""
        chamadas = []
        original = glossario.load_glossary_entries_from_db
        glossario.load_glossary_entries_from_db = lambda *a, **k: chamadas.append(a)
        self.addCleanup(
            setattr, glossario, "load_glossary_entries_from_db", original
        )

        load_glossary_entries(
            str(self.arquivo), prefer_db=False, db_path=str(self.indice)
        )

        self.assertEqual(chamadas, [])


class WorkerProgressEndStateTests(WorkerFallbackHarness, unittest.TestCase):
    """A barra tem de terminar num estado que signifique algo (ROADMAP 17.10).

    Interrompida pelo disjuntor — ou morta por excecao — ela congelava no valor
    em que estava: 43% para sempre, e era o unico sinal na tela que continuava
    dizendo "estou trabalhando" depois do dialogo de aviso.
    """

    def test_a_clean_run_fills_the_bar(self):
        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)

        self.assertEqual(app.progress.value, 1.0)

    def test_the_circuit_breaker_puts_the_bar_back_to_rest(self):
        # Comentarios grandes o bastante para render mais lotes que o limite do
        # disjuntor: com um lote so ele nunca dispara, e o teste passaria sem
        # exercitar nada.
        movetext = " ".join(
            f"{i + 1}. e4 {{Comentario {i} " + "x" * (BATCH_MAX_CHARS // 2) + "}}"
            for i in range(12)
        )

        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text(
                '[Event "T"]\n\n' + movetext + " *\n", encoding="utf-8"
            )
            app = FakeApp(Path(tmp) / "cache.db")

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showwarning,
            )
            translation_worker.translate_text = lambda *_a, **_k: None
            translation_worker.messagebox.showwarning = lambda *_a, **_k: None
            try:
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showwarning,
                ) = originais

        self.assertTrue(
            any("ABORTADO" in linha for linha in app.logs),
            "o disjuntor devia ter agido",
        )
        self.assertEqual(app.progress.value, 0.0)

    def test_a_general_exception_puts_the_bar_back_to_rest(self):
        original = translation_worker.generate_translated_pgn
        translation_worker.generate_translated_pgn = lambda *_a, **_k: 1 / 0
        self.addCleanup(
            setattr, translation_worker, "generate_translated_pgn", original
        )

        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            originais = (
                translation_worker.messagebox.showerror,
            )
            translation_worker.messagebox.showerror = lambda *_a, **_k: None
            try:
                app, _pgn = self.run_worker(Path(tmp), translate)
            finally:
                (translation_worker.messagebox.showerror,) = originais

        self.assertTrue(any("ERRO GERAL" in linha for linha in app.logs))
        self.assertEqual(app.progress.value, 0.0)

    def test_a_cancelled_run_puts_the_bar_back_to_rest(self):
        def translate(text, *_args, **_kwargs):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text(self.PGN, encoding="utf-8")
            app = FakeApp(Path(tmp) / "cache.db")
            app.cancel_flag.set()
            original = translation_worker.translate_text
            translation_worker.translate_text = translate
            try:
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                translation_worker.translate_text = original

        self.assertEqual(app.progress.value, 0.0)


class WorkerFailureListSurvivesAnExceptionTests(
    WorkerFallbackHarness, unittest.TestCase
):
    """Garantia T4 no caminho da excecao (ROADMAP 17.10).

    A lista era gravada so no caminho feliz. Uma excecao geral a perdia — e o
    resultado nao era "sem lista", era pior: a da execucao ANTERIOR continuava
    valendo, e "Reprocessar Falhas" reprocessava com confianca os arquivos de
    outra execucao.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        # Configuracoes proprias, para nao encostar no arquivo de ninguem.
        self.settings_path = self.base / "settings.json"
        original = settings.default_settings_path
        settings.default_settings_path = lambda: str(self.settings_path)
        self.addCleanup(setattr, settings, "default_settings_path", original)

        # A lista de uma execucao ANTERIOR, apontando para outro arquivo.
        failed_runs.save_failed_run(
            {
                "target_language": "pt",
                "source_language": "en",
                "files": [str(self.base / "execucao-antiga.pgn")],
                "failed_count": 7,
                "when": "2026-07-01T10:00:00",
            }
        )

    def roda_e_explode_na_geracao(self):
        original = translation_worker.generate_translated_pgn
        translation_worker.generate_translated_pgn = lambda *_a, **_k: 1 / 0
        self.addCleanup(
            setattr, translation_worker, "generate_translated_pgn", original
        )

        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return "desalinhado"          # cai no modo individual
            if text == "Second comment here":
                return None                   # ...e uma falha de verdade
            return f"[{text}]"

        erro = translation_worker.messagebox.showerror
        translation_worker.messagebox.showerror = lambda *_a, **_k: None
        try:
            return self.run_worker(self.base, translate)
        finally:
            translation_worker.messagebox.showerror = erro

    def test_the_stale_list_is_replaced_by_this_run(self):
        app, pgn = self.roda_e_explode_na_geracao()

        registro = failed_runs.load_failed_run()
        self.assertIsNotNone(registro, "a lista desta execucao devia ter sido gravada")
        self.assertEqual(registro["files"], [str(pgn)])
        self.assertEqual(registro["failed_count"], 1)
        self.assertTrue(any("ERRO GERAL" in linha for linha in app.logs))

    def test_it_is_written_only_once(self):
        """O caminho normal grava no fim, e o tratador de excecao grava se o
        normal nao chegou la — nunca os dois."""
        chamadas = []
        original = translation_worker.save_failed_run
        translation_worker.save_failed_run = lambda record, *a, **k: chamadas.append(
            record
        )
        self.addCleanup(
            setattr, translation_worker, "save_failed_run", original
        )

        self.roda_e_explode_na_geracao()

        self.assertEqual(len(chamadas), 1)

    def test_a_cancelled_run_still_keeps_the_previous_list(self):
        """Cancelar nao registra: os arquivos ainda nao visitados nao foram
        avaliados, e gravar essa lista parcial perderia o que a anterior sabia."""
        pgn = self.base / "game.pgn"
        pgn.write_text(self.PGN, encoding="utf-8")
        app = FakeApp(self.base / "cache.db")
        app.cancel_flag.set()

        original = translation_worker.translate_text
        translation_worker.translate_text = lambda *_a, **_k: None
        try:
            translation_worker.run_translation(app, str(pgn), "pt", False)
        finally:
            translation_worker.translate_text = original

        registro = failed_runs.load_failed_run()
        self.assertEqual(registro["failed_count"], 7, "a lista antiga devia ficar")


class WorkerBatchFitsWhatIsSentTests(unittest.TestCase):
    """Garantia B1 sobre o texto ENVIADO, e nao sobre o cru (ROADMAP 17.10)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def roda(self, comentarios, cleanup_rules):
        """Uma execucao com regras de limpeza que EXPANDEM o comentario."""
        movetext = " ".join(
            f"{i + 1}. e4 {{{texto}}}" for i, texto in enumerate(comentarios)
        )
        pgn = self.base / "game.pgn"
        pgn.write_text(f'[Event "T"]\n\n{movetext} *\n', encoding="utf-8")

        app = FakeApp(self.base / "cache.db")
        enviados = []

        def translate(text, *_args, **_kwargs):
            enviados.append(text)
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        originais = (
            translation_worker.translate_text,
            translation_worker.load_cleanup_substitutions,
            translation_worker.messagebox.showinfo,
            translation_worker.messagebox.showwarning,
        )
        translation_worker.translate_text = translate
        translation_worker.load_cleanup_substitutions = lambda **_k: cleanup_rules
        translation_worker.messagebox.showinfo = lambda *_a, **_k: None
        translation_worker.messagebox.showwarning = lambda *_a, **_k: None
        try:
            translation_worker.run_translation(app, str(pgn), "pt", False)
        finally:
            (
                translation_worker.translate_text,
                translation_worker.load_cleanup_substitutions,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            ) = originais

        return app, enviados

    # Medido nesta maquina com as funcoes reais: cada comentario tem 970
    # caracteres crus e 1.362 depois da regra de limpeza. O lote cru fica com 4
    # deles (3.895 <= 4.800); enviado, esse mesmo lote tem 5.463 — acima do
    # limite. E a situacao exata que a folga de 200 caracteres nao cobria.
    REGRAS_QUE_EXPANDEM = [("EXPANDIR", "b" * 400)]

    def comentarios_que_expandem(self, quantos=5):
        return [f"{i} " + "x " * 480 + "EXPANDIR" for i in range(quantos)]

    def test_a_cleanup_rule_that_expands_never_overflows_the_limit(self):
        """Medido no texto cru, o lote cabia; enviado, ele passava de
        `BATCH_MAX_CHARS` — e a camada de API dividiria por sentenca, podendo
        cortar no meio de um `|||` e tornando o realinhamento impossivel.
        """
        _app, enviados = self.roda(
            self.comentarios_que_expandem(), self.REGRAS_QUE_EXPANDEM
        )

        self.assertTrue(enviados)
        for texto in enviados:
            with self.subTest(tamanho=len(texto)):
                self.assertLessEqual(len(texto), BATCH_MAX_CHARS)

    def test_the_split_is_announced(self):
        app, _enviados = self.roda(
            self.comentarios_que_expandem(), self.REGRAS_QUE_EXPANDEM
        )

        self.assertTrue(
            any("dividido em" in linha for linha in app.logs),
            f"a divisao devia aparecer no log: {app.logs}",
        )

    def test_every_comment_still_gets_its_own_translation(self):
        """O que a divisao nao pode fazer e trocar as traducoes de lugar — o
        pior defeito possivel deste programa."""
        comentarios = self.comentarios_que_expandem()

        self.roda(comentarios, self.REGRAS_QUE_EXPANDEM)

        conn = sqlite3.connect(str(self.base / "cache.db"))
        try:
            gravadas = dict(
                conn.execute(
                    "SELECT original_comment, translated_comment FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()

        self.assertEqual(len(gravadas), len(comentarios))
        for original, traduzida in gravadas.items():
            with self.subTest(original=original[:6]):
                # A limpeza trocou o `X` final, entao o prefixo e o que da para
                # comparar — e e ele que identifica o comentario.
                self.assertTrue(traduzida.startswith(f"[{original[:2]}"))

    def test_without_expansion_there_is_no_extra_request(self):
        """Contraprova: no caminho comum sai um grupo so, e nada muda."""
        comentarios = [f"Comentario {i} do arquivo." for i in range(5)]

        app, enviados = self.roda(comentarios, [])

        self.assertEqual(len(enviados), 1)
        self.assertFalse(any("dividido em" in linha for linha in app.logs))


class RestoreOrMaximizeTests(unittest.TestCase):
    """A geometria salva era ignorada em silencio (ROADMAP 17.10).

    Os dois editores restauravam a geometria na construcao, e o `maximize=True`
    agendado a +50 ms a sobrescrevia depois: todo o caminho de `safe_geometry`,
    com `clamp_geometry` e testes proprios, estava morto na pratica.
    """

    class JanelaFalsa:
        def __init__(self, falhar=False):
            self.geometrias = []
            self.agendados = []
            self.falhar = falhar

        def geometry(self, valor):
            if self.falhar:
                raise RuntimeError("geometria invalida")
            self.geometrias.append(valor)

        def after(self, _delay, callback=None):
            self.agendados.append(callback)

    def test_a_saved_geometry_is_applied_and_nothing_maximizes(self):
        win = self.JanelaFalsa()

        self.assertTrue(window_utils.restore_or_maximize(win, None, "900x600+10+20"))

        self.assertEqual(win.geometrias, ["900x600+10+20"])

    def test_without_a_saved_geometry_it_maximizes(self):
        """Primeira abertura: as duas janelas sao listas largas, e 1280x760 num
        monitor grande desperdicaria a tela."""
        win = self.JanelaFalsa()

        for vazio in (None, "", 0):
            with self.subTest(vazio=vazio):
                self.assertFalse(window_utils.restore_or_maximize(win, None, vazio))

        self.assertEqual(win.geometrias, [], "nao ha geometria para aplicar")

    def test_a_geometry_the_tk_refuses_falls_back_to_maximizing(self):
        win = self.JanelaFalsa(falhar=True)

        self.assertFalse(
            window_utils.restore_or_maximize(win, None, "isto-nao-e-geometria")
        )

    def test_the_editors_do_not_ask_for_both(self):
        """A prova de que a escolha ficou num lugar so: nenhum dos dois editores
        chama `bring_window_to_front` com `maximize=True` na construcao."""
        for modulo in ("edit_window.py", "glossary_editor.py"):
            with self.subTest(modulo=modulo):
                fonte = (
                    Path(__file__).resolve().parent.parent / "tradutor_pgn" / modulo
                ).read_text(encoding="utf-8")
                self.assertNotIn(
                    "bring_window_to_front(self.win", fonte,
                    "a janela principal do editor deve passar por restore_or_maximize",
                )


class ImportCsvOverwriteFlowTests(unittest.TestCase):
    """O dialogo da importacao, com os tres desfechos (ROADMAP 17.7).

    Reduzir a escolha a um "sim/nao" era o que fazia o fluxo natural — exportar,
    corrigir na planilha, importar — terminar em "Sem alteracao" para tudo, com o
    trabalho da planilha jogado fora sem que nada tivesse falhado.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "traducoes.db"

        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "The rook", "a torre errada", "pt", "en")
        conn.commit()
        conn.close()

        self.csv_path = self.base / "traducoes.csv"
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["original_comment", "translated_comment", "source_language",
                 "target_language", "verified"]
            )
            writer.writerow(["The rook", "a torre", "en", "pt", ""])

        self.dialogos = []
        self.resposta = True
        original = db_tools.messagebox
        db_tools.messagebox = types.SimpleNamespace(
            showinfo=lambda t, m, **_k: self.dialogos.append(("info", t, m)),
            showerror=lambda t, m, **_k: self.dialogos.append(("error", t, m)),
            askyesno=lambda t, m, **_k: (
                self.dialogos.append(("askyesno", t, m)) or True
            ),
            askyesnocancel=lambda t, m, **_k: (
                self.dialogos.append(("askyesnocancel", t, m)) or self.resposta
            ),
        )
        self.addCleanup(setattr, db_tools, "messagebox", original)

        original_picker = db_tools.filedialog
        db_tools.filedialog = types.SimpleNamespace(
            askopenfilename=lambda **_k: str(self.csv_path),
            asksaveasfilename=lambda **_k: "",
        )
        self.addCleanup(setattr, db_tools, "filedialog", original_picker)

        original_run = db_tools.run_with_progress
        db_tools.run_with_progress = self.rodar_sincrono
        self.addCleanup(setattr, db_tools, "run_with_progress", original_run)

    def rodar_sincrono(self, _parent, _titulo, work, on_success=None, on_cancel=None, **_kw):
        try:
            resultado = work(BackgroundTask())
        except TaskCanceled:
            if on_cancel is not None:
                on_cancel(None)
            return
        if on_success is not None:
            on_success(resultado)

    def app_falso(self):
        return types.SimpleNamespace(
            output_db=str(self.db_path),
            root=None,
            translation_cache={"The rook": "a torre errada"},
            log_message=lambda _m: None,
        )

    def gravada(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                "SELECT translated_comment FROM comments WHERE original_comment = ?",
                ("The rook",),
            ).fetchone()[0]
        finally:
            conn.close()

    def pergunta(self, tipo="askyesnocancel"):
        return next(m for t, _tt, m in self.dialogos if t == tipo)

    def test_the_dialog_offers_the_three_outcomes(self):
        self.resposta = None

        db_tools.import_csv(self.app_falso())

        texto = self.pergunta()
        self.assertIn("Sim:", texto)
        self.assertIn("Nao:", texto)
        self.assertIn("Cancelar:", texto)
        self.assertIn("DIFEREM", texto)

    def test_yes_overwrites(self):
        self.resposta = True

        db_tools.import_csv(self.app_falso())

        self.assertEqual(self.gravada(), "a torre")
        self.assertIn("Sobrescritas: 1", self.pergunta("info"))

    def test_no_imports_respecting_t1(self):
        self.resposta = False

        db_tools.import_csv(self.app_falso())

        self.assertEqual(self.gravada(), "a torre errada")
        self.assertIn("Sem alteracao: 1", self.pergunta("info"))

    def test_cancel_writes_nothing_and_says_nothing_more(self):
        self.resposta = None

        db_tools.import_csv(self.app_falso())

        self.assertEqual(self.gravada(), "a torre errada")
        self.assertEqual([t for t, _tt, _m in self.dialogos], ["askyesnocancel"])

    def test_overwriting_clears_the_in_memory_cache(self):
        """Ele tem precedencia sobre o banco: deixado como estava, a proxima
        traducao reescreveria no PGN o texto que acabou de ser corrigido."""
        self.resposta = True
        app = self.app_falso()

        db_tools.import_csv(app)

        self.assertEqual(app.translation_cache, {})

    def test_without_anything_to_overwrite_it_is_a_plain_yes_or_no(self):
        """A pergunta de tres botoes so aparece quando ha o que sobrescrever;
        no resto, o dialogo continua sendo o de sempre."""
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["original_comment", "translated_comment", "source_language",
                 "target_language", "verified"]
            )
            writer.writerow(["The bishop", "o bispo", "en", "pt", ""])

        db_tools.import_csv(self.app_falso())

        tipos = [t for t, _tt, _m in self.dialogos]
        self.assertIn("askyesno", tipos)
        self.assertNotIn("askyesnocancel", tipos)
        self.assertIn("nao serao sobrescritas", self.pergunta("askyesno"))


# ===========================================================================
# Secao 16 — o aviso de qualidade passa a conhecer xadrez
# ===========================================================================


class MoveAnchorTests(unittest.TestCase):
    """A ancora que a garantia Q1 compara, e por que ela nao tem idioma."""

    def test_the_anchor_is_the_same_move_in_two_languages(self):
        """`Nf3` e `Cf3` sao o mesmo lance: so a letra muda."""
        self.assertEqual(move_anchors("plays Nf3 here"), move_anchors("joga Cf3 aqui"))

    def test_pawn_moves_count_too(self):
        """`extract_moves` os descarta (nao ha letra para corrigir); aqui um
        `h5` que sumiu importa tanto quanto um `Nf3`."""
        self.assertEqual(move_anchors("then h5"), Counter({("h5", "", ""): 1}))

    def test_the_check_mark_is_part_of_the_anchor(self):
        self.assertNotEqual(move_anchors("Bxf7+"), move_anchors("Bxf7"))

    def test_the_capture_mark_is_normalized(self):
        """O original traz `N×d4` e a traducao chega com `Nxd4`, porque uma regra
        automatica do glossario ja converteu o sinal."""
        self.assertEqual(move_anchors("N×d4"), move_anchors("Cxd4"))

    def test_a_command_annotation_is_not_a_move(self):
        """`[%cal Ra1h8]` tem a forma de um lance de Torre e nao e lance nenhum
        (garantia X1)."""
        self.assertEqual(move_anchors("boa {[%cal Ra1h8]}"), Counter())

    def test_repetition_is_counted(self):
        """Multiconjunto, e nao conjunto: a traducao que repetiu um lance a mais
        que o original tambem divergiu."""
        self.assertEqual(move_anchors("Nf3 Nf3")[("f3", "", "")], 2)

    def test_empty_text_has_no_anchors(self):
        for vazio in ("", None):
            with self.subTest(vazio=vazio):
                self.assertEqual(move_anchors(vazio), Counter())


class ChessQualityHeuristicsTests(unittest.TestCase):
    """Garantia Q1 e as demais heuristicas de xadrez (ROADMAP 16.1)."""

    def avisos(self, original, traduzida, origem=None, destino=None):
        return evaluate_translation_quality(original, traduzida, origem, destino)

    def um(self, original, traduzida, trecho, origem=None, destino=None):
        """Exige que algum aviso contenha `trecho`, e devolve esse aviso."""
        avisos = self.avisos(original, traduzida, origem, destino)
        achados = [a for a in avisos if trecho in a]
        self.assertTrue(achados, f"nenhum aviso com {trecho!r}; havia {avisos}")
        return achados[0]

    def nenhum(self, original, traduzida, trecho, origem=None, destino=None):
        avisos = self.avisos(original, traduzida, origem, destino)
        self.assertEqual(
            [a for a in avisos if trecho in a], [], f"avisos: {avisos}"
        )

    # --------------------------------------------------- Q1: lance perdido

    def test_a_move_the_translator_ate_is_a_warning(self):
        """O aviso de maior valor da secao: o texto continua lendo bem e diz
        outra coisa."""
        aviso = self.um(
            "White plays Bxf7+ and then Qd5+ wins.",
            "As brancas jogam Bxf7+ e ganham.",
            "não aparece na tradução",
        )
        self.assertIn("d5+", aviso)

    def test_a_move_the_translator_invented_is_a_warning(self):
        aviso = self.um(
            "White plays Bxf7+ and wins the game right there.",
            "As brancas jogam Bxf7+ e Dd5+ e ganham a partida ali mesmo.",
            "não está no original",
        )
        self.assertIn("d5+", aviso)

    def test_translating_the_piece_letter_is_not_a_warning(self):
        """A contraprova que faz o aviso valer: `Nf3` -> `Cf3` e o certo."""
        self.nenhum(
            "White plays Nf3 and Rd1, a good setup for the coming attack.",
            "As brancas jogam Cf3 e Td1, uma boa formação para o ataque.",
            "aparece na tradução",
        )

    def test_the_number_glued_to_the_move_is_caught(self):
        """Medido no banco de desenvolvimento: 4 dos 6 casos reais. `20 Na2` ->
        `20Ca2` deixa de ser notacao valida, e o aviso e o que faz alguem ver."""
        self.um(
            "on account of 20 Na2, winning a pawn for White in the endgame.",
            "por conta de 20Ca2, ganhando um peão para as brancas no final.",
            "não aparece na tradução",
        )

    # ------------------------------------------------ Q1: anotacao rompida

    def test_a_broken_annotation_is_a_warning(self):
        """Enquanto a mascara da secao 13 nao existia, este aviso era a rede;
        depois dela, e como se acha o legado que ja esta no banco."""
        aviso = self.um(
            "Good move {[%eval +0.35]} in this position, says the engine.",
            "Bom lance {[%eval +0. 35]} nesta posição, diz o motor.",
            "Anotação do original ausente",
        )
        self.assertIn("[%eval +0.35]", aviso)

    def test_an_intact_annotation_is_not_a_warning(self):
        self.nenhum(
            "Good move [%eval +0.35] in this position, says the engine here.",
            "Bom lance [%eval +0.35] nesta posição, diz o motor aqui.",
            "Anotação",
        )

    def test_an_annotation_that_appeared_out_of_nowhere_is_a_warning(self):
        self.um(
            "Good move in this position, or so the engine seems to believe.",
            "Bom lance [%clk 0:05:00] nesta posição, ou o motor assim acredita.",
            "Anotação na tradução",
        )

    # ------------------------------------------------- NAGs e simbolos

    def test_a_lost_nag_is_a_warning(self):
        self.um(
            "This is the critical moment of the whole game $14 for both sides.",
            "Este é o momento crítico de toda a partida para os dois lados.",
            "NAG do original ausente",
        )

    def test_a_lost_evaluation_symbol_is_a_warning(self):
        self.um(
            "White is much better here $$ and the position speaks +- for itself.",
            "As brancas estão muito melhor aqui e a posição fala por si.",
            "Símbolo de avaliação do original ausente",
        )

    def test_ordinary_question_marks_are_not_symbols(self):
        """`!` e `?` sozinhos sao pontuacao. "Is this sound?" -> "Isso e
        correto?" tem um `?` de cada lado por acidente, e uma frase que ganha ou
        perde um ponto de interrogacao e prosa normal."""
        self.nenhum(
            "Is this really the best that White can do in such a position?",
            "Será que isto é realmente o melhor que as brancas podem fazer!",
            "Símbolo de avaliação",
        )

    def test_a_longer_symbol_is_not_counted_twice(self):
        """Contando do mais curto para o mais longo, `+/-` viraria tambem um
        `+/` e todo texto com avaliacao pareceria ter simbolos a mais."""
        self.assertEqual(eval_symbols("+/-"), Counter({"+/-": 1}))
        self.assertEqual(eval_symbols("+/- +/-"), Counter({"+/-": 2}))

    # ------------------------------------------------------- sinais diretos

    def test_the_replacement_character_is_a_warning(self):
        """As garantias E4 e G2 impedem isso na leitura nova; isto acha o legado
        que ja esta gravado."""
        self.um(
            "A posi�ao das brancas e melhor aqui do que parece a primeira vista.",
            "A posição das brancas é melhor aqui do que parece à primeira vista.",
            "U+FFFD",
        )

    def test_the_batch_separator_in_the_stored_text_is_a_warning(self):
        """No texto GRAVADO ele e evidencia de um desalinhamento que a contagem
        de partes nao pegou (garantia B2)."""
        self.um(
            "First comment here about the position of the white pieces.",
            "Primeiro comentário ||| segundo comentário que vazou para cá.",
            "separador de lote",
        )

    # -------------------------------------------------------- quase-igualdade

    def test_a_translation_that_barely_changed_is_a_warning(self):
        original = (
            "The position after 15 Nf3 is balanced and both sides have chances."
        )
        self.um(original, original.replace("balanced", "balancedo"), "quase idêntica")

    def test_a_citation_that_is_almost_identical_is_not_a_warning(self):
        """O falso positivo que a medicao achou, e a razao de a conta ter dois
        passos: o `quick_ratio` da 0,953 aqui porque a citacao domina a contagem
        de caracteres, e o `ratio` ve o bloco comum e responde 0,822."""
        self.nenhum(
            "is about equal, Z. Hracek-G. Jones, Porto Carras 2011.",
            "é quase igual, Z. Hracek-G. Jones, Porto Carras 2011.",
            "quase idêntica",
        )

    def test_a_short_original_is_left_alone(self):
        """Abaixo do piso, ser quase identica e o resultado certo: nao ha o que
        traduzir numa citacao curta."""
        self.nenhum("Tilburg 1993", "Tilburgo 1993", "quase idêntica")

    def test_an_exactly_equal_translation_keeps_its_own_warning(self):
        """"Igual" e "quase igual" nao podem virar dois avisos para o mesmo
        fato."""
        texto = "The position after 15 Nf3 is balanced and both sides have chances."
        avisos = self.avisos(texto, texto)
        self.assertIn("Tradução igual ao original.", avisos)
        self.assertEqual([a for a in avisos if "quase" in a], [])

    # ----------------------------------------------------- as cinco antigas

    def test_the_five_generic_heuristics_still_answer(self):
        """A secao 16 acrescenta; nao substitui. Medido no banco de
        desenvolvimento: das 11 linhas que o `quality_warning` marcava, zero
        deixaram de ser marcadas."""
        self.assertEqual(self.avisos("qualquer", ""), ["Tradução vazia."])
        self.assertIn("igual ao original", " ".join(self.avisos("mesmo", "mesmo")))
        self.assertIn("chaves", " ".join(self.avisos("a", "b {c}")))
        longo = "palavra " * 20
        self.assertIn("muito curta", " ".join(self.avisos(longo, "curta")))
        self.assertIn("muito longa", " ".join(self.avisos(longo, longo * 3)))


class SuspectTerminologyTests(unittest.TestCase):
    """Terminologia suspeita por par de idiomas (ROADMAP 16.1, item 8)."""

    def arquivo(self, linhas):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        corpo = ",\n    ".join(repr(t) for t in linhas)
        caminho.write_text(f"termos = [\n    {corpo},\n]\n", encoding="utf-8")
        return str(caminho)

    def test_the_term_must_be_in_the_original_and_the_form_in_the_translation(self):
        """As duas condicoes juntas sao o que faz o aviso ser especifico:
        "ritmo" numa traducao e palavra comum, e so vira suspeita quando o
        original diz "tempo"."""
        caminho = self.arquivo([("tempo", "ritmo", "pt")])

        self.assertEqual(
            find_suspect_terms("loses a tempo", "perde um ritmo", "en", "pt", caminho),
            [("tempo", "ritmo")],
        )
        self.assertEqual(
            find_suspect_terms("a fast game", "um jogo de ritmo alto", "en", "pt", caminho),
            [],
            "sem o termo no original nao ha suspeita",
        )
        self.assertEqual(
            find_suspect_terms("loses a tempo", "perde um tempo", "en", "pt", caminho),
            [],
            "com a forma certa na traducao nao ha suspeita",
        )

    def test_the_suspect_form_matches_inflected(self):
        """Em portugues ela chega flexionada: "quadrado" aparece como
        "quadrados", "fixado" como "fixada"."""
        caminho = self.arquivo([("square", "quadrado", "pt")])
        self.assertEqual(
            find_suspect_terms("the squares", "os quadrados", "en", "pt", caminho),
            [("square", "quadrado")],
        )

    def test_the_term_matches_whole_words_only(self):
        """Sem a fronteira, `pin` casaria "opinion" e o aviso viraria ruido.

        A palavra do exemplo tem de conter o termo DE VERDADE. A primeira versao
        deste teste usava "opening", que nao tem "pin" nenhum — e ele passava com
        a fronteira e sem ela, o que e a definicao de nao proteger nada.
        """
        caminho = self.arquivo([("pin", "alfinete", "pt")])
        for palavra in ("opinion", "spinning"):
            with self.subTest(palavra=palavra):
                self.assertEqual(
                    find_suspect_terms(
                        f"in my {palavra}", "o alfinete", "en", "pt", caminho
                    ),
                    [],
                )
        # Contraprova: o termo sozinho continua sendo achado.
        self.assertEqual(
            find_suspect_terms("a nasty pin", "um alfinete", "en", "pt", caminho),
            [("pin", "alfinete")],
        )

    def test_the_scope_keeps_the_list_inside_its_pair(self):
        """Garantia S11: a lista de portugues nao pode acusar erro numa traducao
        para o italiano."""
        caminho = self.arquivo([("file", "arquivo", "pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", "pt", caminho),
            [("file", "arquivo")],
        )
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", "it", caminho),
            [],
        )

    def test_without_a_target_language_nothing_is_applied(self):
        """E o oposto do que `scope_matches` faz sozinho — la o destino ausente
        nao filtra nada, o que e certo para o glossario e errado aqui."""
        caminho = self.arquivo([("file", "arquivo", "pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo aberto", "en", None, caminho),
            [],
        )
        self.assertEqual(suspect_terms_for(None, None, caminho), [])

    def test_a_pair_scope_needs_the_declared_source(self):
        caminho = self.arquivo([("file", "arquivo", "en>pt")])
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo", "en", "pt", caminho),
            [("file", "arquivo")],
        )
        self.assertEqual(
            find_suspect_terms("the open file", "o arquivo", "", "pt", caminho),
            [],
            "origem nao declarada nao satisfaz um escopo de par",
        )

    def test_a_malformed_entry_is_skipped_and_the_rest_survives(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        caminho.write_text(
            "termos = [\n"
            "    ('so', 'dois'),\n"
            "    ('', 'vazio', 'pt'),\n"
            "    ('check', 'cheque', 'pt'),\n"
            "]\n",
            encoding="utf-8",
        )
        self.assertEqual(
            load_suspect_terms(str(caminho)), [("check", "cheque", "pt")]
        )

    def test_a_broken_file_degrades_and_reports(self):
        """Ela vem com o programa, entao um defeito nela e nosso — e nao pode
        impedir o programa de funcionar nem passar calado (garantia S5)."""
        reportados = []
        anterior = set_glossary_error_handler(reportados.append)
        self.addCleanup(set_glossary_error_handler, anterior)

        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        caminho = Path(sandbox.name) / "Termos-suspeitos.txt"
        caminho.write_text("termos = [('a',\n", encoding="utf-8")

        self.assertEqual(call_quietly(load_suspect_terms, str(caminho)), [])
        self.assertEqual(len(reportados), 1)
        self.assertIn("termos suspeitos", reportados[0])

    def test_a_missing_file_is_simply_empty(self):
        self.assertEqual(load_suspect_terms("nao-existe-em-lugar-nenhum.txt"), [])


class ShippedSuspectTermsTests(unittest.TestCase):
    """O arquivo que vem com o programa, medido no banco de desenvolvimento."""

    def setUp(self):
        self.entradas = load_suspect_terms(chess_terms._default_terms_path())

    def test_it_is_not_empty(self):
        self.assertGreater(len(self.entradas), 10)

    def test_white_and_black_cover_every_non_english_target(self):
        """O que se detecta e o termo ter ficado EM INGLES. Para 'en' nao existe:
        la "White" e a palavra certa."""
        for idioma, _nome in [(code, nome) for nome, code in LANGUAGES]:
            escopos = {
                escopo for termo, _s, escopo in self.entradas if termo == "White"
            }
            with self.subTest(idioma=idioma):
                if idioma == "en":
                    self.assertNotIn("en", escopos)
                else:
                    self.assertIn(idioma, escopos)

    def test_the_measured_pt_terms_are_there(self):
        pares_pt = {
            (termo, suspeito)
            for termo, suspeito, escopo in self.entradas
            if escopo == "pt"
        }
        for par in [
            ("check", "cheque"),
            ("file", "arquivo"),
            ("tempo", "ritmo"),
            ("square", "quadrado"),
            ("pin", "alfinete"),
            ("sound", "som"),
        ]:
            with self.subTest(par=par):
                self.assertIn(par, pares_pt)

    def test_the_two_that_the_measurement_rejected_are_absent(self):
        """`exchange` -> `troca` marcava 178 linhas e a maioria estava CERTA
        ("trocar" e a traducao boa do verbo); `rank` -> `classificacao` marcava 2
        e uma estava certa ("the rank of master player"). Sobrou `back rank`."""
        pares = {(termo, suspeito) for termo, suspeito, _e in self.entradas}
        self.assertNotIn(("exchange", "troca"), pares)
        self.assertNotIn(("rank", "classificação"), pares)
        self.assertIn(("back rank", "classificação"), pares)

    def test_no_entry_is_its_own_correct_translation(self):
        """Uma entrada em que a forma suspeita e a certa marcaria toda traducao
        boa. So `White`/`Black` sao iguais dos dois lados, e ai o suspeito e
        justamente NAO ter mudado."""
        for termo, suspeito, escopo in self.entradas:
            if termo in ("White", "Black"):
                self.assertEqual(termo, suspeito)
                continue
            with self.subTest(termo=termo):
                self.assertNotEqual(termo.casefold(), suspeito.casefold())

    def test_a_real_sentence_from_the_book_is_flagged(self):
        """Uma das 321 linhas que o filtro "Avisos QA" nao mostrava."""
        avisos = evaluate_translation_quality(
            "White has more space and control of the only entirely open file.",
            "As brancas têm mais espaço e controle do único arquivo aberto.",
            "en",
            "pt",
        )
        self.assertTrue(
            any("'file' no original e 'arquivo'" in a for a in avisos), avisos
        )


class QualityHeuristicsVersionTests(unittest.TestCase):
    """Garantia Q2: as heuristicas tem versao, e muda-las reavalia o banco."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_a_fresh_database_records_the_current_version_when_reevaluated(self):
        conn = self.banco()
        self.assertEqual(get_quality_heuristics_version(conn), 0)
        self.assertFalse(quality_heuristics_are_current(conn))

        set_db_metadata(conn, QUALITY_VERSION_KEY, QUALITY_HEURISTICS_VERSION)
        self.assertTrue(quality_heuristics_are_current(conn))

    def test_a_missing_mark_reads_as_zero(self):
        """Zero e a resposta certa: um banco gravado antes desta versao teve os
        avisos calculados pelas cinco genericas, e nao ha como distinguir isso de
        "nunca calculado" — as duas pedem a mesma acao."""
        conn = self.banco()
        self.assertEqual(get_quality_heuristics_version(conn), 0)

    def test_a_garbage_mark_reads_as_zero_too(self):
        conn = self.banco()
        set_db_metadata(conn, QUALITY_VERSION_KEY, "nao e numero")
        self.assertEqual(get_quality_heuristics_version(conn), 0)

    def test_metadata_survives_a_reopen(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = str(Path(sandbox.name) / "cache.db")

        conn = initialize_database(db_path)
        set_db_metadata(conn, QUALITY_VERSION_KEY, 7)
        conn.commit()
        conn.close()

        conn = initialize_database(db_path)
        try:
            self.assertEqual(get_quality_heuristics_version(conn), 7)
        finally:
            conn.close()

    def test_reading_the_mark_tolerates_a_database_without_the_table(self):
        """Um banco antes da migracao 6 nao tem `db_metadata`, e perguntar pela
        marca nao pode levantar."""
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        db_path = Path(sandbox.name) / "antigo.db"
        _schema3_database(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            self.assertIsNone(get_db_metadata(conn, QUALITY_VERSION_KEY))
            self.assertEqual(get_quality_heuristics_version(conn), 0)
        finally:
            conn.close()

    def test_the_backfill_does_not_advance_the_version(self):
        """E a diferenca entre ele e a reavaliacao: preencher `NULL` bastava
        enquanto o unico jeito de a coluna estar errada fosse nao existir."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "orig", "trans", "pt", "en")
        cur.execute("UPDATE comments SET quality_warning = NULL")
        conn.commit()

        self.assertEqual(backfill_quality_warnings(conn), 1)
        self.assertEqual(get_quality_heuristics_version(conn), 0)


class QualityReevaluationTests(unittest.TestCase):
    """A reavaliacao em massa: o que ela muda, o que ela relata, o que ela nao grava."""

    def banco(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.db_path = str(Path(self.sandbox.name) / "cache.db")
        conn = initialize_database(self.db_path)
        self.addCleanup(conn.close)
        cur = conn.cursor()
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        conn.commit()
        return conn

    def flags(self, conn):
        return dict(
            conn.execute("SELECT original_comment, quality_warning FROM comments")
        )

    def test_a_stale_verdict_is_corrected(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        stats = reevaluate_quality_warnings(conn)

        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(
            self.flags(conn), {"White plays Nf3.": 0, "The open file.": 1}
        )

    def test_running_twice_changes_nothing_the_second_time(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        reevaluate_quality_warnings(conn)
        self.assertEqual(reevaluate_quality_warnings(conn)["changed"], 0)

    def test_the_pair_comes_from_the_row_and_not_from_an_argument(self):
        """O banco tem pares diferentes na mesma tabela, e a terminologia e
        escopada por idioma: avaliar tudo com um par so acusaria erro onde nao
        ha."""
        conn = self.banco()
        cur = conn.cursor()
        # Mesmo texto, destino italiano: a lista de portugues nao vale aqui.
        save_translation(cur, "The open file.", "O arquivo aberto.", "it", "en")
        conn.commit()

        reevaluate_quality_warnings(conn)

        self.assertEqual(
            conn.execute(
                "SELECT quality_warning FROM comments"
                " WHERE target_language = 'it'"
            ).fetchone()[0],
            0,
        )

    def test_progress_is_reported_and_ends_at_the_total(self):
        conn = self.banco()
        marcos = []
        reevaluate_quality_warnings(conn, progress_callback=lambda f, t: marcos.append((f, t)))
        self.assertEqual(marcos[0], (0, 2))
        self.assertEqual(marcos[-1], (2, 2))

    def test_cancelling_raises_and_leaves_the_rest_alone(self):
        conn = self.banco()
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()

        with self.assertRaises(QualityReevaluationCanceled):
            reevaluate_quality_warnings(conn, batch_size=1, should_cancel=lambda: True)

    def test_an_empty_database_is_scanned_without_error(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "vazio.db"))
        try:
            self.assertEqual(
                reevaluate_quality_warnings(conn), {"scanned": 0, "changed": 0}
            )
        finally:
            conn.close()


class QualityColumnMatchesTheScreenTests(unittest.TestCase):
    """Garantia R6 com as heuristicas novas: a coluna nao pode divergir da tela.

    A terminologia depende do par de idiomas, entao o par tem de chegar aos DOIS
    caminhos — a gravacao (que materializa o bit) e a leitura (que mostra as
    frases). Se um deles avaliar sem par, a contagem do rodape passa a nao bater
    com o que a lista exibe, e nada quebra.
    """

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def linhas(self, conn, destino="pt"):
        return fetch_review_rows(conn.cursor(), destino)

    def test_the_saved_flag_agrees_with_the_row_evaluation(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        conn.commit()

        for row in self.linhas(conn):
            with self.subTest(original=row[1]):
                gravado = conn.execute(
                    "SELECT quality_warning FROM comments WHERE id = ?", (row[0],)
                ).fetchone()[0]
                self.assertEqual(gravado, 1 if row_has_quality_warning(row) else 0)

    def test_the_row_carries_the_pair_at_the_end(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        conn.commit()

        row = self.linhas(conn)[0]
        self.assertEqual(row_language_pair(row), ("en", "pt"))

    def test_a_row_without_the_pair_is_still_evaluated(self):
        """Tolerante de proposito: uma tupla de sete campos continua sendo
        avaliada, so sem a parte de terminologia."""
        curta = (1, "The open file.", "O arquivo aberto.", 0, None, None, None)
        self.assertEqual(row_language_pair(curta), (None, None))
        self.assertFalse(row_has_quality_warning(curta))

    def test_editing_a_translation_keeps_the_flag_in_agreement(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "A coluna aberta.", "pt", "en")
        conn.commit()
        row_id = self.linhas(conn)[0][0]

        # A edicao introduz o erro de terminologia: o bit tem de acompanhar.
        update_translation_by_id(cur, row_id, "O arquivo aberto.")
        conn.commit()

        row = self.linhas(conn)[0]
        gravado = conn.execute(
            "SELECT quality_warning FROM comments WHERE id = ?", (row_id,)
        ).fetchone()[0]
        self.assertEqual(gravado, 1)
        self.assertTrue(row_has_quality_warning(row))

    def test_the_counts_agree_with_the_rows(self):
        """A agregada de status conta pela coluna; a lista avalia em Python. Os
        dois numeros tem de ser o mesmo."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(cur, "White plays Nf3.", "As brancas jogam Cf3.", "pt", "en")
        save_translation(cur, "A nasty check.", "Um cheque desagradável.", "pt", "en")
        conn.commit()

        resumo = get_review_status_counts(cur, "pt")
        self.assertEqual(
            resumo["warnings"],
            len(filter_quality_warning_rows(self.linhas(conn))),
        )


# ===========================================================================
# Secao 18 — o banco passa a saber de onde cada traducao veio
# ===========================================================================


class ReadingContextTests(unittest.TestCase):
    """O contexto de leitura sai do PGN: partida, indice e numero do lance.

    Tudo aqui roda sobre `comment_reading_context`, que e a funcao pura, e sobre a
    extracao de verdade num arquivo em disco. Nenhum destes numeros existia no
    banco antes desta secao — a lista do editor era ordem de insercao, e ordem de
    insercao mistura todos os PGN ja processados.
    """

    def contexto(self, texto):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\{.*?\}", texto, re.DOTALL)]
        return comment_reading_context(texto, spans)

    def test_the_move_cited_inside_a_comment_is_not_the_position(self):
        """O caso que obriga a apagar os spans antes de ler o movetext.

        Comentario de livro cita lance a vontade ("melhor era 14. Bxf7"). Lido
        junto com o movetext, o lance CITADO no comentario 1 passaria a ser a
        posicao do comentario 2 — um numero errado com cara de medido.
        """
        texto = '[Event "A"]\n\n1. e4 {melhor era 14. Bxf7} 2. Nf3 {aqui}\n'
        self.assertEqual(self.contexto(texto), [(1, 1), (1, 2)])

    def test_an_event_tag_inside_a_comment_does_not_start_a_game(self):
        """A mesma protecao, do outro lado: o comentario tambem nao cria partida."""
        texto = '[Event "A"]\n\n1. e4 {citando\n[Event "B"]\nno meio} 2. Nf3 {aqui}\n'
        self.assertEqual([partida for partida, _lance in self.contexto(texto)], [1, 1])

    def test_a_comment_before_the_first_move_has_no_move_number(self):
        """E `None`, e nao o lance da partida ANTERIOR.

        Sem o recorte por partida, um comentario colado nas tags da partida 2
        herdaria o lance 41 da partida 1 e afirmaria com confianca uma posicao que
        nao existe. `None` e a unica resposta verdadeira.
        """
        texto = (
            '[Event "A"]\n\n1. e4 e5 41. Kf1 1-0\n\n'
            '[Event "B"]\n[White "X"]\n\n{antes de tudo} 1. d4 {depois} 1/2-1/2\n'
        )
        self.assertEqual(self.contexto(texto), [(2, None), (2, 1)])

    def test_the_game_number_counts_the_event_tags(self):
        texto = (
            '[Event "A"]\n\n1. e4 {um} 1-0\n\n'
            '[Event "B"]\n\n1. d4 {dois} 1-0\n\n'
            '[Event "C"]\n\n1. c4 {tres} 1-0\n'
        )
        self.assertEqual([p for p, _l in self.contexto(texto)], [1, 2, 3])

    def test_a_date_tag_is_not_a_move_number(self):
        """`[Date "2011.??.??"]` — a data com mes e dia desconhecidos.

        A data COMPLETA (`2011.05.12`) nao serve para este teste, e descobri-lo foi
        o que a mutacao deu: ela ja e recusada pela regra do decimal, entao o teste
        passava com a checagem de linha de tag e sem ela. A forma com `??` e comum
        em PGN de banco de dados, e nela o `2011.` vira lance 2011 se ninguem
        reparar que aquilo e uma linha de tag.
        """
        texto = '[Event "A"]\n[Date "2011.??.??"]\n\n{antes do primeiro lance} 1. e4\n'
        self.assertEqual(self.contexto(texto), [(1, None)])

    def test_a_semicolon_comment_does_not_give_a_move_number(self):
        """Comentario `;` e texto, nao movetext — e o programa nem o traduz.

        O `;` tem de ser a ULTIMA coisa antes do comentario, e isto tambem saiu da
        mutacao: com um `2. Nf3` depois dele, o lance certo vinha do `2.` e o teste
        passava sem a checagem nenhuma.
        """
        texto = '[Event "A"]\n\n1. e4 ; ver a partida 99. Kh1\n{aqui}\n'
        self.assertEqual(self.contexto(texto), [(1, 1)])

    def test_movetext_with_no_tags_is_a_single_game(self):
        """Nao existe partida zero em ordem de leitura."""
        self.assertEqual(self.contexto("1. e4 {um} 2. Nf3 {dois}"), [(1, 1), (1, 2)])

    def test_the_decimal_inside_the_movetext_is_not_taken_as_a_move(self):
        """`+0.35` num comentario nao chega aqui (o span e apagado), mas um
        decimal solto no movetext tambem nao pode virar lance.

        Este teste falhou quando foi escrito: o `0.` casava e o comentario
        seguinte saia com "lance 0" — um numero errado, e visivel na tela.
        """
        texto = "1. e4 {um} +0.35 {dois}"
        self.assertEqual([lance for _p, lance in self.contexto(texto)], [1, 1])

    def test_castling_written_with_zeros_is_still_a_move(self):
        """A contraprova do recorte acima, e o que impede a correcao larga.

        Recusar todo digito depois do ponto (`1. 0-0`, roque escrito com zeros em
        PGN antigo) apagaria um lance legitimo. O que caracteriza decimal e o
        digito COLADO no ponto.
        """
        self.assertEqual(self.contexto("1. 0-0 {depois do roque}"), [(1, 1)])

    def test_the_index_counts_only_the_comments_that_become_rows(self):
        """Um `{}` vazio nao ocupa posicao: ele nao vira linha no banco.

        Se ocupasse, o indice do comentario seguinte pularia um numero e a ordem
        de leitura teria um buraco que nada explica.
        """
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        pgn = base / "vazio.pgn"
        pgn.write_text(
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {} 3. Bb5 {dois}\n', encoding="utf-8"
        )

        info = extract_comments_from_file(str(pgn))
        self.assertEqual(
            info["occurrences"],
            [(1, 1, 1, "um"), (2, 1, 3, "dois")],
        )

    def test_the_extraction_keeps_the_occurrences_aligned_with_the_comments(self):
        """`comments[i]` e `occurrences[i]` falam da mesma posicao do arquivo."""
        base = Path(tempfile.mkdtemp())
        pgn = base / "alinhado.pgn"
        pgn.write_text(
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 3. Bb5 {tres}\n',
            encoding="utf-8",
        )

        info = extract_comments_from_file(str(pgn))
        self.assertEqual(
            [texto for _i, _p, _l, texto in info["occurrences"]], info["comments"]
        )
        self.assertEqual(
            [indice for indice, _p, _l, _t in info["occurrences"]], [1, 2, 3]
        )

    def test_a_file_that_cannot_be_read_returns_an_empty_occurrence_list(self):
        """O worker le a chave sem checar; ela precisa existir sempre."""
        info = extract_comments_from_file(str(Path(tempfile.mkdtemp()) / "nao-existe.pgn"))
        self.assertEqual(info["occurrences"], [])


class OccurrenceTestCase(unittest.TestCase):
    """Base das ocorrencias: um banco novo e dois PGN de mentira em disco."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.conn = initialize_database(str(self.base / "cache.db"))
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def caminho(self, nome, pasta=None):
        """Um caminho ABSOLUTO, que e como a ocorrencia guarda arquivo."""
        destino = self.base if pasta is None else self.base / pasta
        destino.mkdir(parents=True, exist_ok=True)
        return str(destino / nome)

    def gravar(self, *textos, source="en", target="pt"):
        for texto in textos:
            save_translation(self.cur, texto, f"T {texto}", target, source)
        self.conn.commit()
        return resolve_comment_ids(self.cur, target, list(textos), source)

    def registrar(self, arquivo, ocorrencias, ids=None, target="pt", source="en"):
        if ids is None:
            ids = resolve_comment_ids(
                self.cur, target, [t for _i, _p, _l, t in ocorrencias], source
            )
        resultado = record_occurrences(self.cur, arquivo, ocorrencias, ids)
        self.conn.commit()
        return resultado

    def linhas_de_ocorrencia(self):
        return self.cur.execute(
            f"SELECT source_file, game_index, comment_index, move_number"
            f" FROM {OCCURRENCES_TABLE} ORDER BY source_file, comment_index"
        ).fetchall()


class OccurrenceRecordingTests(OccurrenceTestCase):
    """Gravar de onde o comentario veio, sem tocar na identidade da traducao."""

    def test_the_same_comment_in_two_books_is_one_row_and_two_occurrences(self):
        """O coracao do desenho (ROADMAP 18): a relacao e N para 1.

        O reuso e o que faz o acervo valer — o mesmo comentario em doze livros e
        uma traducao e uma revisao. Se o contexto tivesse entrado como coluna de
        `comments`, cada livro teria criado a sua linha e a revisao passaria a ser
        feita doze vezes.
        """
        ids = self.gravar("Diagram")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 5, "Diagram")], ids)
        self.registrar(self.caminho("cap02.pgn"), [(1, 3, 9, "Diagram")], ids)

        self.assertEqual(
            self.cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 1
        )
        self.assertEqual(
            self.cur.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0],
            2,
        )

    def test_the_occurrence_keeps_the_game_and_the_move(self):
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(7, 3, 24, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 3, 7, 24)])

    def test_a_comment_before_the_first_move_stores_a_null_move(self):
        """`None` chega ao banco como NULL, e nao como zero: zero se confundiria
        com medicao."""
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, None, "um")], ids)

        self.assertIsNone(self.linhas_de_ocorrencia()[0][3])

    def test_reprocessing_the_same_file_does_not_duplicate_the_positions(self):
        """Traduzir a mesma pasta duas vezes e rotina (o cache existe para isso)."""
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        posicoes = [(1, 1, 1, "um"), (2, 1, 2, "dois")]

        self.registrar(arquivo, posicoes, ids)
        self.registrar(arquivo, posicoes, ids)

        self.assertEqual(len(self.linhas_de_ocorrencia()), 2)

    def test_a_file_that_shrank_loses_the_positions_that_no_longer_exist(self):
        """O arquivo em disco e a verdade sobre a obra.

        O usuario apagou metade do capitulo e reprocessou: as posicoes que
        sobravam nao existem mais, e mante-las deixaria o banco afirmando que o
        comentario 2 daquele arquivo e um texto que nao esta la.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um"), (2, 1, 2, "dois")], ids)

        self.registrar(arquivo, [(1, 1, 1, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 1, 1, 1)])

    def test_a_comment_without_a_row_is_counted_and_not_recorded(self):
        """Um comentario que falhou na traducao nao tem linha para apontar.

        A ocorrencia aponta para uma traducao; sem ela nao ha para onde apontar. O
        que nao pode acontecer e o numero desaparecer — "a obra tem 2 posicoes" e
        diferente de "tem 2, uma ainda sem traducao".
        """
        ids = self.gravar("um")
        gravadas, sem_linha = self.registrar(
            self.caminho("cap01.pgn"),
            [(1, 1, 1, "um"), (2, 1, 2, "o que falhou")],
            ids,
        )

        self.assertEqual((gravadas, sem_linha), (1, 1))
        self.assertEqual(len(self.linhas_de_ocorrencia()), 1)

    def test_two_spellings_of_the_same_path_are_one_work(self):
        """O caminho e a chave da obra, e `cap01.pgn` e `./cap01.pgn` sao o mesmo
        arquivo. Duas grafias no banco dariam duas obras no filtro, cada uma com
        metade do livro."""
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um")], ids)
        self.registrar(os.path.join(str(self.base), ".", "cap01.pgn"),
                       [(1, 1, 1, "um")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [(arquivo, 1, 1, 1)])

    def test_a_position_of_the_work_has_a_single_owner(self):
        """A UNIQUE da tabela, exercitada por fora de `record_occurrences`.

        Ela nao inclui `comment_id` de proposito: com ele, o comentario 5 de um
        arquivo poderia ter dois donos ao mesmo tempo — a afirmacao velha e a nova
        convivendo, e a ordem de leitura decidindo por sorteio qual aparece.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")

        with self.assertRaises(sqlite3.IntegrityError):
            self.cur.executemany(
                f"INSERT INTO {OCCURRENCES_TABLE}"
                f" (comment_id, source_file, game_index, comment_index)"
                f" VALUES (?, ?, 1, 5)",
                [(ids["um"], arquivo), (ids["dois"], arquivo)],
            )

    def test_resolve_only_answers_inside_the_pair(self):
        """O mesmo texto vindo do espanhol e outra traducao (garantia P1).

        Resolver sem o par faria a ocorrencia de um PGN ingles apontar para a linha
        espanhola — o contexto certo no comentario errado.
        """
        save_translation(self.cur, "Nada", "Nothing", "pt", "es")
        self.conn.commit()

        self.assertEqual(resolve_comment_ids(self.cur, "pt", ["Nada"], "en"), {})
        self.assertEqual(
            list(resolve_comment_ids(self.cur, "pt", ["Nada"], "es")), ["Nada"]
        )

    def test_recording_nothing_still_clears_the_file(self):
        """Um arquivo que ficou sem nenhuma posicao resolvivel nao pode manter as
        antigas: elas falam de um conteudo que ninguem mais le ali."""
        ids = self.gravar("um")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(arquivo, [(1, 1, 1, "um")], ids)

        self.registrar(arquivo, [(1, 1, 1, "outro texto")], ids)

        self.assertEqual(self.linhas_de_ocorrencia(), [])


class ReadingOrderTests(OccurrenceTestCase):
    """A lista do editor em ordem de leitura da obra, e o filtro por arquivo."""

    def setUp(self):
        super().setUp()
        # Inseridos FORA da ordem de leitura, de proposito: e o que acontece de
        # verdade, porque quem grava e a ordem em que a API respondeu e o cache
        # encheu. Com `ORDER BY id` a lista sai nesta ordem aqui.
        self.ids = self.gravar("C terceiro", "A primeiro", "B segundo")
        self.arquivo = self.caminho("cap01.pgn")
        self.outro = self.caminho("cap02.pgn")
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "A primeiro"),
                (2, 1, 3, "B segundo"),
                (3, 2, 12, "C terceiro"),
            ],
            self.ids,
        )

    def originais(self, **kwargs):
        return [
            linha[1]
            for linha in fetch_review_rows_page(self.cur, "pt", **kwargs)
        ]

    def leitura(self, **kwargs):
        return self.originais(
            source_file=self.arquivo, order=ORDER_BY_OCCURRENCE, **kwargs
        )

    def test_the_list_follows_the_work_and_not_the_insertion_order(self):
        """O item inteiro da secao 18, numa linha: `ORDER BY id` nao e ordem de
        leitura de nada."""
        self.assertEqual(self.originais(), ["C terceiro", "A primeiro", "B segundo"])
        self.assertEqual(self.leitura(), ["A primeiro", "B segundo", "C terceiro"])

    def test_a_comment_repeated_in_the_file_appears_once(self):
        """"Diagram" aparece trinta vezes num livro, e a lista e de comentarios."""
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "A primeiro"),
                (2, 1, 2, "A primeiro"),
                (3, 1, 3, "A primeiro"),
                (4, 1, 4, "B segundo"),
            ],
            self.ids,
        )

        self.assertEqual(self.leitura(), ["A primeiro", "B segundo"])

    def test_the_repeated_comment_is_ordered_by_its_first_position(self):
        """Onde o leitor o encontra primeiro, e nao onde ele reaparece."""
        self.registrar(
            self.arquivo,
            [
                (1, 1, 1, "B segundo"),
                (2, 1, 2, "A primeiro"),
                (3, 1, 3, "B segundo"),
            ],
            self.ids,
        )

        self.assertEqual(self.leitura(), ["B segundo", "A primeiro"])

    def test_the_file_filter_leaves_out_the_other_book(self):
        self.registrar(self.outro, [(1, 1, 1, "C terceiro")], self.ids)

        self.assertEqual(
            self.originais(source_file=self.outro, order=ORDER_BY_OCCURRENCE),
            ["C terceiro"],
        )
        self.assertEqual(
            count_review_rows(self.cur, "pt", source_file=self.outro), 1
        )

    def test_a_row_with_no_occurrence_is_outside_every_file(self):
        """As 201.607 linhas migradas nao pertencem a obra nenhuma — e o filtro
        "Todos" continua sendo o unico lugar em que elas aparecem."""
        self.gravar("sem arquivo")

        self.assertEqual(len(self.originais()), 4)
        self.assertNotIn("sem arquivo", self.leitura())

    def test_the_status_counts_respect_the_file(self):
        self.registrar(self.outro, [(1, 1, 1, "C terceiro")], self.ids)

        resumo = get_review_status_counts(self.cur, "pt", source_file=self.outro)
        self.assertEqual((resumo["total"], resumo["pending"]), (1, 1))

    def test_the_offset_of_an_id_follows_the_active_order(self):
        """A classe de defeito que a garantia R10 fechou, pelo outro lado.

        "C terceiro" e o primeiro id do banco e o ULTIMO da obra. Com a lista em
        ordem de leitura e o offset contado por id, o "Ir para ID" mandaria a
        janela para a pagina do offset 0 e selecionaria outra linha — sem erro
        nenhum na tela.
        """
        alvo = self.ids["C terceiro"]

        self.assertEqual(get_review_row_offset(self.cur, "pt", alvo), 0)
        self.assertEqual(
            get_review_row_offset(
                self.cur, "pt", alvo,
                source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
            ),
            2,
        )

    def test_the_offset_and_the_page_agree_in_reading_order(self):
        """O offset serve para posicionar na pagina: os dois criterios tem de ser
        o mesmo. Conferido linha por linha, e nao so na primeira."""
        for esperado, texto in enumerate(["A primeiro", "B segundo", "C terceiro"]):
            offset = get_review_row_offset(
                self.cur, "pt", self.ids[texto],
                source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
            )
            self.assertEqual(offset, esperado, texto)
            self.assertEqual(
                self.leitura(limit=1, offset=offset), [texto], texto
            )

    def test_paging_in_reading_order_neither_repeats_nor_skips(self):
        """Ordem total: sem desempate, duas linhas podem trocar de lugar entre
        duas paginas — uma sai duas vezes e a outra nenhuma."""
        paginas = [
            self.leitura(limit=2, offset=0),
            self.leitura(limit=2, offset=2),
        ]

        self.assertEqual(
            paginas[0] + paginas[1], ["A primeiro", "B segundo", "C terceiro"]
        )

    def test_asking_for_reading_order_without_a_file_falls_back_to_id(self):
        """Sem arquivo, ordenar pela primeira ocorrencia de cada comentario
        custaria uma agregacao da tabela por pagina — a garantia R5."""
        self.assertFalse(reads_in_occurrence_order(ORDER_BY_OCCURRENCE, None))
        self.assertEqual(
            self.originais(order=ORDER_BY_OCCURRENCE),
            ["C terceiro", "A primeiro", "B segundo"],
        )

    def test_the_search_and_the_file_filter_compose(self):
        self.assertEqual(
            self.leitura(search_text="segundo", search_mode=SEARCH_MODE_SUBSTRING),
            ["B segundo"],
        )

    def test_the_status_filter_and_the_reading_order_compose(self):
        set_translation_verified_by_id(self.cur, self.ids["B segundo"])
        self.conn.commit()

        self.assertEqual(self.leitura(status_filter="verified"), ["B segundo"])
        self.assertEqual(
            self.leitura(status_filter="pending"), ["A primeiro", "C terceiro"]
        )

    def test_the_full_row_fetch_takes_the_order_too(self):
        """`fetch_review_rows` alimenta o relatorio QA e as estatisticas; sem a
        ordem, o relatorio de uma obra sairia embaralhado."""
        self.assertEqual(
            [
                linha[1]
                for linha in fetch_review_rows(
                    self.cur, "pt",
                    source_file=self.arquivo, order=ORDER_BY_OCCURRENCE,
                )
            ],
            ["A primeiro", "B segundo", "C terceiro"],
        )


class OccurrenceListingTests(OccurrenceTestCase):
    """O que o filtro por arquivo e o rodape do editor leem do banco."""

    def test_the_file_list_separates_positions_from_comments(self):
        """As duas contagens dizem coisas diferentes: tamanho da obra e trabalho
        de revisao. A diferenca entre elas e a repeticao interna do livro."""
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(
            arquivo,
            [(1, 1, 1, "um"), (2, 1, 2, "um"), (3, 1, 3, "dois")],
            ids,
        )

        self.assertEqual(list_occurrence_files(self.cur, "pt"), [(arquivo, 3, 2)])

    def test_the_file_list_is_scoped_to_the_pair(self):
        """O editor mostra um par por vez (garantia R9), e o menu de arquivos
        precisa acompanhar: um arquivo do par espanhol no menu do ingles seria um
        filtro que devolve zero linhas."""
        ids_en = self.gravar("um", source="en")
        ids_es = self.gravar("uno", source="es")
        self.registrar(self.caminho("ingles.pgn"), [(1, 1, 1, "um")], ids_en)
        self.registrar(
            self.caminho("espanhol.pgn"), [(1, 1, 1, "uno")], ids_es, source="es"
        )

        self.assertEqual(
            [linha[0] for linha in list_occurrence_files(self.cur, "pt", "en")],
            [self.caminho("ingles.pgn")],
        )
        self.assertEqual(
            len(list_occurrence_files(self.cur, "pt")), 2
        )

    def test_the_file_list_is_ordered_by_name(self):
        """E como capitulo se ordena — e nao por quantidade, que faria a ordem do
        menu mudar a cada execucao."""
        ids = self.gravar("um")
        for nome in ("cap03.pgn", "cap01.pgn", "cap02.pgn"):
            self.registrar(self.caminho(nome), [(1, 1, 1, "um")], ids)

        self.assertEqual(
            [os.path.basename(linha[0]) for linha in list_occurrence_files(self.cur, "pt")],
            ["cap01.pgn", "cap02.pgn", "cap03.pgn"],
        )

    def test_the_occurrences_of_a_comment_come_with_the_full_total(self):
        """A lista vem cortada e o total vem inteiro: o rodape mostra as primeiras
        e diz quantas faltam."""
        ids = self.gravar("Diagram")
        for nome in ("cap01.pgn", "cap02.pgn", "cap03.pgn"):
            self.registrar(self.caminho(nome), [(1, 1, 1, "Diagram")], ids)

        linhas, total = fetch_comment_occurrences(self.cur, ids["Diagram"], limit=2)

        self.assertEqual(total, 3)
        self.assertEqual(len(linhas), 2)

    def test_the_preferred_file_comes_first(self):
        """Quem esta lendo o capitulo 7 nao pode ver no rodape a posicao do mesmo
        comentario no capitulo 1: e verdade, responde outra pergunta, e na tela
        passa por erro."""
        ids = self.gravar("Diagram")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "Diagram")], ids)
        self.registrar(self.caminho("cap07.pgn"), [(1, 1, 1, "Diagram")], ids)

        linhas, _total = fetch_comment_occurrences(
            self.cur, ids["Diagram"], limit=1,
            preferred_file=self.caminho("cap07.pgn"),
        )

        self.assertEqual([os.path.basename(l[0]) for l in linhas], ["cap07.pgn"])

    def test_a_comment_with_no_occurrence_answers_empty(self):
        ids = self.gravar("um")
        self.assertEqual(fetch_comment_occurrences(self.cur, ids["um"]), ([], 0))


class FileProgressTests(OccurrenceTestCase):
    """Progresso por obra: "faltam 120 comentarios do capitulo 7"."""

    def test_a_comment_repeated_in_the_file_counts_once(self):
        """O numero mais facil de errar aqui.

        Somando `verified` sobre o `JOIN`, um comentario verificado que aparece
        tres vezes viraria tres verificacoes e o progresso passaria de 100%.
        """
        ids = self.gravar("um", "dois")
        arquivo = self.caminho("cap01.pgn")
        self.registrar(
            arquivo,
            [
                (1, 1, 1, "um"),
                (2, 1, 2, "um"),
                (3, 1, 3, "um"),
                (4, 1, 4, "dois"),
            ],
            ids,
        )
        set_translation_verified_by_id(self.cur, ids["um"])
        self.conn.commit()

        (linha,) = get_file_progress(self.cur)
        _arquivo, posicoes, comentarios, verificadas, pendentes, _avisos = linha

        self.assertEqual((comentarios, verificadas, pendentes), (2, 1, 1))
        # As posicoes, essas sim, contam a repeticao: e o tamanho da obra.
        self.assertEqual(posicoes, 4)

    def test_the_progress_counts_the_quality_warnings_of_the_work(self):
        arquivo = self.caminho("cap01.pgn")
        save_translation(self.cur, "The open file.", "O arquivo aberto.", "pt", "en")
        save_translation(self.cur, "The rook.", "A torre.", "pt", "en")
        self.conn.commit()
        self.registrar(
            arquivo,
            [(1, 1, 1, "The open file."), (2, 1, 2, "The rook.")],
        )

        self.assertEqual(get_file_progress(self.cur)[0][5], 1)

    def test_each_work_is_counted_on_its_own(self):
        ids = self.gravar("um", "dois")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)
        self.registrar(
            self.caminho("cap02.pgn"),
            [(1, 1, 1, "um"), (2, 1, 2, "dois")],
            ids,
        )

        self.assertEqual(
            [(os.path.basename(l[0]), l[2]) for l in get_file_progress(self.cur)],
            [("cap01.pgn", 1), ("cap02.pgn", 2)],
        )

    def test_a_database_with_no_occurrence_has_no_work(self):
        """O estado de todo banco migrado: traducao ha, procedencia nao."""
        self.gravar("um")
        self.assertEqual(get_file_progress(self.cur), [])
        self.assertEqual(get_database_stats(self.cur)["per_file"], [])

    def test_the_stats_carry_the_progress_per_work(self):
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)

        self.assertEqual(
            get_database_stats(self.cur)["per_file"], get_file_progress(self.cur)
        )


class OccurrenceSchemaTests(unittest.TestCase):
    """A migracao 6 -> 7, e o que ela deliberadamente NAO faz."""

    def banco_no_schema_6(self):
        """Um banco completo, menos a tabela de ocorrencias.

        Feito derrubando a tabela e voltando a marca de versao: o ponto do teste e
        que a abertura seguinte reconheca o banco antigo e complete o schema, e
        essa e exatamente a situacao do banco do usuario depois da atualizacao.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "cache.db"

        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        conn.commit()
        conn.execute(f"DROP TABLE {OCCURRENCES_TABLE}")
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
        conn.close()
        return db_path

    def test_opening_an_older_database_creates_the_table(self):
        db_path = self.banco_no_schema_6()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)

        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
        )
        self.assertEqual(
            conn.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0], 0
        )

    def test_the_migration_does_not_invent_a_provenance(self):
        """Nao ha de onde derivar arquivo, partida e lance das linhas ja gravadas.

        Um backfill teria de inventar, e uma procedencia falsa e pior do que a
        ausencia: ela apareceria no filtro por arquivo como uma obra que ninguem
        traduziu.
        """
        db_path = self.banco_no_schema_6()

        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        self.assertEqual(list_occurrence_files(cur, "pt"), [])
        self.assertEqual(
            cur.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2
        )

    def test_the_unique_of_comments_is_untouched(self):
        """A tabela ao lado nao pode ter mexido no que define uma traducao."""
        db_path = self.banco_no_schema_6()
        conn = initialize_database(str(db_path))
        self.addCleanup(conn.close)
        cur = conn.cursor()

        self.assertEqual(save_translation(cur, "the rook", "outra", "pt", "en"), "unchanged")
        self.assertEqual(save_translation(cur, "the rook", "la torre", "es", "en"), "inserted")


class ClearTranslationsTakesOccurrencesTests(OccurrenceTestCase):
    """Garantia Z3: zerar leva historico, indice, cache — e ocorrencias."""

    def test_zeroing_the_bank_takes_the_occurrences(self):
        """O `AUTOINCREMENT` reinicia com a tabela.

        Uma ocorrencia sobrevivente apontaria para a PRIMEIRA traducao gravada
        depois do zeramento: o comentario errado, no arquivo certo, sem nada
        acusando na tela.
        """
        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)

        clear_all_translations(self.conn)

        cur = self.conn.cursor()
        self.assertEqual(
            cur.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0], 0
        )
        self.assertEqual(get_file_progress(cur), [])

    def test_the_table_still_exists_after_zeroing(self):
        """Derrubar sem recriar deixaria o proximo filtro por arquivo em erro."""
        clear_all_translations(self.conn)
        cur = self.conn.cursor()

        ids = self.gravar("um")
        self.registrar(self.caminho("cap01.pgn"), [(1, 1, 1, "um")], ids)
        self.assertEqual(len(get_file_progress(cur)), 1)


class WorkerOccurrenceTests(unittest.TestCase):
    """O worker grava a procedencia com os dados que ele ja tem na mao."""

    def setUp(self):
        original = translation_worker.messagebox

        class SemDialogos:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)

        translation_worker.messagebox = SemDialogos
        self.addCleanup(setattr, translation_worker, "messagebox", original)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "cache.db"

    def falso_translate(self, resposta=None):
        def falso(text, *_a, **_k):
            if resposta is not None:
                return resposta
            # Devolve o texto com um prefixo, preservando os separadores de lote:
            # assim o realinhamento continua valendo e cada comentario ganha uma
            # traducao propria.
            return " ||| ".join(f"T {parte}" for parte in text.split(" ||| "))

        original = translation_worker.translate_text
        translation_worker.translate_text = falso
        self.addCleanup(setattr, translation_worker, "translate_text", original)

    def escreve(self, nome, conteudo):
        caminho = self.base / nome
        caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def ocorrencias(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                f"SELECT o.source_file, o.game_index, o.comment_index,"
                f" o.move_number, c.original_comment"
                f" FROM {OCCURRENCES_TABLE} o JOIN comments c ON c.id = o.comment_id"
                f" ORDER BY o.source_file, o.comment_index"
            ).fetchall()
        finally:
            conn.close()

    def test_a_run_records_where_each_comment_was_read(self):
        """Ponta a ponta: do PGN em disco a tabela de ocorrencias."""
        self.falso_translate()
        pgn = self.escreve(
            "cap01.pgn",
            '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 1-0\n\n'
            '[Event "B"]\n\n1. d4 {tres} 1-0\n',
        )

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="en"
        )

        self.assertEqual(
            self.ocorrencias(),
            [
                (str(pgn), 1, 1, 1, "um"),
                (str(pgn), 1, 2, 2, "dois"),
                (str(pgn), 2, 3, 1, "tres"),
            ],
        )

    def test_a_comment_reused_from_the_cache_is_recorded_too(self):
        """A segunda execucao nao chama a API — e a procedencia do arquivo novo
        tem de aparecer do mesmo jeito. Registrar so o que a API respondeu deixaria
        de fora justamente o acervo que o cache existe para reaproveitar."""
        self.falso_translate()
        primeiro = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 1-0\n')
        translation_worker.run_translation(
            FakeApp(self.db_path), str(primeiro), "pt", False, source_language="en"
        )

        segundo = self.escreve("cap02.pgn", '[Event "A"]\n\n1. e4 e5 2. Nf3 {um} 1-0\n')
        translation_worker.run_translation(
            FakeApp(self.db_path), str(segundo), "pt", False, source_language="en"
        )

        self.assertEqual(
            [(os.path.basename(l[0]), l[3]) for l in self.ocorrencias()],
            [("cap01.pgn", 1), ("cap02.pgn", 2)],
        )

    def test_the_run_says_how_many_positions_it_recorded(self):
        """O numero no log e o que separa "a obra tem 2 posicoes" de "tem 2, uma
        ainda sem traducao"."""
        self.falso_translate()
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 2. Nf3 {dois} 1-0\n')
        app = FakeApp(self.db_path)

        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="en"
        )

        self.assertTrue(
            any("Posicoes registradas: 2/2" in linha for linha in app.logs),
            app.logs,
        )

    def test_a_comment_the_api_refused_is_reported_as_missing(self):
        """A API nao respondeu: o comentario fica no idioma original e sem linha no
        banco, e a posicao dele nao pode ser inventada."""
        self.falso_translate(resposta="")
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {um} 1-0\n')
        app = FakeApp(self.db_path)

        translation_worker.run_translation(
            app, str(pgn), "pt", False, source_language="en"
        )

        self.assertEqual(self.ocorrencias(), [])
        self.assertTrue(
            any("1 sem traducao no banco" in linha for linha in app.logs), app.logs
        )

    def test_the_occurrence_is_recorded_under_the_declared_pair(self):
        """A ocorrencia aponta para a LINHA, e a linha e do par: o mesmo PGN
        declarado como espanhol e como ingles da duas traducoes, cada uma com a
        sua procedencia."""
        self.falso_translate()
        pgn = self.escreve("cap01.pgn", '[Event "A"]\n\n1. e4 {Nada} 1-0\n')

        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="es"
        )
        translation_worker.run_translation(
            FakeApp(self.db_path), str(pgn), "pt", False, source_language="it"
        )

        conn = initialize_database(str(self.db_path))
        self.addCleanup(conn.close)
        # O arquivo e o mesmo, entao a posicao 1 dele tem um dono so: a ultima
        # execucao. As duas linhas de traducao continuam existindo.
        self.assertEqual(
            conn.execute(
                f"SELECT c.source_language FROM {OCCURRENCES_TABLE} o"
                f" JOIN comments c ON c.id = o.comment_id"
            ).fetchall(),
            [("it",)],
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2
        )


# ===========================================================================
# Secao 19 — o fluxo do tradutor profissional
# ===========================================================================


class WordCountTests(unittest.TestCase):
    """A metrica com que tradutor orca, mede e cobra (ROADMAP 19, item 6)."""

    def test_words_are_separated_by_whitespace(self):
        self.assertEqual(count_words("a coluna aberta"), 3)
        self.assertEqual(count_words("  espaco   duplo\ne quebra\tde linha  "), 6)

    def test_nothing_counts_zero(self):
        """Somar o banco inteiro tem linhas sem traducao; um `None` aqui nao pode
        derrubar a agregacao."""
        self.assertEqual(count_words(None), 0)
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words("   "), 0)

    def test_notation_counts_as_one_word(self):
        """`14.Bxf7` e uma palavra pela definicao de espaco — que e a mesma que o
        cliente usa para pagar. Contar so o que tem letra daria um numero MENOR do
        que aquele pelo qual o tradutor cobra."""
        self.assertEqual(count_words("melhor era 14.Bxf7 aqui"), 4)

    def test_the_five_counters_move_together(self):
        """`add_word_counts` existe para que as cinco somas nao possam divergir: um
        `+=` esquecido daria um relatorio que fecha em quase tudo."""
        acumulador = {}
        add_word_counts(acumulador, ("en", "pt"), "the open file", "a coluna aberta", 1)
        add_word_counts(acumulador, ("en", "pt"), "the rook", "a torre", 0)

        self.assertEqual(
            acumulador[("en", "pt")],
            {"rows": 2, "original": 5, "translated": 5, "verified": 3, "pending": 2},
        )

    def test_the_total_sums_every_pair(self):
        acumulador = {}
        add_word_counts(acumulador, ("en", "pt"), "one two", "um dois", 1)
        add_word_counts(acumulador, ("es", "pt"), "tres", "tres", 0)

        self.assertEqual(
            total_word_counts(acumulador),
            {"rows": 2, "original": 3, "translated": 3, "verified": 2, "pending": 1},
        )


class WordCountByPairTests(unittest.TestCase):
    """A contagem sobre o banco: por par, por status, em blocos e cancelavel."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_the_counts_are_separated_by_pair_and_status(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "the open file", "a coluna aberta", "pt", "en")
        save_translation(cur, "el alfil", "o bispo", "pt", "es")
        conn.commit()
        set_translation_verified_by_id(
            cur,
            cur.execute(
                "SELECT id FROM comments WHERE source_language = 'en'"
            ).fetchone()[0],
        )
        conn.commit()

        por_par, total = count_words_by_pair(cur)

        self.assertEqual(por_par[("en", "pt")]["verified"], 3)
        self.assertEqual(por_par[("en", "pt")]["pending"], 0)
        self.assertEqual(por_par[("es", "pt")]["pending"], 2)
        self.assertEqual(total["original"], 5)
        self.assertEqual(total["translated"], 5)

    def test_the_translation_is_counted_as_the_reviewer_left_it(self):
        """O original e achatado (um espaco entre palavras) e a traducao passou pela
        mao do revisor: ela pode ter quebra de linha e espaco duplo.

        E o motivo de a contagem ser em Python e nao em SQL: contar espacos daria a
        resposta certa de um lado e errada do outro.
        """
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "one two three", "um  dois\ntres", "pt", "en")
        conn.commit()

        _por_par, total = count_words_by_pair(cur)

        self.assertEqual((total["original"], total["translated"]), (3, 3))

    def test_it_reports_progress_and_can_be_canceled(self):
        conn = self.banco()
        cur = conn.cursor()
        for i in range(12):
            save_translation(cur, f"orig {i} um dois", f"trad {i} um", "pt", "en")
        conn.commit()

        self.addCleanup(setattr, database, "WORD_COUNT_CHUNK", database.WORD_COUNT_CHUNK)
        database.WORD_COUNT_CHUNK = 5

        progresso = []
        por_par, _total = count_words_by_pair(
            cur, progress_callback=lambda f, t: progresso.append((f, t))
        )
        self.assertEqual(por_par[("en", "pt")]["rows"], 12)
        self.assertEqual(progresso[0], (0, 12))
        self.assertEqual(progresso[-1], (12, 12))

        with self.assertRaises(database.WordCountCanceled):
            count_words_by_pair(cur, should_cancel=lambda: True)


class DailyReviewActivityTests(unittest.TestCase):
    """Produtividade por dia, do `comment_history` (ROADMAP 19, item 6)."""

    def banco(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        conn = initialize_database(str(Path(sandbox.name) / "cache.db"))
        self.addCleanup(conn.close)
        return conn

    def test_each_edit_counts_and_the_words_are_the_new_ones(self):
        """A mesma linha editada duas vezes conta duas: sao duas passagens de
        revisao, e o numero e de ATIVIDADE, nao de acervo."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "orig", "uma palavra", "pt", "en")
        conn.commit()
        row_id = cur.execute("SELECT id FROM comments").fetchone()[0]
        update_translation_by_id(cur, row_id, "duas palavras aqui")
        update_translation_by_id(cur, row_id, "agora sao quatro palavras aqui")
        conn.commit()

        atividade = get_daily_review_activity(cur)

        self.assertEqual(len(atividade), 1)
        _dia, edicoes, palavras = atividade[0]
        self.assertEqual(edicoes, 2)
        self.assertEqual(palavras, 3 + 5)

    def test_a_bank_without_history_answers_empty(self):
        """Traducao gravada pelo worker nao gera historico: o numero de um banco
        recem-traduzido e zero, e a tela precisa dizer isso em palavras."""
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "orig", "trad", "pt", "en")
        conn.commit()

        self.assertEqual(get_daily_review_activity(cur), [])

    def test_the_most_recent_days_come_first_and_the_list_is_cut(self):
        conn = self.banco()
        cur = conn.cursor()
        save_translation(cur, "orig", "trad", "pt", "en")
        conn.commit()
        row_id = cur.execute("SELECT id FROM comments").fetchone()[0]
        for dia in range(1, 6):
            cur.execute(
                "INSERT INTO comment_history (comment_id, action, previous_translation,"
                " new_translation, previous_verified, new_verified, created_at)"
                " VALUES (?, 'edit', 'a', 'uma palavra', 0, 0, ?)",
                (row_id, f"2026-07-0{dia} 10:00:00"),
            )
        conn.commit()

        atividade = get_daily_review_activity(cur, limit=3)

        self.assertEqual([dia for dia, _e, _p in atividade],
                         ["2026-07-05", "2026-07-04", "2026-07-03"])


class TmxExportTests(unittest.TestCase):
    """Exportacao TMX 1.4 (ROADMAP 19, item 8)."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.db_path = self.base / "cache.db"

    def semear(self, linhas):
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        for original, traducao, origem, destino in linhas:
            cur.execute(
                "INSERT INTO comments (original_comment, translated_comment,"
                " source_language, target_language) VALUES (?, ?, ?, ?)",
                (original, traducao, origem, destino),
            )
        conn.commit()
        conn.close()

    def exportar(self):
        destino = self.base / "memoria.tmx"
        unidades = db_tools.export_translations_to_tmx(str(self.db_path), str(destino))
        return unidades, destino

    def test_the_file_is_valid_xml_with_one_unit_per_row(self):
        self.semear([
            ("the rook", "a torre", "en", "pt"),
            ("the bishop", "o bispo", "en", "pt"),
        ])

        unidades, destino = self.exportar()

        raiz = ET.parse(destino).getroot()
        self.assertEqual(unidades, 2)
        self.assertEqual(raiz.get("version"), "1.4")
        self.assertEqual(len(raiz.findall(".//tu")), 2)

    def test_the_header_declares_many_source_languages(self):
        """O acervo tem varios idiomas de origem ao mesmo tempo. Declarar um so
        faria toda ferramenta importar o acervo inteiro como se fosse dele; `*all*`
        e o valor que o proprio padrao TMX define para isso."""
        self.semear([("a", "b", "en", "pt"), ("c", "d", "es", "pt")])

        _unidades, destino = self.exportar()

        raiz = ET.parse(destino).getroot()
        self.assertEqual(raiz.find("header").get("srclang"), "*all*")

    def test_a_row_without_source_language_becomes_und(self):
        """`xml:lang=""` nao e valido, inventar `en` seria mentir, e pular as linhas
        deixaria de fora a maioria de um banco anterior a secao 9.2."""
        self.semear([("sem origem", "sin origen", "", "pt")])

        _unidades, destino = self.exportar()

        idiomas = [
            tuv.get("{http://www.w3.org/XML/1998/namespace}lang")
            for tuv in ET.parse(destino).getroot().findall(".//tuv")
        ]
        self.assertEqual(idiomas, ["und", "pt"])

    def test_a_row_without_translation_is_left_out(self):
        """Uma memoria com o lado de destino vazio nao ajuda ferramenta nenhuma e
        polui a busca por concordancia de quem a importar."""
        self.semear([
            ("com traducao", "tem", "en", "pt"),
            ("sem traducao", "", "en", "pt"),
            ("nula", None, "en", "pt"),
        ])

        unidades, destino = self.exportar()

        self.assertEqual(unidades, 1)
        self.assertEqual(len(ET.parse(destino).getroot().findall(".//tu")), 1)

    def test_the_markup_of_the_comment_is_escaped(self):
        """Um `&` ou um `<` no comentario sao comuns em livro de xadrez ("Black &
        White"), e crus eles produzem um arquivo que nenhuma ferramenta abre."""
        self.semear([("Black & <White>", "Pretas & <Brancas>", "en", "pt")])

        _unidades, destino = self.exportar()

        bruto = destino.read_text(encoding="utf-8")
        self.assertIn("Black &amp; &lt;White&gt;", bruto)
        segmentos = [s.text for s in ET.parse(destino).getroot().findall(".//seg")]
        self.assertEqual(segmentos, ["Black & <White>", "Pretas & <Brancas>"])

    def test_a_forbidden_control_character_is_removed(self):
        """O XML 1.0 nao aceita controle C0 nem escapado: um deles no meio de um
        comentario produz um arquivo que nao abre — e o erro apareceria na
        ferramenta do usuario, nao aqui."""
        self.semear([("antes\x01depois", "traducao", "en", "pt")])

        _unidades, destino = self.exportar()

        segmentos = [s.text for s in ET.parse(destino).getroot().findall(".//seg")]
        self.assertEqual(segmentos[0], "antesdepois")

    def test_the_tuid_is_the_database_id(self):
        """E o que permite reconhecer a mesma unidade depois de uma ida e volta pelo
        OmegaT (ROADMAP 19, item 8)."""
        self.semear([("a", "b", "en", "pt")])
        conn = initialize_database(str(self.db_path))
        row_id = conn.execute("SELECT id FROM comments").fetchone()[0]
        conn.close()

        _unidades, destino = self.exportar()

        self.assertEqual(
            ET.parse(destino).getroot().find(".//tu").get("tuid"), str(row_id)
        )

    def test_canceling_leaves_no_half_written_file(self):
        """Um TMX truncado nao fecha `</body>`, entao ele nao abre em ferramenta
        nenhuma — mas o usuario so descobre isso depois de ter contado com ele."""
        self.semear([("a", "b", "en", "pt")])
        destino = self.base / "memoria.tmx"

        with self.assertRaises(TaskCanceled):
            db_tools.export_translations_to_tmx(
                str(self.db_path), str(destino), should_cancel=lambda: True
            )

        self.assertFalse(destino.exists())


class ExportCsvIdColumnTests(unittest.TestCase):
    """O `id` no CSV (ROADMAP 19, item 8) e a exportacao de uma selecao (item 9)."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.db_path = self.base / "cache.db"
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        for i in range(4):
            save_translation(cur, f"orig {i}", f"trad {i}", "pt", "en")
        conn.commit()
        self.ids = [r[0] for r in cur.execute("SELECT id FROM comments ORDER BY id")]
        conn.close()

    def exportar(self, **kwargs):
        destino = self.base / "saida.csv"
        db_tools.export_translations_to_csv(str(self.db_path), str(destino), **kwargs)
        with open(destino, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def test_the_id_is_the_first_column(self):
        gravadas = self.exportar()

        self.assertEqual(gravadas[0][0], "id")
        self.assertEqual([linha[0] for linha in gravadas[1:]], [str(i) for i in self.ids])

    def test_the_exported_file_is_still_importable(self):
        """A coluna nova nao pode quebrar o round-trip: o CSV exportado tem de voltar
        pela importacao, que le por NOME de coluna."""
        destino = self.base / "saida.csv"
        db_tools.export_translations_to_csv(str(self.db_path), str(destino))

        previa = db_tools.analyze_translations_csv_import(
            str(self.db_path), str(destino)
        )

        self.assertEqual(previa["total_rows"], 4)
        self.assertEqual(previa["inserted"], 0)

    def test_the_status_and_the_note_are_exported(self):
        """Nada do que o revisor escreveu pode ficar preso no programa."""
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        set_review_status_by_id(cur, self.ids[0], REVIEW_STATUS_DOUBT, note="ver autor")
        conn.commit()
        conn.close()

        gravadas = self.exportar()
        cabecalho = gravadas[0]
        linha = gravadas[1]

        self.assertEqual(linha[cabecalho.index("review_status")], "doubt")
        self.assertEqual(linha[cabecalho.index("reviewer_note")], "ver autor")

    def test_only_the_selected_ids_are_exported(self):
        gravadas = self.exportar(only_ids=[self.ids[1], self.ids[3]])

        self.assertEqual(
            [linha[0] for linha in gravadas[1:]],
            [str(self.ids[1]), str(self.ids[3])],
        )

    def test_an_empty_selection_exports_nothing(self):
        """Lista vazia nao e o mesmo que `None`: exportar o banco inteiro para quem
        pediu nada e o pior desfecho possivel de "exportar a selecao"."""
        gravadas = self.exportar(only_ids=[])

        self.assertEqual(len(gravadas), 1, "so o cabecalho")


class WrapPgnCommentTests(unittest.TestCase):
    """Requebra em 80 colunas na gravacao (ROADMAP 19, item 13)."""

    def test_no_line_passes_the_width(self):
        texto = " ".join(["palavra"] * 30)
        linhas = wrap_pgn_comment(texto, 40, 40).split("\n")

        self.assertTrue(len(linhas) > 1)
        self.assertTrue(all(len(l) <= 40 for l in linhas), linhas)

    def test_only_whitespace_changes(self):
        """A promessa que permite requebrar sem tocar na chave de cache: as palavras
        saem na mesma ordem e com os mesmos caracteres."""
        texto = "a coluna aberta e uma estrada para a torre"
        requebrado = wrap_pgn_comment(texto, 20, 20)

        self.assertEqual(requebrado.split(), texto.split())

    def test_the_first_line_knows_it_starts_mid_line(self):
        """Depois de `12. Nf3 {` sobra menos espaco. Sem isso, a requebra acertaria
        todas as linhas menos a unica que divide espaco com o movetext."""
        texto = "uma duas tres quatro cinco"

        primeira = wrap_pgn_comment(texto, 30, 10).split("\n")[0]

        self.assertLessEqual(len(primeira), 10)

    def test_an_annotation_is_never_broken(self):
        """A garantia X1 gastou uma secao protegendo esses spans; quebra-los na
        gravacao seria desfazer o trabalho no ultimo passo."""
        texto = "antes [%cal Ra1h8,Rb2b7] depois"

        for largura in range(12, 32):
            requebrado = wrap_pgn_comment(texto, largura, largura)
            self.assertIn("[%cal Ra1h8,Rb2b7]", requebrado, largura)

    def test_a_word_longer_than_the_line_stays_whole(self):
        """Cortar no meio dela produziria um token que nao existe."""
        gigante = "a" * 50
        requebrado = wrap_pgn_comment(f"antes {gigante} depois", 20, 20)

        self.assertIn(gigante, requebrado)

    def test_an_empty_comment_survives(self):
        self.assertEqual(wrap_pgn_comment("", 80, 80), "")
        self.assertEqual(wrap_pgn_comment(None, 80, 80), "")


class WrapOnDiskTests(unittest.TestCase):
    """A requebra dentro da gravacao do PGN, com o fim de linha do arquivo."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.texto = (
            "A coluna aberta e uma estrada para a torre, e as pretas precisam "
            "disputa-la agora mesmo antes que seja tarde demais para isso."
        )

    def gerar(self, eol, **kwargs):
        entrada = self.base / "entrada.pgn"
        entrada.write_bytes(
            f'[Event "A"]{eol}{eol}1. e4 {{{self.texto}}} 1-0{eol}'.encode("utf-8")
        )
        info = extract_comments_from_file(str(entrada))
        saida = self.base / "saida.pgn"
        generate_translated_pgn(
            str(entrada), str(saida), {info["comments"][0]: self.texto},
            info["positions"], **kwargs
        )
        return saida.read_bytes()

    def test_it_is_off_by_default(self):
        """O comportamento de sempre: comentario em linha unica."""
        bruto = self.gerar("\n").decode("utf-8")

        self.assertIn("{" + self.texto + "}", bruto)

    def test_with_the_width_no_line_passes_it(self):
        bruto = self.gerar("\n", wrap_columns=80).decode("utf-8")

        self.assertTrue(any("\n" in l for l in [bruto]))
        for linha in bruto.split("\n"):
            self.assertLessEqual(len(linha), 80, linha)

    def test_the_line_ending_of_the_file_is_used(self):
        """O conteudo e lido com `newline=''` justamente para o `\\r\\n` sobreviver
        (ROADMAP 13.6): inserir `\\n` puro daria um PGN de fim de linha misturado."""
        bruto = self.gerar("\r\n", wrap_columns=80)

        self.assertNotIn(b"\n", bruto.replace(b"\r\n", b""))

    def test_the_words_are_the_same_as_without_wrapping(self):
        sem = self.gerar("\n").decode("utf-8")
        com = self.gerar("\n", wrap_columns=60).decode("utf-8")

        self.assertEqual(sem.split(), com.split())


class ReviewStatusTests(unittest.TestCase):
    """Status alem do binario, e o par de campos em lockstep (item 12)."""

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.conn = initialize_database(str(Path(self.sandbox.name) / "cache.db"))
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        save_translation(self.cur, "the rook", "a torre", "pt", "en")
        save_translation(self.cur, "the bishop", "o bispo", "pt", "en")
        self.conn.commit()
        self.ids = [r[0] for r in self.cur.execute("SELECT id FROM comments ORDER BY id")]

    def status(self, comment_id):
        return fetch_review_status_by_id(self.cur, comment_id)

    def verified(self, comment_id):
        return self.cur.execute(
            "SELECT verified FROM comments WHERE id = ?", (comment_id,)
        ).fetchone()[0]

    def test_rejecting_stores_the_status_and_the_note(self):
        set_review_status_by_id(
            self.cur, self.ids[0], REVIEW_STATUS_REJECTED, note="termo inventado"
        )
        self.conn.commit()

        self.assertEqual(
            self.status(self.ids[0]), (REVIEW_STATUS_REJECTED, "termo inventado")
        )

    def test_a_status_beyond_pending_drops_the_verified_bit(self):
        """Rejeitar uma linha verificada e dizer que a verificacao estava errada.
        Deixar o bit de pe a manteria fora do filtro de pendentes, e ela nunca
        voltaria para a fila de ninguem."""
        set_translation_verified_by_id(self.cur, self.ids[0])
        self.conn.commit()
        self.assertEqual(self.verified(self.ids[0]), 1)

        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_DOUBT)
        self.conn.commit()

        self.assertEqual(self.verified(self.ids[0]), 0)
        self.assertIsNone(
            self.cur.execute(
                "SELECT verified_at FROM comments WHERE id = ?", (self.ids[0],)
            ).fetchone()[0]
        )

    def test_verifying_clears_the_status(self):
        """O outro lado do lockstep: uma traducao aceita nao esta "em duvida"."""
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_DOUBT, note="ver")
        self.conn.commit()

        set_translation_verified_by_id(self.cur, self.ids[0])
        self.conn.commit()

        self.assertEqual(self.status(self.ids[0])[0], REVIEW_STATUS_PENDING)
        self.assertEqual(self.verified(self.ids[0]), 1)
        # A NOTA fica: ela e o que o revisor escreveu, e verificar a linha nao
        # apaga o que ele disse sobre ela.
        self.assertEqual(self.status(self.ids[0])[1], "ver")

    def test_the_note_is_kept_when_only_the_status_changes(self):
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_DOUBT, note="ver")
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_REJECTED)
        self.conn.commit()

        self.assertEqual(self.status(self.ids[0]), (REVIEW_STATUS_REJECTED, "ver"))

    def test_an_unknown_status_is_refused(self):
        """O campo e um enum de tres valores. Um quarto valor gravado por engano
        criaria uma linha que nenhum filtro mostra."""
        with self.assertRaises(ValueError):
            set_review_status_by_id(self.cur, self.ids[0], "arquivada")

    def test_the_filters_separate_the_two_new_states(self):
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_REJECTED)
        set_review_status_by_id(self.cur, self.ids[1], REVIEW_STATUS_DOUBT)
        self.conn.commit()

        rejeitadas = fetch_review_rows(
            self.cur, "pt", status_filter=REVIEW_STATUS_REJECTED
        )
        duvidas = fetch_review_rows(self.cur, "pt", status_filter=REVIEW_STATUS_DOUBT)

        self.assertEqual([l[1] for l in rejeitadas], ["the rook"])
        self.assertEqual([l[1] for l in duvidas], ["the bishop"])

    def test_the_new_states_are_subsets_of_pending(self):
        """Somar rejeitadas e em duvida ao pendente daria um total maior que a
        tabela."""
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_REJECTED)
        self.conn.commit()

        resumo = get_review_status_counts(self.cur, "pt")

        self.assertEqual(resumo["total"], 2)
        self.assertEqual(resumo["pending"], 2)
        self.assertEqual(resumo[REVIEW_STATUS_REJECTED], 1)
        self.assertEqual(resumo[REVIEW_STATUS_DOUBT], 0)

    def test_the_page_count_of_the_new_filters_comes_from_the_summary(self):
        """Se o resumo e o total do filtro divergirem, a lista pagina pelo numero
        errado sem nada quebrar na tela."""
        set_review_status_by_id(self.cur, self.ids[0], REVIEW_STATUS_REJECTED)
        self.conn.commit()

        resumo = get_review_status_counts(self.cur, "pt")
        for filtro in (REVIEW_STATUS_REJECTED, REVIEW_STATUS_DOUBT):
            self.assertEqual(
                count_from_status_counts(resumo, filtro),
                count_review_rows(self.cur, "pt", status_filter=filtro),
                filtro,
            )

    def test_an_inconsistent_row_does_not_leak_into_the_filter(self):
        """A guarda `verified <> 1` do filtro, exercitada pelo caso que ela existe
        para pegar.

        Pelo caminho do programa esse estado nao acontece — o lockstep o impede —,
        entao o teste o escreve com SQL cru, que e o que um `UPDATE` de fora (uma
        restauracao pela metade, uma ferramenta externa) produziria. Sem a guarda, a
        linha apareceria ao mesmo tempo em "Verificadas" e em "Rejeitadas", e nenhuma
        das duas contagens fecharia com o total.
        """
        self.cur.execute(
            "UPDATE comments SET verified = 1, review_status = ? WHERE id = ?",
            (REVIEW_STATUS_REJECTED, self.ids[0]),
        )
        self.conn.commit()

        rejeitadas = fetch_review_rows(
            self.cur, "pt", status_filter=REVIEW_STATUS_REJECTED
        )
        resumo = get_review_status_counts(self.cur, "pt")

        self.assertEqual(rejeitadas, [])
        self.assertEqual(resumo[REVIEW_STATUS_REJECTED], 0)
        self.assertEqual(resumo["verified"], 1)

    def test_a_migrated_database_reads_every_row_as_pending(self):
        """Um banco anterior ao schema 8 nao tem a coluna: ela entra com `''` para
        todas as linhas, e `''` e pendente."""
        self.assertEqual(self.status(self.ids[1]), (REVIEW_STATUS_PENDING, ""))
        self.assertEqual(
            get_review_status_counts(self.cur, "pt")[REVIEW_STATUS_REJECTED], 0
        )


class DiffSpansTests(unittest.TestCase):
    """As faixas pintadas na previa de "Aplicar todas" (item 5)."""

    def test_the_changed_word_is_marked_on_both_sides(self):
        antes = "a coluna aberta"
        depois = "a fileira aberta"

        faixas_antes, faixas_depois = diff_spans(antes, depois)

        self.assertEqual([antes[i:f] for i, f in faixas_antes], ["coluna"])
        self.assertEqual([depois[i:f] for i, f in faixas_depois], ["fileira"])

    def test_identical_texts_have_no_spans(self):
        self.assertEqual(diff_spans("igual", "igual"), ([], []))

    def test_the_diff_is_by_word_and_not_by_character(self):
        """Por caractere, `torre`/`Torre` viraria um `T` trocado no meio de uma
        palavra inteira pintada de igual — e o que o revisor precisa ver e a palavra
        que mudou."""
        antes, depois = "a torre", "a Torre"

        _antes_spans, faixas_depois = diff_spans(antes, depois)

        self.assertEqual([depois[i:f] for i, f in faixas_depois], ["Torre"])

    def test_an_insertion_marks_only_the_new_side(self):
        faixas_antes, faixas_depois = diff_spans("a torre", "a torre branca")

        self.assertEqual(faixas_antes, [])
        self.assertEqual(len(faixas_depois), 1)

    def test_many_replacements_are_all_marked(self):
        """O caso do item: conferir 80 substituicoes a olho nu e o mesmo que nao
        conferir."""
        antes = " ".join(f"palavra{i}" for i in range(10))
        depois = " ".join(
            (f"trocada{i}" if i % 2 == 0 else f"palavra{i}") for i in range(10)
        )

        _faixas_antes, faixas_depois = diff_spans(antes, depois)

        self.assertEqual(len(faixas_depois), 5)


class SettingsConcurrencyTests(unittest.TestCase):
    """O rascunho passou a gravar em segundo plano (item 10).

    Duas threads chamando `update_settings` sem lock fazem a segunda ler o disco
    ANTES de a primeira gravar, e o que a primeira escreveu desaparece — a perda que
    a garantia R4 existe para impedir, agora por corrida.
    """

    def test_concurrent_updates_do_not_lose_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "settings.json")

            def gravar(indice):
                def mutator(disk):
                    disk[f"chave_{indice}"] = indice
                settings.update_settings(mutator, caminho)

            threads = [
                threading.Thread(target=gravar, args=(i,)) for i in range(24)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            gravado = settings.load_settings(caminho)
            self.assertEqual(
                sorted(gravado), sorted(f"chave_{i}" for i in range(24))
            )


def _pgn_com_comentarios(caminho, quantos, tamanho=180, prefixo="c"):
    """PGN sintetico com `quantos` comentarios distintos. Devolve o caminho.

    Usado nas medicoes da secao 20: os testes de custo precisam de um arquivo
    grande o bastante para que a diferenca entre O(n) e O(n.m) apareca, e pequeno
    o bastante para a suite nao demorar.
    """
    partes = ['[Event "Medicao"]\n[Site "?"]\n\n']
    for i in range(quantos):
        partes.append(f"{i % 60 + 1}. Nf3 {{{prefixo} {i} " + "x" * tamanho + "}} Nf6 ")
        if i % 20 == 19:
            partes.append("\n")
    partes.append("1-0\n")
    Path(caminho).write_text("".join(partes), encoding="utf-8", newline="")
    return str(caminho)


class GenerationIsLinearTests(unittest.TestCase):
    """A gravacao refazia o arquivo INTEIRO a cada comentario (ROADMAP 20.1).

    `content[:start] + rep + content[end:]`, uma vez por comentario, custa o
    PRODUTO do numero de comentarios pelo tamanho do arquivo. Medido nesta
    maquina: 15.000 comentarios num PGN de 3,2 MB levavam 26,9 s; com uma passada
    e `"".join`, 18,9 ms.

    E uma das duas familias que mutacao nenhuma pega (a producao estava correta,
    so lenta), entao o que a protege e cronometro — como no teste do `busy_timeout`.
    """

    def test_eight_thousand_comments_are_written_in_well_under_a_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            entrada = _pgn_com_comentarios(Path(tmp) / "grande.pgn", 8000)
            info = extract_comments_from_file(entrada)
            mapa = {c: c.upper() for c in info["comments"]}
            saida = str(Path(tmp) / "grande-BR.pgn")

            comeco = time.perf_counter()
            ok = generate_translated_pgn(entrada, saida, mapa, info["positions"])
            decorrido = time.perf_counter() - comeco

        self.assertTrue(ok)
        # A versao quadratica levava 6,5 s aqui; a linear, 9,6 ms. O limite e
        # generoso de proposito — o que ele precisa distinguir e uma ordem de
        # grandeza, e nao a velocidade desta maquina.
        self.assertLess(
            decorrido,
            0.5,
            f"a geracao levou {decorrido:.2f}s; a versao O(n.m) levava 6,5s",
        )

    def test_the_output_is_the_same_the_slow_version_produced(self):
        """A forma nova nao pode mudar o arquivo, so o tempo de escreve-lo."""
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text(
                '[Event "T"]\r\n\r\n'
                "1. e4 {Primeiro} e5 {Segundo} 2. Nf3 {Terceiro} Nc6 *\r\n",
                encoding="utf-8",
                newline="",
            )
            info = extract_comments_from_file(str(pgn))
            saida = str(Path(tmp) / "game-BR.pgn")
            generate_translated_pgn(
                str(pgn),
                saida,
                {"Primeiro": "Um", "Segundo": "", "Terceiro": "Tres"},
                info["positions"],
            )
            texto = Path(saida).read_text(encoding="utf-8", newline="")

        # `{Segundo}` sai inteiro, com um espaco vizinho (garantia X2); os outros
        # dois viram a traducao; o `\r\n` do original sobrevive (ROADMAP 13.6).
        self.assertEqual(
            texto,
            '[Event "T"]\r\n\r\n1. e4 {Um} e5 2. Nf3 {Tres} Nc6 *\r\n',
        )

    def test_two_emptied_comments_side_by_side_do_not_eat_the_rest_of_the_file(self):
        """O caso que a versao anterior destruia, e que precisava de DOIS erros.

        `{a} {b}` com os dois esvaziados: o span de `{b}` reclamava para tras o
        espaco que o de `{a}` ja havia levado, e os dois spans sobrepostos, com a
        substituicao da direita para a esquerda, apagavam tudo o que vinha depois.

        A rodada de mutacao mostrou que cada uma das duas mudancas basta: com a
        passada unica, uma sobreposicao de um caractere so produz uma fatia vazia;
        com o limite do span anterior, ela nao se forma. Por isso a mutacao que
        tira **so** o limite sobrevive a este teste — o que ele protege e o
        comportamento, e o comportamento tem duas trancas.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text(
                '[Event "T"]\n\n1. e4 {a} {b}1-0\n', encoding="utf-8", newline=""
            )
            info = extract_comments_from_file(str(pgn))
            saida = str(Path(tmp) / "game-BR.pgn")
            generate_translated_pgn(
                str(pgn), saida, {"a": "", "b": ""}, info["positions"]
            )
            texto = Path(saida).read_text(encoding="utf-8", newline="")

        self.assertIn("1-0", texto)
        self.assertNotIn("{a}", texto)
        self.assertNotIn("{b}", texto)
        self.assertEqual(texto, '[Event "T"]\n\n1. e4 1-0\n')

    def test_the_generation_does_not_hold_a_second_copy_of_the_file(self):
        """Gravar pedaco por pedaco, em vez de juntar tudo antes.

        O `"".join` produzia o PGN de saida inteiro na memoria ao lado do de
        entrada. Medido nesta maquina, num PGN de 3,2 MB: 15,1 MB de pico com o
        `join` contra 7,8 MB gravando os pedacos. Trocar 27 s por 8 MB de pico
        seria consertar metade do item.
        """
        import tracemalloc

        with tempfile.TemporaryDirectory() as tmp:
            entrada = _pgn_com_comentarios(Path(tmp) / "grande.pgn", 15000)
            tamanho = os.path.getsize(entrada)
            info = extract_comments_from_file(entrada)
            mapa = {c: c.upper() for c in info["comments"]}
            saida = str(Path(tmp) / "grande-BR.pgn")

            tracemalloc.start()
            generate_translated_pgn(entrada, saida, mapa, info["positions"])
            pico = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()

            self.assertEqual(
                len(Path(saida).read_text(encoding="utf-8")),
                len(Path(entrada).read_text(encoding="utf-8")),
                "o arquivo de saida saiu incompleto",
            )

        # Duas vezes o arquivo: o conteudo lido e o mapa das traducoes. A terceira
        # copia — o arquivo de saida montado por `join` — e a que saiu.
        self.assertLess(
            pico,
            3 * tamanho,
            f"pico de {pico/1e6:.1f} MB para um PGN de {tamanho/1e6:.1f} MB",
        )

    def test_the_bom_is_written_once_and_not_once_per_piece(self):
        """O risco que a gravacao por pedacos cria, fixado como teste.

        `utf-8-sig` e `utf-16` escrevem a marca de ordem de bytes na PRIMEIRA
        codificacao, e o encoder incremental sabe disso. Se algum dia deixar de
        saber — ou se alguem trocar o `write` por um `open` por pedaco —, cada
        pedaco levaria a sua BOM e o arquivo sairia impresstavel para qualquer
        leitor. Um `assertIn` no texto nao pegaria: as BOMs viram caracteres
        invisiveis no meio da prosa.
        """
        with tempfile.TemporaryDirectory() as tmp:
            casos = {
                "com-bom.pgn": ("utf-8", True, b"\xef\xbb\xbf"),
                "sig.pgn": ("utf-8-sig", False, b"\xef\xbb\xbf"),
                "utf16.pgn": ("utf-16", False, b"\xff\xfe"),
            }
            for nome, (codificacao, bom, marca) in casos.items():
                alvo = Path(tmp) / nome
                pgn_utils.write_pgn_pieces(
                    str(alvo),
                    lambda: ["um ", "dois ", "tres"],
                    codificacao,
                    use_bom=bom,
                )
                cru = alvo.read_bytes()

                self.assertTrue(cru.startswith(marca), nome)
                self.assertEqual(cru.count(marca), 1, f"{nome}: {cru[:30]!r}")

    def test_a_translation_the_input_encoding_cannot_hold_falls_back_to_utf8(self):
        """O fallback de codificacao, agora que a gravacao e por pedacos.

        O erro de codificacao acontece NO MEIO da gravacao — o `w` da segunda
        tentativa e o que trunca o arquivo pela metade que a primeira deixou. Sem
        isso, o PGN de saida ficaria cortado no primeiro caractere que o cp1252
        nao aceita, e o log diria que deu tudo certo.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            # Com acento: um PGN so de ASCII e detectado como UTF-8 (nunca como
            # 'ascii'), e o fallback que este teste exercita nao aconteceria.
            movetext = " ".join(
                f"{i + 1}. e4 {{comentário {i} com ação}}" for i in range(400)
            )
            pgn.write_text(f'[Event "T"]\n\n{movetext} *\n', encoding="cp1252")
            info = extract_comments_from_file(str(pgn))
            self.assertEqual(detect_encoding(str(pgn)), "cp1252")

            # O ultimo comentario recebe um caractere que o cp1252 nao representa.
            mapa = {c: c for c in info["comments"]}
            mapa[info["comments"][-1]] = "posicao ganha 中"
            saida = str(Path(tmp) / "game-BR.pgn")
            logs = []

            ok = generate_translated_pgn(
                str(pgn), saida, mapa, info["positions"], logs.append
            )

            self.assertTrue(ok)
            texto = Path(saida).read_text(encoding="utf-8")
            self.assertIn("posicao ganha 中", texto)
            self.assertTrue(texto.rstrip().endswith("*"), "o arquivo saiu truncado")
            self.assertEqual(texto.count("{"), 400)

        self.assertTrue(
            any("UTF-8" in linha for linha in logs),
            f"a troca de codificacao tem de aparecer no log: {logs}",
        )

    def test_cancelling_stops_the_generation_before_writing_anything(self):
        """A fase nao tinha checagem de `cancel_flag` nenhuma (ROADMAP 20.1)."""
        with tempfile.TemporaryDirectory() as tmp:
            entrada = _pgn_com_comentarios(Path(tmp) / "grande.pgn", 600)
            info = extract_comments_from_file(entrada)
            mapa = {c: c.upper() for c in info["comments"]}
            saida = Path(tmp) / "grande-BR.pgn"
            bandeira = threading.Event()
            bandeira.set()
            logs = []

            ok = generate_translated_pgn(
                entrada,
                str(saida),
                mapa,
                info["positions"],
                logs.append,
                cancel_flag=bandeira,
            )

            self.assertFalse(ok)
            self.assertFalse(
                saida.exists(),
                "um arquivo cancelado no meio nao pode ficar em disco",
            )

        self.assertTrue(
            any("cancelada" in linha.lower() for linha in logs),
            f"o cancelamento tem de aparecer no log: {logs}",
        )

    def test_a_flag_that_is_not_set_generates_the_file(self):
        """O cenario parte do valor que NAO e o padrao, e depois volta a ele."""
        with tempfile.TemporaryDirectory() as tmp:
            entrada = _pgn_com_comentarios(Path(tmp) / "g.pgn", 30)
            info = extract_comments_from_file(entrada)
            saida = Path(tmp) / "g-BR.pgn"

            ok = generate_translated_pgn(
                entrada,
                str(saida),
                {c: "x" for c in info["comments"]},
                info["positions"],
                cancel_flag=threading.Event(),
            )

            self.assertTrue(ok)
            self.assertTrue(saida.exists())


class ReadPgnOnceTests(unittest.TestCase):
    """Cada PGN era lido quatro vezes por execucao (ROADMAP 20.2).

    A deteccao de codificacao lia o arquivo inteiro em bytes, a extracao abria
    de novo em modo texto, e a geracao repetia as duas. `read_pgn_text` le uma
    vez e detecta nos bytes que leu.
    """

    def contar_leituras(self, alvo, acao):
        real = open
        leituras = []

        def contando(path, mode="r", *args, **kwargs):
            if os.path.abspath(str(path)) == os.path.abspath(alvo) and "r" in mode:
                leituras.append(mode)
            return real(path, mode, *args, **kwargs)

        import builtins

        builtins.open = contando
        try:
            resultado = acao()
        finally:
            builtins.open = real
        return leituras, resultado

    def test_the_extraction_opens_the_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = _pgn_com_comentarios(Path(tmp) / "game.pgn", 20)
            leituras, info = self.contar_leituras(
                pgn, lambda: extract_comments_from_file(pgn)
            )

        self.assertEqual(len(leituras), 1, f"leituras: {leituras}")
        self.assertEqual(len(info["comments"]), 20)

    def test_the_generation_does_not_reread_when_it_gets_the_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            pgn = _pgn_com_comentarios(Path(tmp) / "game.pgn", 20)
            conteudo, enc = read_pgn_text(pgn)
            info = extract_comments_from_content(conteudo)
            saida = str(Path(tmp) / "game-BR.pgn")

            leituras, ok = self.contar_leituras(
                pgn,
                lambda: generate_translated_pgn(
                    pgn,
                    saida,
                    {c: c.upper() for c in info["comments"]},
                    info["positions"],
                    content=conteudo,
                    encoding=enc,
                ),
            )

            self.assertTrue(ok)
            self.assertEqual(leituras, [], "o arquivo nao devia ser lido de novo")
            self.assertIn("X" * 10, Path(saida).read_text(encoding="utf-8"))

    def test_the_generation_still_reads_the_file_when_it_gets_nothing(self):
        """O caminho antigo continua valendo: quem nao passa conteudo, le."""
        with tempfile.TemporaryDirectory() as tmp:
            pgn = _pgn_com_comentarios(Path(tmp) / "game.pgn", 5)
            info = extract_comments_from_file(pgn)
            saida = str(Path(tmp) / "game-BR.pgn")

            leituras, ok = self.contar_leituras(
                pgn,
                lambda: generate_translated_pgn(
                    pgn, saida, {c: "y" for c in info["comments"]}, info["positions"]
                ),
            )

            self.assertTrue(ok)
            self.assertEqual(len(leituras), 1)

    def test_read_pgn_text_agrees_with_detect_plus_open(self):
        """Sem mudanca de comportamento: o texto e a codificacao sao os mesmos.

        As codificacoes cobertas sao as que as garantias E1-E4 protegem, e o
        `\\r\\n` esta ali por 13.6: `read_pgn_text` nao pode traduzir fim de linha,
        como o `open(..., newline='')` que ele substitui nao traduzia.
        """
        casos = {
            "utf8.pgn": ('[Event "Ação"]\r\n\r\n1. e4 {Comentário} *\r\n', "utf-8"),
            "bom.pgn": ('[Event "Ação"]\n\n1. e4 {ok} *\n', "utf-8-sig"),
            "cp1252.pgn": ('[Event "Ação"]\n\n1. e4 {ok} *\n', "cp1252"),
            "utf16.pgn": ('[Event "Ação"]\n\n1. e4 {ok} *\n', "utf-16"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for nome, (texto, codificacao) in casos.items():
                caminho = Path(tmp) / nome
                caminho.write_text(texto, encoding=codificacao, newline="")

                esperado_enc = detect_encoding(str(caminho))
                with open(
                    str(caminho), "r", encoding=esperado_enc, errors="replace",
                    newline="",
                ) as handle:
                    esperado = handle.read()

                conteudo, enc = read_pgn_text(str(caminho))

                self.assertEqual(enc, esperado_enc, nome)
                self.assertEqual(conteudo, esperado, nome)

    def test_detect_from_bytes_answers_like_detect_from_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.pgn"
            caminho.write_text("1. e4 {ação} *\n", encoding="cp1252")

            self.assertEqual(
                detect_encoding_from_bytes(caminho.read_bytes()),
                detect_encoding(str(caminho)),
            )


class CheapFirstPassTests(unittest.TestCase):
    """A primeira passada le so os textos (ROADMAP 20.4).

    Posicao e contexto de leitura custam 174 ms dos 263 ms da extracao num PGN de
    3,2 MB, e nao servem para nada antes da vez do arquivo.
    """

    def test_the_cheap_extraction_finds_the_same_texts(self):
        conteudo = (
            '[Event "T"]\n\n1. e4 {Primeiro} e5 {} 2. Nf3 {Segundo} ; nota\n'
        )
        completa = extract_comments_from_content(conteudo)
        barata = extract_comment_texts(conteudo)

        self.assertEqual(barata["comments"], completa["comments"])
        self.assertEqual(
            barata["semicolon_comments"], completa["semicolon_comments"]
        )
        self.assertEqual(barata["semicolon_comments"], 1)
        self.assertNotIn("positions", barata)

    def test_the_cheap_extraction_reports_the_encoding_and_survives_a_bad_file(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text('[Event "T"]\n\n1. e4 {ok} *\n', encoding="utf-8")

            info = extract_comment_texts_from_file(str(pgn), logs.append)
            self.assertEqual(info["comments"], ["ok"])
            self.assertTrue(
                any("Codificacao detectada" in linha for linha in logs), logs
            )

            ausente = extract_comment_texts_from_file(
                str(Path(tmp) / "nao-existe.pgn"), logs.append
            )

        self.assertEqual(ausente["comments"], [])
        self.assertEqual(ausente["semicolon_comments"], 0)
        self.assertTrue(any("[ERRO]" in linha for linha in logs), logs)

    def test_known_texts_reuses_the_object_instead_of_a_second_equal_one(self):
        """Ler o arquivo duas vezes nao pode fazer o texto viver duas vezes.

        A segunda extracao devolve o MESMO objeto que a primeira passada guardou.
        `assertEqual` passaria de qualquer jeito — o que este teste afirma e
        identidade, que e o que decide se a memoria e uma copia ou um ponteiro
        (ROADMAP 20.4).
        """
        conteudo = '[Event "T"]\n\n1. e4 {Primeiro} e5 {Segundo} *\n'
        primeiro = extract_comment_texts(conteudo)["comments"][0]
        conhecidos = {primeiro: primeiro}

        com = extract_comments_from_content(conteudo, known_texts=conhecidos)
        sem = extract_comments_from_content(conteudo)

        self.assertIs(com["comments"][0], primeiro)
        self.assertIs(com["positions"][0][2], primeiro)
        self.assertIsNot(sem["comments"][0], primeiro)
        # O que nao esta no mapa continua saindo como texto novo, e igual.
        self.assertEqual(com["comments"][1], "Segundo")

    def test_skipping_the_semicolon_count_does_not_change_the_comments(self):
        conteudo = '[Event "T"]\n\n1. e4 {ok} ; nota\n'
        com = extract_comments_from_content(conteudo)
        sem = extract_comments_from_content(conteudo, count_semicolons=False)

        self.assertEqual(sem["comments"], com["comments"])
        self.assertEqual(sem["positions"], com["positions"])
        self.assertEqual(com["semicolon_comments"], 1)
        self.assertEqual(sem["semicolon_comments"], 0)


class WorkerDeduplicatesTheBatchTests(unittest.TestCase):
    """Duplicatas dentro do arquivo pagavam API (ROADMAP 20.3).

    O cache so aprende a traducao depois da resposta, e o lote inteiro sai antes
    dela: um capitulo com "Diagram" trinta vezes enviava as trinta.
    """

    PGN = (
        '[Event "T"]\n\n'
        "1. e4 {Diagram} e5 {Diagram} 2. Nf3 {Comentario unico} "
        "Nc6 {Diagram} 3. Bb5 {Diagram} *\n"
    )

    def rodar(self, tmp_path, conteudo=None, nome="game.pgn"):
        pgn = tmp_path / nome
        pgn.write_text(conteudo or self.PGN, encoding="utf-8")
        app = FakeApp(tmp_path / "cache.db")
        enviados = []

        def translate(text, *_args, **_kwargs):
            enviados.append(text)
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        originais = (
            translation_worker.translate_text,
            translation_worker.messagebox.showinfo,
            translation_worker.messagebox.showwarning,
        )
        translation_worker.translate_text = translate
        translation_worker.messagebox.showinfo = lambda *_a, **_k: None
        translation_worker.messagebox.showwarning = lambda *_a, **_k: None
        try:
            translation_worker.run_translation(app, str(pgn), "pt", False)
        finally:
            (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
                translation_worker.messagebox.showwarning,
            ) = originais

        return app, pgn, enviados

    def test_the_repeated_comment_is_sent_to_the_api_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            _app, _pgn, enviados = self.rodar(Path(tmp))

        partes = [p for envio in enviados for p in envio.split(" ||| ")]
        self.assertEqual(
            partes.count("Diagram"),
            1,
            f"o comentario repetido foi enviado {partes.count('Diagram')} vezes: "
            f"{enviados}",
        )
        self.assertEqual(partes.count("Comentario unico"), 1)

    def test_every_occurrence_is_still_replaced_in_the_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _app, pgn, _enviados = self.rodar(Path(tmp))
            saida = Path(str(pgn).replace("game.pgn", "game-BR.pgn"))
            texto = saida.read_text(encoding="utf-8")

        self.assertEqual(texto.count("{[Diagram]}"), 4)
        self.assertIn("{[Comentario unico]}", texto)
        self.assertNotIn("{Diagram}", texto)

    def test_the_counters_account_for_every_comment(self):
        """5 comentarios = 2 traduzidos + 3 repeticoes, e o log diz os tres.

        Antes, o resumo mostrava "Total: 5" e "Novas: 2" e os outros tres nao
        apareciam em contador nenhum: a segunda gravacao da mesma chave volta
        "unchanged", que nao e contado em lugar nenhum.
        """
        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn, _enviados = self.rodar(Path(tmp))

        self.assertTrue(
            any("Total de comentarios detectados: 5" in l for l in app.logs), app.logs
        )
        self.assertTrue(
            any(
                "Comentarios repetidos dentro do proprio arquivo: 3" in l
                for l in app.logs
            ),
            app.logs,
        )
        self.assertTrue(
            any("Comentarios novos traduzidos nesta execucao: 2" in l for l in app.logs),
            app.logs,
        )
        self.assertTrue(
            any(
                "Comentarios repetidos no proprio arquivo (nao reenviados): 3" in l
                for l in app.logs
            ),
            app.logs,
        )

    def test_a_file_without_repetition_says_nothing_about_repetition(self):
        """O mesmo criterio das linhas de lances e de `;`: so quando existe."""
        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn, _enviados = self.rodar(
                Path(tmp),
                conteudo='[Event "T"]\n\n1. e4 {Um} e5 {Outro} *\n',
            )

        self.assertFalse(
            any("repetido" in linha.lower() for linha in app.logs), app.logs
        )

    def test_the_progress_bar_reaches_the_end_while_processing(self):
        """Com o denominador antigo (5) e dois passos, a barra parava em 40%.

        O `finally` poe a barra em 100% de qualquer jeito, entao o que este teste
        olha e o ultimo valor ANTES dele.
        """
        valores = []

        class ProgressoQueGrava(FakeProgress):
            def set(self, value):
                valores.append(value)
                super().set(value)

        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            pgn.write_text(self.PGN, encoding="utf-8")
            app = FakeApp(Path(tmp) / "cache.db")
            app.progress = ProgressoQueGrava()

            def translate(text, *_args, **_kwargs):
                if " ||| " in text:
                    return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
                return f"[{text}]"

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
            )
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            try:
                translation_worker.run_translation(app, str(pgn), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showinfo,
                ) = originais

        self.assertEqual(
            valores[-1], 1.0, "o `finally` sempre fecha a barra numa execucao limpa"
        )
        self.assertIn(
            1.0,
            valores[:-1],
            f"a barra nunca chegou ao fim durante o processamento: {valores}",
        )

    def test_the_same_comment_in_two_files_still_comes_from_the_cache(self):
        """A deduplicacao e por arquivo; entre arquivos quem serve e o cache."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("a.pgn", "b.pgn"):
                (base / nome).write_text(
                    '[Event "T"]\n\n1. e4 {Diagram} *\n', encoding="utf-8"
                )
            app = FakeApp(base / "cache.db")
            enviados = []

            def translate(text, *_args, **_kwargs):
                enviados.append(text)
                return f"[{text}]"

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
            )
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            try:
                translation_worker.run_translation(app, str(base), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showinfo,
                ) = originais

        self.assertEqual(enviados, ["Diagram"])
        self.assertTrue(
            any("Traducoes reutilizadas do cache: 1" in l for l in app.logs), app.logs
        )


class WorkerReleasesEachFileTests(unittest.TestCase):
    """`info_by_file` segurava todos os PGN a execucao inteira (ROADMAP 20.4)."""

    def rodar(self, base, arquivos):
        app = FakeApp(base / "cache.db")

        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        originais = (
            translation_worker.translate_text,
            translation_worker.messagebox.showinfo,
        )
        translation_worker.translate_text = translate
        translation_worker.messagebox.showinfo = lambda *_a, **_k: None
        try:
            translation_worker.run_translation(app, str(base), "pt", False)
        finally:
            (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
            ) = originais
        return app

    def test_the_positions_are_extracted_after_the_api_phase_of_each_file(self):
        """O sinal observavel de "processar e soltar por arquivo".

        Antes, a extracao completa de TODOS os arquivos acontecia antes de a
        primeira linha "Processando arquivo" existir, e o resultado ficava
        guardado ate o fim. Agora cada arquivo e lido na vez dele e **depois** da
        fase da API: o conteudo so serve para gravar, e a fase da API dura
        minutos — atravessa-la segurando um livro de 40 MB e o custo que 20.4
        existe para nao pagar.
        """
        ordem = []
        original = pgn_utils.extract_comments_from_content

        def registrando(*args, **kwargs):
            ordem.append("extraiu")
            return original(*args, **kwargs)

        # Os DOIS nomes: o worker importou a funcao no import dele, entao trocar
        # so a de `pgn_utils` deixaria passar uma primeira passada que voltasse a
        # chamar `extract_comments_from_file` — que e a forma antiga, e e ela que
        # este teste tem de pegar.
        for modulo in (pgn_utils, translation_worker):
            setattr(modulo, "extract_comments_from_content", registrando)
            self.addCleanup(
                setattr, modulo, "extract_comments_from_content", original
            )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nome in ("a.pgn", "b.pgn", "c.pgn"):
                _pgn_com_comentarios(base / nome, 3, prefixo=nome)

            app = FakeApp(base / "cache.db")

            def translate(text, *_args, **_kwargs):
                ordem.append("api")
                if " ||| " in text:
                    return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
                return f"[{text}]"

            originais = (
                translation_worker.translate_text,
                translation_worker.messagebox.showinfo,
            )
            translation_worker.translate_text = translate
            translation_worker.messagebox.showinfo = lambda *_a, **_k: None
            try:
                translation_worker.run_translation(app, str(base), "pt", False)
            finally:
                (
                    translation_worker.translate_text,
                    translation_worker.messagebox.showinfo,
                ) = originais

        self.assertEqual(ordem.count("extraiu"), 3)
        self.assertEqual(
            ordem,
            ["api", "extraiu", "api", "extraiu", "api", "extraiu"],
            "cada arquivo devia ser lido na vez dele, depois da fase da API",
        )

    def test_the_run_does_not_hold_every_file_in_memory(self):
        """A outra familia que mutacao nao pega: correto e gordo.

        Sete arquivos de 1.200 comentarios com so 120 textos distintos cada. A
        forma antiga guardava os 8.400 comentarios, as 8.400 posicoes e as 8.400
        ocorrencias de todos eles ate o fim; medido nesta maquina, 8,6 MB de pico
        contra 2,3 MB. O limite e generoso — o que ele distingue e "guarda tudo"
        de "guarda um arquivo".
        """
        import tracemalloc

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for indice in range(7):
                partes = ['[Event "T"]\n\n']
                for i in range(1200):
                    texto = f"comentario {i % 120} " + "x" * 200
                    partes.append(f"{i % 60 + 1}. Nf3 {{{texto}}} Nf6 ")
                    if i % 20 == 19:
                        partes.append("\n")
                partes.append("1-0\n")
                (base / f"f{indice}.pgn").write_text(
                    "".join(partes), encoding="utf-8", newline=""
                )

            tracemalloc.start()
            app = self.rodar(base, 7)
            pico = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()

        self.assertTrue(any("Total de comentarios: 8400" in l for l in app.logs), app.logs)
        self.assertLess(
            pico,
            5_000_000,
            f"pico de {pico/1e6:.1f} MB; a forma antiga chegava a 8,6 MB",
        )


class SpellingIndexTests(unittest.TestCase):
    """O `spelling.ssp` era reparseado a cada uso (ROADMAP 20.5).

    985 mil linhas, 1,0 s e 72 MB de pico para corrigir cinco tags de um PGN de
    20 KB. O indice derivado abre em 29 ms — 27 deles conferindo o hash do
    fonte — e consulta por chave.
    """

    SSP = (
        '@PLAYER ",."\n'
        "Kasparov, Garry\n"
        "=Kasparov\n"
        "=Kasparow\n"
        '%Prefix "Van " "van "\n'
        '@SITE ""\n'
        "Linares ESP\n"
        "=Linares\n"
        '%Suffix " ESP" " Espanha"\n'
        '@PLAYER ""\n'
        "Karpov, Anatoly\n"
        "=Karpov\n"
        "=Kasparov\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fonte = self.base / "spelling.ssp"
        self.fonte.write_text(self.SSP, encoding="utf-8")
        self.db = self.base / SPELLING_DB_FILENAME

    def abrir(self, **kwargs):
        dados = load_spelling_data(str(self.fonte), str(self.db), **kwargs)
        self.addCleanup(close_spelling_data, dados)
        return dados

    def test_the_index_sits_next_to_the_source(self):
        """Junto do fonte, e nao numa pasta de cache do sistema.

        E a mesma escolha do `glossario.db`: apagar um e obvio quando se apaga o
        outro, e ninguem procura por um cache invisivel para forcar a
        reconstrucao.
        """
        self.assertEqual(
            default_spelling_db_path(str(self.fonte)), str(self.db)
        )

    def test_the_index_answers_exactly_like_the_dictionary(self):
        dicionario = parse_spelling_file(str(self.fonte))
        indice = self.abrir()

        casos = [
            ("Kasparov", "PLAYER"),
            ("kasparow", "PLAYER"),
            ("Karpov", "PLAYER"),
            ("Van der Wiel", "PLAYER"),
            ("desconhecido", "PLAYER"),
            ("Linares", "SITE"),
            ("Linares ESP", "SITE"),
            ("qualquer", "EVENT"),
        ]
        for valor, secao in casos:
            self.assertEqual(
                correct_spelling_value(valor, secao, indice),
                correct_spelling_value(valor, secao, dicionario),
                f"{secao}: {valor!r}",
            )

    def test_a_repeated_section_keeps_appending_in_the_index(self):
        """A semantica de 17.10, atravessada pelo indice.

        Um segundo bloco `@PLAYER` ACRESCENTA; e a chave repetida (`=Kasparov`
        nos dois blocos) continua valendo pelo PRIMEIRO. Sem o `INSERT OR
        IGNORE`, o bloco de baixo passaria a sobrescrever o de cima.
        """
        indice = self.abrir()

        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")
        self.assertEqual(indice.entry("PLAYER", "karpov"), "Karpov, Anatoly")

    def test_the_section_parameters_come_from_the_last_block(self):
        indice = self.abrir()
        dicionario = parse_spelling_file(str(self.fonte))

        self.assertEqual(
            indice.get("PLAYER")["ignore_chars"],
            dicionario["PLAYER"]["ignore_chars"],
        )
        self.assertEqual(
            indice.get("PLAYER")["prefix_rules"],
            dicionario["PLAYER"]["prefix_rules"],
        )
        self.assertEqual(
            indice.get("SITE")["suffix_rules"], dicionario["SITE"]["suffix_rules"]
        )

    def test_the_second_use_does_not_read_the_source_again(self):
        """O ponto do item: o custo de 1,0 s acontece uma vez, e nao por uso."""
        self.abrir()

        leituras = []
        original = pgn_spellcheck.iter_spelling_records

        def contando(*args, **kwargs):
            leituras.append(args)
            return original(*args, **kwargs)

        pgn_spellcheck.iter_spelling_records = contando
        self.addCleanup(
            setattr, pgn_spellcheck, "iter_spelling_records", original
        )

        indice = self.abrir()

        self.assertEqual(leituras, [], "o indice valido nao devia ser reconstruido")
        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")

    def test_a_changed_source_rebuilds_the_index(self):
        self.abrir()
        self.assertFalse(spelling_index_is_stale(str(self.fonte), str(self.db)))

        self.fonte.write_text(
            '@PLAYER ""\nTal, Mihail\n=Tal\n', encoding="utf-8"
        )

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "tal"), "Tal, Mihail")
        self.assertIsNone(indice.entry("PLAYER", "kasparov"))

    def test_an_index_without_the_final_mark_is_rebuilt(self):
        """Construcao interrompida: a marca e gravada por ultimo, de proposito."""
        build_spelling_index(str(self.fonte), str(self.db))
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("DELETE FROM spelling_metadata WHERE key = 'source_hash'")
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))

    def test_an_index_from_another_schema_is_rebuilt(self):
        build_spelling_index(str(self.fonte), str(self.db))
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "UPDATE spelling_metadata SET value = '0' WHERE key = 'schema_version'"
            )
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))

    def test_a_corrupt_index_is_rebuilt_instead_of_breaking_the_button(self):
        self.db.write_bytes(b"isto nao e um banco sqlite")

        self.assertTrue(spelling_index_is_stale(str(self.fonte), str(self.db)))
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "kasparov"), "Kasparov, Garry")

    def test_it_falls_back_to_the_dictionary_when_the_index_cannot_be_used(self):
        """Disco sem permissao de escrita: o botao continua funcionando.

        O log tem de dizer o motivo — degradar em silencio faria a normalizacao
        custar 1,0 s por arquivo sem que nada explicasse por que.
        """
        logs = []
        original = pgn_spellcheck.sqlite3.connect

        def recusando(*_args, **_kwargs):
            raise sqlite3.OperationalError("unable to open database file")

        pgn_spellcheck.sqlite3.connect = recusando
        try:
            dados = load_spelling_data(
                str(self.fonte), str(self.db), log_message=logs.append
            )
        finally:
            pgn_spellcheck.sqlite3.connect = original

        self.assertIsInstance(dados, dict)
        self.assertEqual(
            correct_spelling_value("Kasparov", "PLAYER", dados), "Kasparov, Garry"
        )
        self.assertTrue(any("[AVISO]" in linha for linha in logs), logs)

    def test_use_index_false_never_touches_the_disk(self):
        dados = load_spelling_data(str(self.fonte), str(self.db), use_index=False)

        self.assertIsInstance(dados, dict)
        self.assertFalse(self.db.exists())

    def test_the_index_starts_from_scratch_and_forgets_what_left_the_source(self):
        indice = self.abrir()
        self.assertEqual(indice.entry("PLAYER", "kasparow"), "Kasparov, Garry")
        close_spelling_data(indice)

        self.fonte.write_text(
            '@PLAYER ",."\nKasparov, Garry\n=Kasparov\n', encoding="utf-8"
        )
        indice = self.abrir()

        self.assertIsNone(
            indice.entry("PLAYER", "kasparow"),
            "o apelido saiu do arquivo e nao pode sobreviver no indice",
        )

    def test_the_normalizer_uses_the_index_and_closes_it(self):
        """No Windows, um `spelling.db` preso ao processo nao pode ser trocado."""
        pgn = self.base / "game.pgn"
        pgn.write_text('[White "Kasparov"]\n\n1. e4 *\n', encoding="utf-8")
        logs = []

        stats = normalize_pgn_metadata_path(
            str(self.base), spelling_path=str(self.fonte), log_message=logs.append
        )

        self.assertEqual(stats["changed_files"], 1)
        self.assertTrue(self.db.exists())
        saida = Path(stats["outputs"][0]).read_text(encoding="utf-8")
        self.assertIn('[White "Kasparov, Garry"]', saida)
        # Se a conexao tivesse ficado aberta, o `os.remove` levantaria aqui.
        os.remove(self.db)

    def test_the_records_are_a_stream_and_not_a_list(self):
        """O gerador e o que mantem o pico de memoria baixo na construcao."""
        registros = iter_spelling_records(str(self.fonte))

        self.assertTrue(hasattr(registros, "__next__"))
        self.assertEqual(next(registros), ("section", "PLAYER", ",.", None))


class GlossaryOrderingKeyTests(unittest.TestCase):
    """A chave do cache de ordenacao era O(n) por consulta (ROADMAP 20.6).

    Uma tupla de 7.334 elementos montada e hasheada a cada tecla do editor:
    1,75 ms dos 9,15 ms que uma tecla custava. Com o numero de versao, 0,0002 ms.
    """

    def test_a_loaded_list_has_a_constant_sized_key(self):
        regras = versioned_rules([(f"palavra {i}", f"outra {i}") for i in range(5000)])

        chave = glossario._ordered_rules_cache_key(regras)

        self.assertEqual(len(chave), 2, "a chave nao pode crescer com as regras")
        self.assertIs(chave[0], VersionedRules)

    def test_two_loads_of_the_same_content_do_not_share_the_entry(self):
        pares = [("a", "b"), ("cc", "dd")]
        primeira = versioned_rules(pares)
        segunda = versioned_rules(pares)

        self.assertNotEqual(
            glossario._ordered_rules_cache_key(primeira),
            glossario._ordered_rules_cache_key(segunda),
        )
        # E as duas continuam recebendo a MESMA ordem: a chave nova custa uma
        # reordenacao, nunca uma resposta errada.
        self.assertEqual(
            order_rules_by_specificity(primeira),
            order_rules_by_specificity(segunda),
        )

    def test_mutating_the_list_invalidates_the_cached_order(self):
        """O modo de falha que a chave por conteudo nao tinha.

        Uma lista marcada por identidade que mude no lugar continuaria valendo
        como a mesma, e a ordem devolvida traria regras que nao estao mais nela.
        Cada mutacao renova a versao.
        """
        regras = versioned_rules([("curta", "x")])
        self.assertEqual(order_rules_by_specificity(regras), [("curta", "x")])

        regras.append(("uma regra bem mais longa", "y"))

        self.assertEqual(
            order_rules_by_specificity(regras),
            [("uma regra bem mais longa", "y"), ("curta", "x")],
        )

    def test_every_mutation_renews_the_version(self):
        regras = versioned_rules([("a", "b"), ("cc", "dd"), ("eee", "fff")])
        vistas = {regras.version}

        for mutacao in (
            lambda r: r.append(("z", "z")),
            lambda r: r.extend([("y", "y")]),
            lambda r: r.insert(0, ("x", "x")),
            lambda r: r.remove(("x", "x")),
            lambda r: r.pop(),
            lambda r: r.sort(),
            lambda r: r.reverse(),
            lambda r: r.clear(),
            lambda r: r.__setitem__(0, ("w", "w")),
            lambda r: r.__delitem__(0),
            lambda r: r.__iadd__([("v", "v")]),
            lambda r: r.__imul__(2),
        ):
            antes = regras.version
            if not regras:
                regras.extend([("a", "b"), ("cc", "dd")])
            mutacao(regras)
            self.assertNotEqual(
                regras.version, antes, f"{mutacao} nao renovou a versao"
            )
            self.assertNotIn(regras.version, vistas)
            vistas.add(regras.version)

    def test_a_plain_list_still_gets_the_content_key(self):
        """Uma lista literal — de teste, ou escrita a mao — continua valendo."""
        chave = glossario._ordered_rules_cache_key([("a", "b"), ("cc", "dd", 5)])

        self.assertEqual(chave, (("a", "b", 0), ("cc", "dd", 5)))

    def test_the_loaders_hand_out_versioned_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "Substituicoes.txt"
            arquivo.write_text(
                "substituicoes = [\n"
                "    ('knight', 'cavalo', 'suggestion', 0, '*'),\n"
                "]\n",
                encoding="utf-8",
            )

            regras = load_interactive_substitutions(str(arquivo))

        self.assertIsInstance(regras, VersionedRules)
        self.assertEqual(len(glossario._ordered_rules_cache_key(regras)), 2)

    def test_the_suggestions_are_the_same_with_and_without_the_version(self):
        pares = [
            ("knight", "cavalo"),
            ("the knight on f3", "o cavalo em f3"),
            ("rook", "torre"),
        ]
        texto = "The knight on f3 and the rook are placed."

        self.assertEqual(
            find_glossary_suggestions(texto, versioned_rules(pares)),
            find_glossary_suggestions(texto, list(pares)),
        )


if __name__ == "__main__":
    unittest.main()
