import csv
import os
import threading
from collections import Counter
from contextlib import closing
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .app_config import LANGUAGE_NAMES, LANGUAGES, UNKNOWN_SOURCE_LABEL, language_label
from .database import (
    ORDER_BY_ID,
    ORDER_BY_OCCURRENCE,
    REVIEW_STATUS_DOUBT,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    SEARCH_MODE_SUBSTRING,
    SEARCH_MODE_TERMS,
    SOURCE_LANGUAGE_UNKNOWN,
    count_from_status_counts,
    count_review_rows,
    fetch_comment_occurrences,
    fetch_exact_translation_match_candidates,
    fetch_review_row_ids,
    fetch_review_rows,
    fetch_review_rows_page,
    fetch_review_status_by_id,
    fetch_translation_by_id,
    get_review_row_offset,
    get_review_status_counts,
    initialize_database,
    list_occurrence_files,
    quality_warning_flag,
    set_exact_translation_matches_verified,
    set_review_status_by_id,
    set_translation_verified_by_id,
    update_translation_by_id,
)
from .db_tools import apply_automatic_rules_to_database, export_translations_to_csv
from .editor_text import diff_spans, find_text_ranges, replace_all_text
from .glossario import (
    add_to_glossary,
    apply_automatic_substitutions,
    case_adjusted_replacement,
    delete_glossary_entry_by_pair,
    find_glossary_matches,
    find_glossary_suggestions,
    load_automatic_substitutions,
    load_interactive_substitutions,
    versioned_rules,
)
from .editor_common import (
    ERROR_TEXT_COLOR,
    MUTED_TEXT_COLOR,
    OK_TEXT_COLOR,
    ROW_COLOR,
    ROW_HOVER_COLOR,
    ROW_TEXT_COLOR,
    SELECTED_ROW_COLOR,
    SELECTED_ROW_TEXT_COLOR,
    WARNING_TEXT_COLOR,
    clamp_page,
    format_timestamp,
    local_index_for_offset,
    page_count as compute_page_count,
    page_offset,
    page_of_offset,
    preview,
    row_index_for_id,
    window_safe_geometry,
)
from .editor_widgets import (
    flash_message,
    render_row_buttons,
    restore_sash,
    save_window_section,
)
from .glossary_editor import open_glossary_editor
from .history_window import HistoryWindow
from .review_quality import (
    QUALITY_REPORT_HEADERS,
    build_quality_report_rows,
    evaluate_translation_quality,
    find_first_quality_warning,
    row_has_quality_warning,
    row_language_pair,
    row_quality_flag,
    row_quality_warnings,
)
from .settings import (
    clear_editor_draft,
    get_editor_draft,
    load_settings,
    set_editor_draft,
    update_settings,
)
from .window_utils import bring_window_to_front, restore_or_maximize


ROW_COLOR = ("#f8fafc", "#1f2937")
VERIFIED_ROW_COLOR = ("#d1fae5", "#14532d")
VERIFIED_ROW_TEXT_COLOR = ("#065f46", "#d1fae5")
SUGGESTION_COLOR = ("#f8fafc", "#1f2937")
SUGGESTION_TEXT_COLOR = ("#111827", "#e5e7eb")
SUGGESTION_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
PAGE_SIZE = 100
SEARCH_MODE_LABEL_TERMS = "Termos"
SEARCH_MODE_LABEL_SUBSTRING = "Trecho"
# A largura minima da janela e a SOMA dos minimos dos tres paineis, e nao um
# numero escolhido a parte (ROADMAP 22.10). Ela era 1120 contra 1176 de soma, e
# quem pagava a diferenca era sempre o mesmo painel: medido na janela real em
# 1120 px, o de sugestoes ficava com **109** dos 300 px que declara, e os seis
# botoes dele apareciam com 40 px dos 140 de que precisam — seis rotulos
# ilegiveis. Derivar a constante da soma e o que impede a conta de voltar a
# divergir quando um dos minimos mudar.
SASH_WIDTH = 8
LIST_PANE_MIN = 320
EDITOR_PANE_MIN = 520
# 308, e nao os 300 declarados antes: 300 e a largura do painel, e os seis
# botoes dele pedem 140 px cada em duas colunas — com os `padx` de 10/4 sobram
# 136, e todos os seis ficavam 4 px curtos. O numero e o `winfo_reqwidth` do
# painel montado, medido na janela real.
SUGGESTION_PANE_MIN = 308
# O painel de baixo contem o editor e as sugestoes: o minimo dele e o dos dois
# mais o divisor. Declarar 620 aqui (o que havia) autorizava arrastar o divisor
# da lista ate esmagar as sugestoes, mesmo com a janela larga.
BOTTOM_PANE_MIN = EDITOR_PANE_MIN + SASH_WIDTH + SUGGESTION_PANE_MIN
MAIN_PANE_PADX = 20
MIN_WIDTH = LIST_PANE_MIN + SASH_WIDTH + BOTTOM_PANE_MIN + MAIN_PANE_PADX
MIN_HEIGHT = 680

# Largura PEDIDA pelo painel da lista na primeira abertura, quando ainda nao ha
# posicao de divisor gravada. E um pedido e nao uma garantia: numa janela
# estreita o `minsize` dos outros dois paineis vence, e a lista recua ate os 320
# dela — foi assim que a largura minima passou a fechar (ROADMAP 22.10).
LIST_PANE_DEFAULT = 400

# Quanto da mensagem transitoria do rodape cabe na fileira dos rotulos, medido
# na janela real na largura minima (ROADMAP 22.10). A faixa tem 1.144 px; o caso
# tipico gasta 700 deles com o "?" (32), o "Salvo" (31), o "Item n/N · par"
# (~200), as quatro contagens (389) e os `padx`, e o rascunho leva mais ~140 —
# sobram ~304 px, e a fonte da faixa gasta 5,66 px por caractere (48 caracteres
# tipicos medem 270 px).
#
# As duas mensagens de propagacao do editor passam disso (73 e 56 caracteres) e
# ficam com reticencias. E o certo: elas sao recibo de uma acao que o usuario
# acabou de confirmar num dialogo que ja dizia o efeito por extenso (garantia
# V1), e a contagem que fica — que este mesmo item protegeu — mostra o resultado.
MESSAGE_PREVIEW_CHARS = 52

# Rotulo do filtro de origem que nao filtra nada. Precisa ser diferente de
# `UNKNOWN_SOURCE_LABEL`: "Todos" traz a tabela inteira, "Não informado" traz so
# as linhas cuja origem ninguem declarou. Confundir os dois foi exatamente o que
# esta janela passou a existir para evitar.
SOURCE_FILTER_ALL = "Todos"

# O mesmo para o filtro por arquivo. O rotulo diz "arquivos" no plural porque este
# menu convive com o de origem na mesma barra, e dois "Todos" lado a lado nao
# dizem de que.
FILE_FILTER_ALL = "Todos os arquivos"

# Os filtros de status da lista: rotulo na tela -> filtro que o banco entende
# (ROADMAP 19, item 12). Um dicionario, e nao dois lugares (a lista de valores do
# botao segmentado e um `if/elif` traduzindo), porque era assim antes e acrescentar
# um filtro exigia mexer nos dois — esquecer um dava um botao que nao filtra nada.
#
# "Rejeitadas" e "Em duvida" sao RECORTES das pendentes, e a ordem na tela diz isso:
# elas vem depois de "Pendentes".
# O nome do status da linha aberta, em palavras (garantia F19, ROADMAP 22.9). A
# pendente nao tem rotulo: e o padrao, e escrever "Pendente" em toda linha faria
# o normal virar ruido e esconderia a excecao — a mesma regra da prioridade no
# editor de glossario e das contagens do rodape.
REVIEW_STATUS_LABELS = {
    REVIEW_STATUS_REJECTED: "Rejeitada",
    REVIEW_STATUS_DOUBT: "Em dúvida",
}

STATUS_FILTER_LABELS = {
    "Todas": "all",
    "Pendentes": "pending",
    "Rejeitadas": REVIEW_STATUS_REJECTED,
    "Em dúvida": REVIEW_STATUS_DOUBT,
    "Verificadas": "verified",
    "Avisos QA": "warnings",
}

# Pausa na digitacao que dispara a gravacao do rascunho. Eram 700 ms (ROADMAP 19,
# item 10): quem digita uma frase de comentario para varias vezes por mais de 700 ms
# — para pensar, para ler o original —, e cada parada custava uma releitura e uma
# regravacao do JSON inteiro. 2,5 s ainda salva antes de qualquer coisa que se possa
# perder (fechar a janela grava na hora) e reduz as gravacoes de uma revisao longa a
# uma fracao.
DRAFT_SAVE_DELAY_MS = 2500

# Quantos saltos a pilha do "voltar" guarda. Uma sessao de revisao dura horas e
# cada busca empilha um retrato; sem limite, a pilha cresce com a sessao. Cinquenta
# cobre qualquer ida-e-volta de concordancia — e o corte e pelo comeco, que e a
# parte a que ninguem mais volta.
HISTORY_STACK_LIMIT = 50

# Quantas ocorrencias o rodape do original mostra por extenso. **Uma**, e o numero
# saiu de uma captura de tela: com duas, o texto passava da linha do "Original:" e
# o Tk cortava o COMECO dele — o rotulo aparecia sem o "Lido em: cap01.pgn", e o
# que sobrava na tela era um "· comentário 2 | cap02.pgn ..." colado no rotulo,
# ilegivel. A posicao mostrada e a do arquivo que esta sendo lido, e as outras
# viram contagem — que e o que informa mesmo, porque editar ali muda todas.
OCCURRENCE_PREVIEW_LIMIT = 1

# Quantos originais a confirmacao da propagacao lista por extenso. Acima disso a
# lista deixa de ser legivel num dialogo e o que fica e a contagem — mas os
# primeiros ja mostram DO QUE se trata, que e o que a contagem sozinha nao diz.
PROPAGATION_PREVIEW_LIMIT = 8


# Os atalhos da janela, agrupados como o dialogo "Atalhos" os mostra (garantia
# F18, ROADMAP 22.8). Sao treze, e ate aqui **nenhum aparecia na interface**: nao
# ha menu, o CustomTkinter nao tem tooltip, e o README documentava tres. O
# criterio e do proprio projeto — "um atalho que ninguem descobre nao devolve a
# pagina a ninguem" (item 19.3) —, aplicado ate entao so ao botao "< Voltar".
#
# O caso extremo era o `Ctrl+B`: ele nao tem botao (o "B" da barra faz outra
# coisa), nao estava no README, e portanto nao tinha caminho de descoberta
# NENHUM — um recurso restaurado no item 4.1 que so quem lesse o fonte acharia.
#
# A sequencia do Tk vai junto de proposito: e ela que um teste compara com os
# binds reais da janela, e e o que impede a lista de envelhecer sozinha. Sem
# isso, esta tabela seria documentacao — a especie que fica errada em silencio.
KEYBOARD_SHORTCUTS = (
    (
        "Navegar",
        (
            ("Alt+←", "<Alt-Left>", "Linha anterior"),
            ("Alt+→", "<Alt-Right>", "Próxima linha"),
            ("Ctrl+PageUp", "<Control-Prior>", "Página anterior da lista"),
            ("Ctrl+PageDown", "<Control-Next>", "Próxima página da lista"),
            ("Alt+Backspace", "<Alt-BackSpace>", "Voltar ao ponto anterior"),
            ("F7", "<F7>", "Próximo aviso de qualidade"),
        ),
    ),
    (
        "Buscar",
        (
            ("Ctrl+L", "<Control-l>", "Buscar na lista (troca a página)"),
            ("Ctrl+F", "<Control-f>", "Buscar dentro da tradução aberta"),
            ("F3", "<F3>", "Próxima ocorrência no texto"),
        ),
    ),
    (
        "Editar e gravar",
        (
            ("Ctrl+S", "<Control-s>", "Salvar"),
            ("Ctrl+Enter", "<Control-Return>", "Salvar e marcar como verificada"),
            (
                "Ctrl+Shift+Enter",
                "<Control-Shift-Return>",
                "Marcar como verificada e ir para a próxima",
            ),
            ("Ctrl+Z", "<Control-z>", "Desfazer"),
            ("Ctrl+Y", "<Control-y>", "Refazer"),
            ("Ctrl+B", "<Control-b>", "Negrito no trecho selecionado da tradução"),
        ),
    ),
    (
        "Ver",
        (
            ("Ctrl++", "<Control-plus>", "Aumentar a fonte dos dois textos"),
            ("Ctrl+=", "<Control-equal>", "Aumentar a fonte (teclado sem Shift)"),
            ("Ctrl+-", "<Control-minus>", "Diminuir a fonte dos dois textos"),
        ),
    ),
    (
        "Janelas",
        (
            ("Ctrl+H", "<Control-h>", "Histórico da tradução aberta"),
            ("F1", "<F1>", "Esta lista de atalhos"),
        ),
    ),
)

# Os gestos de MOUSE ficam numa tabela propria, e nao no fim da de cima
# (ROADMAP 22.11). A razao e de teste, e vale registra-la: a parceria entre a
# lista e a janela e conferida nos dois sentidos, e o lado "todo bind aparece na
# lista" so consegue separar atalho de evento de ciclo de vida porque o Tk poe
# `Key` em toda sequencia de TECLA. Um `<Double-Button-1>` na mesma tupla ficaria
# fora dessa conferencia — listado e nunca verificado, que e a forma de
# envelhecer que a garantia F18 existe para impedir.
MOUSE_GESTURES = (
    ("Ctrl+roda", "Aumentar e diminuir a fonte dos dois textos"),
    ("Duplo clique numa sugestão", "Aplicar a sugestão na tradução"),
    ("Clique em \"Lido em:\"", "Todas as posições em que este comentário aparece"),
)


# O estado LIGADO do botao "B" (ROADMAP 22.8). Cores de outra familia que a do
# botao padrao, e diferentes nos dois temas — o par anterior era identico ao
# desligado no tema escuro. A borda e a segunda diferenca, e a que funciona para
# quem nao distingue os dois azuis.
BOLD_ACTIVE_COLOR = ("#1d4ed8", "#1e40af")
BOLD_ACTIVE_HOVER_COLOR = ("#1e40af", "#1d4ed8")
BOLD_ACTIVE_BORDER_COLOR = ("#bfdbfe", "#93c5fd")


def theme_button_colors():
    """`(fg_color, hover_color)` padrao do botao, lidos do TEMA.

    Transcrever os hexes do tema para restaurar um botao — que era o que o "B"
    fazia — congela a aparencia dele no tema que existia quando alguem copiou.
    Se a leitura falhar (um tema sem essas chaves), o par de fabrica do
    CustomTkinter 5.2.2 e melhor do que uma excecao no meio de um clique.
    """
    try:
        tema = ctk.ThemeManager.theme["CTkButton"]
        return tema["fg_color"], tema["hover_color"]
    except (AttributeError, KeyError, TypeError):  # pragma: no cover - tema exotico
        return ("#3B8ED0", "#1F6AA5"), ("#36719F", "#144870")


def source_filter_labels():
    return [SOURCE_FILTER_ALL, UNKNOWN_SOURCE_LABEL] + [nome for nome, _ in LANGUAGES]


def target_language_labels():
    return [nome for nome, _ in LANGUAGES]


def source_filter_code(label):
    """O que o rotulo do seletor de origem significa para o banco.

    Tres respostas diferentes, e o `None` e a que nao pode ser confundida com as
    outras duas: `None` nao filtra, `""` filtra pelas linhas sem origem
    declarada, e um codigo filtra por aquele idioma. Devolver `""` para "Todos"
    esconderia a tabela inteira menos as legadas.
    """
    if label == SOURCE_FILTER_ALL:
        return None
    if label == UNKNOWN_SOURCE_LABEL:
        return SOURCE_LANGUAGE_UNKNOWN
    for nome, codigo in LANGUAGES:
        if nome == label:
            return codigo
    return None


def target_language_code(label):
    for nome, codigo in LANGUAGES:
        if nome == label:
            return codigo
    return None


def occurrence_file_labels(paths):
    """`{rotulo: caminho}` — nome curto e UNICO para cada arquivo do menu.

    O banco guarda o caminho inteiro (e a chave da ocorrencia), e o caminho
    inteiro nao cabe num menu de 200 pixels. O que o tradutor chama de capitulo e
    o nome do arquivo, entao e ele que aparece.

    Quando dois caminhos tem o mesmo nome, o rotulo ganha a pasta imediata: sem
    isso, `Livro A/cap01.pgn` e `Livro B/cap01.pgn` viriam como duas opcoes com o
    mesmo texto, e escolher uma seria sorteio. Se a pasta tambem repetir — duas
    arvores com a mesma estrutura —, o rotulo passa a ser o caminho inteiro, feio
    e correto.

    A ordem de entrada e preservada: ela vem ordenada por nome de arquivo do
    banco, que e a ordem em que capitulo se le.
    """
    repetidos = Counter(os.path.basename(caminho) for caminho in paths)
    rotulos = {}
    for caminho in paths:
        nome = os.path.basename(caminho) or caminho
        rotulo = nome
        if repetidos[nome] > 1:
            pasta = os.path.basename(os.path.dirname(caminho))
            rotulo = f"{pasta}/{nome}" if pasta else caminho
        if rotulo in rotulos:
            rotulo = caminho
        rotulos[rotulo] = caminho
    return rotulos


def format_occurrence_context(occurrences, total):
    """"Onde este comentario foi lido", para o rodape do original.

    Vazio quando nao ha ocorrencia — que e o estado de toda linha gravada antes
    desta versao (ROADMAP 18) e o de toda linha importada por CSV. Um rotulo fixo
    dizendo "sem arquivo" apareceria em 201.607 linhas do banco real e nao
    informaria nada.

    As posicoes que nao cabem viram contagem, e a contagem diz que a traducao e a
    mesma nelas: e a informacao que muda o que o revisor faz. Cabe UMA por vez —
    ver `OCCURRENCE_PREVIEW_LIMIT` para o que a tela fez com duas.

    **Um localizador por posicao, e nao dois.** O lance e o que um leitor de xadrez
    usa para achar o comentario no PGN; o indice do comentario e a ordem da
    extracao, que ninguem ve em lugar nenhum — ele entra so quando nao ha lance
    (um comentario antes do primeiro lance da partida). Levar os dois somava ~90 px
    a uma linha que ja estourava.
    """
    if not occurrences:
        return ""

    partes = []
    for source_file, game_index, comment_index, move_number in occurrences:
        pedaco = os.path.basename(source_file) or source_file
        if game_index:
            pedaco += f" · partida {game_index}"
        if move_number:
            pedaco += f" · lance {move_number}"
        else:
            pedaco += f" · comentário {comment_index}"
        partes.append(pedaco)

    texto = "Lido em: " + " | ".join(partes)
    restantes = total - len(occurrences)
    if restantes > 0:
        plural = "posição" if restantes == 1 else "posições"
        texto += f" · e mais {restantes} {plural} (a mesma tradução)"
    return texto


def format_occurrence_lines(occurrences):
    """Uma linha por posicao, para a janela que as mostra TODAS (ROADMAP 22.11).

    Diferente de `format_occurrence_context` em tres coisas, e cada uma vem de a
    janela nao ter o aperto de largura do rodape: o caminho vem INTEIRO (e o que
    distingue dois capitulos com o mesmo nome de arquivo em pastas diferentes), o
    lance e o indice do comentario aparecem juntos, e nada e resumido em
    contagem.

    Pura, para poder ser conferida sem abrir janela.
    """
    linhas = []
    for source_file, game_index, comment_index, move_number in occurrences:
        pedaco = source_file or "(sem arquivo)"
        if game_index:
            pedaco += f" · partida {game_index}"
        if move_number:
            pedaco += f" · lance {move_number}"
        pedaco += f" · comentário {comment_index}"
        linhas.append(pedaco)
    return linhas


def format_propagation_confirmation(translation, candidates, limit=PROPAGATION_PREVIEW_LIMIT):
    """A pergunta da verificacao em massa, por ORIGINAL (garantia V1).

    A mensagem antiga era um aviso depois do fato: "N iguais também verificadas".
    "Iguais" descreve as traducoes, e e justamente por isso que ela nao alarmava
    ninguem — o que esta sendo dado por revisado sao N originais DIFERENTES, cada
    um com um texto que o usuario nao leu.

    O caso que isto existe para pegar e o das traducoes curtas: se o tradutor
    verteu "Checkmate." errado como "Empate.", verificar o "Draw." -> "Empate."
    legitimo marca a linha errada junto. Com os originais na tela, quem revisa ve
    "Checkmate." na lista e responde "Nao".
    """
    linhas = [
        f"Esta tradução também está gravada para {len(candidates)} "
        f"original(is) diferente(s), ainda não verificado(s):",
        "",
        f'  Tradução: "{preview(translation, 90)}"',
        "",
        "Originais que seriam marcados como verificados:",
    ]
    for _row_id, original in candidates[:limit]:
        linhas.append(f'  - "{preview(original, 90)}"')
    if len(candidates) > limit:
        linhas.append(f"  ... e mais {len(candidates) - limit}.")
    linhas.extend(
        [
            "",
            "Marcar todos como verificados?",
            "Não: verifica só a linha aberta.",
        ]
    )
    return "\n".join(linhas)


def safe_geometry(win, geometry):
    return window_safe_geometry(win, geometry, MIN_WIDTH, MIN_HEIGHT)


def row_label(row):
    """As tres linhas de um item da lista (ROADMAP 19, item 4).

    A primeira linha carrega o que decide se vale abrir a linha, e nada mais: o
    status, o id, o **marcador de aviso QA** e o **idioma de origem**. Os dois
    ultimos faltavam, e cada um por um motivo diferente:

    - sem o marcador, achar as linhas com aviso exigia trocar o filtro para
      "Avisos QA" — e ai a lista deixava de mostrar o resto da obra, que e
      justamente o contexto de quem revisa;
    - sem a origem, em "Origem: Todos" nao havia como saber de que lingua a linha
      veio sem carrega-la. O rodape diz, mas so depois de clicar.

    O marcador sai da COLUNA materializada, e nao de reavaliar o texto: e a mesma
    resposta que o filtro usa (garantia R6). Uma linha que nao traz a coluna — as
    tuplas de sete campos — nao ganha marcador nenhum, em vez de ganhar "sem
    aviso", que seria uma afirmacao que ninguem fez.
    """
    status = "OK" if len(row) > 3 and row[3] == 1 else "PEND"
    aviso = " ⚠ QA" if row_quality_flag(row) == 1 else ""
    origem, _destino = row_language_pair(row)
    idioma = f"  {language_label(origem)}" if origem is not None else ""
    return (
        f"{status}  #{row[0]}{aviso}{idioma}\n"
        f"O: {preview(row[1], 54)}\n"
        f"T: {preview(row[2], 54)}"
    )


def row_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_COLOR
    return ROW_COLOR


def row_text_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_TEXT_COLOR
    return ROW_TEXT_COLOR


class EditorState:
    """Estado mutavel da janela de edicao, em atributos.

    Antes cada um destes campos era um dict de um item so, lido e escrito pelo
    indice: `page_index = {...}` e depois `page_index[...]` em toda parte.
    Isso nao era estilo: as dezenas de funcoes aninhadas de
    `open_translation_editor` precisam ESCREVER no estado compartilhado, e uma
    atribuicao simples dentro de uma funcao aninhada cria uma variavel local em
    vez de alterar a de fora. O dict contornava isso porque mutar um objeto nao
    e atribuir a um nome.

    Um objeto com atributos resolve o mesmo problema sem o ruido do
    `["value"]`, e — o que importa mais — deixa o estado da janela declarado num
    lugar so, em vez de espalhado por onze linhas soltas no meio da construcao
    da interface. E o primeiro passo para a janela virar uma classe (item 3.1
    do ROADMAP): quando as funcoes aninhadas virarem metodos, este estado ja
    esta reunido.
    """

    def __init__(self, font_size=12):
        # Paginacao e contagens da lista.
        self.rows = []
        self.total_rows = 0
        self.page_index = 0
        self.status_counts = {"total": 0, "pending": 0, "verified": 0, "qa": 0}
        self.active_search = ""

        # Selecao.
        self.selected_index = None
        self.selected_suggestion = None
        # Selecao em LOTE (ROADMAP 19, item 9), por id: ela sobrevive a trocar de
        # pagina, que e o que torna "exportar so a selecao" util — juntar 30 linhas
        # de tres paginas e o caso real de quem prepara uma entrega.
        self.selected_ids = set()

        # Edicao em andamento. `loading` suprime o marcador de "nao salvo"
        # enquanto o proprio programa preenche os campos.
        self.dirty = False
        self.loading = False
        self.draft_save_after = None

        # Aparencia e busca dentro do texto.
        self.font_size = font_size
        self.bold_view = False
        self.current_find_match = None

        # Pilha do "voltar" (ROADMAP 19, item 3). Cada item e um retrato do que a
        # janela mostrava antes de um SALTO — a linha aberta e os filtros que a
        # traziam —, e nao so o id: usar a busca como concordancia troca a lista, e
        # voltar para um id que a busca nova nao contem nao e voltar.
        self.history_stack = []

        # Os filtros que a ULTIMA consulta da lista usou, gravados por
        # `reload_rows`. E daqui que sai o retrato do "voltar", e nao dos
        # seletores: cada seletor chama o seu comando com o widget ja no valor
        # NOVO, entao ler o widget gravava para onde o usuario estava indo
        # (garantia F13, ROADMAP 22.3).
        self.applied_view = {}


class TranslationEditor:
    """A janela de edicao de traducoes.

    Era uma funcao de 2.2 mil linhas com 86 funcoes aninhadas, todas presas ao
    mesmo escopo de closure: mudar qualquer coisa exigia ler o arquivo inteiro
    para saber o que estava no escopo, e escrever no estado compartilhado so
    funcionava por meio de dicts de um item so. Os nomes agora sao atributos e as
    funcoes sao metodos (ROADMAP 3.1).

    A conversao nao mudou comportamento nenhum: cada funcao virou metodo com o
    mesmo corpo. O estado ja tinha sido reunido em `EditorState` na etapa 1, que
    e o que tornou este passo viavel.
    """

    def __init__(self, app):
        self.app = app
        self.build_state()
        self.build_list_pane()
        self.build_editor_pane()
        self.build_suggestion_pane()
        self.build_status_bar()
        self.connect_events()
        # Depois de `build_list_pane`, que cria os seletores de origem e destino:
        # o recorte do glossario depende dos dois (garantia S11).
        self.glossary = self.load_scoped_interactive_glossary()
        self.automatic_glossary = self.load_scoped_automatic_glossary()
        # Antes da primeira pagina: o filtro por arquivo participa da consulta que
        # a carrega, e restaurar a escolha depois faria a janela abrir na lista
        # inteira e recarregar em seguida.
        self.refresh_file_filter(restore=self.editor_settings.get("file_filter"))
        self.load_first_page()

    def read_theme_colors(self):
        """As cores que o Tk puro usa, no tema de agora.

        Os widgets do CustomTkinter recebem pares `("claro", "escuro")` e trocam
        sozinhos quando o tema muda. Estes aqui nao: os tres `PanedWindow`, os
        dois `tk.Text`, as tags deles e as bordas sao Tk puro, e recebem UMA cor
        — a escolhida no instante em que sao configurados.

        Por isso elas ficam reunidas num metodo, e nao espalhadas por dois
        `build_*`: o programa roda em `set_appearance_mode("System")`, o Windows
        troca de tema sozinho ao anoitecer, e `apply_theme_colors` precisa saber
        onde estao todas para reaplica-las (garantia F18, ROADMAP 22.8).
        """
        escuro = ctk.get_appearance_mode() == "Dark"
        self.pane_bg = "#2b2b2b" if escuro else "#d1d5db"
        self.text_bg = "#111827" if escuro else "#f9fafb"
        self.text_fg = "#e5e7eb" if escuro else "#111827"
        self.text_border = "#374151" if escuro else "#d1d5db"
        # A borda de quem tem o foco do teclado. Ela e a unica cor daqui que nao
        # existia: sem ela, o anel do container tinha a MESMA cor com e sem foco.
        self.focus_border = "#60a5fa" if escuro else "#1d4ed8"
        self.highlight_bg = "#7c5800" if escuro else "#fff3bf"
        self.highlight_fg = "#fef3c7" if escuro else "#111827"
        self.find_bg = "#334155" if escuro else "#fde68a"
        self.find_fg = "#f8fafc" if escuro else "#111827"
        self.current_find_bg = "#ea580c" if escuro else "#fb923c"
        # Texto ESCURO sobre o laranja, nos dois temas (ROADMAP 22.9). Era branco,
        # e branco sobre laranja da 2,3:1 no claro e 3,6:1 no escuro — as duas
        # reprovadas. `#111827` da 7,8:1 e 5,0:1. Quem muda e a cor do TEXTO, e nao
        # a do fundo: o fundo e o que distingue a ocorrencia atual das outras, e
        # escurece-lo o bastante para o branco passar apagaria essa diferenca.
        self.current_find_fg = "#111827"
        # As duas cores do diff da previa (ROADMAP 19, item 5). Vermelho e verde
        # apagados, e nao os saturados: o que se le ali e texto, e um fundo forte
        # atras de uma frase inteira e ilegivel.
        self.diff_removed_bg = "#7f1d1d" if escuro else "#fecaca"
        self.diff_added_bg = "#14532d" if escuro else "#bbf7d0"

    def apply_theme_colors(self, _mode=None):
        """Reaplica as cores do Tk puro. Chamada pelo rastreador de tema do CTk.

        Recebe o modo como argumento porque e assim que o rastreador chama, e o
        ignora: `read_theme_colors` pergunta ao proprio CustomTkinter, que e a
        mesma resposta e uma fonte a menos.

        Sai calada se a janela ja morreu — o rastreador guarda o callback numa
        lista de classe, e uma janela fechada nao pode virar erro na proxima
        troca de tema.
        """
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:  # pragma: no cover - interpretador ja sem Tk
            return

        self.read_theme_colors()
        for pane in (self.main_pane, self.bottom_pane, self.texts_pane):
            pane.configure(bg=self.pane_bg)

        for texto in (self.orig_text, self.trans_text):
            texto.configure(
                bg=self.text_bg, fg=self.text_fg, insertbackground=self.text_fg
            )
            texto.tag_configure(
                "glossary_hit",
                background=self.highlight_bg,
                foreground=self.highlight_fg,
            )
            texto.tag_configure(
                "find_match", background=self.find_bg, foreground=self.find_fg
            )
            texto.tag_configure(
                "find_current",
                background=self.current_find_bg,
                foreground=self.current_find_fg,
            )
            self.paint_focus_border(texto, texto is self.focused_text)

        # A borda "neutra" do campo de nota e `text_border`, entao ela tambem
        # mudou de cor (garantia F10 continua valendo: quem manda na cor e o
        # status).
        self.update_review_status_label()

    def paint_focus_border(self, texto, com_foco):
        """Pinta o anel do container do texto conforme ele tem ou nao o foco.

        Quem recebe o foco do teclado e o `tk.Text`; quem desenha a borda visivel
        e o `tk.Frame` em volta dele. Por isso o bind fica num e o efeito no
        outro — e por isso o `highlightcolor` do proprio Text nao resolveria.
        """
        cor = self.focus_border if com_foco else self.text_border
        try:
            texto.master.configure(highlightbackground=cor, highlightcolor=cor)
        except tk.TclError:  # pragma: no cover - widget ja destruido
            pass

    def build_state(self):
        """Estado da janela, variaveis de controle e fontes."""
        # Antes de qualquer widget: os `build_*` leem estas cores.
        self.read_theme_colors()
        # Qual dos dois textos tem o foco, para a troca de tema saber qual anel
        # repintar de qual cor.
        self.focused_text = None
        # O destino comeca no que a janela principal tem selecionado — que e o
        # que esta janela sempre fez — mas deixa de estar preso a ele: o seletor
        # abaixo permite trocar sem fechar o editor.
        self.lang = self.app.target_language.get()

        self.win = ctk.CTkToplevel(self.app.root)
        self.win.title(f"Editar traduções ({self.lang})")
        self.win.geometry("1280x760")
        # As mesmas constantes que `safe_geometry` usa. Escritos a mao aqui, os
        # dois numeros eram uma segunda fonte da largura minima — e foi por ela
        # que a soma dos paineis pode divergir sem ninguem notar.
        self.win.minsize(MIN_WIDTH, MIN_HEIGHT)

        self.settings = load_settings()
        self.editor_settings = self.settings.get("editor", {})
        if not isinstance(self.editor_settings, dict):
            self.editor_settings = {}

        # Restaurar a geometria salva OU maximizar — nunca as duas, que era o que
        # estava escrito aqui e fazia a restauracao perder sempre (o maximizar e
        # agendado e roda depois). Ver `restore_or_maximize`.
        saved_geometry = self.editor_settings.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            saved_geometry = safe_geometry(self.win, saved_geometry)
        restore_or_maximize(self.win, self.app.root, saved_geometry)

        self.row_buttons = []
        self.row_checkboxes = []
        # Quantas posicoes tem a linha aberta. Decide se o rodape da procedencia
        # e clicavel (ROADMAP 22.11).
        self.origin_occurrences = 0
        # `{rotulo do menu: caminho no banco}`. Refeito a cada troca de par, e nao
        # a cada consulta: agrupar as ocorrencias por arquivo custa O(ocorrencias),
        # e faze-lo por tecla digitada seria a regressao de R5 que o proprio filtro
        # veio evitar.
        self.file_options = {}
        saved_font_size = self.editor_settings.get("font_size", 12)
        if not isinstance(saved_font_size, int):
            saved_font_size = 12
        self.state = EditorState(font_size=max(9, min(24, saved_font_size)))
        self.current = {
            "id": None,
            "orig": "",
            "trans": "",
            "saved_trans": "",
            "created_at": "",
            "updated_at": "",
            "verified_at": "",
            "source_language": "",
            "target_language": "",
            # Status de revisao e nota da linha aberta (ROADMAP 19, item 12).
            "review_status": REVIEW_STATUS_PENDING,
            "reviewer_note": "",
            # True quando o texto exibido difere do banco apenas por causa das regras
            # automaticas, sem o usuario ter digitado nada. Nesse estado a gravacao
            # silenciosa (a que acontece ao navegar) e suprimida: so uma acao
            # deliberada altera o banco (garantia R1 da SPEC.md).
            "auto_only": False,
        }
        # O glossario desta janela e o recorte do PAR dela (garantia S11), e nao
        # o do app: a lista do app e o arquivo inteiro. Carregado depois de
        # `self.lang` e dos seletores existirem — ver `scoped_languages`.
        self.glossary = self.app.glossary_substitutions
        self.automatic_glossary = []
        self.current_suggestions = []
        self.suggestion_buttons = []
        self.search_text = tk.StringVar(master=self.win, value="")
        self.editor_find_text = tk.StringVar(master=self.win, value="")
        self.editor_replace_text = tk.StringVar(master=self.win, value="")
        self.editor_case_sensitive = tk.BooleanVar(master=self.win, value=False)
        self.go_page_text = tk.StringVar(master=self.win, value="")
        self.go_id_text = tk.StringVar(master=self.win, value="")
        self.reviewer_note_text = tk.StringVar(master=self.win, value="")
        self.body_font = tkfont.Font(family="Segoe UI", size=self.state.font_size)
        self.body_bold_font = tkfont.Font(family="Segoe UI", size=self.state.font_size, weight="bold")
        self.row_font = ctk.CTkFont(family="Segoe UI", size=11)
        self.suggestion_font = ctk.CTkFont(size=11)

        if not hasattr(self.app, "glossary_change_callbacks"):
            self.app.glossary_change_callbacks = []

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)


    def build_list_pane(self):
        """Painel esquerdo: paginacao, busca, filtros e a lista."""
        self.main_pane = tk.PanedWindow(
            self.win,
            orient=tk.HORIZONTAL,
            sashwidth=SASH_WIDTH,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        self.list_frame = ctk.CTkFrame(
            self.main_pane, corner_radius=8, width=LIST_PANE_DEFAULT
        )
        self.main_pane.add(self.list_frame, minsize=LIST_PANE_MIN)
        self.list_frame.columnconfigure(0, weight=1)
        # A lista e a unica que cresce. Ela desceu para a linha 7 quando a barra da
        # selecao em lote entrou na 6 (ROADMAP 19, item 9).
        self.list_frame.rowconfigure(7, weight=1)

        self.header = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        self.header.columnconfigure(1, weight=1)
        ctk.CTkLabel(self.header, text="Traduções", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.page_label = ctk.CTkLabel(self.header, text="", anchor="e")
        self.page_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.page_nav = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.page_nav.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.page_nav.columnconfigure(1, weight=1)
        self.btn_page_prev = ctk.CTkButton(self.page_nav, text="< Página", width=92)
        self.btn_page_prev.grid(row=0, column=0, sticky="w", padx=(0, 6))
        # O "voltar" fica entre as duas viradas de pagina, e nao na barra de
        # salto (ROADMAP 22.10). A razao e medida, e nao estetica: na barra de
        # salto ele era o que fazia a fileira pedir 406 px, e `grid` distribui a
        # falta entre TODAS as colunas — a sobra caia nos dois campos de digitar,
        # que ficavam com **11 px** (o da pagina) e 29 px (o do id) com o divisor
        # no minimo, e com 51 px mesmo na largura padrao do painel. Fora dali, os
        # mesmos campos medem 54 e 72 px no minimo.
        #
        # A decisao do 19.3 — que o "voltar" precisa de botao, e nao so do
        # `Alt+Backspace` — continua de pe: ele continua visivel, e agora ao lado
        # das outras duas setas, que e o que ele tambem e.
        self.btn_go_back = ctk.CTkButton(self.page_nav, text="< Voltar", width=76)
        self.btn_go_back.grid(row=0, column=1, padx=6)
        self.btn_page_next = ctk.CTkButton(self.page_nav, text="Página >", width=92)
        self.btn_page_next.grid(row=0, column=2, sticky="e", padx=(6, 0))

        self.search_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.search_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.search_bar.columnconfigure(0, weight=1)
        # O placeholder fica, e nao vira rotulo: o botao "Buscar" ao lado ja
        # nomeia o campo, e o que este texto acrescenta e o ESCOPO da busca —
        # informacao de quem esta comecando, nao de quem usa a janela o dia
        # inteiro. Ele nao aparece hoje (ver `find_bar`, garantia F17), e voltaria
        # sozinho se o CustomTkinter corrigir a comparacao. Um rotulo permanente
        # com esta frase custaria ~230 px numa coluna de 320 px de minimo.
        self.search_entry = ctk.CTkEntry(
            self.search_bar,
            textvariable=self.search_text,
            placeholder_text="Buscar no original ou tradução",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_search = ctk.CTkButton(self.search_bar, text="Buscar", width=82)
        self.btn_search.grid(row=0, column=1, padx=(0, 6))
        # "Limpar busca", e nao "Limpar": a janela tinha TRES botoes escritos
        # "Limpar" fazendo tres coisas diferentes — este, o da selecao em lote e
        # o do status de revisao, que GRAVA no banco (ROADMAP 22.10). Um rotulo
        # que nao carrega o objeto obriga a deduzi-lo da posicao, e a posicao e
        # justamente o que muda quando a janela e reorganizada.
        self.btn_clear_search = ctk.CTkButton(
            self.search_bar, text="Limpar busca", width=100
        )
        self.btn_clear_search.grid(row=0, column=2)

        # As duas buscas nao sao a mesma coisa e nenhuma serve para tudo, entao a
        # escolha e do usuario e fica a vista (garantia R8):
        #   Termos  — indexado, custa o tamanho da pagina, casa palavra inteira
        #   Trecho  — varre a tabela, mas acha qualquer pedaco literal
        self.search_mode_segment = ctk.CTkSegmentedButton(
            self.search_bar,
            values=[SEARCH_MODE_LABEL_TERMS, SEARCH_MODE_LABEL_SUBSTRING],
        )
        saved_mode = self.editor_settings.get("search_mode", SEARCH_MODE_LABEL_TERMS)
        if saved_mode not in {SEARCH_MODE_LABEL_TERMS, SEARCH_MODE_LABEL_SUBSTRING}:
            saved_mode = SEARCH_MODE_LABEL_TERMS
        self.search_mode_segment.set(saved_mode)
        self.search_mode_segment.grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0)
        )

        self.jump_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.jump_bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.jump_bar.columnconfigure(1, weight=1)
        self.jump_bar.columnconfigure(4, weight=1)
        ctk.CTkLabel(self.jump_bar, text="Página").grid(row=0, column=0, sticky="w")
        self.page_entry = ctk.CTkEntry(self.jump_bar, textvariable=self.go_page_text, width=64)
        self.page_entry.grid(row=0, column=1, sticky="ew", padx=(6, 4))
        self.btn_go_page = ctk.CTkButton(self.jump_bar, text="Ir", width=46)
        self.btn_go_page.grid(row=0, column=2, padx=(0, 10))
        ctk.CTkLabel(self.jump_bar, text="ID").grid(row=0, column=3, sticky="w")
        self.id_entry = ctk.CTkEntry(self.jump_bar, textvariable=self.go_id_text, width=82)
        self.id_entry.grid(row=0, column=4, sticky="ew", padx=(6, 4))
        self.btn_go_id = ctk.CTkButton(self.jump_bar, text="Ir", width=46)
        self.btn_go_id.grid(row=0, column=5)

        self.status_segment = ctk.CTkSegmentedButton(
            self.list_frame,
            values=list(STATUS_FILTER_LABELS),
        )
        saved_status = self.editor_settings.get("status_filter", "Todas")
        if saved_status not in STATUS_FILTER_LABELS:
            saved_status = "Todas"
        self.status_segment.set(saved_status)
        self.status_segment.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))

        self.build_language_bar()
        self.build_batch_bar()

        self.rows_frame = ctk.CTkScrollableFrame(self.list_frame, height=420)
        self.rows_frame.grid(row=7, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def build_batch_bar(self):
        """A barra da selecao em lote, entre os filtros e a lista.

        Fica ai porque e onde ela se explica: as acoes valem para o que esta
        marcado NA LISTA, e a lista comeca logo abaixo. No rodape da janela ela
        ficaria junto das acoes da linha ABERTA, e as duas seriam confundidas —
        "Marcar como verificada" e "Marcar selecionadas" fazem coisas diferentes.

        **Duas fileiras e `grid`, e nao uma fileira e `pack`** (ROADMAP 22.10).
        Medido na janela real com o divisor no minimo da lista (320 px, que da
        300 uteis): a fileira unica pedia 435 px, o "Verificar" aparecia com 25
        dos seus 80 e o "Exportar" comecava em x=355 — inteiramente fora da
        faixa. Nao era o ultimo botao que sumia por acaso: `pack` nao encolhe
        filho nenhum, entrega a largura pedida a quem chega primeiro e simplesmente
        nao desenha o que sobrar. `grid` com peso divide a falta entre todos —
        medido, quatro botoes de 120 px num quadro de 300 ficam com 71 px cada.

        Os rotulos tambem mudaram, e por isso a fileira unica deixou de caber de
        vez: "Página" (que MARCA) lido a duas linhas dos botoes "< Página" e
        "Página >" (que NAVEGAM) e "Limpar" (que desmarca) ao lado de outros dois
        "Limpar" que fazem outras coisas.
        """
        self.batch_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.batch_bar.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.batch_bar.columnconfigure(0, weight=1)

        marcar = ctk.CTkFrame(self.batch_bar, fg_color="transparent")
        marcar.grid(row=0, column=0, sticky="ew")
        for coluna in range(3):
            marcar.columnconfigure(coluna, weight=1)

        self.btn_batch_page = ctk.CTkButton(marcar, text="Marcar página", width=104)
        self.btn_batch_page.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        # "Marcar tudo" e o filtro inteiro, e nao a pagina (ROADMAP 22.11):
        # marcar os 3.000 resultados de um capitulo eram 30 idas ao botao da
        # pagina mais 29 viradas.
        self.btn_batch_all = ctk.CTkButton(marcar, text="Marcar tudo", width=92)
        self.btn_batch_all.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self.btn_batch_clear = ctk.CTkButton(marcar, text="Desmarcar", width=86)
        self.btn_batch_clear.grid(row=0, column=2, sticky="ew")

        acoes = ctk.CTkFrame(self.batch_bar, fg_color="transparent")
        acoes.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        acoes.columnconfigure(0, weight=1)

        self.batch_label = ctk.CTkLabel(
            acoes,
            text="nenhuma selecionada",
            text_color=MUTED_TEXT_COLOR,
            anchor="w",
        )
        self.batch_label.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_batch_verify = ctk.CTkButton(acoes, text="Verificar", width=80)
        self.btn_batch_verify.grid(row=0, column=1, padx=(0, 4))
        self.btn_batch_export = ctk.CTkButton(acoes, text="Exportar", width=80)
        self.btn_batch_export.grid(row=0, column=2)

    def build_language_bar(self):
        """Os seletores de idioma e o de arquivo, acima da lista.

        Ficam junto dos outros filtros, e nao numa barra propria no topo da
        janela, porque e isso que eles sao: filtram a mesma lista que o status e
        a busca filtram, e a lista e o que muda quando qualquer um dos tres muda.

        O de ARQUIVO tem uma linha propria porque ele nao e um par com os outros
        dois — e mais largo (nome de capitulo) e escolher um muda tambem a ORDEM
        da lista, que e o que a secao 18 do ROADMAP existe para dar.

        **Sao menus, e nao botoes segmentados como o status.** Oito idiomas em
        botoes lado a lado nao cabem na largura do painel, e a forma segmentada so
        se paga quando todas as opcoes ficam visiveis de uma vez.

        A ORIGEM e o filtro que este item existe para dar (ver ROADMAP), e por
        isso ela e a primeira e a unica com a opcao "Todos": o destino nunca e
        "todos", porque a janela edita as traducoes de um idioma so — o rascunho,
        o titulo e a aplicacao das regras automaticas sao todos por idioma de
        destino.
        """
        self.language_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.language_bar.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.language_bar.columnconfigure(1, weight=1)
        self.language_bar.columnconfigure(3, weight=1)

        ctk.CTkLabel(self.language_bar, text="Arquivo").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.file_menu = ctk.CTkOptionMenu(
            self.language_bar,
            values=[FILE_FILTER_ALL],
            command=lambda _value: self.change_file_filter(),
        )
        self.file_menu.set(FILE_FILTER_ALL)
        self.file_menu.grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(6, 0)
        )

        ctk.CTkLabel(self.language_bar, text="Origem").grid(row=0, column=0, sticky="w")
        self.source_menu = ctk.CTkOptionMenu(
            self.language_bar,
            values=source_filter_labels(),
            command=lambda _value: self.change_language_filter(),
        )
        saved_source = self.editor_settings.get("source_filter", SOURCE_FILTER_ALL)
        if saved_source not in source_filter_labels():
            saved_source = SOURCE_FILTER_ALL
        self.source_menu.set(saved_source)
        self.source_menu.grid(row=0, column=1, sticky="ew", padx=(6, 10))

        ctk.CTkLabel(self.language_bar, text="Destino").grid(row=0, column=2, sticky="w")
        self.target_menu = ctk.CTkOptionMenu(
            self.language_bar,
            values=target_language_labels(),
            command=lambda _value: self.change_language_filter(),
        )
        # Um idioma que nao esteja na lista (um banco antigo com um codigo que o
        # programa nao oferece mais) cai no primeiro em vez de deixar o menu em
        # branco — e o `change_language_filter` que roda depois grava a troca.
        self.target_menu.set(LANGUAGE_NAMES.get(self.lang, LANGUAGES[0][0]))
        self.target_menu.grid(row=0, column=3, sticky="ew", padx=(6, 0))


    def build_editor_pane(self):
        """Painel central: original, traducao e busca no texto."""
        self.bottom_pane = tk.PanedWindow(
            self.main_pane,
            orient=tk.HORIZONTAL,
            sashwidth=SASH_WIDTH,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.main_pane.add(self.bottom_pane, minsize=BOTTOM_PANE_MIN)

        self.text_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.text_frame, minsize=EDITOR_PANE_MIN)
        self.text_frame.columnconfigure(0, weight=1)
        # Row 0 e o divisor dos dois textos; as barras que sobram vem depois dele.
        self.text_frame.rowconfigure(0, weight=1, minsize=300)

        # Os dois textos vivem num divisor proprio (ROADMAP 19, item 1). Empilhados,
        # o original tem 6 linhas contra as 12 da traducao, e um comentario longo de
        # livro obriga a rolar a FONTE enquanto se escreve a traducao. Lado a lado,
        # os dois crescem juntos. E um divisor, e nao dois layouts alternativos,
        # porque assim a proporcao entre eles continua sendo do usuario nas duas
        # orientacoes — e trocar a orientacao e uma linha (`configure(orient=...)`),
        # sem destruir os widgets e perder o texto e o desfazer de dentro deles.
        self.side_by_side = bool(self.editor_settings.get("side_by_side", False))
        self.texts_pane = tk.PanedWindow(
            self.text_frame,
            orient=tk.HORIZONTAL if self.side_by_side else tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.FLAT,
            bd=0,
            bg=self.pane_bg,
        )
        self.texts_pane.grid(row=0, column=0, sticky="nsew")

        self.original_block = ctk.CTkFrame(self.texts_pane, fg_color="transparent")
        self.texts_pane.add(self.original_block, minsize=120)
        self.original_block.columnconfigure(0, weight=1)
        self.original_block.rowconfigure(1, weight=1)

        self.translation_block = ctk.CTkFrame(self.texts_pane, fg_color="transparent")
        self.texts_pane.add(self.translation_block, minsize=180)
        self.translation_block.columnconfigure(0, weight=1)
        self.translation_block.rowconfigure(1, weight=1)

        # "Original:" e, embaixo dele, de onde este original foi lido. O lugar e
        # aqui e nao no rodape da janela porque a procedencia e do ORIGINAL: e o
        # texto do livro que tem arquivo, partida e lance — a traducao e a do
        # acervo, e pode servir a doze livros (ROADMAP 18).
        self.original_header = ctk.CTkFrame(self.original_block, fg_color="transparent")
        self.original_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 2))
        self.original_header.columnconfigure(0, weight=1)
        ctk.CTkLabel(self.original_header, text="Original:").grid(
            row=0, column=0, sticky="w"
        )
        # **Linha propria, e medida.** Na mesma linha do rotulo, um nome de capitulo
        # de verdade ("Move by Move - Sicilian - capitulo 01.pgn") pedia 728 px numa
        # faixa de 596: o Tk cortava o texto e, encostado a direita, cortava o
        # COMECO dele — o nome do arquivo, que e a parte que responde a pergunta.
        # Em linha propria e ancorado a oeste, a faixa inteira e dele e o que falta
        # sai do fim.
        self.origin_label = ctk.CTkLabel(
            self.original_header,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=MUTED_TEXT_COLOR,
        )
        # Clicavel quando ha mais de uma posicao (ROADMAP 22.11). O rodape dizia
        # "e mais N posições (a mesma tradução)" e nenhum gesto mostrava QUAIS —
        # e antes de editar um texto que serve a doze posicoes, "em que capitulos
        # isto aparece" e o que decide se a edicao vale para todas. O bind fica
        # sempre ligado e quem decide e o metodo: ligar e desligar conforme a
        # linha aberta deixaria o estado do bind e o da tela divergirem.
        self.origin_label.bind("<Button-1>", self.open_occurrences_window)
        self.orig_text = self.create_text_editor(self.original_block, 1, readonly=True)
        self.translation_header = ctk.CTkFrame(
            self.translation_block, fg_color="transparent"
        )
        self.translation_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(0, 2))
        ctk.CTkLabel(self.translation_header, text="Tradução:").pack(side=tk.LEFT)
        self.font_controls = ctk.CTkFrame(self.translation_header, fg_color="transparent")
        self.font_controls.pack(side=tk.RIGHT)
        # O primeiro dos controles, e nao um item de menu: a orientacao e uma
        # escolha que se experimenta — o revisor a troca, olha, e decide.
        self.btn_layout = ctk.CTkButton(self.font_controls, text="", width=42)
        self.btn_layout.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_font_down = ctk.CTkButton(self.font_controls, text="A-", width=42)
        self.btn_font_down.pack(side=tk.LEFT, padx=(0, 4))
        self.font_label = ctk.CTkLabel(self.font_controls, text=f"{self.state.font_size} pt", width=46)
        self.font_label.pack(side=tk.LEFT)
        self.btn_font_up = ctk.CTkButton(self.font_controls, text="A+", width=42)
        self.btn_font_up.pack(side=tk.LEFT, padx=4)
        self.btn_bold = ctk.CTkButton(
            self.font_controls,
            text="B",
            width=42,
            font=ctk.CTkFont(weight="bold"),
        )
        self.btn_bold.pack(side=tk.LEFT, padx=(4, 0))
        self.trans_text = self.create_text_editor(
            self.translation_block, 1, bottom_pad=4
        )
        self.update_layout_button()

        # Os dois campos tem ROTULO, e nao placeholder (garantia F17, ROADMAP
        # 22.7). Eram os unicos campos da janela sem nada que os nomeasse: dois
        # retangulos iguais lado a lado, um que busca e um que substitui. O
        # placeholder que deveria distingui-los nunca apareceu — o CustomTkinter
        # 5.2.2 compara o OBJETO `StringVar` com `""` para decidir se o mostra, e
        # essa comparacao e falsa sempre —, e mesmo se aparecesse ele some na
        # primeira tecla, que e justamente quando os dois campos ficam parecidos.
        self.find_bar = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        self.find_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.find_bar.columnconfigure(1, weight=1)
        self.find_bar.columnconfigure(3, weight=1)

        ctk.CTkLabel(self.find_bar, text="Buscar:").grid(row=0, column=0, sticky="w")
        self.editor_find_entry = ctk.CTkEntry(
            self.find_bar,
            textvariable=self.editor_find_text,
            width=120,
        )
        self.editor_find_entry.grid(row=0, column=1, sticky="ew", padx=(6, 10))
        # "Trocar por:" e nao "Substituir:": o botao que aplica este campo se
        # chama "Trocar", e o rotulo tem de usar a palavra do botao.
        ctk.CTkLabel(self.find_bar, text="Trocar por:").grid(
            row=0, column=2, sticky="w"
        )
        self.editor_replace_entry = ctk.CTkEntry(
            self.find_bar,
            textvariable=self.editor_replace_text,
            width=120,
        )
        self.editor_replace_entry.grid(row=0, column=3, sticky="ew", padx=(6, 0))
        self.find_buttons = ctk.CTkFrame(self.find_bar, fg_color="transparent")
        self.find_buttons.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.btn_find_next = ctk.CTkButton(self.find_buttons, text="Prox.", width=58)
        self.btn_find_next.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_replace_current = ctk.CTkButton(self.find_buttons, text="Trocar", width=68)
        self.btn_replace_current.pack(side=tk.LEFT, padx=4)
        self.btn_replace_all = ctk.CTkButton(self.find_buttons, text="Todos", width=62)
        self.btn_replace_all.pack(side=tk.LEFT, padx=4)
        self.case_check = ctk.CTkCheckBox(
            self.find_buttons,
            text="Aa",
            variable=self.editor_case_sensitive,
            width=46,
        )
        self.case_check.pack(side=tk.LEFT, padx=(4, 0))

        # A nota do revisor (ROADMAP 19, item 12). Uma linha de entrada, e nao um
        # bloco de texto: ela e um recado curto — "conferir com o autor", "termo
        # inventado" —, e um campo alto roubaria altura da traducao para um texto que
        # quase sempre tem cinco palavras.
        self.note_bar = ctk.CTkFrame(self.text_frame, fg_color="transparent")
        self.note_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.note_bar.columnconfigure(1, weight=1)
        ctk.CTkLabel(self.note_bar, text="Nota:").grid(row=0, column=0, sticky="w")
        self.note_entry = ctk.CTkEntry(
            self.note_bar,
            textvariable=self.reviewer_note_text,
            placeholder_text="Por que esta linha volta (rejeitada ou em dúvida)",
        )
        self.note_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        # O status EM PALAVRAS (garantia F19, ROADMAP 22.9). Ele era comunicado so
        # pela cor da borda do campo, e cor sozinha nao e informacao: para um
        # protanope as duas viram tons de oliva com 2,8:1 entre si, e a mensagem
        # "Marcada como rejeitada" some em segundos. Sai do grid quando a linha
        # esta pendente — o padrao nao precisa de rotulo —, como o rodape da
        # procedencia faz.
        self.review_status_label = ctk.CTkLabel(
            self.note_bar, text="", anchor="w", font=ctk.CTkFont(weight="bold")
        )
        self.btn_reject = ctk.CTkButton(self.note_bar, text="Rejeitar", width=90)
        self.btn_reject.grid(row=0, column=3, padx=(0, 4))
        self.btn_doubt = ctk.CTkButton(self.note_bar, text="Em dúvida", width=96)
        self.btn_doubt.grid(row=0, column=4, padx=(0, 4))
        # "Limpar status" (ROADMAP 22.10). Era o mais perigoso dos tres "Limpar"
        # da janela: os outros dois mexem so na tela, e este GRAVA no banco.
        self.btn_clear_status = ctk.CTkButton(
            self.note_bar, text="Limpar status", width=102
        )
        self.btn_clear_status.grid(row=0, column=5)

        self.qa_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            text_color=OK_TEXT_COLOR,
        )
        self.qa_label.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 2))
        self.history_label = ctk.CTkLabel(
            self.text_frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
        )
        self.history_label.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))


    def create_text_editor(self, parent, row, readonly=False, bottom_pad=8):
        container = tk.Frame(
            parent,
            bg=self.text_border,
            highlightthickness=1,
            highlightbackground=self.text_border,
        )
        container.grid(row=row, column=0, sticky="nsew", padx=10, pady=(0, bottom_pad))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        text = tk.Text(
            container,
            wrap=tk.WORD,
            undo=not readonly,
            relief=tk.FLAT,
            borderwidth=0,
            font=self.body_font,
            bg=self.text_bg,
            fg=self.text_fg,
            insertbackground=self.text_fg,
            selectbackground="#2563eb",
            selectforeground="#ffffff",
            padx=8,
            pady=6,
            height=6 if readonly else 12,
        )
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.tag_configure("bold", font=self.body_bold_font)
        text.tag_configure(
            "glossary_hit",
            background=self.highlight_bg,
            foreground=self.highlight_fg,
            font=self.body_bold_font,
        )
        text.tag_configure(
            "find_match",
            background=self.find_bg,
            foreground=self.find_fg,
        )
        text.tag_configure(
            "find_current",
            background=self.current_find_bg,
            foreground=self.current_find_fg,
        )

        # O foco do teclado passa a ter sinal (garantia F18, ROADMAP 22.8). Numa
        # janela com ~30 botoes e 6 campos, o unico sinal de onde o Tab parou era
        # o cursor piscando dentro de um texto — e nenhum widget do CustomTkinter
        # desenha indicador de foco (o unico que reage a `<FocusIn>` e o
        # `CTkEntry`, e so para trocar o placeholder, que nem aparece — F17).
        text.bind("<FocusIn>", lambda _event, t=text: self.on_text_focus(t, True))
        text.bind("<FocusOut>", lambda _event, t=text: self.on_text_focus(t, False))

        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    def on_text_focus(self, texto, ganhou):
        """Guarda quem tem o foco e pinta o anel dele.

        O estado e guardado, e nao so pintado, porque a troca de tema repinta os
        dois aneis e precisa saber qual deles e o do campo em foco.
        """
        self.focused_text = texto if ganhou else None
        self.paint_focus_border(texto, ganhou)


    def build_suggestion_pane(self):
        """Painel direito: sugestoes do glossario."""
        self.sugg_frame = ctk.CTkFrame(self.bottom_pane, corner_radius=8)
        self.bottom_pane.add(self.sugg_frame, minsize=SUGGESTION_PANE_MIN)
        self.sugg_frame.columnconfigure(0, weight=1)
        self.sugg_frame.columnconfigure(1, weight=1)
        self.sugg_frame.rowconfigure(1, weight=1)

        ctk.CTkLabel(self.sugg_frame, text="Sugestões do glossário:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4)
        )

        self.suggestions_frame = ctk.CTkScrollableFrame(self.sugg_frame, height=160)
        self.suggestions_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            padx=10,
            pady=(0, 8),
        )

        self.btn_refresh = ctk.CTkButton(self.sugg_frame, text="Recarregar sugestões")
        self.btn_apply_one = ctk.CTkButton(self.sugg_frame, text="Aplicar selecionada")
        self.btn_apply_all = ctk.CTkButton(self.sugg_frame, text="Aplicar todas")
        self.btn_add_gloss = ctk.CTkButton(self.sugg_frame, text="Adicionar ao glossário")
        self.btn_reload_gloss = ctk.CTkButton(self.sugg_frame, text="Atualizar glossário")
        self.btn_open_gloss = ctk.CTkButton(self.sugg_frame, text="Editar glossário")

        self.btn_refresh.grid(row=2, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.btn_apply_one.grid(row=2, column=1, sticky="ew", padx=(4, 10), pady=4)
        self.btn_apply_all.grid(row=3, column=0, sticky="ew", padx=(10, 4), pady=4)
        self.btn_add_gloss.grid(row=3, column=1, sticky="ew", padx=(4, 10), pady=4)
        self.btn_reload_gloss.grid(row=4, column=0, sticky="ew", padx=(10, 4), pady=(0, 10))
        self.btn_open_gloss.grid(row=4, column=1, sticky="ew", padx=(4, 10), pady=(0, 10))


    def build_status_bar(self):
        """Rodape: mensagens, contagens e os botoes de acao."""
        self.status_frame = ctk.CTkFrame(self.win, corner_radius=8)
        self.status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.status_frame.columnconfigure(0, weight=1)

        self.status_info = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.status_info.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

        # **A ORDEM DE EMPACOTAMENTO decide quem some quando falta espaco**, e nao
        # a ordem na tela (ROADMAP 22.10). `pack` atende quem chega primeiro e
        # simplesmente nao desenha o que sobrar. Os cinco rotulos eram todos
        # `side=LEFT` na ordem em que se leem, e o pior caso medido pedia 1.167 px
        # numa faixa de 1.080: quem sumia era o ULTIMO empacotado, o
        # `counts_label` — a contagem que FICA, empurrada por uma mensagem que ia
        # embora sozinha em 1,5 s.
        #
        # A ordem abaixo e a de importancia, e nao a da leitura. As tres decisoes,
        # da mais protegida para a menos:
        #
        #   1. o aviso de que ha texto nao salvo, que e o unico rotulo da faixa
        #      cuja ausencia custa trabalho ao usuario;
        #   2. as duas contagens estaveis, que respondem "onde estou" e "quanto
        #      falta" e ficam ancoradas a direita;
        #   3. a mensagem transitoria, cortada por `preview` (ver `show_message`),
        #      e o estado do rascunho — os dois que se repoem sozinhos.
        #
        # A posicao na tela continua saindo do `side`: os dois `RIGHT` vao para a
        # direita mesmo tendo sido empacotados no meio.
        self.btn_shortcuts = ctk.CTkButton(self.status_info, text="?", width=32)
        self.btn_shortcuts.pack(side=tk.RIGHT)

        self.dirty_label = ctk.CTkLabel(self.status_info, text="Salvo", text_color=OK_TEXT_COLOR)
        self.dirty_label.pack(side=tk.LEFT, padx=(0, 12))

        self.counts_label = ctk.CTkLabel(
            self.status_info,
            text="Todas: 0 · Pendentes: 0 · Verificadas: 0 · QA: 0",
        )
        self.counts_label.pack(side=tk.RIGHT, padx=(12, 12))

        self.selection_label = ctk.CTkLabel(self.status_info, text="Item 0/0")
        self.selection_label.pack(side=tk.RIGHT, padx=(12, 0))

        self.msg_label = ctk.CTkLabel(self.status_info, text="", text_color=OK_TEXT_COLOR)
        self.msg_label.pack(side=tk.LEFT)

        self.draft_label = ctk.CTkLabel(self.status_info, text="", text_color=MUTED_TEXT_COLOR)
        self.draft_label.pack(side=tk.LEFT, padx=(12, 0))

        self.primary_actions = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.primary_actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 4))
        self.secondary_actions = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.secondary_actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.btn_save_verify = ctk.CTkButton(
            self.primary_actions,
            text="Salvar e verificar",
            width=150,
        )
        self.btn_save_plain = ctk.CTkButton(self.primary_actions, text="Salvar", width=90)
        self.btn_mark = ctk.CTkButton(
            self.primary_actions,
            text="Marcar como verificada",
            width=170,
        )
        self.btn_pending = ctk.CTkButton(
            self.primary_actions,
            text="Marcar como pendente",
            width=165,
        )
        self.btn_prev = ctk.CTkButton(self.primary_actions, text="< Anterior", width=110)
        self.btn_next = ctk.CTkButton(self.primary_actions, text="Próxima >", width=110)

        for index, button in enumerate(
            [
                self.btn_save_verify,
                self.btn_save_plain,
                self.btn_mark,
                self.btn_pending,
                self.btn_prev,
                self.btn_next,
            ]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
            self.primary_actions.columnconfigure(index, weight=1)

        self.btn_copy_original = ctk.CTkButton(
            self.secondary_actions,
            text="Copiar original",
            width=120,
        )
        self.btn_restore = ctk.CTkButton(self.secondary_actions, text="Restaurar", width=90)
        self.btn_undo = ctk.CTkButton(self.secondary_actions, text="Desfazer", width=86)
        self.btn_redo = ctk.CTkButton(self.secondary_actions, text="Refazer", width=78)
        self.btn_next_qa = ctk.CTkButton(
            self.secondary_actions,
            text="Próximo aviso QA",
            width=150,
        )
        self.btn_export_qa = ctk.CTkButton(self.secondary_actions, text="Exportar QA", width=110)
        self.btn_apply_auto = ctk.CTkButton(
            self.secondary_actions,
            text="Aplicar automaticas",
            width=150,
        )
        self.btn_history = ctk.CTkButton(self.secondary_actions, text="Hist\u00f3rico", width=100)

        for index, button in enumerate(
            [
                self.btn_copy_original,
                self.btn_restore,
                self.btn_undo,
                self.btn_redo,
                self.btn_next_qa,
                self.btn_export_qa,
                self.btn_apply_auto,
                self.btn_history,
            ]
        ):
            button.grid(row=0, column=index, sticky="ew", padx=(0, 6), pady=2)
            self.secondary_actions.columnconfigure(index, weight=1)


    def connect_events(self):
        """Liga cada botao, atalho e evento ao metodo correspondente."""
        self.btn_copy_original.configure(command=self.copy_original_to_translation)
        self.btn_restore.configure(command=self.restore_saved_translation)
        self.btn_undo.configure(command=self.undo_translation)
        self.btn_redo.configure(command=self.redo_translation)
        self.btn_save_plain.configure(command=lambda: self.save_changes(False))
        self.btn_save_verify.configure(command=lambda: self.save_changes(False, mark_verified=True))
        self.btn_font_down.configure(command=lambda: self.adjust_font(-1))
        self.btn_font_up.configure(command=lambda: self.adjust_font(1))
        self.btn_bold.configure(command=self.toggle_bold_view)
        self.btn_layout.configure(command=self.toggle_side_by_side)
        self.btn_search.configure(command=self.apply_search)
        self.btn_clear_search.configure(command=self.clear_search)
        self.btn_go_page.configure(command=self.go_to_page)
        self.btn_go_id.configure(command=self.go_to_id)
        self.btn_go_back.configure(command=self.go_back)
        self.btn_batch_page.configure(command=self.select_page_rows)
        self.btn_batch_all.configure(command=self.select_all_filtered_rows)
        self.btn_batch_clear.configure(command=self.clear_row_selection)
        self.btn_batch_verify.configure(command=self.verify_selected_rows)
        self.btn_batch_export.configure(command=self.export_selected_rows)
        self.btn_reject.configure(
            command=lambda: self.set_review_status(REVIEW_STATUS_REJECTED)
        )
        self.btn_doubt.configure(
            command=lambda: self.set_review_status(REVIEW_STATUS_DOUBT)
        )
        self.btn_clear_status.configure(
            command=lambda: self.set_review_status(REVIEW_STATUS_PENDING)
        )
        self.btn_page_prev.configure(command=lambda: self.change_page(-1))
        self.btn_page_next.configure(command=lambda: self.change_page(1))
        self.btn_prev.configure(command=lambda: self.navigate(-1))
        self.btn_next.configure(command=lambda: self.navigate(1))
        self.btn_mark.configure(command=self.mark_and_next)
        self.btn_pending.configure(command=self.mark_pending)
        self.btn_next_qa.configure(command=self.go_to_next_quality_warning)
        self.btn_export_qa.configure(command=self.export_quality_report)
        self.btn_apply_auto.configure(command=self.apply_automatic_rules_for_current_language)
        self.btn_history.configure(command=self.open_history_window)
        self.status_segment.configure(command=lambda _value: self.toggle_filter())
        # Trocar o modo refaz a busca na hora: deixar o resultado antigo na tela
        # com o seletor novo faria a lista mentir sobre o que esta mostrando.
        self.search_mode_segment.configure(command=lambda _value: self.apply_search())
        self.btn_refresh.configure(command=self.refresh_suggestions)
        self.btn_apply_one.configure(command=self.apply_one)
        self.btn_apply_all.configure(command=self.apply_all)
        self.btn_add_gloss.configure(command=self.add_gloss_popup)
        self.btn_reload_gloss.configure(command=self.reload_glossary)
        self.btn_open_gloss.configure(command=self.open_integrated_glossary_editor)
        self.btn_find_next.configure(command=self.find_next_in_translation)
        self.btn_replace_current.configure(command=self.replace_current_in_translation)
        self.btn_replace_all.configure(command=self.replace_all_in_translation)
        self.editor_find_text.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        self.editor_case_sensitive.trace_add(
            "write",
            lambda *_args: self.refresh_find_matches(keep_current=False),
        )
        # A nota do revisor fecha o ciclo do teclado (ROADMAP 22.11): digitar e
        # navegar a descartava em silencio, e `Enter` no campo nao fazia nada.
        self.reviewer_note_text.trace_add("write", lambda *_args: self.on_note_edited())
        self.note_entry.bind("<Return>", self.save_note_shortcut)
        self.search_entry.bind("<Return>", lambda _event: self.apply_search())
        self.editor_find_entry.bind("<Return>", self.find_next_in_translation)
        self.editor_replace_entry.bind("<Return>", self.replace_current_in_translation)
        self.page_entry.bind("<Return>", lambda _event: self.go_to_page())
        self.id_entry.bind("<Return>", lambda _event: self.go_to_id())
        self.trans_text.bind("<<Modified>>", self.on_translation_modified)
        self.trans_text.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.trans_text.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.trans_text.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.trans_text.bind("<Control-b>", self.toggle_bold_selection)
        self.trans_text.bind("<Control-B>", self.toggle_bold_selection)
        # `Ctrl+F` no TEXTO e `Ctrl+L` na LISTA (ROADMAP 19, item 2).
        self.win.bind("<Control-f>", self.focus_editor_find)
        self.win.bind("<Control-F>", self.focus_editor_find)
        self.win.bind("<Control-l>", self.focus_search)
        self.win.bind("<Control-L>", self.focus_search)
        # Voltar de onde a busca tirou o revisor (ROADMAP 19, item 3).
        self.win.bind("<Alt-BackSpace>", self.go_back_shortcut)
        self.win.bind("<Control-h>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-H>", lambda _event: (self.open_history_window(), "break")[1])
        self.win.bind("<Control-s>", self.save_shortcut)
        self.win.bind("<Control-S>", self.save_shortcut)
        self.win.bind("<Control-Return>", self.verify_shortcut)
        # Verificar-e-avancar, que era a unica acao do fluxo alcancavel so pelo
        # botao (ROADMAP 22.11). `Ctrl+Enter` verifica e FICA na linha: so no
        # filtro "Pendentes" a linha sai da lista e a proxima entra de brinde —
        # em "Todas", que e o contexto que o 19.4 defende para quem revisa, eram
        # dois acordes por linha. `mark_and_next` faz a coisa certa nos dois
        # filtros, e ganha o acorde vizinho do que ja existia em vez de tomar o
        # lugar dele: quem tem o Ctrl+Enter na memoria dos dedos continua com ele.
        self.win.bind("<Control-Shift-Return>", self.mark_and_next_shortcut)
        # As viradas de pagina existiam so nos botoes. O `Control` e o que impede
        # de roubar a rolagem nativa do texto — `PageDown` dentro de um
        # comentario longo tem de continuar rolando o comentario.
        self.win.bind("<Control-Prior>", lambda _event: (self.change_page(-1), "break")[1])
        self.win.bind("<Control-Next>", lambda _event: (self.change_page(1), "break")[1])
        # Zoom pelo teclado e pela roda. Ir de 12 a 18 pt eram seis cliques num
        # botao de 42 px. As tres teclas sao a mesma acao em teclados diferentes:
        # onde o "+" exige Shift, o Tk entrega `<Control-plus>`; onde nao, chega
        # `<Control-equal>`.
        self.win.bind("<Control-plus>", lambda _event: (self.adjust_font(1), "break")[1])
        self.win.bind("<Control-equal>", lambda _event: (self.adjust_font(1), "break")[1])
        self.win.bind("<Control-minus>", lambda _event: (self.adjust_font(-1), "break")[1])
        self.win.bind("<Control-MouseWheel>", self.zoom_with_wheel)
        self.win.bind("<Control-z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-Z>", lambda _event: (self.undo_translation(), "break")[1])
        self.win.bind("<Control-y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Control-Y>", lambda _event: (self.redo_translation(), "break")[1])
        self.win.bind("<Alt-Left>", self.previous_shortcut)
        self.win.bind("<Alt-Right>", self.next_shortcut)
        self.win.bind("<F3>", self.find_next_in_translation)
        self.win.bind("<F7>", self.next_quality_warning_shortcut)
        # F1 e o "?" do rodape: os dois unicos caminhos de descoberta dos treze
        # atalhos (garantia F18, ROADMAP 22.8).
        self.win.bind("<F1>", self.open_shortcuts_window)
        self.btn_shortcuts.configure(command=self.open_shortcuts_window)
        self.win.bind(
            "<Destroy>",
            lambda event: self.unregister_glossary_callback() if event.widget is self.win else None,
        )
        self.win.protocol("WM_DELETE_WINDOW", self.close_editor)

        # O tema do sistema pode trocar com a janela aberta — o programa roda em
        # `set_appearance_mode("System")` e o CustomTkinter re-detecta o tema do
        # Windows a cada 30 ms. Os widgets CTk se atualizam sozinhos; o Tk puro
        # daqui, nao (garantia F18, ROADMAP 22.8). O registrador e interno da
        # biblioteca, entao a falta dele nao pode impedir a janela de abrir: o
        # preco de nao ter o gancho e a janela ficar com as cores do tema
        # anterior ate ser reaberta, que e exatamente o que acontecia antes.
        try:
            ctk.AppearanceModeTracker.add(self.apply_theme_colors, self.win)
        except Exception:  # pragma: no cover - versao sem o registrador
            pass

        self.app.glossary_change_callbacks.append(self.on_glossary_editor_change)

    def load_first_page(self):
        """Carrega a primeira pagina e seleciona o primeiro item."""
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

        self.win.after(100, self.restore_pane_positions)

    def show_message(self, text):
        """Escreve no rodape — cortando o texto que nao cabe na faixa.

        O corte e aqui e nao em quem chama porque a razao dele e a LARGURA do
        rodape, e nao o conteudo da mensagem (ROADMAP 22.10). Cortar com
        reticencias e diferente de deixar o Tk cortar: o `pack` corta sem sinal
        nenhum, e uma frase que termina no meio parece uma frase que acabou.

        `flash_message` recebe o texto JA cortado, e e o certo — o tempo de tela
        de F16 e o tempo de ler o que esta na tela.
        """
        flash_message(self.msg_label, self.win, preview(text, MESSAGE_PREVIEW_CHARS))

    def save_editor_settings(self):
        save_window_section(
            self.settings,
            "editor",
            {
                "font_size": self.state.font_size,
                "status_filter": self.status_segment.get(),
                "search_mode": self.search_mode_segment.get(),
                # So a ORIGEM e lembrada. O destino volta a cada abertura para o
                # que a janela principal tem selecionado, que e o comportamento
                # que esta janela sempre teve: lembra-lo faria quem marcasse
                # "Inglês" na janela principal abrir o editor em portugues, sem
                # nada na tela explicando de onde veio aquilo.
                "source_filter": self.source_menu.get(),
                # O arquivo e lembrado pelo CAMINHO, e nao pelo rotulo do menu:
                # o rotulo depende de quais outros arquivos existem hoje (ele
                # ganha a pasta quando dois nomes coincidem), e guardar um rotulo
                # que amanha significa outro arquivo seria guardar a resposta
                # errada. Revisar um livro leva dias — reabrir no capitulo em que
                # se estava e o ponto.
                "file_filter": self.selected_source_file() or "",
                # A orientacao dos dois textos (ROADMAP 19, item 1).
                "side_by_side": self.side_by_side,
            },
            window=self.win,
            sashes=(
                ("main_sash_y", self.main_pane, 0),
                ("bottom_sash_x", self.bottom_pane, 0),
                # O divisor dos textos grava sob a chave da orientacao ATIVA, e no
                # eixo dela: as duas posicoes convivem no arquivo, e trocar de
                # orientacao devolve a proporcao que o usuario escolheu para
                # aquela — e nao a da outra, que mediria a dimensao errada.
                (
                    self.texts_sash_key(),
                    self.texts_pane,
                    0,
                    0 if self.side_by_side else 1,
                ),
            ),
        )

    def restore_pane_positions(self):
        """Recoloca os divisores nas posicoes gravadas.

        **Quem impede o terceiro painel de pagar a conta e o `minsize`, e nao um
        teto calculado aqui.** Isto foi medido (ROADMAP 22.10): o `PanedWindow`
        do Tk honra o `minsize` dos vizinhos ao POSICIONAR um divisor, e nao so
        ao arrasta-lo — com `BOTTOM_PANE_MIN` declarado, uma posicao gravada de
        900 px numa tela larga e recolocada em 320 numa janela estreita, sozinha.

        A primeira versao deste metodo calculava um teto do que a janela tinha
        naquele instante, e uma mutacao mostrou que ele era uma segunda tranca —
        removida, nada mudava. Pior: `restore_pane_positions` roda agendado, a
        largura ainda pode nao ser a final, e o teto tirado de uma largura velha
        ENCOLHIA a lista abaixo do que o usuario tinha escolhido (442 px medidos
        onde ele pediu 900).

        Os maximos tambem sairam. O antigo prendia a lista em 520 px: quem
        arrumasse um painel de 700 numa tela grande o perdia a cada abertura, e o
        que protegia a janela nunca foi esse numero.
        """
        restore_sash(
            self.main_pane, self.editor_settings.get("main_sash_y"), LIST_PANE_MIN
        )
        restore_sash(
            self.bottom_pane,
            self.editor_settings.get("bottom_sash_x"),
            EDITOR_PANE_MIN,
        )
        self.restore_texts_sash()

    def cancel_draft_save(self):
        if self.state.draft_save_after is None:
            return
        try:
            self.win.after_cancel(self.state.draft_save_after)
        except tk.TclError:
            pass
        self.state.draft_save_after = None

    def draft_text(self):
        return self.trans_text.get("1.0", tk.END).rstrip("\n")

    def clear_current_draft(self, persist=True):
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        comment_id = self.current["id"]
        # Mantem o snapshot local coerente...
        clear_editor_draft(self.settings, self.app.output_db, self.lang, comment_id)

        if persist:
            # ...e limpa o rascunho relendo o disco, para nao apagar o que a
            # outra janela gravou (garantia R4 da SPEC.md).
            try:
                update_settings(
                    lambda disk: clear_editor_draft(
                        disk, self.app.output_db, self.lang, comment_id
                    )
                )
            except OSError:
                self.draft_label.configure(
                    text="Falha ao limpar rascunho",
                    text_color=ERROR_TEXT_COLOR,
                )
                return
        self.draft_label.configure(text="", text_color=MUTED_TEXT_COLOR)

    def persist_current_draft(self):
        """Grava o rascunho da linha aberta — o disco, fora da thread do Tk.

        Cada gravacao rele o JSON inteiro de configuracoes, serializa tudo e troca o
        arquivo de nome (garantia R4). Na thread do Tk, isso e um engasgo na
        digitacao em disco lento ou com antivirus no caminho — o programa parava
        entre duas teclas (ROADMAP 19, item 10).

        O que roda na thread e SO o disco. Os valores sao capturados aqui, na thread
        principal, e o resultado volta por `after`: a thread nao le widget e nao
        escreve rotulo, que e a garantia C1.

        O snapshot em memoria (`self.settings`) e atualizado AQUI, e nao la: ele e
        lido pela propria janela — se a linha for reaberta antes de a gravacao
        terminar, o rascunho tem de estar visivel.
        """
        self.state.draft_save_after = None
        if not self.current["id"]:
            self.draft_label.configure(text="")
            return

        comment_id = self.current["id"]
        text = self.draft_text()
        base = self.current["saved_trans"]

        if text == base:
            self.clear_current_draft(persist=True)
            return

        set_editor_draft(
            self.settings, self.app.output_db, self.lang, comment_id, text, base
        )
        db_path = self.app.output_db
        lang = self.lang

        def gravar():
            try:
                update_settings(
                    lambda disk: set_editor_draft(
                        disk, db_path, lang, comment_id, text, base
                    )
                )
            except OSError:
                self.report_draft_saved(False)
                return
            self.report_draft_saved(True)

        threading.Thread(target=gravar, daemon=True).start()

    def report_draft_saved(self, ok):
        """Volta para a thread do Tk e escreve o rotulo (garantia C1).

        Tolera a janela ter sumido no meio da gravacao: fechar o editor durante um
        `after` pendente levanta `TclError`, e nao ha mais ninguem a quem avisar.
        """
        def aplicar():
            if not self.win.winfo_exists():
                return
            if ok:
                self.draft_label.configure(
                    text=f"Rascunho salvo {datetime.now().strftime('%H:%M:%S')}",
                    text_color=MUTED_TEXT_COLOR,
                )
            else:
                self.draft_label.configure(
                    text="Falha ao salvar rascunho",
                    text_color=ERROR_TEXT_COLOR,
                )

        try:
            self.win.after(0, aplicar)
        except (tk.TclError, RuntimeError):  # pragma: no cover - janela ja fechada
            pass

    def schedule_draft_save(self):
        if self.state.loading or not self.current["id"]:
            return
        self.cancel_draft_save()
        self.draft_label.configure(text="Salvando rascunho...", text_color=MUTED_TEXT_COLOR)
        self.state.draft_save_after = self.win.after(
            DRAFT_SAVE_DELAY_MS, self.persist_current_draft
        )

    def set_dirty(self, value, autosave_draft=True):
        self.state.dirty = value
        if value:
            self.dirty_label.configure(text="Alterações não salvas", text_color=WARNING_TEXT_COLOR)
            if autosave_draft:
                self.schedule_draft_save()
        else:
            self.cancel_draft_save()
            self.dirty_label.configure(text="Salvo", text_color=OK_TEXT_COLOR)

    def update_counts_label(self):
        contagens = self.state.status_counts
        # Rejeitadas e em duvida so aparecem quando existem: um "Rejeitadas: 0" fixo
        # no rodape de quem nunca usou o recurso e ruido, e o rodape ja e a linha mais
        # cheia da janela.
        extras = ""
        rejeitadas = contagens.get(REVIEW_STATUS_REJECTED, 0)
        duvidas = contagens.get(REVIEW_STATUS_DOUBT, 0)
        if rejeitadas:
            extras += f" · Rejeitadas: {rejeitadas}"
        if duvidas:
            extras += f" · Em dúvida: {duvidas}"
        self.counts_label.configure(
            text=(
                f"Todas: {contagens['total']} · "
                f"Pendentes: {contagens['pending']} · "
                f"Verificadas: {contagens['verified']} · "
                f"QA: {contagens['qa']}{extras}"
            )
        )

    def update_selection_label(self):
        index = self.get_index()
        if index is None or not self.state.rows:
            self.selection_label.configure(text=f"Item 0/{self.state.total_rows}")
            return

        absolute_index = page_offset(self.state.page_index, PAGE_SIZE) + index + 1
        self.selection_label.configure(
            text=f"Item {absolute_index}/{self.state.total_rows} · {self.current_pair()}"
        )

    def set_origin_text(self, texto, total=0):
        """Poe (ou tira) a linha de procedencia do original.

        Sem procedencia ela **sai do grid**, e nao fica como rotulo vazio: as
        linhas gravadas antes desta versao sao a maioria de um banco antigo, e uma
        faixa em branco acima do texto em todas elas seria altura roubada do
        comentario para nao dizer nada. E o mesmo padrao do aviso de conflito do
        editor de glossario.

        `total` e quantas posicoes existem ao todo, e nao quantas cabem no
        rotulo. Com mais de uma, o rotulo vira um alvo de clique — e o cursor de
        mao e o unico sinal disso, porque um "(ver todas)" no texto gastaria a
        largura que o item 18.4 mediu como escassa justamente aqui.
        """
        self.origin_occurrences = total
        self.origin_label.configure(text=texto)
        try:
            self.origin_label.configure(cursor="hand2" if total > 1 else "")
        except tk.TclError:  # pragma: no cover - cursor sem suporte
            pass
        if texto:
            self.origin_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        else:
            self.origin_label.grid_remove()

    def open_occurrences_window(self, _event=None):
        """A lista de TODAS as posicoes deste comentario (ROADMAP 22.11).

        Modeless e copiavel, como a janela de estatisticas e a de historico: o
        revisor confere os capitulos com a traducao a vista, e cola a lista num
        recado se precisar. So abre com mais de uma posicao — com uma so, o
        rodape ja e a lista inteira, e uma janela para repetir o que esta na tela
        seria um clique acidental com janela de premio.

        A consulta e a mesma do rodape, sem limite. Ela ja e paga a cada troca de
        linha; esta e a segunda vez, e so quando alguem pede.
        """
        if not self.current["id"] or getattr(self, "origin_occurrences", 0) <= 1:
            return None

        janela = getattr(self, "occurrences_win", None)
        if janela is not None and janela.winfo_exists():
            janela.destroy()

        with closing(initialize_database(self.app.output_db)) as conn:
            posicoes, total = fetch_comment_occurrences(
                conn.cursor(),
                self.current["id"],
                limit=None,
                preferred_file=self.selected_source_file(),
            )

        janela = ctk.CTkToplevel(self.win)
        self.occurrences_win = janela
        janela.title(f"Posições deste comentário ({total})")
        janela.geometry("560x360")
        janela.minsize(360, 220)
        janela.transient(self.win)
        bring_window_to_front(janela, self.win, maximize=False)
        janela.columnconfigure(0, weight=1)
        janela.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            janela,
            text=f"A mesma tradução serve a {total} posição(oes):",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        texto = tk.Text(
            janela,
            wrap=tk.NONE,
            relief=tk.FLAT,
            borderwidth=0,
            font=self.body_font,
            bg=self.text_bg,
            fg=self.text_fg,
            insertbackground=self.text_fg,
            padx=8,
            pady=6,
        )
        barra = tk.Scrollbar(janela, orient=tk.VERTICAL, command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        texto.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=(0, 8))
        barra.grid(row=1, column=1, sticky="ns", pady=(0, 8), padx=(0, 12))
        texto.insert("1.0", "\n".join(format_occurrence_lines(posicoes)))
        # `disabled` e o mesmo estado do texto do original: no Tk ele impede
        # digitar e continua permitindo selecionar e copiar, que e metade do
        # motivo desta janela existir.
        texto.configure(state=tk.DISABLED)

        ctk.CTkButton(janela, text="Fechar", width=100, command=janela.destroy).grid(
            row=2, column=0, columnspan=2, sticky="e", padx=12, pady=(0, 12)
        )
        return janela

    def current_pair(self):
        """O par de idiomas da linha carregada, como `Inglês -> pt`.

        Sai da LINHA e nao do filtro: com "Origem: Todos" os dois divergem, e e
        justamente nesse caso que a informacao importa — e o unico momento em que
        a lista mistura idiomas de origem.
        """
        origem = self.current.get("source_language") or ""
        return f"{language_label(origem)} -> {self.lang}"

    def current_row_languages(self):
        """`(origem, destino)` da LINHA aberta — o par com que a QA a avalia.

        Nao confundir com `scoped_languages`, que e o par do FILTRO: la "Todos"
        vira `""` de proposito, porque uma regra de glossario com escopo nao pode
        valer para uma lista que mistura origens. Aqui a pergunta e outra — de
        que lingua veio ESTE texto —, e quem responde e a linha que o `load_item`
        carregou.

        Existe para que a avaliacao da TELA e a da COLUNA materializada leiam o
        par do mesmo lugar. As duas divergindo e a garantia R6 quebrada por
        dentro da janela (garantia Q3, ROADMAP 22.2).
        """
        return (
            self.current.get("source_language") or "",
            self.current.get("target_language") or self.lang,
        )

    def update_quality_warnings(self):
        """Os avisos do texto que esta NA TELA, avaliado com o par da linha.

        **O par nao e detalhe.** A heuristica de terminologia (garantia Q1) so
        roda com ele, e a coluna materializada — que e quem decide o marcador da
        lista e o filtro "Avisos QA" — sempre o passou. Sem o par aqui, uma linha
        cujo unico problema fosse terminologia dizia "QA: sem avisos" em verde
        enquanto a lista a marcava com "⚠ QA" e o filtro a mostrava: R6 violada
        entre dois pontos da MESMA janela (garantia Q3, ROADMAP 22.2).

        O texto avaliado e o do WIDGET, e nao o do banco — e ele que o revisor
        esta vendo, e o aviso tem de acompanhar o que ele acabou de digitar.

        **Sem linha aberta nao ha o que avaliar**, e a saida vem antes de tudo. O
        codigo anterior avaliava assim mesmo: com o editor vazio, "traducao
        vazia" e um aviso VERDADEIRO sobre coisa nenhuma, e ele aparecia em ambar
        na abertura de um banco sem linhas. O ramo que existia para esse caso
        nunca era alcancado, porque o aviso chegava antes dele.
        """
        if not self.current["id"]:
            self.qa_label.configure(text="", text_color=OK_TEXT_COLOR)
            return

        origem, destino = self.current_row_languages()
        warnings = evaluate_translation_quality(
            self.current["orig"],
            self.trans_text.get("1.0", tk.END),
            origem,
            destino,
        )
        if warnings:
            self.qa_label.configure(
                text="QA: " + " | ".join(warnings),
                text_color=WARNING_TEXT_COLOR,
            )
        else:
            self.qa_label.configure(text="QA: sem avisos", text_color=OK_TEXT_COLOR)

    def update_history_label(self):
        if not self.current["id"]:
            self.history_label.configure(text="")
            return

        self.history_label.configure(
            text=(
                f"Criada: {format_timestamp(self.current['created_at'])} | "
                f"Editada: {format_timestamp(self.current['updated_at'])} | "
                f"Verificada: {format_timestamp(self.current['verified_at'])}"
            )
        )

    def set_current_history(self, row):
        self.current["created_at"] = row[2] or "" if len(row) > 2 else ""
        self.current["updated_at"] = row[3] or "" if len(row) > 3 else ""
        self.current["verified_at"] = row[4] or "" if len(row) > 4 else ""
        self.update_history_label()

    def text_index_for_offset(self, offset):
        return f"1.0+{max(0, int(offset))}c"

    def clear_find_highlights(self):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)
        self.state.current_find_match = None

    def editor_find_ranges(self):
        return find_text_ranges(
            self.draft_text(),
            self.editor_find_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )

    def highlight_find_ranges(self, ranges, current_range=None):
        self.trans_text.tag_remove("find_match", "1.0", tk.END)
        self.trans_text.tag_remove("find_current", "1.0", tk.END)

        for start, end in ranges:
            self.trans_text.tag_add(
                "find_match",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )

        if current_range is not None:
            start, end = current_range
            self.trans_text.tag_add(
                "find_current",
                self.text_index_for_offset(start),
                self.text_index_for_offset(end),
            )
            self.trans_text.tag_raise("find_current")

    def refresh_find_matches(self, keep_current=True):
        if not self.editor_find_text.get():
            self.clear_find_highlights()
            return []

        ranges = self.editor_find_ranges()
        current_range = None
        if keep_current and self.state.current_find_match in ranges:
            current_range = self.state.current_find_match
        self.state.current_find_match = current_range
        self.highlight_find_ranges(ranges, current_range)
        return ranges

    def select_find_match(self, ranges, index):
        if not ranges:
            self.clear_find_highlights()
            return

        index = index % len(ranges)
        current_range = ranges[index]
        self.state.current_find_match = current_range
        self.highlight_find_ranges(ranges, current_range)

        start, end = current_range
        start_index = self.text_index_for_offset(start)
        end_index = self.text_index_for_offset(end)
        self.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.trans_text.tag_add(tk.SEL, start_index, end_index)
        self.trans_text.mark_set(tk.INSERT, end_index)
        self.trans_text.see(start_index)
        self.trans_text.focus_set()
        self.show_message(f"Ocorrencia {index + 1}/{len(ranges)}")

    def find_next_in_translation(self, _event=None):
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia encontrada")
            return "break"

        if self.state.current_find_match in ranges:
            offset = self.state.current_find_match[1]
        else:
            try:
                offset = len(self.trans_text.get("1.0", tk.INSERT))
            except tk.TclError:
                offset = 0

        for index, (start, _end) in enumerate(ranges):
            if start >= offset:
                self.select_find_match(ranges, index)
                return "break"

        self.select_find_match(ranges, 0)
        return "break"

    def replace_current_in_translation(self, _event=None):
        if not self.current["id"]:
            return "break"
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return "break"

        ranges = self.refresh_find_matches()
        if not ranges:
            self.show_message("Nenhuma ocorrencia para substituir")
            return "break"

        match = self.state.current_find_match
        if match not in ranges:
            match = ranges[0]
        start, end = match
        replacement = self.editor_replace_text.get()
        self.trans_text.delete(self.text_index_for_offset(start), self.text_index_for_offset(end))
        self.trans_text.insert(self.text_index_for_offset(start), replacement)
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()

        next_offset = start + len(replacement)
        ranges = self.refresh_find_matches(keep_current=False)
        if ranges:
            for index, (match_start, _match_end) in enumerate(ranges):
                if match_start >= next_offset:
                    self.select_find_match(ranges, index)
                    break
            else:
                self.select_find_match(ranges, 0)

        self.show_message("Ocorrencia substituida")
        return "break"

    def replace_all_in_translation(self):
        if not self.current["id"]:
            return
        if not self.editor_find_text.get():
            self.editor_find_entry.focus_set()
            self.show_message("Digite o texto da busca")
            return

        new_text, count = replace_all_text(
            self.draft_text(),
            self.editor_find_text.get(),
            self.editor_replace_text.get(),
            case_sensitive=self.editor_case_sensitive.get(),
        )
        if count == 0:
            self.show_message("Nenhuma ocorrencia para substituir")
            return

        self.set_translation_text(new_text, mark_dirty=True, keep_undo=True)
        self.refresh_find_matches(keep_current=False)
        self.show_message(f"{count} ocorrencia(s) substituida(s)")

    def set_translation_text(self,
        text,
        mark_dirty=False,
        autosave_draft=True,
        insert_offset=None,
        focus_editor=False,
        keep_undo=False,
    ):
        """Poe `text` no editor da traducao.

        `keep_undo` decide se a pilha de desfazer do Tk sobrevive, e a pergunta
        que responde e uma so: **a linha aberta mudou?**

        **Trocando de linha, a pilha tem de morrer.** Um Ctrl+Z que atravessasse
        a troca traria o texto da linha ANTERIOR para dentro desta — e a gravacao
        ao navegar o levaria para o banco, escrevendo numa linha a traducao de
        outra. Por isso o padrao e apagar: um chamador novo que esqueca o
        argumento erra para o lado seguro.

        **Reescrevendo a MESMA linha, ela tem de sobreviver** (garantia F14,
        ROADMAP 22.4). "Copiar original", "Aplicar selecionada", "Aplicar todas"
        e o "Todos" da busca-e-troca reescrevem o texto inteiro de uma vez — sao
        as acoes que mais pedem um Ctrl+Z — e eram justamente as que o
        desligavam. "Trocar", que edita o widget com `delete`/`insert` sem passar
        por aqui, sempre teve desfazer: a diferenca era efeito colateral do
        caminho de carga, e nao decisao.

        A substituicao inteira entra como **um** passo de desfazer. Os
        separadores automaticos sao desligados no meio dela de proposito: sem
        isso o `delete` e o `insert` viram dois Ctrl+Z para uma acao so, e o
        primeiro deles deixa o editor vazio.
        """
        self.state.loading = True
        try:
            if keep_undo:
                self.trans_text.configure(autoseparators=False)
                self.trans_text.edit_separator()
            self.trans_text.delete("1.0", tk.END)
            self.trans_text.insert("1.0", text or "")
            if keep_undo:
                self.trans_text.edit_separator()
            else:
                self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        finally:
            if keep_undo:
                try:
                    self.trans_text.configure(autoseparators=True)
                except tk.TclError:  # pragma: no cover - widget ja destruido
                    pass
        self.state.loading = False
        self.set_dirty(mark_dirty, autosave_draft=autosave_draft)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches(keep_current=False)
        if insert_offset is not None:
            insert_index = self.text_index_for_offset(insert_offset)
            self.trans_text.mark_set(tk.INSERT, insert_index)
            self.trans_text.see(insert_index)
            self.trans_text.tag_remove(tk.SEL, "1.0", tk.END)
        if focus_editor:
            self.trans_text.focus_set()

    def on_translation_modified(self, _event=None):
        try:
            modified = self.trans_text.edit_modified()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            return
        if modified and not self.state.loading:
            # A partir daqui a alteracao e do usuario, nao mais das regras
            # automaticas: a gravacao ao navegar volta a ser legitima.
            self.current["auto_only"] = False
            self.set_dirty(True)
            self.update_quality_warnings()
            self.refresh_find_matches()

    def update_layout_button(self):
        """O botao mostra o que ele VAI fazer, e nao o estado atual.

        Um botao que anuncia o estado obriga a decorar qual desenho significa o
        que; anunciando o destino, ele se le como um comando. O texto vai junto do
        simbolo no tooltip — que o CustomTkinter nao tem —, entao o simbolo carrega
        a orientacao de destino: colunas para lado a lado, linhas para empilhado.
        """
        self.btn_layout.configure(text="▤" if self.side_by_side else "▥")

    def toggle_side_by_side(self):
        """Troca a orientacao dos dois textos (ROADMAP 19, item 1).

        `configure(orient=...)` em vez de reconstruir os painéis: o texto digitado,
        a pilha de desfazer do Tk, a selecao e as marcas de busca vivem DENTRO dos
        widgets, e recria-los perderia os quatro — no meio de uma edicao nao
        salva.
        """
        self.side_by_side = not self.side_by_side
        self.texts_pane.configure(
            orient=tk.HORIZONTAL if self.side_by_side else tk.VERTICAL
        )
        self.update_layout_button()
        # A posicao gravada e por orientacao: o divisor horizontal mede largura e o
        # vertical mede altura, e reaproveitar o numero de um no outro poria o
        # divisor num lugar sem relacao com o que o usuario escolheu.
        self.win.after_idle(self.restore_texts_sash)
        self.save_editor_settings()

    def texts_sash_key(self):
        return "texts_sash_x" if self.side_by_side else "texts_sash_y"

    def restore_texts_sash(self):
        restore_sash(
            self.texts_pane,
            self.editor_settings.get(self.texts_sash_key()),
            120,
            axis=0 if self.side_by_side else 1,
        )

    def apply_font_size(self):
        size = self.state.font_size
        self.body_font.configure(size=size)
        self.body_bold_font.configure(size=size, weight="bold")
        self.row_font.configure(size=max(10, size - 1))
        self.suggestion_font.configure(size=max(10, size - 1))
        self.font_label.configure(text=f"{size} pt")
        for text in (self.orig_text, self.trans_text):
            text.tag_configure("bold", font=self.body_bold_font)
            text.tag_configure("glossary_hit", font=self.body_bold_font)

    def adjust_font(self, delta):
        self.state.font_size = max(9, min(24, self.state.font_size + delta))
        self.apply_font_size()
        self.save_editor_settings()

    def toggle_bold_view(self):
        """Liga e desliga o negrito de LEITURA do editor inteiro.

        O estado ligado tem de se ver nos DOIS temas (garantia F18, ROADMAP
        22.8). Ele era `("#3b82f6", "#1f6aa5")` contra `("#3B8ED0", "#1F6AA5")`
        do desligado: no escuro, `#1f6aa5` e `#1F6AA5` sao a MESMA cor, byte a
        byte — clicar o botao no tema escuro nao mudava nada na tela. No claro a
        diferenca era (0, -12, +38) em RGB, sutil demais para um estado.

        Hoje a cor ligada e de outra familia e vem com borda: duas diferencas, e
        a borda funciona mesmo para quem nao distingue os dois azuis.

        E o desligado volta ao par do TEMA, e nao a um par copiado a mao: os
        hexes que estavam aqui eram os do tema padrao transcritos, e nao
        acompanhariam uma troca de tema do CustomTkinter.
        """
        self.state.bold_view = not self.state.bold_view
        if self.state.bold_view:
            self.trans_text.configure(font=self.body_bold_font)
            self.btn_bold.configure(
                fg_color=BOLD_ACTIVE_COLOR,
                hover_color=BOLD_ACTIVE_HOVER_COLOR,
                border_width=2,
                border_color=BOLD_ACTIVE_BORDER_COLOR,
            )
        else:
            self.trans_text.configure(font=self.body_font)
            fg_color, hover_color = theme_button_colors()
            self.btn_bold.configure(
                fg_color=fg_color, hover_color=hover_color, border_width=0
            )

    def toggle_bold_selection(self, _event=None):
        """Marca (ou desmarca) em negrito o trecho selecionado da traducao.

        Existia no projeto original e se perdeu quando o botao "B" passou a
        alternar a fonte do editor inteiro (`toggle_bold_view`). Sao recursos
        diferentes e ambos uteis: um e leitura, o outro e marcacao. O botao
        continua com o alternador de fonte, junto dos controles A-/A+ onde ele
        pertence; a marcacao voltou no `Ctrl+B`, que e o gesto universal para
        "negrito no que esta selecionado".

        A marca e **visual e da sessao**: a tag do Tk nao vai para o banco, e
        recarregar a traducao a desfaz. Era assim no original, e faz sentido —
        o que se grava e o texto do comentario, nao a formatacao de quem revisa.
        """
        try:
            inicio = self.trans_text.index(tk.SEL_FIRST)
            fim = self.trans_text.index(tk.SEL_LAST)
        except tk.TclError:
            self.show_message("Selecione um trecho da tradução")
            return "break"

        if "bold" in self.trans_text.tag_names(inicio):
            self.trans_text.tag_remove("bold", inicio, fim)
        else:
            self.trans_text.tag_add("bold", inicio, fim)
        return "break"

    def highlight_glossary_hits(self):
        self.trans_text.tag_remove("glossary_hit", "1.0", tk.END)
        # Lido UMA vez: estava dentro do laco, o que fazia ate 80 travessias
        # Tk->Python do texto inteiro para pintar sempre a mesma coisa.
        text = self.trans_text.get("1.0", tk.END)
        for orig, _new in self.current_suggestions:
            for start, end in find_glossary_matches(text, orig):
                self.trans_text.tag_add(
                    "glossary_hit",
                    self.text_index_for_offset(start),
                    self.text_index_for_offset(end),
                )

    def clear_current(self):
        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.configure(state="disabled")
        self.trans_text.delete("1.0", tk.END)
        self.current["id"] = None
        self.current["orig"] = ""
        self.current["trans"] = ""
        self.current["saved_trans"] = ""
        self.current["created_at"] = ""
        self.current["updated_at"] = ""
        self.current["verified_at"] = ""
        # Sem isto o rotulo continuaria anunciando o par da linha que acabou de
        # sair da tela — a informacao errada e mais cara que nenhuma.
        self.current["source_language"] = ""
        self.current["target_language"] = ""
        try:
            self.trans_text.edit_reset()
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        self.clear_find_highlights()
        self.draft_label.configure(text="")
        # Mesma razao do par de idiomas acima: a procedencia da linha anterior na
        # tela, sem linha nenhuma aberta, e uma afirmacao sobre o vazio. A nota do
        # revisor sai junto, e por um motivo mais grave: deixada na tela, o proximo
        # "Rejeitar" a gravaria na linha errada.
        self.set_origin_text("")
        self.current["review_status"] = REVIEW_STATUS_PENDING
        self.current["reviewer_note"] = ""
        self.reviewer_note_text.set("")
        self.update_review_status_label()
        self.refresh_suggestions()
        self.update_selection_label()
        self.update_quality_warnings()
        self.update_history_label()

    def page_count(self):
        return compute_page_count(self.state.total_rows, PAGE_SIZE)

    def selected_status_filter(self):
        # "warnings" e os dois status de revisao sao resolvidos em SQL, cada um pela
        # sua coluna, entao todos os filtros usam exatamente o mesmo caminho
        # paginado — nada de carregar a tabela inteira para depois fatiar.
        return STATUS_FILTER_LABELS.get(self.status_segment.get(), "all")

    def selected_search_mode(self):
        """O modo escolhido no seletor, na forma que o banco entende.

        Lido a cada consulta, e nao guardado no estado: assim trocar o modo e o
        proprio recarregamento ja bastam para o resultado mudar, sem uma copia
        do valor para ficar desatualizada.
        """
        if self.search_mode_segment.get() == SEARCH_MODE_LABEL_SUBSTRING:
            return SEARCH_MODE_SUBSTRING
        return SEARCH_MODE_TERMS

    def qa_filter_active(self):
        return self.status_segment.get() == "Avisos QA"

    def selected_source_language(self):
        """O filtro de origem na forma que o banco entende (`None` = todos).

        Lido a cada consulta pelo mesmo motivo de `selected_search_mode`: o
        seletor e a fonte da verdade, e uma copia no estado so daria uma segunda
        coisa para ficar desatualizada.
        """
        return source_filter_code(self.source_menu.get())

    def selected_source_file(self):
        """O arquivo escolhido, como o banco o guarda, ou `None` para todos."""
        return self.file_options.get(self.file_menu.get())

    def selected_order(self):
        """A ordem da lista, que segue o filtro por arquivo.

        Nao ha um seletor de ordem, e a ausencia e a decisao: escolher um arquivo E
        pedir a obra em ordem de leitura, e ninguem quer o capitulo 7 na ordem em
        que as traducoes dele foram inseridas no cache. Sem arquivo, a ordem de
        leitura nao existe — o mesmo comentario esta em varios — e a lista volta ao
        `id`, que e o que ela sempre foi.
        """
        if self.selected_source_file():
            return ORDER_BY_OCCURRENCE
        return ORDER_BY_ID

    def list_filters(self):
        """Os filtros da lista, num lugar so.

        TODA consulta da lista — o resumo por status, o total, a pagina, o offset
        do "Ir para ID", a varredura do "Proximo aviso QA" — tem de receber
        EXATAMENTE estes filtros. A garantia R10 nasceu de duas que recebiam um a
        menos, e o sintoma nao foi erro: foi uma posicao calculada na lista errada,
        que na tela parece uma selecao qualquer. Montar aqui e o que impede a
        proxima — o filtro por arquivo teria sido a terceira.
        """
        return {
            "search_text": self.state.active_search,
            "search_mode": self.selected_search_mode(),
            "source_language": self.selected_source_language(),
            "source_file": self.selected_source_file(),
        }

    def list_query_args(self):
        """`list_filters` mais a ORDEM, para quem posiciona linha.

        Sao dois metodos porque sao duas perguntas: o resumo por status conta
        linhas e nao se importa com a ordem; contar, paginar e achar a posicao de
        um id se importam, e para esses a ordem faz parte do resultado.
        """
        return dict(self.list_filters(), order=self.selected_order())

    def current_view(self):
        """Retrato do que a janela mostra: a linha aberta e os filtros que a trazem.

        Guardar so o id nao serviria (ROADMAP 19, item 3): quem usa a busca como
        concordancia — "como traduzi *outpost* ate aqui?" — troca a lista, e o id
        de antes pode nao estar no resultado novo. Voltar so e voltar se os filtros
        voltarem com ele.

        **O retrato tem de guardar tudo que decide QUAL lista aparece**, e nao so
        o que se ve nos filtros mais obvios. Dois campos faltavam (garantia F13,
        ROADMAP 22.3):

        - o MODO da busca, porque `bisp` em "Trecho" e `bisp` em "Termos" sao
          duas listas diferentes com o mesmo texto no campo;
        - o DESTINO, porque trocar de par e um dos saltos que F3 promete desfazer
          — e sem ele o retrato era reposto contra o par novo, onde nenhum id do
          antigo existe.

        **E os campos que ja existiam guardavam o valor errado.** O retrato lia os
        SELETORES, e o comando de um seletor roda com o widget ja no valor novo:
        trocar de "Todas" para "Verificadas" empilhava "Verificadas", e "voltar"
        nao repunha filtro nenhum. Hoje os filtros saem de `state.applied_view` —
        o que a ultima consulta da lista usou —, e so a linha aberta e lida na
        hora, porque ela nao passa por seletor nenhum.
        """
        return dict(self.state.applied_view, id=self.current["id"])

    def remember_position(self):
        """Empilha o retrato atual, antes de um salto.

        Chamada pelas operacoes que **trocam a lista** — buscar, limpar a busca, ir
        para um id ou uma pagina, trocar de filtro, de arquivo, de par, e o salto
        para o proximo aviso QA. Navegar de uma linha para a vizinha nao empilha: a
        pilha existe para desfazer o salto que descarta a pagina, e um "voltar" que
        andasse linha por linha nao devolveria nada a quem revisa um livro.

        Nao empilha sem linha aberta (nao ha para onde voltar) nem o mesmo retrato
        duas vezes seguidas — dois cliques em "Buscar" com o mesmo texto sao um
        salto, nao dois.

        **Nos caminhos que trocam um SELETOR, esta chamada vem antes do
        `save_changes`** (garantia F13). A gravacao pode recarregar a lista por
        conta propria — com o filtro "Avisos QA" ativo, corrigir o aviso tira a
        linha (R7) —, e esse recarregamento atualizaria `applied_view` ja com o
        seletor que o usuario acabou de mexer. O retrato tem de ser tirado antes de
        qualquer coisa acontecer: ele e o "de onde", e tudo o que vem depois e o
        "para onde".
        """
        if not self.current["id"]:
            return
        retrato = self.current_view()
        if self.state.history_stack and self.state.history_stack[-1] == retrato:
            return
        self.state.history_stack.append(retrato)
        # A pilha e memoria de sessao, e uma sessao de revisao dura horas: sem
        # limite ela cresce com cada salto. O corte e pelo comeco, que e a parte a
        # que ninguem mais volta.
        if len(self.state.history_stack) > HISTORY_STACK_LIMIT:
            del self.state.history_stack[0]

    def apply_language_selection(self):
        """Poe em vigor o par que esta nos seletores: idioma, titulo e glossario.

        Sao os efeitos da troca de par que NAO sao o proprio seletor. Viviam
        dentro de `change_language_filter`, e por isso o "voltar" repunha o
        seletor e nada mais: a lista voltava para o par certo e as sugestoes
        continuavam sendo as do par que se deixou (garantias S11 e F13).

        Nao inclui `refresh_file_filter`: quem chama decide se o menu de arquivos
        e reconstruido antes ou depois de escolher o arquivo do retrato.
        """
        novo_destino = target_language_code(self.target_menu.get())
        if novo_destino and novo_destino != self.lang:
            self.lang = novo_destino
            self.win.title(f"Editar traduções ({self.lang})")

        # O par decide QUAIS regras do glossario existem (garantia S11), entao
        # trocar de par troca as sugestoes oferecidas. Sem isto, a janela
        # continuaria propondo a terminologia do par anterior.
        self.glossary = self.load_scoped_interactive_glossary()
        self.automatic_glossary = self.load_scoped_automatic_glossary()

    def restore_view(self, retrato):
        """Repoe os filtros do retrato e seleciona a linha dele.

        Devolve `True` se a linha foi encontrada. Os seletores sao repostos ANTES
        da consulta porque e deles que `list_filters` le — e o `refresh_file_filter`
        entra no meio porque trocar de par muda quais arquivos existem.

        A ordem nao e arbitraria: o par entra antes do menu de arquivos porque e
        `self.lang` que decide quais obras existem, e o menu de arquivos entra
        antes do `jump_to_id` porque o arquivo escolhido decide a ORDEM da lista,
        e a ordem decide a posicao do id (garantia R10).
        """
        self.search_text.set(retrato["search"])
        self.state.active_search = retrato["search"]
        self.search_mode_segment.set(retrato["mode"])
        self.status_segment.set(retrato["status"])
        self.source_menu.set(retrato["source"])

        # O retrato guarda o CODIGO do destino (`self.lang`), e o menu mostra o
        # nome: a conversao e aqui, como na abertura da janela.
        destino_anterior = self.lang
        self.target_menu.set(
            LANGUAGE_NAMES.get(retrato["target"], LANGUAGES[0][0])
        )
        self.apply_language_selection()
        if self.lang != destino_anterior:
            # Mesma razao de `change_language_filter`: a selecao em lote e por id,
            # e um id do par que se deixou nao esta na lista nova (ROADMAP 19,
            # item 9).
            self.state.selected_ids.clear()

        self.refresh_file_filter()
        if retrato["file"] in self.file_menu.cget("values"):
            self.file_menu.set(retrato["file"])
        self.state.page_index = retrato["page"]
        return self.jump_to_id(retrato["id"])

    def go_back(self):
        """Volta ao ultimo retrato empilhado (`Alt+Backspace`).

        Repor um retrato mexe nos seletores ANTES de saber se a linha dele ainda
        existe, entao um retrato que falha deixa a janela no meio do caminho.
        Enquanto ha proximo isso nao aparece — ele repoe tudo de novo —, mas
        quando nenhum serve a janela ficava com os filtros do ultimo que falhou, e
        desde que o par entrou no retrato (F13) ate em outro idioma de destino.
        Por isso o ponto de partida e guardado e reposto: "Nada para voltar" passa
        a querer dizer que nada mudou.
        """
        self.save_changes()
        partida = self.current_view()
        tentou = False
        while self.state.history_stack:
            tentou = True
            retrato = self.state.history_stack.pop()
            if self.restore_view(retrato):
                self.show_message("Voltou para o ponto anterior")
                return True
            # A linha pode ter deixado de existir — o "Zerar Traducoes" de outra
            # janela, ou uma importacao. Um retrato que nao da para repor nao pode
            # travar a pilha: o proximo assume.
        if tentou:
            self.restore_view(partida)
        self.show_message("Nada para voltar")
        return False

    def refresh_file_filter(self, restore=None):
        """Reconstroi o menu de arquivos do par atual.

        `restore` e um caminho a reselecionar — a escolha da sessao anterior, ou a
        da sessao atual quando o par muda. Um arquivo que nao esta mais na lista
        (outro par de idiomas, banco zerado) cai em "Todos os arquivos" em vez de
        deixar o menu apontando para um filtro que nao devolve linha nenhuma: uma
        lista vazia sem explicacao e o pior desfecho possivel de um filtro
        lembrado.
        """
        anterior = restore if restore is not None else self.selected_source_file()
        with closing(initialize_database(self.app.output_db)) as conn:
            arquivos = list_occurrence_files(
                conn.cursor(), self.lang, self.selected_source_language()
            )

        self.file_options = occurrence_file_labels([linha[0] for linha in arquivos])
        self.file_menu.configure(values=[FILE_FILTER_ALL] + list(self.file_options))

        escolhido = FILE_FILTER_ALL
        if anterior:
            for rotulo, caminho in self.file_options.items():
                if caminho == anterior:
                    escolhido = rotulo
                    break
        self.file_menu.set(escolhido)

    def change_file_filter(self):
        """Troca de obra: grava o que estava aberto e recomeca na primeira pagina.

        Nao reconstroi a lista de arquivos, de proposito: quem acabou de escolher
        um item de um menu nao espera que o menu mude sozinho embaixo do dedo. A
        lista e refeita quando o PAR muda, que e quando ela pode de fato ter outro
        conteudo.
        """
        self.remember_position()
        if self.current["id"]:
            self.save_changes()

        self.state.page_index = 0
        self.clear_current()
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        self.save_editor_settings()

    def change_language_filter(self):
        """Troca de par de idiomas: grava o que estava aberto e recomeca.

        Grava ANTES de trocar (`save_changes`), e nao depois: a linha em edicao
        pertence ao par antigo, e apos a troca ela nao esta mais na lista — o
        rascunho seria gravado contra um item que a janela nao mostra mais, ou
        perdido em silencio.

        Volta para a primeira pagina porque a pagina 40 do par anterior nao quer
        dizer nada no novo: o filtro pode ter 3 linhas, e `clamp_page` deixaria o
        usuario numa lista vazia sem explicar por que.
        """
        self.remember_position()
        if self.current["id"]:
            self.save_changes()

        # Idioma, titulo e o recorte do glossario (garantia S11). O mesmo bloco
        # que o "voltar" usa — eram estas linhas, aqui dentro, que faltavam la
        # (garantia F13).
        self.apply_language_selection()

        # O par decide quais ARQUIVOS existem: um par sem execucao nenhuma nao tem
        # obra, e manter no menu os arquivos do par anterior daria um filtro que
        # devolve zero linhas sempre. A escolha atual e reposta quando o arquivo
        # existe nos dois pares — um mesmo PGN traduzido para dois idiomas.
        self.refresh_file_filter()

        # A selecao em lote morre na troca de par (ROADMAP 19, item 9). Ela e por
        # id, e um id do par anterior nao esta na lista nova: "Verificar" marcaria
        # linhas que o revisor nao ve, que e o oposto do que a selecao serve.
        self.state.selected_ids.clear()

        self.state.page_index = 0
        self.clear_current()
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        self.save_editor_settings()

    def fetch_quality_warning_rows(self, cur):
        """Linhas com aviso — usado pelo relatorio QA, que precisa de todas."""
        return fetch_review_rows(
            cur,
            self.lang,
            status_filter="warnings",
            **self.list_query_args(),
        )

    def update_page_controls(self):
        pages = self.page_count()
        current_page = self.state.page_index + 1 if pages else 0
        search_suffix = " · busca ativa" if self.state.active_search else ""
        status_suffix = f" · {self.status_segment.get().lower()}"
        # A ordem muda quando um arquivo e escolhido, e uma lista que reordena sem
        # dizer nada parece embaralhada. O rotulo e o unico lugar em que isso cabe
        # sem um controle novo na tela.
        order_suffix = (
            " · ordem de leitura"
            if self.selected_order() == ORDER_BY_OCCURRENCE
            else ""
        )
        self.page_label.configure(
            text=(
                f"Página {current_page}/{pages} · "
                f"{self.state.total_rows} traduções"
                f"{status_suffix}{search_suffix}{order_suffix}"
            )
        )
        self.btn_page_prev.configure(
            state="normal" if self.state.page_index > 0 else "disabled"
        )
        self.btn_page_next.configure(
            state="normal" if self.state.page_index + 1 < pages else "disabled"
        )

    def render_rows(self):
        self.row_buttons.clear()
        self.row_checkboxes.clear()
        self.state.selected_index = None
        self.update_page_controls()
        self.update_counts_label()
        self.update_selection_label()

        if self.qa_filter_active():
            vazio = "Nenhum aviso QA encontrado."
        elif self.state.active_search:
            vazio = "Nenhuma tradução encontrada para a busca."
        else:
            vazio = "Nenhuma tradução encontrada."

        # O retorno de `render_row_buttons` sao os QUADROS; os botoes e as marcas
        # foram guardados por `build_row_button`, que e quem sabe qual e qual.
        render_row_buttons(
            self.rows_frame, self.state.rows, self.build_row_button, vazio
        )
        self.update_selection_controls()

    def build_row_button(self, parent, index, row):
        """A linha da lista: uma marca de selecao e o botao (ROADMAP 19, item 9).

        Devolve o QUADRO, que e o que `render_row_buttons` empacota; o botao vai
        para `self.row_buttons` e a marca para `self.row_checkboxes`, porque quem
        pinta a selecao mexe no botao e quem le a selecao em lote le as marcas.

        A marca fica FORA do botao porque um `CTkButton` nao aceita filho: clicar
        nela nao pode carregar a linha, e clicar na linha nao pode marcar. Sao duas
        acoes diferentes no mesmo lugar, e confundi-las faria o revisor marcar como
        verificada uma linha que ele so queria ler.
        """
        quadro = ctk.CTkFrame(parent, fg_color="transparent")
        quadro.columnconfigure(1, weight=1)

        marcada = tk.BooleanVar(master=self.win, value=row[0] in self.state.selected_ids)
        marca = ctk.CTkCheckBox(
            quadro,
            text="",
            width=24,
            variable=marcada,
            command=lambda i=index: self.toggle_row_selection(i),
        )
        marca.grid(row=0, column=0, sticky="n", padx=(2, 4), pady=2)
        marca.selection_var = marcada

        botao = ctk.CTkButton(
            quadro,
            text=row_label(row),
            anchor="w",
            height=64,
            fg_color=row_color(row),
            text_color=row_text_color(row),
            hover_color=ROW_HOVER_COLOR,
            font=self.row_font,
            command=lambda i=index: self.select_row_from_click(i),
        )
        botao.grid(row=0, column=1, sticky="ew")

        self.row_buttons.append(botao)
        self.row_checkboxes.append(marca)
        return quadro

    def select_row_from_click(self, index):
        """Carrega a linha clicada E poe o foco na traducao (ROADMAP 22.11).

        So no caminho do CLIQUE. Depois de escolher uma linha na lista o gesto
        seguinte e sempre digitar, e o segundo clique — dentro do texto — era
        obrigatorio: sem ele a digitacao ia para o botao da lista. E a mesma
        razao pela qual `apply_one` ja pedia `focus_editor=True`.

        Os recarregamentos programaticos ficam de fora de proposito: eles rodam
        depois de gravar, de filtrar e de buscar, e roubar o foco do campo de
        busca no meio de uma busca seria trocar um incomodo por outro pior.
        """
        self.select_index(index, save_previous=True)
        try:
            self.trans_text.focus_set()
        except tk.TclError:  # pragma: no cover - janela fechando
            pass

    def toggle_row_selection(self, index):
        """Marca ou desmarca a linha `index`, pelo ID.

        Por id, e nao por posicao: a selecao sobrevive a trocar de pagina, que e o
        que torna "exportar so a selecao" util em vez de uma curiosidade — juntar 30
        linhas de tres paginas diferentes e o caso real.
        """
        if not (0 <= index < len(self.state.rows)):
            return
        row_id = self.state.rows[index][0]
        if row_id in self.state.selected_ids:
            self.state.selected_ids.discard(row_id)
        else:
            self.state.selected_ids.add(row_id)
        self.update_selection_controls()

    def select_page_rows(self):
        """Marca todas as linhas da pagina (o "marcar a pagina" do item 9)."""
        for row in self.state.rows:
            self.state.selected_ids.add(row[0])
        self.sync_row_checkboxes()
        self.update_selection_controls()

    def select_all_filtered_rows(self):
        """Marca TODAS as linhas do filtro, e nao so as da pagina (22.11).

        Confirma quando passa de uma pagina porque e ai que o gesto deixa de ser
        verificavel na tela: com 100 linhas o revisor ve o que marcou, com 3.000
        ele so ve o contador. O dialogo diz o numero ANTES — e o unico ponto em
        que ele aparece, e por isso ele existe: um "Marcar tudo (N)" com o N no
        rotulo nao cabe na faixa de 300 px medida em 22.10.

        Devolve quantas ficaram marcadas, ou `None` se o usuario desistiu.
        """
        # Com o `status_filter` junto, e nao so os filtros de lista: o que a
        # lista mostra e o que "tudo" tem de querer dizer. Sem ele, "Marcar tudo"
        # sob o filtro "Avisos QA" marcaria tambem as linhas limpas.
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            ids = fetch_review_row_ids(
                cur,
                self.lang,
                status_filter=self.selected_status_filter(),
                **self.list_filters(),
            )

        if not ids:
            self.show_message("Nenhuma linha no filtro atual")
            return 0

        if len(ids) > PAGE_SIZE and not messagebox.askyesno(
            "Marcar tudo",
            f"Marcar as {len(ids)} traduções do filtro atual?\n\n"
            "São mais do que cabe numa página: o que estiver marcado fora da "
            "tela também entra em \"Verificar\" e \"Exportar\".",
            parent=self.win,
        ):
            return None

        self.state.selected_ids.update(ids)
        self.sync_row_checkboxes()
        self.update_selection_controls()
        self.show_message(f"{len(ids)} linha(s) marcada(s)")
        return len(self.state.selected_ids)

    def clear_row_selection(self):
        self.state.selected_ids.clear()
        self.sync_row_checkboxes()
        self.update_selection_controls()

    def sync_row_checkboxes(self):
        for indice, marca in enumerate(self.row_checkboxes):
            if indice >= len(self.state.rows):
                break
            if self.state.rows[indice][0] in self.state.selected_ids:
                marca.select()
            else:
                marca.deselect()

    def update_selection_controls(self):
        """Habilita as acoes em lote so quando ha selecao, e diz quantas.

        Um botao "Marcar selecionadas" clicavel com nada marcado nao tem resposta
        boa: ou ele nao faz nada em silencio, ou avisa que nao ha selecao — e as
        duas sao piores do que um botao apagado que se explica pelo contador ao
        lado.
        """
        quantas = len(self.state.selected_ids)
        self.batch_label.configure(
            text=f"{quantas} selecionada(s)" if quantas else "nenhuma selecionada"
        )
        estado = "normal" if quantas else "disabled"
        self.btn_batch_verify.configure(state=estado)
        self.btn_batch_export.configure(state=estado)
        self.btn_batch_clear.configure(state=estado)

    def reload_rows(self):
        filtros = self.list_filters()
        consulta = self.list_query_args()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            self.state.status_counts.update(
                get_review_status_counts(cur, self.lang, **filtros)
            )
            # A contagem de avisos ja vem agregada junto com as demais.
            self.state.status_counts["qa"] = self.state.status_counts.get("warnings", 0)

            # O total do filtro ativo tambem ja veio no resumo acima: as duas
            # consultas varriam a mesma tabela com o mesmo `WHERE`. Com busca
            # ativa, cada varredura dessas custa ~100 ms e nao usa indice
            # (`LIKE '%termo%'`), entao e uma por interacao a menos (ROADMAP 2.8).
            status_filter = self.selected_status_filter()
            self.state.total_rows = count_from_status_counts(
                self.state.status_counts,
                status_filter,
            )
            if self.state.total_rows is None:
                self.state.total_rows = count_review_rows(
                    cur, self.lang, status_filter=status_filter, **filtros
                )
            self.state.page_index = clamp_page(
                self.state.page_index, self.state.total_rows, PAGE_SIZE
            )
            offset = page_offset(self.state.page_index, PAGE_SIZE)
            self.state.rows = list(
                fetch_review_rows_page(
                    cur,
                    self.lang,
                    limit=PAGE_SIZE,
                    offset=offset,
                    status_filter=status_filter,
                    **consulta,
                )
            )

        # O retrato do "voltar" sai DAQUI (garantia F13). Estes sao os filtros que
        # esta consulta usou — o que a janela esta mostrando agora —, e o proximo
        # salto empilha exatamente isto. Lidos dos seletores no momento do salto,
        # eles ja seriam os do destino: o comando de um seletor roda com o widget
        # no valor novo, e "voltar" repunha o filtro que o usuario acabou de
        # escolher em vez do que ele deixou.
        #
        # O destino sai de `self.lang`, e nao do menu, pela mesma razao: `lang` so
        # muda quando a troca de par entra em vigor, e o menu muda no clique.
        self.state.applied_view = {
            "search": self.state.active_search,
            "mode": self.search_mode_segment.get(),
            "status": self.status_segment.get(),
            "source": self.source_menu.get(),
            "target": self.lang,
            "file": self.file_menu.get(),
            "page": self.state.page_index,
        }
        self.render_rows()

    def get_index(self):
        return self.state.selected_index

    def update_row_selection(self, new_index):
        old_index = self.state.selected_index
        if old_index is not None and 0 <= old_index < len(self.row_buttons):
            self.row_buttons[old_index].configure(
                fg_color=row_color(self.state.rows[old_index]),
                text_color=row_text_color(self.state.rows[old_index]),
            )

        self.state.selected_index = new_index
        if new_index is not None and 0 <= new_index < len(self.row_buttons):
            self.row_buttons[new_index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        self.update_selection_label()

    def select_index(self, index, save_previous=False):
        if not self.state.rows:
            return

        if save_previous and self.current["id"]:
            # `save_changes` pode trocar `state.rows` por baixo: com o filtro "Avisos
            # QA" ativo, corrigir o aviso tira a linha atual da lista; com o
            # filtro "pendentes", marcar como verificada faz o mesmo. Nos dois
            # casos ele recarrega e chama `select_index` por conta propria, e a
            # posicao que chegou aqui passa a apontar para outra linha.
            #
            # Guardar o id do alvo antes de gravar e reencontra-lo depois e o
            # que garante que o clique em B nao acabe carregando C.
            target_id = self.state.rows[index][0] if 0 <= index < len(self.state.rows) else None
            self.save_changes()
            if not self.state.rows:
                return
            index = row_index_for_id(self.state.rows, target_id, fallback=index)
            if index is None:
                return

        index = max(0, min(index, len(self.state.rows) - 1))
        self.update_row_selection(index)
        self.load_item()

    def load_item(self):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.state.rows)):
            return

        comment_id = self.state.rows[index][0]
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            row = fetch_translation_by_id(cur, comment_id)
            # Na MESMA conexao da linha: sao duas consultas indexadas por id, e
            # abrir o banco de novo custaria mais do que as duas juntas.
            ocorrencias, total_ocorrencias = fetch_comment_occurrences(
                cur,
                comment_id,
                limit=OCCURRENCE_PREVIEW_LIMIT,
                preferred_file=self.selected_source_file(),
            )
            status_revisao, nota_revisao = fetch_review_status_by_id(cur, comment_id)

        if row is None:
            return

        self.current["review_status"] = status_revisao
        self.current["reviewer_note"] = nota_revisao
        self.reviewer_note_text.set(nota_revisao)
        self.update_review_status_label()

        self.set_origin_text(
            format_occurrence_context(ocorrencias, total_ocorrencias),
            total_ocorrencias,
        )

        orig, trans = row[0], row[1]
        self.current["id"] = comment_id
        self.current["orig"] = orig or ""
        self.current["trans"] = trans or ""
        self.current["saved_trans"] = self.current["trans"]
        # O par de idiomas da LINHA, que nao e o mesmo que o filtro: com
        # "Origem: Todos" ativo a lista mistura pares de proposito, e sem isto
        # nada na tela diz de qual delas veio o texto que esta sendo revisado.
        self.current["source_language"] = row[5] if len(row) > 5 else ""
        # O destino tambem sai da LINHA, e nao de `self.lang`: os dois coincidem
        # hoje (a lista e filtrada por destino), e guardar o da linha e o que
        # mantem a avaliacao de qualidade da tela igual a da coluna materializada
        # se algum dia a lista misturar destinos (garantia R6).
        self.current["target_language"] = row[6] if len(row) > 6 else self.lang
        self.set_current_history(row)

        self.orig_text.configure(state="normal")
        self.orig_text.delete("1.0", tk.END)
        self.orig_text.insert("1.0", self.current["orig"])
        self.orig_text.configure(state="disabled")

        draft = get_editor_draft(
            self.settings,
            self.app.output_db,
            self.lang,
            comment_id,
            self.current["trans"],
        )
        if draft is None:
            auto_text = apply_automatic_substitutions(self.current["trans"], self.automatic_glossary)
            if auto_text != self.current["trans"]:
                # Sugestao das regras automaticas: mostra e sinaliza como nao
                # salva, mas nao grava sozinha nem gera rascunho. Aplicar em
                # massa continua sendo o caminho deliberado, com preview e backup.
                self.current["auto_only"] = True
                self.set_translation_text(auto_text, mark_dirty=True, autosave_draft=False)
            else:
                self.current["auto_only"] = False
                self.set_translation_text(self.current["trans"], mark_dirty=False)
        else:
            self.current["auto_only"] = False
            self.set_translation_text(
                draft["text"],
                mark_dirty=True,
                autosave_draft=False,
            )
            self.draft_label.configure(
                text=f"Rascunho restaurado {format_timestamp(draft['updated_at'])}",
                text_color=MUTED_TEXT_COLOR,
            )
            self.show_message("Rascunho restaurado")

        # DEPOIS de carregar, e nao antes. `select_index` pinta a selecao — o que
        # ja atualiza o rotulo — e so entao chama este metodo; sem esta segunda
        # chamada o rotulo anuncia o par da linha ANTERIOR, que e o pior tipo de
        # informacao errada porque parece certa.
        self.update_selection_label()

    def update_current_row_cache(self, verified=None):
        index = self.get_index()
        if index is None or not (0 <= index < len(self.state.rows)):
            return

        if verified is None:
            verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0

        # O par de idiomas vai junto, nas duas ultimas posicoes, como nas linhas
        # que vem do banco. Sem ele a linha reconstruida aqui seria avaliada sem
        # par e a mesma linha relida do banco seria avaliada com par: a contagem
        # de avisos da tela passaria a depender de a linha ter sido editada nesta
        # sessao (garantia R6).
        #
        # E o bit de aviso vai junto pelo mesmo motivo, agora que o rotulo da linha
        # o mostra: calculado pela MESMA funcao que a gravacao usa. Copiar o bit
        # antigo faria o marcador da lista ficar mostrando o veredito de antes da
        # edicao — a linha corrigida continuaria marcada, e a que passou a ter aviso
        # nao apareceria.
        #
        # O par sai de `current_row_languages`, que e de onde o rotulo "QA:" da
        # tela tambem o le: a linha reconstruida aqui e a avaliacao exibida tem de
        # concordar, e para isso o par tem de vir de um lugar so (garantia Q3).
        origem, destino = self.current_row_languages()
        self.state.rows[index] = (
            self.current["id"],
            self.current["orig"],
            self.current["trans"],
            verified,
            self.current["created_at"],
            self.current["updated_at"],
            self.current["verified_at"],
            origem,
            destino,
            quality_warning_flag(
                self.current["orig"], self.current["trans"], origem, destino
            ),
        )
        self.row_buttons[index].configure(text=row_label(self.state.rows[index]))
        if self.state.selected_index == index:
            self.row_buttons[index].configure(
                fg_color=SELECTED_ROW_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )
        else:
            self.row_buttons[index].configure(
                fg_color=row_color(self.state.rows[index]),
                text_color=row_text_color(self.state.rows[index]),
            )

    def confirm_and_propagate(self, translation, candidates):
        """Pergunta, e so entao propaga a verificacao. Devolve quantas marcou.

        Garantia V1. A propagacao acontecia sem nenhuma pergunta e era anunciada
        depois — "N iguais também verificadas" —, e o que ela marca sao N
        originais DIFERENTES que ninguem leu. Marcar por acidente e o oposto exato
        do que "verificada" quer dizer.

        Os ids sao os que a previa mostrou (`only_ids`): se o worker gravar uma
        linha nova com a mesma traducao enquanto o dialogo estiver aberto, ela nao
        entra na propagacao — o usuario nao a viu.
        """
        if not candidates:
            return 0

        if not messagebox.askyesno(
            "Verificar traduções iguais",
            format_propagation_confirmation(translation, candidates),
            parent=self.win,
        ):
            return 0

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            propagated = set_exact_translation_matches_verified(
                cur,
                self.current["id"],
                only_ids=[row_id for row_id, _original in candidates],
            )
            conn.commit()
        return propagated

    def save_changes(self, silent=True, mark_verified=False):
        if not self.current["id"]:
            return

        nova_nota = self.reviewer_note_text.get().strip()
        # Os dois lados aparados: a nota vem do banco como esta la, e comparar
        # uma ponta aparada com uma nao aparada faria toda navegacao numa linha
        # com espaco sobrando gravar de novo — o oposto de R1.
        nota_mudou = nova_nota != (self.current.get("reviewer_note") or "").strip()

        # Gravacao silenciosa e a que acontece ao navegar pela lista. Se a unica
        # diferenca veio das regras automaticas, o usuario nao pediu nada: rolar
        # 50 linhas nao pode reescrever 50 traducoes e gerar 50 registros de
        # historico (garantia R1 da SPEC.md). Salvar explicitamente ou marcar
        # como verificada continua funcionando normalmente.
        #
        # Uma nota digitada e acao do usuario, e por isso ela atravessa esta
        # saida: sem a excecao, anotar numa linha que so as regras automaticas
        # tocaram e navegar perderia a nota — que e justamente o caminho que este
        # item veio fechar (ROADMAP 22.11).
        if silent and not mark_verified and self.current["auto_only"] and not nota_mudou:
            return

        new_trans = self.trans_text.get("1.0", tk.END).rstrip("\n")

        updated_row = None
        propagation_candidates = []
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            # A nota do revisor vai junto (ROADMAP 22.11). Ela so era gravada por
            # "Rejeitar", "Em dúvida" e "Limpar status": escrever a nota e navegar
            # a descartava em silencio, e e o caso comum — anotar "conferir com o
            # autor" numa linha que continua pendente.
            #
            # ANTES da traducao, e nao depois: `set_review_status_by_id` mantem o
            # `verified` em lockstep com o status (garantia F10), e chama-la
            # depois de um `mark_verified` desfaria a verificacao que o usuario
            # acabou de pedir. Com o status ATUAL, que e o que a linha ja tem —
            # esta gravacao e da nota, e nao do status.
            if nota_mudou:
                set_review_status_by_id(
                    cur,
                    self.current["id"],
                    self.current.get("review_status") or REVIEW_STATUS_PENDING,
                    note=nova_nota,
                )
            update_translation_by_id(cur, self.current["id"], new_trans, mark_verified)
            if mark_verified:
                propagation_candidates = fetch_exact_translation_match_candidates(
                    cur, self.current["id"]
                )
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()

        # A pergunta vem com a conexao JA fechada e a transacao comitada
        # (garantia C3): um dialogo modal aberto sobre uma transacao de escrita
        # seguraria o banco enquanto ninguem clica, e o "Salvar" do worker
        # esperaria o `busy_timeout` inteiro. O que ficou gravado ate aqui e o que
        # o usuario pediu — a propagacao e uma segunda decisao.
        propagated_rows = self.confirm_and_propagate(new_trans, propagation_candidates)

        self.current["trans"] = new_trans
        self.current["saved_trans"] = new_trans
        self.current["reviewer_note"] = nova_nota
        self.current["auto_only"] = False
        self.clear_current_draft()
        if updated_row is not None:
            self.set_current_history(updated_row)
        try:
            self.trans_text.edit_modified(False)
        except tk.TclError:
            pass
        self.set_dirty(False)
        if mark_verified and propagated_rows:
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                # Verificar propaga para as traducoes iguais, entao a lista
                # inteira pode ter mudado de tamanho. A linha atual continua
                # sendo a certa; a posicao dela, nao.
                self.select_index(
                    row_index_for_id(self.state.rows, self.current["id"], fallback=idx or 0)
                )
            else:
                self.clear_current()
            if not silent:
                self.show_message(
                    f"Tradução salva e verificada; {propagated_rows} outro(s) "
                    f"original(is) também verificado(s)"
                )
            return propagated_rows

        index = self.get_index()
        old_warning = False
        new_warning = False
        if index is not None and 0 <= index < len(self.state.rows):
            old_verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0
            old_warning = row_has_quality_warning(self.state.rows[index])
            verified = 1 if mark_verified else old_verified
            self.update_current_row_cache(verified)
            new_warning = row_has_quality_warning(self.state.rows[index])
            if old_warning != new_warning:
                if new_warning:
                    self.state.status_counts["qa"] += 1
                else:
                    self.state.status_counts["qa"] = max(0, self.state.status_counts["qa"] - 1)
                self.update_counts_label()
            if mark_verified and old_verified != 1:
                self.state.status_counts["pending"] = max(0, self.state.status_counts["pending"] - 1)
                self.state.status_counts["verified"] += 1
                self.update_counts_label()

        if self.qa_filter_active() and old_warning and not new_warning:
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if idx is None else min(idx, len(self.state.rows) - 1))
            else:
                self.clear_current()

        if mark_verified and self.selected_status_filter() == "pending":
            idx = self.get_index()
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if idx is None else min(idx, len(self.state.rows) - 1))
            else:
                self.clear_current()

        if not silent:
            if mark_verified:
                self.show_message("Tradução salva e verificada")
            else:
                self.show_message("Tradução salva")

    def index_after_save(self, comment_id, previous_index, delta=1):
        """Para onde ir depois de uma gravacao que pode ter encolhido a lista.

        `save_changes` pode tirar a linha aberta do filtro ativo — com "Avisos
        QA", corrigir o aviso faz exatamente isso — e ja selecionar quem ocupou o
        lugar dela (garantia R7). **Quem esta naquela posicao JA e a proxima**, e
        somar mais uma casa pula uma traducao sem nada na tela dizendo que ela
        existiu (garantia F15, ROADMAP 22.5).

        Para TRAS a conta nao muda: a linha que vinha antes continua uma casa
        antes da posicao vaga.

        A regra vivia dentro de `mark_and_next`, que era o unico dos tres
        caminhos a aplica-la. Aqui ela e uma so — e por isso o `navigate` e o F7
        deixaram de ser duas copias que ninguem escreveu.

        Devolve `None` quando nao ha lista para onde ir.
        """
        position = row_index_for_id(
            self.state.rows, comment_id, fallback=previous_index or 0
        )
        if position is None:
            return None
        saiu_da_lista = self.state.rows[position][0] != comment_id
        if saiu_da_lista and delta > 0:
            return position
        return position + delta

    def navigate(self, delta):
        """Anda uma linha na lista, gravando o que estava aberto.

        O id e a posicao sao capturados ANTES da gravacao: depois dela, a posicao
        lida pode ja ser a de quem ainda nao foi visto. Ver `index_after_save`.
        """
        current_id = self.current["id"]
        index = self.get_index()
        self.save_changes()
        if index is None:
            index = 0

        new_index = self.index_after_save(current_id, index, delta)
        if new_index is None:
            self.show_message("Fim da lista")
            return

        if 0 <= new_index < len(self.state.rows):
            self.select_index(new_index)
        elif new_index < 0 and self.state.page_index > 0:
            self.state.page_index -= 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(len(self.state.rows) - 1)
        elif new_index >= len(self.state.rows) and self.state.page_index + 1 < self.page_count():
            self.state.page_index += 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")

    def change_page(self, delta):
        self.save_changes()
        new_page = self.state.page_index + delta
        if 0 <= new_page < self.page_count():
            self.state.page_index = new_page
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)

    def go_to_page(self):
        self.save_changes()
        try:
            target_page = int(self.go_page_text.get().strip())
        except ValueError:
            self.show_message("Página inválida")
            return

        pages = self.page_count()
        if not (1 <= target_page <= pages):
            self.show_message("Página fora do intervalo")
            return

        self.remember_position()
        self.state.page_index = target_page - 1
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)

    def jump_to_id(self, target_id):
        """Seleciona a linha `target_id` dentro dos filtros ativos. `True` se achou.

        Extraida de `go_to_id` para que o "voltar" (item 3) use a MESMA maquina:
        offset calculado na lista filtrada e na ordem ativa, pagina derivada dele.
        Duas implementacoes de "posicionar num id" divergiriam no dia em que uma
        das duas ganhasse um filtro novo — que e a historia da garantia R10.
        """
        if not target_id:
            return False

        with closing(initialize_database(self.app.output_db)) as conn:
            offset = get_review_row_offset(
                conn.cursor(),
                self.lang,
                target_id,
                status_filter=self.selected_status_filter(),
                **self.list_query_args(),
            )

        if offset is None:
            return False

        self.state.page_index = page_of_offset(offset, PAGE_SIZE)
        self.reload_rows()
        target_index = local_index_for_offset(offset, PAGE_SIZE, len(self.state.rows))
        if target_index is None:
            return False
        self.select_index(target_index)
        return True

    def go_to_id(self):
        self.save_changes()
        try:
            target_id = int(self.go_id_text.get().strip())
        except ValueError:
            self.show_message("ID inválido")
            return

        self.remember_position()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            # Vale para todos os filtros, inclusive "Avisos QA": o offset sai de
            # um COUNT indexado em vez de uma varredura ate achar o ID.
            #
            # Os filtros entram aqui pelo mesmo motivo que entram no `reload_rows`
            # (garantia R10): o offset e uma posicao NA LISTA FILTRADA. Sem eles,
            # digitar um ID ingles com "Origem: Espanhol" ativo calculava a posicao
            # na tabela inteira e selecionava uma linha espanhola arbitraria — sem
            # mensagem nenhuma. E a mesma classe do bug que a garantia R7 fechou:
            # navegar pela posicao errada. A ORDEM vai junto: com a obra em ordem
            # de leitura, "quantas linhas vem antes" nao e mais "quantas tem id
            # menor".
            offset = get_review_row_offset(
                cur,
                self.lang,
                target_id,
                status_filter=self.selected_status_filter(),
                **self.list_query_args(),
            )

        if offset is None:
            self.show_message("ID não encontrado nos filtros atuais")
            return

        self.state.page_index = page_of_offset(offset, PAGE_SIZE)
        self.reload_rows()
        target_index = local_index_for_offset(offset, PAGE_SIZE, len(self.state.rows))
        if target_index is not None:
            self.select_index(target_index)

    def find_quality_warning_offset(self, start_offset, stop_offset):
        """Varre da posicao `start_offset` ate `stop_offset` procurando um aviso.

        As posicoes sao offsets NA LISTA FILTRADA, e `stop_offset` vem de
        `state.total_rows` — que ja e o total filtrado. Sem passar o filtro de
        origem para a consulta (garantia R10), F7 varria as primeiras N linhas da
        tabela INTEIRA usando o total filtrado como limite, e anunciava o aviso de
        uma linha que nao esta na tela.
        """
        if start_offset >= stop_offset:
            return None

        offset = start_offset
        consulta = self.list_query_args()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            while offset < stop_offset:
                page_start = page_offset(page_of_offset(offset, PAGE_SIZE), PAGE_SIZE)
                local_start = offset - page_start
                page_rows = list(
                    fetch_review_rows_page(
                        cur,
                        self.lang,
                        limit=PAGE_SIZE,
                        offset=page_start,
                        status_filter=self.selected_status_filter(),
                        **consulta,
                    )
                )
                if not page_rows:
                    break

                page_limit = stop_offset - page_start
                if page_limit < len(page_rows):
                    page_rows = page_rows[:page_limit]

                found = find_first_quality_warning(page_rows, local_start)
                if found is not None:
                    found_index, _row, warnings = found
                    return page_start + found_index, warnings

                offset = page_start + len(page_rows)

        return None

    def go_to_next_quality_warning(self):
        # Capturados antes da gravacao, como em `navigate`: e aqui que pular uma
        # linha mais doi, porque a fila de avisos existe justamente para nao
        # deixar nenhuma para tras (garantia F15, ROADMAP 22.5).
        current_id = self.current["id"]
        previous_index = self.get_index()
        self.save_changes()
        total = self.state.total_rows
        if total == 0:
            self.show_message("Nenhum item nos filtros atuais")
            return

        # F7 tambem e um salto: ele pode atravessar a obra inteira e dar a volta.
        self.remember_position()

        base_offset = page_offset(self.state.page_index, PAGE_SIZE)
        local_index = self.index_after_save(current_id, previous_index, 1)
        start_offset = base_offset + (local_index or 0)

        if start_offset >= total:
            start_offset = 0

        if self.qa_filter_active():
            # Todas as linhas do filtro ja tem aviso: basta ir para a proxima.
            target_offset = start_offset
            self.state.page_index = page_of_offset(target_offset, PAGE_SIZE)
            self.reload_rows()
            # `state.rows` vem de um reload novo e pode ser menor que a pagina
            # anterior
            # (o worker de traducao escreve no mesmo banco), entao o indice
            # precisa ser limitado antes de indexar a lista.
            local_index = local_index_for_offset(target_offset, PAGE_SIZE, len(self.state.rows))
            if local_index is not None:
                self.select_index(local_index)
                # `row_quality_warnings`, e nao `evaluate_translation_quality`: a
                # primeira le o par das proprias posicoes 7 e 8 da linha. Sem o
                # par, uma linha marcada SO por terminologia devolvia lista vazia
                # aqui — o F7 parava nela (ela esta na lista pela coluna) e ficava
                # mudo sobre o motivo. E o ramo sem filtro, logo abaixo, sempre
                # acertou: ele passa por `find_first_quality_warning`, que usa a
                # mesma funcao (garantia Q3, ROADMAP 22.2).
                warnings = row_quality_warnings(self.state.rows[local_index])
                if warnings:
                    self.show_message("Aviso QA: " + warnings[0])
            return

        found = self.find_quality_warning_offset(start_offset, total)
        if found is None and start_offset > 0:
            found = self.find_quality_warning_offset(0, start_offset)

        if found is None:
            self.show_message("Nenhum aviso QA nos filtros atuais")
            return

        target_offset, warnings = found
        self.state.page_index = page_of_offset(target_offset, PAGE_SIZE)
        self.reload_rows()
        local_index = local_index_for_offset(target_offset, PAGE_SIZE, len(self.state.rows))
        if local_index is not None:
            self.select_index(local_index)
        self.show_message("Aviso QA: " + warnings[0])

    def export_quality_report(self):
        self.save_changes()
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            report_rows = build_quality_report_rows(
                self.fetch_quality_warning_rows(cur),
                self.lang,
            )

        if not report_rows:
            self.show_message("Nenhum aviso QA para exportar")
            return

        save_path = filedialog.asksaveasfilename(
            title="Salvar relatorio QA",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return

        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(QUALITY_REPORT_HEADERS)
                writer.writerows(report_rows)
        except OSError as exc:
            messagebox.showerror("Erro", f"Erro ao exportar relatorio QA:\n{exc}")
            return

        messagebox.showinfo(
            "Exportar QA",
            f"Relatorio QA exportado com {len(report_rows)} avisos:\n{save_path}",
        )

    def mark_and_next(self):
        if not self.current["id"]:
            return

        # Mesma raiz do `select_index`: `save_changes(mark_verified=True)` pode
        # recarregar a lista — propagando para as traducoes iguais, ou tirando
        # esta linha do filtro ativo — e ai a posicao capturada agora aponta
        # para outra linha. Guardamos o id e reencontramos a posicao depois.
        current_id = self.current["id"]
        index = self.get_index()
        propagated = self.save_changes(mark_verified=True) or 0

        if self.selected_status_filter() == "pending":
            if propagated:
                self.show_message(
                    f"Verificada; {propagated} outro(s) original(is) também "
                    f"verificado(s)"
                )
            else:
                self.show_message("Marcada como verificada" if self.current["id"] else "Sem traduções pendentes")
            return

        # A regra de "se a linha saiu da lista, quem ocupou o lugar dela ja E a
        # proxima" nasceu aqui e agora vive em `index_after_save`, que e onde o
        # `navigate` e o F7 tambem a leem (garantia F15).
        new_index = self.index_after_save(current_id, index, 1)
        if new_index is None:
            self.show_message("Fim da lista")
            return

        if 0 <= new_index < len(self.state.rows):
            self.select_index(new_index)
        elif new_index >= len(self.state.rows) and self.state.page_index + 1 < self.page_count():
            self.state.page_index += 1
            self.reload_rows()
            if self.state.rows:
                self.select_index(0)
        else:
            self.show_message("Fim da lista")
            return

        if propagated:
            self.show_message(
                f"Verificada; {propagated} outro(s) original(is) também verificado(s)"
            )
        else:
            self.show_message("Marcada como verificada")

    def mark_pending(self):
        if not self.current["id"]:
            return

        self.save_changes()
        updated_row = None
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            set_translation_verified_by_id(cur, self.current["id"], False)
            updated_row = fetch_translation_by_id(cur, self.current["id"])
            conn.commit()
        if updated_row is not None:
            self.set_current_history(updated_row)

        index = self.get_index()
        if self.selected_status_filter() == "verified":
            self.reload_rows()
            if self.state.rows:
                self.select_index(0 if index is None else min(index, len(self.state.rows) - 1))
            else:
                self.clear_current()
        elif index is not None and 0 <= index < len(self.state.rows):
            old_verified = self.state.rows[index][3] if len(self.state.rows[index]) > 3 else 0
            self.update_current_row_cache(0)
            if old_verified == 1:
                self.state.status_counts["verified"] = max(0, self.state.status_counts["verified"] - 1)
                self.state.status_counts["pending"] += 1
                self.update_counts_label()

        self.show_message("Marcada como pendente")

    def verify_selected_rows(self):
        """Marca como verificadas as linhas selecionadas (ROADMAP 19, item 9).

        Passa pelo MESMO caminho de uma linha so (`set_translation_verified_by_id`),
        entao cada uma ganha carimbo e entrada de historico. Um `UPDATE` em massa
        seria mais rapido e deixaria N linhas verificadas sem historico — e a
        garantia R2 existe porque a pergunta "quem marcou isto, e quando" e a
        primeira que se faz numa revisao que deu errado.

        **NAO propaga para traducoes iguais.** A propagacao tem confirmacao propria
        (garantia V1) porque marca originais que ninguem leu; encadea-la aqui faria
        um clique em "Verificar" com 100 linhas marcadas abrir 100 dialogos, ou —
        pior — nenhum.
        """
        if not self.state.selected_ids:
            return
        self.save_changes()
        alvos = sorted(self.state.selected_ids)
        aberto = self.current["id"]
        indice_antes = self.get_index()

        if not messagebox.askyesno(
            "Verificar selecionadas",
            f"Marcar {len(alvos)} tradução(oes) selecionada(s) como verificada(s)?\n\n"
            f"{self.describe_selection_outside_filters(alvos)}"
            "Traduções iguais em outras linhas NÃO são afetadas.",
            parent=self.win,
        ):
            return

        marcadas = 0
        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            for comment_id in alvos:
                marcadas += set_translation_verified_by_id(cur, comment_id) or 0
            conn.commit()

        self.clear_row_selection()
        self.reload_rows()
        if self.state.rows:
            # A linha ABERTA de volta, e nao a primeira da pagina (ROADMAP
            # 22.11). Era o unico recarregamento pos-acao que nao reencontrava a
            # linha pelo id: quem verificava um lote no meio de um capitulo de
            # 3.000 linhas voltava ao comeco da pagina e tinha de se achar de
            # novo. Os outros dois caminhos ja usavam `row_index_for_id`.
            self.select_index(
                row_index_for_id(self.state.rows, aberto, fallback=indice_antes or 0)
                or 0
            )
        self.show_message(f"{marcadas} tradução(oes) verificada(s)")
        return marcadas

    def describe_selection_outside_filters(self, alvos):
        """"N das marcadas estao fora do que a lista mostra", ou "".

        A selecao e por id e **sobrevive** a trocar de arquivo, de status e de
        busca — so a troca de PAR a apaga. Isso e util de proposito: juntar
        linhas de tres capitulos e o caso que a barra existe para servir
        (garantia F7).

        Mas a razao registrada para mata-la na troca de par — "um id do par
        anterior nao esta na lista nova, e Verificar marcaria linhas que o revisor
        nao ve" — vale letra por letra para os outros tres, e a diferenca e que
        deles da para voltar: os ids continuam validos. **Entao a sobrevivencia
        fica, e quem passa a dizer a verdade e a confirmacao** (ROADMAP 22.11);
        matar a selecao a cada troca de filtro trocaria um risco silencioso por
        uma perda de trabalho garantida.

        A consulta e a mesma lista de ids do "Marcar tudo", e custa o que ela
        custa: 3,03 ms no banco de dev. Uma vez por lote, contra uma confirmacao
        que hoje afirma menos do que sabe.
        """
        with closing(initialize_database(self.app.output_db)) as conn:
            visiveis = set(
                fetch_review_row_ids(
                    conn.cursor(),
                    self.lang,
                    status_filter=self.selected_status_filter(),
                    **self.list_filters(),
                )
            )
        fora = [alvo for alvo in alvos if alvo not in visiveis]
        if not fora:
            return ""
        return (
            f"{len(fora)} dela(s) está(ão) fora dos filtros atuais — "
            "marcada(s) antes de você trocar de arquivo, de status ou de busca, "
            "e não aparece(m) nesta lista.\n\n"
        )

    def export_selected_rows(self):
        """Exporta so as linhas selecionadas para CSV (ROADMAP 19, item 9)."""
        if not self.state.selected_ids:
            return
        self.save_changes()
        alvos = sorted(self.state.selected_ids)

        save_path = filedialog.asksaveasfilename(
            title="Exportar selecao",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return

        try:
            escritas = export_translations_to_csv(
                self.app.output_db, save_path, only_ids=alvos
            )
        except OSError as exc:
            messagebox.showerror("Erro", f"Erro ao exportar a selecao:\n{exc}")
            return

        messagebox.showinfo(
            "Exportar selecao",
            f"{escritas} tradução(oes) exportada(s) para:\n{save_path}",
        )

    def set_review_status(self, status):
        """Grava o status de revisao e a nota da linha aberta (item 12).

        A nota vai junto com o status na mesma gravacao porque na tela e um gesto so:
        quem rejeita escreve por que. Uma linha rejeitada ou em duvida deixa de estar
        verificada — dizer que a verificacao estava errada e o proposito do botao.

        **A edicao aberta e gravada antes** (garantia F12, ROADMAP 22.1): rejeitar
        e anotar por que e justamente o gesto de quem estava mexendo no texto e
        desistiu, e o recarregamento que vem depois descartava o que ele digitou.
        """
        if not self.current["id"]:
            return 0

        # Lidos ANTES de gravar, e nao depois: `save_changes` pode recarregar a
        # lista — com o filtro "Avisos QA" ativo, corrigir o aviso tira a propria
        # linha (garantia R7) — e ai `current` ja aponta para outra, cuja nota o
        # `load_item` acabou de por no campo. O status iria para a linha errada,
        # com a nota errada, e as duas na tela pareceriam certas.
        comment_id = self.current["id"]
        nota = self.reviewer_note_text.get().strip()
        self.save_changes()

        with closing(initialize_database(self.app.output_db)) as conn:
            cur = conn.cursor()
            mudou = set_review_status_by_id(cur, comment_id, status, note=nota)
            conn.commit()

        # So anuncia na tela se a tela ainda for desta linha. Depois de um
        # recarregamento a janela pode estar mostrando outra, e pintar nela o
        # status que foi para esta e a mesma classe de erro que a garantia R3
        # evita na janela de historico. A linha certa reaparece logo abaixo, pelo
        # id — e `load_item` rele status e nota do banco.
        if self.current["id"] == comment_id:
            self.current["review_status"] = status
            self.current["reviewer_note"] = nota
            self.update_review_status_label()

        if status:
            self.show_message(
                "Marcada como rejeitada" if status == REVIEW_STATUS_REJECTED
                else "Marcada como em dúvida"
            )
        else:
            self.show_message("Status de revisão limpo")

        # A linha pode ter saido do filtro ativo (era verificada e deixou de ser, ou
        # o filtro e "Rejeitadas"), entao a lista e recarregada e a posicao
        # reencontrada pelo id — a mesma regra de `mark_and_next`.
        if mudou:
            indice = self.get_index()
            self.reload_rows()
            if self.state.rows:
                self.select_index(
                    row_index_for_id(
                        self.state.rows, comment_id, fallback=indice or 0
                    )
                )
            else:
                self.clear_current()
        return mudou

    def update_review_status_label(self):
        """Diz o status da linha aberta EM PALAVRAS, e pinta o campo de nota.

        A cor continua no campo, porque e ali que o olho vai quando a pergunta e
        "esta linha volta para alguem?" — mas ela deixou de ser a unica forma de
        saber (garantia F19, ROADMAP 22.9).

        **A docstring que estava aqui dizia "e diz qual e no rodape", e o metodo
        nao escrevia rodape nenhum.** Nenhum outro ponto da janela dizia o nome do
        status: o rodape mostra contagens do filtro inteiro, e a linha da lista
        rotula a rejeitada de "PEND", igual a uma pendente comum. Quem perdesse a
        mensagem de confirmacao ficava com uma borda colorida — que para um
        protanope e a mesma cor nos dois casos.

        Sem status, o rotulo sai do grid e o campo volta ao neutro: a nota de uma
        linha pendente e um lembrete, e nao um alarme.
        """
        status = self.current.get("review_status") or REVIEW_STATUS_PENDING
        cor = {
            REVIEW_STATUS_REJECTED: ERROR_TEXT_COLOR,
            REVIEW_STATUS_DOUBT: WARNING_TEXT_COLOR,
        }.get(status, self.text_border)
        try:
            self.note_entry.configure(border_color=cor)
        except tk.TclError:  # pragma: no cover - tema sem essa propriedade
            pass

        texto = REVIEW_STATUS_LABELS.get(status, "")
        self.review_status_label.configure(text=texto, text_color=cor)
        if texto:
            self.review_status_label.grid(row=0, column=2, sticky="w", padx=(0, 8))
        else:
            self.review_status_label.grid_remove()

    def open_shortcuts_window(self, _event=None):
        """A lista de atalhos, em janela propria (garantia F18, ROADMAP 22.8).

        E o unico lugar possivel para os tres que nao tem botao — `Ctrl+F`,
        `Ctrl+L` e `Ctrl+B` —, e por isso a correcao foi esta e nao pendurar o
        atalho no rotulo dos botoes: os rotulos alcancam dez dos treze, e as duas
        fileiras do rodape ja estao apertadas (ROADMAP 22.10).

        **Modeless, e de proposito**: ela existe para ser consultada enquanto se
        experimenta o atalho. Um modal obrigaria a fechar para usar o que se
        acabou de ler. Reabrir traz a que ja esta aberta para a frente, em vez de
        empilhar copias.
        """
        janela = getattr(self, "shortcuts_win", None)
        if janela is not None and janela.winfo_exists():
            bring_window_to_front(janela, self.win, maximize=False)
            return janela

        janela = ctk.CTkToplevel(self.win)
        self.shortcuts_win = janela
        janela.title("Atalhos do editor")
        janela.geometry("460x520")
        janela.minsize(380, 360)
        janela.transient(self.win)
        bring_window_to_front(janela, self.win, maximize=False)
        janela.columnconfigure(0, weight=1)

        linha = 0

        def escrever(titulo, itens):
            nonlocal linha
            ctk.CTkLabel(
                janela, text=titulo, font=ctk.CTkFont(weight="bold"), anchor="w"
            ).grid(row=linha, column=0, sticky="ew", padx=16, pady=(14, 2))
            linha += 1
            for rotulo, descricao in itens:
                item = ctk.CTkFrame(janela, fg_color="transparent")
                item.grid(row=linha, column=0, sticky="ew", padx=16)
                item.columnconfigure(1, weight=1)
                ctk.CTkLabel(
                    item, text=rotulo, width=140, anchor="w",
                    font=ctk.CTkFont(weight="bold"),
                ).grid(row=0, column=0, sticky="w")
                ctk.CTkLabel(item, text=descricao, anchor="w", justify=tk.LEFT).grid(
                    row=0, column=1, sticky="ew"
                )
                linha += 1

        for titulo, atalhos in KEYBOARD_SHORTCUTS:
            escrever(titulo, [(rotulo, descricao) for rotulo, _seq, descricao in atalhos])
        # Os gestos de mouse entram na MESMA janela (ROADMAP 22.11): sao tao
        # invisiveis quanto os atalhos, e quem procura "como faco isto mais
        # rapido" abre um lugar so.
        escrever("Mouse", MOUSE_GESTURES)

        ctk.CTkButton(janela, text="Fechar", width=100, command=janela.destroy).grid(
            row=linha, column=0, sticky="e", padx=16, pady=16
        )
        return janela

    def open_history_window(self):
        if not self.current["id"]:
            self.show_message("Selecione uma traducao")
            return

        self.save_changes()
        # O item e fixado AQUI, e nao lido pela subjanela a cada acao: ela e
        # modeless e a lista principal continua clicavel enquanto ela esta
        # aberta (garantia R3).
        return HistoryWindow(self, self.current["id"], self.current["orig"])

    def undo_translation(self):
        try:
            self.trans_text.edit_undo()
        except tk.TclError:
            self.show_message("Nada para desfazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def redo_translation(self):
        try:
            self.trans_text.edit_redo()
        except tk.TclError:
            self.show_message("Nada para refazer")
            return
        self.set_dirty(True)
        self.refresh_suggestions()
        self.update_quality_warnings()
        self.refresh_find_matches()

    def restore_saved_translation(self):
        """"Restaurar": devolve a linha ao texto que esta no banco.

        `keep_undo` tambem aqui, e este vai alem dos quatro que o ROADMAP 22.4
        nomeia — pela mesma regra, que e a linha nao ter mudado. E o caso em que
        o desfazer vale mais: "Restaurar" era o unico caminho de volta das outras
        quatro acoes e descartava TUDO, inclusive o que o revisor queria manter.
        Com a pilha de pe, ele deixa de ser um penhasco.
        """
        if not self.current["id"]:
            return
        self.set_translation_text(
            self.current["saved_trans"], mark_dirty=False, keep_undo=True
        )
        self.current["trans"] = self.current["saved_trans"]
        self.clear_current_draft()
        self.show_message("Tradução restaurada")

    def copy_original_to_translation(self):
        if not self.current["id"]:
            return
        self.set_translation_text(
            self.current["orig"], mark_dirty=True, keep_undo=True
        )
        self.show_message("Original copiado para tradução")

    def toggle_filter(self):
        """Troca o filtro de status: grava o que estava aberto e recomeca.

        A gravacao vem primeiro porque a troca RECARREGA a lista, e o
        recarregamento passa por `set_translation_text` — que sobrescreve o
        widget e, pior, chama `set_dirty(False)`, que cancela o rascunho ainda
        agendado. Sem ela, o que o revisor digitou desde a ultima pausa de 2,5 s
        nao estava no widget, nem no banco, nem no rascunho (garantia F12,
        ROADMAP 22.1).
        """
        self.remember_position()
        self.save_changes()
        self.state.page_index = 0
        self.save_editor_settings()
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def apply_search(self):
        # Antes de tudo: e este o salto que o item 3 existe para desfazer — usar a
        # busca como concordancia descartava a pagina em que se estava. Antes do
        # `save_changes` tambem, pelo motivo que `remember_position` explica.
        self.remember_position()
        self.save_changes()
        self.state.active_search = self.search_text.get().strip()
        self.state.page_index = 0
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def clear_search(self):
        """Limpa a busca da lista: grava o que estava aberto e recomeca.

        `apply_search` sempre gravou e este, o botao ao lado dela na mesma
        barra, nao gravava — dois gestos vizinhos com desfechos opostos para a
        edicao aberta (garantia F12, ROADMAP 22.1).

        A gravacao fica DEPOIS da saida antecipada: sem busca ativa o clique nao
        troca lista nenhuma, e gravar ali seria um efeito colateral de um botao
        que nao fez nada.
        """
        if not self.state.active_search and not self.search_text.get():
            return
        self.remember_position()
        self.save_changes()
        self.search_text.set("")
        self.state.active_search = ""
        self.state.page_index = 0
        self.reload_rows()
        if self.state.rows:
            self.select_index(0)
        else:
            self.clear_current()

    def apply_automatic_rules_for_current_language(self):
        self.save_changes()
        previous_id = self.current["id"]

        def concluido(stats):
            # Chega pela thread do Tk quando a operacao termina; `None` quando
            # o usuario cancelou, nao confirmou ou nao havia o que mudar.
            if not stats or stats.get("changed", 0) == 0:
                return
            if not self.win.winfo_exists():
                return

            self.reload_rows()
            if not self.state.rows:
                self.clear_current()
                return

            self.select_index(row_index_for_id(self.state.rows, previous_id, fallback=0))
            self.show_message(f"{stats['changed']} traducao(oes) atualizada(s)")

        # Restrito ao mesmo filtro que a lista mostra: com "Origem: Espanhol"
        # ativo, o usuario esta olhando as traducoes vindas do espanhol, e
        # reescrever tambem as das outras linguas seria uma alteracao em massa
        # que ele nao pediu nem consegue ver na tela.
        apply_automatic_rules_to_database(
            self.app,
            target_language=self.lang,
            parent=self.win,
            on_finish=concluido,
            source_language=self.selected_source_language(),
        )

    def select_suggestion(self, index):
        old = self.state.selected_suggestion
        if old is not None and 0 <= old < len(self.suggestion_buttons):
            self.suggestion_buttons[old].configure(
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
            )

        self.state.selected_suggestion = index
        if 0 <= index < len(self.suggestion_buttons):
            self.suggestion_buttons[index].configure(
                fg_color=SUGGESTION_SELECTED_COLOR,
                text_color=SELECTED_ROW_TEXT_COLOR,
            )

    def delete_suggestion_from_glossary(self, orig, new):
        # Exclui pelo par, nunca por indice: a lista exibida aqui e deduplicada
        # e a exclusao opera sobre a lista completa do arquivo, entao os indices
        # nao correspondem (garantia S6 da SPEC.md).
        if delete_glossary_entry_by_pair(orig, new) is None:
            self.show_message("Entrada não encontrada no glossário")
            return

        self.reload_glossary(show_feedback=False)
        self.show_message(f'Removido do glossário: "{preview(orig, 30)}"')

    def show_suggestion_context_menu(self, event, orig, new):
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(
            label="Excluir do glossário",
            command=lambda: self.delete_suggestion_from_glossary(orig, new),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def refresh_suggestions(self):
        for child in self.suggestions_frame.winfo_children():
            child.destroy()
        self.suggestion_buttons.clear()
        self.state.selected_suggestion = None

        text = self.trans_text.get("1.0", tk.END)
        self.current_suggestions = find_glossary_suggestions(text, self.glossary)
        self.highlight_glossary_hits()

        if not self.current_suggestions:
            ctk.CTkLabel(self.suggestions_frame, text="Nenhuma sugestão.").pack(
                anchor="w", padx=6, pady=6
            )
            return

        for index, (orig, new) in enumerate(self.current_suggestions):
            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=f'"{preview(orig, 45)}" -> "{preview(new, 45)}"',
                anchor="w",
                fg_color=SUGGESTION_COLOR,
                text_color=SUGGESTION_TEXT_COLOR,
                hover_color=ROW_HOVER_COLOR,
                font=self.suggestion_font,
                command=lambda i=index: self.select_suggestion(i),
            )
            btn.pack(fill=tk.X, padx=2, pady=2)
            btn.bind(
                "<Button-3>",
                lambda event, o=orig, n=new: self.show_suggestion_context_menu(event, o, n),
            )
            # Aplicar uma sugestao custava dois cliques com deslocamento — marcar
            # na lista e ir ate "Aplicar selecionada", no canto oposto do painel
            # (ROADMAP 22.11). O clique simples continua so selecionando: quem
            # quer ler a regra antes de aplicar nao pode ser obrigado a aplicar
            # para le-la.
            btn.bind(
                "<Double-Button-1>",
                lambda _event, i=index: self.apply_suggestion_at(i),
            )
            self.suggestion_buttons.append(btn)

    def apply_suggestion_at(self, index):
        """Seleciona a sugestao e a aplica — o duplo clique (ROADMAP 22.11)."""
        self.select_suggestion(index)
        self.apply_one()
        return "break"

    def apply_glossary_pair_with_cursor(self, text, orig, new, count=0):
        matches = find_glossary_matches(text, orig)
        if count > 0:
            matches = matches[:count]
        if not matches:
            return text, None

        parts = []
        last = 0
        cursor_offset = 0
        insert_offset = None
        for start, end in matches:
            before = text[last:start]
            parts.append(before)
            cursor_offset += len(before)
            replacement = case_adjusted_replacement(text[start:end], new)
            parts.append(replacement)
            cursor_offset += len(replacement)
            insert_offset = cursor_offset
            last = end
        parts.append(text[last:])
        return "".join(parts), insert_offset

    def apply_suggestions_with_cursor(self, text, suggestions):
        insert_offset = None
        for orig, new in suggestions:
            text, pair_offset = self.apply_glossary_pair_with_cursor(text, orig, new)
            if pair_offset is not None:
                insert_offset = pair_offset
        return text, insert_offset

    def apply_one(self):
        index = self.state.selected_suggestion
        if index is None or not (0 <= index < len(self.current_suggestions)):
            return

        orig, new = self.current_suggestions[index]
        text = self.draft_text()
        updated_text, insert_offset = self.apply_glossary_pair_with_cursor(
            text,
            orig,
            new,
            count=1,
        )
        if insert_offset is None:
            self.show_message("Sugestão não encontrada no texto")
            return
        self.set_translation_text(
            updated_text,
            mark_dirty=True,
            insert_offset=insert_offset,
            focus_editor=True,
            keep_undo=True,
        )

    def apply_all(self):
        text = self.draft_text()
        preview_text, preview_offset = self.apply_suggestions_with_cursor(
            text,
            self.current_suggestions,
        )
        if preview_text == text:
            self.show_message("Nenhuma alteração sugerida")
            return

        pop = ctk.CTkToplevel(self.win)
        pop.title("Pré-visualizar substituições")
        pop.geometry("980x560")
        bring_window_to_front(pop, self.win, maximize=True)

        ctk.CTkLabel(pop, text="Antes").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(pop, text="Depois").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 2))

        before_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        after_text = ctk.CTkTextbox(pop, wrap=tk.WORD)
        before_text.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        after_text.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        before_text.insert("1.0", text)
        after_text.insert("1.0", preview_text)

        # As faixas trocadas, pintadas (ROADMAP 19, item 5). Sem isto, conferir 80
        # substituicoes era comparar dois blocos de texto a olho nu — que e o mesmo
        # que nao conferir. As cores sao as duas que a janela ja usa para "mudou":
        # a de remocao no lado de antes, a de acerto no lado de depois.
        faixas_antes, faixas_depois = diff_spans(text, preview_text)
        for caixa, faixas, cor in (
            (before_text, faixas_antes, self.diff_removed_bg),
            (after_text, faixas_depois, self.diff_added_bg),
        ):
            caixa.tag_config("diff", background=cor)
            for inicio, fim in faixas:
                caixa.tag_add(
                    "diff",
                    f"1.0+{inicio}c",
                    f"1.0+{fim}c",
                )
        # DEPOIS de pintar: um `CTkTextbox` desabilitado nao aceita `tag_add`.
        before_text.configure(state="disabled")
        after_text.configure(state="disabled")

        actions = ctk.CTkFrame(pop, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))
        ctk.CTkLabel(
            actions,
            text=f"{len(faixas_depois)} trecho(s) alterado(s)",
            text_color=MUTED_TEXT_COLOR,
        ).pack(side=tk.LEFT, padx=(0, 12))

        def confirm():
            self.set_translation_text(
                preview_text,
                mark_dirty=True,
                insert_offset=preview_offset,
                focus_editor=True,
                keep_undo=True,
            )
            pop.destroy()

        ctk.CTkButton(actions, text="Cancelar", width=100, command=pop.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ctk.CTkButton(actions, text="Aplicar", width=100, command=confirm).pack(side=tk.RIGHT)

        pop.columnconfigure(0, weight=1)
        pop.columnconfigure(1, weight=1)
        pop.rowconfigure(1, weight=1)

    def scoped_languages(self):
        """O par que decide quais regras do glossario existem nesta janela.

        O destino e o da janela; a origem sai do filtro, e `None` ali significa
        "Todos" — que para o escopo (garantia S11) e o mesmo que nao declarar:
        uma regra que exige `en>pt` nao pode ser aplicada a uma lista que mistura
        origens, porque ela nao vale para todas as linhas dela.
        """
        return self.selected_source_language() or "", self.lang

    def load_scoped_automatic_glossary(self):
        origem, destino = self.scoped_languages()
        return load_automatic_substitutions(
            source_language=origem, target_language=destino
        )

    def load_scoped_interactive_glossary(self):
        origem, destino = self.scoped_languages()
        return load_interactive_substitutions(
            source_language=origem, target_language=destino
        )

    def reload_glossary(self, show_feedback=True):
        self.glossary = self.load_scoped_interactive_glossary()
        self.automatic_glossary = self.load_scoped_automatic_glossary()
        # A lista do app fica SEM escopo de proposito: ela e o glossario inteiro,
        # e quem a le e a contagem do "Zerar Glossario" — que precisa dizer
        # quantas regras existem, e nao quantas valem para o par desta janela.
        self.app.glossary_substitutions = load_interactive_substitutions()
        self.refresh_suggestions()
        if show_feedback:
            self.show_message(f"Glossário atualizado: {len(self.glossary)} entradas")

    def on_glossary_editor_change(self, updated_entries):
        if not self.win.winfo_exists():
            self.unregister_glossary_callback()
            return
        # `updated_entries` vem do editor de glossario e nao tem escopo aplicado:
        # ele edita o arquivo inteiro. O que esta janela oferece e o recorte do
        # par dela, entao a lista dela e recarregada com filtro.
        #
        # `versioned_rules` e nao `list`: esta lista e a que a PROXIMA janela do
        # editor adota como glossario inicial, e sem a marca de versao a ordenacao
        # dela volta a custar a chave por conteudo em cada tecla (ROADMAP 20.6).
        self.app.glossary_substitutions = versioned_rules(updated_entries)
        self.glossary = self.load_scoped_interactive_glossary()
        self.automatic_glossary = self.load_scoped_automatic_glossary()
        self.refresh_suggestions()
        self.show_message(f"Glossário atualizado: {len(self.glossary)} entradas")

    def selected_translation_text(self):
        try:
            return self.trans_text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ""

    def open_integrated_glossary_editor(self):
        selection = self.selected_translation_text()
        if selection:
            open_glossary_editor(self.app, initial_original=selection)
            self.show_message("Selecao enviada ao editor de glossario")
        else:
            open_glossary_editor(self.app)
            self.show_message("Selecione um trecho para pre-preencher o glossario")

    def unregister_glossary_callback(self):
        callbacks = getattr(self.app, "glossary_change_callbacks", [])
        if self.on_glossary_editor_change in callbacks:
            callbacks.remove(self.on_glossary_editor_change)


    def add_gloss_popup(self):
        sel_text = self.selected_translation_text()

        pop = ctk.CTkToplevel(self.win)
        pop.title("Adicionar ao glossário")
        pop.geometry("380x255")
        # `maximize=False`: sao tres campos e um botao. Maximizado, o formulario
        # ficava num canto de uma janela do tamanho da tela, cobrindo o editor —
        # e o texto que o usuario acabou de selecionar para copiar dali.
        bring_window_to_front(pop, self.win, maximize=False)

        ctk.CTkLabel(pop, text="Texto original:").pack(anchor="w", padx=12, pady=(12, 2))
        original_entry = ctk.CTkEntry(pop, width=350)
        original_entry.pack(padx=12, fill=tk.X)
        original_entry.insert(0, sel_text)

        ctk.CTkLabel(pop, text="Substituir por:").pack(anchor="w", padx=12, pady=(10, 2))
        replacement_entry = ctk.CTkEntry(pop, width=350)
        replacement_entry.pack(padx=12, fill=tk.X)

        ctk.CTkLabel(pop, text="Tipo:").pack(anchor="w", padx=12, pady=(10, 2))
        type_var = tk.StringVar(master=pop, value="Sugestão")
        ctk.CTkSegmentedButton(
            pop,
            values=["Sugestão", "Automático", "Limpeza"],
            variable=type_var,
        ).pack(padx=12, fill=tk.X)

        _type_map = {"Sugestão": "suggestion", "Automático": "automatic", "Limpeza": "cleanup"}

        def confirm():
            """Grava a regra, e nao fecha a janela sem dizer o que aconteceu.

            Antes, os tres desfechos — gravou, campo vazio, gravacao falhou —
            terminavam na MESMA coisa: a janela fechada. Sem regra nenhuma no
            glossario e sem uma palavra na tela, o usuario tinha todo motivo para
            achar que gravou.
            """
            orig = original_entry.get().strip()
            new = replacement_entry.get().strip()
            rule_type = _type_map.get(type_var.get(), "suggestion")

            if not orig:
                messagebox.showwarning(
                    "Adicionar ao glossário",
                    "Informe o texto original da regra.",
                    parent=pop,
                )
                return
            if not new and rule_type != "cleanup":
                messagebox.showwarning(
                    "Adicionar ao glossário",
                    "Informe a substituição.\n\n"
                    "Só as regras de limpeza podem ter substituição vazia — elas "
                    "existem justamente para remover o trecho.",
                    parent=pop,
                )
                return

            if not add_to_glossary(orig, new, rule_type=rule_type):
                messagebox.showerror(
                    "Adicionar ao glossário",
                    "Não foi possível gravar a regra no glossário.\n\n"
                    "Nada foi adicionado.",
                    parent=pop,
                )
                return

            self.reload_glossary(show_feedback=False)
            self.show_message("Entrada adicionada ao glossário")
            pop.destroy()

        ctk.CTkButton(pop, text="Adicionar", command=confirm).pack(pady=14)

    def focus_search(self, _event=None):
        """`Ctrl+L`: busca da LISTA (ROADMAP 19, item 2).

        Era o que `Ctrl+F` fazia. A troca nao e questao de gosto: `Ctrl+F` e o
        gesto universal de "procurar no que estou lendo", e quem revisa um
        comentario longo de livro o aperta para achar uma palavra NO TEXTO. Caindo
        no campo da lista, ele fazia a coisa mais destrutiva possivel — a busca da
        lista TROCA a pagina, e o revisor perdia o lugar em que estava.
        """
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
        return "break"

    def focus_editor_find(self, _event=None):
        """`Ctrl+F`: busca dentro da traducao aberta."""
        self.editor_find_entry.focus_set()
        self.editor_find_entry.select_range(0, tk.END)
        return "break"

    def go_back_shortcut(self, _event=None):
        self.go_back()
        return "break"

    def save_shortcut(self, _event=None):
        self.save_changes(False)
        return "break"

    def verify_shortcut(self, _event=None):
        self.save_changes(False, mark_verified=True)
        return "break"

    def mark_and_next_shortcut(self, _event=None):
        self.mark_and_next()
        return "break"

    def on_note_edited(self):
        """Nota diferente da carregada e sujeira — e o rodape passa a dize-lo.

        `autosave_draft=False` porque o rascunho e do TEXTO da traducao: agendar
        uma gravacao dele porque alguem digitou na nota gravaria o mesmo texto de
        sempre num arquivo de rascunho, a cada tecla.

        A comparacao e com `current["reviewer_note"]`, que `load_item` acerta
        ANTES de povoar o campo — e o que impede a propria carga da linha de
        marcar a janela como suja.
        """
        if self.state.loading or not self.current["id"]:
            return
        mudou = self.reviewer_note_text.get().strip() != (
            self.current.get("reviewer_note") or ""
        ).strip()
        if mudou and not self.state.dirty:
            self.set_dirty(True, autosave_draft=False)

    def save_note_shortcut(self, _event=None):
        self.save_changes(False)
        return "break"

    def zoom_with_wheel(self, event):
        """Ctrl+roda muda o tamanho da fonte dos dois textos (ROADMAP 22.11).

        O sinal de `event.delta` e o que diz a direcao; o valor absoluto (120 por
        entalhe no Windows) nao entra na conta, porque um entalhe da roda tem de
        valer um ponto — o mesmo que um clique em "A+". Multiplicar pelos 120
        levaria a fonte de 12 a 24 pt num giro.
        """
        self.adjust_font(1 if getattr(event, "delta", 0) > 0 else -1)
        return "break"

    def previous_shortcut(self, _event=None):
        self.navigate(-1)
        return "break"

    def next_shortcut(self, _event=None):
        self.navigate(1)
        return "break"

    def next_quality_warning_shortcut(self, _event=None):
        self.go_to_next_quality_warning()
        return "break"

    def close_editor(self):
        self.save_changes()
        self.save_editor_settings()
        self.unregister_glossary_callback()
        # O rastreador guarda os callbacks numa lista de CLASSE: sem tirar o
        # desta janela, cada abrir-e-fechar deixaria mais um la, e todos seriam
        # chamados na proxima troca de tema (garantia F18).
        try:
            ctk.AppearanceModeTracker.remove(self.apply_theme_colors)
        except Exception:  # pragma: no cover - versao sem o registrador
            pass
        self.win.destroy()


def open_translation_editor(app):
    """Abre a janela de edicao de traducoes.

    Continua sendo uma funcao porque e assim que o resto do programa chama, e
    porque quem abre a janela nao tem o que fazer com a instancia.
    """
    return TranslationEditor(app)
