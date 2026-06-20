from datetime import datetime

import tkinter as tk

from .helpers import format_timestamp
from ..review_quality import evaluate_translation_quality
from ..settings import clear_editor_draft, save_settings, set_editor_draft


class EditorDraftsMixin:
    def show_message(self, text):
        self.msg_label.configure(text=text)
        self.win.after(1500, lambda: self.msg_label.configure(text=""))

    def save_editor_settings(self):
        editor = self.settings.setdefault("editor", {})
        if not isinstance(editor, dict):
            editor = {}
            self.settings["editor"] = editor

        editor["self.font_size"] = self.font_size["value"]
        editor["status_filter"] = self.status_segment.get()
        editor["geometry"] = self.win.geometry()

        try:
            editor["main_sash_y"] = self.main_pane.sash_coord(0)[1]
        except tk.TclError:
            pass

        try:
            editor["bottom_sash_x"] = self.bottom_pane.sash_coord(0)[0]
        except tk.TclError:
            pass

        try:
            save_settings(self.settings)
        except OSError:
            pass

    def restore_pane_positions(self):
        main_sash_y = self.editor_settings.get("main_sash_y")
        bottom_sash_x = self.editor_settings.get("bottom_sash_x")

        try:
            if isinstance(main_sash_y, int) and main_sash_y > 0:
                self.main_pane.sash_place(0, 0, main_sash_y)
        except tk.TclError:
            pass

        try:
            if isinstance(bottom_sash_x, int) and bottom_sash_x > 0:
                self.bottom_pane.sash_place(0, bottom_sash_x, 0)
        except tk.TclError:
            pass

    def cancel_draft_save(self):
        if self.draft_save_after["value"] is None:
            return
        try:
            self.win.after_cancel(self.draft_save_after["value"])
        except tk.TclError:
            pass
        self.draft_save_after["value"] = None

    def draft_text(self):
        return self.trans_text.get("1.0", tk.END).rstrip("\n")

    def clear_current_draft(self, persist=True):
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        changed = clear_editor_draft(
            self.settings,
            self.app.output_db,
            self.lang,
            self.current["id"],
        )
        if changed and persist:
            try:
                save_settings(self.settings)
            except OSError:
                self.draft_label.configure(
                    text="Falha ao limpar rascunho",
                    text_color="#dc2626",
                )
                return
        self.draft_label.configure(text="", text_color="#64748b")

    def persist_current_draft(self):
        self.draft_save_after["value"] = None
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        text = self.draft_text()
        try:
            if text == self.current["saved_trans"]:
                self.clear_current_draft(persist=False)
            else:
                set_editor_draft(
                    self.settings,
                    self.app.output_db,
                    self.lang,
                    self.current["id"],
                    text,
                    self.current["saved_trans"],
                )
                self.draft_label.configure(
                    text=f"Rascunho salvo {datetime.now().strftime('%H:%M:%S')}",
                    text_color="#64748b",
                )
            save_settings(self.settings)
        except OSError:
            self.draft_label.configure(
                text="Falha ao salvar rascunho",
                text_color="#dc2626",
            )

    def schedule_draft_save(self):
        if self.dirty["loading"] or not self.current["id"]:
            return
        self.cancel_draft_save()
        self.draft_label.configure(text="Salvando rascunho...", text_color="#64748b")
        self.draft_save_after["value"] = self.win.after(700, self.persist_current_draft)

    def set_dirty(self, value, autosave_draft=True):
        self.dirty["value"] = value
        if value:
            self.dirty_label.configure(text="Alterações não salvas", text_color="#f59e0b")
            if autosave_draft:
                self.schedule_draft_save()
        else:
            self.cancel_draft_save()
            self.dirty_label.configure(text="Salvo", text_color="#16a34a")

    def update_counts_label(self):
        self.counts_label.configure(
            text=(
                f"Todas: {self.status_counts['total']} · "
                f"Pendentes: {self.status_counts['pending']} · "
                f"Verificadas: {self.status_counts['verified']} · "
                f"QA: {self.status_counts['qa']}"
            )
        )

    def update_selection_label(self):
        index = self.get_index()
        if index is None or not self.rows:
            self.selection_label.configure(text=f"Item 0/{self.total_rows['value']}")
            return

        absolute_index = self.page_index["value"] * PAGE_SIZE + index + 1
        self.selection_label.configure(text=f"Item {absolute_index}/{self.total_rows['value']}")

    def update_quality_warnings(self):
        warnings = evaluate_translation_quality(
            self.current["orig"],
            self.trans_text.get("1.0", tk.END),
        )
        if warnings:
            self.qa_label.configure(
                text="QA: " + " | ".join(warnings),
                text_color="#f59e0b",
            )
        elif self.current["id"]:
            self.qa_label.configure(text="QA: sem avisos", text_color="#16a34a")
        else:
            self.qa_label.configure(text="", text_color="#16a34a")

    def update_history_label(self):
        if not self.current["id"]:
            self.history_label.configure(text="")
            return

        self.history_label.configure(
            text=(
                f"Criada: {format_timestamp(self.current['created_at'])} | "
                f"Editada: {format_timestamp(self.current['updated_at'])} | "
                f"Verificada: {format_timestamp(self.current['verified_at'])}"
            )
        )

    def set_current_history(self, row):
        self.current["created_at"] = row[2] or "" if len(row) > 2 else ""
        self.current["updated_at"] = row[3] or "" if len(row) > 3 else ""
        self.current["verified_at"] = row[4] or "" if len(row) > 4 else ""
        self.update_history_label()
