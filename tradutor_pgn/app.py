import queue
import threading
import tkinter as tk

from . import __version__, app_actions, app_paths, first_run
from .app_config import LANGUAGE_NAMES
from .editor_common import window_safe_geometry
from .glossario import set_glossary_error_handler
from .main_window import setup_main_ui
from .settings import (
    load_settings,
    read_main_window_settings,
    write_main_window_settings,
)
from .window_utils import install_callback_error_reporter, restore_or_maximize


# O minimo da janela principal. Estava escrito duas vezes em numeros crus
# (`geometry` e `minsize`), que e a mesma duplicacao que o 22.10 tirou do editor.
MAIN_MIN_WIDTH = 900
MAIN_MIN_HEIGHT = 600


class PGNTranslatorApp:
    def __init__(self, root):
        self.root = root
        # A versao no titulo, e nao so no log: com instalador, "qual versao voce
        # esta rodando?" e a primeira pergunta de qualquer suporte, e a barra de
        # titulo e o unico lugar que o usuario ve sem procurar (ROADMAP 21.6).
        self.root.title(f"PGN Tradutor Pro {__version__}")
        self.root.geometry(f"{MAIN_MIN_WIDTH}x650")
        self.root.minsize(MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)

        # Variáveis principais, restauradas do que a sessao anterior escolheu.
        #
        # O idioma de ORIGEM e a razao de isto existir. Ele e a escolha que mais
        # muda o resultado — decide o `sl=` da API e liga a correcao das letras
        # dos lances (P3) —, e o padrao dele, "Detectar", e justamente o valor
        # que deixa as duas desligadas. Resetar a cada abertura significa que
        # esquecer um clique custa uma execucao inteira traduzida no escuro, e o
        # programa nao teria como avisar depois: o resultado parece pronto.
        escolhas = read_main_window_settings(load_settings(), LANGUAGE_NAMES)
        # Tamanho e posicao, como os dois editores ja faziam (ROADMAP 22.12).
        # Esta era a unica janela do programa que abria maximizada sempre, e num
        # monitor grande isso e uma janela de 900 px de conteudo esticada por
        # 2.560. `restore_or_maximize` decide entre uma coisa e outra num lugar
        # so, porque sao alternativas — pedir as duas faz a restauracao perder.
        restore_or_maximize(
            self.root,
            None,
            window_safe_geometry(
                self.root, escolhas["geometry"], MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT
            )
            if escolhas["geometry"]
            else "",
        )
        self.source_path = tk.StringVar(value=escolhas["source_path"])
        self.target_language = tk.StringVar(value=escolhas["target_language"])
        self.source_language = tk.StringVar(value=escolhas["source_language"])
        self.process_subdirs = tk.BooleanVar(value=escolhas["process_subdirs"])
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

        # ANTES da primeira carga do glossario, e essa e a ordem inteira do
        # assunto: e aqui que a pasta de dados nasce e que o glossario inicial
        # chega nela (ROADMAP 21). Carregar primeiro faria a instalacao nova
        # abrir sem regras e avisar que o arquivo nao existe — o arquivo que
        # estava para ser criado uma linha depois.
        try:
            first_run.prepare_data_dir(self.log_message)
        except OSError as exc:
            # Nao pode impedir o programa de abrir: sem a pasta de dados ele
            # degrada para "sem glossario" (garantia S5), que e recuperavel.
            self.log_message(f"[AVISO] Nao foi possivel preparar a pasta de dados: {exc}")
        self.log_message(first_run.describe_data_dir())

        self.glossary_substitutions = app_actions.load_interactive_glossary(self)
        self.log_message(f"Glossário carregado: {len(self.glossary_substitutions)} entradas")

        # O banco fica na pasta de DADOS, que rodando do fonte e ao lado do
        # script e empacotado e o `%APPDATA%` (ver `app_paths`). E a diferenca
        # entre uma atualizacao que troca o programa e uma que leva o acervo
        # junto (ROADMAP 21).
        self.output_db = app_paths.data_path("traducoes.db")

        # Cache de traduções em memória (chave = comentário achatado)
        self.translation_cache = {}

        # Controle de pausa
        self.pause_flag = threading.Event()  # set() => pausado, clear() => rodando
        self.cancel_flag = threading.Event()

        # Configuração da interface
        self.setup_ui()

        # O X da janela principal passa por `close_main_window` (ROADMAP 22.12):
        # sem handler, ele matava uma traducao em andamento e as janelas filhas
        # sem passar pelos fechamentos delas.
        self.root.protocol("WM_DELETE_WINDOW", self.close_main_window)

        # Atualização do log
        self.update_log()

        # Depois da restauracao acima. **Hoje a ordem nao muda nada** — ligado
        # antes, o `trace` gravaria de volta exatamente o que acabou de ser
        # lido —, e uma mutacao mostrou isso; a primeira versao deste comentario
        # dizia que a ordem evitava um problema atual, e nao evita. Ela existe
        # para o dia em que a leitura ganhar qualquer normalizacao: ai o laco
        # passaria a gravar o valor normalizado por cima do que o usuario tinha.
        self._remember_choices()

        # Retencao de `backups/` e `logs/` (garantia S8). Roda aqui, e nao so
        # quando um backup novo e criado, senao quem parar de editar o glossario
        # fica com a pilha inteira para sempre. Numa thread: sao centenas de
        # arquivos numa pasta com meses de uso.
        app_actions.run_startup_cleanup(self)

        # Se as heuristicas de aviso de qualidade mudaram desde a ultima vez que
        # este banco foi avaliado, a coluna materializada esta com o veredito
        # velho e a garantia R6 esta violada (ROADMAP 16.2). Agendado, com
        # progresso, e sem fazer nada quando ja esta em dia.
        app_actions.run_startup_quality_check(self)

    # ============================
    #       INTERFACE
    # ============================
    def setup_ui(self):
        setup_main_ui(self)

    def _remember_choices(self):
        """Grava as escolhas da janela assim que elas mudam.

        No clique, e nao ao iniciar uma traducao: quem escolhe o idioma e fecha o
        programa sem traduzir escolheu do mesmo jeito, e perder isso reproduz em
        menor escala o problema que a persistencia veio resolver.

        Uma falha de disco aqui nao pode derrubar um clique de radio — lembrar a
        escolha e conveniencia, e a traducao continua usando o que esta na tela.
        """
        def gravar(*_args):
            try:
                write_main_window_settings(
                    {
                        "source_language": self.source_language.get(),
                        "target_language": self.target_language.get(),
                        "process_subdirs": bool(self.process_subdirs.get()),
                        "source_path": self.source_path.get(),
                    }
                )
            except OSError:
                pass

        for variavel in (
            self.source_language,
            self.target_language,
            self.process_subdirs,
            self.source_path,
        ):
            variavel.trace_add("write", gravar)

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

    def close_main_window(self):
        return app_actions.close_main_window(self)

    def _reset_buttons(self):
        app_actions.reset_buttons(self)

    # ============================
    #   FERRAMENTAS DO BANCO
    # ============================
    def show_db_stats(self):
        app_actions.show_db_stats(self)

    def export_csv(self):
        app_actions.export_csv(self)

    def export_tmx(self):
        app_actions.export_tmx(self)

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

    def fix_move_notation(self):
        app_actions.fix_move_notation(self)

    def reevaluate_quality_warnings(self):
        app_actions.reevaluate_quality_warnings(self)

    def reset_translations(self):
        app_actions.reset_translations(self)

    def reset_glossary(self):
        app_actions.reset_glossary(self)

    # ============================
    #   EDITAR TRADUÇÕES
    # ============================
    def open_edit_window(self):
        app_actions.open_edit_window(self)

    def open_glossary_window(self):
        app_actions.open_glossary_window(self)
