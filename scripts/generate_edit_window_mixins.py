"""Generate TranslationEditor mixins from tradutor_pgn/edit_window.py."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tradutor_pgn" / "edit_window.py"
if not SRC.exists():
    SRC = ROOT / "tradutor_pgn" / "edit_window.py.bak"
PKG = ROOT / "tradutor_pgn" / "edit_window"

OPEN_DEF = "def open_translation_editor(app):"
OPEN_METHOD = "    def open(self):"

REPLACEMENTS = [
    (r"\bwin\b", "self.win"),
    (r"\bapp\b", "self.app"),
    (r"\blang\b", "self.lang"),
    (r"\bsettings\b", "self.settings"),
    (r"\beditor_settings\b", "self.editor_settings"),
    (r"\brows\b", "self.rows"),
    (r"\brow_buttons\b", "self.row_buttons"),
    (r"\btotal_rows\b", "self.total_rows"),
    (r"\bstatus_counts\b", "self.status_counts"),
    (r"\bpage_index\b", "self.page_index"),
    (r"\bcurrent\b", "self.current"),
    (r"\bdirty\b", "self.dirty"),
    (r"\bdraft_save_after\b", "self.draft_save_after"),
    (r"\bselected_index\b", "self.selected_index"),
    (r"\bselected_suggestion\b", "self.selected_suggestion"),
    (r"\bglossary\b", "self.glossary"),
    (r"\bcurrent_suggestions\b", "self.current_suggestions"),
    (r"\bsuggestion_buttons\b", "self.suggestion_buttons"),
    (r"\bsearch_text\b", "self.search_text"),
    (r"\beditor_find_text\b", "self.editor_find_text"),
    (r"\beditor_replace_text\b", "self.editor_replace_text"),
    (r"\beditor_case_sensitive\b", "self.editor_case_sensitive"),
    (r"\bcurrent_find_match\b", "self.current_find_match"),
    (r"\bgo_page_text\b", "self.go_page_text"),
    (r"\bgo_id_text\b", "self.go_id_text"),
    (r"\bactive_search\b", "self.active_search"),
    (r"\bfont_size\b", "self.font_size"),
    (r"\bbody_font\b", "self.body_font"),
    (r"\bbody_bold_font\b", "self.body_bold_font"),
    (r"\brow_font\b", "self.row_font"),
    (r"\bsuggestion_font\b", "self.suggestion_font"),
    (r"\bmain_pane\b", "self.main_pane"),
    (r"\bbottom_pane\b", "self.bottom_pane"),
    (r"\blist_frame\b", "self.list_frame"),
    (r"\brows_frame\b", "self.rows_frame"),
    (r"\btext_frame\b", "self.text_frame"),
    (r"\bsugg_frame\b", "self.sugg_frame"),
    (r"\bsuggestions_frame\b", "self.suggestions_frame"),
    (r"\borig_text\b", "self.orig_text"),
    (r"\btrans_text\b", "self.trans_text"),
    (r"\bsearch_entry\b", "self.search_entry"),
    (r"\beditor_find_entry\b", "self.editor_find_entry"),
    (r"\beditor_replace_entry\b", "self.editor_replace_entry"),
    (r"\bpage_entry\b", "self.page_entry"),
    (r"\bid_entry\b", "self.id_entry"),
    (r"\bstatus_segment\b", "self.status_segment"),
    (r"\bmsg_label\b", "self.msg_label"),
    (r"\bdirty_label\b", "self.dirty_label"),
    (r"\bdraft_label\b", "self.draft_label"),
    (r"\bselection_label\b", "self.selection_label"),
    (r"\bcounts_label\b", "self.counts_label"),
    (r"\bqa_label\b", "self.qa_label"),
    (r"\bhistory_label\b", "self.history_label"),
    (r"\bpage_label\b", "self.page_label"),
    (r"\bfont_label\b", "self.font_label"),
    (r"\bpane_bg\b", "self.pane_bg"),
    (r"\btext_bg\b", "self.text_bg"),
    (r"\btext_fg\b", "self.text_fg"),
    (r"\btext_border\b", "self.text_border"),
    (r"\bhighlight_bg\b", "self.highlight_bg"),
    (r"\bhighlight_fg\b", "self.highlight_fg"),
    (r"\bfind_bg\b", "self.find_bg"),
    (r"\bfind_fg\b", "self.find_fg"),
    (r"\bcurrent_find_bg\b", "self.current_find_bg"),
    (r"\bbtn_page_prev\b", "self.btn_page_prev"),
    (r"\bbtn_page_next\b", "self.btn_page_next"),
    (r"\bbtn_font_down\b", "self.btn_font_down"),
    (r"\bbtn_font_up\b", "self.btn_font_up"),
    (r"\bbtn_bold\b", "self.btn_bold"),
    (r"\bbtn_search\b", "self.btn_search"),
    (r"\bbtn_clear_search\b", "self.btn_clear_search"),
    (r"\bbtn_go_page\b", "self.btn_go_page"),
    (r"\bbtn_go_id\b", "self.btn_go_id"),
    (r"\bbtn_prev\b", "self.btn_prev"),
    (r"\bbtn_next\b", "self.btn_next"),
    (r"\bbtn_mark\b", "self.btn_mark"),
    (r"\bbtn_pending\b", "self.btn_pending"),
    (r"\bbtn_history\b", "self.btn_history"),
    (r"\bbtn_next_qa\b", "self.btn_next_qa"),
    (r"\bbtn_export_qa\b", "self.btn_export_qa"),
    (r"\bbtn_copy_original\b", "self.btn_copy_original"),
    (r"\bbtn_restore\b", "self.btn_restore"),
    (r"\bbtn_undo\b", "self.btn_undo"),
    (r"\bbtn_redo\b", "self.btn_redo"),
    (r"\bbtn_save_plain\b", "self.btn_save_plain"),
    (r"\bbtn_save_verify\b", "self.btn_save_verify"),
    (r"\bbtn_refresh\b", "self.btn_refresh"),
    (r"\bbtn_apply_one\b", "self.btn_apply_one"),
    (r"\bbtn_apply_all\b", "self.btn_apply_all"),
    (r"\bbtn_add_gloss\b", "self.btn_add_gloss"),
    (r"\bbtn_find_next\b", "self.btn_find_next"),
    (r"\bbtn_replace_current\b", "self.btn_replace_current"),
    (r"\bbtn_replace_all\b", "self.btn_replace_all"),
    (r"\bcase_check\b", "self.case_check"),
]

FUNCTION_GROUPS = {
    "ui_legacy.py": {
        "header": '''import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from .constants import STATUS_FILTER_VALUES
''',
        "class_name": "EditorUiMixin",
        "methods": ["_build_ui"],
    },
    "drafts.py": {
        "header": '''from datetime import datetime

import tkinter as tk

from .helpers import format_timestamp
from .review_quality import evaluate_translation_quality
from .settings import clear_editor_draft, save_settings, set_editor_draft
''',
        "class_name": "EditorDraftsMixin",
        "methods": [
            "show_message",
            "save_editor_settings",
            "restore_pane_positions",
            "cancel_draft_save",
            "draft_text",
            "clear_current_draft",
            "persist_current_draft",
            "schedule_draft_save",
            "set_dirty",
            "update_counts_label",
            "update_selection_label",
            "update_quality_warnings",
            "update_history_label",
            "set_current_history",
        ],
    },
    "find_replace.py": {
        "header": '''import tkinter as tk

from .editor_text import find_text_ranges, replace_all_text
''',
        "class_name": "EditorFindReplaceMixin",
        "methods": [
            "text_index_for_offset",
            "clear_find_highlights",
            "editor_find_ranges",
            "highlight_find_ranges",
            "refresh_find_matches",
            "select_find_match",
            "find_next_in_translation",
            "replace_current_in_translation",
            "replace_all_in_translation",
        ],
    },
    "text_editing.py": {
        "header": '''import tkinter as tk

from .review_quality import evaluate_translation_quality
''',
        "class_name": "EditorTextEditingMixin",
        "methods": [
            "set_translation_text",
            "on_translation_modified",
            "apply_font_size",
            "adjust_font",
            "toggle_bold_selection",
            "clear_current",
            "undo_translation",
            "redo_translation",
            "restore_saved_translation",
            "copy_original_to_translation",
        ],
    },
    "glossary.py": {
        "header": '''import tkinter as tk

import customtkinter as ctk

from .constants import ROW_HOVER_COLOR, SUGGESTION_COLOR, SUGGESTION_SELECTED_COLOR
from .glossario import add_to_glossary, apply_all_substitutions, apply_substitution, find_glossary_suggestions
from .helpers import preview
''',
        "class_name": "EditorGlossaryMixin",
        "methods": [
            "highlight_glossary_hits",
            "select_suggestion",
            "refresh_suggestions",
            "apply_one",
            "apply_all",
            "add_gloss_popup",
        ],
    },
    "pagination_legacy.py": {
        "header": '''from contextlib import closing
import tkinter as tk

import customtkinter as ctk

from .constants import PAGE_SIZE, ROW_HOVER_COLOR, SELECTED_ROW_COLOR
from ..database import (
    count_review_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    get_review_row_offset,
    get_review_status_counts,
    initialize_database,
)
from .helpers import row_color, row_label
from ..review_quality import filter_quality_warning_rows
''',
        "class_name": "EditorPaginationMixin",
        "methods": [
            "page_count",
            "selected_status_filter",
            "qa_filter_active",
            "fetch_quality_warning_rows",
            "update_page_controls",
            "render_rows",
            "reload_rows",
            "get_index",
            "update_row_selection",
            "select_index",
            "navigate",
            "change_page",
            "go_to_page",
            "go_to_id",
            "toggle_filter",
            "apply_search",
            "clear_search",
        ],
    },
    "persistence.py": {
        "header": '''from contextlib import closing
import tkinter as tk

from .constants import SELECTED_ROW_COLOR
from ..database import (
    fetch_translation_by_id,
    initialize_database,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from .helpers import format_timestamp, row_color, row_label
from ..review_quality import row_has_quality_warning
from ..settings import get_editor_draft
''',
        "class_name": "EditorPersistenceMixin",
        "methods": [
            "load_item",
            "update_current_row_cache",
            "save_changes",
            "mark_and_next",
            "mark_pending",
        ],
    },
    "quality_navigation.py": {
        "header": '''import csv
from contextlib import closing
from tkinter import filedialog, messagebox

from .constants import PAGE_SIZE
from ..database import (
    fetch_review_rows_page,
    initialize_database,
)
from ..review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    find_first_quality_warning,
)
''',
        "class_name": "EditorQualityNavigationMixin",
        "methods": [
            "find_quality_warning_offset",
            "go_to_next_quality_warning",
            "export_quality_report",
        ],
    },
    "shortcuts.py": {
        "header": '''import tkinter as tk
''',
        "class_name": "EditorShortcutsMixin",
        "methods": [
            "focus_search",
            "save_shortcut",
            "verify_shortcut",
            "previous_shortcut",
            "next_shortcut",
            "next_quality_warning_shortcut",
            "close_editor",
            "_wire_events",
            "_startup",
        ],
    },
}


def apply_replacements(text: str) -> str:
    for pattern, repl in REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"^\s*nonlocal\s+.*$", "", text, flags=re.MULTILINE)
    text = text.replace("def create_text_editor", "def _create_text_editor")
    text = re.sub(r"(?<!def )_create_text_editor\(", "self._create_text_editor(", text)
    text = re.sub(r"\bself\.search_text=", "search_text=", text)
    text = re.sub(r"\bself\.status_filter=", "status_filter=", text)
    text = re.sub(r"\bself\.only_unverified=", "only_unverified=", text)
    text = re.sub(r"\bself\.limit=", "limit=", text)
    text = re.sub(r"\bself\.offset=", "offset=", text)
    text = re.sub(r"\bself\.mark_verified=", "mark_verified=", text)
    text = re.sub(r"\bself\.history_action=", "history_action=", text)
    text = re.sub(r"\bself\.silent=", "silent=", text)
    return text


def extract_methods(source_lines: list[str]) -> dict[str, list[str]]:
    start = next(i for i, line in enumerate(source_lines) if line == OPEN_DEF)
    body = source_lines[start + 1 :]

    methods: dict[str, list[str]] = {}
    current_name = None
    current_lines: list[str] = []

    for line in body:
        if line.startswith("    def "):
            if current_name is not None:
                methods[current_name] = current_lines
            current_name = line.strip().split("(")[0].replace("def ", "")
            current_lines = [line]
            continue

        if current_name is None:
            continue

        if re.match(r"^    btn_\w+\.configure\(command=", line):
            methods[current_name] = current_lines
            break

        current_lines.append(line)

    return methods


def fix_method_signature(line: str) -> str:
    match = re.match(r"(\s*)def (\w+)\((.*)\):\s*$", line)
    if not match:
        return line
    indent, name, params = match.groups()
    params = params.strip()
    if params.startswith("self") or name == "_create_text_editor" and params.startswith("self"):
        return line
    if params:
        return f"{indent}def {name}(self, {params}):"
    return f"{indent}def {name}(self):"


def convert_method_lines(lines: list[str]) -> str:
    converted = []
    for line in lines:
        if line.strip().startswith("def "):
            converted.append(fix_method_signature(line))
        else:
            converted.append(line)
    return qualify_method_refs(apply_replacements("\n".join(converted)))


def extract_inline_ui(source_lines: list[str]) -> str:
    start = next(i for i, line in enumerate(source_lines) if line == OPEN_DEF)
    pane_line = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    pane_bg =")
    )
    create_def = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    def create_text_editor")
    )
    original_label = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith('    ctk.CTkLabel(text_frame, text="Original:")')
    )
    show_def = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    def show_message")
    )
    before = source_lines[pane_line:create_def]
    after = source_lines[original_label:show_def]
    return apply_replacements("\n".join(before + after))


ALL_METHOD_NAMES = sorted(
    {
        name
        for spec in FUNCTION_GROUPS.values()
        for name in spec["methods"]
        if not name.startswith("_")
    }
    | {
        "open_history_window",
        "create_text_editor",
        "show_message",
        "save_changes",
        "reload_rows",
        "select_index",
        "clear_current",
        "restore_pane_positions",
        "refresh_find_matches",
        "undo_translation",
        "redo_translation",
        "toggle_filter",
        "apply_search",
        "go_to_page",
        "go_to_id",
        "find_next_in_translation",
        "replace_current_in_translation",
        "close_editor",
    },
    key=len,
    reverse=True,
)


def qualify_method_refs(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if re.match(r"\s*def\s+\w+", line):
            lines.append(line)
            continue
        for name in ALL_METHOD_NAMES:
            line = re.sub(rf"(?<!self\.)\b{name}\b", f"self.{name}", line)
        lines.append(line.replace("self.self.", "self."))
    return "\n".join(lines)


def extract_wire_and_startup(source_lines: list[str]) -> tuple[str, str]:
    start = next(
        i
        for i, line in enumerate(source_lines)
        if line.startswith("    btn_copy_original.configure(command=")
    )
    end = next(
        i
        for i, line in enumerate(source_lines)
        if line.strip() == "win.after(100, restore_pane_positions)"
    )
    wire_lines = source_lines[start:end]
    startup_lines = source_lines[end : end + 1]

    wire_body = []
    for line in wire_lines:
        wire_body.append(qualify_method_refs(apply_replacements(line)))

    startup_body = []
    for line in startup_lines:
        startup_body.append(
            qualify_method_refs(
                apply_replacements(line).replace(
                    "restore_pane_positions", "self.restore_pane_positions"
                )
            )
        )

    wire = "    def _wire_events(self):\n" + indent_block("\n".join(wire_body), 8)
    startup = "    def _startup(self):\n" + indent_block("\n".join(startup_body), 8)
    return wire, startup


def write_history_window(methods: dict[str, list[str]]):
    content = '''from contextlib import closing

import customtkinter as ctk
import tkinter as tk

from .constants import ROW_COLOR, ROW_HOVER_COLOR, SELECTED_ROW_COLOR
from .database import fetch_comment_history, fetch_translation_by_id, initialize_database, update_translation_by_id
from .helpers import format_timestamp, history_action_label, history_status_label, preview
'''
    chunks = [convert_method_lines(methods["open_history_window"])]
    content += "\n\nclass EditorHistoryMixin:\n" + "\n\n".join(chunks) + "\n"
    (PKG / "history_window.py").write_text(content, encoding="utf-8")
    print("Wrote history_window.py")


def write_editor_init(source_lines: list[str]) -> str:
    start = next(i for i, line in enumerate(source_lines) if line == OPEN_DEF)
    win_line = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    win = ctk.CTkToplevel")
    )
    rows_line = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    rows = []")
    )
    pane_line = next(
        i
        for i, line in enumerate(source_lines[start:], start)
        if line.startswith("    pane_bg =")
    )
    init_block = source_lines[win_line:rows_line] + source_lines[rows_line:pane_line]
    init_body = apply_replacements("\n".join(init_block))
    init_body = init_body.replace(
        "safe_geometry(win, saved_geometry)",
        "safe_geometry(self.win, saved_geometry)",
    )
    init_body = re.sub(r"^\s*self\.glossary = self\.app\.glossary_substitutions\s*$", "", init_body, flags=re.MULTILINE)
    return init_body


def indent_block(text: str, spaces: int = 8) -> str:
    prefix = " " * spaces
    lines = []
    for line in text.splitlines():
        if not line.strip():
            lines.append("")
            continue
        if line.startswith("    "):
            lines.append(prefix + line[4:])
        else:
            lines.append(prefix + line)
    return "\n".join(lines)


def write_editor_py(init_body: str):
    init_text = indent_block(init_body)
    content = '''import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from .constants import PAGE_SIZE
from .drafts import EditorDraftsMixin
from .find_replace import EditorFindReplaceMixin
from .glossary import EditorGlossaryMixin
from .helpers import safe_geometry
from .history_window import EditorHistoryMixin
from .list_navigation import EditorListNavigationMixin
from .settings import load_settings
from .shortcuts import EditorShortcutsMixin
from .text_editing import EditorTextEditingMixin
from .ui import EditorUiMixin


class TranslationEditor(
    EditorUiMixin,
    EditorDraftsMixin,
    EditorFindReplaceMixin,
    EditorTextEditingMixin,
    EditorGlossaryMixin,
    EditorListNavigationMixin,
    EditorHistoryMixin,
    EditorShortcutsMixin,
):
    def __init__(self, app):
        self.app = app
        self.lang = app.target_language.get()
        self.glossary = app.glossary_substitutions

    def open(self):
        self.settings = load_settings()
        self.editor_settings = self.settings.get("editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

'''
    content += init_text + "\n"
    content += '''        self._build_ui()
        self._wire_events()
        self._startup()


def open_translation_editor(app):
    TranslationEditor(app).open()
'''
    (PKG / "editor.py").write_text(content, encoding="utf-8")
    print("Wrote editor.py")


def write_init_py():
    content = '''from .editor import open_translation_editor
from .helpers import safe_geometry

__all__ = ["open_translation_editor", "safe_geometry"]
'''
    (PKG / "__init__.py").write_text(content, encoding="utf-8")
    print("Wrote __init__.py")


def write_list_navigation_py():
    content = '''from .pagination import EditorPaginationMixin
from .persistence import EditorPersistenceMixin
from .quality_navigation import EditorQualityNavigationMixin


class EditorListNavigationMixin(
    EditorPaginationMixin,
    EditorPersistenceMixin,
    EditorQualityNavigationMixin,
):
    pass
'''
    (PKG / "list_navigation.py").write_text(content, encoding="utf-8")
    print("Wrote list_navigation.py")


def write_pagination_py():
    content = '''from .list_filters import EditorListFiltersMixin
from .list_page_data import EditorListPageDataMixin
from .list_selection import EditorListSelectionMixin


class EditorPaginationMixin(
    EditorListFiltersMixin,
    EditorListPageDataMixin,
    EditorListSelectionMixin,
):
    pass
'''
    (PKG / "pagination.py").write_text(content, encoding="utf-8")
    print("Wrote pagination.py")


def write_ui_py():
    content = '''import tkinter as tk

import customtkinter as ctk

from .ui_footer import EditorFooterUiMixin
from .ui_glossary_panel import EditorGlossaryPanelUiMixin
from .ui_list_panel import EditorListPanelUiMixin
from .ui_text_panel import EditorTextPanelUiMixin


class EditorUiMixin(
    EditorListPanelUiMixin,
    EditorTextPanelUiMixin,
    EditorGlossaryPanelUiMixin,
    EditorFooterUiMixin,
):
    def _build_ui(self):
        self.pane_bg = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
        self.main_pane = tk.PanedWindow(
            self.win,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))

        self._build_list_panel()

        self.bottom_pane = tk.PanedWindow(
            self.main_pane,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.add(self.bottom_pane, minsize=260)

        self._build_text_panel()
        self._build_glossary_panel()
        self._build_navigation_bar()
        self._build_status_bar()
'''
    (PKG / "ui.py").write_text(content, encoding="utf-8")
    print("Wrote ui.py")


def main():
    source = SRC.read_text(encoding="utf-8").splitlines()
    methods = extract_methods(source)

    for filename, spec in FUNCTION_GROUPS.items():
        if filename in {"ui_legacy.py", "pagination_legacy.py"}:
            continue
        chunks = []
        for method_name in spec["methods"]:
            if method_name in {"_wire_events", "_startup"}:
                continue
            if method_name not in methods:
                raise SystemExit(f"Missing method: {method_name}")
            chunks.append(convert_method_lines(methods[method_name]))

        if filename == "shortcuts.py":
            wire, startup = extract_wire_and_startup(source)
            chunks.append(wire)
            chunks.append(startup)

        content = spec["header"] + "\n\nclass " + spec["class_name"] + ":\n" + "\n\n".join(chunks) + "\n"
        (PKG / filename).write_text(content, encoding="utf-8")
        print(f"Wrote {filename}")

    write_history_window(methods)
    write_pagination_py()
    write_list_navigation_py()
    write_ui_py()
    write_editor_py(write_editor_init(source))
    write_init_py()
    print("Done")


if __name__ == "__main__":
    main()
