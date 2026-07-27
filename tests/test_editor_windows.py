"""Testes que abrem as janelas de edicao de verdade e clicam nos widgets.

O ROADMAP registrava que `open_translation_editor` e `open_glossary_editor` so
seriam testaveis depois de virarem classes (item 3.1). Nao e o caso: o Tk expoe
a arvore de widgets, e `invoke()` dispara o mesmo `command` que um clique. Da
para exercitar as duas janelas hoje, sem tocar na estrutura delas.

Isso inverte a ordem prevista — a rede de testes vem ANTES da refatoracao, que e
exatamente o que ela precisa para nao ser feita as cegas.

O que estes testes protegem sao bugs que ja aconteceram e que nenhum teste de
funcao pura pegaria, porque nascem da interacao entre gravar, recarregar a lista
e selecionar (garantias R7 e S6).

Precisam de um display. Onde nao houver, a classe inteira e pulada.
"""

import io
import os
import sqlite3
import sys
import tempfile
import tkinter as tk
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from tradutor_pgn import (
    app_actions,
    db_tools,
    edit_window,
    editor_widgets,
    glossario,
    glossary_editor,
    history_window,
    settings,
    translation_worker,
    window_utils,
)
from tradutor_pgn.database import initialize_database, save_translation
from tradutor_pgn.glossario import load_glossary_entry_details, save_glossary_entries


def _display_available():
    try:
        root = tk.Tk()
    except Exception:
        return False
    root.destroy()
    return True


DISPLAY = _display_available()

# Todo modulo capaz de abrir um dialogo durante os testes.
DIALOG_MODULES = (
    edit_window,
    glossary_editor,
    db_tools,
    app_actions,
    translation_worker,
)


class _SilentDialogs:
    """Substitui o `messagebox` do modulo sob teste e registra as chamadas."""

    def __init__(self):
        self.calls = []

    def _record(self, kind):
        def handler(title, message, **_kwargs):
            self.calls.append((kind, title, message))
            return None

        return handler

    def install(self, *modules):
        """Silencia o `messagebox` de TODOS os modulos que possam abrir dialogo.

        Nao basta cobrir o modulo sob teste: "Aplicar automaticas" no editor de
        traducoes chama `db_tools`, que abre a confirmacao no proprio namespace.
        Um so modulo esquecido trava a suite num dialogo modal invisivel.
        """
        self.calls.clear()
        recorder = self

        class Fake:
            showinfo = staticmethod(recorder._record("info"))
            showwarning = staticmethod(recorder._record("warning"))
            showerror = staticmethod(recorder._record("error"))

            @staticmethod
            def askyesno(title, message, **_kwargs):
                recorder.calls.append(("askyesno", title, message))
                return True

        self.previous = []
        for module in modules:
            if hasattr(module, "messagebox"):
                self.previous.append((module, module.messagebox))
                module.messagebox = Fake

    def restore(self):
        for module, original in self.previous:
            module.messagebox = original

    def titles(self, kind=None):
        return [t for k, t, _m in self.calls if kind is None or k == kind]


class _SilentFileDialogs:
    """Faz todo seletor de arquivo responder "cancelado".

    Sem isto, varrer os botoes abriria dialogos nativos e a suite travaria
    esperando alguem clicar.
    """

    def install(self, *modules):
        class Fake:
            asksaveasfilename = staticmethod(lambda **_kwargs: "")
            askopenfilename = staticmethod(lambda **_kwargs: "")
            askdirectory = staticmethod(lambda **_kwargs: "")

        self.previous = []
        for module in modules:
            if hasattr(module, "filedialog"):
                self.previous.append((module, module.filedialog))
                module.filedialog = Fake

    def restore(self):
        for module, original in self.previous:
            module.filedialog = original


class FakeApp:
    """O minimo que as duas janelas usam do app real."""

    def __init__(self, root, output_db):
        self.root = root
        self.output_db = output_db
        self.target_language = tk.StringVar(value="pt")
        self.glossary_substitutions = []
        self.glossary_change_callbacks = []
        self.logs = []

    def log_message(self, message):
        self.logs.append(message)


@unittest.skipUnless(DISPLAY, "sem display para o Tk")
class EditorWindowTestCase(unittest.TestCase):
    """Base: sandbox em disco, janela aberta, helpers de widget."""

    module = None  # definido pelas subclasses

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="editor-test-")
        base = Path(self.sandbox.name)
        self.addCleanup(self.sandbox.cleanup)

        # Mesmo isolamento do test_core: nada aqui pode tocar os arquivos reais.
        self._paths = (
            glossario._default_substitutions_path,
            glossario._default_glossary_db_path,
            settings.default_settings_path,
        )
        glossario._default_substitutions_path = lambda: str(base / "Substituicoes.txt")
        glossario._default_glossary_db_path = lambda: str(base / "glossario.db")
        settings.default_settings_path = lambda: str(base / "settings.json")
        self.addCleanup(self._restore_paths)

        self.db_path = str(base / "traducoes.db")
        self.root = tk.Tk()
        self.root.withdraw()          # nada pisca na tela durante a suite
        self.addCleanup(self._destroy_root)
        self.app = FakeApp(self.root, self.db_path)

        self.dialogs = _SilentDialogs()
        self.dialogs.install(*DIALOG_MODULES)
        self.addCleanup(self.dialogs.restore)

        self.file_dialogs = _SilentFileDialogs()
        self.file_dialogs.install(*DIALOG_MODULES)
        self.addCleanup(self.file_dialogs.restore)

    def _restore_paths(self):
        (
            glossario._default_substitutions_path,
            glossario._default_glossary_db_path,
            settings.default_settings_path,
        ) = self._paths

    def _destroy_root(self):
        # As janelas agendam trabalho com `after` (levantar a janela, restaurar a
        # posicao do divisor). Destruir sem cancelar deixa esses callbacks
        # dispararem no vazio e o Tk imprime "invalid command name" no meio da
        # saida da suite — barulho que esconderia uma falha de verdade.
        try:
            for after_id in self.root.tk.eval("after info").split():
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---------------- helpers de widget ----------------

    def pump(self):
        self.root.update()

    def open_window(self, opener, *args, **kwargs):
        opener(self.app, *args, **kwargs)
        self.pump()
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertTrue(tops, "a janela nao abriu")
        self.win = tops[-1]
        return self.win

    def walk(self):
        def descend(widget):
            yield widget
            for child in widget.winfo_children():
                yield from descend(child)

        return descend(self.win)

    def widgets(self, kind):
        return [w for w in self.walk() if isinstance(w, kind)]

    def buttons(self):
        result = []
        for widget in self.widgets(self.module.ctk.CTkButton):
            try:
                result.append((widget, widget.cget("text") or ""))
            except tk.TclError:
                continue
        return result

    def button(self, label):
        """Botao cujo texto e exatamente `label`."""
        for widget, text in self.buttons():
            if text.strip() == label:
                return widget
        self.fail(f"botao {label!r} nao encontrado; ha {sorted(t.strip() for _w, t in self.buttons())}")

    def button_containing(self, needle):
        for widget, text in self.buttons():
            if needle in text:
                return widget
        return None

    def click(self, widget):
        widget.invoke()
        self.pump()

    def texts(self):
        return self.widgets(tk.Text)

    def set_text(self, widget, value):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        self.pump()

    def text_value(self, widget):
        return widget.get("1.0", tk.END).strip()

    def click_every_button(self, skip=()):
        """Aciona todos os botoes da janela e exige que nenhum exploda.

        Cobertura de crash barata sobre as dezenas de funcoes aninhadas das
        duas janelas: nao afirma o que cada botao FAZ, mas garante que nenhum
        levanta excecao nem deixa a janela num estado invalido. E a rede que
        uma refatoracao estrutural (item 3.1) precisa — quase nenhum desses
        caminhos tem teste proprio, e uma variavel esquecida no meio da
        conversao apareceria aqui.

        A lista de botoes e relida a cada passo: clicar recria as linhas.
        """
        clicados = []
        vistos = set()

        while True:
            pendente = None
            for widget, text in self.buttons():
                rotulo = text.strip()
                if rotulo in vistos or rotulo in skip or not rotulo:
                    continue
                pendente = (widget, rotulo)
                break

            if pendente is None:
                break

            widget, rotulo = pendente
            vistos.add(rotulo)
            try:
                widget.invoke()
                self.pump()
            except Exception as exc:  # noqa: BLE001 - o teste E sobre isso
                self.fail(f"o botao {rotulo!r} levantou {type(exc).__name__}: {exc}")
            clicados.append(rotulo)

            self.assertTrue(
                self.win.winfo_exists(), f"a janela morreu ao clicar em {rotulo!r}"
            )

        return clicados


# ===========================================================================
# Editor de traducoes
# ===========================================================================


class TranslationEditorTests(EditorWindowTestCase):
    """Garantia R7: a lista carrega o item clicado."""

    module = edit_window

    ROWS = ["AAA primeira linha", "BBB segunda linha", "CCC terceira linha"]

    def setUp(self):
        super().setUp()
        # Traducao identica ao original => aviso de qualidade nas tres linhas.
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for texto in self.ROWS:
            save_translation(cur, texto, texto, "pt")
        conn.commit()
        conn.close()

        self.open_window(edit_window.open_translation_editor)

    def segment_with(self, valor):
        """O seletor que oferece `valor`, e nao "o primeiro da arvore".

        A janela tem mais de um `CTkSegmentedButton` (o filtro de status e o
        modo de busca). Escolher por posicao fazia o teste mexer no seletor
        errado assim que a interface ganhava outro — e ele passava a nao
        exercitar o filtro nenhum, sem acusar nada.
        """
        for widget in self.widgets(edit_window.ctk.CTkSegmentedButton):
            if valor in widget.cget("values"):
                return widget
        self.fail(f"nenhum seletor oferece {valor!r}")

    def use_qa_filter(self):
        segment = self.segment_with("Avisos QA")
        segment.set("Avisos QA")
        segment._command("Avisos QA")
        self.pump()
        self.assertEqual(segment.get(), "Avisos QA")

    def row_buttons(self):
        return [
            widget
            for widget, text in self.buttons()
            if any(prefixo in text for prefixo in ("AAA", "BBB", "CCC"))
        ]

    def row_labels(self):
        return [
            text.split("O: ")[-1][:3]
            for _widget, text in self.buttons()
            if any(prefixo in text for prefixo in ("AAA", "BBB", "CCC"))
        ]

    def loaded_original(self):
        return self.text_value(self.texts()[0])

    def fix_current_warning(self):
        """Corrige a traducao da linha atual, matando o aviso de qualidade."""
        self.set_text(self.texts()[1], "traducao corrigida, com tamanho parecido")

    def test_the_three_rows_start_with_a_warning(self):
        self.use_qa_filter()
        self.assertEqual(self.row_labels(), ["AAA", "BBB", "CCC"])

    def test_clicking_a_row_loads_that_row(self):
        self.use_qa_filter()
        self.click(self.row_buttons()[1])
        self.assertTrue(self.loaded_original().startswith("BBB"))

    def test_clicking_b_loads_b_after_the_save_drops_a_row(self):
        """O bug do item 3.3.

        Corrigir A tira A do filtro "Avisos QA" no momento em que a gravacao
        acontece — que e durante o clique em B. A lista encolhe, B sobe para a
        posicao 0, e a posicao 1 do clique passa a ser C. Pela posicao, clicar
        em B carregava C.
        """
        self.use_qa_filter()
        self.click(self.row_buttons()[0])
        self.fix_current_warning()

        self.click(self.row_buttons()[1])

        self.assertEqual(self.row_labels(), ["BBB", "CCC"], "A devia ter saido do filtro")
        self.assertTrue(
            self.loaded_original().startswith("BBB"),
            f"clicou em B e carregou {self.loaded_original()[:12]!r}",
        )

    def test_mark_verified_advances_without_skipping(self):
        """Mesma raiz, em "Marcar como verificada".

        A linha atual sai da lista ao ser gravada, entao quem ocupou o lugar
        dela ja E a proxima. Avancar uma casa alem disso pulava uma traducao.
        """
        self.use_qa_filter()
        self.click(self.row_buttons()[0])
        self.fix_current_warning()

        self.click(self.button("Marcar como verificada"))

        self.assertEqual(self.row_labels(), ["BBB", "CCC"])
        self.assertTrue(
            self.loaded_original().startswith("BBB"),
            f"pulou uma traducao: carregou {self.loaded_original()[:12]!r}",
        )

    def test_every_button_survives_a_click(self):
        """Nenhum dos botoes da janela pode levantar excecao."""
        clicados = self.click_every_button(
            skip={"Editar glossário"}   # abre outra janela; testada na classe dela
        )
        self.assertGreater(len(clicados), 20, f"clicou pouca coisa: {clicados}")

    def test_navigation_without_a_reload_still_walks_in_order(self):
        """Contraprova: sem lista encolhendo, "Proxima" anda normalmente."""
        self.click(self.row_buttons()[0])
        self.assertTrue(self.loaded_original().startswith("AAA"))
        self.click(self.button("Próxima >"))
        self.assertTrue(self.loaded_original().startswith("BBB"))
        self.click(self.button("Próxima >"))
        self.assertTrue(self.loaded_original().startswith("CCC"))


# ===========================================================================
# Editor de glossario
# ===========================================================================


class GlossaryEditorTests(EditorWindowTestCase):
    """Garantia S6: a operacao atinge a entrada apontada."""

    module = glossary_editor

    ENTRIES = [
        ("rook", "torre", "suggestion"),
        ("queen", "dama", "suggestion"),
        ("pawn", "peao", "automatic"),
    ]

    def setUp(self):
        super().setUp()
        self.glossary_path = glossario._default_substitutions_path()
        save_glossary_entries(self.ENTRIES, self.glossary_path, create_backup=False)
        self.open_window(glossary_editor.open_glossary_editor)

    def entries_on_disk(self):
        return load_glossary_entry_details(self.glossary_path, deduplicate=False)

    def row_for(self, needle):
        widget = self.button_containing(needle)
        self.assertIsNotNone(widget, f"linha {needle!r} nao encontrada")
        return widget

    def external_change(self, entries):
        """Outra janela grava no glossario enquanto esta esta aberta."""
        save_glossary_entries(entries, self.glossary_path, create_backup=False)

    def test_every_button_survives_a_click(self):
        clicados = self.click_every_button()
        self.assertGreater(len(clicados), 15, f"clicou pouca coisa: {clicados}")

    def test_saving_edits_the_selected_entry(self):
        self.click(self.row_for("queen"))
        self.set_text(self.texts()[1], "rainha")
        self.click(self.button("Salvar"))

        self.assertIn(("queen", "rainha", "suggestion"), self.entries_on_disk())
        self.assertIn(("rook", "torre", "suggestion"), self.entries_on_disk())

    def test_saving_survives_an_external_insertion(self):
        """O bug do item 3.4.

        A posicao de "queen" foi capturada no carregamento (1). Uma insercao no
        inicio do arquivo empurra tudo, e gravar na posicao 1 escreve por cima
        de "rook".
        """
        self.click(self.row_for("queen"))
        self.external_change([("bishop", "bispo", "suggestion")] + list(self.ENTRIES))

        self.set_text(self.texts()[1], "rainha")
        self.click(self.button("Salvar"))

        entradas = self.entries_on_disk()
        self.assertIn(("rook", "torre", "suggestion"), entradas, "gravou por cima da vizinha")
        self.assertIn(("queen", "rainha", "suggestion"), entradas)
        self.assertNotIn(("queen", "dama", "suggestion"), entradas)

    def test_deleting_survives_an_external_insertion(self):
        self.click(self.row_for("queen"))
        self.external_change([("bishop", "bispo", "suggestion")] + list(self.ENTRIES))

        self.click(self.button("Excluir"))

        entradas = self.entries_on_disk()
        self.assertIn(("rook", "torre", "suggestion"), entradas, "excluiu a vizinha")
        self.assertNotIn(("queen", "dama", "suggestion"), entradas)

    def test_saving_an_entry_removed_elsewhere_writes_nothing(self):
        self.click(self.row_for("rook"))
        sobraram = [("bishop", "bispo", "suggestion"), ("pawn", "peao", "automatic")]
        self.external_change(sobraram)

        self.set_text(self.texts()[1], "torre nova")
        self.click(self.button("Salvar"))

        self.assertEqual(self.entries_on_disk(), sobraram, "gravou uma entrada que sumiu")
        self.assertIn("Entrada não encontrada", self.dialogs.titles("warning"))

    def test_deleting_an_entry_removed_elsewhere_writes_nothing(self):
        self.click(self.row_for("rook"))
        sobraram = [("bishop", "bispo", "suggestion"), ("pawn", "peao", "automatic")]
        self.external_change(sobraram)

        self.click(self.button("Excluir"))

        self.assertEqual(self.entries_on_disk(), sobraram)
        self.assertIn("Entrada não encontrada", self.dialogs.titles("warning"))


class GlossaryConflictEditorTests(EditorWindowTestCase):
    """Garantia S9: a janela diz qual regra do conflito esta valendo.

    A logica de quem vence esta coberta por funcao pura em
    `GlossaryConflictTests`. O que so aparece aqui e o outro lado: que a
    mensagem chega mesmo a tela na regra selecionada, e que "Manter esta" grava
    o arquivo certo — a queixa do item 1.5 era exatamente que as duas regras
    apareciam lado a lado com o mesmo aspecto.
    """

    module = glossary_editor

    ENTRIES = [
        ("torre", "rook", "suggestion"),
        ("dama", "queen", "suggestion"),
        ("torre", "castle", "suggestion"),
    ]

    def setUp(self):
        super().setUp()
        self.glossary_path = glossario._default_substitutions_path()
        save_glossary_entries(self.ENTRIES, self.glossary_path, create_backup=False)
        self.open_window(glossary_editor.open_glossary_editor)

    def entries_on_disk(self):
        return load_glossary_entry_details(self.glossary_path, deduplicate=False)

    def row_for(self, needle):
        widget = self.button_containing(needle)
        self.assertIsNotNone(widget, f"linha {needle!r} nao encontrada")
        return widget

    def conflict_text(self):
        """O texto do aviso de conflito, ou vazio se ele nao esta na tela."""
        for widget in self.widgets(glossary_editor.ctk.CTkLabel):
            try:
                text = widget.cget("text") or ""
            except tk.TclError:
                continue
            if text.startswith("Conflito em") and widget.winfo_ismapped():
                return text
        return ""

    def test_the_losing_rule_names_the_one_that_wins(self):
        self.click(self.row_for("castle"))

        aviso = self.conflict_text()
        self.assertIn("#1", aviso)
        self.assertIn("rook", aviso)
        self.assertIn("nunca é aplicada", aviso)

    def test_the_winning_rule_says_it_is_the_winner(self):
        self.click(self.row_for("rook"))

        aviso = self.conflict_text()
        self.assertIn("vence esta regra", aviso)
        self.assertNotIn("nunca é aplicada", aviso)

    def test_a_rule_without_conflict_shows_no_warning(self):
        self.click(self.row_for("queen"))
        self.assertEqual(self.conflict_text(), "")

    def test_keeping_a_rule_removes_only_the_one_it_disputed(self):
        self.click(self.row_for("castle"))
        self.click(self.button("Manter esta"))

        entradas = self.entries_on_disk()
        self.assertIn(("torre", "castle", "suggestion"), entradas)
        self.assertNotIn(("torre", "rook", "suggestion"), entradas)
        self.assertIn(("dama", "queen", "suggestion"), entradas, "levou junto quem nao disputava")

        # Resolvido tambem na tela: nao sobra aviso de conflito nenhum.
        self.assertEqual(self.conflict_text(), "")


class TranslationEditorMethodCoverageTests(EditorWindowTestCase):
    """Roadmap 3.1 etapa 2: os caminhos que varrer os botoes nao alcanca.

    A conversao das 86 funcoes aninhadas em metodos foi mecanica, e o defeito
    tipico de uma conversao dessas e um nome que ficou para tras: um
    `NameError` num caminho pouco usado, que sob `pythonw` some sem deixar
    rastro. `click_every_button` cobre 71 dos 94 metodos; estes testes existem
    para os 23 que sobravam — atalhos de teclado, busca dentro do texto,
    sugestoes e os auxiliares puros.

    O contrato e o mesmo do `click_every_button`: nao afirmam o que cada
    caminho FAZ (isso seria inventar especificacao agora), e sim que nenhum
    deles levanta excecao. Onde o resultado e obvio, ha afirmacao de verdade.
    """

    module = edit_window

    ROWS = [
        ("O bispo domina a diagonal", "O bispo domina a diagonal"),
        ("A torre entra na coluna", "A torre entra na coluna"),
    ]

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for original, traducao in self.ROWS:
            save_translation(cur, original, traducao, "pt")
        conn.commit()
        conn.close()

        self.app.glossary_substitutions = [("bispo", "alfil")]
        # A conversao em classe deu isto de graca: o `open_translation_editor`
        # devolve a instancia, entao o teste alcanca os metodos direto, sem
        # precisar achar o widget que dispara cada um.
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win

    # ------------------------------------------------ auxiliares puros

    def test_the_pure_helpers_answer(self):
        self.assertEqual(self.editor.text_index_for_offset(5), "1.0+5c")
        self.assertEqual(self.editor.text_index_for_offset(-3), "1.0+0c")
        self.assertEqual(history_window.history_action_label("restore"), "Restauracao")
        self.assertEqual(history_window.history_action_label(""), "Alteracao")
        self.assertEqual(
            history_window.history_action_label("acao_nova_de_outra_versao"),
            "acao_nova_de_outra_versao",
            "acao desconhecida aparece pelo nome, em vez de sumir num rotulo generico",
        )
        self.assertEqual(history_window.history_status_label(1), "verificada")
        self.assertEqual(history_window.history_status_label(0), "pendente")

    def test_applying_a_glossary_pair_reports_where_the_cursor_lands(self):
        texto, offset = self.editor.apply_glossary_pair_with_cursor(
            "o bispo e o bispo", "bispo", "alfil"
        )
        self.assertEqual(texto, "o alfil e o alfil")
        self.assertEqual(offset, len("o alfil e o alfil"))

        intacto, nenhum = self.editor.apply_glossary_pair_with_cursor(
            "sem nada aqui", "bispo", "alfil"
        )
        self.assertEqual(intacto, "sem nada aqui")
        self.assertIsNone(nenhum)

    # ------------------------------------------------ busca dentro do texto

    def test_the_find_flow_runs_end_to_end(self):
        self.editor.select_index(0)
        self.editor.editor_find_text.set("bispo")
        self.pump()

        self.assertTrue(self.editor.editor_find_ranges(), "nao achou o termo")
        self.editor.find_next_in_translation()
        self.pump()
        self.assertIsNotNone(
            self.editor.state.current_find_match, "nenhuma ocorrencia ficou marcada"
        )

        self.editor.editor_replace_text.set("alfil")
        self.editor.replace_current_in_translation()
        self.pump()
        self.assertIn("alfil", self.editor.draft_text())

    def test_selecting_a_find_match_with_no_ranges_just_clears(self):
        self.editor.select_index(0)
        self.editor.select_find_match([], 0)
        self.assertIsNone(self.editor.state.current_find_match)

    # ------------------------------------------------ sugestoes

    def test_selecting_and_applying_a_suggestion(self):
        self.editor.select_index(0)
        self.pump()
        self.assertTrue(self.editor.current_suggestions, "o glossario nao sugeriu nada")

        self.editor.select_suggestion(0)
        self.assertEqual(self.editor.state.selected_suggestion, 0)

        self.editor.apply_one()
        self.pump()
        self.assertIn("alfil", self.editor.draft_text())

    def test_the_suggestion_context_menu_is_built_and_posted(self):
        """`tk_popup` e substituido de proposito: ele e MODAL.

        Chamado de verdade, ele entra num laco de eventos esperando alguem
        clicar ou apertar Esc — e como nao ha ninguem, a suite ficava 40 s
        parada nesta linha. Trocando so o `tk_popup`, o metodo continua sendo
        exercitado inteiro (monta o menu, registra o comando, solta o grab); o
        que sai e a espera por um humano, que nunca foi o objeto do teste.
        """
        self.editor.select_index(0)
        self.pump()

        chamadas = []
        original = tk.Menu.tk_popup
        tk.Menu.tk_popup = lambda self, x, y, *a: chamadas.append((x, y))
        self.addCleanup(setattr, tk.Menu, "tk_popup", original)

        evento = types.SimpleNamespace(x_root=10, y_root=20)
        self.editor.show_suggestion_context_menu(evento, "bispo", "alfil")

        self.assertEqual(chamadas, [(10, 20)], "o menu nao foi exibido no ponto do clique")

    def test_deleting_a_suggestion_that_is_not_in_the_glossary(self):
        """Sai pela mensagem, sem tocar no arquivo — garantia S6."""
        self.editor.delete_suggestion_from_glossary("nao existe", "nada")

    def test_the_glossary_change_callback_refreshes_the_suggestions(self):
        self.editor.select_index(0)
        self.editor.on_glossary_editor_change([("torre", "roque")])
        self.pump()
        self.assertEqual(self.editor.glossary, [("torre", "roque")])

    # ------------------------------------------------ navegacao e atalhos

    def test_going_to_an_id_that_exists_and_one_that_does_not(self):
        self.editor.go_id_text.set("1")
        self.editor.go_to_id()
        self.pump()

        self.editor.go_id_text.set("99999")
        self.editor.go_to_id()
        self.pump()

        self.editor.go_id_text.set("nao e numero")
        self.editor.go_to_id()
        self.pump()

    def test_changing_page_beyond_the_only_page_is_a_no_op(self):
        antes = self.editor.state.page_index
        self.editor.change_page(1)
        self.editor.change_page(-1)
        self.assertEqual(self.editor.state.page_index, antes)

    def test_the_quality_warning_scan_walks_the_offsets(self):
        achado = self.editor.find_quality_warning_offset(0, self.editor.state.total_rows)
        self.assertIsNotNone(achado, "as duas linhas tem aviso de QA")
        self.assertIsNone(self.editor.find_quality_warning_offset(5, 5))

    def test_every_keyboard_shortcut_survives(self):
        """Os atalhos passam por metodos que nenhum botao alcanca.

        O `focus_set` nao e enfeite: sem um widget com foco, o Tk simplesmente
        **nao entrega** alguns eventos sinteticos — `<Control-f>` e um deles,
        enquanto `<Control-s>` chega. Sem essa linha o teste passaria sem
        exercitar nada, que e o pior resultado possivel para um teste de
        atalho.
        """
        self.editor.select_index(0)
        self.editor.trans_text.focus_set()
        self.pump()
        for atalho in (
            "<Control-f>",
            "<Control-s>",
            "<Control-Return>",
            "<Alt-Left>",
            "<Alt-Right>",
            "<F3>",
            "<F7>",
            "<Control-h>",
        ):
            with self.subTest(atalho=atalho):
                self.win.event_generate(atalho)
                self.pump()
                self.assertTrue(self.win.winfo_exists(), "a janela morreu")

    def test_the_draft_is_persisted_and_cleared(self):
        self.editor.select_index(0)
        self.editor.set_translation_text("um rascunho qualquer", mark_dirty=True)
        self.editor.persist_current_draft()
        self.pump()

        rascunhos = settings.load_settings().get("editor_drafts", {})
        self.assertTrue(rascunhos, "o rascunho nao foi gravado")

        self.editor.clear_current_draft()
        self.assertFalse(settings.load_settings().get("editor_drafts", {}))

    def test_the_integrated_glossary_editor_opens_from_a_selection(self):
        self.editor.select_index(0)
        self.editor.open_integrated_glossary_editor()
        self.pump()

    def marcas_de_negrito(self):
        return self.editor.trans_text.tag_ranges("bold")

    def test_bold_marks_the_selection_and_unmarks_it(self):
        """O recurso que existia no projeto original e se perdeu no caminho.

        E marcacao de quem revisa, nao formatacao do comentario: a tag e do Tk e
        nao vai para o banco.
        """
        self.editor.select_index(0)
        self.editor.set_translation_text("O bispo domina a diagonal", mark_dirty=False)
        self.pump()

        self.editor.trans_text.tag_add(tk.SEL, "1.0+2c", "1.0+7c")
        self.editor.toggle_bold_selection()
        self.assertTrue(self.marcas_de_negrito(), "a selecao nao ficou em negrito")

        self.editor.toggle_bold_selection()
        self.assertFalse(self.marcas_de_negrito(), "clicar de novo nao desmarcou")

    def test_bold_without_a_selection_says_so_instead_of_failing(self):
        self.editor.select_index(0)
        self.editor.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.editor.toggle_bold_selection()
        self.assertFalse(self.marcas_de_negrito())

    def test_bold_is_reachable_by_the_keyboard(self):
        """Sem o atalho o metodo existiria sem nenhuma forma de aciona-lo."""
        self.editor.select_index(0)
        self.editor.set_translation_text("O bispo domina a diagonal", mark_dirty=False)
        self.pump()
        self.editor.trans_text.tag_add(tk.SEL, "1.0+2c", "1.0+7c")
        self.editor.trans_text.focus_set()
        self.pump()

        self.editor.trans_text.event_generate("<Control-b>")
        self.pump()
        self.assertTrue(self.marcas_de_negrito(), "o Ctrl+B nao chegou ao metodo")

    def test_the_two_bold_features_do_not_replace_each_other(self):
        """Alternar a fonte do editor e marcar um trecho sao coisas distintas.

        O botao "B" continua com o alternador de fonte, ao lado do A-/A+; a
        marcacao vive no Ctrl+B. Trocar um pelo outro foi como o recurso se
        perdeu.
        """
        self.editor.select_index(0)
        self.editor.set_translation_text("O bispo domina a diagonal", mark_dirty=False)
        self.pump()

        self.editor.trans_text.tag_add(tk.SEL, "1.0+2c", "1.0+7c")
        self.editor.toggle_bold_selection()
        marcado = self.marcas_de_negrito()

        self.editor.toggle_bold_view()
        self.assertEqual(
            self.marcas_de_negrito(), marcado, "a fonte do editor apagou a marcacao"
        )
        self.assertTrue(self.editor.state.bold_view)

    def test_the_search_mode_selector_changes_what_the_list_shows(self):
        """Roadmap 2.8 / R8: os dois modos convivem, e o seletor decide qual vale.

        "bisp" e o discriminador: por termo nao casa nada (palavra inteira), por
        trecho acha "bispo". Se o seletor nao chegasse ate a consulta, as duas
        posicoes dariam a mesma lista e o teste nao veria diferenca.
        """
        # Alcancado pelo nome, e nao caçado na arvore de widgets: e o que a
        # conversao em classe (item 3.1) tornou possivel.
        seletor = self.editor.search_mode_segment

        self.editor.search_text.set("bisp")
        seletor.set(edit_window.SEARCH_MODE_LABEL_TERMS)
        seletor._command(edit_window.SEARCH_MODE_LABEL_TERMS)
        self.pump()
        self.assertEqual(
            self.editor.state.total_rows, 0, "por termo, 'bisp' nao casa palavra alguma"
        )

        seletor.set(edit_window.SEARCH_MODE_LABEL_SUBSTRING)
        seletor._command(edit_window.SEARCH_MODE_LABEL_SUBSTRING)
        self.pump()
        self.assertEqual(
            self.editor.state.total_rows, 1, "por trecho, 'bisp' tinha de achar 'bispo'"
        )

        # Trocar o modo refaz a busca sozinho: a lista nunca fica mostrando o
        # resultado de um modo com o seletor apontando para o outro.
        self.assertEqual(self.editor.state.active_search, "bisp")

    def test_the_search_mode_survives_reopening_the_window(self):
        seletor = self.editor.search_mode_segment
        seletor.set(edit_window.SEARCH_MODE_LABEL_SUBSTRING)
        self.editor.save_editor_settings()

        outro = edit_window.open_translation_editor(self.app)
        self.pump()
        self.addCleanup(outro.win.destroy)
        self.assertEqual(
            outro.search_mode_segment.get(), edit_window.SEARCH_MODE_LABEL_SUBSTRING
        )

    def test_closing_the_editor_saves_and_unregisters(self):
        self.editor.select_index(0)
        self.editor.close_editor()
        self.pump()

        self.assertNotIn(
            self.editor.on_glossary_editor_change,
            getattr(self.app, "glossary_change_callbacks", []),
            "o callback do glossario ficou registrado numa janela fechada",
        )


class HistoryWindowTests(EditorWindowTestCase):
    """Garantia R3: a subjanela opera sobre o item que ela declara.

    Ela e modeless — a lista principal continua clicavel enquanto ela esta
    aberta. Se o item fosse relido do editor a cada acao, "Restaurar" gravaria
    naquele que estivesse selecionado no instante do clique, e nao no que o
    titulo anuncia. R3 estava na tabela de invariantes da SPEC sem teste
    proprio; extrair a janela para uma classe (ROADMAP 3.1) tornou o teste
    facil de escrever.
    """

    module = edit_window

    ROWS = [("Primeira linha", "Traducao um"), ("Segunda linha", "Traducao dois")]

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for original, traducao in self.ROWS:
            save_translation(cur, original, traducao, "pt")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win

    def traducao_no_banco(self, comment_id):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT translated_comment FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()[0]
        finally:
            conn.close()

    def edita(self, indice, texto):
        self.editor.select_index(indice)
        self.editor.set_translation_text(texto, mark_dirty=True)
        self.editor.save_changes(silent=False)
        self.pump()

    def test_the_history_lists_the_changes(self):
        self.edita(0, "Primeira versao editada")
        janela = self.editor.open_history_window()
        self.pump()
        self.addCleanup(janela.win.destroy)

        self.assertTrue(janela.rows, "a edicao nao apareceu no historico")
        self.assertEqual(janela.comment_id, self.editor.current["id"])

    def test_restoring_brings_the_previous_text_back(self):
        self.edita(0, "Texto trocado")
        alvo = self.editor.current["id"]
        janela = self.editor.open_history_window()
        self.pump()
        self.addCleanup(janela.win.destroy)

        janela.select(0)
        janela.restore_selected(2)          # coluna "anterior"
        self.pump()

        self.assertEqual(self.traducao_no_banco(alvo), "Traducao um")
        self.assertEqual(self.editor.draft_text(), "Traducao um")

    def test_it_writes_to_the_item_it_declares_even_after_the_list_moves(self):
        """O coracao de R3, e o unico caminho em que o defeito aparece."""
        self.edita(0, "Texto trocado")
        alvo = self.editor.current["id"]

        janela = self.editor.open_history_window()
        self.pump()
        self.addCleanup(janela.win.destroy)

        # A janela e modeless: o usuario clica em outra linha com ela aberta.
        self.editor.select_index(1)
        self.pump()
        outro = self.editor.current["id"]
        self.assertNotEqual(alvo, outro)

        janela.select(0)
        janela.restore_selected(2)
        self.pump()

        self.assertEqual(
            self.traducao_no_banco(alvo),
            "Traducao um",
            "a restauracao nao atingiu o item que o titulo declara",
        )
        self.assertEqual(
            self.traducao_no_banco(outro),
            "Traducao dois",
            "a restauracao gravou por cima do item selecionado agora",
        )
        self.assertEqual(
            self.editor.draft_text(),
            "Traducao dois",
            "o texto na tela, que e de outro item, nao podia ter mudado",
        )

    def test_an_item_without_history_shows_the_empty_state(self):
        self.editor.select_index(1)
        janela = self.editor.open_history_window()
        self.pump()
        self.addCleanup(janela.win.destroy)

        self.assertEqual(janela.rows, [])
        self.assertEqual(janela.btn_restore_previous.cget("state"), "disabled")


class SharedEditorWidgetTkTests(EditorWindowTestCase):
    """Roadmap 3.2: as pecas compartilhadas que precisam mesmo de um widget."""

    module = edit_window

    def setUp(self):
        super().setUp()
        self.pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.pane.add(tk.Frame(self.pane, width=100))
        self.pane.add(tk.Frame(self.pane, width=100))
        self.pane.pack(fill=tk.BOTH, expand=True)
        self.root.update()

    def test_it_places_the_sash_when_the_value_is_usable(self):
        """Aqui so o que precisa do Tk.

        A posicao EXATA nao e afirmada de proposito: o Tk limita o divisor ao
        tamanho real do painel, entao o numero depende da janela e o teste
        falharia por motivo nenhum. Onde colocar e decisao de
        `clamped_sash_position`, que e pura e tem teste proprio.
        """
        self.assertTrue(editor_widgets.restore_sash(self.pane, 400, 360, 520))

    def test_a_missing_or_invalid_position_is_ignored(self):
        for valor in (None, 0, -5, "480", 12.5):
            with self.subTest(valor=valor):
                self.assertFalse(editor_widgets.restore_sash(self.pane, valor, 360, 520))

    def test_collecting_sash_positions_skips_what_cannot_answer(self):
        """Um painel destruido nao pode impedir as configuracoes de serem salvas."""
        self.pane.destroy()
        self.assertEqual(
            editor_widgets.collect_sash_positions((("x", self.pane, 0),)), {}
        )

    def test_rendering_rows_replaces_the_previous_ones(self):
        frame = edit_window.ctk.CTkScrollableFrame(self.root)
        frame.pack()

        def build(parent, index, item):
            return edit_window.ctk.CTkButton(parent, text=f"{index}:{item}")

        primeiros = editor_widgets.render_row_buttons(frame, ["a", "b"], build, "vazio")
        self.assertEqual([b.cget("text") for b in primeiros], ["0:a", "1:b"])

        segundos = editor_widgets.render_row_buttons(frame, ["c"], build, "vazio")
        self.assertEqual([b.cget("text") for b in segundos], ["0:c"])
        for antigo in primeiros:
            self.assertFalse(antigo.winfo_exists(), "os botoes antigos sobreviveram")

    def test_an_empty_list_shows_the_message_and_no_buttons(self):
        frame = edit_window.ctk.CTkScrollableFrame(self.root)
        frame.pack()
        botoes = editor_widgets.render_row_buttons(
            frame, [], lambda *_a: None, "Nada aqui."
        )
        self.assertEqual(botoes, [])
        self.root.update()

        def desce(widget):
            yield widget
            for filho in widget.winfo_children():
                yield from desce(filho)

        # Varre a subarvore: o `CTkScrollableFrame` interpoe widgets proprios
        # entre ele e o conteudo, e a profundidade nao e contrato de ninguem.
        rotulos = [
            w.cget("text")
            for w in desce(frame)
            if isinstance(w, edit_window.ctk.CTkLabel)
        ]
        self.assertIn("Nada aqui.", rotulos)


@unittest.skipUnless(DISPLAY, "sem display para o Tk")
class CallbackErrorHookTests(unittest.TestCase):
    """Roadmap 6.2: o gancho do Tk dispara mesmo, e chega ate os `Toplevel`.

    As funcoes puras em `test_core` conferem a mensagem; nao conferem que ela
    alguma vez aparece. Toda a correcao depende de o Tk realmente procurar
    `report_callback_exception` na RAIZ quando um callback explode — se essa
    suposicao estiver errada, os testes puros continuam verdes e o erro continua
    invisivel, que e exatamente o defeito que este item existe para corrigir.
    """

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._destroy)

        self.dialogs = []
        self.logs = []
        window_utils.install_callback_error_reporter(
            self.root,
            log_message=self.logs.append,
            show_error=lambda titulo, msg: self.dialogs.append((titulo, msg)),
        )

    def _destroy(self):
        # Mesma razao do `_destroy_root` da classe base: o app real agenda
        # `update_log` e o CTk agenda `check_dpi_scaling`. Destruir sem cancelar
        # faz o Tk imprimir "invalid command name" no meio da saida da suite —
        # barulho que esconderia uma falha de verdade.
        try:
            for after_id in self.root.tk.eval("after info").split():
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def dispara_em(self, widget, exc):
        """Agenda um callback que explode e deixa o Tk despacha-lo."""
        def explode():
            raise exc

        widget.after(0, explode)
        widget.update()

    def test_an_exploding_callback_becomes_a_dialog(self):
        self.dispara_em(self.root, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(self.dialogs), 1, "o erro nao chegou a lugar nenhum")
        self.assertEqual(self.dialogs[0][0], window_utils.DATABASE_BUSY_TITLE)
        self.assertTrue(any("Traceback" in linha for linha in self.logs))

    def test_it_also_covers_a_toplevel(self):
        """As janelas de edicao sao `Toplevel` da raiz, e e la que o lock ocorre."""
        janela = tk.Toplevel(self.root)
        janela.withdraw()
        self.dispara_em(janela, sqlite3.OperationalError("database is locked"))

        self.assertEqual(len(self.dialogs), 1)
        self.assertEqual(self.dialogs[0][0], window_utils.DATABASE_BUSY_TITLE)

    def test_installing_on_a_toplevel_still_reaches_the_root(self):
        """Instalar na janela errada nao pode virar um relator que nunca dispara.

        O Tk procura o handler em `_root()`. Sem resolver isso, passar um
        `Toplevel` daria o pior resultado: tudo configurado, nada nunca aparece.
        """
        janela = tk.Toplevel(self.root)
        janela.withdraw()
        recebidos = []
        window_utils.install_callback_error_reporter(
            janela,
            show_error=lambda titulo, msg: recebidos.append(titulo),
        )

        self.dispara_em(self.root, ValueError("veio da raiz"))

        self.assertEqual(recebidos, [window_utils.UNEXPECTED_ERROR_TITLE])

    def test_the_real_app_installs_it(self):
        """Ponta a ponta: abrir o programa de verdade e ver o dialogo aparecer.

        Sem este teste, apagar a chamada de `app.py` nao quebraria nada — todo o
        resto continuaria verde testando um relator que ninguem liga. Foi o que a
        verificacao por mutacao acusou.
        """
        import tkinter.messagebox as tk_messagebox

        from tradutor_pgn import app as app_module

        sandbox = tempfile.TemporaryDirectory(prefix="app-test-")
        self.addCleanup(sandbox.cleanup)
        base = Path(sandbox.name)

        recebidos = []
        originais = {
            "showerror": tk_messagebox.showerror,
            "cleanup": app_module.app_actions.run_startup_cleanup,
            "argv0": sys.argv[0],
            "subs": glossario._default_substitutions_path,
            "gdb": glossario._default_glossary_db_path,
            "settings": settings.default_settings_path,
        }
        self.addCleanup(self._restaura_app, tk_messagebox, app_module, originais)

        tk_messagebox.showerror = lambda titulo, msg, **_kw: recebidos.append(titulo)
        # A limpeza deriva a pasta de `sys.argv[0]` e apagaria backups de verdade.
        app_module.app_actions.run_startup_cleanup = lambda _app: None
        sys.argv[0] = str(base / "PGN_Tradutor_Pro.py")
        glossario._default_substitutions_path = lambda: str(base / "Substituicoes.txt")
        glossario._default_glossary_db_path = lambda: str(base / "glossario.db")
        settings.default_settings_path = lambda: str(base / "settings.json")

        # Na raiz de verdade, como em producao: o app substitui o relator que o
        # `setUp` instalou, e o dialogo passa a ser o `messagebox` interceptado.
        aplicativo = app_module.PGNTranslatorApp(self.root)

        self.dispara_em(self.root, sqlite3.OperationalError("database is locked"))

        self.assertEqual(
            recebidos,
            [window_utils.DATABASE_BUSY_TITLE],
            "o programa nao instalou o relator de erros",
        )
        self.assertIsNotNone(aplicativo.output_db)

    def _restaura_app(self, tk_messagebox, app_module, originais):
        tk_messagebox.showerror = originais["showerror"]
        app_module.app_actions.run_startup_cleanup = originais["cleanup"]
        sys.argv[0] = originais["argv0"]
        glossario._default_substitutions_path = originais["subs"]
        glossario._default_glossary_db_path = originais["gdb"]
        settings.default_settings_path = originais["settings"]

    def test_without_the_reporter_the_error_is_invisible(self):
        """Contraprova: e assim que o programa se comportava ate agora.

        O Tk padrao imprime em `stderr` — que sob `pythonw` nao existe. Aqui o
        que importa e que nada e oferecido ao usuario.
        """
        del self.root.report_callback_exception
        with redirect_stderr(io.StringIO()):
            self.dispara_em(self.root, sqlite3.OperationalError("database is locked"))

        self.assertEqual(self.dialogs, [], "sem o relator nao deveria haver dialogo")


if __name__ == "__main__":
    unittest.main()
