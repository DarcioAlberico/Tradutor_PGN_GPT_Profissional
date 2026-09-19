"""A posicao (FEN) de cada comentario de um PGN — ROADMAP 28.8, garantia O5.

O revisor decide "qual bispo", "que coluna", "troca ou qualidade" olhando a
posicao — ate aqui em outro programa. Este modulo calcula a FEN do tabuleiro
no ponto em que cada comentario aparece, para o editor desenha-la.

**`python-chess` e opcional, e por licenca.** O pacote e GPL-3.0-ou-posterior
e o programa nao muda de licenca por causa de um quadro de conforto: ele e
importado aqui dentro, na hora, e `chess_available()` diz se existe. Sem ele
nada quebra — o worker pula o passo e o editor nao mostra o quadro. O `.spec`
do PyInstaller o exclui de proposito; quem roda do fonte e o tem instalado ve
o tabuleiro.

**Alinhamento por texto, em sequencia, ressincronizado por partida.** O
programa le os comentarios com uma expressao regular (`pgn_utils`), e o
`python-chess` os le com um parser de lances; os dois concordam no texto, e e
por ele que a FEN chega ao comentario certo. Dentro de uma partida os
comentarios sao casados na ordem, com busca para a frente: um lance ilegal faz
o parser pular o resto da variante, e os comentarios dali ficam sem FEN — mas
o casamento retoma no proximo texto igual, e uma FEN NUNCA vai parar num
comentario de texto diferente. Medido no PGN real do usuario (99 partidas,
7.487 comentarios): 7.487 de 7.487 casados.

**Sem `board.copy()`.** Copiar o tabuleiro ao entrar em cada variante custava
10,16 s no mesmo arquivo; desfazer o lance da linha principal ao entrar na
variante e refaze-lo ao sair custa 1,54 s. A ordem de visita e a ordem em que
o `python-chess` exporta — e a ordem do arquivo: lance principal e o comentario
dele, depois cada variante inteira, depois a continuacao da linha principal.

**O PGN do usuario usa so `\\r` como fim de linha** (exportacao ChessBase).
`read_pgn_text` preserva isso (G1); o leitor por linhas do `python-chess` ve
um arquivo de uma linha e devolve zero partidas SEM erro. O parser recebe uma
copia normalizada; o arquivo em disco nao muda.
"""

import io
import re

from .pgn_utils import flatten_comment

# Ate onde a busca para a frente vai, dentro da partida. Um pulo de variante
# perde algumas dezenas de comentarios, nao centenas; e um limite pequeno
# impede que um "Diagram" repetido la na frente case com o errado.
FORWARD_SEARCH_LIMIT = 60

_LINE_ENDINGS_RE = re.compile(r"\r\n?")


def chess_available():
    """O `python-chess` esta instalado? So ele desenha o tabuleiro."""
    try:
        import chess  # noqa: F401
        import chess.pgn  # noqa: F401
    except ImportError:
        return False
    return True


def normalize_line_endings(content):
    """`\\r` e `\\r\\n` viram `\\n`: e o que o leitor por linhas do parser entende."""
    return _LINE_ENDINGS_RE.sub("\n", content)


def _walk_game(game, emit):
    """Chama `emit(texto, fen)` para cada comentario, na ordem do arquivo.

    `emit` recebe o texto CRU do comentario (como o parser o deu) e a FEN da
    posicao em que ele aparece. Um comentario antes do primeiro lance de uma
    variante (`starting_comment`) recebe a posicao ANTES desse lance.

    Sem copia do tabuleiro: ao entrar numa variante o lance principal e
    desfeito, e refeito ao sair. Recursao so nas variantes; a linha principal
    e um laco, entao a profundidade de recursao e a profundidade de
    aninhamento das variantes, e nao o numero de lances.
    """
    board = game.board()
    if game.comment:
        emit(game.comment, board.fen())
    _walk_line(game, board, emit)


def _walk_line(node, board, emit):
    """Segue a linha a partir de `node` (ja no tabuleiro) ate o fim, deixando
    os lances dela empilhados: quem chamou sabe a profundidade em que
    comecou e desfaz ate ela. E o detalhe que decide a correcao: uma variante
    tem VARIOS lances, e desfazer um so ao sair dela deixava o tabuleiro
    dentro da variante para o resto da partida — o `push` seguinte falhava
    por lance impossivel, e o erro, engolido, deixava a partida sem FEN dali
    em diante (692 de 7.487 na primeira medicao)."""
    while node.variations:
        main = node.variations[0]
        board.push(main.move)
        if main.comment:
            emit(main.comment, board.fen())
        if len(node.variations) > 1:
            board.pop()
            profundidade = len(board.move_stack)
            for alt in node.variations[1:]:
                if alt.starting_comment:
                    emit(alt.starting_comment, board.fen())
                board.push(alt.move)
                if alt.comment:
                    emit(alt.comment, board.fen())
                _walk_line(alt, board, emit)
                while len(board.move_stack) > profundidade:
                    board.pop()
            board.push(main.move)
        node = main


def parsed_comments_by_game(content, should_cancel=None):
    """`[[(texto achatado, fen), ...], ...]`, uma lista por partida.

    Devolve `None` quando o `python-chess` nao esta instalado. Erros de parse
    de uma partida nao derrubam o arquivo: o `python-chess` os acumula em
    `game.errors` e segue — o que fica sem lance fica sem FEN.
    """
    if not chess_available():
        return None
    import chess.pgn

    fonte = io.StringIO(normalize_line_endings(content))
    partidas = []
    while True:
        if should_cancel is not None and should_cancel():
            return None
        game = chess.pgn.read_game(fonte)
        if game is None:
            break
        comentarios = []

        def emit(texto, fen, _lista=comentarios):
            achatado = flatten_comment(texto)
            if achatado:
                _lista.append((achatado, fen))

        # Sem `try` em volta: um lance que o `python-chess` aceitou ao ler e
        # empurravel de volta, e um erro aqui seria erro DESTE codigo — melhor
        # subir do que deixar a partida sem FEN em silencio, que foi
        # exatamente como o defeito da profundidade se escondeu.
        _walk_game(game, emit)
        partidas.append(comentarios)
    return partidas


def align_fens(occurrences, parsed_by_game):
    """A FEN de cada ocorrencia da extracao, ou `None`.

    `occurrences` e a lista `(indice, partida, lance, texto)` de
    `extract_comments_from_content`; `parsed_by_game` e o que
    `parsed_comments_by_game` devolveu. Devolve uma lista paralela a
    `occurrences`.

    Por partida, em sequencia, tres tentativas na ordem: o texto do parser
    no ponteiro e IGUAL (recebe a FEN, o ponteiro avanca); o texto do parser
    no ponteiro CONTEM o da extracao — o parser juntou dois `{}` seguidos do
    mesmo lance num texto so, e os dois estao na mesma posicao (recebe a FEN,
    o ponteiro NAO avanca, para o vizinho casar com o mesmo pedaco); ou o
    proximo texto igual ate `FORWARD_SEARCH_LIMIT` a frente (o ponteiro pula
    para depois dele). Nada casou: fica sem FEN e o ponteiro nao avanca. A
    ordem importa: um pedaco curto de um comentario juntado (":", "Instead")
    tambem existe sozinho mais adiante, e a busca para a frente o casaria la
    — medido, isso deixava 245 comentarios sem FEN atras do ponteiro.

    A partida e a da extracao (contagem de `[Event`), e o parser conta do
    mesmo jeito; quando os totais divergem — um PGN que o parser leu em menos
    partidas —, o casamento cai para a sequencia global, que continua nunca
    dando FEN a texto diferente, so perde a ressincronizacao.
    """
    if parsed_by_game is None:
        return [None] * len(occurrences)

    total_partidas = max((partida for _i, partida, _l, _t in occurrences), default=0)
    por_partida = len(parsed_by_game) == total_partidas
    if por_partida:
        listas = parsed_by_game
    else:
        listas = [[item for partida in parsed_by_game for item in partida]]

    ponteiros = [0] * len(listas)
    fens = []
    for _indice, partida, _lance, texto in occurrences:
        alvo = partida - 1 if por_partida else 0
        if alvo >= len(listas):
            fens.append(None)
            continue
        lista = listas[alvo]
        j = ponteiros[alvo]
        fen = None
        if j < len(lista) and lista[j][0] == texto:
            fen = lista[j][1]
            ponteiros[alvo] = j + 1
        elif j < len(lista) and texto in lista[j][0]:
            # O parser juntou dois `{}` seguidos do mesmo lance num texto so;
            # os dois estao na MESMA posicao, e o ponteiro fica para o vizinho
            # casar com o mesmo pedaco. Conferido ANTES da busca para a frente:
            # um pedaco curto (":", "Instead") tambem existe sozinho mais
            # adiante, e a busca o casaria la, pulando dezenas de comentarios.
            fen = lista[j][1]
        else:
            for k in range(j + 1, min(len(lista), j + FORWARD_SEARCH_LIMIT)):
                if lista[k][0] == texto:
                    fen = lista[k][1]
                    ponteiros[alvo] = k + 1
                    break
        fens.append(fen)
    return fens


def compute_comment_fens(content, occurrences, should_cancel=None):
    """A FEN de cada ocorrencia de um PGN ja lido, ou `None` para todas.

    `None` em tudo quer dizer "sem `python-chess`" ou "cancelado"; uma lista
    com alguns `None` quer dizer que o parser nao alcancou aqueles comentarios.
    """
    parsed = parsed_comments_by_game(content, should_cancel)
    if parsed is None:
        return [None] * len(occurrences)
    return align_fens(occurrences, parsed)


# ---------------------------------------------------------------- o desenho
#
# O quadro do editor nao precisa do `python-chess`: uma FEN gravada e texto, e
# ler as oito fileiras dela e uma dezena de linhas. Assim o `.exe` sem o pacote
# desenha as FENs que um banco vindo do fonte ja tem.

PIECE_GLYPHS = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}


def fen_board_rows(fen):
    """As oito fileiras da FEN, da oitava a primeira, como listas de 8 pecas
    (letra ou `""`). `None` para uma FEN que nao tem oito fileiras de oito."""
    if not fen:
        return None
    campo = fen.split()[0]
    fileiras = campo.split("/")
    if len(fileiras) != 8:
        return None
    tabuleiro = []
    for fileira in fileiras:
        casas = []
        for c in fileira:
            if c.isdigit():
                casas.extend([""] * int(c))
            elif c in PIECE_GLYPHS:
                casas.append(c)
            else:
                return None
        if len(casas) != 8:
            return None
        tabuleiro.append(casas)
    return tabuleiro


def side_to_move(fen):
    """"Brancas jogam" / "Pretas jogam", ou `""` quando a FEN nao diz."""
    partes = (fen or "").split()
    if len(partes) < 2:
        return ""
    return {"w": "Brancas jogam", "b": "Pretas jogam"}.get(partes[1], "")
