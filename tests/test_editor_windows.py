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

import inspect
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
    editor_common,
    editor_widgets,
    glossario,
    glossary_editor,
    history_window,
    settings,
    stats_window,
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
from tradutor_pgn.review_quality import row_quality_flag, row_quality_warnings


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


class ListSwitchSavesTheOpenEditTests(EditorWindowTestCase):
    """Garantia F12: toda troca de lista grava a edicao aberta antes de recarregar.

    Oito caminhos ja gravavam (`navigate`, `change_page`, `go_to_page`, `go_to_id`,
    `apply_search`, `change_file_filter`, `change_language_filter`, `go_back`) e
    tres nao: o filtro de status, o "Limpar" da busca e os botoes de status de
    revisao (ROADMAP 22.1).

    O que se perdia nao era so "nao gravou". O recarregamento passa por
    `set_translation_text` -> `set_dirty(False)` -> `cancel_draft_save`, entao o
    texto digitado desde a ultima pausa de 2,5 s sumia do widget, do banco E do
    rascunho — sem uma palavra na tela.

    Por isso cada teste daqui olha o BANCO, e nao o widget: o widget seria
    repovoado pelo recarregamento de qualquer jeito, e afirmar sobre ele passaria
    com a producao consertada e com a quebrada.
    """

    module = edit_window

    ROWS = [
        ("AAA original um", "AAA traducao um"),
        ("BBB original dois", "BBB traducao dois"),
        ("CCC original tres", "CCC traducao tres"),
    ]

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for original, traducao in self.ROWS:
            save_translation(cur, original, traducao, "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.editor.select_index(0)
        self.pump()

    def digitar(self, texto):
        """Digita como o usuario digita: no widget, disparando `<<Modified>>`.

        `set_translation_text` nao serve aqui — ela e o caminho do PROGRAMA e
        decide sozinha o estado de sujeira. O que estes testes protegem e
        exatamente o texto que o usuario acabou de digitar e ainda nao salvou.
        """
        self.editor.trans_text.delete("1.0", tk.END)
        self.editor.trans_text.insert("1.0", texto)
        self.pump()
        self.assertTrue(
            self.editor.state.dirty, "a digitacao nao marcou a edicao como suja"
        )

    def traducao_no_banco(self, original):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT translated_comment FROM comments WHERE original_comment = ?",
                (original,),
            ).fetchone()[0]
        finally:
            conn.close()

    def status_no_banco(self, original):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT review_status, reviewer_note FROM comments"
                " WHERE original_comment = ?",
                (original,),
            ).fetchone()
        finally:
            conn.close()

    def test_switching_the_status_filter_saves_the_open_edit(self):
        self.digitar("TEXTO DIGITADO E NAO SALVO")

        self.editor.status_segment.set("Pendentes")
        self.editor.toggle_filter()
        self.pump()

        self.assertEqual(
            self.traducao_no_banco("AAA original um"), "TEXTO DIGITADO E NAO SALVO"
        )

    def test_clearing_the_search_saves_the_open_edit(self):
        """"Buscar" gravava e "Limpar", o botao ao lado na mesma barra, descartava."""
        self.editor.search_text.set("BBB")
        self.editor.apply_search()
        self.pump()
        self.assertEqual(self.editor.current["orig"], "BBB original dois")

        self.digitar("EDICAO ANTES DE LIMPAR A BUSCA")

        self.editor.clear_search()
        self.pump()

        self.assertEqual(
            self.traducao_no_banco("BBB original dois"), "EDICAO ANTES DE LIMPAR A BUSCA"
        )

    def test_rejecting_saves_the_open_edit(self):
        """Rejeitar e anotar por que e o gesto de quem estava mexendo no texto."""
        self.digitar("EDICAO ANTES DE REJEITAR")
        self.editor.reviewer_note_text.set("conferir com o autor")

        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        self.assertEqual(
            self.traducao_no_banco("AAA original um"), "EDICAO ANTES DE REJEITAR"
        )
        self.assertEqual(
            self.status_no_banco("AAA original um"),
            ("rejected", "conferir com o autor"),
        )

    def test_clearing_the_search_with_nothing_searched_does_not_touch_the_database(self):
        """Sem busca ativa o clique nao troca lista nenhuma — e nao pode gravar.

        A saida antecipada vem ANTES da gravacao de proposito: um botao que nao
        fez nada nao pode ter escrito no banco, e uma gravacao aqui carimbaria
        `updated_at` e o historico de uma linha que o usuario nao pediu para
        salvar (garantia R1).
        """
        self.digitar("TEXTO QUE NAO DEVE SER GRAVADO")

        self.editor.clear_search()
        self.pump()

        self.assertEqual(self.traducao_no_banco("AAA original um"), "AAA traducao um")

    def test_rejecting_writes_to_the_line_the_user_was_looking_at(self):
        """O id e a nota sao lidos ANTES da gravacao do texto.

        O cenario e o unico em que os dois divergem: com o filtro "Avisos QA"
        ativo, corrigir o aviso tira a propria linha da lista, e o
        recarregamento de `save_changes` deixa `current` apontando para a
        SEGUINTE (garantia R7). Lendo o id depois, "Rejeitar" carimbaria essa
        outra — e a nota lida seria a dela, ja reposta por `load_item`.

        E o caso que distingue a correcao completa da parcial: so acrescentar
        `save_changes` no comeco passa em todos os outros testes desta classe e
        falha neste.
        """
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Traducao identica ao original: as duas nascem com aviso de qualidade.
        for texto in ("DDD aviso um", "EEE aviso dois"):
            save_translation(cur, texto, texto, "pt", "en")
        conn.commit()
        conn.close()

        self.editor.status_segment.set("Avisos QA")
        self.editor.toggle_filter()
        self.pump()
        self.assertEqual(
            [linha[1] for linha in self.editor.state.rows],
            ["DDD aviso um", "EEE aviso dois"],
        )

        self.editor.select_index(0)
        self.pump()
        self.digitar("traducao boa aqui")
        self.editor.reviewer_note_text.set("conferir com o autor")

        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        # A precondicao do cenario: a correcao tirou a linha do filtro, entao o
        # recarregamento de `save_changes` de fato mudou a linha aberta.
        self.assertNotIn(
            "DDD aviso um", [linha[1] for linha in self.editor.state.rows]
        )
        self.assertEqual(
            self.status_no_banco("DDD aviso um"),
            ("rejected", "conferir com o autor"),
        )
        # A vizinha continua pendente e sem nota. Comparada com `or ""` porque
        # uma linha que ninguem tocou tem `reviewer_note` em NULL, e nao em
        # vazio — a mesma normalizacao que `fetch_review_status_by_id` faz. Com o
        # id lido depois da gravacao, e ESTA linha que apareceria como
        # "rejected"/"conferir com o autor".
        status_vizinha, nota_vizinha = self.status_no_banco("EEE aviso dois")
        self.assertEqual(status_vizinha or "", "")
        self.assertEqual(nota_vizinha or "", "")


class QualityLabelUsesTheRowLanguagePairTests(EditorWindowTestCase):
    """Garantia Q3: a avaliacao de QA na tela usa o par de idiomas da linha.

    A heuristica de terminologia (Q1) so roda com o par, e a coluna materializada
    sempre o passou. O rotulo "QA:" e o anuncio do F7 nao passavam: uma linha cujo
    unico problema fosse terminologia dizia "QA: sem avisos" em VERDE enquanto a
    lista a marcava com "⚠ QA" e o filtro "Avisos QA" a mostrava — a garantia R6
    violada entre dois pontos da mesma janela (ROADMAP 22.2).

    O par usado aqui e `('White', 'White', 'pt')` do `Termos-suspeitos.txt` que vem
    com o programa: "o termo nao foi traduzido". Escolhido porque o aviso dele e o
    UNICO que estes textos produzem — qualquer outra heuristica disparando faria o
    teste passar sem o par e nao provaria nada.
    """

    module = edit_window

    ORIGINAL = "White has a decisive advantage on the queenside."
    TRADUCAO = "White tem vantagem decisiva na ala da dama."

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, self.ORIGINAL, self.TRADUCAO, "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.editor.select_index(0)
        self.pump()

    def test_the_label_names_a_terminology_only_warning(self):
        self.assertIn("Terminologia", self.editor.qa_label.cget("text"))

    def test_the_label_says_exactly_what_the_materialized_column_says(self):
        """O enunciado de Q3, na forma mais direta que ele tem.

        A linha da lista traz a coluna `quality_warning` (posicao 9) e o par
        (posicoes 7 e 8). Se o rotulo e a coluna discordarem, e a janela
        contradizendo a si mesma — o marcador "⚠ QA" na lista e o verde no rodape,
        na mesma linha, ao mesmo tempo.
        """
        linha = self.editor.state.rows[0]
        self.assertEqual(row_quality_flag(linha), 1, "a coluna nao marcou a linha")
        self.assertEqual(
            self.editor.qa_label.cget("text"),
            "QA: " + " | ".join(row_quality_warnings(linha)),
        )

    def test_a_line_without_declared_origin_is_evaluated_too(self):
        """As linhas legadas sao a maioria de um banco anterior a 9.2.

        A terminologia e escopada por DESTINO e nao por par, justamente para
        alcanca-las. Uma correcao que so passasse o par quando a origem existe
        deixaria de fora quem mais precisa dela.
        """
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "White is clearly better here.", "White esta melhor.", "pt")
        conn.commit()
        conn.close()

        self.editor.reload_rows()
        self.pump()
        indice = [linha[1] for linha in self.editor.state.rows].index(
            "White is clearly better here."
        )
        self.editor.select_index(indice)
        self.pump()

        self.assertEqual(self.editor.current["source_language"], "")
        self.assertIn("Terminologia", self.editor.qa_label.cget("text"))

    def test_the_next_warning_shortcut_names_the_warning_under_the_qa_filter(self):
        """F7 parava na linha e ficava mudo sobre o motivo.

        O ramo do filtro "Avisos QA" avaliava a linha sem o par, entao para uma
        linha marcada so por terminologia a lista de avisos voltava vazia e o
        `if warnings:` engolia a mensagem. A linha era selecionada de qualquer
        jeito — ela esta na lista pela coluna materializada —, e o revisor ficava
        sem saber por que o programa parou ali.
        """
        self.editor.status_segment.set("Avisos QA")
        self.editor.toggle_filter()
        self.pump()
        self.assertEqual([linha[1] for linha in self.editor.state.rows], [self.ORIGINAL])

        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertIn("Aviso QA:", self.editor.msg_label.cget("text"))
        self.assertIn("Terminologia", self.editor.msg_label.cget("text"))

    def test_the_edited_row_keeps_agreeing_with_the_label(self):
        """A linha reconstruida em memoria e o rotulo leem o par do mesmo lugar.

        `update_current_row_cache` monta a tupla da linha editada a mao. Com o par
        vindo de outra fonte que nao a do rotulo, o marcador da lista passaria a
        depender de a linha ter sido editada NESTA sessao — que e a divergencia que
        R6 proibe, agora dentro da janela.
        """
        self.editor.trans_text.delete("1.0", tk.END)
        self.editor.trans_text.insert("1.0", "White segue melhor no flanco de dama.")
        self.pump()
        self.editor.save_changes(silent=False)
        self.pump()

        linha = self.editor.state.rows[0]
        self.assertEqual(row_quality_flag(linha), 1)
        self.assertEqual(
            self.editor.qa_label.cget("text"),
            "QA: " + " | ".join(row_quality_warnings(linha)),
        )

    def test_with_no_line_open_there_is_no_verdict_on_the_screen(self):
        """Com o editor vazio, "traducao vazia" e um aviso VERDADEIRO sobre nada.

        O texto do widget vazio sempre produzia esse aviso, entao o rotulo aparecia
        em ambar na abertura de um banco sem linhas — e o ramo que existia para o
        caso "sem linha aberta" nunca era alcancado, porque o aviso chegava antes
        dele.
        """
        self.editor.clear_current()
        self.pump()

        self.assertEqual(self.editor.qa_label.cget("text"), "")


class BackStackRestoresTheWholeViewTests(EditorWindowTestCase):
    """Garantia F13: o retrato do "voltar" repoe tambem o modo de busca e o par.

    O retrato guardava id, busca, status, origem, arquivo e pagina. Faltavam dois
    campos, e cada falta quebrava F3 de um jeito (ROADMAP 22.3):

    - o MODO da busca, porque o mesmo texto em "Trecho" e em "Termos" da duas
      listas diferentes — o retrato era reposto sob o modo novo;
    - o DESTINO, porque trocar de par e um dos saltos que F3 promete desfazer, e
      sem ele `jump_to_id` procurava o id do par antigo dentro do par novo,
      falhava, e o `while` de `go_back` consumia a pilha INTEIRA em silencio.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Dois pares de idiomas e um texto que so a busca por TRECHO acha.
        # Nenhuma outra linha pode conter "bisp" — a busca varre o original E a
        # traducao, e uma segunda linha casando faria o teste medir outra coisa.
        save_translation(cur, "the bishop pair", "o par de bispos", "pt", "en")
        save_translation(cur, "a rook endgame", "um final de torres", "pt", "en")
        save_translation(cur, "el caballo activo", "o cavalo ativo", "pt", "es")
        save_translation(cur, "the same in french", "le meme en francais", "fr", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.editor.select_index(0)
        self.pump()

    def originais(self):
        return [linha[1] for linha in self.editor.state.rows]

    def test_going_back_restores_the_search_mode(self):
        """`bisp` em "Trecho" acha "bispos"; em "Termos" nao acha nada.

        Sem o modo no retrato, "Voltar" repunha o texto `bisp` sob o modo novo:
        a consulta nao achava a linha do retrato, o retrato era DESCARTADO e o
        revisor caia num anterior — com a janela dizendo "Voltou para o ponto
        anterior".

        Comeca numa linha DIFERENTE da que a busca acha: caindo no retrato
        anterior, o teste tem de poder notar. Com as duas sendo a mesma linha ele
        passaria com a producao consertada e com a quebrada.
        """
        self.editor.select_index(1)
        self.pump()
        self.assertEqual(self.editor.current["orig"], "a rook endgame")

        self.editor.search_mode_segment.set(edit_window.SEARCH_MODE_LABEL_SUBSTRING)
        self.editor.search_text.set("bisp")
        self.editor.apply_search()
        self.pump()
        self.assertEqual(self.originais(), ["the bishop pair"])
        id_do_retrato = self.editor.current["id"]

        # A troca de modo e ela propria um salto (dispara `apply_search`).
        self.editor.search_mode_segment.set(edit_window.SEARCH_MODE_LABEL_TERMS)
        self.editor.apply_search()
        self.pump()
        self.assertEqual(self.originais(), [])

        self.assertTrue(self.editor.go_back())
        self.pump()

        self.assertEqual(
            self.editor.search_mode_segment.get(),
            edit_window.SEARCH_MODE_LABEL_SUBSTRING,
        )
        self.assertEqual(self.editor.current["id"], id_do_retrato)
        self.assertEqual(self.originais(), ["the bishop pair"])

    def test_going_back_restores_the_target_language(self):
        """Trocar de par e um salto que F3 promete desfazer.

        Sem o destino no retrato, `jump_to_id` procurava um id de pt dentro de fr,
        nao achava, e o retrato era descartado — junto com todos os outros da
        pilha, ate "Nada para voltar".
        """
        id_em_portugues = self.editor.current["id"]

        self.editor.target_menu.set("Francês")
        self.editor.change_language_filter()
        self.pump()
        self.assertEqual(self.editor.lang, "fr")
        self.assertEqual(self.originais(), ["the same in french"])

        self.assertTrue(self.editor.go_back())
        self.pump()

        self.assertEqual(self.editor.lang, "pt")
        self.assertEqual(self.editor.target_menu.get(), "Português")
        self.assertEqual(self.editor.current["id"], id_em_portugues)
        self.assertIn("(pt)", self.editor.win.title())

    def test_going_back_across_pairs_keeps_the_rest_of_the_stack(self):
        """O sintoma que doia: um retrato irrecuperavel consumia os outros 49.

        `go_back` descarta o retrato que nao da para repor e tenta o proximo — o
        que e certo quando a linha foi apagada, e desastroso quando a causa e o
        proprio "voltar" procurando no par errado: TODOS os retratos sao do par
        que se deixou, entao todos falham em sequencia.
        """
        self.editor.select_index(1)
        self.pump()
        # Dois saltos dentro de pt, para a pilha ter fundo.
        self.editor.search_text.set("rook")
        self.editor.apply_search()
        self.pump()
        self.editor.clear_search()
        self.pump()
        altura_antes = len(self.editor.state.history_stack)
        self.assertGreaterEqual(altura_antes, 2)

        self.editor.target_menu.set("Francês")
        self.editor.change_language_filter()
        self.pump()

        self.assertTrue(self.editor.go_back())
        self.pump()

        self.assertEqual(self.editor.lang, "pt")
        # Um retrato consumido — o da troca de par —, e nao a pilha inteira.
        self.assertEqual(len(self.editor.state.history_stack), altura_antes)

    def test_going_back_rescopes_the_glossary_to_the_restored_pair(self):
        """As sugestoes seguem o par reposto (garantia S11).

        A regra e escopada `en>pt`: ela existe com "Origem: Inglês" e desaparece
        com "Origem: Espanhol". O "voltar" repunha o SELETOR e nada mais — a lista
        voltava para o par certo e as sugestoes continuavam sendo as do par que se
        deixou.
        """
        save_glossary_entries([("bishop", "bispo", "suggestion", 0, "en>pt")])
        self.editor.source_menu.set("Inglês")
        self.editor.change_language_filter()
        self.pump()
        self.assertIn(("bishop", "bispo"), [(o, n) for o, n, *_ in self.editor.glossary])

        self.editor.source_menu.set("Espanhol")
        self.editor.change_language_filter()
        self.pump()
        self.assertNotIn(
            ("bishop", "bispo"), [(o, n) for o, n, *_ in self.editor.glossary]
        )

        self.assertTrue(self.editor.go_back())
        self.pump()

        self.assertEqual(self.editor.source_menu.get(), "Inglês")
        self.assertIn(("bishop", "bispo"), [(o, n) for o, n, *_ in self.editor.glossary])

    def test_the_snapshot_keeps_the_filter_that_was_in_effect(self):
        """O retrato e de ONDE se estava, e nao de para onde se vai.

        Este e o defeito que a implementacao de 22.3 encontrou e que o
        diagnostico nao tinha visto: o retrato lia os SELETORES, e o comando de um
        seletor roda com o widget ja no valor novo. Trocar de "Todas" para
        "Verificadas" empilhava "Verificadas" — e "voltar" repunha o filtro que o
        usuario acabou de escolher, ou seja, nao repunha nada.

        Vale para os tres seletores medidos, e nao so para o status: origem e modo
        de busca tinham o mesmo defeito.
        """
        self.assertEqual(self.editor.status_segment.get(), "Todas")

        self.editor.status_segment.set("Verificadas")
        self.editor.toggle_filter()
        self.pump()
        self.assertEqual(self.editor.state.history_stack[-1]["status"], "Todas")

        self.editor.source_menu.set("Espanhol")
        self.editor.change_language_filter()
        self.pump()
        self.assertEqual(self.editor.state.history_stack[-1]["source"], "Todos")

        self.editor.search_mode_segment.set(edit_window.SEARCH_MODE_LABEL_SUBSTRING)
        self.editor.apply_search()
        self.pump()
        self.assertEqual(
            self.editor.state.history_stack[-1]["mode"],
            edit_window.SEARCH_MODE_LABEL_TERMS,
        )

    def test_the_snapshot_is_taken_before_the_save_that_reloads(self):
        """O retrato vem antes do `save_changes`, e nao depois.

        A gravacao pode recarregar a lista por conta propria: com o filtro
        "Avisos QA" ativo, corrigir o aviso tira a linha (R7). Como o filtro ja
        esta no valor NOVO quando o comando roda, esse recarregamento gravaria em
        `applied_view` o filtro de destino — e o retrato empilhado logo depois
        seria o do lugar aonde o usuario esta indo.

        E o unico caminho em que a ordem das duas chamadas se ve de fora, e sem
        ele a ordem passaria por preferencia de escrita.
        """
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Traducao igual ao original: as duas nascem com aviso de qualidade.
        for texto in ("DDD aviso um", "EEE aviso dois"):
            save_translation(cur, texto, texto, "pt", "en")
        conn.commit()
        conn.close()

        self.editor.reload_rows()
        self.pump()
        indice = [linha[1] for linha in self.editor.state.rows].index("DDD aviso um")
        self.editor.select_index(indice)
        self.pump()
        id_editada = self.editor.current["id"]

        # A edicao corrige o aviso, e ainda nao esta salva.
        self.editor.trans_text.delete("1.0", tk.END)
        self.editor.trans_text.insert("1.0", "uma traducao boa de verdade")
        self.pump()

        self.editor.status_segment.set("Avisos QA")
        self.editor.toggle_filter()
        self.pump()

        retrato = self.editor.state.history_stack[-1]
        self.assertEqual(retrato["status"], "Todas")
        self.assertEqual(retrato["id"], id_editada)

        self.assertTrue(self.editor.go_back())
        self.pump()
        self.assertEqual(self.editor.status_segment.get(), "Todas")
        self.assertEqual(self.editor.current["id"], id_editada)

    def test_going_back_from_a_filter_restores_the_old_filter(self):
        """O sintoma do defeito acima, visto de fora: "voltar" nao voltava nada."""
        self.editor.status_segment.set("Verificadas")
        self.editor.toggle_filter()
        self.pump()

        self.assertTrue(self.editor.go_back())
        self.pump()

        self.assertEqual(self.editor.status_segment.get(), "Todas")

    def test_a_stack_that_cannot_be_restored_leaves_the_window_where_it_was(self):
        """"Nada para voltar" tem de querer dizer que nada mudou.

        Repor um retrato mexe nos seletores ANTES de saber se a linha existe.
        Enquanto ha proximo isso nao aparece; quando nenhum serve, a janela ficava
        com os filtros do ultimo que falhou — e, desde que o par entrou no retrato,
        ate em outro idioma de destino.
        """
        self.editor.search_text.set("rook")
        self.editor.apply_search()
        self.pump()
        self.assertEqual(len(self.editor.state.history_stack), 1)

        # O retrato aponta para uma linha que deixou de existir (o "Zerar
        # Traducoes" de outra janela, ou uma importacao).
        conn = initialize_database(self.db_path)
        conn.execute("DELETE FROM comments WHERE original_comment = ?", ("the bishop pair",))
        conn.commit()
        conn.close()

        busca_antes = self.editor.state.active_search
        id_antes = self.editor.current["id"]

        self.assertFalse(self.editor.go_back())
        self.pump()

        self.assertEqual(self.editor.state.active_search, busca_antes)
        self.assertEqual(self.editor.current["id"], id_antes)
        self.assertEqual(self.editor.lang, "pt")


class BlockRewritesKeepTheUndoStackTests(EditorWindowTestCase):
    """Garantia F14: reescrever a linha aberta nao apaga o desfazer (ROADMAP 22.4).

    `set_translation_text` chamava `edit_reset()` sempre, e por ela passam as
    acoes que reescrevem o texto INTEIRO de uma vez — "Copiar original", "Aplicar
    selecionada", "Aplicar todas", o "Todos" da busca-e-troca e o "Restaurar".
    Eram as que mais pedem um Ctrl+Z, e eram as unicas que o desligavam: "Trocar"
    (uma ocorrencia) edita o widget direto e sempre teve desfazer.

    O `edit_reset` nao era gratuito, e por isso o padrao continua sendo apagar: a
    pilha nao pode atravessar uma TROCA DE LINHA, senao um Ctrl+Z traz o texto da
    linha anterior para dentro desta — e a gravacao ao navegar o leva para o
    banco.
    """

    module = edit_window

    ROWS = [
        ("AAA original um", "AAA traducao um"),
        ("BBB original dois", "BBB traducao dois"),
    ]

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for original, traducao in self.ROWS:
            save_translation(cur, original, traducao, "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win
        self.editor.select_index(0)
        self.pump()

    def texto(self):
        return self.editor.trans_text.get("1.0", tk.END).strip()

    def digitar(self, texto):
        self.editor.trans_text.delete("1.0", tk.END)
        self.editor.trans_text.insert("1.0", texto)
        self.pump()

    def test_copying_the_original_can_be_undone(self):
        self.digitar("o que o revisor escreveu")

        self.editor.copy_original_to_translation()
        self.pump()
        self.assertEqual(self.texto(), "AAA original um")

        self.editor.undo_translation()
        self.pump()
        self.assertEqual(self.texto(), "o que o revisor escreveu")

    def test_restoring_the_saved_text_can_be_undone(self):
        """"Restaurar" era o unico caminho de volta, e descartava tudo."""
        self.digitar("uma revisao que vale a pena")

        self.editor.restore_saved_translation()
        self.pump()
        self.assertEqual(self.texto(), "AAA traducao um")

        self.editor.undo_translation()
        self.pump()
        self.assertEqual(self.texto(), "uma revisao que vale a pena")

    def test_replacing_all_can_be_undone_in_a_single_step(self):
        """Uma acao, um Ctrl+Z — e nao um por `delete`/`insert`.

        Sem desligar os separadores automaticos durante a substituicao, o
        primeiro Ctrl+Z desfaz so o `insert` e deixa o editor VAZIO: o revisor
        veria a traducao sumir onde esperava ve-la voltar.
        """
        self.digitar("torre e torre e torre")

        self.editor.editor_find_text.set("torre")
        self.editor.editor_replace_text.set("bispo")
        self.editor.replace_all_in_translation()
        self.pump()
        self.assertEqual(self.texto(), "bispo e bispo e bispo")

        self.editor.undo_translation()
        self.pump()
        self.assertEqual(self.texto(), "torre e torre e torre")

    def test_applying_a_suggestion_can_be_undone(self):
        save_glossary_entries([("torre", "bispo", "suggestion")])
        self.editor.reload_glossary(show_feedback=False)
        self.digitar("a torre domina")
        self.editor.refresh_suggestions()
        self.pump()
        self.assertTrue(self.editor.current_suggestions, "o glossario nao sugeriu nada")

        self.editor.select_suggestion(0)
        self.editor.apply_one()
        self.pump()
        self.assertEqual(self.texto(), "a bispo domina")

        self.editor.undo_translation()
        self.pump()
        self.assertEqual(self.texto(), "a torre domina")

    def test_applying_all_suggestions_can_be_undone(self):
        """A previa de "Aplicar todas" e uma janela propria; o botao dela e o alvo."""
        save_glossary_entries([("torre", "bispo", "suggestion")])
        self.editor.reload_glossary(show_feedback=False)
        self.digitar("a torre e a torre")
        self.editor.refresh_suggestions()
        self.pump()

        self.editor.apply_all()
        self.pump()

        # A previa e uma `CTkToplevel` da JANELA do editor, e nao da raiz — e ali
        # que ela aparece na arvore. Os helpers de widget da classe base miram
        # `self.win`, entao ela vira o alvo enquanto o botao e procurado.
        previas = [
            w for w in self.editor.win.winfo_children() if isinstance(w, tk.Toplevel)
        ]
        self.assertTrue(previas, "a previa de 'Aplicar todas' nao abriu")
        self.win = previas[-1]
        self.click(self.button("Aplicar"))
        self.win = self.editor.win

        self.assertEqual(self.texto(), "a bispo e a bispo")

        self.editor.undo_translation()
        self.pump()
        self.assertEqual(self.texto(), "a torre e a torre")

    def test_the_undo_stack_never_crosses_a_line_change(self):
        """O que o `edit_reset` protege, e a razao de ele continuar sendo o padrao.

        Um Ctrl+Z que atravessasse a troca de linha traria o texto da ANTERIOR
        para dentro desta — e a gravacao ao navegar o levaria para o banco,
        escrevendo numa linha a traducao de outra.
        """
        self.digitar("texto digitado na primeira linha")

        self.editor.select_index(1, save_previous=True)
        self.pump()
        self.assertEqual(self.texto(), "BBB traducao dois")

        self.editor.undo_translation()
        self.pump()

        self.assertEqual(self.texto(), "BBB traducao dois")
        self.assertNotIn("primeira linha", self.texto())


class NavigationAfterASaveThatShrinksTheListTests(EditorWindowTestCase):
    """Garantia F15: gravar e avancar nao pula a linha que ocupou o lugar.

    Uma gravacao pode tirar a linha aberta do filtro ativo — com "Avisos QA", e o
    que acontece quando a edicao corrige o aviso —, e `save_changes` ja seleciona
    quem ocupou a posicao dela (garantia R7). Quem esta ali JA e a proxima:
    avancar mais uma casa pula uma traducao, sem nada na tela dizendo que ela
    existiu.

    `mark_and_next` sabia disso e guardava o id antes de gravar; `navigate` e o
    "Proximo aviso QA" (F7) nao (ROADMAP 22.5). A fila de avisos e onde isso mais
    doi: pular na fila e nao revisar.
    """

    module = edit_window

    LINHAS = ["AAA aviso um", "BBB aviso dois", "CCC aviso tres"]

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        # Traducao identica ao original: as tres nascem com aviso de qualidade.
        for texto in self.LINHAS:
            save_translation(cur, texto, texto, "pt", "en")
        conn.commit()
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win
        self.editor.status_segment.set("Avisos QA")
        self.editor.toggle_filter()
        self.pump()
        self.assertEqual([linha[1] for linha in self.editor.state.rows], self.LINHAS)

    def corrigir_o_aviso(self, texto="uma traducao boa de verdade"):
        """Reescreve a linha aberta com um texto sem aviso — ela sai do filtro."""
        self.editor.trans_text.delete("1.0", tk.END)
        self.editor.trans_text.insert("1.0", texto)
        self.pump()

    def test_next_lands_on_the_line_that_took_the_place(self):
        self.editor.select_index(0)
        self.pump()
        self.corrigir_o_aviso()

        self.editor.navigate(1)
        self.pump()

        self.assertEqual(self.editor.current["orig"], "BBB aviso dois")

    def test_the_next_warning_shortcut_lands_on_it_too(self):
        """O F7 tinha a mesma conta, e nele o defeito e pior: pular na fila de
        avisos e exatamente nao revisar o que a fila existe para mostrar."""
        self.editor.select_index(0)
        self.pump()
        self.corrigir_o_aviso()

        self.editor.go_to_next_quality_warning()
        self.pump()

        self.assertEqual(self.editor.current["orig"], "BBB aviso dois")

    def test_previous_still_goes_back_one(self):
        """A regra vale so para frente: para tras, a posicao vaga ja e a certa."""
        self.editor.select_index(1)
        self.pump()
        self.corrigir_o_aviso()

        self.editor.navigate(-1)
        self.pump()

        self.assertEqual(self.editor.current["orig"], "AAA aviso um")

    def test_next_still_advances_one_when_the_line_stays(self):
        """O caso comum, que a correcao nao pode quebrar: sem edicao nenhuma,
        "Proxima >" anda uma casa."""
        self.editor.select_index(0)
        self.pump()

        self.editor.navigate(1)
        self.pump()

        self.assertEqual(self.editor.current["orig"], "BBB aviso dois")

    def test_next_still_advances_one_when_the_edit_keeps_the_warning(self):
        """Editar sem tirar o aviso mantem a linha na lista — e a conta e a normal."""
        self.editor.select_index(0)
        self.pump()
        # Continua igual ao original: o aviso permanece.
        self.corrigir_o_aviso("AAA aviso um")

        self.editor.navigate(1)
        self.pump()

        self.assertEqual(self.editor.current["orig"], "BBB aviso dois")


class FlashDurationTests(unittest.TestCase):
    """A conta do tempo de tela e pura, e por isso e conferida sem abrir janela."""

    def test_short_messages_keep_the_floor(self):
        """Abaixo do piso o texto e curto o bastante para ser lido de relance."""
        self.assertEqual(editor_common.flash_duration_ms("Salvo"), 1500)
        self.assertEqual(editor_common.flash_duration_ms("Tradução salva"), 1500)

    def test_the_longest_message_of_the_window_gets_more_than_the_floor(self):
        """O caso que motivou o item: 73 caracteres no tempo de "Salvo"."""
        texto = (
            "Tradução salva e verificada; 3 outro(s) original(is) também "
            "verificado(s)"
        )
        self.assertEqual(len(texto), 73)
        self.assertEqual(editor_common.flash_duration_ms(texto), 3285)

    def test_the_ceiling_stops_a_label_from_parking_on_the_screen(self):
        self.assertEqual(editor_common.flash_duration_ms("x" * 1000), 6000)

    def test_no_text_still_has_a_duration(self):
        self.assertEqual(editor_common.flash_duration_ms(""), 1500)
        self.assertEqual(editor_common.flash_duration_ms(None), 1500)


class FakeFlashWindow:
    """Uma janela com o que `flash_message` usa: agendar, cancelar e nada mais.

    Deixa o teste do atropelo ser DETERMINISTICO: o defeito e sobre qual `after`
    dispara quando, e com um Tk de verdade isso viraria um teste de relogio.
    """

    def __init__(self):
        self.agendados = {}
        self.cancelados = []
        self._contador = 0

    def after(self, milliseconds, callback):
        self._contador += 1
        identificador = f"after#{self._contador}"
        self.agendados[identificador] = (milliseconds, callback)
        return identificador

    def after_cancel(self, identificador):
        if identificador not in self.agendados:
            raise ValueError(f"id desconhecido: {identificador}")
        del self.agendados[identificador]
        self.cancelados.append(identificador)

    def disparar(self, identificador):
        _ms, callback = self.agendados.pop(identificador)
        callback()


class FakeFlashLabel:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]

    def cget(self, chave):
        return self.text if chave == "text" else None


class FlashMessageTimerTests(unittest.TestCase):
    """Garantia F16: uma mensagem nova nao e apagada pelo timer da anterior."""

    def setUp(self):
        self.label = FakeFlashLabel()
        self.window = FakeFlashWindow()

    def test_the_old_timer_is_cancelled_before_the_new_one_is_scheduled(self):
        """O defeito, em duas linhas: A em t=0, B em t=1,0 s, A apaga B em t=1,5 s."""
        primeiro = editor_widgets.flash_message(self.label, self.window, "mensagem A")
        segundo = editor_widgets.flash_message(self.label, self.window, "mensagem B")

        self.assertEqual(self.label.text, "mensagem B")
        self.assertEqual(self.window.cancelados, [primeiro])
        self.assertEqual(list(self.window.agendados), [segundo])

    def test_the_surviving_timer_clears_the_message_it_belongs_to(self):
        editor_widgets.flash_message(self.label, self.window, "mensagem A")
        segundo = editor_widgets.flash_message(self.label, self.window, "mensagem B")

        self.window.disparar(segundo)

        self.assertEqual(self.label.text, "")
        self.assertIsNone(self.label._flash_after)

    def test_the_scheduled_time_comes_from_the_text(self):
        curta = editor_widgets.flash_message(self.label, self.window, "Salvo")
        self.assertEqual(self.window.agendados[curta][0], 1500)

        longa_texto = "Tradução salva e verificada; 3 outro(s) original(is) também verificado(s)"
        longa = editor_widgets.flash_message(self.label, self.window, longa_texto)
        self.assertEqual(
            self.window.agendados[longa][0], editor_common.flash_duration_ms(longa_texto)
        )

    def test_an_explicit_duration_still_wins(self):
        """Quem sabe o que quer continua podendo dizer."""
        identificador = editor_widgets.flash_message(
            self.label, self.window, "mensagem", 250
        )
        self.assertEqual(self.window.agendados[identificador][0], 250)

    def test_cancelling_tolerates_a_timer_that_no_longer_exists(self):
        """Fechar a janela com um `after` pendente nao pode virar erro no callback."""
        self.label._flash_after = "after#inexistente"
        editor_widgets.cancel_flash(self.label, self.window)
        self.assertIsNone(self.label._flash_after)


class FlashMessageIsWiredEverywhereTests(EditorWindowTestCase):
    """As tres janelas que dao recado passam pela MESMA funcao (ROADMAP 22.6).

    A de estatisticas tinha uma copia do padrao — `after` sem cancelar o
    anterior —, e uma copia que ninguem lembraria de corrigir junto e o que o
    item 3.2 do ROADMAP descreve.
    """

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
        self.win = self.editor.win

    def esperar(self, milissegundos):
        """Bombeia o laco do Tk pelo tempo pedido, para os `after` dispararem."""
        limite = time.monotonic() + milissegundos / 1000
        while time.monotonic() < limite:
            self.root.update()
            time.sleep(0.005)

    def test_the_editor_message_survives_an_older_timer(self):
        # A com um timer curtissimo, B logo em seguida: se o de A nao for
        # cancelado, ele apaga B antes de o teste olhar.
        editor_widgets.flash_message(self.editor.msg_label, self.editor.win, "A", 1)
        self.editor.show_message("mensagem que tem de ficar")

        self.esperar(80)

        self.assertEqual(
            self.editor.msg_label.cget("text"), "mensagem que tem de ficar"
        )

    def test_the_stats_window_uses_the_same_path(self):
        janela = stats_window.StatsWindow(self.app, "relatorio de teste")
        self.addCleanup(janela.win.destroy)
        self.pump()

        janela._flash("primeira")
        pendente = janela.msg_label._flash_after
        self.assertIsNotNone(pendente, "a janela de estatisticas nao passou pelo flash")

        janela._flash("segunda")
        self.assertEqual(janela.msg_label.cget("text"), "segunda")
        self.assertNotEqual(janela.msg_label._flash_after, pendente)


class NoFieldDependsOnAPlaceholderTests(EditorWindowTestCase):
    """Garantia F17: nenhum campo da janela depende do placeholder para ser lido.

    O CustomTkinter 5.2.2 decide mostrar o placeholder comparando o OBJETO
    `StringVar` com `""` — comparacao que e falsa sempre —, entao **nenhum**
    placeholder do programa aparece (ROADMAP 22.7). Os campos com rotulo ou botao
    ao lado nao perdem nada com isso; os dois do buscar-e-substituir perdiam a
    identidade: dois retangulos iguais lado a lado, um que busca e um que troca.

    Mesmo com a biblioteca corrigida um dia, o rotulo continua sendo o certo
    ali: placeholder some na primeira tecla, que e justamente quando os dois
    campos com texto dentro ficam impossiveis de distinguir.
    """

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
        self.win = self.editor.win

    def rotulos_da_barra_de_busca(self):
        """`{(linha, coluna): texto}` dos rotulos da barra de buscar-e-trocar.

        A LINHA entra na chave, e nao so a coluna: um rotulo empurrado para a
        fileira dos botoes continua na mesma coluna do campo e passaria por
        vizinho dele — foi uma mutacao que sobreviveu ate esta chave existir.
        """
        rotulos = {}
        for filho in self.editor.find_bar.winfo_children():
            if isinstance(filho, self.module.ctk.CTkLabel):
                info = filho.grid_info()
                if info:
                    rotulos[(int(info["row"]), int(info["column"]))] = filho.cget("text")
        return rotulos

    def test_the_variable_never_compares_equal_to_the_empty_string(self):
        """O fato que mata todo placeholder do programa, e a razao dos rotulos.

        E semantica do `tkinter.Variable`, e nao da biblioteca de widgets: se um
        dia ela mudar de ideia sobre o placeholder, esta comparacao continua
        sendo a que ela erra hoje.
        """
        variavel = tk.StringVar(master=self.root, value="")
        self.assertEqual(variavel.get(), "")
        self.assertFalse(variavel == "")

    def test_the_find_and_replace_fields_have_labels(self):
        rotulos = self.rotulos_da_barra_de_busca()
        self.assertEqual(sorted(rotulos.values()), ["Buscar:", "Trocar por:"])

    def test_each_label_sits_immediately_before_its_field(self):
        """Nao basta existir: o rotulo tem de estar ao LADO do campo.

        Tres jeitos de errar isso passam num teste que so procura o texto na
        arvore, e cada um deles e uma mutacao desta rodada: o rotulo nao gridado
        (`winfo_manager`), os dois trocados de lugar, e um deles empurrado para
        outra fileira do grid — na mesma coluna, mas embaixo dos botoes.
        """
        rotulos = self.rotulos_da_barra_de_busca()
        busca = self.editor.editor_find_entry.grid_info()
        troca = self.editor.editor_replace_entry.grid_info()

        self.assertEqual(self.editor.editor_find_entry.winfo_manager(), "grid")
        self.assertEqual(self.editor.editor_replace_entry.winfo_manager(), "grid")
        self.assertEqual(
            rotulos.get((int(busca["row"]), int(busca["column"]) - 1)), "Buscar:"
        )
        self.assertEqual(
            rotulos.get((int(troca["row"]), int(troca["column"]) - 1)), "Trocar por:"
        )

    def test_the_labelled_fields_no_longer_declare_a_placeholder(self):
        """O rotulo passa a ser a unica fonte do nome.

        Se a biblioteca for corrigida um dia, um placeholder sobrevivente viraria
        uma segunda dica dizendo a mesma coisa dentro do campo.
        """
        for campo in (self.editor.editor_find_entry, self.editor.editor_replace_entry):
            self.assertEqual(campo.cget("placeholder_text"), None)

    def test_the_fields_that_kept_a_placeholder_are_named_by_something_else(self):
        """Os que ficaram nao dependem dele: ha um botao ou um rotulo ao lado.

        A busca da lista tem o botao "Buscar" na mesma barra; a nota tem o rotulo
        "Nota:". O placeholder deles acrescenta uma dica — o escopo da busca, o
        que escrever na nota — e nao a identidade do campo.
        """
        self.assertIsNotNone(self.editor.search_entry.cget("placeholder_text"))
        self.assertEqual(self.editor.btn_search.cget("text"), "Buscar")

        self.assertIsNotNone(self.editor.note_entry.cget("placeholder_text"))
        rotulos = [
            filho.cget("text")
            for filho in self.editor.note_bar.winfo_children()
            if isinstance(filho, self.module.ctk.CTkLabel)
        ]
        self.assertIn("Nota:", rotulos)


class WhatWasInvisibleTests(EditorWindowTestCase):
    """Garantia F18: o que a janela sabe fazer aparece na janela (ROADMAP 22.8).

    Quatro coisas eram invisiveis, e cada uma de um jeito: os treze atalhos so
    existiam no fonte; o foco do teclado nao tinha indicador; o estado ligado do
    botao "B" era a MESMA cor do desligado no tema escuro; e uma troca de tema do
    Windows com a janela aberta deixava o Tk puro com as cores antigas.
    """

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
        self.win = self.editor.win

    # ----------------------------------------------------------- atalhos

    def normalizar(self, sequencia):
        """A forma do Tk sem o `Key` que ele acrescenta ao registrar o bind.

        `<Control-f>` volta de `bind()` como `<Control-Key-f>` e `<F3>` como
        `<Key-F3>`: comparar as strings cruas nao casa em nenhuma das duas
        direcoes. E `Ctrl+Z`, ligado nas duas caixas, e a mesma tecla para quem
        le a lista — por isso tudo em minusculas.
        """
        return str(sequencia).lower().replace("-key-", "-").replace("<key-", "<")

    def sequencias_da_tabela(self):
        return {
            self.normalizar(sequencia)
            for _titulo, atalhos in edit_window.KEYBOARD_SHORTCUTS
            for _rotulo, sequencia, _descricao in atalhos
        }

    def sequencias_ligadas(self):
        """As sequencias de TECLADO que a janela realmente tem.

        Duas fontes, porque alguns atalhos vivem no widget de texto e nao na
        janela. E so teclado: `<<Modified>>`, `<FocusIn>`, `<Configure>` e
        `<Destroy>` sao eventos de ciclo de vida, e quem os separa e o proprio
        Tk — ele poe `Key` em toda sequencia de tecla.
        """
        ligadas = set()
        for widget in (self.editor.win, self.editor.trans_text):
            for sequencia in widget.bind():
                if "key-" not in str(sequencia).lower():
                    continue
                ligadas.add(self.normalizar(sequencia))
        return ligadas

    def test_every_shortcut_of_the_dialog_is_really_bound(self):
        """A lista nao pode prometer uma tecla que a janela nao escuta."""
        ligadas = self.sequencias_ligadas()
        for sequencia in sorted(self.sequencias_da_tabela()):
            self.assertIn(sequencia, ligadas, sequencia)

    def test_every_bound_shortcut_is_in_the_dialog(self):
        """E o contrario, que e o lado que envelhece sozinho.

        Um atalho novo, ligado e nao listado, volta a ser o que este item veio
        consertar — e sem este teste ninguem notaria.
        """
        da_tabela = self.sequencias_da_tabela()
        for sequencia in sorted(self.sequencias_ligadas()):
            self.assertIn(sequencia, da_tabela, sequencia)

    def test_the_dialog_lists_the_three_shortcuts_that_have_no_button(self):
        """O motivo de existir um dialogo em vez de rotulos nos botoes."""
        rotulos = {
            rotulo
            for _titulo, atalhos in edit_window.KEYBOARD_SHORTCUTS
            for rotulo, _sequencia, _descricao in atalhos
        }
        self.assertLessEqual({"Ctrl+F", "Ctrl+L", "Ctrl+B"}, rotulos)

    def test_the_shortcut_window_opens_and_does_not_stack_copies(self):
        primeira = self.editor.open_shortcuts_window()
        self.pump()
        self.assertTrue(primeira.winfo_exists())

        segunda = self.editor.open_shortcuts_window()
        self.pump()
        self.assertIs(segunda, primeira)
        self.addCleanup(primeira.destroy)

    def test_the_footer_has_a_visible_way_in(self):
        """Um atalho para descobrir atalhos so serve a quem ja os descobriu."""
        self.assertEqual(self.editor.btn_shortcuts.cget("text"), "?")
        self.assertEqual(self.editor.btn_shortcuts.winfo_manager(), "pack")

    # -------------------------------------------------------------- foco

    def test_the_focused_text_gets_a_different_border(self):
        neutra = self.editor.text_border
        moldura = self.editor.trans_text.master

        self.editor.on_text_focus(self.editor.trans_text, True)
        self.pump()
        self.assertEqual(moldura.cget("highlightbackground"), self.editor.focus_border)
        self.assertNotEqual(self.editor.focus_border, neutra)

        self.editor.on_text_focus(self.editor.trans_text, False)
        self.pump()
        self.assertEqual(moldura.cget("highlightbackground"), neutra)

    def test_both_texts_answer_to_the_focus_event(self):
        """O bind existe nos DOIS; o original tambem recebe foco (para copiar)."""
        for texto in (self.editor.orig_text, self.editor.trans_text):
            self.assertIn("<FocusIn>", [str(s) for s in texto.bind()])
            self.assertIn("<FocusOut>", [str(s) for s in texto.bind()])

    # ---------------------------------------------------------- o "B"

    def test_the_bold_button_looks_different_when_it_is_on(self):
        desligado = self.editor.btn_bold.cget("fg_color")
        self.editor.toggle_bold_view()
        self.pump()
        ligado = self.editor.btn_bold.cget("fg_color")

        self.assertNotEqual(ligado, desligado)
        self.assertEqual(self.editor.btn_bold.cget("border_width"), 2)

        self.editor.toggle_bold_view()
        self.pump()
        self.assertEqual(self.editor.btn_bold.cget("fg_color"), desligado)
        self.assertEqual(self.editor.btn_bold.cget("border_width"), 0)

    def test_the_two_states_differ_in_both_themes(self):
        """O defeito era exatamente este: iguais no escuro, byte a byte."""
        ligado = edit_window.BOLD_ACTIVE_COLOR
        desligado, _hover = edit_window.theme_button_colors()
        for indice, tema in enumerate(("claro", "escuro")):
            self.assertNotEqual(
                ligado[indice].lower(), desligado[indice].lower(), tema
            )

    def test_the_off_state_comes_from_the_theme(self):
        """Restaurar com hexes copiados congela o botao no tema de quem copiou."""
        self.editor.toggle_bold_view()
        self.editor.toggle_bold_view()
        self.pump()
        esperado, _hover = edit_window.theme_button_colors()
        self.assertEqual(list(self.editor.btn_bold.cget("fg_color")), list(esperado))

    # ---------------------------------------------------------- o tema

    def test_changing_the_theme_repaints_the_pure_tk_widgets(self):
        """Os widgets CTk se viram sozinhos; estes precisavam de alguem.

        O rastreador do CustomTkinter chama o callback com o nome do modo, e e
        assim que ele e chamado aqui — sem depender de o Windows trocar de tema
        no meio do teste.
        """
        antes = {
            "pane": self.editor.main_pane.cget("bg"),
            "texto": self.editor.trans_text.cget("bg"),
        }
        original = edit_window.ctk.get_appearance_mode
        outro = "Light" if original() == "Dark" else "Dark"
        edit_window.ctk.get_appearance_mode = lambda: outro
        self.addCleanup(setattr, edit_window.ctk, "get_appearance_mode", original)

        self.editor.apply_theme_colors(outro)
        self.pump()

        self.assertNotEqual(self.editor.main_pane.cget("bg"), antes["pane"])
        self.assertNotEqual(self.editor.trans_text.cget("bg"), antes["texto"])
        self.assertEqual(self.editor.trans_text.cget("bg"), self.editor.text_bg)
        self.assertEqual(
            self.editor.trans_text.tag_cget("find_match", "background"),
            self.editor.find_bg,
        )

    def test_repainting_keeps_the_focus_border_of_the_focused_text(self):
        """A troca de tema nao pode apagar o sinal de foco de quem o tem."""
        self.editor.on_text_focus(self.editor.trans_text, True)
        self.editor.apply_theme_colors()
        self.pump()

        self.assertEqual(
            self.editor.trans_text.master.cget("highlightbackground"),
            self.editor.focus_border,
        )
        self.assertEqual(
            self.editor.orig_text.master.cget("highlightbackground"),
            self.editor.text_border,
        )

    def test_a_dead_window_does_not_raise_on_a_theme_change(self):
        """O rastreador guarda o callback numa lista de classe."""
        outro_editor = edit_window.open_translation_editor(self.app)
        self.pump()
        outro_editor.win.destroy()
        self.pump()

        outro_editor.apply_theme_colors("Dark")  # nao pode levantar


def contrast_ratio(frente, fundo):
    """A razao de contraste da WCAG entre duas cores `#rrggbb`.

    A formula mora no teste, e nao na producao: nada no programa precisa
    CALCULAR contraste — ele precisa ter cores que passem, e isso e uma
    afirmacao a conferir, nao um comportamento a executar.
    """
    def luminancia(cor):
        canais = [int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        canais = [
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in canais
        ]
        return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]

    a, b = luminancia(frente), luminancia(fundo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


class SemanticColorsPassContrastTests(unittest.TestCase):
    """Garantia F19 (cores): as cores de rotulo passam nos DOIS temas.

    Cada uma era um hex unico para os dois fundos, e um hex so nao serve a dois
    fundos: as quatro reprovavam o minimo de 4,5:1 em pelo menos um tema, e o
    ambar dos avisos dava 1,55:1 no claro — o pior par da janela, e justamente o
    texto que avisa que algo esta errado (ROADMAP 22.9).

    Sem Tk: sao numeros sobre constantes.
    """

    MINIMO = 4.5

    def pares(self):
        return {
            "verde (OK)": editor_common.OK_TEXT_COLOR,
            "ambar (aviso)": editor_common.WARNING_TEXT_COLOR,
            "vermelho (erro)": editor_common.ERROR_TEXT_COLOR,
            "cinza (discreto)": editor_common.MUTED_TEXT_COLOR,
        }

    def test_the_formula_agrees_with_a_known_pair(self):
        """Uma ancora: preto sobre branco e 21:1, por definicao."""
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=2)

    def test_every_semantic_color_passes_in_both_themes(self):
        claro, escuro = editor_common.LABEL_BACKGROUNDS
        for nome, (cor_clara, cor_escura) in self.pares().items():
            for cor, fundo, tema in (
                (cor_clara, claro, "claro"),
                (cor_escura, escuro, "escuro"),
            ):
                razao = contrast_ratio(cor, fundo)
                self.assertGreaterEqual(
                    razao, self.MINIMO,
                    f"{nome} no tema {tema}: {razao:.2f}:1 sobre {fundo}",
                )

    def test_the_old_single_color_would_fail(self):
        """O teste acima so prova algo se a cor ANTIGA nao passasse por ele.

        Sem esta ancora, um par escolhido por acaso pareceria uma correcao.
        """
        claro, escuro = editor_common.LABEL_BACKGROUNDS
        antigas = {"#16a34a": claro, "#f59e0b": claro, "#dc2626": escuro, "#64748b": escuro}
        for cor, fundo in antigas.items():
            self.assertLess(contrast_ratio(cor, fundo), self.MINIMO, cor)

    def test_the_selected_row_passes_too(self):
        """A linha selecionada usa fonte de 11 px: texto normal, 4,5:1."""
        claro, escuro = editor_common.SELECTED_ROW_COLOR
        branco = editor_common.SELECTED_ROW_TEXT_COLOR
        self.assertGreaterEqual(contrast_ratio(branco, claro), self.MINIMO)
        self.assertGreaterEqual(contrast_ratio(branco, escuro), self.MINIMO)


class ReviewStatusIsWrittenNotOnlyPaintedTests(EditorWindowTestCase):
    """Garantia F19 (status): o status da linha aberta aparece em PALAVRAS.

    Ele era comunicado so pela cor da borda do campo de nota. A docstring do
    metodo dizia "e diz qual e no rodape" e o metodo nao escrevia rodape nenhum:
    nenhum ponto da janela dizia o NOME do status — o rodape agrega contagens e a
    linha da lista rotula a rejeitada de "PEND", igual a pendente comum. Para um
    protanope as duas cores viram tons de oliva com 2,8:1 entre si, e a mensagem
    de confirmacao some em segundos (ROADMAP 22.9).
    """

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
        self.win = self.editor.win
        self.editor.select_index(0)
        self.pump()

    def test_the_current_match_highlight_is_readable(self):
        """Medido na TAG que a janela usa, e nao num hex escrito no teste.

        Foi a mutacao que sobreviveu a primeira rodada: o teste declarava a cor
        que esperava e media a propria declaracao, entao voltar a producao para o
        branco nao mudava nada nele. Aqui as duas cores saem do widget.
        """
        fundo = self.editor.trans_text.tag_cget("find_current", "background")
        frente = self.editor.trans_text.tag_cget("find_current", "foreground")

        self.assertEqual(fundo, self.editor.current_find_bg)
        self.assertGreaterEqual(contrast_ratio(frente, fundo), 4.5)
        # O branco era a cor anterior, e reprova nos dois temas — sem esta linha,
        # um fundo escurecido a ponto de o branco passar tambem contaria como
        # correcao, e ai a ocorrencia ATUAL deixaria de se distinguir das outras.
        self.assertLess(contrast_ratio("#ffffff", fundo), 4.5)

    def test_a_pending_line_says_nothing(self):
        """O padrao nao precisa de rotulo: escreve-lo em toda linha e ruido."""
        self.assertEqual(self.editor.review_status_label.cget("text"), "")
        self.assertEqual(self.editor.review_status_label.winfo_manager(), "")

    def test_rejecting_writes_the_word(self):
        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()

        self.assertEqual(self.editor.review_status_label.cget("text"), "Rejeitada")
        self.assertEqual(self.editor.review_status_label.winfo_manager(), "grid")

    def test_doubting_writes_the_other_word(self):
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()

        self.assertEqual(self.editor.review_status_label.cget("text"), "Em dúvida")

    def test_clearing_the_status_takes_the_word_out_of_the_way(self):
        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()
        self.editor.set_review_status(edit_window.REVIEW_STATUS_PENDING)
        self.pump()

        self.assertEqual(self.editor.review_status_label.cget("text"), "")
        self.assertEqual(self.editor.review_status_label.winfo_manager(), "")

    def test_the_word_and_the_border_say_the_same_thing(self):
        """Duas formas do mesmo fato, e nao duas fontes que podem divergir."""
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()

        self.assertEqual(
            list(self.editor.review_status_label.cget("text_color")),
            list(editor_common.WARNING_TEXT_COLOR),
        )
        self.assertEqual(
            list(self.editor.note_entry.cget("border_color")),
            list(editor_common.WARNING_TEXT_COLOR),
        )

    def test_the_word_follows_the_line_that_is_open(self):
        """Deixado na tela, ele afirmaria sobre a linha errada."""
        self.editor.set_review_status(edit_window.REVIEW_STATUS_REJECTED)
        self.pump()
        self.assertEqual(self.editor.review_status_label.cget("text"), "Rejeitada")

        self.editor.clear_current()
        self.pump()
        self.assertEqual(self.editor.review_status_label.cget("text"), "")


class LabelsAndWidthsFitTests(EditorWindowTestCase):
    """Garantia F20: o rotulo carrega o objeto, e a faixa cabe (ROADMAP 22.10).

    Duas familias que sao a mesma coisa vista de dois lados — a janela afirmando
    o que nao entrega.

    **Rotulos que colidiam.** Tres botoes "Limpar" faziam tres coisas diferentes
    (limpar a busca, desmarcar a selecao e limpar o status de revisao, que GRAVA
    no banco), e "Página" era quatro (duas setas de navegacao, o rotulo do campo
    de salto e o botao que MARCA a pagina inteira).

    **Larguras que nao fechavam.** Os numeros aqui sao medidos com `winfo_*` na
    janela de verdade, e nao calculados das constantes — a licao do 18.4, e o que
    a secao 22.14 exige deste item. Foi a medicao que mudou tres conclusoes do
    diagnostico:

    - o painel de sugestoes ficava com **109** px na largura minima, e nao 244;
    - na barra de lote nao era so o "Exportar" que sumia: o "Verificar"
      aparecia com 25 dos seus 80 px e o "Exportar" comecava em x=355 numa faixa
      de 300 — `pack` nao encolhe filho nenhum;
    - a barra de salto, que o diagnostico nem citava, deixava o campo da pagina
      com **11 px** — `grid` reparte a falta por todas as colunas.
    """

    module = edit_window

    # O campo da pagina precisa mostrar o numero que se digita nele. Quatro
    # digitos e o que um livro de 200 mil linhas pede (2.015 paginas de 100).
    LARGURA_MINIMA_DO_CAMPO = 40

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for i in range(3):
            save_translation(cur, f"the rook {i}", f"a torre {i}", "pt", "en")
        conn.commit()
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win

    # ------------------------------------------------------------- medida

    def moldar(self, largura=None, sash=None):
        """Poe a janela na largura pedida, fora da vista, e deixa o Tk assentar.

        Os `after` pendentes sao cancelados antes: `bring_window_to_front`
        levanta e maximiza a janela 50 ms depois de ela nascer, e disparar no meio
        da medida trocaria a geometria por baixo dela. Sao os mesmos `after` que
        o `GuiTestCase` cancela ao destruir a raiz, pelo mesmo motivo.

        O `deiconify` explicito vem logo depois, e nao e cerimonia: o
        `CTkToplevel` nasce ESCONDIDO — ele se retira para pintar a barra de
        titulo com a cor do tema e se mostra de novo por um `after`, que e um dos
        que acabaram de ser cancelados. Sem ele, todo `winfo_width` desta classe
        responde 1, que e o que um widget nao mapeado responde.

        A janela vai para +3000+3000 para nao aparecer na frente de quem esta
        trabalhando noutro programa enquanto a suite roda.
        """
        for after_id in self.win.tk.eval("after info").split():
            try:
                self.win.after_cancel(after_id)
            except tk.TclError:
                pass

        largura = edit_window.MIN_WIDTH if largura is None else largura
        self.win.geometry(f"{largura}x{edit_window.MIN_HEIGHT}+3000+3000")
        self.win.deiconify()
        self.assentar()
        self.editor.restore_pane_positions()
        self.assentar()
        if sash is not None:
            self.editor.main_pane.sash_place(0, sash, 0)
            self.assentar()

    def assentar(self, voltas=6):
        for _ in range(voltas):
            self.win.update_idletasks()
            self.root.update()

    # ------------------------------------------------------------ rotulos

    def rotulos_dos_botoes(self):
        """`{texto: [nomes dos atributos]}` de todo botao nomeado da janela."""
        rotulos = {}
        for nome in sorted(dir(self.editor)):
            if not nome.startswith("btn_"):
                continue
            widget = getattr(self.editor, nome)
            try:
                texto = str(widget.cget("text"))
            except (tk.TclError, ValueError, AttributeError):
                continue
            rotulos.setdefault(texto, []).append(nome)
        return rotulos

    def test_no_two_buttons_of_the_window_say_the_same_thing(self):
        """Um rotulo repetido obriga a deduzir o objeto da POSICAO do botao.

        A unica excecao e o "Ir", que aparece duas vezes na barra de salto — e la
        o objeto esta no rotulo do campo colado a ele ("Página" e "ID"), que e
        justamente o que os "Limpar" nao tinham.
        """
        repetidos = {
            texto: donos
            for texto, donos in self.rotulos_dos_botoes().items()
            if len(donos) > 1
        }
        self.assertEqual(sorted(repetidos), ["Ir"], repetidos)

    def test_the_three_clears_carry_their_object(self):
        self.assertEqual(self.editor.btn_clear_search.cget("text"), "Limpar busca")
        self.assertEqual(self.editor.btn_batch_clear.cget("text"), "Desmarcar")
        self.assertEqual(self.editor.btn_clear_status.cget("text"), "Limpar status")

    def test_the_batch_bar_does_not_borrow_the_word_of_the_navigation(self):
        """"Página" ao lado de "< Página" e "Página >" le-se como navegacao."""
        self.assertEqual(self.editor.btn_batch_page.cget("text"), "Marcar página")
        navegacao = {
            self.editor.btn_page_prev.cget("text"),
            self.editor.btn_page_next.cget("text"),
        }
        self.assertNotIn(self.editor.btn_batch_page.cget("text"), navegacao)

    # ------------------------------------------------------------ larguras

    def test_the_minimum_width_is_the_sum_of_what_the_panels_declare(self):
        """A janela nao pode pedir menos do que o que ela poe dentro de si.

        Sem esta conta os dois numeros vivem separados, que era o defeito: 1120
        declarados contra 1176 de soma, e a diferenca saia toda do mesmo painel.
        """
        self.assertEqual(
            edit_window.BOTTOM_PANE_MIN,
            edit_window.EDITOR_PANE_MIN
            + edit_window.SASH_WIDTH
            + edit_window.SUGGESTION_PANE_MIN,
        )
        self.assertEqual(
            edit_window.MIN_WIDTH,
            edit_window.LIST_PANE_MIN
            + edit_window.SASH_WIDTH
            + edit_window.BOTTOM_PANE_MIN
            + edit_window.MAIN_PANE_PADX,
        )

    def test_the_window_asks_the_manager_for_the_width_it_computed(self):
        """O `minsize` era escrito a mao, e era a segunda fonte da largura."""
        self.assertEqual(
            tuple(self.win.tk.call("wm", "minsize", self.win._w)),
            (edit_window.MIN_WIDTH, edit_window.MIN_HEIGHT),
        )

    def test_at_the_minimum_width_every_panel_gets_its_minimum(self):
        """O caso da PRIMEIRA abertura, e nao o de arrastar o divisor.

        `minsize` de `PanedWindow` so vale ao arrastar: no desenho inicial cada
        painel recebe o que pede e o ultimo fica com o resto — e o ultimo aqui e
        o de sugestoes.
        """
        self.moldar()
        for nome, painel, minimo in (
            ("lista", self.editor.list_frame, edit_window.LIST_PANE_MIN),
            ("baixo", self.editor.bottom_pane, edit_window.BOTTOM_PANE_MIN),
            ("editor", self.editor.text_frame, edit_window.EDITOR_PANE_MIN),
            ("sugestoes", self.editor.sugg_frame, edit_window.SUGGESTION_PANE_MIN),
        ):
            self.assertGreaterEqual(
                painel.winfo_width(), minimo,
                f"o painel de {nome} ficou com {painel.winfo_width()} de {minimo}",
            )

    def test_the_six_suggestion_buttons_are_whole_at_the_minimum_width(self):
        """Eram os seis rotulos cortados que o item veio consertar."""
        self.moldar()
        for nome in (
            "btn_refresh",
            "btn_apply_one",
            "btn_apply_all",
            "btn_add_gloss",
            "btn_reload_gloss",
            "btn_open_gloss",
        ):
            botao = getattr(self.editor, nome)
            self.assertGreaterEqual(
                botao.winfo_width(), botao.winfo_reqwidth(),
                f"{nome} ({botao.cget('text')!r}) ficou com "
                f"{botao.winfo_width()} de {botao.winfo_reqwidth()}",
            )

    def test_no_batch_button_lands_outside_the_bar(self):
        """Com o divisor no minimo, que e onde `pack` jogava dois deles fora.

        A afirmacao e sobre a POSICAO e nao sobre a largura, porque era assim que
        o defeito aparecia: o "Exportar" tinha os 80 px que pediu e comecava em
        x=355 numa faixa de 300 — desenhado inteiro, e inteiramente invisivel.
        """
        self.moldar(sash=edit_window.LIST_PANE_MIN)
        for nome in (
            "btn_batch_page",
            "btn_batch_all",
            "btn_batch_clear",
            "btn_batch_verify",
            "btn_batch_export",
        ):
            botao = getattr(self.editor, nome)
            faixa = botao.master.winfo_width()
            fim = botao.winfo_x() + botao.winfo_width()
            self.assertGreater(botao.winfo_width(), 1, nome)
            self.assertLessEqual(
                fim, faixa, f"{nome} termina em {fim} numa faixa de {faixa}"
            )

    def test_the_page_field_still_takes_a_page_number_at_the_minimum(self):
        """O "< Voltar" saiu desta barra por causa deste numero.

        `grid` reparte a falta por TODAS as colunas, e nao so pelas que tem peso:
        com o botao ali, os 106 px que a fileira pedia a mais saiam dos dois
        campos de digitar.
        """
        self.moldar(sash=edit_window.LIST_PANE_MIN)
        self.assertGreaterEqual(
            self.editor.page_entry.winfo_width(), self.LARGURA_MINIMA_DO_CAMPO,
            f"campo da pagina com {self.editor.page_entry.winfo_width()} px",
        )
        self.assertGreaterEqual(
            self.editor.id_entry.winfo_width(), self.LARGURA_MINIMA_DO_CAMPO,
            f"campo do id com {self.editor.id_entry.winfo_width()} px",
        )

    def test_the_back_button_is_still_on_screen(self):
        """Ele mudou de fileira, e nao de existencia (decisao do 19.3)."""
        self.assertEqual(self.editor.btn_go_back.winfo_manager(), "grid")
        self.assertIs(self.editor.btn_go_back.master, self.editor.page_nav)

    # ------------------------------------------------------ divisor gravado

    # Uma lista mais ESTREITA que o antigo minimo de 360, e nao mais larga que o
    # antigo maximo de 520: nesta tela (1360x768) a janela cabe no maximo 1340 de
    # painel, e com os 836 do painel de baixo a lista nunca passa de 496 px — o
    # maximo de 520 nunca chegava a valer aqui. Ver o ROADMAP 22.10.
    LISTA_GRAVADA = 330
    # Uma janela acima do minimo, e que cabe nesta tela: na largura MINIMA o teto
    # da lista e exatamente 320 (1164 de painel menos o divisor e os 836 do
    # painel de baixo), entao qualquer posicao gravada recuaria para la e o teste
    # nao distinguiria minimo nenhum.
    LARGURA_FOLGADA = 1300

    def test_the_list_panel_comes_back_the_size_it_was_left(self):
        """Os limites do divisor eram numeros escolhidos a parte dos paineis.

        Sem posicao gravada os dois codigos fazem a mesma coisa (nao mexem no
        divisor), e por isso este teste GRAVA uma — foi uma mutacao que mostrou
        que sem ela nada distinguia um minimo de 320 de um de 360.
        """
        self.editor.editor_settings["main_sash_y"] = self.LISTA_GRAVADA
        self.moldar(largura=self.LARGURA_FOLGADA)

        self.assertAlmostEqual(
            self.editor.list_frame.winfo_width(), self.LISTA_GRAVADA, delta=4
        )

    def test_a_saved_position_that_does_not_fit_comes_back_to_the_minimum(self):
        """E a outra ponta: numa janela estreita, a mesma posicao recua sozinha.

        Quem faz esse recuo e o `minsize` do painel de baixo — medido, com ele
        declarado o Tk honra o minimo dos vizinhos tambem ao POSICIONAR o
        divisor, e nao so ao arrasta-lo.
        """
        self.editor.editor_settings["main_sash_y"] = 900
        self.moldar()

        self.assertEqual(self.editor.list_frame.winfo_width(), edit_window.LIST_PANE_MIN)
        self.assertGreaterEqual(
            self.editor.sugg_frame.winfo_width(), edit_window.SUGGESTION_PANE_MIN
        )

    # -------------------------------------------------------------- rodape

    PIOR_CASO = {
        "dirty_label": "Alterações não salvas",
        "draft_label": "Rascunho restaurado 31/12/2026 23:59",
        "selection_label": "Item 201482/201482 · Não informado -> pt",
        "counts_label": (
            "Todas: 201.482 · Pendentes: 198.765 · Verificadas: 2.717 · "
            "QA: 12.345 · Rejeitadas: 999 · Em dúvida: 999"
        ),
    }

    def encher_o_rodape(self):
        self.moldar()
        for nome, texto in self.PIOR_CASO.items():
            getattr(self.editor, nome).configure(text=texto)
        self.editor.show_message(
            "Tradução salva e verificada; 12345 outro(s) original(is) "
            "também verificado(s)"
        )
        self.assentar()

    def test_the_stable_labels_survive_the_worst_case_footer(self):
        """Quem cede e o texto que ja vai sumir, e nao a contagem que fica.

        A ordem de empacotamento e o que decide isso: `pack` atende quem chega
        primeiro. Com os cinco rotulos em `side=LEFT` na ordem da leitura, o
        ultimo era o `counts_label`.
        """
        self.encher_o_rodape()
        for nome in ("dirty_label", "selection_label", "counts_label"):
            rotulo = getattr(self.editor, nome)
            self.assertGreaterEqual(
                rotulo.winfo_width(), rotulo.winfo_reqwidth(),
                f"{nome} ficou com {rotulo.winfo_width()} de "
                f"{rotulo.winfo_reqwidth()}",
            )

    def test_somebody_does_cede_in_the_worst_case(self):
        """A ancora do teste acima: se coubesse tudo, ele nao provaria nada."""
        self.encher_o_rodape()
        self.assertLess(
            self.editor.msg_label.winfo_width(),
            self.editor.msg_label.winfo_reqwidth(),
        )

    def test_the_two_stable_labels_sit_on_the_right(self):
        """A ORDEM protege; o lado e o que se le. Sao duas afirmacoes.

        Uma mutacao mostrou a diferenca: devolvendo as contagens para
        `side=LEFT` sem mexer na ordem, elas continuam inteiras — e a faixa passa
        a ter as duas informacoes estaveis espremidas entre a mensagem e o
        rascunho, que e o desenho que este item veio desfazer.
        """
        self.encher_o_rodape()

        for nome in ("selection_label", "counts_label"):
            rotulo = getattr(self.editor, nome)
            self.assertGreater(
                rotulo.winfo_x(), self.editor.msg_label.winfo_x(), nome
            )
            self.assertGreater(
                rotulo.winfo_x(), self.editor.draft_label.winfo_x(), nome
            )

    def test_a_long_message_is_cut_with_an_ellipsis(self):
        """Cortada por `preview`, e nao pelo Tk: o corte do Tk nao deixa sinal."""
        longa = (
            "Tradução salva e verificada; 12345 outro(s) original(is) "
            "também verificado(s)"
        )
        self.assertGreater(len(longa), edit_window.MESSAGE_PREVIEW_CHARS)

        self.editor.show_message(longa)
        self.pump()

        exibida = self.editor.msg_label.cget("text")
        self.assertEqual(len(exibida), edit_window.MESSAGE_PREVIEW_CHARS)
        self.assertTrue(exibida.endswith("..."), exibida)
        self.assertTrue(longa.startswith(exibida[:-3]), exibida)

    def test_a_short_message_is_left_alone(self):
        """Quase toda mensagem do editor cabe: cortar sempre seria ruido."""
        self.editor.show_message("Marcada como verificada")
        self.pump()

        self.assertEqual(
            self.editor.msg_label.cget("text"), "Marcada como verificada"
        )


class GestureCostTests(EditorWindowTestCase):
    """Garantia F21: o que se repete o dia inteiro tem atalho (ROADMAP 22.11).

    Cada teste aqui e um gesto que custava mais do que precisava num livro de
    20.000 linhas: um acorde a mais por linha, 30 idas a um botao para marcar um
    capitulo, dois cliques com deslocamento para aplicar uma sugestao, um clique
    so para pousar o cursor onde se vai digitar.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        for i in range(5):
            save_translation(cur, f"the rook {i}", f"a torre {i}", "pt", "en")
        conn.commit()
        self.ids = [r[0] for r in cur.execute("SELECT id FROM comments ORDER BY id")]
        conn.close()
        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win
        self.editor.select_index(0)
        self.pump()

    def linha(self, comment_id):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT translated_comment, verified, review_status, reviewer_note "
                "FROM comments WHERE id = ?",
                (comment_id,),
            ).fetchone()
        finally:
            conn.close()

    # -------------------------------------------------------- verificar-e-ir

    def test_verify_and_advance_has_a_shortcut(self):
        """`Ctrl+Enter` verifica e FICA; so o botao sabia verificar e avancar."""
        self.assertEqual(self.editor.get_index(), 0)

        self.editor.mark_and_next_shortcut()
        self.pump()

        self.assertEqual(self.linha(self.ids[0])[1], 1)
        self.assertEqual(self.editor.get_index(), 1)

    def test_the_old_shortcut_still_does_what_it_always_did(self):
        """Promover o `Ctrl+Enter` teria trocado o significado de um habito."""
        self.editor.verify_shortcut()
        self.pump()

        self.assertEqual(self.linha(self.ids[0])[1], 1)
        self.assertEqual(self.editor.get_index(), 0)

    # ------------------------------------------------------------- paginas

    def test_the_page_turns_with_the_keyboard(self):
        """`change_page` so existia nos botoes; nenhum `<Prior>/<Next>` no pacote.

        A pagina encolhe para duas linhas em vez de o banco crescer para 250: e o
        mesmo `change_page`, e ele recarrega a lista do banco a cada virada — um
        `total_rows` escrito a mao seria apagado pela primeira recarga.
        """
        original = edit_window.PAGE_SIZE
        edit_window.PAGE_SIZE = 2
        self.addCleanup(setattr, edit_window, "PAGE_SIZE", original)
        self.editor.reload_rows()
        self.pump()
        self.assertEqual(self.editor.page_count(), 3)

        self.editor.win.event_generate("<Control-Next>")
        self.pump()
        self.assertEqual(self.editor.state.page_index, 1)

        self.editor.win.event_generate("<Control-Prior>")
        self.pump()
        self.assertEqual(self.editor.state.page_index, 0)

    def test_the_bare_page_keys_are_left_to_the_text(self):
        """`PageDown` dentro de um comentario longo tem de rolar o comentario."""
        ligadas = {str(s) for s in self.editor.win.bind()}
        self.assertNotIn("<Prior>", ligadas)
        self.assertNotIn("<Next>", ligadas)

    # ---------------------------------------------------------- marcar tudo

    def test_marking_everything_takes_the_whole_filter(self):
        """A barra so sabia marcar a PAGINA: 3.000 resultados eram 30 idas."""
        self.editor.select_all_filtered_rows()
        self.pump()

        self.assertEqual(self.editor.state.selected_ids, set(self.ids))

    def test_marking_everything_obeys_the_status_filter(self):
        """"Tudo" e o que a lista mostra. Sem o filtro, marcaria as linhas limpas."""
        conn = initialize_database(self.db_path)
        conn.execute("UPDATE comments SET verified = 1 WHERE id = ?", (self.ids[0],))
        conn.commit()
        conn.close()

        self.editor.status_segment.set("Pendentes")
        self.editor.toggle_filter()
        self.pump()
        self.editor.select_all_filtered_rows()
        self.pump()

        self.assertEqual(self.editor.state.selected_ids, set(self.ids[1:]))

    def test_marking_more_than_a_page_asks_first(self):
        """Com 3.000 marcadas o revisor so ve o contador: a pergunta diz o numero."""
        original = edit_window.PAGE_SIZE
        edit_window.PAGE_SIZE = 2
        self.addCleanup(setattr, edit_window, "PAGE_SIZE", original)
        self.dialogs.askyesno_result = False

        self.assertIsNone(self.editor.select_all_filtered_rows())
        self.assertEqual(self.editor.state.selected_ids, set())
        self.assertTrue(
            any("5 traduções" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_marking_a_single_page_does_not_ask(self):
        """Com 100 linhas o revisor ve o que marcou; perguntar seria ruido."""
        self.editor.select_all_filtered_rows()

        self.assertEqual(self.dialogs.messages("askyesno"), [])

    # ------------------------------------------------------------ sugestoes

    def test_double_clicking_a_suggestion_applies_it(self):
        """Eram dois cliques com deslocamento ate o canto oposto do painel."""
        self.editor.set_translation_text("a torre de dama")
        self.editor.glossary = [("torre", "TORRE", "sugestão")]
        self.editor.refresh_suggestions()
        self.pump()
        self.assertTrue(self.editor.suggestion_buttons, "sem sugestao para aplicar")

        self.editor.apply_suggestion_at(0)
        self.pump()

        self.assertIn("TORRE", self.editor.trans_text.get("1.0", tk.END))

    def test_a_single_click_still_only_selects(self):
        """Quem quer ler a regra antes nao pode ser obrigado a aplicar para le-la."""
        self.editor.set_translation_text("a torre de dama")
        self.editor.glossary = [("torre", "TORRE", "sugestão")]
        self.editor.refresh_suggestions()
        self.pump()

        self.editor.select_suggestion(0)
        self.pump()

        self.assertEqual(self.editor.state.selected_suggestion, 0)
        self.assertNotIn("TORRE", self.editor.trans_text.get("1.0", tk.END))

    def test_every_suggestion_answers_the_double_click(self):
        """O bind e por botao: um laco que esqueca um deixaria linhas mortas.

        A pergunta e feita ao CANVAS do botao, e nao ao botao: o `CTkButton` e um
        quadro com um canvas e um rotulo dentro, e o `bind` dele repassa a
        sequencia aos dois filhos — perguntar ao quadro devolve `None`.
        """
        self.editor.set_translation_text("a torre e o bispo")
        self.editor.glossary = [
            ("torre", "TORRE", "sugestão"),
            ("bispo", "BISPO", "sugestão"),
        ]
        self.editor.refresh_suggestions()
        self.pump()

        self.assertEqual(len(self.editor.suggestion_buttons), 2)
        for botao in self.editor.suggestion_buttons:
            ligadas = [str(s) for s in botao._canvas.bind()]
            self.assertIn("<Double-Button-1>", ligadas, ligadas)

    # ------------------------------------------------------- foco no clique

    def com_foco(self):
        """Quem tem o foco DENTRO desta janela, pelo caminho do widget.

        `focus_get()` devolve `None` quando o programa inteiro nao esta ativo, e
        numa suite que roda em segundo plano isso e o normal — os dois lados da
        comparacao viriam `None` e o teste passaria sem afirmar nada.
        `focus_lastfor` responde "quem receberia o foco quando esta janela o
        tiver", que e a pergunta de verdade.

        O caminho, e nao o objeto: os widgets do CustomTkinter poem o foco no Tk
        puro que carregam dentro, e o caminho dele comeca pelo do CTk.
        """
        return str(self.win.focus_lastfor())

    def test_clicking_a_row_puts_the_cursor_where_typing_goes(self):
        """O segundo clique — dentro do texto — era obrigatorio para digitar."""
        self.editor.search_entry.focus_set()
        self.pump()

        self.editor.select_row_from_click(2)
        self.pump()

        self.assertTrue(
            self.com_foco().startswith(str(self.editor.trans_text)), self.com_foco()
        )

    def test_a_programmatic_reload_does_not_steal_the_focus(self):
        """Roubar o foco do campo de busca no meio de uma busca seria pior."""
        self.editor.search_entry.focus_set()
        self.pump()
        antes = self.com_foco()
        self.assertTrue(antes.startswith(str(self.editor.search_entry)), antes)

        self.editor.select_index(1)
        self.pump()

        self.assertEqual(self.com_foco(), antes)

    # ------------------------------------------------------ nota do revisor

    def test_editing_the_note_marks_the_window_dirty(self):
        """Nada marcava sujeira: `set_dirty` so olhava o texto da traducao."""
        self.assertFalse(self.editor.state.dirty)

        self.editor.reviewer_note_text.set("conferir com o autor")
        self.pump()

        self.assertTrue(self.editor.state.dirty)
        self.assertIn("não salvas", self.editor.dirty_label.cget("text"))

    def test_loading_a_line_with_a_note_does_not_look_dirty(self):
        """A propria carga povoa o campo: sem a comparacao, toda linha nasceria suja."""
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.editor.reviewer_note_text.set("termo inventado")
        self.editor.save_changes(False)
        self.pump()

        self.editor.select_index(2)
        self.pump()
        self.editor.select_index(0)
        self.pump()

        self.assertFalse(self.editor.state.dirty)

    def test_navigating_away_saves_the_note(self):
        """Editar a nota e navegar a descartava em silencio."""
        self.editor.reviewer_note_text.set("conferir com o autor")
        self.editor.navigate(1)
        self.pump()

        self.assertEqual(self.linha(self.ids[0])[3], "conferir com o autor")

    def test_enter_in_the_note_field_writes_it(self):
        """`Enter` no campo nao fazia nada — o ciclo de teclado nao fechava."""
        self.editor.reviewer_note_text.set("voltar a este")

        self.editor.save_note_shortcut()
        self.pump()

        self.assertEqual(self.linha(self.ids[0])[3], "voltar a este")

    def test_saving_the_note_does_not_undo_a_verification(self):
        """A nota e gravada ANTES da traducao, e nao depois.

        `set_review_status_by_id` mantem `verified` em lockstep com o status
        (garantia F10): chamada depois de um `mark_verified`, ela reescreveria o
        status ANTIGO por cima e derrubaria o `verified` junto.

        **A linha comeca "em dúvida", e nao pendente.** Foi uma mutacao que
        mostrou por que: com a linha pendente as duas ordens dao o mesmo
        resultado — o status vazio preserva o `verified` — e o teste passava com
        a producao certa e com a errada. E so com um status na linha que a ordem
        vira observavel.
        """
        self.editor.set_review_status(edit_window.REVIEW_STATUS_DOUBT)
        self.pump()
        self.editor.select_index(0)
        self.pump()
        self.assertEqual(self.linha(self.ids[0])[2], edit_window.REVIEW_STATUS_DOUBT)

        self.editor.reviewer_note_text.set("verificada com nota")
        self.editor.save_changes(False, mark_verified=True)
        self.pump()

        _traducao, verificada, status, nota = self.linha(self.ids[0])
        self.assertEqual(verificada, 1)
        self.assertEqual(status, edit_window.REVIEW_STATUS_PENDING)
        self.assertEqual(nota, "verificada com nota")

    def test_a_note_that_did_not_change_writes_nothing(self):
        """Navegar por 50 linhas nao pode carimbar 50 vezes (garantia R1)."""
        antes = self.linha(self.ids[0])
        self.editor.navigate(1)
        self.pump()
        self.editor.navigate(-1)
        self.pump()

        self.assertEqual(self.linha(self.ids[0]), antes)

    # ---------------------------------------------------------------- zoom

    def test_the_wheel_zooms_one_point_at_a_time(self):
        """O `delta` do Windows vale 120 por entalhe: multiplicar por ele daria 24 pt."""
        tamanho = self.editor.state.font_size

        self.editor.zoom_with_wheel(types.SimpleNamespace(delta=120))
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho + 1)

        self.editor.zoom_with_wheel(types.SimpleNamespace(delta=-120))
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho)

    def test_only_the_SIGN_of_the_wheel_matters(self):
        """So o sinal, e nao o valor: a divisao por 120 e o que este teste mata.

        Uma roda de alta resolucao manda `delta` pequeno — 40, 30 — e uma
        `delta // 120` engole todos eles: a roda simplesmente nao faz nada. E
        `delta` grande (dois entalhes num evento so) daria dois pontos de uma
        vez. Com `delta=±120`, que e o caso comum, as duas contas dao o mesmo
        numero — por isso o teste acima nao bastava.
        """
        tamanho = self.editor.state.font_size

        self.editor.zoom_with_wheel(types.SimpleNamespace(delta=40))
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho + 1)

        self.editor.zoom_with_wheel(types.SimpleNamespace(delta=360))
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho + 2)

        self.editor.zoom_with_wheel(types.SimpleNamespace(delta=-15))
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho + 1)

    def test_the_keyboard_zooms_too(self):
        """Ir de 12 a 18 pt eram seis cliques num botao de 42 px."""
        tamanho = self.editor.state.font_size

        self.editor.win.event_generate("<Control-plus>")
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho + 1)

        self.editor.win.event_generate("<Control-minus>")
        self.pump()
        self.assertEqual(self.editor.state.font_size, tamanho)

    def test_the_unshifted_key_zooms_in_too(self):
        """Onde o "+" nao pede Shift, o Tk entrega `<Control-equal>`."""
        tamanho = self.editor.state.font_size

        self.editor.win.event_generate("<Control-equal>")
        self.pump()

        self.assertEqual(self.editor.state.font_size, tamanho + 1)

    # ------------------------------------------------ o lote e o que se ve

    def test_verifying_a_batch_comes_back_to_the_line_that_was_open(self):
        """Era o unico recarregamento pos-acao que voltava ao topo da pagina."""
        self.editor.select_index(3)
        self.pump()
        self.editor.toggle_row_selection(0)
        self.dialogs.askyesno_result = True

        self.editor.verify_selected_rows()
        self.pump()

        self.assertEqual(self.editor.current["id"], self.ids[3])

    def test_the_confirmation_counts_what_is_outside_the_filters(self):
        """A selecao sobrevive a troca de arquivo, status e busca — e a
        confirmacao passa a dizer quantas das marcadas estao fora da lista."""
        self.editor.toggle_row_selection(0)
        self.editor.toggle_row_selection(1)
        conn = initialize_database(self.db_path)
        conn.execute("UPDATE comments SET verified = 1 WHERE id = ?", (self.ids[0],))
        conn.commit()
        conn.close()

        self.editor.status_segment.set("Pendentes")
        self.editor.toggle_filter()
        self.pump()
        self.dialogs.askyesno_result = False
        self.editor.verify_selected_rows()

        self.assertTrue(
            any("fora dos filtros atuais" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_the_confirmation_says_nothing_when_everything_is_visible(self):
        """A ancora: o aviso so pode aparecer quando ele e verdade."""
        self.editor.toggle_row_selection(0)
        self.dialogs.askyesno_result = False

        self.editor.verify_selected_rows()

        self.assertFalse(
            any("fora dos filtros" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_the_selection_survives_a_change_of_status_filter(self):
        """A decisao registrada: ela vive, e a confirmacao e que diz a verdade."""
        self.editor.toggle_row_selection(0)

        self.editor.status_segment.set("Pendentes")
        self.editor.toggle_filter()
        self.pump()

        self.assertEqual(self.editor.state.selected_ids, {self.ids[0]})

    # -------------------------------------------------- as outras posicoes

    def semear_posicoes(self, *arquivos):
        """Poe a MESMA traducao em varios arquivos — o comentario reusado.

        E o caso que o rodape resume em "e mais N posições (a mesma tradução)":
        um "Diagram" que serve a doze capitulos.
        """
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        ids = resolve_comment_ids(cur, "pt", ["the rook 0"], "en")
        for numero, arquivo in enumerate(arquivos, start=1):
            record_occurrences(
                cur, arquivo, [(1, numero, numero * 3, "the rook 0")], ids
            )
        conn.commit()
        conn.close()

    def test_the_origin_footer_opens_the_list_of_positions(self):
        """O rodape dizia "e mais N posições" e nenhum gesto mostrava QUAIS."""
        self.semear_posicoes("livro/cap01.pgn", "livro/cap07.pgn")

        self.editor.select_index(0)
        self.pump()
        self.assertEqual(self.editor.origin_occurrences, 2)

        janela = self.editor.open_occurrences_window()
        self.pump()
        self.assertIsNotNone(janela)
        self.addCleanup(janela.destroy)

        textos = [
            w.get("1.0", tk.END)
            for w in janela.winfo_children()
            if isinstance(w, tk.Text)
        ]
        self.assertTrue(textos, "a janela nao tem o texto das posicoes")
        self.assertIn("cap01.pgn", textos[0])
        self.assertIn("cap07.pgn", textos[0])

    def test_a_single_position_does_not_open_a_window(self):
        """Com uma so, o rodape ja E a lista inteira."""
        self.semear_posicoes("livro/cap01.pgn")

        self.editor.select_index(0)
        self.pump()

        self.assertIsNone(self.editor.open_occurrences_window())

    def test_the_footer_only_looks_clickable_when_it_is(self):
        """O cursor de mao e o unico sinal de que ali ha um alvo."""
        self.semear_posicoes("livro/cap01.pgn", "livro/cap07.pgn")

        self.editor.select_index(1)
        self.pump()
        self.assertEqual(str(self.editor.origin_label.cget("cursor")), "")

        self.editor.select_index(0)
        self.pump()
        self.assertEqual(str(self.editor.origin_label.cget("cursor")), "hand2")

    def test_the_footer_is_really_wired_to_the_click(self):
        """O metodo funcionar nao prova que alguem o chama.

        Foi uma mutacao que mostrou o buraco: tirar o `bind` do rodape deixava
        todos os outros testes verdes, porque eles chamavam
        `open_occurrences_window` na mao. A pergunta vai ao `_label` interno,
        porque o `bind` do `CTkLabel` repassa a sequencia ao rotulo e ao canvas
        que ele carrega dentro — perguntar ao quadro devolve `None`.
        """
        self.semear_posicoes("livro/cap01.pgn", "livro/cap07.pgn")
        self.editor.select_index(0)
        self.pump()

        ligadas = [str(s) for s in self.editor.origin_label._label.bind()]
        self.assertIn("<Button-1>", ligadas, ligadas)

    def test_the_shortcut_window_also_lists_the_mouse_gestures(self):
        """Tres gestos invisiveis a mais nao podem morar so no fonte (F18)."""
        janela = self.editor.open_shortcuts_window()
        self.pump()
        self.addCleanup(janela.destroy)

        rotulos = []
        for widget in janela.winfo_children():
            for filho in [widget] + list(widget.winfo_children()):
                try:
                    rotulos.append(str(filho.cget("text")))
                except (tk.TclError, ValueError, AttributeError):
                    continue

        self.assertIn("Mouse", rotulos)
        for rotulo, _descricao in edit_window.MOUSE_GESTURES:
            self.assertIn(rotulo, rotulos)


class OccurrenceLinesTests(unittest.TestCase):
    """`format_occurrence_lines` — sem Tk, que e o ponto de ela ser pura."""

    def test_the_whole_path_comes_along(self):
        """Dois capitulos com o mesmo nome de arquivo em pastas diferentes."""
        linhas = edit_window.format_occurrence_lines(
            [("livros/A/cap01.pgn", 1, 4, "12")]
        )
        self.assertEqual(linhas, ["livros/A/cap01.pgn · partida 1 · lance 12 · comentário 4"])

    def test_a_comment_before_the_first_move_still_has_a_locator(self):
        linhas = edit_window.format_occurrence_lines([("cap01.pgn", 2, 0, "")])
        self.assertEqual(linhas, ["cap01.pgn · partida 2 · comentário 0"])

    def test_a_row_without_a_file_says_so_instead_of_showing_a_blank(self):
        linhas = edit_window.format_occurrence_lines([("", 0, 1, "")])
        self.assertEqual(linhas, ["(sem arquivo) · comentário 1"])


class StatsWindowIsReallyNotEditableTests(EditorWindowTestCase):
    """Garantia F24: a janela "nao editavel" nao aceita edicao (ROADMAP 22.12).

    O `_block_typing` deixava passar QUALQUER tecla com Control, e os bindings de
    classe do Tk mapeiam sete delas para editar: Ctrl+V cola, Ctrl+X recorta,
    Ctrl+K apaga ate o fim da linha, Ctrl+D apaga o caractere, Ctrl+O abre linha,
    Ctrl+T transpoe e Ctrl+H apaga para tras. O docstring da janela ja dizia por
    que isso nao pode acontecer: "um relatorio editavel viraria um numero
    diferente do que o banco disse".
    """

    module = edit_window

    RELATORIO = "Total: 201.482\nVerificadas: 2.717\n"

    def setUp(self):
        super().setUp()
        self.janela = stats_window.StatsWindow(self.app, self.RELATORIO)
        self.addCleanup(self.janela.win.destroy)
        self.pump()
        self.win = self.janela.win
        self.texto = self.janela.text

    def conteudo(self):
        return self.texto.get("1.0", tk.END).strip()

    def evento(self, keysym, control=True):
        return types.SimpleNamespace(keysym=keysym, state=0x4 if control else 0)

    def test_copying_and_selecting_still_work(self):
        """Sao eles que fazem a janela ser copiavel — o proposito dela."""
        for tecla in ("c", "C", "a", "A", "Insert"):
            self.assertIsNone(
                self.janela._block_typing(self.evento(tecla)), tecla
            )

    def test_the_seven_editing_combinations_are_blocked(self):
        """A lista era NEGRA ("qualquer coisa com Control") e deixava as sete passar."""
        for tecla in ("v", "x", "k", "d", "o", "t", "h", "V", "X"):
            self.assertEqual(
                self.janela._block_typing(self.evento(tecla)), "break", tecla
            )

    def test_typing_a_letter_is_blocked(self):
        self.assertEqual(self.janela._block_typing(self.evento("z", control=False)), "break")

    def test_the_arrows_still_move(self):
        for tecla in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            self.assertIsNone(
                self.janela._block_typing(self.evento(tecla, control=False)), tecla
            )

    def test_pasting_through_the_virtual_event_does_nothing(self):
        """O Tk edita pelo evento virtual, entao e nele que a decisao pertence.

        Uma versao futura que mapeie outra tecla para `<<Paste>>` continua barrada
        sem ninguem precisar acrescenta-la a lista.

        **O evento e gerado no `_textbox` interno**, e nao no `CTkTextbox`: o
        widget do CustomTkinter e um quadro, e quem edita e o `tk.Text` que ele
        carrega dentro — e para la que o `bind` dele repassa tudo. Gerado no
        quadro, o evento nao chega a lugar nenhum e o teste passa com a producao
        certa E com a errada, que foi o que uma mutacao mostrou.
        """
        self.win.clipboard_clear()
        self.win.clipboard_append("NUMERO INVENTADO")
        self.texto._textbox.focus_set()
        self.pump()

        self.texto._textbox.event_generate("<<Paste>>")
        self.pump()

        self.assertEqual(self.conteudo(), self.RELATORIO.strip())

    def test_the_paste_would_work_without_the_guard(self):
        """A ancora: um `Text` comum, no mesmo cenario, aceita a colagem.

        Sem ela, "o texto nao mudou" valeria tambem por o evento nao ter chegado
        a lugar nenhum — que e exatamente como o teste acima estava errado antes.
        """
        self.win.clipboard_clear()
        self.win.clipboard_append("NUMERO INVENTADO")
        solto = tk.Text(self.win)
        solto.insert("1.0", self.RELATORIO)
        self.addCleanup(solto.destroy)
        solto.focus_set()
        self.pump()

        solto.event_generate("<<Paste>>")
        self.pump()

        self.assertIn("NUMERO INVENTADO", solto.get("1.0", tk.END))

    def test_cutting_through_the_virtual_event_does_nothing(self):
        self.texto._textbox.tag_add(tk.SEL, "1.0", "1.5")
        self.texto._textbox.focus_set()
        self.pump()

        self.texto._textbox.event_generate("<<Cut>>")
        self.pump()

        self.assertEqual(self.conteudo(), self.RELATORIO.strip())

    def test_the_csv_button_only_exists_when_there_are_tables(self):
        """Um "Salvar CSV" que grava um arquivo vazio e pior do que nenhum."""
        self.assertEqual(self.janela.btn_save_csv.winfo_manager(), "")

    def test_the_csv_button_appears_with_tables(self):
        janela = stats_window.StatsWindow(
            self.app,
            self.RELATORIO,
            tables=[("progresso-por-obra", ["arquivo"], [("cap01.pgn",)])],
        )
        self.addCleanup(janela.win.destroy)
        self.pump()

        self.assertEqual(janela.btn_save_csv.winfo_manager(), "pack")

    def test_the_csv_has_a_block_per_table(self):
        """Um arquivo so: as tres tabelas sao lidas juntas."""
        janela = stats_window.StatsWindow(
            self.app,
            self.RELATORIO,
            tables=[
                ("progresso-por-obra", ["arquivo", "linhas"], [("cap01.pgn", 120)]),
                ("atividade-por-dia", ["dia", "edicoes"], [("2026-07-31", 12)]),
            ],
        )
        self.addCleanup(janela.win.destroy)
        self.pump()
        destino = Path(self.base) / "estatisticas.csv"
        self.file_dialogs.answer = str(destino)

        self.assertEqual(janela.save_csv(), str(destino))

        linhas = destino.read_text(encoding="utf-8-sig").splitlines()
        self.assertIn("progresso-por-obra", linhas)
        self.assertIn("atividade-por-dia", linhas)
        self.assertIn("cap01.pgn,120", linhas)
        self.assertIn("2026-07-31,12", linhas)

    def test_giving_up_on_the_dialog_writes_nothing(self):
        janela = stats_window.StatsWindow(
            self.app, self.RELATORIO, tables=[("t", ["a"], [("b",)])]
        )
        self.addCleanup(janela.win.destroy)
        self.file_dialogs.answer = ""

        self.assertIsNone(janela.save_csv())


class HistoryWindowSaysWhatChangedTests(EditorWindowTestCase):
    """Garantia F25: o historico pergunta antes e mostra o que mudou (22.12).

    Era a unica restauracao do programa sem confirmacao — restaurar o banco
    pergunta, o backup do glossario pergunta, ate excluir UMA regra pergunta —,
    com os dois botoes de restaurar colados no "Fechar". E os dois textos
    "Anterior"/"Nova" nao pintavam o diff que a previa do 19.5 ja sabia pintar.
    """

    module = edit_window

    def setUp(self):
        super().setUp()
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        save_translation(cur, "the rook", "a torre", "pt", "en")
        conn.commit()
        self.comment_id = cur.execute("SELECT id FROM comments").fetchone()[0]
        conn.close()

        self.editor = edit_window.open_translation_editor(self.app)
        self.pump()
        self.win = self.editor.win
        self.editor.select_index(0)
        self.pump()

        # Duas versoes no historico: a original e uma edicao.
        self.editor.set_translation_text("a TORRE de dama", mark_dirty=True)
        self.editor.save_changes(False)
        self.pump()

    def abrir(self):
        janela = self.editor.open_history_window()
        self.pump()
        self.addCleanup(janela.win.destroy)
        return janela

    def traducao(self):
        conn = initialize_database(self.db_path)
        try:
            return conn.execute(
                "SELECT translated_comment FROM comments WHERE id = ?",
                (self.comment_id,),
            ).fetchone()[0]
        finally:
            conn.close()

    def test_restoring_asks_first(self):
        janela = self.abrir()
        self.dialogs.askyesno_result = False

        janela.restore_selected(2)
        self.pump()

        self.assertEqual(self.traducao(), "a TORRE de dama")
        self.assertTrue(self.dialogs.messages("askyesno"), "nao perguntou nada")

    def test_the_question_shows_what_would_come_in(self):
        """E o que distingue "Restaurar anterior" de "Restaurar nova"."""
        janela = self.abrir()
        self.dialogs.askyesno_result = False

        janela.restore_selected(2)

        self.assertTrue(
            any("a torre" in m for m in self.dialogs.messages("askyesno")),
            self.dialogs.messages("askyesno"),
        )

    def test_saying_yes_restores(self):
        janela = self.abrir()
        self.dialogs.askyesno_result = True

        janela.restore_selected(2)
        self.pump()

        self.assertEqual(self.traducao(), "a torre")

    def test_both_sides_paint_what_changed(self):
        janela = self.abrir()
        self.pump()

        for caixa in (janela.previous_text, janela.new_text):
            faixas = caixa.tag_ranges("diff")
            self.assertTrue(faixas, "nenhum trecho pintado")

    def test_the_two_sides_use_the_colors_of_the_preview(self):
        """As mesmas do 19.5: remocao de um lado, acerto do outro."""
        janela = self.abrir()

        self.assertEqual(
            janela.previous_text.tag_cget("diff", "background"),
            self.editor.diff_removed_bg,
        )
        self.assertEqual(
            janela.new_text.tag_cget("diff", "background"),
            self.editor.diff_added_bg,
        )

    def test_the_row_says_how_much_changed(self):
        """Entre 100 linhas com o mesmo rotulo, o tamanho e o que distingue."""
        janela = self.abrir()

        self.assertIn("trecho(s)", janela.buttons[0].cget("text"))

    def test_the_detail_says_it_too(self):
        janela = self.abrir()

        self.assertIn("trecho(s)", janela.diff_label.cget("text"))

    def test_the_cut_at_a_hundred_versions_is_announced(self):
        """A lista simplesmente terminava, e a linha parecia comecar no meio."""
        conn = initialize_database(self.db_path)
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO comment_history "
            "(comment_id, action, previous_translation, new_translation, "
            " previous_verified, new_verified) VALUES (?, 'edit', ?, ?, 0, 0)",
            [
                (self.comment_id, f"versao {n}", f"versao {n + 1}")
                for n in range(history_window.HISTORY_LIMIT)
            ],
        )
        conn.commit()
        conn.close()

        janela = self.abrir()

        self.assertIn(
            str(history_window.HISTORY_LIMIT), janela.limit_label.cget("text")
        )

    def test_a_short_history_says_nothing(self):
        """Um aviso de corte numa linha com duas edicoes seria ruido."""
        janela = self.abrir()

        self.assertEqual(janela.limit_label.cget("text"), "")


class GlossaryPreviewUsesTheRealPipelineTests(EditorWindowTestCase):
    """Garantia S17: o "Teste rápido" usa a conversao de verdade (22.12).

    Ele trabalhava com os pares crus, e por isso divergia da aplicacao em quatro
    pontos: prioridade descartada, escopo ignorado, `@casa@` inerte e apenas a
    PRIMEIRA ocorrencia trocada. E a licao da garantia S9 escrita noutro lugar —
    o anuncio nao IMITA o criterio da aplicacao, ele USA o criterio.
    """

    module = glossary_editor

    def abrir(self, entradas):
        save_glossary_entries(entradas)
        self.editor = glossary_editor.open_glossary_editor(self.app)
        self.pump()
        self.win = self.editor.win
        return self.editor

    def previa(self):
        return self.editor.preview_text.get("1.0", tk.END).strip()

    def test_the_square_placeholder_is_expanded(self):
        """Uma linha com `@casa@` e 64 regras na aplicacao e casava NADA na previa."""
        self.abrir([("@casa@-torre", "torre de @casa@", "sugestão")])
        self.editor.select_entry(0)
        self.editor.test_text_var.set("o e4-torre avanca")

        self.editor.refresh_preview()
        self.pump()

        self.assertIn("torre de e4", self.previa())

    def test_every_occurrence_is_replaced_and_not_only_the_first(self):
        """O pipeline troca todas; a previa mostrava um resultado impossivel."""
        self.abrir([("bishop", "bispo", "sugestão")])
        self.editor.select_entry(0)
        self.editor.test_text_var.set("bishop takes bishop")

        self.editor.refresh_preview()
        self.pump()

        self.assertEqual(self.previa(), "bispo takes bispo")

    def test_priority_decides_in_the_preview_as_it_decides_in_the_pipeline(self):
        """Com uma regra promovida, a previa dava um resultado e o pipeline outro.

        E a previa ficava contradizendo o banner de conflito exibido ao lado dela
        (garantia S9), que ja anunciava a vencedora certa.
        """
        self.abrir(
            [
                ("the rook", "a torre", "sugestão"),
                ("the rook", "o roque", "sugestão"),
            ]
        )
        # A segunda promovida: prioridade decide antes do comprimento (S10).
        self.editor.state.entries[1] = ("the rook", "o roque", "suggestion", 5, "")

        self.editor.test_text_var.set("the rook is strong")
        self.editor.apply_all_to_preview()
        self.pump()

        self.assertIn("o roque", self.previa())

    def test_a_rule_scoped_to_another_pair_does_not_show_up(self):
        """O escopo era ignorado: a previa aplicava regra de par nenhum (S11)."""
        self.app.source_language = tk.StringVar(value="en")
        self.abrir([("movimento", "lance", "sugestão")])
        self.editor.state.entries[0] = ("movimento", "lance", "suggestion", 0, "en>it")

        self.editor.test_text_var.set("o movimento seguinte")
        self.editor.apply_all_to_preview()
        self.pump()

        self.assertEqual(self.previa(), "o movimento seguinte")

    def test_the_same_rule_shows_up_for_its_own_pair(self):
        """A ancora: sem ela, "nao apareceu" valeria por qualquer motivo."""
        self.app.source_language = tk.StringVar(value="en")
        self.abrir([("movimento", "lance", "sugestão")])
        self.editor.state.entries[0] = ("movimento", "lance", "suggestion", 0, "en>pt")

        self.editor.test_text_var.set("o movimento seguinte")
        self.editor.apply_all_to_preview()
        self.pump()

        self.assertEqual(self.previa(), "o lance seguinte")

    def test_an_empty_rule_leaves_the_text_alone(self):
        self.abrir([("bishop", "bispo", "sugestão")])
        self.editor.new_entry()
        self.editor.test_text_var.set("bishop takes bishop")

        self.editor.refresh_preview()
        self.pump()

        self.assertEqual(self.previa(), "bishop takes bishop")


class GlossaryEditorParityTests(EditorWindowTestCase):
    """Garantia S18: o editor de glossario anda pelo teclado (ROADMAP 22.12).

    `connect_events` ligava dois atalhos — Ctrl+S e Ctrl+N — contra os treze do
    editor de traducoes. Os que faltavam sao os do fluxo de quem varre uma lista:
    achar, andar e virar pagina.
    """

    module = glossary_editor

    def setUp(self):
        super().setUp()
        save_glossary_entries(
            [(f"termo {n}", f"traducao {n}", "sugestão") for n in range(6)]
        )
        self.editor = glossary_editor.open_glossary_editor(self.app)
        self.pump()
        self.win = self.editor.win

    def test_control_l_goes_to_the_search_field(self):
        # O `CTkToplevel` nasce escondido (ele se retira para pintar a barra de
        # titulo) e se mostra por um `after`. Num widget de janela que nunca foi
        # mapeada o Tk nao registra foco nenhum, e a pergunta abaixo responderia
        # sempre "a propria janela".
        self.win.deiconify()
        self.pump()
        self.editor.orig_text.focus_set()
        self.pump()

        self.editor.focus_search()
        self.pump()

        # Pelo caminho do widget e por `focus_lastfor`: ver `com_foco` na classe
        # dos gestos — `focus_get()` responde `None` com o programa em segundo
        # plano, que e como esta suite roda.
        foco = str(self.win.focus_lastfor())
        self.assertTrue(foco.startswith(str(self.editor.search_entry)), foco)

    def test_alt_right_walks_to_the_next_entry(self):
        self.editor.select_entry(0)
        self.pump()

        self.editor.step_entry(1)
        self.pump()

        self.assertEqual(self.editor.state.selected_index, 1)

    def test_alt_left_walks_back(self):
        self.editor.select_entry(2)
        self.pump()

        self.editor.step_entry(-1)
        self.pump()

        self.assertEqual(self.editor.state.selected_index, 1)

    def test_it_stops_at_the_ends_instead_of_wrapping(self):
        """Dar a volta faria `Alt+→` no fim da lista parecer que nada aconteceu."""
        self.editor.select_entry(0)
        self.pump()

        self.assertIsNone(self.editor.step_entry(-1))
        self.assertEqual(self.editor.state.selected_index, 0)

    def test_walking_follows_the_filtered_list_and_not_the_file(self):
        """Com um filtro ativo, +1 no indice do arquivo pousaria fora da tela."""
        self.editor.search_text.set("termo 3")
        self.editor.apply_search()
        self.pump()
        visiveis = list(self.editor.state.filtered_indices)
        self.assertEqual(len(visiveis), 1, visiveis)

        self.editor.select_entry(visiveis[0])
        self.pump()

        self.assertIsNone(self.editor.step_entry(1))

    def test_the_four_new_shortcuts_are_bound(self):
        ligadas = {str(s) for s in self.win.bind()}
        for sequencia in (
            "<Control-Key-l>",
            "<Alt-Key-Left>",
            "<Alt-Key-Right>",
            "<Control-Key-Prior>",
            "<Control-Key-Next>",
        ):
            self.assertIn(sequencia, ligadas, sequencia)

    def test_the_load_error_opens_in_front_of_the_editor(self):
        """Era o unico `messagebox` do arquivo sem `parent`: abria ATRAS."""
        fonte = inspect.getsource(glossary_editor)
        for pedaco in fonte.split("messagebox.show")[1:]:
            chamada = pedaco[: pedaco.index(")\n") + 1]
            self.assertIn("parent=", chamada, chamada)


if __name__ == "__main__":
    unittest.main()
