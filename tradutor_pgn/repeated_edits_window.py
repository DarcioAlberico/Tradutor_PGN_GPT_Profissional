"""A subjanela "Trocas repetidas nesta obra" (garantia S21, ROADMAP 28.5).

Lista os pares `antes -> depois` que a revisao mais digitou nas linhas de um
arquivo, diz se ja ha regra para cada um e oferece criar a `automatic` e
aplica-la as pendentes do arquivo. E a unica ferramenta da secao 28 que vale
para qualquer motor, qualquer livro e qualquer par: ela capitaliza o trabalho
enquanto ele acontece.

Modeless, como a de historico e pela mesma razao: a lista do editor continua
clicavel, e "Ver exemplo" a usa. O arquivo e o par sao fixados na abertura — a
janela fala de UMA obra, e trocar o filtro do editor por baixo dela nao pode
mudar do que ela esta falando.
"""

from contextlib import closing
import os
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .database import fetch_file_edit_events, initialize_database
from .db_tools import apply_automatic_rules_to_database, preview_automatic_rule_impact
from .editor_common import (
    MUTED_TEXT_COLOR,
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    preview,
)
from .editor_widgets import render_row_buttons
from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_SCOPE_SEPARATOR,
    add_glossary_entry,
    filter_glossary_entries_by_type,
    load_glossary_entry_details,
    load_interactive_substitutions,
)
from .repeated_edits import repeated_edits_report
from .window_utils import bring_window_to_front


def rule_scope_for_pair(source_language, target_language):
    """O escopo da regra criada daqui: o par do editor, ou so o destino.

    `en>pt` quando a origem esta declarada, `pt` quando o editor esta em "Todos"
    — a troca foi vista neste destino, e e para ele que a regra vale (garantia
    S11: uma regra de portugues nao pode corromper o italiano).
    """
    if source_language:
        return f"{source_language}{GLOSSARY_SCOPE_SEPARATOR}{target_language}"
    return target_language or ""


def describe_pair(item):
    """"94x em 94 linhas  'o jogo' -> 'a partida'  |  sugestao" — a linha da lista."""
    return (
        f"{item['count']}x em {item['lines']} linha(s)   "
        f"{preview(item['old'], 34)!r} -> {preview(item['new'], 34)!r}"
        f"   |   {item['rule_label']}"
    )


def describe_summary(events, items):
    """O cabecalho: quantas edicoes humanas a obra tem e quantos pares repetidos.

    Diz tambem quando NAO ha o que mostrar, e por que: um arquivo recem
    traduzido nao tem edicao nenhuma, e uma lista vazia sem explicacao se le como
    "a ferramenta nao funcionou".
    """
    if not events:
        return (
            "Nenhuma edição humana registrada nas linhas deste arquivo ainda. "
            "A lista nasce da revisão: volte depois de editar algumas linhas."
        )
    if not items:
        return (
            f"{len(events)} edição(ões) humana(s) nesta obra, "
            "nenhuma troca repetida ainda."
        )
    return (
        f"{len(events)} edição(ões) humana(s) nesta obra; "
        f"{len(items)} troca(s) repetida(s) listada(s)."
    )


def already_automatic(item):
    """Ja existe automatica que produz exatamente isto? Nao ha o que criar."""
    return (
        item.get("rule_type") == GLOSSARY_RULE_AUTOMATIC
        and item.get("rule_produces") == item["new"]
    )


class RepeatedEditsWindow:
    """A janela. Le o historico uma vez por abertura e a cada regra criada."""

    def __init__(self, editor, source_file, target_language, source_language=None):
        self.editor = editor
        self.app = editor.app
        self.source_file = source_file
        self.target_language = target_language
        self.source_language = source_language

        self.events = []
        self.items = []
        self.buttons = []
        self.selected = None

        self.build()
        self.refresh()

    # ------------------------------------------------------------- construcao

    def build(self):
        nome = os.path.basename(self.source_file) or self.source_file
        self.win = ctk.CTkToplevel(self.editor.win)
        self.win.title(f"Trocas repetidas - {nome}")
        self.win.geometry("960x540")
        self.win.minsize(760, 400)
        self.win.transient(self.editor.win)
        # `maximize=False` pela razao da janela de historico: modeless PARA QUE
        # a lista do editor continue acessivel, e maximizar a taparia.
        bring_window_to_front(self.win, self.editor.win, maximize=False)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)

        self.summary_label = ctk.CTkLabel(
            self.win, text="", anchor="w", justify=tk.LEFT, wraplength=900
        )
        self.summary_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        self.rows_frame = ctk.CTkScrollableFrame(self.win)
        self.rows_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        detail = ctk.CTkFrame(self.win, corner_radius=8)
        detail.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        detail.columnconfigure(0, weight=1)

        self.detail_label = ctk.CTkLabel(
            detail, text="", anchor="w", justify=tk.LEFT, wraplength=900
        )
        self.detail_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))

        actions = ctk.CTkFrame(detail, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.hint_label = ctk.CTkLabel(
            actions, text="", anchor="w", text_color=MUTED_TEXT_COLOR
        )
        self.hint_label.pack(side=tk.LEFT)

        btn_close = ctk.CTkButton(actions, text="Fechar", width=90, command=self.win.destroy)
        btn_close.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_example = ctk.CTkButton(
            actions, text="Ver exemplo", width=110, command=self.show_example
        )
        self.btn_example.pack(side=tk.RIGHT, padx=6)
        self.btn_create = ctk.CTkButton(
            actions,
            text="Criar automática e aplicar",
            width=190,
            command=self.create_automatic_rule,
        )
        self.btn_create.pack(side=tk.RIGHT, padx=6)

    # ------------------------------------------------------------------ dados

    def load(self):
        with closing(initialize_database(self.app.output_db)) as conn:
            self.events = fetch_file_edit_events(
                conn.cursor(),
                self.source_file,
                self.target_language,
                self.source_language,
            )
        self.items = repeated_edits_report(self.events, load_glossary_entry_details())

    def refresh(self, keep=None):
        """Rele o banco e o glossario e refaz a lista.

        `keep` e o par `(old, new)` a manter selecionado: depois de criar uma
        regra, a linha continua a mesma e so a coluna "regra" muda.
        """
        self.load()
        self.buttons = render_row_buttons(
            self.rows_frame,
            self.items,
            self.build_row_button,
            "Nenhuma troca repetida.",
        )
        self.summary_label.configure(text=describe_summary(self.events, self.items))
        self.selected = None
        if not self.items:
            self.clear_detail()
            return
        indice = 0
        if keep is not None:
            for posicao, item in enumerate(self.items):
                if (item["old"], item["new"]) == keep:
                    indice = posicao
                    break
        self.select(indice)

    # ------------------------------------------------------------------ lista

    def build_row_button(self, frame, index, item):
        return ctk.CTkButton(
            frame,
            text=describe_pair(item),
            anchor="w",
            fg_color=ROW_COLOR,
            hover_color=ROW_HOVER_COLOR,
            text_color=ROW_TEXT_COLOR,
            command=lambda i=index: self.select(i),
        )

    def select(self, index):
        if not (0 <= index < len(self.items)):
            return
        anterior = self.selected
        if anterior is not None and 0 <= anterior < len(self.buttons):
            self.buttons[anterior].configure(fg_color=ROW_COLOR, text_color=ROW_TEXT_COLOR)
        self.selected = index
        if index < len(self.buttons):
            self.buttons[index].configure(
                fg_color=SELECTED_ROW_COLOR, text_color=SELECTED_ROW_TEXT_COLOR
            )
        self.show_detail(self.items[index])

    def show_detail(self, item):
        self.detail_label.configure(
            text=(
                f"Antes: {item['old']!r}\n"
                f"Depois: {item['new']!r}\n"
                f"{item['count']} ocorrência(s) em {item['lines']} linha(s); "
                f"primeiro exemplo: ID {item['example_id']}\n"
                f"Regra no glossário: {item['rule_label']}"
            )
        )
        if already_automatic(item):
            self.btn_create.configure(state="disabled")
            self.hint_label.configure(text="Já há regra automática para esta troca.")
        else:
            self.btn_create.configure(state="normal")
            escopo = rule_scope_for_pair(self.source_language, self.target_language)
            self.hint_label.configure(text=f"A regra nova vale para o escopo {escopo!r}.")
        self.btn_example.configure(state="normal")

    def clear_detail(self):
        self.detail_label.configure(text="")
        self.hint_label.configure(text="")
        self.btn_create.configure(state="disabled")
        self.btn_example.configure(state="disabled")

    def current_item(self):
        if self.selected is None or not (0 <= self.selected < len(self.items)):
            return None
        return self.items[self.selected]

    # ----------------------------------------------------------------- acoes

    def show_example(self):
        """Posiciona o editor no primeiro comentario em que a troca apareceu.

        Pela mesma maquina do "Ir para ID" (`jump_to_id`): filtros e ordem
        ativos. Se a linha saiu do filtro atual, o editor diz — nao a janela.
        """
        item = self.current_item()
        if item is None:
            return
        if not self.editor.jump_to_id(item["example_id"]):
            messagebox.showinfo(
                "Trocas repetidas",
                f"A tradução {item['example_id']} não está na lista "
                "com os filtros atuais do editor.",
                parent=self.win,
            )

    def create_automatic_rule(self):
        """Cria a regra `automatic` e oferece aplica-la as pendentes do arquivo.

        Duas perguntas, e sao perguntas diferentes: a primeira e a de S20 —
        quantas pendentes do ESCOPO DA REGRA ela alteraria, com dez exemplos,
        antes de gravar no glossario; a segunda e a de "Aplicar Automaticas"
        restrita a esta obra e a esta regra (S19), com a previa e o backup de
        sempre. Recusar a primeira nao grava nada; recusar a segunda deixa a
        regra criada, valendo para as traducoes novas.
        """
        item = self.current_item()
        if item is None or already_automatic(item):
            return
        escopo = rule_scope_for_pair(self.source_language, self.target_language)
        entrada = (item["old"], item["new"], GLOSSARY_RULE_AUTOMATIC, 0, escopo)
        par = (item["old"], item["new"])

        def aplicado(_stats):
            if self.win.winfo_exists():
                self.refresh(keep=par)

        def decidido(promover):
            if not promover or not self.win.winfo_exists():
                return
            try:
                resultado = add_glossary_entry(
                    item["old"],
                    item["new"],
                    rule_type=GLOSSARY_RULE_AUTOMATIC,
                    scope=escopo,
                )
            except Exception as exc:
                messagebox.showerror(
                    "Trocas repetidas",
                    f"Erro ao gravar a regra no glossário:\n{exc}",
                    parent=self.win,
                )
                return
            self.notify_glossary_change()
            if resultado["status"] != "inserted":
                messagebox.showinfo(
                    "Trocas repetidas",
                    "Esta regra já existia no glossário.",
                    parent=self.win,
                )
            self.refresh(keep=par)
            apply_automatic_rules_to_database(
                self.app,
                target_language=self.target_language,
                parent=self.win,
                on_finish=aplicado,
                source_language=self.source_language,
                source_file=self.source_file,
                automatic_rules=filter_glossary_entries_by_type(
                    [entrada], GLOSSARY_RULE_AUTOMATIC
                ),
            )

        preview_automatic_rule_impact(
            self.app, entrada, parent=self.win, on_decision=decidido
        )

    def notify_glossary_change(self):
        """O mesmo aviso que o editor de glossario da ao gravar (S5/S11).

        O editor de traducoes recarrega o recorte do par dele por este
        callback; sem o aviso, a regra recem-criada so apareceria na proxima
        abertura.
        """
        self.app.glossary_substitutions = load_interactive_substitutions()
        for callback in list(getattr(self.app, "glossary_change_callbacks", [])):
            callback(self.app.glossary_substitutions)
