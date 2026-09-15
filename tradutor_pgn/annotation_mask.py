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

# O par de nomes de uma citacao de partida — `V. Kramnik-D. Navara` em
# `V. Kramnik-D. Navara, Prague 2008` (garantia X4, ROADMAP 28.3). A maquina
# traduzia o NOME em ~2,5 % das citacoes do banco de desenvolvimento (E. Can ->
# "E. Pode", K. Lie -> "K. Mentira", J. Hammer -> "J. Martelo"); a sede fica
# de fora da mascara de proposito — o revisor a traduz (Berna, Praga) em um
# terco das citacoes verificadas, e "correspondence" e "correspondencia".
#
# Inicial (uma letra, ou duas: `Ju.`), ponto, espaco opcional, sobrenome com
# uma particula opcional ("N. De Firmian", "L. Van Wely"); o hifen entre os
# dois; e a virgula logo depois, que e o que separa uma citacao de qualquer
# outro par com hifen. Medido no banco de desenvolvimento: casa as 821
# citacoes, e 2 pares fora do formato `Sede ANO` que tambem sao citacoes.
_PLAYER_NAME = r"[A-Z][a-z]?\. ?(?:[A-Z][\w'-]*(?: [A-Z][\w'-]*)?)"
PLAYER_PAIR_RE = re.compile(rf"(?<![\w.])(?:{_PLAYER_NAME})-(?:{_PLAYER_NAME})(?=,)")


def mask_annotations(text, player_names=True):
    """Troca cada anotacao `[%...]` — e cada par de nomes de citacao — por um
    sentinela numerado.

    Devolve `(texto_mascarado, tokens)`, onde `tokens[i]` e o texto original do
    sentinela `i`, byte a byte. A lista vazia significa "nada a proteger" — e o
    caso de quase todo comentario de livro, que segue pelo caminho de sempre.

    Os nomes entram na MESMA lista e voltam pela mesma restauracao verificada
    (X4 e X1 pelo mesmo mecanismo): um sentinela de nome que a maquina
    engoliu conta como falha do comentario, e nao como nome errado gravado.
    `player_names=False` desliga so essa metade — e para quem mede.
    """
    tokens = []

    def _swap(match):
        tokens.append(match.group(0))
        return _SENTINEL_TEMPLATE.format(n=len(tokens) - 1)

    mascarado = COMMAND_TAG_RE.sub(_swap, text or "")
    if player_names:
        mascarado = PLAYER_PAIR_RE.sub(_swap, mascarado)
    return mascarado, tokens



def has_player_name_tokens(tokens):
    """Ha algum par de nomes entre os `tokens` de uma mascara?

    E o que decide se uma restauracao que falhou merece a segunda tentativa
    sem a mascara de nomes (X4): so faz sentido quando havia nome mascarado.
    """
    return any(not COMMAND_TAG_RE.fullmatch(token) for token in tokens)


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
