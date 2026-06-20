class EditorListFiltersMixin:
    def selected_status_filter(self):
        value = self.status_segment.get()
        if value == "Pendentes":
            return "pending"
        if value == "Verificadas":
            return "verified"
        return "all"

    def qa_filter_active(self):
        return self.status_segment.get() == "Avisos QA"

    def toggle_filter(self):
        self.page_index["value"] = 0
        self.save_editor_settings()
        self.reload_rows()
        if self.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def apply_search(self):
        self.save_changes()
        self.active_search["value"] = self.search_text.get().strip()
        self.page_index["value"] = 0
        self.reload_rows()
        if self.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def clear_search(self):
        if not self.active_search["value"] and not self.search_text.get():
            return
        self.search_text.set("")
        self.active_search["value"] = ""
        self.page_index["value"] = 0
        self.reload_rows()
        if self.rows:
            self.select_index(0)
        else:
            self.clear_current()
