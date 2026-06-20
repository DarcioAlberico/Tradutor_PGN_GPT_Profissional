from contextlib import closing
import tkinter as tk

import customtkinter as ctk

from .constants import PAGE_SIZE, ROW_HOVER_COLOR
from ..database import (
    count_review_rows,
    fetch_review_rows,
    fetch_review_rows_page,
    get_review_status_counts,
    initialize_database,
)
from .helpers import row_color, row_label
from ..review_quality import filter_quality_warning_rows


class EditorListPageDataMixin:
    def page_count(self):
        if self.total_rows["value"] == 0:
            return 0
        return (self.total_rows["value"] + PAGE_SIZE - 1) // PAGE_SIZE

    def fetch_quality_warning_rows(self, cur):
        review_rows = fetch_review_rows(
            cur,
            self.lang,
            search_text=self.active_search["value"],
            status_filter="all",
        )
        return filter_quality_warning_rows(review_rows)

    def update_page_controls(self):
        pages = self.page_count()
        current_page = self.page_index["value"] + 1 if pages else 0
        search_suffix = " · busca ativa" if self.active_search["value"] else ""
        status_suffix = f" · {self.status_segment.get().lower()}"
        self.page_label.configure(
            text=(
                f"Página {current_page}/{pages} · "
                f"{self.total_rows['value']} traduções{status_suffix}{search_suffix}"
            )
        )
        self.btn_page_prev.configure(
            state="normal" if self.page_index["value"] > 0 else "disabled"
        )
        self.btn_page_next.configure(
            state="normal" if self.page_index["value"] + 1 < pages else "disabled"
        )

    def render_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self.row_buttons.clear()
        self.selected_index["value"] = None
        self.update_page_controls()
        self.update_counts_label()
        self.update_selection_label()

        if not self.rows:
            if self.qa_filter_active():
                empty_text = "Nenhum aviso QA encontrado."
            else:
                empty_text = (
                    "Nenhuma tradução encontrada para a busca."
                    if self.active_search["value"]
                    else "Nenhuma tradução encontrada."
                )
            ctk.CTkLabel(self.rows_frame, text=empty_text).pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, row in enumerate(self.rows):
            btn = ctk.CTkButton(
                self.rows_frame,
                text=row_label(row),
                anchor="w",
                fg_color=row_color(row),
                hover_color=ROW_HOVER_COLOR,
                font=self.row_font,
                command=lambda i=index: self.select_index(i, save_previous=True),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            self.row_buttons.append(btn)

    def reload_rows(self):
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            self.status_counts.update(
                get_review_status_counts(
                    cur,
                    self.lang,
                    self.active_search["value"],
                )
            )
            qa_rows = self.fetch_quality_warning_rows(cur)
            if self.qa_filter_active():
                self.total_rows["value"] = len(qa_rows)
            else:
                self.total_rows["value"] = count_review_rows(
                    cur,
                    self.lang,
                    search_text=self.active_search["value"],
                    status_filter=self.selected_status_filter(),
                )
            self.status_counts["qa"] = len(qa_rows)
            pages = self.page_count()
            if pages == 0:
                self.page_index["value"] = 0
            else:
                self.page_index["value"] = min(self.page_index["value"], pages - 1)

            offset = self.page_index["value"] * PAGE_SIZE
            if self.qa_filter_active():
                self.rows = qa_rows[offset:offset + PAGE_SIZE]
            else:
                self.rows = list(
                    fetch_review_rows_page(
                        cur,
                        self.lang,
                        limit=PAGE_SIZE,
                        offset=offset,
                        search_text=self.active_search["value"],
                        status_filter=self.selected_status_filter(),
                    )
                )
        self.render_rows()
