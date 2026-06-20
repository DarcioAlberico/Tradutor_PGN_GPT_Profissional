from contextlib import closing

from .constants import PAGE_SIZE, SELECTED_ROW_COLOR
from ..database import get_review_row_offset, initialize_database
from .helpers import row_color


class EditorListSelectionMixin:
    def get_index(self):
        return self.selected_index["value"]

    def update_row_selection(self, new_index):
        old_index = self.selected_index["value"]
        if old_index is not None and 0 <= old_index < len(self.row_buttons):
            self.row_buttons[old_index].configure(fg_color=row_color(self.rows[old_index]))

        self.selected_index["value"] = new_index
        if new_index is not None and 0 <= new_index < len(self.row_buttons):
            self.row_buttons[new_index].configure(fg_color=SELECTED_ROW_COLOR)
        self.update_selection_label()

    def select_index(self, index, save_previous=False):
        if not self.rows:
            return
        if save_previous and self.current["id"]:
            self.save_changes()
        index = max(0, min(index, len(self.rows) - 1))
        self.update_row_selection(index)
        self.load_item()

    def navigate(self, delta):
        self.save_changes()
        index = self.get_index()
        if index is None:
            index = 0

        new_index = index + delta
        if 0 <= new_index < len(self.rows):
            self.select_index(new_index)
        elif new_index < 0 and self.page_index["value"] > 0:
            self.page_index["value"] -= 1
            self.reload_rows()
            if self.rows:
                self.select_index(len(self.rows) - 1)
        elif new_index >= len(self.rows) and self.page_index["value"] + 1 < self.page_count():
            self.page_index["value"] += 1
            self.reload_rows()
            if self.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")

    def change_page(self, delta):
        self.save_changes()
        new_page = self.page_index["value"] + delta
        if 0 <= new_page < self.page_count():
            self.page_index["value"] = new_page
            self.reload_rows()
            if self.rows:
                self.select_index(0)

    def go_to_page(self):
        self.save_changes()
        try:
            target_page = int(self.go_page_text.get().strip())
        except ValueError:
            self.show_message("Página inválida")
            return

        pages = self.page_count()
        if not (1 <= target_page <= pages):
            self.show_message("Página fora do intervalo")
            return

        self.page_index["value"] = target_page - 1
        self.reload_rows()
        if self.rows:
            self.select_index(0)

    def go_to_id(self):
        self.save_changes()
        try:
            target_id = int(self.go_id_text.get().strip())
        except ValueError:
            self.show_message("ID inválido")
            return

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            if self.qa_filter_active():
                offset = None
                for index, row in enumerate(self.fetch_quality_warning_rows(cur)):
                    if row[0] == target_id:
                        offset = index
                        break
            else:
                offset = get_review_row_offset(
                    cur,
                    self.lang,
                    target_id,
                    search_text=self.active_search["value"],
                    status_filter=self.selected_status_filter(),
                )

        if offset is None:
            self.show_message("ID não encontrado nos filtros atuais")
            return

        self.page_index["value"] = offset // PAGE_SIZE
        target_index = offset % PAGE_SIZE
        self.reload_rows()
        if self.rows:
            self.select_index(target_index)
