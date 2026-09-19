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

from .editor_common import clamped_sash_position, flash_duration_ms
from .settings import update_settings


# Quanto o ponteiro fica parado sobre o controle antes de a dica aparecer
# (ROADMAP 28.9, item 4). Meio segundo e o padrao do Windows: mais curto
# atrapalha quem so passa o ponteiro, mais longo parece que nao ha dica.
TOOLTIP_DELAY_MS = 500
TOOLTIP_COLORS = ("#1f2937", "#e5e7eb")
TOOLTIP_TEXT_COLORS = ("#f9fafb", "#111827")


class Tooltip:
    """Uma dica sob o ponteiro, para os controles que nao tem palavra.

    `▤/▥`, "B", "Aa", "A-/A+", "?", "Priorizar esta"/"Manter esta": cada um
    e curto porque a faixa em que vive nao tem largura para uma frase (22.8),
    e a dica e o que devolve a frase sem gastar largura. E um `Toplevel` sem
    decoracao com um `CTkLabel` dentro — o rotulo recebe pares de cor e troca
    sozinho com o tema (F18). Nasce no `<Enter>` depois de `TOOLTIP_DELAY_MS`,
    some no `<Leave>`, no clique e quando o controle e destruido: a dica de um
    botao que ja nao existe seria uma janela orfa flutuando na tela.
    """

    def __init__(self, widget, text, delay_ms=TOOLTIP_DELAY_MS):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.after_id = None
        self.window = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _event=None):
        self.cancel()
        try:
            self.after_id = self.widget.after(self.delay_ms, self.show)
        except tk.TclError:  # pragma: no cover - widget ja destruido
            self.after_id = None

    def cancel(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:  # pragma: no cover
                pass
            self.after_id = None

    def show(self):
        self.after_id = None
        if self.window is not None:
            return
        try:
            if not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
                return
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        janela = tk.Toplevel(self.widget)
        janela.overrideredirect(True)
        janela.attributes("-topmost", True)
        rotulo = ctk.CTkLabel(
            janela,
            text=self.text,
            fg_color=TOOLTIP_COLORS,
            text_color=TOOLTIP_TEXT_COLORS,
            corner_radius=4,
            padx=8,
            pady=4,
        )
        rotulo.pack()
        janela.geometry(f"+{x}+{y}")
        self.window = janela

    def hide(self, _event=None):
        self.cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:  # pragma: no cover
                pass
            self.window = None


def attach_tooltip(widget, text, delay_ms=TOOLTIP_DELAY_MS):
    """Liga uma dica ao controle e a devolve (para o teste dirigir)."""
    dica = Tooltip(widget, text, delay_ms)
    widget.tooltip = dica
    return dica


def flash_message(label, window, text, milliseconds=None, **configure):
    """Escreve no rotulo de status e apaga sozinho depois de um tempo.

    `configure` passa adiante o que cada editor precisar — o de glossario usa
    cor para distinguir aviso de confirmacao, o de traducoes nao usa.

    **Cancela o apagamento pendente antes de agendar o seu** (ROADMAP 22.6). Sem
    isso o timer de uma mensagem antiga apagava a mensagem NOVA: A em t=0 e B em
    t=1,0 s davam a B meio segundo de tela, porque o `after` de A chegava em
    t=1,5 s e limpava o rotulo sem olhar o que havia nele. O editor encadeia
    mensagens nesse ritmo em fluxos comuns — "Rascunho restaurado" seguido de
    "Aviso QA: ...".

    Sem `milliseconds`, o tempo vem de `flash_duration_ms`: ele cresce com o
    texto, porque 1,5 s fixos serviam a "Salvo" e nao a uma frase de 74
    caracteres.

    O id fica no proprio rotulo, e nao num atributo de quem chama: sao varias
    janelas e cada uma tem o seu, e a unica coisa que as tres compartilham e este
    modulo.
    """
    cancel_flash(label, window)
    label.configure(text=text, **configure)

    if milliseconds is None:
        milliseconds = flash_duration_ms(text)

    def limpar():
        label._flash_after = None
        try:
            label.configure(text="")
        except tk.TclError:  # pragma: no cover - janela fechada antes do tempo
            pass

    label._flash_after = window.after(milliseconds, limpar)
    return label._flash_after


def cancel_flash(label, window):
    """Cancela o apagamento pendente deste rotulo, se houver.

    Tolera o `after` ja ter disparado ou a janela ter morrido: cancelar um id
    que nao existe mais nao e erro nenhum aqui — a intencao ja esta cumprida.
    """
    pendente = getattr(label, "_flash_after", None)
    if pendente is None:
        return
    label._flash_after = None
    try:
        window.after_cancel(pendente)
    except (tk.TclError, ValueError):
        pass


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
