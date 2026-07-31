"""Confirmacao que exige o usuario DIGITAR uma palavra, e nao so clicar em "Sim".

O programa ja tem confirmacoes por `messagebox.askyesno`, e elas bastam para o
que e reversivel: restaurar um backup, importar um CSV, aplicar as regras
automaticas. Todas essas tiram um backup antes e podem ser desfeitas voltando a
ele.

Zerar o banco de traducoes e zerar o glossario nao sao dessa familia. O que elas
apagam e o trabalho acumulado do usuario — 201 mil traducoes, 7 mil regras — e um
"Sim" e um clique a um pixel de distancia do "Não". Digitar a palavra e o que
transforma o gesto em decisao: nao ha como fazer isso por engano, nem por um
duplo clique que pegou o dialogo no caminho.

O modulo nao decide o que apagar nem apaga nada: ele so pergunta.
"""

import tkinter as tk

import customtkinter as ctk

from .window_utils import bring_window_to_front


# A palavra e "apagar", e nao "delete" (ROADMAP 22.12). O dialogo e todo em
# portugues, o botao dele se chama "Apagar", e quem digitava "apagar" — a leitura
# mais natural do que esta na tela — era RECUSADO sem explicacao. Uma barreira
# que existe para transformar clique em decisao nao pode falhar por vocabulario.
CONFIRMATION_WORD = "apagar"

# "delete" continua aceito por uma versao. Quem usa o programa ha meses tem a
# palavra antiga na memoria dos dedos, e recusa-la de repente e a mesma
# frustracao pelo lado oposto. Sai na proxima que mexer neste arquivo.
LEGACY_CONFIRMATION_WORDS = ("delete",)

# O botao de apagar tem duas caras, e a diferenca precisa ser visivel de longe.
# O `state="disabled"` do CustomTkinter escurece o fundo padrao, mas sobre um
# vermelho saturado o resultado e quase o mesmo tom — conferido na janela de
# verdade, as duas capturas ficaram indistinguiveis. Um botao que parece
# clicavel e nao faz nada le-se como "o programa quebrou", e nao como "voce
# ainda nao digitou a palavra".
CONFIRM_ENABLED_COLOR = ("#b91c1c", "#7f1d1d")
CONFIRM_DISABLED_COLOR = ("#d1d5db", "#374151")


def confirmation_accepted(text, word=CONFIRMATION_WORD):
    """O que foi digitado libera a acao?

    Funcao pura, e separada do dialogo de proposito: e a regra que decide, e
    querer testa-la nao pode exigir abrir uma janela.

    Aceita espaco nas pontas e qualquer caixa. Exigir a palavra exatamente
    minuscula e sem espaco nao acrescenta seguranca nenhuma — quem digitou
    "APAGAR " decidiu tanto quanto quem digitou "apagar" —, e so produz um
    dialogo que recusa sem dizer por que.

    A palavra ANTIGA tambem passa, e so quando o dialogo esta pedindo a padrao:
    um chamador que peca outra palavra qualquer nao ganha `delete` de brinde.
    """
    digitado = (text or "").strip().casefold()
    if digitado == word.strip().casefold():
        return True
    if word == CONFIRMATION_WORD:
        return digitado in {antiga.casefold() for antiga in LEGACY_CONFIRMATION_WORDS}
    return False


def ask_typed_confirmation(parent, title, message, word=CONFIRMATION_WORD):
    """Abre o dialogo e devolve `True` so se a palavra foi digitada.

    E modal (`grab_set`) e sincrono (`wait_window`): quem chama recebe a resposta
    como receberia de um `askyesno`, e nao por callback. As acoes que usam isto
    comecam apagando, entao devolver o controle antes da resposta so criaria a
    chance de a janela de tras ser clicada no meio.

    Fechar no X ou no Esc e "não". Nao ha caminho em que sumir com o dialogo
    signifique seguir adiante.
    """
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.geometry("520x300")
    win.resizable(False, False)
    win.transient(parent)
    bring_window_to_front(win, parent)
    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)

    resposta = {"ok": False}
    digitado = tk.StringVar(master=win, value="")

    ctk.CTkLabel(
        win,
        text=message,
        anchor="w",
        justify=tk.LEFT,
        wraplength=470,
    ).grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 8))

    ctk.CTkLabel(
        win,
        text=f"Para confirmar, digite  {word}  abaixo:",
        anchor="w",
        justify=tk.LEFT,
    ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 4))

    entrada = ctk.CTkEntry(win, textvariable=digitado, placeholder_text=word)
    entrada.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))

    botoes = ctk.CTkFrame(win, fg_color="transparent")
    botoes.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
    botoes.columnconfigure(0, weight=1)

    def cancelar():
        resposta["ok"] = False
        fechar()

    def confirmar():
        # Confere de novo em vez de confiar no estado do botao: o `trace` que o
        # habilita e um efeito colateral da digitacao, e um caminho que o
        # desligue (um `invoke()` direto, por exemplo) nao pode virar uma
        # confirmacao que ninguem digitou.
        if not confirmation_accepted(digitado.get(), word):
            return
        resposta["ok"] = True
        fechar()

    def fechar():
        try:
            win.grab_release()
            win.destroy()
        except tk.TclError:  # pragma: no cover - janela ja destruida
            pass

    btn_cancel = ctk.CTkButton(botoes, text="Cancelar", width=120, command=cancelar)
    btn_cancel.grid(row=0, column=1, padx=(0, 8))
    btn_ok = ctk.CTkButton(
        botoes,
        text="Apagar",
        width=120,
        command=confirmar,
        state="disabled",
        fg_color=CONFIRM_DISABLED_COLOR,
        hover_color=("#991b1b", "#991b1b"),
        text_color=("gray40", "gray60"),
    )
    btn_ok.grid(row=0, column=2)

    def atualizar(*_args):
        liberado = confirmation_accepted(digitado.get(), word)
        btn_ok.configure(
            state="normal" if liberado else "disabled",
            fg_color=CONFIRM_ENABLED_COLOR if liberado else CONFIRM_DISABLED_COLOR,
            text_color=("white", "white") if liberado else ("gray40", "gray60"),
        )

    digitado.trace_add("write", atualizar)
    entrada.bind("<Return>", lambda _event: confirmar())
    win.bind("<Escape>", lambda _event: cancelar())
    win.protocol("WM_DELETE_WINDOW", cancelar)

    try:
        win.grab_set()
    except tk.TclError:  # pragma: no cover - sem gerenciador de janelas
        pass
    entrada.focus_set()

    parent.wait_window(win)
    return resposta["ok"]
