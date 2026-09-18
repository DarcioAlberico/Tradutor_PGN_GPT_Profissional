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
import time
import tkinter as tk
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import customtkinter as ctk

import gui_harness
from gui_harness import GuiTestCase
from tradutor_pgn import app as app_module
from tradutor_pgn import db_tools
from tradutor_pgn.background_task import BackgroundTask, TaskCanceled
from tradutor_pgn.database import (
    QualityReevaluationCanceled,
    get_quality_heuristics_version,
    initialize_database,
    save_translation,
)
from tradutor_pgn.review_quality import QUALITY_HEURISTICS_VERSION
from tradutor_pgn import api_keys, app_actions, app_config, app_paths, confirm_dialog, settings
from tradutor_pgn import llm_providers, provider_dialog
from tradutor_pgn import glossary_editor, settings_window
from tradutor_pgn.editor_common import DESTRUCTIVE_COLOR
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

        # A conferencia dos avisos QA da abertura sai do caminho pelo mesmo
        # motivo, e por um a mais: ela agenda com `after`, entao dispararia no
        # meio de qualquer `pump()` de qualquer teste. Tem classe propria, que usa
        # esta referencia.
        self.startup_quality_check = app_actions.run_startup_quality_check
        self.patch(app_actions, "run_startup_quality_check", lambda _app: None)

        # Sem chave de modelo de linguagem, por padrao: o "Iniciar tradução"
        # abre um dialogo MODAL quando ha uma (ROADMAP 28.7), e a maquina de
        # quem desenvolve pode ter `ANTHROPIC_API_KEY` no ambiente — a suite
        # pararia num `wait_window`. Quem quer o dialogo o pede (ProviderDialogTests).
        self.patch(app_actions, "configured_providers", lambda: [])

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
            provider="google",
        ):
            chamadas.append(
                {
                    "source_path": source_path,
                    "target_language": target_language,
                    "source_language": source_language,
                    "process_subdirs": process_subdirs,
                    "only_files": only_files,
                    "provider": provider,
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
                # Sem chave configurada, o motor e o Google e ninguem pergunta.
                "provider": "google",
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
        """A palavra errada e "apagando", e nao "apagar".

        Era "apagar" ate 2026-08-01, quando essa passou a ser a palavra CERTA
        (ROADMAP 22.12) — o dialogo e todo em portugues e o botao dele se chama
        "Apagar". A palavra escolhida agora e uma que ninguem digitaria por
        engano e que nao e nem a nova nem a antiga.
        """
        estados = {}

        def roteiro(janela):
            self.campo(janela).insert(0, "apagando")
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

class RememberedChoicesTests(MainWindowTestCase):
    """A janela reabre no que a sessao anterior escolheu.

    O idioma de ORIGEM e a razao de isto existir: ele decide o `sl=` da API e
    liga a correcao das letras dos lances, e o padrao dele — "Detectar" — e
    justamente o valor que deixa as duas desligadas. Uma execucao feita no
    escuro nao denuncia nada: o resultado parece pronto.
    """

    def reabrir(self):
        """Fecha a janela atual e abre outra sobre o mesmo sandbox."""
        self._fecha_log_da_execucao()
        self.app.root.update()
        for widget in list(self.root.winfo_children()):
            widget.destroy()
        self.app = app_module.PGNTranslatorApp(self.root)
        self.root.withdraw()
        self.pump()
        return self.app

    def test_the_source_language_survives_a_restart(self):
        self.app.source_language.set("en")
        self.pump()

        self.assertEqual(self.reabrir().source_language.get(), "en")

    def test_every_choice_survives_together(self):
        self.app.source_language.set("es")
        self.app.target_language.set("fr")
        self.app.process_subdirs.set(False)
        self.app.source_path.set(str(self.base / "partidas"))
        self.pump()

        novo = self.reabrir()

        self.assertEqual(novo.source_language.get(), "es")
        self.assertEqual(novo.target_language.get(), "fr")
        self.assertFalse(novo.process_subdirs.get())
        self.assertEqual(novo.source_path.get(), str(self.base / "partidas"))

    def test_detect_is_remembered_as_a_choice(self):
        """Voltar para "Detectar" e uma decisao, e nao a ausencia de uma.

        Guardada so a escolha "nao vazia", quem tivesse marcado ingles uma vez
        nunca mais conseguiria voltar ao padrao pelo seletor.
        """
        self.app.source_language.set("en")
        self.pump()
        self.reabrir()

        self.app.source_language.set("")
        self.pump()

        self.assertEqual(self.reabrir().source_language.get(), "")

    def test_a_file_edited_from_outside_wins_on_reopening(self):
        """A janela le o disco na abertura, e nao um estado seu de antes.

        O arquivo de configuracoes e JSON e o usuario pode edita-lo — ou outra
        instancia do programa pode te-lo mudado. O que abre depois obedece ao
        que esta la.
        """
        self.app.source_language.set("en")
        self.pump()

        settings.save_settings(
            dict(
                settings.load_settings(),
                **{settings.MAIN_WINDOW_KEY: {"source_language": "es"}},
            )
        )
        novo = self.reabrir()

        self.assertEqual(novo.source_language.get(), "es")

    def test_the_editor_drafts_are_not_lost(self):
        """Garantia R4: os rascunhos vivem no mesmo arquivo."""
        settings.update_settings(
            lambda disco: disco.__setitem__(
                "editor_drafts", {"chave": {"text": "rascunho vivo"}}
            )
        )

        self.app.source_language.set("de")
        self.pump()

        self.assertEqual(
            settings.load_settings()["editor_drafts"],
            {"chave": {"text": "rascunho vivo"}},
        )


# ===========================================================================
# Secao 17 — nenhuma escrita em massa roda durante uma traducao
# ===========================================================================


class HarnessTeardownTests(GuiTestCase):
    """A desmontagem da suite nao pode quebrar por causa de um `after` pendente.

    `tkinter.after_cancel` le o script do `after` com `splitlist(...)[0]` para
    apagar o comando antes de cancelar. Quando o script e uma LISTA Tcl de
    varias palavras — alguem agendou com argumentos —, esse `[0]` e uma tupla e
    o `deletecommand` levanta `TypeError` **antes** de o timer ser cancelado.
    Um `except tk.TclError` nao pega isso: a suite completa ganhava um erro de
    desmontagem numa classe que nao tinha nada a ver com o assunto, e o timer
    ficava vivo.
    """

    def test_an_after_with_a_list_script_is_cancelled_and_does_not_raise(self):
        self.root.tk.eval('after 60000 [list puts "a b"]')
        self.assertTrue(self.root.tk.eval("after info").split())

        gui_harness.cancel_pending_after(self.root)

        self.assertEqual(self.root.tk.eval("after info").split(), [])

    def test_the_ordinary_after_is_cancelled_too(self):
        self.root.after(60000, lambda: None)

        gui_harness.cancel_pending_after(self.root)

        self.assertEqual(self.root.tk.eval("after info").split(), [])


class LastRunEntryPointTests(MainWindowTestCase):
    """A porta de entrada do dia (ROADMAP 28.10): "Revisar pendentes" e "Abrir pasta".

    Traduzir e revisar sao o mesmo fluxo, e o segundo passo exigia abrir o
    editor, achar o arquivo no seletor e trocar o status. Os dois botoes vivem
    sob a barra de progresso, nascem desabilitados e acordam quando uma
    execucao grava posicoes.
    """

    def com_execucao(self, arquivos=("C:/obras/cap01.pgn",), gerados=None, idioma="pt"):
        self.app.last_run = {
            "files": [os.path.abspath(a) for a in arquivos],
            "generated": [os.path.abspath(g) for g in (gerados or ())],
            "target_language": idioma,
            "completed": True,
        }
        app_actions.refresh_last_run_buttons(self.app)
        self.pump()

    def test_both_buttons_start_disabled(self):
        self.assertEqual(self.app.review_run_button.cget("state"), "disabled")
        self.assertEqual(self.app.open_folder_button.cget("state"), "disabled")

    def test_a_run_wakes_them_up(self):
        self.com_execucao()
        self.assertEqual(self.app.review_run_button.cget("state"), "normal")
        self.assertEqual(self.app.open_folder_button.cget("state"), "normal")

    def test_resetting_the_buttons_keeps_them_in_sync(self):
        """`reset_buttons` roda no fim de toda execucao: e o momento certo."""
        self.app.last_run = None
        app_actions.reset_buttons(self.app)
        self.pump()
        self.assertEqual(self.app.review_run_button.cget("state"), "disabled")

        self.app.last_run = {"files": ["x"], "generated": [], "target_language": "pt"}
        app_actions.reset_buttons(self.app)
        self.pump()
        self.assertEqual(self.app.review_run_button.cget("state"), "normal")

    def test_reviewing_opens_the_editor_on_the_file_pending_and_the_run_target(self):
        chamadas = []
        self.patch(
            app_actions, "open_translation_editor",
            lambda app, **kwargs: chamadas.append(kwargs),
        )
        # O radio mudou depois da execucao: o que vale e o destino DA EXECUCAO.
        self.app.target_language.set("it")
        self.com_execucao(idioma="pt")

        self.button("Revisar pendentes").invoke()
        self.pump()

        self.assertEqual(chamadas, [{
            "source_file": os.path.abspath("C:/obras/cap01.pgn"),
            "status_filter": "Pendentes",
            "target_language": "pt",
        }])

    def test_with_several_files_it_opens_the_first_and_says_so(self):
        chamadas = []
        self.patch(
            app_actions, "open_translation_editor",
            lambda app, **kwargs: chamadas.append(kwargs),
        )
        self.com_execucao(arquivos=("C:/obras/cap01.pgn", "C:/obras/cap02.pgn"))

        self.button("Revisar pendentes").invoke()
        self.pump()

        self.assertEqual(chamadas[0]["source_file"], os.path.abspath("C:/obras/cap01.pgn"))
        texto = self.log()
        self.assertIn("cap01.pgn", texto)
        self.assertIn("1 arquivo(s)", texto)

    def test_reviewing_without_a_run_explains_instead_of_opening(self):
        chamadas = []
        self.patch(
            app_actions, "open_translation_editor",
            lambda app, **kwargs: chamadas.append(kwargs),
        )
        self.app.last_run = None

        self.assertIsNone(app_actions.review_last_run(self.app))
        self.assertEqual(chamadas, [])
        self.assertEqual(len(self.dialogs.messages("info")), 1)

    def test_opening_the_folder_prefers_the_generated_file(self):
        abertas = []
        self.patch(app_actions, "open_path_in_explorer", abertas.append)
        self.com_execucao(
            arquivos=("C:/obras/cap01.pgn",), gerados=("C:/saida/cap01-BR.pgn",)
        )

        self.button("Abrir pasta").invoke()
        self.pump()

        self.assertEqual(abertas, [os.path.dirname(os.path.abspath("C:/saida/cap01-BR.pgn"))])

    def test_without_a_generated_file_it_opens_the_source_folder(self):
        abertas = []
        self.patch(app_actions, "open_path_in_explorer", abertas.append)
        self.com_execucao(arquivos=("C:/obras/cap01.pgn",))

        self.button("Abrir pasta").invoke()
        self.pump()

        self.assertEqual(abertas, [os.path.dirname(os.path.abspath("C:/obras/cap01.pgn"))])

    def test_a_folder_that_will_not_open_says_so(self):
        def falhar(_path):
            raise OSError("pasta sumiu")

        self.patch(app_actions, "open_path_in_explorer", falhar)
        self.com_execucao()

        self.assertIsNone(app_actions.open_last_run_folder(self.app))
        self.assertEqual(len(self.dialogs.messages("error")), 1)
        self.assertIn("pasta sumiu", self.dialogs.messages("error")[0])

    def test_the_progress_label_starts_empty_beside_the_run_buttons(self):
        self.assertEqual(self.app.progress_label.cget("text"), "")
        self.assertEqual(self.app.progress_label.winfo_manager(), "pack")
        self.assertIs(self.app.progress_label.master, self.app.retry_button.master)

    def test_the_new_controls_cost_the_log_no_height(self):
        """A familia "correto e nao cabe na tela" (22.10), medida onde doi.

        A janela principal nao tem folga vertical: o log e o ultimo a receber
        espaco, e uma fileira propria para estes controles o derrubava de 33 px
        para 1 px. Eles moram na fileira dos botoes, que ja existia — entao o
        fim do log continua alcancavel, que e o que F23 protege.
        """
        for numero in range(80):
            self.app.log_message(f"linha {numero}")
        app_actions.update_log(self.app)
        self.pump()
        self.app.log_text.see(tk.END)
        self.pump()

        self.assertGreater(self.app.log_text.winfo_height(), 24)
        self.assertTrue(app_actions.log_is_at_the_end(self.app.log_text))

    def test_at_the_minimum_width_the_run_controls_do_not_push_cancel_out(self):
        """`pack` nao desenha o que sobra: quem tem de sumir e o atalho, nunca o
        "Cancelar"."""
        self.app.root.geometry(f"{app_module.MAIN_MIN_WIDTH}x{app_module.MAIN_MIN_HEIGHT}")
        self.pump()
        self.pump()
        fileira = self.app.retry_button.master
        for botao in (
            self.app.start_button,
            self.app.pause_button,
            self.app.resume_button,
            self.app.cancel_button,
        ):
            fim = botao.winfo_x() + botao.winfo_width()
            self.assertLessEqual(
                fim, fileira.winfo_width(),
                f"{botao.cget('text')} termina em {fim} numa fileira de {fileira.winfo_width()}",
            )


class MassWriteGuardTests(MainWindowTestCase):
    """Garantia T5 (ROADMAP 17.2 e 17.3).

    Tres das seis ferramentas de escrita verificavam `is_processing` e recusavam
    com dialogo; **Restaurar BD, Importar CSV e Aplicar Automaticas nao
    verificavam nada**. Restaurar um backup enquanto o worker grava produz um
    banco que nao e nem o backup nem a execucao, com o cache em memoria
    apontando para linhas que ja nao existem.

    Agravante que faz a mensagem ser parte da correcao: os botoes de
    "Ferramentas" sao criados anonimos e nao ha como desabilita-los. O clique
    acontece — e sem dialogo ele nao faz nada e nao diz nada.
    """

    # Rotulo -> alias em `app_actions` que a acao delega.
    FERRAMENTAS = {
        "Restaurar BD": "restore_database_file",
        "Importar CSV": "import_translations_csv",
        "Aplicar Automaticas": "apply_auto_rules_to_database",
        "Corrigir Lances": "fix_move_notation_in_database",
        "Consertar Prosa": "normalize_prose_in_database",
        "Zerar Traduções": "reset_translations_database",
        "Zerar Glossário": "reset_glossary_file",
        # Fora da grade, na fileira dos botoes de execucao (Z5, ROADMAP 28.6).
        "Reverter execução": "revert_last_run_in_database",
    }

    def espiar(self):
        chamadas = []
        for alias in self.FERRAMENTAS.values():
            self.patch(
                app_actions,
                alias,
                lambda *_a, _nome=alias, **_k: chamadas.append(_nome),
            )
        return chamadas

    def test_none_of_them_runs_during_a_translation(self):
        chamadas = self.espiar()
        self.app.is_processing = True

        for rotulo in self.FERRAMENTAS:
            self.button(rotulo).invoke()
            self.pump()

        self.assertEqual(chamadas, [], "alguma ferramenta rodou durante a traducao")

    def test_each_one_says_why_instead_of_swallowing_the_click(self):
        self.espiar()
        self.app.is_processing = True

        for rotulo in self.FERRAMENTAS:
            with self.subTest(rotulo=rotulo):
                self.dialogs.calls.clear()
                self.button(rotulo).invoke()
                self.pump()
                mensagens = self.dialogs.messages("info")
                self.assertEqual(len(mensagens), 1, f"{rotulo} nao disse nada")
                self.assertIn("tradução em andamento", mensagens[0])

    def test_all_of_them_run_when_nothing_is_running(self):
        """Contraprova: a guarda nao pode ter trancado a ferramenta de vez."""
        chamadas = self.espiar()
        self.app.is_processing = False

        for rotulo in self.FERRAMENTAS:
            self.button(rotulo).invoke()
            self.pump()

        self.assertEqual(sorted(chamadas), sorted(self.FERRAMENTAS.values()))

    def test_a_backup_is_still_allowed(self):
        """`Backup BD` fica de fora de proposito: ele so LE o banco, e a copia
        sai consistente mesmo com o worker escrevendo (a API de backup do SQLite
        ve o banco logico). Recusar aqui negaria a copia justamente a quem quer
        guardar o estado de uma execucao longa."""
        chamadas = []
        self.patch(
            app_actions, "backup_database_file", lambda app: chamadas.append("backup")
        )
        self.app.is_processing = True

        self.button("Backup BD").invoke()
        self.pump()

        self.assertEqual(chamadas, ["backup"])


class SilentButtonTests(MainWindowTestCase):
    """Os dois botoes que engoliam o clique (ROADMAP 17.3).

    "Reprocessar Falhas" e "Normalizar PGN" comecavam com `if
    app.is_processing: return` — retorno mudo. Clicar durante uma traducao nao
    fazia nada e nao dizia nada, enquanto "Corrigir Lances", no mesmo caso, abria
    um dialogo explicando.
    """

    def test_reprocessing_says_why_it_refuses(self):
        chamadas, _pronto = self.worker_falso()
        self.app.is_processing = True

        self.button("Reprocessar Falhas").invoke()
        self.pump()

        self.assertEqual(chamadas, [])
        self.assertEqual(len(self.dialogs.messages("info")), 1)
        self.assertIn("tradução em andamento", self.dialogs.messages("info")[0])

    def test_normalizing_says_why_it_refuses(self):
        chamadas = []
        self.patch(
            app_actions,
            "normalize_pgn_metadata_path",
            lambda *a, **k: chamadas.append(a),
        )
        self.app.source_path.set(self.escreve_pgn("entrada.pgn"))
        self.app.is_processing = True

        self.button("Normalizar PGN").invoke()
        self.pump()

        self.assertEqual(chamadas, [])
        self.assertEqual(len(self.dialogs.messages("info")), 1)
        self.assertIn("tradução em andamento", self.dialogs.messages("info")[0])

    def test_the_retry_button_is_disabled_with_the_others(self):
        """As duas comecam uma traducao; deixar so uma apagada dizia que a outra
        estava disponivel."""
        self.assertEqual(self.app.retry_button.cget("state"), "normal")

        app_actions._begin_translation_run(self.app)
        self.pump()

        self.assertEqual(self.app.start_button.cget("state"), "disabled")
        self.assertEqual(self.app.retry_button.cget("state"), "disabled")

    def test_the_retry_button_comes_back_with_the_others(self):
        app_actions._begin_translation_run(self.app)
        self.pump()

        app_actions.reset_buttons(self.app)
        self.pump()

        self.assertEqual(self.app.retry_button.cget("state"), "normal")

    def test_the_normalizer_also_disables_it(self):
        """O normalizador poe `is_processing` de pe sem passar por
        `_begin_translation_run`, e por isso tem a sua propria lista de botoes."""
        self.patch(
            app_actions, "normalize_pgn_metadata_path", lambda *a, **k: {}
        )
        self.app.source_path.set(self.escreve_pgn("entrada.pgn"))

        # A thread do normalizador nao e iniciada: o que interessa e o estado
        # que o clique deixa antes dela.
        self.patch(app_actions.threading, "Thread", lambda **_k: types.SimpleNamespace(
            start=lambda: None
        ))

        self.button("Normalizar PGN").invoke()
        self.pump()

        self.assertEqual(self.app.retry_button.cget("state"), "disabled")


class NormalizerPartialFailureDialogTests(MainWindowTestCase):
    """Um arquivo ilegivel nao interrompe mais o lote — e o resultado diz isso.

    Um "concluida" liso sobre um lote com falhas seria pior do que o erro que a
    correcao tirou do caminho (ROADMAP 17.10).
    """

    def resumo(self, falhas):
        return {
            "files": 3,
            "changed_files": 2,
            "unchanged_files": 0,
            "changes": 4,
            "skipped_normalized": 0,
            "outputs": [],
            "failed": falhas,
        }

    def test_a_run_with_failures_warns_and_counts_them(self):
        app_actions._finish_metadata_normalization(
            self.app,
            summary=self.resumo([{"file": "b.pgn", "error": "permissao negada"}]),
        )
        self.pump()

        avisos = self.dialogs.messages("warning")
        self.assertEqual(len(avisos), 1)
        self.assertIn("Falharam: 1", avisos[0])
        self.assertEqual(self.dialogs.messages("info"), [])

    def test_the_reason_goes_to_the_log(self):
        app_actions._finish_metadata_normalization(
            self.app,
            summary=self.resumo([{"file": "b.pgn", "error": "permissao negada"}]),
        )
        self.pump()

        self.assertIn("permissao negada", self.log())

    def test_a_clean_run_still_reports_success(self):
        app_actions._finish_metadata_normalization(self.app, summary=self.resumo([]))
        self.pump()

        infos = self.dialogs.messages("info")
        self.assertEqual(len(infos), 1)
        self.assertIn("Normalizacao concluida", infos[0])
        self.assertNotIn("Falharam", infos[0])
        self.assertEqual(self.dialogs.messages("warning"), [])


# ===========================================================================
# Secao 16 — a versao das heuristicas e a reavaliacao (garantia Q2)
# ===========================================================================


class QualityReevaluationToolTests(MainWindowTestCase):
    """O botao "Reavaliar QA" e a conferencia da abertura."""

    def setUp(self):
        super().setUp()
        # As tarefas de fundo rodam na hora: o que esta sob teste e a
        # orquestracao, e a thread tem teste proprio em test_background_task.
        self.patch(db_tools, "run_with_progress", self._rodar_sincrono)

    def _rodar_sincrono(self, _parent, _titulo, work, on_success=None, on_cancel=None, **_kw):
        try:
            resultado = work(BackgroundTask())
        except TaskCanceled:
            if on_cancel is not None:
                on_cancel(None)
            return
        if on_success is not None:
            on_success(resultado)

    def com_linhas(self, *pares):
        """Grava traducoes no banco do sandbox e devolve a conexao fechada."""
        conn = initialize_database(self.app.output_db)
        cur = conn.cursor()
        for original, traduzida in pares:
            save_translation(cur, original, traduzida, "pt", "en")
        conn.commit()
        conn.close()

    def versao(self):
        conn = initialize_database(self.app.output_db)
        try:
            return get_quality_heuristics_version(conn)
        finally:
            conn.close()

    def esperar(self, condicao, limite=5.0):
        """Bombeia o Tk ate a condicao valer, ou desiste.

        `run_startup_quality_check` agenda com `after`, entao o efeito dela nao
        acontece dentro do `pump()` que vem logo depois — o callback so dispara
        quando o atraso passa. Chamar a funcao interna direto testaria outra
        coisa: o agendamento e parte do que este item decidiu (a janela aparece
        primeiro).
        """
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            self.root.update()
            if condicao():
                return True
            time.sleep(0.02)
        return condicao()

    def avisos_marcados(self):
        conn = initialize_database(self.app.output_db)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM comments WHERE quality_warning = 1"
            ).fetchone()[0]
        finally:
            conn.close()

    # -------------------------------------------------------------- o botao

    def test_the_button_reaches_the_operation(self):
        chamadas = []
        self.patch(
            app_actions,
            "reevaluate_quality_in_database",
            lambda app: chamadas.append(app),
        )

        self.button("Reavaliar QA").invoke()
        self.pump()

        self.assertEqual(chamadas, [self.app])

    def test_it_does_not_run_during_a_translation(self):
        """Garantia T5: e uma escrita em massa como as outras."""
        chamadas = []
        self.patch(
            app_actions,
            "reevaluate_quality_in_database",
            lambda app: chamadas.append(app),
        )
        self.app.is_processing = True

        self.button("Reavaliar QA").invoke()
        self.pump()

        self.assertEqual(chamadas, [])
        self.assertEqual(len(self.dialogs.messages("info")), 1)
        self.assertIn("tradução em andamento", self.dialogs.messages("info")[0])

    def test_a_stale_database_is_reevaluated_and_stamped(self):
        self.com_linhas(("The open file.", "O arquivo aberto."))
        conn = initialize_database(self.app.output_db)
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()
        conn.close()

        self.button("Reavaliar QA").invoke()
        self.pump()

        self.assertEqual(self.avisos_marcados(), 1)
        self.assertEqual(self.versao(), QUALITY_HEURISTICS_VERSION)
        self.assertIn("Avisos QA reavaliados", self.log())

    def test_asking_again_says_it_is_already_current(self):
        self.com_linhas(("The open file.", "O arquivo aberto."))
        self.button("Reavaliar QA").invoke()
        self.pump()
        self.dialogs.calls.clear()

        self.button("Reavaliar QA").invoke()
        self.pump()

        mensagens = self.dialogs.messages("info")
        self.assertEqual(len(mensagens), 1)
        self.assertIn("ja estao na versao atual", mensagens[0])

    def test_cancelling_leaves_the_old_mark(self):
        """A ordem e o item: gravar a versao depois de um cancelamento diria que
        o banco esta em dia com um veredito que metade das linhas nao recebeu — e
        ninguem descobriria, porque a coluna nao acusa que esta velha."""
        self.com_linhas(("The open file.", "O arquivo aberto."))

        def cancelar(_parent, _titulo, work, on_cancel=None, **_kw):
            task = BackgroundTask()
            task.cancel()
            try:
                work(task)
            except (TaskCanceled, QualityReevaluationCanceled):
                if on_cancel is not None:
                    on_cancel(None)

        self.patch(db_tools, "run_with_progress", cancelar)

        self.button("Reavaliar QA").invoke()
        self.pump()

        self.assertEqual(self.versao(), 0, "cancelar nao pode marcar como em dia")

    # ----------------------------------------------------- a abertura

    def test_the_startup_check_stamps_an_empty_database_without_a_dialog(self):
        """O caminho mais comum de todos — banco novo. Sem este atalho, toda
        primeira abertura abriria uma janela de progresso modal para varrer zero
        linha."""
        abertas = []
        self.patch(
            db_tools,
            "run_with_progress",
            lambda *a, **k: abertas.append(a[1]),
        )

        self.startup_quality_check(self.app)

        self.assertTrue(
            self.esperar(lambda: self.versao() == QUALITY_HEURISTICS_VERSION),
            "a abertura devia ter gravado a versao",
        )
        self.assertEqual(abertas, [], "nao devia abrir progresso nenhum")
        self.assertEqual(self.dialogs.calls, [])

    def test_the_startup_check_reevaluates_a_stale_database(self):
        self.com_linhas(("The open file.", "O arquivo aberto."))
        conn = initialize_database(self.app.output_db)
        conn.execute("UPDATE comments SET quality_warning = 0")
        conn.commit()
        conn.close()

        self.startup_quality_check(self.app)

        self.assertTrue(
            self.esperar(lambda: self.versao() == QUALITY_HEURISTICS_VERSION),
            "a abertura devia ter reavaliado",
        )
        self.assertEqual(self.avisos_marcados(), 1)

    def test_the_startup_check_is_silent_when_already_current(self):
        """Um aviso por sessao dizendo que nada aconteceu seria pior do que
        nenhum aviso."""
        self.com_linhas(("The open file.", "O arquivo aberto."))
        self.startup_quality_check(self.app)
        self.esperar(lambda: self.versao() == QUALITY_HEURISTICS_VERSION)
        self.dialogs.calls.clear()

        self.startup_quality_check(self.app)
        self.esperar(lambda: False, limite=0.6)

        self.assertEqual(self.dialogs.calls, [])


class ClosingTheMainWindowTests(MainWindowTestCase):
    """Garantia F22: o X da janela principal tem handler (ROADMAP 22.12).

    Nao havia nenhum. O X e o botao mais perto do cursor de quem acha que
    terminou, e ele matava o processo inteiro — com a traducao em andamento no
    meio de um PGN, e com as janelas filhas sem passar pelos fechamentos delas.
    """

    def setUp(self):
        super().setUp()
        # Fechar de verdade destruiria a raiz que o `GuiTestCase` gerencia e o
        # `tearDown` cairia. O que interessa aqui e a DECISAO — fechar, cancelar
        # ou nao fazer nada —, e ela e observavel sem executar o `destroy`.
        self.destruida = []
        self.app.root.destroy = lambda: self.destruida.append(True)

    def test_the_x_is_wired(self):
        self.assertTrue(self.app.root.protocol("WM_DELETE_WINDOW"))

    def test_with_nothing_running_it_just_closes(self):
        self.assertTrue(self.app.close_main_window())
        self.assertEqual(len(self.destruida), 1)
        self.assertEqual(self.dialogs.calls, [])

    def test_a_running_translation_is_not_killed_without_asking(self):
        self.app.is_processing = True
        self.dialogs.askyesno_result = False

        self.assertFalse(self.app.close_main_window())

        self.assertEqual(self.destruida, [])
        self.assertFalse(self.app.cancel_flag.is_set())
        self.assertTrue(self.dialogs.messages("askyesno"), "nao perguntou nada")

    def test_saying_yes_cancels_instead_of_closing(self):
        """Fechar depois de pedir o cancelamento mataria a thread do mesmo jeito.

        O worker precisa de tempo para fechar o arquivo que esta escrevendo, e a
        lista de falhas (T4) so e gravada quando ele chega ao fim.
        """
        self.app.is_processing = True
        self.dialogs.askyesno_result = True

        self.assertFalse(self.app.close_main_window())

        self.assertTrue(self.app.cancel_flag.is_set())
        self.assertEqual(self.destruida, [])

    def test_the_children_close_through_their_own_handler(self):
        """E o `close_editor` que grava a edicao aberta e a posicao da janela."""
        chamou = []
        filha = tk.Toplevel(self.app.root)
        filha.protocol("WM_DELETE_WINDOW", lambda: chamou.append(True))
        self.addCleanup(filha.destroy)
        self.pump()

        self.app.close_main_window()

        self.assertEqual(chamou, [True])

    def test_a_child_that_explodes_does_not_trap_the_program(self):
        """O X ja foi clicado: travar ali deixaria a janela sem saida.

        O relator de callbacks e substituido porque a excecao de um fechamento
        de filha NAO volta pelo `tk.call` — o Tk a entrega ao relator, que a
        transforma em dialogo (garantia C3). Sem esta troca, este teste abre um
        `messagebox` de verdade e a suite inteira para esperando um clique: o
        relator monta o dialogo com o `messagebox` do `tkinter`, e nao com o do
        modulo, entao o silenciador do harness nao o alcanca.
        """
        relatados = []
        self.addCleanup(
            setattr,
            self.app.root,
            "report_callback_exception",
            self.app.root.report_callback_exception,
        )
        self.app.root.report_callback_exception = lambda *args: relatados.append(args)

        filha = tk.Toplevel(self.app.root)

        def explode():
            raise RuntimeError("fechamento com defeito")

        filha.protocol("WM_DELETE_WINDOW", explode)
        self.addCleanup(filha.destroy)
        self.pump()

        self.assertTrue(self.app.close_main_window())
        self.assertEqual(len(self.destruida), 1)
        # E o erro nao some: ele vira log e dialogo pelo caminho de sempre.
        self.assertEqual(len(relatados), 1, relatados)

    def test_the_size_and_position_are_remembered(self):
        """Era a unica janela do programa que nunca lembrava onde estava.

        A afirmacao e "o que foi gravado e a geometria DESTA janela", e nao um
        `1000x700` escrito no teste: a raiz da suite esta retirada da tela, e uma
        janela retirada nao aceita mudanca de tamanho — o teste estaria medindo
        essa limitacao, e nao a gravacao.
        """
        self.app.root.geometry("+30+40")
        self.pump()
        esperada = self.app.root.geometry()

        self.app.close_main_window()

        guardado = settings.load_settings().get(settings.MAIN_WINDOW_KEY, {})
        self.assertEqual(guardado.get("geometry"), esperada)
        self.assertRegex(esperada, r"^\d+x\d+[+-]-?\d+[+-]-?\d+$")

    def test_a_saved_geometry_is_restored_on_the_next_opening(self):
        """A ancora do teste acima: gravar sem ler de volta nao serve de nada."""
        settings.write_main_window_settings({"geometry": "1010x710+22+33"})

        outro = app_module.PGNTranslatorApp(tk.Toplevel(self.root))
        self.addCleanup(outro.root.destroy)
        self.pump()

        self.assertTrue(outro.root.geometry().startswith("1010x710"), outro.root.geometry())


class LogDoesNotYankTheReaderBackTests(MainWindowTestCase):
    """Garantia F23: o log so rola sozinho se o fim ja estava visivel (22.12).

    O `see(END)` era incondicional: reler um `[AVISO]` durante uma execucao era
    ser puxado de volta a cada tick de 100 ms.
    """

    def encher(self, quantas):
        for numero in range(quantas):
            self.app.log_message(f"linha {numero}")
        app_actions.update_log(self.app)
        self.pump()

    def test_following_the_end_keeps_following(self):
        self.encher(80)
        # Levado ao fim de proposito: a janela abre com varias mensagens de
        # inicializacao ja no log, entao "recem-aberta" nao e o mesmo que "no fim".
        self.app.log_text.see(tk.END)
        self.pump()
        self.assertTrue(app_actions.log_is_at_the_end(self.app.log_text))

        self.app.log_message("recem-chegada")
        app_actions.update_log(self.app)
        self.pump()

        self.assertIn("recem-chegada", self.app.log_text.get("end-3l", "end"))
        self.assertTrue(app_actions.log_is_at_the_end(self.app.log_text))

    def test_reading_the_middle_is_not_interrupted(self):
        """A afirmacao e "nao pulou para o fim", e nao "a fracao ficou igual".

        Ela muda por definicao: uma linha nova cresce o total, e a mesma posicao
        em pixels vira outra fracao. Exigir igualdade seria exigir que o log
        parasse de crescer.
        """
        self.encher(200)
        self.app.log_text.yview_moveto(0.1)
        self.pump()
        antes = self.app.log_text.yview()[0]

        self.app.log_message("chegou enquanto se lia o meio")
        app_actions.update_log(self.app)
        self.pump()

        self.assertFalse(app_actions.log_is_at_the_end(self.app.log_text))
        self.assertAlmostEqual(self.app.log_text.yview()[0], antes, places=2)


class RevertRunButtonTests(MainWindowTestCase):
    """"Reverter execucao" (Z5): vermelho como os "Zerar", na fileira dos botoes
    de execucao ao lado de "Revisar pendentes", e sempre habilitado — a ultima
    execucao pode ser de outra sessao."""

    def test_it_is_red_in_the_run_row_and_enabled(self):
        botao = self.button("Reverter execução")
        self.assertEqual(botao.cget("fg_color"), DESTRUCTIVE_COLOR)
        self.assertIs(botao.master, self.app.review_run_button.master)
        self.assertEqual(botao.cget("state"), "normal")

    def test_it_calls_the_tool_with_the_app(self):
        recebidos = []
        self.patch(app_actions, "revert_last_run_in_database", recebidos.append)
        self.button("Reverter execução").invoke()
        self.assertEqual(recebidos, [self.app])


class SettingsWindowTests(MainWindowTestCase):
    """A tela de Configuracoes (garantia M4, ROADMAP 28.10).

    `utf8_bom` e `wrap_columns` so existiam no JSON editado a mao. A tela da um
    controle a cada opcao do usuario e grava pela mesma porta das outras
    janelas (R4) — e um teste enumera as chaves contra os controles, para uma
    opcao nova nao nascer sem lugar na tela.
    """

    def setUp(self):
        super().setUp()
        # O tema e estado de CLASSE do CustomTkinter: um teste que o troque de
        # verdade deixaria a suite inteira escura. Volta ao que o lancador poe.
        self.addCleanup(ctk.set_appearance_mode, "System")
        self.aplicados = []
        self.patch(settings_window, "apply_appearance", self.aplicados.append)

    def grava(self, **secoes):
        settings.save_settings(secoes, settings.default_settings_path())

    def arquivo(self):
        return settings.load_settings(settings.default_settings_path())

    def abre(self):
        janela = self.app.open_settings_window()
        self.pump()
        self.addCleanup(self.fecha, janela)
        return janela

    def fecha(self, janela):
        try:
            janela.win.destroy()
        except tk.TclError:
            pass

    def test_the_button_opens_the_window(self):
        antes = len(self.toplevels())
        self.button("Configurações").invoke()
        self.pump()
        novas = self.toplevels()[antes:]
        self.assertEqual(len(novas), 1)
        self.assertEqual(novas[0].title(), "Configurações")
        novas[0].destroy()

    def test_every_user_option_has_a_control(self):
        """Garantia M4: as chaves de `USER_OPTION_SECTIONS` contra a tela."""
        janela = self.abre()
        esperadas = {
            (secao, chave)
            for secao, padroes in settings.USER_OPTION_SECTIONS.items()
            for chave in padroes
        }
        self.assertEqual(set(janela.controls), esperadas)
        for widget in janela.controls.values():
            self.assertTrue(widget.winfo_exists())

    def test_it_opens_with_what_the_file_says(self):
        self.grava(output={"utf8_bom": True, "wrap_columns": 80}, appearance={"theme": "dark"})
        janela = self.abre()
        self.assertTrue(janela.bom_var.get())
        self.assertEqual(janela.wrap_var.get(), "80")
        self.assertEqual(janela.theme_var.get(), "Escuro")

    def test_it_opens_with_the_defaults_when_there_is_no_file(self):
        janela = self.abre()
        self.assertFalse(janela.bom_var.get())
        self.assertEqual(janela.wrap_var.get(), "0")
        self.assertEqual(janela.theme_var.get(), "Sistema")

    def test_saving_writes_through_update_settings_and_keeps_a_draft(self):
        """R4 pela tela: um rascunho gravado por OUTRA janela enquanto esta
        estava aberta sobrevive ao Salvar."""
        janela = self.abre()
        janela.bom_var.set(True)
        janela.wrap_var.set("80")

        # O editor grava um rascunho depois de a tela ter lido o arquivo.
        def rascunho(dados):
            settings.set_editor_draft(dados, self.db_path, "pt", 7, "texto", "base")

        settings.update_settings(rascunho, settings.default_settings_path())

        self.assertTrue(janela.save())
        self.pump()

        gravado = self.arquivo()
        self.assertEqual(
            settings.read_output_settings(gravado), {"utf8_bom": True, "wrap_columns": 80}
        )
        rascunho_gravado = settings.get_editor_draft(gravado, self.db_path, "pt", 7, "base")
        self.assertEqual(
            (rascunho_gravado or {}).get("text"),
            "texto",
            "o rascunho gravado pelo editor sumiu no Salvar da tela",
        )
        self.assertIn("salvas", janela.status_label.cget("text"))

    def test_an_invalid_width_is_refused_on_screen_and_nothing_is_written(self):
        self.grava(output={"utf8_bom": False, "wrap_columns": 80})
        janela = self.abre()
        for digitado in ("abc", "10", "-5", "1.5"):
            with self.subTest(digitado=digitado):
                janela.wrap_var.set(digitado)
                self.assertFalse(janela.save())
                self.pump()
                self.assertTrue(janela.status_label.cget("text"), "a razao devia estar na tela")
                self.assertEqual(self.dialogs.messages("error"), [], "sem dialogo: o campo esta ali")
                self.assertEqual(
                    settings.read_output_settings(self.arquivo())["wrap_columns"],
                    80,
                    "gravou um valor recusado",
                )

    def test_empty_width_means_off(self):
        self.grava(output={"utf8_bom": False, "wrap_columns": 80})
        janela = self.abre()
        janela.wrap_var.set("")
        self.assertTrue(janela.save())
        self.assertEqual(settings.read_output_settings(self.arquivo())["wrap_columns"], 0)

    def test_the_theme_is_applied_only_when_it_changes_and_after_writing(self):
        janela = self.abre()
        self.assertTrue(janela.save())
        self.assertEqual(self.aplicados, [], "salvar sem mudar o tema nao devia repintar")

        janela.theme_var.set("Escuro")
        self.assertTrue(janela.save())
        self.assertEqual(self.aplicados, ["dark"])
        self.assertEqual(settings.read_appearance_settings(self.arquivo())["theme"], "dark")

        # Salvar de novo com o mesmo tema: nada a aplicar.
        self.assertTrue(janela.save())
        self.assertEqual(self.aplicados, ["dark"])

    def test_a_failed_write_does_not_apply_the_theme(self):
        janela = self.abre()
        janela.theme_var.set("Claro")

        def falha(*_a, **_k):
            raise OSError("disco cheio")

        self.patch(settings_window, "write_settings_sections", falha)

        self.assertFalse(janela.save())
        self.assertEqual(self.aplicados, [], "aplicou um tema que o arquivo nao tem")
        self.assertIn("continuam como estavam", janela.status_label.cget("text"))

    def test_the_saved_theme_is_applied_when_the_program_opens(self):
        """A escolha vale na proxima abertura, sem passar pela tela de novo."""
        self.grava(appearance={"theme": "dark"})
        modos = []
        self.patch(app_module.ctk, "set_appearance_mode", modos.append)
        outra = app_module.PGNTranslatorApp(tk.Toplevel(self.root))
        self.addCleanup(outra.root.destroy)
        self.assertEqual(modos, ["Dark"])

    def test_the_window_fits_its_minimum_size(self):
        """Familia "correto e nao cabe na tela" (22.10): o requerido contra o
        minimo, medido, e nao a olho."""
        janela = self.abre()
        janela.win.withdraw()
        janela.win.update_idletasks()
        largura, altura = janela.MIN_SIZE
        self.assertLessEqual(janela.win.winfo_reqwidth(), largura)
        self.assertLessEqual(janela.win.winfo_reqheight(), altura)

    def test_a_typed_key_is_stored_encrypted_and_leaves_the_field(self):
        """K1 pela tela: a chave digitada vai para `chaves-api.json`, nunca
        para o `settings.json`, e o campo volta a dizer so o estado."""
        janela = self.abre()
        janela.key_entries["deepseek"].insert(0, " ds-chave-9876 ")
        janela.model_vars["deepseek"].set("deepseek-reasoner")
        self.assertTrue(janela.save())
        self.pump()

        self.assertEqual(api_keys.load_api_key("deepseek"), "ds-chave-9876")
        self.assertNotIn("ds-chave-9876", Path(settings.default_settings_path()).read_text(encoding="utf-8"))
        self.assertEqual(settings.read_llm_settings(self.arquivo())["deepseek_model"], "deepseek-reasoner")
        self.assertEqual(janela.key_entries["deepseek"].get(), "")
        self.assertIn("****9876", janela.key_entries["deepseek"].cget("placeholder_text"))
        self.assertNotIn("ds-chave-9876", janela.key_entries["deepseek"].cget("placeholder_text"))

    def test_the_clear_box_removes_a_stored_key_and_an_empty_model_means_default(self):
        api_keys.save_api_key("openai", "sk-abcd-1111")
        janela = self.abre()
        self.assertIn("****1111", janela.key_entries["openai"].cget("placeholder_text"))
        janela.clear_key_vars["openai"].set(True)
        janela.model_vars["openai"].set("   ")
        self.assertTrue(janela.save())
        self.assertIsNone(api_keys.load_api_key("openai"))
        self.assertEqual(
            settings.read_llm_settings(self.arquivo())["openai_model"], settings.LLM_DEFAULTS["openai_model"]
        )
        # Sem tocar em nada, salvar de novo nao apaga nem grava chave.
        api_keys.save_api_key("anthropic", "sk-ant-2222")
        janela = self.abre()
        self.assertTrue(janela.save())
        self.assertEqual(api_keys.load_api_key("anthropic"), "sk-ant-2222")

    def test_the_data_folder_is_shown_and_can_be_opened(self):
        janela = self.abre()
        self.assertIn(str(self.base), janela.data_dir_label.cget("text"))
        abertas = []
        self.patch(app_actions, "open_path_in_explorer", abertas.append)
        janela.btn_open_data_dir.invoke()
        self.assertEqual(abertas, [app_paths.data_dir()])

    def test_the_glossary_pane_follows_the_theme_and_lets_go_on_close(self):
        """O `PanedWindow` do glossario e Tk puro e lia o tema uma vez; agora o
        tema troca de dentro do programa, e ele precisa acompanhar."""
        editor = glossary_editor.open_glossary_editor(self.app)
        self.pump()
        self.addCleanup(lambda: editor.win.winfo_exists() and editor.win.destroy())

        ctk.set_appearance_mode("Dark")
        self.pump()
        self.assertEqual(editor.main_pane.cget("bg"), "#2b2b2b")
        ctk.set_appearance_mode("Light")
        self.pump()
        self.assertEqual(editor.main_pane.cget("bg"), "#d1d5db")

        editor.close_editor()
        self.pump()
        self.assertNotIn(
            editor.apply_pane_color,
            ctk.AppearanceModeTracker.callback_list,
            "o gancho ficou registrado depois de fechar",
        )


if __name__ == "__main__":
    unittest.main()


class SettingsCredentialCheckTests(MainWindowTestCase):
    """O botao "Testar chaves e modelos": o que esta no campo vale para o
    teste, o provedor sem chave e dito, o resultado chega pela fila e o botao
    volta — sem rede (a conferencia e substituida)."""

    def setUp(self):
        super().setUp()
        self.patch(api_keys, "load_api_key", lambda *_a, **_k: "")

    def abre(self):
        janela = self.app.open_settings_window()
        self.pump()
        self.addCleanup(lambda: janela.win.destroy() if janela.win.winfo_exists() else None)
        return janela

    def espera_resultado(self, janela, tentativas=50):
        for _ in range(tentativas):
            self.pump()
            if janela.btn_test_keys.cget("state") == "normal" and "testando" not in janela.test_result_label.cget("text"):
                return janela.test_result_label.cget("text")
            time.sleep(0.05)
        self.fail("o teste das chaves nao terminou: " + janela.test_result_label.cget("text"))

    def test_the_typed_key_and_model_are_checked_and_the_keyless_provider_is_said(self):
        pedidos = []

        def falso(provider_id, model, api_key=None, **_k):
            pedidos.append((provider_id, model, api_key))
            return (provider_id == "deepseek", "chave aceita" if provider_id == "deepseek" else "chave recusada (401)")

        self.patch(settings_window, "check_credentials", falso)
        janela = self.abre()
        janela.key_entries["deepseek"].insert(0, " ds-chave-1234 ")
        janela.model_vars["deepseek"].set("deepseek-flash")
        janela.key_entries["openai"].insert(0, "oa-chave-5678")
        janela.btn_test_keys.invoke()
        texto = self.espera_resultado(janela)

        self.assertEqual(sorted(pedidos), [("deepseek", "deepseek-flash", "ds-chave-1234"), ("openai", "gpt-5", "oa-chave-5678")])
        self.assertIn("\u2713 DeepSeek: chave aceita", texto)
        self.assertIn("\u2717 ChatGPT (OpenAI): chave recusada (401)", texto)
        self.assertIn("Claude (Anthropic): sem chave", texto)
        self.assertNotIn("ds-chave-1234", texto)
        self.assertEqual(janela.btn_test_keys.cget("state"), "normal")

    def test_without_any_key_nothing_is_asked(self):
        chamadas = []
        self.patch(settings_window, "check_credentials", lambda *a, **k: chamadas.append(a) or (True, "x"))
        janela = self.abre()
        janela.btn_test_keys.invoke()
        self.pump()
        self.assertEqual(chamadas, [])
        self.assertEqual(janela.test_result_label.cget("text").count("sem chave"), 3)
        self.assertEqual(janela.btn_test_keys.cget("state"), "normal")


class ProviderDialogTests(MainWindowTestCase):
    """O dialogo do "Iniciar tradução" (ROADMAP 28.7): so com chave, sempre
    com chave, e a escolha nunca e um motor sem chave."""

    def dialogo(self, configurados, lembrado="google"):
        d = provider_dialog.ProviderChoiceDialog(
            self.app, configurados, settings.LLM_DEFAULTS, lembrado
        )
        self.pump()
        self.addCleanup(d.close)
        return d

    def test_it_lists_google_and_every_provider_and_disables_the_keyless(self):
        d = self.dialogo(["deepseek"])
        self.assertEqual(set(d.radios), {"google", *llm_providers.PROVIDER_ORDER})
        self.assertEqual(d.radios["deepseek"].cget("state"), "normal")
        self.assertEqual(d.radios["anthropic"].cget("state"), "disabled")
        self.assertEqual(d.radios["google"].cget("state"), "normal")
        self.assertIn(settings.LLM_DEFAULTS["deepseek_model"], d.radios["deepseek"].cget("text"))
        self.assertEqual(d.choice_var.get(), "google")

    def test_the_remembered_provider_is_preselected_only_with_a_key(self):
        self.assertEqual(self.dialogo(["openai"], "openai").choice_var.get(), "openai")
        self.assertEqual(self.dialogo(["deepseek"], "openai").choice_var.get(), "google")

    def test_confirm_returns_the_choice_and_cancel_returns_none(self):
        d = self.dialogo(["openai"], "openai")
        d.confirm()
        self.assertEqual(d.result, "openai")
        d = self.dialogo(["openai"])
        d.cancel()
        self.assertIsNone(d.result)
        # Um motor sem chave nao sai daqui como escolha, nem forcando a variavel.
        d = self.dialogo(["openai"])
        d.choice_var.set("anthropic")
        d.confirm()
        self.assertEqual(d.result, "google")

    def test_start_asks_only_with_a_key_and_passes_the_choice_to_the_worker(self):
        chamadas, pronto = self.worker_falso()
        self.app.source_path.set(self.escreve_pgn("a.pgn"))
        perguntas = []
        self.patch(app_actions, "ask_translation_provider", lambda *a: perguntas.append(a) or "openai")

        # Sem chave: sem pergunta, Google.
        self.app.start_translation()
        self.assertTrue(pronto.wait(5))
        self.assertEqual(perguntas, [])
        self.assertEqual(chamadas[-1]["provider"], "google")
        self.app.is_processing = False  # o worker falso nao faz o `finally`
        self.app._reset_buttons()
        self.pump()

        # Com chave: pergunta, e a escolha vai para o worker e fica lembrada.
        self.patch(app_actions, "configured_providers", lambda: ["openai"])
        pronto.clear()
        self.app.start_translation()
        self.assertTrue(pronto.wait(5))
        self.assertEqual(len(perguntas), 1)
        self.assertEqual(perguntas[0][1], ["openai"])
        self.assertEqual(chamadas[-1]["provider"], "openai")
        self.assertEqual(self.app.translation_provider, "openai")
        self.assertEqual(
            settings.read_main_window_settings(
                settings.load_settings(settings.default_settings_path()), app_config.LANGUAGE_NAMES
            )["translation_provider"],
            "openai",
        )
        self.app.is_processing = False
        self.app._reset_buttons()
        self.pump()

        # Cancelar no dialogo: nada comeca.
        self.patch(app_actions, "ask_translation_provider", lambda *a: None)
        pronto.clear()
        antes = len(chamadas)
        self.app.start_translation()
        self.pump()
        self.assertFalse(self.app.is_processing)
        self.assertEqual(len(chamadas), antes)

    def test_claude_without_the_sdk_is_refused_before_starting(self):
        chamadas, _pronto = self.worker_falso()
        self.app.source_path.set(self.escreve_pgn("a.pgn"))
        self.patch(app_actions, "configured_providers", lambda: ["anthropic"])
        self.patch(app_actions, "ask_translation_provider", lambda *a: "anthropic")
        self.patch(app_actions, "anthropic_sdk_available", lambda: False)
        self.app.start_translation()
        self.pump()
        self.assertFalse(self.app.is_processing)
        self.assertEqual(chamadas, [])
        self.assertTrue(any("anthropic" in m for m in self.dialogs.messages("error")))
