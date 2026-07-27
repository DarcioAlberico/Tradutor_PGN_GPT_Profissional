import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .glossario import (
    build_glossary_lookup,
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
    glossary_entry_type,
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
    return f"{status}  #{index + 1}  -  {type_label}\nDe: {preview(orig)}\nPara: {preview(new)}"


def open_glossary_editor(app, on_change=None, initial_original=None, initial_replacement=None):
    win = ctk.CTkToplevel(app.root)
    win.title("Editor de Glossário")
    win.geometry("1120x700")
    win.minsize(1040, 640)
    bring_window_to_front(win, app.root, maximize=True)

    settings = load_settings()
    editor_settings = settings.get("glossary_editor", {})
    if not isinstance(editor_settings, dict):
        editor_settings = {}

    saved_geometry = editor_settings.get("geometry")
    if isinstance(saved_geometry, str) and saved_geometry:
        try:
            win.geometry(safe_geometry(win, saved_geometry))
        except tk.TclError:
            pass

    entries = []
    diagnostics = []
    conflicts = {}
    filtered_indices = []
    row_buttons = []
    selected = {"index": None}
    validation_lookup = {"value": None}
    page_index = {"value": 0}
    dirty = {"value": False, "loading": False}
    form_baseline = {"orig": "", "new": "", "type": GLOSSARY_RULE_SUGGESTION}

    search_text = tk.StringVar(master=win, value="")
    test_text_var = tk.StringVar(master=win, value="")
    sort_text = tk.StringVar(master=win, value=editor_settings.get("sort", "Ordem do arquivo"))
    rule_type_text = tk.StringVar(master=win, value=rule_type_label(GLOSSARY_RULE_SUGGESTION))

    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)

    pane_bg = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
    main_pane = tk.PanedWindow(
        win,
        orient=tk.HORIZONTAL,
        sashwidth=8,
        sashrelief=tk.FLAT,
        bd=0,
        bg=pane_bg,
    )
    main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

    list_frame = ctk.CTkFrame(main_pane, corner_radius=8, width=420)
    main_pane.add(list_frame, minsize=340)
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
    list_count_label = ctk.CTkLabel(header, text="", anchor="e")
    list_count_label.grid(row=0, column=1, sticky="e")

    page_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
    page_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
    page_bar.columnconfigure(1, weight=1)
    btn_page_prev = ctk.CTkButton(page_bar, text="< Página", width=92)
    btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
    page_label = ctk.CTkLabel(page_bar, text="", anchor="center")
    page_label.grid(row=0, column=1, sticky="ew")
    btn_page_next = ctk.CTkButton(page_bar, text="Página >", width=92)
    btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

    search_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
    search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
    search_bar.columnconfigure(0, weight=1)
    search_entry = ctk.CTkEntry(
        search_bar,
        textvariable=search_text,
        placeholder_text="Buscar original ou substituição",
    )
    search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    btn_search = ctk.CTkButton(search_bar, text="Buscar", width=82)
    btn_search.grid(row=0, column=1, padx=(0, 6))
    btn_clear_search = ctk.CTkButton(search_bar, text="Limpar", width=74)
    btn_clear_search.grid(row=0, column=2)

    filter_segment = ctk.CTkSegmentedButton(
        list_frame,
        values=["Todas", "Duplicadas", "Conflitos", "Inválidas"],
    )
    filter_segment.set(editor_settings.get("filter", "Todas") if editor_settings.get("filter") in {
        "Todas",
        "Duplicadas",
        "Conflitos",
        "Inválidas",
    } else "Todas")
    filter_segment.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

    sort_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
    sort_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))
    sort_bar.columnconfigure(1, weight=1)
    ctk.CTkLabel(sort_bar, text="Ordem").grid(row=0, column=0, sticky="w", padx=(0, 6))
    sort_menu = ctk.CTkOptionMenu(
        sort_bar,
        variable=sort_text,
        values=["Ordem do arquivo", "Original A-Z", "Substituição A-Z", "Maior original"],
    )
    sort_menu.grid(row=0, column=1, sticky="ew")

    counts_label = ctk.CTkLabel(list_frame, text="", anchor="w")
    counts_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))

    rows_frame = ctk.CTkScrollableFrame(list_frame, height=420)
    rows_frame.grid(row=6, column=0, sticky="nsew", padx=10, pady=(0, 10))

    detail_frame = ctk.CTkFrame(main_pane, corner_radius=8)
    main_pane.add(detail_frame, minsize=620)
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
    orig_text = ctk.CTkTextbox(detail_frame, height=120, wrap=tk.WORD)
    orig_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

    ctk.CTkLabel(detail_frame, text="Substituir por:").grid(
        row=2,
        column=0,
        sticky="w",
        padx=10,
        pady=(0, 2),
    )
    new_text = ctk.CTkTextbox(detail_frame, height=120, wrap=tk.WORD)
    new_text.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 8))

    type_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
    type_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))
    type_bar.columnconfigure(1, weight=1)
    ctk.CTkLabel(type_bar, text="Tipo:").grid(row=0, column=0, sticky="w", padx=(0, 6))
    type_menu = ctk.CTkOptionMenu(
        type_bar,
        variable=rule_type_text,
        values=[rule_type_label(rule_type) for rule_type in GLOSSARY_RULE_TYPES],
        width=160,
    )
    type_menu.grid(row=0, column=1, sticky="w")

    validation_label = ctk.CTkLabel(
        detail_frame,
        text="",
        anchor="w",
        justify=tk.LEFT,
        text_color=OK_COLOR,
    )
    validation_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 8))

    # So aparece quando a entrada selecionada disputa um padrao com outra. Fora
    # disso a barra sai do grid, para nao ocupar espaco permanente com nada.
    conflict_bar = ctk.CTkFrame(detail_frame, fg_color="transparent")
    conflict_bar.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))
    conflict_bar.columnconfigure(0, weight=1)
    conflict_label = ctk.CTkLabel(
        conflict_bar,
        text="",
        anchor="w",
        justify=tk.LEFT,
        text_color=WARNING_COLOR,
        wraplength=460,
    )
    conflict_label.grid(row=0, column=0, sticky="ew")
    btn_keep_conflict = ctk.CTkButton(conflict_bar, text="Manter esta", width=110)
    btn_keep_conflict.grid(row=0, column=1, sticky="e", padx=(6, 0))
    conflict_bar.grid_remove()

    test_header = ctk.CTkFrame(detail_frame, fg_color="transparent")
    test_header.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 2))
    test_header.columnconfigure(1, weight=1)
    ctk.CTkLabel(test_header, text="Teste rápido:").grid(row=0, column=0, sticky="w")
    btn_apply_preview = ctk.CTkButton(test_header, text="Aplicar selecionada", width=140)
    btn_apply_preview.grid(row=0, column=2, sticky="e")
    btn_apply_all_preview = ctk.CTkButton(test_header, text="Aplicar todas", width=110)
    btn_apply_all_preview.grid(row=0, column=3, sticky="e", padx=(6, 0))

    test_input = ctk.CTkEntry(
        detail_frame,
        textvariable=test_text_var,
        placeholder_text="Digite ou cole uma frase para testar a substituição selecionada",
    )
    test_input.grid(row=8, column=0, sticky="ew", padx=10, pady=(0, 6))

    preview_text = ctk.CTkTextbox(detail_frame, height=90, wrap=tk.WORD)
    preview_text.grid(row=9, column=0, sticky="nsew", padx=10, pady=(0, 10))
    preview_text.configure(state="disabled")

    footer = ctk.CTkFrame(win, corner_radius=8)
    footer.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
    footer.columnconfigure(0, weight=1)

    status_line = ctk.CTkFrame(footer, fg_color="transparent")
    status_line.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
    msg_label = ctk.CTkLabel(status_line, text="", text_color=OK_COLOR)
    msg_label.pack(side=tk.LEFT)
    dirty_label = ctk.CTkLabel(status_line, text="Salvo", text_color=OK_COLOR)
    dirty_label.pack(side=tk.LEFT, padx=(12, 0))
    file_label = ctk.CTkLabel(status_line, text="", text_color="#64748b")
    file_label.pack(side=tk.LEFT, padx=(12, 0))

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
    buttons = {}
    for column, (text, width) in enumerate(action_specs):
        button = ctk.CTkButton(actions, text=text, width=width)
        row = column // 5
        col = column % 5
        button.grid(row=row, column=col, sticky="ew", padx=(0, 6), pady=2)
        actions.columnconfigure(col, weight=1)
        buttons[text] = button

    def show_message(text, color=OK_COLOR):
        flash_message(msg_label, win, text, 1800, text_color=color)

    def save_editor_settings():
        save_window_section(
            settings,
            "glossary_editor",
            {"filter": filter_segment.get(), "sort": sort_text.get()},
            window=win,
            sashes=(("main_sash_x", main_pane, 0),),
        )

    def restore_pane_position():
        restore_sash(main_pane, editor_settings.get("main_sash_x"), 360, 520)

    def update_app_glossary():
        app.glossary_substitutions = load_interactive_substitutions()
        if hasattr(app, "log_message"):
            app.log_message(
                f"Glossário atualizado: {len(app.glossary_substitutions)} entradas"
            )
        for callback in list(getattr(app, "glossary_change_callbacks", [])):
            callback(app.glossary_substitutions)
        if on_change is not None:
            on_change(app.glossary_substitutions)

    def text_value(widget):
        return widget.get("1.0", tk.END).rstrip("\n")

    def set_text(widget, value):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        try:
            widget.edit_modified(False)
        except tk.TclError:
            pass

    def current_pair():
        return text_value(orig_text), text_value(new_text)

    def current_rule_type():
        return rule_type_value(rule_type_text.get())

    def set_rule_type(rule_type):
        rule_type_text.set(rule_type_label(glossary_entry_type((None, None, rule_type))))

    def set_form_baseline(orig="", new="", rule_type=None):
        form_baseline["orig"] = orig or ""
        form_baseline["new"] = new or ""
        form_baseline["type"] = rule_type or GLOSSARY_RULE_SUGGESTION

    def form_changed():
        orig, new = current_pair()
        return (
            orig != form_baseline["orig"]
            or new != form_baseline["new"]
            or current_rule_type() != form_baseline["type"]
        )

    def set_dirty(value):
        dirty["value"] = value
        dirty_label.configure(
            text="Alterações não salvas" if value else "Salvo",
            text_color=WARNING_COLOR if value else OK_COLOR,
        )
        refresh_validation()

    def mark_dirty(_event=None):
        if not dirty["loading"]:
            set_dirty(form_changed())

    def refresh_preview():
        orig, new = current_pair()
        sample = test_text_var.get()
        result = apply_substitution(sample, orig, new) if orig else sample
        set_preview_text(result)

    def apply_all_to_preview():
        set_preview_text(apply_all_substitutions(test_text_var.get(), entry_pairs(entries)))

    def set_preview_text(value):
        preview_text.configure(state="normal")
        preview_text.delete("1.0", tk.END)
        preview_text.insert("1.0", value)
        preview_text.configure(state="disabled")

    def refresh_validation():
        orig, new = current_pair()
        current_index = selected["index"]
        warnings = validate_glossary_entry(
            orig,
            new,
            current_index=current_index,
            rule_type=current_rule_type(),
            existing_lookup=current_validation_lookup(),
        )
        if warnings:
            validation_label.configure(
                text="Avisos: " + " | ".join(warnings),
                text_color=WARNING_COLOR,
            )
        elif orig or new:
            validation_label.configure(text="Entrada válida", text_color=OK_COLOR)
        else:
            validation_label.configure(text="", text_color=OK_COLOR)
        refresh_preview()

    def refresh_conflict():
        """Diz qual regra do conflito o programa aplica (garantia S9).

        Descreve a entrada **como esta no arquivo**, nao o que esta no
        formulario: quem vence depende da posicao no glossario e do tipo
        gravados, e o texto sendo digitado ainda nao e nenhum dos dois.
        """
        index = selected["index"]
        message = ""
        if index is not None and 0 <= index < len(entries):
            message = describe_glossary_conflict(entries, index, conflicts)

        if message:
            conflict_label.configure(text=message)
            conflict_bar.grid()
        else:
            conflict_label.configure(text="")
            conflict_bar.grid_remove()

    def keep_this_rule():
        index = selected["index"]
        if index is None or index not in conflicts:
            show_message("Selecione uma regra em conflito", WARNING_COLOR)
            return
        if dirty["value"] and not confirm_discard_changes():
            return

        info = conflicts[index]
        descartadas = [position for position in info["group"] if position != index]
        detalhes = "\n".join(
            f"#{position + 1}  {rule_type_label(glossary_entry_type(entries[position]))}"
            f"  ->  {preview(glossary_entry_pair(entries[position])[1], 48)}"
            for position in descartadas
        )
        if not messagebox.askyesno(
            "Manter esta regra",
            f"Manter a regra #{index + 1} para {info['pattern']!r} e remover "
            f"{len(descartadas)} regra(s) que disputam o mesmo texto?\n\n{detalhes}",
            parent=win,
        ):
            return

        restantes = resolve_glossary_conflict(entries, index, conflicts)
        if restantes is None:
            show_message("Nada a resolver", WARNING_COLOR)
            return

        # A entrada mantida e reencontrada pelo conteudo: remover as anteriores
        # desloca a posicao dela, e o arquivo pode ter mudado por fora (S6).
        mantida = (*glossary_entry_pair(entries[index]), glossary_entry_type(entries[index]))
        try:
            save_glossary_entries(restantes)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao gravar glossário:\n{exc}", parent=win)
            return

        load_rows_from_file()
        selected["index"] = find_glossary_entry_index(entries, mantida)
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if selected["index"] is not None:
            select_entry(selected["index"])
        else:
            clear_form()
        show_message(f"{len(descartadas)} regra(s) em conflito removida(s)")

    def load_rows_from_file():
        nonlocal entries, diagnostics, conflicts
        try:
            entries = load_glossary_entry_details(deduplicate=False)
            conflicts = glossary_conflicts(entries)
            diagnostics = build_glossary_diagnostics(entries, conflicts)
        except Exception as exc:
            entries = []
            diagnostics = []
            conflicts = {}
            messagebox.showerror("Erro", f"Erro ao carregar glossário:\n{exc}")
        # O indice de validacao e derivado de `entries`; invalida junto.
        validation_lookup["value"] = None
        file_label.configure(text=f"Arquivo: Substituicoes.txt")

    def current_validation_lookup():
        if validation_lookup["value"] is None:
            validation_lookup["value"] = build_glossary_lookup(entries)
        return validation_lookup["value"]

    def apply_filter():
        nonlocal filtered_indices
        filtered_indices = glossary_filter_indices(
            entries,
            search_text.get(),
            filter_segment.get(),
            diagnostics,
        )
        filtered_indices = sort_glossary_indices(entries, filtered_indices, sort_text.get())
        page_index["value"] = clamp_page(
            page_index["value"], len(filtered_indices), PAGE_SIZE
        )
        render_rows()
        save_editor_settings()

    def page_count():
        return compute_page_count(len(filtered_indices), PAGE_SIZE)

    def update_page_controls():
        pages = page_count()
        current_page = page_index["value"] + 1 if pages else 0
        page_label.configure(text=f"Página {current_page}/{pages}")
        btn_page_prev.configure(state="normal" if page_index["value"] > 0 else "disabled")
        btn_page_next.configure(
            state="normal" if page_index["value"] + 1 < pages else "disabled"
        )

    def change_page(delta):
        new_page = page_index["value"] + delta
        if 0 <= new_page < page_count():
            page_index["value"] = new_page
            render_rows()

    def refresh_counts():
        counts = glossary_counts(entries, diagnostics)
        counts_label.configure(
            text=(
                f"Total: {counts['total']} · "
                f"Duplicadas: {counts['duplicates']} · "
                f"Conflitos: {counts['conflicts']} · "
                f"Avisos: {counts['invalid']}"
            )
        )
        list_count_label.configure(text=f"{len(filtered_indices)} exibidas")
        update_page_controls()

    def build_row_button(parent, _visible_index, entry_index):
        button = ctk.CTkButton(
            parent,
            text=row_label(entries, entry_index, diagnostics),
            anchor="w",
            height=64,
            fg_color=ROW_COLOR,
            text_color=ROW_TEXT_COLOR,
            hover_color=ROW_HOVER_COLOR,
            command=lambda i=entry_index: select_entry(i),
        )
        if entry_index == selected["index"]:
            button.configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        return button

    def render_rows():
        row_buttons.clear()
        refresh_counts()

        start = page_offset(page_index["value"], PAGE_SIZE)
        page_indices = filtered_indices[start:start + PAGE_SIZE]
        botoes = render_row_buttons(
            rows_frame, page_indices, build_row_button, "Nenhuma entrada encontrada."
        )
        # A lista guarda pares: o destaque e movido pela posicao no ARQUIVO, que
        # nao e a posicao na pagina quando ha filtro ou ordenacao.
        row_buttons.extend(zip(page_indices, botoes))

    def update_row_selection(index):
        """Move o destaque trocando so as cores dos botoes afetados.

        Antes isto chamava `render_rows()`, que destroi e recria ate 150
        CTkButtons e ainda recalcula os contadores sobre todas as entradas — a
        cada clique numa linha. O editor de traducoes ja fazia assim.
        """
        for entry_index, button in row_buttons:
            selecionado = entry_index == index
            button.configure(
                fg_color=SELECTED_ROW_COLOR if selecionado else ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR if selecionado else ROW_TEXT_COLOR,
            )

    def select_entry(index):
        if dirty["value"] and not confirm_discard_changes():
            return
        selected["index"] = index
        dirty["loading"] = True
        entry = entries[index]
        orig, new = glossary_entry_pair(entry)
        rule_type = glossary_entry_type(entry)
        set_text(orig_text, orig)
        set_text(new_text, new)
        set_rule_type(rule_type)
        set_form_baseline(orig, new, rule_type)
        dirty["loading"] = False
        set_dirty(False)
        update_row_selection(index)
        refresh_conflict()
        orig_text.focus_set()

    def clear_form():
        selected["index"] = None
        dirty["loading"] = True
        set_text(orig_text, "")
        set_text(new_text, "")
        set_rule_type(GLOSSARY_RULE_SUGGESTION)
        set_form_baseline()
        dirty["loading"] = False
        set_dirty(False)
        refresh_conflict()
        render_rows()
        orig_text.focus_set()

    def start_prefilled_entry(original, replacement=""):
        selected["index"] = None
        page_index["value"] = 0
        search_text.set("")
        filter_segment.set("Todas")
        dirty["loading"] = True
        set_text(orig_text, (original or "").strip())
        set_text(new_text, (replacement or "").strip())
        set_rule_type(GLOSSARY_RULE_SUGGESTION)
        set_form_baseline()
        dirty["loading"] = False
        set_dirty(True)
        refresh_conflict()
        apply_filter()
        if text_value(orig_text):
            new_text.focus_set()
        else:
            orig_text.focus_set()
        show_message("Nova entrada pronta para revisar", WARNING_COLOR)

    def confirm_discard_changes():
        return messagebox.askyesno(
            "Alterações não salvas",
            "Descartar as alterações atuais?",
            parent=win,
        )

    def new_entry():
        if dirty["value"] and not confirm_discard_changes():
            return
        clear_form()
        show_message("Nova entrada")

    def reload_all(select_first=True):
        if dirty["value"] and not confirm_discard_changes():
            return
        load_rows_from_file()
        selected["index"] = None
        page_index["value"] = 0
        apply_filter()
        if select_first and filtered_indices:
            select_entry(filtered_indices[0])
        else:
            clear_form()

    def current_baseline_entry():
        """A entrada como estava quando foi carregada no formulario.

        E o que identifica a linha no arquivo — a posicao nao serve, porque a
        janela nao e notificada de alteracoes externas ao glossario.
        """
        return (
            form_baseline["orig"],
            form_baseline["new"],
            form_baseline["type"],
        )

    def locate_saved_entry(orig, new, rule_type):
        """Posicao, no `entries` recem recarregado, da entrada acabada de gravar.

        A gravacao normaliza os espacos das pontas (garantia S7), entao procurar
        pelo texto digitado pode nao achar nada. `find_glossary_entry_index`
        normaliza os dois lados antes de comparar.
        """
        return find_glossary_entry_index(entries, (orig, new, rule_type))

    def report_entry_vanished():
        """A entrada editada nao existe mais como estava no arquivo."""
        apply_filter()
        clear_form()
        messagebox.showwarning(
            "Entrada não encontrada",
            "A entrada que estava sendo editada foi alterada ou removida do "
            "glossário por fora desta janela.\n\n"
            "Nada foi gravado, para não sobrescrever outra entrada. A lista foi "
            "recarregada.",
            parent=win,
        )

    def save_current():
        orig, new = current_pair()
        rule_type = current_rule_type()
        warnings = validate_glossary_entry(
            orig,
            new,
            entries,
            selected["index"],
            rule_type=rule_type,
        )
        blocking = [
            warning
            for warning in warnings
            if warning in {"Texto original vazio.", "Texto de substituição vazio."}
        ]
        if blocking:
            show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        try:
            if selected["index"] is None:
                result = add_glossary_entry(orig, new, rule_type=rule_type)
                load_rows_from_file()
                selected["index"] = locate_saved_entry(orig, new, rule_type)
                show_message(
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
                    current_baseline_entry(),
                    orig,
                    new,
                    rule_type=rule_type,
                    index_hint=selected["index"],
                )
                load_rows_from_file()
                if result is None:
                    report_entry_vanished()
                    return
                selected["index"] = result["index"]
                show_message("Entrada salva")
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar glossário:\n{exc}", parent=win)
            return

        set_form_baseline(orig, new, rule_type)
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if selected["index"] is not None and selected["index"] < len(entries):
            select_entry(selected["index"])

    def save_as_new():
        orig, new = current_pair()
        rule_type = current_rule_type()
        warnings = validate_glossary_entry(orig, new, entries, rule_type=rule_type)
        if "Texto original vazio." in warnings or "Texto de substituição vazio." in warnings:
            show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        try:
            result = add_glossary_entry(orig, new, rule_type=rule_type)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar nova entrada:\n{exc}", parent=win)
            return

        load_rows_from_file()
        if result["status"] == "unchanged":
            show_message("Entrada já existia", WARNING_COLOR)
        else:
            show_message("Nova entrada salva")
        # Vale para os dois casos: a entrada existente e a recem inserida sao
        # localizadas do mesmo jeito. `len(entries) - 1` so acertava porque a
        # insercao acrescenta no fim, e errava quando ela nao acontecia.
        selected["index"] = locate_saved_entry(orig, new, rule_type)
        set_form_baseline(orig, new, rule_type)
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if selected["index"] is not None:
            select_entry(selected["index"])

    def delete_current():
        index = selected["index"]
        if index is None or not (0 <= index < len(entries)):
            show_message("Selecione uma entrada", WARNING_COLOR)
            return

        if not messagebox.askyesno(
            "Excluir entrada",
            "Excluir a entrada selecionada do glossário?",
            parent=win,
        ):
            return

        orig, new = glossary_entry_pair(entries[index])
        rule_type = glossary_entry_type(entries[index])
        try:
            # Pelo conteudo, nao pela posicao: mesma razao do "Salvar" (S6).
            removed = delete_glossary_entry_by_pair(
                orig, new, rule_type=rule_type, index_hint=index
            )
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao excluir entrada:\n{exc}", parent=win)
            return

        if removed is None:
            load_rows_from_file()
            report_entry_vanished()
            return

        load_rows_from_file()
        selected["index"] = None
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if filtered_indices:
            # `removed["index"]` e a posicao real da entrada no arquivo, que
            # pode diferir da que estava selecionada. `filtered_indices` guarda
            # posicoes de `entries`, entao a vizinha e a primeira que sobrou a
            # partir dela — nao `filtered_indices[index]`, que com filtro ou
            # ordenacao ativos apontaria para uma entrada arbitraria.
            seguintes = [i for i in filtered_indices if i >= removed["index"]]
            select_entry(seguintes[0] if seguintes else filtered_indices[-1])
        else:
            clear_form()
        show_message("Entrada excluída")

    def deduplicate_entries():
        deduplicated = deduplicate_glossary_entries(entries)
        removed = len(entries) - len(deduplicated)
        if removed <= 0:
            show_message("Nenhuma duplicata exata encontrada")
            return

        if not messagebox.askyesno(
            "Deduplicar glossário",
            f"Remover {removed} duplicata(s) exata(s)?",
            parent=win,
        ):
            return

        try:
            save_glossary_entries(deduplicated)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao deduplicar glossário:\n{exc}", parent=win)
            return

        load_rows_from_file()
        selected["index"] = None
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[0])
        show_message(f"{removed} duplicata(s) removida(s)")

    def create_backup_now():
        try:
            backup_path = create_glossary_backup()
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao criar backup:\n{exc}", parent=win)
            return

        if backup_path:
            show_message(f"Backup criado: {os.path.basename(backup_path)}")
        else:
            show_message("Arquivo de glossário ainda não existe", WARNING_COLOR)

    def export_csv():
        save_path = filedialog.asksaveasfilename(
            title="Exportar glossário CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            parent=win,
        )
        if not save_path:
            return

        try:
            stats = export_glossary_csv(save_path, entries=entries)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao exportar CSV:\n{exc}", parent=win)
            return

        show_message(f"CSV exportado: {stats['exported']} entradas")

    def import_csv():
        csv_path = filedialog.askopenfilename(
            title="Importar glossário CSV",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            parent=win,
        )
        if not csv_path:
            return

        try:
            preview = analyze_glossary_csv_import(None, csv_path)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao analisar CSV:\n{exc}", parent=win)
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
                parent=win,
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
            parent=win,
        )
        if not confirmed:
            return

        try:
            # A previa acima ja tem as entradas escolhidas; importar recalculando
            # releria o CSV e poderia gravar algo diferente do confirmado.
            stats = import_glossary_csv(None, csv_path, analysis=preview)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao importar CSV:\n{exc}", parent=win)
            return

        load_rows_from_file()
        selected["index"] = None
        set_dirty(False)
        update_app_glossary()
        page_index["value"] = 0
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[0])
        show_message(f"Importadas {stats['inserted']} entrada(s)")

    def restore_backup():
        backup_path = filedialog.askopenfilename(
            title="Restaurar backup do glossário",
            filetypes=[("Arquivos TXT", "*.txt"), ("Todos os arquivos", "*.*")],
            parent=win,
        )
        if not backup_path:
            return

        try:
            backup_entries = load_glossary_entries(backup_path, deduplicate=False)
        except Exception as exc:
            messagebox.showerror("Erro", f"Backup inválido:\n{exc}", parent=win)
            return

        if not messagebox.askyesno(
            "Restaurar backup",
            (
                f"Restaurar este backup com {len(backup_entries)} entrada(s)?\n\n"
                "O glossário atual será salvo em um backup de segurança antes da restauração."
            ),
            parent=win,
        ):
            return

        try:
            restore_glossary_from_backup(None, backup_path)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao restaurar backup:\n{exc}", parent=win)
            return

        load_rows_from_file()
        selected["index"] = None
        set_dirty(False)
        update_app_glossary()
        page_index["value"] = 0
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[0])
        show_message("Backup restaurado")

    def apply_search():
        page_index["value"] = 0
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[0])

    def clear_search():
        search_text.set("")
        page_index["value"] = 0
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[0])

    def close_editor():
        if dirty["value"] and not confirm_discard_changes():
            return
        save_editor_settings()
        win.destroy()

    buttons["Nova entrada"].configure(command=new_entry)
    buttons["Salvar"].configure(command=save_current)
    buttons["Salvar como nova"].configure(command=save_as_new)
    buttons["Excluir"].configure(command=delete_current)
    buttons["Deduplicar"].configure(command=deduplicate_entries)
    buttons["Backup"].configure(command=create_backup_now)
    buttons["Recarregar"].configure(command=reload_all)
    buttons["Exportar CSV"].configure(command=export_csv)
    buttons["Importar CSV"].configure(command=import_csv)
    buttons["Restaurar backup"].configure(command=restore_backup)
    btn_page_prev.configure(command=lambda: change_page(-1))
    btn_page_next.configure(command=lambda: change_page(1))
    btn_search.configure(command=apply_search)
    btn_clear_search.configure(command=clear_search)
    btn_keep_conflict.configure(command=keep_this_rule)
    btn_apply_preview.configure(command=refresh_preview)
    btn_apply_all_preview.configure(command=apply_all_to_preview)
    sort_menu.configure(command=lambda _value: (page_index.update({"value": 0}), apply_filter()))
    filter_segment.configure(command=lambda _value: (page_index.update({"value": 0}), apply_filter()))
    type_menu.configure(command=lambda _value: mark_dirty())
    search_entry.bind("<Return>", lambda _event: apply_search())
    test_input.bind("<KeyRelease>", lambda _event: refresh_preview())
    orig_text.bind("<<Modified>>", lambda event: (orig_text.edit_modified(False), mark_dirty())[1])
    new_text.bind("<<Modified>>", lambda event: (new_text.edit_modified(False), mark_dirty())[1])
    win.bind("<Control-s>", lambda _event: (save_current(), "break")[1])
    win.bind("<Control-S>", lambda _event: (save_current(), "break")[1])
    win.bind("<Control-n>", lambda _event: (new_entry(), "break")[1])
    win.bind("<Control-N>", lambda _event: (new_entry(), "break")[1])
    win.protocol("WM_DELETE_WINDOW", close_editor)

    has_initial_entry = bool(
        (initial_original or "").strip() or (initial_replacement or "").strip()
    )
    reload_all(select_first=not has_initial_entry)
    if has_initial_entry:
        start_prefilled_entry(initial_original, initial_replacement)
    win.after(100, restore_pane_position)
