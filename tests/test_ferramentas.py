"""As ferramentas de banco (db_tools): backup, zerar, CSV/TMX, estatisticas, previas.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import csv
import xml.etree.ElementTree as ET
import os
import sqlite3
import types
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path

from tradutor_pgn import (
    db_export,
    app_actions,
    database,
    db_tools,
    glossario,
)
from tradutor_pgn.app_config import (
    DATABASE_BACKUP_KEEP_COUNT,
    GLOSSARY_BACKUP_KEEP_COUNT,
    LOG_KEEP_COUNT,
)
from tradutor_pgn.database import (
    REVIEW_STATUS_DOUBT,
    MoveNotationCanceled,
    analyze_move_notation_updates,
    apply_move_notation_updates,
    adopt_unknown_source_language,
    RUN_CANCELED,
    RUN_COMPLETED,
    begin_translation_run,
    finish_translation_run,
    AutomaticRulesCanceled,
    count_adoptable_unknown_source,
    count_words_by_pair,
    fetch_exact_translation_match_candidates,
    get_daily_review_activity,
    initialize_database,
    overwrite_translation_by_id,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
    set_review_status_by_id,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from tradutor_pgn.glossario import (
    analyze_glossary_csv_import,
    import_glossary_csv,
    load_glossary_entries,
    load_glossary_entry_details,
    load_interactive_substitutions,
    restore_glossary_from_backup,
    save_glossary_entries,
)
from tradutor_pgn.word_count import add_word_counts, count_words, total_word_counts
from tradutor_pgn.background_task import TaskCanceled
from tradutor_pgn import app_config
from tradutor_pgn.background_task import BackgroundTask
from tradutor_pgn.chess_notation import (
    fix_move_notation,
)
from tradutor_pgn.confirm_dialog import CONFIRMATION_WORD, confirmation_accepted
from tradutor_pgn.db_tools import (
    analyze_translations_csv_import,
    create_database_backup,
    export_translations_to_csv,
    format_import_preview,
    import_translations_from_csv,
    restore_database_from_backup,
)
from tradutor_pgn.edit_window import format_propagation_confirmation
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
    create_glossary_backup,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    SynchronousProgress,
    _stamp,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


class StatsTablesTests(unittest.TestCase):
    """Garantia F24 (CSV): as tabelas do relatorio saem em planilha (22.12).

    A janela exportava so `.txt` corrido, e as tres tabelas — progresso por obra,
    palavras por par e atividade por dia — sao o que se cola num orcamento.
    """

    ESTATISTICAS = {
        "per_file": [("cap01.pgn", 120, 100, 40, 60, 3)],
        "words_by_pair": {
            ("en", "pt"): {
                "original": 1000,
                "translated": 1100,
                "verified": 400,
                "pending": 700,
            }
        },
        "daily": [("2026-07-31", 12, 340)],
    }

    def test_the_three_tables_come_out(self):
        titulos = [titulo for titulo, _cab, _linhas in db_tools.stats_tables(self.ESTATISTICAS)]
        self.assertEqual(
            titulos, ["progresso-por-obra", "palavras-por-par", "atividade-por-dia"]
        )

    def test_every_header_matches_its_rows(self):
        """Um cabecalho com uma coluna a mais desalinha a planilha inteira."""
        for titulo, cabecalho, linhas in db_tools.stats_tables(self.ESTATISTICAS):
            for linha in linhas:
                self.assertEqual(len(linha), len(cabecalho), titulo)

    def test_the_language_pair_comes_out_readable(self):
        _titulo, _cab, linhas = db_tools.stats_tables(self.ESTATISTICAS)[1]
        self.assertEqual(linhas[0][0], app_config.language_label("en"))
        self.assertEqual(linhas[0][1], "pt")

    def test_empty_stats_produce_empty_tables_and_not_an_error(self):
        tabelas = db_tools.stats_tables({})
        self.assertEqual([linhas for _t, _c, linhas in tabelas], [[], [], []])


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
            # No modulo que a funcao LE (`db_export`, ROADMAP 28.11): trocar a
            # copia re-exportada por `db_tools` nao mudaria nada — e o teste
            # passaria do mesmo jeito, sem ver a progressao.
            self.addCleanup(setattr, db_export, "EXPORT_CHUNK", db_export.EXPORT_CHUNK)
            db_export.EXPORT_CHUNK = 500

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
            self.assertGreaterEqual(len(progresso), 3, "com blocos de 500 ha progressao no meio")

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


class ProseInDatabaseTests(unittest.TestCase):
    """Garantia P6: a passada sobre o banco alcanca o que ja esta gravado —
    so as linhas pendentes, com historico, e nunca as verificadas.

    A secao 11 do ROADMAP nasceu porque a correcao de lances so alcancava a
    traducao nova e 4.144 linhas ficaram erradas; as normalizacoes de prosa
    nascem com a passada.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db_path = self.base / "traducoes.db"
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "The d5-knight is strong after", "O cavalo-d5 e forte depois", "pt", "en")
        save_translation(cur, "After 10... d5 White is fine", "Depois de 10...d5 as brancas estao bem", "pt", "en")
        save_translation(cur, "A quiet move.", "Um lance tranquilo.", "pt", "en")
        # A verificada tem o mesmo defeito e NAO pode ser tocada.
        save_translation(cur, "Black is better after", "As pretas estao melhores depois", "pt", "en")
        cur.execute("UPDATE comments SET verified = 1 WHERE original_comment = ?", ("Black is better after",))
        conn.commit()
        conn.close()

        self.dialogos = []
        self.confirma = True
        original = db_tools.messagebox
        db_tools.messagebox = types.SimpleNamespace(
            showinfo=lambda t, m, **_k: self.dialogos.append(("info", t, m)),
            showerror=lambda t, m, **_k: self.dialogos.append(("error", t, m)),
            askyesno=lambda t, m, **_k: (self.dialogos.append(("askyesno", t, m)) or self.confirma),
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
            translation_cache={"A quiet move.": "Um lance tranquilo."},
            log_message=lambda _m: None,
        )

    def linhas(self):
        conn = initialize_database(str(self.db_path))
        try:
            return {
                orig: (trad, verified)
                for orig, trad, verified in conn.execute(
                    "SELECT original_comment, translated_comment, verified FROM comments"
                )
            }
        finally:
            conn.close()

    def historico(self):
        conn = initialize_database(str(self.db_path))
        try:
            return conn.execute(
                "SELECT c.original_comment, h.action, h.previous_translation, h.new_translation"
                " FROM comment_history h JOIN comments c ON c.id = h.comment_id"
                " WHERE h.action = 'prose_fix' ORDER BY h.id"
            ).fetchall()
        finally:
            conn.close()

    def test_the_preview_counts_only_pending_rows_and_writes_nothing(self):
        antes = self.linhas()
        stats = db_tools.analyze_database_prose(str(self.db_path), "en", "pt")

        self.assertEqual(stats["scanned"], 3, "a verificada nem entra na contagem")
        self.assertEqual(stats["changed"], 2)
        self.assertEqual(stats["moves"], 3, "hifen + preposicao na primeira, espaco na segunda")
        self.assertEqual(self.linhas(), antes, "a previa gravou")

    def test_applying_rewrites_pending_rows_with_history_and_leaves_verified_alone(self):
        db_tools.normalize_prose_in_database(self.app_falso(), "en", "pt")

        self.assertEqual(
            self.linhas(),
            {
                "The d5-knight is strong after": ("O cavalo de d5 e forte depois de", 0),
                "After 10... d5 White is fine": ("Depois de 10... d5 as brancas estao bem", 0),
                "A quiet move.": ("Um lance tranquilo.", 0),
                "Black is better after": ("As pretas estao melhores depois", 1),
            },
        )
        self.assertEqual(
            self.historico(),
            [
                ("The d5-knight is strong after", "prose_fix", "O cavalo-d5 e forte depois", "O cavalo de d5 e forte depois de"),
                ("After 10... d5 White is fine", "prose_fix", "Depois de 10...d5 as brancas estao bem", "Depois de 10... d5 as brancas estao bem"),
            ],
        )

    def test_saying_no_leaves_everything_and_the_preview_names_the_scope(self):
        self.confirma = False
        antes = self.linhas()

        db_tools.normalize_prose_in_database(self.app_falso(), "en", "pt")

        self.assertEqual(self.linhas(), antes)
        pergunta = next(m for tipo, _t, m in self.dialogos if tipo == "askyesno")
        self.assertIn("PENDENTES", pergunta)
        self.assertIn("Traducoes que serao alteradas: 2", pergunta)
        self.assertIn("ja verificadas nao sao tocadas", pergunta)

    def test_a_backup_is_created_and_the_cache_is_dropped(self):
        app = self.app_falso()

        db_tools.normalize_prose_in_database(app, "en", "pt")

        copias = list((self.base / "backups").glob("traducoes-backup-*.db"))
        self.assertEqual(len(copias), 1)
        self.assertIn(copias[0].name, self.dialogos[-1][2])
        self.assertEqual(app.translation_cache, {}, "o cache tem o texto de ANTES")

    def test_nothing_to_do_says_so_without_asking(self):
        conn = initialize_database(str(self.db_path))
        conn.execute("UPDATE comments SET verified = 1")
        conn.commit()
        conn.close()

        db_tools.normalize_prose_in_database(self.app_falso(), "en", "pt")

        self.assertEqual([tipo for tipo, _t, _m in self.dialogos], ["info"])
        self.assertIn("Nenhuma tradu", self.dialogos[0][2])


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


class TypedConfirmationTests(unittest.TestCase):
    """A regra do dialogo que exige digitar a palavra.

    Pura e separada da janela de proposito: e ela que decide se algo e apagado, e
    testa-la nao pode exigir abrir um `Toplevel`.
    """

    def test_the_word_releases_the_action(self):
        self.assertTrue(confirmation_accepted(CONFIRMATION_WORD))

    def test_the_word_is_in_the_language_of_the_dialog(self):
        """O dialogo e todo em portugues e o botao dele se chama "Apagar".

        A palavra era `delete`, e quem digitava "apagar" — a leitura mais natural
        do que esta na tela — era RECUSADO sem explicacao (ROADMAP 22.12). Uma
        barreira que existe para transformar clique em decisao nao pode falhar
        por vocabulario.
        """
        self.assertEqual(CONFIRMATION_WORD, "apagar")

    def test_case_and_surrounding_space_do_not_matter(self):
        """Quem digitou APAGAR decidiu tanto quanto quem digitou apagar."""
        for texto in ["APAGAR", " apagar ", "Apagar", "\tapagar\n"]:
            with self.subTest(texto=texto):
                self.assertTrue(confirmation_accepted(texto))

    def test_the_old_word_still_passes_for_one_version(self):
        """Quem usa o programa ha meses tem `delete` na memoria dos dedos."""
        for texto in ["delete", "DELETE", " delete "]:
            with self.subTest(texto=texto):
                self.assertTrue(confirmation_accepted(texto))

    def test_the_old_word_does_not_leak_into_another_word(self):
        """Um chamador que peca outra palavra nao ganha `delete` de brinde."""
        self.assertFalse(confirmation_accepted("delete", word="zerar"))
        self.assertTrue(confirmation_accepted("zerar", word="zerar"))

    def test_anything_else_does_not(self):
        for texto in ["", None, "apag", "apagars", "del", "sim", "s"]:
            with self.subTest(texto=texto):
                self.assertFalse(confirmation_accepted(texto))

    def test_a_yes_never_passes_for_the_word(self):
        """O ponto do dialogo e nao ser um Sim a um clique de distancia."""
        self.assertFalse(confirmation_accepted("sim"))
        self.assertFalse(confirmation_accepted("yes"))
        self.assertFalse(confirmation_accepted("ok"))


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


class DiscardUnreviewedToolTests(ResetToolsTestCase):
    """A ferramenta em volta de Z4 segue "Zerar Traducoes" passo a passo (Z1, Z2, Z3)."""

    LIVRO = "C:/obras/livro.pgn"

    def banco(self):
        db_path = self.base / "traducoes.db"
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        textos = ["the rook", "the bishop", "the queen"]
        for texto in textos:
            save_translation(cur, texto, f"T {texto}", "pt", "en")
        ids = resolve_comment_ids(cur, "pt", textos, "en")
        record_occurrences(
            cur, self.LIVRO, [(n + 1, 1, n + 1, t) for n, t in enumerate(textos)], ids
        )
        set_translation_verified_by_id(cur, ids["the queen"], True)
        conn.commit()
        conn.close()
        return db_path

    def arquivo(self):
        return os.path.abspath(self.LIVRO)

    def backups(self):
        pasta = self.base / "backups"
        return sorted(p.name for p in pasta.glob("*.db")) if pasta.exists() else []

    def linhas(self, db_path):
        conn = initialize_database(str(db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        finally:
            conn.close()

    def descartar(self, app, on_finish=None):
        db_tools.discard_unreviewed_translations(
            app, self.arquivo(), "pt", source_language="en", on_finish=on_finish
        )

    def test_the_backup_comes_before_the_question_and_is_named_in_it(self):
        db_path = self.banco()
        self.resposta = False
        self.descartar(self.app_falso(db_path))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(len(self.perguntas), 1)
        self.assertIn(self.backups()[0], self.perguntas[0][1])

    def test_the_question_names_the_file_and_the_count(self):
        db_path = self.banco()
        self.resposta = False
        self.descartar(self.app_falso(db_path))
        self.assertIn("2 tradução(ões)", self.perguntas[0][1])
        self.assertIn("livro.pgn", self.perguntas[0][1])

    def test_saying_no_leaves_the_database_and_the_cache_alone(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        self.resposta = False
        resultados = []
        self.descartar(app, on_finish=resultados.append)
        self.assertEqual(self.linhas(db_path), 3)
        self.assertEqual(app.translation_cache, {"the rook": "a torre"})
        self.assertEqual(resultados, [None])

    def test_saying_yes_discards_only_the_unreviewed_and_clears_the_cache(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        resultados = []
        self.descartar(app, on_finish=resultados.append)
        self.assertEqual(self.linhas(db_path), 1)
        self.assertEqual(app.translation_cache, {})
        self.assertEqual(resultados, [2])
        self.assertIn("info", [tipo for tipo, _t, _m in self.dialogos])

    def test_nothing_to_discard_means_no_question_and_no_backup(self):
        db_path = self.base / "traducoes.db"
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        ids = resolve_comment_ids(cur, "pt", ["the rook"], "en")
        record_occurrences(cur, self.LIVRO, [(1, 1, 1, "the rook")], ids)
        set_translation_verified_by_id(cur, ids["the rook"], True)
        conn.commit()
        conn.close()
        resultados = []
        self.descartar(self.app_falso(db_path), on_finish=resultados.append)
        self.assertEqual(self.perguntas, [])
        self.assertEqual(self.backups(), [])
        self.assertEqual(resultados, [None])
        self.assertIn("livro.pgn", self.dialogos[0][2])


class RevertRunToolTests(ResetToolsTestCase):
    """A ferramenta em volta de Z5 segue "Descartar nao revisadas" passo a passo."""

    LIVRO = "C:/obras/livro.pgn"

    def banco(self, com_execucao=True):
        db_path = self.base / "traducoes.db"
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        save_translation(cur, "the king", "o rei", "pt", "en")
        if com_execucao:
            run_id = begin_translation_run(cur, "pt", "en", "C:/obras", [self.LIVRO], "google-gtx")
            textos = ["the rook", "the bishop", "the queen"]
            for texto in textos:
                save_translation(cur, texto, f"T {texto}", "pt", "en", run_id=run_id)
            ids = resolve_comment_ids(cur, "pt", textos, "en")
            record_occurrences(
                cur, self.LIVRO, [(n + 1, 1, n + 1, t) for n, t in enumerate(textos)], ids
            )
            set_translation_verified_by_id(cur, ids["the queen"], True)
            finish_translation_run(cur, run_id, RUN_COMPLETED, 3, 0)
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

    def reverter(self, app, on_finish=None):
        db_tools.revert_last_translation_run(app, on_finish=on_finish)

    def test_the_backup_comes_before_the_question_and_is_named_in_it(self):
        db_path = self.banco()
        self.resposta = False
        self.reverter(self.app_falso(db_path))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(len(self.perguntas), 1)
        self.assertIn(self.backups()[0], self.perguntas[0][1])

    def test_the_question_describes_the_run_and_the_count(self):
        db_path = self.banco()
        self.resposta = False
        self.reverter(self.app_falso(db_path))
        pergunta = self.perguntas[0][1]
        self.assertIn("2 tradução(ões)", pergunta)
        self.assertIn("livro.pgn", pergunta)
        self.assertIn("#1", pergunta)
        self.assertIn("concluída", pergunta)
        self.assertIn("google-gtx", pergunta)

    def test_saying_no_leaves_the_database_and_the_cache_alone(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        self.resposta = False
        resultados = []
        self.reverter(app, on_finish=resultados.append)
        self.assertEqual(self.linhas(db_path), 4)
        self.assertEqual(app.translation_cache, {"the rook": "a torre"})
        self.assertEqual(resultados, [None])

    def test_saying_yes_reverts_only_the_untouched_and_clears_the_cache(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        resultados = []
        self.reverter(app, on_finish=resultados.append)
        self.assertEqual(self.linhas(db_path), 2)
        self.assertEqual(app.translation_cache, {})
        self.assertEqual(resultados, [2])
        self.assertIn("info", [tipo for tipo, _t, _m in self.dialogos])

    def test_no_run_means_no_question_and_no_backup(self):
        db_path = self.banco(com_execucao=False)
        resultados = []
        self.reverter(self.app_falso(db_path), on_finish=resultados.append)
        self.assertEqual(self.perguntas, [])
        self.assertEqual(self.backups(), [])
        self.assertEqual(resultados, [None])
        self.assertIn("Nenhuma execução", self.dialogos[0][2])

    def test_nothing_left_to_revert_says_so_without_a_backup(self):
        db_path = self.banco()
        app = self.app_falso(db_path)
        self.reverter(app)
        self.perguntas.clear()
        self.dialogos.clear()
        self.reverter(app)
        self.assertEqual(self.perguntas, [])
        self.assertEqual(len(self.backups()), 1, "a segunda chamada nao devia criar backup")
        self.assertIn("Não há o que reverter", self.dialogos[0][2])

    def test_it_reverts_the_newest_run_and_not_an_older_one(self):
        db_path = self.banco()
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        r2 = begin_translation_run(cur, "pt", "en", "C:/obras", ["C:/obras/cap2.pgn"], "google-gtx")
        save_translation(cur, "the knight", "T the knight", "pt", "en", run_id=r2)
        finish_translation_run(cur, r2, RUN_COMPLETED, 1, 0)
        conn.commit()
        conn.close()

        resultados = []
        self.reverter(self.app_falso(db_path), on_finish=resultados.append)
        self.assertIn("#2", self.perguntas[0][1])
        self.assertIn("cap2.pgn", self.perguntas[0][1])
        self.assertEqual(resultados, [1])
        self.assertEqual(self.linhas(db_path), 4, "a execucao #1 nao devia ser tocada")

    def test_the_stats_report_lists_the_runs_newest_first(self):
        db_path = self.banco()
        conn = initialize_database(str(db_path))
        cur = conn.cursor()
        r2 = begin_translation_run(cur, "pt", "en", "", [], "google-gtx")
        finish_translation_run(cur, r2, RUN_CANCELED, 0, 0)
        conn.commit()
        conn.close()
        stats = db_tools.collect_database_stats(str(db_path))
        self.assertEqual([run["id"] for run in stats["runs"]], [2, 1])
        relatorio = db_tools.format_database_stats(stats)
        self.assertIn("Ultimas execucoes", relatorio)
        self.assertLess(relatorio.index("#2  "), relatorio.index("#1  "))
        self.assertIn("cancelada", relatorio)
        self.assertIn("3 inserida(s)", relatorio)
        # Um relatorio montado a mao, sem a chave, continua saindo.
        stats.pop("runs")
        self.assertIn("nenhuma execução registrada", db_tools.format_database_stats(stats))


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

    # ------------------------------------------------------- ROADMAP 22.12

    def test_the_question_counts_the_file_and_not_the_applicable_rules(self):
        """Garantia S16. Anunciava 7.325 e apagava 5.910 no glossario real.

        Aqui a mesma divergencia cabe em duas linhas: a de `@casa@` vale 64
        regras na aplicacao e UMA no arquivo, e a de limpeza nao entra na lista
        aplicavel mas e apagada do mesmo jeito.
        """
        self.glossario_com(
            [
                ("@casa@-torre", "torre de @casa@", "suggestion"),
                ("  x  ", "y", "cleanup"),
            ]
        )
        app = self.app_falso(self.base / "traducoes.db")
        # O estado que o dialogo lia antes: a lista APLICAVEL, com 64 regras.
        app.glossary_substitutions = load_interactive_substitutions()
        self.assertEqual(len(app.glossary_substitutions), 64)
        self.resposta = False

        db_tools.reset_glossary(app)

        self.assertIn("2 regras", self.perguntas[0][1])
        self.assertNotIn("64 regras", self.perguntas[0][1])

    def test_the_question_says_the_number_by_type(self):
        self.glossario_com([("rook", "torre", "suggestion"), ("  x  ", "y", "cleanup")])
        app = self.app_falso(self.base / "traducoes.db")
        self.resposta = False

        db_tools.reset_glossary(app)

        self.assertIn("1 sugestão e 1 limpeza", self.perguntas[0][1])

    def test_the_factory_rules_do_not_come_back_from_nowhere(self):
        """Zerar deixava a sessao sem regra nenhuma e a abertura seguinte com 232.

        A semente e mesclada em toda carga (S15) e o zerar nao a apaga — ela vem
        com o programa. Esvaziar a lista em memoria fazia o programa "recuperar"
        sozinho, no dia seguinte, um glossario que o usuario acabou de zerar.
        """
        caminho = self.glossario_com([("rook", "torre")])
        semente = self.base / "semente.txt"
        semente.write_text(
            "substituicoes = [('bishop', 'bispo', 'suggestion', 0, 'pt')]",
            encoding="utf-8",
        )
        original = glossario._default_seed_path
        glossario._default_seed_path = lambda: str(semente)
        self.addCleanup(setattr, glossario, "_default_seed_path", original)

        app = self.app_falso(self.base / "traducoes.db")

        db_tools.reset_glossary(app)

        self.assertEqual(load_glossary_entries(str(caminho), prefer_db=False), [])
        self.assertEqual(
            [tuple(regra[:2]) for regra in app.glossary_substitutions],
            [("bishop", "bispo")],
        )

    def test_the_result_says_what_is_left(self):
        """Sem isso, "glossario zerado" com sugestoes ainda aparecendo confunde."""
        self.glossario_com([("rook", "torre")])
        semente = self.base / "semente.txt"
        semente.write_text(
            "substituicoes = [('bishop', 'bispo', 'suggestion', 0, 'pt')]",
            encoding="utf-8",
        )
        original = glossario._default_seed_path
        glossario._default_seed_path = lambda: str(semente)
        self.addCleanup(setattr, glossario, "_default_seed_path", original)

        db_tools.reset_glossary(self.app_falso(self.base / "traducoes.db"))

        infos = [m for tipo, _t, m in self.dialogos if tipo == "info"]
        self.assertTrue(infos, self.dialogos)
        self.assertIn("1 regra(s) de fábrica", infos[0])

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


if __name__ == "__main__":
    unittest.main()
