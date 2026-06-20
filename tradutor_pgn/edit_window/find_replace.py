import tkinter as tk

from ..editor_text import find_text_ranges, replace_all_text


class EditorFindReplaceMixin:
    def text_index_for_offset(self, offset):
        return f"1.0+{max(0, int(offset))}c"

    def clear_find_highlights(self):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)
        self.current_find_match["value"] = None

    def editor_find_ranges(self):
        return find_text_ranges(
            self.draft_text(),
            self.editor_find_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )

    def highlight_find_ranges(self, ranges, current_range=None):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)

        for start, end in ranges:
            self.trans_text.tag_add(
                "find_match",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )

        if current_range is not None:
            start, end = current_range
            self.trans_text.tag_add(
                "find_current",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )
            self.trans_text.tag_raise("find_current")

    def refresh_find_matches(self, keep_current=True):
        if not self.editor_find_text.get():
            self.clear_find_highlights()
            return []

        ranges = self.editor_find_ranges()
        current_range = None
        if keep_current and self.current_find_match["value"] in ranges:
            current_range = self.current_find_match["value"]
        self.current_find_match["value"] = current_range
        self.highlight_find_ranges(ranges, current_range)
        return ranges

    def select_find_match(self, ranges, index):
        if not ranges:
            self.clear_find_highlights()
            return

        index = index % len(ranges)
        current_range = ranges[index]
        self.current_find_match["value"] = current_range
        self.highlight_find_ranges(ranges, current_range)

        start, end = current_range
        start_index = self.text_index_for_offset(start)
        end_index = self.text_index_for_offset(end)
        self.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.trans_text.tag_add(tk.SEL, start_index, end_index)
        self.trans_text.mark_set(tk.INSERT, end_index)
        self.trans_text.see(start_index)
        self.trans_text.focus_set()
        self.show_message(f"Ocorrencia {index + 1}/{len(ranges)}")

    def find_next_in_translation(self, _event=None):
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia encontrada")
            return "break"

        if self.current_find_match["value"] in ranges:
            offset = self.current_find_match["value"][1]
        else:
            try:
                offset = len(self.trans_text.get("1.0", tk.INSERT))
            except tk.TclError:
                offset = 0

        for index, (start, _end) in enumerate(ranges):
            if start >= offset:
                self.select_find_match(ranges, index)
                return "break"

        self.select_find_match(ranges, 0)
        return "break"

    def replace_current_in_translation(self, _event=None):
        if not self.current["id"]:
            return "break"
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia para substituir")
            return "break"

        match = self.current_find_match["value"]
        if match not in ranges:
            match = ranges[0]
        start, end = match
        replacement = self.editor_replace_text.get()
        self.trans_text.delete(self.text_index_for_offset(start), self.text_index_for_offset(end))
        self.trans_text.insert(self.text_index_for_offset(start), replacement)
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()

        next_offset = start + len(replacement)
        ranges = self.refresh_find_matches(keep_current=False)
        if ranges:
            for index, (match_start, _match_end) in enumerate(ranges):
                if match_start >= next_offset:
                    self.select_find_match(ranges, index)
                    break
            else:
                self.select_find_match(ranges, 0)

        self.show_message("Ocorrencia substituida")
        return "break"

    def replace_all_in_translation(self):
        if not self.current["id"]:
            return
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return

        new_text, count = replace_all_text(
            self.draft_text(),
            self.editor_find_text.get(),
            self.editor_replace_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )
        if count == 0:
            self.show_message("Nenhuma ocorrencia para substituir")
            return

        self.set_translation_text(new_text, mark_dirty=True)
        self.refresh_find_matches(keep_current=False)
        self.show_message(f"{count} ocorrencia(s) substituida(s)")
