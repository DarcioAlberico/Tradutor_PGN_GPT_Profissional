import tkinter as tk

import customtkinter as ctk

from .constants import ROW_HOVER_COLOR, SUGGESTION_COLOR, SUGGESTION_SELECTED_COLOR
from ..glossario import add_to_glossary, apply_all_substitutions, apply_substitution, find_glossary_suggestions
from .helpers import preview


class EditorGlossaryMixin:
    def highlight_glossary_hits(self):
        self.trans_text.tag_remove("glossary_hit", "1.0", tk.END)
        for orig, _new in self.current_suggestions:
            if not orig:
                continue
            start = "1.0"
            while True:
                pos = self.trans_text.search(orig, start, stopindex=tk.END)
                if not pos:
                    break
                end = f"{pos}+{len(orig)}c"
                self.trans_text.tag_add("glossary_hit", pos, end)
                start = end

    def select_suggestion(self, index):
        old = self.selected_suggestion["value"]
        if old is not None and 0 <= old < len(self.suggestion_buttons):
            self.suggestion_buttons[old].configure(fg_color=SUGGESTION_COLOR)

        self.selected_suggestion["value"] = index
        if 0 <= index < len(self.suggestion_buttons):
            self.suggestion_buttons[index].configure(fg_color=SUGGESTION_SELECTED_COLOR)

    def refresh_suggestions(self):

        for child in self.suggestions_frame.winfo_children():
            child.destroy()
        self.suggestion_buttons.clear()
        self.selected_suggestion["value"] = None

        text = self.trans_text.get("1.0", tk.END)
        self.current_suggestions = find_glossary_suggestions(text, self.glossary)
        self.highlight_glossary_hits()

        if not self.current_suggestions:
            ctk.CTkLabel(self.suggestions_frame, text="Nenhuma sugestão.").pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, (orig, new) in enumerate(self.current_suggestions):
            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=f'"{preview(orig, 45)}" -> "{preview(new, 45)}"',
                anchor="w",
                fg_color=SUGGESTION_COLOR,
                hover_color=ROW_HOVER_COLOR,
                font=self.suggestion_font,
                command=lambda i=index: self.select_suggestion(i),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            self.suggestion_buttons.append(btn)

    def apply_one(self):
        index = self.selected_suggestion["value"]
        if index is None or not (0 <= index < len(self.current_suggestions)):
            return

        orig, new = self.current_suggestions[index]
        text = self.trans_text.get("1.0", tk.END)
        self.trans_text.delete("1.0", tk.END)
        self.trans_text.insert("1.0", apply_substitution(text, orig, new))
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def apply_all(self):
        text = self.trans_text.get("1.0", tk.END)
        preview_text = apply_all_substitutions(text, self.current_suggestions)
        if preview_text == text:
            self.show_message("Nenhuma alteração sugerida")
            return

        pop = ctk.CTkToplevel(self.win)
        pop.title("Pré-visualizar substituições")
        pop.geometry("980x560")
        pop.transient(self.win)

        ctk.CTkLabel(pop, text="Antes").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(pop, text="Depois").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 2))

        before_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        after_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        before_text.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        after_text.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        before_text.insert("1.0", text)
        after_text.insert("1.0", preview_text)
        before_text.configure(state="disabled")
        after_text.configure(state="disabled")

        actions = ctk.CTkFrame(pop, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))

        def confirm(self):
            self.trans_text.delete("1.0", tk.END)
            self.trans_text.insert("1.0", preview_text)
            self.set_dirty(True)
            self.refresh_suggestions()
            self.update_quality_warnings()
            self.refresh_find_matches()
            pop.destroy()

        ctk.CTkButton(actions, text="Cancelar", width=100, command=pop.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ctk.CTkButton(actions, text="Aplicar", width=100, command=confirm).pack(side=tk.RIGHT)

        pop.columnconfigure(0, weight=1)
        pop.columnconfigure(1, weight=1)
        pop.rowconfigure(1, weight=1)

    def add_gloss_popup(self):
        try:
            sel_text = self.trans_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            sel_text = ""

        pop = ctk.CTkToplevel(self.win)
        pop.title("Adicionar ao glossário")
        pop.geometry("380x190")
        pop.transient(self.win)

        ctk.CTkLabel(pop, text="Texto original:").pack(anchor="w", padx=12, pady=(12, 2))
        original_entry = ctk.CTkEntry(pop, width=350)
        original_entry.pack(padx=12, fill=tk.X)
        original_entry.insert(0, sel_text)

        ctk.CTkLabel(pop, text="Substituir por:").pack(anchor="w", padx=12, pady=(10, 2))
        replacement_entry = ctk.CTkEntry(pop, width=350)
        replacement_entry.pack(padx=12, fill=tk.X)

        def confirm(self):
            orig = original_entry.get().strip()
            new = replacement_entry.get().strip()
            if orig and new:
                if add_to_glossary(orig, new) and (orig, new) not in self.glossary:
                    self.glossary.append((orig, new))
                    self.refresh_suggestions()
            pop.destroy()

        ctk.CTkButton(pop, text="Adicionar", command=confirm).pack(pady=14)
