"""Avisos de qualidade de uma traducao — inclusive os que sabem que e xadrez.

As cinco primeiras heuristicas sao genericas de traducao (vazia, igual ao
original, chaves perdidas, curta demais, longa demais) e eram as unicas que
existiam. A medicao que motivou a secao 16 do ROADMAP dimensionou o buraco no
banco de desenvolvimento (6.500 traducoes en -> pt, reais, de livro):

    linhas com erro de terminologia enxadristica     321  (4,9%)
    linhas que o `quality_warning` marcava            11
    intersecao entre os dois conjuntos                 0

As heuristicas de xadrez fecham isso. Todas comparam ORIGINAL com TRADUCAO, e a
materia-prima delas ja existia no programa — as ancoras de lance de
`chess_notation`, o padrao de anotacao de `annotation_mask`, a terminologia que o
glossario ja conhecia como sugestao.

**Nenhuma heuristica aqui grava nada.** O resultado e uma lista de frases, e quem
decide o que fazer com ela e o editor (que a mostra) e a coluna materializada
`quality_warning` (que a resume num bit, garantia R6).

O modulo continua sem Tk e sem banco.
"""

from collections import Counter
from difflib import SequenceMatcher
import re

from .annotation_mask import COMMAND_TAG_RE
from .chess_notation import move_anchors
from .chess_terms import find_suspect_terms


# Sobe quando as heuristicas mudam de veredito. `quality_warning` e
# materializada, e o backfill so preenche `NULL`: sem esta versao, acrescentar
# uma regra deixaria as linhas ja avaliadas com o veredito velho e a garantia R6
# passaria a ser violada exatamente pela melhoria (ROADMAP 16.2).
#
# A versao 1 e a primeira que existe. Um banco gravado antes dela nao tem versao
# nenhuma, e "ausente" e tratado como desatualizado — que e a verdade: aquelas
# linhas foram avaliadas pelas cinco genericas.
#
# **Mexer em qualquer heuristica deste arquivo obriga a subir este numero**, e o
# `Termos-suspeitos.txt` conta como heuristica.
QUALITY_HEURISTICS_VERSION = 1

QUALITY_REPORT_HEADERS = [
    "id",
    "target_language",
    "status",
    "warning_count",
    "warnings",
    "original_comment",
    "translated_comment",
]

# Comprimento minimo do original para as heuristicas de PROPORCAO valerem. Abaixo
# disto a razao entre tamanhos nao diz nada: um original de 6 caracteres tem toda
# traducao "muito longa". A quase-igualdade usa o mesmo piso, e ali ele foi
# medido — o unico falso positivo dela no banco de desenvolvimento era uma linha
# de 35 caracteres (`, A. Jongsma-C. Lutz, Tilburg 1993,`), em que ser quase
# identica e o resultado CERTO: nao ha o que traduzir numa citacao.
PROPORTION_MINIMUM_LENGTH = 40

# Acima desta semelhanca, uma traducao que nao e igual ao original tambem nao e
# uma traducao — o tradutor desistiu e devolveu o texto quase como recebeu.
#
# A conta e feita em DOIS passos, e o barato existe para o caro poder ser
# exato. `quick_ratio` compara multiconjuntos de caracteres: e rapido e nunca
# subestima, entao serve de filtro. `ratio` compara SEQUENCIAS, o que custa
# O(n*m) e por isso so roda no que o filtro deixou passar.
#
# Nao e otimizacao premature: o `quick_ratio` sozinho da falso positivo em
# citacao. Medido no banco de desenvolvimento, a unica linha que ele marcava era
# `is about equal, Z. Hracek-G. Jones, Porto Carras 2011.` -> `é quase igual,
# Z. Hracek-G. Jones, Porto Carras 2011.` — quick 0,953, e a prosa FOI traduzida;
# os 40 caracteres de citacao e que dominam a contagem de caracteres. O `ratio`
# ve o bloco comum e responde 0,822, rejeitando. Com o par, a heuristica marca
# zero linha nas 6.500 e continua armada para o caso de verdade.
NEAR_EQUALITY_RATIO = 0.95

# Quantos itens uma lista de aviso nomeia antes de virar contagem. O aviso existe
# para levar o revisor ate o lugar; tres exemplos fazem isso, e trinta viram uma
# frase que ninguem le.
WARNING_SAMPLE_LIMIT = 3

# NAG do padrao PGN: `$1`, `$14`. Vive no movetext, que a traducao nunca toca,
# mas aparece em comentario copiado de software de analise.
NAG_RE = re.compile(r"\$\d+")

# Simbolos de avaliacao de MAIS DE UM caractere, e a razao de nao haver `!` e `?`
# sozinhos e que eles sao pontuacao: "Is this sound?" -> "Isso e som?" tem um `?`
# de cada lado por acidente, e uma frase que ganha ou perde um ponto de
# interrogacao na traducao e prosa normal, nao avaliacao perdida.
EVAL_SYMBOLS = (
    "!!", "??", "!?", "?!",
    "+-", "-+", "+/-", "-/+", "+/=", "=/+", "+/", "=/",
    "∞", "⩲", "⩱", "±", "∓", "⨀",
)
_EVAL_SYMBOLS_BY_LENGTH = tuple(sorted(EVAL_SYMBOLS, key=len, reverse=True))

# O sinal de que `errors='replace'` engoliu bytes na leitura. As garantias E4 e
# G2 impedem isso em arquivo novo; isto acha o legado que ja esta no banco.
REPLACEMENT_CHAR = "�"

# O separador de lote. No texto GRAVADO ele e evidencia de um desalinhamento que
# a contagem de partes nao pegou (garantia B2).
BATCH_SEPARATOR_MARK = "|||"


def eval_symbols(text):
    """Multiconjunto dos simbolos de avaliacao de `text`.

    Conta do mais longo para o mais curto, apagando o que ja contou: sem isso um
    `+/-` seria contado tambem como `+/`, e todo texto com avaliacao pareceria
    ter simbolos a mais.
    """
    restante = text or ""
    achados = Counter()
    for simbolo in _EVAL_SYMBOLS_BY_LENGTH:
        quantos = restante.count(simbolo)
        if quantos:
            achados[simbolo] += quantos
            restante = restante.replace(simbolo, " ")
    return achados


def format_anchor(anchor):
    """A ancora de lance como se le: `('xd4', '', '+')` -> `xd4+`."""
    corpo, igual, fim = anchor
    return f"{corpo}{igual}{fim}"


def _sample(items):
    """Nomeia os primeiros e conta o resto."""
    itens = list(items)
    nomeados = ", ".join(itens[:WARNING_SAMPLE_LIMIT])
    if len(itens) > WARNING_SAMPLE_LIMIT:
        return f"{nomeados} (e mais {len(itens) - WARNING_SAMPLE_LIMIT})"
    return nomeados


def _missing_and_extra(esquerda, direita):
    """`(o que sumiu, o que apareceu)` entre dois multiconjuntos."""
    return esquerda - direita, direita - esquerda


def _move_warnings(original, translated):
    """Garantia Q1, primeira metade: lance perdido ou inventado.

    Compara as ANCORAS — a parte do lance que e igual em todo idioma —, entao o
    aviso nao precisa saber de que lingua o comentario veio e vale tambem para as
    linhas legadas. Um `Bxf7+` no original que nao esta na traducao e o tradutor
    tendo comido um lance, e e o erro mais grave que um comentario de xadrez pode
    ter: o texto continua lendo bem e diz outra coisa.

    Medido no banco de desenvolvimento: 6 comentarios em 6.500. Quatro sao o
    tradutor colando o numero no lance (`20 Na2` -> `20Ca2`), que deixa de ser
    notacao valida; um e um lance que sumiu mesmo; e um e um falso positivo cuja
    causa esta no ORIGINAL (`Ng5+which`, sem espaco, faz o `+` nao entrar na
    ancora do original e entrar na da traducao).
    """
    avisos = []
    faltando, sobrando = _missing_and_extra(
        move_anchors(original), move_anchors(translated)
    )
    if faltando:
        avisos.append(
            "Lance do original que não aparece na tradução: "
            + _sample(format_anchor(a) for a in sorted(faltando.elements()))
        )
    if sobrando:
        avisos.append(
            "Lance na tradução que não está no original: "
            + _sample(format_anchor(a) for a in sorted(sobrando.elements()))
        )
    return avisos


def _annotation_warnings(original, translated):
    """Garantia Q1, segunda metade: anotacao `[%...]` rompida.

    Compara byte a byte, porque e assim que a garantia X1 promete que elas
    atravessam a traducao. Enquanto a mascara da secao 13 nao existia, este aviso
    era a rede; depois dela, e a prova de que a mascara funcionou — e a unica
    forma de descobrir as anotacoes que execucoes ANTERIORES ja corromperam e
    deixaram no banco.
    """
    avisos = []
    faltando, sobrando = _missing_and_extra(
        Counter(COMMAND_TAG_RE.findall(original or "")),
        Counter(COMMAND_TAG_RE.findall(translated or "")),
    )
    if faltando:
        avisos.append(
            "Anotação do original ausente ou alterada na tradução: "
            + _sample(sorted(faltando.elements()))
        )
    if sobrando:
        avisos.append(
            "Anotação na tradução que não está no original: "
            + _sample(sorted(sobrando.elements()))
        )
    return avisos


def _symbol_warnings(original, translated):
    """NAGs `$n` e simbolos de avaliacao: o multiconjunto tem de bater."""
    avisos = []
    for nome, esquerda, direita in (
        ("NAG", Counter(NAG_RE.findall(original or "")), Counter(NAG_RE.findall(translated or ""))),
        ("Símbolo de avaliação", eval_symbols(original), eval_symbols(translated)),
    ):
        faltando, sobrando = _missing_and_extra(esquerda, direita)
        if faltando:
            avisos.append(
                f"{nome} do original ausente na tradução: "
                + _sample(sorted(faltando.elements()))
            )
        if sobrando:
            avisos.append(
                f"{nome} na tradução que não está no original: "
                + _sample(sorted(sobrando.elements()))
            )
    return avisos


def _terminology_warnings(original, translated, source_language, target_language):
    """Terminologia suspeita, com escopo de idioma (ROADMAP 16.1, item 8).

    E a heuristica que fecha a medicao que abriu a secao 16: as 321 linhas com
    erro enxadristico que o filtro "Avisos QA" nao mostrava. O conhecimento ja
    estava no glossario do usuario, preso no tipo `suggestion` — aplicado um a
    um, a mao, por quem abrisse a linha certa. Isto e o que faz a linha certa
    aparecer.
    """
    return [
        f"Terminologia: '{termo}' no original e '{suspeito}' na tradução."
        for termo, suspeito in find_suspect_terms(
            original, translated, source_language, target_language
        )
    ]


def evaluate_translation_quality(
    original,
    translated,
    source_language=None,
    target_language=None,
):
    """As frases de aviso desta traducao, ou uma lista vazia.

    O par de idiomas e opcional e so a terminologia o usa — as demais heuristicas
    comparam original com traducao e nao dependem de lingua. Sem destino
    declarado, a terminologia nao roda: aplicar a lista de portugues a uma
    traducao para o italiano acusaria erro onde nao ha.

    Quem chama TEM de passar o par quando o conhece. A coluna materializada e a
    exibicao usam esta mesma funcao, e se uma passar o par e a outra nao, a
    contagem de avisos divergiria do que a tela mostra — que e exatamente o que a
    garantia R6 proibe.
    """
    original = (original or "").strip()
    translated = (translated or "").strip()
    warnings = []

    if not translated:
        warnings.append("Tradução vazia.")
        return warnings

    if original and translated.casefold() == original.casefold():
        warnings.append("Tradução igual ao original.")

    if "{" in translated or "}" in translated:
        warnings.append("Contém chaves { } que podem interferir no comentário PGN.")

    original_len = len(original)
    translated_len = len(translated)
    if original_len >= PROPORTION_MINIMUM_LENGTH:
        if translated_len < original_len * 0.35:
            warnings.append("Tradução muito curta em relação ao original.")
        elif translated_len > original_len * 2.5:
            warnings.append("Tradução muito longa em relação ao original.")

        # So aqui, e nao antes: "quase identica" pressupoe que havia prosa para
        # traduzir. Numa citacao curta a semelhanca alta e o resultado certo.
        if translated.casefold() != original.casefold():
            comparador = SequenceMatcher(None, original, translated)
            if (
                comparador.quick_ratio() >= NEAR_EQUALITY_RATIO
                and comparador.ratio() >= NEAR_EQUALITY_RATIO
            ):
                warnings.append("Tradução quase idêntica ao original.")

    warnings.extend(_move_warnings(original, translated))
    warnings.extend(_annotation_warnings(original, translated))
    warnings.extend(_symbol_warnings(original, translated))

    if REPLACEMENT_CHAR in original or REPLACEMENT_CHAR in translated:
        warnings.append(
            "Contém U+FFFD: bytes perdidos na leitura do arquivo de origem."
        )

    if BATCH_SEPARATOR_MARK in translated:
        warnings.append(
            "Contém o separador de lote (|||): sinal de desalinhamento na tradução."
        )

    warnings.extend(
        _terminology_warnings(original, translated, source_language, target_language)
    )

    return warnings


# Posicoes do par de idiomas nas linhas do editor. Elas vem no FIM da tupla de
# proposito — o editor le as sete primeiras por posicao em varios pontos —, e a
# leitura e tolerante: uma linha de sete campos continua sendo avaliada, so sem a
# parte de terminologia.
ROW_SOURCE_LANGUAGE_INDEX = 7
ROW_TARGET_LANGUAGE_INDEX = 8
# O bit materializado, acrescentado depois do par pelo mesmo motivo. Ele e o que o
# marcador da lista le (ROADMAP 19, item 4), e nao existe em toda linha: as tuplas
# montadas a mao nos testes e as de sete campos param antes dele.
ROW_QUALITY_WARNING_INDEX = 9


def row_quality_flag(row):
    """O bit `quality_warning` da linha, ou `None` se ela nao o traz.

    `None` e diferente de zero: zero e "avaliada, sem aviso" e `None` e "esta
    tupla nao carrega a coluna". Quem mostra o marcador precisa distinguir os dois
    — um marcador de "sem aviso" numa linha que ninguem avaliou seria uma
    afirmacao inventada.
    """
    if len(row) > ROW_QUALITY_WARNING_INDEX:
        return row[ROW_QUALITY_WARNING_INDEX]
    return None


def row_language_pair(row):
    """`(origem, destino)` da linha, ou `(None, None)` se ela nao os traz."""
    if len(row) > ROW_TARGET_LANGUAGE_INDEX:
        return row[ROW_SOURCE_LANGUAGE_INDEX], row[ROW_TARGET_LANGUAGE_INDEX]
    return None, None


def row_quality_warnings(row):
    if len(row) < 3:
        return []
    source_language, target_language = row_language_pair(row)
    return evaluate_translation_quality(
        row[1], row[2], source_language, target_language
    )


def row_has_quality_warning(row):
    return bool(row_quality_warnings(row))


def filter_quality_warning_rows(rows):
    return [row for row in rows if row_has_quality_warning(row)]


def build_quality_report_rows(rows, target_language=""):
    report_rows = []
    for row in rows:
        if len(row) < 4:
            continue

        warnings = row_quality_warnings(row)
        if not warnings:
            continue

        status = "verified" if row[3] == 1 else "pending"
        report_rows.append((
            row[0],
            target_language,
            status,
            len(warnings),
            " | ".join(warnings),
            row[1] or "",
            row[2] or "",
        ))

    return report_rows


def summarize_quality_warnings(rows):
    warning_counts = Counter()
    summary = {
        "total_rows": 0,
        "warning_rows": 0,
        "pending_warning_rows": 0,
        "verified_warning_rows": 0,
        "warning_total": 0,
        "warning_counts": {},
    }

    for row in rows:
        if len(row) < 3:
            continue

        summary["total_rows"] += 1
        warnings = row_quality_warnings(row)
        if not warnings:
            continue

        summary["warning_rows"] += 1
        summary["warning_total"] += len(warnings)
        warning_counts.update(warnings)

        if len(row) > 3 and row[3] == 1:
            summary["verified_warning_rows"] += 1
        else:
            summary["pending_warning_rows"] += 1

    summary["warning_counts"] = dict(
        sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return summary


def find_first_quality_warning(rows, start_index=0):
    for index, row in enumerate(rows[start_index:], start=start_index):
        warnings = row_quality_warnings(row)
        if warnings:
            return index, row, warnings

    return None
