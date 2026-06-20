import csv
from contextlib import closing
from tkinter import filedialog, messagebox

from .constants import PAGE_SIZE
from ..database import fetch_review_rows_page, initialize_database
from ..review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    find_first_quality_warning,
)


class EditorQualityNavigationMixin:
    def find_quality_warning_offset(self, start_offset, stop_offset):
        if start_offset >= stop_offset:
            return None

        offset = start_offset
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            while offset < stop_offset:
                page_start = (offset // PAGE_SIZE) * PAGE_SIZE
                local_start = offset - page_start
                page_rows = list(
                    fetch_review_rows_page(
                        cur,
                        self.lang,
                        limit=PAGE_SIZE,
                        offset=page_start,
                        search_text=self.active_search["value"],
                        status_filter=self.selected_status_filter(),
                    )
                )
                if not page_rows:
                    break

                page_limit = stop_offset - page_start
                if page_limit < len(page_rows):
                    page_rows = page_rows[:page_limit]

                found = find_first_quality_warning(page_rows, local_start)
                if found is not None:
                    found_index, _row, warnings = found
                    return page_start + found_index, warnings

                offset = page_start + len(page_rows)

        return None

    def go_to_next_quality_warning(self):
        self.save_changes()
        total = self.total_rows["value"]
        if total == 0:
            self.show_message("Nenhum item nos filtros atuais")
            return

        index = self.get_index()
        if index is None:
            start_offset = self.page_index["value"] * PAGE_SIZE
        else:
            start_offset = self.page_index["value"] * PAGE_SIZE + index + 1

        if start_offset >= total:
            start_offset = 0

        if self.qa_filter_active():
            target_offset = start_offset
            self.page_index["value"] = target_offset // PAGE_SIZE
            self.reload_rows()
            if self.rows:
                local_index = target_offset % PAGE_SIZE
                self.select_index(local_index)
                warnings = evaluate_translation_quality(
                    self.rows[local_index][1],
                    self.rows[local_index][2],
                )
                if warnings:
                    self.show_message("Aviso QA: " + warnings[0])
            return

        found = self.find_quality_warning_offset(start_offset, total)
        if found is None and start_offset > 0:
            found = self.find_quality_warning_offset(0, start_offset)

        if found is None:
            self.show_message("Nenhum aviso QA nos filtros atuais")
            return

        target_offset, warnings = found
        self.page_index["value"] = target_offset // PAGE_SIZE
        self.reload_rows()
        if self.rows:
            self.select_index(target_offset % PAGE_SIZE)
        self.show_message("Aviso QA: " + warnings[0])

    def export_quality_report(self):
        self.save_changes()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            report_rows = build_quality_report_rows(
                self.fetch_quality_warning_rows(cur),
                self.lang,
            )

        if not report_rows:
            self.show_message("Nenhum aviso QA para exportar")
            return

        save_path = filedialog.asksaveasfilename(
            title="Salvar relatorio QA",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return

        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(QUALITY_REPORT_HEADERS)
                writer.writerows(report_rows)
        except OSError as exc:
            messagebox.showerror("Erro", f"Erro ao exportar relatorio QA:\n{exc}")
            return

        messagebox.showinfo(
            "Exportar QA",
            f"Relatorio QA exportado com {len(report_rows)} avisos:\n{save_path}",
        )
