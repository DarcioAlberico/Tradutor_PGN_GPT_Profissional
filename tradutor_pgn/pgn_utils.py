import os
import re

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


def output_suffix_for_language(target_language: str) -> str:
    return LANGUAGE_OUTPUT_SUFFIXES.get(target_language, target_language.upper())


def strip_generated_suffix(filename_without_ext: str) -> str:
    suffixes = "|".join(re.escape(s) for s in LANGUAGE_OUTPUT_SUFFIXES.values())
    return re.sub(rf"-({suffixes})$", "", filename_without_ext, flags=re.IGNORECASE)


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


def extract_comments_from_file(pgn_file: str, log_message=None):
    comments = []
    positions = []
    comment_pattern = re.compile(r'\{(.*?)\}', re.DOTALL)

    try:
        enc = detect_encoding(pgn_file)
        if log_message:
            log_message(f"Arquivo: {os.path.basename(pgn_file)} | Codificacao detectada: {enc}")

        # `newline=''` preserva o `\r\n` no conteudo: as posicoes extraidas aqui
        # sao offsets NESTE texto, e a geracao rele o arquivo do mesmo jeito —
        # com universal newlines, todo PGN de saida trocava o fim de linha da
        # plataforma em silencio (ROADMAP 13.6). Dentro dos comentarios o
        # `flatten_comment` colapsa qualquer `\r` junto com o resto do espaco.
        with open(pgn_file, 'r', encoding=enc, errors='replace', newline='') as f:
            content = f.read()

        for match in comment_pattern.finditer(content):
            normalized = flatten_comment(match.group(1))
            if not normalized:
                continue

            comments.append(normalized)
            positions.append((match.start(), match.end(), normalized))

        return {
            "comments": comments,
            "positions": positions,
            "semicolon_comments": count_semicolon_comments(content),
        }

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao extrair comentarios de {pgn_file}: {e}")
        return {"comments": [], "positions": [], "semicolon_comments": 0}


BATCH_SEPARATOR = " ||| "
_SEP_LEN = len(BATCH_SEPARATOR)

# Precisa ser estritamente menor que MAX_TRANSLATE_CHARS: se um lote passasse do
# limite da camada de API, ela o dividiria por sentenca e poderia cortar no meio
# de um separador, tornando o realinhamento impossivel (garantia B1 da SPEC.md).
BATCH_MAX_CHARS = MAX_TRANSLATE_CHARS - 200


def create_comment_batches(comments, max_chars=BATCH_MAX_CHARS):
    batches = []
    current = []
    length = 0

    for comment in comments:
        l = len(comment)
        # Account for separator that will be inserted between items
        extra = _SEP_LEN if current else 0
        if l > max_chars:
            if current:
                batches.append(current)
            batches.append([comment])
            current = []
            length = 0
        elif length + extra + l > max_chars:
            batches.append(current)
            current = [comment]
            length = l
        else:
            current.append(comment)
            length += extra + l

    if current:
        batches.append(current)

    return batches


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


def _output_encoding(preferred_encoding: str, use_bom: bool) -> str:
    """A codificacao de gravacao, honrando a opcao de BOM.

    A opcao existe por causa do consumidor: um PGN ASCII de entrada sai UTF-8
    quando a traducao introduz acentos, e UTF-8 **sem BOM** o ChessBase do
    Windows le como ANSI — mojibake (ROADMAP 13.6). So mexe em UTF-8: um BOM
    nao significa nada em cp1252, e `utf-8-sig` ja o escreve sozinho.
    """
    if not use_bom:
        return preferred_encoding
    if preferred_encoding.lower().replace("-", "").replace("_", "") == "utf8":
        return "utf-8-sig"
    return preferred_encoding


def write_translated_pgn(
    output_file: str,
    content: str,
    preferred_encoding: str,
    log_message=None,
    use_bom: bool = False,
):
    # `newline=''` nos dois caminhos: o conteudo carrega o fim de linha do
    # arquivo original (lido tambem com `newline=''`), e a escrita nao pode
    # troca-lo pelo da plataforma (ROADMAP 13.6).
    try:
        enc = _output_encoding(preferred_encoding, use_bom)
        with open(output_file, 'w', encoding=enc, newline='') as f:
            f.write(content)
        return enc
    except UnicodeEncodeError:
        enc = _output_encoding('utf-8', use_bom)
        with open(output_file, 'w', encoding=enc, newline='') as f:
            f.write(content)
        if log_message:
            log_message(f"  - Codificacao de saida alterada para UTF-8: {output_file}")
        return enc


def generate_translated_pgn(
    input_file,
    output_file,
    translated_map,
    positions,
    log_message=None,
    use_bom=False,
):
    try:
        enc = detect_encoding(input_file)
        with open(input_file, 'r', encoding=enc, errors='replace', newline='') as f:
            content = f.read()

        replacements = []
        for start, end, norm in positions:
            if norm not in translated_map:
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
                elif start > 0 and content[start - 1] in " \t":
                    start -= 1
                replacements.append((start, end, ""))
            else:
                repl = "{" + sanitize_pgn_comment(translated) + "}"
                replacements.append((start, end, repl))

        replacements.sort(reverse=True, key=lambda x: x[0])

        for start, end, rep in replacements:
            content = content[:start] + rep + content[end:]

        write_translated_pgn(output_file, content, enc, log_message, use_bom=use_bom)
        return True

    except Exception as e:
        if log_message:
            log_message(f"[ERRO] Falha ao gravar PGN traduzido: {e}")
        return False
