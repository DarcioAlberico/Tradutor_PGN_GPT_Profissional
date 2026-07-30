"""Contagem de palavras — a metrica com que tradutor profissional orca e cobra.

Modulo proprio, e minusculo, por dois motivos: ele e usado dos dois lados (o banco
agrega, a janela de estatisticas exibe), e a definicao de "palavra" e uma decisao
que precisa estar num lugar so. Duas contagens diferentes no mesmo programa fariam
o orcamento discordar do relatorio.

Sem Tk e sem banco, como `chess_terms` e `annotation_mask`.
"""


def count_words(text):
    """Palavras separadas por espaco em branco.

    E a mesma definicao que as ferramentas de traducao usam para orcar (`wc -w`,
    a contagem do Word, a de OmegaT): sequencias separadas por espaco, tabulacao ou
    quebra de linha. **Nao e** contagem de palavras de dicionario — `14.Bxf7` conta
    como uma, e um travessao solto tambem.

    A alternativa, contar so o que tem letra, foi recusada de proposito: ela
    responderia outra pergunta ("quantas palavras de prosa ha aqui") e daria um
    numero MENOR do que aquele pelo qual o tradutor cobra. Um orcamento que
    subconta e pior que um que sobreconta um travessao.

    `None` conta zero: uma traducao que nao existe nao tem palavras. Sem isto,
    somar o banco inteiro exigiria um `or ""` em cada chamada — e a que faltasse
    derrubaria a agregacao inteira.
    """
    if not text:
        return 0
    return len(text.split())


def add_word_counts(acumulador, chave, original, translated, verified):
    """Soma um par de textos no acumulador `{chave: contagens}`.

    A escrita fica aqui, e nao no laco de quem agrega, porque as cinco somas tem de
    andar juntas: `rows`, palavras do original, palavras da traducao, e as palavras
    da traducao separadas por status. Um `+=` esquecido num dos cinco daria um
    relatorio que fecha em quase tudo — o pior tipo de numero errado.

    Devolve o dicionario da chave, ja atualizado.
    """
    contagens = acumulador.get(chave)
    if contagens is None:
        contagens = {
            "rows": 0,
            "original": 0,
            "translated": 0,
            "verified": 0,
            "pending": 0,
        }
        acumulador[chave] = contagens

    palavras_original = count_words(original)
    palavras_traducao = count_words(translated)
    contagens["rows"] += 1
    contagens["original"] += palavras_original
    contagens["translated"] += palavras_traducao
    if verified == 1:
        contagens["verified"] += palavras_traducao
    else:
        contagens["pending"] += palavras_traducao
    return contagens


def total_word_counts(acumulador):
    """Soma de todas as chaves, na mesma forma de cada uma."""
    total = {"rows": 0, "original": 0, "translated": 0, "verified": 0, "pending": 0}
    for contagens in acumulador.values():
        for campo in total:
            total[campo] += contagens[campo]
    return total
