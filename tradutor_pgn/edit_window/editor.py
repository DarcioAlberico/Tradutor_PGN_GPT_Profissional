import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from .constants import PAGE_SIZE
from .drafts import EditorDraftsMixin
from .find_replace import EditorFindReplaceMixin
from .glossary import EditorGlossaryMixin
from .helpers import safe_geometry
from .history_window import EditorHistoryMixin
from .list_navigation import EditorListNavigationMixin
from ..settings import load_settings
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

        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title(f"Editar traduções ({self.lang})")
        self.win.geometry("1180x720")
        self.win.minsize(980, 620)

        self.settings = load_settings()
        self.editor_settings = self.settings.get("editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

        saved_geometry = self.editor_settings.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            try:
                self.win.geometry(safe_geometry(self.win, saved_geometry))
            except tk.TclError:
                pass

        self.rows = []
        self.row_buttons = []
        self.total_rows = {"value": 0}
        self.status_counts = {"total": 0, "pending": 0, "verified": 0, "qa": 0}
        self.page_index = {"value": 0}
        self.current = {
            "id": None,
            "orig": "",
            "trans": "",
            "saved_trans": "",
            "created_at": "",
            "updated_at": "",
            "verified_at": "",
        }
        self.dirty = {"value": False, "loading": False}
        self.draft_save_after = {"value": None}
        self.selected_index = {"value": None}
        self.selected_suggestion = {"value": None}

        self.current_suggestions = []
        self.suggestion_buttons = []
        self.search_text = tk.StringVar(master=self.win, value="")
        self.editor_find_text = tk.StringVar(master=self.win, value="")
        self.editor_replace_text = tk.StringVar(master=self.win, value="")
        self.editor_case_sensitive = tk.BooleanVar(master=self.win, value=False)
        self.current_find_match = {"value": None}
        self.go_page_text = tk.StringVar(master=self.win, value="")
        self.go_id_text = tk.StringVar(master=self.win, value="")
        self.active_search = {"value": ""}
        saved_font_size = self.editor_settings.get("self.font_size", 12)
        if not isinstance(saved_font_size, int):
            saved_font_size = 12
        self.font_size = {"value": max(9, min(24, saved_font_size))}
        self.body_font = tkfont.Font(family="Segoe UI", size=self.font_size["value"])
        self.body_bold_font = tkfont.Font(family="Segoe UI", size=self.font_size["value"], weight="bold")
        self.row_font = ctk.CTkFont(family="Consolas", size=11)
        self.suggestion_font = ctk.CTkFont(size=11)

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)
        self._build_ui()
        self._wire_events()
        self._startup()


def open_translation_editor(app):
    TranslationEditor(app).open()
