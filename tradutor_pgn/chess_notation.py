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
    return re.compile(
        r"(?<!\w)"
        r"(?:"
        rf"(?P<peca>{pecas})(?P<meio>[a-h]?[1-8]?x?[a-h][1-8])"
        r"|"
        r"(?P<peao>[a-h](?:x[a-h])?[1-8])"
        r")"
        rf"(?:(?P<igual>=)(?P<promo>{pecas}))?"
        r"(?P<fim>[+#]?)"
        r"(?!\w)"
    )


def _anchor(match):
    """A parte do lance que e igual em todos os idiomas.

    E o que permite parear um lance do original com o mesmo lance da traducao
    sem olhar para as letras — que sao justamente o que pode estar errado.
    """
    return (
        match.group("meio") or match.group("peao"),
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


def _rendered_in(match, source_ids, target_letters):
    """O mesmo lance escrito no idioma de destino.

    So chamada para lances que `_explained_by` ja aprovou, entao toda letra tem
    traducao.
    """
    partes = []
    if match.group("peca"):
        partes.append(target_letters[source_ids[match.group("peca")]])
    partes.append(match.group("meio") or match.group("peao"))
    if match.group("promo"):
        partes.append("=" + target_letters[source_ids[match.group("promo")]])
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
    return [
        m
        for m in _move_pattern(_all_known_letters()).finditer(text)
        if _has_letter(m) and _explained_by(m, letras)
    ]


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
            _rendered_in(match, origem_ids, destino_letras)
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
    candidatos = [m for m in padrao.finditer(translated) if _has_letter(m)]

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
    for match, certo in trocas:
        pedacos.append(translated[fim_anterior:match.start()])
        pedacos.append(certo)
        if certo != match.group(0):
            corrigidos += 1
        fim_anterior = match.end()
    pedacos.append(translated[fim_anterior:])
    return "".join(pedacos), corrigidos
