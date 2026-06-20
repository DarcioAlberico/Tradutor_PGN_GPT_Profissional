from contextlib import closing

import customtkinter as ctk
import tkinter as tk

from .constants import ROW_COLOR, ROW_HOVER_COLOR, SELECTED_ROW_COLOR
from ..database import fetch_comment_history, fetch_translation_by_id, initialize_database, update_translation_by_id
from .helpers import format_timestamp, history_action_label, history_status_label, preview


class EditorHistoryMixin:
    def open_history_window(self):
        if not self.current["id"]:
            self.show_message("Selecione uma traducao")
            return

        self.save_changes()

        history_win = ctk.CTkToplevel(self.win)
        history_win.title(f"Historico da traducao {self.current['id']}")
        history_win.geometry("980x560")
        history_win.minsize(820, 430)
        history_win.transient(self.win)
        history_win.columnconfigure(1, weight=1)
        history_win.rowconfigure(1, weight=1)

        title = (
            f"ID {self.current['id']} | "
            f"{preview(self.current['orig'], 120)}"
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

        def set_history_text(self, widget, value):
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert("1.0", value or "")
            widget.configure(state="disabled")

        def set_restore_buttons(self, enabled):
            state = "normal" if enabled else "disabled"
            btn_restore_previous.configure(state=state)
            btn_restore_new.configure(state=state)

        def selected_history_row(self):
            index = selected_history["value"]
            if index is None or not (0 <= index < len(history_rows)):
                return None
            return history_rows[index]

        def restore_history_translation(self, text):
            if text is None:
                text = ""

            with closing(initialize_database(self.app.output_db)) as conn:
                cur = conn.cursor()
                changed = update_translation_by_id(
                    cur,
                    self.current["id"],
                    text,
                    history_action="restore",
                )
                updated_row = fetch_translation_by_id(cur, self.current["id"])
                conn.commit()

            self.current["trans"] = text
            self.current["saved_trans"] = text
            self.clear_current_draft()
            if updated_row is not None:
                self.set_current_history(updated_row)
            self.set_translation_text(text, mark_dirty=False)
            self.update_current_row_cache()
            refresh_history()
            if changed:
                self.show_message("Versao restaurada")
            else:
                self.show_message("Versao ja estava aplicada")

        def select_history(self, index):
            old = selected_history["value"]
            if old is not None and 0 <= old < len(history_buttons):
                history_buttons[old].configure(fg_color=ROW_COLOR)

            selected_history["value"] = index
            if 0 <= index < len(history_buttons):
                history_buttons[index].configure(fg_color=SELECTED_ROW_COLOR)

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

        def refresh_history(self):

            for child in history_list.winfo_children():
                child.destroy()
            history_buttons.clear()
            selected_history["value"] = None

            with closing(initialize_database(self.app.output_db)) as conn:
                cur = conn.cursor()
                history_rows = list(fetch_comment_history(cur, self.current["id"], limit=100))

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
