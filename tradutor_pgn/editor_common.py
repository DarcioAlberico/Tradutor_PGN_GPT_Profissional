"""Logica compartilhada pelas janelas de edicao.

As duas janelas (`edit_window` e `glossary_editor`) mantinham copias quase
identicas destes trechos, divergindo so em constantes. Aqui elas ficam em um
lugar so e, principalmente, em funcoes PURAS: nada aqui importa Tk nem recebe
widget, entao tudo pode ser testado sem abrir uma janela.
"""
from datetime import datetime

import re


# Cores das linhas das listas, iguais nas duas janelas.
ROW_COLOR = ("#f8fafc", "#1f2937")
ROW_TEXT_COLOR = ("#111827", "#e5e7eb")
ROW_HOVER_COLOR = ("#e2e8f0", "#374151")
SELECTED_ROW_COLOR = ("#3b82f6", "#1f6aa5")
SELECTED_ROW_TEXT_COLOR = "#ffffff"

GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)$")


def preview(text, limit=120):
    """Colapsa espacos e corta o texto para caber num rotulo."""
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def clamp_geometry(geometry, screen_width, screen_height, min_width, min_height):
    """Ajusta uma geometria salva para caber na tela atual.

    Recebe as dimensoes da tela como numeros em vez de um widget, para poder ser
    testada sem Tk. Uma geometria em formato desconhecido e devolvida intacta —
    quem chama decide o que fazer com ela.

    Trata o caso de posicao negativa salva num monitor que nao existe mais: o
    Tk aceita `+-71+28`, e sem o ajuste a janela abriria fora da area visivel.
    """
    match = GEOMETRY_RE.match(geometry or "")
    if not match:
        return geometry

    width = int(match.group(1))
    height = int(match.group(2))
    x = int(match.group(4))
    y = int(match.group(6))

    if match.group(3) == "-" and x >= 0:
        x = -x
    if match.group(5) == "-" and y >= 0:
        y = -y

    width = min(max(width, min_width), screen_width)
    height = min(max(height, min_height), screen_height)
    x = min(max(0, x), max(0, screen_width - width))
    y = min(max(0, y), max(0, screen_height - height))

    return f"{width}x{height}+{x}+{y}"


def window_safe_geometry(win, geometry, min_width, min_height):
    """`clamp_geometry` lendo as dimensoes da tela do proprio widget."""
    return clamp_geometry(
        geometry,
        win.winfo_screenwidth(),
        win.winfo_screenheight(),
        min_width,
        min_height,
    )


def page_count(total, page_size):
    """Quantidade de paginas para `total` itens."""
    if total <= 0 or page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size


def clamp_page(page_index, total, page_size):
    """Mantem o indice de pagina dentro do intervalo valido.

    Usado depois de qualquer operacao que encolha a lista (excluir, filtrar,
    buscar): sem isso a pagina atual pode ficar alem do fim.
    """
    pages = page_count(total, page_size)
    if pages == 0:
        return 0
    return min(max(0, page_index), pages - 1)


def page_offset(page_index, page_size):
    """Deslocamento (OFFSET do SQL) do inicio de uma pagina."""
    return max(0, page_index) * page_size


def page_of_offset(offset, page_size):
    """Pagina que contem um deslocamento absoluto."""
    if page_size <= 0:
        return 0
    return max(0, offset) // page_size


def row_index_for_id(rows, row_id, fallback=0):
    """Posicao da linha cujo id e `row_id`, ou o `fallback` limitado a lista.

    O editor guarda a posicao clicada, mas a lista pode ser trocada antes de
    essa posicao ser usada: gravar uma traducao com o filtro "Avisos QA" ativo
    faz a propria linha deixar de casar com o filtro, e todas as seguintes sobem
    uma casa. Aplicar a posicao antiga a lista nova seleciona a linha vizinha —
    o clique em B carrega C. Reencontrar pelo id elimina a classe inteira.

    Quando a linha nao esta mais na lista, `fallback` limitado ao tamanho atual
    aponta para quem ocupou o lugar dela. Devolve `None` se a lista estiver
    vazia: nao ha o que selecionar.

    O id e sempre a primeira coluna das linhas do editor.
    """
    if not rows:
        return None

    if row_id is not None:
        for index, row in enumerate(rows):
            if row[0] == row_id:
                return index

    return min(max(0, fallback), len(rows) - 1)


def local_index_for_offset(offset, page_size, page_length):
    """Posicao dentro da pagina para um deslocamento absoluto.

    Limita ao tamanho real da pagina recebida: a lista pode ter encolhido entre
    o calculo do deslocamento e a leitura da pagina (o worker de traducao grava
    no mesmo banco enquanto o editor esta aberto). Devolve `None` se a pagina
    estiver vazia.
    """
    if page_length <= 0:
        return None
    return min(max(0, offset) % page_size, page_length - 1)


def format_timestamp(value):
    """Carimbo do banco no formato que se le na tela, ou o proprio valor.

    Puro, e por isso mora aqui. Os dois editores mostram datas vindas das mesmas
    colunas; devolver o valor cru quando o formato nao bate e proposital — um
    carimbo inesperado deve aparecer como esta, e nao virar "-" e sumir.
    """
    if not value:
        return "-"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except ValueError:
        return value


def clamped_sash_position(value, minimum, maximum=None):
    """Posicao valida para um divisor, ou `None` se o valor gravado nao serve.

    Os limites nao sao decoracao: uma posicao gravada numa tela grande deixaria
    o painel fora da janela numa tela menor, sem nenhuma forma de traze-lo de
    volta a nao ser apagando as configuracoes na mao.

    Puro de proposito — a decisao e testavel sem abrir janela; ao Tk resta so
    colocar o divisor onde esta funcao mandar.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    largura = value if maximum is None else min(maximum, value)
    return max(minimum, largura)
