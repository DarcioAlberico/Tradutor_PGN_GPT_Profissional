"""Consertos deterministicos da PROSA traduzida, guiados pelo original.

Sao as correcoes que a medicao da secao 28 do ROADMAP mostrou serem
mecanicas: o original prova a forma, a traducao da maquina a perdeu, e nenhum
julgamento e necessario para repor. Cada funcao e pura, recebe o original e a
traducao e devolve `(texto, quantidade)`, no mesmo desenho de
`chess_notation.fix_move_notation`; o worker as chama depois das regras
automaticas e antes de gravar, para que banco e PGN recebam o mesmo texto.

A primeira delas e a preposicao final (ROADMAP 28.4). Um comentario de livro
de xadrez e muitas vezes um fragmento — "White is clearly better after" — e o
lance vem no movetext, fora do comentario. A maquina traduz o fragmento como
frase inteira e devolve "as brancas estao claramente melhores depois": o
"depois" adverbial no lugar do "depois de" preposicional. Medido nas 6.500
traducoes do banco de desenvolvimento: 680 originais terminam em `after`; a
maquina devolveu "depois" sem "de" em 532, e `'' -> 'de'` e a substituicao
mais frequente da revisao (532). Contra as decisoes humanas, 124 de 125
linhas marcadas foram editadas. As outras preposicoes finais (`with`, `by`,
`to`, `for`, `than`, `due to`) saem certas — a tabela tem uma linha porque a
medicao encontrou uma.
"""
import re

from .chess_notation import CAPTURE_MARKS, PIECE_LETTERS

# (idioma de origem, palavra final do original, palavra final da traducao,
#  complemento). A traducao que ja termina em "depois de" nao casa o segundo
# padrao — "de" e a ultima palavra — e fica como esta.
_TRAILING_PREPOSITIONS = {
    "pt": (
        ("en", "after", "depois", "de"),
    ),
}

# Adverbios que fazem `after` ser adverbial, e nao preposicional:
# "doesn't lose immediately after" termina a frase, e "depois" esta certo.
# `right after` e `just after` NAO entram — sao "logo depois de", que precisa
# do "de" do mesmo jeito. Medido: 2 ocorrencias em 680, e a lista e curta de
# proposito (garantia P7).
_ADVERBS_BEFORE = ("immediately", "shortly", "soon", "long")

_TRAILING_PUNCTUATION = ".,;:!?)\"'"


def _last_words(text):
    """As duas ultimas palavras (minusculas) e a pontuacao que sobra no fim."""
    stripped = text.rstrip()
    trailing = ""
    while stripped and stripped[-1] in _TRAILING_PUNCTUATION:
        trailing = stripped[-1] + trailing
        stripped = stripped[:-1].rstrip()
    words = re.findall(r"[\w'-]+", stripped)
    return [w.lower() for w in words[-2:]], stripped, trailing


def _table_for(source_language, target_language):
    entries = _TRAILING_PREPOSITIONS.get(target_language or "", ())
    # Origem nao declarada ("Detectar") nao desliga a regra: o que a decide e a
    # palavra final do original, e "after" so e ingles.
    return [e for e in entries if not source_language or e[0] == source_language]


def fix_trailing_preposition(original, translation, source_language, target_language):
    """Repoe a preposicao que a maquina perdeu no fim de um fragmento.

    So age quando o ORIGINAL termina na palavra da tabela (pontuacao a parte),
    sem um dos adverbios de `_ADVERBS_BEFORE` logo antes dela, e a TRADUCAO
    termina na palavra correspondente sem o complemento. Nunca inventa: se a
    traducao terminou em "apos" ou ja em "depois de", nao ha o que repor. A
    pontuacao final da traducao e preservada depois do complemento.

    Devolve `(texto, 1)` quando corrigiu e `(texto, 0)` quando nao.
    """
    if not original or not translation:
        return translation, 0

    orig_words, _stripped, _trailing = _last_words(original)
    if not orig_words:
        return translation, 0
    orig_last = orig_words[-1]
    orig_prev = orig_words[-2] if len(orig_words) > 1 else ""

    for _source, orig_ending, trans_ending, complement in _table_for(
        source_language, target_language
    ):
        if orig_last != orig_ending or orig_prev in _ADVERBS_BEFORE:
            continue
        trans_words, stripped, trailing = _last_words(translation)
        if not trans_words or trans_words[-1] != trans_ending:
            continue
        return f"{stripped} {complement}{trailing}", 1

    return translation, 0


# ============================================================================
# As normalizacoes de 28.2 (camada 2): espaco do lance, hifen peca-casa e o
# espaco de largura zero. Todas guiadas pelo original (garantia P5).
# ============================================================================

# O corpo de um lance, sem as bordas de `chess_notation._move_pattern`: aqui
# ele precisa casar COLADO a um numero (`12h5`) ou a uma reticencia (`...Cd3`),
# que e justamente o defeito. As letras sao as de todos os idiomas, porque a
# traducao ja veio com a letra do destino.
_LETTERS = "|".join(
    sorted(
        {re.escape(letra) for letras in PIECE_LETTERS.values() for letra in letras.values()},
        key=len,
        reverse=True,
    )
)
_CAPTURE = f"[{re.escape(CAPTURE_MARKS)}]"
_MOVE_BODY = (
    rf"(?:(?:{_LETTERS})?[a-h]?[1-8]?{_CAPTURE}?[a-h][1-8](?:=(?:{_LETTERS}))?"
    r"|[0O]-[0O](?:-[0O])?)[+#]?"
)
_CAPTURE_TO_X = {ord(marca): "x" for marca in CAPTURE_MARKS}
_LEADING_LETTER = re.compile(rf"^(?:{_LETTERS})")

# No ORIGINAL, as formas com espaco: `10... d5`, `... Nd3`, `12 h5`.
_ORIG_NUM_ELLIPSIS = re.compile(rf"(?<!\w)(\d+)\.\.\. ({_MOVE_BODY})(?!\w)")
_ORIG_ELLIPSIS = re.compile(rf"(?<![\d.])\.\.\. ({_MOVE_BODY})(?!\w)")
# A mesma forma quando ha um espaco tambem ANTES da reticencia ("playing ... b5"):
# a maquina cola dos dois lados ("jogar...b5"), e o original prova os dois.
_ORIG_ELLIPSIS_SPACED = re.compile(rf"(?<= )\.\.\. ({_MOVE_BODY})(?!\w)")
_ORIG_NUM_SPACE = re.compile(rf"(?<!\w)(\d+) ({_MOVE_BODY})(?!\w)")
# Na TRADUCAO, as mesmas formas coladas.
_TRANS_NUM_ELLIPSIS = re.compile(rf"(?<!\w)(\d+)\.\.\.({_MOVE_BODY})(?!\w)")
_TRANS_ELLIPSIS = re.compile(rf"(?<![\d.])\.\.\.({_MOVE_BODY})(?!\w)")
_TRANS_NUM_GLUED = re.compile(rf"(?<!\w)(\d+)({_MOVE_BODY})(?!\w)")


def _move_anchor(body):
    """A parte do lance que nao muda de idioma: sem a letra da peca, com a
    captura normalizada em `x` e sem `+`/`#` — a mesma ideia de
    `chess_notation._anchor`, sobre o corpo cru."""
    corpo = _LEADING_LETTER.sub("", body).translate(_CAPTURE_TO_X)
    return corpo.rstrip("+#")


def fix_move_spacing(original, translation):
    """Repoe o espaco entre a reticencia (ou o numero) e o lance.

    A maquina devolve `10...d5`, `...Cd3` e `12h5` onde o original tinha
    `10... d5`, `... Nd3` e `12 h5`. Medido no banco de desenvolvimento: 40 +
    66 + 5 ocorrencias na saida da maquina e **zero** no original — a forma
    colada nunca vem do livro. Ainda assim a regra so age quando o original
    tem a forma com espaco para o MESMO lance (numero e ancora): e o que a
    torna incapaz de inventar um espaco (garantia P5).

    Devolve `(texto, quantos)`.
    """
    if not original or not translation:
        return translation, 0

    com_numero = {
        (numero, _move_anchor(lance))
        for numero, lance in _ORIG_NUM_ELLIPSIS.findall(original)
    }
    sem_numero = {_move_anchor(lance) for lance in _ORIG_ELLIPSIS.findall(original)}
    espaco_antes = {
        _move_anchor(lance) for lance in _ORIG_ELLIPSIS_SPACED.findall(original)
    }
    numero_espaco = {
        (numero, _move_anchor(lance))
        for numero, lance in _ORIG_NUM_SPACE.findall(original)
    }
    if not (com_numero or sem_numero or numero_espaco):
        return translation, 0

    quantos = 0

    def com_numero_sub(m):
        nonlocal quantos
        if (m.group(1), _move_anchor(m.group(2))) in com_numero:
            quantos += 1
            return f"{m.group(1)}... {m.group(2)}"
        return m.group(0)

    def sem_numero_sub(m):
        nonlocal quantos
        ancora = _move_anchor(m.group(1))
        if ancora not in sem_numero:
            return m.group(0)
        quantos += 1
        colada_antes = m.start() > 0 and m.string[m.start() - 1].isalnum()
        antes = " " if colada_antes and ancora in espaco_antes else ""
        return f"{antes}... {m.group(1)}"

    def numero_colado_sub(m):
        nonlocal quantos
        if (m.group(1), _move_anchor(m.group(2))) in numero_espaco:
            quantos += 1
            return f"{m.group(1)} {m.group(2)}"
        return m.group(0)

    texto = _TRANS_NUM_ELLIPSIS.sub(com_numero_sub, translation)
    texto = _TRANS_ELLIPSIS.sub(sem_numero_sub, texto)
    texto = _TRANS_NUM_GLUED.sub(numero_colado_sub, texto)
    return texto, quantos


# O hifen do ingles (`d5-knight`, `e7-pawn`) sobrevive a traducao como
# `cavalo-d5`, `peao-e7`. A forma portuguesa e "cavalo de d5". So a CASA
# completa: `e-pawn` (so a coluna) aparece 3 vezes na saida da maquina e a
# revisao nao a resolveu com "de" — fica de fora.
_PIECE_WORDS = {
    "pt": r"cavalos?|bispos?|torres?|damas?|reis?|pe[ãa]o|pe[õo]es",
}
_ORIG_SQUARE_PIECE = re.compile(
    r"(?<!\w)([a-h][1-8])-(?:knights?|bishops?|rooks?|queens?|kings?|pawns?)(?!\w)",
    re.I,
)


def fix_piece_square_hyphen(original, translation, target_language):
    """`cavalo-d5` -> `cavalo de d5`, so onde o original tem `d5-knight`.

    Medido: 413 `casa-peca` no original, 131 `peca-casa` na saida da maquina,
    e a revisao trocou 124 delas por "peca de casa". Nenhum original portugues
    usa o hifen, e a tabela e por destino: fora do `pt` nao ha regra.
    """
    if not original or not translation:
        return translation, 0
    pecas = _PIECE_WORDS.get(target_language or "")
    if pecas is None:
        return translation, 0
    casas = {casa.lower() for casa in _ORIG_SQUARE_PIECE.findall(original)}
    if not casas:
        return translation, 0

    padrao = re.compile(rf"(?<!\w)({pecas})-([a-h][1-8])(?!\w)", re.I)
    quantos = 0

    def sub(m):
        nonlocal quantos
        if m.group(2).lower() in casas:
            quantos += 1
            return f"{m.group(1)} de {m.group(2)}"
        return m.group(0)

    return padrao.sub(sub, translation), quantos


_ZERO_WIDTH = "​"


def strip_zero_width_spaces(original, translation):
    """Tira o `U+200B` que a API insere.

    Medido: 68 na saida da maquina, zero no original. So age quando o original
    nao tem nenhum — se tiver, e conteudo, nao lixo. Os espacos que sobram
    colados sao colapsados.
    """
    if not translation or _ZERO_WIDTH not in translation:
        return translation, 0
    if original and _ZERO_WIDTH in original:
        return translation, 0
    quantos = translation.count(_ZERO_WIDTH)
    texto = translation.replace(_ZERO_WIDTH, "")
    texto = re.sub(r" {2,}", " ", texto).strip()
    return texto, quantos


def normalize_prose(original, translation, source_language, target_language):
    """Todas as normalizacoes, na ordem em que o pipeline as aplica.

    E a funcao que o worker chama e que a passada sobre o banco (garantia P6)
    injeta, com a mesma forma de `fix_move_notation`: `(texto, quantos)`. O
    espaco de largura zero vai primeiro — os outros regexes nao o enxergam
    como fronteira de palavra.
    """
    texto, total = strip_zero_width_spaces(original, translation)
    texto, n = fix_move_spacing(original, texto)
    total += n
    texto, n = fix_piece_square_hyphen(original, texto, target_language)
    total += n
    texto, n = fix_trailing_preposition(original, texto, source_language, target_language)
    total += n
    return texto, total
