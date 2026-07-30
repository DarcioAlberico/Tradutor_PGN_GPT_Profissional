"""Corrige as letras dos lances de uma traducao, usando o comentario original.

O problema e das letras, e ele nao tem solucao dentro do glossario. A notacao
algebrica usa uma letra por peca, e as letras **colidem entre idiomas**:

    peca      en   pt   es   fr   it   de   ru
    Rei       K    R    R    R    R    K    Кр
    Dama      Q    D    D    D    D    D    Ф
    Torre     R    T    T    T    T    T    Л
    Bispo     B    B    A    F    A    L    С
    Cavalo    N    C    C    C    C    S    К

O `R` do ingles e Torre; o `R` do portugues e Rei. Uma dupla de regras
`K -> R` e `R -> T` aplicada em sequencia destroi a informacao: depois da
primeira, os `R` que vieram de `K` sao indistinguiveis dos que ja eram `R`, e a
segunda transforma os dois em `T`. **Nao e a ordem que esta errada — e a
sequencia.** Feito numa passagem so, `Kf1` vira `Rf1` e `Rf1` vira `Tf1` sem
ambiguidade nenhuma.

Isso resolve metade. A outra metade e que o tradutor automatico **e
inconstante**: as vezes traduz `Kf1` para `Rf1`, as vezes deixa `Kf1`, as vezes
troca por outra letra qualquer. Nao da para saber, olhando so a traducao, se o
`Rf1` que esta la e um Rei ja traduzido ou uma Torre que ficou para tras.

Quem sabe e o **comentario original**. Ele esta no idioma de origem, e o idioma
de origem o usuario declarou (ver a secao 3.3 da SPEC). Entao a correcao nao
adivinha: ela le os lances do original, converte cada um para o idioma de
destino, e usa isso para dizer o que cada lance da traducao tinha de ser.

**A ancora e a parte do lance que NAO muda de idioma.** Casa, captura, xeque,
desempate — `f1`, `xe4+`, `bd7` — sao iguais em todas as linguas; so a letra da
peca muda. Entao `Kf1` no original e `?f1` na traducao sao o mesmo lance, e o
`?` e o que se corrige.

O modulo nao importa Tk nem banco: e funcao pura, e da para testa-lo sem abrir
janela nem criar arquivo.
"""

import re
from collections import Counter


# As letras de cada peca, por idioma. As chaves sao os identificadores canonicos
# (os do ingles), e nao ha nada de especial neles alem de serem os do padrao PGN.
#
# O rei russo e `Кр`, e nao `К`: em russo Rei (Король) e Cavalo (Конь) comecam
# com a mesma letra, e a notacao usa duas letras no rei justamente para
# desempatar. Uma tabela com `К` nos dois tornaria o russo indecifravel — e todo
# lance de rei viraria lance de cavalo.
PIECE_LETTERS = {
    "en": {"K": "K", "Q": "Q", "R": "R", "B": "B", "N": "N"},
    "pt": {"K": "R", "Q": "D", "R": "T", "B": "B", "N": "C"},
    "es": {"K": "R", "Q": "D", "R": "T", "B": "A", "N": "C"},
    "fr": {"K": "R", "Q": "D", "R": "T", "B": "F", "N": "C"},
    "it": {"K": "R", "Q": "D", "R": "T", "B": "A", "N": "C"},
    "de": {"K": "K", "Q": "D", "R": "T", "B": "L", "N": "S"},
    "ru": {"K": "Кр", "Q": "Ф", "R": "Л", "B": "С", "N": "К"},
}


def supports_notation(language):
    return language in PIECE_LETTERS


def _letters_of(language):
    return set(PIECE_LETTERS[language].values())


def _all_known_letters():
    return {letra for letras in PIECE_LETTERS.values() for letra in letras.values()}


# Como a captura pode estar escrita. O `x` e o do padrao PGN; o `×` (sinal de
# multiplicacao) e o `:` aparecem em material publicado e chegam aos comentarios
# como estao. Medido no banco real: 4.316 capturas com `x`, 198 com `×` e 7 com
# `:` — os 205 ultimos passavam sem correcao nenhuma, porque o lance nem era
# reconhecido como lance.
CAPTURE_MARKS = "x×:"

# Anotacoes de maquina embutidas no comentario: `[%cal Ra1h8]`, `[%csl Gd4]`,
# `[%clk 0:05:30]`. Nada dentro delas e lance — mas os codigos de cor do
# Lichess (R, G, Y, B) colidem com letras de peca, e `Ra1h8` tem a forma exata
# de um lance de Torre: sem esta exclusao, a correcao reescrevia a seta
# vermelha como `Ta1h8`, deterministicamente (ROADMAP 13.1, garantia X1). A
# exclusao vale para os DOIS lados — no original, um `[%cal Rd4d8]` viraria uma
# ancora esperada falsa; na traducao, e o proprio texto que seria reescrito — e
# tambem para a ferramenta em massa do banco, que passa por estas funcoes.
COMMAND_TAG_RE = re.compile(r"\[%[a-zA-Z]+\b[^\]]*\]")


def _command_spans(text):
    return [m.span() for m in COMMAND_TAG_RE.finditer(text)]


def _inside_any(position, spans):
    return any(start <= position < end for start, end in spans)


def _piece_ids_by_letter(language):
    """`letra -> id da peca` do idioma.

    Nenhum idioma da tabela tem duas pecas com a mesma letra — e o que o `Кр` do
    russo garante —, entao a inversao e uma bijecao.
    """
    return {letra: peca for peca, letra in PIECE_LETTERS[language].items()}


def _move_pattern(letters):
    """Regex de um lance, com a letra da peca e a da promocao em grupos proprios.

    As bordas sao `\\w` para nao casar no meio de uma palavra. O lance pode ser
    seguido de `!`, `?`, `.`, virgula ou parenteses, que nao sao `\\w`.

    As letras entram na alternancia das mais longas para as mais curtas. **Isso
    e precaucao, e nao o que faz o russo funcionar** — vale registrar porque a
    primeira versao deste comentario dizia o contrario e uma mutacao mostrou que
    era falso. O `К` (Cavalo) e prefixo do `Кр` (Rei), mas com a ordem ingenua o
    regex casa `К`, tenta seguir com `рf1` no lugar da casa, falha e **retrocede**
    para `Кр` sozinho. A ordem so passaria a decidir se a tabela ganhasse duas
    letras em que a mais curta tambem levasse a um lance valido — e ai o
    retrocesso escolheria a errada em silencio.
    """
    pecas = "|".join(sorted((re.escape(l) for l in letters), key=len, reverse=True))
    captura = f"[{re.escape(CAPTURE_MARKS)}]"
    return re.compile(
        r"(?<!\w)"
        r"(?:"
        rf"(?P<peca>{pecas})(?P<meio>[a-h]?[1-8]?{captura}?[a-h][1-8])"
        r"|"
        rf"(?P<peao>[a-h](?:{captura}[a-h])?[1-8])"
        r")"
        rf"(?:(?P<igual>=)(?P<promo>{pecas}))?"
        r"(?P<fim>[+#]?)"
        r"(?!\w)"
    )


_CAPTURE_TO_X = {ord(marca): "x" for marca in CAPTURE_MARKS}


def _anchor(match):
    """A parte do lance que e igual em todos os idiomas.

    E o que permite parear um lance do original com o mesmo lance da traducao
    sem olhar para as letras — que sao justamente o que pode estar errado.

    O sinal de captura e normalizado porque ele **muda entre os dois lados sem
    ser questao de idioma**: o original traz `N×d4` e a traducao chega com
    `Nxd4`, porque uma regra automatica do glossario ja converteu o `×`. Sem
    normalizar, os dois teriam ancoras diferentes e o lance nao seria pareado.
    """
    corpo = match.group("meio") or match.group("peao")
    return (
        corpo.translate(_CAPTURE_TO_X),
        match.group("igual") or "",
        match.group("fim") or "",
    )


def _has_letter(match):
    """Ha alguma letra de peca para corrigir neste lance?

    Um lance de peao sem promocao (`e4`, `exd5`) e identico em todos os idiomas.
    Ignora-lo nao e economia: e o que impede a correcao de mexer em texto que
    nao tem letra nenhuma para trocar.
    """
    return bool(match.group("peca") or match.group("promo"))


def _explained_by(match, letters):
    """Todas as letras deste lance pertencem a `letters`?

    E o unico ponto que decide se o idioma declarado explica um lance do
    original, e ele fica aqui de proposito: a versao anterior tinha DUAS
    protecoes — um regex restrito ao alfabeto da origem e uma checagem na
    conversao — e uma mutacao mostrou que elas eram equivalentes, ou seja, que
    uma delas nao estava sendo testada por nada. Duas guardas para a mesma
    decisao e a situacao que o item 3.6 do ROADMAP corrigiu no glossario.
    """
    for grupo in ("peca", "promo"):
        letra = match.group(grupo)
        if letra and letra not in letters:
            return False
    return True


def _target_letters_for(match, source_ids, target_letters):
    """As letras que este lance do original tem no idioma de destino.

    Devolve `(letra_da_peca, letra_da_promocao)`, com `None` onde nao ha. So
    chamada para lances que `_explained_by` ja aprovou, entao toda letra tem
    traducao.
    """
    def traduz(grupo):
        letra = match.group(grupo)
        return target_letters[source_ids[letra]] if letra else None

    return traduz("peca"), traduz("promo")


def _relettered(match, letras):
    """O lance da TRADUCAO com as letras trocadas, ou `None` se as formas nao batem.

    O corpo sai da traducao, e nao do original, e isso e o que a palavra "so a
    letra muda" quer dizer literalmente. Copiar o lance do original inteiro
    parecia equivalente e nao e: o original guarda `N×d4` e a traducao chega com
    `Nxd4`, porque uma regra automatica do glossario ja normalizou o sinal de
    captura. Reescrevendo com o corpo do original, a correcao devolveria o `×`
    ao texto — desfazendo, em silencio, uma decisao que o usuario tomou no
    glossario.

    `None` quando um lado tem letra e o outro nao. Inserir uma peca onde a
    traducao nao tem nenhuma seria acrescentar informacao, e esta funcao so
    substitui.
    """
    peca, promo = letras
    if bool(peca) != bool(match.group("peca")):
        return None
    if bool(promo) != bool(match.group("promo")):
        return None

    partes = []
    if peca:
        partes.append(peca)
    partes.append(match.group("meio") or match.group("peao"))
    if promo:
        partes.append("=" + promo)
    partes.append(match.group("fim") or "")
    return "".join(partes)


def extract_moves(text, language):
    """Os lances de `text` que o alfabeto de `language` explica, na ordem.

    Devolve so os que tem letra de peca ou de promocao — os unicos que a
    traducao pode ter estragado. Um lance com uma letra de fora do alfabeto
    declarado fica fora: nao da para dizer que peca ele move, e um lance que o
    idioma declarado nao explica nao e corrigido nem chutado.
    """
    if not text or not supports_notation(language):
        return []
    letras = _letters_of(language)
    anotacoes = _command_spans(text)
    return [
        m
        for m in _move_pattern(_all_known_letters()).finditer(text)
        if _has_letter(m)
        and _explained_by(m, letras)
        and not _inside_any(m.start(), anotacoes)
    ]


def move_anchors(text):
    """Multiconjunto das ancoras de lance de `text`, sem olhar para idioma nenhum.

    E a mesma `_anchor` que a correcao usa — de proposito. Duas definicoes de
    "ancora" divergindo seria a classe de defeito dos itens 2.8, 3.6 e 11.1: nada
    quebraria, elas so discordariam.

    Duas diferencas em relacao a `extract_moves`, e as duas sao por causa do uso:

    - **Nao filtra por idioma.** A ancora e justamente a parte que nao muda de
      lingua, entao comparar as ancoras dos dois lados nao precisa saber de qual
      idioma o texto veio — e por isso funciona tambem nas linhas legadas, cuja
      origem ninguem declarou.
    - **Inclui lances de peao.** `extract_moves` os descarta porque nao ha letra
      para corrigir; aqui um `h5` que sumiu da traducao importa tanto quanto um
      `Nf3`. Medido no banco de desenvolvimento: dos 6 comentarios em que as
      ancoras divergem, 2 sao exatamente lances de peao.

    O que esta dentro de uma anotacao `[%...]` fica de fora, pela mesma razao de
    sempre: `[%cal Ra1h8]` tem a forma de um lance de Torre e nao e lance nenhum
    (garantia X1).
    """
    anotacoes = _command_spans(text or "")
    achadas = Counter()
    for match in _move_pattern(_all_known_letters()).finditer(text or ""):
        if _inside_any(match.start(), anotacoes):
            continue
        achadas[_anchor(match)] += 1
    return achadas


def fix_move_notation(original, translated, source_language, target_language):
    """Reescreve as letras dos lances de `translated` conforme o original.

    Devolve `(texto, quantidade_corrigida)`. `quantidade` conta os lances que
    mudaram de fato, e nao os examinados: aplicar duas vezes devolve zero na
    segunda.

    **So a letra da peca muda.** Casa, captura, desempate, xeque e o `=` da
    promocao saem do proprio texto da traducao; a funcao nunca insere um lance
    que nao estava la nem apaga um que estava. O pior caso possivel dela e
    deixar um lance como o tradutor escreveu.

    Nao faz nada quando: o idioma de origem nao foi declarado, origem e destino
    sao o mesmo, algum dos dois esta fora da tabela, ou o original nao tem
    lance nenhum com letra.
    """
    if not translated or not original:
        return translated, 0
    if source_language == target_language:
        return translated, 0
    if not supports_notation(source_language) or not supports_notation(target_language):
        return translated, 0

    origem_ids = _piece_ids_by_letter(source_language)
    destino_letras = PIECE_LETTERS[target_language]

    esperados = {}
    for match in extract_moves(original, source_language):
        esperados.setdefault(_anchor(match), []).append(
            _target_letters_for(match, origem_ids, destino_letras)
        )
    if not esperados:
        return translated, 0

    # A traducao e varrida com TODAS as letras conhecidas, e nao so com as dos
    # dois idiomas em jogo. Nao e generosidade: o tradutor as vezes devolve a
    # notacao inglesa mesmo num par que nao passa pelo ingles, e um `Kf1` numa
    # traducao es -> pt nao seria nem reconhecido como lance por um alfabeto
    # restrito aos dois. Qual letra esta la e justamente o que nao importa — quem
    # decide o pareamento e a ancora, e quem decide a letra certa e o original.
    #
    # O ORIGINAL continua lido so no alfabeto declarado, e essa assimetria e o
    # item inteiro: ali a letra e a informacao, e aceitar mais alfabetos
    # devolveria a ambiguidade que a declaracao do idioma veio resolver.
    padrao = _move_pattern(_all_known_letters())
    anotacoes = _command_spans(translated)
    candidatos = [
        m
        for m in padrao.finditer(translated)
        if _has_letter(m) and not _inside_any(m.start(), anotacoes)
    ]

    por_ancora = {}
    for match in candidatos:
        por_ancora.setdefault(_anchor(match), []).append(match)

    trocas = []
    for ancora, achados in por_ancora.items():
        corretos = esperados.get(ancora)
        if not corretos:
            # Um lance que nao existe no original nao tem como ser conferido.
            continue
        if len(corretos) == 1:
            # O caso comum: uma casa, um lance. Vale para todas as ocorrencias,
            # inclusive quando a traducao repetiu o lance mais vezes que o
            # original.
            trocas.extend((m, corretos[0]) for m in achados)
        elif len(corretos) == len(achados):
            # Mesma casa com pecas diferentes ("Rf1 ou Kf1"). A ancora empata,
            # entao o desempate e a ORDEM — que o tradutor preserva, porque ele
            # traduz o texto e nao o reordena.
            trocas.extend(zip(achados, corretos))
        # Quantidades diferentes e ancora repetida: nao ha pareamento seguro, e
        # inventar um seria pior do que deixar como esta. Ninguem e tocado.

    if not trocas:
        return translated, 0

    trocas.sort(key=lambda par: par[0].start())
    pedacos = []
    fim_anterior = 0
    corrigidos = 0
    for match, letras in trocas:
        certo = _relettered(match, letras)
        if certo is None:
            continue
        pedacos.append(translated[fim_anterior:match.start()])
        pedacos.append(certo)
        if certo != match.group(0):
            corrigidos += 1
        fim_anterior = match.end()
    pedacos.append(translated[fim_anterior:])
    return "".join(pedacos), corrigidos
