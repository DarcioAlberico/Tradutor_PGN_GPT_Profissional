"""A janela das estatisticas do banco: copiavel, exportavel, redimensionavel.

O resumo era um `messagebox` (ROADMAP 19, item 7). Um `messagebox` do Tk nao rola,
nao se seleciona e nao se copia — e o conteudo dele e justamente o numero que um
tradutor profissional poe num orcamento ou numa fatura. Com o progresso por obra
(secao 18) e as contagens de palavras (item 6), ele tambem passou a ser mais alto
que a tela.

O calculo NAO mora aqui: quem o faz e `db_tools.collect_database_stats`, numa
thread de trabalho. Esta janela recebe texto pronto — e por isso ela nao tem
nenhuma consulta, nenhum `initialize_database` e nenhum caminho de erro de banco.
"""

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .window_utils import bring_window_to_front


class StatsWindow:
    """Mostra o relatorio de estatisticas e deixa copia-lo ou salva-lo."""

    def __init__(self, app, report):
        self.app = app
        self.report = report

        self.win = ctk.CTkToplevel(app.root)
        self.win.title("Estatisticas do Banco de Dados")
        self.win.geometry("760x620")
        self.win.minsize(520, 380)
        # Modeless e sem `grab_set`: o proposito da janela e ser consultada
        # ENQUANTO se trabalha — copiar um numero para o orcamento, conferir quanto
        # falta do capitulo. Um modal aqui seria o `messagebox` de volta, so maior.
        bring_window_to_front(self.win, app.root)

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

        # `CTkTextbox` em estado normal, e nao um rotulo: o texto precisa ser
        # selecionavel para o `Ctrl+C` do sistema funcionar. A escrita e barrada no
        # `<Key>`, e nao pelo estado `disabled`, porque `disabled` no Tk tambem
        # impede a SELECAO — era isso ou um campo que ninguem consegue copiar.
        self.text = ctk.CTkTextbox(self.win, wrap=tk.NONE, font=("Consolas", 12))
        self.text.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        self.text.insert("1.0", report)
        self.text.bind("<Key>", self._block_typing)

        actions = ctk.CTkFrame(self.win, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.msg_label = ctk.CTkLabel(actions, text="", text_color="#16a34a")
        self.msg_label.pack(side=tk.LEFT)

        self.btn_close = ctk.CTkButton(
            actions, text="Fechar", width=100, command=self.win.destroy
        )
        self.btn_close.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_save = ctk.CTkButton(
            actions, text="Salvar .txt", width=110, command=self.save_report
        )
        self.btn_save.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_copy = ctk.CTkButton(
            actions, text="Copiar", width=100, command=self.copy_report
        )
        self.btn_copy.pack(side=tk.RIGHT)

    def _block_typing(self, event):
        """Deixa passar o que copia e navega; barra o que altera.

        `Ctrl+C`, `Ctrl+A` e as setas continuam funcionando — sao eles que fazem a
        janela ser copiavel. Qualquer outra tecla e engolida, porque um relatorio
        editavel viraria um numero diferente do que o banco disse, e ninguem
        distinguiria os dois num print de tela.
        """
        if event.state & 0x4:  # Control
            return None
        if event.keysym in {
            "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
        }:
            return None
        return "break"

    def copy_report(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.report)
        self._flash("Relatorio copiado")

    def save_report(self):
        caminho = filedialog.asksaveasfilename(
            title="Salvar estatisticas",
            defaultextension=".txt",
            filetypes=[("Arquivo de texto", "*.txt"), ("Todos os arquivos", "*.*")],
        )
        if not caminho:
            return
        try:
            # `utf-8-sig` como o CSV do programa: o Bloco de Notas e o Excel do
            # Windows leem UTF-8 sem BOM como ANSI, e o relatorio tem acento.
            with open(caminho, "w", encoding="utf-8-sig") as arquivo:
                arquivo.write(self.report + "\n")
        except OSError as exc:
            messagebox.showerror("Erro", f"Nao foi possivel salvar:\n{exc}")
            return
        self._flash("Relatorio salvo")

    def _flash(self, texto):
        self.msg_label.configure(text=texto)
        self.win.after(2000, lambda: self.msg_label.configure(text=""))
