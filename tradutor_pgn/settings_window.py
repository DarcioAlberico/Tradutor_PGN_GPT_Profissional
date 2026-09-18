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

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from . import api_keys, app_paths, first_run
from .editor_common import ERROR_TEXT_COLOR, MUTED_TEXT_COLOR, OK_TEXT_COLOR
from .editor_widgets import flash_message
from .llm_providers import PROVIDERS, anthropic_sdk_available, model_setting_key
from .pgn_positions import chess_available
from .pgn_utils import PGN_EXPORT_LINE_WIDTH
from .settings import (
    APPEARANCE_KEY,
    APPEARANCE_THEMES,
    BOARD_KEY,
    CTK_APPEARANCE_MODES,
    LLM_KEY,
    MIN_WRAP_COLUMNS,
    OUTPUT_KEY,
    load_settings,
    parse_wrap_columns,
    read_appearance_settings,
    read_board_settings,
    read_llm_settings,
    read_output_settings,
    write_settings_sections,
)
from .window_utils import bring_window_to_front

# Rotulo -> valor gravado. A ordem e a do seletor.
THEME_LABELS = {"Sistema": "system", "Claro": "light", "Escuro": "dark"}
THEME_BY_VALUE = {valor: rotulo for rotulo, valor in THEME_LABELS.items()}
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
        # As chaves NAO sao lidas para a tela (K1): o campo nasce vazio, o
        # placeholder diz o estado, e so o que for digitado e gravado.
        self.clear_key_vars = {}
        self.key_entries = {}
        self.model_vars = {}

        self.build()

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
        self.build_actions()

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
