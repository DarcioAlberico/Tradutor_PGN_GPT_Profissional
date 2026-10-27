"""O banco de traducoes: schema, migracoes, cache, historico, execucoes, FTS.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

from difflib import SequenceMatcher
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from tradutor_pgn import (
    database,
)
from tradutor_pgn.database import (
    FTS_TABLE,
    OCCURRENCES_TABLE,
    REVIEW_STATUS_DOUBT,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    SEARCH_MODE_SUBSTRING,
    SEARCH_MODE_TERMS,
    SOURCE_LANGUAGE_UNKNOWN,
    adopt_unknown_source_language,
    build_fts_match_query,
    RUN_COMPLETED,
    RUN_CRASHED,
    RUN_FAILED,
    RUN_RUNNING,
    SCHEMA_VERSION,
    begin_translation_run,
    clear_all_translations,
    count_revertible_run_translations,
    finish_translation_run,
    get_translation_run,
    list_translation_runs,
    mark_unfinished_runs_crashed,
    revert_translation_run,
    count_unreviewed_file_translations,
    discard_unreviewed_file_translations,
    fts_index_ready,
    count_from_status_counts,
    count_review_rows,
    escape_like_pattern,
    fetch_comment_history,
    find_similar_translations,
    fts5_available,
    fetch_export_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_review_status_by_id,
    fetch_translation_by_id,
    get_review_row_offset,
    get_review_status_counts,
    get_database_stats,
    initialize_database,
    list_occurrence_files,
    load_translation_cache,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
    set_review_status_by_id,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.db_tools import (
    analyze_database_automatic_rules,
    analyze_translations_csv_import,
    apply_database_automatic_rules,
    create_database_backup,
    format_automatic_rule_examples,
    import_translations_from_csv,
    restore_database_from_backup,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    _schema3_database,
    escrita_disponivel,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class CoveringIndexTests(unittest.TestCase):
    """Garantia R11: o resumo por status nao toca a tabela (ROADMAP 22.13).

    O item 19.12 acrescentou `review_status` a agregada de
    `get_review_status_counts` e nao a acrescentou aos dois indices de cobertura
    criados para ela. A cobertura se perdeu em silencio — nada quebra, a consulta
    so passa a ler a tabela linha a linha, na thread do Tk, a cada recarga da
    lista.

    O teste le o PLANO, e nao o tempo: cronometrar em 20 linhas nao distingue
    nada, e a palavra `COVERING` no `EXPLAIN QUERY PLAN` e exatamente a afirmacao
    que se quer proteger.
    """

    def plano(self, cursor, **kwargs):
        sql, params = database.review_status_counts_query(**kwargs)
        return " ".join(
            linha[3]
            for linha in cursor.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        )

    def test_the_summary_by_target_only_reads_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "c.db"))
            cur = conn.cursor()
            save_translation(cur, "orig", "trans", "pt", "en")
            conn.commit()

            plano = self.plano(cur, target_language="pt")
            self.assertIn("idx_comments_counts", plano)
            self.assertIn("COVERING", plano.upper(), plano)
            conn.close()

    def test_the_summary_with_a_source_filter_reads_the_other_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "c.db"))
            cur = conn.cursor()
            save_translation(cur, "orig", "trans", "pt", "en")
            conn.commit()

            plano = self.plano(cur, target_language="pt", source_language="en")
            self.assertIn("idx_comments_pair_counts", plano)
            self.assertIn("COVERING", plano.upper(), plano)
            conn.close()

    def test_review_status_is_in_both_indexes(self):
        """A coluna que 19.12 acrescentou ao WHERE e nao acrescentou aqui."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = initialize_database(str(Path(tmp) / "c.db"))
            for indice in ("idx_comments_counts", "idx_comments_pair_counts"):
                colunas = [
                    linha[2]
                    for linha in conn.execute(f"PRAGMA index_info({indice})").fetchall()
                ]
                self.assertIn("review_status", colunas, indice)
            conn.close()

    def test_an_old_database_gets_the_index_rebuilt(self):
        """`CREATE INDEX IF NOT EXISTS` nao troca as colunas de um indice que existe.

        Sem o `DROP` da migracao 9, o banco de quem ja usava o programa ficaria
        com o indice velho para sempre — e a correcao valeria so para instalacoes
        novas, que sao exatamente as que nao tem o problema.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "c.db")
            conn = initialize_database(caminho)
            conn.close()

            # Volta ao estado anterior: indice sem `review_status` e versao 8.
            conn = sqlite3.connect(caminho)
            conn.execute("DROP INDEX idx_comments_counts")
            conn.execute(
                "CREATE INDEX idx_comments_counts "
                "ON comments(target_language, verified, quality_warning)"
            )
            conn.execute("PRAGMA user_version = 8")
            conn.commit()
            conn.close()

            conn = initialize_database(caminho)
            colunas = [
                linha[2]
                for linha in conn.execute(
                    "PRAGMA index_info(idx_comments_counts)"
                ).fetchall()
            ]
            self.assertIn("review_status", colunas)
            conn.close()


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
                history = fetch_comment_history(cursor=conn.cursor(), comment_id=verified_id, only_text_changes=False)
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
            self.assertEqual(len(fetch_comment_history(cursor, comment_id, only_text_changes=False)), 1)

            self.assertEqual(set_translation_verified_by_id(cursor, comment_id, False), 1)
            conn.commit()

            pending = fetch_review_rows_page(cursor, "pt", limit=1, offset=0)[0]
            self.assertEqual(pending[3], 0)
            self.assertIsNone(pending[6])
            history = fetch_comment_history(cursor, comment_id, only_text_changes=False)
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
            # O historico INTEIRO: este teste e sobre o que a gravacao registra,
            # e duas das tres entradas daqui (`mark_pending` e a verificacao) nao
            # mudam o texto — a lista da janela as deixa de fora de proposito
            # (ROADMAP 23.1), e perguntar por elas aqui e pedir outra coisa.
            history = fetch_comment_history(cursor, comment_id, only_text_changes=False)
            self.assertEqual(len(history), 3)
            self.assertEqual(history[0][1], "restore")
            self.assertEqual(history[0][2], "trans revisada")
            self.assertEqual(history[0][3], "trans")
            # Fechada DENTRO do `with`: o Windows nao apaga arquivo aberto, e a
            # limpeza do diretorio temporario acontece na saida do bloco. Sem
            # isto o teste depende de o coletor de lixo ter passado antes — e
            # passou, por anos, ate um teste novo em outra classe mudar o ritmo
            # das alocacoes e a limpeza estourar `PermissionError`.
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
            history = fetch_comment_history(cursor, propagated_id, only_text_changes=False)
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
                    # O subconjunto pendente dos avisos, que "Avisos QA" lista (F28).
                    "pending_warnings": 0,
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
                    "pending_warnings": 0,
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
                    "pending_warnings": 0,
                    "rejected": 0,
                    "doubt": 0,
                },
            )
            conn.close()


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
            def abrir(caminho):
                return initialize_database(str(caminho))

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


class DiscardUnreviewedRowsTests(unittest.TestCase):
    """Garantia Z4 no banco: a "linha que nenhum humano tocou", e so ela.

    Cinco linhas com uma marca cada — verificada, com status, com nota, com
    historico, reusada por outro arquivo — mais uma limpa: sobra exatamente
    cada marcada, e a limpa vai. E o cenario da SPEC, e cada clausula do
    `WHERE` decide UMA linha, para uma clausula apagada por engano derrubar um
    teste com nome.
    """

    LIVRO = "C:/obras/livro.pgn"
    OUTRO = "C:/obras/outro.pgn"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "traducoes.db")
        self.conn = initialize_database(self.db_path)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def semear(self, textos, arquivo=None, source="en", target="pt"):
        """Grava as linhas e as ocorrencias delas no arquivo. Devolve os ids."""
        for texto in textos:
            save_translation(self.cur, texto, f"T {texto}", target, source)
        ids = resolve_comment_ids(self.cur, target, list(textos), source)
        record_occurrences(
            self.cur,
            arquivo or self.LIVRO,
            [(n + 1, 1, n + 1, texto) for n, texto in enumerate(textos)],
            ids,
        )
        self.conn.commit()
        return ids

    def cenario(self):
        textos = ["limpa", "verificada", "com status", "com nota", "editada", "reusada"]
        ids = self.semear(textos)
        set_translation_verified_by_id(self.cur, ids["verificada"], True)
        set_review_status_by_id(self.cur, ids["com status"], REVIEW_STATUS_DOUBT)
        set_review_status_by_id(self.cur, ids["com nota"], REVIEW_STATUS_PENDING, "ver depois")
        update_translation_by_id(self.cur, ids["editada"], "T editada, a mao", history_action="edit")
        # A reusada aparece tambem no OUTRO arquivo — apaga-la encurtaria a
        # obra dele.
        self.cur.execute(
            f"INSERT INTO {OCCURRENCES_TABLE} (comment_id, source_file, game_index, comment_index, move_number)"
            " VALUES (?, ?, 1, 1, 1)",
            (ids["reusada"], os.path.abspath(self.OUTRO)),
        )
        self.conn.commit()
        return ids

    def arquivo(self):
        return os.path.abspath(self.LIVRO)

    def originais(self):
        return sorted(
            r[0] for r in self.cur.execute("SELECT original_comment FROM comments")
        )

    def test_each_mark_saves_its_row_and_the_clean_one_goes(self):
        self.cenario()

        self.assertEqual(count_unreviewed_file_translations(self.cur, self.arquivo(), "pt"), 1)
        apagadas = discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt")
        self.conn.commit()

        self.assertEqual(apagadas, 1)
        self.assertEqual(
            self.originais(),
            ["com nota", "com status", "editada", "reusada", "verificada"],
        )

    def test_the_row_reused_by_another_file_keeps_both_occurrences(self):
        ids = self.cenario()
        discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt")
        self.conn.commit()
        quantas = self.cur.execute(
            f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE} WHERE comment_id = ?",
            (ids["reusada"],),
        ).fetchone()[0]
        self.assertEqual(quantas, 2)

    def test_the_occurrences_of_the_discarded_rows_go_with_them(self):
        ids = self.cenario()
        discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt")
        self.conn.commit()
        orfas = self.cur.execute(
            f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE} WHERE comment_id = ?",
            (ids["limpa"],),
        ).fetchone()[0]
        self.assertEqual(orfas, 0)
        # E o arquivo continua no filtro do editor com as cinco que ficaram.
        arquivos = list_occurrence_files(self.cur, "pt")
        self.assertEqual(
            [(a, p) for a, p, _c in arquivos],
            [(self.arquivo(), 5), (os.path.abspath(self.OUTRO), 1)],
        )

    def test_a_row_verified_without_history_stays_by_the_verified_clause(self):
        """Verificar pela janela grava historico; uma linha importada de CSV ja
        verificada nao tem historico nenhum — e a clausula `verified` e o que a
        poupa."""
        ids = self.semear(["importada"])
        self.cur.execute("UPDATE comments SET verified = 1 WHERE id = ?", (ids["importada"],))
        self.conn.commit()
        self.assertEqual(count_unreviewed_file_translations(self.cur, self.arquivo(), "pt"), 0)

    def test_a_verified_row_marked_pending_again_has_history_and_stays(self):
        """Verificar e voltar a pendente gravam historico: alguem OLHOU a linha."""
        ids = self.semear(["olhada"])
        set_translation_verified_by_id(self.cur, ids["olhada"], True)
        set_translation_verified_by_id(self.cur, ids["olhada"], False)
        self.conn.commit()
        self.assertEqual(count_unreviewed_file_translations(self.cur, self.arquivo(), "pt"), 0)

    def test_the_other_file_is_not_touched(self):
        self.semear(["deste"])
        self.semear(["daquele"], arquivo=self.OUTRO)
        apagadas = discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt")
        self.conn.commit()
        self.assertEqual(apagadas, 1)
        self.assertEqual(self.originais(), ["daquele"])

    def test_the_pair_is_the_one_on_screen(self):
        """A mesma obra traduzida para dois destinos: so o destino da janela cai."""
        self.semear(["frase"], target="pt")
        self.cur.execute(
            "INSERT INTO comments (original_comment, translated_comment, source_language, target_language)"
            " VALUES ('frase', 'T it', 'en', 'it')"
        )
        id_it = self.cur.lastrowid
        self.cur.execute(
            f"INSERT INTO {OCCURRENCES_TABLE} (comment_id, source_file, game_index, comment_index, move_number)"
            " VALUES (?, ?, 1, 2, 1)",
            (id_it, self.arquivo()),
        )
        self.conn.commit()

        self.assertEqual(count_unreviewed_file_translations(self.cur, self.arquivo(), "pt"), 1)
        self.assertEqual(count_unreviewed_file_translations(self.cur, self.arquivo(), "pt", "es"), 0)
        discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt", "en")
        self.conn.commit()
        restantes = self.cur.execute(
            "SELECT target_language FROM comments WHERE original_comment = 'frase'"
        ).fetchall()
        self.assertEqual(restantes, [("it",)])

    def test_more_rows_than_one_chunk_all_go(self):
        """O `IN (...)` e por lotes: acima do lote nada pode sobrar."""
        textos = [f"linha {n}" for n in range(database.CACHE_LOOKUP_CHUNK + 5)]
        self.semear(textos)
        apagadas = discard_unreviewed_file_translations(self.cur, self.arquivo(), "pt")
        self.conn.commit()
        self.assertEqual(apagadas, len(textos))
        self.assertEqual(self.originais(), [])
        self.assertEqual(
            self.cur.execute(f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE}").fetchone()[0], 0
        )


class TranslationRunRecordTests(unittest.TestCase):
    """A tabela de execucoes (garantia Z5, ROADMAP 28.6): abrir, fechar,
    listar, marcar o que morreu, e a coluna que so o INSERT preenche."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "traducoes.db")
        self.conn = initialize_database(self.db_path)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def test_begin_and_finish_record_the_outcome_and_the_counts(self):
        run_id = begin_translation_run(
            self.cur, "pt", "en", "C:/obras", ["C:/obras/a.pgn", "b.pgn"], "google-gtx", "x.log"
        )
        aberta = get_translation_run(self.cur, run_id)
        self.assertEqual(aberta["outcome"], RUN_RUNNING)
        self.assertIsNone(aberta["finished_at"])
        self.assertEqual(aberta["files"], [os.path.abspath("C:/obras/a.pgn"), os.path.abspath("b.pgn")])
        self.assertEqual(aberta["provider"], "google-gtx")
        self.assertEqual(aberta["log_path"], "x.log")

        self.assertEqual(finish_translation_run(self.cur, run_id, RUN_FAILED, 12, 3), 1)
        fechada = get_translation_run(self.cur, run_id)
        self.assertEqual(fechada["outcome"], RUN_FAILED)
        self.assertIsNotNone(fechada["finished_at"])
        self.assertEqual((fechada["inserted_count"], fechada["failed_count"]), (12, 3))

        with self.assertRaises(ValueError):
            finish_translation_run(self.cur, run_id, RUN_RUNNING, 0, 0)
        with self.assertRaises(ValueError):
            finish_translation_run(self.cur, run_id, "explodiu", 0, 0)

    def test_the_list_is_newest_first_and_capped(self):
        for n in range(5):
            begin_translation_run(self.cur, "pt", "en", "", [], "g")
        ids = [run["id"] for run in list_translation_runs(self.cur, limit=3)]
        self.assertEqual(ids, [5, 4, 3])
        self.assertIsNone(get_translation_run(self.cur, 99))

    def test_a_run_left_open_is_marked_crashed_by_the_next_one(self):
        morta = begin_translation_run(self.cur, "pt", "en", "", [], "g")
        viva = begin_translation_run(self.cur, "pt", "en", "", [], "g")
        self.assertEqual(get_translation_run(self.cur, morta)["outcome"], RUN_CRASHED)
        self.assertIsNotNone(get_translation_run(self.cur, morta)["finished_at"])
        self.assertEqual(get_translation_run(self.cur, viva)["outcome"], RUN_RUNNING)
        # Uma fechada nao e tocada pela varredura.
        finish_translation_run(self.cur, viva, RUN_COMPLETED, 0, 0)
        self.assertEqual(mark_unfinished_runs_crashed(self.cur), 0)
        self.assertEqual(get_translation_run(self.cur, viva)["outcome"], RUN_COMPLETED)

    def test_only_an_insert_stamps_the_run(self):
        """Uma linha vazia preenchida ja existia: reverter nao pode leva-la."""
        run_id = begin_translation_run(self.cur, "pt", "en", "", [], "g")
        self.assertEqual(save_translation(self.cur, "new", "nova", "pt", "en", run_id=run_id), "inserted")
        save_translation(self.cur, "empty", "", "pt", "en")
        self.assertEqual(
            save_translation(self.cur, "empty", "cheia", "pt", "en", run_id=run_id), "filled_empty"
        )
        self.assertEqual(
            save_translation(self.cur, "new", "outra", "pt", "en", run_id=run_id), "unchanged"
        )
        carimbos = dict(
            self.cur.execute("SELECT original_comment, inserted_run_id FROM comments").fetchall()
        )
        self.assertEqual(carimbos, {"new": run_id, "empty": None})
        # Sem execucao (importacao, ferramentas): nulo.
        save_translation(self.cur, "loose", "solta", "pt", "en")
        self.assertIsNone(
            self.cur.execute(
                "SELECT inserted_run_id FROM comments WHERE original_comment = 'loose'"
            ).fetchone()[0]
        )

    def test_a_version_9_database_gains_the_column_and_the_table(self):
        caminho = str(Path(self.tmp.name) / "velho.db")
        velho = sqlite3.connect(caminho)
        velho.execute(
            """
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_comment TEXT, translated_comment TEXT,
                source_language TEXT NOT NULL DEFAULT '', target_language TEXT,
                verified INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT,
                verified_at TEXT, quality_warning INTEGER,
                review_status TEXT NOT NULL DEFAULT '', reviewer_note TEXT,
                UNIQUE(original_comment, source_language, target_language)
            )
            """
        )
        velho.execute(
            "INSERT INTO comments (original_comment, translated_comment, target_language)"
            " VALUES ('old', 'velha', 'pt')"
        )
        velho.execute("PRAGMA user_version = 9")
        velho.commit()
        velho.close()

        conn = initialize_database(caminho)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            colunas = [r[1] for r in conn.execute("PRAGMA table_info(comments)")]
            self.assertIn("inserted_run_id", colunas)
            self.assertEqual(
                conn.execute("SELECT inserted_run_id FROM comments").fetchone(), (None,)
            )
            self.assertEqual(list_translation_runs(conn.cursor()), [])
        finally:
            conn.close()

    def test_clearing_the_database_drops_the_runs_too(self):
        """Z3 estendido: uma execucao apontando para ids que o AUTOINCREMENT vai
        reusar seria "reverter" apagando as linhas erradas."""
        run_id = begin_translation_run(self.cur, "pt", "en", "", [], "g")
        save_translation(self.cur, "x", "y", "pt", "en", run_id=run_id)
        self.conn.commit()
        clear_all_translations(self.conn)
        self.assertEqual(list_translation_runs(self.conn.cursor()), [])


class RevertRunRowsTests(unittest.TestCase):
    """Garantia Z5 no banco: o que a execucao inseriu e ninguem tocou, e so.

    O cenario da SPEC: uma execucao com sete insercoes, cinco com uma marca
    cada (verificada, status, nota, historico, reusada por um arquivo fora da
    execucao) e duas limpas; mais uma linha de OUTRA execucao e uma vazia que
    esta execucao preencheu. Somem as duas limpas, com as ocorrencias delas.
    """

    LIVRO = "C:/obras/livro.pgn"
    OUTRO = "C:/obras/outro.pgn"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "traducoes.db")
        self.conn = initialize_database(self.db_path)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()

    def semear(self, textos, run_id, arquivo=None):
        for texto in textos:
            save_translation(self.cur, texto, f"T {texto}", "pt", "en", run_id=run_id)
        ids = resolve_comment_ids(self.cur, "pt", list(textos), "en")
        record_occurrences(
            self.cur,
            arquivo or self.LIVRO,
            [(n + 1, 1, n + 1, texto) for n, texto in enumerate(textos)],
            ids,
        )
        self.conn.commit()
        return ids

    def cenario(self):
        # A execucao anterior traduziu o MESMO livro: a linha dela tem
        # ocorrencia so em arquivos desta execucao, e o que a poupa e
        # exclusivamente o `inserted_run_id` — a clausula que distingue "o que
        # esta execucao inseriu" de "o que esta execucao encontrou no cache".
        anterior = begin_translation_run(self.cur, "pt", "en", "", [self.LIVRO], "g")
        self.semear(["de outra execucao"], anterior)
        finish_translation_run(self.cur, anterior, RUN_COMPLETED, 1, 0)
        save_translation(self.cur, "vazia antes", "", "pt", "en")

        run_id = begin_translation_run(self.cur, "pt", "en", "C:/obras", [self.LIVRO], "g")
        textos = [
            "limpa", "limpa 2", "verificada", "verificada sem historico",
            "com status", "com nota", "editada", "reusada",
        ]
        ids = self.semear(textos, run_id)
        self.assertEqual(
            save_translation(self.cur, "vazia antes", "T cheia", "pt", "en", run_id=run_id),
            "filled_empty",
        )
        set_translation_verified_by_id(self.cur, ids["verificada"], True)
        # Verificada SEM historico — uma importacao de CSV ja verificada. E o
        # unico cenario em que a clausula `verified` decide sozinha: verificar
        # pela janela grava historico, e a clausula vizinha a esconderia
        # (padrao 4 da memoria de testes; o mesmo sobrevivente de Z4).
        self.cur.execute(
            "UPDATE comments SET verified = 1 WHERE id = ?", (ids["verificada sem historico"],)
        )
        set_review_status_by_id(self.cur, ids["com status"], REVIEW_STATUS_DOUBT)
        set_review_status_by_id(self.cur, ids["com nota"], REVIEW_STATUS_PENDING, "ver depois")
        update_translation_by_id(self.cur, ids["editada"], "T editada, a mao", history_action="edit")
        self.cur.execute(
            f"INSERT INTO {OCCURRENCES_TABLE} (comment_id, source_file, game_index, comment_index, move_number)"
            " VALUES (?, ?, 1, 9, 1)",
            (ids["reusada"], os.path.abspath(self.OUTRO)),
        )
        finish_translation_run(self.cur, run_id, RUN_COMPLETED, 8, 0)
        self.conn.commit()
        return get_translation_run(self.cur, run_id), ids

    def originais(self):
        return sorted(r[0] for r in self.cur.execute("SELECT original_comment FROM comments"))

    def test_each_mark_saves_its_row_and_the_clean_ones_go(self):
        run, _ids = self.cenario()
        self.assertEqual(count_revertible_run_translations(self.cur, run), 2)
        self.assertEqual(revert_translation_run(self.cur, run), 2)
        self.assertEqual(
            self.originais(),
            sorted([
                "de outra execucao", "vazia antes", "verificada",
                "verificada sem historico", "com status", "com nota", "editada",
                "reusada",
            ]),
        )
        # Nada mais a reverter na segunda vez.
        self.assertEqual(count_revertible_run_translations(self.cur, run), 0)

    def test_the_occurrences_of_the_deleted_rows_go_along(self):
        run, ids = self.cenario()
        revert_translation_run(self.cur, run)
        orfas = self.cur.execute(
            f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE} o"
            " WHERE NOT EXISTS (SELECT 1 FROM comments c WHERE c.id = o.comment_id)"
        ).fetchone()[0]
        self.assertEqual(orfas, 0)
        self.assertEqual(
            self.cur.execute(
                f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE} WHERE comment_id IN (?, ?)",
                (ids["limpa"], ids["limpa 2"]),
            ).fetchone()[0],
            0,
        )

    def test_a_row_reused_by_a_file_of_the_same_run_is_still_revertible(self):
        """A clausula e "arquivo FORA da execucao": dois capitulos da mesma
        execucao repetindo um comentario nao poupam a linha."""
        cap2 = "C:/obras/cap2.pgn"
        run_id = begin_translation_run(self.cur, "pt", "en", "", [self.LIVRO, cap2], "g")
        ids = self.semear(["Diagram"], run_id)
        self.cur.execute(
            f"INSERT INTO {OCCURRENCES_TABLE} (comment_id, source_file, game_index, comment_index, move_number)"
            " VALUES (?, ?, 1, 1, 1)",
            (ids["Diagram"], os.path.abspath(cap2)),
        )
        finish_translation_run(self.cur, run_id, RUN_COMPLETED, 1, 0)
        run = get_translation_run(self.cur, run_id)
        self.assertEqual(count_revertible_run_translations(self.cur, run), 1)

    def test_a_run_from_before_the_column_has_nothing_to_revert(self):
        save_translation(self.cur, "antiga", "velha", "pt", "en")
        run_id = begin_translation_run(self.cur, "pt", "en", "", [self.LIVRO], "g")
        finish_translation_run(self.cur, run_id, RUN_COMPLETED, 0, 0)
        run = get_translation_run(self.cur, run_id)
        self.assertEqual(count_revertible_run_translations(self.cur, run), 0)
        self.assertEqual(revert_translation_run(self.cur, run), 0)
        self.assertEqual(self.originais(), ["antiga"])

    def test_more_than_a_batch_of_rows_is_deleted_whole(self):
        run_id = begin_translation_run(self.cur, "pt", "en", "", [self.LIVRO], "g")
        textos = [f"linha {n}" for n in range(905)]
        self.semear(textos, run_id)
        run = get_translation_run(self.cur, run_id)
        self.assertEqual(revert_translation_run(self.cur, run), 905)
        self.assertEqual(self.originais(), [])


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


class ReadOnlyConnectionTests(unittest.TestCase):
    """`open_database_readonly`: le, nao escreve, e nunca espera (F30)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="com espaco ")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "t.db")
        conn = initialize_database(self.db_path)
        save_translation(conn.cursor(), "a", "A", "pt", "en")
        conn.commit()
        conn.close()

    def test_it_reads_and_refuses_to_write(self):
        conn = database.open_database_readonly(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO comments (original_comment) VALUES ('x')")
        # A tabela `temp` continua gravavel: e onde o `fts5vocab` das
        # semelhantes vive.
        conn.execute("CREATE TEMP TABLE t (x)")

    def test_it_does_not_wait_behind_a_writer(self):
        """Com um escritor segurando a transacao, `open_database` esperaria
        ate 30 s pelo `journal_mode`; a leitura nao pode esperar nem um."""
        escritor = initialize_database(self.db_path)
        self.addCleanup(escritor.close)
        escritor.execute("BEGIN EXCLUSIVE")
        inicio = time.perf_counter()
        try:
            conn = database.open_database_readonly(self.db_path)
            try:
                conn.execute("SELECT COUNT(*) FROM comments").fetchone()
            except sqlite3.OperationalError:
                pass  # ocupado: falhar na hora e o comportamento certo
            finally:
                conn.close()
        except sqlite3.OperationalError:
            pass
        self.assertLess(time.perf_counter() - inicio, 1.0, "a leitura ficou esperando o escritor")
        escritor.rollback()


class SimilarTranslationsTests(unittest.TestCase):
    """`find_similar_translations` (ROADMAP 28.13, F30): o FTS5 acha as
    candidatas pelos termos raros, o `SequenceMatcher` ordena, e so o par."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "t.db")
        self.conn = initialize_database(self.db_path)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        if not fts5_available(self.conn):
            self.skipTest("SQLite sem FTS5")

    def semear(self, linhas):
        """`[(original, traducao, origem, verificada)]` -> ids por original."""
        for original, traducao, origem, verificada in linhas:
            save_translation(self.cur, original, traducao, "pt", origem)
        ids = resolve_comment_ids(self.cur, "pt", [l[0] for l in linhas if l[2] == "en"], "en")
        for original, _t, origem, verificada in linhas:
            if verificada and origem == "en":
                set_translation_verified_by_id(self.cur, ids[original], True)
        self.conn.commit()
        return ids

    def test_the_closest_of_the_pair_come_first_and_the_rest_stay_out(self):
        ids = self.semear([
            ("chances are about even, Kamsky-Jobava, Brasov 2011.", "as chances sao iguais, Kamsky-Jobava, Brasov 2011.", "en", True),
            ("chances are about even, Torrecillas-Leon, Barcelona 2011.", "as chances sao iguais, Torrecillas-Leon, Barcelona 2011.", "en", False),
            ("chances are roughly even here, Smith-Jones, London 2010.", "chances mais ou menos iguais aqui", "en", False),
            ("the knight is dominant on d5 and cannot be challenged", "o cavalo domina d5", "en", False),
            ("chances are about even, Kamsky-Jobava, Brasov 2011.", "SEM TRADUCAO", "es", False),
            ("chances are about even, Rossi-Bianchi, Roma 2011.", "", "en", False),
        ])
        alvo = "chances are about even, Torrecillas-Leon, Barcelona 2011."
        itens = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en")
        originais = [item[1] for item in itens]
        self.assertNotIn(alvo, originais, "a propria linha nao e semelhante de si")
        self.assertEqual(originais[0], "chances are about even, Kamsky-Jobava, Brasov 2011.")
        self.assertNotIn("the knight is dominant on d5 and cannot be challenged", originais)
        self.assertNotIn("chances are about even, Rossi-Bianchi, Roma 2011.", originais, "sem traducao nao serve")
        # O par (R9): a linha de espanhol tem o MESMO original e fica de fora.
        self.assertTrue(all(item[2] != "SEM TRADUCAO" for item in itens))
        self.assertGreaterEqual(itens[0][4], 0.6)
        self.assertEqual(itens[0][3], 1, "a verificada vem com a marca")
        # Ordem decrescente de semelhanca.
        self.assertEqual([i[4] for i in itens], sorted((i[4] for i in itens), reverse=True))

    def test_with_source_filter_off_the_target_alone_decides(self):
        ids = self.semear([
            ("chances are about even, Kamsky-Jobava, Brasov 2011.", "A", "en", False),
            ("chances are about even, Rossi-Bianchi, Roma 2011.", "B", "it", False),
        ])
        alvo = "chances are about even, Kamsky-Jobava, Brasov 2011."
        com_filtro = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en")
        sem_filtro = find_similar_translations(self.cur, ids[alvo], alvo, "pt", None)
        self.assertEqual([i[2] for i in com_filtro], [])
        self.assertEqual([i[2] for i in sem_filtro], ["B"])

    def test_common_words_do_not_drive_the_query(self):
        """"white" em toda linha nao distingue nada: filtrado pelo `fts5vocab`."""
        linhas = [(f"white plays move number {n} here", f"T{n}", "en", False) for n in range(40)]
        linhas.append(("white is winning", "brancas ganham", "en", False))
        ids = self.semear(linhas)
        # So palavras comuns: consulta vazia, nada devolvido — e nao 40 linhas
        # que so compartilham "white".
        self.assertEqual(
            find_similar_translations(self.cur, ids["white is winning"], "white is winning", "pt", "en"),
            [],
        )
        termos = database._similar_query_terms(self.cur, "white plays move number 7 here")
        self.assertNotIn("white", termos)
        self.assertNotIn("plays", termos)

    def test_without_fts5_the_answer_is_none(self):
        original = database.fts5_available
        database.fts5_available = lambda _conn: False
        self.addCleanup(setattr, database, "fts5_available", original)
        self.assertIsNone(find_similar_translations(self.cur, 1, "anything at all", "pt", "en"))

    def test_the_limit_and_the_floor_hold(self):
        base = "the bishop pair gives white a lasting edge in the endgame"
        linhas = [(f"{base} number {n}", f"T{n}", "en", False) for n in range(8)]
        # Compartilha termos raros ("bishop", "pair", "endgame") — o FTS a
        # devolve como candidata — mas e outra frase: fica abaixo do piso.
        parecida_so_nos_termos = "bishop pair? no: knights rule this endgame, pair or not"
        linhas.append((parecida_so_nos_termos, "outra", "en", False))
        ids = self.semear(linhas)
        alvo = f"{base} number 0"
        itens = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en", limit=3)
        self.assertEqual(len(itens), 3)
        self.assertTrue(all(i[4] >= database.SIMILAR_MIN_RATIO for i in itens))
        todas = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en", limit=20)
        self.assertNotIn(parecida_so_nos_termos, [i[1] for i in todas], "abaixo do piso nao entra")

    def test_a_candidate_below_the_floor_is_not_offered(self):
        """Compartilha os termos raros (o FTS a devolve), mas e outra frase."""
        alvo = "queen sacrifice on h7 wins by force"
        longe = "sacrifice? the queen stays; h7 is not the point, force is"
        ids = self.semear([
            (alvo, "alvo", "en", False),
            ("queen sacrifice on h7 wins by force too", "perto", "en", False),
            (longe, "longe", "en", False),
        ])
        itens = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en")
        self.assertEqual([i[2] for i in itens], ["perto"])
        self.assertLess(
            SequenceMatcher(None, longe, alvo).ratio(), database.SIMILAR_MIN_RATIO,
            "o cenario exige a longe abaixo do piso",
        )

    def test_on_a_tie_the_verified_line_comes_first(self):
        ids = self.semear([
            ("the rook lift via a3 is the thematic plan here", "alvo", "en", False),
            ("the rook lift via h3 is the thematic plan here", "nao verificada", "en", False),
            ("the rook lift via b3 is the thematic plan here", "verificada", "en", True),
        ])
        alvo = "the rook lift via a3 is the thematic plan here"
        itens = find_similar_translations(self.cur, ids[alvo], alvo, "pt", "en")
        self.assertEqual(len(itens), 2)
        self.assertEqual(itens[0][4], itens[1][4], "o cenario exige empate no ratio")
        self.assertEqual(itens[0][2], "verificada")


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


if __name__ == "__main__":
    unittest.main()
