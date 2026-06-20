import tkinter as tk

from ..review_quality import evaluate_translation_quality


class EditorTextEditingMixin:
    def set_translation_text(self, text, mark_dirty=False, autosave_draft=True):
        self.dirty["loading"] = True
        self.trans_text.delete("1.0", tk.END)
        self.trans_text.insert("1.0", text or "")
        try:
            self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.dirty["loading"] = False
        self.set_dirty(mark_dirty, autosave_draft=autosave_draft)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches(keep_current=False)

    def on_translation_modified(self, _event=None):
        try:
            modified = self.trans_text.edit_modified()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            return
        if modified and not self.dirty["loading"]:
            self.set_dirty(True)
            self.update_quality_warnings()
            self.refresh_find_matches()

    def apply_font_size(self):
        size = self.font_size["value"]
        self.body_font.configure(size=size)
        self.body_bold_font.configure(size=size, weight="bold")
        self.row_font.configure(size=max(10, size - 1))
        self.suggestion_font.configure(size=max(10, size - 1))
        self.font_label.configure(text=f"{size} pt")
        for text in (self.orig_text, self.trans_text):
            text.tag_configure("bold", font=self.body_bold_font)
            text.tag_configure("glossary_hit", font=self.body_bold_font)

    def adjust_font(self, delta):
        self.font_size["value"] = max(9, min(24, self.font_size["value"] + delta))
        self.apply_font_size()
        self.save_editor_settings()

    def toggle_bold_selection(self):
        try:
            start = self.trans_text.index(tk.SEL_FIRST)
            end = self.trans_text.index(tk.SEL_LAST)
        except tk.TclError:
            self.show_message("Selecione um trecho da tradução")
            return

        if "bold" in self.trans_text.tag_names(start):
            self.trans_text.tag_remove("bold", start, end)
        else:
            self.trans_text.tag_add("bold", start, end)

    def clear_current(self):
        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.configure(state="disabled")
        self.trans_text.delete("1.0", tk.END)
        self.current["id"] = None
        self.current["orig"] = ""
        self.current["trans"] = ""
        self.current["saved_trans"] = ""
        self.current["created_at"] = ""
        self.current["updated_at"] = ""
        self.current["verified_at"] = ""
        try:
            self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        self.clear_find_highlights()
        self.draft_label.configure(text="")
        self.refresh_suggestions()
        self.update_selection_label()
        self.update_quality_warnings()
        self.update_history_label()

    def undo_translation(self):
        try:
            self.trans_text.edit_undo()
        except tk.TclError:
            self.show_message("Nada para desfazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def redo_translation(self):
        try:
            self.trans_text.edit_redo()
        except tk.TclError:
            self.show_message("Nada para refazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def restore_saved_translation(self):
        if not self.current["id"]:
            return
        self.set_translation_text(self.current["saved_trans"], mark_dirty=False)
        self.current["trans"] = self.current["saved_trans"]
        self.clear_current_draft()
        self.show_message("Tradução restaurada")

    def copy_original_to_translation(self):
        if not self.current["id"]:
            return
        self.set_translation_text(self.current["orig"], mark_dirty=True)
        self.show_message("Original copiado para tradução")
