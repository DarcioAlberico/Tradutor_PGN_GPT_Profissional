import tkinter as tk

import customtkinter as ctk


class EditorGlossaryPanelUiMixin:
    def _build_glossary_panel(self):
        self.sugg_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.sugg_frame, minsize=300)
        self.sugg_frame.columnconfigure(0, weight=1)
        self.sugg_frame.columnconfigure(1, weight=1)
        self.sugg_frame.rowconfigure(1, weight=1)

        ctk.CTkLabel(self.sugg_frame, text="Sugestões do glossário:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )

        self.suggestions_frame = ctk.CTkScrollableFrame(self.sugg_frame, height=160)
        self.suggestions_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            padx=10,
            pady=(0, 8),
        )

        self.btn_refresh = ctk.CTkButton(self.sugg_frame, text="Recarregar sugestões")
        self.btn_apply_one = ctk.CTkButton(self.sugg_frame, text="Aplicar selecionada")
        self.btn_apply_all = ctk.CTkButton(self.sugg_frame, text="Aplicar todas")
        self.btn_add_gloss = ctk.CTkButton(self.sugg_frame, text="Adicionar ao glossário")

        self.btn_refresh.grid(row=2, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.btn_apply_one.grid(row=2, column=1, sticky="ew", padx=(4, 10), pady=4)
        self.btn_apply_all.grid(row=3, column=0, sticky="ew", padx=(10, 4), pady=(0, 10))
        self.btn_add_gloss.grid(row=3, column=1, sticky="ew", padx=(4, 10), pady=(0, 10))
