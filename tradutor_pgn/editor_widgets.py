"""Pecas de interface que os dois editores compartilham.

Separado de `editor_common.py` de proposito: aquele modulo nao importa Tk, e e
essa restricao que o mantem testavel sem abrir janela. Aqui estao as funcoes que
precisam mesmo de um widget — e que ate agora existiam em duas copias, uma em
cada editor (ROADMAP 3.2).

Duas copias de uma funcao nao sao so repeticao. `save_window_section` implementa
a garantia R4: gravar **so** a secao desta janela, relendo o disco imediatamente
antes. Com duas copias, corrigir uma e esquecer a outra da exatamente o defeito
que R4 existe para impedir — e nada quebra na hora, o usuario e que perde um
rascunho depois.
"""

import tkinter as tk

import customtkinter as ctk

from .editor_common import clamped_sash_position
from .settings import update_settings


def flash_message(label, window, text, milliseconds=1500, **configure):
    """Escreve no rotulo de status e apaga sozinho depois de um tempo.

    `configure` passa adiante o que cada editor precisar — o de glossario usa
    cor para distinguir aviso de confirmacao, o de traducoes nao usa.
    """
    label.configure(text=text, **configure)
    window.after(milliseconds, lambda: label.configure(text=""))


def collect_sash_positions(sashes):
    """`{chave: posicao}` dos divisores que ainda existem.

    Cada item e `(chave, pane, indice)` ou `(chave, pane, indice, eixo)`. O eixo e
    0 para divisor HORIZONTAL (a posicao e uma largura, em x) e 1 para VERTICAL (e
    uma altura, em y) — `sash_coord` devolve o par, e o outro valor e sempre 1. Sem
    o eixo, um divisor vertical gravaria constantemente a mesma posicao inutil, que
    e o que aconteceria com o divisor dos dois textos (ROADMAP 19, item 1). O
    padrao e 0 porque os divisores que ja existiam sao todos horizontais.

    Um `PanedWindow` que ainda nao foi desenhado (ou que ja foi destruido) nao
    responde `sash_coord`. Perder a posicao de um divisor e irrelevante; nao
    gravar as configuracoes por causa disso, nao.
    """
    posicoes = {}
    for item in sashes:
        chave, pane, indice = item[:3]
        eixo = item[3] if len(item) > 3 else 0
        try:
            posicoes[chave] = pane.sash_coord(indice)[eixo]
        except tk.TclError:
            continue
    return posicoes


def save_window_section(local_settings, section, values, window=None, sashes=()):
    """Grava apenas a secao desta janela, relendo o disco antes (garantia R4).

    Cada janela carrega seu proprio snapshot das configuracoes na abertura. Se
    cada uma gravasse o snapshot inteiro, a ultima a salvar apagaria o que a
    outra escreveu depois — inclusive os rascunhos de traducao, que o editor
    salva a cada 700 ms.

    Falhar ao gravar nao pode derrubar nada: perder a posicao de uma janela e
    aborrecimento, e a chamada acontece ao fechar.

    Devolve o dicionario efetivamente gravado.
    """
    dados = dict(values)
    if window is not None:
        dados["geometry"] = window.geometry()
    dados.update(collect_sash_positions(sashes))

    def aplicar(disk_settings):
        secao = disk_settings.setdefault(section, {})
        if not isinstance(secao, dict):
            secao = {}
            disk_settings[section] = secao
        secao.update(dados)

    try:
        update_settings(aplicar)
    except OSError:
        pass

    # Mantem o snapshot em memoria coerente com o que foi para o disco.
    local = local_settings.setdefault(section, {})
    if isinstance(local, dict):
        local.update(dados)
    return dados


def restore_sash(pane, value, minimum, maximum=None, axis=0):
    """Recoloca um divisor na posicao gravada. `True` se recolocou.

    Onde colocar e decisao de `clamped_sash_position`, que e pura; aqui so
    sobra o que precisa do Tk — inclusive o painel que ja nao existe mais.

    `axis` diz em que coordenada a posicao vale, e o par de `sash_place` e
    posicional: com o eixo errado, o divisor vertical seria empurrado na horizontal
    e ficaria onde estava. E o mesmo eixo de `collect_sash_positions`, pelo mesmo
    motivo.
    """
    posicao = clamped_sash_position(value, minimum, maximum)
    if posicao is None:
        return False
    try:
        if axis:
            pane.sash_place(0, 0, posicao)
        else:
            pane.sash_place(0, posicao, 0)
    except tk.TclError:
        return False
    return True


def render_row_buttons(frame, items, build, empty_text):
    """Refaz a lista de linhas: limpa, e cria um botao por item.

    `build(frame, indice, item)` monta o botao — e ali que os dois editores
    diferem de verdade (rotulo, cores, comando), entao e o que fica com eles.
    O que se repetia era a moldura: destruir os filhos antigos, tratar a lista
    vazia e empacotar cada botao do mesmo jeito.

    Devolve os botoes criados, na ordem.
    """
    for child in frame.winfo_children():
        child.destroy()

    if not items:
        ctk.CTkLabel(frame, text=empty_text).pack(anchor="w", padx=6, pady=6)
        return []

    botoes = []
    for indice, item in enumerate(items):
        botao = build(frame, indice, item)
        botao.pack(fill=tk.X, padx=2, pady=2)
        botoes.append(botao)
    return botoes
