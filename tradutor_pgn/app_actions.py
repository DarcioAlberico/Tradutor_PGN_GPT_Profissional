import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from .db_tools import backup_database as backup_database_file
from .db_tools import apply_automatic_rules_to_database as apply_auto_rules_to_database
from .db_tools import export_csv as export_translations_csv
from .db_tools import import_csv as import_translations_csv
from .db_tools import restore_database as restore_database_file
from .db_tools import show_db_stats as show_database_stats
from .edit_window import open_translation_editor
from .glossary_editor import open_glossary_editor
from .pgn_spellcheck import normalize_pgn_metadata_path
from .translation_worker import run_translation


def select_file(app):
    file_path = filedialog.askopenfilename(
        title="Selecione um arquivo PGN",
        filetypes=[("Arquivos PGN", "*.pgn"), ("Todos os arquivos", "*.*")],
    )
    if file_path:
        app.source_path.set(file_path)


def select_directory(app):
    dir_path = filedialog.askdirectory(title="Selecione uma pasta com arquivos PGN")
    if dir_path:
        app.source_path.set(dir_path)


def log_message(app, message: str):
    app.log_queue.put(message)


def update_log(app):
    try:
        while not app.log_queue.empty():
            msg = app.log_queue.get_nowait()
            app.log_text.configure(state="normal")
            app.log_text.insert(tk.END, msg + "\n")
            app.log_text.see(tk.END)
            app.log_text.configure(state="disabled")
    except queue.Empty:
        pass
    finally:
        app.root.after(100, app.update_log)


def start_translation(app):
    if app.is_processing:
        return

    source_path = app.source_path.get().strip()
    if not source_path:
        messagebox.showerror("Erro", "Selecione um arquivo ou pasta PGN.")
        return

    if not os.path.exists(source_path):
        messagebox.showerror("Erro", "O caminho informado não existe.")
        return

    app.log_text.configure(state="normal")
    app.log_text.delete("1.0", tk.END)
    app.log_text.configure(state="disabled")

    app.is_processing = True
    app.start_button.configure(state="disabled")
    app.pause_button.configure(state="normal")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="normal")
    app.progress.set(0)
    app.pause_flag.clear()
    app.cancel_flag.clear()

    target_language = app.target_language.get()
    process_subdirs = app.process_subdirs.get()

    threading.Thread(
        target=run_translation,
        args=(app, source_path, target_language, process_subdirs),
        daemon=True,
    ).start()


def pause_translation(app):
    if app.is_processing and not app.pause_flag.is_set():
        app.pause_flag.set()
        app.pause_button.configure(state="disabled")
        app.resume_button.configure(state="normal")
        app.log_message("Pausa solicitada…")


def resume_translation(app):
    if app.is_processing and app.pause_flag.is_set():
        app.pause_flag.clear()
        app.pause_button.configure(state="normal")
        app.resume_button.configure(state="disabled")
        app.log_message("Continuação solicitada…")


def cancel_translation(app):
    if app.is_processing:
        app.cancel_flag.set()
        app.pause_flag.clear()
        app.pause_button.configure(state="disabled")
        app.resume_button.configure(state="disabled")
        app.cancel_button.configure(state="disabled")
        app.log_message("Cancelamento solicitado…")


def reset_buttons(app):
    app.start_button.configure(state="normal")
    app.pause_button.configure(state="disabled")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="disabled")


def show_db_stats(app):
    show_database_stats(app)


def export_csv(app):
    export_translations_csv(app)


def import_csv(app):
    import_translations_csv(app)


def backup_database(app):
    backup_database_file(app)


def restore_database(app):
    restore_database_file(app)


def apply_automatic_rules(app):
    apply_auto_rules_to_database(app, target_language=app.target_language.get())


def _finish_metadata_normalization(app, summary=None, error=None):
    app.is_processing = False
    reset_buttons(app)
    if error:
        messagebox.showerror("Normalizar PGN", f"Erro ao normalizar PGN:\n{error}")
        app.log_message(f"[ERRO] Normalizacao PGN falhou: {error}")
        return

    app.progress.set(1)
    app.log_message(
        "Normalizacao PGN concluida: "
        f"{summary['changed_files']} arquivo(s) alterado(s), "
        f"{summary['unchanged_files']} sem alteracao, "
        f"{summary['changes']} correcao(oes)."
    )
    if summary["skipped_normalized"]:
        app.log_message(
            f"Arquivos -NORM.pgn ignorados: {summary['skipped_normalized']}"
        )
    messagebox.showinfo(
        "Normalizar PGN",
        (
            "Normalizacao concluida.\n\n"
            f"Arquivos analisados: {summary['files']}\n"
            f"Arquivos alterados: {summary['changed_files']}\n"
            f"Sem alteracao: {summary['unchanged_files']}\n"
            f"Correcoes aplicadas: {summary['changes']}"
        ),
    )


def normalize_pgn_metadata(app):
    if app.is_processing:
        return

    source_path = app.source_path.get().strip()
    if not source_path:
        messagebox.showerror("Erro", "Selecione um arquivo ou pasta PGN.")
        return

    if not os.path.exists(source_path):
        messagebox.showerror("Erro", "O caminho informado nao existe.")
        return

    confirmed = messagebox.askyesno(
        "Normalizar PGN",
        (
            "Corrigir metadados PGN usando spelling_ssp/spelling.ssp?\n\n"
            "Apenas tags White, Black, Site, Event e Round serao alteradas.\n"
            "Comentarios, lances e variacoes nao serao modificados.\n"
            "Os arquivos de saida serao criados com sufixo -NORM.pgn."
        ),
    )
    if not confirmed:
        return

    app.log_text.configure(state="normal")
    app.log_text.delete("1.0", tk.END)
    app.log_text.configure(state="disabled")

    app.is_processing = True
    app.start_button.configure(state="disabled")
    app.pause_button.configure(state="disabled")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="disabled")
    app.progress.set(0)

    def worker():
        try:
            summary = normalize_pgn_metadata_path(
                source_path,
                process_subdirs=app.process_subdirs.get(),
                log_message=app.log_message,
                progress_callback=lambda value: app.root.after(
                    0,
                    lambda v=value: app.progress.set(v),
                ),
            )
        except Exception as exc:
            app.root.after(0, lambda e=exc: _finish_metadata_normalization(app, error=e))
            return

        app.root.after(
            0,
            lambda result=summary: _finish_metadata_normalization(app, summary=result),
        )

    threading.Thread(target=worker, daemon=True).start()


def open_edit_window(app):
    open_translation_editor(app)


def open_glossary_window(app):
    open_glossary_editor(app)
