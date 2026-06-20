import tkinter as tk

import customtkinter as ctk


class EditorListPanelUiMixin:
    def _build_list_panel(self):
        self.list_frame = ctk.CTkFrame(self.main_pane, corner_radius=8)
        self.main_pane.add(self.list_frame, minsize=130)

        header = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        header.pack(fill=tk.X, padx=10, pady=(10, 4))
        ctk.CTkLabel(header, text="Traduções", font=ctk.CTkFont(weight="bold")).pack(
            side=tk.LEFT
        )
        self.btn_page_next = ctk.CTkButton(header, text="Página >", width=100)
        self.btn_page_next.pack(side=tk.RIGHT, padx=(6, 0))
        self.page_label = ctk.CTkLabel(header, text="")
        self.page_label.pack(side=tk.RIGHT, padx=6)
        self.btn_page_prev = ctk.CTkButton(header, text="< Página", width=100)
        self.btn_page_prev.pack(side=tk.RIGHT)
        font_controls = ctk.CTkFrame(header, fg_color="transparent")
        font_controls.pack(side=tk.RIGHT, padx=(0, 12))
        self.btn_font_down = ctk.CTkButton(font_controls, text="A-", width=42)
        self.btn_font_down.pack(side=tk.LEFT, padx=(0, 4))
        self.font_label = ctk.CTkLabel(font_controls, text=f"{self.font_size['value']} pt", width=46)
        self.font_label.pack(side=tk.LEFT)
        self.btn_font_up = ctk.CTkButton(font_controls, text="A+", width=42)
        self.btn_font_up.pack(side=tk.LEFT, padx=4)
        self.btn_bold = ctk.CTkButton(
            font_controls,
            text="B",
            width=42,
            font=ctk.CTkFont(weight="bold"),
        )
        self.btn_bold.pack(side=tk.LEFT, padx=(4, 0))

        search_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        search_bar.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.search_entry = ctk.CTkEntry(
            search_bar,
            textvariable=self.search_text,
            placeholder_text="Buscar no original ou tradução",
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.btn_search = ctk.CTkButton(search_bar, text="Buscar", width=90)
        self.btn_search.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_clear_search = ctk.CTkButton(search_bar, text="Limpar", width=80)
        self.btn_clear_search.pack(side=tk.LEFT)

        jump_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        jump_bar.pack(fill=tk.X, padx=10, pady=(0, 6))
        ctk.CTkLabel(jump_bar, text="Página:").pack(side=tk.LEFT)
        self.page_entry = ctk.CTkEntry(jump_bar, textvariable=self.go_page_text, width=72)
        self.page_entry.pack(side=tk.LEFT, padx=(6, 4))
        self.btn_go_page = ctk.CTkButton(jump_bar, text="Ir", width=48)
        self.btn_go_page.pack(side=tk.LEFT, padx=(0, 12))
        ctk.CTkLabel(jump_bar, text="ID:").pack(side=tk.LEFT)
        self.id_entry = ctk.CTkEntry(jump_bar, textvariable=self.go_id_text, width=90)
        self.id_entry.pack(side=tk.LEFT, padx=(6, 4))
        self.btn_go_id = ctk.CTkButton(jump_bar, text="Ir para ID", width=88)
        self.btn_go_id.pack(side=tk.LEFT)

        self.rows_frame = ctk.CTkScrollableFrame(self.list_frame, height=210)
        self.rows_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
