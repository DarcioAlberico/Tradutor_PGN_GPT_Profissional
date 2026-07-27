import os
import queue
import sys
import threading
import tkinter as tk

from . import app_actions
from .glossario import set_glossary_error_handler
from .main_window import setup_main_ui
from .window_utils import bring_window_to_front, install_callback_error_reporter


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

        # Antes de qualquer coisa que possa falhar: sob `pythonw` nao ha console,
        # entao sem isto um erro em callback do Tk desaparece sem deixar rastro e
        # a operacao apenas nao acontece (ROADMAP 6.2). Instalado na raiz, vale
        # tambem para as janelas de edicao, que sao `Toplevel` dela.
        install_callback_error_reporter(self.root, log_message=self.log_message)

        # Registrado ANTES da primeira carga: e justamente essa que pode falhar
        # (garantia S5). Sem o handler, o erro so existiria como print, que num
        # app Tk empacotado com `pythonw` nao aparece em lugar nenhum.
        self._glossary_error_shown = None
        set_glossary_error_handler(
            lambda message: app_actions.report_glossary_failure(self, message)
        )

        self.glossary_substitutions = app_actions.load_interactive_glossary(self)
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

        # Retencao de `backups/` e `logs/` (garantia S8). Roda aqui, e nao so
        # quando um backup novo e criado, senao quem parar de editar o glossario
        # fica com a pilha inteira para sempre. Numa thread: sao centenas de
        # arquivos numa pasta com meses de uso.
        app_actions.run_startup_cleanup(self)

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

    def retry_failed_translation(self):
        app_actions.retry_failed_translation(self)

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

    def apply_automatic_rules(self):
        app_actions.apply_automatic_rules(self)

    def normalize_pgn_metadata(self):
        app_actions.normalize_pgn_metadata(self)

    # ============================
    #   EDITAR TRADUÇÕES
    # ============================
    def open_edit_window(self):
        app_actions.open_edit_window(self)

    def open_glossary_window(self):
        app_actions.open_glossary_window(self)
