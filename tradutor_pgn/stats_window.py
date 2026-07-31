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

import csv
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .editor_common import OK_TEXT_COLOR
from .editor_widgets import flash_message
from .window_utils import bring_window_to_front


class StatsWindow:
    """Mostra o relatorio de estatisticas e deixa copia-lo ou salva-lo."""

    def __init__(self, app, report, tables=()):
        self.app = app
        self.report = report
        # `[(titulo, cabecalho, linhas)]`, montado por `db_tools.stats_tables`.
        # Vazio quando quem abre a janela nao tem tabela nenhuma para dar — o
        # botao de CSV some junto, em vez de salvar um arquivo com nada dentro.
        self.tables = list(tables)

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
        # Os eventos VIRTUAIS, alem das teclas (ROADMAP 22.12). O `<Key>` acima
        # deixava passar qualquer combinacao com Control, e os bindings de classe
        # do Tk mapeiam sete delas para EDITAR: Ctrl+V cola, Ctrl+X recorta,
        # Ctrl+K apaga ate o fim da linha, Ctrl+D apaga o caractere, Ctrl+O abre
        # linha, Ctrl+T transpoe e Ctrl+H apaga para tras. Um relatorio editavel
        # vira um numero diferente do que o banco disse, e ninguem distingue os
        # dois num print de tela.
        #
        # Barrar aqui, e nao ampliar a lista de teclas: o Tk faz a edicao pelo
        # evento virtual, entao e nele que a decisao pertence — uma versao futura
        # do Tk que mapeie outra tecla para `<<Paste>>` continua barrada.
        for evento in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<<Undo>>", "<<Redo>>"):
            self.text.bind(evento, lambda _event: "break")

        actions = ctk.CTkFrame(self.win, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.msg_label = ctk.CTkLabel(actions, text="", text_color=OK_TEXT_COLOR)
        self.msg_label.pack(side=tk.LEFT)

        self.btn_close = ctk.CTkButton(
            actions, text="Fechar", width=100, command=self.win.destroy
        )
        self.btn_close.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_save = ctk.CTkButton(
            actions, text="Salvar .txt", width=110, command=self.save_report
        )
        self.btn_save.pack(side=tk.RIGHT, padx=(6, 0))
        # O `.txt` e para ler; o CSV e para a planilha (ROADMAP 22.12). As tres
        # tabelas do relatorio — progresso por obra, palavras por par e
        # atividade por dia — sao justamente o que um tradutor cola num
        # orcamento, e do texto corrido elas so saem a mao.
        self.btn_save_csv = ctk.CTkButton(
            actions, text="Salvar CSV", width=110, command=self.save_csv
        )
        if self.tables:
            self.btn_save_csv.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_copy = ctk.CTkButton(
            actions, text="Copiar", width=100, command=self.copy_report
        )
        self.btn_copy.pack(side=tk.RIGHT)

    # As unicas combinacoes com Control que a janela deixa passar: copiar e
    # selecionar tudo. Era uma lista NEGRA — "qualquer coisa com Control" — e
    # lista negra e a forma errada de decidir isto: bastava o Tk mapear uma tecla
    # a mais para a janela "nao editavel" passar a aceitar edicao (ROADMAP 22.12).
    COPY_KEYS = {"c", "C", "a", "A", "Insert"}
    NAVIGATION_KEYS = {
        "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
    }

    def _block_typing(self, event):
        """Deixa passar o que copia e navega; barra o que altera.

        `Ctrl+C`, `Ctrl+A` e as setas continuam funcionando — sao eles que fazem a
        janela ser copiavel. Qualquer outra tecla e engolida, porque um relatorio
        editavel viraria um numero diferente do que o banco disse, e ninguem
        distinguiria os dois num print de tela.
        """
        if event.state & 0x4:  # Control
            return None if event.keysym in self.COPY_KEYS else "break"
        if event.keysym in self.NAVIGATION_KEYS:
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

    def save_csv(self):
        """Grava as tres tabelas num CSV so (ROADMAP 22.12).

        Um arquivo, e nao tres: elas sao lidas juntas ("quanto falta do capitulo
        7 e quantas palavras isso da"), e tres seletores de arquivo seguidos para
        um clique so seria pior do que a linha em branco que as separa. Cada
        bloco comeca por uma linha com o nome da tabela, que e o que permite
        acha-las depois de colar tudo numa planilha.

        `utf-8-sig` pelo mesmo motivo do `.txt` e do CSV de traducoes: o Excel do
        Windows le UTF-8 sem BOM como ANSI, e ha acento em nome de arquivo e em
        rotulo de idioma.
        """
        caminho = filedialog.asksaveasfilename(
            title="Salvar estatisticas em CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not caminho:
            return None
        try:
            with open(caminho, "w", encoding="utf-8-sig", newline="") as arquivo:
                escritor = csv.writer(arquivo)
                for indice, (titulo, cabecalho, linhas) in enumerate(self.tables):
                    if indice:
                        escritor.writerow([])
                    escritor.writerow([titulo])
                    escritor.writerow(cabecalho)
                    escritor.writerows(linhas)
        except OSError as exc:
            messagebox.showerror("Erro", f"Nao foi possivel salvar:\n{exc}")
            return None
        self._flash(f"{len(self.tables)} tabela(s) salvas em CSV")
        return caminho

    def _flash(self, texto):
        """A mesma funcao dos dois editores, e nao um terceiro timer.

        Esta janela tinha a copia do padrao que o ROADMAP 22.6 consertou: o
        `after` era agendado sem cancelar o anterior, entao clicar "Copiar" e
        "Salvar .txt" em seguida fazia o timer do primeiro apagar a mensagem do
        segundo. Uma copia que ninguem lembraria de corrigir junto e exatamente o
        que o item 3.2 do ROADMAP descreve.
        """
        flash_message(self.msg_label, self.win, texto)
