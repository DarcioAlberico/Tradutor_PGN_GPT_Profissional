import tkinter as tk

import customtkinter as ctk


class EditorFooterUiMixin:
    def _build_navigation_bar(self):
        nav = ctk.CTkFrame(self.win, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 2))
        nav.columnconfigure(0, weight=1)

        nav_actions = ctk.CTkFrame(nav, fg_color="transparent")
        nav_actions.grid(row=0, column=0, sticky="w")

        self.btn_prev = ctk.CTkButton(nav_actions, text="< Anterior", width=110)
        self.btn_next = ctk.CTkButton(nav_actions, text="Próxima >", width=110)
        self.btn_mark = ctk.CTkButton(nav_actions, text="Marcar como verificada", width=180)
        self.btn_pending = ctk.CTkButton(nav_actions, text="Marcar como pendente", width=170)
        self.btn_history = ctk.CTkButton(nav_actions, text="Hist\u00f3rico", width=100)
        self.btn_next_qa = ctk.CTkButton(nav_actions, text="Próximo aviso QA", width=150)
        self.btn_export_qa = ctk.CTkButton(nav_actions, text="Exportar QA", width=110)

        nav_buttons = [
            self.btn_prev,
            self.btn_next,
            self.btn_mark,
            self.btn_pending,
            self.btn_next_qa,
            self.btn_export_qa,
            self.btn_history,
        ]
        for index, button in enumerate(nav_buttons):
            button.grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=(0, 6),
                pady=3,
            )

        self.status_segment = ctk.CTkSegmentedButton(
            nav,
            values=["Todas", "Pendentes", "Verificadas", "Avisos QA"],
        )
        saved_status = self.editor_settings.get("status_filter", "Todas")
        if saved_status not in {"Todas", "Pendentes", "Verificadas", "Avisos QA"}:
            saved_status = "Todas"
        self.status_segment.set(saved_status)
        self.status_segment.grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_status_bar(self):
        status_frame = ctk.CTkFrame(self.win, fg_color="transparent")
        status_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        status_info = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_info.pack(fill=tk.X)

        self.msg_label = ctk.CTkLabel(status_info, text="", text_color="#16a34a")
        self.msg_label.pack(side=tk.LEFT)

        self.dirty_label = ctk.CTkLabel(status_info, text="Salvo", text_color="#16a34a")
        self.dirty_label.pack(side=tk.LEFT, padx=(12, 0))

        self.draft_label = ctk.CTkLabel(status_info, text="", text_color="#64748b")
        self.draft_label.pack(side=tk.LEFT, padx=(12, 0))

        self.selection_label = ctk.CTkLabel(status_info, text="Item 0/0")
        self.selection_label.pack(side=tk.LEFT, padx=(12, 0))

        self.counts_label = ctk.CTkLabel(
            status_info,
            text="Todas: 0 · Pendentes: 0 · Verificadas: 0 · QA: 0",
        )
        self.counts_label.pack(side=tk.LEFT, padx=(12, 0))

        edit_actions = ctk.CTkFrame(status_frame, fg_color="transparent")
        edit_actions.pack(fill=tk.X, pady=(4, 0))

        self.btn_copy_original = ctk.CTkButton(edit_actions, text="Copiar original", width=120)
        self.btn_restore = ctk.CTkButton(edit_actions, text="Restaurar", width=90)
        self.btn_undo = ctk.CTkButton(edit_actions, text="Desfazer", width=86)
        self.btn_redo = ctk.CTkButton(edit_actions, text="Refazer", width=78)
        self.btn_save_plain = ctk.CTkButton(edit_actions, text="Salvar", width=78)
        self.btn_save_verify = ctk.CTkButton(edit_actions, text="Salvar e verificar", width=150)

        for index, button in enumerate(
            [
                self.btn_copy_original,
                self.btn_restore,
                self.btn_undo,
                self.btn_redo,
                self.btn_save_plain,
                self.btn_save_verify,
            ]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
            edit_actions.columnconfigure(index, weight=1)
