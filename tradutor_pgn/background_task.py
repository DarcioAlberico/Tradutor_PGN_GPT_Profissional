"""Roda uma operacao demorada fora da thread do Tk, com progresso e cancelamento.

Existe porque varias ferramentas do programa faziam trabalho pesado dentro do
proprio callback do botao. A pior delas, "Aplicar automaticas", segurava a janela
por 38 s no banco real — tempo suficiente para o Windows marcar o programa como
"nao esta respondendo", e sem nenhuma forma de desistir.

O modulo NAO conhece nenhuma tarefa especifica: recebe uma funcao que roda na
thread de trabalho e devolve o que quiser. As duas unicas regras que ele impoe
sao as que a garantia C1 exige — a funcao de trabalho nunca toca em widget, e
tudo o que aparece na tela e agendado com `after` na thread principal.
"""

import threading
import tkinter as tk

import customtkinter as ctk

from .editor_common import MUTED_TEXT_COLOR

from .window_utils import bring_window_to_front


class TaskCanceled(Exception):
    """A tarefa foi interrompida pelo usuario."""


class BackgroundTask:
    """Handle passado para a funcao de trabalho.

    `report(feito, total)` e `cancelado()` sao seguros de chamar da thread de
    trabalho; nenhum dos dois toca em widget.
    """

    def __init__(self, on_progress=None):
        self._cancel = threading.Event()
        self._on_progress = on_progress

    def cancel(self):
        self._cancel.set()

    def cancelado(self):
        return self._cancel.is_set()

    def raise_if_canceled(self):
        if self._cancel.is_set():
            raise TaskCanceled()

    def report(self, feito, total):
        if self._on_progress is not None:
            self._on_progress(feito, total)


def run_with_progress(
    parent,
    title,
    work,
    on_success=None,
    on_error=None,
    on_cancel=None,
    message="Processando...",
    allow_cancel=True,
):
    """Executa `work(task)` numa thread, com uma janela de progresso.

    `work` recebe um `BackgroundTask` e roda FORA da thread do Tk: ele nao pode
    tocar em widget nenhum. O valor que devolver chega em `on_success`, ja de
    volta na thread principal — e o mesmo vale para `on_error` e `on_cancel`.

    A janela de progresso e modal (`grab_set`) de proposito: as operacoes que
    usam isto alteram o banco inteiro, e deixar o resto da interface clicavel
    durante uma delas convida a exatamente o tipo de corrida que o resto do
    projeto passou a semana consertando.
    """
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.geometry("460x170")
    win.resizable(False, False)
    win.transient(parent)
    bring_window_to_front(win, parent)

    win.columnconfigure(0, weight=1)

    label = ctk.CTkLabel(win, text=message, anchor="w", justify=tk.LEFT)
    label.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 6))

    bar = ctk.CTkProgressBar(win, mode="indeterminate")
    bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
    bar.start()

    detail = ctk.CTkLabel(win, text="", anchor="w", text_color=MUTED_TEXT_COLOR)
    detail.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

    botao = ctk.CTkButton(win, text="Cancelar", width=110)
    botao.grid(row=3, column=0, pady=(0, 14))
    if not allow_cancel:
        botao.configure(state="disabled")

    estado = {"determinado": False, "encerrada": False}

    def fechar():
        if estado["encerrada"]:
            return
        estado["encerrada"] = True
        try:
            bar.stop()
            win.grab_release()
            win.destroy()
        except tk.TclError:
            pass

    def mostrar_progresso(feito, total):
        # Chamado na thread principal (ver `progresso`).
        if estado["encerrada"]:
            return
        try:
            if total > 0:
                if not estado["determinado"]:
                    estado["determinado"] = True
                    bar.stop()
                    bar.configure(mode="determinate")
                bar.set(min(1.0, feito / total))
                detail.configure(text=f"{feito:,} de {total:,}".replace(",", "."))
        except tk.TclError:
            pass

    def progresso(feito, total):
        # Chamado da thread de trabalho: so agenda (garantia C1).
        try:
            parent.after(0, lambda f=feito, t=total: mostrar_progresso(f, t))
        except (tk.TclError, RuntimeError):
            pass

    task = BackgroundTask(on_progress=progresso)
    botao.configure(command=lambda: (task.cancel(), botao.configure(state="disabled")))
    win.protocol("WM_DELETE_WINDOW", task.cancel if allow_cancel else (lambda: None))

    try:
        win.grab_set()
    except tk.TclError:
        pass

    def terminar(callback, valor):
        fechar()
        if callback is not None:
            callback(valor)

    def agendar(callback, valor):
        """Devolve o controle para a thread do Tk (garantia C1).

        Tolera a janela ter sumido no meio do caminho: se o usuario fechar o
        programa enquanto a tarefa roda, `after` levanta — e ai nao ha mais
        ninguem para avisar, entao nao ha o que fazer alem de sair calado. Sem
        isso, fechar o programa durante uma operacao longa imprime um traceback
        de thread.
        """
        try:
            parent.after(0, lambda: terminar(callback, valor))
        except (tk.TclError, RuntimeError):
            pass

    def worker():
        try:
            resultado = work(task)
        except TaskCanceled:
            agendar(on_cancel, None)
            return
        except Exception as exc:
            agendar(on_error, exc)
            return

        agendar(on_cancel if task.cancelado() else on_success, resultado)

    threading.Thread(target=worker, daemon=True).start()
    return task
