"""O prompt e o lote JSON dos modelos de linguagem (ROADMAP 28.7).

Puro — sem rede, sem Tk, sem banco. Nasceu no piloto (`ferramentas/piloto_llm.py`),
que agora importa daqui: o provedor de produto e o piloto falam com o modelo
pelo MESMO texto, e uma mudanca de prompt e medida pelo piloto antes de valer
na traducao de verdade.

O desenho que o piloto mediu e o provedor herda (ROADMAP 28.7):

- bloco de sistema FIXO (regras duras, letras das pecas, terminologia da
  semente) e um segundo bloco com as regras `automatic` do par — os dois com
  `cache_control` no provedor Anthropic; nada de data ou contador neles, para o
  prefixo ser identico em toda requisicao (36 % da entrada veio do cache no
  piloto);
- lote como JSON numerado — cada item com `id` e `texto`, cada resposta com
  `id` e `traducao` —, e a validacao exige CADA id exatamente uma vez (B5):
  um id a menos, a mais ou repetido e um lote desalinhado;
- as sugestoes do glossario que CASAM no texto do lote vao na mensagem, ate
  `MAX_SUGESTOES_POR_LOTE`: as 5.622 inteiras seriam dezenas de milhares de
  tokens por requisicao.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from .app_config import language_label
from .chess_notation import PIECE_LETTERS
from .glossario import find_glossary_matches, load_seed_entries

MAX_SUGESTOES_POR_LOTE = 80

# O esquema da resposta: o que `output_config.format` (Anthropic) exige e o que
# `validar_lote` confere para os provedores que so prometem "um JSON".
ESQUEMA_DO_LOTE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "traducao": {"type": "string"},
                },
                "required": ["id", "traducao"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["itens"],
    "additionalProperties": False,
}


def terminologia_da_semente(destino: str) -> list[str]:
    """`termo -> traducao` da semente para o destino: a terminologia de xadrez."""
    pares = []
    for entrada in load_seed_entries():
        orig, new = entrada[0], entrada[1]
        escopo = entrada[4] if len(entrada) > 4 else ""
        if escopo == destino:
            pares.append(f"{orig} -> {new}")
    return pares


def _tabela_de_pecas(origem: str, destino: str) -> str:
    """A linha das letras das pecas, ou a regra de nao mexer quando o par nao
    esta em `PIECE_LETTERS` — a mesma fonte de `fix_move_notation`."""
    letras = PIECE_LETTERS.get(destino)
    if not letras or origem not in PIECE_LETTERS:
        return (
            "- Lances: mantenha a notacao EXATAMENTE como esta no original, "
            "letras das pecas inclusive.\n"
        )
    de = PIECE_LETTERS[origem]
    tabela = ", ".join(f"{de[peca]} -> {letras[peca]}" for peca in ("K", "Q", "R", "B", "N"))
    return (
        "- Lances: troque SO a letra da peca, pela tabela abaixo; nunca mude casa, "
        "numero do lance, 'x', '+', '#', '=', nem simbolos de avaliacao "
        "(!, ?, !?, ?!, +-, -+, =, etc.). Nao acrescente nem remova lances.\n"
        f"- Letras das pecas ({origem} -> {destino}): {tabela}. Lances de peao e "
        "roques (O-O, O-O-O) ficam como estao.\n"
    )


def prompt_de_sistema(origem: str, destino: str) -> str:
    """O bloco FIXO do sistema: regras duras, letras das pecas e terminologia.

    Fixo de proposito — nada de data, nada de contador — para o prefixo ser
    identico em toda requisicao e o cache de prompt casar. `origem` vazia e
    "detectar": o modelo le o idioma do texto, como o `gtx` com `sl=auto`.
    """
    nome_origem = language_label(origem, unknown="o idioma do original")
    nome_destino = language_label(destino)
    termos = "\n".join(terminologia_da_semente(destino))
    if origem and destino == "pt":
        brancas = (
            "- Brancas e pretas: 'White' -> 'as brancas', 'Black' -> 'as pretas', em "
            "minusculas no meio da frase, com o verbo no plural.\n"
        )
    else:
        brancas = (
            "- Brancas e pretas: use a forma corrente dos livros de xadrez em "
            f"{nome_destino}, em minusculas no meio da frase.\n"
        )
    texto = (
        f"Voce traduz comentarios de partidas de xadrez de livros, de {nome_origem} "
        f"para {nome_destino}, para um tradutor profissional revisar. Cada item e um "
        "comentario que aparece entre chaves num arquivo PGN; `antes` e `depois`, "
        "quando vierem, sao o lance anterior e o seguinte no arquivo, e servem so "
        "de contexto.\n\n"
        "Regras que nao podem ser quebradas:\n"
        "- Traduza cada item sozinho e devolva exatamente um resultado por id, em "
        "JSON, no formato {\"itens\": [{\"id\": n, \"traducao\": \"...\"}]}.\n"
        + _tabela_de_pecas(origem, destino)
        + "- Os marcadores ⟦n⟧ sao trechos protegidos: devolva cada um exatamente "
        "uma vez, no lugar correspondente, sem alterar o numero.\n"
        "- Um fragmento que termina em preposicao ou conjuncao no original "
        "(\"after\", \"with\") continua fragmento na traducao, com a preposicao "
        "equivalente no fim (\"depois de\", \"com\"); nao complete a frase.\n"
        + brancas
        + "- Nomes de jogadores, torneios e cidades ficam como estao.\n"
        "- Sem notas, sem explicacoes, sem aspas a mais: so a traducao.\n"
    )
    if termos:
        texto += f"\nTerminologia de xadrez em {nome_destino} (use estas formas):\n{termos}\n"
    return texto


def regras_automaticas_em_texto(regras: Iterable[Sequence[Any]]) -> str:
    """As regras `automatic` do par como bloco de sistema, uma por linha."""
    linhas = [f"{regra[0]} -> {regra[1]}" for regra in regras]
    if not linhas:
        return ""
    return (
        "Glossario do usuario (regras obrigatorias, aplicadas tambem depois da "
        "sua resposta):\n" + "\n".join(linhas) + "\n"
    )


def sugestoes_para_o_lote(
    textos: Iterable[str],
    interativas: Iterable[Sequence[Any]],
    limite: int = MAX_SUGESTOES_POR_LOTE,
) -> list[str]:
    """As regras `suggestion` que casam no texto do lote, ate `limite`."""
    texto = "\n".join(textos)
    escolhidas: list[str] = []
    vistos: set[tuple[str, str]] = set()
    for regra in interativas:
        orig, new = regra[0], regra[1]
        if (orig, new) in vistos or not orig or "@casa@" in orig:
            continue
        if find_glossary_matches(texto, orig):
            escolhidas.append(f"{orig} -> {new}")
            vistos.add((orig, new))
            if len(escolhidas) >= limite:
                break
    return escolhidas


def mensagem_do_lote(itens: Sequence[dict[str, Any]], sugestoes: Sequence[str]) -> str:
    """A mensagem do usuario: os itens em JSON e as sugestoes que casam.

    Cada item e `{"id", "texto"}` e, opcionalmente, `"antes"`/`"depois"` (o
    contexto de lances que o piloto tem e o worker nao)."""
    corpo = {
        "itens": [
            {
                "id": item["id"],
                "antes": item.get("antes", ""),
                "texto": item["texto"],
                "depois": item.get("depois", ""),
            }
            for item in itens
        ]
    }
    texto = "Traduza os itens abaixo.\n\n" + json.dumps(corpo, ensure_ascii=False, indent=0)
    if sugestoes:
        texto += (
            "\n\nSugestoes do glossario que casam neste lote (prefira estas formas "
            "quando o sentido for o mesmo):\n" + "\n".join(sugestoes)
        )
    return texto


def validar_lote(
    resposta_json: str, ids_esperados: Iterable[int]
) -> tuple[dict[int, str], list[str]]:
    """`(por_id, problemas)`: cada id exatamente uma vez, ou o lote e desalinhado (B5)."""
    por_id: dict[int, str] = {}
    problemas: list[str] = []
    try:
        itens = json.loads(resposta_json)["itens"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {}, [f"json invalido: {exc}"]
    if not isinstance(itens, list):
        return {}, ["json invalido: 'itens' nao e uma lista"]
    vistos: Counter[int] = Counter()
    for item in itens:
        try:
            cid = int(item["id"])
            vistos[cid] += 1
            por_id[cid] = str(item["traducao"])
        except (KeyError, TypeError, ValueError):
            problemas.append(f"item sem id/traducao: {item!r}"[:120])
    esperados = set(ids_esperados)
    for cid in sorted(esperados - set(vistos)):
        problemas.append(f"id {cid} faltou")
    for cid, quantas in sorted(vistos.items()):
        if quantas > 1:
            problemas.append(f"id {cid} veio {quantas} vezes")
        if cid not in esperados:
            problemas.append(f"id {cid} nao era deste lote")
            por_id.pop(cid, None)
    return por_id, problemas
