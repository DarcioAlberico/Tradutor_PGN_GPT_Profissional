import os
import queue
import sys
import threading
import tkinter as tk

from . import app_actions
from .glossario import load_substitutions
from .main_window import setup_main_ui
from .window_utils import bring_window_to_front


class PGNTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PGN Tradutor Pro")
        self.root.geometry("900x650")
        self.root.minsize(900, 600)
        bring_window_to_front(self.root, maximize=True)

        # Variáveis principais
        self.source_path = tk.StringVar()
        self.target_language = tk.StringVar(value="pt")
        self.process_subdirs = tk.BooleanVar(value=True)
        self.is_processing = False
        self.log_queue = queue.Queue()

        self.glossary_substitutions = load_substitutions()
        self.log_message(f"Glossário carregado: {len(self.glossary_substitutions)} entradas")

        # Banco de dados SEMPRE ao lado do script
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.output_db = os.path.join(script_dir, "traducoes.db")

        # Cache de traduções em memória (chave = comentário achatado)
        self.translation_cache = {}

        # Controle de pausa
        self.pause_flag = threading.Event()  # set() => pausado, clear() => rodando
        self.cancel_flag = threading.Event()

        # Configuração da interface
        self.setup_ui()

        # Atualização do log
        self.update_log()

    # ============================
    #       INTERFACE
    # ============================
    def setup_ui(self):
        setup_main_ui(self)

    # ============================
    #   SELEÇÃO DE ARQUIVOS
    # ============================
    def select_file(self):
        app_actions.select_file(self)

    def select_directory(self):
        app_actions.select_directory(self)

    # ============================
    #     SISTEMA DE LOG
    # ============================
    def log_message(self, message: str):
        app_actions.log_message(self, message)

    def update_log(self):
        app_actions.update_log(self)

    # ============================
    #     INICIAR TRADUÇÃO
    # ============================
    def start_translation(self):
        app_actions.start_translation(self)

    # ============================
    #   PAUSAR / CONTINUAR
    # ============================
    def pause_translation(self):
        app_actions.pause_translation(self)

    def resume_translation(self):
        app_actions.resume_translation(self)

    def cancel_translation(self):
        app_actions.cancel_translation(self)

    def _reset_buttons(self):
        app_actions.reset_buttons(self)

    # ============================
    #   FERRAMENTAS DO BANCO
    # ============================
    def show_db_stats(self):
        app_actions.show_db_stats(self)

    def export_csv(self):
        app_actions.export_csv(self)

    def import_csv(self):
        app_actions.import_csv(self)

    def backup_database(self):
        app_actions.backup_database(self)

    def restore_database(self):
        app_actions.restore_database(self)

    # ============================
    #   EDITAR TRADUÇÕES
    # ============================
    def open_edit_window(self):
        app_actions.open_edit_window(self)

    def open_glossary_window(self):
        app_actions.open_glossary_window(self)
