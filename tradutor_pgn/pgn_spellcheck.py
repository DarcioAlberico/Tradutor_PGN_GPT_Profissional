import hashlib
import os
import re
import sqlite3
from pathlib import Path

from .pgn_utils import available_output_path, read_pgn_text, write_translated_pgn


DEFAULT_SPELLING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "spelling_ssp",
    "spelling.ssp",
)
# O indice derivado do `spelling.ssp` (ROADMAP 20.5). Fica ao lado do fonte, com
# o mesmo desenho do `glossario.db`: reconstruido quando o hash do fonte muda.
#
# Ao contrario do `glossario.db`, ele NAO e versionado, e a diferenca e de
# tamanho: o indice do glossario tem 1,1 MB e viaja junto para que um clone nao
# precise reconstrui-lo, e este tem 25,5 MB para uma construcao de 2 s. Cada
# maquina o constroi na primeira normalizacao e o reaproveita depois. O `*.db` do
# `.gitignore` ja o mantem fora; o `!glossario.db` e a unica excecao.
SPELLING_DB_FILENAME = "spelling.db"
# Sobe quando a forma do indice muda. Um banco gravado por uma versao anterior e
# descartado e reconstruido em vez de consultado com o esquema errado.
SPELLING_DB_SCHEMA_VERSION = 1
# Quantas entradas por `executemany`. O arquivo tem 985 mil linhas e 514 mil
# entradas: acumular tudo numa lista antes de gravar seria pagar de novo a
# memoria que este indice existe para nao gastar.
_SPELLING_INSERT_CHUNK = 20000
NORMALIZED_SUFFIX = "-NORM"
# O `-\d+` opcional e o sufixo de colisao de `available_output_path`. Sem ele
# `game-NORM-2.pgn` nao era reconhecido como saida do normalizador e voltava como
# ENTRADA na varredura seguinte, virando `game-NORM-2-NORM.pgn` — o mesmo defeito
# que `strip_generated_suffix` tinha com `-BR-2`.
NORMALIZED_NAME_RE = re.compile(
    re.escape(NORMALIZED_SUFFIX) + r"(-\d+)?$", re.IGNORECASE
)
# Quais tags o "Normalizar PGN" corrige, e em que secao do spelling.ssp cada uma
# procura. Fonte unica: o `PGN_TAG_RE` abaixo e DERIVADO daqui.
#
# A lista ja esteve escrita duas vezes — aqui e a mao dentro do regex — e as duas
# copias falhavam em silencio ao divergir, cada uma de um jeito: acrescentar uma
# tag so neste dict nao tinha efeito nenhum (o regex nunca casava a linha), e
# acrescentar so no regex levantava `KeyError` no `SUPPORTED_TAGS[tag_name]`,
# derrubando a normalizacao de qualquer PGN que tivesse aquela tag. Nenhum dos
# dois erros e visivel ao ler so um dos lados.
SUPPORTED_TAGS = {
    "White": "PLAYER",
    "Black": "PLAYER",
    "Site": "SITE",
    "Event": "EVENT",
    "Round": "ROUND",
}
SECTION_RE = re.compile(r'^@(\w+)\s+"([^"]*)"')
PGN_TAG_RE = re.compile(
    r'^(\['
    + "(" + "|".join(re.escape(tag) for tag in sorted(SUPPORTED_TAGS)) + ")"
    + r'\s+")((?:\\.|[^"\\])*)("\]\s*)$'
)
QUOTED_PAIR_RE = re.compile(r'"([^"]*)"\s+"([^"]*)"')


def is_normalized_pgn(file_path):
    name, ext = os.path.splitext(os.path.basename(file_path))
    return ext.lower() == ".pgn" and NORMALIZED_NAME_RE.search(name) is not None


def normalized_output_path(input_file):
    file_dir = os.path.dirname(input_file)
    name, ext = os.path.splitext(os.path.basename(input_file))
    if NORMALIZED_NAME_RE.search(name):
        output_file = os.path.join(file_dir, f"{name}-novo{ext}")
    else:
        output_file = os.path.join(file_dir, f"{name}{NORMALIZED_SUFFIX}{ext}")
    return available_output_path(output_file)


def collect_spellcheck_pgn_files(source_path, process_subdirs):
    pgn_files = []
    skipped_normalized = 0

    def add_file(path, allow_normalized=False):
        nonlocal skipped_normalized
        if not path.lower().endswith(".pgn"):
            return
        if not allow_normalized and is_normalized_pgn(path):
            skipped_normalized += 1
            return
        pgn_files.append(path)

    if os.path.isfile(source_path):
        add_file(source_path, allow_normalized=True)
    elif process_subdirs:
        for root, _, files in os.walk(source_path):
            for filename in files:
                add_file(os.path.join(root, filename))
    else:
        for filename in os.listdir(source_path):
            add_file(os.path.join(source_path, filename))

    return sorted(pgn_files), skipped_normalized


def strip_ssp_comment(line):
    return line.split("#", 1)[0].strip()


def normalize_spell_key(value, ignore_chars):
    normalized = value.strip()
    for char in ignore_chars:
        normalized = normalized.replace(char, "")
    return normalized.casefold()


def iter_spelling_records(path=DEFAULT_SPELLING_PATH):
    """Percorre o `spelling.ssp` uma vez e emite o que cada linha declara.

    Existe para que a leitura do formato exista UMA vez e sirva aos dois
    consumidores: o dicionario em memoria (`parse_spelling_file`) e o indice
    SQLite (`build_spelling_index`, ROADMAP 20.5). Duas leituras do mesmo formato
    e a situacao que `SUPPORTED_TAGS` descreve — duas copias que falham em
    silencio ao divergir —, e aqui a divergencia seria pior: o indice
    responderia diferente do arquivo, e ninguem compara os dois.

    Emite tuplas `(tipo, secao, a, b)`:

    - `("section", NOME, ignore_chars, None)` quando um bloco `@SECAO "chars"`
      comeca;
    - `("entry", NOME, chave_normalizada, canonico)` para cada nome e cada
      apelido `=`;
    - `("prefix"|"suffix", NOME, de, para)` para as regras de afixo.

    A chave sai daqui **ja normalizada**, com o `ignore_chars` que valia naquele
    ponto do arquivo: e o que preserva a semantica de um bloco repetido mudar o
    parametro sem reescrever as chaves de cima.

    E um gerador de proposito: um `spelling.ssp` de 30 MB e 985 mil linhas nao
    cabe numa lista de eventos sem gastar a memoria que 20.5 economiza.
    """
    current_section = None
    current_canonical = None
    ignore_chars = ""

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            section_match = SECTION_RE.match(line)
            if section_match:
                current_section = section_match.group(1).upper()
                ignore_chars = section_match.group(2)
                current_canonical = None
                yield ("section", current_section, ignore_chars, None)
                continue

            if current_section is None:
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("%Bio"):
                continue

            if stripped.startswith("%Prefix"):
                pair = QUOTED_PAIR_RE.search(stripped)
                if pair:
                    yield ("prefix", current_section, pair.group(1), pair.group(2))
                continue

            if stripped.startswith("%Suffix"):
                pair = QUOTED_PAIR_RE.search(stripped)
                if pair:
                    yield ("suffix", current_section, pair.group(1), pair.group(2))
                continue

            if stripped.startswith("="):
                if current_canonical is None:
                    continue
                alias = strip_ssp_comment(stripped[1:])
                if alias:
                    yield (
                        "entry",
                        current_section,
                        normalize_spell_key(alias, ignore_chars),
                        current_canonical,
                    )
                continue

            if line[:1].isspace():
                continue

            canonical = strip_ssp_comment(line)
            if not canonical:
                current_canonical = None
                continue

            current_canonical = canonical
            yield (
                "entry",
                current_section,
                normalize_spell_key(canonical, ignore_chars),
                canonical,
            )


def _empty_section(ignore_chars=""):
    return {
        "entries": {},
        "ignore_chars": ignore_chars,
        "prefix_rules": [],
        "suffix_rules": [],
    }


def parse_spelling_file(path=DEFAULT_SPELLING_PATH):
    """Le o `spelling.ssp` em `{secao: {entries, ignore_chars, prefix/suffix}}`.

    **Uma secao repetida ACRESCENTA, e nao substitui.** Antes era uma atribuicao,
    e o jeito natural de acrescentar nomes ao arquivo — abrir um segundo bloco
    `@PLAYER` no fim — apagava as 984 mil entradas do bloco anterior sem uma
    linha de aviso. O usuario acrescentava dez nomes e perdia o dicionario.

    Os apelidos continuam entrando por `setdefault` dentro de cada secao (o
    primeiro a definir uma chave vence), e o merge preserva isso entre blocos: o
    bloco de cima continua tendo precedencia sobre o de baixo, que e a mesma
    regra de dentro de um bloco so.

    `ignore_chars` do bloco repetido substitui o do anterior de proposito: e um
    parametro do bloco, e nao uma lista para acumular. Ele vale para as chaves
    normalizadas dali em diante — as ja gravadas ficam como estao, porque a
    normalizacao delas ja aconteceu (ver `iter_spelling_records`).

    Custa 1,0 s e 72 MB de pico com o dicionario real, e e por isso que a
    normalizacao passou a preferir o indice SQLite (ROADMAP 20.5). Continua
    existindo porque e a definicao do formato em memoria, e o caminho de
    degradacao quando o indice nao pode ser gravado.
    """
    sections = {}

    for tipo, secao, a, b in iter_spelling_records(path):
        if tipo == "section":
            sections.setdefault(secao, _empty_section(a))["ignore_chars"] = a
        elif tipo == "entry":
            sections[secao]["entries"].setdefault(a, b)
        elif tipo == "prefix":
            sections[secao]["prefix_rules"].append((a, b))
        elif tipo == "suffix":
            sections[secao]["suffix_rules"].append((a, b))

    return sections


def default_spelling_db_path(spelling_path=DEFAULT_SPELLING_PATH):
    """O indice fica ao lado do fonte, e nao numa pasta de cache do sistema.

    E a mesma escolha do `glossario.db`: o derivado mora junto do que o gerou,
    entao apagar um e obvio quando se apaga o outro, e ninguem procura por um
    cache invisivel quando quer forcar a reconstrucao.
    """
    return os.path.join(os.path.dirname(os.path.abspath(spelling_path)),
                        SPELLING_DB_FILENAME)


def spelling_source_fingerprint(path):
    """Hash do conteudo do fonte, para saber se o indice ainda vale.

    Pelo conteudo, e nao pelo `mtime`, pela mesma razao do glossario: o `mtime`
    muda quando o arquivo e reescrito igual, e nao muda quando outro arquivo com
    o mesmo nome toma o lugar dele com a mesma data. Aqui ha um segundo motivo — o
    `spelling.ssp` e substituido a mao por versoes novas das classificacoes, e o
    hash e o que garante que a troca seja notada.

    Custa 21 ms nos 30 MB do dicionario real, contra 1,0 s de reparse: vale
    conferir a cada uso.
    """
    if not os.path.exists(path):
        return ""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for bloco in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(bloco)
    return hasher.hexdigest()


_SPELLING_TABLES = (
    "spelling_sections",
    "spelling_entries",
    "spelling_affixes",
    "spelling_metadata",
)


def _reset_spelling_db(db_path):
    """Devolve uma conexao com o banco vazio, pronto para receber o indice.

    Zera por `DROP TABLE`, e **nao** apagando o arquivo. Apagar era o obvio e
    estava errado: no Windows, remover um `.db` que outra conexao mantem aberto
    falha, o `except OSError` engolia a falha, e o indice novo era gravado POR
    CIMA do antigo — com os nomes que ja tinham saido do fonte continuando a
    responder. Quem mostrou isso foi o teste da troca do fonte, e o defeito era
    exatamente o que o hash existe para evitar.

    Um arquivo que nao e banco nenhum — truncado, corrompido, meio gravado — nao
    tem tabela para derrubar. Nesse caso ele e apagado e a abertura recomeca, uma
    vez so: se falhar de novo, quem chamou degrada para o dicionario com aviso.
    """
    for ultima_tentativa in (False, True):
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                "".join(f"DROP TABLE IF EXISTS {t};" for t in _SPELLING_TABLES)
            )
            _initialize_spelling_db(conn)
            return conn
        except sqlite3.DatabaseError:
            conn.close()
            if ultima_tentativa:
                raise
            _remove_spelling_db(db_path)


def _initialize_spelling_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS spelling_sections (
            section TEXT PRIMARY KEY,
            ignore_chars TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS spelling_entries (
            section TEXT NOT NULL,
            key TEXT NOT NULL,
            canonical TEXT NOT NULL,
            PRIMARY KEY (section, key)
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS spelling_affixes (
            section TEXT NOT NULL,
            kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            old_text TEXT NOT NULL,
            new_text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spelling_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def build_spelling_index(spelling_path=DEFAULT_SPELLING_PATH, db_path=None,
                         log_message=None):
    """Constroi o indice SQLite do `spelling.ssp`. Devolve o caminho do banco.

    A gravacao e em fluxo: os eventos de `iter_spelling_records` viram `INSERT` em
    blocos, e o dicionario inteiro nunca existe na memoria — que e metade do
    ganho de 20.5 (o reparse custava 72 MB de pico para normalizar um PGN de
    20 KB).

    `INSERT OR IGNORE` sobre a chave `(section, key)` reproduz o `setdefault` do
    dicionario: **o primeiro a definir uma chave vence**, dentro do bloco e entre
    blocos repetidos. Sem isso, um `@PLAYER` no fim do arquivo passaria a
    sobrescrever os nomes do bloco de cima — o defeito que `parse_spelling_file`
    documenta, de volta pela porta do indice.

    O `source_hash` e gravado **por ultimo**, e de proposito: uma construcao
    interrompida deixa um banco sem a marca, que a carga seguinte trata como
    invalido e refaz. E a mesma escolha da reavaliacao de qualidade (Q2) — a
    marca significa "isto terminou".
    """
    if db_path is None:
        db_path = default_spelling_db_path(spelling_path)

    if log_message:
        log_message(
            f"Construindo o indice de {os.path.basename(spelling_path)} "
            f"(so nesta vez; depois ele e reaproveitado)..."
        )

    # Do zero: o indice e derivado, e reaproveitar um banco antigo exigiria saber
    # o que mudou no fonte — que e exatamente o que o hash NAO diz.
    conn = _reset_spelling_db(db_path)
    try:
        conn.execute("BEGIN")
        secoes = {}
        afixos = []
        lote = []
        total = 0
        for tipo, secao, a, b in iter_spelling_records(spelling_path):
            if tipo == "section":
                secoes[secao] = a
            elif tipo == "entry":
                lote.append((secao, a, b))
                if len(lote) >= _SPELLING_INSERT_CHUNK:
                    total += _insert_spelling_entries(conn, lote)
                    lote = []
            else:
                afixos.append((secao, tipo, len(afixos), a, b))
        total += _insert_spelling_entries(conn, lote)
        # As linhas que de fato entraram, e nao as que foram tentadas: o
        # dicionario real tem 4.495 chaves repetidas, e o `INSERT OR IGNORE`
        # descarta a segunda de cada uma. Contar as tentativas daria um numero
        # que nao existe em lugar nenhum — nem no arquivo, nem no banco.
        gravadas = conn.total_changes

        conn.executemany(
            "INSERT OR REPLACE INTO spelling_sections (section, ignore_chars) "
            "VALUES (?, ?)",
            list(secoes.items()),
        )
        conn.executemany(
            "INSERT INTO spelling_affixes (section, kind, position, old_text, "
            "new_text) VALUES (?, ?, ?, ?, ?)",
            afixos,
        )
        _set_spelling_metadata(conn, "schema_version", SPELLING_DB_SCHEMA_VERSION)
        _set_spelling_metadata(conn, "entry_count", gravadas)
        _set_spelling_metadata(
            conn, "source_hash", spelling_source_fingerprint(spelling_path)
        )
        conn.commit()
    finally:
        conn.close()

    if log_message:
        repetidas = total - gravadas
        sufixo = f" ({repetidas} chaves repetidas ignoradas)" if repetidas else ""
        log_message(
            f"Indice pronto: {gravadas} entradas em {SPELLING_DB_FILENAME}{sufixo}."
        )
    return db_path


def _insert_spelling_entries(conn, lote):
    if not lote:
        return 0
    conn.executemany(
        "INSERT OR IGNORE INTO spelling_entries (section, key, canonical) "
        "VALUES (?, ?, ?)",
        lote,
    )
    return len(lote)


def _set_spelling_metadata(conn, key, value):
    conn.execute(
        """
        INSERT INTO spelling_metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def _remove_spelling_db(db_path):
    """Apaga o banco e os auxiliares do WAL, se existirem."""
    for sufixo in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(db_path + sufixo)
        except OSError:
            pass


class SpellingIndex:
    """O `spelling.ssp` consultado por chave, sem o arquivo na memoria.

    Responde as mesmas duas perguntas que o dicionario de `parse_spelling_file`
    responde, e e por isso que `correct_spelling_value` aceita os dois sem saber
    qual tem na mao:

    - `get(secao)` -> os parametros do bloco (`ignore_chars` e as regras de
      afixo). Sao poucos por secao, entao vem todos na abertura;
    - `entry(secao, chave)` -> o nome canonico, com um `SELECT` na chave
      primaria. Sao 514 mil entradas, e ler as 514 mil para corrigir cinco tags
      de um PGN e o desperdicio que 20.5 elimina.

    Nao e um `dict`, e nao finge ser: quem itera o dicionario inteiro tem de
    continuar chamando `parse_spelling_file`.
    """

    def __init__(self, conn, db_path=None):
        self._conn = conn
        self.db_path = db_path
        self._sections = {}
        for section, ignore_chars in conn.execute(
            "SELECT section, ignore_chars FROM spelling_sections"
        ):
            self._sections[section] = _empty_section(ignore_chars)
        for section, kind, old_text, new_text in conn.execute(
            "SELECT section, kind, old_text, new_text FROM spelling_affixes "
            "ORDER BY position"
        ):
            secao = self._sections.setdefault(section, _empty_section())
            secao[f"{kind}_rules"].append((old_text, new_text))

    def get(self, section_name, default=None):
        return self._sections.get(section_name, default)

    def entry(self, section_name, key):
        row = self._conn.execute(
            "SELECT canonical FROM spelling_entries WHERE section = ? AND key = ?",
            (section_name, key),
        ).fetchone()
        return row[0] if row else None

    def close(self):
        self._conn.close()


def spelling_index_is_stale(spelling_path, db_path):
    """O indice precisa ser reconstruido?

    Vale para: banco inexistente, esquema de outra versao, marca de conclusao
    ausente (construcao interrompida) e fonte com outro conteudo. Qualquer
    excecao ao abrir tambem conta como "precisa reconstruir" — um arquivo
    corrompido nao pode ser motivo de o botao deixar de funcionar.
    """
    if not os.path.exists(db_path):
        return True
    try:
        # Somente leitura, e pela URI que o `pathlib` escapa: o caminho deste
        # projeto tem espaco ("Python Course"), e uma URI montada com `f"file:{...}"`
        # depende de o caminho nao ter nada que o SQLite leia como parametro.
        uri = Path(os.path.abspath(db_path)).as_uri()
        conn = sqlite3.connect(f"{uri}?mode=ro", uri=True)
    except (sqlite3.Error, ValueError):
        return True
    try:
        marcas = dict(
            conn.execute("SELECT key, value FROM spelling_metadata").fetchall()
        )
    except sqlite3.Error:
        return True
    finally:
        conn.close()

    if marcas.get("schema_version") != str(SPELLING_DB_SCHEMA_VERSION):
        return True
    # A construcao interrompida cai nesta mesma linha, e nao numa guarda propria:
    # sem a marca, `get` devolve `None`, que nunca e igual a um hash. Havia uma
    # guarda separada para ela, e a rodada de mutacao mostrou que era redundante —
    # apagar a guarda nao deixava nenhum teste vermelho porque a comparacao ja
    # respondia "precisa reconstruir".
    return marcas.get("source_hash") != spelling_source_fingerprint(spelling_path)


def load_spelling_data(spelling_path=DEFAULT_SPELLING_PATH, db_path=None,
                       log_message=None, use_index=True):
    """O dicionario de grafias: o indice SQLite quando da, o dicionario quando nao.

    Devolve `SpellingIndex` no caminho normal. Cai para `parse_spelling_file`
    quando o indice nao pode ser construido nem lido — disco sem permissao de
    escrita (o `_internal` do executavel numa pasta protegida), banco corrompido,
    SQLite reclamando de algo. O botao continua funcionando; volta a custar 1,0 s
    e 72 MB por uso, que era o custo de sempre.

    `use_index=False` pede o dicionario direto, sem tocar em disco. E o que os
    testes do formato usam.
    """
    if not use_index:
        return parse_spelling_file(spelling_path)

    if db_path is None:
        db_path = default_spelling_db_path(spelling_path)

    try:
        if spelling_index_is_stale(spelling_path, db_path):
            build_spelling_index(spelling_path, db_path, log_message=log_message)
        conn = sqlite3.connect(db_path)
        return SpellingIndex(conn, db_path)
    except (sqlite3.Error, OSError) as exc:
        if log_message:
            log_message(
                f"[AVISO] Nao foi possivel usar o indice {SPELLING_DB_FILENAME} "
                f"({exc}). Lendo o dicionario direto do arquivo, que e mais lento."
            )
        _remove_spelling_db(db_path)
        return parse_spelling_file(spelling_path)


def close_spelling_data(spelling_data):
    """Fecha o indice, se for um. Um dicionario nao tem o que fechar."""
    fechar = getattr(spelling_data, "close", None)
    if fechar is not None:
        fechar()


def apply_affix_rules(value, section_data):
    result = value.strip()
    for old, new in section_data.get("prefix_rules", []):
        if result.startswith(old):
            result = new + result[len(old):]
    for old, new in section_data.get("suffix_rules", []):
        if result.endswith(old):
            result = result[: len(result) - len(old)] + new
    return result


def player_name_variants(value):
    variants = [value]
    cleaned = value.strip()
    if " " in cleaned and "," not in cleaned:
        before, after = cleaned.rsplit(" ", 1)
        variants.append(f"{after}, {before}")
    return variants


def _spelling_entry(spelling_data, section_name, section_data, key):
    """O canonico de uma chave, venha ele do indice ou do dicionario.

    Pelo metodo `entry` quando existe, e nao por `isinstance`: e o que permite ao
    teste passar um dicionario literal — como todos os do formato fazem — sem
    conhecer o `SpellingIndex`, e ao programa consultar o indice sem carregar o
    arquivo (ROADMAP 20.5).
    """
    buscar = getattr(spelling_data, "entry", None)
    if buscar is not None:
        return buscar(section_name, key)
    return section_data.get("entries", {}).get(key)


def correct_spelling_value(value, section_name, spelling_data):
    section_data = spelling_data.get(section_name)
    if not section_data:
        return value

    prepared = apply_affix_rules(value, section_data)
    variants = player_name_variants(prepared) if section_name == "PLAYER" else [prepared]
    ignore_chars = section_data.get("ignore_chars", "")

    for variant in variants:
        key = normalize_spell_key(variant, ignore_chars)
        corrected = _spelling_entry(spelling_data, section_name, section_data, key)
        if corrected:
            return corrected

    return value


def unescape_pgn_tag_value(value):
    """`O\\"Kelly` -> `O"Kelly`. O inverso de `escape_pgn_tag_value`.

    O valor lido do PGN vem escapado (o padrao PGN escapa `"` e `\\` com
    barra), e e nessa forma que ele era comparado com o dicionario — onde os
    nomes estao escritos como se escreve, sem barra. Um nome com apostrofo duplo
    nunca casava.
    """
    return re.sub(r'\\(.)', r'\1', value or "")


def escape_pgn_tag_value(value):
    """Poe de volta as barras que o padrao PGN exige dentro de `[Tag "..."]`.

    Sem isto, um valor canonico com `"` era inserido cru na linha e quebrava a
    tag: `[White "O"Kelly"]` nao e mais uma tag valida, e o dano nao aparece no
    programa que a escreveu — aparece no ChessBase de quem abre o arquivo. A
    barra vem primeiro, senao as barras recem-inseridas seriam escapadas de novo.
    """
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def normalize_pgn_metadata_content(content, spelling_data):
    changes = []
    updated_lines = []

    for line in content.splitlines(keepends=True):
        newline = ""
        body = line
        if body.endswith("\r\n"):
            body = body[:-2]
            newline = "\r\n"
        elif body.endswith("\n"):
            body = body[:-1]
            newline = "\n"

        match = PGN_TAG_RE.match(body)
        if not match:
            updated_lines.append(line)
            continue

        prefix, tag_name, raw_value, suffix = match.groups()
        section_name = SUPPORTED_TAGS[tag_name]
        # O dicionario fala na forma que se escreve, e o arquivo na forma
        # escapada. A conversao acontece nas duas pontas — desescapar para
        # comparar, reescapar para gravar —, e nao so numa delas: corrigir a
        # entrada sem reescapar a saida foi como um `"` no valor canonico passou a
        # poder quebrar a tag.
        value = unescape_pgn_tag_value(raw_value)
        corrected = correct_spelling_value(value, section_name, spelling_data)
        if corrected != value:
            changes.append(
                {
                    "tag": tag_name,
                    "previous": value,
                    "new": corrected,
                }
            )
            body = f"{prefix}{escape_pgn_tag_value(corrected)}{suffix}"

        updated_lines.append(body + newline)

    return "".join(updated_lines), changes


def normalize_pgn_metadata_file(input_file, spelling_data, output_file=None, log_message=None):
    # `read_pgn_text` le o arquivo uma vez e detecta a codificacao nos bytes que
    # leu (ROADMAP 20.2); antes eram duas leituras, uma para detectar e outra para
    # ler. Ele nao traduz fim de linha, e e isso que torna real o cuidado de
    # `normalize_pgn_metadata_content` com o `\r\n`: com universal newlines, todo
    # `\r\n` ja chegava convertido e aquele tratamento era codigo morto — e a
    # escrita devolvia o fim de linha DA PLATAFORMA, nao o do arquivo
    # (ROADMAP 13.6).
    content, enc = read_pgn_text(input_file)

    updated_content, changes = normalize_pgn_metadata_content(content, spelling_data)
    if not changes:
        return {
            "input_file": input_file,
            "output_file": None,
            "changed": False,
            "changes": [],
        }

    output_file = output_file or normalized_output_path(input_file)
    output_encoding = write_translated_pgn(output_file, updated_content, enc, log_message)
    return {
        "input_file": input_file,
        "output_file": output_file,
        "changed": True,
        "changes": changes,
        "encoding": output_encoding,
    }


def normalize_pgn_metadata_path(
    source_path,
    process_subdirs=False,
    spelling_path=DEFAULT_SPELLING_PATH,
    log_message=None,
    progress_callback=None,
):
    if not os.path.exists(spelling_path):
        raise FileNotFoundError(f"Arquivo spelling.ssp nao encontrado: {spelling_path}")

    if log_message:
        # "Dicionario", e nao "spelling.ssp": com o indice, o arquivo so e lido
        # quando ele precisa ser reconstruido, e ai a proxima linha do log diz
        # isso. Anunciar a leitura de um arquivo que nao vai ser lido e mentira
        # pequena, mas e mentira no unico lugar onde o usuario procura o motivo de
        # uma demora.
        log_message("Carregando o dicionario de grafias...")
    # Pelo indice (ROADMAP 20.5). A primeira normalizacao desta maquina paga a
    # construcao; as seguintes abrem o banco em milissegundos, e nenhuma delas
    # carrega as 514 mil entradas na memoria para corrigir cinco tags.
    spelling_data = load_spelling_data(spelling_path, log_message=log_message)
    try:
        return _normalize_pgn_metadata_files(
            source_path, process_subdirs, spelling_data, log_message,
            progress_callback,
        )
    finally:
        # O indice e uma conexao aberta; sem isto o arquivo fica preso ao
        # processo, e no Windows um `spelling.db` preso nao pode ser substituido.
        close_spelling_data(spelling_data)


def _normalize_pgn_metadata_files(
    source_path,
    process_subdirs,
    spelling_data,
    log_message,
    progress_callback,
):
    """A varredura em si, com o dicionario ja carregado.

    Separada de `normalize_pgn_metadata_path` para que o `finally` que fecha o
    indice caiba numa linha e nao dependa de cada `return` do meio do laco se
    lembrar dele.
    """
    pgn_files, skipped_normalized = collect_spellcheck_pgn_files(
        source_path,
        process_subdirs,
    )
    stats = {
        "files": len(pgn_files),
        "changed_files": 0,
        "unchanged_files": 0,
        "changes": 0,
        "skipped_normalized": skipped_normalized,
        "outputs": [],
        # Arquivos que levantaram, com o motivo. Existem porque um unico PGN
        # ilegivel — permissao negada, arquivo em uso pelo ChessBase, disco cheio
        # na gravacao — derrubava o LOTE INTEIRO: a excecao subia daqui ate o
        # `except` da interface, que mostrava "Erro ao normalizar PGN" e nenhuma
        # estatistica. Os arquivos ja corrigidos ficavam em disco sem que nada
        # dissesse quais eram, e os seguintes nunca eram tentados.
        "failed": [],
    }

    for index, pgn_file in enumerate(pgn_files, start=1):
        try:
            result = normalize_pgn_metadata_file(
                pgn_file,
                spelling_data,
                log_message=log_message,
            )
        except Exception as exc:
            stats["failed"].append({"file": pgn_file, "error": str(exc)})
            if log_message:
                log_message(f"  - [FALHA] {os.path.basename(pgn_file)}: {exc}")
            if progress_callback and stats["files"]:
                progress_callback(index / stats["files"])
            continue

        if result["changed"]:
            stats["changed_files"] += 1
            stats["changes"] += len(result["changes"])
            stats["outputs"].append(result["output_file"])
            if log_message:
                log_message(
                    f"  - {os.path.basename(pgn_file)}: "
                    f"{len(result['changes'])} correcao(oes) -> "
                    f"{os.path.basename(result['output_file'])}"
                )
        else:
            stats["unchanged_files"] += 1
            if log_message:
                log_message(f"  - {os.path.basename(pgn_file)}: sem alteracoes")

        if progress_callback and stats["files"]:
            progress_callback(index / stats["files"])

    return stats
