"""A tela de Configuracoes (garantia M4, ROADMAP 28.10).

Ate aqui `utf8_bom` e `wrap_columns` so existiam no JSON editado a mao — o
mesmo JSON que o Bloco de Notas ja apagou uma vez (ROADMAP 12.1). Esta janela
da a cada opcao do usuario um controle, e grava pela MESMA porta que as outras
janelas (`update_settings`, garantia R4): salvar daqui nunca apaga um rascunho
que o editor gravou enquanto ela estava aberta.

O que ela mostra e o que `settings.USER_OPTION_SECTIONS` declara, e um teste
enumera as chaves de la contra os controles daqui. A pasta de dados aparece,
mas nao se edita: ela e decidida antes de o programa abrir (`app_paths`), e
fingir um campo editavel para algo que so muda por variavel de ambiente seria
prometer o que a tela nao faz.

Sobre o BOM, sem vender o que ele nao e: a memoria de 2026-08-03 registra que
o caso dos acentos no ChessBase foi resolvido pela promocao para UTF-8, e que
o BOM sozinho nunca resolveria. O texto da tela diz o que o BOM faz, e so.
"""

import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
import unicodedata

import customtkinter as ctk

from . import api_keys, app_paths, first_run
from .editor_common import ERROR_TEXT_COLOR, MUTED_TEXT_COLOR, OK_TEXT_COLOR
from .editor_widgets import flash_message
from .llm_providers import PROVIDERS, anthropic_sdk_available, check_credentials, model_setting_key
from .pgn_positions import chess_available
from .pgn_utils import PGN_EXPORT_LINE_WIDTH
from .personal_dictionary import PersonalDictionary
from .settings import (
    APPEARANCE_KEY,
    APPEARANCE_THEMES,
    BOARD_KEY,
    CTK_APPEARANCE_MODES,
    LLM_KEY,
    MIN_WRAP_COLUMNS,
    OUTPUT_KEY,
    WRITING_KEY,
    WRITING_RULE_NAMES,
    change_disabled_writing_rules,
    load_settings,
    parse_wrap_columns,
    read_appearance_settings,
    read_board_settings,
    read_llm_settings,
    read_output_settings,
    read_writing_settings,
    notify_writing_settings_changed,
    writing_settings_revision,
    write_settings_sections,
)
from .writing_controller import get_shared_writing_assistant
from .writing_types import AssistantStatus, WritingRequest
from .window_utils import bring_window_to_front

# Rotulo -> valor gravado. A ordem e a do seletor.
THEME_LABELS = {"Sistema": "system", "Claro": "light", "Escuro": "dark"}
THEME_BY_VALUE = {valor: rotulo for rotulo, valor in THEME_LABELS.items()}
CATEGORY_LABELS = {
    "SPELLING": "Ortografia", "NOMINAL_AGREEMENT": "Concordância nominal",
    "VERBAL_AGREEMENT": "Concordância verbal", "GRAMMAR": "Gramática",
    "PUNCTUATION": "Pontuação", "REPEATED_WORD": "Palavras repetidas",
}
assert tuple(THEME_LABELS.values()) == APPEARANCE_THEMES


def apply_appearance(theme):
    """Liga o tema no CustomTkinter. Separado para o teste substituir."""
    ctk.set_appearance_mode(CTK_APPEARANCE_MODES[theme])


class SettingsWindow:
    """A janela. Le o arquivo na abertura e grava no Salvar, secao por secao."""

    MIN_SIZE = (620, 650)
    HINT_WRAP = 520
    # A altura do corpo rolavel: as cinco secoes requerem ~1.000 px e a tela
    # nao tem isso; o corpo rola e o "Salvar" fica sempre a vista embaixo.
    BODY_HEIGHT = 540

    def __init__(self, app):
        self.app = app
        # `(secao, chave) -> widget`: o que a garantia M4 confere. Cada opcao de
        # `USER_OPTION_SECTIONS` precisa aparecer aqui, ou o teste acusa.
        self.controls = {}

        settings = load_settings()
        self.output = read_output_settings(settings)
        self.appearance = read_appearance_settings(settings)
        self.board = read_board_settings(settings)
        self.llm = read_llm_settings(settings)
        self.writing = read_writing_settings(settings)
        self._writing_revision = writing_settings_revision()
        self._writing_closed = False
        self._writing_after = None
        self._writing_future = None
        self._writing_success = None
        self._writing_testing = False
        self._writing_start_requested = False
        self._writing_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="writing-settings")
        self._writing_assistant = None
        # As chaves NAO sao lidas para a tela (K1): o campo nasce vazio, o
        # placeholder diz o estado, e so o que for digitado e gravado.
        self.clear_key_vars = {}
        self.key_entries = {}
        self.model_vars = {}

        self.build()
        if not hasattr(app, "writing_settings_windows"):
            app.writing_settings_windows = []
        app.writing_settings_windows.append(self)
        self.win.bind("<Destroy>", self._destroy_writing_settings, add="+")
        self.poll_writing_settings()

    # ------------------------------------------------------------- construcao

    def build(self):
        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title("Configurações")
        # Medido: a janela requer 580 x 633 com os textos de ajuda requebrados
        # em 540 px; o minimo fica acima disso para nada ser cortado, e um
        # teste confere o requerido contra o minimo.
        self.win.geometry("680x700")
        self.win.minsize(*self.MIN_SIZE)
        self.win.transient(self.app.root)
        # `maximize=False`: e um formulario de meia duzia de campos, e
        # maximiza-lo seria esticar seis controles por um monitor inteiro.
        bring_window_to_front(self.win, self.app.root, maximize=False)
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

        # O corpo rola (ROADMAP 28.7 trouxe a quinta secao, e as cinco nao
        # cabem numa tela de notebook); os botoes ficam fora dele, sempre a vista.
        self.body = ctk.CTkScrollableFrame(
            self.win, height=self.BODY_HEIGHT, fg_color="transparent"
        )
        self.body.grid(row=0, column=0, sticky="nsew", padx=(6, 0))
        self.body.columnconfigure(0, weight=1)

        self.build_output_section()
        self.build_appearance_section()
        self.build_board_section()
        self.build_llm_section()
        self.build_data_dir_section()
        self.build_writing_section()
        self.build_actions()

    def build_writing_section(self):
        frame = self.section(5, "Revisão linguística")
        self.spelling_var = tk.BooleanVar(master=self.win, value=self.writing["spelling_enabled"])
        self.grammar_var = tk.BooleanVar(master=self.win, value=self.writing["grammar_enabled"])
        for row, key, variable, label in (
            (1, "spelling_enabled", self.spelling_var, "Verificar ortografia"),
            (2, "grammar_enabled", self.grammar_var, "Verificar concordância (experimental, local)"),
        ):
            checkbox = ctk.CTkCheckBox(frame, text=label, variable=variable)
            checkbox.grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=4)
            self.controls[(WRITING_KEY, key)] = checkbox
        self.writing_status_label = ctk.CTkLabel(frame, text="Não iniciado", anchor="w", justify=tk.LEFT, wraplength=self.HINT_WRAP)
        self.writing_status_label.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10)
        self.btn_test_writing = ctk.CTkButton(frame, text="Testar revisão local", command=self.test_writing)
        self.btn_test_writing.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=4)
        self.hint(frame, 5, "As opções passam a valer ao salvar. O teste usa uma frase de exemplo local; nenhum comentário é enviado à internet.")
        categories = ctk.CTkFrame(frame, fg_color="transparent")
        categories.grid(row=6, column=0, columnspan=2, sticky="ew", padx=10)
        self.category_vars = {}
        for index, (category, label) in enumerate(CATEGORY_LABELS.items()):
            variable = tk.BooleanVar(master=self.win, value=category in self.writing["visible_categories"])
            self.category_vars[category] = variable
            ctk.CTkCheckBox(categories, text=label, variable=variable).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12), pady=4)
        self.controls[(WRITING_KEY, "visible_categories")] = categories
        self.hint(frame, 7, "Categorias exibidas no painel e no texto. Ocultar não altera a tradução.")
        ctk.CTkLabel(frame, text="Vocabulário pessoal (todos os livros)", anchor="w").grid(row=8, column=0, columnspan=2, sticky="w", padx=10)
        self.word_search_var = tk.StringVar(master=self.win)
        ctk.CTkLabel(frame, text="Pesquisar palavra:", anchor="w").grid(row=9, column=0, sticky="w", padx=10)
        search = ctk.CTkEntry(frame, textvariable=self.word_search_var)
        search.grid(row=9, column=1, sticky="ew", padx=10)
        self.word_search_var.trace_add("write", lambda *_: self.refresh_vocabulary())
        self.word_list = tk.Listbox(frame, height=5, exportselection=False)
        self.word_list.grid(row=10, column=0, columnspan=2, sticky="ew", padx=10, pady=4)
        self.word_entry_var = tk.StringVar(master=self.win)
        ctk.CTkEntry(frame, textvariable=self.word_entry_var).grid(row=11, column=0, sticky="ew", padx=10)
        self.btn_add_word = ctk.CTkButton(frame, text="Adicionar palavra", command=self.add_vocabulary_word)
        self.btn_add_word.grid(row=11, column=1, sticky="w", padx=10)
        self.btn_remove_word = ctk.CTkButton(frame, text="Remover selecionada…", command=self.remove_vocabulary_word)
        self.btn_remove_word.grid(row=12, column=0, columnspan=2, sticky="w", padx=10, pady=4)
        ctk.CTkLabel(frame, text="Regras desativadas", anchor="w").grid(row=13, column=0, columnspan=2, sticky="w", padx=10)
        self.rule_list = tk.Listbox(frame, height=4, exportselection=False)
        self.rule_list.grid(row=14, column=0, columnspan=2, sticky="ew", padx=10, pady=4)
        self.controls[(WRITING_KEY, "disabled_rule_ids")] = self.rule_list
        self.btn_reactivate_rule = ctk.CTkButton(frame, text="Reativar selecionada", command=self.reactivate_rule)
        self.btn_reactivate_rule.grid(row=15, column=0, sticky="w", padx=10, pady=4)
        self.btn_reactivate_all = ctk.CTkButton(frame, text="Reativar todas", command=self.reactivate_all_rules)
        self.btn_reactivate_all.grid(row=15, column=1, sticky="w", padx=10, pady=4)
        self.writing_message_label = ctk.CTkLabel(frame, text="", anchor="w", wraplength=self.HINT_WRAP)
        self.writing_message_label.grid(row=16, column=0, columnspan=2, sticky="ew", padx=10, pady=4)
        self.refresh_vocabulary()
        self.refresh_disabled_rules()

    def writing_values(self):
        return {
            "spelling_enabled": bool(self.spelling_var.get()),
            "grammar_enabled": bool(self.grammar_var.get()),
            "visible_categories": [key for key, variable in self.category_vars.items() if variable.get()],
        }

    def refresh_vocabulary(self):
        if self._writing_closed:
            return
        try:
            words = PersonalDictionary().list_words()
        except (OSError, ValueError):
            self.writing_message_label.configure(text="Não foi possível ler o vocabulário pessoal.")
            return
        query = unicodedata.normalize("NFC", self.word_search_var.get()).casefold()
        self.word_list.delete(0, tk.END)
        for word in words:
            if query in unicodedata.normalize("NFC", word).casefold():
                self.word_list.insert(tk.END, word)

    def refresh_disabled_rules(self):
        self._disabled_rules = read_writing_settings(load_settings())["disabled_rule_ids"]
        self.rule_list.delete(0, tk.END)
        for rule in self._disabled_rules:
            name = WRITING_RULE_NAMES.get(rule)
            self.rule_list.insert(tk.END, f"{rule} — {name}" if name else rule)

    def _start_writing_job(self, work, success):
        if self._writing_closed or self._writing_future is not None:
            return False
        self._writing_success = success
        self._writing_future = self._writing_executor.submit(work)
        self._writing_job_controls("disabled")
        return True

    def _writing_job_controls(self, state):
        for button in (self.btn_test_writing, self.btn_add_word, self.btn_remove_word,
                       self.btn_reactivate_rule, self.btn_reactivate_all):
            button.configure(state=state)

    def add_vocabulary_word(self):
        word = self.word_entry_var.get().strip()
        if not word:
            self.writing_message_label.configure(text="Digite uma palavra.")
            return
        def added(changed):
            self.writing_message_label.configure(text="Palavra adicionada." if changed else "A palavra já existe no vocabulário.")
            if changed:
                self.word_entry_var.set("")
        def work():
            changed = PersonalDictionary().add(word)
            if changed:
                notify_writing_settings_changed()
            return changed
        self._start_writing_job(work, added)

    def remove_vocabulary_word(self):
        selected = self.word_list.curselection()
        if not selected or self._writing_future is not None:
            return
        word = self.word_list.get(selected[0])
        if not messagebox.askyesno("Vocabulário pessoal", f"Remover “{word}” do vocabulário de todos os livros?", parent=self.win):
            return
        def work():
            changed = PersonalDictionary().remove(word)
            if changed:
                notify_writing_settings_changed()
            return changed
        self._start_writing_job(work, lambda _changed: self.writing_message_label.configure(text="Vocabulário atualizado."))

    def reactivate_rule(self):
        selected = self.rule_list.curselection()
        if selected:
            rule = self._disabled_rules[selected[0]]
            self._start_writing_job(lambda: change_disabled_writing_rules(enable=[rule]), self._rules_reactivated)

    def reactivate_all_rules(self):
        self._start_writing_job(lambda: change_disabled_writing_rules(enable_all=True), self._rules_reactivated)

    def _rules_reactivated(self, _value):
        self.writing_message_label.configure(text="Regras reativadas.")

    def _current_writing_assistant(self):
        return (getattr(self.app, "writing_assistant", None)
                or next((editor.writing_assistant for editor in getattr(self.app, "writing_editors", ())
                         if not editor._writing_closed), None)
                or self._writing_assistant)

    def test_writing(self):
        if self._writing_future is not None or self._writing_closed:
            return
        assistant = self._current_writing_assistant() or get_shared_writing_assistant()
        self._writing_assistant = assistant
        self.app.writing_assistant = assistant
        request = WritingRequest("As peças estão no tabuleiro.", 0, "pt", grammar_enabled=bool(self.grammar_var.get()))
        def tested(result):
            self._writing_testing = False
            self.writing_message_label.configure(text="Teste local concluído." if result.mode != "unavailable" else "Teste local indisponível.")
        self._writing_testing = self._start_writing_job(lambda: assistant.analyze(request), tested)

    def poll_writing_settings(self):
        if self._writing_closed:
            return
        if self._writing_after is not None:
            self.win.after_cancel(self._writing_after)
            self._writing_after = None
        revision = writing_settings_revision()
        if revision != self._writing_revision:
            current = read_writing_settings(load_settings())
            # Keep unsaved choices; untouched controls follow other windows.
            local = self.writing_values()
            for key, variable in (("spelling_enabled", self.spelling_var), ("grammar_enabled", self.grammar_var)):
                if local[key] == self.writing[key]:
                    variable.set(current[key])
            if local["visible_categories"] == self.writing["visible_categories"]:
                for key, variable in self.category_vars.items():
                    variable.set(key in current["visible_categories"])
            self.writing = current
            self._writing_revision = revision
            assistant = self._current_writing_assistant()
            if assistant is not None:
                assistant.invalidate_cache()
            self.refresh_vocabulary()
            self.refresh_disabled_rules()
        future = self._writing_future
        if future is not None and future.done():
            self._writing_future = None
            success, self._writing_success = self._writing_success, None
            try:
                result = future.result()
            except Exception:
                self._writing_testing = False
                self.writing_message_label.configure(text="Não foi possível concluir a operação local. Tente novamente.")
            else:
                success(result)
            self._writing_job_controls("normal")
        if self._writing_start_requested and self._writing_future is None:
            self._writing_start_requested = False
            if self.writing["grammar_enabled"]:
                self.test_writing()
        assistant = self._current_writing_assistant()
        status = assistant.status() if assistant is not None else AssistantStatus("stopped", "unavailable")
        diagnostic = status.diagnostic
        if not (self.writing["spelling_enabled"] or self.writing["grammar_enabled"]):
            label, diagnostic = "Não iniciado", "Revisão linguística desativada."
        elif status.state in {"starting", "restarting"} or self._writing_testing:
            label = "Iniciando"
        elif status.state == "stopped":
            label = "Não iniciado"
        else:
            label = {"full": "Completo", "spelling_only": "Somente ortografia", "unavailable": "Indisponível"}[status.mode]
            if not self.writing["grammar_enabled"] and status.mode == "full":
                label = "Somente ortografia"
        self.writing_status_label.configure(text=f"{label}\n{diagnostic}".rstrip())
        self._writing_after = self.win.after(100, self.poll_writing_settings)

    def _destroy_writing_settings(self, event):
        if event.widget is not self.win or self._writing_closed:
            return
        self._writing_closed = True
        if self._writing_after is not None:
            self.win.after_cancel(self._writing_after)
            self._writing_after = None
        self._writing_executor.shutdown(wait=False, cancel_futures=True)
        if self in self.app.writing_settings_windows:
            self.app.writing_settings_windows.remove(self)

    def section(self, row, title):
        frame = ctk.CTkFrame(self.body, corner_radius=8)
        frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(12 if row == 0 else 0, 10))
        frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            frame, text=title, anchor="w", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4))
        return frame

    def hint(self, parent, row, text, columnspan=2):
        ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            justify=tk.LEFT,
            wraplength=self.HINT_WRAP,
            text_color=MUTED_TEXT_COLOR,
        ).grid(row=row, column=0, columnspan=columnspan, sticky="w", padx=10, pady=(0, 6))

    def build_output_section(self):
        frame = self.section(0, "Gravação dos PGN traduzidos")

        self.bom_var = tk.BooleanVar(value=self.output["utf8_bom"])
        bom = ctk.CTkCheckBox(
            frame, text="UTF-8 com BOM", variable=self.bom_var, onvalue=True, offvalue=False
        )
        bom.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 0))
        self.controls[(OUTPUT_KEY, "utf8_bom")] = bom
        self.hint(
            frame,
            2,
            "Marca o arquivo com a assinatura UTF-8. Alguns programas do Windows "
            "leem UTF-8 sem ela como ANSI e mostram os acentos trocados; outros "
            "(git, leitores estritos) estranham a assinatura. Desligado por padrão.",
        )

        ctk.CTkLabel(frame, text="Requebra dos comentários (colunas)", anchor="w").grid(
            row=3, column=0, sticky="w", padx=10, pady=(6, 0)
        )
        self.wrap_var = tk.StringVar(
            value=str(self.output["wrap_columns"]) if self.output["wrap_columns"] else "0"
        )
        wrap = ctk.CTkEntry(frame, width=90, textvariable=self.wrap_var, justify="right")
        wrap.grid(row=3, column=1, sticky="w", padx=10, pady=(6, 0))
        self.controls[(OUTPUT_KEY, "wrap_columns")] = wrap
        self.hint(
            frame,
            4,
            f"0 desliga (comentário em linha única, o comportamento de sempre). "
            f"{PGN_EXPORT_LINE_WIDTH} é o export format do padrão PGN, o que "
            f"editora espera receber. Mínimo {MIN_WRAP_COLUMNS}. Só o espaço em "
            f"branco muda; vale a partir da próxima tradução.",
        )

    def build_appearance_section(self):
        frame = self.section(1, "Aparência")

        ctk.CTkLabel(frame, text="Tema", anchor="w").grid(
            row=1, column=0, sticky="w", padx=10, pady=(4, 0)
        )
        self.theme_var = tk.StringVar(value=THEME_BY_VALUE[self.appearance["theme"]])
        theme = ctk.CTkSegmentedButton(
            frame, values=list(THEME_LABELS), variable=self.theme_var
        )
        theme.grid(row=1, column=1, sticky="w", padx=10, pady=(4, 0))
        self.controls[(APPEARANCE_KEY, "theme")] = theme
        self.hint(
            frame,
            2,
            "\"Sistema\" segue o tema do Windows. A troca vale ao salvar, para "
            "esta e para as outras janelas abertas.",
        )

    def build_board_section(self):
        frame = self.section(2, "Tabuleiro")
        self.fen_var = tk.BooleanVar(value=self.board["fen"])
        fen = ctk.CTkCheckBox(
            frame,
            text="Calcular a posição (FEN) de cada comentário ao traduzir",
            variable=self.fen_var,
            onvalue=True,
            offvalue=False,
        )
        fen.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 0))
        self.controls[(BOARD_KEY, "fen")] = fen
        if chess_available():
            aviso = "O pacote python-chess está instalado."
        else:
            aviso = (
                "O pacote python-chess NÃO está instalado nesta máquina, então "
                "nada é calculado e o quadro não aparece; desligar aqui só cala "
                "o aviso do log."
            )
        self.hint(
            frame,
            2,
            f"O editor mostra o tabuleiro da linha aberta. Custa cerca de 2 s "
            f"por 800 KB de PGN, na vez de cada arquivo. {aviso}",
        )

    def build_llm_section(self):
        frame = self.section(3, "Modelos de linguagem (Claude, ChatGPT, DeepSeek)")
        frame.columnconfigure(1, weight=1)
        for coluna, titulo in ((1, "Chave de API"), (2, "Modelo")):
            ctk.CTkLabel(frame, text=titulo, anchor="w", text_color=MUTED_TEXT_COLOR).grid(
                row=1, column=coluna, sticky="w", padx=(10 if coluna == 1 else 4, 4)
            )
        linha = 1
        for spec in PROVIDERS.values():
            linha += 1
            ctk.CTkLabel(frame, text=spec.label, anchor="w").grid(
                row=linha, column=0, sticky="w", padx=10, pady=(2, 0)
            )
            # Sem `textvariable`, de proposito: o CTkEntry so mostra o
            # placeholder (o estado da chave) quando nao ha variavel ligada.
            entrada = ctk.CTkEntry(
                frame,
                width=200,
                show="\u2022",
                placeholder_text=self.describe_key_state(spec),
            )
            entrada.grid(row=linha, column=1, sticky="ew", padx=(10, 4), pady=(2, 0))
            self.key_entries[spec.id] = entrada
            chave_modelo = model_setting_key(spec.id)
            self.model_vars[spec.id] = tk.StringVar(value=self.llm[chave_modelo])
            modelo = ctk.CTkEntry(frame, width=150, textvariable=self.model_vars[spec.id])
            modelo.grid(row=linha, column=2, sticky="w", padx=4, pady=(2, 0))
            self.controls[(LLM_KEY, chave_modelo)] = modelo
            self.clear_key_vars[spec.id] = tk.BooleanVar(value=False)
            if api_keys.stored_key_state(spec.id) != "ausente":
                ctk.CTkCheckBox(
                    frame,
                    text="apagar",
                    width=70,
                    variable=self.clear_key_vars[spec.id],
                    onvalue=True,
                    offvalue=False,
                ).grid(row=linha, column=3, sticky="w", padx=(4, 10), pady=(2, 0))
        # "Testar": uma requisicao gratuita por provedor com chave (a API de
        # modelos), na thread de fundo, com o resultado voltando pela fila e um
        # `after` agendado daqui — a thread nunca toca em widget (C1), e um
        # `after` chamado de dentro dela nao funciona fora do `mainloop`.
        linha += 1
        self.btn_test_keys = ctk.CTkButton(
            frame, text="Testar chaves e modelos", width=190, command=self.test_credentials
        )
        self.btn_test_keys.grid(row=linha, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 0))
        linha += 1
        self.test_result_label = ctk.CTkLabel(
            frame, text="", anchor="w", justify=tk.LEFT, wraplength=self.HINT_WRAP
        )
        self.test_result_label.grid(row=linha, column=0, columnspan=4, sticky="w", padx=10, pady=(2, 0))
        self._test_queue = queue.Queue()
        self._test_results = {}
        if anthropic_sdk_available():
            sdk = "O pacote anthropic (para o Claude) está instalado."
        else:
            sdk = (
                "O pacote anthropic NÃO está instalado: sem ele o Claude não pode "
                "ser usado (uv sync --extra llm); ChatGPT e DeepSeek não precisam dele."
            )
        self.hint(
            frame,
            linha + 1,
            "Com pelo menos uma chave gravada, \"Iniciar tradução\" pergunta qual "
            "motor usar. A chave fica em chaves-api.json na pasta de dados, cifrada "
            "com o DPAPI do Windows (só esta conta, nesta máquina); uma variável "
            "de ambiente (ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY) tem "
            "precedência. O campo da chave nasce vazio de propósito: digite para "
            "trocar, marque \"apagar\" para remover. O nome do modelo é o que a "
            f"API do provedor aceita; confira no console dele. {sdk}",
            columnspan=4,
        )

    def test_credentials(self):
        """Confere chave e modelo de cada provedor que tem chave (digitada ou
        gravada), sem gravar nada: o que esta no campo vale para o teste."""
        alvos = []
        for spec in PROVIDERS.values():
            digitada = self.key_entries[spec.id].get().strip()
            chave = digitada or api_keys.load_api_key(spec.id, spec.env_var)
            modelo = self.model_vars[spec.id].get().strip() or spec.default_model
            alvos.append((spec, chave, modelo))
        self._test_results = {
            spec.id: (None, "sem chave") for spec, chave, _m in alvos if not chave
        }
        pendentes = [(spec, chave, modelo) for spec, chave, modelo in alvos if chave]
        self.show_test_results(pendentes)
        if not pendentes:
            return
        self.btn_test_keys.configure(state="disabled")

        def conferir():
            for spec, chave, modelo in pendentes:
                try:
                    resultado = check_credentials(spec.id, modelo, api_key=chave)
                except Exception as exc:  # a rede e de quem a chama
                    resultado = (False, f"erro: {exc}")
                self._test_queue.put((spec.id, resultado))

        threading.Thread(target=conferir, daemon=True).start()
        self.win.after(100, self.poll_test_results)

    def poll_test_results(self):
        """Drena a fila na thread do Tk; para quando todos responderam."""
        try:
            while True:
                provider_id, resultado = self._test_queue.get_nowait()
                self._test_results[provider_id] = resultado
        except queue.Empty:
            pass
        faltam = [spec for spec in PROVIDERS.values() if spec.id not in self._test_results]
        self.show_test_results([(spec, None, None) for spec in faltam])
        if faltam:
            try:
                self.win.after(100, self.poll_test_results)
            except tk.TclError:  # a janela fechou no meio
                pass
            return
        try:
            self.btn_test_keys.configure(state="normal")
        except tk.TclError:
            pass

    def show_test_results(self, pendentes):
        """Uma linha por provedor: o resultado, ou "testando…" enquanto nao ha."""
        ainda = {spec.id for spec, _c, _m in pendentes}
        linhas = []
        for spec in PROVIDERS.values():
            if spec.id in self._test_results:
                ok, texto = self._test_results[spec.id]
                marca = "✓ " if ok else ("✗ " if ok is False else "")
                linhas.append(f"{marca}{spec.label}: {texto}")
            elif spec.id in ainda:
                linhas.append(f"{spec.label}: testando…")
        try:
            self.test_result_label.configure(text="\n".join(linhas))
        except tk.TclError:
            pass

    def describe_key_state(self, spec):
        """O que o campo vazio diz da chave, sem mostra-la (K1)."""
        do_ambiente = api_keys.load_api_key(spec.id, spec.env_var)
        estado = api_keys.stored_key_state(spec.id)
        if do_ambiente and estado == "ausente":
            return f"do ambiente ({spec.env_var}) {api_keys.mask_api_key(do_ambiente)}"
        if estado == "ok":
            gravada = api_keys.load_api_key(spec.id)
            return f"gravada {api_keys.mask_api_key(gravada)}"
        if estado == "ilegivel":
            return "gravada, mas ilegível nesta máquina — digite de novo"
        return "não configurada"

    def build_data_dir_section(self):
        frame = self.section(4, "Pasta de dados")
        self.data_dir_label = ctk.CTkLabel(
            frame,
            text=first_run.describe_data_dir(),
            anchor="w",
            justify=tk.LEFT,
            wraplength=440,
        )
        self.data_dir_label.grid(row=1, column=0, sticky="w", padx=10, pady=(4, 0))
        self.btn_open_data_dir = ctk.CTkButton(
            frame, text="Abrir pasta", width=110, command=self.open_data_dir
        )
        self.btn_open_data_dir.grid(row=1, column=1, sticky="e", padx=10, pady=(4, 0))
        self.hint(
            frame,
            2,
            f"Glossário, banco de traduções, backups, logs e este arquivo de "
            f"configurações vivem aqui. Para usar outra pasta, defina a variável "
            f"de ambiente {app_paths.DATA_DIR_ENV} antes de abrir o programa.",
        )

    def build_actions(self):
        actions = ctk.CTkFrame(self.win, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.status_label = ctk.CTkLabel(actions, text="", anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_cancel = ctk.CTkButton(
            actions, text="Cancelar", width=100, command=self.win.destroy
        )
        self.btn_cancel.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_save = ctk.CTkButton(actions, text="Salvar", width=100, command=self.save)
        self.btn_save.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ acoes

    def values(self):
        """O que a tela gravaria agora: `(secoes, erro)`.

        Separado do `save` para o teste conferir a validacao sem disco — e para
        a razao de uma recusa ser UMA string, escrita na tela e nao num dialogo:
        o campo errado esta a dois centimetros, e um `messagebox` o taparia.
        """
        colunas, erro = parse_wrap_columns(self.wrap_var.get())
        if erro:
            return None, erro
        return {
            OUTPUT_KEY: {
                "utf8_bom": bool(self.bom_var.get()),
                "wrap_columns": colunas,
            },
            APPEARANCE_KEY: {"theme": THEME_LABELS[self.theme_var.get()]},
            BOARD_KEY: {"fen": bool(self.fen_var.get())},
            LLM_KEY: {
                model_setting_key(pid): (var.get().strip() or PROVIDERS[pid].default_model)
                for pid, var in self.model_vars.items()
            },
            WRITING_KEY: {key: value for key, value in self.writing_values().items()
                          if value != self.writing[key]},
        }, None

    def key_changes(self):
        """`{provedor: chave_nova_ou_vazia}` do que a tela pede para gravar.

        So os campos tocados entram: chave digitada grava, "apagar" marcado
        apaga, e o resto fica como esta — nunca se regrava o que nao se leu."""
        mudancas = {}
        for pid, entrada in self.key_entries.items():
            digitada = entrada.get().strip()
            if digitada:
                mudancas[pid] = digitada
            elif self.clear_key_vars[pid].get():
                mudancas[pid] = ""
        return mudancas

    def save(self):
        secoes, erro = self.values()
        if erro:
            flash_message(
                self.status_label, self.win, erro, 6000, text_color=ERROR_TEXT_COLOR
            )
            return False
        mudancas_de_chave = self.key_changes()
        grammar_just_enabled = secoes[WRITING_KEY].get("grammar_enabled") is True
        try:
            write_settings_sections(secoes)
            for pid, chave in mudancas_de_chave.items():
                api_keys.save_api_key(pid, chave)
        except OSError:
            # O aviso ja saiu pelo canal de M3 (`set_settings_warning_handler`);
            # aqui so o que a tela precisa dizer: nada foi gravado.
            flash_message(
                self.status_label,
                self.win,
                "Não foi possível gravar; as configurações continuam como estavam.",
                6000,
                text_color=ERROR_TEXT_COLOR,
            )
            return False
        # O tema so depois de gravado: aplicar antes e falhar na gravacao
        # deixaria a tela num tema que o arquivo nao tem, e a proxima abertura
        # voltaria atras sem explicar.
        tema = secoes[APPEARANCE_KEY]["theme"]
        if tema != self.appearance["theme"]:
            apply_appearance(tema)
            self.appearance["theme"] = tema
        self.output = dict(secoes[OUTPUT_KEY])
        self.llm = dict(secoes[LLM_KEY])
        if secoes[WRITING_KEY]:
            # The event is published by the atomic settings update, only on
            # success. Consume it here too, retaining any concurrent rule IDs.
            self.poll_writing_settings()
        if grammar_just_enabled:
            self._writing_start_requested = True
            self.poll_writing_settings()
        # A chave digitada sai do campo depois de gravada: o campo volta a
        # dizer o estado, e a chave nao fica na tela.
        for pid in mudancas_de_chave:
            self.key_entries[pid].delete(0, tk.END)
            self.clear_key_vars[pid].set(False)
            self.key_entries[pid].configure(
                placeholder_text=self.describe_key_state(PROVIDERS[pid])
            )
        flash_message(
            self.status_label, self.win, "Configurações salvas.", 2500, text_color=OK_TEXT_COLOR
        )
        return True

    def open_data_dir(self):
        # Importado aqui para a janela nao depender de `app_actions`, que
        # importa metade do programa; e a mesma funcao do "Abrir pasta" da
        # janela principal, e o teste a substitui la e aqui.
        from . import app_actions

        pasta = app_paths.data_dir()
        try:
            app_actions.open_path_in_explorer(pasta)
        except OSError as exc:
            messagebox.showerror(
                "Abrir pasta", f"Não foi possível abrir a pasta:\n{pasta}\n\n{exc}"
            )
            return None
        return pasta


def open_settings_window(app):
    """Abre a tela. Devolve a instancia, como as outras janelas."""
    return SettingsWindow(app)
