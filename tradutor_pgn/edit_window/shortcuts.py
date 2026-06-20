import tkinter as tk


class EditorShortcutsMixin:
    def focus_search(self, _event=None):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
        return "break"

    def save_shortcut(self, _event=None):
        self.save_changes(False)
        return "break"

    def verify_shortcut(self, _event=None):
        self.save_changes(False, mark_verified=True)
        return "break"

    def previous_shortcut(self, _event=None):
        self.navigate(-1)
        return "break"

    def next_shortcut(self, _event=None):
        self.navigate(1)
        return "break"

    def next_quality_warning_shortcut(self, _event=None):
        self.go_to_next_quality_warning()
        return "break"

    def close_editor(self):
        self.save_changes()
        self.save_editor_settings()
        self.win.destroy()

    def _wire_events(self):
        self.btn_copy_original.configure(command=self.copy_original_to_translation)
        self.btn_restore.configure(command=self.restore_saved_translation)
        self.btn_undo.configure(command=self.undo_translation)
        self.btn_redo.configure(command=self.redo_translation)
        self.btn_save_plain.configure(command=lambda: self.save_changes(False))
        self.btn_save_verify.configure(command=lambda: self.save_changes(False, mark_verified=True))
        self.btn_font_down.configure(command=lambda: self.adjust_font(-1))
        self.btn_font_up.configure(command=lambda: self.adjust_font(1))
        self.btn_bold.configure(command=self.toggle_bold_selection)
        self.btn_search.configure(command=self.apply_search)
        self.btn_clear_search.configure(command=self.clear_search)
        self.btn_go_page.configure(command=self.go_to_page)
        self.btn_go_id.configure(command=self.go_to_id)
        self.btn_page_prev.configure(command=lambda: self.change_page(-1))
        self.btn_page_next.configure(command=lambda: self.change_page(1))
        self.btn_prev.configure(command=lambda: self.navigate(-1))
        self.btn_next.configure(command=lambda: self.navigate(1))
        self.btn_mark.configure(command=self.mark_and_next)
        self.btn_pending.configure(command=self.mark_pending)
        self.btn_next_qa.configure(command=self.go_to_next_quality_warning)
        self.btn_export_qa.configure(command=self.export_quality_report)
        self.btn_history.configure(command=self.open_history_window)
        self.status_segment.configure(command=lambda _value: self.toggle_filter())
        self.btn_refresh.configure(command=self.refresh_suggestions)
        self.btn_apply_one.configure(command=self.apply_one)
        self.btn_apply_all.configure(command=self.apply_all)
        self.btn_add_gloss.configure(command=self.add_gloss_popup)
        self.btn_find_next.configure(command=self.find_next_in_translation)
        self.btn_replace_current.configure(command=self.replace_current_in_translation)
        self.btn_replace_all.configure(command=self.replace_all_in_translation)
        self.editor_find_text.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        self.editor_case_sensitive.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        self.search_entry.bind("<Return>", lambda _event: self.apply_search())
        self.editor_find_entry.bind("<Return>", self.find_next_in_translation)
        self.editor_replace_entry.bind("<Return>", self.replace_current_in_translation)
        self.page_entry.bind("<Return>", lambda _event: self.go_to_page())
        self.id_entry.bind("<Return>", lambda _event: self.go_to_id())
        self.trans_text.bind("<<Modified>>", self.on_translation_modified)
        self.trans_text.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.trans_text.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Control-f>", self.focus_search)
        self.win.bind("<Control-F>", self.focus_search)
        self.win.bind("<Control-h>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-H>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-s>", self.save_shortcut)
        self.win.bind("<Control-S>", self.save_shortcut)
        self.win.bind("<Control-Return>", self.verify_shortcut)
        self.win.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Alt-Left>", self.previous_shortcut)
        self.win.bind("<Alt-Right>", self.next_shortcut)
        self.win.bind("<F3>", self.find_next_in_translation)
        self.win.bind("<F7>", self.next_quality_warning_shortcut)
        self.win.protocol("WM_DELETE_WINDOW", self.close_editor)

        self.reload_rows()
        if self.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def _startup(self):
        self.win.after(100, self.restore_pane_positions)
