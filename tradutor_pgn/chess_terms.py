"""Termos cuja traducao errada da para reconhecer pelo texto (ROADMAP 16.1).

O `Termos-suspeitos.txt` diz, linha a linha: "se o ORIGINAL tem o termo X e a
TRADUCAO tem a forma Y, isto e provavelmente erro de terminologia". Nada aqui
corrige nada — o resultado e um aviso de qualidade, e o aviso e o que leva o
revisor ate a linha.

**Por que isto e um arquivo, e nao uma lista em Python.** E terminologia, que e
o material que este projeto passou uma revisao inteira curando (secao 14) — e
curar exige poder ler, contar e editar. Fica ao lado do dicionario-semente, com
as mesmas regras: vem com o programa, e substituido na atualizacao, e um defeito
nele nao pode impedir o programa de funcionar.

O modulo nao importa Tk nem banco. Le arquivo, e por isso a leitura tem cache: a
avaliacao de qualidade roda a cada gravacao de traducao, e reler um arquivo por
comentario seria pagar I/O num caminho que o worker percorre milhares de vezes.
"""

import ast
import os
import re
from functools import lru_cache

from .glossario import report_glossary_error, scope_matches


SUSPECT_TERMS_FILENAME = "Termos-suspeitos.txt"


def _default_terms_path():
    """A lista vive ao lado do MODULO, e nao do executavel.

    Mesma distincao do dicionario-semente: o que vem com o programa sai de
    `__file__`, o que e do usuario sai de `sys.argv[0]`. Sob PyInstaller isso a
    poe dentro de `_internal`, junto do pacote.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), SUSPECT_TERMS_FILENAME)


def _parse_terms(text):
    """`termos = [(termo, suspeito, escopo), ...]` -> lista de tuplas de tres.

    Por `ast.literal_eval`, nunca `exec` — a mesma regra do `Substituicoes.txt`.
    Uma entrada malformada e descartada em silencio; o arquivo inteiro
    malformado levanta, e quem chama reporta.
    """
    modulo = ast.parse(text)
    for node in ast.walk(modulo):
        if isinstance(node, ast.Assign):
            nomes = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "termos" in nomes:
                bruto = ast.literal_eval(node.value)
                break
    else:
        raise ValueError("arquivo de termos suspeitos sem a lista `termos`")

    entradas = []
    for item in bruto or []:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            continue
        termo, suspeito, escopo = (str(campo or "").strip() for campo in item)
        if not termo or not suspeito:
            continue
        entradas.append((termo, suspeito, escopo))
    return entradas


@lru_cache(maxsize=4)
def _load_terms(path):
    """Entradas compiladas, com cache: o arquivo nao muda durante a execucao.

    Devolve uma tupla de `(termo, suspeito, escopo, regex_do_termo,
    regex_do_suspeito)`. Os regex sao compilados UMA vez aqui, e nao a cada
    avaliacao: sao 25 padroes, e a avaliacao roda por comentario gravado.

    Os dois lados toleram flexao, e cada um do seu jeito — a diferenca nao e
    estilo, e o que cada lingua faz com a palavra:

    - **O termo em ingles aceita um `s` final** (`\\bsquares?\\b`), e so ele. Um
      `\\w*` generico pareceria mais completo e traria um erro caro: `tempo`
      passaria a casar "temporary", que e palavra comum e nao tem nada a ver com
      o tempo do xadrez. As formas que interessam sao os plurais — "squares",
      "files", "pieces", "checks" —, e um `s` as cobre.
    - **A forma suspeita em portugues aceita sufixo livre** (`\\w*`), porque ela
      chega flexionada em genero e numero: "quadrado" aparece como "quadrados",
      "fixado" como "fixada". Aqui o risco inverso nao existe: a forma so e
      consultada quando o termo ingles ja apareceu no original.
    """
    if not path or not os.path.exists(path):
        return ()
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            entradas = _parse_terms(handle.read())
    except (OSError, SyntaxError, ValueError) as exc:
        # A lista e conveniencia: sem ela o programa perde um aviso, nao uma
        # funcao. Mas o arquivo vem com o programa, entao o defeito e nosso e
        # nao pode ser silencioso (garantia S5).
        report_glossary_error(f"Erro ao ler os termos suspeitos: {exc}")
        return ()

    compiladas = []
    for termo, suspeito, escopo in entradas:
        compiladas.append(
            (
                termo,
                suspeito,
                escopo,
                re.compile(r"\b" + re.escape(termo) + r"s?\b", re.IGNORECASE),
                re.compile(r"\b" + re.escape(suspeito) + r"\w*", re.IGNORECASE),
            )
        )
    return tuple(compiladas)


def load_suspect_terms(path=None):
    """As entradas cruas `(termo, suspeito, escopo)`. Para testes e inspecao."""
    return [(t, s, e) for t, s, e, _rt, _rs in _load_terms(path or _default_terms_path())]


def suspect_terms_for(source_language=None, target_language=None, path=None):
    """As entradas que valem para este par de idiomas (garantia S11).

    **Sem idioma de destino, nenhuma entrada vale.** Uma lista de termos e sobre
    um par: aplicar a lista de portugues a uma traducao para o italiano acusaria
    erro onde nao ha. E o oposto do que `scope_matches` faz sozinho — la o
    destino ausente nao filtra nada, o que e o certo para o glossario (mantem de
    pe quem nao passa idioma) e errado aqui.
    """
    if not target_language:
        return []
    return [
        (termo, suspeito, re_termo, re_suspeito)
        for termo, suspeito, escopo, re_termo, re_suspeito in _load_terms(
            path or _default_terms_path()
        )
        if scope_matches(escopo, source_language, target_language)
    ]


def find_suspect_terms(original, translated, source_language=None, target_language=None, path=None):
    """Os pares `(termo, forma_suspeita)` que aparecem dos dois lados.

    O termo tem de estar no ORIGINAL e a forma suspeita na TRADUCAO. As duas
    condicoes juntas sao o que faz o aviso ser especifico: "ritmo" numa traducao
    e palavra comum, e so vira suspeita quando o original diz "tempo".
    """
    if not original or not translated:
        return []
    achados = []
    for termo, suspeito, re_termo, re_suspeito in suspect_terms_for(
        source_language, target_language, path
    ):
        if re_termo.search(original) and re_suspeito.search(translated):
            achados.append((termo, suspeito))
    return achados
