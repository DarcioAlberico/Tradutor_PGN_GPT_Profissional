from contextlib import closing
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


class EditorPersistenceMixin:
    def load_item(self):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.rows)):
            return

        comment_id = self.rows[index][0]
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            row = fetch_translation_by_id(cur, comment_id)

        if row is None:
            return

        orig, trans = row[0], row[1]
        self.current["id"] = comment_id
        self.current["orig"] = orig or ""
        self.current["trans"] = trans or ""
        self.current["saved_trans"] = self.current["trans"]
        self.set_current_history(row)

        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.insert("1.0", self.current["orig"])
        self.orig_text.configure(state="disabled")

        draft = get_editor_draft(
            self.settings,
            self.app.output_db,
            self.lang,
            comment_id,
            self.current["trans"],
        )
        if draft is None:
            self.set_translation_text(self.current["trans"], mark_dirty=False)
        else:
            self.set_translation_text(
                draft["text"],
                mark_dirty=True,
                autosave_draft=False,
            )
            self.draft_label.configure(
                text=f"Rascunho restaurado {format_timestamp(draft['updated_at'])}",
                text_color="#64748b",
            )
            self.show_message("Rascunho restaurado")

    def update_current_row_cache(self, verified=None):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.rows)):
            return

        if verified is None:
            verified = self.rows[index][3] if len(self.rows[index]) > 3 else 0

        self.rows[index] = (
            self.current["id"],
            self.current["orig"],
            self.current["trans"],
            verified,
            self.current["created_at"],
            self.current["updated_at"],
            self.current["verified_at"],
        )
        self.row_buttons[index].configure(text=row_label(self.rows[index]))
        if self.selected_index["value"] == index:
            self.row_buttons[index].configure(fg_color=SELECTED_ROW_COLOR)
        else:
            self.row_buttons[index].configure(fg_color=row_color(self.rows[index]))

    def save_changes(self, silent=True, mark_verified=False):
        if not self.current["id"]:
            return

        new_trans = self.trans_text.get("1.0", tk.END).rstrip("\n")

        updated_row = None
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            update_translation_by_id(cur, self.current["id"], new_trans, mark_verified)
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()

        self.current["trans"] = new_trans
        self.current["saved_trans"] = new_trans
        self.clear_current_draft()
        if updated_row is not None:
            self.set_current_history(updated_row)
        try:
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        index = self.get_index()
        old_warning = False
        new_warning = False
        if index is not None and 0 <= index < len(self.rows):
            old_verified = self.rows[index][3] if len(self.rows[index]) > 3 else 0
            old_warning = row_has_quality_warning(self.rows[index])
            verified = 1 if mark_verified else old_verified
            self.update_current_row_cache(verified)
            new_warning = row_has_quality_warning(self.rows[index])
            if old_warning != new_warning:
                if new_warning:
                    self.status_counts["qa"] += 1
                else:
                    self.status_counts["qa"] = max(0, self.status_counts["qa"] - 1)
                self.update_counts_label()
            if mark_verified and old_verified != 1:
                self.status_counts["pending"] = max(0, self.status_counts["pending"] - 1)
                self.status_counts["verified"] += 1
                self.update_counts_label()

        if self.qa_filter_active() and old_warning and not new_warning:
            idx = self.get_index()
            self.reload_rows()
            if self.rows:
                self.select_index(0 if idx is None else min(idx, len(self.rows) - 1))
            else:
                self.clear_current()

        if mark_verified and self.selected_status_filter() == "pending":
            idx = self.get_index()
            self.reload_rows()
            if self.rows:
                self.select_index(0 if idx is None else min(idx, len(self.rows) - 1))
            else:
                self.clear_current()

        if not silent:
            if mark_verified:
                self.show_message("Tradução salva e verificada")
            else:
                self.show_message("Tradução salva")

    def mark_and_next(self):
        if not self.current["id"]:
            return

        index = self.get_index()
        self.save_changes(mark_verified=True)

        if self.selected_status_filter() == "pending":
            self.show_message("Marcada como verificada" if self.current["id"] else "Sem traduções pendentes")
            return

        if index is None:
            index = 0
        new_index = index + 1

        if 0 <= new_index < len(self.rows):
            self.select_index(new_index)
        elif new_index >= len(self.rows) and self.page_index["value"] + 1 < self.page_count():
            self.page_index["value"] += 1
            self.reload_rows()
            if self.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")
            return

        self.show_message("Marcada como verificada")

    def mark_pending(self):
        if not self.current["id"]:
            return

        self.save_changes()
        updated_row = None
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            set_translation_verified_by_id(cur, self.current["id"], False)
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()
        if updated_row is not None:
            self.set_current_history(updated_row)

        index = self.get_index()
        if self.selected_status_filter() == "verified":
            self.reload_rows()
            if self.rows:
                self.select_index(0 if index is None else min(index, len(self.rows) - 1))
            else:
                self.clear_current()
        elif index is not None and 0 <= index < len(self.rows):
            old_verified = self.rows[index][3] if len(self.rows[index]) > 3 else 0
            self.update_current_row_cache(0)
            if old_verified == 1:
                self.status_counts["verified"] = max(0, self.status_counts["verified"] - 1)
                self.status_counts["pending"] += 1
                self.update_counts_label()

        self.show_message("Marcada como pendente")
