import csv
from contextlib import closing
from datetime import datetime
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .database import (
    count_review_rows,
    fetch_comment_history,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_translation_by_id,
    get_review_row_offset,
    get_review_status_counts,
    initialize_database,
    set_exact_translation_matches_verified,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from .db_tools import apply_automatic_rules_to_database
from .editor_text import find_text_ranges, replace_all_text
from .glossario import (
    add_to_glossary,
    find_glossary_matches,
    find_glossary_suggestions,
    load_substitutions,
)
from .glossary_editor import open_glossary_editor
from .review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    filter_quality_warning_rows,
    find_first_quality_warning,
    row_has_quality_warning,
)
from .settings import (
    clear_editor_draft,
    get_editor_draft,
    load_settings,
    save_settings,
    set_editor_draft,
)
from .window_utils import bring_window_to_front


ROW_COLOR = ("#f8fafc", "#1f2937")
ROW_TEXT_COLOR = ("#111827", "#e5e7eb")
VERIFIED_ROW_COLOR = ("#d1fae5", "#14532d")
VERIFIED_ROW_TEXT_COLOR = ("#065f46", "#d1fae5")
ROW_HOVER_COLOR = ("#e2e8f0", "#374151")
SELECTED_ROW_COLOR = ("#3b82f6", "#1f6aa5")
SELECTED_ROW_TEXT_COLOR = "#ffffff"
SUGGESTION_COLOR = ("#f8fafc", "#1f2937")
SUGGESTION_TEXT_COLOR = ("#111827", "#e5e7eb")
SUGGESTION_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
PAGE_SIZE = 100
GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)$")


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

    width = min(max(width, 1120), screen_width)
    height = min(max(height, 680), screen_height)
    max_x = max(0, screen_width - width)
    max_y = max(0, screen_height - height)
    x = min(max(0, x), max_x)
    y = min(max(0, y), max_y)

    return f"{width}x{height}+{x}+{y}"


def preview(text, limit=120):
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def row_label(row):
    status = "OK" if len(row) > 3 and row[3] == 1 else "PEND"
    return (
        f"{status}  #{row[0]}\n"
        f"O: {preview(row[1], 54)}\n"
        f"T: {preview(row[2], 54)}"
    )


def row_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_COLOR
    return ROW_COLOR


def row_text_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_TEXT_COLOR
    return ROW_TEXT_COLOR


def open_translation_editor(app):
    lang = app.target_language.get()

    win = ctk.CTkToplevel(app.root)
    win.title(f"Editar traduções ({lang})")
    win.geometry("1280x760")
    win.minsize(1120, 680)
    bring_window_to_front(win, app.root, maximize=True)

    settings = load_settings()
    editor_settings = settings.get("editor", {})
    if not isinstance(editor_settings, dict):
        editor_settings = {}

    saved_geometry = editor_settings.get("geometry")
    if isinstance(saved_geometry, str) and saved_geometry:
        try:
            win.geometry(safe_geometry(win, saved_geometry))
        except tk.TclError:
            pass

    rows = []
    row_buttons = []
    total_rows = {"value": 0}
    status_counts = {"total": 0, "pending": 0, "verified": 0, "qa": 0}
    page_index = {"value": 0}
    current = {
        "id": None,
        "orig": "",
        "trans": "",
        "saved_trans": "",
        "created_at": "",
        "updated_at": "",
        "verified_at": "",
    }
    dirty = {"value": False, "loading": False}
    draft_save_after = {"value": None}
    selected_index = {"value": None}
    selected_suggestion = {"value": None}
    glossary = app.glossary_substitutions
    current_suggestions = []
    suggestion_buttons = []
    search_text = tk.StringVar(master=win, value="")
    editor_find_text = tk.StringVar(master=win, value="")
    editor_replace_text = tk.StringVar(master=win, value="")
    editor_case_sensitive = tk.BooleanVar(master=win, value=False)
    current_find_match = {"value": None}
    go_page_text = tk.StringVar(master=win, value="")
    go_id_text = tk.StringVar(master=win, value="")
    active_search = {"value": ""}
    saved_font_size = editor_settings.get("font_size", 12)
    if not isinstance(saved_font_size, int):
        saved_font_size = 12
    font_size = {"value": max(9, min(24, saved_font_size))}
    body_font = tkfont.Font(family="Segoe UI", size=font_size["value"])
    body_bold_font = tkfont.Font(family="Segoe UI", size=font_size["value"], weight="bold")
    row_font = ctk.CTkFont(family="Segoe UI", size=11)
    suggestion_font = ctk.CTkFont(size=11)

    if not hasattr(app, "glossary_change_callbacks"):
        app.glossary_change_callbacks = []

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

    list_frame = ctk.CTkFrame(main_pane, corner_radius=8, width=400)
    main_pane.add(list_frame, minsize=320)
    list_frame.columnconfigure(0, weight=1)
    list_frame.rowconfigure(5, weight=1)

    header = ctk.CTkFrame(list_frame, fg_color="transparent")
    header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
    header.columnconfigure(1, weight=1)
    ctk.CTkLabel(header, text="Traduções", font=ctk.CTkFont(weight="bold")).grid(
        row=0, column=0, sticky="w"
    )
    page_label = ctk.CTkLabel(header, text="", anchor="e")
    page_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

    page_nav = ctk.CTkFrame(list_frame, fg_color="transparent")
    page_nav.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
    page_nav.columnconfigure(1, weight=1)
    btn_page_prev = ctk.CTkButton(page_nav, text="< Página", width=92)
    btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
    btn_page_next = ctk.CTkButton(page_nav, text="Página >", width=92)
    btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

    search_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
    search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
    search_bar.columnconfigure(0, weight=1)
    search_entry = ctk.CTkEntry(
        search_bar,
        textvariable=search_text,
        placeholder_text="Buscar no original ou tradução",
    )
    search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    btn_search = ctk.CTkButton(search_bar, text="Buscar", width=82)
    btn_search.grid(row=0, column=1, padx=(0, 6))
    btn_clear_search = ctk.CTkButton(search_bar, text="Limpar", width=74)
    btn_clear_search.grid(row=0, column=2)

    jump_bar = ctk.CTkFrame(list_frame, fg_color="transparent")
    jump_bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
    jump_bar.columnconfigure(1, weight=1)
    jump_bar.columnconfigure(4, weight=1)
    ctk.CTkLabel(jump_bar, text="Página").grid(row=0, column=0, sticky="w")
    page_entry = ctk.CTkEntry(jump_bar, textvariable=go_page_text, width=64)
    page_entry.grid(row=0, column=1, sticky="ew", padx=(6, 4))
    btn_go_page = ctk.CTkButton(jump_bar, text="Ir", width=46)
    btn_go_page.grid(row=0, column=2, padx=(0, 10))
    ctk.CTkLabel(jump_bar, text="ID").grid(row=0, column=3, sticky="w")
    id_entry = ctk.CTkEntry(jump_bar, textvariable=go_id_text, width=82)
    id_entry.grid(row=0, column=4, sticky="ew", padx=(6, 4))
    btn_go_id = ctk.CTkButton(jump_bar, text="Ir", width=46)
    btn_go_id.grid(row=0, column=5)

    status_segment = ctk.CTkSegmentedButton(
        list_frame,
        values=["Todas", "Pendentes", "Verificadas", "Avisos QA"],
    )
    saved_status = editor_settings.get("status_filter", "Todas")
    if saved_status not in {"Todas", "Pendentes", "Verificadas", "Avisos QA"}:
        saved_status = "Todas"
    status_segment.set(saved_status)
    status_segment.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))

    rows_frame = ctk.CTkScrollableFrame(list_frame, height=420)
    rows_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 10))

    bottom_pane = tk.PanedWindow(
        main_pane,
        orient=tk.HORIZONTAL,
        sashwidth=8,
        sashrelief=tk.FLAT,
        bd=0,
        bg=pane_bg,
    )
    main_pane.add(bottom_pane, minsize=620)

    text_frame = ctk.CTkFrame(bottom_pane, corner_radius=8)
    bottom_pane.add(text_frame, minsize=520)
    text_frame.columnconfigure(0, weight=1)
    text_frame.rowconfigure(1, weight=1, minsize=120)
    text_frame.rowconfigure(3, weight=3, minsize=180)

    text_bg = "#111827" if ctk.get_appearance_mode() == "Dark" else "#f9fafb"
    text_fg = "#e5e7eb" if ctk.get_appearance_mode() == "Dark" else "#111827"
    text_border = "#374151" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
    highlight_bg = "#7c5800" if ctk.get_appearance_mode() == "Dark" else "#fff3bf"
    highlight_fg = "#fef3c7" if ctk.get_appearance_mode() == "Dark" else "#111827"
    find_bg = "#334155" if ctk.get_appearance_mode() == "Dark" else "#fde68a"
    find_fg = "#f8fafc" if ctk.get_appearance_mode() == "Dark" else "#111827"
    current_find_bg = "#ea580c" if ctk.get_appearance_mode() == "Dark" else "#fb923c"

    def create_text_editor(parent, row, readonly=False, bottom_pad=8):
        container = tk.Frame(
            parent,
            bg=text_border,
            highlightthickness=1,
            highlightbackground=text_border,
        )
        container.grid(row=row, column=0, sticky="nsew", padx=10, pady=(0, bottom_pad))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        text = tk.Text(
            container,
            wrap=tk.WORD,
            undo=not readonly,
            relief=tk.FLAT,
            borderwidth=0,
            font=body_font,
            bg=text_bg,
            fg=text_fg,
            insertbackground=text_fg,
            selectbackground="#2563eb",
            selectforeground="#ffffff",
            padx=8,
            pady=6,
            height=6 if readonly else 12,
        )
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.tag_configure("bold", font=body_bold_font)
        text.tag_configure(
            "glossary_hit",
            background=highlight_bg,
            foreground=highlight_fg,
            font=body_bold_font,
        )
        text.tag_configure(
            "find_match",
            background=find_bg,
            foreground=find_fg,
        )
        text.tag_configure(
            "find_current",
            background=current_find_bg,
            foreground="#ffffff",
        )
        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    ctk.CTkLabel(text_frame, text="Original:").grid(
        row=0, column=0, sticky="w", padx=10, pady=(10, 2)
    )
    orig_text = create_text_editor(text_frame, 1, readonly=True)
    translation_header = ctk.CTkFrame(text_frame, fg_color="transparent")
    translation_header.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
    ctk.CTkLabel(translation_header, text="Tradução:").pack(side=tk.LEFT)
    font_controls = ctk.CTkFrame(translation_header, fg_color="transparent")
    font_controls.pack(side=tk.RIGHT)
    btn_font_down = ctk.CTkButton(font_controls, text="A-", width=42)
    btn_font_down.pack(side=tk.LEFT, padx=(0, 4))
    font_label = ctk.CTkLabel(font_controls, text=f"{font_size['value']} pt", width=46)
    font_label.pack(side=tk.LEFT)
    btn_font_up = ctk.CTkButton(font_controls, text="A+", width=42)
    btn_font_up.pack(side=tk.LEFT, padx=4)
    btn_bold = ctk.CTkButton(
        font_controls,
        text="B",
        width=42,
        font=ctk.CTkFont(weight="bold"),
    )
    btn_bold.pack(side=tk.LEFT, padx=(4, 0))
    trans_text = create_text_editor(text_frame, 3, bottom_pad=4)

    find_bar = ctk.CTkFrame(text_frame, fg_color="transparent")
    find_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 4))
    find_bar.columnconfigure(0, weight=1)
    find_bar.columnconfigure(1, weight=1)

    editor_find_entry = ctk.CTkEntry(
        find_bar,
        textvariable=editor_find_text,
        placeholder_text="Buscar",
        width=120,
    )
    editor_find_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    editor_replace_entry = ctk.CTkEntry(
        find_bar,
        textvariable=editor_replace_text,
        placeholder_text="Substituir",
        width=120,
    )
    editor_replace_entry.grid(row=0, column=1, sticky="ew", padx=4)
    find_buttons = ctk.CTkFrame(find_bar, fg_color="transparent")
    find_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
    btn_find_next = ctk.CTkButton(find_buttons, text="Prox.", width=58)
    btn_find_next.pack(side=tk.LEFT, padx=(0, 4))
    btn_replace_current = ctk.CTkButton(find_buttons, text="Trocar", width=68)
    btn_replace_current.pack(side=tk.LEFT, padx=4)
    btn_replace_all = ctk.CTkButton(find_buttons, text="Todos", width=62)
    btn_replace_all.pack(side=tk.LEFT, padx=4)
    case_check = ctk.CTkCheckBox(
        find_buttons,
        text="Aa",
        variable=editor_case_sensitive,
        width=46,
    )
    case_check.pack(side=tk.LEFT, padx=(4, 0))

    qa_label = ctk.CTkLabel(
        text_frame,
        text="",
        anchor="w",
        justify=tk.LEFT,
        text_color="#16a34a",
    )
    qa_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 2))
    history_label = ctk.CTkLabel(
        text_frame,
        text="",
        anchor="w",
        justify=tk.LEFT,
    )
    history_label.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))

    sugg_frame = ctk.CTkFrame(bottom_pane, corner_radius=8)
    bottom_pane.add(sugg_frame, minsize=300)
    sugg_frame.columnconfigure(0, weight=1)
    sugg_frame.columnconfigure(1, weight=1)
    sugg_frame.rowconfigure(1, weight=1)

    ctk.CTkLabel(sugg_frame, text="Sugestões do glossário:").grid(
        row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
    )

    suggestions_frame = ctk.CTkScrollableFrame(sugg_frame, height=160)
    suggestions_frame.grid(
        row=1,
        column=0,
        columnspan=2,
        sticky="nsew",
        padx=10,
        pady=(0, 8),
    )

    btn_refresh = ctk.CTkButton(sugg_frame, text="Recarregar sugestões")
    btn_apply_one = ctk.CTkButton(sugg_frame, text="Aplicar selecionada")
    btn_apply_all = ctk.CTkButton(sugg_frame, text="Aplicar todas")
    btn_add_gloss = ctk.CTkButton(sugg_frame, text="Adicionar ao glossário")
    btn_reload_gloss = ctk.CTkButton(sugg_frame, text="Atualizar glossário")
    btn_open_gloss = ctk.CTkButton(sugg_frame, text="Editar glossário")

    btn_refresh.grid(row=2, column=0, sticky="ew", padx=(10, 4), pady=4)
    btn_apply_one.grid(row=2, column=1, sticky="ew", padx=(4, 10), pady=4)
    btn_apply_all.grid(row=3, column=0, sticky="ew", padx=(10, 4), pady=4)
    btn_add_gloss.grid(row=3, column=1, sticky="ew", padx=(4, 10), pady=4)
    btn_reload_gloss.grid(row=4, column=0, sticky="ew", padx=(10, 4), pady=(0, 10))
    btn_open_gloss.grid(row=4, column=1, sticky="ew", padx=(4, 10), pady=(0, 10))

    status_frame = ctk.CTkFrame(win, corner_radius=8)
    status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
    status_frame.columnconfigure(0, weight=1)

    status_info = ctk.CTkFrame(status_frame, fg_color="transparent")
    status_info.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

    msg_label = ctk.CTkLabel(status_info, text="", text_color="#16a34a")
    msg_label.pack(side=tk.LEFT)

    dirty_label = ctk.CTkLabel(status_info, text="Salvo", text_color="#16a34a")
    dirty_label.pack(side=tk.LEFT, padx=(12, 0))

    draft_label = ctk.CTkLabel(status_info, text="", text_color="#64748b")
    draft_label.pack(side=tk.LEFT, padx=(12, 0))

    selection_label = ctk.CTkLabel(status_info, text="Item 0/0")
    selection_label.pack(side=tk.LEFT, padx=(12, 0))

    counts_label = ctk.CTkLabel(
        status_info,
        text="Todas: 0 · Pendentes: 0 · Verificadas: 0 · QA: 0",
    )
    counts_label.pack(side=tk.LEFT, padx=(12, 0))

    primary_actions = ctk.CTkFrame(status_frame, fg_color="transparent")
    primary_actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 4))
    secondary_actions = ctk.CTkFrame(status_frame, fg_color="transparent")
    secondary_actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

    btn_save_verify = ctk.CTkButton(
        primary_actions,
        text="Salvar e verificar",
        width=150,
    )
    btn_save_plain = ctk.CTkButton(primary_actions, text="Salvar", width=90)
    btn_mark = ctk.CTkButton(
        primary_actions,
        text="Marcar como verificada",
        width=170,
    )
    btn_pending = ctk.CTkButton(
        primary_actions,
        text="Marcar como pendente",
        width=165,
    )
    btn_prev = ctk.CTkButton(primary_actions, text="< Anterior", width=110)
    btn_next = ctk.CTkButton(primary_actions, text="Próxima >", width=110)

    for index, button in enumerate(
        [
            btn_save_verify,
            btn_save_plain,
            btn_mark,
            btn_pending,
            btn_prev,
            btn_next,
        ]
    ):
        button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
        primary_actions.columnconfigure(index, weight=1)

    btn_copy_original = ctk.CTkButton(
        secondary_actions,
        text="Copiar original",
        width=120,
    )
    btn_restore = ctk.CTkButton(secondary_actions, text="Restaurar", width=90)
    btn_undo = ctk.CTkButton(secondary_actions, text="Desfazer", width=86)
    btn_redo = ctk.CTkButton(secondary_actions, text="Refazer", width=78)
    btn_next_qa = ctk.CTkButton(
        secondary_actions,
        text="Próximo aviso QA",
        width=150,
    )
    btn_export_qa = ctk.CTkButton(secondary_actions, text="Exportar QA", width=110)
    btn_apply_auto = ctk.CTkButton(
        secondary_actions,
        text="Aplicar automaticas",
        width=150,
    )
    btn_history = ctk.CTkButton(secondary_actions, text="Hist\u00f3rico", width=100)

    for index, button in enumerate(
        [
            btn_copy_original,
            btn_restore,
            btn_undo,
            btn_redo,
            btn_next_qa,
            btn_export_qa,
            btn_apply_auto,
            btn_history,
        ]
    ):
        button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
        secondary_actions.columnconfigure(index, weight=1)

    def show_message(text):
        msg_label.configure(text=text)
        win.after(1500, lambda: msg_label.configure(text=""))

    def save_editor_settings():
        editor = settings.setdefault("editor", {})
        if not isinstance(editor, dict):
            editor = {}
            settings["editor"] = editor

        editor["font_size"] = font_size["value"]
        editor["status_filter"] = status_segment.get()
        editor["geometry"] = win.geometry()

        try:
            editor["main_sash_y"] = main_pane.sash_coord(0)[0]
        except tk.TclError:
            pass

        try:
            editor["bottom_sash_x"] = bottom_pane.sash_coord(0)[0]
        except tk.TclError:
            pass

        try:
            save_settings(settings)
        except OSError:
            pass

    def restore_pane_positions():
        main_sash_y = editor_settings.get("main_sash_y")
        bottom_sash_x = editor_settings.get("bottom_sash_x")

        try:
            if isinstance(main_sash_y, int) and main_sash_y > 0:
                sidebar_width = max(360, min(520, main_sash_y))
                main_pane.sash_place(0, sidebar_width, 0)
        except tk.TclError:
            pass

        try:
            if isinstance(bottom_sash_x, int) and bottom_sash_x > 0:
                editor_width = max(520, bottom_sash_x)
                bottom_pane.sash_place(0, editor_width, 0)
        except tk.TclError:
            pass

    def cancel_draft_save():
        if draft_save_after["value"] is None:
            return
        try:
            win.after_cancel(draft_save_after["value"])
        except tk.TclError:
            pass
        draft_save_after["value"] = None

    def draft_text():
        return trans_text.get("1.0", tk.END).rstrip("\n")

    def clear_current_draft(persist=True):
        if not current["id"]:
            draft_label.configure(text="")
            return

        changed = clear_editor_draft(
            settings,
            app.output_db,
            lang,
            current["id"],
        )
        if changed and persist:
            try:
                save_settings(settings)
            except OSError:
                draft_label.configure(
                    text="Falha ao limpar rascunho",
                    text_color="#dc2626",
                )
                return
        draft_label.configure(text="", text_color="#64748b")

    def persist_current_draft():
        draft_save_after["value"] = None
        if not current["id"]:
            draft_label.configure(text="")
            return

        text = draft_text()
        try:
            if text == current["saved_trans"]:
                clear_current_draft(persist=False)
            else:
                set_editor_draft(
                    settings,
                    app.output_db,
                    lang,
                    current["id"],
                    text,
                    current["saved_trans"],
                )
                draft_label.configure(
                    text=f"Rascunho salvo {datetime.now().strftime('%H:%M:%S')}",
                    text_color="#64748b",
                )
            save_settings(settings)
        except OSError:
            draft_label.configure(
                text="Falha ao salvar rascunho",
                text_color="#dc2626",
            )

    def schedule_draft_save():
        if dirty["loading"] or not current["id"]:
            return
        cancel_draft_save()
        draft_label.configure(text="Salvando rascunho...", text_color="#64748b")
        draft_save_after["value"] = win.after(700, persist_current_draft)

    def set_dirty(value, autosave_draft=True):
        dirty["value"] = value
        if value:
            dirty_label.configure(text="Alterações não salvas", text_color="#f59e0b")
            if autosave_draft:
                schedule_draft_save()
        else:
            cancel_draft_save()
            dirty_label.configure(text="Salvo", text_color="#16a34a")

    def update_counts_label():
        counts_label.configure(
            text=(
                f"Todas: {status_counts['total']} · "
                f"Pendentes: {status_counts['pending']} · "
                f"Verificadas: {status_counts['verified']} · "
                f"QA: {status_counts['qa']}"
            )
        )

    def update_selection_label():
        index = get_index()
        if index is None or not rows:
            selection_label.configure(text=f"Item 0/{total_rows['value']}")
            return

        absolute_index = page_index["value"] * PAGE_SIZE + index + 1
        selection_label.configure(text=f"Item {absolute_index}/{total_rows['value']}")

    def update_quality_warnings():
        warnings = evaluate_translation_quality(
            current["orig"],
            trans_text.get("1.0", tk.END),
        )
        if warnings:
            qa_label.configure(
                text="QA: " + " | ".join(warnings),
                text_color="#f59e0b",
            )
        elif current["id"]:
            qa_label.configure(text="QA: sem avisos", text_color="#16a34a")
        else:
            qa_label.configure(text="", text_color="#16a34a")

    def format_timestamp(value):
        if not value:
            return "-"
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        except ValueError:
            return value

    def update_history_label():
        if not current["id"]:
            history_label.configure(text="")
            return

        history_label.configure(
            text=(
                f"Criada: {format_timestamp(current['created_at'])} | "
                f"Editada: {format_timestamp(current['updated_at'])} | "
                f"Verificada: {format_timestamp(current['verified_at'])}"
            )
        )

    def set_current_history(row):
        current["created_at"] = row[2] or "" if len(row) > 2 else ""
        current["updated_at"] = row[3] or "" if len(row) > 3 else ""
        current["verified_at"] = row[4] or "" if len(row) > 4 else ""
        update_history_label()

    def text_index_for_offset(offset):
        return f"1.0+{max(0, int(offset))}c"

    def clear_find_highlights():
        trans_text.tag_remove("find_match", "1.0", tk.END)
        trans_text.tag_remove("find_current", "1.0", tk.END)
        current_find_match["value"] = None

    def editor_find_ranges():
        return find_text_ranges(
            draft_text(),
            editor_find_text.get(),
            case_sensitive=editor_case_sensitive.get(),
        )

    def highlight_find_ranges(ranges, current_range=None):
        trans_text.tag_remove("find_match", "1.0", tk.END)
        trans_text.tag_remove("find_current", "1.0", tk.END)

        for start, end in ranges:
            trans_text.tag_add(
                "find_match",
                text_index_for_offset(start),
                text_index_for_offset(end),
            )

        if current_range is not None:
            start, end = current_range
            trans_text.tag_add(
                "find_current",
                text_index_for_offset(start),
                text_index_for_offset(end),
            )
            trans_text.tag_raise("find_current")

    def refresh_find_matches(keep_current=True):
        if not editor_find_text.get():
            clear_find_highlights()
            return []

        ranges = editor_find_ranges()
        current_range = None
        if keep_current and current_find_match["value"] in ranges:
            current_range = current_find_match["value"]
        current_find_match["value"] = current_range
        highlight_find_ranges(ranges, current_range)
        return ranges

    def select_find_match(ranges, index):
        if not ranges:
            clear_find_highlights()
            return

        index = index % len(ranges)
        current_range = ranges[index]
        current_find_match["value"] = current_range
        highlight_find_ranges(ranges, current_range)

        start, end = current_range
        start_index = text_index_for_offset(start)
        end_index = text_index_for_offset(end)
        trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        trans_text.tag_add(tk.SEL, start_index, end_index)
        trans_text.mark_set(tk.INSERT, end_index)
        trans_text.see(start_index)
        trans_text.focus_set()
        show_message(f"Ocorrencia {index + 1}/{len(ranges)}")

    def find_next_in_translation(_event=None):
        if not editor_find_text.get():
            editor_find_entry.focus_set()
            show_message("Digite o texto da busca")
            return "break"

        ranges = refresh_find_matches()
        if not ranges:
            show_message("Nenhuma ocorrencia encontrada")
            return "break"

        if current_find_match["value"] in ranges:
            offset = current_find_match["value"][1]
        else:
            try:
                offset = len(trans_text.get("1.0", tk.INSERT))
            except tk.TclError:
                offset = 0

        for index, (start, _end) in enumerate(ranges):
            if start >= offset:
                select_find_match(ranges, index)
                return "break"

        select_find_match(ranges, 0)
        return "break"

    def replace_current_in_translation(_event=None):
        if not current["id"]:
            return "break"
        if not editor_find_text.get():
            editor_find_entry.focus_set()
            show_message("Digite o texto da busca")
            return "break"

        ranges = refresh_find_matches()
        if not ranges:
            show_message("Nenhuma ocorrencia para substituir")
            return "break"

        match = current_find_match["value"]
        if match not in ranges:
            match = ranges[0]
        start, end = match
        replacement = editor_replace_text.get()
        trans_text.delete(text_index_for_offset(start), text_index_for_offset(end))
        trans_text.insert(text_index_for_offset(start), replacement)
        set_dirty(True)
        refresh_suggestions()
        update_quality_warnings()

        next_offset = start + len(replacement)
        ranges = refresh_find_matches(keep_current=False)
        if ranges:
            for index, (match_start, _match_end) in enumerate(ranges):
                if match_start >= next_offset:
                    select_find_match(ranges, index)
                    break
            else:
                select_find_match(ranges, 0)

        show_message("Ocorrencia substituida")
        return "break"

    def replace_all_in_translation():
        if not current["id"]:
            return
        if not editor_find_text.get():
            editor_find_entry.focus_set()
            show_message("Digite o texto da busca")
            return

        new_text, count = replace_all_text(
            draft_text(),
            editor_find_text.get(),
            editor_replace_text.get(),
            case_sensitive=editor_case_sensitive.get(),
        )
        if count == 0:
            show_message("Nenhuma ocorrencia para substituir")
            return

        set_translation_text(new_text, mark_dirty=True)
        refresh_find_matches(keep_current=False)
        show_message(f"{count} ocorrencia(s) substituida(s)")

    def set_translation_text(
        text,
        mark_dirty=False,
        autosave_draft=True,
        insert_offset=None,
        focus_editor=False,
    ):
        dirty["loading"] = True
        trans_text.delete("1.0", tk.END)
        trans_text.insert("1.0", text or "")
        try:
            trans_text.edit_reset()
            trans_text.edit_modified(False)
        except tk.TclError:
            pass
        dirty["loading"] = False
        set_dirty(mark_dirty, autosave_draft=autosave_draft)
        refresh_suggestions()
        update_quality_warnings()
        refresh_find_matches(keep_current=False)
        if insert_offset is not None:
            insert_index = text_index_for_offset(insert_offset)
            trans_text.mark_set(tk.INSERT, insert_index)
            trans_text.see(insert_index)
            trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        if focus_editor:
            trans_text.focus_set()

    def on_translation_modified(_event=None):
        try:
            modified = trans_text.edit_modified()
            trans_text.edit_modified(False)
        except tk.TclError:
            return
        if modified and not dirty["loading"]:
            set_dirty(True)
            update_quality_warnings()
            refresh_find_matches()

    def apply_font_size():
        size = font_size["value"]
        body_font.configure(size=size)
        body_bold_font.configure(size=size, weight="bold")
        row_font.configure(size=max(10, size - 1))
        suggestion_font.configure(size=max(10, size - 1))
        font_label.configure(text=f"{size} pt")
        for text in (orig_text, trans_text):
            text.tag_configure("bold", font=body_bold_font)
            text.tag_configure("glossary_hit", font=body_bold_font)

    def adjust_font(delta):
        font_size["value"] = max(9, min(24, font_size["value"] + delta))
        apply_font_size()
        save_editor_settings()

    def toggle_bold_selection():
        try:
            start = trans_text.index(tk.SEL_FIRST)
            end = trans_text.index(tk.SEL_LAST)
        except tk.TclError:
            show_message("Selecione um trecho da tradução")
            return

        if "bold" in trans_text.tag_names(start):
            trans_text.tag_remove("bold", start, end)
        else:
            trans_text.tag_add("bold", start, end)

    def highlight_glossary_hits():
        trans_text.tag_remove("glossary_hit", "1.0", tk.END)
        for orig, _new in current_suggestions:
            text = trans_text.get("1.0", tk.END)
            for start, end in find_glossary_matches(text, orig):
                trans_text.tag_add(
                    "glossary_hit",
                    text_index_for_offset(start),
                    text_index_for_offset(end),
                )

    def clear_current():
        orig_text.configure(state="normal")
        orig_text.delete("1.0", tk.END)
        orig_text.configure(state="disabled")
        trans_text.delete("1.0", tk.END)
        current["id"] = None
        current["orig"] = ""
        current["trans"] = ""
        current["saved_trans"] = ""
        current["created_at"] = ""
        current["updated_at"] = ""
        current["verified_at"] = ""
        try:
            trans_text.edit_reset()
            trans_text.edit_modified(False)
        except tk.TclError:
            pass
        set_dirty(False)
        clear_find_highlights()
        draft_label.configure(text="")
        refresh_suggestions()
        update_selection_label()
        update_quality_warnings()
        update_history_label()

    def page_count():
        if total_rows["value"] == 0:
            return 0
        return (total_rows["value"] + PAGE_SIZE - 1) // PAGE_SIZE

    def selected_status_filter():
        value = status_segment.get()
        if value == "Pendentes":
            return "pending"
        if value == "Verificadas":
            return "verified"
        return "all"

    def qa_filter_active():
        return status_segment.get() == "Avisos QA"

    def fetch_quality_warning_rows(cur):
        review_rows = fetch_review_rows(
            cur,
            lang,
            search_text=active_search["value"],
            status_filter="all",
        )
        return filter_quality_warning_rows(review_rows)

    def update_page_controls():
        pages = page_count()
        current_page = page_index["value"] + 1 if pages else 0
        search_suffix = " · busca ativa" if active_search["value"] else ""
        status_suffix = f" · {status_segment.get().lower()}"
        page_label.configure(
            text=(
                f"Página {current_page}/{pages} · "
                f"{total_rows['value']} traduções{status_suffix}{search_suffix}"
            )
        )
        btn_page_prev.configure(
            state="normal" if page_index["value"] > 0 else "disabled"
        )
        btn_page_next.configure(
            state="normal" if page_index["value"] + 1 < pages else "disabled"
        )

    def render_rows():
        for child in rows_frame.winfo_children():
            child.destroy()
        row_buttons.clear()
        selected_index["value"] = None
        update_page_controls()
        update_counts_label()
        update_selection_label()

        if not rows:
            if qa_filter_active():
                empty_text = "Nenhum aviso QA encontrado."
            else:
                empty_text = (
                    "Nenhuma tradução encontrada para a busca."
                    if active_search["value"]
                    else "Nenhuma tradução encontrada."
                )
            ctk.CTkLabel(rows_frame, text=empty_text).pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, row in enumerate(rows):
            btn = ctk.CTkButton(
                rows_frame,
                text=row_label(row),
                anchor="w",
                height=64,
                fg_color=row_color(row),
                text_color=row_text_color(row),
                hover_color=ROW_HOVER_COLOR,
                font=row_font,
                command=lambda i=index: select_index(i, save_previous=True),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            row_buttons.append(btn)

    def reload_rows():
        nonlocal rows
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            status_counts.update(
                get_review_status_counts(
                    cur,
                    lang,
                    active_search["value"],
                )
            )
            qa_rows = fetch_quality_warning_rows(cur)
            status_counts["qa"] = len(qa_rows)
            if qa_filter_active():
                total_rows["value"] = len(qa_rows)
            else:
                total_rows["value"] = count_review_rows(
                    cur,
                    lang,
                    search_text=active_search["value"],
                    status_filter=selected_status_filter(),
                )
            pages = page_count()
            if pages == 0:
                page_index["value"] = 0
            else:
                page_index["value"] = min(page_index["value"], pages - 1)

            offset = page_index["value"] * PAGE_SIZE
            if qa_filter_active():
                rows = qa_rows[offset:offset + PAGE_SIZE]
            else:
                rows = list(
                    fetch_review_rows_page(
                        cur,
                        lang,
                        limit=PAGE_SIZE,
                        offset=offset,
                        search_text=active_search["value"],
                        status_filter=selected_status_filter(),
                    )
                )
        render_rows()

    def get_index():
        return selected_index["value"]

    def update_row_selection(new_index):
        old_index = selected_index["value"]
        if old_index is not None and 0 <= old_index < len(row_buttons):
            row_buttons[old_index].configure(
                fg_color=row_color(rows[old_index]),
                text_color=row_text_color(rows[old_index]),
            )

        selected_index["value"] = new_index
        if new_index is not None and 0 <= new_index < len(row_buttons):
            row_buttons[new_index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        update_selection_label()

    def select_index(index, save_previous=False):
        if not rows:
            return
        if save_previous and current["id"]:
            save_changes()
        index = max(0, min(index, len(rows) - 1))
        update_row_selection(index)
        load_item()

    def load_item():
        index = get_index()
        if index is None or not (0 <= index < len(rows)):
            return

        comment_id = rows[index][0]
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            row = fetch_translation_by_id(cur, comment_id)

        if row is None:
            return

        orig, trans = row[0], row[1]
        current["id"] = comment_id
        current["orig"] = orig or ""
        current["trans"] = trans or ""
        current["saved_trans"] = current["trans"]
        set_current_history(row)

        orig_text.configure(state="normal")
        orig_text.delete("1.0", tk.END)
        orig_text.insert("1.0", current["orig"])
        orig_text.configure(state="disabled")

        draft = get_editor_draft(
            settings,
            app.output_db,
            lang,
            comment_id,
            current["trans"],
        )
        if draft is None:
            set_translation_text(current["trans"], mark_dirty=False)
        else:
            set_translation_text(
                draft["text"],
                mark_dirty=True,
                autosave_draft=False,
            )
            draft_label.configure(
                text=f"Rascunho restaurado {format_timestamp(draft['updated_at'])}",
                text_color="#64748b",
            )
            show_message("Rascunho restaurado")

    def update_current_row_cache(verified=None):
        index = get_index()
        if index is None or not (0 <= index < len(rows)):
            return

        if verified is None:
            verified = rows[index][3] if len(rows[index]) > 3 else 0

        rows[index] = (
            current["id"],
            current["orig"],
            current["trans"],
            verified,
            current["created_at"],
            current["updated_at"],
            current["verified_at"],
        )
        row_buttons[index].configure(text=row_label(rows[index]))
        if selected_index["value"] == index:
            row_buttons[index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        else:
            row_buttons[index].configure(
                fg_color=row_color(rows[index]),
                text_color=row_text_color(rows[index]),
            )

    def save_changes(silent=True, mark_verified=False):
        if not current["id"]:
            return

        new_trans = trans_text.get("1.0", tk.END).rstrip("\n")

        updated_row = None
        propagated_rows = 0
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            update_translation_by_id(cur, current["id"], new_trans, mark_verified)
            if mark_verified:
                propagated_rows = set_exact_translation_matches_verified(cur, current["id"])
            updated_row = fetch_translation_by_id(cur, current["id"])
            conn.commit()

        current["trans"] = new_trans
        current["saved_trans"] = new_trans
        clear_current_draft()
        if updated_row is not None:
            set_current_history(updated_row)
        try:
            trans_text.edit_modified(False)
        except tk.TclError:
            pass
        set_dirty(False)
        if mark_verified and propagated_rows:
            idx = get_index()
            reload_rows()
            if rows:
                next_index = 0 if idx is None else min(idx, len(rows) - 1)
                for row_index, row in enumerate(rows):
                    if row[0] == current["id"]:
                        next_index = row_index
                        break
                select_index(next_index)
            else:
                clear_current()
            if not silent:
                show_message(
                    f"Tradução salva e verificada; {propagated_rows} iguais também verificadas"
                )
            return

        index = get_index()
        old_warning = False
        new_warning = False
        if index is not None and 0 <= index < len(rows):
            old_verified = rows[index][3] if len(rows[index]) > 3 else 0
            old_warning = row_has_quality_warning(rows[index])
            verified = 1 if mark_verified else old_verified
            update_current_row_cache(verified)
            new_warning = row_has_quality_warning(rows[index])
            if old_warning != new_warning:
                if new_warning:
                    status_counts["qa"] += 1
                else:
                    status_counts["qa"] = max(0, status_counts["qa"] - 1)
                update_counts_label()
            if mark_verified and old_verified != 1:
                status_counts["pending"] = max(0, status_counts["pending"] - 1)
                status_counts["verified"] += 1
                update_counts_label()

        if qa_filter_active() and old_warning and not new_warning:
            idx = get_index()
            reload_rows()
            if rows:
                select_index(0 if idx is None else min(idx, len(rows) - 1))
            else:
                clear_current()

        if mark_verified and selected_status_filter() == "pending":
            idx = get_index()
            reload_rows()
            if rows:
                select_index(0 if idx is None else min(idx, len(rows) - 1))
            else:
                clear_current()

        if not silent:
            if mark_verified:
                show_message("Tradução salva e verificada")
            else:
                show_message("Tradução salva")

    def navigate(delta):
        save_changes()
        index = get_index()
        if index is None:
            index = 0

        new_index = index + delta
        if 0 <= new_index < len(rows):
            select_index(new_index)
        elif new_index < 0 and page_index["value"] > 0:
            page_index["value"] -= 1
            reload_rows()
            if rows:
                select_index(len(rows) - 1)
        elif new_index >= len(rows) and page_index["value"] + 1 < page_count():
            page_index["value"] += 1
            reload_rows()
            if rows:
                select_index(0)
        else:
            show_message("Fim da lista")

    def change_page(delta):
        save_changes()
        new_page = page_index["value"] + delta
        if 0 <= new_page < page_count():
            page_index["value"] = new_page
            reload_rows()
            if rows:
                select_index(0)

    def go_to_page():
        save_changes()
        try:
            target_page = int(go_page_text.get().strip())
        except ValueError:
            show_message("Página inválida")
            return

        pages = page_count()
        if not (1 <= target_page <= pages):
            show_message("Página fora do intervalo")
            return

        page_index["value"] = target_page - 1
        reload_rows()
        if rows:
            select_index(0)

    def go_to_id():
        save_changes()
        try:
            target_id = int(go_id_text.get().strip())
        except ValueError:
            show_message("ID inválido")
            return

        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            if qa_filter_active():
                offset = None
                for index, row in enumerate(fetch_quality_warning_rows(cur)):
                    if row[0] == target_id:
                        offset = index
                        break
            else:
                offset = get_review_row_offset(
                    cur,
                    lang,
                    target_id,
                    search_text=active_search["value"],
                    status_filter=selected_status_filter(),
                )

        if offset is None:
            show_message("ID não encontrado nos filtros atuais")
            return

        page_index["value"] = offset // PAGE_SIZE
        target_index = offset % PAGE_SIZE
        reload_rows()
        if rows:
            select_index(target_index)

    def find_quality_warning_offset(start_offset, stop_offset):
        if start_offset >= stop_offset:
            return None

        offset = start_offset
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            while offset < stop_offset:
                page_start = (offset // PAGE_SIZE) * PAGE_SIZE
                local_start = offset - page_start
                page_rows = list(
                    fetch_review_rows_page(
                        cur,
                        lang,
                        limit=PAGE_SIZE,
                        offset=page_start,
                        search_text=active_search["value"],
                        status_filter=selected_status_filter(),
                    )
                )
                if not page_rows:
                    break

                page_limit = stop_offset - page_start
                if page_limit < len(page_rows):
                    page_rows = page_rows[:page_limit]

                found = find_first_quality_warning(page_rows, local_start)
                if found is not None:
                    found_index, _row, warnings = found
                    return page_start + found_index, warnings

                offset = page_start + len(page_rows)

        return None

    def go_to_next_quality_warning():
        save_changes()
        total = total_rows["value"]
        if total == 0:
            show_message("Nenhum item nos filtros atuais")
            return

        index = get_index()
        if index is None:
            start_offset = page_index["value"] * PAGE_SIZE
        else:
            start_offset = page_index["value"] * PAGE_SIZE + index + 1

        if start_offset >= total:
            start_offset = 0

        if qa_filter_active():
            target_offset = start_offset
            page_index["value"] = target_offset // PAGE_SIZE
            reload_rows()
            if rows:
                local_index = target_offset % PAGE_SIZE
                select_index(local_index)
                warnings = evaluate_translation_quality(
                    rows[local_index][1],
                    rows[local_index][2],
                )
                if warnings:
                    show_message("Aviso QA: " + warnings[0])
            return

        found = find_quality_warning_offset(start_offset, total)
        if found is None and start_offset > 0:
            found = find_quality_warning_offset(0, start_offset)

        if found is None:
            show_message("Nenhum aviso QA nos filtros atuais")
            return

        target_offset, warnings = found
        page_index["value"] = target_offset // PAGE_SIZE
        reload_rows()
        if rows:
            select_index(target_offset % PAGE_SIZE)
        show_message("Aviso QA: " + warnings[0])

    def export_quality_report():
        save_changes()
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            report_rows = build_quality_report_rows(
                fetch_quality_warning_rows(cur),
                lang,
            )

        if not report_rows:
            show_message("Nenhum aviso QA para exportar")
            return

        save_path = filedialog.asksaveasfilename(
            title="Salvar relatorio QA",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return

        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(QUALITY_REPORT_HEADERS)
                writer.writerows(report_rows)
        except OSError as exc:
            messagebox.showerror("Erro", f"Erro ao exportar relatorio QA:\n{exc}")
            return

        messagebox.showinfo(
            "Exportar QA",
            f"Relatorio QA exportado com {len(report_rows)} avisos:\n{save_path}",
        )

    def mark_and_next():
        if not current["id"]:
            return

        index = get_index()
        save_changes(mark_verified=True)

        if selected_status_filter() == "pending":
            show_message("Marcada como verificada" if current["id"] else "Sem traduções pendentes")
            return

        if index is None:
            index = 0
        new_index = index + 1

        if 0 <= new_index < len(rows):
            select_index(new_index)
        elif new_index >= len(rows) and page_index["value"] + 1 < page_count():
            page_index["value"] += 1
            reload_rows()
            if rows:
                select_index(0)
        else:
            show_message("Fim da lista")
            return

        show_message("Marcada como verificada")

    def mark_pending():
        if not current["id"]:
            return

        save_changes()
        updated_row = None
        with closing(initialize_database(app.output_db)) as conn:
            cur = conn.cursor()
            set_translation_verified_by_id(cur, current["id"], False)
            updated_row = fetch_translation_by_id(cur, current["id"])
            conn.commit()
        if updated_row is not None:
            set_current_history(updated_row)

        index = get_index()
        if selected_status_filter() == "verified":
            reload_rows()
            if rows:
                select_index(0 if index is None else min(index, len(rows) - 1))
            else:
                clear_current()
        elif index is not None and 0 <= index < len(rows):
            old_verified = rows[index][3] if len(rows[index]) > 3 else 0
            update_current_row_cache(0)
            if old_verified == 1:
                status_counts["verified"] = max(0, status_counts["verified"] - 1)
                status_counts["pending"] += 1
                update_counts_label()

        show_message("Marcada como pendente")

    def history_action_label(action):
        labels = {
            "edit": "Edicao",
            "edit_verify": "Edicao + verificacao",
            "verify": "Verificacao",
            "verify_exact_match": "Verificacao por traducao igual",
            "automatic_rules": "Regras automaticas",
            "mark_pending": "Voltou para pendente",
            "fill_empty": "Preenchimento inicial",
            "restore": "Restauracao",
            "status": "Status",
        }
        return labels.get(action or "", action or "Alteracao")

    def history_status_label(value):
        return "verificada" if value == 1 else "pendente"

    def open_history_window():
        if not current["id"]:
            show_message("Selecione uma traducao")
            return

        save_changes()

        history_win = ctk.CTkToplevel(win)
        history_win.title(f"Historico da traducao {current['id']}")
        history_win.geometry("980x560")
        history_win.minsize(820, 430)
        bring_window_to_front(history_win, win, maximize=True)
        history_win.columnconfigure(1, weight=1)
        history_win.rowconfigure(1, weight=1)

        title = (
            f"ID {current['id']} | "
            f"{preview(current['orig'], 120)}"
        )
        ctk.CTkLabel(
            history_win,
            text=title,
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))

        history_list = ctk.CTkScrollableFrame(history_win, width=300)
        history_list.grid(row=1, column=0, sticky="nsw", padx=(10, 6), pady=(0, 10))

        detail_frame = ctk.CTkFrame(history_win, corner_radius=8)
        detail_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 10), pady=(0, 10))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.rowconfigure(2, weight=1)

        metadata_label = ctk.CTkLabel(detail_frame, text="", anchor="w")
        metadata_label.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(10, 6),
        )

        ctk.CTkLabel(detail_frame, text="Anterior").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 2)
        )
        ctk.CTkLabel(detail_frame, text="Nova").grid(
            row=1, column=1, sticky="w", padx=10, pady=(0, 2)
        )

        previous_text = ctk.CTkTextbox(detail_frame, wrap=tk.WORD)
        new_text = ctk.CTkTextbox(detail_frame, wrap=tk.WORD)
        previous_text.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        new_text.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))

        actions = ctk.CTkFrame(detail_frame, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))
        btn_restore_previous = ctk.CTkButton(
            actions,
            text="Restaurar anterior",
            width=150,
        )
        btn_restore_new = ctk.CTkButton(
            actions,
            text="Restaurar nova",
            width=130,
        )
        btn_close_history = ctk.CTkButton(
            actions,
            text="Fechar",
            width=90,
            command=history_win.destroy,
        )
        btn_close_history.pack(side=tk.RIGHT, padx=(6, 0))
        btn_restore_new.pack(side=tk.RIGHT, padx=6)
        btn_restore_previous.pack(side=tk.RIGHT, padx=6)

        history_rows = []
        history_buttons = []
        selected_history = {"value": None}

        def set_history_text(widget, value):
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert("1.0", value or "")
            widget.configure(state="disabled")

        def set_restore_buttons(enabled):
            state = "normal" if enabled else "disabled"
            btn_restore_previous.configure(state=state)
            btn_restore_new.configure(state=state)

        def selected_history_row():
            index = selected_history["value"]
            if index is None or not (0 <= index < len(history_rows)):
                return None
            return history_rows[index]

        def restore_history_translation(text):
            if text is None:
                text = ""

            with closing(initialize_database(app.output_db)) as conn:
                cur = conn.cursor()
                changed = update_translation_by_id(
                    cur,
                    current["id"],
                    text,
                    history_action="restore",
                )
                updated_row = fetch_translation_by_id(cur, current["id"])
                conn.commit()

            current["trans"] = text
            current["saved_trans"] = text
            clear_current_draft()
            if updated_row is not None:
                set_current_history(updated_row)
            set_translation_text(text, mark_dirty=False)
            update_current_row_cache()
            refresh_history()
            if changed:
                show_message("Versao restaurada")
            else:
                show_message("Versao ja estava aplicada")

        def select_history(index):
            old = selected_history["value"]
            if old is not None and 0 <= old < len(history_buttons):
                history_buttons[old].configure(
                    fg_color=ROW_COLOR,
                    text_color=ROW_TEXT_COLOR,
                )

            selected_history["value"] = index
            if 0 <= index < len(history_buttons):
                history_buttons[index].configure(
                    fg_color=SELECTED_ROW_COLOR,
                    text_color=SELECTED_ROW_TEXT_COLOR,
                )

            row = selected_history_row()
            if row is None:
                metadata_label.configure(text="")
                set_history_text(previous_text, "")
                set_history_text(new_text, "")
                set_restore_buttons(False)
                return

            (
                _history_id,
                action,
                previous_translation,
                new_translation,
                previous_verified,
                new_verified,
                created_at,
            ) = row
            metadata_label.configure(
                text=(
                    f"{format_timestamp(created_at)} | "
                    f"{history_action_label(action)} | "
                    f"{history_status_label(previous_verified)} -> "
                    f"{history_status_label(new_verified)}"
                )
            )
            set_history_text(previous_text, previous_translation)
            set_history_text(new_text, new_translation)
            set_restore_buttons(True)

        def refresh_history():
            nonlocal history_rows
            for child in history_list.winfo_children():
                child.destroy()
            history_buttons.clear()
            selected_history["value"] = None

            with closing(initialize_database(app.output_db)) as conn:
                cur = conn.cursor()
                history_rows = list(fetch_comment_history(cur, current["id"], limit=100))

            if not history_rows:
                ctk.CTkLabel(
                    history_list,
                    text="Nenhuma alteracao registrada.",
                    anchor="w",
                ).pack(anchor="w", padx=6, pady=6)
                metadata_label.configure(text="")
                set_history_text(previous_text, "")
                set_history_text(new_text, "")
                set_restore_buttons(False)
                return

            for index, row in enumerate(history_rows):
                _history_id, action, _prev, _new, previous_verified, new_verified, created_at = row
                label = (
                    f"{format_timestamp(created_at)}\n"
                    f"{history_action_label(action)} | "
                    f"{history_status_label(previous_verified)} -> "
                    f"{history_status_label(new_verified)}"
                )
                btn = ctk.CTkButton(
                    history_list,
                    text=label,
                    anchor="w",
                    fg_color=ROW_COLOR,
                    text_color=ROW_TEXT_COLOR,
                    hover_color=ROW_HOVER_COLOR,
                    command=lambda i=index: select_history(i),
                )
                btn.pack(fill=tk.X, padx=2, pady=2)
                history_buttons.append(btn)

            select_history(0)

        btn_restore_previous.configure(
            command=lambda: (
                restore_history_translation(selected_history_row()[2])
                if selected_history_row() is not None
                else None
            )
        )
        btn_restore_new.configure(
            command=lambda: (
                restore_history_translation(selected_history_row()[3])
                if selected_history_row() is not None
                else None
            )
        )

        refresh_history()

    def undo_translation():
        try:
            trans_text.edit_undo()
        except tk.TclError:
            show_message("Nada para desfazer")
            return
        set_dirty(True)
        refresh_suggestions()
        update_quality_warnings()
        refresh_find_matches()

    def redo_translation():
        try:
            trans_text.edit_redo()
        except tk.TclError:
            show_message("Nada para refazer")
            return
        set_dirty(True)
        refresh_suggestions()
        update_quality_warnings()
        refresh_find_matches()

    def restore_saved_translation():
        if not current["id"]:
            return
        set_translation_text(current["saved_trans"], mark_dirty=False)
        current["trans"] = current["saved_trans"]
        clear_current_draft()
        show_message("Tradução restaurada")

    def copy_original_to_translation():
        if not current["id"]:
            return
        set_translation_text(current["orig"], mark_dirty=True)
        show_message("Original copiado para tradução")

    def toggle_filter():
        page_index["value"] = 0
        save_editor_settings()
        reload_rows()
        if rows:
            select_index(0)
        else:
            clear_current()

    def apply_search():
        save_changes()
        active_search["value"] = search_text.get().strip()
        page_index["value"] = 0
        reload_rows()
        if rows:
            select_index(0)
        else:
            clear_current()

    def clear_search():
        if not active_search["value"] and not search_text.get():
            return
        search_text.set("")
        active_search["value"] = ""
        page_index["value"] = 0
        reload_rows()
        if rows:
            select_index(0)
        else:
            clear_current()

    def apply_automatic_rules_for_current_language():
        save_changes()
        previous_id = current["id"]
        stats = apply_automatic_rules_to_database(
            app,
            target_language=lang,
            parent=win,
        )
        if not stats or stats.get("changed", 0) == 0:
            return

        reload_rows()
        if not rows:
            clear_current()
            return

        next_index = 0
        if previous_id is not None:
            for row_index, row in enumerate(rows):
                if row[0] == previous_id:
                    next_index = row_index
                    break
        select_index(next_index)
        show_message(f"{stats['changed']} traducao(oes) atualizada(s)")

    def select_suggestion(index):
        old = selected_suggestion["value"]
        if old is not None and 0 <= old < len(suggestion_buttons):
            suggestion_buttons[old].configure(
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
            )

        selected_suggestion["value"] = index
        if 0 <= index < len(suggestion_buttons):
            suggestion_buttons[index].configure(
                fg_color=SUGGESTION_SELECTED_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )

    def refresh_suggestions():
        nonlocal current_suggestions
        for child in suggestions_frame.winfo_children():
            child.destroy()
        suggestion_buttons.clear()
        selected_suggestion["value"] = None

        text = trans_text.get("1.0", tk.END)
        current_suggestions = find_glossary_suggestions(text, glossary)
        highlight_glossary_hits()

        if not current_suggestions:
            ctk.CTkLabel(suggestions_frame, text="Nenhuma sugestão.").pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, (orig, new) in enumerate(current_suggestions):
            btn = ctk.CTkButton(
                suggestions_frame,
                text=f'"{preview(orig, 45)}" -> "{preview(new, 45)}"',
                anchor="w",
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
                hover_color=ROW_HOVER_COLOR,
                font=suggestion_font,
                command=lambda i=index: select_suggestion(i),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            suggestion_buttons.append(btn)

    def apply_glossary_pair_with_cursor(text, orig, new, count=0):
        matches = find_glossary_matches(text, orig)
        if count > 0:
            matches = matches[:count]
        if not matches:
            return text, None

        parts = []
        last = 0
        cursor_offset = 0
        insert_offset = None
        for start, end in matches:
            before = text[last:start]
            parts.append(before)
            cursor_offset += len(before)
            parts.append(new)
            cursor_offset += len(new)
            insert_offset = cursor_offset
            last = end
        parts.append(text[last:])
        return "".join(parts), insert_offset

    def apply_suggestions_with_cursor(text, suggestions):
        insert_offset = None
        for orig, new in suggestions:
            text, pair_offset = apply_glossary_pair_with_cursor(text, orig, new)
            if pair_offset is not None:
                insert_offset = pair_offset
        return text, insert_offset

    def apply_one():
        index = selected_suggestion["value"]
        if index is None or not (0 <= index < len(current_suggestions)):
            return

        orig, new = current_suggestions[index]
        text = draft_text()
        updated_text, insert_offset = apply_glossary_pair_with_cursor(
            text,
            orig,
            new,
            count=1,
        )
        if insert_offset is None:
            show_message("Sugestão não encontrada no texto")
            return
        set_translation_text(
            updated_text,
            mark_dirty=True,
            insert_offset=insert_offset,
            focus_editor=True,
        )

    def apply_all():
        text = draft_text()
        preview_text, preview_offset = apply_suggestions_with_cursor(
            text,
            current_suggestions,
        )
        if preview_text == text:
            show_message("Nenhuma alteração sugerida")
            return

        pop = ctk.CTkToplevel(win)
        pop.title("Pré-visualizar substituições")
        pop.geometry("980x560")
        bring_window_to_front(pop, win, maximize=True)

        ctk.CTkLabel(pop, text="Antes").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(pop, text="Depois").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 2))

        before_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        after_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        before_text.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        after_text.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        before_text.insert("1.0", text)
        after_text.insert("1.0", preview_text)
        before_text.configure(state="disabled")
        after_text.configure(state="disabled")

        actions = ctk.CTkFrame(pop, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))

        def confirm():
            set_translation_text(
                preview_text,
                mark_dirty=True,
                insert_offset=preview_offset,
                focus_editor=True,
            )
            pop.destroy()

        ctk.CTkButton(actions, text="Cancelar", width=100, command=pop.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ctk.CTkButton(actions, text="Aplicar", width=100, command=confirm).pack(side=tk.RIGHT)

        pop.columnconfigure(0, weight=1)
        pop.columnconfigure(1, weight=1)
        pop.rowconfigure(1, weight=1)

    def reload_glossary(show_feedback=True):
        nonlocal glossary
        glossary = load_substitutions()
        app.glossary_substitutions = glossary
        refresh_suggestions()
        if show_feedback:
            show_message(f"Glossário atualizado: {len(glossary)} entradas")

    def on_glossary_editor_change(updated_entries):
        nonlocal glossary
        if not win.winfo_exists():
            unregister_glossary_callback()
            return
        glossary = list(updated_entries)
        app.glossary_substitutions = glossary
        refresh_suggestions()
        show_message(f"Glossário atualizado: {len(glossary)} entradas")

    def selected_translation_text():
        try:
            return trans_text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ""

    def open_integrated_glossary_editor():
        selection = selected_translation_text()
        if selection:
            open_glossary_editor(app, initial_original=selection)
            show_message("Selecao enviada ao editor de glossario")
        else:
            open_glossary_editor(app)
            show_message("Selecione um trecho para pre-preencher o glossario")

    def unregister_glossary_callback():
        callbacks = getattr(app, "glossary_change_callbacks", [])
        if on_glossary_editor_change in callbacks:
            callbacks.remove(on_glossary_editor_change)

    app.glossary_change_callbacks.append(on_glossary_editor_change)

    def add_gloss_popup():
        sel_text = selected_translation_text()

        pop = ctk.CTkToplevel(win)
        pop.title("Adicionar ao glossário")
        pop.geometry("380x190")
        bring_window_to_front(pop, win, maximize=True)

        ctk.CTkLabel(pop, text="Texto original:").pack(anchor="w", padx=12, pady=(12, 2))
        original_entry = ctk.CTkEntry(pop, width=350)
        original_entry.pack(padx=12, fill=tk.X)
        original_entry.insert(0, sel_text)

        ctk.CTkLabel(pop, text="Substituir por:").pack(anchor="w", padx=12, pady=(10, 2))
        replacement_entry = ctk.CTkEntry(pop, width=350)
        replacement_entry.pack(padx=12, fill=tk.X)

        def confirm():
            orig = original_entry.get().strip()
            new = replacement_entry.get().strip()
            if orig and new:
                if add_to_glossary(orig, new):
                    reload_glossary(show_feedback=False)
                    show_message("Entrada adicionada ao glossário")
            pop.destroy()

        ctk.CTkButton(pop, text="Adicionar", command=confirm).pack(pady=14)

    def focus_search(_event=None):
        search_entry.focus_set()
        search_entry.select_range(0, tk.END)
        return "break"

    def save_shortcut(_event=None):
        save_changes(False)
        return "break"

    def verify_shortcut(_event=None):
        save_changes(False, mark_verified=True)
        return "break"

    def previous_shortcut(_event=None):
        navigate(-1)
        return "break"

    def next_shortcut(_event=None):
        navigate(1)
        return "break"

    def next_quality_warning_shortcut(_event=None):
        go_to_next_quality_warning()
        return "break"

    def close_editor():
        save_changes()
        save_editor_settings()
        unregister_glossary_callback()
        win.destroy()

    btn_copy_original.configure(command=copy_original_to_translation)
    btn_restore.configure(command=restore_saved_translation)
    btn_undo.configure(command=undo_translation)
    btn_redo.configure(command=redo_translation)
    btn_save_plain.configure(command=lambda: save_changes(False))
    btn_save_verify.configure(command=lambda: save_changes(False, mark_verified=True))
    btn_font_down.configure(command=lambda: adjust_font(-1))
    btn_font_up.configure(command=lambda: adjust_font(1))
    btn_bold.configure(command=toggle_bold_selection)
    btn_search.configure(command=apply_search)
    btn_clear_search.configure(command=clear_search)
    btn_go_page.configure(command=go_to_page)
    btn_go_id.configure(command=go_to_id)
    btn_page_prev.configure(command=lambda: change_page(-1))
    btn_page_next.configure(command=lambda: change_page(1))
    btn_prev.configure(command=lambda: navigate(-1))
    btn_next.configure(command=lambda: navigate(1))
    btn_mark.configure(command=mark_and_next)
    btn_pending.configure(command=mark_pending)
    btn_next_qa.configure(command=go_to_next_quality_warning)
    btn_export_qa.configure(command=export_quality_report)
    btn_apply_auto.configure(command=apply_automatic_rules_for_current_language)
    btn_history.configure(command=open_history_window)
    status_segment.configure(command=lambda _value: toggle_filter())
    btn_refresh.configure(command=refresh_suggestions)
    btn_apply_one.configure(command=apply_one)
    btn_apply_all.configure(command=apply_all)
    btn_add_gloss.configure(command=add_gloss_popup)
    btn_reload_gloss.configure(command=reload_glossary)
    btn_open_gloss.configure(command=open_integrated_glossary_editor)
    btn_find_next.configure(command=find_next_in_translation)
    btn_replace_current.configure(command=replace_current_in_translation)
    btn_replace_all.configure(command=replace_all_in_translation)
    editor_find_text.trace_add(
        "write",
        lambda *_args: refresh_find_matches(keep_current=False),
    )
    editor_case_sensitive.trace_add(
        "write",
        lambda *_args: refresh_find_matches(keep_current=False),
    )
    search_entry.bind("<Return>", lambda _event: apply_search())
    editor_find_entry.bind("<Return>", find_next_in_translation)
    editor_replace_entry.bind("<Return>", replace_current_in_translation)
    page_entry.bind("<Return>", lambda _event: go_to_page())
    id_entry.bind("<Return>", lambda _event: go_to_id())
    trans_text.bind("<<Modified>>", on_translation_modified)
    trans_text.bind("<Control-z>", lambda _event: (undo_translation(), "break")[1])
    trans_text.bind("<Control-Z>", lambda _event: (undo_translation(), "break")[1])
    trans_text.bind("<Control-y>", lambda _event: (redo_translation(), "break")[1])
    trans_text.bind("<Control-Y>", lambda _event: (redo_translation(), "break")[1])
    win.bind("<Control-f>", focus_search)
    win.bind("<Control-F>", focus_search)
    win.bind("<Control-h>", lambda _event: (open_history_window(), "break")[1])
    win.bind("<Control-H>", lambda _event: (open_history_window(), "break")[1])
    win.bind("<Control-s>", save_shortcut)
    win.bind("<Control-S>", save_shortcut)
    win.bind("<Control-Return>", verify_shortcut)
    win.bind("<Control-z>", lambda _event: (undo_translation(), "break")[1])
    win.bind("<Control-Z>", lambda _event: (undo_translation(), "break")[1])
    win.bind("<Control-y>", lambda _event: (redo_translation(), "break")[1])
    win.bind("<Control-Y>", lambda _event: (redo_translation(), "break")[1])
    win.bind("<Alt-Left>", previous_shortcut)
    win.bind("<Alt-Right>", next_shortcut)
    win.bind("<F3>", find_next_in_translation)
    win.bind("<F7>", next_quality_warning_shortcut)
    win.bind(
        "<Destroy>",
        lambda event: unregister_glossary_callback() if event.widget is win else None,
    )
    win.protocol("WM_DELETE_WINDOW", close_editor)

    reload_rows()
    if rows:
        select_index(0)
    else:
        clear_current()

    win.after(100, restore_pane_positions)
