# -*- coding: utf-8 -*-
"""Corretor ortografico da PROSA traduzida (ROADMAP 19.11 e 26).

O `spelling.ssp` que o programa ja traz e dicionario de nomes proprios para as
tags do PGN; ele nao sabe nada de prosa. Este modulo e a outra metade: um
dicionario hunspell do idioma de DESTINO, para o erro de digitacao da revisao
aparecer para quem revisa, e nao para o proximo leitor.

**So o portugues tem dicionario embarcado, e o programa diz isso** em vez de
ficar em silencio. Um corretor que nao marca nada e indistinguivel de um texto
sem erro, e essa e a confusao que `unsupported_language_notice` evita.

O filtro do ruido e o assunto do modulo, e nao o dicionario. Medido nas 6.500
linhas do banco de desenvolvimento, com o dicionario pt-BR do VERO:

| etapa                                    | ocorrencias | distintas |
| ---------------------------------------- | ----------- | --------- |
| o dicionario nao conhece                 | 5.098       | 2.380     |
| menos notacao e palavra colada a digito  | 3.347       | 1.969     |
| menos o que ja esta no texto de origem   | **95**      | **27**    |

O que sobra sao 94 linhas de 6.500 (1,4%), e o teor delas e util: `contra-jogo`,
`subvariacoes`, `dragonistas`, `fianquetada`, `pseudo-sacrificio` — vocabulario
que um dicionario de 2010 nao tem — mais uns poucos toponimos.

**O indice de sobrenomes do `spelling.ssp` foi medido e descartado.** Derivar os
212.787 sobrenomes das 514 mil entradas e consulta-los tira UMA palavra do
resultado (27 -> 26). Um indice novo, uma versao de esquema a mais e uma tabela
de 25 MB a manter, por uma palavra: o filtro do texto de origem ja faz esse
trabalho, porque o nome do jogador que aparece na prosa traduzida veio do PGN em
ingles e esta no acervo.
"""
import os
import re
import threading

# Diretorio dos dicionarios: ao lado do MODULO, como o `spelling_ssp`, e pela
# mesma razao (ver `pgn_spellcheck.DEFAULT_SPELLING_PATH`). E dado de programa,
# nao do usuario: ele nao edita e nao perde numa reinstalacao.
DICTIONARY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dicionarios",
)

# Idioma de destino -> nome base do par `.dic`/`.aff`. Um dicionario por idioma
# custa alguns MB e uma licenca a conferir, entao a lista cresce por decisao e
# nao por acidente: acrescentar um idioma e por o par aqui e no diretorio.
DICTIONARY_NAMES = {"pt": "pt_BR"}

# A palavra leva junto o hifen e o apostrofo internos (`contra-jogo`,
# `d'Alembert`), e NAO leva os das pontas: sem isso `'insipido'` entre aspas
# simples virava a palavra `insipido'`, que nenhum dicionario conhece. O digito
# entra no token de proposito — ver `_is_notation`.
TOKEN_RE = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)

# Notacao de lance, de casa e de roque, ja com os digitos dentro do token.
NOTATION_RE = re.compile(
    r"^(?:[RDTBCKQNP]?[a-h]?[1-8]?x?[a-h][1-8](?:=[RDTBC])?[+#!?]*"
    r"|0-0(?:-0)?|O-O(?:-O)?"
    r"|[a-h][1-8](?:-[a-h][1-8])?"
    r")$"
)

_dictionaries = {}
# Um cadeado para o REGISTRO (rapido, so protege os dicionarios) e um por IDIOMA
# (segurado durante a carga inteira). Os dois existem porque um so nao serve: um
# cadeado unico segurado durante a carga faria o idioma B esperar o A sem
# precisar, e um cadeado unico solto durante a carga deixa N threads carregarem
# o MESMO dicionario ao mesmo tempo.
#
# A segunda forma foi a primeira versao deste modulo, e a suite de janelas a
# encontrou: cada janela de teste dispara a carga do seu lado, e a checagem
# "ja esta no cache?" e feita antes de qualquer uma terminar. O processo chegou
# a 1,3 GB com varias copias de 4,6 MB sendo montadas em paralelo, e a suite
# passou de 407 s para nao terminar. Ver ROADMAP 26.4.
_registry_lock = threading.Lock()
_language_locks = {}
# Idiomas cuja carga esta em andamento. Protegido por `_registry_lock`.
_loading = set()


def dictionary_files(target_language):
    """`(.dic, .aff)` do idioma, ou `None` quando nao ha dicionario para ele."""
    nome = DICTIONARY_NAMES.get((target_language or "").lower())
    if not nome:
        return None
    base = os.path.join(DICTIONARY_DIR, nome)
    dic, aff = base + ".dic", base + ".aff"
    if os.path.exists(dic) and os.path.exists(aff):
        return dic, aff
    return None


def has_dictionary(target_language):
    return dictionary_files(target_language) is not None


def unsupported_language_notice(target_language):
    """A frase que a janela mostra quando o idioma nao tem dicionario.

    Existe para o corretor nao ser silencioso onde ele nao funciona: sem isto,
    "nenhuma marca" quer dizer duas coisas opostas — texto sem erro e corretor
    ausente — e a janela nao distingue as duas (a mesma discussao da garantia
    X3).
    """
    if has_dictionary(target_language):
        return ""
    idioma = (target_language or "?").upper()
    return f"Ortografia: sem dicionario para {idioma} (so PT por enquanto)"


def load_dictionary(target_language):
    """O dicionario do idioma, carregado uma vez por processo.

    A carga custa ~2,3 s e le 4,6 MB, entao ela NAO pode acontecer na thread da
    interface (a mesma regra do 2.11). Quem chama de dentro da janela usa
    `request_dictionary`.

    Devolve `None` quando nao ha dicionario ou quando o `spylls` nao esta
    instalado — o corretor e a unica coisa que depende dele, e o programa
    inteiro nao pode deixar de abrir por causa disso.
    """
    chave = (target_language or "").lower()
    with _registry_lock:
        if chave in _dictionaries:
            return _dictionaries[chave]
        cadeado = _language_locks.setdefault(chave, threading.Lock())

    # O cadeado do idioma e segurado durante a CARGA inteira, e a checagem do
    # cache e refeita dentro dele: quem esperou aqui pega o que o primeiro
    # carregou, em vez de montar a sua propria copia.
    with cadeado:
        with _registry_lock:
            if chave in _dictionaries:
                return _dictionaries[chave]

        arquivos = dictionary_files(chave)
        dicionario = None
        if arquivos:
            try:
                from spylls.hunspell import Dictionary

                dicionario = Dictionary.from_files(os.path.splitext(arquivos[0])[0])
            except Exception:
                dicionario = None

        with _registry_lock:
            _dictionaries[chave] = dicionario
        return dicionario


def is_loading(target_language):
    """Ha uma carga deste idioma em andamento?"""
    with _registry_lock:
        return (target_language or "").lower() in _loading


def request_dictionary(target_language):
    """O dicionario se ele ja estiver pronto; senao pede a carga e devolve `None`.

    **Quem pergunta e a interface, e nao a thread que avisa.** A versao anterior
    recebia um `on_ready` e o chamava NA THREAD de carga; quem estava do outro
    lado precisava de `win.after(...)` para voltar a thread do Tk, e `after`
    registra um comando no interpretador Tk. Fora da thread principal isso
    levanta `RuntimeError: main thread is not in main loop` sempre que a janela
    ja morreu ou que nao ha mainloop rodando — a suite de janelas produziu isso
    dezenas de vezes, uma por janela de teste (ROADMAP 26.5).

    Assim nenhuma chamada Tk sai da thread principal: a janela pergunta, e se a
    resposta ainda nao chegou ela **reagenda a si mesma** com o `after` dela,
    que roda onde deve.
    """
    chave = (target_language or "").lower()
    with _registry_lock:
        if chave in _dictionaries:
            return _dictionaries[chave]
        if chave in _loading:
            return None
        if dictionary_files(chave) is None:
            return None
        _loading.add(chave)

    def trabalho():
        try:
            load_dictionary(chave)
        finally:
            with _registry_lock:
                _loading.discard(chave)

    threading.Thread(target=trabalho, daemon=True).start()
    return None


def source_vocabulary(text):
    """As palavras de um texto, em minusculas — o filtro que faz o trabalho.

    O nome do jogador, do torneio e da cidade chegam a traducao vindos do
    original em ingles, e e la que eles estao. Comparar com o proprio texto de
    origem tira 3.347 marcas e deixa 95, sem lista nova para manter.
    """
    return {m.group().lower() for m in TOKEN_RE.finditer(text or "")}


def glossary_vocabulary(rules):
    """As palavras do lado DIREITO do glossario, em minusculas.

    E a terminologia que o proprio projeto impos, e um corretor que a marca esta
    brigando com a decisao de quem o usa: `contra-jogo` sozinho respondia por 58
    das 143 marcas do banco de desenvolvimento. Medido, este filtro leva as 143
    para 81, e as linhas marcadas de 140 para 80.

    O lado direito e nao o esquerdo: a esquerda esta o que se quer TROCAR, que e
    justamente o texto errado. Ensina-lo ao corretor seria calar o aviso no
    unico lugar em que ele acerta sozinho.

    Nao ha lista nova para manter: quem acrescenta um termo ao glossario ensina
    o corretor no mesmo gesto.

    `rules` sao pares `(original, substituicao)` — o formato que a janela ja tem
    na mao, escopado ao par de idiomas dela (garantia S11).
    """
    vocabulario = set()
    for regra in rules or ():
        try:
            substituicao = regra[1]
        except (IndexError, TypeError):
            continue
        for m in TOKEN_RE.finditer(substituicao or ""):
            vocabulario.add(m.group().lower())
    return vocabulario


def _is_notation(word):
    # Palavra colada a digito e notacao, mesmo quando nao casa o padrao: `Cd4`,
    # `13.exd5`, `h4-h5`. Nenhuma palavra de prosa tem digito no meio, e sem
    # esta linha o token quebrado no digito (`Cd`) vira marca — eram 40 das 70
    # marcas mais frequentes antes de medir.
    return any(c.isdigit() for c in word) or bool(NOTATION_RE.match(word))


def misspelled_spans(text, dictionary, known_words=()):
    """`[(inicio, fim, palavra)]` do que o dicionario nao conhece.

    `known_words` sao as palavras que nao devem ser marcadas mesmo desconhecidas
    — em minusculas. Na janela e o vocabulario do texto de ORIGEM da linha.

    Sem dicionario devolve vazio: quem quer distinguir "sem erro" de "sem
    dicionario" pergunta a `has_dictionary`, e nao ao tamanho desta lista.
    """
    if dictionary is None or not text:
        return []

    conhecidas = set(known_words)
    marcas = []
    cache = {}
    for m in TOKEN_RE.finditer(text):
        palavra = m.group()
        if palavra.lower() in conhecidas or _is_notation(palavra):
            continue
        if palavra not in cache:
            try:
                cache[palavra] = bool(
                    dictionary.lookup(palavra) or dictionary.lookup(palavra.lower())
                )
            except Exception:
                cache[palavra] = True
        if not cache[palavra]:
            marcas.append((m.start(), m.end(), palavra))
    return marcas


def suggestions(word, dictionary, limit=5):
    """As sugestoes do dicionario para uma palavra, no maximo `limit`."""
    if dictionary is None or not word:
        return []
    try:
        saida = []
        for sugestao in dictionary.suggest(word):
            saida.append(sugestao)
            if len(saida) >= limit:
                break
        return saida
    except Exception:
        return []
