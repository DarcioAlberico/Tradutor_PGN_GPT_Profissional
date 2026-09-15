"""O que a revisao trocou, contado: os pares `antes -> depois` mais frequentes.

Existe porque o ranking "o que o revisor de fato trocou" existia como script de
medicao e nao existia no programa (ROADMAP 28.5, item 3). No banco de dev ele
mostrou 94 vezes `o jogo -> a partida`, 90 `troca -> qualidade`, 87
`movimentos -> lances` — trocas que o revisor digitou uma a uma, e das quais
metade nem tinha regra no glossario. Depois de trezentas linhas de um livro
novo, esta lista e o que diz quais regras aquele livro pede.

O modulo e puro: recebe eventos do historico e entradas do glossario, devolve
listas. Quem le o banco e `database.fetch_file_edit_events`; quem mostra e
`repeated_edits_window`.
"""

import re
from collections import Counter
from difflib import SequenceMatcher

from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    apply_substitution,
    glossary_entry_pair,
    glossary_entry_type,
)


# Palavra (com hifen interno, para `peão-b2` ser um token) ou um sinal de
# pontuacao. A mesma tokenizacao do script de medicao: o diff e por token, e
# nao por caractere, porque a regra do glossario e por texto inteiro — um diff
# por caractere devolveria `jog -> partid`, que nao e regra de nada.
TOKEN_RE = re.compile(r"\w+(?:-\w+)*|[^\w\s]")

# Quantas vezes uma troca precisa aparecer para ser "repetida". Uma vez e uma
# correcao; duas e um padrao que vai voltar na proxima linha.
DEFAULT_MIN_COUNT = 2
DEFAULT_LIMIT = 40

RULE_STATUS_NONE = "sem regra"
RULE_STATUS_LABELS = {
    GLOSSARY_RULE_AUTOMATIC: "automática",
    GLOSSARY_RULE_SUGGESTION: "sugestão",
    GLOSSARY_RULE_CLEANUP: "limpeza",
}
# Ordem de preferencia quando mais de uma regra cobre a troca: a automatica e a
# que ja faz o trabalho sozinha, e e isso que o usuario quer saber primeiro.
_RULE_TYPE_RANK = {
    GLOSSARY_RULE_AUTOMATIC: 0,
    GLOSSARY_RULE_SUGGESTION: 1,
    GLOSSARY_RULE_CLEANUP: 2,
}


def token_replacements(previous, new):
    """Os trechos que uma edicao TROCOU, como pares `(antes, depois)`.

    So os blocos `replace` do diff por token. Insercoes puras (`'' -> 'de'`, a
    troca mais frequente da revisao) e remocoes puras ficam de fora de
    proposito: uma regra do glossario precisa de um texto para casar, e "onde
    faltava um `de`" nao e um texto — e o P7, que resolveu isso no pipeline.
    """
    antes = TOKEN_RE.findall(previous or "")
    depois = TOKEN_RE.findall(new or "")
    pares = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, antes, depois, autojunk=False
    ).get_opcodes():
        if tag != "replace":
            continue
        pares.append((" ".join(antes[i1:i2]), " ".join(depois[j1:j2])))
    return pares


def count_repeated_edits(events, min_count=DEFAULT_MIN_COUNT, limit=DEFAULT_LIMIT):
    """Os pares mais frequentes de uma lista de `(comment_id, antes, depois)`.

    Cada item devolvido tem `old`, `new`, `count` (ocorrencias), `lines`
    (comentarios distintos em que a troca aparece) e `example_id` (o primeiro
    comentario em que apareceu — para abrir e ver o contexto). Ordenado por
    ocorrencias, depois por linhas, depois pelo texto, para a lista ser a mesma
    a cada abertura.

    `count` e `lines` sao numeros diferentes e os dois interessam: `o -> a` 24
    vezes em 19 linhas e uma troca que se repete DENTRO da linha, e isso pesa
    menos do que 24 linhas distintas.
    """
    ocorrencias = Counter()
    linhas = Counter()
    exemplo = {}
    for comment_id, previous, new in events:
        vistos = set()
        for par in token_replacements(previous, new):
            ocorrencias[par] += 1
            if par not in vistos:
                vistos.add(par)
                linhas[par] += 1
                exemplo.setdefault(par, comment_id)

    itens = [
        {
            "old": old,
            "new": new,
            "count": count,
            "lines": linhas[(old, new)],
            "example_id": exemplo[(old, new)],
        }
        for (old, new), count in ocorrencias.items()
        if count >= min_count
    ]
    itens.sort(key=lambda item: (-item["count"], -item["lines"], item["old"], item["new"]))
    if limit is not None:
        itens = itens[:limit]
    return itens


def glossary_rule_index(entries):
    """`orig.casefold() -> [(orig, new, tipo)]`, para achar a regra de uma troca.

    Indexado pela caixa dobrada porque e assim que a regra casa: um `orig`
    minusculo casa qualquer caixa (`_compiled_glossary_pattern`), e a troca
    `Brancas -> brancas` e coberta por uma regra escrita `brancas`. A conferencia
    de verdade — a regra PRODUZ o `depois`? — e feita com a substituicao real,
    em `rule_status`; o indice so evita percorrer 6 mil entradas por troca.
    """
    indice = {}
    for entry in entries:
        orig, new = glossary_entry_pair(entry)
        if not orig:
            continue
        indice.setdefault(orig.casefold(), []).append(
            (orig, new, glossary_entry_type(entry))
        )
    return indice


def rule_status(index, old, new):
    """Ja existe regra para esta troca? `(tipo, o_que_ela_produz)` ou `None`.

    Usa `apply_substitution` — a substituicao do pipeline — sobre o texto
    `old`, e nao uma comparacao de strings: e o criterio da garantia S9 (o
    anuncio USA o criterio da aplicacao). Uma regra cujo `orig` casa mas produz
    outra coisa (`troca -> permuta` quando o revisor escreve `qualidade`) volta
    com o tipo E o texto que ela produz, para a lista dizer "sugestao (produz
    'permuta')" em vez de "ja tem regra".

    Uma regra que casa e NAO muda o texto tambem volta, com `produz == old`:
    e o caso real de `Brancas -> brancas` no glossario do usuario — a
    substituicao devolve a caixa do texto casado (`case_adjusted_replacement`),
    entao a regra recapitaliza o que ela mesma acabou de baixar e nunca produz
    nada. Dizer "sem regra" ali esconderia que a regra existe e e inerte.

    `None` e "nenhuma regra casa neste texto".
    """
    candidatas = index.get((old or "").casefold(), [])
    cobre = []
    dispara = []
    inerte = []
    for orig, replacement, rule_type in candidatas:
        produzido = apply_substitution(old, orig, replacement)
        if produzido == new:
            destino = cobre
        elif produzido == old:
            destino = inerte
        else:
            destino = dispara
        destino.append((_RULE_TYPE_RANK.get(rule_type, 9), rule_type, produzido))
    for grupo in (cobre, dispara, inerte):
        if grupo:
            grupo.sort()
            _rank, rule_type, produzido = grupo[0]
            return rule_type, produzido
    return None


def format_rule_status(status, old, new):
    """O texto da coluna "regra".

    "automática" / "sugestão" / "limpeza" quando a regra produz exatamente o que
    o revisor escreveu; "sugestão (produz 'As pretas')" quando ela dispara e
    produz outra coisa; "sugestão (não altera o texto)" quando casa e nao muda
    nada; "sem regra" quando nenhuma casa.
    """
    if status is None:
        return RULE_STATUS_NONE
    rule_type, produzido = status
    rotulo = RULE_STATUS_LABELS.get(rule_type, rule_type)
    if produzido == new:
        return rotulo
    if produzido == old:
        return f"{rotulo} (não altera o texto)"
    return f"{rotulo} (produz {produzido!r})"


def annotate_with_glossary(items, entries):
    """Acrescenta `rule_type`, `rule_produces` e `rule_label` a cada par."""
    indice = glossary_rule_index(entries)
    anotados = []
    for item in items:
        status = rule_status(indice, item["old"], item["new"])
        anotado = dict(item)
        anotado["rule_type"] = None if status is None else status[0]
        anotado["rule_produces"] = None if status is None else status[1]
        anotado["rule_label"] = format_rule_status(status, item["old"], item["new"])
        anotados.append(anotado)
    return anotados


def repeated_edits_report(events, entries, min_count=DEFAULT_MIN_COUNT, limit=DEFAULT_LIMIT):
    """Eventos + glossario -> a lista pronta para a janela."""
    return annotate_with_glossary(
        count_repeated_edits(events, min_count=min_count, limit=limit), entries
    )
