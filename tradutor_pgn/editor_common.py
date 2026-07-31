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
# O azul claro era `#3b82f6`, e o branco sobre ele dava 3,7:1 — reprovado para os
# 11 px do rotulo da linha (ROADMAP 22.9). `#1d4ed8` da 6,7:1; o escuro ja
# passava com 5,7:1 e ficou como estava.
SELECTED_ROW_COLOR = ("#1d4ed8", "#1f6aa5")
SELECTED_ROW_TEXT_COLOR = "#ffffff"

# As quatro cores semanticas dos rotulos, em pares `(claro, escuro)` — ROADMAP
# 22.9. Cada uma era UM hex para os dois temas, e um hex so nao serve a dois
# fundos: as quatro reprovavam o minimo de 4,5:1 do texto de 13 px em pelo menos
# um tema, e o ambar dos avisos dava **1,55:1** no claro — o pior par da janela,
# e justamente o texto que avisa que algo esta errado.
#
# Medido pela formula de luminancia relativa da WCAG, contra os dois fundos de
# rotulo do programa (`LABEL_BACKGROUNDS`), e conferido em teste:
#
#   |          | antes (claro/escuro) | depois        |
#   |----------|----------------------|---------------|
#   | verde    | 2,38 / 4,30          | 5,15 / 8,13   |
#   | ambar    | **1,55** / 6,59      | 5,12 / 6,59   |
#   | vermelho | 3,49 / 2,93          | 6,00 / 5,12   |
#   | cinza    | 3,44 / 2,98          | 5,47 / 5,52   |
#
# Elas vivem aqui, e nao em cada janela, porque as tres janelas que dao recado
# usam as mesmas quatro — e um hex copiado e um lugar a mais para esquecer de
# corrigir (a licao do item 3.2).
OK_TEXT_COLOR = ("#166534", "#4ade80")
WARNING_TEXT_COLOR = ("#92400e", "#f59e0b")
ERROR_TEXT_COLOR = ("#991b1b", "#f87171")
MUTED_TEXT_COLOR = ("#475569", "#94a3b8")

# Os dois fundos contra os quais as cores acima foram medidas. O claro nao e
# chute: foi amostrado dos pixels de uma captura real da janela; o escuro e o do
# codigo (`pane_bg`). Ficam aqui para o teste medir contra os mesmos.
LABEL_BACKGROUNDS = ("#dbdbdb", "#2b2b2b")

GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)$")

# Quanto tempo uma mensagem de status fica na tela (ROADMAP 22.6). Eram 1,5 s
# fixos para qualquer texto, e a conta abaixo e o que o piso nao dava: a
# mensagem mais longa que a janela produz — "Tradução salva e verificada; N
# outro(s) original(is) também verificado(s)", 74 caracteres — cabia no mesmo
# tempo que "Salvo".
#
# O numero por caractere sai de uma convencao de leitura, e nao de uma medicao
# nesta maquina: ~200 palavras por minuto, palavra media de ~6,3 caracteres com
# o espaco, dao ~21 caracteres por segundo — ~47 ms cada. 45 ms arredonda para
# baixo, que e o lado seguro (mensagem de menos, e nao rotulo parado na tela).
FLASH_MINIMUM_MS = 1500
FLASH_MS_PER_CHARACTER = 45
FLASH_MAXIMUM_MS = 6000


def flash_duration_ms(text):
    """Quanto tempo `text` fica na tela, em milissegundos.

    Pura, e por isso mora aqui: o tempo de leitura de uma frase nao depende de
    widget nenhum, e assim ele pode ser conferido sem abrir janela.

    O piso e o que o programa sempre usou — abaixo dele o texto e curto o
    bastante para ser lido de relance — e o teto existe porque um rotulo parado
    na tela deixa de ser noticia e vira parte do fundo.
    """
    caracteres = len(text or "")
    return max(
        FLASH_MINIMUM_MS,
        min(FLASH_MAXIMUM_MS, caracteres * FLASH_MS_PER_CHARACTER),
    )


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
