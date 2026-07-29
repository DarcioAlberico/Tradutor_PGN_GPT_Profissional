"""Testes que abrem a JANELA PRINCIPAL de verdade e clicam nos botoes dela.

`app_actions.py` era o modulo menos coberto do projeto. Instrumentando as 25
funcoes e rodando a suite inteira, **cinco** eram alcancadas — e as outras vinte
sao justamente o caminho por onde o usuario comeca tudo: iniciar, pausar,
cancelar, reprocessar o que falhou, abrir os dois editores e as ferramentas de
banco.

O app aqui e o real (`PGNTranslatorApp`), com os botoes de verdade. Nao e
capricho: quase tudo o que estas funcoes fazem e **estado de botao**, e um botao
que fica habilitado quando nao devia so aparece na tela. Um `FakeApp` com
atributos soltos passaria por cima exatamente do que ha para verificar.

Precisam de display. Onde nao houver, as classes sao puladas.
"""

import os
import threading
import tkinter as tk
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import customtkinter as ctk

from gui_harness import GuiTestCase
from tradutor_pgn import app as app_module
from tradutor_pgn import app_actions, app_config, confirm_dialog, edit_window
from tradutor_pgn import glossary_editor
from tradutor_pgn import main_window
from tradutor_pgn.backup_retention import is_backup_of_family, prune_log_files
from tradutor_pgn.failed_runs import load_failed_run, save_failed_run


class _Relogio:
    """`datetime` falso: entrega os momentos na ordem, repetindo o ultimo."""

    def __init__(self, momentos):
        self.momentos = list(momentos)

    def now(self):
        return self.momentos.pop(0) if len(self.momentos) > 1 else self.momentos[0]


class MainWindowTestCase(GuiTestCase):
    """A janela principal de verdade, sobre o sandbox do `GuiTestCase`."""

    def setUp(self):
        super().setUp()

        # A limpeza da abertura sobe uma thread e varre `backups/` e `logs/`.
        # Aqui ela sai do caminho; tem teste proprio, que usa esta referencia.
        self.startup_cleanup = app_actions.run_startup_cleanup
        self.patch(app_actions, "run_startup_cleanup", lambda _app: None)

        self.app = app_module.PGNTranslatorApp(self.root)
        self.root.withdraw()
        self.pump()

        # O arquivo de log de uma execucao so fecha em `reset_buttons`. Um teste
        # que comece uma execucao e nao a termine deixa o handle aberto, e o
        # Windows nao apaga arquivo em uso: o sandbox ficaria para tras.
        self.addCleanup(self._fecha_log_da_execucao)

    def _fecha_log_da_execucao(self):
        handle = getattr(getattr(self, "app", None), "_log_file_handle", None)
        if handle is None:
            return
        try:
            handle.close()
        except OSError:
            pass
        self.app._log_file_handle = None

    def patch(self, modulo, nome, valor):
        """Troca um atributo de modulo e agenda a restauracao."""
        self.addCleanup(setattr, modulo, nome, getattr(modulo, nome))
        setattr(modulo, nome, valor)
        return valor

    # ---------------- helpers ----------------

    def walk(self, raiz=None):
        def desce(widget):
            yield widget
            for filho in widget.winfo_children():
                yield from desce(filho)

        return desce(raiz if raiz is not None else self.root)

    def button(self, label):
        """Botao da janela principal cujo texto e exatamente `label`."""
        rotulos = []
        for widget in self.walk():
            if isinstance(widget, ctk.CTkButton):
                texto = (widget.cget("text") or "").strip()
                rotulos.append(texto)
                if texto == label:
                    return widget
        self.fail(f"botao {label!r} nao encontrado; ha {sorted(rotulos)}")

    def toplevels(self):
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]

    def log(self):
        """O texto do log da janela, depois de drenar a fila.

        Acumula: a janela nunca limpa o log durante uma sessao. Quem quer saber
        se uma linha foi escrita **de novo** usa `log_count`.
        """
        self.app.update_log()
        return self.app.log_text.get("1.0", tk.END)

    def log_count(self, trecho):
        return self.log().count(trecho)

    def estados(self):
        return {
            "start": self.app.start_button.cget("state"),
            "pause": self.app.pause_button.cget("state"),
            "resume": self.app.resume_button.cget("state"),
            "cancel": self.app.cancel_button.cget("state"),
        }

    def worker_falso(self):
        """Substitui `run_translation`. Devolve (chamadas, evento de termino)."""
        chamadas = []
        pronto = threading.Event()

        def falso(
            app,
            source_path,
            target_language,
            process_subdirs,
            only_files=None,
            source_language="",
        ):
            chamadas.append(
                {
                    "source_path": source_path,
                    "target_language": target_language,
                    "source_language": source_language,
                    "process_subdirs": process_subdirs,
                    "only_files": only_files,
                }
            )
            pronto.set()

        self.patch(app_actions, "run_translation", falso)
        return chamadas, pronto

    def escreve_pgn(self, nome):
        caminho = self.base / nome
        caminho.write_text('[Event "T"]\n\n1. e4 {Um comentario.} *\n', encoding="utf-8")
        return str(caminho)


# ===========================================================================
# Controles de execucao
# ===========================================================================


class TranslationControlTests(MainWindowTestCase):
    """Pausar, continuar e cancelar — e os guardas de cada um."""

    def test_the_controls_do_nothing_when_nothing_is_running(self):
        """Os tres comecam com `if app.is_processing`, e por um bom motivo.

        Sem o guarda, clicar em "Cancelar" sem execucao nenhuma deixaria o
        `cancel_flag` ligado — e a proxima traducao morreria na primeira
        checagem, sem explicacao.
        """
        antes = self.estados()

        self.app.pause_translation()
        self.app.resume_translation()
        self.app.cancel_translation()

        self.assertFalse(self.app.pause_flag.is_set())
        self.assertFalse(self.app.cancel_flag.is_set())
        self.assertEqual(self.estados(), antes, "os botoes mudaram sem execucao")

    def test_pausing_and_resuming_swap_the_two_buttons(self):
        self.app.is_processing = True
        self.app.pause_button.configure(state="normal")

        self.app.pause_translation()
        self.assertTrue(self.app.pause_flag.is_set())
        self.assertEqual(self.app.pause_button.cget("state"), "disabled")
        self.assertEqual(self.app.resume_button.cget("state"), "normal")
        self.assertIn("Pausa solicitada", self.log())

        self.app.resume_translation()
        self.assertFalse(self.app.pause_flag.is_set())
        self.assertEqual(self.app.pause_button.cget("state"), "normal")
        self.assertEqual(self.app.resume_button.cget("state"), "disabled")
        self.assertIn("Continuação solicitada", self.log())

    def test_pausing_twice_is_not_a_second_pause(self):
        """`resume_button` ja esta habilitado; repetir so gastaria log."""
        self.app.is_processing = True
        self.app.pause_translation()
        self.app.pause_translation()
        self.assertEqual(self.log_count("Pausa solicitada"), 1)

    def test_resuming_a_run_that_is_not_paused_does_nothing(self):
        self.app.is_processing = True
        self.app.resume_translation()
        self.assertEqual(self.log_count("Continuação solicitada"), 0)

    def test_canceling_takes_the_run_out_of_the_pause(self):
        """Uma execucao cancelada nao pode continuar pausada.

        O `cancel_flag` sozinho nao bastaria como intencao: quem esta esperando
        na pausa precisa sair dela para chegar ate a checagem de cancelamento.
        """
        self.app.is_processing = True
        self.app.pause_translation()

        self.app.cancel_translation()

        self.assertTrue(self.app.cancel_flag.is_set())
        self.assertFalse(self.app.pause_flag.is_set(), "ficou cancelada E pausada")
        self.assertEqual(
            [self.estados()[k] for k in ("pause", "resume", "cancel")],
            ["disabled", "disabled", "disabled"],
            "sobrou botao de controle clicavel depois do cancelamento",
        )
        self.assertIn("Cancelamento solicitado", self.log())


class RunLifecycleTests(MainWindowTestCase):
    """O preparo e o encerramento comuns as duas formas de iniciar."""

    def test_beginning_a_run_clears_the_flags_and_arms_the_buttons(self):
        self.app.pause_flag.set()
        self.app.cancel_flag.set()

        app_actions._begin_translation_run(self.app)

        self.assertTrue(self.app.is_processing)
        self.assertFalse(self.app.pause_flag.is_set(), "comecou querendo pausar")
        self.assertFalse(self.app.cancel_flag.is_set(), "comecou querendo parar")
        self.assertEqual(
            self.estados(),
            {"start": "disabled", "pause": "normal", "resume": "disabled", "cancel": "normal"},
        )

    def test_the_run_log_is_named_so_the_retention_can_find_it(self):
        """ROADMAP 1.4: o modo de falha mais chato possivel.

        Se o formato do nome divergir do que `prune_log_files` procura, a
        retencao de `logs/` vira um no-op **silencioso** — nada quebra, nada
        avisa, e a pasta cresce para sempre. Por isso aqui o produtor de verdade
        e conferido contra o consumidor de verdade, e nao contra uma copia do
        padrao escrita no teste.
        """
        agora = datetime(2026, 7, 27, 14, 30, 12)
        self.patch(app_actions, "datetime", _Relogio([agora - timedelta(days=1), agora]))

        app_actions._begin_translation_run(self.app)
        antigo = Path(self.app._log_file_path)
        app_actions.reset_buttons(self.app)

        app_actions._begin_translation_run(self.app)
        novo = Path(self.app._log_file_path)
        app_actions.reset_buttons(self.app)

        self.assertNotEqual(antigo.name, novo.name)
        self.assertTrue(antigo.exists() and novo.exists())
        for arquivo in (antigo, novo):
            self.assertTrue(
                is_backup_of_family(arquivo.name, "traducao-", ".log"),
                f"{arquivo.name!r} nao casa com o padrao da retencao de logs",
            )

        removidos = prune_log_files(str(antigo.parent), keep_count=1)

        self.assertEqual([Path(p).name for p in removidos], [antigo.name])
        self.assertTrue(novo.exists(), "a retencao levou o log mais novo")

    def test_resetting_the_buttons_closes_the_log_and_says_where_it_is(self):
        app_actions._begin_translation_run(self.app)
        caminho = self.app._log_file_path

        app_actions.reset_buttons(self.app)

        self.assertIsNone(self.app._log_file_handle, "o arquivo de log ficou aberto")
        self.assertEqual(
            self.estados(),
            {"start": "normal", "pause": "disabled", "resume": "disabled", "cancel": "disabled"},
        )
        self.assertIn(caminho, self.log())

    def test_resetting_twice_does_not_announce_the_log_again(self):
        """Sem o `handle = None`, cada reset repetiria a linha do log."""
        app_actions._begin_translation_run(self.app)
        app_actions.reset_buttons(self.app)
        app_actions.reset_buttons(self.app)

        self.assertEqual(self.log_count("Log salvo em"), 1)


class StartTranslationTests(MainWindowTestCase):
    """O botao "Iniciar Tradução": guardas e o que chega ao worker."""

    def test_starting_without_a_path_complains_and_starts_nothing(self):
        chamadas, _pronto = self.worker_falso()

        self.click_start()

        self.assertEqual(chamadas, [])
        self.assertFalse(self.app.is_processing)
        self.assertIn("Erro", self.dialogs.titles("error"))

    def test_starting_with_a_path_that_does_not_exist_complains(self):
        chamadas, _pronto = self.worker_falso()
        self.app.source_path.set(str(self.base / "nao-existe.pgn"))

        self.click_start()

        self.assertEqual(chamadas, [])
        self.assertIn(
            "O caminho informado não existe.", self.dialogs.messages("error")
        )

    def test_starting_hands_the_worker_what_the_window_shows(self):
        chamadas, pronto = self.worker_falso()
        pgn = self.escreve_pgn("partida.pgn")
        self.app.source_path.set(pgn)
        self.app.target_language.set("es")
        # Nao e o padrao de proposito: com "detectar" selecionado, um worker que
        # ignorasse o seletor de origem seria indistinguivel de um que o le.
        self.app.source_language.set("it")
        self.app.process_subdirs.set(False)

        self.click_start()
        self.assertTrue(pronto.wait(10), "o worker nao foi chamado")

        self.assertEqual(
            chamadas,
            [{
                "source_path": pgn,
                "target_language": "es",
                "source_language": "it",
                "process_subdirs": False,
                "only_files": None,
            }],
        )
        self.assertEqual(self.app.start_button.cget("state"), "disabled")

    def test_starting_while_a_translation_runs_does_nothing(self):
        chamadas, _pronto = self.worker_falso()
        self.app.source_path.set(self.escreve_pgn("partida.pgn"))
        self.app.is_processing = True

        self.click_start()

        self.assertEqual(chamadas, [], "duas execucoes ao mesmo tempo")

    def click_start(self):
        self.button("Iniciar Tradução").invoke()
        self.pump()


class RetryFailedTranslationTests(MainWindowTestCase):
    """O dialogo do item 7.3: reprocessar so o que ficou devendo."""

    def registra(self, arquivos, idioma="en", falhas=3, origem="de"):
        save_failed_run(
            {
                "target_language": idioma,
                "source_language": origem,
                "files": [str(a) for a in arquivos],
                "failed_count": falhas,
                "when": "2026-07-27T14:00:00",
            }
        )

    def clicar(self):
        self.button("Reprocessar Falhas").invoke()
        self.pump()

    def test_without_a_record_it_says_there_is_nothing_to_redo(self):
        chamadas, _pronto = self.worker_falso()

        self.clicar()

        self.assertEqual(chamadas, [])
        self.assertIn("Reprocessar falhas", self.dialogs.titles("info"))

    def test_it_uses_the_language_of_the_failed_run_and_not_the_selector(self):
        """A lista foi montada traduzindo aquele PAR de idiomas.

        Reaproveita-la com outro selecionado produziria um arquivo misturado sem
        que ninguem tivesse pedido — e, desde que a origem entrou na chave do
        banco, as traducoes que faltam iriam parar numa gaveta diferente da dos
        comentarios que ja deram certo.
        """
        chamadas, pronto = self.worker_falso()
        pgn = self.escreve_pgn("faltou.pgn")
        self.registra([pgn], idioma="fr", origem="ru")
        self.app.target_language.set("pt")
        self.app.source_language.set("en")

        self.clicar()
        self.assertTrue(pronto.wait(10), "o worker nao foi chamado")

        self.assertEqual(chamadas[0]["target_language"], "fr")
        self.assertEqual(chamadas[0]["source_language"], "ru")
        self.assertEqual(chamadas[0]["only_files"], [pgn])
        self.assertEqual(
            self.app.target_language.get(), "fr", "o seletor nao acompanhou"
        )
        self.assertEqual(
            self.app.source_language.get(),
            "ru",
            "o seletor de origem nao acompanhou",
        )
        self.assertIn("Idioma ajustado", self.log())
        self.assertIn("Idioma de origem ajustado", self.log())

    def test_files_that_vanished_are_dropped_and_the_rest_still_runs(self):
        chamadas, pronto = self.worker_falso()
        existe = self.escreve_pgn("existe.pgn")
        sumiu = str(self.base / "sumiu.pgn")
        self.registra([existe, sumiu])

        self.clicar()
        self.assertTrue(pronto.wait(10))

        self.assertEqual(chamadas[0]["only_files"], [existe])
        self.assertIn(
            "1 arquivo(s) da lista nao estao mais no disco",
            "\n".join(self.dialogs.messages("askyesno")),
        )

    def test_when_every_file_vanished_it_offers_to_drop_the_list(self):
        chamadas, _pronto = self.worker_falso()
        self.registra([str(self.base / "sumiu.pgn")])

        self.clicar()

        self.assertEqual(chamadas, [], "reprocessou uma lista sem arquivo nenhum")
        self.assertIn(
            "Nenhum arquivo da lista existe mais.",
            "\n".join(self.dialogs.messages("askyesno")),
        )
        self.assertIsNone(load_failed_run(), "a lista obsoleta continuou la")

    def test_refusing_the_confirmation_starts_nothing(self):
        chamadas, _pronto = self.worker_falso()
        self.dialogs.askyesno_result = False
        self.registra([self.escreve_pgn("faltou.pgn")])

        self.clicar()

        self.assertEqual(chamadas, [])
        self.assertIsNotNone(load_failed_run(), "recusar apagou a lista")

    def test_it_does_nothing_while_a_translation_runs(self):
        chamadas, _pronto = self.worker_falso()
        self.registra([self.escreve_pgn("faltou.pgn")])
        self.app.is_processing = True

        self.clicar()

        self.assertEqual(chamadas, [])


# ===========================================================================
# Ferramentas e janelas
# ===========================================================================


class ToolButtonTests(MainWindowTestCase):
    """Os botoes de "Ferramentas" chamam a operacao certa, com o argumento certo."""

    ALIASES = {
        "Estatísticas do BD": "show_database_stats",
        "Exportar CSV": "export_translations_csv",
        "Importar CSV": "import_translations_csv",
        "Backup BD": "backup_database_file",
        "Restaurar BD": "restore_database_file",
    }

    def test_each_tool_button_reaches_its_own_operation(self):
        """Sao delegacoes de uma linha, e e por isso que trocam de lugar facil.

        Um "Backup BD" ligado a restauracao continua compilando, continua
        abrindo dialogo, e destroi o banco do usuario.
        """
        recebidos = {}
        for rotulo, alias in self.ALIASES.items():
            self.patch(
                app_actions,
                alias,
                lambda app, _a=alias: recebidos.setdefault(_a, app),
            )

        for rotulo in self.ALIASES:
            self.button(rotulo).invoke()
            self.pump()

        self.assertEqual(sorted(recebidos), sorted(self.ALIASES.values()))
        for alias, recebido in recebidos.items():
            self.assertIs(recebido, self.app, f"{alias} recebeu outro app")

    def test_applying_automatic_rules_passes_the_selected_language(self):
        """Sem o idioma, a operacao varreria o banco inteiro — todos os idiomas."""
        recebidos = []
        self.patch(
            app_actions,
            "apply_auto_rules_to_database",
            lambda app, target_language=None: recebidos.append(target_language),
        )
        self.app.target_language.set("de")

        self.button("Aplicar Automaticas").invoke()
        self.pump()

        self.assertEqual(recebidos, ["de"])

    def test_the_two_editor_buttons_open_the_two_editors(self):
        abertos = []
        self.patch(
            app_actions, "open_translation_editor", lambda app: abertos.append("traducoes")
        )
        self.patch(
            app_actions, "open_glossary_editor", lambda app: abertos.append("glossario")
        )

        self.button("Editar Traduções").invoke()
        self.button("Editar Glossário").invoke()
        self.pump()

        self.assertEqual(abertos, ["traducoes", "glossario"])

    def test_the_edit_button_really_opens_a_window(self):
        """Sem isto, os dois testes acima passariam com a abertura quebrada."""
        antes = len(self.toplevels())

        self.button("Editar Traduções").invoke()
        self.pump()

        depois = self.toplevels()
        self.assertEqual(len(depois), antes + 1, "nenhuma janela abriu")
        self.addCleanup(depois[-1].destroy)


class FileSelectionTests(MainWindowTestCase):
    """"Arquivo" e "Pasta": preenchem o campo, e cancelar nao apaga o que havia."""

    def test_choosing_a_file_fills_the_path(self):
        escolhido = self.escreve_pgn("escolhido.pgn")
        self.file_dialogs.answer = escolhido

        self.button("Arquivo").invoke()

        self.assertEqual(self.app.source_path.get(), escolhido)

    def test_choosing_a_directory_fills_the_path(self):
        self.file_dialogs.answer = str(self.base)

        self.button("Pasta").invoke()

        self.assertEqual(self.app.source_path.get(), str(self.base))

    def test_canceling_the_dialog_keeps_what_was_there(self):
        self.app.source_path.set("caminho anterior")
        self.file_dialogs.answer = ""     # cancelado

        self.button("Arquivo").invoke()
        self.button("Pasta").invoke()

        self.assertEqual(self.app.source_path.get(), "caminho anterior")


class NormalizePgnTests(MainWindowTestCase):
    """"Normalizar PGN": os guardas e o desfecho."""

    def test_it_refuses_without_a_usable_path(self):
        self.button("Normalizar PGN").invoke()
        self.assertFalse(self.app.is_processing)

        self.app.source_path.set(str(self.base / "nao-existe.pgn"))
        self.button("Normalizar PGN").invoke()
        self.assertFalse(self.app.is_processing)
        self.assertEqual(len(self.dialogs.titles("error")), 2)

    def test_refusing_the_confirmation_starts_nothing(self):
        self.dialogs.askyesno_result = False
        self.app.source_path.set(self.escreve_pgn("partida.pgn"))

        self.button("Normalizar PGN").invoke()

        self.assertFalse(self.app.is_processing)

    def em_andamento(self):
        """O estado em que `normalize_pgn_metadata` deixa a janela.

        Sem desabilitar os botoes aqui, afirmar que o fim os "libera" nao prova
        nada: eles ja estariam habilitados, e remover o `reset_buttons` da
        producao passaria despercebido. Foi o que a conferencia por mutacao
        acusou na primeira versao destes dois testes.
        """
        self.app.is_processing = True
        for botao in (
            self.app.start_button,
            self.app.pause_button,
            self.app.resume_button,
            self.app.cancel_button,
        ):
            botao.configure(state="disabled")

    def test_finishing_reports_the_summary_and_frees_the_buttons(self):
        self.em_andamento()
        resumo = {
            "files": 3,
            "changed_files": 2,
            "unchanged_files": 1,
            "changes": 7,
            "skipped_normalized": 1,
        }

        app_actions._finish_metadata_normalization(self.app, summary=resumo)

        self.assertFalse(self.app.is_processing)
        self.assertEqual(self.app.start_button.cget("state"), "normal")
        self.assertIn("Normalizar PGN", self.dialogs.titles("info"))
        registro = self.log()
        self.assertIn("2 arquivo(s) alterado(s)", registro)
        self.assertIn("Arquivos -NORM.pgn ignorados: 1", registro)

    def test_a_failure_frees_the_buttons_too(self):
        """Senao o programa fica preso em "processando" ate ser reaberto."""
        self.em_andamento()

        app_actions._finish_metadata_normalization(self.app, error=OSError("disco cheio"))

        self.assertFalse(self.app.is_processing)
        self.assertEqual(self.app.start_button.cget("state"), "normal")
        self.assertIn("Normalizar PGN", self.dialogs.titles("error"))
        self.assertIn("disco cheio", self.log())


class StartupCleanupTests(MainWindowTestCase):
    """A retencao da abertura (garantia S8) — fora da thread da interface."""

    def esperar_log(self, trecho, timeout=5.0):
        limite = threading.Event()
        fim = timeout
        passo = 0.05
        while fim > 0:
            if trecho in self.log():
                return True
            limite.wait(passo)
            fim -= passo
        return False

    def test_it_reports_what_it_removed_without_touching_the_ui(self):
        removidos = {"glossario": ["a.txt", "b.txt"], "banco": ["c.db"], "logs": []}
        self.patch(app_actions, "prune_generated_files", lambda _base: removidos)

        self.startup_cleanup(self.app)

        self.assertTrue(
            self.esperar_log("Limpeza automatica"),
            "a limpeza nao reportou nada no log da janela",
        )
        registro = self.log()
        self.assertIn("2 backup(s) do glossario", registro)
        self.assertIn("1 do banco", registro)

    def test_it_stays_quiet_when_there_is_nothing_to_remove(self):
        self.patch(
            app_actions,
            "prune_generated_files",
            lambda _base: {"glossario": [], "banco": [], "logs": []},
        )

        self.startup_cleanup(self.app)

        self.assertFalse(self.esperar_log("Limpeza automatica", timeout=1.0))

    def test_a_failing_cleanup_never_stops_the_program(self):
        """A limpeza e conveniencia, nao funcionalidade.

        Ela roda na abertura: uma excecao que suba daqui e um programa que nao
        abre — e, sob `pythonw`, um programa que nao abre sem dizer por que.
        """
        def explode(_base):
            raise OSError("pasta somiu")

        self.patch(app_actions, "prune_generated_files", explode)

        self.startup_cleanup(self.app)

        self.assertTrue(self.esperar_log("[LIMPEZA] Falhou"))
        self.assertTrue(self.app.root.winfo_exists(), "a janela morreu")


class CreditsFooterTests(MainWindowTestCase):
    """Os creditos no rodape da janela principal.

    Um rotulo que **parece** um link mas nao abre nada e pior do que texto
    simples: ele promete uma acao e nao entrega, e a falha e silenciosa. Por isso
    o teste central aqui e o clique, e nao o texto.
    """

    def labels(self):
        return [
            (w.cget("text") or "")
            for w in self.walk()
            if isinstance(w, ctk.CTkLabel)
        ]

    def test_the_window_credits_the_authors_and_the_repository(self):
        textos = " | ".join(self.labels())

        self.assertIn(app_config.APP_AUTHORS, textos)
        self.assertIn(app_config.APP_REPOSITORY_URL, textos)

    def test_clicking_the_link_opens_the_repository(self):
        """O que separa um link de um texto azul.

        O clique e gerado no `Label` **interno**, e nao no `CTkLabel`. Um
        `CTkLabel` e um frame com um canvas e um label dentro, e `CTkLabel.bind`
        instala o handler nesses dois filhos — que sao os que ficam debaixo do
        ponteiro do usuario. Gerar o evento no frame externo nao dispara nada, e
        a primeira versao deste teste falhou por isso: ela media o proprio
        engano, e nao o link.
        """
        abertos = []
        self.patch(main_window.webbrowser, "open", abertos.append)

        # `event_generate` so entrega para widget **mapeado**, e o `setUp` deixa
        # a janela em `withdraw()`. Sem isto o evento e descartado em silencio e
        # o teste afirma que o link nao funciona — o que ele nao sabe distinguir
        # de um link realmente quebrado.
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)
        self.pump()

        sob_o_ponteiro = [
            filho
            for filho in self.app.repository_link.winfo_children()
            if isinstance(filho, tk.Label)
        ]
        self.assertTrue(sob_o_ponteiro, "o CTkLabel nao tem label interno")

        sob_o_ponteiro[0].event_generate("<Button-1>")
        self.pump()

        self.assertEqual(abertos, [app_config.APP_REPOSITORY_URL])

    def test_the_link_says_it_is_clickable(self):
        """O cursor e a unica pista de que aquilo responde ao clique."""
        self.assertEqual(self.app.repository_link.cget("cursor"), "hand2")

    def test_the_footer_actually_reaches_the_screen(self):
        """O defeito que estes testes pegaram de verdade.

        A primeira versao empacotava o rodape **depois** do log, que leva
        `expand=True`. O packer do Tk entrega a cavidade restante ao log, e o
        rodape fica com altura zero: existe como widget, responde a `cget`, e
        nao aparece na tela — sem erro nenhum.

        Afirmar que o rotulo existe nao pega isso, e foi por isso que o teste do
        clique falhou primeiro: `event_generate` so entrega para widget mapeado.
        Aqui a exigencia fica explicita, em vez de depender desse efeito.
        """
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)
        self.pump()

        link = self.app.repository_link
        self.assertTrue(link.winfo_ismapped(), "o rodape nao chegou a tela")
        self.assertGreater(link.winfo_height(), 1, "o rodape ficou com altura zero")

    def test_the_footer_is_below_the_log(self):
        """Rodape e uma posicao, e nao so um conjunto de rotulos.

        A ordem do `pack` resolve a visibilidade e o `side=BOTTOM` resolve o
        lugar — sao coisas diferentes, e uma mutacao mostrou isso: tirando so o
        `side`, o rodape continua visivel e sobe para cima do log, o que os
        outros testes desta classe aceitam sem reclamar.
        """
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)
        self.pump()

        self.assertGreater(
            self.app.repository_link.winfo_rooty(),
            self.app.log_text.winfo_rooty(),
            "o rodape ficou acima do log",
        )


class ResetButtonTests(MainWindowTestCase):
    """Os dois botoes que apagam trabalho do usuario.

    Sao as unicas acoes da janela sem volta pelo proprio programa — o que existe
    e o backup —, entao o que se exige aqui e o roteamento e a recusa em rodar
    durante uma traducao. O que cada uma faz com o disco esta em
    `ResetTranslationsTests` e `ResetGlossaryTests`.
    """

    def test_each_reset_button_reaches_its_own_operation(self):
        """Trocados de lugar, os dois continuam abrindo dialogo e apagam a
        coisa errada — e a errada aqui e o trabalho de meses do usuario."""
        recebidos = []
        self.patch(
            app_actions,
            "reset_translations_database",
            lambda app: recebidos.append(("traducoes", app)),
        )
        self.patch(
            app_actions,
            "reset_glossary_file",
            lambda app: recebidos.append(("glossario", app)),
        )

        self.button("Zerar Traduções").invoke()
        self.button("Zerar Glossário").invoke()
        self.pump()

        self.assertEqual([nome for nome, _app in recebidos], ["traducoes", "glossario"])
        for _nome, app in recebidos:
            self.assertIs(app, self.app)

    def test_neither_runs_during_a_translation(self):
        """Zerar o banco no meio de uma execucao daria o pior dos dois mundos:
        o worker continua gravando no que acabou de ser apagado."""
        chamadas = []
        self.patch(
            app_actions, "reset_translations_database", lambda app: chamadas.append("t")
        )
        self.patch(app_actions, "reset_glossary_file", lambda app: chamadas.append("g"))
        self.app.is_processing = True

        self.button("Zerar Traduções").invoke()
        self.button("Zerar Glossário").invoke()
        self.pump()

        self.assertEqual(chamadas, [])
        self.assertEqual(len(self.dialogs.messages("info")), 2)

    def test_they_are_visibly_destructive(self):
        """A confirmacao digitada e a defesa; a cor e o aviso.

        Sem ela os dois ficam indistinguiveis de "Backup BD" na mesma grade, a
        um clique apressado de distancia.
        """
        for rotulo in ("Zerar Traduções", "Zerar Glossário"):
            with self.subTest(rotulo=rotulo):
                self.assertEqual(
                    self.button(rotulo).cget("fg_color"),
                    main_window.DESTRUCTIVE_COLOR,
                )
        self.assertNotEqual(
            self.button("Backup BD").cget("fg_color"), main_window.DESTRUCTIVE_COLOR
        )


class SourceLanguageSelectorTests(MainWindowTestCase):
    """O seletor de idioma de origem da janela principal."""

    def test_it_starts_on_automatic_detection(self):
        """O padrao e o que o programa sempre fez (`sl=auto`): quem nao mexer no
        seletor continua exatamente onde estava."""
        self.assertEqual(self.app.source_language.get(), "")

    def test_it_offers_detect_plus_every_language(self):
        rotulos = [b.cget("text") for b in self.app.source_language_buttons]
        self.assertEqual(
            rotulos,
            [app_config.AUTO_SOURCE_LABEL] + [nome for nome, _c in app_config.LANGUAGES],
        )

    def test_clicking_a_language_sets_the_variable(self):
        por_rotulo = {
            b.cget("text"): b for b in self.app.source_language_buttons
        }
        por_rotulo["Espanhol"].invoke()
        self.pump()

        self.assertEqual(self.app.source_language.get(), "es")

    def test_source_and_target_are_independent(self):
        """Sao dois seletores, e um `variable` trocado ligaria os dois sem erro
        visivel — o programa so passaria a traduzir de e para o mesmo idioma."""
        por_rotulo = {b.cget("text"): b for b in self.app.source_language_buttons}
        por_rotulo["Alemão"].invoke()
        self.app.target_language.set("pt")
        self.pump()

        self.assertEqual(self.app.source_language.get(), "de")
        self.assertEqual(self.app.target_language.get(), "pt")

class TypedConfirmationDialogTests(MainWindowTestCase):
    """O dialogo de confirmacao digitada, aberto de verdade.

    A regra que ele aplica ja tem teste puro. O que so aparece com a janela na
    tela e o outro lado dela: o botao "Apagar" precisa ficar visivelmente
    inerte ate a palavra ser digitada.
    """

    def abrir(self, roteiro):
        """Abre o dialogo e roda `roteiro(janela)` de dentro dele.

        `ask_typed_confirmation` e sincrono (`wait_window`), entao a resposta
        precisa ser agendada ANTES — como um usuario, que so age depois de a
        janela estar na tela.
        """
        resultado = {}

        def agir():
            janela = [
                w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
            ][-1]
            try:
                roteiro(janela)
            finally:
                janela.destroy()

        self.root.after(50, agir)
        resultado["ok"] = confirm_dialog.ask_typed_confirmation(
            self.root, "Zerar", "mensagem"
        )
        return resultado["ok"]

    def campo(self, janela):
        for widget in self.walk(janela):
            if isinstance(widget, ctk.CTkEntry):
                return widget
        self.fail("o dialogo nao tem campo de texto")

    def botao(self, janela, rotulo):
        for widget in self.walk(janela):
            if isinstance(widget, ctk.CTkButton):
                if (widget.cget("text") or "").strip() == rotulo:
                    return widget
        self.fail(f"botao {rotulo!r} nao encontrado no dialogo")

    def test_the_delete_button_starts_inert(self):
        estados = {}

        def roteiro(janela):
            botao = self.botao(janela, "Apagar")
            estados["state"] = botao.cget("state")
            estados["cor"] = botao.cget("fg_color")

        self.abrir(roteiro)

        self.assertEqual(estados["state"], "disabled")
        self.assertEqual(estados["cor"], confirm_dialog.CONFIRM_DISABLED_COLOR)

    def test_typing_the_word_arms_it_and_the_colour_says_so(self):
        """O `state` sozinho nao basta, e foi a janela de verdade que mostrou.

        Sobre um vermelho saturado o escurecimento que o CustomTkinter aplica a
        um botao desabilitado e quase imperceptivel: as duas capturas ficaram
        indistinguiveis. Um botao que parece clicavel e nao faz nada le-se como
        "o programa quebrou", e nao como "falta digitar a palavra".
        """
        estados = {}

        def roteiro(janela):
            campo = self.campo(janela)
            botao = self.botao(janela, "Apagar")
            campo.insert(0, confirm_dialog.CONFIRMATION_WORD)
            self.pump()
            estados["state"] = botao.cget("state")
            estados["cor"] = botao.cget("fg_color")

        self.abrir(roteiro)

        self.assertEqual(estados["state"], "normal")
        self.assertEqual(estados["cor"], confirm_dialog.CONFIRM_ENABLED_COLOR)

    def test_a_wrong_word_leaves_it_inert(self):
        estados = {}

        def roteiro(janela):
            self.campo(janela).insert(0, "apagar")
            self.pump()
            estados["state"] = self.botao(janela, "Apagar").cget("state")

        self.abrir(roteiro)

        self.assertEqual(estados["state"], "disabled")

    def test_confirming_answers_yes_and_cancelling_answers_no(self):
        def digitar_e_confirmar(janela):
            self.campo(janela).insert(0, confirm_dialog.CONFIRMATION_WORD)
            self.pump()
            self.botao(janela, "Apagar").invoke()

        def cancelar(janela):
            self.campo(janela).insert(0, confirm_dialog.CONFIRMATION_WORD)
            self.pump()
            self.botao(janela, "Cancelar").invoke()

        self.assertTrue(self.abrir(digitar_e_confirmar))
        self.assertFalse(self.abrir(cancelar))

    def test_closing_the_window_is_a_no(self):
        """Sumir com o dialogo nunca pode significar seguir adiante.

        **Fechar precisa ser o fechar de verdade**, e a primeira versao deste
        teste nao era: ela chamava `destroy()`, que NAO dispara o
        `WM_DELETE_WINDOW` — so o gerenciador de janelas dispara. O dialogo
        entao devolvia o `False` que ja era o padrao, e trocar o handler por um
        que respondesse "sim" continuava passando. Aqui o script registrado no
        protocolo e executado como o X da janela o executaria.
        """
        def fechar_como_o_gerenciador(janela):
            self.campo(janela).insert(0, confirm_dialog.CONFIRMATION_WORD)
            self.pump()
            janela.tk.eval(janela.protocol("WM_DELETE_WINDOW"))

        self.assertFalse(self.abrir(fechar_como_o_gerenciador))

    def test_escape_is_a_no_too(self):
        def apertar_escape(janela):
            self.campo(janela).insert(0, confirm_dialog.CONFIRMATION_WORD)
            self.pump()
            janela.focus_force()
            janela.event_generate("<Escape>")
            self.pump()

        self.assertFalse(self.abrir(apertar_escape))

    def test_the_button_refuses_even_when_invoked_directly(self):
        """O `command` confere de novo, e nao confia no estado do botao.

        O `trace` que habilita e um efeito colateral da digitacao; um caminho
        que o desligue nao pode virar uma confirmacao que ninguem digitou.
        """
        def roteiro(janela):
            botao = self.botao(janela, "Apagar")
            botao.configure(state="normal")
            botao.invoke()

        self.assertFalse(self.abrir(roteiro))

if __name__ == "__main__":
    unittest.main()
