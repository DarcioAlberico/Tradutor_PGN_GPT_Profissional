"""Snapshot-only Tk view. Providers, preferences and edits belong to its caller."""

import customtkinter as ctk

from .editor_common import MUTED_TEXT_COLOR, ROW_COLOR, ROW_TEXT_COLOR
from .writing_types import AssistantStatus


class WritingActionButton(ctk.CTkButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._canvas.configure(takefocus=True)
        self.bind("<Return>", lambda _event: self.invoke(), add="+")
        self.bind("<space>", lambda _event: self.invoke(), add="+")

    def focus_set(self):
        self._canvas.focus_set()


class WritingPanel(ctk.CTkFrame):
    def __init__(self, parent, *, on_select=None, on_apply=None, on_apply_all=None,
                 on_ignore_once=None, on_ignore_session=None, on_add_personal=None,
                 on_disable_rule=None, on_undo_bulk=None, on_settings=None):
        super().__init__(parent, width=300, corner_radius=8)
        self.callbacks = dict(select=on_select, apply=on_apply, apply_all=on_apply_all,
                              ignore_once=on_ignore_once, ignore_session=on_ignore_session,
                              add_personal=on_add_personal, disable_rule=on_disable_rule,
                              undo_bulk=on_undo_bulk, settings=on_settings)
        self.issues = ()
        self.selected_index = None
        self.issue_buttons = []
        self.closed = False
        self.manual_collapsed = None
        self.collapsed = False
        self.available_width = 1800
        self.on_collapse = None
        self.status = AssistantStatus("starting", "spelling_only", "Carregando dicionário pt-BR")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.toggle_button = WritingActionButton(self, text="Revisão linguística  ‹", width=32, command=self.toggle_collapsed)
        self.toggle_button.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", width=270)
        self.body.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self.body.columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.body, text="", anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.diagnostic_label = ctk.CTkLabel(self.body, text="", wraplength=270,
                                              justify="left", text_color=MUTED_TEXT_COLOR)
        self.diagnostic_label.grid(row=1, column=0, sticky="ew")
        self.issue_list = ctk.CTkScrollableFrame(self.body, width=245, height=100)
        self.issue_list.grid(row=2, column=0, sticky="nsew")
        self.issue_list.columnconfigure(0, weight=1)
        self.explanation = ctk.CTkLabel(self.body, text="", wraplength=270, justify="left")
        self.explanation.grid(row=3, column=0, sticky="ew", pady=4)
        self.suggestions = ctk.CTkOptionMenu(self.body, values=["Sem sugestões"])
        self.suggestions.grid(row=4, column=0, sticky="ew", pady=4)
        actions = (("apply", "Aplicar"), ("apply_all", "Aplicar todas iguais neste livro"),
                   ("ignore_once", "Ignorar uma vez"), ("ignore_session", "Ignorar na sessão"),
                   ("add_personal", "Adicionar ao vocabulário pessoal"),
                   ("disable_rule", "Desativar esta regra"), ("undo_bulk", "Desfazer lote do livro"),
                   ("settings", "Configurações de escrita"))
        self.action_buttons = {}
        for index, (name, label) in enumerate(actions, 5):
            button = WritingActionButton(self.body, text=label, command=lambda action=name: self._invoke(action))
            button.grid(row=index, column=0, sticky="ew", pady=2)
            button.bind("<FocusIn>", lambda _event, target=button: self._reveal_action(target), add="+")
            self.action_buttons[name] = button
        self.apply_button = self.action_buttons["apply"]
        self.set_snapshot((), self.status)

    @property
    def active_issue(self):
        if self.selected_index is None or not 0 <= self.selected_index < len(self.issues):
            return None
        return self.issues[self.selected_index]

    def set_snapshot(self, issues, status=None):
        if self.closed:
            return
        selected = self.active_issue
        self.issues = tuple(sorted((issue for issue in issues if issue.state == "active"),
                                   key=lambda issue: (issue.start, issue.end, issue.rule_id)))
        if status is not None:
            self.status = status
        for button in self.issue_buttons:
            button.destroy()
        self.issue_buttons = []
        for index, issue in enumerate(self.issues):
            category = "Ortografia" if issue.category == "SPELLING" else "Gramática"
            button = ctk.CTkButton(self.issue_list, text=f"{index + 1}. {category}: {issue.original}",
                                 anchor="w", fg_color=ROW_COLOR, text_color=ROW_TEXT_COLOR,
                                 command=lambda i=index: self.select(i))
            button.grid(row=index, column=0, sticky="ew", pady=2)
            self.issue_buttons.append(button)
        self.selected_index = next((i for i, issue in enumerate(self.issues)
                                    if selected and issue.issue_id == selected.issue_id),
                                   0 if self.issues else None)
        self._refresh_details()

    def _refresh_details(self):
        issue = self.active_issue
        mode = {"full": "Completo", "spelling_only": "Somente ortografia", "unavailable": "Indisponível"}[self.status.mode]
        if self.status.state in {"starting", "restarting"}:
            mode = "Iniciando"
        position = self.selected_index + 1 if self.selected_index is not None else 0
        self.status_label.configure(text=f"{position}/{len(self.issues)} · {mode}")
        self.diagnostic_label.configure(text=self.status.diagnostic)
        self.explanation.configure(text=f"{issue.message}\n{issue.explanation}" if issue else "Nenhuma ocorrência ativa.")
        suggestions = list(issue.suggestions) if issue else []
        self.suggestions.configure(values=suggestions or ["Sem sugestões"], state="normal" if suggestions else "disabled")
        self.suggestions.set(suggestions[0] if suggestions else "Sem sugestões")
        for name, button in self.action_buttons.items():
            enabled = self.callbacks[name] is not None and (name in {"settings", "undo_bulk"} or issue is not None)
            if name in {"apply", "apply_all"}:
                enabled = enabled and bool(suggestions)
            button.configure(state="normal" if enabled else "disabled")
        for index, button in enumerate(self.issue_buttons):
            button.configure(border_width=2 if index == self.selected_index else 0)

    def select(self, index):
        if self.closed or not 0 <= index < len(self.issues):
            return
        self.selected_index = index
        self._refresh_details()
        callback = self.callbacks["select"]
        if callback:
            callback(self.active_issue)

    def navigate(self, delta):
        if self.closed or not self.issues:
            return
        self.select(((self.selected_index or 0) + delta) % len(self.issues))

    def _invoke(self, action):
        if self.closed or self.callbacks[action] is None:
            return
        if action in {"settings", "undo_bulk"}:
            self.callbacks[action]()
        elif self.active_issue:
            if action in {"apply", "apply_all"}:
                if self.active_issue.suggestions:
                    self.callbacks[action](self.active_issue, self.suggestions.get())
            else:
                self.callbacks[action](self.active_issue)

    def toggle_collapsed(self):
        self.manual_collapsed = not self.collapsed
        self.set_available_width(self.available_width)

    def _reveal_action(self, button):
        canvas = self.body._parent_canvas
        bounds = canvas.bbox("all")
        if not bounds:
            return
        top = canvas.canvasy(0)
        height = canvas.winfo_height()
        y = button.winfo_y()
        bottom = y + button.winfo_height()
        if y < top:
            canvas.yview_moveto(max(0, y / bounds[3]))
        elif bottom > top + height:
            canvas.yview_moveto(max(0, (bottom - height) / bounds[3]))

    def set_available_width(self, width):
        if self.closed:
            return
        self.available_width = width
        self.collapsed = self.manual_collapsed if self.manual_collapsed is not None else width < 1550
        self.configure(width=42 if self.collapsed else 300)
        if self.collapsed:
            self.body.grid_remove()
        else:
            self.body.grid()
        self.toggle_button.configure(text="›" if self.collapsed else "Revisão linguística  ‹")
        if self.on_collapse is not None:
            self.on_collapse(self.collapsed)

    def destroy(self):
        self.closed = True
        self.callbacks.clear()
        self.on_collapse = None
        self.issues = ()
        super().destroy()
