import os
import re
from bisect import bisect_right

from .app_config import LANGUAGE_OUTPUT_SUFFIXES, MAX_TRANSLATE_CHARS

try:
    import chardet
except ImportError:
    chardet = None


_SENTENCE_SPACING_RE = re.compile(r'([.!?])\s*(\w)')


def _sentence_spacing(match):
    # Ponto ENTRE DIGITOS e notacao, nao fim de frase: `2.5`, `[%eval +0.35]`,
    # a versao `1.2.3`. Inserir espaco ali quebrava a anotacao e todo decimal
    # em prosa ANTES de qualquer traducao — e o texto quebrado era tres coisas
    # ao mesmo tempo: a chave de cache, o que ia para a API e o que voltava ao
    # PGN (ROADMAP 13.2). `14.Bxf7` continua ganhando o espaco de sempre: o que
    # segue o ponto e letra, nao digito.
    if (
        match.group(1) == "."
        and match.group(2).isdigit()
        and match.start() > 0
        and match.string[match.start() - 1].isdigit()
    ):
        return match.group(0)
    return f"{match.group(1)} {match.group(2)}"


def flatten_comment(text: str) -> str:
    text = " ".join(text.split())
    return _SENTENCE_SPACING_RE.sub(_sentence_spacing, text)


# BOMs reconhecidas, da mais longa para a mais curta. A ordem importa: a BOM de
# UTF-16-LE (`FF FE`) e prefixo da de UTF-32-LE (`FF FE 00 00`), entao testar a
# curta primeiro classificaria todo UTF-32-LE como UTF-16.
_BOMS = (
    (b'\x00\x00\xfe\xff', 'utf-32'),
    (b'\xff\xfe\x00\x00', 'utf-32'),
    (b'\xef\xbb\xbf', 'utf-8-sig'),
    (b'\xfe\xff', 'utf-16'),
    (b'\xff\xfe', 'utf-16'),
)


def _decodes_completely(raw: bytes, encoding: str) -> bool:
    """A codificacao da conta do arquivo INTEIRO, sem substituir nada.

    Existe porque a leitura usa `errors='replace'`: uma codificacao que nao
    decodifica troca o byte por `U+FFFD` em silencio, e esse texto e o que vai
    para a chave de cache e para o PGN gerado (garantias E4 e G2).
    """
    try:
        raw.decode(encoding)
        return True
    except (UnicodeDecodeError, LookupError):
        return False


def _looks_like_bomless_utf16(raw: bytes) -> str:
    """Detecta UTF-16 sem BOM pelos NUL intercalados, ou devolve ''.

    Um PGN em UTF-16-LE com texto ASCII e uma letra e um `\\x00` alternados. Isso
    passa no teste "e tudo ASCII" de E2 — `\\x00` E ASCII valido — e o arquivo era
    lido como UTF-8, produzindo comentarios com um NUL entre cada letra que
    viravam chave de cache.

    Nenhum PGN legitimo de byte unico tem NUL, entao a presenca deles ja seria
    suspeita; o que decide qual variante e o LADO em que aparecem: `\\x00` nas
    posicoes impares e little-endian, nas pares e big-endian.
    """
    if len(raw) < 4 or b'\x00' not in raw:
        return ''

    # Um numero impar de bytes nao pode ser UTF-16.
    amostra = raw[: len(raw) - (len(raw) % 2)]
    pares = amostra[0::2]
    impares = amostra[1::2]

    nulos_pares = pares.count(0)
    nulos_impares = impares.count(0)
    metade = len(pares)
    if metade == 0:
        return ''

    # Exigir a grande maioria, e nao a totalidade: um PGN em UTF-16 pode ter
    # alguns caracteres acentuados fora do bloco ASCII.
    if nulos_impares >= metade * 0.9 and nulos_pares == 0:
        return 'utf-16-le'
    if nulos_pares >= metade * 0.9 and nulos_impares == 0:
        return 'utf-16-be'
    return ''


def detect_encoding_from_bytes(raw: bytes) -> str:
    """A codificacao dos bytes de um PGN, sem tocar no disco.

    Separada de `detect_encoding` para que quem ja tem os bytes na mao nao
    precise de uma segunda leitura do arquivo (ROADMAP 20.2): cada PGN era lido
    quatro vezes por execucao — a deteccao lia inteiro, a extracao relia, e a
    geracao repetia as duas.

    O criterio e o de sempre, e continua sendo o do arquivo INTEIRO: ver
    `detect_encoding`.
    """
    try:
        for bom, encoding in _BOMS:
            if raw.startswith(bom):
                # A BOM e uma declaracao explicita de quem gravou o arquivo. So
                # nao vale se o resto do arquivo a desmentir.
                if _decodes_completely(raw, encoding):
                    return encoding
                break

        # UTF-16 sem BOM: precisa vir ANTES do teste de ASCII puro, que ele
        # passaria por causa dos NUL (ver `_looks_like_bomless_utf16`).
        utf16 = _looks_like_bomless_utf16(raw)
        if utf16 and _decodes_completely(raw, utf16):
            return utf16

        # Conteudo integralmente ASCII: qualquer superset serve, e UTF-8 e o
        # mais seguro para o que for gravado depois. Nunca devolver 'ascii'.
        try:
            raw.decode('ascii')
            return 'utf-8'
        except UnicodeDecodeError:
            pass

        # Ha bytes altos. UTF-8 valido nao acontece por acaso: se decodifica,
        # e UTF-8.
        try:
            raw.decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            pass

        if chardet is not None:
            result = chardet.detect(raw)
            enc = (result.get('encoding') or '').lower()
            confidence = result.get('confidence') or 0

            if confidence >= 0.60 and enc:
                if enc == 'windows-1252':
                    enc = 'cp1252'
                elif enc in ('iso-8859-1', 'latin-1'):
                    enc = 'latin-1'
                # 'ascii' aqui seria contraditorio: ja sabemos que ha bytes altos.
                if enc not in ('ascii', 'utf-8') and _decodes_completely(raw, enc):
                    return enc

        for enc in ('cp1252', 'latin-1'):
            if _decodes_completely(raw, enc):
                return enc

    except Exception:
        pass

    return 'utf-8'


def detect_encoding(file_path: str) -> str:
    """Detecta a codificacao de um PGN analisando o arquivo inteiro.

    Ler apenas uma amostra e inseguro: um PGN costuma comecar com milhares de
    linhas ASCII puro e so trazer acentos bem depois. Uma amostra desse trecho
    faz o chardet responder 'ascii', e a leitura seguinte destroi todos os
    acentos do arquivo (garantias E1 e E2 da SPEC.md).

    Nenhuma codificacao e devolvida sem que ela decodifique o arquivo inteiro
    (garantia E4) — inclusive a que o `chardet` sugerir. Antes, so o fallback
    final verificava, e o palpite do `chardet` era aceito no escuro.
    """
    try:
        with open(file_path, 'rb') as f:
            raw = f.read()
    except Exception:
        return 'utf-8'

    return detect_encoding_from_bytes(raw)


def read_pgn_text(file_path: str):
    """`(texto, codificacao)` do PGN, com UMA leitura do arquivo (garantia G4).

    A codificacao e detectada sobre os bytes que acabaram de ser lidos, e o
    texto sai desses mesmos bytes. O caminho antigo — `detect_encoding` lendo o
    arquivo inteiro e o `open` em modo texto lendo de novo — pagava duas
    leituras por chamada, e a execucao chamava as duas duas vezes: uma na
    extracao e outra na geracao (ROADMAP 20.2).

    `errors='replace'` e o mesmo do `open` que isto substitui, e vale a mesma
    observacao de `_decodes_completely`: a deteccao ja exige que a codificacao
    escolhida decodifique o arquivo inteiro, entao o `replace` so age no
    fallback, quando nao ha codificacao que sirva.

    Nao ha traducao de fim de linha, como no `open(..., newline='')` que isto
    substitui: o `\\r\\n` do arquivo sobrevive ate a gravacao (ROADMAP 13.6).
    """
    with open(file_path, 'rb') as f:
        raw = f.read()

    enc = detect_encoding_from_bytes(raw)
    return raw.decode(enc, errors='replace'), enc


def output_suffix_for_language(target_language: str) -> str:
    return LANGUAGE_OUTPUT_SUFFIXES.get(target_language, target_language.upper())


def strip_generated_suffix(filename_without_ext: str) -> str:
    """Tira o sufixo de idioma de um nome de PGN gerado por este programa.

    O `-\\d+` opcional no fim e o sufixo de colisao que `available_output_path`
    acrescenta quando o arquivo de saida ja existe. Sem ele, `game-BR-2.pgn` nao
    era reconhecido como gerado: a terceira execucao sobre a mesma pasta pegava
    aquele arquivo como ENTRADA e traduzia portugues para portugues, produzindo
    `game-BR-2-BR.pgn` — e cada execucao seguinte acrescentava mais um.
    """
    suffixes = "|".join(re.escape(s) for s in LANGUAGE_OUTPUT_SUFFIXES.values())
    return re.sub(
        rf"-({suffixes})(-\d+)?$", "", filename_without_ext, flags=re.IGNORECASE
    )


def is_generated_pgn(file_path: str) -> bool:
    name, ext = os.path.splitext(os.path.basename(file_path))
    if ext.lower() != ".pgn":
        return False
    return strip_generated_suffix(name) != name


def translated_output_path(input_file: str, target_language: str) -> str:
    file_dir = os.path.dirname(input_file)
    name, ext = os.path.splitext(os.path.basename(input_file))
    base_name = strip_generated_suffix(name)
    suffix = output_suffix_for_language(target_language)
    output_file = os.path.join(file_dir, f"{base_name}-{suffix}{ext}")

    if os.path.abspath(output_file) == os.path.abspath(input_file):
        output_file = os.path.join(file_dir, f"{name}-novo{ext}")

    return output_file


def available_output_path(output_file: str) -> str:
    if not os.path.exists(output_file):
        return output_file

    file_dir = os.path.dirname(output_file)
    name, ext = os.path.splitext(os.path.basename(output_file))
    index = 2

    while True:
        candidate = os.path.join(file_dir, f"{name}-{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1


def collect_pgn_files(source_path: str, process_subdirs: bool):
    pgn_files = []
    skipped_generated = 0

    def add_file(path, allow_generated=False):
        nonlocal skipped_generated
        if not path.lower().endswith(".pgn"):
            return
        if not allow_generated and is_generated_pgn(path):
            skipped_generated += 1
            return
        pgn_files.append(path)

    if os.path.isfile(source_path):
        add_file(source_path, allow_generated=True)
    elif process_subdirs:
        for root, _, files in os.walk(source_path):
            for f in files:
                add_file(os.path.join(root, f))
    else:
        for f in os.listdir(source_path):
            add_file(os.path.join(source_path, f))

    return sorted(pgn_files), skipped_generated


def count_semicolon_comments(content: str) -> int:
    """Quantas linhas tem comentario `;` (a segunda forma do padrao PGN).

    O programa nao traduz esses comentarios; contar e anunciar e o que impede o
    modo de falha mais confuso — um PGN anotado so com `;` respondendo "nenhum
    comentario encontrado" como se nada existisse (garantia X3).

    Um `;` dentro de `{...}` e texto do comentario, e um numa linha de tag
    (`[Event "a;b"]`) e parte do valor: os dois ficam de fora. As chaves sao
    removidas preservando as quebras de linha, para que a contagem por linha
    nao junte vizinhas.
    """
    sem_chaves = re.sub(
        r'\{.*?\}',
        lambda m: "\n" * m.group(0).count("\n"),
        content,
        flags=re.DOTALL,
    )
    total = 0
    for line in sem_chaves.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('['):
            continue
        if ';' in line:
            total += 1
    return total


# Uma partida comeca na tag `Event`: o padrao PGN exige que ela seja a primeira
# do par de tags, entao contar `[Event` e contar partidas. Ancorada no comeco da
# linha porque e la que a tag mora — e a busca roda sobre o texto com os
# comentarios apagados (ver `_blank_spans`), entao um `[Event` DENTRO de um
# comentario nao vira partida nova.
_GAME_START_RE = re.compile(r'^[ \t]*\[[ \t]*Event\b', re.MULTILINE)

# Numero de lance no movetext: digitos seguidos de ponto (`12.`, `12...`, e
# tambem `12 .`, que alguns exportadores escrevem). Tres recortes, e cada um pega
# um caso diferente:
#
# `(?<![\w.])` separa o numero de lance de um numero DENTRO de outra coisa: em
# `0.35` o `35` nao casa (vem depois de um ponto) e em `12345.` nada casa (o
# `2345` vem depois de um digito).
#
# `(?!\d)` depois do ponto e o que impede um DECIMAL de virar lance. Sem ele,
# um `+0.35` solto no movetext dava "lance 0" — um numero errado e visivel na
# tela, encontrado pelo teste deste caso. E o mesmo criterio de `flatten_comment`
# (ROADMAP 13.2): ponto entre digitos e notacao, nao pontuacao. Exige o digito
# COLADO no ponto de proposito: `1. 0-0` — roque escrito com zeros, que aparece em
# PGN antigo — continua sendo o lance 1.
#
# O limite de quatro digitos e o argumento do primeiro recorte pelo outro lado:
# nenhuma partida chega ao lance 10.000, e uma data solta no movetext deixa de ser
# confundida com lance.
_MOVE_NUMBER_RE = re.compile(r'(?<![\w.])(\d{1,4})[ \t]*\.(?!\d)')


def _blank_spans(content: str, spans) -> str:
    """Copia de `content` com os spans trocados por espaco, nos MESMOS offsets.

    Existe para que a leitura do movetext — partidas e numeros de lance — nunca
    veja o texto dos comentarios. Um comentario de livro cita lances a vontade
    ("melhor era 14. Bxf7"), e sem apagar os spans o lance citado passaria a
    valer como a posicao do comentario seguinte.

    As quebras de linha DENTRO do span ficam de pe: as checagens seguintes sao
    por linha (uma linha de tag, um comentario `;`), e engolir o `\\n` de um
    comentario multilinha juntaria duas linhas que nao sao vizinhas.

    Os offsets se preservam porque cada caractere apagado e trocado por um, e nao
    por nada: as posicoes dos comentarios ja foram medidas no texto original e
    precisam continuar valendo aqui.
    """
    pedacos = []
    ultimo = 0
    for start, end in spans:
        pedacos.append(content[ultimo:start])
        trecho = content[start:end]
        if "\n" in trecho:
            pedacos.append("".join("\n" if c == "\n" else " " for c in trecho))
        else:
            pedacos.append(" " * len(trecho))
        ultimo = end
    pedacos.append(content[ultimo:])
    return "".join(pedacos)


def _outside_movetext(content: str, pos: int) -> bool:
    """A posicao esta numa linha de tag, ou depois de um `;` na propria linha?

    Os dois casos tem numeros com ponto que nao sao lance: `[Date "2011.05.12"]`
    e o resto de linha de um comentario `;`, que este programa nao traduz mas que
    continua sendo texto e nao movetext.
    """
    inicio = content.rfind("\n", 0, pos) + 1
    prefixo = content[inicio:pos]
    return prefixo.lstrip().startswith("[") or ";" in prefixo


def comment_reading_context(content: str, spans):
    """Para cada span de comentario, `(partida, numero do lance)`.

    E o contexto que o banco nao tinha (ROADMAP 18): sem ele a lista do editor e
    ordem de insercao, e nao ordem de leitura da obra.

    A partida sai da contagem de tags `Event` que vem ANTES do comentario. Um
    comentario antes da primeira delas conta como da partida 1: em ordem de
    leitura nao existe partida zero, e um PGN de movetext solto — sem tag nenhuma
    — e uma partida so.

    O lance e o ultimo numero de lance antes do comentario, DENTRO da mesma
    partida. O recorte por partida e o que impede o pior erro possivel aqui: um
    comentario colado nas tags da partida 2 herdaria o lance 41 da partida 1 e
    diria com confianca uma posicao que nao existe. Sem nenhum lance antes dele,
    o lance e `None` — que e o que o banco grava, em vez de um zero que se
    confundiria com medicao.

    Devolve uma lista paralela a `spans`. Nao le nem valida lance nenhum: validar
    e nao-objetivo (secao 1 da SPEC), e o que se registra aqui e onde o
    comentario estava, nao o que o tabuleiro dizia.
    """
    limpo = _blank_spans(content, spans)
    inicios_de_partida = [m.start() for m in _GAME_START_RE.finditer(limpo)]
    lances = [
        (m.start(), int(m.group(1)))
        for m in _MOVE_NUMBER_RE.finditer(limpo)
        if not _outside_movetext(limpo, m.start())
    ]
    posicoes_de_lance = [pos for pos, _numero in lances]

    contexto = []
    for start, _end in spans:
        partida = bisect_right(inicios_de_partida, start)
        # O comeco da partida do comentario. Fora de qualquer partida declarada
        # (movetext solto), o limite e o comeco do arquivo.
        limite = inicios_de_partida[partida - 1] if partida else 0
        anterior = bisect_right(posicoes_de_lance, start)
        lance = None
        if anterior and lances[anterior - 1][0] >= limite:
            lance = lances[anterior - 1][1]
        contexto.append((max(1, partida), lance))
    return contexto


_COMMENT_RE = re.compile(r'\{(.*?)\}', re.DOTALL)


def extract_comment_texts(content: str):
    """So os TEXTOS dos comentarios e a contagem de `;`. A metade barata.

    A primeira passada da execucao precisa apenas disto: quantos comentarios ha
    (para a barra de progresso) e quais textos sao (para adotar as linhas sem
    idioma e para carregar o cache). Posicao e contexto de leitura sao caros — o
    contexto sozinho custa 174 ms dos 263 ms da extracao completa num PGN de
    3,2 MB — e so servem na vez do arquivo, ja perto da gravacao.

    Medir isto foi o que decidiu o desenho de 20.4: a alternativa era a extracao
    completa nas duas passadas, que custaria a parte cara duas vezes por arquivo.
    """
    textos = [flatten_comment(m.group(1)) for m in _COMMENT_RE.finditer(content)]
    return {
        "comments": [texto for texto in textos if texto],
        "semicolon_comments": count_semicolon_comments(content),
    }


def extract_comment_texts_from_file(pgn_file: str, log_message=None):
    """Le o PGN e devolve so os textos. Ver `extract_comment_texts`.

    A codificacao e anunciada aqui, e nao na segunda passada: e o momento em que
    o programa a descobre, e repetir a linha por arquivo diria duas vezes a mesma
    coisa.
    """
    try:
        content, enc = read_pgn_text(pgn_file)
        if log_message:
            log_message(f"Arquivo: {os.path.basename(pgn_file)} | Codificacao detectada: {enc}")

        return extract_comment_texts(content)

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao extrair comentarios de {pgn_file}: {e}")
        return {"comments": [], "semicolon_comments": 0}


def extract_comments_from_content(
    content: str, count_semicolons: bool = True, known_texts=None
):
    """Os comentarios `{...}` de um PGN JA LIDO, com posicao e contexto.

    Separada de `extract_comments_from_file` para que a segunda passada da
    execucao — a que gera o PGN — aproveite o texto que acabou de ler em vez de
    reler o arquivo (ROADMAP 20.2). Nao toca no disco, e e por isso que ela nao
    tem tratador de excecao: quem le decide o que fazer com um arquivo ilegivel.

    `occurrences` e a lista de `(indice, partida, lance, texto)` na ordem em que
    os comentarios aparecem no arquivo — o que o worker grava na tabela
    `occurrences` para que o banco saiba de onde cada traducao veio (ROADMAP 18).
    O indice conta os comentarios APROVEITADOS, na mesma ordem de `comments` e
    `positions`: um `{}` vazio nao ocupa posicao porque nao vira linha nenhuma no
    banco.

    `count_semicolons=False` devolve zero em `semicolon_comments` em vez de
    recontar: a execucao ja contou na primeira passada (garantia X3 e cumprida
    la), e a contagem custa 29 ms por 3,2 MB de arquivo.

    `known_texts` e um mapa `{texto: texto}` do que quem chama JA TEM em memoria.
    Um comentario que esta la sai como **o objeto que ja existe**, e nao como um
    segundo objeto de igual conteudo. E o que impede o texto de viver duas vezes
    quando a execucao le o arquivo em duas passadas (ROADMAP 20.4): num livro com
    8 mil comentarios de 400 caracteres, sao 3,9 MB de texto duplicado no momento
    exato em que o arquivo esta sendo gravado. As chaves da traducao continuam
    casando de qualquer jeito — o `dict` compara por valor —, entao isto e so
    memoria, e nunca comportamento.
    """
    comments = []
    positions = []
    occurrences = []

    # TODOS os spans entram na leitura do contexto, inclusive os que serao
    # descartados: o que interessa ali e apagar o texto dos comentarios do
    # movetext, e um `{}` vazio tambem nao e movetext.
    encontrados = list(_COMMENT_RE.finditer(content))
    contexto = comment_reading_context(
        content, [(m.start(), m.end()) for m in encontrados]
    )

    for match, (partida, lance) in zip(encontrados, contexto):
        normalized = flatten_comment(match.group(1))
        if not normalized:
            continue
        if known_texts is not None:
            normalized = known_texts.get(normalized, normalized)

        comments.append(normalized)
        positions.append((match.start(), match.end(), normalized))
        occurrences.append((len(comments), partida, lance, normalized))

    return {
        "comments": comments,
        "positions": positions,
        "occurrences": occurrences,
        "semicolon_comments": (
            count_semicolon_comments(content) if count_semicolons else 0
        ),
    }


def extract_comments_from_file(pgn_file: str, log_message=None):
    """Le o PGN e extrai os comentarios dele. Ver `extract_comments_from_content`.

    O texto sai de `read_pgn_text`, que preserva o `\\r\\n` do arquivo: as
    posicoes extraidas aqui sao offsets NESTE texto, e o mesmo texto vai para a
    geracao — com universal newlines, todo PGN de saida trocava o fim de linha da
    plataforma em silencio (ROADMAP 13.6). Dentro dos comentarios o
    `flatten_comment` colapsa qualquer `\\r` junto com o resto do espaco.
    """
    try:
        content, enc = read_pgn_text(pgn_file)
        if log_message:
            log_message(f"Arquivo: {os.path.basename(pgn_file)} | Codificacao detectada: {enc}")

        return extract_comments_from_content(content)

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao extrair comentarios de {pgn_file}: {e}")
        return {
            "comments": [],
            "positions": [],
            "occurrences": [],
            "semicolon_comments": 0,
        }


BATCH_SEPARATOR = " ||| "
_SEP_LEN = len(BATCH_SEPARATOR)

# Precisa ser estritamente menor que MAX_TRANSLATE_CHARS: se um lote passasse do
# limite da camada de API, ela o dividiria por sentenca e poderia cortar no meio
# de um separador, tornando o realinhamento impossivel (garantia B1 da SPEC.md).
BATCH_MAX_CHARS = MAX_TRANSLATE_CHARS - 200


def batch_index_groups(texts, max_chars=BATCH_MAX_CHARS):
    """Os grupos de `create_comment_batches`, na forma de indices.

    Existe porque o lote e montado sobre o texto CRU e enviado LIMPO e
    MASCARADO: as regras de limpeza podem encurtar (o caso comum) mas tambem
    expandir, e a mascara troca cada `[%cal ...]` por uma sentinela de tamanho
    diferente. O texto medido, portanto, nao e o texto enviado — e a garantia B1
    (`BATCH_MAX_CHARS < MAX_TRANSLATE_CHARS`) vinha sendo sustentada pela folga
    de 200 caracteres, o que e acoplamento, nao garantia. Estourar o limite faz a
    camada de API dividir por sentenca, e o corte pode cair no meio de um `|||`:
    o realinhamento se torna impossivel.

    Com os grupos como indices, o worker reagrupa o que ja transformou usando o
    MESMO algoritmo, sem uma segunda copia dele para divergir.
    """
    groups = []
    current = []
    length = 0

    for index, text in enumerate(texts):
        l = len(text)
        # Account for separator that will be inserted between items
        extra = _SEP_LEN if current else 0
        if l > max_chars:
            if current:
                groups.append(current)
            groups.append([index])
            current = []
            length = 0
        elif length + extra + l > max_chars:
            groups.append(current)
            current = [index]
            length = l
        else:
            current.append(index)
            length += extra + l

    if current:
        groups.append(current)

    return groups


def create_comment_batches(comments, max_chars=BATCH_MAX_CHARS):
    comments = list(comments)
    return [
        [comments[i] for i in group]
        for group in batch_index_groups(comments, max_chars)
    ]


def join_comments_for_batch(comments):
    """Junta comentários com separador para envio em uma única requisição."""
    return BATCH_SEPARATOR.join(comments)


def split_batch_translation(translated_text, expected_count):
    """Divide a resposta traduzida de volta em comentários individuais.

    Retorna a lista de partes se o número bater, ou None se houver
    desalinhamento (sinal para usar fallback individual).
    """
    if expected_count == 1:
        return [translated_text.strip()]

    parts = [p.strip() for p in translated_text.split(BATCH_SEPARATOR)]
    if len(parts) == expected_count:
        return parts

    # O Google às vezes altera os espaços ao redor de |||
    parts = [p.strip() for p in re.split(r"\s*\|\|\|\s*", translated_text)]
    if len(parts) == expected_count:
        return parts

    return None


def sanitize_pgn_comment(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


# Um `[%...]` conta como UMA palavra na requebra. Ele tem espacos dentro
# (`[%cal Ra1h8,Rb2b7]`, `[%eval +0.35]`) e ferramentas que o leem esperam a
# anotacao inteira numa linha; quebra-la no meio nao corrompe o texto, mas produz um
# arquivo em que um leitor estrito deixa de reconhecer o comando. Como a garantia X1
# gastou uma secao inteira protegendo esses spans, quebra-los na gravacao seria
# desfazer o trabalho no ultimo passo.
_WRAP_TOKEN_RE = re.compile(r"\[%[^\]]*\]|\S+")

# Largura do export format do padrao PGN, e o que editora espera receber.
PGN_EXPORT_LINE_WIDTH = 80


def wrap_pgn_comment(text: str, width: int, first_line_room: int) -> str:
    """Requebra o comentario para caber em `width` colunas (ROADMAP 19, item 13).

    `first_line_room` e quanto sobra na linha em que o comentario COMECA — depois de
    `12. Nf3 {`, a primeira linha tem menos espaco que as seguintes. Sem isso, a
    requebra acertaria todas as linhas menos a primeira, que e a unica em que o
    comentario divide espaco com o movetext.

    **So o espaco em branco muda.** As palavras saem na mesma ordem e com os mesmos
    caracteres: um espaco entre duas delas vira uma quebra de linha, e nada mais. E
    o que permite requebrar sem tocar na chave de cache — que e o texto ACHATADO, e
    continua sendo (ROADMAP 13.2).

    Uma palavra mais longa que a linha inteira (um URL, um `[%cal]` gigante) fica
    inteira e estoura a coluna: cortar no meio dela produziria um token que nao
    existe. Requebrar e formatacao; inventar palavra, nao.
    """
    tokens = _WRAP_TOKEN_RE.findall(text or "")
    if not tokens:
        return text or ""

    linhas = []
    atual = ""
    espaco = max(1, first_line_room)
    for token in tokens:
        if not atual:
            candidato = token
        else:
            candidato = f"{atual} {token}"
        if atual and len(candidato) > espaco:
            linhas.append(atual)
            atual = token
            espaco = max(1, width)
        else:
            atual = candidato
    if atual:
        linhas.append(atual)
    return "\n".join(linhas)


def _normalized_encoding_name(encoding: str) -> str:
    return (encoding or "").lower().replace("-", "").replace("_", "")


def _is_unicode_encoding(encoding: str) -> bool:
    """A codificacao representa qualquer caractere E se anuncia ao leitor."""
    return _normalized_encoding_name(encoding).startswith("utf")


def _output_encoding(preferred_encoding: str, use_bom: bool) -> str:
    """A codificacao de gravacao: UTF-8 quando a de entrada nao for Unicode.

    A saida herdava a codificacao do PGN de entrada, e isso quebra em silencio
    quando ela e de byte unico. Um PGN em ingles com dois nomes de jogador
    acentuados e detectado como cp1252; a traducao para portugues enche o
    arquivo de acento; e o arquivo sai com quinze mil bytes altos em cp1252.
    Leitor que espera UTF-8 — o ChessBase 26, por exemplo — trata esses bytes
    como UTF-8 invalido e os DESCARTA: "Dragao" no lugar de "Dragão", "posio"
    no lugar de "posição". Nao e mojibake, e letra que some, e nada no programa
    acusava.

    O fallback de `write_pgn_pieces` nao alcanca este caso: ele so dispara no
    `UnicodeEncodeError`, e cp1252 representa todo acento do portugues sem
    reclamar. O acento nao se perde na GRAVACAO, se perde na leitura seguinte.

    So promove o que nao e Unicode. UTF-16 e UTF-32 ficam onde estao: carregam
    BOM, se anunciam ao leitor e nao perdem caractere nenhum. E promover uma
    saida que so tem ASCII nao muda byte algum — nesse caso as duas gravacoes
    dao o mesmo arquivo.

    `use_bom` continua valendo depois da promocao, e por isso ela pode sair sem
    BOM: um BOM que ninguem pediu incomoda (git, diff, parsers estritos), e
    quem le no ChessBase antigo — que trata UTF-8 sem BOM como ANSI e mostra
    mojibake — liga a opcao no `pgn_tradutor_pro_settings.json` (ROADMAP 13.6).
    So mexe em UTF-8: um BOM nao significa nada em cp1252, e `utf-8-sig` ja o
    escreve sozinho.
    """
    encoding = preferred_encoding
    if not _is_unicode_encoding(encoding):
        encoding = "utf-8"
    if not use_bom:
        return encoding
    if _normalized_encoding_name(encoding) == "utf8":
        return "utf-8-sig"
    return encoding


def write_pgn_pieces(
    output_file: str,
    pieces_factory,
    preferred_encoding: str,
    log_message=None,
    use_bom: bool = False,
):
    """Grava os pedacos do PGN em sequencia, sem junta-los numa string.

    `pieces_factory` e uma funcao que devolve um iteravel de pedacos — e uma
    funcao, e nao o iteravel, porque o fallback de codificacao precisa percorrer
    tudo de novo, e um gerador esgotado nao serve. Guardar os pedacos numa lista
    resolveria o mesmo problema pagando exatamente o que isto evita: uma copia do
    arquivo inteiro na memoria (ROADMAP 20.1).

    `newline=''` nos dois caminhos: o conteudo carrega o fim de linha do arquivo
    original (lido tambem sem traducao de linha), e a escrita nao pode troca-lo
    pelo da plataforma (ROADMAP 13.6).

    O segundo `open` trunca o que a primeira tentativa deixou pela metade — um
    `UnicodeEncodeError` acontece no meio da gravacao, e o arquivo parcial nao
    pode sobreviver ao lado do bom.
    """
    try:
        enc = _output_encoding(preferred_encoding, use_bom)
        if log_message and not _is_unicode_encoding(preferred_encoding):
            # Visivel no log porque e o programa mudando a codificacao por conta
            # propria: quem comparar a entrada com a saida byte a byte tem de
            # achar aqui o motivo de elas nao baterem.
            log_message(
                f"  - Codificacao de saida alterada de {preferred_encoding} "
                f"para {enc}, para o acento sobreviver a leitura: {output_file}"
            )
        with open(output_file, 'w', encoding=enc, newline='') as f:
            for pedaco in pieces_factory():
                f.write(pedaco)
        return enc
    except UnicodeEncodeError:
        enc = _output_encoding('utf-8', use_bom)
        with open(output_file, 'w', encoding=enc, newline='') as f:
            for pedaco in pieces_factory():
                f.write(pedaco)
        if log_message:
            log_message(f"  - Codificacao de saida alterada para UTF-8: {output_file}")
        return enc


def write_translated_pgn(
    output_file: str,
    content: str,
    preferred_encoding: str,
    log_message=None,
    use_bom: bool = False,
):
    """Grava um PGN que ja esta inteiro numa string. Ver `write_pgn_pieces`."""
    return write_pgn_pieces(
        output_file,
        lambda: (content,),
        preferred_encoding,
        log_message,
        use_bom=use_bom,
    )


def _comment_line_room(content, start, width):
    """Quantas colunas sobram na linha em que o comentario comeca.

    O `{` conta: ele entra na linha junto com o texto.

    A coluna e medida no texto ORIGINAL, e nao no texto final. Na esmagadora
    maioria dos casos da no mesmo — o que vem antes do comentario na linha e
    movetext, que a traducao nao toca. Da diferente quando dois comentarios
    dividem a linha: o primeiro pode encolher ou crescer, e a coluna do segundo
    muda com ele. Nao ha conta exata a fazer aqui sem gerar o arquivo duas vezes
    (a largura do primeiro depende da requebra dele, que depende da coluna dele),
    e o erro so desloca uma quebra de linha — formatacao, nunca texto.

    Era isto que a versao anterior fazia tambem, apesar de o comentario dela
    dizer o contrario ("o conteudo antes do comentario ja e final"): a requebra
    sempre foi calculada nesta fase, antes de qualquer substituicao.
    """
    inicio_da_linha = content.rfind("\n", 0, start) + 1
    coluna = start - inicio_da_linha
    return width - coluna - 1


# De quantos em quantos comentarios a geracao olha o `cancel_flag`. A fase toda
# custa 23 ms num PGN de 3,2 MB com 15 mil comentarios (ROADMAP 20.1), entao o
# intervalo nao precisa ser curto; ele existe para o caso extremo — livro de
# dezenas de MB com requebra ligada —, em que a fase deixa de ser instantanea.
_CANCEL_CHECK_EVERY = 512


def generate_translated_pgn(
    input_file,
    output_file,
    translated_map,
    positions,
    log_message=None,
    use_bom=False,
    wrap_columns=0,
    content=None,
    encoding=None,
    cancel_flag=None,
):
    """Grava o PGN traduzido. `wrap_columns` requebra os comentarios (item 13).

    Zero desliga a requebra, que e o comportamento de sempre: o comentario sai em
    linha unica, como o programa sempre escreveu.

    `content` e `encoding` sao o texto e a codificacao que quem chama JA LEU. Sem
    eles o arquivo e lido aqui, como sempre foi; com eles a execucao economiza
    uma releitura e uma redeteccao por arquivo (ROADMAP 20.2). O texto tem de ser
    o mesmo em que `positions` foi medido — sao offsets nele.

    `cancel_flag` interrompe a fase sem gravar nada. Ela nao tinha checagem
    nenhuma: num acervo grande, "Cancelar" ficava sem efeito visivel enquanto o
    arquivo era montado (ROADMAP 20.1).
    """
    try:
        if content is None:
            content, enc = read_pgn_text(input_file)
        else:
            enc = encoding or detect_encoding(input_file)

        # O fim de linha do arquivo, para a requebra usar o mesmo. `\r\n` presente
        # em qualquer lugar decide: um PGN meio-a-meio nao existe na pratica, e na
        # duvida entre os dois o do Windows e o que ChessBase e editora esperam.
        eol = "\r\n" if "\r\n" in content else "\n"

        replacements = []
        # O fim do span anterior JA AJUSTADO. Ele existe por causa do espaco
        # vizinho que um comentario esvaziado leva junto: sem esse limite,
        # `{a} {b}` com os dois esvaziados fazia o segundo span reclamar para tras
        # um caractere que o primeiro ja havia levado, e dois spans sobrepostos,
        # com a substituicao da direita para a esquerda, apagavam o RESTO DO
        # ARQUIVO.
        #
        # Hoje ele e a segunda tranca, e nao a unica: na passada unica abaixo, uma
        # sobreposicao de um caractere daria uma fatia vazia e nao estrago. Fica
        # porque e o que mantem `replacements` sem sobreposicao, que e o
        # invariante de que a montagem depende — confiar na fatia vazia seria
        # correcao por acidente. A rodada de mutacao registra isso (ROADMAP 20.8).
        fim_anterior = 0
        # Em ordem crescente, que e como a extracao entrega e o que permite montar
        # o arquivo numa passada. O `sorted` esta aqui porque `positions` e
        # parametro: um chamador pode passar outra ordem, e ai a passada unica
        # produziria um arquivo embaralhado em silencio.
        for indice, (start, end, norm) in enumerate(
            sorted(positions, key=lambda posicao: posicao[0])
        ):
            if cancel_flag is not None and indice % _CANCEL_CHECK_EVERY == 0:
                if cancel_flag.is_set():
                    if log_message:
                        log_message("  - Geracao do PGN traduzido cancelada.")
                    return False
            if norm not in translated_map:
                continue
            if start < fim_anterior:
                # Spans sobrepostos. Nao acontece com o que a extracao produz —
                # os `{...}` sao disjuntos, e o ajuste do espaco vizinho abaixo
                # respeita o span anterior —, mas aplicar o segundo por cima do
                # primeiro corromperia o arquivo em silencio, e e isso que o aviso
                # evita.
                if log_message:
                    log_message(
                        f"[AVISO] Comentario em posicao sobreposta ignorado na "
                        f"gravacao: offset {start}."
                    )
                continue
            translated = translated_map[norm]
            if translated == "":
                # Comentario esvaziado pelas regras de limpeza: o span sai
                # inteiro, com um espaco vizinho junto, em vez de deixar um
                # `{}` pontilhando o arquivo (garantia X2). So espaco ou tab —
                # nunca a quebra de linha, que estrutura o resto do arquivo, e
                # nunca outro span: `{a}{b}` colados nao tem espaco entre si.
                #
                # Uma traducao que FALHOU nunca chega aqui: ela nao entra no
                # `translated_map`, e o comentario original fica como esta
                # (garantia T3). O unico "" do mapa e o da limpeza.
                if end < len(content) and content[end] in " \t":
                    end += 1
                elif start > fim_anterior and content[start - 1] in " \t":
                    start -= 1
                replacements.append((start, end, ""))
                fim_anterior = end
            else:
                texto = sanitize_pgn_comment(translated)
                if wrap_columns:
                    texto = wrap_pgn_comment(
                        texto,
                        wrap_columns,
                        _comment_line_room(content, start, wrap_columns),
                    )
                    # A quebra tem de ser a DO ARQUIVO. O conteudo foi lido com
                    # `newline=''` justamente para o `\r\n` do original sobreviver
                    # (ROADMAP 13.6); inserir `\n` puro no meio de um arquivo CRLF
                    # produziria um PGN de fim de linha misturado — e a requebra,
                    # que existe para agradar editora, entregaria um arquivo pior
                    # do que o sem requebra.
                    if eol != "\n":
                        texto = texto.replace("\n", eol)
                repl = "{" + texto + "}"
                replacements.append((start, end, repl))
                fim_anterior = end

        # Uma passada, gravando pedaco por pedaco (ROADMAP 20.1). O laco anterior
        # refazia o arquivo INTEIRO a cada comentario (`content[:start] + rep +
        # content[end:]`), da direita para a esquerda: 15 mil comentarios num PGN
        # de 3,2 MB custavam 27 s de copia de memoria, e o custo cresce com o
        # PRODUTO dos dois — num livro de 40 MB sao centenas de GB copiados.
        #
        # Direto para o arquivo, e nao por um `"".join`: juntar produziria o PGN de
        # saida inteiro na memoria ao lado do de entrada, e num livro de 9 MB isso
        # media 8 MB de pico a mais do que a versao lenta gastava. O tempo era o
        # problema do item; trocar tempo por pico seria consertar metade.
        def pedacos():
            ultimo = 0
            for inicio, fim, texto in replacements:
                yield content[ultimo:inicio]
                yield texto
                ultimo = fim
            yield content[ultimo:]

        write_pgn_pieces(output_file, pedacos, enc, log_message, use_bom=use_bom)
        return True

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao gravar PGN traduzido: {e}")
        return False
