import re
from difflib import SequenceMatcher


# A unidade do diff: uma palavra, ou um pedaco de espaco/pontuacao. Diferenca por
# CARACTERE marcaria "torre"/"Torre" como um `T` trocado no meio de uma palavra
# inteira pintada de igual, e o que o revisor precisa ver e a palavra que mudou.
_DIFF_TOKEN_RE = re.compile(r"\w+|\W+", re.UNICODE)


def _tokens_with_spans(text):
    return [(m.group(0), m.start(), m.end()) for m in _DIFF_TOKEN_RE.finditer(text or "")]


def diff_spans(before, after):
    """`(faixas_no_antes, faixas_no_depois)` do que muda entre os dois textos.

    E o diff que faltava na previa de "Aplicar todas" (ROADMAP 19, item 5): dois
    blocos de texto lado a lado nao mostram QUAIS das 80 substituicoes aconteceram,
    e conferi-los a olho e o mesmo que nao conferir.

    **O ROADMAP dizia que as faixas "ja sao calculadas", e isso era meia verdade.**
    `apply_glossary_pair_with_cursor` calcula as posicoes de cada regra no texto
    daquela passagem, e as descarta guardando so o cursor — mas o problema maior e
    que elas nao serviriam: a segunda regra aplicada desloca as faixas da primeira,
    e a previa mostra o texto DEPOIS de todas. Comparar os dois textos prontos
    responde a pergunta certa e nao depende de quantas passagens houve.

    O diff e por token, e nao por caractere, e as faixas devolvidas sao offsets de
    caractere em cada lado — que e o que o Tk precisa para pintar.
    """
    tokens_antes = _tokens_with_spans(before)
    tokens_depois = _tokens_with_spans(after)
    matcher = SequenceMatcher(
        None,
        [t[0] for t in tokens_antes],
        [t[0] for t in tokens_depois],
        autojunk=False,
    )

    faixas_antes = []
    faixas_depois = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            faixas_antes.append((tokens_antes[i1][1], tokens_antes[i2 - 1][2]))
        if j2 > j1:
            faixas_depois.append((tokens_depois[j1][1], tokens_depois[j2 - 1][2]))
    return faixas_antes, faixas_depois


def find_text_ranges(text, query, case_sensitive=False):
    text = text or ""
    query = query or ""
    if not query:
        return []

    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    ranges = []
    start = 0
    step = max(1, len(query))

    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        ranges.append((index, index + len(query)))
        start = index + step

    return ranges


def replace_text_range(text, start, end, replacement):
    text = text or ""
    replacement = replacement or ""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return text[:start] + replacement + text[end:]


def replace_all_text(text, query, replacement, case_sensitive=False):
    ranges = find_text_ranges(text, query, case_sensitive=case_sensitive)
    if not ranges:
        return text or "", 0

    updated = text or ""
    for start, end in reversed(ranges):
        updated = replace_text_range(updated, start, end, replacement)
    return updated, len(ranges)
