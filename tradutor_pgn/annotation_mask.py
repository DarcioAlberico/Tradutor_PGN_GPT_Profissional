"""Protege as anotacoes de maquina durante a traducao (garantia X1).

Dentro de um comentario PGN vivem coisas que nao sao prosa: `[%clk 0:05:30]`,
`[%eval +0.35]`, `[%cal Ra1h8]`, `[%csl Gd4]` — as anotacoes de relogio,
avaliacao, setas e casas coloridas do Lichess e do ChessBase. O pipeline nao
tinha o conceito de "token que nao se traduz": tudo ia cru para a API, que pode
traduzir `eval`, quebrar um colchete ou reformatar o payload (ROADMAP 13.3).

A protecao e mascara com restauracao VERIFICADA: cada anotacao vira um
sentinela antes do envio e volta byte a byte depois — e a volta e conferida.
Se algum sentinela sumiu, duplicou ou apareceu sem ter ido (vazamento de outro
comentario do mesmo lote), a restauracao acusa e o comentario e tratado como
falha de traducao (garantias T2/T3): melhor ficar no idioma original do que
gravar uma anotacao corrompida com cara de certa.

O sentinela e `⟦n⟧`: um par de colchetes matematicos que nao e palavra de
lingua nenhuma — nao ha o que traduzir nele — com o indice preso entre os
dois. A leitura tolera espacos que o tradutor insira em volta do numero;
qualquer mutacao alem disso e exatamente o que a verificacao existe para
pegar.

O modulo nao importa Tk nem banco: e funcao pura, como `chess_notation`, e da
para testa-lo sem abrir janela nem criar arquivo.
"""

import re


# O mesmo padrao de `chess_notation.COMMAND_TAG_RE`, mantido la e importado
# aqui: os dois modulos precisam concordar sobre o que e uma anotacao, e duas
# copias divergindo seria a classe de defeito que o item 3.6 do ROADMAP
# corrigiu no glossario.
from .chess_notation import COMMAND_TAG_RE

_SENTINEL_TEMPLATE = "⟦{n}⟧"
_SENTINEL_RE = re.compile(r"⟦\s*(\d+)\s*⟧")


def mask_annotations(text):
    """Troca cada anotacao `[%...]` por um sentinela numerado.

    Devolve `(texto_mascarado, tokens)`, onde `tokens[i]` e o texto original do
    sentinela `i`, byte a byte. A lista vazia significa "nada a proteger" — e o
    caso de quase todo comentario de livro, que segue pelo caminho de sempre.
    """
    tokens = []

    def _swap(match):
        tokens.append(match.group(0))
        return _SENTINEL_TEMPLATE.format(n=len(tokens) - 1)

    return COMMAND_TAG_RE.sub(_swap, text or ""), tokens


def restore_annotations(text, tokens):
    """Devolve os sentinelas de `text` aos textos originais de `tokens`.

    Retorna `(texto_restaurado, ok)`. `ok` e falso quando a traducao nao
    devolveu cada sentinela exatamente uma vez — sumiu, duplicou, ou trouxe um
    indice que este comentario nunca teve (um sentinela do vizinho de lote, o
    rastro de um separador comido). Nesses casos o texto restaurado nao deve
    ser gravado; quem chama decide o destino, e o destino certo e contar como
    falha (T2/T3).

    Um texto sem mascara (`tokens` vazio) so passa se tambem nao contiver
    sentinela nenhum: um `⟦0⟧` num comentario que nao mascarou nada e vazamento,
    nao ruido.
    """
    if not tokens:
        return text, _SENTINEL_RE.search(text or "") is None

    vistos = []

    def _swap(match):
        indice = int(match.group(1))
        vistos.append(indice)
        if 0 <= indice < len(tokens):
            return tokens[indice]
        return match.group(0)

    restaurado = _SENTINEL_RE.sub(_swap, text or "")
    ok = sorted(vistos) == list(range(len(tokens)))
    return restaurado, ok
