"""O dialogo do "Iniciar tradução": Google ou um modelo de linguagem? (ROADMAP 28.7)

Aparece so quando ha pelo menos uma chave configurada — sem chave nenhuma o
Google e o unico motor, e perguntar seria um clique a mais por nada. Com
chave, a pergunta e feita SEMPRE, e o motor nunca troca em silencio (a licao
de M1): o que a execucao anterior usou vem pre-selecionado, e so isso.

Um provedor sem chave aparece desligado, com "sem chave — Configurações" ao
lado, em vez de sumir: a lista inteira e o que diz ao usuario que os outros
existem. A chave em si nunca aparece aqui (K1); o que aparece e o modelo.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

import customtkinter as ctk

from .editor_common import MUTED_TEXT_COLOR
from .llm_providers import GOOGLE_PROVIDER, PROVIDERS, model_setting_key
from .window_utils import bring_window_to_front


class ProviderChoiceDialog:
    """A janela. `result` e o id escolhido, ou `None` se cancelou."""

    def __init__(
        self,
        app: Any,
        configured: list[str],
        models: dict[str, str],
        preselected: str = GOOGLE_PROVIDER,
    ) -> None:
        self.app = app
        self.configured = set(configured)
        self.models = models
        self.result: str | None = None
        if preselected not in self.configured and preselected != GOOGLE_PROVIDER:
            preselected = GOOGLE_PROVIDER
        self.choice_var = tk.StringVar(value=preselected)
        self.radios: dict[str, ctk.CTkRadioButton] = {}
        self.build()

    def build(self) -> None:
        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title("Motor de tradução")
        self.win.resizable(False, False)
        self.win.transient(self.app.root)
        bring_window_to_front(self.win, self.app.root, maximize=False)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)

        ctk.CTkLabel(
            self.win,
            text="Usar um modelo de linguagem nesta tradução?",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        opcoes = ctk.CTkFrame(self.win, fg_color="transparent")
        opcoes.grid(row=1, column=0, sticky="ew", padx=16)
        linha = 0
        self.radios[GOOGLE_PROVIDER] = ctk.CTkRadioButton(
            opcoes,
            text="Google (gratuito, o motor de sempre)",
            variable=self.choice_var,
            value=GOOGLE_PROVIDER,
        )
        self.radios[GOOGLE_PROVIDER].grid(row=linha, column=0, sticky="w", pady=3)
        for spec in PROVIDERS.values():
            linha += 1
            modelo = self.models.get(model_setting_key(spec.id), spec.default_model)
            radio = ctk.CTkRadioButton(
                opcoes,
                text=f"{spec.label} — modelo {modelo}",
                variable=self.choice_var,
                value=spec.id,
            )
            radio.grid(row=linha, column=0, sticky="w", pady=3)
            self.radios[spec.id] = radio
            if spec.id not in self.configured:
                radio.configure(state="disabled")
                ctk.CTkLabel(
                    opcoes,
                    text="sem chave — Configurações",
                    text_color=MUTED_TEXT_COLOR,
                ).grid(row=linha, column=1, sticky="w", padx=(10, 0))

        ctk.CTkLabel(
            self.win,
            text=(
                "Um modelo de linguagem custa dinheiro por livro (centavos por "
                "centena de comentários) e a execução fica registrada para "
                "\"Reverter execução\" desfazer o que ele gravou."
            ),
            anchor="w",
            justify=tk.LEFT,
            wraplength=420,
            text_color=MUTED_TEXT_COLOR,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(8, 4))

        botoes = ctk.CTkFrame(self.win, fg_color="transparent")
        botoes.grid(row=3, column=0, sticky="e", padx=16, pady=(4, 14))
        self.btn_cancel = ctk.CTkButton(botoes, text="Cancelar", width=100, command=self.cancel)
        self.btn_cancel.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_start = ctk.CTkButton(
            botoes, text="Iniciar tradução", width=140, command=self.confirm
        )
        self.btn_start.pack(side=tk.RIGHT)
        self.win.bind("<Return>", lambda _e: self.confirm())
        self.win.bind("<Escape>", lambda _e: self.cancel())

    def confirm(self) -> None:
        escolhido = self.choice_var.get()
        if escolhido != GOOGLE_PROVIDER and escolhido not in self.configured:
            # Nao deveria acontecer (o radio esta desligado), mas a guarda e o
            # que impede um motor sem chave de sair daqui como escolha.
            escolhido = GOOGLE_PROVIDER
        self.result = escolhido
        self.close()

    def cancel(self) -> None:
        self.result = None
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def ask_translation_provider(
    app: Any, configured: list[str], models: dict[str, str], preselected: str
) -> str | None:
    """Abre o dialogo modal e devolve a escolha (`None` = cancelou)."""
    dialogo = ProviderChoiceDialog(app, configured, models, preselected)
    try:
        dialogo.win.grab_set()
    except tk.TclError:
        pass
    app.root.wait_window(dialogo.win)
    return dialogo.result
