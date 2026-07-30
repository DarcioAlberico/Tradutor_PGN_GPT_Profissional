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
import threading
import time
import tkinter as tk
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from gui_harness import DISPLAY, GuiTestCase
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
from tradutor_pgn.database import (
    initialize_database,
    record_occurrences,
    resolve_comment_ids,
    save_translation,
)
from tradutor_pgn.glossario import (
    glossary_entry_priority,
    load_glossary_entry_details,
    save_glossary_entries,
)


def com_prioridade(entries, priority=0, scope=""):
    """Entradas de tres campos como o arquivo as devolve: com prioridade e escopo.

    A entrada detalhada ganhou um quarto campo no item 1.5 parte 2 e um quinto na
    secao 15. Nos testes cujo assunto nao e nenhum dos dois, escrever `, 0, ""`
    em cada tupla so acrescenta ruido — mas apaga-los da comparacao esconderia um
    deles mexido por engano.
    """
    return [
        (orig, new, rule_type, priority, scope) for orig, new, rule_type in entries
    ]


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


class EditorWindowTestCase(GuiTestCase):
    """Base dos editores: o `GuiTestCase` mais os helpers de widget."""

    module = None  # definido pelas subclasses

    def setUp(self):
        super().setUp()
        self.app = FakeApp(self.root, self.db_path)

    # ---------------- helpers de widget ----------------

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

        self.assertIn(("queen", "rainha", "suggestion", 0, ""), self.entries_on_disk())
        self.assertIn(("rook", "torre", "suggestion", 0, ""), self.entries_on_disk())

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
        self.assertIn(("rook", "torre", "suggestion", 0, ""), entradas, "gravou por cima da vizinha")
        self.assertIn(("queen", "rainha", "suggestion", 0, ""), entradas)
        self.assertNotIn(("queen", "dama", "suggestion", 0, ""), entradas)

    def test_deleting_survives_an_external_insertion(self):
        self.click(self.row_for("queen"))
        self.external_change([("bishop", "bispo", "suggestion")] + list(self.ENTRIES))

        self.click(self.button("Excluir"))

        entradas = self.entries_on_disk()
        self.assertIn(("rook", "torre", "suggestion", 0, ""), entradas, "excluiu a vizinha")
        self.assertNotIn(("queen", "dama", "suggestion", 0, ""), entradas)

    def test_saving_an_entry_removed_elsewhere_writes_nothing(self):
        self.click(self.row_for("rook"))
        sobraram = [("bishop", "bispo", "suggestion"), ("pawn", "peao", "automatic")]
        self.external_change(sobraram)

        self.set_text(self.texts()[1], "torre nova")
        self.click(self.button("Salvar"))

        self.assertEqual(self.entries_on_disk(), com_prioridade(sobraram), "gravou uma entrada que sumiu")
        self.assertIn("Entrada não encontrada", self.dialogs.titles("warning"))

    def test_deleting_an_entry_removed_elsewhere_writes_nothing(self):
        self.click(self.row_for("rook"))
        sobraram = [("bishop", "bispo", "suggestion"), ("pawn", "peao", "automatic")]
        self.external_change(sobraram)

        self.click(self.button("Excluir"))

        self.assertEqual(self.entries_on_disk(), com_prioridade(sobraram))
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
        self.assertIn(("torre", "castle", "suggestion", 0, ""), entradas)
        self.assertNotIn(("torre", "rook", "suggestion", 0, ""), entradas)
        self.assertIn(("dama", "queen", "suggestion", 0, ""), entradas, "levou junto quem nao disputava")

        # Resolvido tambem na tela: nao sobra aviso de conflito nenhum.
        self.assertEqual(self.conflict_text(), "")


class GlossaryPriorityEditorTests(EditorWindowTestCase):
    """Item 1.5 parte 2: a prioridade na janela.

    A logica pura esta coberta em `GlossaryPriorityTests` e
    `GlossaryPromotionTests`. O que so aparece aqui e o outro lado: que o campo
    carrega e grava o valor, que um valor invalido nao chega ao arquivo, e que
    "Priorizar esta" resolve o conflito **sem apagar** a regra concorrente — que
    era a unica saida que a janela oferecia ate agora.
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
        self.editor = glossary_editor.open_glossary_editor(self.app)
        self.pump()
        self.win = self.editor.win

    def entries_on_disk(self):
        return load_glossary_entry_details(self.glossary_path, deduplicate=False)

    def conflict_text(self):
        for widget in self.widgets(glossary_editor.ctk.CTkLabel):
            try:
                text = widget.cget("text") or ""
            except tk.TclError:
                continue
            if text.startswith("Conflito em") and widget.winfo_ismapped():
                return text
        return ""

    # ------------------------------------------------ o campo

    def test_the_field_loads_and_saves_the_priority(self):
        self.editor.select_entry(2)
        self.assertEqual(self.editor.priority_text.get(), "0")

        self.editor.priority_text.set("3")
        self.editor.mark_dirty()
        self.assertTrue(self.editor.state.dirty, "mexer na prioridade nao sujou o form")

        self.click(self.button("Salvar"))

        self.assertIn(("torre", "castle", "suggestion", 3, ""), self.entries_on_disk())
        self.assertIn(("torre", "rook", "suggestion", 0, ""), self.entries_on_disk())

    def test_an_invalid_priority_never_reaches_the_file(self):
        """Cair para zero em silencio gravaria uma decisao que ninguem tomou.

        A regra parte com prioridade 5, e nao com zero: se o teste comecasse em
        zero, gravar "zero por engano" produziria exatamente o arquivo que ja
        estava la e a falha seria invisivel. Foi o que a conferencia por mutacao
        acusou na primeira versao deste teste.
        """
        self.editor.select_entry(2)
        self.editor.priority_text.set("5")
        self.editor.mark_dirty()
        self.click(self.button("Salvar"))
        self.assertIn(
            ("torre", "castle", "suggestion", 5, ""), self.entries_on_disk()
        )
        antes = self.entries_on_disk()

        self.editor.priority_text.set("alta")
        self.editor.mark_dirty()
        self.assertIn(
            glossary_editor.INVALID_PRIORITY_WARNING,
            self.editor.validation_label.cget("text"),
        )

        self.click(self.button("Salvar"))
        self.assertEqual(self.entries_on_disk(), antes, "gravou uma prioridade invalida")

        self.click(self.button("Salvar como nova"))
        self.assertEqual(self.entries_on_disk(), antes)

    def test_promoting_keeps_the_rule_selected(self):
        """Depois de priorizar, a regra continua no formulario.

        Ela e reencontrada pelo par e pelo tipo — a prioridade acabou de mudar,
        entao nao serve para identificar. Sem isso o formulario e limpo e o
        usuario perde de vista a regra sobre a qual acabou de decidir.
        """
        self.click(self.row_for("castle"))
        self.click(self.button("Priorizar esta"))

        self.assertIsNotNone(self.editor.state.selected_index, "perdeu a selecao")
        self.assertEqual(self.editor.text_value(self.editor.new_text), "castle")
        self.assertEqual(self.editor.priority_text.get(), "1")

    def test_the_row_shows_the_priority_only_when_there_is_one(self):
        self.assertIsNone(self.button_containing("P+"), "P0 apareceu na lista")

        self.editor.select_entry(2)
        self.editor.priority_text.set("2")
        self.editor.mark_dirty()
        self.click(self.button("Salvar"))

        self.assertIsNotNone(
            self.button_containing("P+2"), "a linha nao mostra a prioridade"
        )

    # ------------------------------------------------ priorizar

    def test_promoting_resolves_the_conflict_without_deleting(self):
        """A diferenca em relacao a "Manter esta", que e o ponto do item."""
        self.click(self.row_for("castle"))
        self.assertIn("nunca é aplicada", self.conflict_text())

        self.click(self.button("Priorizar esta"))

        entradas = self.entries_on_disk()
        self.assertEqual(len(entradas), 3, "a promocao apagou uma regra")
        self.assertIn(("torre", "rook", "suggestion", 0, ""), entradas)
        self.assertIn(("torre", "castle", "suggestion", 1, ""), entradas)
        self.assertNotIn("nunca é aplicada", self.conflict_text())

    def test_promoting_the_winner_says_there_is_nothing_to_do(self):
        self.click(self.row_for("rook"))
        antes = self.entries_on_disk()

        self.click(self.button("Priorizar esta"))

        self.assertEqual(self.entries_on_disk(), antes, "reescreveu o arquivo a toa")

    def test_the_app_glossary_follows_the_new_order(self):
        """A promocao tem de chegar as sugestoes do editor de traducoes."""
        self.click(self.row_for("castle"))
        self.click(self.button("Priorizar esta"))

        regras = self.app.glossary_substitutions
        self.assertEqual(
            glossario.apply_all_substitutions("a torre", regras),
            "a castle",
            f"o glossario do app nao acompanhou: {regras}",
        )

    def row_for(self, needle):
        widget = self.button_containing(needle)
        self.assertIsNotNone(widget, f"linha {needle!r} nao encontrada")
        return widget


class GlossaryEditorMethodCoverageTests(EditorWindowTestCase):
    """Roadmap 3.5: os caminhos que varrer os botoes nao alcanca.

    Mesmo contrato do `TranslationEditorMethodCoverageTests`. Instrumentando a
    classe, `click_every_button` mais os testes de S6 e S9 alcancavam 51 dos 56
    metodos; estes existem para os cinco que sobravam — paginacao, fechamento,
    confirmacao de descarte, a entrada pre-preenchida e a localizacao do que
    acabou de ser gravado. Eram exatamente onde um `NameError` da conversao
    sobreviveria: sob `pythonw` ele some sem deixar rastro.
    """

    module = glossary_editor

    # Duas paginas cheias: `PAGE_SIZE` e 150, e sem passar dele `change_page`
    # nao tem para onde ir — os botoes de pagina ficam desabilitados e varrer a
    # janela nunca chega la.
    TOTAL = 200

    def setUp(self):
        super().setUp()
        self.glossary_path = glossario._default_substitutions_path()
        save_glossary_entries(
            [(f"peca{i:03d}", f"pieza{i:03d}", "suggestion") for i in range(self.TOTAL)],
            self.glossary_path,
            create_backup=False,
        )
        self.editor = glossary_editor.open_glossary_editor(self.app)
        self.pump()
        self.win = self.editor.win

    def entries_on_disk(self):
        return load_glossary_entry_details(self.glossary_path, deduplicate=False)

    def answer_no_to_dialogs(self):
        """Faz o `askyesno` responder "nao". Devolve como restaurar."""
        original = glossary_editor.messagebox

        class Nao:
            showinfo = staticmethod(lambda *_a, **_k: None)
            showwarning = staticmethod(lambda *_a, **_k: None)
            showerror = staticmethod(lambda *_a, **_k: None)
            askyesno = staticmethod(lambda *_a, **_k: False)

        glossary_editor.messagebox = Nao

        def restaura():
            glossary_editor.messagebox = original

        return restaura

    def test_opening_returns_the_instance(self):
        """A assimetria que a skill tinha registrado como armadilha.

        Abrir o editor de traducoes devolvia a instancia e abrir este devolvia
        `None`, entao dirigi-lo de fora — nos testes ou na skill — exigia andar
        na arvore de widgets para alcancar qualquer coisa.
        """
        self.assertIsInstance(self.editor, glossary_editor.GlossaryEditor)
        self.assertIs(self.editor.win, self.win)

    # ------------------------------------------------ paginacao

    def test_paging_moves_the_list_and_stops_at_the_ends(self):
        self.assertEqual(self.editor.page_count(), 2)
        self.assertIsNotNone(self.button_containing("peca000"))

        self.editor.change_page(1)
        self.pump()
        self.assertEqual(self.editor.state.page_index, 1)
        self.assertIsNone(self.button_containing("peca000"), "a pagina nao trocou")
        self.assertIsNotNone(self.button_containing("peca150"))

        self.editor.change_page(1)
        self.assertEqual(self.editor.state.page_index, 1, "passou da ultima pagina")

        self.editor.change_page(-1)
        self.pump()
        self.assertEqual(self.editor.state.page_index, 0)
        self.editor.change_page(-1)
        self.assertEqual(self.editor.state.page_index, 0, "passou da primeira pagina")

    def test_changing_the_filter_goes_back_to_the_first_page(self):
        """Era um `lambda` com `page_index.update({"value": 0})` embutido.

        Sem o retorno a primeira pagina, trocar o filtro na pagina 2 mostraria
        uma pagina que a lista nova pode nem ter.
        """
        self.editor.change_page(1)
        self.assertEqual(self.editor.state.page_index, 1)

        self.editor.restart_at_first_page("Todas")
        self.pump()
        self.assertEqual(self.editor.state.page_index, 0)

    # ------------------------------------------------ entrada pre-preenchida

    def test_a_prefilled_entry_opens_ready_to_review(self):
        """O caminho que o editor de traducoes usa ao mandar um trecho para ca."""
        editor = glossary_editor.open_glossary_editor(
            self.app, initial_original="  bishop  ", initial_replacement="  bispo  "
        )
        self.pump()
        self.addCleanup(editor.win.destroy)

        self.assertEqual(editor.text_value(editor.orig_text), "bishop")
        self.assertEqual(editor.text_value(editor.new_text), "bispo")
        self.assertIsNone(editor.state.selected_index, "pre-preenchida e entrada nova")
        self.assertTrue(editor.state.dirty, "abriu pedindo revisao, e nao salva")

    # ------------------------------------------------ gravar uma entrada nova

    def test_saving_as_new_selects_the_entry_it_just_wrote(self):
        """`locate_saved_entry` procura pelo conteudo NORMALIZADO (garantia S7).

        A gravacao tira os espacos das pontas, entao reencontrar pelo texto que
        foi digitado nao acha nada — e a selecao cairia na entrada errada ou em
        nenhuma.
        """
        self.editor.set_text(self.editor.orig_text, "  bishop  ")
        self.editor.set_text(self.editor.new_text, "  bispo  ")
        self.click(self.button("Salvar como nova"))

        entradas = self.entries_on_disk()
        self.assertIn(("bishop", "bispo", "suggestion", 0, ""), entradas)
        self.assertIsNotNone(self.editor.state.selected_index, "nao reencontrou o que gravou")
        self.assertEqual(
            entradas[self.editor.state.selected_index],
            ("bishop", "bispo", "suggestion", 0, ""),
        )

    # ------------------------------------------------ fechar

    def test_closing_with_unsaved_changes_asks_before_discarding(self):
        self.editor.select_entry(0)
        self.editor.set_text(self.editor.new_text, "torre alta")
        self.editor.mark_dirty()
        self.assertTrue(self.editor.state.dirty, "a edicao nao marcou a janela como suja")

        restaura = self.answer_no_to_dialogs()
        try:
            self.editor.close_editor()
        finally:
            restaura()
        self.assertTrue(
            self.editor.win.winfo_exists(), "fechou apesar de o usuario ter dito nao"
        )

        self.editor.close_editor()      # o dialogo da suite responde "sim"
        self.pump()
        self.assertFalse(self.editor.win.winfo_exists())

    def test_closing_without_changes_does_not_ask(self):
        self.editor.close_editor()
        self.pump()
        self.assertFalse(self.editor.win.winfo_exists())
        self.assertNotIn("Alterações não salvas", self.dialogs.titles("askyesno"))


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

        # No ARQUIVO, e nao so em `app.glossary_substitutions`: a janela carrega
        # o recorte do par dela (garantia S11), entao a regra tem de existir onde
        # ela procura. Injetar so na lista do app deixava de valer quando o
        # editor passou a filtrar por idioma.
        save_glossary_entries(
            [("bispo", "alfil")],
            path=glossario._default_substitutions_path(),
            create_backup=False,
        )
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
        """O callback avisa que o arquivo mudou; a lista sai do DISCO.

        O editor de glossario grava antes de chamar, e o que esta janela precisa
        e o recorte do par dela (garantia S11) — que a lista passada no callback
        nao tem, porque aquela e o arquivo inteiro. Por isso o teste grava a regra
        nova e confere que ela chegou pela recarga, e nao pelo argumento.
        """
        self.editor.select_index(0)
        save_glossary_entries(
            [("torre", "roque")],
            path=glossario._default_substitutions_path(),
            create_backup=False,
        )
        self.editor.on_glossary_editor_change([("torre", "roque")])
        self.pump()

        self.assertEqual(self.editor.glossary, [("torre", "roque")])
        self.assertEqual(self.app.glossary_substitutions, [("torre", "roque")])

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


class EditorLanguagePairTests(EditorWindowTestCase):
    """Os dois seletores de idioma do editor.

    O que eles resolvem e uma queixa de uso: o banco guarda pares de idiomas
    misturados na mesma lista, e revisar uma traducao do espanhol achando que e
    do italiano nao produz erro nenhum — produz uma revisao errada.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "EN um", "PT um", "pt", "en")
        save_translation(cur, "EN dois", "PT dois", "pt", "en")
        save_translation(cur, "ES um", "PT tres", "pt", "es")
        save_translation(cur, "LEGADO um", "PT quatro", "pt")
        save_translation(cur, "EN outro destino", "FR um", "fr", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win

    def rotulos(self):
        """Os originais que a lista esta mostrando."""
        return sorted(linha[1] for linha in self.editor.state.rows)

    def escolher(self, menu, valor):
        """Escolhe no `CTkOptionMenu` como um clique escolheria.

        `set()` sozinho muda o texto e NAO dispara o `command` — usa-lo sem a
        chamada abaixo daria um teste que troca o rotulo e nunca recarrega a
        lista, e que passaria com o `command` desligado.
        """
        menu.set(valor)
        menu._command(valor)
        self.pump()

    def test_it_opens_showing_every_source(self):
        self.assertEqual(self.editor.source_menu.get(), edit_window.SOURCE_FILTER_ALL)
        self.assertEqual(self.rotulos(), ["EN dois", "EN um", "ES um", "LEGADO um"])

    def test_choosing_a_source_loads_only_that_pair(self):
        self.escolher(self.editor.source_menu, "Inglês")
        self.assertEqual(self.rotulos(), ["EN dois", "EN um"])

    def test_the_unknown_source_is_its_own_bucket(self):
        """"Não informado" nao pode ser um sinonimo de "Todos".

        No banco real quase tudo esta nesse balde, entao confundir os dois
        pareceria funcionar por muito tempo.
        """
        self.escolher(self.editor.source_menu, edit_window.UNKNOWN_SOURCE_LABEL)
        self.assertEqual(self.rotulos(), ["LEGADO um"])

    def test_the_count_follows_the_filter(self):
        self.escolher(self.editor.source_menu, "Espanhol")
        self.assertEqual(self.editor.state.total_rows, 1)
        self.assertIn("1 traduções", self.editor.page_label.cget("text"))

    def test_changing_the_target_switches_the_list_and_the_title(self):
        self.escolher(self.editor.target_menu, "Francês")
        self.assertEqual(self.editor.lang, "fr")
        self.assertEqual(self.rotulos(), ["EN outro destino"])
        self.assertIn("fr", self.editor.win.title())

    def test_the_two_filters_combine(self):
        self.escolher(self.editor.target_menu, "Francês")
        self.escolher(self.editor.source_menu, "Espanhol")
        self.assertEqual(self.rotulos(), [])

    def test_switching_goes_back_to_the_first_page(self):
        """A pagina 40 do par anterior nao quer dizer nada no novo.

        **Os dois pares precisam ter mais de uma pagina**, e a primeira versao
        deste teste nao tinha: com quatro linhas ao todo, `clamp_page` ja
        devolvia zero sozinho, e remover a linha que zera a pagina nao mudava
        nada. E o mesmo defeito que o ROADMAP registra tres vezes — o cenario
        usava o valor padrao, e com ele a producao quebrada e indistinguivel da
        correta.
        """
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for i in range(edit_window.PAGE_SIZE + 20):
            save_translation(cur, f"EN massa {i}", f"PT massa {i}", "pt", "en")
            save_translation(cur, f"ES massa {i}", f"PT massa es {i}", "pt", "es")
        conn.commit()
        conn.close()

        self.escolher(self.editor.source_menu, "Inglês")
        self.editor.change_page(1)
        self.assertEqual(self.editor.state.page_index, 1, "nao havia segunda pagina")

        self.escolher(self.editor.source_menu, "Espanhol")

        self.assertEqual(self.editor.state.page_index, 0)
        self.assertTrue(
            all(linha[1].startswith("ES") for linha in self.editor.state.rows),
            "a lista trouxe linhas do par anterior",
        )

    def test_the_edit_in_progress_is_saved_before_switching(self):
        """A linha aberta pertence ao par antigo; depois da troca ela sai da
        lista, e gravar depois seria gravar contra um item que sumiu."""
        self.escolher(self.editor.source_menu, "Inglês")
        self.editor.select_index(0)
        alvo = self.editor.current["id"]
        self.set_text(self.editor.trans_text, "PT um revisado")
        self.editor.set_dirty(True)

        self.escolher(self.editor.source_menu, "Espanhol")

        conn = initialize_database(self.db_path)
        try:
            gravado = conn.execute(
                "SELECT translated_comment FROM comments WHERE id = ?", (alvo,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(gravado, "PT um revisado")

    def test_the_source_filter_is_remembered_between_sessions(self):
        self.escolher(self.editor.source_menu, "Espanhol")
        self.editor.close_editor()
        self.pump()

        outro = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = outro.win
        self.addCleanup(outro.win.destroy)

        self.assertEqual(outro.source_menu.get(), "Espanhol")
        self.assertEqual(
            sorted(linha[1] for linha in outro.state.rows), ["ES um"]
        )

    def test_the_target_follows_the_main_window_on_every_opening(self):
        """Lembrar o destino faria quem marcasse "Francês" na janela principal
        abrir o editor em portugues, sem nada na tela explicando de onde veio."""
        self.escolher(self.editor.target_menu, "Francês")
        self.editor.close_editor()
        self.pump()

        self.app.target_language.set("pt")
        outro = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = outro.win
        self.addCleanup(outro.win.destroy)

        self.assertEqual(outro.lang, "pt")

    def test_the_status_bar_names_the_pair_of_the_selected_row(self):
        """Com "Origem: Todos" a lista mistura pares de proposito.

        E o unico momento em que o filtro nao responde de onde a linha veio —
        e e justamente quando saber importa. Sem isto, o dado esta no banco, foi
        buscado pela consulta e nao chega a tela.
        """
        self.editor.select_index(0)
        self.pump()
        self.assertIn("Inglês -> pt", self.editor.selection_label.cget("text"))

        alvo = next(
            i for i, linha in enumerate(self.editor.state.rows)
            if linha[1] == "LEGADO um"
        )
        self.editor.select_index(alvo)
        self.pump()
        self.assertIn(
            edit_window.UNKNOWN_SOURCE_LABEL, self.editor.selection_label.cget("text")
        )

    def test_clearing_the_selection_drops_the_pair(self):
        """Anunciar o par da linha que saiu da tela e pior do que nao anunciar."""
        self.editor.select_index(0)
        self.pump()
        self.editor.clear_current()
        self.pump()

        self.assertNotIn("Inglês", self.editor.selection_label.cget("text"))

    def test_no_two_options_mean_the_same_thing(self):
        """Duas opcoes com o mesmo efeito sao uma que nao funciona.

        O rotulo desconhecido cai em `None` — "todos" —, que e o unico destino
        seguro para um valor que a janela nao reconhece; por isso o teste
        percorre so os rotulos que ela mesma oferece.
        """
        rotulos = edit_window.source_filter_labels()
        codigos = [edit_window.source_filter_code(r) for r in rotulos]

        self.assertEqual(len(set(codigos)), len(rotulos), dict(zip(rotulos, codigos)))

    def test_all_and_unknown_are_not_the_same_code(self):
        self.assertIsNone(edit_window.source_filter_code(edit_window.SOURCE_FILTER_ALL))
        self.assertEqual(
            edit_window.source_filter_code(edit_window.UNKNOWN_SOURCE_LABEL), ""
        )


# ===========================================================================
# Secao 17 — navegacao dentro do filtro, e a propagacao que se anuncia
# ===========================================================================


class SourceFilterNavigationTests(EditorWindowTestCase):
    """Garantia R10: "Ir para ID" e "Proximo aviso" respeitam o filtro de origem.

    Os dois caminhos consultavam o banco SEM `source_language`, embora as funcoes
    aceitem o parametro e o `reload_rows` o passe. Com "Origem: Espanhol" ativo,
    digitar um ID ingles calculava o offset na lista NAO filtrada e selecionava
    uma linha espanhola arbitraria — sem mensagem. E a mesma classe do bug que a
    garantia R7 fechou: navegar pela posicao errada.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Muitas linhas inglesas primeiro (ids baixos) e algumas espanholas
        # depois: assim o offset calculado na tabela inteira cai fora da lista
        # espanhola, que e o que o bug produzia.
        for i in range(6):
            save_translation(cur, f"EN {i} rook rook rook", f"EN {i} torre", "pt", "en")
        for i in range(3):
            # Traducao igual ao original => aviso de qualidade garantido.
            texto = f"ES {i} la torre la torre"
            save_translation(cur, texto, texto, "pt", "es")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.win = tops[-1]

    def usar_origem(self, rotulo):
        self.editor.source_menu.set(rotulo)
        self.editor.change_language_filter()
        self.pump()

    def id_de(self, original):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT id FROM comments WHERE original_comment = ?", (original,)
            ).fetchone()[0]
        finally:
            conn.close()

    def original_carregado(self):
        return self.editor.current["orig"]

    # ------------------------------------------------------------ Ir para ID

    def test_an_id_outside_the_filter_is_refused_instead_of_landing_anywhere(self):
        """O bug: com o filtro espanhol, um ID ingles selecionava uma linha
        espanhola arbitraria e nada dizia."""
        self.usar_origem("Espanhol")
        alvo = self.id_de("EN 0 rook rook rook")

        self.editor.go_id_text.set(str(alvo))
        self.editor.go_to_id()
        self.pump()

        self.assertTrue(
            self.original_carregado().startswith("ES 0"),
            f"a selecao saiu do filtro: {self.original_carregado()!r}",
        )
        self.assertIn("não encontrado", self.editor.msg_label.cget("text"))

    def test_an_id_inside_the_filter_is_found(self):
        """Contraprova: dentro do filtro, a navegacao continua funcionando."""
        self.usar_origem("Espanhol")
        alvo = self.id_de("ES 2 la torre la torre")

        self.editor.go_id_text.set(str(alvo))
        self.editor.go_to_id()
        self.pump()

        self.assertTrue(self.original_carregado().startswith("ES 2"))

    def test_the_offset_is_computed_inside_the_filter(self):
        """A prova de que nao e sorte de pagina unica: sem o filtro na consulta,
        o offset de `ES 0` seria 6 (a posicao dele na tabela inteira), e nao 0."""
        self.usar_origem("Espanhol")
        alvo = self.id_de("ES 0 la torre la torre")

        self.editor.go_id_text.set(str(alvo))
        self.editor.go_to_id()
        self.pump()

        self.assertEqual(self.editor.state.selected_index, 0)

    # -------------------------------------------------------- Proximo aviso

    def test_the_next_warning_stays_inside_the_filter(self):
        """F7 varria as primeiras N linhas da tabela inteira usando o total
        FILTRADO como limite, e anunciava o aviso de uma linha que nao esta na
        tela."""
        self.usar_origem("Espanhol")
        self.editor.select_index(0)
        self.pump()

        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertTrue(
            self.original_carregado().startswith("ES"),
            f"F7 saiu do filtro: {self.original_carregado()!r}",
        )

    def test_with_no_warning_in_the_filter_it_says_so(self):
        """As linhas inglesas nao tem aviso; as espanholas, sim. Filtrando pelo
        ingles, a resposta certa e "nenhum" — e nao a linha espanhola."""
        self.usar_origem("Inglês")

        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertIn("Nenhum aviso QA", self.editor.msg_label.cget("text"))
        self.assertFalse(self.original_carregado().startswith("ES"))

    def test_the_scan_finds_the_warning_when_the_filter_has_one(self):
        self.usar_origem("Espanhol")

        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertIn("Aviso QA", self.editor.msg_label.cget("text"))


class BulkVerificationConfirmationTests(EditorWindowTestCase):
    """Garantia V1, na janela: a propagacao pergunta antes de marcar.

    Ela acontecia sem nenhuma pergunta e era anunciada depois — "N iguais
    também verificadas". O que ela marca sao N originais DIFERENTES que ninguem
    leu; nas traducoes curtas isso da por revisado o texto errado.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "Draw.", "Empate.", "pt", "en")
        save_translation(cur, "Checkmate.", "Empate.", "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        tops = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.win = tops[-1]

    def estados(self):
        conn = initialize_database(self.db_path)
        try:
            return dict(
                conn.execute(
                    "SELECT original_comment, verified FROM comments"
                ).fetchall()
            )
        finally:
            conn.close()

    def abrir_o_draw(self):
        for indice, linha in enumerate(self.editor.state.rows):
            if linha[1] == "Draw.":
                self.editor.select_index(indice)
                self.pump()
                return
        self.fail("a linha 'Draw.' nao esta na lista")

    def test_the_question_names_the_other_original(self):
        self.abrir_o_draw()

        self.click(self.button("Marcar como verificada"))

        perguntas = [m for k, _t, m in self.dialogs.calls if k == "askyesno"]
        self.assertEqual(len(perguntas), 1, "a propagacao devia ter perguntado")
        self.assertIn("Checkmate.", perguntas[0])
        self.assertIn("1 original(is) diferente(s)", perguntas[0])

    def test_saying_yes_propagates(self):
        self.dialogs.askyesno_result = True
        self.abrir_o_draw()

        self.click(self.button("Marcar como verificada"))

        self.assertEqual(self.estados(), {"Draw.": 1, "Checkmate.": 1})

    def test_saying_no_verifies_only_the_open_row(self):
        """O que o item existe para permitir: recusar a propagacao sem perder a
        verificacao que o usuario pediu."""
        self.dialogs.askyesno_result = False
        self.abrir_o_draw()

        self.click(self.button("Marcar como verificada"))

        self.assertEqual(self.estados(), {"Draw.": 1, "Checkmate.": 0})

    def test_a_translation_without_twins_asks_nothing(self):
        """A pergunta so aparece quando ha consequencia: um dialogo por
        verificacao viraria ruido e seria clicado no automatico."""
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "Good move.", "Bom lance.", "pt", "en")
        conn.commit()
        conn.close()
        self.editor.reload_rows()
        self.pump()

        for indice, linha in enumerate(self.editor.state.rows):
            if linha[1] == "Good move.":
                self.editor.select_index(indice)
                self.pump()
                break
        self.dialogs.calls.clear()

        self.click(self.button("Marcar como verificada"))

        self.assertEqual([k for k, _t, _m in self.dialogs.calls if k == "askyesno"], [])
        self.assertEqual(self.estados()["Good move."], 1)


class AddToGlossaryPopupTests(EditorWindowTestCase):
    """O popup "Adicionar ao glossario" (ROADMAP 17.10).

    Abria em tela cheia para tres campos e fechava sem validar nem avisar: os
    tres desfechos — gravou, campo vazio, gravacao falhou — terminavam na MESMA
    coisa, a janela fechada. Sem regra nenhuma no glossario e sem uma palavra na
    tela, o usuario tinha todo motivo para achar que gravou.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "The rook", "a torre", "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        self.editor.select_index(0)
        self.pump()

    def abrir_popup(self):
        antes = set(self.editor.win.winfo_children())
        self.editor.add_gloss_popup()
        self.pump()
        novos = [
            w
            for w in self.editor.win.winfo_children()
            if isinstance(w, tk.Toplevel) and w not in antes
        ]
        self.assertTrue(novos, "o popup nao abriu")
        self.pop = novos[-1]
        self.addCleanup(self._fechar_popup)
        return self.pop

    def _fechar_popup(self):
        try:
            if self.pop.winfo_exists():
                self.pop.destroy()
        except tk.TclError:
            pass

    def widgets_do_popup(self, kind):
        def desce(widget):
            yield widget
            for filho in widget.winfo_children():
                yield from desce(filho)

        return [w for w in desce(self.pop) if isinstance(w, kind)]

    def botao_adicionar(self):
        for widget in self.widgets_do_popup(edit_window.ctk.CTkButton):
            if (widget.cget("text") or "").strip() == "Adicionar":
                return widget
        self.fail("o botao Adicionar nao esta no popup")

    def entradas(self):
        return self.widgets_do_popup(edit_window.ctk.CTkEntry)

    def regras(self):
        return load_glossary_entry_details(
            glossario._default_substitutions_path(), prefer_db=False
        )

    def test_an_empty_original_warns_and_keeps_the_window_open(self):
        self.abrir_popup()
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(len(self.dialogs.messages("warning")), 1)
        # A mensagem tem de ser a do campo QUE FALTA. Sem exigir isso, o teste
        # passava tambem com a validacao do original removida: com os dois campos
        # vazios, a validacao da substituicao dispara e produz um aviso, uma
        # janela aberta e nenhuma regra gravada — indistinguivel do certo.
        self.assertIn("original", self.dialogs.messages("warning")[0])
        self.assertTrue(self.pop.winfo_exists(), "a janela nao pode fechar sem gravar")
        self.assertEqual(self.regras(), [])

    def test_an_empty_original_is_refused_even_with_a_replacement(self):
        """Um original vazio com substituicao preenchida so pode cair na
        validacao do original — nao ha outra que o pegue."""
        self.abrir_popup()
        self.entradas()[1].insert(0, "torre")
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(len(self.dialogs.messages("warning")), 1)
        self.assertIn("original", self.dialogs.messages("warning")[0])
        self.assertEqual(self.regras(), [])

    def test_an_empty_original_is_refused_in_a_cleanup_rule_too(self):
        """A regra de limpeza dispensa a substituicao, e nao o original: sem
        padrao nao ha o que casar, e a entrada seria lixo no arquivo."""
        self.abrir_popup()
        for widget in self.widgets_do_popup(edit_window.ctk.CTkSegmentedButton):
            widget.set("Limpeza")
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(len(self.dialogs.messages("warning")), 1)
        self.assertIn("original", self.dialogs.messages("warning")[0])
        self.assertEqual(self.regras(), [])

    def test_a_suggestion_without_a_replacement_warns(self):
        self.abrir_popup()
        self.entradas()[0].insert(0, "rook")
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(len(self.dialogs.messages("warning")), 1)
        self.assertIn("substituição", self.dialogs.messages("warning")[0])
        self.assertEqual(self.regras(), [])

    def test_a_complete_rule_is_written_and_the_window_closes(self):
        self.abrir_popup()
        self.entradas()[0].insert(0, "rook")
        self.entradas()[1].insert(0, "torre")
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(self.dialogs.messages("warning"), [])
        self.assertFalse(self.pop.winfo_exists(), "gravou: a janela devia fechar")
        self.assertEqual([orig for orig, *_r in self.regras()], ["rook"])

    def test_a_cleanup_rule_may_have_an_empty_replacement(self):
        """Elas existem justamente para remover o trecho (garantia S14)."""
        self.abrir_popup()
        self.entradas()[0].insert(0, "lixo de conversao")
        for widget in self.widgets_do_popup(edit_window.ctk.CTkSegmentedButton):
            widget.set("Limpeza")
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(self.dialogs.messages("warning"), [])
        self.assertEqual(
            [(orig, new) for orig, new, *_r in self.regras()],
            [("lixo de conversao", "")],
        )

    def test_a_write_failure_says_so_instead_of_closing(self):
        """Falha = janela fechada = usuario acha que gravou."""
        self.abrir_popup()
        self.entradas()[0].insert(0, "rook")
        self.entradas()[1].insert(0, "torre")
        original = edit_window.add_to_glossary
        edit_window.add_to_glossary = lambda *a, **k: False
        self.addCleanup(setattr, edit_window, "add_to_glossary", original)
        self.dialogs.calls.clear()

        self.botao_adicionar().invoke()
        self.pump()

        self.assertEqual(len(self.dialogs.messages("error")), 1)
        self.assertTrue(self.pop.winfo_exists())

    def test_it_does_not_open_maximized(self):
        """Tres campos e um botao. Maximizado, o formulario ficava num canto de
        uma janela do tamanho da tela, cobrindo o editor — e o texto que o
        usuario acabou de selecionar para copiar dali."""
        chamadas = []
        original = edit_window.bring_window_to_front
        edit_window.bring_window_to_front = (
            lambda win, parent=None, maximize=False: chamadas.append(maximize)
        )
        self.addCleanup(setattr, edit_window, "bring_window_to_front", original)

        self.editor.add_gloss_popup()
        self.pump()
        self.pop = [
            w for w in self.editor.win.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        self.addCleanup(self._fechar_popup)

        self.assertEqual(chamadas, [False])


class HistoryWindowStaysOutOfTheWayTests(EditorWindowTestCase):
    """A janela de historico e modeless PARA QUE a lista continue clicavel.

    Ela abria maximizada, cobrindo exatamente a lista que a garantia R3 existe
    para manter acessivel: maximizar anulava na tela o que o `transient` sem
    `grab_set` garante no codigo (ROADMAP 17.10).
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "The rook", "a torre", "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        self.editor.select_index(0)
        self.pump()

    def test_it_does_not_open_maximized(self):
        chamadas = []
        original = history_window.bring_window_to_front
        history_window.bring_window_to_front = (
            lambda win, parent=None, maximize=False: chamadas.append(maximize)
        )
        self.addCleanup(
            setattr, history_window, "bring_window_to_front", original
        )

        janela = history_window.HistoryWindow(
            self.editor, self.editor.current["id"], "The rook"
        )
        self.pump()
        self.addCleanup(janela.win.destroy)

        self.assertEqual(chamadas, [False])


# ===========================================================================
# Secao 18 — o filtro por arquivo e a ordem de leitura, na janela
# ===========================================================================


class FileFilterLabelTests(unittest.TestCase):
    """Os rotulos do menu de arquivos. Funcao pura, sem display."""

    def test_the_label_is_the_file_name(self):
        rotulos = edit_window.occurrence_file_labels(
            [os.path.join("C:", "livro", "cap01.pgn")]
        )
        self.assertEqual(list(rotulos), ["cap01.pgn"])

    def test_two_files_with_the_same_name_gain_the_folder(self):
        """Sem isto, duas obras apareceriam no menu com o mesmo texto e escolher
        uma seria sorteio."""
        a = os.path.join("C:", "Livro A", "cap01.pgn")
        b = os.path.join("C:", "Livro B", "cap01.pgn")

        rotulos = edit_window.occurrence_file_labels([a, b])

        self.assertEqual(len(rotulos), 2)
        self.assertEqual(sorted(rotulos.values()), sorted([a, b]))
        self.assertIn("Livro A/cap01.pgn", rotulos)

    def test_the_same_folder_name_in_two_trees_falls_back_to_the_path(self):
        """A pasta imediata tambem pode repetir. O caminho inteiro e feio e e a
        unica coisa que sempre distingue."""
        a = os.path.join("C:", "x", "livro", "cap01.pgn")
        b = os.path.join("C:", "y", "livro", "cap01.pgn")

        rotulos = edit_window.occurrence_file_labels([a, b])

        self.assertEqual(len(rotulos), 2)
        self.assertEqual(sorted(rotulos.values()), sorted([a, b]))

    def test_the_order_of_the_menu_follows_the_bank(self):
        """O banco devolve por nome de arquivo, que e como capitulo se ordena."""
        caminhos = [f"/livro/cap0{i}.pgn" for i in (1, 2, 3)]
        self.assertEqual(
            list(edit_window.occurrence_file_labels(caminhos)),
            ["cap01.pgn", "cap02.pgn", "cap03.pgn"],
        )


class OccurrenceContextLabelTests(unittest.TestCase):
    """O rodape que diz de onde o original aberto veio."""

    def test_no_occurrence_says_nothing(self):
        """As linhas gravadas antes desta versao nao tem procedencia, e um rotulo
        fixo apareceria em 201.607 delas sem informar nada."""
        self.assertEqual(edit_window.format_occurrence_context([], 0), "")

    def test_the_file_the_game_and_the_move_are_named(self):
        texto = edit_window.format_occurrence_context(
            [(os.path.join("C:", "livro", "cap07.pgn"), 3, 41, 24)], 1
        )

        self.assertIn("cap07.pgn", texto)
        self.assertIn("partida 3", texto)
        self.assertIn("lance 24", texto)

    def test_the_comment_index_gives_way_to_the_move(self):
        """Um localizador por posicao. O lance e o que um leitor de xadrez usa; o
        indice do comentario e a ordem da extracao, que ninguem ve. Levar os dois
        somava ~90 px a uma linha que ja estourava a faixa."""
        texto = edit_window.format_occurrence_context(
            [(os.path.join("C:", "livro", "cap07.pgn"), 3, 41, 24)], 1
        )

        self.assertNotIn("comentário", texto)

    def test_without_a_move_the_comment_index_is_the_locator(self):
        """Um comentario antes do primeiro lance nao tem lance — e "lance 0" seria
        uma medicao que ninguem fez. Sem o lance, o indice e o que resta para achar
        a linha na obra."""
        texto = edit_window.format_occurrence_context(
            [(os.path.join("C:", "livro", "cap07.pgn"), 1, 2, None)], 1
        )

        self.assertNotIn("lance", texto)
        self.assertIn("comentário 2", texto)

    def test_the_reused_translation_says_in_how_many_positions(self):
        """A informacao que muda o que o revisor faz: editar aqui muda as doze."""
        texto = edit_window.format_occurrence_context([("/livro/cap01.pgn", 1, 1, 1)], 12)

        self.assertIn("e mais 11 posições (a mesma tradução)", texto)

    def test_a_single_extra_position_is_singular(self):
        texto = edit_window.format_occurrence_context([("/livro/cap01.pgn", 1, 1, 1)], 2)
        self.assertIn("e mais 1 posição (a mesma tradução)", texto)

    def test_a_single_position_does_not_claim_reuse(self):
        texto = edit_window.format_occurrence_context([("/l/cap01.pgn", 1, 1, 1)], 1)
        self.assertNotIn("a mesma tradução", texto)
        self.assertNotIn("e mais", texto)

    def test_only_one_position_is_spelled_out(self):
        """O rodape divide a linha com o rotulo "Original:". Com duas posicoes por
        extenso, o texto passava da linha e o Tk cortava o COMECO dele — o nome do
        arquivo, que e a parte que responde a pergunta. Encontrado numa captura de
        tela do app, e nao por teste nenhum."""
        self.assertEqual(edit_window.OCCURRENCE_PREVIEW_LIMIT, 1)


class EditorFileFilterTests(EditorWindowTestCase):
    """O filtro por arquivo e a ordem de leitura da obra, na janela de verdade."""

    module = edit_window

    def setUp(self):
        super().setUp()
        self.arquivo = str(Path(self.base) / "cap01.pgn")
        self.outro = str(Path(self.base) / "cap02.pgn")

        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Inseridos fora da ordem de leitura, que e o que acontece de verdade: a
        # ordem de insercao e a ordem em que a API respondeu.
        for texto in ("C terceiro", "A primeiro", "B segundo", "sem arquivo"):
            save_translation(cur, texto, f"T {texto}", "pt", "en")
        conn.commit()
        ids = resolve_comment_ids(
            cur, "pt", ["A primeiro", "B segundo", "C terceiro"], "en"
        )
        record_occurrences(
            cur,
            self.arquivo,
            [
                (1, 1, 1, "A primeiro"),
                (2, 1, 3, "B segundo"),
                (3, 2, 12, "C terceiro"),
            ],
            ids,
        )
        record_occurrences(
            cur, self.outro, [(1, 1, 1, "C terceiro")], ids
        )
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]

    def rotulo_de(self, caminho):
        for rotulo, valor in self.editor.file_options.items():
            if valor == caminho:
                return rotulo
        self.fail(f"{caminho} nao esta no menu: {list(self.editor.file_options)}")

    def usar_arquivo(self, caminho):
        self.editor.file_menu.set(self.rotulo_de(caminho))
        self.editor.change_file_filter()
        self.pump()

    def originais(self):
        return [linha[1] for linha in self.editor.state.rows]

    # ------------------------------------------------------------- o menu

    def test_the_menu_lists_the_files_of_the_pair(self):
        self.assertEqual(
            self.editor.file_menu.cget("values"),
            [edit_window.FILE_FILTER_ALL, "cap01.pgn", "cap02.pgn"],
        )

    def test_it_opens_showing_every_file(self):
        """O filtro nao pode comecar escondendo o acervo: as linhas sem
        procedencia — as 201.607 do banco real — so aparecem em "Todos"."""
        self.assertEqual(self.editor.file_menu.get(), edit_window.FILE_FILTER_ALL)
        self.assertIsNone(self.editor.selected_source_file())
        self.assertIn("sem arquivo", self.originais())

    # ------------------------------------------- filtro e ordem de leitura

    def test_choosing_a_file_shows_the_work_in_reading_order(self):
        """O item inteiro da secao 18: `ORDER BY id` nao e ordem de leitura."""
        self.assertEqual(
            self.originais(),
            ["C terceiro", "A primeiro", "B segundo", "sem arquivo"],
        )

        self.usar_arquivo(self.arquivo)

        self.assertEqual(
            self.originais(), ["A primeiro", "B segundo", "C terceiro"]
        )

    def test_the_other_book_is_left_out(self):
        self.usar_arquivo(self.outro)
        self.assertEqual(self.originais(), ["C terceiro"])

    def test_the_counts_follow_the_file(self):
        self.usar_arquivo(self.outro)
        self.assertEqual(self.editor.state.total_rows, 1)
        self.assertIn("Todas: 1", self.editor.counts_label.cget("text"))

    def test_the_label_announces_the_reading_order(self):
        """Uma lista que reordena sem dizer nada parece embaralhada."""
        self.assertNotIn("ordem de leitura", self.editor.page_label.cget("text"))

        self.usar_arquivo(self.arquivo)

        self.assertIn("ordem de leitura", self.editor.page_label.cget("text"))

    def test_going_back_to_every_file_restores_the_id_order(self):
        self.usar_arquivo(self.arquivo)
        self.editor.file_menu.set(edit_window.FILE_FILTER_ALL)
        self.editor.change_file_filter()
        self.pump()

        self.assertEqual(self.editor.selected_order(), edit_window.ORDER_BY_ID)
        self.assertEqual(
            self.originais(),
            ["C terceiro", "A primeiro", "B segundo", "sem arquivo"],
        )

    # ------------------------------------------------- navegar dentro dela

    def test_go_to_id_lands_on_the_right_row_in_reading_order(self):
        """A classe de defeito da garantia R10, pelo lado da ordem.

        "C terceiro" e o primeiro id do banco e o ULTIMO da obra: com o offset
        contado por id, a janela iria para a posicao 0 e selecionaria "A
        primeiro" — sem erro nenhum na tela.
        """
        self.usar_arquivo(self.arquivo)
        conn = initialize_database(self.db_path)
        alvo = conn.execute(
            "SELECT id FROM comments WHERE original_comment = 'C terceiro'"
        ).fetchone()[0]
        conn.close()

        self.editor.go_id_text.set(str(alvo))
        self.editor.go_to_id()
        self.pump()

        self.assertEqual(self.editor.current["orig"], "C terceiro")
        self.assertEqual(self.editor.state.selected_index, 2)

    def test_an_id_outside_the_file_is_refused(self):
        """O mesmo criterio do filtro de origem (R10): fora do filtro, a resposta
        e "nao encontrado", e nao uma linha qualquer."""
        self.usar_arquivo(self.outro)

        conn = initialize_database(self.db_path)
        alvo = conn.execute(
            "SELECT id FROM comments WHERE original_comment = 'sem arquivo'"
        ).fetchone()[0]
        conn.close()

        self.editor.go_id_text.set(str(alvo))
        self.editor.go_to_id()
        self.pump()

        self.assertIn("não encontrado", self.editor.msg_label.cget("text"))
        self.assertEqual(self.editor.current["orig"], "C terceiro")

    def test_the_next_warning_stays_inside_the_file(self):
        """F7 varre a lista FILTRADA. Sem o arquivo na consulta, ele varreria as
        primeiras N linhas da tabela inteira usando o total da obra como limite."""
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Traducao igual ao original => aviso garantido, e so no arquivo de fora.
        save_translation(cur, "la torre la torre", "la torre la torre", "pt", "en")
        conn.commit()
        conn.close()

        self.usar_arquivo(self.arquivo)
        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertIn("Nenhum aviso QA", self.editor.msg_label.cget("text"))
        self.assertIn(self.editor.current["orig"], self.originais())

    # ------------------------------------------------------ o que a tela diz

    def test_the_footer_says_where_the_open_original_was_read(self):
        self.usar_arquivo(self.arquivo)
        self.editor.select_index(2)
        self.pump()

        texto = self.editor.origin_label.cget("text")
        self.assertIn("cap01.pgn", texto)
        self.assertIn("partida 2", texto)
        self.assertIn("lance 12", texto)

    def test_the_footer_prefers_the_file_being_read(self):
        """"C terceiro" esta nos dois capitulos. Lendo o cap02, o rodape mostra a
        posicao NELE — a do cap01 e verdade e responde outra pergunta.

        Uma posicao cabe no rodape (a outra vira contagem), entao aqui a afirmacao
        e exclusiva: o cap01 nao pode aparecer. Enquanto o rodape mostrava duas,
        "cap02 aparece no texto" valia com e sem a preferencia — foi o que a
        mutacao mostrou.
        """
        self.usar_arquivo(self.outro)
        self.editor.select_index(0)
        self.pump()

        texto = self.editor.origin_label.cget("text")
        self.assertIn("cap02.pgn", texto)
        self.assertNotIn("cap01.pgn", texto)
        self.assertIn("e mais 1 posição", texto)

    def test_a_row_without_provenance_leaves_the_footer_empty(self):
        indice = self.originais().index("sem arquivo")
        self.editor.select_index(indice)
        self.pump()

        self.assertEqual(self.editor.origin_label.cget("text"), "")

    def test_without_provenance_the_line_leaves_the_grid(self):
        """Um rotulo vazio ainda ocupa uma linha, e as linhas sem procedencia sao a
        maioria de um banco antigo: seria altura roubada do comentario em 201.607
        delas para nao dizer nada."""
        self.usar_arquivo(self.arquivo)
        self.editor.select_index(0)
        self.pump()
        self.assertEqual(self.editor.origin_label.winfo_manager(), "grid")

        self.editor.file_menu.set(edit_window.FILE_FILTER_ALL)
        self.editor.change_file_filter()
        indice = self.originais().index("sem arquivo")
        self.editor.select_index(indice)
        self.pump()

        self.assertEqual(self.editor.origin_label.winfo_manager(), "")

    def test_the_footer_is_cleared_when_no_row_is_open(self):
        """A procedencia da linha anterior, sem linha aberta, e uma afirmacao
        sobre o vazio — o mesmo criterio do par de idiomas."""
        self.usar_arquivo(self.arquivo)
        self.editor.select_index(0)
        self.pump()
        self.assertNotEqual(self.editor.origin_label.cget("text"), "")

        self.editor.clear_current()
        self.pump()

        self.assertEqual(self.editor.origin_label.cget("text"), "")

    # --------------------------------------------------- a escolha lembrada

    def test_the_chosen_file_is_remembered_by_path(self):
        """Revisar um livro leva dias; reabrir no capitulo em que se estava e o
        ponto. Guardado pelo CAMINHO porque o rotulo depende de quais outros
        arquivos existem hoje."""
        self.usar_arquivo(self.arquivo)

        gravado = settings.load_settings()["editor"]["file_filter"]

        self.assertEqual(gravado, self.arquivo)

    def test_a_remembered_file_that_no_longer_exists_falls_back_to_all(self):
        """Uma lista vazia sem explicacao e o pior desfecho de um filtro
        lembrado."""
        self.editor.refresh_file_filter(restore=str(Path(self.base) / "sumiu.pgn"))
        self.pump()

        self.assertEqual(self.editor.file_menu.get(), edit_window.FILE_FILTER_ALL)
        self.assertIsNone(self.editor.selected_source_file())

    def test_changing_the_pair_rebuilds_the_file_list(self):
        """Um par sem execucao nenhuma nao tem obra, e manter os arquivos do par
        anterior daria um filtro que devolve zero linhas sempre."""
        self.usar_arquivo(self.arquivo)

        self.editor.target_menu.set("Inglês")
        self.editor.change_language_filter()
        self.pump()

        self.assertEqual(
            self.editor.file_menu.cget("values"), [edit_window.FILE_FILTER_ALL]
        )
        self.assertIsNone(self.editor.selected_source_file())

    def test_the_source_filter_narrows_the_file_list(self):
        """O menu de arquivos e do PAR: um arquivo do espanhol no menu do ingles
        seria um filtro que nao devolve linha nenhuma."""
        self.editor.source_menu.set("Espanhol")
        self.editor.change_language_filter()
        self.pump()

        self.assertEqual(
            self.editor.file_menu.cget("values"), [edit_window.FILE_FILTER_ALL]
        )

    # ------------------------------------------------- todos os filtros juntos

    def test_every_list_query_gets_the_same_filters(self):
        """A garantia R10 nasceu de duas consultas que recebiam um filtro a menos.

        Este teste olha o CONTRATO em vez de um sintoma: o que a janela manda para
        o banco sai de um lugar so, e o filtro por arquivo entra nele — senao a
        proxima consulta acrescentada volta a esquecer.
        """
        self.usar_arquivo(self.arquivo)

        filtros = self.editor.list_filters()
        consulta = self.editor.list_query_args()

        self.assertEqual(filtros["source_file"], self.arquivo)
        self.assertEqual(consulta["order"], edit_window.ORDER_BY_OCCURRENCE)
        self.assertEqual(
            set(consulta) - set(filtros), {"order"}
        )


# ===========================================================================
# Secao 19 — o fluxo do tradutor profissional, na janela
# ===========================================================================


class RowLabelTests(unittest.TestCase):
    """O rotulo da linha da lista (ROADMAP 19, item 4). Funcao pura."""

    def linha(self, verified=0, origem="en", aviso=0):
        return (7, "the rook", "a torre", verified, "", "", "", origem, "pt", aviso)

    def test_the_qa_marker_appears_only_with_a_warning(self):
        """Sem o marcador, achar as linhas com aviso exigia trocar o filtro para
        "Avisos QA" — e ai a lista deixava de mostrar o resto da obra."""
        self.assertIn("QA", edit_window.row_label(self.linha(aviso=1)))
        self.assertNotIn("QA", edit_window.row_label(self.linha(aviso=0)))

    def test_the_marker_comes_from_the_column_and_not_from_the_text(self):
        """A mesma resposta que o filtro usa (garantia R6). Aqui a traducao e
        identica ao original — que geraria aviso se o rotulo reavaliasse o texto — e
        a coluna diz zero: quem manda e a coluna."""
        linha = (7, "igual", "igual", 0, "", "", "", "en", "pt", 0)

        self.assertNotIn("QA", edit_window.row_label(linha))

    def test_the_source_language_is_named(self):
        """Em "Origem: Todos" nao havia como saber de que lingua a linha veio sem
        carrega-la."""
        self.assertIn("Inglês", edit_window.row_label(self.linha(origem="en")))
        self.assertIn("Espanhol", edit_window.row_label(self.linha(origem="es")))

    def test_a_row_without_the_new_fields_still_renders(self):
        """As tuplas de sete campos existem nos testes e no historico da janela: elas
        nao ganham marcador nem idioma, em vez de ganharem "sem aviso"."""
        curta = (7, "the rook", "a torre", 1, "", "", "")

        rotulo = edit_window.row_label(curta)

        self.assertIn("#7", rotulo)
        self.assertNotIn("QA", rotulo)

    def test_the_status_and_the_id_survive_the_new_fields(self):
        rotulo = edit_window.row_label(self.linha(verified=1, aviso=1))

        self.assertTrue(rotulo.startswith("OK  #7"))


class EditorShortcutTests(EditorWindowTestCase):
    """`Ctrl+F` no texto e `Ctrl+L` na lista (ROADMAP 19, item 2)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "The rook is strong", "A torre e forte", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]

    def focados(self):
        """Quais campos receberam `focus_set`, interceptando a chamada.

        `focus_get()` nao serve aqui: a janela da suite nao e mapeada (o `root` fica
        `withdraw`n para nada piscar na tela), e o Tk nao entrega foco a janela nao
        visivel — ele devolve `None` para os dois casos, certo e errado. Interceptar
        a chamada e a mesma decisao que a suite ja tomou para a geometria (SPEC,
        secao 9, nota de 17.11): confere-se a decisao no codigo, nao o efeito do
        gerenciador de janelas.
        """
        chamados = []
        for nome, campo in (
            ("texto", self.editor.editor_find_entry),
            ("lista", self.editor.search_entry),
        ):
            original = campo.focus_set
            campo.focus_set = (
                lambda n=nome, o=original: (chamados.append(n), o())[0]
            )
            self.addCleanup(setattr, campo, "focus_set", original)
        return chamados

    def test_control_f_focuses_the_search_inside_the_text(self):
        """Caindo no campo da lista, `Ctrl+F` fazia a coisa mais destrutiva
        possivel: a busca da lista TROCA a pagina, e o revisor perdia o lugar."""
        chamados = self.focados()

        self.editor.focus_editor_find()

        self.assertEqual(chamados, ["texto"])

    def test_control_l_focuses_the_search_of_the_list(self):
        chamados = self.focados()

        self.editor.focus_search()

        self.assertEqual(chamados, ["lista"])

    def test_both_shortcuts_are_bound_to_the_right_method(self):
        """O que o teste acima nao pega: os dois metodos existem e funcionam, e a
        LIGACAO pode ter ficado trocada."""
        self.assertIn("focus_editor_find", self.editor.win.bind("<Control-f>"))
        self.assertIn("focus_search", self.editor.win.bind("<Control-l>"))


class EditorBackStackTests(EditorWindowTestCase):
    """Voltar de onde a busca tirou o revisor (ROADMAP 19, item 3)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for i in range(6):
            save_translation(cur, f"comentario {i} rook", f"traducao {i} torre", "pt", "en")
        save_translation(cur, "outpost eterno", "casa avancada", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]

    def buscar(self, texto):
        self.editor.search_text.set(texto)
        self.editor.apply_search()
        self.pump()

    def test_searching_and_going_back_restores_the_line_and_the_search(self):
        """O caso do item: usar a busca como concordancia descartava a pagina em que
        se estava. Guardar so o id nao bastaria — o id de antes nao esta no resultado
        da busca nova, entao os FILTROS voltam junto."""
        self.editor.select_index(2)
        self.pump()
        original = self.editor.current["orig"]

        self.buscar("outpost")
        self.assertEqual(self.editor.current["orig"], "outpost eterno")

        self.editor.go_back()
        self.pump()

        self.assertEqual(self.editor.current["orig"], original)
        self.assertEqual(self.editor.state.active_search, "")

    def test_walking_to_the_next_line_does_not_stack(self):
        """Um "voltar" que andasse linha por linha nao devolveria nada a quem revisa
        um livro: a pilha e dos SALTOS."""
        self.editor.select_index(0)
        self.pump()
        self.editor.navigate(1)
        self.editor.navigate(1)
        self.pump()

        self.assertEqual(self.editor.state.history_stack, [])

    def test_going_back_with_nothing_stacked_says_so(self):
        self.editor.select_index(0)
        self.pump()

        self.assertFalse(self.editor.go_back())
        self.assertIn("Nada para voltar", self.editor.msg_label.cget("text"))

    def test_the_stack_survives_two_jumps_and_unwinds_in_order(self):
        self.editor.select_index(0)
        self.pump()
        primeiro = self.editor.current["orig"]
        self.buscar("comentario 3")
        segundo = self.editor.current["orig"]
        self.buscar("outpost")

        self.editor.go_back()
        self.pump()
        self.assertEqual(self.editor.current["orig"], segundo)

        self.editor.go_back()
        self.pump()
        self.assertEqual(self.editor.current["orig"], primeiro)

    def test_a_line_that_vanished_does_not_block_the_stack(self):
        """Um retrato que nao da para repor — a linha foi apagada por outra janela —
        nao pode travar o "voltar": o PROXIMO da pilha assume.

        Sao dois retratos de proposito, e o de cima e o morto: com um so, desistir no
        primeiro e continuar dao o mesmo observavel ("Nada para voltar"), e o teste
        passava com as duas producoes — foi o que a mutacao mostrou.
        """
        self.editor.select_index(0)
        self.pump()
        vivo = self.editor.current["orig"]

        self.buscar("comentario 3")
        morto = self.editor.current["id"]
        self.buscar("outpost")

        conn = initialize_database(self.db_path)
        conn.execute("DELETE FROM comments WHERE id = ?", (morto,))
        conn.commit()
        conn.close()

        self.assertTrue(self.editor.go_back())
        self.pump()
        self.assertEqual(self.editor.current["orig"], vivo)

    def test_the_stack_is_capped(self):
        """Uma sessao de revisao dura horas, e cada salto empilha um retrato."""
        self.editor.select_index(0)
        self.pump()
        self.addCleanup(
            setattr, edit_window, "HISTORY_STACK_LIMIT",
            edit_window.HISTORY_STACK_LIMIT,
        )
        edit_window.HISTORY_STACK_LIMIT = 3

        for i in range(6):
            self.buscar(f"comentario {i % 5}")

        self.assertLessEqual(len(self.editor.state.history_stack), 3)


class SideBySideLayoutTests(EditorWindowTestCase):
    """Lado a lado opcional (ROADMAP 19, item 1)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "The rook", "a torre", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]

    def test_it_starts_stacked(self):
        """O comportamento de sempre: original acima da traducao."""
        self.assertFalse(self.editor.side_by_side)
        self.assertEqual(str(self.editor.texts_pane.cget("orient")), "vertical")

    def test_the_toggle_changes_the_orientation(self):
        self.editor.toggle_side_by_side()
        self.pump()

        self.assertTrue(self.editor.side_by_side)
        self.assertEqual(str(self.editor.texts_pane.cget("orient")), "horizontal")

    def test_the_text_survives_the_toggle(self):
        """`configure(orient=...)` em vez de reconstruir os paineis: o texto
        digitado, o desfazer e a selecao vivem DENTRO dos widgets."""
        self.editor.select_index(0)
        self.pump()
        self.set_text(self.editor.trans_text, "traducao em andamento")

        self.editor.toggle_side_by_side()
        self.pump()

        self.assertEqual(
            self.text_value(self.editor.trans_text), "traducao em andamento"
        )

    def test_the_choice_is_remembered(self):
        self.editor.toggle_side_by_side()
        self.pump()

        self.assertTrue(settings.load_settings()["editor"]["side_by_side"])

    def test_each_orientation_has_its_own_sash_key(self):
        """O divisor horizontal mede largura e o vertical mede altura: reaproveitar o
        numero de um no outro poria o divisor num lugar sem relacao com o escolhido."""
        vertical = self.editor.texts_sash_key()
        self.editor.toggle_side_by_side()
        horizontal = self.editor.texts_sash_key()

        self.assertNotEqual(vertical, horizontal)
        self.assertEqual((vertical, horizontal), ("texts_sash_y", "texts_sash_x"))

    def test_the_saved_sash_uses_the_axis_of_the_active_orientation(self):
        """`sash_coord` devolve o par, e o outro valor e sempre 1: gravar sempre o x
        deixaria o divisor vertical com a posicao inutil."""
        chaves = [
            item for item in self._sashes_gravados() if item[0].startswith("texts_")
        ]
        self.assertEqual(len(chaves), 1)
        self.assertEqual(chaves[0][3], 1, "vertical grava no eixo y")

        self.editor.toggle_side_by_side()
        chaves = [
            item for item in self._sashes_gravados() if item[0].startswith("texts_")
        ]
        self.assertEqual(chaves[0][3], 0, "horizontal grava no eixo x")

    def _sashes_gravados(self):
        """Os `sashes` que a janela passa para `save_window_section`."""
        capturado = {}
        original = edit_window.save_window_section

        def espiao(local_settings, section, values, window=None, sashes=()):
            capturado["sashes"] = sashes
            return original(local_settings, section, values, window=window, sashes=sashes)

        edit_window.save_window_section = espiao
        try:
            self.editor.save_editor_settings()
        finally:
            edit_window.save_window_section = original
        return capturado["sashes"]


class BatchSelectionTests(EditorWindowTestCase):
    """Selecao em lote na lista (ROADMAP 19, item 9)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for i in range(4):
            save_translation(cur, f"orig {i}", f"trad {i}", "pt", "en")
        conn.commit()
        self.ids = [r[0] for r in cur.execute("SELECT id FROM comments ORDER BY id")]
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]

    def verificadas(self):
        conn = initialize_database(self.db_path)
        try:
            return [
                r[0] for r in conn.execute(
                    "SELECT id FROM comments WHERE verified = 1 ORDER BY id"
                )
            ]
        finally:
            conn.close()

    def test_nothing_is_selected_at_first_and_the_actions_are_off(self):
        """Um botao "Verificar" clicavel com nada marcado nao tem resposta boa."""
        self.assertEqual(self.editor.state.selected_ids, set())
        self.assertEqual(self.editor.btn_batch_verify.cget("state"), "disabled")
        self.assertIn("nenhuma", self.editor.batch_label.cget("text"))

    def test_toggling_a_row_selects_it_by_id(self):
        self.editor.toggle_row_selection(1)

        self.assertEqual(self.editor.state.selected_ids, {self.ids[1]})
        self.assertEqual(self.editor.btn_batch_verify.cget("state"), "normal")
        self.assertIn("1 selecionada", self.editor.batch_label.cget("text"))

    def test_selecting_the_page_takes_every_row(self):
        self.editor.select_page_rows()

        self.assertEqual(self.editor.state.selected_ids, set(self.ids))

    def test_verifying_the_selection_marks_only_those(self):
        self.editor.toggle_row_selection(0)
        self.editor.toggle_row_selection(2)
        self.dialogs.askyesno_result = True

        self.editor.verify_selected_rows()
        self.pump()

        self.assertEqual(self.verificadas(), [self.ids[0], self.ids[2]])

    def test_verifying_asks_first(self):
        """Marcar 100 linhas de uma vez e irreversivel por clique: a pergunta e a
        unica defesa, e ela diz quantas."""
        self.editor.select_page_rows()
        self.dialogs.askyesno_result = False

        self.editor.verify_selected_rows()
        self.pump()

        self.assertEqual(self.verificadas(), [])
        self.assertTrue(
            any("4 tradução" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_the_confirmation_says_that_equal_translations_are_untouched(self):
        """A propagacao tem confirmacao propria (garantia V1). Encadea-la aqui daria
        100 dialogos, ou — pior — nenhum."""
        self.editor.toggle_row_selection(0)
        self.dialogs.askyesno_result = False
        self.editor.verify_selected_rows()

        self.assertTrue(
            any("NÃO" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_the_selection_is_cleared_after_verifying(self):
        self.editor.toggle_row_selection(0)
        self.dialogs.askyesno_result = True

        self.editor.verify_selected_rows()
        self.pump()

        self.assertEqual(self.editor.state.selected_ids, set())

    def test_changing_the_pair_drops_the_selection(self):
        """Ela e por id, e um id do par anterior nao esta na lista nova: "Verificar"
        marcaria linhas que o revisor nao ve."""
        self.editor.select_page_rows()

        self.editor.target_menu.set("Inglês")
        self.editor.change_language_filter()
        self.pump()

        self.assertEqual(self.editor.state.selected_ids, set())

    def test_exporting_the_selection_writes_only_those_rows(self):
        self.editor.toggle_row_selection(1)
        destino = Path(self.base) / "selecao.csv"
        self.file_dialogs.answer = str(destino)

        self.editor.export_selected_rows()
        self.pump()

        linhas = destino.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(linhas), 2, linhas)
        self.assertTrue(linhas[1].startswith(f"{self.ids[1]},"))


class ReviewStatusEditorTests(EditorWindowTestCase):
    """Rejeitada, em duvida e a nota do revisor, na janela (item 12)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        save_translation(cur, "the bishop", "o bispo", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        self.editor.select_index(0)
        self.pump()

    def status_no_banco(self, original):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT review_status, reviewer_note, verified FROM comments"
                " WHERE original_comment = ?",
                (original,),
            ).fetchone()
        finally:
            conn.close()

    def test_rejecting_saves_the_status_and_the_note_together(self):
        """Na tela e um gesto so: quem rejeita escreve por que."""
        self.editor.reviewer_note_text.set("termo inventado")

        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        self.assertEqual(
            self.status_no_banco("the rook"), ("rejected", "termo inventado", 0)
        )

    def test_the_note_of_the_open_line_is_loaded(self):
        self.editor.reviewer_note_text.set("ver com o autor")
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()

        self.editor.select_index(1)
        self.pump()
        self.assertEqual(self.editor.reviewer_note_text.get(), "")

        self.editor.select_index(0)
        self.pump()
        self.assertEqual(self.editor.reviewer_note_text.get(), "ver com o autor")

    def test_clearing_the_current_line_clears_the_note(self):
        """Deixada na tela, o proximo "Rejeitar" gravaria a nota na linha errada."""
        self.editor.reviewer_note_text.set("nota da linha 1")
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()

        self.editor.clear_current()
        self.pump()

        self.assertEqual(self.editor.reviewer_note_text.get(), "")

    def test_the_filter_shows_only_the_rejected_ones(self):
        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        self.editor.status_segment.set("Rejeitadas")
        self.editor.toggle_filter()
        self.pump()

        self.assertEqual([l[1] for l in self.editor.state.rows], ["the rook"])

    def test_the_counts_label_names_the_new_states_only_when_they_exist(self):
        """Um "Rejeitadas: 0" fixo no rodape de quem nunca usou o recurso e ruido."""
        self.assertNotIn("Rejeitadas", self.editor.counts_label.cget("text"))

        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        self.assertIn("Rejeitadas: 1", self.editor.counts_label.cget("text"))

    def test_verifying_a_doubtful_line_clears_the_status(self):
        """O lockstep visto da janela: uma traducao aceita nao esta "em duvida"."""
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()

        self.editor.save_changes(silent=True, mark_verified=True)
        self.pump()

        status, _nota, verified = self.status_no_banco("the rook")
        self.assertEqual((status, verified), ("", 1))

    def test_the_status_filter_labels_and_the_codes_agree(self):
        """A lista de rotulos do botao segmentado e a traducao para o banco vivem no
        MESMO dicionario: eram dois lugares, e acrescentar um filtro exigia mexer nos
        dois — esquecer um dava um botao que nao filtra nada."""
        self.assertEqual(
            list(self.editor.status_segment.cget("values")),
            list(edit_window.STATUS_FILTER_LABELS),
        )
        for rotulo, codigo in edit_window.STATUS_FILTER_LABELS.items():
            self.editor.status_segment.set(rotulo)
            self.assertEqual(self.editor.selected_status_filter(), codigo, rotulo)


class DraftOffThreadTests(EditorWindowTestCase):
    """O rascunho grava fora da thread da interface (ROADMAP 19, item 10)."""

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        self.editor.select_index(0)
        self.pump()

    def test_the_disk_write_happens_off_the_tk_thread(self):
        """Cada gravacao rele o JSON inteiro, serializa e troca o arquivo de nome. Na
        thread do Tk, isso e um engasgo na digitacao em disco lento."""
        threads = []
        original = edit_window.update_settings

        def espiao(mutator, path=None):
            threads.append(threading.current_thread())
            return original(mutator, path)

        edit_window.update_settings = espiao
        self.addCleanup(setattr, edit_window, "update_settings", original)

        self.set_text(self.editor.trans_text, "rascunho novo")
        self.editor.persist_current_draft()
        for _ in range(50):
            if threads:
                break
            time.sleep(0.02)

        self.assertTrue(threads, "a gravacao nao aconteceu")
        self.assertNotIn(
            threading.main_thread(), threads, "gravou na thread do Tk"
        )

    def test_the_draft_reaches_the_disk(self):
        self.set_text(self.editor.trans_text, "rascunho que precisa sobreviver")
        self.editor.persist_current_draft()

        for _ in range(100):
            rascunhos = settings.load_settings().get("editor_drafts") or {}
            if rascunhos:
                break
            time.sleep(0.02)

        self.assertTrue(rascunhos, "o rascunho nao chegou ao disco")
        self.assertIn(
            "rascunho que precisa sobreviver",
            [d["text"] for d in rascunhos.values()],
        )

    def test_the_debounce_is_long_enough_to_be_worth_it(self):
        """Eram 700 ms: quem digita uma frase para varias vezes por mais que isso — e
        cada parada custava uma releitura e uma regravacao do JSON inteiro."""
        self.assertGreaterEqual(edit_window.DRAFT_SAVE_DELAY_MS, 2000)


if __name__ == "__main__":
    unittest.main()
