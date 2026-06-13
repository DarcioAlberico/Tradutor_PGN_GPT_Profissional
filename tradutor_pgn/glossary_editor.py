import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .glossario import (
    add_glossary_entry,
    analyze_glossary_csv_import,
    create_glossary_backup,
    deduplicate_glossary_entries,
    delete_glossary_entry,
    export_glossary_csv,
    apply_all_substitutions,
    apply_substitution,
    import_glossary_csv,
    load_glossary_entries,
    load_substitutions,
    restore_glossary_from_backup,
    save_glossary_entries,
    update_glossary_entry,
    validate_glossary_entry,
)
from .settings import load_settings, save_settings


ROW_COLOR = ("#f8fafc", "#1f2937")
ROW_TEXT_COLOR = ("#111827", "#e5e7eb")
ROW_HOVER_COLOR = ("#e2e8f0", "#374151")
SELECTED_ROW_COLOR = ("#3b82f6", "#1f6aa5")
SELECTED_ROW_TEXT_COLOR = "#ffffff"
WARNING_COLOR = "#f59e0b"
OK_COLOR = "#16a34a"
ERROR_COLOR = "#dc2626"
PAGE_SIZE = 150
GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)$")


def preview(text, limit=68):
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def safe_geometry(win, geometry):
    match = GEOMETRY_RE.match(geometry or "")
    if not match:
        return geometry

    width = int(match.group(1))
    height = int(match.group(2))
    x = int(match.group(4))
    y = int(match.group(6))
    if match.group(3) == "-" and x >= 0:
        x = -x
    if match.group(5) == "-" and y >= 0:
        y = -y

    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    width = min(max(width, 1040), screen_width)
    height = min(max(height, 640), screen_height)
    x = min(max(0, x), max(0, screen_width - width))
    y = min(max(0, y), max(0, screen_height - height))
    return f"{width}x{height}+{x}+{y}"


def build_glossary_diagnostics(entries):
    pair_counts = {}
    replacements_by_original = {}
    for orig, new in entries:
        pair_counts[(orig, new)] = pair_counts.get((orig, new), 0) + 1
        replacements_by_original.setdefault(orig, set()).add(new)

    diagnostics = []
    for orig, new in entries:
        warnings = validate_glossary_entry(orig, new)
        if pair_counts.get((orig, new), 0) > 1:
            warnings.append("Entrada duplicada.")
        if orig and len(replacements_by_original.get(orig, set())) > 1:
            warnings.append("Mesmo original com substituição diferente.")
        diagnostics.append(warnings)
    return diagnostics


def glossary_entry_warnings(entries, index, diagnostics=None):
    if diagnostics is not None and 0 <= index < len(diagnostics):
        return diagnostics[index]
    orig, new = entries[index]
    return validate_glossary_entry(orig, new, entries, current_index=index)


def glossary_filter_indices(entries, search_text="", filter_name="Todas", diagnostics=None):
    query = (search_text or "").strip().lower()
    result = []

    for index, (orig, new) in enumerate(entries):
        if query and query not in orig.lower() and query not in new.lower():
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
        return sorted(indices, key=lambda index: (entries[index][0].casefold(), index))
    if sort_name == "Substituição A-Z":
        return sorted(indices, key=lambda index: (entries[index][1].casefold(), index))
    if sort_name == "Maior original":
        return sorted(indices, key=lambda index: (-len(entries[index][0]), index))
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
    orig, new = entries[index]
    warnings = glossary_entry_warnings(entries, index, diagnostics)
    status = "AVISO" if warnings else "OK"
    return f"{status}  #{index + 1}\nDe: {preview(orig)}\nPara: {preview(new)}"


def open_glossary_editor(app, on_change=None, initial_original=None, initial_replacement=None):
    win = ctk.CTkToplevel(app.root)
    win.title("Editor de Glossário")
    win.geometry("1120x700")
    win.minsize(1040, 640)

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
    filtered_indices = []
    row_buttons = []
    selected = {"index": None}
    page_index = {"value": 0}
    dirty = {"value": False, "loading": False}

    search_text = tk.StringVar(master=win, value="")
    test_text_var = tk.StringVar(master=win, value="")
    sort_text = tk.StringVar(master=win, value=editor_settings.get("sort", "Ordem do arquivo"))

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
    detail_frame.rowconfigure(7, weight=1)

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

    validation_label = ctk.CTkLabel(
        detail_frame,
        text="",
        anchor="w",
        justify=tk.LEFT,
        text_color=OK_COLOR,
    )
    validation_label.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))

    test_header = ctk.CTkFrame(detail_frame, fg_color="transparent")
    test_header.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 2))
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
    test_input.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 6))

    preview_text = ctk.CTkTextbox(detail_frame, height=90, wrap=tk.WORD)
    preview_text.grid(row=7, column=0, sticky="nsew", padx=10, pady=(0, 10))
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
        msg_label.configure(text=text, text_color=color)
        win.after(1800, lambda: msg_label.configure(text=""))

    def save_editor_settings():
        editor = settings.setdefault("glossary_editor", {})
        if not isinstance(editor, dict):
            editor = {}
            settings["glossary_editor"] = editor
        editor["geometry"] = win.geometry()
        editor["filter"] = filter_segment.get()
        editor["sort"] = sort_text.get()
        try:
            editor["main_sash_x"] = main_pane.sash_coord(0)[0]
        except tk.TclError:
            pass
        try:
            save_settings(settings)
        except OSError:
            pass

    def restore_pane_position():
        sash_x = editor_settings.get("main_sash_x")
        if isinstance(sash_x, int) and sash_x > 0:
            try:
                main_pane.sash_place(0, max(360, min(520, sash_x)), 0)
            except tk.TclError:
                pass

    def update_app_glossary():
        app.glossary_substitutions = load_substitutions()
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

    def current_pair():
        return text_value(orig_text), text_value(new_text)

    def set_dirty(value):
        dirty["value"] = value
        dirty_label.configure(
            text="Alterações não salvas" if value else "Salvo",
            text_color=WARNING_COLOR if value else OK_COLOR,
        )
        refresh_validation()

    def mark_dirty(_event=None):
        if not dirty["loading"]:
            set_dirty(True)

    def refresh_preview():
        orig, new = current_pair()
        sample = test_text_var.get()
        result = apply_substitution(sample, orig, new) if orig else sample
        set_preview_text(result)

    def apply_all_to_preview():
        set_preview_text(apply_all_substitutions(test_text_var.get(), entries))

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
            entries,
            current_index=current_index,
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

    def load_rows_from_file():
        nonlocal entries, diagnostics
        try:
            entries = load_glossary_entries(deduplicate=False)
            diagnostics = build_glossary_diagnostics(entries)
        except Exception as exc:
            entries = []
            diagnostics = []
            messagebox.showerror("Erro", f"Erro ao carregar glossário:\n{exc}")
        file_label.configure(text=f"Arquivo: Substituicoes.txt")

    def apply_filter():
        nonlocal filtered_indices
        filtered_indices = glossary_filter_indices(
            entries,
            search_text.get(),
            filter_segment.get(),
            diagnostics,
        )
        filtered_indices = sort_glossary_indices(entries, filtered_indices, sort_text.get())
        pages = page_count()
        page_index["value"] = min(page_index["value"], max(0, pages - 1))
        render_rows()
        save_editor_settings()

    def page_count():
        if not filtered_indices:
            return 0
        return (len(filtered_indices) + PAGE_SIZE - 1) // PAGE_SIZE

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

    def render_rows():
        for child in rows_frame.winfo_children():
            child.destroy()
        row_buttons.clear()
        refresh_counts()

        if not filtered_indices:
            ctk.CTkLabel(rows_frame, text="Nenhuma entrada encontrada.").pack(
                anchor="w",
                padx=6,
                pady=6,
            )
            return

        start = page_index["value"] * PAGE_SIZE
        page_indices = filtered_indices[start:start + PAGE_SIZE]

        for visible_index, entry_index in enumerate(page_indices):
            button = ctk.CTkButton(
                rows_frame,
                text=row_label(entries, entry_index, diagnostics),
                anchor="w",
                height=64,
                fg_color=ROW_COLOR,
                text_color=ROW_TEXT_COLOR,
                hover_color=ROW_HOVER_COLOR,
                command=lambda i=entry_index: select_entry(i),
            )
            button.pack(fill=tk.X, padx=2, pady=2)
            row_buttons.append((entry_index, button))
            if entry_index == selected["index"]:
                button.configure(
                    fg_color=SELECTED_ROW_COLOR,
                    text_color=SELECTED_ROW_TEXT_COLOR,
                )

    def select_entry(index):
        if dirty["value"] and not confirm_discard_changes():
            return
        selected["index"] = index
        dirty["loading"] = True
        orig, new = entries[index]
        set_text(orig_text, orig)
        set_text(new_text, new)
        dirty["loading"] = False
        set_dirty(False)
        render_rows()
        orig_text.focus_set()

    def clear_form():
        selected["index"] = None
        dirty["loading"] = True
        set_text(orig_text, "")
        set_text(new_text, "")
        dirty["loading"] = False
        set_dirty(False)
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
        dirty["loading"] = False
        set_dirty(True)
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

    def save_current():
        orig, new = current_pair()
        warnings = validate_glossary_entry(orig, new, entries, selected["index"])
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
                result = add_glossary_entry(orig, new)
                load_rows_from_file()
                pair = (orig, new)
                selected["index"] = entries.index(pair) if pair in entries else len(entries) - 1
                show_message(
                    "Entrada adicionada"
                    if result["status"] == "inserted"
                    else "Entrada já existia",
                    OK_COLOR if result["status"] == "inserted" else WARNING_COLOR,
                )
            else:
                update_glossary_entry(selected["index"], orig, new)
                load_rows_from_file()
                show_message("Entrada salva")
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar glossário:\n{exc}", parent=win)
            return

        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if selected["index"] is not None and selected["index"] < len(entries):
            select_entry(selected["index"])

    def save_as_new():
        orig, new = current_pair()
        warnings = validate_glossary_entry(orig, new, entries)
        if "Texto original vazio." in warnings or "Texto de substituição vazio." in warnings:
            show_message("Corrija os campos obrigatórios", ERROR_COLOR)
            return

        try:
            result = add_glossary_entry(orig, new)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao salvar nova entrada:\n{exc}", parent=win)
            return

        load_rows_from_file()
        if result["status"] == "unchanged":
            show_message("Entrada já existia", WARNING_COLOR)
            pair = (orig, new)
            selected["index"] = entries.index(pair) if pair in entries else None
        else:
            selected["index"] = len(entries) - 1
            show_message("Nova entrada salva")
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

        try:
            delete_glossary_entry(index)
        except Exception as exc:
            messagebox.showerror("Erro", f"Erro ao excluir entrada:\n{exc}", parent=win)
            return

        load_rows_from_file()
        selected["index"] = None
        set_dirty(False)
        update_app_glossary()
        apply_filter()
        if filtered_indices:
            select_entry(filtered_indices[min(index, len(filtered_indices) - 1)])
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
            stats = import_glossary_csv(None, csv_path)
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
    btn_apply_preview.configure(command=refresh_preview)
    btn_apply_all_preview.configure(command=apply_all_to_preview)
    sort_menu.configure(command=lambda _value: (page_index.update({"value": 0}), apply_filter()))
    filter_segment.configure(command=lambda _value: (page_index.update({"value": 0}), apply_filter()))
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
