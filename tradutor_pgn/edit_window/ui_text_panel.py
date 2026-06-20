import tkinter as tk

import customtkinter as ctk


class EditorTextPanelUiMixin:
    def _create_text_editor(self, parent, row, readonly=False, bottom_pad=8):
        container = tk.Frame(
            parent,
            bg=self.text_border,
            highlightthickness=1,
            highlightbackground=self.text_border,
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
            font=self.body_font,
            bg=self.text_bg,
            fg=self.text_fg,
            insertbackground=self.text_fg,
            selectbackground="#2563eb",
            selectforeground="#ffffff",
            padx=8,
            pady=6,
        )
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.tag_configure("bold", font=self.body_bold_font)
        text.tag_configure(
            "glossary_hit",
            background=self.highlight_bg,
            foreground=self.highlight_fg,
            font=self.body_bold_font,
        )
        text.tag_configure(
            "find_match",
            background=self.find_bg,
            foreground=self.find_fg,
        )
        text.tag_configure(
            "find_current",
            background=self.current_find_bg,
            foreground="#ffffff",
        )
        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    def _build_text_panel(self):
        self.text_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.text_frame, minsize=520)
        self.text_frame.columnconfigure(0, weight=1)
        self.text_frame.rowconfigure(1, weight=1)
        self.text_frame.rowconfigure(3, weight=1)

        self.text_bg = "#111827" if ctk.get_appearance_mode() == "Dark" else "#f9fafb"
        self.text_fg = "#e5e7eb" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.text_border = "#374151" if ctk.get_appearance_mode() == "Dark" else "#d1d5db"
        self.highlight_bg = "#7c5800" if ctk.get_appearance_mode() == "Dark" else "#fff3bf"
        self.highlight_fg = "#fef3c7" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.find_bg = "#334155" if ctk.get_appearance_mode() == "Dark" else "#fde68a"
        self.find_fg = "#f8fafc" if ctk.get_appearance_mode() == "Dark" else "#111827"
        self.current_find_bg = "#ea580c" if ctk.get_appearance_mode() == "Dark" else "#fb923c"

        ctk.CTkLabel(self.text_frame, text="Original:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2)
        )
        self.orig_text = self._create_text_editor(self.text_frame, 1, readonly=True)
        translation_header = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        translation_header.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
        ctk.CTkLabel(translation_header, text="Tradução:").pack(side=tk.LEFT)
        self.trans_text = self._create_text_editor(self.text_frame, 3, bottom_pad=4)

        find_bar = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        find_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 4))
        find_bar.columnconfigure(0, weight=1)
        find_bar.columnconfigure(1, weight=1)

        self.editor_find_entry = ctk.CTkEntry(
            find_bar,
            textvariable=self.editor_find_text,
            placeholder_text="Buscar",
            width=120,
        )
        self.editor_find_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.editor_replace_entry = ctk.CTkEntry(
            find_bar,
            textvariable=self.editor_replace_text,
            placeholder_text="Substituir",
            width=120,
        )
        self.editor_replace_entry.grid(row=0, column=1, sticky="ew", padx=4)
        find_buttons = ctk.CTkFrame(find_bar, fg_color="transparent")
        find_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.btn_find_next = ctk.CTkButton(find_buttons, text="Prox.", width=58)
        self.btn_find_next.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_replace_current = ctk.CTkButton(find_buttons, text="Trocar", width=68)
        self.btn_replace_current.pack(side=tk.LEFT, padx=4)
        self.btn_replace_all = ctk.CTkButton(find_buttons, text="Todos", width=62)
        self.btn_replace_all.pack(side=tk.LEFT, padx=4)
        self.case_check = ctk.CTkCheckBox(
            find_buttons,
            text="Aa",
            variable=self.editor_case_sensitive,
            width=46,
        )
        self.case_check.pack(side=tk.LEFT, padx=(4, 0))

        self.qa_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color="#16a34a",
        )
        self.qa_label.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 2))
        self.history_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
        )
        self.history_label.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))
