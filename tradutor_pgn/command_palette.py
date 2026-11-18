"""Paleta de comandos da janela principal e suas condições de disponibilidade."""
from dataclasses import dataclass
import os
import tkinter as tk
from tkinter import messagebox
import unicodedata

import customtkinter as ctk

from .window_utils import bring_window_to_front


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    keywords: str
    action: str
    reason: str | None = None


def commands_for(app):
    source = app.source_path.get().strip()
    reason = ("Há uma tradução em andamento." if app.is_processing else
              "Selecione um arquivo ou pasta PGN." if not source else
              "O arquivo ou pasta selecionado não existe." if not os.path.exists(source) else None)
    last_run = getattr(app, "last_run", None)
    review_reason = (None if isinstance(last_run, dict) and last_run.get("files") else
                     "Nenhuma execução registrou arquivos para revisão.")
    verification_reason = ("A verificação de dados já está em andamento."
                           if getattr(app, "_data_verification_active", False) else None)
    canceled = app.cancel_flag.is_set()
    paused = app.pause_flag.is_set()
    inactive_reason = "Nenhuma tradução está em andamento."
    stopping_reason = "O cancelamento já foi solicitado."
    pause_reason = (inactive_reason if not app.is_processing else stopping_reason if canceled else
                    "A tradução já está pausada." if paused else None)
    resume_reason = (inactive_reason if not app.is_processing else stopping_reason if canceled else
                     "A tradução não está pausada." if not paused else None)
    cancel_reason = inactive_reason if not app.is_processing else stopping_reason if canceled else None
    retry_reason = ("Há uma tradução em andamento." if app.is_processing else
                    "Não há falhas disponíveis para reprocessar." if app.retry_button.cget("state") == "disabled" else None)
    return (
        Command("file", "Selecionar arquivo PGN", "abrir arquivo escolher", "select_file"),
        Command("directory", "Selecionar pasta de PGNs", "abrir pasta escolher diretorio", "select_directory"),
        Command("start", "Iniciar tradução", "traduzir iniciar arquivo", "start_translation", reason),
        Command("retry", "Reprocessar falhas", "tentar novamente arquivos pendentes", "retry_failed_translation", retry_reason),
        Command("pause", "Pausar tradução", "pausar suspender processamento", "pause_translation", pause_reason),
        Command("resume", "Continuar tradução", "retomar prosseguir processamento", "resume_translation", resume_reason),
        Command("cancel", "Cancelar tradução", "interromper parar processamento", "cancel_translation", cancel_reason),
        Command("library", "Abrir Biblioteca", "traduzidos livros pacotes", "open_translation_library"),
        Command("translations_folder", "Abrir pasta Minhas Traduções", "pasta traducoes arquivos traduzidos explorer", "open_translations_folder"),
        Command("last_run_folder", "Abrir pasta da última execução", "pasta ultima execucao resultado", "open_last_run_folder", review_reason),
        Command("edit_translations", "Editar traduções", "editor revisar comentarios", "open_edit_window"),
        Command("review", "Revisar pendentes da última execução", "revisao pendencias traduzidos", "review_last_run", review_reason),
        Command("glossary", "Abrir glossário", "regras termos editar", "open_glossary_window"),
        Command("new_rule", "Criar regra no glossário", "nova entrada termos", "_new_glossary_entry"),
        Command("export_tmx", "Exportar memória TMX", "exportar tmx memoria traducao", "export_tmx"),
        Command("export_csv", "Exportar traduções CSV", "exportar csv memoria banco", "export_csv"),
        Command("import_csv", "Importar traduções CSV", "importar csv memoria banco", "import_csv",
                "Há uma tradução em andamento." if app.is_processing else None),
        Command("backup", "Criar backup do banco", "backup banco copia seguranca", "backup_database"),
        Command("verify_data", "Verificar meus dados", "integridade diagnostico banco glossario", "verify_user_data", verification_reason),
        Command("settings", "Abrir configurações", "preferencias opcoes ajustes", "open_settings_window"),
    )


def _normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


def filter_commands(commands, query):
    terms = _normalize(query).split()
    return [item for item in commands if all(term in _normalize(item.label + " " + item.keywords) for term in terms)]


def _open_glossary_editor(app):
    from .glossary_editor import open_glossary_editor
    return open_glossary_editor(app)


def _new_glossary_entry(app):
    editor = _open_glossary_editor(app)
    editor.new_entry()


def run_command(app, command_id):
    command = next((item for item in commands_for(app) if item.id == command_id), None)
    if command is None:
        return "Comando desconhecido."
    if command.reason:
        return command.reason
    if command.action == "_new_glossary_entry":
        _new_glossary_entry(app)
    else:
        getattr(app, command.action)()
    return None


class CommandPalette:
    def __init__(self, app):
        self.app = app
        self.win = ctk.CTkToplevel(app.root)
        self.win.title("Comandos")
        self.win.geometry("550x420")
        self.win.minsize(400, 300)
        self.win.transient(app.root)
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self.win, text="Comandos", font=ctk.CTkFont(size=20, weight="bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        self.query = tk.StringVar(master=self.win)
        self.entry = ctk.CTkEntry(self.win, textvariable=self.query, placeholder_text="Buscar comando")
        self.entry.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        results = ctk.CTkFrame(self.win, fg_color="transparent")
        results.grid(row=2, column=0, sticky="nsew", padx=16)
        results.grid_columnconfigure(0, weight=1)
        results.grid_rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(results, exportselection=False, activestyle="dotbox", font=("Segoe UI", 12))
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(results, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.status = ctk.CTkLabel(self.win, text="", anchor="w", justify=tk.LEFT, wraplength=500)
        self.status.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 2))
        controls = ctk.CTkFrame(self.win, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="e", padx=16, pady=(4, 14))
        ctk.CTkButton(controls, text="Cancelar", width=100, command=self.win.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(controls, text="Executar", width=100, command=self.execute).pack(side="right")
        self.items = []
        self.query.trace_add("write", self.refresh)
        self.entry.bind("<Down>", self.down)
        self.entry.bind("<Up>", self.up)
        self.entry.bind("<Return>", self.execute)
        self.listbox.bind("<<ListboxSelect>>", self.update_status)
        self.listbox.bind("<Double-Button-1>", self.execute)
        self.listbox.bind("<Return>", self.execute)
        self.win.bind("<Escape>", lambda event: self.win.destroy())
        self.refresh()
        bring_window_to_front(self.win, app.root, maximize=False)
        self.entry.focus_set()

    def refresh(self, *_args):
        self.items = filter_commands(commands_for(self.app), self.query.get())
        self.listbox.delete(0, tk.END)
        for item in self.items:
            self.listbox.insert(tk.END, item.label + (" — indisponível" if item.reason else ""))
        if self.items:
            self.listbox.selection_set(0)
            self.listbox.activate(0)
        self.update_status()

    def update_status(self, _event=None):
        selected = self.listbox.curselection()
        item = self.items[selected[0]] if selected else None
        self.status.configure(text=(item.reason or "Enter executa o comando selecionado.") if item else "Nenhum comando encontrado.")

    def move(self, amount):
        if self.items:
            current = self.listbox.curselection()
            index = max(0, min(len(self.items) - 1, (current[0] if current else 0) + amount))
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self.update_status()
        return "break"

    def down(self, _event=None):
        return self.move(1)

    def up(self, _event=None):
        return self.move(-1)

    def execute(self, _event=None):
        selected = self.listbox.curselection()
        if not selected:
            return "break"
        command_id = self.items[selected[0]].id
        current = next(item for item in commands_for(self.app) if item.id == command_id)
        if current.reason:
            self.status.configure(text=current.reason)
            return "break"
        self.win.destroy()
        reason = run_command(self.app, command_id)
        if reason:
            messagebox.showinfo("Comandos", reason, parent=self.app.root)
        return "break"


def open_command_palette(app, _event=None):
    previous = getattr(app, "command_palette", None)
    if previous is not None and previous.win.winfo_exists():
        previous.win.lift()
        previous.entry.focus_set()
    else:
        app.command_palette = CommandPalette(app)
    return "break"
