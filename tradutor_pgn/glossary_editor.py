import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .glossario import (
    build_glossary_lookup,
    GLOSSARY_PRIORITY_DEFAULT,
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_RULE_TYPES,
    add_glossary_entry,
    analyze_glossary_csv_import,
    create_glossary_backup,
    deduplicate_glossary_entries,
    delete_glossary_entry_by_pair,
    describe_glossary_conflict,
    export_glossary_csv,
    glossary_conflicts,
    resolve_glossary_conflict,
    find_glossary_entry_index,
    apply_all_substitutions,
    apply_substitution,
    import_glossary_csv,
    glossary_entry_pair,
    glossary_entry_priority,
    glossary_entry_type,
    normalize_glossary_priority,
    promote_glossary_rule,
    load_glossary_entry_details,
    load_glossary_entries,
    load_interactive_substitutions,
    restore_glossary_from_backup,
    save_glossary_entries,
    update_glossary_entry_by_entry,
    validate_glossary_entry,
)
from .settings import load_settings
from .editor_common import (
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    clamp_page,
    page_count as compute_page_count,
    page_offset,
    preview as common_preview,
    window_safe_geometry,
)
from .editor_widgets import (
    flash_message,
    render_row_buttons,
    restore_sash,
    save_window_section,
)
from .window_utils import bring_window_to_front


INVALID_PRIORITY_WARNING = "Prioridade precisa ser um número inteiro."
WARNING_COLOR = "#f59e0b"
OK_COLOR = "#16a34a"
ERROR_COLOR = "#dc2626"
PAGE_SIZE = 150
MIN_WIDTH = 1040
MIN_HEIGHT = 640
RULE_TYPE_LABELS = {
    GLOSSARY_RULE_SUGGESTION: "Sugestão",
    GLOSSARY_RULE_CLEANUP: "Limpeza",
    GLOSSARY_RULE_AUTOMATIC: "Automática",
}
RULE_TYPE_BY_LABEL = {label: value for value, label in RULE_TYPE_LABELS.items()}


def rule_type_label(rule_type):
    return RULE_TYPE_LABELS.get(rule_type, RULE_TYPE_LABELS[GLOSSARY_RULE_SUGGESTION])


def rule_type_value(label):
    return RULE_TYPE_BY_LABEL.get(label, GLOSSARY_RULE_SUGGESTION)


def entry_pairs(entries):
    return [glossary_entry_pair(entry) for entry in entries]


def preview(text, limit=68):
    return common_preview(text, limit)


def safe_geometry(win, geometry):
    return window_safe_geometry(win, geometry, MIN_WIDTH, MIN_HEIGHT)


def build_glossary_diagnostics(entries, conflicts=None):
    """Avisos por entrada, na ordem de `entries`.

    O aviso de conflito vem de `glossary_conflicts`, e nao de um agrupamento
    proprio, para que o filtro "Conflitos" mostre exatamente as regras para as
    quais o editor consegue dizer quem vence. Sem isso a lista acusaria disputas
    que nao existem — duas regras de mesmo padrao em contextos que o programa
    nunca carrega juntos.
    """
    pair_counts = {}
    for orig, new in entry_pairs(entries):
        pair_counts[(orig, new)] = pair_counts.get((orig, new), 0) + 1

    if conflicts is None:
        conflicts = glossary_conflicts(entries)

    diagnostics = []
    for index, entry in enumerate(entries):
        orig, new = glossary_entry_pair(entry)
        warnings = validate_glossary_entry(
            orig,
            new,
            rule_type=glossary_entry_type(entry),
        )
        if pair_counts.get((orig, new), 0) > 1:
            warnings.append("Entrada duplicada.")
        if index in conflicts:
            warnings.append("Mesmo original com substituição diferente.")
        diagnostics.append(warnings)
    return diagnostics


def glossary_entry_warnings(entries, index, diagnostics=None):
    if diagnostics is not None and 0 <= index < len(diagnostics):
        return diagnostics[index]
    orig, new = glossary_entry_pair(entries[index])
    return validate_glossary_entry(
        orig,
        new,
        entries,
        current_index=index,
        rule_type=glossary_entry_type(entries[index]),
    )


def glossary_filter_indices(entries, search_text="", filter_name="Todas", diagnostics=None):
    query = (search_text or "").strip().lower()
    result = []

    for index, entry in enumerate(entries):
        orig, new = glossary_entry_pair(entry)
        label = rule_type_label(glossary_entry_type(entry))
        if query and query not in orig.lower() and query not in new.lower() and query not in label.lower():
            continue

        warnings = glossary_entry_warnings(entries, index, diagnostics)
        if filter_name == "Duplicadas" and "Entrada duplicada." not in warnings:
            continue
        if filter_name == "Conflitos" and "Mesmo original com substituição diferente." not in warnings:
            continue
        if filter_name == "Inválidas" and not warnings:
            continue

        result.append(index)

    return result


def sort_glossary_indices(entries, indices, sort_name="Ordem do arquivo"):
    if sort_name == "Original A-Z":
        return sorted(indices, key=lambda index: (glossary_entry_pair(entries[index])[0].casefold(), index))
    if sort_name == "Substituição A-Z":
        return sorted(indices, key=lambda index: (glossary_entry_pair(entries[index])[1].casefold(), index))
    if sort_name == "Maior original":
        return sorted(indices, key=lambda index: (-len(glossary_entry_pair(entries[index])[0]), index))
    return list(indices)


def glossary_counts(entries, diagnostics=None):
    counts = {"total": len(entries), "duplicates": 0, "conflicts": 0, "invalid": 0}
    for index in range(len(entries)):
        warnings = glossary_entry_warnings(entries, index, diagnostics)
        if "Entrada duplicada." in warnings:
            counts["duplicates"] += 1
        if "Mesmo original com substituição diferente." in warnings:
            counts["conflicts"] += 1
        if warnings:
            counts["invalid"] += 1
    return counts


def row_label(entries, index, diagnostics=None):
    entry = entries[index]
    orig, new = glossary_entry_pair(entry)
    type_label = rule_type_label(glossary_entry_type(entry))
    warnings = glossary_entry_warnings(entries, index, diagnostics)
    status = "AVISO" if warnings else "OK"
    # A prioridade so aparece quando ha uma: mostra-la como "P0" em 7 mil linhas
    # transformaria a ausencia de decisao em ruido em toda a lista.
    priority = glossary_entry_priority(entry)
    marca = f"  ·  P{priority:+d}" if priority != GLOSSARY_PRIORITY_DEFAULT else ""
    return (
        f"{status}  #{index + 1}  -  {type_label}{marca}\n"
        f"De: {preview(orig)}\nPara: {preview(new)}"
    )


class GlossaryEditorState:
    """Estado mutavel da janela do glossario, em atributos.

    Antes cada um destes campos era um dict de um item so, lido e escrito pelo
    indice: `dirty = {"value": False}` e depois `dirty["value"]` em toda parte.
    Isso nao era estilo — as 49 funcoes aninhadas de `open_glossary_editor`
    precisavam ESCREVER no estado compartilhado, e uma atribuicao simples dentro
    de uma funcao aninhada cria uma variavel local em vez de alterar a de fora.
    Mutar um dict contornava isso porque mutar um objeto nao e atribuir a um
    nome.

    Numa classe o problema nao existe, entao os dicts sairam. E o espelho do
    `EditorState` do editor de traducoes, pela mesma razao que la: separa o
    estado que muda em tempo de execucao (`self.state.dirty`) da arvore de
    widgets (`self.dirty_label`).
    """

    def __init__(self):
        # O glossario como foi carregado do arquivo.
        self.entries = []
        self.diagnostics = []
        self.conflicts = {}

        # A lista como esta sendo exibida.
        self.filtered_indices = []
        self.page_index = 0

        # Posicao em `entries` — nao na lista filtrada, que muda com o filtro e
        # com a ordenacao (garantia S6).
        self.selected_index = None

        # `loading` suprime o marcador de "nao salvo" enquanto o proprio
        # programa preenche o formulario.
        self.dirty = False
        self.loading = False

        # Indice por original, para a validacao a cada tecla. Derivado de
        # `entries`: invalidado junto com ela.
        self.validation_lookup = None


class GlossaryEditor:
    """A janela de edicao do glossario.

    Era uma funcao de 985 linhas com 49 funcoes aninhadas, presas ao mesmo
    escopo de closure e escrevendo no estado por dicts de um item so. O outro
    editor passou por isto no item 3.1 do ROADMAP; este ficou para tras, e a
    assimetria aparecia ate de fora: abrir o editor de traducoes devolvia a
    instancia, abrir este devolvia `None`.

    A conversao nao mudou comportamento nenhum: cada funcao virou metodo com o
    mesmo corpo.
    """

    def __init__(self, app, on_change=None, initial_original=None, initial_replacement=None):
        self.app = app
        self.on_change = on_change
        self.build_state()
        self.build_list_pane()
        self.build_detail_pane()
        self.build_footer()
        self.connect_events()
        self.load_first_entry(initial_original, initial_replacement)

    def build_state(self):
        """Janela, configuracoes salvas, estado e variaveis de controle."""
        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title("Editor de Glossário")
        self.win.geometry("1120x700")
        self.win.minsize(1040, 640)
        bring_window_to_front(self.win, self.app.root, maximize=True)

        self.settings = load_settings()
        self.editor_settings = self.settings.get("glossary_editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

        saved_geometry = self.editor_settings.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            try:
                self.win.geometry(safe_geometry(self.win, saved_geometry))
            except tk.TclError:
                pass

        self.state = GlossaryEditorState()
        self.row_buttons = []
        self.form_baseline = {
            "orig": "",
            "new": "",
            "type": GLOSSARY_RULE_SUGGESTION,
            "priority": GLOSSARY_PRIORITY_DEFAULT,
        }

        self.search_text = tk.StringVar(master=self.win, value="")
        self.test_text_var = tk.StringVar(master=self.win, value="")
        self.sort_text = tk.StringVar(
            master=self.win,
            value=self.editor_settings.get("sort", "Ordem do arquivo"),
        )
        self.rule_type_text = tk.StringVar(
            master=self.win,
            value=rule_type_label(GLOSSARY_RULE_SUGGESTION),
        )
        self.priority_text = tk.StringVar(
            master=self.win, value=str(GLOSSARY_PRIORITY_DEFAULT)
        )

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

    def build_list_pane(self):
        """Painel esquerdo: paginacao, busca, filtros, ordem e a lista."""
        pane_bg = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
        self.main_pane = tk.PanedWindow(
            self.win,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=pane_bg,
        )
        self.main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        list_frame = ctk.CTkFrame(self.main_pane, corner_radius=8, width=420)
        self.main_pane.add(list_frame, minsize=340)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(6, weight=1)

        header = ctk.CTkFrame(list_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        header.columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="Glossário", font=ctk.CTkFont(weight="bold")).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.list_count_label = ctk.CTkLabel(header, text="", anchor="e")
        self.list_count_label.grid(row=0, column=1, sticky="e")

        page_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        page_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        page_bar.columnconfigure(1, weight=1)
        self.btn_page_prev = ctk.CTkButton(page_bar, text="< Página", width=92)
        self.btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.page_label = ctk.CTkLabel(page_bar, text="", anchor="center")
        self.page_label.grid(row=0, column=1, sticky="ew")
        self.btn_page_next = ctk.CTkButton(page_bar, text="Página >", width=92)
        self.btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

        search_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        search_bar.columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(
            search_bar,
            textvariable=self.search_text,
            placeholder_text="Buscar original ou substituição",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_search = ctk.CTkButton(search_bar, text="Buscar", width=82)
        self.btn_search.grid(row=0, column=1, padx=(0, 6))
        self.btn_clear_search = ctk.CTkButton(search_bar, text="Limpar", width=74)
        self.btn_clear_search.grid(row=0, column=2)

        self.filter_segment = ctk.CTkSegmentedButton(
            list_frame,
            values=["Todas", "Duplicadas", "Conflitos", "Inválidas"],
        )
        filtro_salvo = self.editor_settings.get("filter")
        self.filter_segment.set(
            filtro_salvo
            if filtro_salvo in {"Todas", "Duplicadas", "Conflitos", "Inválidas"}
            else "Todas"
        )
        self.filter_segment.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

        sort_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
        sort_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))
        sort_bar.columnconfigure(1, weight=1)
        ctk.CTkLabel(sort_bar, text="Ordem").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.sort_menu = ctk.CTkOptionMenu(
            sort_bar,
            variable=self.sort_text,
            values=["Ordem do arquivo", "Original A-Z", "Substituição A-Z", "Maior original"],
        )
        self.sort_menu.grid(row=0, column=1, sticky="ew")

        self.counts_label = ctk.CTkLabel(list_frame, text="", anchor="w")
        self.counts_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.rows_frame = ctk.CTkScrollableFrame(list_frame, height=420)
        self.rows_frame.grid(row=6, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def build_detail_pane(self):
        """Painel direito: o formulario, o aviso de conflito e o teste rapido."""
        detail_frame = ctk.CTkFrame(self.main_pane, corner_radius=8)
        self.main_pane.add(detail_frame, minsize=620)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(1, weight=1)
        detail_frame.rowconfigure(3, weight=1)
        detail_frame.rowconfigure(9, weight=1)

        ctk.CTkLabel(detail_frame, text="Texto encontrado:").grid(
            row=0,
            column=0,
            sticky="w",
            padx=10,
            pady=(10, 2),
        )
        self.orig_text = ctk.CTkTextbox(detail_frame, height=120, wrap=tk.WORD)
        self.orig_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        ctk.CTkLabel(detail_frame, text="Substituir por:").grid(
            row=2,
            column=0,
            sticky="w",
            padx=10,
            pady=(0, 2),
        )
        self.new_text = ctk.CTkTextbox(detail_frame, height=120, wrap=tk.WORD)
        self.new_text.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 8))

        type_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
        type_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))
        type_bar.columnconfigure(4, weight=1)
        ctk.CTkLabel(type_bar, text="Tipo:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.type_menu = ctk.CTkOptionMenu(
            type_bar,
            variable=self.rule_type_text,
            values=[rule_type_label(rule_type) for rule_type in GLOSSARY_RULE_TYPES],
            width=160,
        )
        self.type_menu.grid(row=0, column=1, sticky="w")

        # Campo de texto, e nao um seletor de valores: a prioridade e um inteiro
        # qualquer no arquivo, e um `Substituicoes.txt` editado a mao pode trazer
        # um valor fora de qualquer faixa que a janela oferecesse. Um seletor
        # teria de escolher entre esconder esse valor ou troca-lo — o campo
        # mostra o que esta la, e o que nao for inteiro vira aviso de validacao.
        ctk.CTkLabel(type_bar, text="Prioridade:").grid(
            row=0, column=2, sticky="w", padx=(16, 6)
        )
        self.priority_entry = ctk.CTkEntry(
            type_bar,
            textvariable=self.priority_text,
            width=70,
            justify="center",
        )
        self.priority_entry.grid(row=0, column=3, sticky="w")
        ctk.CTkLabel(
            type_bar,
            text="(maior vence; 0 deixa o comprimento decidir)",
            text_color="#64748b",
            anchor="w",
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))

        self.validation_label = ctk.CTkLabel(
            detail_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=OK_COLOR,
        )
        self.validation_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 8))

        # So aparece quando a entrada selecionada disputa um padrao com outra. Fora
        # disso a barra sai do grid, para nao ocupar espaco permanente com nada.
        self.conflict_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
        self.conflict_bar.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.conflict_bar.columnconfigure(0, weight=1)
        self.conflict_label = ctk.CTkLabel(
            self.conflict_bar,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=WARNING_COLOR,
            wraplength=460,
        )
        self.conflict_label.grid(row=0, column=0, sticky="ew")
        # Duas saidas para o mesmo conflito, e a ordem na barra e a ordem em que
        # convem tenta-las: priorizar nao apaga nada e da para desfazer mudando
        # um numero; manter remove as concorrentes do arquivo.
        self.btn_promote_conflict = ctk.CTkButton(
            self.conflict_bar, text="Priorizar esta", width=120
        )
        self.btn_promote_conflict.grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.btn_keep_conflict = ctk.CTkButton(self.conflict_bar, text="Manter esta", width=110)
        self.btn_keep_conflict.grid(row=0, column=2, sticky="e", padx=(6, 0))
        self.conflict_bar.grid_remove()

        test_header = ctk.CTkFrame(detail_frame, fg_color="transparent")
        test_header.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 2))
        test_header.columnconfigure(1, weight=1)
        ctk.CTkLabel(test_header, text="Teste rápido:").grid(row=0, column=0, sticky="w")
        self.btn_apply_preview = ctk.CTkButton(test_header, text="Aplicar selecionada", width=140)
        self.btn_apply_preview.grid(row=0, column=2, sticky="e")
        self.btn_apply_all_preview = ctk.CTkButton(test_header, text="Aplicar todas", width=110)
        self.btn_apply_all_preview.grid(row=0, column=3, sticky="e", padx=(6, 0))

        self.test_input = ctk.CTkEntry(
            detail_frame,
            textvariable=self.test_text_var,
            placeholder_text="Digite ou cole uma frase para testar a substituição selecionada",
        )
        self.test_input.grid(row=8, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.preview_text = ctk.CTkTextbox(detail_frame, height=90, wrap=tk.WORD)
        self.preview_text.grid(row=9, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview_text.configure(state="disabled")

    def build_footer(self):
        """Rodape: mensagens, indicador de alteracoes e a barra de acoes."""
        footer = ctk.CTkFrame(self.win, corner_radius=8)
        footer.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        footer.columnconfigure(0, weight=1)

        status_line = ctk.CTkFrame(footer, fg_color="transparent")
        status_line.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        self.msg_label = ctk.CTkLabel(status_line, text="", text_color=OK_COLOR)
        self.msg_label.pack(side=tk.LEFT)
        self.dirty_label = ctk.CTkLabel(status_line, text="Salvo", text_color=OK_COLOR)
        self.dirty_label.pack(side=tk.LEFT, padx=(12, 0))
        self.file_label = ctk.CTkLabel(status_line, text="", text_color="#64748b")
        self.file_label.pack(side=tk.LEFT, padx=(12, 0))

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))
        action_specs = [
            ("Nova entrada", 120),
            ("Salvar", 100),
            ("Salvar como nova", 140),
            ("Excluir", 100),
            ("Deduplicar", 110),
            ("Backup", 100),
            ("Recarregar", 110),
            ("Exportar CSV", 120),
            ("Importar CSV", 120),
            ("Restaurar backup", 140),
        ]
        self.buttons = {}
        for column, (text, width) in enumerate(action_specs):
            button = ctk.CTkButton(actions, text=text, width=width)
            row = column // 5
            col = column % 5
            button.grid(row=row, column=col, sticky="ew", padx=(0, 6), pady=2)
            actions.columnconfigure(col, weight=1)
            self.buttons[text] = button

    def connect_events(self):
        """Liga os comandos, os atalhos e o fechamento da janela."""
        self.buttons["Nova entrada"].configure(command=self.new_entry)
        self.buttons["Salvar"].configure(command=self.save_current)
        self.buttons["Salvar como nova"].configure(command=self.save_as_new)
        self.buttons["Excluir"].configure(command=self.delete_current)
        self.buttons["Deduplicar"].configure(command=self.deduplicate_entries)
        self.buttons["Backup"].configure(command=self.create_backup_now)
        self.buttons["Recarregar"].configure(command=self.reload_all)
        self.buttons["Exportar CSV"].configure(command=self.export_csv)
        self.buttons["Importar CSV"].configure(command=self.import_csv)
        self.buttons["Restaurar backup"].configure(command=self.restore_backup)
        self.btn_page_prev.configure(command=lambda: self.change_page(-1))
        self.btn_page_next.configure(command=lambda: self.change_page(1))
        self.btn_search.configure(command=self.apply_search)
        self.btn_clear_search.configure(command=self.clear_search)
        self.btn_keep_conflict.configure(command=self.keep_this_rule)
        self.btn_promote_conflict.configure(command=self.promote_this_rule)
        self.priority_text.trace_add("write", lambda *_a: self.mark_dirty())
        self.btn_apply_preview.configure(command=self.refresh_preview)
        self.btn_apply_all_preview.configure(command=self.apply_all_to_preview)
        self.sort_menu.configure(command=self.restart_at_first_page)
        self.filter_segment.configure(command=self.restart_at_first_page)
        self.type_menu.configure(command=lambda _value: self.mark_dirty())
        self.search_entry.bind("<Return>", lambda _event: self.apply_search())
        self.test_input.bind("<KeyRelease>", lambda _event: self.refresh_preview())
        self.orig_text.bind(
            "<<Modified>>",
            lambda event: (self.orig_text.edit_modified(False), self.mark_dirty())[1],
        )
        self.new_text.bind(
            "<<Modified>>",
            lambda event: (self.new_text.edit_modified(False), self.mark_dirty())[1],
        )
        self.win.bind("<Control-s>", lambda _event: (self.save_current(), "break")[1])
        self.win.bind("<Control-S>", lambda _event: (self.save_current(), "break")[1])
        self.win.bind("<Control-n>", lambda _event: (self.new_entry(), "break")[1])
        self.win.bind("<Control-N>", lambda _event: (self.new_entry(), "break")[1])
        self.win.protocol("WM_DELETE_WINDOW", self.close_editor)

    def load_first_entry(self, initial_original=None, initial_replacement=None):
        """Primeira carga: a lista, e a entrada pre-preenchida quando ha uma."""
        has_initial_entry = bool(
            (initial_original or "").strip() or (initial_replacement or "").strip()
        )
        self.reload_all(select_first=not has_initial_entry)
        if has_initial_entry:
            self.start_prefilled_entry(initial_original, initial_replacement)
        self.win.after(100, self.restore_pane_position)

    def show_message(self, text, color=OK_COLOR):
        flash_message(self.msg_label, self.win, text, 1800, text_color=color)

    def save_editor_settings(self):
        save_window_section(
            self.settings,
            "glossary_editor",
            {"filter": self.filter_segment.get(), "sort": self.sort_text.get()},
            window=self.win,
            sashes=(("main_sash_x", self.main_pane, 0),),
        )

    def restore_pane_position(self):
        restore_sash(self.main_pane, self.editor_settings.get("main_sash_x"), 360, 520)

    def update_app_glossary(self):
        self.app.glossary_substitutions = load_interactive_substitutions()
        if hasattr(self.app, "log_message"):
            self.app.log_message(
                f"Glossário atualizado: {len(self.app.glossary_substitutions)} entradas"
            )
        for callback in list(getattr(self.app, "glossary_change_callbacks", [])):
            callback(self.app.glossary_substitutions)
        if self.on_change is not None:
            self.on_change(self.app.glossary_substitutions)

    def text_value(self, widget):
        return widget.get("1.0", tk.END).rstrip("\n")

    def set_text(self, widget, value):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        try:
            widget.edit_modified(False)
        except tk.TclError:
            pass

    def current_pair(self):
        return self.text_value(self.orig_text), self.text_value(self.new_text)

    def current_rule_type(self):
        return rule_type_value(self.rule_type_text.get())

    def set_rule_type(self, rule_type):
        self.rule_type_text.set(rule_type_label(glossary_entry_type((None, None, rule_type))))

    def current_priority(self):
        """A prioridade digitada, ou `None` se o texto nao for um inteiro.

        `None` e um estado legitimo do formulario, e nao um erro a esconder: o
        campo esta vazio ou tem lixo, a validacao avisa e "Salvar" recusa. Cair
        para zero em silencio gravaria uma decisao que o usuario nao tomou.
        """
        texto = self.priority_text.get().strip()
        if not texto:
            return None
        try:
            return int(texto)
        except ValueError:
            return None

    def set_priority(self, priority):
        self.priority_text.set(str(normalize_glossary_priority(priority)))

    def set_form_baseline(self, orig="", new="", rule_type=None, priority=None):
        self.form_baseline["orig"] = orig or ""
        self.form_baseline["new"] = new or ""
        self.form_baseline["type"] = rule_type or GLOSSARY_RULE_SUGGESTION
        self.form_baseline["priority"] = normalize_glossary_priority(priority)

    def form_changed(self):
        orig, new = self.current_pair()
        return (
            orig != self.form_baseline["orig"]
            or new != self.form_baseline["new"]
            or self.current_rule_type() != self.form_baseline["type"]
            or self.current_priority() != self.form_baseline["priority"]
        )

    def set_dirty(self, value):
        self.state.dirty = value
        self.dirty_label.configure(
            text="Alterações não salvas" if value else "Salvo",
            text_color=WARNING_COLOR if value else OK_COLOR,
        )
        self.refresh_validation()

    def mark_dirty(self, _event=None):
        if not self.state.loading:
            self.set_dirty(self.form_changed())

    def refresh_preview(self):
        orig, new = self.current_pair()
        sample = self.test_text_var.get()
        result = apply_substitution(sample, orig, new) if orig else sample
        self.set_preview_text(result)

    def apply_all_to_preview(self):
        self.set_preview_text(
            apply_all_substitutions(
                self.test_text_var.get(), entry_pairs(self.state.entries)
            )
        )

    def set_preview_text(self, value):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", value)
        self.preview_text.configure(state="disabled")

    def refresh_validation(self):
        orig, new = self.current_pair()
        current_index = self.state.selected_index
        warnings = validate_glossary_entry(
            orig,
            new,
            current_index=current_index,
            rule_type=self.current_rule_type(),
            existing_lookup=self.current_validation_lookup(),
        )
        if self.current_priority() is None:
            warnings.append(INVALID_PRIORITY_WARNING)
        if warnings:
            self.validation_label.configure(
                text="Avisos: " + " | ".join(warnings),
                text_color=WARNING_COLOR,
            )
        elif orig or new:
            self.validation_label.configure(text="Entrada válida", text_color=OK_COLOR)
        else:
            self.validation_label.configure(text="", text_color=OK_COLOR)
        self.refresh_preview()

    def refresh_conflict(self):
        """Diz qual regra do conflito o programa aplica (garantia S9).

        Descreve a entrada **como esta no arquivo**, nao o que esta no
        formulario: quem vence depende da posicao no glossario e do tipo
        gravados, e o texto sendo digitado ainda nao e nenhum dos dois.
        """
        index = self.state.selected_index
        message = ""
        if index is not None and 0 <= index < len(self.state.entries):
            message = describe_glossary_conflict(self.state.entries, index, self.state.conflicts)

        if message:
            self.conflict_label.configure(text=message)
            self.conflict_bar.grid()
        else:
            self.conflict_label.configure(text="")
            self.conflict_bar.grid_remove()

    def keep_this_rule(self):
        index = self.state.selected_index
        if index is None or index not in self.state.conflicts:
            self.show_message("Selecione uma regra em conflito", WARNING_COLOR)
            return
        if self.state.dirty and not self.confirm_discard_changes():
            return

        info = self.state.conflicts[index]
        descartadas = [position for position in info["group"] if position != index]
        detalhes = "\n".join(
            f"#{position + 1}  {rule_type_label(glossary_entry_type(self.state.entries[position]))}"
            f"  ->  {preview(glossary_entry_pair(self.state.entries[position])[1], 48)}"
            for position in descartadas
        )
        if not messagebox.askyesno(
            "Manter esta regra",
            f"Manter a regra #{index + 1} para {info['pattern']!r} e remover "
            f"{len(descartadas)} regra(s) que disputam o mesmo texto?\n\n{detalhes}",
            parent=self.win,
        ):
            return

        restantes = resolve_glossary_conflict(self.state.entries, index, self.state.conflicts)
        if restantes is None:
            self.show_message("Nada a resolver", WARNING_COLOR)
            return

        # A entrada mantida e reencontrada pelo conteudo: remover as anteriores
        # desloca a posicao dela, e o arquivo pode ter mudado por fora (S6).
        entrada = self.state.entries[index]
        mantida = (*glossary_entry_pair(entrada), glossary_entry_type(entrada))
        try:
            save_glossary_entries(restantes)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao gravar glossário:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        self.state.selected_index = find_glossary_entry_index(self.state.entries, mantida)
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if self.state.selected_index is not None:
            self.select_entry(self.state.selected_index)
        else:
            self.clear_form()
        self.show_message(f"{len(descartadas)} regra(s) em conflito removida(s)")

    def promote_this_rule(self):
        """Resolve o conflito pela prioridade, sem apagar nada (ROADMAP 1.5).

        "Manter esta" tambem faz esta regra vencer, mas removendo as outras do
        arquivo — uma decisao que nao da para revisar depois, porque o que foi
        descartado nao esta mais la. Aqui as duas regras continuam existindo e a
        escolha e um numero no glossario.
        """
        index = self.state.selected_index
        if index is None or index not in self.state.conflicts:
            self.show_message("Selecione uma regra em conflito", WARNING_COLOR)
            return
        if self.state.dirty and not self.confirm_discard_changes():
            return

        promovidas = promote_glossary_rule(self.state.entries, index, self.state.conflicts)
        if promovidas is None:
            self.show_message("Esta regra já vence o conflito", WARNING_COLOR)
            return

        nova = glossary_entry_priority(promovidas[index])
        info = self.state.conflicts[index]
        if not messagebox.askyesno(
            "Priorizar esta regra",
            f"Dar prioridade {nova} à regra #{index + 1} para {info['pattern']!r}?\n\n"
            "As regras que disputam o mesmo texto continuam no glossário; esta "
            "passa a ser a aplicada.",
            parent=self.win,
        ):
            return

        # Reencontrada pelo conteudo, como em "Manter esta": nada foi removido
        # aqui, mas o arquivo pode ter mudado por fora (S6).
        entrada = self.state.entries[index]
        promovida = (*glossary_entry_pair(entrada), glossary_entry_type(entrada))
        try:
            save_glossary_entries(promovidas)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao gravar glossário:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        self.state.selected_index = find_glossary_entry_index(self.state.entries, promovida)
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if self.state.selected_index is not None:
            self.select_entry(self.state.selected_index)
        else:
            self.clear_form()
        self.show_message(f"Regra priorizada (prioridade {nova})")

    def load_rows_from_file(self):
        try:
            self.state.entries = load_glossary_entry_details(deduplicate=False)
            self.state.conflicts = glossary_conflicts(self.state.entries)
            self.state.diagnostics = build_glossary_diagnostics(
                self.state.entries, self.state.conflicts
            )
        except Exception as exc:
            self.state.entries = []
            self.state.diagnostics = []
            self.state.conflicts = {}
            messagebox.showerror("Erro", f"Erro ao carregar glossário:\n{exc}")
        # O indice de validacao e derivado de `entries`; invalida junto.
        self.state.validation_lookup = None
        self.file_label.configure(text=f"Arquivo: Substituicoes.txt")

    def current_validation_lookup(self):
        if self.state.validation_lookup is None:
            self.state.validation_lookup = build_glossary_lookup(self.state.entries)
        return self.state.validation_lookup

    def apply_filter(self):
        self.state.filtered_indices = glossary_filter_indices(
            self.state.entries,
            self.search_text.get(),
            self.filter_segment.get(),
            self.state.diagnostics,
        )
        self.state.filtered_indices = sort_glossary_indices(
            self.state.entries, self.state.filtered_indices, self.sort_text.get()
        )
        self.state.page_index = clamp_page(
            self.state.page_index, len(self.state.filtered_indices), PAGE_SIZE
        )
        self.render_rows()
        self.save_editor_settings()

    def page_count(self):
        return compute_page_count(len(self.state.filtered_indices), PAGE_SIZE)

    def update_page_controls(self):
        pages = self.page_count()
        current_page = self.state.page_index + 1 if pages else 0
        self.page_label.configure(text=f"Página {current_page}/{pages}")
        self.btn_page_prev.configure(state="normal" if self.state.page_index > 0 else "disabled")
        self.btn_page_next.configure(
            state="normal" if self.state.page_index + 1 < pages else "disabled"
        )

    def change_page(self, delta):
        new_page = self.state.page_index + delta
        if 0 <= new_page < self.page_count():
            self.state.page_index = new_page
            self.render_rows()

    def restart_at_first_page(self, _value=None):
        """Trocar o filtro ou a ordem volta para a primeira pagina.

        Era um `lambda` com `page_index.update({"value": 0})` embutido — a unica
        forma de atribuir dentro de uma expressao enquanto o estado morava num
        dict. Com o estado em atributos, e um metodo comum, como o
        `toggle_filter` do editor de traducoes.
        """
        self.state.page_index = 0
        self.apply_filter()

    def refresh_counts(self):
        counts = glossary_counts(self.state.entries, self.state.diagnostics)
        self.counts_label.configure(
            text=(
                f"Total: {counts['total']} · "
                f"Duplicadas: {counts['duplicates']} · "
                f"Conflitos: {counts['conflicts']} · "
                f"Avisos: {counts['invalid']}"
            )
        )
        self.list_count_label.configure(text=f"{len(self.state.filtered_indices)} exibidas")
        self.update_page_controls()

    def build_row_button(self, parent, _visible_index, entry_index):
        button = ctk.CTkButton(
            parent,
            text=row_label(self.state.entries, entry_index, self.state.diagnostics),
            anchor="w",
            height=64,
            fg_color=ROW_COLOR,
            text_color=ROW_TEXT_COLOR,
            hover_color=ROW_HOVER_COLOR,
            command=lambda i=entry_index: self.select_entry(i),
        )
        if entry_index == self.state.selected_index:
            button.configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        return button

    def render_rows(self):
        self.row_buttons.clear()
        self.refresh_counts()

        start = page_offset(self.state.page_index, PAGE_SIZE)
        page_indices = self.state.filtered_indices[start:start + PAGE_SIZE]
        botoes = render_row_buttons(
            self.rows_frame, page_indices, self.build_row_button, "Nenhuma entrada encontrada."
        )
        # A lista guarda pares: o destaque e movido pela posicao no ARQUIVO, que
        # nao e a posicao na pagina quando ha filtro ou ordenacao.
        self.row_buttons.extend(zip(page_indices, botoes))

    def update_row_selection(self, index):
        """Move o destaque trocando so as cores dos botoes afetados.

        Antes isto chamava `render_rows()`, que destroi e recria ate 150
        CTkButtons e ainda recalcula os contadores sobre todas as entradas — a
        cada clique numa linha. O editor de traducoes ja fazia assim.
        """
        for entry_index, button in self.row_buttons:
            selecionado = entry_index == index
            button.configure(
                fg_color=SELECTED_ROW_COLOR if selecionado else ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR if selecionado else ROW_TEXT_COLOR,
            )

    def select_entry(self, index):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.state.selected_index = index
        self.state.loading = True
        entry = self.state.entries[index]
        orig, new = glossary_entry_pair(entry)
        rule_type = glossary_entry_type(entry)
        priority = glossary_entry_priority(entry)
        self.set_text(self.orig_text, orig)
        self.set_text(self.new_text, new)
        self.set_rule_type(rule_type)
        self.set_priority(priority)
        self.set_form_baseline(orig, new, rule_type, priority)
        self.state.loading = False
        self.set_dirty(False)
        self.update_row_selection(index)
        self.refresh_conflict()
        self.orig_text.focus_set()

    def clear_form(self):
        self.state.selected_index = None
        self.state.loading = True
        self.set_text(self.orig_text, "")
        self.set_text(self.new_text, "")
        self.set_rule_type(GLOSSARY_RULE_SUGGESTION)
        self.set_priority(GLOSSARY_PRIORITY_DEFAULT)
        self.set_form_baseline()
        self.state.loading = False
        self.set_dirty(False)
        self.refresh_conflict()
        self.render_rows()
        self.orig_text.focus_set()

    def start_prefilled_entry(self, original, replacement=""):
        self.state.selected_index = None
        self.state.page_index = 0
        self.search_text.set("")
        self.filter_segment.set("Todas")
        self.state.loading = True
        self.set_text(self.orig_text, (original or "").strip())
        self.set_text(self.new_text, (replacement or "").strip())
        self.set_rule_type(GLOSSARY_RULE_SUGGESTION)
        self.set_priority(GLOSSARY_PRIORITY_DEFAULT)
        self.set_form_baseline()
        self.state.loading = False
        self.set_dirty(True)
        self.refresh_conflict()
        self.apply_filter()
        if self.text_value(self.orig_text):
            self.new_text.focus_set()
        else:
            self.orig_text.focus_set()
        self.show_message("Nova entrada pronta para revisar", WARNING_COLOR)

    def confirm_discard_changes(self):
        return messagebox.askyesno(
            "Alterações não salvas",
            "Descartar as alterações atuais?",
            parent=self.win,
        )

    def new_entry(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.clear_form()
        self.show_message("Nova entrada")

    def reload_all(self, select_first=True):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.load_rows_from_file()
        self.state.selected_index = None
        self.state.page_index = 0
        self.apply_filter()
        if select_first and self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])
        else:
            self.clear_form()

    def current_baseline_entry(self):
        """A entrada como estava quando foi carregada no formulario.

        E o que identifica a linha no arquivo — a posicao nao serve, porque a
        janela nao e notificada de alteracoes externas ao glossario.
        """
        return (
            self.form_baseline["orig"],
            self.form_baseline["new"],
            self.form_baseline["type"],
        )

    def locate_saved_entry(self, orig, new, rule_type):
        """Posicao, no `entries` recem recarregado, da entrada acabada de gravar.

        A gravacao normaliza os espacos das pontas (garantia S7), entao procurar
        pelo texto digitado pode nao achar nada. `find_glossary_entry_index`
        normaliza os dois lados antes de comparar.
        """
        return find_glossary_entry_index(self.state.entries, (orig, new, rule_type))

    def report_entry_vanished(self):
        """A entrada editada nao existe mais como estava no arquivo."""
        self.apply_filter()
        self.clear_form()
        messagebox.showwarning(
            "Entrada não encontrada",
            "A entrada que estava sendo editada foi alterada ou removida do "
            "glossário por fora desta janela.\n\n"
            "Nada foi gravado, para não sobrescrever outra entrada. A lista foi "
            "recarregada.",
            parent=self.win,
        )

    def save_current(self):
        orig, new = self.current_pair()
        rule_type = self.current_rule_type()
        priority = self.current_priority()
        warnings = validate_glossary_entry(
            orig,
            new,
            self.state.entries,
            self.state.selected_index,
            rule_type=rule_type,
        )
        if priority is None:
            warnings.append(INVALID_PRIORITY_WARNING)
        blocking = [
            warning
            for warning in warnings
            if warning in {
                "Texto original vazio.",
                "Texto de substituição vazio.",
                INVALID_PRIORITY_WARNING,
            }
        ]
        if blocking:
            self.show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        try:
            if self.state.selected_index is None:
                result = add_glossary_entry(
                    orig, new, rule_type=rule_type, priority=priority
                )
                self.load_rows_from_file()
                self.state.selected_index = self.locate_saved_entry(orig, new, rule_type)
                self.show_message(
                    "Entrada adicionada"
                    if result["status"] == "inserted"
                    else "Entrada já existia",
                    OK_COLOR if result["status"] == "inserted" else WARNING_COLOR,
                )
            else:
                # Pelo estado exibido, nao pela posicao guardada: o arquivo pode
                # ter mudado por fora desde que esta entrada foi selecionada, e
                # ai o indice aponta para a vizinha (garantia S6).
                result = update_glossary_entry_by_entry(
                    self.current_baseline_entry(),
                    orig,
                    new,
                    rule_type=rule_type,
                    index_hint=self.state.selected_index,
                    priority=priority,
                )
                self.load_rows_from_file()
                if result is None:
                    self.report_entry_vanished()
                    return
                self.state.selected_index = result["index"]
                self.show_message("Entrada salva")
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar glossário:\n{exc}", parent=self.win)
            return

        self.set_form_baseline(orig, new, rule_type, priority)
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if (
            self.state.selected_index is not None
            and self.state.selected_index < len(self.state.entries)
        ):
            self.select_entry(self.state.selected_index)

    def save_as_new(self):
        orig, new = self.current_pair()
        rule_type = self.current_rule_type()
        priority = self.current_priority()
        warnings = validate_glossary_entry(orig, new, self.state.entries, rule_type=rule_type)
        if (
            "Texto original vazio." in warnings
            or "Texto de substituição vazio." in warnings
            or priority is None
        ):
            self.show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        try:
            result = add_glossary_entry(
                orig, new, rule_type=rule_type, priority=priority
            )
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar nova entrada:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        if result["status"] == "unchanged":
            self.show_message("Entrada já existia", WARNING_COLOR)
        else:
            self.show_message("Nova entrada salva")
        # Vale para os dois casos: a entrada existente e a recem inserida sao
        # localizadas do mesmo jeito. `len(entries) - 1` so acertava porque a
        # insercao acrescenta no fim, e errava quando ela nao acontecia.
        self.state.selected_index = self.locate_saved_entry(orig, new, rule_type)
        self.set_form_baseline(orig, new, rule_type, priority)
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if self.state.selected_index is not None:
            self.select_entry(self.state.selected_index)

    def delete_current(self):
        index = self.state.selected_index
        if index is None or not (0 <= index < len(self.state.entries)):
            self.show_message("Selecione uma entrada", WARNING_COLOR)
            return

        if not messagebox.askyesno(
            "Excluir entrada",
            "Excluir a entrada selecionada do glossário?",
            parent=self.win,
        ):
            return

        orig, new = glossary_entry_pair(self.state.entries[index])
        rule_type = glossary_entry_type(self.state.entries[index])
        try:
            # Pelo conteudo, nao pela posicao: mesma razao do "Salvar" (S6).
            removed = delete_glossary_entry_by_pair(
                orig, new, rule_type=rule_type, index_hint=index
            )
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao excluir entrada:\n{exc}", parent=self.win)
            return

        if removed is None:
            self.load_rows_from_file()
            self.report_entry_vanished()
            return

        self.load_rows_from_file()
        self.state.selected_index = None
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if self.state.filtered_indices:
            # `removed["index"]` e a posicao real da entrada no arquivo, que
            # pode diferir da que estava selecionada. `filtered_indices` guarda
            # posicoes de `entries`, entao a vizinha e a primeira que sobrou a
            # partir dela — nao `filtered_indices[index]`, que com filtro ou
            # ordenacao ativos apontaria para uma entrada arbitraria.
            seguintes = [i for i in self.state.filtered_indices if i >= removed["index"]]
            self.select_entry(seguintes[0] if seguintes else self.state.filtered_indices[-1])
        else:
            self.clear_form()
        self.show_message("Entrada excluída")

    def deduplicate_entries(self):
        deduplicated = deduplicate_glossary_entries(self.state.entries)
        removed = len(self.state.entries) - len(deduplicated)
        if removed <= 0:
            self.show_message("Nenhuma duplicata exata encontrada")
            return

        if not messagebox.askyesno(
            "Deduplicar glossário",
            f"Remover {removed} duplicata(s) exata(s)?",
            parent=self.win,
        ):
            return

        try:
            save_glossary_entries(deduplicated)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao deduplicar glossário:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        self.state.selected_index = None
        self.set_dirty(False)
        self.update_app_glossary()
        self.apply_filter()
        if self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])
        self.show_message(f"{removed} duplicata(s) removida(s)")

    def create_backup_now(self):
        try:
            backup_path = create_glossary_backup()
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao criar backup:\n{exc}", parent=self.win)
            return

        if backup_path:
            self.show_message(f"Backup criado: {os.path.basename(backup_path)}")
        else:
            self.show_message("Arquivo de glossário ainda não existe", WARNING_COLOR)

    def export_csv(self):
        save_path = filedialog.asksaveasfilename(
            title="Exportar glossário CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            parent=self.win,
        )
        if not save_path:
            return

        try:
            stats = export_glossary_csv(save_path, entries=self.state.entries)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao exportar CSV:\n{exc}", parent=self.win)
            return

        self.show_message(f"CSV exportado: {stats['exported']} entradas")

    def import_csv(self):
        csv_path = filedialog.askopenfilename(
            title="Importar glossário CSV",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            parent=self.win,
        )
        if not csv_path:
            return

        try:
            preview = analyze_glossary_csv_import(None, csv_path)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao analisar CSV:\n{exc}", parent=self.win)
            return

        if preview["inserted"] == 0:
            messagebox.showinfo(
                "Importar CSV",
                (
                    "Nenhuma entrada nova para importar.\n\n"
                    f"Duplicadas: {preview['duplicates']}\n"
                    f"Conflitos ignorados: {preview['conflicts']}\n"
                    f"Inválidas: {preview['invalid']}"
                ),
                parent=self.win,
            )
            return

        confirmed = messagebox.askyesno(
            "Importar CSV",
            (
                f"Importar {preview['inserted']} entrada(s) nova(s)?\n\n"
                f"Linhas: {preview['total_rows']}\n"
                f"Duplicadas ignoradas: {preview['duplicates']}\n"
                f"Conflitos ignorados: {preview['conflicts']}\n"
                f"Inválidas: {preview['invalid']}"
            ),
            parent=self.win,
        )
        if not confirmed:
            return

        try:
            # A previa acima ja tem as entradas escolhidas; importar recalculando
            # releria o CSV e poderia gravar algo diferente do confirmado.
            stats = import_glossary_csv(None, csv_path, analysis=preview)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao importar CSV:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        self.state.selected_index = None
        self.set_dirty(False)
        self.update_app_glossary()
        self.state.page_index = 0
        self.apply_filter()
        if self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])
        self.show_message(f"Importadas {stats['inserted']} entrada(s)")

    def restore_backup(self):
        backup_path = filedialog.askopenfilename(
            title="Restaurar backup do glossário",
            filetypes=[("Arquivos TXT", "*.txt"), ("Todos os arquivos", "*.*")],
            parent=self.win,
        )
        if not backup_path:
            return

        try:
            backup_entries = load_glossary_entries(backup_path, deduplicate=False)
        except Exception as exc:
            messagebox.showerror("Erro", f"Backup inválido:\n{exc}", parent=self.win)
            return

        if not messagebox.askyesno(
            "Restaurar backup",
            (
                f"Restaurar este backup com {len(backup_entries)} entrada(s)?\n\n"
                "O glossário atual será salvo em um backup de segurança antes da restauração."
            ),
            parent=self.win,
        ):
            return

        try:
            restore_glossary_from_backup(None, backup_path)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao restaurar backup:\n{exc}", parent=self.win)
            return

        self.load_rows_from_file()
        self.state.selected_index = None
        self.set_dirty(False)
        self.update_app_glossary()
        self.state.page_index = 0
        self.apply_filter()
        if self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])
        self.show_message("Backup restaurado")

    def apply_search(self):
        self.state.page_index = 0
        self.apply_filter()
        if self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])

    def clear_search(self):
        self.search_text.set("")
        self.state.page_index = 0
        self.apply_filter()
        if self.state.filtered_indices:
            self.select_entry(self.state.filtered_indices[0])

    def close_editor(self):
        if self.state.dirty and not self.confirm_discard_changes():
            return
        self.save_editor_settings()
        self.win.destroy()


def open_glossary_editor(
    app, on_change=None, initial_original=None, initial_replacement=None
):
    """Abre a janela de edicao do glossario.

    Continua sendo uma funcao porque e assim que o resto do programa chama.
    Devolve a instancia, como `open_translation_editor`: quem dirige a janela
    de fora (os testes de widget, a skill) nao precisa mais andar na arvore de
    widgets para alcancar um metodo.
    """
    return GlossaryEditor(app, on_change, initial_original, initial_replacement)

