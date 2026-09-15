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
