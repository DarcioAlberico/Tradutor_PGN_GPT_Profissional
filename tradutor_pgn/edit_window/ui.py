import tkinter as tk

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
