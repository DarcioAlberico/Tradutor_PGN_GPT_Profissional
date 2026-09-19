"""O worker de traducao: lotes, quedas, disjuntor, registro de execucao, progresso.

Parte da divisao de `test_core.py` (ROADMAP 28.11); ver `tests/helpers.py`."""

import os
import sqlite3
import types
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from tradutor_pgn import (
    glossario,
    settings,
)
from tradutor_pgn.database import (
    RUN_COMPLETED,
    RUN_CRASHED,
    RUN_FAILED,
    list_translation_runs,
    revert_translation_run,
    initialize_database,
    save_translation,
)
from tradutor_pgn.glossario import (
    load_glossary_entries,
    load_glossary_entry_details,
    rebuild_glossary_database,
)
from tradutor_pgn.pgn_utils import (
    BATCH_MAX_CHARS,
    batch_index_groups,
    create_comment_batches,
    detect_encoding,
    detect_encoding_from_bytes,
    extract_comment_texts,
    extract_comment_texts_from_file,
    extract_comments_from_content,
    extract_comments_from_file,
    generate_translated_pgn,
    read_pgn_text,
    translated_output_path,
)
from tradutor_pgn import pgn_utils
from tradutor_pgn import (
    failed_runs,
    llm_providers,
    translation_worker,
)
from helpers import setup_module_sandbox, teardown_module_sandbox
from helpers import (
    FakeApp,
    FakeProgress,
    FakeRoot,
    WorkerFallbackHarness,
    _pgn_com_comentarios,
    escrita_disponivel,
)


def setUpModule():
    setup_module_sandbox()


def tearDownModule():
    teardown_module_sandbox()


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


class ProgressStatusTests(unittest.TestCase):
    """O texto ao lado da barra (ROADMAP 28.10): puro, entao conferido sem worker."""

    def test_the_full_line_with_several_files(self):
        texto = translation_worker.format_progress_status(2, 5, 37, 125, 2410, 6500, 120.5)
        self.assertEqual(texto, "Arquivo 2/5 · Lote 37/125 · 2.410/6.500 · ~3 min")

    def test_a_single_file_hides_the_file_part(self):
        texto = translation_worker.format_progress_status(1, 1, 3, 10, 30, 100, 30.0)
        self.assertTrue(texto.startswith("Lote 3/10"), texto)
        self.assertNotIn("Arquivo", texto)

    def test_no_estimate_before_the_first_comment_nor_after_the_last(self):
        self.assertEqual(
            translation_worker.format_progress_status(1, 1, 1, 4, 0, 40, 5.0),
            "Lote 1/4 · 0/40",
        )
        self.assertEqual(
            translation_worker.format_progress_status(1, 1, 4, 4, 40, 40, 90.0),
            "Lote 4/4 · 40/40",
        )

    def test_the_estimate_is_a_rule_of_three_on_what_was_done(self):
        # 10 feitos em 20 s -> 2 s cada -> 30 que faltam = 60 s = ~1 min
        texto = translation_worker.format_progress_status(1, 1, 1, 4, 10, 40, 20.0)
        self.assertTrue(texto.endswith("~1 min"), texto)

    def test_eta_units(self):
        eta = translation_worker.format_eta
        self.assertEqual(eta(0.4), "~1 s")
        self.assertEqual(eta(45), "~45 s")
        self.assertEqual(eta(150), "~2 min")
        self.assertEqual(eta(3600), "~1 h")
        self.assertEqual(eta(4800), "~1 h 20 min")
        self.assertEqual(eta(None), "")

    def test_the_label_channel_tolerates_an_app_without_the_label(self):
        app = types.SimpleNamespace(root=FakeRoot())
        translation_worker.set_progress_text(app, "qualquer")  # nao levanta

    def test_the_label_channel_writes_through_the_tk_thread(self):
        escritos = []
        app = types.SimpleNamespace(
            root=FakeRoot(),
            progress_label=types.SimpleNamespace(configure=lambda **kw: escritos.append(kw)),
        )
        translation_worker.set_progress_text(app, "Lote 1/2 · 5/10")
        self.assertEqual(escritos, [{"text": "Lote 1/2 · 5/10"}])


class LastRunRecordTests(unittest.TestCase):
    """O worker deixa para a janela principal o que "Revisar pendentes" precisa (28.10)."""

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
        self.pgn = self.base / "game.pgn"
        self.pgn.write_text(
            '[Event "Test"]\n\n1. e4 {White starts} e5 {Black replies}\n',
            encoding="utf-8",
        )
        conn = initialize_database(str(self.db_path))
        cur = conn.cursor()
        save_translation(cur, "White starts", "As brancas começam", "pt")
        save_translation(cur, "Black replies", "As pretas respondem", "pt")
        conn.commit()
        conn.close()

        original_translate = translation_worker.translate_text
        translation_worker.translate_text = lambda *_a, **_k: None
        self.addCleanup(setattr, translation_worker, "translate_text", original_translate)

    def rodar(self, app, alvo="pt"):
        translation_worker.run_translation(app, str(self.pgn), alvo, False)

    def test_a_completed_run_is_recorded_with_its_files_and_target(self):
        app = FakeApp(self.db_path)
        app.last_run = None
        self.rodar(app)
        self.assertEqual(app.last_run["files"], [os.path.abspath(str(self.pgn))])
        self.assertEqual(
            app.last_run["generated"], [os.path.abspath(str(self.base / "game-BR.pgn"))]
        )
        self.assertEqual(app.last_run["target_language"], "pt")
        self.assertTrue(app.last_run["completed"])

    def test_the_progress_label_reaches_concluida_at_the_end(self):
        app = FakeApp(self.db_path)
        textos = []
        app.progress_label = types.SimpleNamespace(
            configure=lambda **kw: textos.append(kw["text"])
        )
        self.rodar(app)
        self.assertTrue(textos, "a barra nao ganhou texto")
        self.assertTrue(any(t.startswith("Lote 1/1") for t in textos), textos)
        # Feito/total, nesta ordem: invertidos, o segundo comentario de dois
        # anunciaria "2/1" — um numero que so aparece a meio caminho, e por isso
        # o unico ponto em que a troca e visivel.
        self.assertTrue(
            any(t.startswith("Lote 1/1 · 1/2") for t in textos), textos
        )
        self.assertIn("Lote 1/1 · 2/2", textos)
        self.assertEqual(textos[-1], "Concluída")

    def test_a_canceled_run_before_any_file_leaves_the_previous_record(self):
        app = FakeApp(self.db_path)
        anterior = {"files": ["x"], "generated": [], "target_language": "pt", "completed": True}
        app.last_run = anterior
        app.cancel_flag.set()
        self.rodar(app)
        self.assertIs(app.last_run, anterior)

    def test_a_file_that_cannot_be_reread_registers_nothing(self):
        """Sem posicoes gravadas nao ha o que o filtro do editor saiba abrir.

        O arquivo some (ou fica ilegivel) entre a primeira passada e a
        gravacao: as traducoes ja estao no banco, mas a procedencia delas nao —
        e "Revisar as pendentes desta execucao" nao tem arquivo para filtrar.
        """
        original = translation_worker.extract_comments_from_content

        def falhar(*_a, **_k):
            raise OSError("o disco sumiu")

        translation_worker.extract_comments_from_content = falhar
        self.addCleanup(
            setattr, translation_worker, "extract_comments_from_content", original
        )
        app = FakeApp(self.db_path)
        app.last_run = None

        self.rodar(app)

        self.assertIsNone(app.last_run)

    def test_a_pgn_without_comments_records_nothing(self):
        self.pgn.write_text('[Event "Test"]\n\n1. e4 e5\n', encoding="utf-8")
        app = FakeApp(self.db_path)
        app.last_run = None
        self.rodar(app)
        self.assertIsNone(app.last_run)


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

    def test_right_count_wrong_sizes_also_falls_back(self):
        """ROADMAP 28.12: o lote volta com o NUMERO certo de partes, mas uma
        delas engoliu a vizinha e a vizinha voltou vazia. A contagem aprova; a
        razao de tamanho manda para o modo individual, e nenhum comentario
        recebe o texto do outro."""
        longos = [
            "White has a clear advantage in the endgame after the exchange of queens.",
            "Black must defend very carefully to hold this position for a draw.",
            "The knight on d5 dominates the board and cannot be challenged.",
        ]
        self.PGN = (
            '[Event "Test"]\n\n'
            f"1. e4 {{{longos[0]}}} e5 {{{longos[1]}}} 2. Nf3 {{{longos[2]}}}\n"
        )
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                partes = text.split(" ||| ")
                # Tres partes, como esperado — mas a primeira levou a segunda.
                return " ||| ".join(
                    [f"[{partes[0]}] [{partes[1]}]", "", f"[{partes[2]}]"]
                )
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        for comentario in longos:
            self.assertEqual(gravadas.get(comentario), f"[{comentario}]")
        self.assertEqual(len(chamadas), 1 + len(longos))
        self.assertTrue(
            any("parte 2 do lote" in linha and "individualmente" in linha for linha in app.logs),
            "o log devia dizer QUAL parte estourou a razao (a vazia, nao a dobrada)",
        )

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


class IndividualFallbackBreakerTests(WorkerFallbackHarness, unittest.TestCase):
    """Garantia B4: o disjuntor alcanca o ramo comentario a comentario.

    `consecutive_failed_batches` so era alimentado no ramo "a API nao
    respondeu". Um lote que RESPONDEU desalinhado caia no fallback individual
    (B2) — e se a rede morresse ali, cada comentario pagava 3 tentativas x 30 s
    sem que nada abortasse: o unico caminho fora do alcance de B3 (ROADMAP
    28.1).
    """

    def pgn_com(self, n, tamanho=20):
        pgn = '[Event "Test"]\n\n'
        comentarios = []
        for indice in range(n):
            texto = f"Comment number {indice} " + "x" * tamanho
            comentarios.append(texto)
            pgn += f"{indice + 1}. e4 {{{texto}}} "
        return pgn, comentarios

    def roda(self, tmp_path, pgn_texto, translate):
        # `run_worker` grava `self.PGN`; o da classe-base tem 3 comentarios,
        # que e exatamente o limite do disjuntor — indistinguivel do bug.
        self.PGN = pgn_texto
        return self.run_worker(tmp_path, translate)

    def test_consecutive_dead_individual_calls_abort_the_run(self):
        pgn_texto, comentarios = self.pgn_com(8)
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                return "so uma parte"  # respondeu, mas desalinhado (B2)
            return None  # e dai a rede morreu

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.roda(tmp_path, pgn_texto, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        limite = translation_worker.MAX_CONSECUTIVE_FAILED_BATCHES
        self.assertGreater(len(comentarios), limite + 1)
        # A do lote, mais `limite` individuais — e nao uma por comentario.
        self.assertEqual(
            len(chamadas),
            1 + limite,
            f"a API foi chamada {len(chamadas)} vezes; devia parar em {1 + limite}",
        )
        self.assertEqual(gravadas, {})
        abortado = [linha for linha in app.logs if "[ABORTADO]" in linha]
        self.assertEqual(len(abortado), 1)
        self.assertIn("modo individual", abortado[0])
        # T2/T3: os que nao foram tentados sao contados, nao esquecidos.
        self.assertIn(f"{len(comentarios) - limite} restantes", abortado[0])
        self.assertTrue(
            any(f"Comentarios que falharam: {len(comentarios)}" in linha for linha in app.logs),
            "o resumo conta os nao tentados como falha",
        )
        self.assertTrue(any("INTERROMPIDA" in linha for linha in app.logs))

    def test_a_group_that_answered_something_resets_the_counter(self):
        """Um grupo em que algum comentario respondeu nao e um lote morto."""
        pgn_texto, comentarios = self.pgn_com(8)
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                return "so uma parte"
            # Dois falham, um responde, dois falham, um responde...
            return None if len(chamadas) % 3 else f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.roda(tmp_path, pgn_texto, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        self.assertEqual(len(chamadas), 1 + len(comentarios))
        self.assertFalse(any("[ABORTADO]" in linha for linha in app.logs))
        self.assertGreater(len(gravadas), 0)

    def test_small_dead_groups_count_as_dead_batches(self):
        """Grupos de 2 nunca chegam ao limite de seguidos; contam como lote."""
        # Comentarios grandes o bastante para caberem dois por lote.
        pgn_texto, comentarios = self.pgn_com(8, tamanho=BATCH_MAX_CHARS // 2 - 40)
        chamadas = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            return "so uma parte" if " ||| " in text else None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.roda(tmp_path, pgn_texto, translate)

        limite = translation_worker.MAX_CONSECUTIVE_FAILED_BATCHES
        lotes = [texto for texto in chamadas if " ||| " in texto]
        self.assertTrue(all(texto.count(" ||| ") == 1 for texto in lotes), "2 por lote")
        self.assertEqual(len(lotes), limite, "parou depois de `limite` lotes mortos")
        self.assertEqual(len(chamadas), limite * 3)
        self.assertTrue(any("[ABORTADO]" in linha for linha in app.logs))


    def test_an_alive_misaligned_group_resets_the_dead_batch_count(self):
        """Lote morto, lote desalinhado mas vivo, tres mortos: so os tres
        seguidos contam. Sem o zeramento, o primeiro morto somaria com os dois
        seguintes e a execucao abortaria um lote antes."""
        pgn_texto, comentarios = self.pgn_com(10, tamanho=BATCH_MAX_CHARS // 2 - 40)
        chamadas = []
        lotes_vistos = []

        def translate(text, *_args, **_kwargs):
            chamadas.append(text)
            if " ||| " in text:
                lotes_vistos.append(text)
                # O segundo lote responde desalinhado; os outros, nada.
                return "so uma parte" if len(lotes_vistos) == 2 else None
            return f"[{text}]"  # os individuais do segundo lote respondem

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.roda(tmp_path, pgn_texto, translate)
            gravadas = self.stored(tmp_path / "cache.db")

        limite = translation_worker.MAX_CONSECUTIVE_FAILED_BATCHES
        self.assertEqual(len(gravadas), 2, "o lote vivo gravou os seus dois")
        # 1 morto + (1 + 2 individuais) + `limite` mortos: o vivo zerou a conta.
        self.assertEqual(len(lotes_vistos), 2 + limite)
        self.assertEqual(len(chamadas), 1 + 3 + limite)
        self.assertTrue(any("[ABORTADO]" in linha for linha in app.logs))


class WorkerPlayerNameTests(WorkerFallbackHarness, unittest.TestCase):
    """X4 no worker: o nome nunca vai a API e sempre volta byte a byte; um
    sentinela de nome engolido custa uma segunda requisicao sem a mascara de
    nomes, e so depois dela o comentario conta como falha."""

    PGN = '[Event "Test"]\n\n1. e4 {and White resigned in G. Sax-G. Mohr, Maribor 2000.} *\n'
    COMMENTS = ["and White resigned in G. Sax-G. Mohr, Maribor 2000."]

    def test_the_name_never_reaches_the_api_and_comes_back_intact(self):
        enviados = []

        def translate(text, *_a, **_k):
            enviados.append(text)
            return text.replace("and White resigned in", "e as brancas abandonaram em")

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)
            gravadas = self.stored(Path(tmp) / "cache.db")

        self.assertEqual(len(enviados), 1)
        self.assertNotIn("Sax", enviados[0])
        self.assertIn("\u27e60\u27e7, Maribor 2000", enviados[0])
        self.assertEqual(gravadas[self.COMMENTS[0]], "e as brancas abandonaram em G. Sax-G. Mohr, Maribor 2000.")
        self.assertFalse(any("reenviados" in l for l in app.logs))

    def test_a_swallowed_name_sentinel_is_resent_without_the_mask(self):
        enviados = []

        def translate(text, *_a, **_k):
            enviados.append(text)
            if "\u27e6" in text:
                return "e as brancas abandonaram em , Maribor 2000."  # o sentinela sumiu
            return "e as brancas abandonaram em G. Sax-G. Mohr, Maribor 2000."

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)
            gravadas = self.stored(Path(tmp) / "cache.db")

        self.assertEqual(len(enviados), 2, "uma segunda requisicao, sozinha")
        self.assertIn("G. Sax-G. Mohr", enviados[1], "a segunda vai com o nome cru")
        self.assertNotIn("\u27e6", enviados[1])
        self.assertEqual(gravadas[self.COMMENTS[0]], "e as brancas abandonaram em G. Sax-G. Mohr, Maribor 2000.")
        self.assertTrue(any("reenviados sem a mascara de nomes: 1" in l for l in app.logs))
        self.assertTrue(any("Comentarios que falharam: 0" in l for l in app.logs))

    def test_the_second_try_is_the_old_behaviour_and_is_stored(self):
        """Sem anotacao no comentario, a segunda tentativa e a traducao crua de
        antes da mascara: o que a maquina devolver e gravado — que e o defeito
        que existia antes de 28.3, e menor do que um comentario no original."""
        def translate(text, *_a, **_k):
            return "e as brancas abandonaram em , Maribor 2000."

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)
            gravadas = self.stored(Path(tmp) / "cache.db")

        self.assertEqual(gravadas[self.COMMENTS[0]], "e as brancas abandonaram em , Maribor 2000.")
        self.assertTrue(any("reenviados sem a mascara de nomes: 1" in l for l in app.logs))

    def test_failing_twice_with_an_annotation_is_a_failure(self):
        """Com anotacao junto, a segunda tentativa ainda e verificada (X1): se
        a anotacao tambem nao volta, e falha, e nada e gravado."""
        self.PGN = '[Event "Test"]\n\n1. e4 {resigned in G. Sax-G. Mohr, Maribor 2000 [%clk 0:01]} *\n'
        self.COMMENTS = ["resigned in G. Sax-G. Mohr, Maribor 2000 [%clk 0:01]"]
        enviados = []

        def translate(text, *_a, **_k):
            enviados.append(text)
            return "abandonou em , Maribor 2000"  # engoliu os dois sentinelas

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)
            gravadas = self.stored(Path(tmp) / "cache.db")

        self.assertEqual(len(enviados), 2)
        self.assertEqual(gravadas, {})
        self.assertTrue(any("[FALHA]" in l and "nomes" in l for l in app.logs))
        self.assertTrue(any("Comentarios que falharam: 1" in l for l in app.logs))

    def test_a_swallowed_annotation_is_not_resent(self):
        """A segunda chance e dos NOMES: uma anotacao [%...] engolida continua
        sendo falha na hora (X1), sem gastar requisicao."""
        self.PGN = '[Event "Test"]\n\n1. e4 {Best was Nxe5 [%clk 0:05:30]} *\n'
        self.COMMENTS = ["Best was Nxe5 [%clk 0:05:30]"]
        enviados = []

        def translate(text, *_a, **_k):
            enviados.append(text)
            return "Melhor era Cxe5"

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)

        self.assertEqual(len(enviados), 1)
        self.assertTrue(any("Comentarios que falharam: 1" in l for l in app.logs))


class WorkerTrailingPrepositionTests(WorkerFallbackHarness, unittest.TestCase):
    """O conserto roda nos DOIS caminhos do worker e chega ao banco e ao PGN."""

    PGN = (
        '[Event "Test"]\n\n'
        "1. e4 {White is better after} e5 {Black is fine after} 2. Nf3 {ok}\n"
    )
    COMMENTS = ["White is better after", "Black is fine after", "ok"]

    def roda(self, tmp_path, alinhado):
        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                if not alinhado:
                    return "so uma parte"
                return " ||| ".join(self.traduz(p) for p in text.split(" ||| "))
            return self.traduz(text)

        return self.run_worker(tmp_path, translate)

    @staticmethod
    def traduz(texto):
        return {
            "White is better after": "As brancas estao melhores depois",
            "Black is fine after": "As pretas estao bem depois",
            "ok": "ok",
        }[texto]

    def test_batch_and_individual_paths_store_the_repaired_text(self):
        for alinhado in (True, False):
            with self.subTest(alinhado=alinhado), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.roda(tmp_path, alinhado)
                gravadas = self.stored(tmp_path / "cache.db")
                saida = next(tmp_path.glob("*-BR.pgn")).read_text(encoding="utf-8")

                self.assertEqual(
                    gravadas["White is better after"], "As brancas estao melhores depois de"
                )
                self.assertEqual(gravadas["Black is fine after"], "As pretas estao bem depois de")
                self.assertIn("{As brancas estao melhores depois de}", saida)
                self.assertTrue(
                    any("Consertos de prosa" in l and l.endswith("2") for l in app.logs),
                    "o resumo conta as duas",
                )


class WorkerTracebackTests(WorkerFallbackHarness, unittest.TestCase):
    """O `[ERRO GERAL]` leva o traceback para o log (ROADMAP 28.1).

    So `str(e)` de um `IndexError` no meio de um livro nao diz em qual das
    etapas ele nasceu, e o log e o unico artefato que sobra depois — o mesmo
    motivo de o relator de callbacks do Tk gravar o traceback.
    """

    def test_the_general_error_logs_where_it_came_from(self):
        def translate(*_args, **_kwargs):
            raise IndexError("list index out of range")

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)

        log = "\n".join(app.logs)
        self.assertIn("[ERRO GERAL] list index out of range", log)
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn("run_translation", log)
        self.assertIn("IndexError", log)


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


class WorkerRunRecordTests(WorkerFallbackHarness, unittest.TestCase):
    """O worker abre a linha da execucao antes do primeiro INSERT e fecha no
    `finally` com o desfecho certo — inclusive quando morreu."""

    def execucoes(self, tmp_path):
        conn = initialize_database(str(tmp_path / "cache.db"))
        try:
            return list_translation_runs(conn.cursor())
        finally:
            conn.close()

    def carimbos(self, tmp_path):
        conn = initialize_database(str(tmp_path / "cache.db"))
        try:
            return dict(
                conn.execute("SELECT original_comment, inserted_run_id FROM comments").fetchall()
            )
        finally:
            conn.close()

    def test_a_clean_run_is_completed_with_its_inserts_stamped(self):
        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.run_worker(tmp_path, translate)
            execucoes = self.execucoes(tmp_path)
            carimbos = self.carimbos(tmp_path)

        self.assertEqual(len(execucoes), 1)
        run = execucoes[0]
        self.assertEqual(run["outcome"], RUN_COMPLETED)
        self.assertEqual(run["inserted_count"], 3)
        self.assertEqual(run["failed_count"], 0)
        self.assertEqual(run["provider"], "google-gtx")
        self.assertEqual(run["target_language"], "pt")
        self.assertEqual([os.path.basename(f) for f in run["files"]], ["game.pgn"])
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(set(carimbos.values()), {run["id"]})

    def test_a_run_with_failures_is_failed_and_counts_them(self):
        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return "desalinhado"
            return None if text == "Second comment here" else f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.run_worker(tmp_path, translate)
            run = self.execucoes(tmp_path)[0]

        self.assertEqual(run["outcome"], RUN_FAILED)
        self.assertEqual((run["inserted_count"], run["failed_count"]), (2, 1))

    def test_a_crash_is_recorded_as_crashed_by_its_own_connection(self):
        def translate(_text, *_args, **_kwargs):
            raise RuntimeError("explodiu no meio")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app, _pgn = self.run_worker(tmp_path, translate)
            run = self.execucoes(tmp_path)[0]

        self.assertEqual(run["outcome"], RUN_CRASHED)
        self.assertIsNotNone(run["finished_at"])
        self.assertTrue(any("ERRO GERAL" in linha for linha in app.logs))

    def test_a_second_run_reuses_nothing_from_a_reverted_first(self):
        """O ciclo inteiro de 28.7: traduzir, reverter, traduzir de novo — a
        segunda execucao insere de novo e carimba com o id dela."""
        def translate(text, *_args, **_kwargs):
            if " ||| " in text:
                return " ||| ".join(f"[{p}]" for p in text.split(" ||| "))
            return f"[{text}]"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.run_worker(tmp_path, translate)
            conn = initialize_database(str(tmp_path / "cache.db"))
            primeira = list_translation_runs(conn.cursor())[0]
            self.assertEqual(revert_translation_run(conn.cursor(), primeira), 3)
            conn.commit()
            conn.close()

            self.run_worker(tmp_path, translate)
            execucoes = self.execucoes(tmp_path)
            carimbos = self.carimbos(tmp_path)

        self.assertEqual([run["outcome"] for run in execucoes], [RUN_COMPLETED, RUN_COMPLETED])
        self.assertEqual(execucoes[0]["inserted_count"], 3)
        self.assertEqual(set(carimbos.values()), {execucoes[0]["id"]})


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

    def test_a_single_byte_input_encoding_does_not_become_the_output_encoding(self):
        """A saida de um PGN cp1252 sai em UTF-8, inteira e com o log dizendo.

        Antes a saida herdava a codificacao da entrada. Um caractere que o
        cp1252 nao representa cortava o arquivo no meio da gravacao, e so o
        fallback do `UnicodeEncodeError` o salvava; um caractere que ele
        representa — todo acento do portugues — nao acionava fallback nenhum e
        saia em byte unico, para o leitor seguinte descartar.

        As duas metades ficam aqui juntas de proposito: o arquivo tem de sair
        INTEIRO (a checagem do truncamento, que era o ponto do teste antigo) e
        tem de sair em UTF-8.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "game.pgn"
            # Com acento: um PGN so de ASCII e detectado como UTF-8 (nunca como
            # 'ascii'), e a promocao que este teste exercita nao aconteceria.
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
            self.assertEqual(detect_encoding(saida), "utf-8")
            texto = Path(saida).read_text(encoding="utf-8")
            self.assertIn("posicao ganha 中", texto)
            self.assertIn("comentário 0 com ação", texto)
            self.assertTrue(texto.rstrip().endswith("*"), "o arquivo saiu truncado")
            self.assertEqual(texto.count("{"), 400)

        self.assertTrue(
            any("cp1252" in linha and "utf-8" in linha for linha in logs),
            f"a troca de codificacao tem de aparecer no log: {logs}",
        )

    def test_an_accented_translation_of_an_ascii_book_survives_the_next_reader(self):
        """O caso real: livro em ingles, traducao para portugues, acento sumido.

        Um PGN em ingles com dois nomes de jogador acentuados e detectado como
        cp1252. A traducao para portugues enche o arquivo de acento, o cp1252 o
        representa sem reclamar — nenhum `UnicodeEncodeError` —, e a saida
        ficava com milhares de bytes altos de byte unico. Quem le esperando
        UTF-8, como o ChessBase 26, descarta cada um deles: "Dragao" no lugar
        de "Dragão", "posio" no lugar de "posição".

        A prova aqui e a do leitor, e nao a do gravador: o arquivo e decodificado
        como UTF-8 estrito. Antes da correcao esta linha levanta
        `UnicodeDecodeError`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pgn = Path(tmp) / "livro.pgn"
            pgn.write_text(
                '[Event "Torneio"]\n[White "Jimenez, José"]\n\n'
                "1. e4 {A sharp line in the Dragon} 1-0\n",
                encoding="cp1252",
            )
            self.assertEqual(detect_encoding(str(pgn)), "cp1252")

            info = extract_comments_from_file(str(pgn))
            traducao = "Uma linha aguda na Dragão, com posição de ataque"
            saida = Path(tmp) / "livro-BR.pgn"

            self.assertTrue(
                generate_translated_pgn(
                    str(pgn),
                    str(saida),
                    {info["comments"][0]: traducao},
                    info["positions"],
                )
            )

            texto = saida.read_bytes().decode("utf-8")  # estrito de proposito
            self.assertIn(traducao, texto)
            self.assertIn("Jimenez, José", texto)

    def test_the_output_encoding_promotes_only_what_is_not_unicode(self):
        """A tabela da promocao, sem passar por disco.

        UTF-16 e UTF-32 nao entram: carregam BOM, se anunciam ao leitor e nao
        perdem caractere. E a opcao de BOM continua valendo DEPOIS da promocao.
        """
        casos = [
            # (codificacao de entrada, use_bom, codificacao de gravacao)
            ("cp1252", False, "utf-8"),
            ("cp1252", True, "utf-8-sig"),
            ("latin-1", False, "utf-8"),
            ("iso-8859-1", False, "utf-8"),
            ("utf-8", False, "utf-8"),
            ("utf-8", True, "utf-8-sig"),
            ("utf-8-sig", False, "utf-8-sig"),
            ("utf-16", False, "utf-16"),
            ("utf-16", True, "utf-16"),
            ("utf-32", False, "utf-32"),
        ]
        for entrada, bom, esperada in casos:
            with self.subTest(entrada=entrada, use_bom=bom):
                self.assertEqual(
                    pgn_utils._output_encoding(entrada, bom), esperada
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

            # Sem o calculo das posicoes (ROADMAP 28.8): o `python-chess` monta
            # a arvore de UMA partida por vez e a solta, mas uma partida de
            # 1.200 comentarios pesa ~9 MB sozinha e mascararia o que este
            # teste mede — se o worker segura TODOS os arquivos ate o fim.
            caminho = settings.default_settings_path()
            settings.save_settings({"board": {"fen": False}}, caminho)
            self.addCleanup(lambda: os.path.exists(caminho) and os.remove(caminho))

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


if __name__ == "__main__":
    unittest.main()


class FakeLLMTranslator:
    """O que o worker ve de um provedor de modelo (ROADMAP 28.7)."""

    def __init__(self, respostas=None):
        self.spec = types.SimpleNamespace(label="Provedor Falso")
        self.model = "modelo-falso"
        self.usage = types.SimpleNamespace(summary=lambda: "9 requisicao(oes)")
        self.calls = []
        self.contexts = []
        self.respostas = respostas

    @property
    def run_label(self):
        return "falso:modelo-falso"

    def describe(self):
        return "Motor: Provedor Falso, modelo modelo-falso, chave ****fake."

    def translate(self, text, target_language, log_message=None, cancel_flag=None, contexts=None, **_k):
        self.calls.append(text)
        self.contexts.append(contexts)
        if self.respostas is not None:
            return self.respostas(text)
        if " ||| " in text:
            return " ||| ".join(f"<{p}>" for p in text.split(" ||| "))
        return f"<{text}>"


class WorkerProviderTests(WorkerFallbackHarness, unittest.TestCase):
    """Com `provider` de modelo de linguagem, TODA chamada a API passa pelo
    provedor, a execucao grava o nome dele, e um provedor indisponivel aborta
    antes de qualquer linha (ROADMAP 28.7)."""

    def google_nunca(self, *_a, **_k):
        raise AssertionError("o Google foi chamado numa execucao com provedor de modelo")

    def execucoes(self, tmp_path):
        conn = initialize_database(str(tmp_path / "cache.db"))
        try:
            return list_translation_runs(conn.cursor())
        finally:
            conn.close()

    def test_the_provider_answers_every_call_and_signs_the_run(self):
        falso = FakeLLMTranslator()
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso) as montado:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.run_worker(tmp_path, self.google_nunca, provider="deepseek")
                stored = self.stored(tmp_path / "cache.db")
                execucoes = self.execucoes(tmp_path)

        self.assertEqual(stored, {c: f"<{c}>" for c in self.COMMENTS})
        self.assertEqual(len(falso.calls), 1, "um lote, uma chamada")
        self.assertEqual(montado.call_args.args[0], "deepseek")
        self.assertEqual(execucoes[0]["provider"], "falso:modelo-falso")
        self.assertEqual(execucoes[0]["outcome"], RUN_COMPLETED)
        self.assertIn(falso.describe(), app.logs)
        self.assertTrue(any("Provedor Falso (modelo-falso): 9 requisicao(oes)" in l for l in app.logs))

    def test_an_empty_part_from_the_model_is_resent_alone_never_saved(self):
        """O id que faltou no JSON volta vazio; o vazio e desalinhamento (B2) e
        o comentario e reenviado sozinho — nada vazio chega ao banco."""
        def respostas(text):
            if " ||| " in text:
                partes = text.split(" ||| ")
                return " ||| ".join(["<%s>" % partes[0], ""] + [f"<{p}>" for p in partes[2:]])
            return f"<{text}>"

        falso = FakeLLMTranslator(respostas)
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.run_worker(tmp_path, self.google_nunca, provider="openai")
                stored = self.stored(tmp_path / "cache.db")

        self.assertEqual(stored, {c: f"<{c}>" for c in self.COMMENTS})
        self.assertEqual(len(falso.calls), 1 + len(self.COMMENTS), "o lote e depois cada um sozinho")
        self.assertTrue(any("traduzindo individualmente" in l for l in app.logs))

    def test_a_provider_that_cannot_be_built_aborts_before_any_line(self):
        def sem_chave(*_a, **_k):
            raise LookupError("sem chave de API para ChatGPT (OpenAI)")

        with unittest.mock.patch.object(translation_worker, "build_translator", sem_chave):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.run_worker(tmp_path, self.google_nunca, provider="openai")
                stored = self.stored(tmp_path / "cache.db")
                execucoes = self.execucoes(tmp_path)

        self.assertEqual(stored, {})
        self.assertEqual(execucoes, [], "nem chegou a abrir a execucao")
        self.assertTrue(any("[ERRO] Motor 'openai' indisponivel" in l for l in app.logs))

    def test_google_is_still_the_default(self):
        with unittest.mock.patch.object(translation_worker, "build_translator") as montado:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                self.run_worker(tmp_path, lambda text, *_a, **_k: text.upper())
                stored = self.stored(tmp_path / "cache.db")
        self.assertEqual(stored, {c: c.upper() for c in self.COMMENTS})
        montado.assert_not_called()

    def test_the_cost_is_estimated_after_the_cache_and_asked_before_the_first_request(self):
        """A pergunta vem DEPOIS da carga do cache — o que ja esta no banco nao
        entra na conta — e ANTES da primeira requisicao; com tudo em cache nao
        ha pergunta (ROADMAP 28.7)."""
        perguntas = []

        def ask(*args, **_k):
            perguntas.append(args)
            return True

        falso = FakeLLMTranslator()
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.run_worker(tmp_path, self.google_nunca, ask_yes_no=ask, provider="deepseek")
                self.assertEqual(len(falso.calls), 1)
                self.assertEqual(len(perguntas), 1)
                titulo, mensagem = perguntas[0]
                self.assertEqual(titulo, "Custo estimado")
                self.assertIn("Motor: Provedor Falso, modelo modelo-falso.", mensagem)
                self.assertIn("Comentários a traduzir pelo modelo: 3,", mensagem)
                self.assertIn("sem preço na tabela para o modelo 'modelo-falso'", mensagem)
                self.assertTrue(mensagem.endswith("Iniciar a tradução?"))
                self.assertTrue(any(
                    "Estimativa para o modelo modelo-falso: 3 comentarios para a API (0 no banco)" in l
                    for l in app.logs
                ))
                self.assertTrue(any("Custo: sem preco na tabela para o modelo 'modelo-falso'" in l for l in app.logs))
                # A ordem: a estimativa depois do cache e antes de abrir a execucao.
                posicoes = [next(i for i, l in enumerate(app.logs) if marca in l)
                            for marca in ("Cache carregado", "Estimativa para o modelo", "Processando arquivo")]
                self.assertEqual(posicoes, sorted(posicoes))

                # Segunda execucao: tudo em cache, nada a enviar, nenhuma pergunta.
                app, _pgn = self.run_worker(tmp_path, self.google_nunca, ask_yes_no=ask, provider="deepseek")
                self.assertEqual(len(perguntas), 1, "com tudo em cache nao ha o que perguntar")
                self.assertEqual(len(falso.calls), 1)
                self.assertTrue(any("0 comentarios para a API (3 no banco)" in l for l in app.logs))

    def test_declining_the_estimate_sends_nothing_and_opens_no_run(self):
        falso = FakeLLMTranslator()
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, _pgn = self.run_worker(
                    tmp_path, self.google_nunca, ask_yes_no=lambda *_a, **_k: False, provider="openai"
                )
                stored = self.stored(tmp_path / "cache.db")
                execucoes = self.execucoes(tmp_path)

        self.assertEqual(falso.calls, [])
        self.assertEqual(stored, {})
        self.assertEqual(execucoes, [], "recusada antes de abrir a execucao")
        self.assertTrue(any("Traducao nao iniciada: a estimativa de custo foi recusada." in l for l in app.logs))
        self.assertFalse(app.is_processing)
        self.assertEqual(app.progress.value, 0.0)

    def test_the_google_run_never_asks_about_cost(self):
        perguntas = []

        def ask(*args, **_k):
            perguntas.append(args)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            self.run_worker(Path(tmp), lambda text, *_a, **_k: text.upper(), ask_yes_no=ask)
        self.assertEqual(perguntas, [])

    def test_a_priced_model_reports_estimated_and_real_dollars(self):
        falso = FakeLLMTranslator()
        falso.model = "claude-opus-5"
        falso.usage = llm_providers.Usage()
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                app, _pgn = self.run_worker(Path(tmp), self.google_nunca, provider="anthropic")
        self.assertTrue(any(
            l.startswith("Custo em dolares: estimado ~US$ 0,00, real US$ 0,00") for l in app.logs
        ), app.logs)


class WorkerReadingContextTests(WorkerFallbackHarness, unittest.TestCase):
    """O modelo recebe o lance anterior e o seguinte de cada comentario, no
    lote e sozinho; o Google nao recebe nada (ROADMAP 28.7)."""

    PGN = '[Event "Test"]\n\n1. e4 {First} e5 2. Nf3 {Second} Nc6 3. Bb5 {Third} *\n'
    COMMENTS = ["First", "Second", "Third"]
    ESPERADO = [("1. e4", "e5"), ("2. Nf3", "Nc6"), ("3. Bb5", "")]

    def google_nunca(self, *_a, **_k):
        raise AssertionError("o Google foi chamado numa execucao com provedor de modelo")

    def test_the_batch_carries_one_context_per_part(self):
        falso = FakeLLMTranslator()
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                self.run_worker(Path(tmp), self.google_nunca, provider="deepseek")
        self.assertEqual(falso.calls, [" ||| ".join(self.COMMENTS)])
        self.assertEqual(falso.contexts, [self.ESPERADO])

    def test_a_comment_sent_alone_carries_its_own_context(self):
        def respostas(text):
            if " ||| " in text:
                return "so uma parte"  # desalinhado: cada um sozinho
            return f"<{text}>"

        falso = FakeLLMTranslator(respostas)
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                self.run_worker(Path(tmp), self.google_nunca, provider="openai")
        self.assertEqual(falso.calls[1:], self.COMMENTS)
        self.assertEqual(falso.contexts[1:], [[c] for c in self.ESPERADO])

    def test_google_gets_no_context_and_the_first_pass_stays_cheap(self):
        with unittest.mock.patch.object(
            translation_worker, "extract_comment_texts_from_file",
            wraps=translation_worker.extract_comment_texts_from_file,
        ) as extracao:
            with tempfile.TemporaryDirectory() as tmp:
                self.run_worker(Path(tmp), lambda text, *_a, **_k: text.upper())
        self.assertFalse(extracao.call_args.kwargs.get("with_contexts"))


class WorkerAnchorGateTests(WorkerFallbackHarness, unittest.TestCase):
    """Garantia T6: com um modelo de linguagem, um lance reescrito nunca chega
    ao banco — uma segunda chance sozinho, depois falha (T2/T3)."""

    PGN = '[Event "Test"]\n\n1. e4 {Best was Nf3 here} e5 {Plain comment} *\n'
    COMMENTS = ["Best was Nf3 here", "Plain comment"]

    def google_nunca(self, *_a, **_k):
        raise AssertionError("o Google foi chamado numa execucao com provedor de modelo")

    @staticmethod
    def reescreve(part):
        return "Melhor era Cf6 aqui" if "Nf3" in part else f"<{part}>"

    def roda_com_modelo(self, respostas):
        falso = FakeLLMTranslator(respostas)
        with unittest.mock.patch.object(translation_worker, "build_translator", return_value=falso):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                app, pgn = self.run_worker(tmp_path, self.google_nunca, provider="deepseek")
                stored = self.stored(tmp_path / "cache.db")
                saida = Path(translated_output_path(str(pgn), "pt"))
                gerado = saida.read_text(encoding="utf-8") if saida.exists() else None
        return app, falso, stored, gerado

    def test_a_rewritten_move_is_resent_once_and_then_refused(self):
        def respostas(text):
            return " ||| ".join(self.reescreve(p) for p in text.split(" ||| "))

        app, falso, stored, gerado = self.roda_com_modelo(respostas)

        self.assertEqual(falso.calls, [" ||| ".join(self.COMMENTS), "Best was Nf3 here"],
                         "o lote e depois o comentario sozinho, uma vez")
        self.assertEqual(stored, {"Plain comment": "<Plain comment>"}, "nada com o lance reescrito")
        self.assertIn("{Best was Nf3 here}", gerado, "o PGN sai com o original")
        self.assertIn("{<Plain comment>}", gerado)
        self.assertTrue(any(
            "[FALHA] Lance reescrito pelo modelo nas duas tentativas (sumiu f3; apareceu f6)" in l
            for l in app.logs
        ), app.logs)
        self.assertTrue(any("Comentarios que falharam: 1" in l for l in app.logs))
        self.assertTrue(any(
            "Lances reescritos pelo modelo: 1 comentario(s) reenviado(s) sozinho(s), 1 recusado(s)" in l
            for l in app.logs
        ))

    def test_the_second_try_can_bring_the_move_back(self):
        """Um modelo nao e deterministico: o que errou no lote acerta sozinho."""
        def respostas(text):
            if " ||| " in text:
                return " ||| ".join(self.reescreve(p) for p in text.split(" ||| "))
            return "Melhor era Cf3 aqui"

        app, falso, stored, _gerado = self.roda_com_modelo(respostas)

        self.assertEqual(len(falso.calls), 2)
        self.assertEqual(stored, {"Best was Nf3 here": "Melhor era Cf3 aqui", "Plain comment": "<Plain comment>"})
        self.assertTrue(any("Comentarios que falharam: 0" in l for l in app.logs))
        self.assertTrue(any(
            "Lances reescritos pelo modelo: 1 comentario(s) reenviado(s) sozinho(s), 0 recusado(s)" in l
            for l in app.logs
        ))

    def test_the_individual_path_has_the_same_gate(self):
        """Lote desalinhado -> individual -> lance reescrito: o mesmo portao,
        a mesma segunda chance, a mesma recusa (a licao da secao 10.4)."""
        def respostas(text):
            if " ||| " in text:
                return "so uma parte"  # desalinhado: cai no individual
            return self.reescreve(text)

        app, falso, stored, gerado = self.roda_com_modelo(respostas)

        self.assertEqual(
            falso.calls,
            [" ||| ".join(self.COMMENTS), "Best was Nf3 here", "Best was Nf3 here", "Plain comment"],
        )
        self.assertEqual(stored, {"Plain comment": "<Plain comment>"})
        self.assertIn("{Best was Nf3 here}", gerado)
        self.assertTrue(any("Comentarios que falharam: 1" in l for l in app.logs))

    def test_the_gate_does_not_apply_to_google(self):
        """O Google nao inventa lance (medido: 6 em 6.500, artefatos que a prosa
        desfaz); para ele o aviso Q1 na revisao e a medida certa."""
        def translate(text, *_a, **_k):
            return " ||| ".join(self.reescreve(p) for p in text.split(" ||| "))

        with tempfile.TemporaryDirectory() as tmp:
            app, _pgn = self.run_worker(Path(tmp), translate)
            stored = self.stored(Path(tmp) / "cache.db")

        self.assertEqual(stored["Best was Nf3 here"], "Melhor era Cf6 aqui")
        self.assertTrue(any("Comentarios que falharam: 0" in l for l in app.logs))
        self.assertFalse(any("Lances reescritos pelo modelo" in l for l in app.logs))

    def test_the_resend_without_names_passes_the_gate_too(self):
        """Sentinela de nome engolido -> reenvio sem a mascara (X4) -> lance
        reescrito nesse reenvio: e a segunda chance, e nao ha terceira."""
        self.PGN = '[Event "Test"]\n\n1. e4 {Nf3 was better in G. Sax-G. Mohr, Maribor 2000.} *\n'
        self.COMMENTS = ["Nf3 was better in G. Sax-G. Mohr, Maribor 2000."]

        def respostas(text):
            if "\u27e6" in text:
                return "Cf3 era melhor em , Maribor 2000."  # sentinela do nome engolido
            return "Cf6 era melhor em G. Sax-G. Mohr, Maribor 2000."  # e agora o lance

        app, falso, stored, gerado = self.roda_com_modelo(respostas)

        self.assertEqual(len(falso.calls), 2)
        self.assertEqual(stored, {})
        self.assertIsNone(gerado, "nada traduzido, nenhum arquivo de saida")
        self.assertTrue(any(
            "Aviso: o reenvio sem a mascara de nomes reescreveu um lance (sumiu f3; apareceu f6)" in l
            for l in app.logs
        ), app.logs)
        self.assertTrue(any("[FALHA]" in l and "nomes" in l for l in app.logs))
        self.assertTrue(any("Comentarios que falharam: 1" in l for l in app.logs))
