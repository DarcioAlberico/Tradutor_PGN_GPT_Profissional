"""A subjanela de historico de uma traducao.

Era um metodo de 245 linhas dentro de `TranslationEditor`, com seis funcoes
aninhadas proprias — o mesmo problema que o item 3.1 resolveu para a janela
inteira, em escala menor. Aqui ele fica isolado: o escopo desta janela e so
dela, e o que ela precisa do editor esta declarado num lugar so (ROADMAP 3.1).
"""

from contextlib import closing
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .database import (
    fetch_comment_history,
    fetch_translation_by_id,
    initialize_database,
    update_translation_by_id,
)
from .editor_common import (
    MUTED_TEXT_COLOR,
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    format_timestamp,
    preview,
)
from .editor_text import diff_spans
from .editor_widgets import render_row_buttons
from .window_utils import bring_window_to_front


ACTION_LABELS = {
    "edit": "Edicao",
    "edit_verify": "Edicao + verificacao",
    "verify": "Verificacao",
    "verify_exact_match": "Verificacao por traducao igual",
    "automatic_rules": "Regras automaticas",
    "mark_pending": "Voltou para pendente",
    "fill_empty": "Preenchimento inicial",
    "restore": "Restauracao",
    "status": "Status",
}

HISTORY_LIMIT = 100


def history_action_label(action):
    """Nome legivel da acao registrada, ou a propria acao se for desconhecida.

    Devolver a acao crua e melhor que "Alteracao" para tudo: uma acao nova
    gravada por uma versao mais recente aparece pelo nome tecnico, em vez de
    somir dentro de um rotulo generico.
    """
    return ACTION_LABELS.get(action or "", action or "Alteracao")


def history_status_label(value):
    return "verificada" if value == 1 else "pendente"


def history_change_summary(previous_translation, new_translation):
    """"3 trecho(s)" ou "sem mudanca no texto", para o rotulo da linha.

    A lista dizia QUANDO e QUE TIPO de acao, e nunca o TAMANHO da mudanca — e
    procurar a versao a restaurar entre 100 linhas iguais e justamente escolher
    pelo tamanho (ROADMAP 22.12). "Verificacao" e "Regras automaticas" produzem
    entradas com o mesmo rotulo, e uma delas nao mexeu no texto.

    Sai do MESMO `diff_spans` que pinta os dois painis ao lado, e nao de uma
    segunda conta: dois criterios de "o que mudou" acabariam divergindo, e a
    lista contradiria a pintura do detalhe.
    """
    _antes, depois = diff_spans(previous_translation or "", new_translation or "")
    if not depois:
        return "sem mudanca no texto"
    return f"{len(depois)} trecho(s)"


class HistoryWindow:
    """Historico de uma traducao, com restauracao de qualquer versao.

    **Modeless de proposito**, e e disso que sai a regra mais importante daqui:
    a lista principal continua clicavel enquanto esta janela esta aberta. Por
    isso o item a que ela se refere e fixado na abertura (`comment_id`) e nunca
    relido do editor. Sem isso, "Restaurar" gravaria no item selecionado no
    instante do clique, e nao naquele que o titulo da janela declara — que e
    exatamente a garantia R3 da SPEC.
    """

    def __init__(self, editor, comment_id, original_text):
        self.editor = editor
        self.app = editor.app
        self.comment_id = comment_id
        self.original_text = original_text

        self.rows = []
        self.buttons = []
        self.selected = None

        self.build()
        self.refresh()

    # ------------------------------------------------------------- construcao

    def build(self):
        self.win = ctk.CTkToplevel(self.editor.win)
        self.win.title(f"Historico da traducao {self.comment_id}")
        self.win.geometry("980x560")
        self.win.minsize(820, 430)
        self.win.transient(self.editor.win)
        # `maximize=False`, e e a mesma decisao que o docstring da classe explica.
        # Esta janela e modeless PARA QUE a lista principal continue clicavel
        # (garantia R3) — e ela abria cobrindo a tela inteira, tapando exatamente
        # a lista que deveria continuar acessivel. Maximizar anulava na tela o que
        # o `transient` sem `grab_set` garante no codigo.
        bring_window_to_front(self.win, self.editor.win, maximize=False)
        self.win.columnconfigure(1, weight=1)
        self.win.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.win,
            text=f"ID {self.comment_id} | {preview(self.original_text, 120)}",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))

        lista = ctk.CTkFrame(self.win, fg_color="transparent")
        lista.grid(row=1, column=0, sticky="nsw", padx=(10, 6), pady=(0, 10))
        lista.rowconfigure(0, weight=1)

        self.history_list = ctk.CTkScrollableFrame(lista, width=300)
        self.history_list.grid(row=0, column=0, sticky="nsew")

        # O corte em 100 versoes era silencioso: a lista simplesmente terminava,
        # e uma linha muito trabalhada parecia ter comecado no meio (ROADMAP
        # 22.12). O rotulo so aparece quando ha corte — dize-lo em toda linha com
        # tres edicoes seria ruido.
        self.limit_label = ctk.CTkLabel(
            lista, text="", anchor="w", text_color=MUTED_TEXT_COLOR
        )
        self.limit_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        detail_frame = ctk.CTkFrame(self.win, corner_radius=8)
        detail_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 10), pady=(0, 10))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.rowconfigure(2, weight=1)

        self.metadata_label = ctk.CTkLabel(detail_frame, text="", anchor="w")
        self.metadata_label.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6)
        )

        ctk.CTkLabel(detail_frame, text="Anterior").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 2)
        )
        ctk.CTkLabel(detail_frame, text="Nova").grid(
            row=1, column=1, sticky="w", padx=10, pady=(0, 2)
        )

        self.previous_text = ctk.CTkTextbox(detail_frame, wrap=tk.WORD)
        self.new_text = ctk.CTkTextbox(detail_frame, wrap=tk.WORD)
        self.previous_text.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        self.new_text.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))

        actions = ctk.CTkFrame(detail_frame, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        self.diff_label = ctk.CTkLabel(
            actions, text="", anchor="w", text_color=MUTED_TEXT_COLOR
        )
        self.diff_label.pack(side=tk.LEFT)

        self.btn_restore_previous = ctk.CTkButton(
            actions,
            text="Restaurar anterior",
            width=150,
            command=lambda: self.restore_selected(2),
        )
        self.btn_restore_new = ctk.CTkButton(
            actions,
            text="Restaurar nova",
            width=130,
            command=lambda: self.restore_selected(3),
        )
        btn_close = ctk.CTkButton(
            actions, text="Fechar", width=90, command=self.win.destroy
        )
        btn_close.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_restore_new.pack(side=tk.RIGHT, padx=6)
        self.btn_restore_previous.pack(side=tk.RIGHT, padx=6)

    # ------------------------------------------------------------------ lista

    def refresh(self):
        self.buttons.clear()
        self.selected = None

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            self.rows = list(
                fetch_comment_history(cur, self.comment_id, limit=HISTORY_LIMIT)
            )

        self.buttons = render_row_buttons(
            self.history_list,
            self.rows,
            self.build_row_button,
            "Nenhuma alteracao registrada.",
        )
        # `== HISTORY_LIMIT` e o unico sinal que existe de que ha mais: a consulta
        # devolve no maximo o limite, e contar o total custaria uma segunda
        # varredura de uma tabela que cresce com cada edicao do acervo. Uma linha
        # com exatamente 100 versoes vera o aviso sem ter sido cortada — e o erro
        # barato: ele diz o que a lista mostra, e nao afirma nada sobre o resto.
        self.limit_label.configure(
            text=(
                f"Mostrando as {HISTORY_LIMIT} mais recentes."
                if len(self.rows) >= HISTORY_LIMIT
                else ""
            )
        )

        if not self.rows:
            self.clear_detail()
            return
        self.select(0)

    def build_row_button(self, parent, index, row):
        _id, action, prev, new, previous_verified, new_verified, created_at = row
        return ctk.CTkButton(
            parent,
            text=(
                f"{format_timestamp(created_at)}\n"
                f"{history_action_label(action)} | "
                f"{history_status_label(previous_verified)} -> "
                f"{history_status_label(new_verified)}\n"
                f"{history_change_summary(prev, new)}"
            ),
            anchor="w",
            fg_color=ROW_COLOR,
            text_color=ROW_TEXT_COLOR,
            hover_color=ROW_HOVER_COLOR,
            command=lambda i=index: self.select(i),
        )

    def selected_row(self):
        if self.selected is None or not (0 <= self.selected < len(self.rows)):
            return None
        return self.rows[self.selected]

    def select(self, index):
        anterior = self.selected
        if anterior is not None and 0 <= anterior < len(self.buttons):
            self.buttons[anterior].configure(
                fg_color=ROW_COLOR, text_color=ROW_TEXT_COLOR
            )

        self.selected = index
        if 0 <= index < len(self.buttons):
            self.buttons[index].configure(
                fg_color=SELECTED_ROW_COLOR, text_color=SELECTED_ROW_TEXT_COLOR
            )

        row = self.selected_row()
        if row is None:
            self.clear_detail()
            return

        (
            _id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
            created_at,
        ) = row
        self.metadata_label.configure(
            text=(
                f"{format_timestamp(created_at)} | "
                f"{history_action_label(action)} | "
                f"{history_status_label(previous_verified)} -> "
                f"{history_status_label(new_verified)}"
            )
        )
        # As faixas trocadas, pintadas nos dois lados — as mesmas cores e o mesmo
        # `diff_spans` da previa do 19.5 (ROADMAP 22.12). Dois blocos de texto
        # lado a lado nao dizem o que mudou entre eles, e aqui o texto e um
        # comentario de livro inteiro: achar a palavra trocada a olho nu e o que
        # fazia a janela de historico ser aberta e fechada sem resposta.
        faixas_antes, faixas_depois = diff_spans(
            previous_translation or "", new_translation or ""
        )
        self.set_text(self.previous_text, previous_translation, faixas_antes, "removed")
        self.set_text(self.new_text, new_translation, faixas_depois, "added")
        self.diff_label.configure(
            text=history_change_summary(previous_translation, new_translation)
        )
        self.set_restore_buttons(True)

    # ---------------------------------------------------------------- detalhe

    def set_text(self, widget, value, faixas=(), tipo="added"):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        # Pintar ANTES de desabilitar: um `CTkTextbox` desabilitado nao aceita
        # `tag_add` — a mesma ordem que a previa de "Aplicar todas" segue.
        cor = (
            self.editor.diff_removed_bg
            if tipo == "removed"
            else self.editor.diff_added_bg
        )
        widget.tag_config("diff", background=cor)
        for inicio, fim in faixas:
            widget.tag_add("diff", f"1.0+{inicio}c", f"1.0+{fim}c")
        widget.configure(state="disabled")

    def set_restore_buttons(self, enabled):
        estado = "normal" if enabled else "disabled"
        self.btn_restore_previous.configure(state=estado)
        self.btn_restore_new.configure(state=estado)

    def clear_detail(self):
        self.metadata_label.configure(text="")
        self.set_text(self.previous_text, "")
        self.set_text(self.new_text, "")
        self.diff_label.configure(text="")
        self.set_restore_buttons(False)

    # ------------------------------------------------------------ restauracao

    def restore_selected(self, campo):
        """Restaura a versao anterior (campo 2) ou a nova (campo 3) da linha."""
        row = self.selected_row()
        if row is None:
            return
        self.restore(row[campo])

    def restore(self, text):
        if text is None:
            text = ""

        # **Pergunta antes** (ROADMAP 22.12). Era a unica restauracao do programa
        # sem confirmacao: restaurar o banco pergunta, o backup do glossario
        # pergunta, excluir UMA regra do glossario pergunta — e aqui os dois
        # botoes de restaurar ficam colados no "Fechar", sobrescrevendo a
        # traducao atual num clique. O texto do dialogo mostra o que vai entrar,
        # porque e ele que distingue os dois botoes.
        if not messagebox.askyesno(
            "Restaurar versao",
            f"Substituir a tradução atual da linha {self.comment_id} por esta "
            f"versão?\n\n{preview(text, 200) or '(vazia)'}",
            parent=self.win,
        ):
            return

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            changed = update_translation_by_id(
                cur, self.comment_id, text, history_action="restore"
            )
            updated_row = fetch_translation_by_id(cur, self.comment_id)
            conn.commit()

        # So mexe no editor se ele ainda estiver mostrando ESTE item; caso
        # contrario a restauracao sobrescreveria o texto de outra traducao na
        # tela (garantia R3).
        if self.editor.current["id"] == self.comment_id:
            self.editor.current["trans"] = text
            self.editor.current["saved_trans"] = text
            self.editor.clear_current_draft()
            if updated_row is not None:
                self.editor.set_current_history(updated_row)
            self.editor.set_translation_text(text, mark_dirty=False)
            self.editor.update_current_row_cache()

        self.refresh()
        if changed:
            self.editor.show_message(f"Versao restaurada (ID {self.comment_id})")
        else:
            self.editor.show_message("Versao ja estava aplicada")
