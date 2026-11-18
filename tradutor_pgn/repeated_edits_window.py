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
from .curation_state import CandidateIgnored, available_candidate, candidate_key, ignored_keys, restore_ignored, set_ignored
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
from .editor_widgets import attach_tooltip, render_row_buttons
from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_SCOPE_SEPARATOR,
    initialize_catalog_glossary,
    _default_substitutions_path,
    filter_glossary_entries_by_type,
    load_interactive_substitutions,
    scope_matches,
)
from .app_paths import glossary_catalog_path
from .glossary_catalog import GlossaryCatalog, GlossaryConflictError, GlossaryDuplicateError, GlossaryEntryDraft
from .glossary_ui_helpers import normalize_search_text
from .repeated_edits import repeated_edits_report
from .window_utils import bring_window_to_front

CANDIDATE_PAGE_SIZE = 40
FREQUENCY_FILTERS = {"Todas as frequências": 0, "Ao menos 5 ocorrências": 5,
                     "Ao menos 10 ocorrências": 10, "Ao menos 20 ocorrências": 20}


def candidate_page(items, page):
    pages = (len(items) + CANDIDATE_PAGE_SIZE - 1) // CANDIDATE_PAGE_SIZE
    page = max(0, min(page, pages - 1)) if pages else 0
    start = page * CANDIDATE_PAGE_SIZE
    return items[start:start + CANDIDATE_PAGE_SIZE], page, pages


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
        f"   |   {item['rule_label']}" + ("   |   ignorada" if item.get("ignored") else "")
    )


def format_historical_example(example):
    """Mostra uma edição histórica limitada, sem representar o texto atual como histórico."""
    def shorten(value):
        value = value or ""
        return value if len(value) <= 10000 else value[:10000] + "\n[Texto truncado]"
    return (f"Edição histórica do comentário ID {example['comment_id']}. "
            "A tradução atual pode ter sido alterada depois.\n\n"
            f"Antes:\n{shorten(example['before'])}\n\nDepois:\n{shorten(example['after'])}")


class HistoricalExampleDialog:
    def __init__(self, parent, text):
        self.win = ctk.CTkToplevel(parent)
        self.win.title("Exemplo de edição histórica")
        self.win.geometry("720x560")
        self.win.minsize(450, 300)
        self.win.transient(parent)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)
        self.text = ctk.CTkTextbox(self.win, wrap=tk.WORD)
        self.text.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 6))
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")
        actions = ctk.CTkFrame(self.win, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e", padx=14, pady=(0, 12))
        ctk.CTkButton(actions, text="Copiar exemplo", width=130, command=self.copy).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkButton(actions, text="Fechar", width=100, command=self.win.destroy).pack(side=tk.LEFT)
        self.win.bind("<Escape>", lambda _event: self.win.destroy())
        bring_window_to_front(self.win, parent, maximize=False)

    def copy(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.text.get("1.0", "end-1c"))


def show_historical_example(parent, text):
    return HistoricalExampleDialog(parent, text)


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


def filter_candidates(items, query="", *, uncovered_only=False, show_ignored=False, only_ignored=False,
                      minimum_count=0):
    terms = normalize_search_text(query).split()
    result = []
    for item in items:
        if minimum_count and item.get("count", 0) < minimum_count:
            continue
        if only_ignored and not item.get("ignored"):
            continue
        if item.get("ignored") and not (show_ignored or only_ignored):
            continue
        if uncovered_only and item.get("rule_produces") == item["new"]:
            continue
        if terms:
            fields = [normalize_search_text(value) for value in
                      (item["old"], item["new"], item.get("rule_label") or "")]
            if not all(any(term in field for field in fields) for term in terms):
                continue
        result.append(item)
    return result


def sort_candidates(items, order):
    if order == "Frequência":
        return sorted(items, key=lambda item: (-item["count"], -item["lines"], item["old"], item["new"]))
    if order == "Mais comentários":
        return sorted(items, key=lambda item: (-item["lines"], -item["count"], item["old"], item["new"]))
    if order == "Menor frequência":
        return sorted(items, key=lambda item: (item["count"], item["lines"], item["old"], item["new"]))
    if order == "Menos comentários":
        return sorted(items, key=lambda item: (item["lines"], item["count"], item["old"], item["new"]))
    if order == "Ordem alfabética":
        return sorted(items, key=lambda item: (normalize_search_text(item["old"]),
                                               normalize_search_text(item["new"])))
    raise ValueError("Ordenação de candidatos inválida")


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
        self.all_items = []
        self.page_index = 0
        self.page_count = 0
        self.buttons = []
        self.selected = None
        self.catalog = GlossaryCatalog(glossary_catalog_path(), _default_substitutions_path())
        self.snapshot = None
        self.ignored_available = True
        self._batching_filters = False

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

        filters = ctk.CTkFrame(self.win, fg_color="transparent")
        filters.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        filters.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar(master=self.win)
        self.uncovered_var = tk.BooleanVar(master=self.win, value=False)
        self.show_ignored_var = tk.BooleanVar(master=self.win, value=False)
        self.only_ignored_var = tk.BooleanVar(master=self.win, value=False)
        self.sort_var = tk.StringVar(master=self.win, value="Frequência")
        self.frequency_var = tk.StringVar(master=self.win, value="Todas as frequências")
        self.search_entry = ctk.CTkEntry(filters, textvariable=self.search_var,
                                         placeholder_text="Buscar texto ou tipo de regra")
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.win.bind("<Control-f>", self.focus_search)
        self.win.bind("<Control-l>", self.clear_filters_shortcut)
        self.win.bind("<Alt-Left>", lambda _event: self.page_shortcut("previous"))
        self.win.bind("<Alt-Right>", lambda _event: self.page_shortcut("next"))
        self.win.bind("<Alt-Home>", lambda _event: self.page_shortcut("first"))
        self.win.bind("<Alt-End>", lambda _event: self.page_shortcut("last"))
        self.win.bind("<Alt-Up>", lambda _event: self.select_candidate_shortcut(-1))
        self.win.bind("<Alt-Down>", lambda _event: self.select_candidate_shortcut(1))
        self.win.bind("<Control-Shift-C>", self.copy_candidate_shortcut)
        ctk.CTkCheckBox(filters, text="Somente sem regra correspondente",
                        variable=self.uncovered_var, command=self.reset_candidate_filter).grid(row=0, column=1)
        ctk.CTkCheckBox(filters, text="Mostrar ignoradas", variable=self.show_ignored_var,
                        command=self.reset_candidate_filter).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.btn_copy = ctk.CTkButton(filters, text="Copiar troca", width=120, command=self.copy_candidate)
        self.btn_copy.grid(row=1, column=1, sticky="e", pady=(6, 0))
        attach_tooltip(self.btn_copy, "Copia a troca selecionada. Atalho: Ctrl+Shift+C.")
        self.btn_restore_ignored = ctk.CTkButton(filters, text="Restaurar ignoradas da lista", width=170,
                                                 command=self.restore_all_ignored)
        self.btn_restore_ignored.grid(row=2, column=1, sticky="e", pady=(6, 0))
        attach_tooltip(self.btn_restore_ignored, "Restaura ignoradas que correspondem à busca e aos filtros de regras e frequência, em todas as páginas.")
        self.btn_clear_filters = ctk.CTkButton(filters, text="Limpar filtros (Ctrl+L)", width=170,
                                               command=self.clear_candidate_filters)
        self.btn_clear_filters.grid(row=3, column=1, sticky="e", pady=(6, 0))
        self.only_ignored_check = ctk.CTkCheckBox(filters, text="Somente ignoradas", variable=self.only_ignored_var,
                                                  command=self.reset_candidate_filter)
        self.only_ignored_check.grid(row=3, column=0, sticky="w", pady=(6, 0))
        attach_tooltip(self.only_ignored_check, "Mostra apenas ignoradas, mesmo quando 'Mostrar ignoradas' estiver desmarcado.")
        self.frequency_menu = ctk.CTkOptionMenu(filters, variable=self.frequency_var,
                                                 values=list(FREQUENCY_FILTERS),
                                                 command=lambda _value: self.reset_candidate_filter())
        self.frequency_menu.grid(row=4, column=0, sticky="w", pady=(6, 0))
        pager = ctk.CTkFrame(filters, fg_color="transparent")
        pager.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.btn_previous = ctk.CTkButton(pager, text="Anterior (Alt+←)", width=120, command=lambda: self.change_page(-1))
        self.btn_previous.pack(side=tk.LEFT)
        self.page_label = ctk.CTkLabel(pager, text="Página 0 de 0", width=130)
        self.page_label.pack(side=tk.LEFT, padx=6)
        self.btn_next = ctk.CTkButton(pager, text="Próxima (Alt+→)", width=120, command=lambda: self.change_page(1))
        self.btn_next.pack(side=tk.LEFT)
        self.search_var.trace_add("write", lambda *_: self.reset_candidate_filter())

        self.rows_frame = ctk.CTkScrollableFrame(self.win)
        self.rows_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        attach_tooltip(self.rows_frame, "Alt+↑/↓ seleciona a troca anterior ou seguinte, inclusive entre páginas.")

        detail = ctk.CTkFrame(self.win, corner_radius=8)
        detail.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        detail.columnconfigure(0, weight=1)

        self.detail_label = ctk.CTkLabel(
            detail, text="", anchor="w", justify=tk.LEFT, wraplength=900
        )
        self.detail_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 4))

        actions = ctk.CTkFrame(detail, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        self.hint_label = ctk.CTkLabel(
            detail, text="", anchor="w", text_color=MUTED_TEXT_COLOR
        )
        self.hint_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.sort_menu = ctk.CTkOptionMenu(detail, variable=self.sort_var,
                                           values=["Frequência", "Menor frequência", "Mais comentários",
                                                   "Menos comentários", "Ordem alfabética"],
                                           width=160, command=lambda _value: self.reset_candidate_filter())
        self.sort_menu.grid(row=1, column=1, sticky="e", padx=10, pady=(0, 4))

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
        self.btn_suggest = ctk.CTkButton(actions, text="Criar sugestão", width=140,
                                         command=self.create_suggestion_rule)
        self.btn_suggest.pack(side=tk.RIGHT, padx=6)
        self.btn_ignore = ctk.CTkButton(actions, text="Ignorar", width=100, command=self.toggle_ignored)
        self.btn_ignore.pack(side=tk.RIGHT, padx=6)
        attach_tooltip(self.btn_ignore, "Ignora ou restaura a troca apenas para esta obra e este par de idiomas.")
        examples = ctk.CTkFrame(detail, fg_color="transparent")
        examples.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkLabel(examples, text="Exemplo:").pack(side=tk.LEFT, padx=(0, 6))
        self.example_choice = tk.StringVar(master=self.win, value="Nenhum")
        self.example_menu = ctk.CTkOptionMenu(examples, variable=self.example_choice,
                                              values=["Nenhum"], width=160, state="disabled")
        self.example_menu.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_example_history = ctk.CTkButton(examples, text="Ver edição histórica", width=160,
                                                 command=self.show_example_history, state="disabled")
        self.btn_example_history.pack(side=tk.LEFT)
        attach_tooltip(self.btn_example_history, "Mostra o antes e o depois registrados na primeira edição desse comentário para a troca.")

    # ------------------------------------------------------------------ dados

    def load(self):
        with closing(initialize_database(self.app.output_db)) as conn:
            self.events = fetch_file_edit_events(
                conn.cursor(),
                self.source_file,
                self.target_language,
                self.source_language,
            )
        try:
            if not os.path.exists(self.catalog.db_path):
                initialize_catalog_glossary()
            self.snapshot = self.catalog.list_entries()
        except Exception as exc:
            self.snapshot = None
            self.ignored_available = False
            self.items = repeated_edits_report(self.events, [], limit=None)
            messagebox.showerror("Trocas repetidas", f"Erro ao carregar catálogo:\n{exc}", parent=self.win)
            return
        entries = [
            (entry.original_text, entry.replacement_text, entry.rule_type, entry.priority, entry.scope)
            for entry in self.snapshot.entries
            if scope_matches(entry.scope, self.source_language, self.target_language)
        ]
        self.items = repeated_edits_report(self.events, entries, limit=None)
        try:
            ignored = ignored_keys()
            self.ignored_available = True
        except (OSError, ValueError) as exc:
            ignored = set()
            self.ignored_available = False
            messagebox.showwarning("Trocas repetidas", f"Não foi possível ler as decisões de curadoria:\n{exc}", parent=self.win)
        for item in self.items:
            item["ignored"] = bool(self.target_language) and candidate_key(
                self.source_file, self.source_language, self.target_language, item["old"], item["new"]
            ) in ignored

    def refresh(self, keep=None):
        """Rele o banco e o glossario e refaz a lista.

        `keep` e o par `(old, new)` a manter selecionado: depois de criar uma
        regra, a linha continua a mesma e so a coluna "regra" muda.
        """
        self.load()
        self.all_items = list(self.items)
        self.apply_candidate_filter(keep)

    def reset_candidate_filter(self):
        if self._batching_filters:
            return
        self.page_index = 0
        self.apply_candidate_filter(retain_selection=False)

    def clear_candidate_filters(self):
        self._batching_filters = True
        try:
            self.search_var.set("")
            self.uncovered_var.set(False)
            self.show_ignored_var.set(False)
            self.only_ignored_var.set(False)
            self.frequency_var.set("Todas as frequências")
        finally:
            self._batching_filters = False
        self.reset_candidate_filter()

    def clear_filters_shortcut(self, _event=None):
        self.clear_candidate_filters()
        return "break"

    def page_shortcut(self, action):
        if not self.page_count:
            return "break"
        target = {"first": 0, "last": self.page_count - 1,
                  "previous": max(0, self.page_index - 1),
                  "next": min(self.page_count - 1, self.page_index + 1)}[action]
        if target != self.page_index:
            self.page_index = target
            self.apply_candidate_filter(retain_selection=False)
        return "break"

    def select_candidate_shortcut(self, direction):
        if not self.items or self.selected is None:
            return "break"
        target = self.selected + direction
        if 0 <= target < len(self.items):
            self.select(target)
        elif target < 0 and self.page_index > 0:
            self.change_page(-1)
            if self.items:
                self.select(len(self.items) - 1)
        elif target >= len(self.items) and self.page_index + 1 < self.page_count:
            self.change_page(1)
        return "break"

    def change_page(self, delta):
        self.page_index += delta
        self.apply_candidate_filter(retain_selection=False)

    def apply_candidate_filter(self, keep=None, *, retain_selection=True):
        if keep is None and retain_selection:
            selected = self.current_item()
            if selected is not None:
                keep = (selected["old"], selected["new"])
        filtered = filter_candidates(self.all_items, self.search_var.get(),
                                     uncovered_only=bool(self.uncovered_var.get()),
                                     show_ignored=bool(self.show_ignored_var.get()),
                                     only_ignored=bool(self.only_ignored_var.get()),
                                     minimum_count=FREQUENCY_FILTERS[self.frequency_var.get()])
        filtered = sort_candidates(filtered, self.sort_var.get())
        if keep is not None:
            for position, item in enumerate(filtered):
                if (item["old"], item["new"]) == keep:
                    self.page_index = position // CANDIDATE_PAGE_SIZE
                    break
        self.items, self.page_index, self.page_count = candidate_page(filtered, self.page_index)
        self.page_label.configure(text=f"Página {self.page_index + 1 if self.page_count else 0} de {self.page_count}")
        self.btn_previous.configure(state="normal" if self.page_index else "disabled")
        self.btn_next.configure(state="normal" if self.page_index + 1 < self.page_count else "disabled")
        restorable = filter_candidates(self.all_items, self.search_var.get(),
                                       uncovered_only=bool(self.uncovered_var.get()), only_ignored=True,
                                       minimum_count=FREQUENCY_FILTERS[self.frequency_var.get()])
        self.btn_restore_ignored.configure(state="normal" if self.ignored_available and self.target_language and restorable else "disabled")
        self.buttons = render_row_buttons(
            self.rows_frame,
            self.items,
            self.build_row_button,
            ("Nenhuma troca corresponde aos filtros." if self.all_items else "Nenhuma troca repetida."),
        )
        summary = describe_summary(self.events, self.all_items)
        if (self.search_var.get().strip() or self.uncovered_var.get() or self.only_ignored_var.get()
                or FREQUENCY_FILTERS[self.frequency_var.get()]
                or any(i.get("ignored") for i in self.all_items)):
            summary += f" Correspondentes: {len(filtered)}."
        self.summary_label.configure(text=summary)
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
            self.win.after_idle(self._reveal_selected)
        self.show_detail(self.items[index])

    def _reveal_selected(self):
        if self.selected is None or not (0 <= self.selected < len(self.buttons)):
            return
        canvas = self.rows_frame._parent_canvas
        bounds = canvas.bbox("all")
        if not bounds or bounds[3] <= 0:
            return
        button = self.buttons[self.selected]
        top = canvas.canvasy(0)
        height = canvas.winfo_height()
        y = button.winfo_y()
        bottom = y + button.winfo_height()
        if y < top:
            canvas.yview_moveto(max(0, y / bounds[3]))
        elif bottom > top + height:
            canvas.yview_moveto(max(0, (bottom - height) / bounds[3]))

    def show_detail(self, item):
        examples = item.get("examples") or ({"comment_id": item["example_id"], "before": None, "after": None},)
        labels = [f"{index}/{len(examples)} · ID {example['comment_id']}" for index, example in enumerate(examples, 1)]
        self.example_menu.configure(values=labels, state="normal" if len(labels) > 1 else "disabled")
        self.example_choice.set(labels[0])
        self.btn_example_history.configure(state="normal" if examples[0].get("before") is not None else "disabled")
        self.detail_label.configure(
            text=(
                f"Antes: {item['old']!r}\n"
                f"Depois: {item['new']!r}\n"
                f"{item['count']} ocorrência(s) no histórico em {item['lines']} comentário(s) distinto(s); "
                f"{len(examples)} exemplo(s) disponível(is) de até 5 comentários distintos\n"
                f"Regra no glossário: {item['rule_label']}"
            )
        )
        self.btn_ignore.configure(
            text="Restaurar" if item.get("ignored") else "Ignorar",
            state="normal" if self.ignored_available and self.target_language else "disabled",
        )
        if item.get("ignored"):
            self.btn_create.configure(state="disabled")
            self.btn_suggest.configure(state="disabled")
            self.hint_label.configure(text="Troca ignorada; restaure-a para criar uma regra.")
        elif self.snapshot is None:
            self.btn_create.configure(state="disabled")
            self.btn_suggest.configure(state="disabled")
            self.hint_label.configure(text="Recarregue o catálogo antes de criar uma regra.")
        elif not self.target_language:
            self.btn_create.configure(state="disabled")
            self.btn_suggest.configure(state="disabled")
            self.hint_label.configure(text="Selecione um idioma de destino para criar regras.")
        elif already_automatic(item):
            self.btn_create.configure(state="disabled")
            self.btn_suggest.configure(state="normal" if self.target_language else "disabled")
            self.hint_label.configure(text="Já há regra automática para esta troca.")
        else:
            self.btn_create.configure(state="normal")
            self.btn_suggest.configure(state="normal" if self.target_language else "disabled")
            escopo = rule_scope_for_pair(self.source_language, self.target_language)
            self.hint_label.configure(text=f"A regra nova vale para o escopo {escopo!r}.")
        self.btn_example.configure(state="normal")
        self.btn_copy.configure(state="normal")

    def clear_detail(self):
        self.detail_label.configure(text="")
        self.hint_label.configure(text="")
        self.btn_create.configure(state="disabled")
        self.btn_suggest.configure(state="disabled")
        self.btn_ignore.configure(state="disabled")
        self.btn_example.configure(state="disabled")
        self.btn_example_history.configure(state="disabled")
        self.example_menu.configure(values=["Nenhum"], state="disabled")
        self.example_choice.set("Nenhum")
        self.btn_copy.configure(state="disabled")

    def current_item(self):
        if self.selected is None or not (0 <= self.selected < len(self.items)):
            return None
        return self.items[self.selected]

    def current_example(self):
        item = self.current_item()
        if item is None:
            return None
        examples = item.get("examples") or ({"comment_id": item["example_id"], "before": None, "after": None},)
        chosen = self.example_choice.get()
        for index, example in enumerate(examples, 1):
            if chosen == f"{index}/{len(examples)} · ID {example['comment_id']}":
                return example
        return examples[0]

    def focus_search(self, _event=None):
        self.search_entry.focus_set()
        return "break"

    def copy_candidate(self):
        item = self.current_item()
        if item is None:
            return
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(f"{item['old']} → {item['new']}")
        except tk.TclError:
            messagebox.showwarning("Trocas repetidas", "Não foi possível copiar a troca.", parent=self.win)

    def copy_candidate_shortcut(self, _event=None):
        self.copy_candidate()
        return "break"

    def candidate_available(self, item):
        """Confere decisões recentes de outras janelas antes de criar uma regra."""
        try:
            key = candidate_key(self.source_file, self.source_language, self.target_language,
                                item["old"], item["new"])
            ignored = key in ignored_keys()
        except (OSError, ValueError) as exc:
            messagebox.showwarning("Trocas repetidas", f"Não foi possível conferir a curadoria:\n{exc}", parent=self.win)
            return False
        if ignored:
            self.refresh(keep=(item["old"], item["new"]))
            messagebox.showwarning("Trocas repetidas", "Esta troca foi ignorada. Restaure-a antes de criar uma regra.", parent=self.win)
            return False
        return True

    def toggle_ignored(self):
        item = self.current_item()
        if item is None or not self.target_language or not self.ignored_available:
            return
        pair = (item["old"], item["new"])
        try:
            key = candidate_key(self.source_file, self.source_language, self.target_language, *pair)
            set_ignored(key, not item.get("ignored", False))
        except (OSError, ValueError) as exc:
            messagebox.showwarning("Trocas repetidas", f"Não foi possível salvar a decisão:\n{exc}", parent=self.win)
            return
        self.refresh(keep=pair)

    def restore_all_ignored(self):
        if not self.ignored_available or not self.target_language:
            return
        try:
            candidates = filter_candidates(self.all_items, self.search_var.get(),
                                           uncovered_only=bool(self.uncovered_var.get()), only_ignored=True,
                                           minimum_count=FREQUENCY_FILTERS[self.frequency_var.get()])
            keys = [candidate_key(self.source_file, self.source_language, self.target_language,
                                  item["old"], item["new"]) for item in candidates]
            if not keys:
                return
            restore_ignored(keys)
        except (OSError, ValueError) as exc:
            messagebox.showwarning("Trocas repetidas", f"Não foi possível restaurar as trocas:\n{exc}", parent=self.win)
            return
        self.refresh()

    # ----------------------------------------------------------------- acoes

    def show_example(self):
        """Posiciona o editor no primeiro comentario em que a troca apareceu.

        Pela mesma maquina do "Ir para ID" (`jump_to_id`): filtros e ordem
        ativos. Se a linha saiu do filtro atual, o editor diz — nao a janela.
        """
        example = self.current_example()
        if example is None:
            return
        if not self.editor.jump_to_id(example["comment_id"]):
            messagebox.showinfo(
                "Trocas repetidas",
                f"A tradução {example['comment_id']} não está na lista "
                "com os filtros atuais do editor.",
                parent=self.win,
            )

    def show_example_history(self):
        example = self.current_example()
        if example is not None and example.get("before") is not None:
            show_historical_example(self.win, format_historical_example(example))

    def create_suggestion_rule(self):
        """Adiciona uma sugestão ao catálogo sem alterar traduções existentes."""
        item = self.current_item()
        if item is None or item.get("ignored") or self.snapshot is None:
            return
        if not self.target_language:
            messagebox.showwarning("Trocas repetidas", "Selecione um idioma de destino antes de criar uma sugestão.", parent=self.win)
            return
        if not self.candidate_available(item):
            return
        scope = rule_scope_for_pair(self.source_language, self.target_language)
        pair = (item["old"], item["new"])
        try:
            key = candidate_key(self.source_file, self.source_language, self.target_language, *pair)
            with available_candidate(key):
                result = self.catalog.add(
                    GlossaryEntryDraft(item["old"], item["new"], GLOSSARY_RULE_SUGGESTION, scope),
                    self.snapshot.catalog_revision,
                )
        except CandidateIgnored:
            self.refresh(keep=pair)
            messagebox.showwarning("Trocas repetidas", "Esta troca foi ignorada. Restaure-a antes de criar uma regra.", parent=self.win)
            return
        except GlossaryConflictError:
            self.refresh(keep=pair)
            messagebox.showwarning("Conflito de revisão", "O catálogo mudou. Nenhuma sugestão foi adicionada; revise a lista atualizada.", parent=self.win)
            return
        except GlossaryDuplicateError:
            self.refresh(keep=pair)
            messagebox.showinfo("Trocas repetidas", "Esta sugestão já existe neste escopo.", parent=self.win)
            return
        except Exception as exc:
            messagebox.showerror("Trocas repetidas", f"Não foi possível criar a sugestão:\n{exc}", parent=self.win)
            return
        self.notify_glossary_change()
        self.refresh(keep=pair)
        if result.warning:
            messagebox.showwarning("Trocas repetidas", result.warning, parent=self.win)
        else:
            messagebox.showinfo("Trocas repetidas", "Sugestão adicionada ao glossário; nenhuma tradução foi alterada.", parent=self.win)

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
        if item is None or item.get("ignored") or already_automatic(item) or self.snapshot is None:
            return
        if not self.target_language:
            messagebox.showwarning("Trocas repetidas", "Selecione um idioma de destino antes de criar uma regra automática.", parent=self.win)
            return
        if not self.candidate_available(item):
            return
        escopo = rule_scope_for_pair(self.source_language, self.target_language)
        entrada = (item["old"], item["new"], GLOSSARY_RULE_AUTOMATIC, 0, escopo)
        par = (item["old"], item["new"])
        expected_catalog_revision = self.snapshot.catalog_revision

        def aplicado(_stats):
            if self.win.winfo_exists():
                self.refresh(keep=par)

        def decidido(promover):
            if not promover or not self.win.winfo_exists():
                return
            if not self.candidate_available(item):
                return
            try:
                key = candidate_key(self.source_file, self.source_language, self.target_language, *par)
                with available_candidate(key):
                    resultado = self.catalog.add(
                        GlossaryEntryDraft(item["old"], item["new"], GLOSSARY_RULE_AUTOMATIC, escopo),
                        expected_catalog_revision,
                    )
            except CandidateIgnored:
                self.refresh(keep=par)
                messagebox.showwarning("Trocas repetidas", "Esta troca foi ignorada. Restaure-a antes de criar uma regra.", parent=self.win)
                return
            except GlossaryConflictError:
                self.refresh(keep=par)
                messagebox.showwarning("Conflito de revisão", "O catálogo mudou. Nada foi adicionado ou aplicado. Revise a lista recarregada.", parent=self.win)
                return
            except GlossaryDuplicateError:
                self.refresh(keep=par)
                messagebox.showinfo("Trocas repetidas", "Esta regra já existe neste tipo e escopo.", parent=self.win)
                return
            except Exception as exc:
                messagebox.showerror(
                    "Trocas repetidas",
                    f"Erro ao gravar a regra no glossário:\n{exc}",
                    parent=self.win,
                )
                return
            self.notify_glossary_change()
            if resultado.warning:
                messagebox.showwarning("Trocas repetidas", resultado.warning, parent=self.win)
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
