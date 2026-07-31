import os
import re
import sqlite3

from .review_quality import QUALITY_HEURISTICS_VERSION, evaluate_translation_quality
from .word_count import add_word_counts, count_words, total_word_counts


# Incrementar sempre que o schema mudar. Enquanto o PRAGMA user_version do
# arquivo bater com este valor, initialize_database pula toda a migracao.
#
# A versao 5 nao muda coluna nenhuma: e uma migracao de DADOS — as chaves de
# cache gravadas com o achatamento antigo, que inseria espaco em `0.35`
# (ROADMAP 13.2). Ela precisa da versao pelo mesmo motivo das outras: rodar
# uma vez, e nunca sobre um banco que ja passou por ela — um `0. 35` inserido
# DEPOIS da correcao e um espaco que estava no PGN de origem, e colapsa-lo
# seria reescrever texto do usuario.
#
# A versao 6 acrescenta a tabela `db_metadata`, que e onde a versao das
# heuristicas de qualidade passa a ser gravada (ROADMAP 16.2). Ela e uma tabela, e
# nao um PRAGMA, por dois motivos: `user_version` ja esta em uso pelo schema, e um
# `application_id` com numero de versao seria usar um campo que significa outra
# coisa. Uma tabela de chave/valor tambem aceita a proxima marca sem migracao
# nenhuma — e o mesmo desenho que o `glossario.db` ja usa.
#
# A versao 7 acrescenta a tabela `occurrences` (ROADMAP 18): onde cada comentario
# foi lido — arquivo, partida, indice e numero do lance. Ela e uma tabela AO LADO,
# e nao colunas em `comments`, porque a relacao e N para 1: o mesmo comentario em
# doze livros continua sendo uma linha, uma traducao e uma revisao, que e o que a
# `UNIQUE(original, origem, destino)` diz e o que o reuso do acervo vale. A
# migracao cria a tabela e mais nada — ver `_create_occurrences_table` para por
# que nao existe backfill.
# A versao 8 acrescenta `review_status` e `reviewer_note` (ROADMAP 19, item 12):
# "rejeitada" e "em duvida" nao caberiam no bit `verified`, e "voltar aqui com o
# autor" e a anotacao que hoje vive no caderno de quem revisa. Sao dois `ALTER
# TABLE` — nenhuma restricao muda, entao a tabela nao e reconstruida e a migracao
# custa o mesmo em 6.500 ou em 201.607 linhas.
SCHEMA_VERSION = 9

# Os estados que uma linha NAO verificada pode ter, alem de "pendente".
#
# **`verified` continua sendo a autoridade sobre verificada/pendente**, e este
# campo so refina o lado pendente. Guardar "verified" aqui tambem daria dois lugares
# dizendo a mesma coisa — e um dia eles discordariam, sem nada quebrar, que e a
# familia de defeito que a garantia R6 existe para nomear. Verificar uma linha LIMPA
# o status: uma traducao aceita nao esta "em duvida".
REVIEW_STATUS_PENDING = ""
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_DOUBT = "doubt"
REVIEW_STATUSES = (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_DOUBT,
)

# Idioma de origem de uma linha gravada antes de o programa perguntar qual era,
# e tambem o de uma execucao em que o usuario escolheu "detectar
# automaticamente". Os dois casos dizem a mesma coisa — nao se sabe de que
# idioma o comentario veio — e por isso compartilham o mesmo valor.
#
# E uma string vazia, e nao `NULL`, por uma razao que nao e de estilo: num indice
# UNIQUE o SQLite considera todo `NULL` DIFERENTE de qualquer outro, inclusive de
# outro `NULL`. Com `NULL` aqui, `UNIQUE(original, origem, destino)` deixaria de
# valer justamente para as linhas legadas — cada execucao inseriria de novo os
# mesmos comentarios, sem nada acusar.
SOURCE_LANGUAGE_UNKNOWN = ""

# Modos de busca do editor. Sao semanticas diferentes, e nenhuma substitui a
# outra — ver a garantia R8 na SPEC.
SEARCH_MODE_TERMS = "terms"          # indexado (FTS5): casa palavras inteiras
SEARCH_MODE_SUBSTRING = "substring"  # `LIKE '%x%'`: casa qualquer trecho
SEARCH_MODES = (SEARCH_MODE_TERMS, SEARCH_MODE_SUBSTRING)

FTS_TABLE = "comments_fts"

# O caractere de escape do `LIKE`. Precisa ser declarado na consulta
# (`ESCAPE '\'`) — o SQLite nao tem um padrao.
LIKE_ESCAPE_CHAR = "\\"

# Fragmento pronto para as duas colunas da busca por trecho. Fica aqui, e nao
# montado no lugar de uso, porque o `ESCAPE` e o padrao escapado sao um par: um
# sem o outro nao da erro nenhum, so volta a tratar o texto do usuario como
# curinga.
LIKE_MATCH_SQL = (
    f"(original_comment LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}'"
    f" OR translated_comment LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}')"
)


def escape_like_pattern(text):
    """Neutraliza os curingas do `LIKE` no texto digitado pelo usuario.

    `%` e `_` sao curingas, e sem isto o campo de busca era uma linguagem de
    padroes que ninguem documentou: a busca mais natural do dominio — `[%eval`,
    uma tag de comando do Lichess, que COMECA com `%` — casava toda linha que
    tivesse `[` seguido de qualquer coisa e `eval` em algum lugar, e devolvia
    lixo em vez de nada.

    A barra vem primeiro na lista de proposito. Escapando `%` antes dela, as
    barras recem-inseridas seriam escapadas de novo e o padrao passaria a
    procurar pela propria barra.
    """
    for char in (LIKE_ESCAPE_CHAR, "%", "_"):
        text = text.replace(char, LIKE_ESCAPE_CHAR + char)
    return text


def open_database(db_path):
    """Abre `db_path` no modo que o uso concorrente exige (garantia C3).

    O editor de traducoes e o worker usam o MESMO arquivo, cada um com sua
    conexao. Duas propriedades interessam aqui, e vale separar bem uma da outra:

    **Leitura.** No `journal_mode` padrao (`delete`) o leitor so e barrado
    enquanto o escritor esta no commit (lock EXCLUSIVE). Com transacoes curtas
    isso e curto, entao a leitura nunca foi o problema grave — quem escreveu
    `WAL` esperando consertar a leitura estava mirando no alvo errado. Em WAL o
    leitor simplesmente nunca espera, o que ainda assim e o comportamento
    desejado para uma janela de interface.

    **Escrita.** Essa e a que mordia. Duas conexoes nao escrevem ao mesmo tempo
    em modo nenhum, WAL inclusive: enquanto o worker mantiver transacao aberta,
    o "Salvar" do editor espera o `busy_timeout` (30 s) e depois falha. O que
    resolve isso nao e o modo do banco e sim nao segurar transacao aberta
    atravessando a rede — ver o commit por comentario em `translation_worker`.

    **`synchronous = NORMAL`** e o que torna aquele commit por comentario
    barato. Medido inserindo 300 linhas no banco real, comitando uma a uma:

        journal=delete synchronous=FULL     3,45 ms por traducao
        journal=wal    synchronous=NORMAL   0,14 ms por traducao

    Em WAL o fsync acontece no checkpoint, e nao em cada commit. Uma queda do
    SISTEMA pode custar as ultimas transacoes; uma queda do PROGRAMA, nao. Para
    um cache de traducoes que se reconstroi reexecutando, e a troca certa.
    """
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        # Mudar de modo exige lock exclusivo por um instante. Se outra conexao
        # estiver escrevendo agora, a troca falha — e tudo bem: o modo fica
        # gravado no arquivo, entao a proxima abertura que pegar o banco livre
        # resolve. Nao abrir o banco por causa disso seria pior que abrir sem
        # WAL.
        pass

    return conn


def quality_warning_flag(
    original,
    translated,
    source_language=None,
    target_language=None,
):
    """1 se a traducao tem algum aviso de qualidade, 0 caso contrario.

    Materializado na coluna `quality_warning` para que contar e paginar por
    "com aviso" seja uma consulta SQL, e nao uma varredura da tabela inteira em
    Python a cada troca de pagina. Precisa ser a MESMA funcao que a interface
    usa para exibir os avisos, senao a contagem diverge do que aparece na tela.

    **O par de idiomas nao e opcional na pratica.** A heuristica de terminologia
    depende dele (ROADMAP 16.1), entao gravar sem o par e exibir com ele — ou o
    contrario — faria a coluna divergir da tela sem nada quebrar, que e
    exatamente o que a garantia R6 proibe. Todo chamador daqui tem o par a mao:
    ou ele veio como argumento, ou esta na linha que ele acabou de ler.
    """
    return (
        1
        if evaluate_translation_quality(
            original, translated, source_language, target_language
        )
        else 0
    )


DB_METADATA_TABLE = "db_metadata"
QUALITY_VERSION_KEY = "quality_heuristics_version"

OCCURRENCES_TABLE = "occurrences"

# As duas ordens da lista do editor. `id` e a ordem de INSERCAO — a que sempre
# existiu, e que mistura todos os PGN ja processados. `occurrence` e a ordem de
# LEITURA de um arquivo, e so existe com um arquivo escolhido: sem ele, "a
# proxima linha da obra" nao quer dizer nada, e ordenar pelo minimo de cada
# comentario custaria uma agregacao da tabela inteira por pagina (garantia R5).
ORDER_BY_ID = "id"
ORDER_BY_OCCURRENCE = "occurrence"


def get_db_metadata(conn, key):
    """Valor da marca, ou `None`. Tolera o banco antes da migracao 6."""
    try:
        row = conn.execute(
            f"SELECT value FROM {DB_METADATA_TABLE} WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def set_db_metadata(conn, key, value):
    conn.execute(
        f"""
        INSERT INTO {DB_METADATA_TABLE} (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def get_quality_heuristics_version(conn):
    """A versao das heuristicas com que este banco foi avaliado.

    Zero quando a marca nao existe, e zero e a resposta certa: um banco gravado
    antes desta versao teve os avisos calculados pelas cinco heuristicas
    genericas, e nao ha como distinguir isso de "nunca calculado". As duas
    respostas pedem a mesma acao — reavaliar.
    """
    valor = get_db_metadata(conn, QUALITY_VERSION_KEY)
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def quality_heuristics_are_current(conn):
    return get_quality_heuristics_version(conn) == QUALITY_HEURISTICS_VERSION


def initialize_database(db_path):
    """Abre a conexao garantindo que o schema esteja atualizado.

    E chamada em muitos pontos da interface (um clique de linha, um save, uma
    navegacao). Por isso a migracao roda apenas quando `user_version` esta
    desatualizado; no caminho comum sobra so o connect.

    Se qualquer coisa depois do connect falhar, a conexao e FECHADA antes de a
    excecao subir. Sem isso ela vazava: quem chama recebe a excecao sem nunca ter
    recebido o objeto, entao nao tem o que fechar, e o arquivo fica preso ate o
    coletor de lixo passar. Num banco corrompido — o caso em que isto falha — o
    efeito e o pior possivel: o programa avisa que nao conseguiu ler o banco e,
    ao mesmo tempo, impede o usuario de substitui-lo pelo backup.
    """
    conn = open_database(db_path)

    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version == SCHEMA_VERSION:
            return conn

        _migrate_database(conn, from_version=current_version)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def fts5_available(conn):
    """O SQLite desta instalacao foi compilado com FTS5?

    E um modulo opcional. Sem ele a busca por termos nao existe, e o programa
    tem de continuar funcionando com o `LIKE` — mais lento, mas correto. Testar
    criando uma tabela em `temp` e o unico jeito confiavel: `compile_options`
    nem sempre lista o modulo, e `PRAGMA module_list` nao existe em toda versao.
    """
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)")
    except sqlite3.Error:
        return False
    try:
        conn.execute("DROP TABLE temp.fts5_probe")
    except sqlite3.Error:
        pass
    return True


def fts_index_ready(cursor):
    """O indice de busca existe neste banco?

    Separado de `fts5_available` porque as duas coisas falham por motivos
    diferentes: o modulo pode existir e o indice nao (banco antigo, migracao que
    nao rodou), e o indice pode existir num arquivo aberto por um Python cujo
    SQLite nao tem FTS5. Consultar sem checar os dois daria `OperationalError`
    no meio de uma navegacao.
    """
    try:
        row = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (FTS_TABLE,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _create_fts_index(conn):
    """Cria o indice de busca e os gatilhos que o mantem em dia.

    `content='comments'` faz do indice um "external content": ele guarda so os
    termos, e o texto continua vivendo uma vez so na tabela original. Num banco
    de 80 MB duplicar o texto seria caro sem necessidade.

    O preco do external content e que a sincronizacao passa a ser
    responsabilidade dos gatilhos, e uma remocao exige o comando `'delete'`
    (com os valores ANTIGOS): apagar a linha sem isso deixa os termos dela no
    indice para sempre, e a busca passa a devolver linhas que nao existem mais.

    `remove_diacritics 2` e o que faz "traducao" achar "tradução". Num corpus em
    portugues digitado por gente, ignorar isso seria a maior fonte de "nao achei"
    injustificado.
    """
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            original_comment,
            translated_comment,
            content='comments',
            content_rowid='id',
            tokenize="unicode61 remove_diacritics 2"
        )
    """)
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS comments_fts_insert AFTER INSERT ON comments
        BEGIN
            INSERT INTO {FTS_TABLE}(rowid, original_comment, translated_comment)
            VALUES (new.id, new.original_comment, new.translated_comment);
        END
    """)
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS comments_fts_delete AFTER DELETE ON comments
        BEGIN
            INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, original_comment, translated_comment)
            VALUES ('delete', old.id, old.original_comment, old.translated_comment);
        END
    """)
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS comments_fts_update AFTER UPDATE ON comments
        BEGIN
            INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, original_comment, translated_comment)
            VALUES ('delete', old.id, old.original_comment, old.translated_comment);
            INSERT INTO {FTS_TABLE}(rowid, original_comment, translated_comment)
            VALUES (new.id, new.original_comment, new.translated_comment);
        END
    """)
    # Popula a partir do conteudo que ja existe. Num banco vazio custa nada; num
    # banco cheio e a unica parte cara da migracao, e roda uma vez so.
    conn.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES ('rebuild')")


def build_fts_match_query(search_text):
    """Traduz o que o usuario digitou para a sintaxe do FTS5, ou `None`.

    O texto digitado nao pode ir cru para o `MATCH`: `AND`, `OR`, `NOT`, `-`,
    `*`, `:`, `(`, `"` sao operadores, e uma busca por `bispo (branco)` ou por
    um trecho com aspas viraria erro de sintaxe no meio da navegacao — nao um
    resultado vazio, um `OperationalError`.

    Cada palavra vira um termo entre aspas (literal para o FTS5), e os termos
    sao exigidos todos (o `AND` implicito). Um `*` no fim de uma palavra e a
    unica sintaxe preservada, porque e a que devolve o casamento por prefixo que
    o `LIKE` dava de graca: `bisp*` acha "bispo".

    Devolve `None` quando nao sobra nenhum termo — busca so de pontuacao, por
    exemplo. Quem chama trata isso como "sem filtro de busca", que e o mesmo que
    o campo vazio faria.
    """
    texto = (search_text or "").strip()
    if not texto:
        return None

    termos = []
    for bruto in texto.split():
        prefixo = bruto.endswith("*")
        palavra = bruto[:-1] if prefixo else bruto
        # Fora letras e digitos nao ha o que casar: o tokenizador do FTS5 ja
        # descarta essa pontuacao, e mante-la so quebraria a sintaxe.
        limpa = "".join(c for c in palavra if c.isalnum() or c in "_")
        if not limpa:
            continue
        termos.append(f'"{limpa}"*' if prefixo else f'"{limpa}"')

    if not termos:
        return None
    return " ".join(termos)


_COMMENTS_TABLE_SQL = """
    CREATE TABLE {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_comment TEXT,
        translated_comment TEXT,
        source_language TEXT NOT NULL DEFAULT '',
        target_language TEXT,
        verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        verified_at TEXT,
        quality_warning INTEGER,
        review_status TEXT NOT NULL DEFAULT '',
        reviewer_note TEXT,
        UNIQUE(original_comment, source_language, target_language)
    )
"""


_OCCURRENCES_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS {OCCURRENCES_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER NOT NULL,
        source_file TEXT NOT NULL,
        game_index INTEGER,
        comment_index INTEGER NOT NULL,
        move_number INTEGER,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_file, comment_index),
        FOREIGN KEY(comment_id) REFERENCES comments(id) ON DELETE CASCADE
    )
"""


def _create_occurrences_table(conn):
    """A tabela de ocorrencias e os indices dela (ROADMAP 18).

    **Nao ha backfill, e nao e esquecimento.** Uma ocorrencia diz em que arquivo,
    partida e lance o comentario foi lido, e isso nao esta em lugar nenhum do
    banco: nao ha de onde derivar. As linhas ja gravadas — 201.607 no banco real —
    ficam sem ocorrencia nenhuma e ganham a primeira quando o arquivo delas for
    processado de novo. Inventar um arquivo para elas seria escrever uma
    procedencia falsa, que e pior do que a ausencia.

    A chave natural e `(source_file, comment_index)`: uma posicao da obra e
    ocupada por um comentario, e nao por varios. Note que a UNIQUE **nao** inclui
    `comment_id` de proposito — com ele, reprocessar um arquivo cujo comentario da
    posicao 5 mudou de texto deixaria as duas afirmacoes no banco, e a posicao 5
    passaria a ter dois donos.

    `game_index` e `move_number` aceitam nulo porque podem faltar de verdade: um
    comentario antes do primeiro lance da partida nao tem lance anterior. Um zero
    ali se confundiria com medicao.

    A `FOREIGN KEY` e declarativa. O SQLite so a aplica com `PRAGMA foreign_keys
    = ON`, que este programa nao liga — o mesmo caso de `comment_history`, e a
    mesma razao: o que apaga comentario em massa e o "Zerar Traducoes", que derruba
    as tabelas juntas em vez de contar com o cascade.
    """
    conn.execute(_OCCURRENCES_TABLE_SQL)
    # A UNIQUE ja indexa `(source_file, comment_index)`, que e a ordem de leitura
    # e tambem o filtro por arquivo. O que falta e o caminho inverso: dado um
    # comentario, onde ele aparece. O indice cobre a consulta inteira — a
    # ordenacao por ocorrencia pergunta `MIN(comment_index)` por linha da pagina, e
    # sem as tres colunas aqui cada pergunta viraria uma leitura da tabela.
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_occurrences_comment
        ON {OCCURRENCES_TABLE}(comment_id, source_file, comment_index)
    """)


def _add_source_language_column(conn):
    """Acrescenta `source_language` e poe o idioma de origem na chave.

    Nao da para fazer isso com um `ALTER TABLE` sozinho. A coluna nova ate
    entraria assim, mas a parte que importa e a outra: `UNIQUE(original_comment,
    target_language)` e uma restricao declarada NA TABELA, e o SQLite nao remove
    restricao de tabela — a unica saida e reconstrui-la, que e o procedimento que
    a documentacao dele chama de "12 passos".

    **Os ids sao preservados de proposito**, e isso paga o passo mais caro da
    migracao. `comments_fts` e um indice `external content` indexado por
    `rowid`; se os ids mudassem, cada linha passaria a apontar para o texto de
    outra e a busca devolveria resultados errados — sem erro nenhum. Copiando o
    `id` explicitamente, o indice continua valendo como estava e nao precisa ser
    reconstruido. Os gatilhos, esses sim, saem antes (referenciam a tabela que
    vai ser derrubada) e voltam depois.

    Medido no banco real (201.607 linhas, 115 MB): 3,4 s para reconstruir a
    tabela, 0,8 s para os indices e 1,4 s do `VACUUM` — que existe porque as
    paginas da tabela antiga ficam livres, mas no arquivo: sem ele o banco salta
    de 115 MB para 183 MB e so encolhe de volta com o uso.
    """
    cursor = conn.cursor()

    # Os gatilhos referenciam `comments`, entao precisam sair antes dela. Voltam
    # em `_create_fts_index`, no fim da migracao.
    for trigger in ("comments_fts_insert", "comments_fts_delete", "comments_fts_update"):
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    cursor.execute("DROP TABLE IF EXISTS comments_new")
    cursor.execute(_COMMENTS_TABLE_SQL.format(name="comments_new"))
    cursor.execute(f"""
        INSERT INTO comments_new (
            id, original_comment, translated_comment, source_language,
            target_language, verified, created_at, updated_at, verified_at,
            quality_warning
        )
        SELECT
            id, original_comment, translated_comment, '{SOURCE_LANGUAGE_UNKNOWN}',
            target_language, verified, created_at, updated_at, verified_at,
            quality_warning
        FROM comments
    """)
    cursor.execute("DROP TABLE comments")
    cursor.execute("ALTER TABLE comments_new RENAME TO comments")
    conn.commit()

    try:
        conn.execute("VACUUM")
    except sqlite3.DatabaseError:  # pragma: no cover - defensivo
        # Recuperar espaco e conveniencia; o banco ja esta correto sem isso.
        pass


# O achatamento antigo inseria espaco depois de `.` mesmo entre digitos, entao
# um comentario com `0.35` entrou no banco com a chave `0. 35`. Corrigido o
# achatamento (ROADMAP 13.2), a chave nova deixaria de casar com a linha
# gravada e o comentario seria pago de novo a API. O padrao e o inverso exato
# do que o achatamento fazia: `digito. digito` com UM espaco.
_LEGACY_DECIMAL_SPACING_RE = re.compile(r"(?<=\d)\. (?=\d)")


def _collapse_decimal_cache_keys(conn):
    """Reachata as chaves gravadas pelo achatamento antigo: `0. 35` -> `0.35`.

    Roda UMA vez, na migracao 4 -> 5. Nao pode rodar de novo porque o espaco
    deixa de ser assinatura do achatamento antigo no momento em que ele e
    corrigido: dali em diante um `0. 35` gravado e um espaco que existia no PGN
    de origem, e colapsa-lo reescreveria texto do usuario.

    Quando a chave colapsada JA existe no mesmo par de idiomas, a linha antiga
    fica como esta: as duas sao conteudos que o banco conhece, e apagar ou
    fundir seria destruir uma traducao (possivelmente revisada) para
    desduplicar um cache. O preco e uma linha que nunca mais casa com arquivo
    nenhum — peso morto, nao erro.

    O `quality_warning` da linha alterada e reavaliado (garantia R6): o texto
    original mudou, e a coluna materializada nao pode divergir do que a
    avaliacao em Python diria. Os gatilhos do FTS ja existem neste ponto da
    migracao e mantem o indice em dia sozinhos; `updated_at` nao e tocado —
    nada aqui e uma edicao de traducao.
    """
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT id, original_comment, translated_comment,
               source_language, target_language
        FROM comments
        WHERE original_comment GLOB '*[0-9]. [0-9]*'
        """
    ).fetchall()

    changed = 0
    for row_id, original, translated, source_language, target_language in rows:
        collapsed = _LEGACY_DECIMAL_SPACING_RE.sub(".", original or "")
        if collapsed == original:
            continue
        conflict = cursor.execute(
            """
            SELECT 1 FROM comments
            WHERE original_comment = ?
              AND source_language = ?
              AND target_language = ?
              AND id <> ?
            LIMIT 1
            """,
            (collapsed, source_language, target_language, row_id),
        ).fetchone()
        if conflict:
            continue
        cursor.execute(
            "UPDATE comments SET original_comment = ?, quality_warning = ? WHERE id = ?",
            (
                collapsed,
                quality_warning_flag(
                    collapsed, translated, source_language, target_language
                ),
                row_id,
            ),
        )
        changed += 1

    conn.commit()
    return changed


def _migrate_database(conn, from_version=0):
    cursor = conn.cursor()

    # Num banco novo isto ja cria o schema final; num que existe e um no-op, e
    # quem acerta a tabela antiga sao os `ALTER TABLE` e a reconstrucao abaixo.
    cursor.execute(_COMMENTS_TABLE_SQL.format(name="IF NOT EXISTS comments"))

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {DB_METADATA_TABLE} (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        previous_translation TEXT,
        new_translation TEXT,
        previous_verified INTEGER,
        new_verified INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(comment_id) REFERENCES comments(id) ON DELETE CASCADE
    )
    """)

    _create_occurrences_table(conn)

    cursor.execute("PRAGMA table_info(comments)")
    cols = [row[1] for row in cursor.fetchall()]

    if "verified" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN verified INTEGER DEFAULT 0")
        conn.commit()
    if "created_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN created_at TEXT")
        cursor.execute("UPDATE comments SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        conn.commit()
    if "updated_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN updated_at TEXT")
        cursor.execute("UPDATE comments SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        conn.commit()
    if "verified_at" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN verified_at TEXT")
        cursor.execute("""
            UPDATE comments
            SET verified_at = CASE WHEN verified = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE verified_at IS NULL
        """)
        conn.commit()

    if "quality_warning" not in cols:
        cursor.execute("ALTER TABLE comments ADD COLUMN quality_warning INTEGER")
        conn.commit()

    # ROADMAP 19, item 12. `NOT NULL DEFAULT ''` para que o filtro nunca precise
    # distinguir vazio de nulo: uma linha antiga e uma linha nova sem status dizem a
    # mesma coisa, e sao ambas "pendente".
    if "review_status" not in cols:
        cursor.execute(
            "ALTER TABLE comments ADD COLUMN review_status TEXT NOT NULL DEFAULT ''"
        )
        conn.commit()
    if "reviewer_note" not in cols:
        # A nota, essa sim, aceita nulo: "nao escreveu nota" e diferente de "escreveu
        # e apagou", e um dia isso pode importar. Quem le trata os dois como vazio.
        cursor.execute("ALTER TABLE comments ADD COLUMN reviewer_note TEXT")
        conn.commit()

    # Por ultimo entre as mudancas de coluna: a reconstrucao copia o conjunto
    # final de colunas, entao tudo o que for acrescentado acima ja precisa estar
    # na tabela quando ela roda.
    if "source_language" not in cols:
        _add_source_language_column(conn)
        cursor = conn.cursor()

    cursor.execute("""
        UPDATE comments
        SET verified = CASE WHEN verified = 1 THEN 1 ELSE 0 END
        WHERE verified IS NULL OR verified NOT IN (0, 1)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_target_language
        ON comments(target_language)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_review_queue
        ON comments(target_language, verified, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_quality
        ON comments(target_language, quality_warning, id)
    """)
    # Os dois indices de COBERTURA do `get_review_status_counts`. "Cobertura"
    # quer dizer que toda coluna que a consulta le esta no indice, e por isso o
    # SQLite nao toca na tabela — e ela e a parte cara: 200 mil linhas de texto
    # de livro contra um indice de cinco colunas curtas.
    #
    # **`review_status` no fim, e essa e a correcao de 22.13.** O item 19.12
    # acrescentou a coluna a agregada e nao a acrescentou aqui, e a cobertura se
    # perdeu em silencio: `EXPLAIN QUERY PLAN` passou a devolver
    # `SEARCH comments USING INDEX idx_comments_counts` **sem** a palavra
    # `COVERING` — uma leitura da tabela por linha do par. Medido em copia
    # sintetica de 204 mil linhas (mediana de 20 execucoes): 118,8 ms -> 60,8 ms
    # no resumo do par e 138,3 ms -> 58,2 ms no resumo so por destino. A consulta
    # roda em TODA recarga da lista, na thread do Tk.
    #
    # E a mesma classe de regressao que a garantia R5 nomeou quando
    # `source_language` entrou no WHERE — desta vez introduzida pelo proprio
    # recurso que a evitou da outra vez. Por isso a migracao 9 DERRUBA os dois
    # antes de recriar: `CREATE INDEX IF NOT EXISTS` sobre um indice com o mesmo
    # nome e colunas diferentes nao faz nada, e o banco de quem ja atualizou
    # ficaria com o indice velho para sempre.
    if from_version < 9:
        cursor.execute("DROP INDEX IF EXISTS idx_comments_counts")
        cursor.execute("DROP INDEX IF EXISTS idx_comments_pair_counts")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_counts
        ON comments(target_language, verified, quality_warning, review_status)
    """)
    # O mesmo, para quando ha filtro de origem. Sem ele o indice acima deixa de
    # cobrir a consulta — `source_language` esta no `WHERE` e nao no indice —, e
    # a agregada volta a tocar a tabela: medido no banco real, 34,9 ms sem filtro
    # de origem contra 78,7 ms com ele.
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_pair_counts
        ON comments(target_language, source_language, verified, quality_warning, review_status)
    """)
    # O editor filtra por par de idiomas, e sem este indice cada troca de filtro
    # varreria a tabela — que e exatamente o que a garantia R5 existe para
    # impedir. A ordem das colunas segue a do `WHERE`: destino sempre presente,
    # origem so quando o filtro nao e "todos".
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_language_pair
        ON comments(target_language, source_language, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comment_history_comment
        ON comment_history(comment_id, id)
    """)

    if fts5_available(conn):
        _create_fts_index(conn)
    # Sem FTS5 o programa continua inteiro, so que a busca por termos nao fica
    # disponivel e a interface cai no `LIKE`. Nao abrir o banco por causa de um
    # modulo opcional ausente seria desproporcional.

    # Depois do FTS de proposito: a atualizacao das chaves passa pelos gatilhos,
    # e sem eles os termos antigos ficariam no indice para sempre.
    if from_version < 5:
        _collapse_decimal_cache_keys(conn)

    conn.commit()
    backfill_quality_warnings(conn)
    return conn


def backfill_quality_warnings(conn, batch_size=5000):
    """Preenche `quality_warning` nas linhas que ainda estao com NULL.

    So roda no upgrade de schema; depois disso a coluna e mantida em cada
    escrita. Devolve quantas linhas foram preenchidas.

    **Nao adianta a versao das heuristicas**, e essa e a diferenca entre ele e a
    reavaliacao. Preencher `NULL` era suficiente enquanto o unico jeito de a
    coluna estar errada fosse nao existir; com heuristica nova, as linhas ja
    preenchidas e que estao erradas — e sao justamente as que ele nao olha
    (ROADMAP 16.2).
    """
    cursor = conn.cursor()
    total = 0

    while True:
        rows = cursor.execute(
            """
            SELECT id, original_comment, translated_comment,
                   source_language, target_language
            FROM comments
            WHERE quality_warning IS NULL
            LIMIT ?
            """,
            (batch_size,),
        ).fetchall()
        if not rows:
            break

        cursor.executemany(
            "UPDATE comments SET quality_warning = ? WHERE id = ?",
            [
                (
                    quality_warning_flag(original, translated, source, target),
                    row_id,
                )
                for row_id, original, translated, source, target in rows
            ],
        )
        conn.commit()
        total += len(rows)

    return total


class QualityReevaluationCanceled(Exception):
    """A reavaliacao dos avisos de qualidade foi interrompida pelo usuario."""


def reevaluate_quality_warnings(
    conn,
    batch_size=2000,
    progress_callback=None,
    should_cancel=None,
):
    """Recalcula `quality_warning` em TODAS as linhas (garantia Q2).

    E o mecanismo que a garantia R6 passa a exigir quando as heuristicas mudam:
    a coluna e materializada, e uma regra nova deixa as linhas ja avaliadas com o
    veredito velho. Medido no banco de desenvolvimento (6.500 linhas): 0,8 s, dos
    quais 0,12 ms por linha sao a avaliacao — o que extrapola para ~25 s nas 200
    mil linhas do banco real, uma vez por mudanca de heuristica.

    Devolve `{"scanned": n, "changed": n}`. `changed` conta as linhas cujo
    veredito virou, e nao as examinadas: rodar duas vezes devolve zero na segunda.

    **A versao so e gravada por quem chama, e so no sucesso.** Cancelar no meio
    deixa a marca velha de proposito — o banco esta metade reavaliado, e dizer que
    ele esta em dia seria mentir de um jeito que ninguem descobre depois. Na
    proxima abertura a reavaliacao e oferecida de novo.

    O par de idiomas sai da propria linha, e nao de um argumento: a terminologia
    e escopada por idioma, e o banco tem pares diferentes na mesma tabela.
    """
    cursor = conn.cursor()
    write_cursor = conn.cursor()
    total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    if progress_callback is not None:
        progress_callback(0, total)

    scanned = 0
    changed = 0
    ultimo_id = 0
    while True:
        rows = cursor.execute(
            """
            SELECT id, original_comment, translated_comment,
                   source_language, target_language, quality_warning
            FROM comments
            WHERE id > ?
            ORDER BY id
            LIMIT ?
            """,
            (ultimo_id, batch_size),
        ).fetchall()
        if not rows:
            break

        # Paginado por `id > ?`, e nao por OFFSET: o editor pode estar gravando
        # no mesmo banco, e um OFFSET sobre uma tabela que muda pula ou repete
        # linhas. Aqui a chave e estavel.
        atualizacoes = []
        for row_id, original, translated, source, target, antigo in rows:
            scanned += 1
            novo = quality_warning_flag(original, translated, source, target)
            if novo != antigo:
                atualizacoes.append((novo, row_id))
            ultimo_id = row_id

        if atualizacoes:
            write_cursor.executemany(
                "UPDATE comments SET quality_warning = ? WHERE id = ?",
                atualizacoes,
            )
            changed += len(atualizacoes)

        # Um commit por lote, e nao um por linha nem um so no fim: o primeiro
        # cobraria 2.000 fsync por lote e o segundo manteria a transacao de
        # escrita aberta durante a varredura inteira, travando o "Salvar" do
        # editor (garantia C3).
        conn.commit()

        if progress_callback is not None:
            progress_callback(scanned, total)
        if should_cancel is not None and should_cancel():
            raise QualityReevaluationCanceled()

    if progress_callback is not None:
        progress_callback(total, total)
    return {"scanned": scanned, "changed": changed}


# Quantos comentarios por consulta ao restringir a carga do cache. O limite de
# parametros do SQLite e 32766 nas versoes recentes e 999 nas antigas; 900 cabe
# em qualquer uma e o custo de mais um lote e desprezivel perto de errar aqui.
CACHE_LOOKUP_CHUNK = 900

# Acima desta fracao da tabela, vale carregar tudo de uma vez.
#
# O limite e sobre MEMORIA, que e o que este item trata, e nao sobre tempo: as
# duas cargas se cruzam em tempo perto de 10% da tabela, mas ate bem depois disso
# a restrita continua valendo a pena. Medido no banco real (195.607 linhas,
# 74 MB na carga completa), pedindo uma fracao da tabela:
#
#     fracao   tempo extra   memoria poupada   MB por 100 ms
#       10%        -34 ms          68 MB          (de graca)
#       25%        443 ms          59 MB             13,3
#       50%       1208 ms          44 MB              3,7
#       75%       1872 ms          32 MB              1,7
#
# A troca piora sem parar: quanto maior a fatia pedida, menos memoria se poupa e
# mais tempo se paga. Em 50% ainda se trocam 44 MB por 1,2 s — aceitavel numa
# operacao que depois passa minutos na rede. Dali para cima, nao.
CACHE_FULL_LOAD_RATIO = 0.50

# So vale consultar o tamanho da tabela (10 ms) quando ha o que decidir. Abaixo
# deste numero a carga restrita custa no maximo ~26 ms, entao gastar 10 ms para
# escolher seria pagar quase metade do trabalho so para pensar nele.
CACHE_RATIO_CHECK_MINIMUM = 2 * CACHE_LOOKUP_CHUNK


def _full_load_is_cheaper(
    cursor,
    target_language,
    quantos,
    source_language=SOURCE_LANGUAGE_UNKNOWN,
):
    """A carga completa compensa para este numero de comentarios?

    Errar aqui nao produz resultado errado — as duas cargas devolvem o mesmo
    dicionario para os comentarios pedidos —, so um tempo pior.
    """
    if quantos < CACHE_RATIO_CHECK_MINIMUM:
        return False
    try:
        total = cursor.execute(
            """
            SELECT COUNT(*)
            FROM comments
            WHERE target_language = ?
              AND source_language = ?
            """,
            (target_language, source_language),
        ).fetchone()[0]
    except sqlite3.Error:  # pragma: no cover - defensivo
        return False
    return total > 0 and quantos >= total * CACHE_FULL_LOAD_RATIO


def adopt_unknown_source_language(
    cursor,
    target_language,
    source_language,
    comments,
    chunk_size=None,
):
    """Rotula com `source_language` as linhas destes comentarios que ainda nao tem um.

    Existe porque o idioma de origem entrou na chave da tabela, e sem isto a
    mudanca cobraria o cache inteiro: as 201.607 linhas ja gravadas ficaram com
    origem "nao informada", entao a primeira execucao que declarasse "estes PGN
    estao em espanhol" nao acharia nenhuma delas e mandaria tudo de volta para a
    API — pagando de novo por traducoes que ja existem.

    Uma linha sem idioma de origem nao contradiz o que o usuario acabou de
    declarar: ela so nao sabia. Adota-la e registrar o que ele disse, e a partir
    dai ela vive no par certo. Nenhuma traducao e tocada — muda so o rotulo.

    `UPDATE OR IGNORE` porque a adocao pode esbarrar na propria chave: se ja
    existir uma linha (mesmo comentario, mesma origem, mesmo destino), a linha
    sem rotulo permanece como esta em vez de derrubar a operacao. Ter as duas e o
    caso normal de quem traduziu o mesmo texto antes e depois de declarar o
    idioma.

    `comments` a `None` adota **todas** as linhas do idioma de destino, e nao so
    as de uma execucao. E o que a ferramenta "Corrigir Lances" usa: o usuario
    declara de uma vez em que idioma esta o que ele ja traduziu, em vez de
    esperar que cada comentario reapareca numa traducao futura para ser rotulado.

    Devolve quantas linhas foram adotadas. Um `source_language` vazio nao adota
    nada: "detectar automaticamente" nao e uma declaracao.
    """
    if not source_language or comments is not None and not comments:
        return 0

    if comments is None:
        cursor.execute(
            """
            UPDATE OR IGNORE comments
            SET source_language = ?
            WHERE target_language = ?
              AND source_language = ?
            """,
            (source_language, target_language, SOURCE_LANGUAGE_UNKNOWN),
        )
        return max(0, cursor.rowcount)

    procurados = list(dict.fromkeys(comments))
    chunk_size = chunk_size or CACHE_LOOKUP_CHUNK
    adotadas = 0
    for inicio in range(0, len(procurados), chunk_size):
        lote = procurados[inicio:inicio + chunk_size]
        marcadores = ",".join("?" * len(lote))
        cursor.execute(
            f"""
            UPDATE OR IGNORE comments
            SET source_language = ?
            WHERE target_language = ?
              AND source_language = ?
              AND original_comment IN ({marcadores})
            """,
            [source_language, target_language, SOURCE_LANGUAGE_UNKNOWN] + lote,
        )
        adotadas += cursor.rowcount if cursor.rowcount > 0 else 0
    return adotadas


def load_translation_cache(
    cursor,
    target_language,
    comments=None,
    source_language=SOURCE_LANGUAGE_UNKNOWN,
):
    """Traducoes ja gravadas do par de idiomas, como `{original: traduzido}`.

    `comments` restringe a carga aos comentarios que a execucao vai de fato
    consultar. Sem ele, carrega o idioma inteiro — 58 MB no banco real, contra
    o que o worker precisa, que e so o conteudo dos arquivos escolhidos
    (ROADMAP 2.9).

    A restricao **nao muda o resultado das consultas do worker**: ele so pergunta
    ao cache por comentarios que extraiu dos arquivos, e sao exatamente esses que
    entram aqui. O que sai da memoria e o que ele nunca perguntaria.

    O contrato e "contem os pedidos que existem", e nao "contem so os pedidos":
    quando a fatia pedida e grande o bastante, a carga completa sai mais barata e
    o resultado traz tudo. Quem precisar de uma contagem exata do que pediu deve
    conta-la sobre a propria lista, e nao pelo tamanho do dicionario.

    A carga e restrita ao PAR de idiomas, e nao so ao destino: desde que a origem
    entrou na chave, duas linhas com o mesmo comentario e origens diferentes sao
    traducoes independentes, e misturar as duas no cache faria a execucao
    reaproveitar a traducao da outra lingua — que e justamente o que declarar o
    idioma de origem existe para evitar.

    A consulta e feita em lotes por causa do limite de parametros do SQLite. O
    `IN` e indexado: `UNIQUE(original_comment, source_language, target_language)`
    ja cria o indice que ele usa.
    """
    if comments is None:
        cursor.execute(
            """
            SELECT original_comment, translated_comment
            FROM comments
            WHERE target_language = ?
              AND source_language = ?
              AND translated_comment IS NOT NULL
              AND translated_comment <> ''
            ORDER BY id
            """,
            (target_language, source_language)
        )
        return {orig: trans for orig, trans in cursor.fetchall()}

    # `dict.fromkeys` remove repetidos preservando a ordem — o mesmo comentario
    # aparece em varios arquivos, e perguntar duas vezes por ele e desperdicio.
    procurados = list(dict.fromkeys(comments))
    if not procurados:
        return {}
    if _full_load_is_cheaper(cursor, target_language, len(procurados), source_language):
        return load_translation_cache(cursor, target_language, source_language=source_language)

    cache = {}
    for inicio in range(0, len(procurados), CACHE_LOOKUP_CHUNK):
        lote = procurados[inicio:inicio + CACHE_LOOKUP_CHUNK]
        marcadores = ",".join("?" * len(lote))
        cursor.execute(
            f"""
            SELECT original_comment, translated_comment
            FROM comments
            WHERE target_language = ?
              AND source_language = ?
              AND translated_comment IS NOT NULL
              AND translated_comment <> ''
              AND original_comment IN ({marcadores})
            """,
            [target_language, source_language] + lote,
        )
        cache.update(cursor.fetchall())
    return cache


def save_translation(
    cursor,
    original_comment,
    translated_comment,
    target_language,
    source_language=SOURCE_LANGUAGE_UNKNOWN,
):
    """
    Salva uma tradução no cache.

    `source_language` e o idioma que o usuário declarou para os PGN desta
    execução, e faz parte da identidade da linha: o mesmo comentário vindo do
    espanhol e do italiano são duas traduções, e não uma reaproveitada.

    Retorna:
    - inserted: linha nova criada.
    - filled_empty: linha existente vazia/nula preenchida.
    - unchanged: já havia tradução preenchida e nada foi sobrescrito.
    """
    source_language = source_language or SOURCE_LANGUAGE_UNKNOWN
    existing_row = cursor.execute(
        """
        SELECT id, translated_comment
        FROM comments
        WHERE original_comment = ?
          AND source_language = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, source_language, target_language)
    ).fetchone()

    if existing_row is None:
        cursor.execute(
            """
            INSERT INTO comments (
                original_comment,
                translated_comment,
                source_language,
                target_language,
                quality_warning,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                original_comment,
                translated_comment,
                source_language,
                target_language,
                quality_warning_flag(
                    original_comment, translated_comment,
                    source_language, target_language,
                ),
            )
        )
        return "inserted" if cursor.rowcount else "unchanged"

    row_id, existing_translation = existing_row
    if existing_translation is None or existing_translation == "":
        cursor.execute(
            """
            UPDATE comments
            SET translated_comment = ?,
                quality_warning = ?,
                verified = 0,
                updated_at = CURRENT_TIMESTAMP,
                verified_at = NULL
            WHERE id = ?
            """,
            (
                translated_comment,
                quality_warning_flag(
                    original_comment, translated_comment,
                    source_language, target_language,
                ),
                row_id,
            )
        )
        if cursor.rowcount:
            record_comment_history(
                cursor,
                row_id,
                "fill_empty",
                existing_translation,
                translated_comment,
                0,
                0,
            )
        return "filled_empty" if cursor.rowcount else "unchanged"

    return "unchanged"

def resolve_comment_ids(
    cursor,
    target_language,
    comments,
    source_language=SOURCE_LANGUAGE_UNKNOWN,
):
    """`{original: id}` das linhas que existem no par, para estes comentarios.

    E o que falta entre a extracao e a tabela de ocorrencias: o worker sabe o
    TEXTO de cada posicao do arquivo, e a ocorrencia precisa do `id` da linha. Um
    comentario que nao esta no banco simplesmente nao aparece no dicionario — e o
    caso de quem falhou na traducao ou foi esvaziado pela limpeza, que nao tem
    linha nenhuma para apontar.

    Em lotes e restrito ao par pelos mesmos motivos de `load_translation_cache`: o
    limite de parametros do SQLite, e a chave `UNIQUE(original_comment,
    source_language, target_language)` — que e tambem o indice que este `IN` usa.
    """
    source_language = source_language or SOURCE_LANGUAGE_UNKNOWN
    procurados = list(dict.fromkeys(comments or []))
    if not procurados:
        return {}

    encontrados = {}
    for inicio in range(0, len(procurados), CACHE_LOOKUP_CHUNK):
        lote = procurados[inicio:inicio + CACHE_LOOKUP_CHUNK]
        marcadores = ",".join("?" * len(lote))
        cursor.execute(
            f"""
            SELECT original_comment, id
            FROM comments
            WHERE target_language = ?
              AND source_language = ?
              AND original_comment IN ({marcadores})
            """,
            [target_language, source_language] + lote,
        )
        encontrados.update(cursor.fetchall())
    return encontrados


def record_occurrences(cursor, source_file, occurrences, comment_ids):
    """Grava onde os comentarios deste arquivo foram lidos (ROADMAP 18).

    `occurrences` e a lista que a extracao devolve — `(indice, partida, lance,
    texto)` — e `comment_ids` o mapa de `resolve_comment_ids`. Devolve
    `(gravadas, sem_linha)`.

    **O conjunto do arquivo e SUBSTITUIDO, e nao mesclado.** O arquivo em disco e
    a verdade sobre a obra: se ele encurtou, as posicoes que sobravam nao existem
    mais, e mesclar as deixaria no banco apontando para comentarios que ninguem le
    mais naquele lugar. O preco esta dito porque e real: uma execucao interrompida
    no meio de um arquivo grava so as posicoes cujos comentarios ela conseguiu
    traduzir, e o arquivo aparece menor do que e ate a execucao seguinte — que
    encontra o resto no cache e completa o registro.

    Um comentario sem linha no banco nao vira ocorrencia: a ocorrencia aponta para
    uma traducao, e nao ha para onde apontar. Isso e contado e devolvido para o log
    em vez de ficar em silencio — e a diferenca entre "esta obra tem 1.200
    posicoes" e "tem 1.200 posicoes, 40 delas ainda sem traducao".

    O caminho e normalizado AQUI, e nao em quem chama, porque ele e a chave da
    tabela: `cap01.pgn` e `.\\cap01.pgn` sao o mesmo arquivo, e duas grafias
    entrando no banco dariam duas obras no filtro do editor — cada uma com metade
    do livro. Esta funcao e a unica porta pela qual caminho entra na tabela, e por
    isso a normalizacao mora nela.
    """
    source_file = os.path.abspath(source_file)
    cursor.execute(
        f"DELETE FROM {OCCURRENCES_TABLE} WHERE source_file = ?", (source_file,)
    )

    linhas = []
    sem_linha = 0
    for comment_index, game_index, move_number, texto in occurrences:
        comment_id = comment_ids.get(texto)
        if comment_id is None:
            sem_linha += 1
            continue
        linhas.append(
            (comment_id, source_file, game_index, comment_index, move_number)
        )

    if linhas:
        cursor.executemany(
            f"""
            INSERT INTO {OCCURRENCES_TABLE} (
                comment_id, source_file, game_index, comment_index, move_number,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            linhas,
        )
    return len(linhas), sem_linha


def list_occurrence_files(cursor, target_language, source_language=None):
    """`[(arquivo, posicoes, comentarios)]` do par, em ordem de nome.

    Alimenta o filtro por arquivo do editor. As duas contagens sao coisas
    diferentes e as duas interessam: `posicoes` e o tamanho da obra (cada `{...}`
    lido), `comentarios` e quantas linhas distintas do banco ela usa. A diferenca
    entre elas e a repeticao interna do livro — trinta "Diagram" sao trinta
    posicoes e um comentario.

    Ordenado por nome de arquivo porque e assim que capitulo se ordena
    (`cap01.pgn`, `cap02.pgn`), e nao por quantidade: o filtro e uma lista de
    obras para escolher, nao um ranking.
    """
    clauses = ["c.target_language = ?"]
    params = [target_language]
    if source_language is not None:
        clauses.append("c.source_language = ?")
        params.append(source_language)

    return cursor.execute(
        f"""
        SELECT o.source_file, COUNT(*), COUNT(DISTINCT o.comment_id)
        FROM {OCCURRENCES_TABLE} o
        JOIN comments c ON c.id = o.comment_id
        WHERE {" AND ".join(clauses)}
        GROUP BY o.source_file
        ORDER BY o.source_file
        """,
        params,
    ).fetchall()


def fetch_comment_occurrences(cursor, comment_id, limit=3, preferred_file=None):
    """`(lista, total)` das ocorrencias de um comentario, na ordem de leitura.

    A lista vem cortada em `limit` e o total vem inteiro, de proposito: o editor
    mostra as primeiras e diz quantas faltam. Um comentario reusado em doze livros
    tem doze ocorrencias, e enfiar as doze no rodape esconderia o texto que o
    revisor esta lendo — mas ocultar que existem seria pior, porque editar ali
    muda a traducao das doze.

    `preferred_file` poe as ocorrencias daquele arquivo na frente. Sem isso, quem
    esta lendo o capitulo 7 com o filtro nele veria no rodape a posicao do mesmo
    comentario no capitulo 1 — informacao verdadeira que responde outra pergunta,
    e que na tela passa por erro.

    `limit=None` traz TODAS. E o que a lista de posicoes do editor pede (ROADMAP
    22.11): o rodape mostra uma e diz quantas faltam, e quem clica nele quer
    justamente as que faltam. `-1` e como o SQLite escreve "sem limite" — o
    `LIMIT` continua na consulta, e nao ha um segundo SQL para manter em dia.
    """
    if limit is None:
        limit = -1
    total = cursor.execute(
        f"SELECT COUNT(*) FROM {OCCURRENCES_TABLE} WHERE comment_id = ?",
        (comment_id,),
    ).fetchone()[0]
    if not total:
        return [], 0

    # `source_file <> ?` vale 0 para o arquivo preferido e 1 para os outros, o que
    # o poe primeiro sem precisar de uma segunda consulta. Sem preferencia, a
    # coluna e constante e a ordenacao e a de sempre.
    linhas = cursor.execute(
        f"""
        SELECT source_file, game_index, comment_index, move_number
        FROM {OCCURRENCES_TABLE}
        WHERE comment_id = ?
        ORDER BY (source_file <> ?), source_file, comment_index
        LIMIT ?
        """,
        (comment_id, preferred_file or "", limit),
    ).fetchall()
    return linhas, total


def get_file_progress(cursor):
    """Progresso por obra: `[(arquivo, posicoes, comentarios, verificadas, pendentes, avisos)]`.

    O `DISTINCT` na subconsulta e o que torna o numero honesto. Somar `verified`
    sobre o `JOIN` contaria a mesma linha uma vez por posicao, e um livro que
    repete um comentario verificado trinta vezes apareceria com trinta
    verificacoes — o progresso passaria de 100%.

    `posicoes` sai de uma contagem separada porque e a unica coisa aqui que
    CONTA repeticao: e o tamanho da obra em comentarios lidos.
    """
    posicoes = dict(
        cursor.execute(
            f"SELECT source_file, COUNT(*) FROM {OCCURRENCES_TABLE} GROUP BY source_file"
        ).fetchall()
    )
    linhas = cursor.execute(
        f"""
        SELECT
            source_file,
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN quality_warning = 1 THEN 1 ELSE 0 END), 0)
        FROM (
            SELECT DISTINCT
                o.source_file AS source_file,
                c.id AS id,
                c.verified AS verified,
                c.quality_warning AS quality_warning
            FROM {OCCURRENCES_TABLE} o
            JOIN comments c ON c.id = o.comment_id
        )
        GROUP BY source_file
        ORDER BY source_file
        """
    ).fetchall()
    return [
        (arquivo, posicoes.get(arquivo, 0), comentarios, verificadas, pendentes, avisos)
        for arquivo, comentarios, verificadas, pendentes, avisos in linhas
    ]


class WordCountCanceled(Exception):
    """A contagem de palavras foi interrompida pelo usuario."""


# Linhas por bloco na contagem de palavras. E o intervalo entre duas chances de
# relatar progresso ou de desistir, e tambem o teto de memoria: 5.000 linhas de
# comentario de livro sao ~2,5 MB, contra os ~100 MB de um `fetchall` do banco
# real. Mesmo numero e mesmo motivo do bloco da exportacao de CSV.
WORD_COUNT_CHUNK = 5000


def count_words_by_pair(cursor, progress_callback=None, should_cancel=None):
    """`{(origem, destino): contagens}` de palavras, mais o total.

    Devolve `(por_par, total)`. As contagens sao as de `word_count`: linhas,
    palavras do original, palavras da traducao, e as da traducao separadas por
    status.

    **Em Python, e nao em SQL**, e a decisao custa uma passagem pelo banco. O SQL
    contaria espacos (`LENGTH(x) - LENGTH(REPLACE(x, ' ', ''))`), o que da a
    resposta certa para o ORIGINAL — ele e achatado, com um espaco entre palavras —
    e errada para a TRADUCAO, que passou pela mao do revisor e pode ter quebra de
    linha, espaco duplo, tabulacao. Um relatorio de orcamento que conta certo de um
    lado e por aproximacao do outro nao serve para cobrar.

    Em blocos e com cancelamento porque a passagem le os dois textos de todas as
    linhas: no banco real sao ~100 MB, e materializar isso de uma vez foi o que o
    item 2.9 do ROADMAP passou a corrigir em toda parte.
    """
    total_linhas = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    if progress_callback is not None:
        progress_callback(0, total_linhas)

    por_par = {}
    lidas = 0
    linhas = cursor.execute(
        """
        SELECT source_language, target_language, original_comment,
               translated_comment, verified
        FROM comments
        ORDER BY id
        """
    )
    while True:
        if should_cancel is not None and should_cancel():
            raise WordCountCanceled()
        bloco = linhas.fetchmany(WORD_COUNT_CHUNK)
        if not bloco:
            break
        for origem, destino, original, traducao, verified in bloco:
            add_word_counts(por_par, (origem, destino), original, traducao, verified)
        lidas += len(bloco)
        if progress_callback is not None:
            progress_callback(lidas, total_linhas)

    return por_par, total_word_counts(por_par)


def get_daily_review_activity(cursor, limit=14):
    """`[(dia, edicoes, palavras)]` do historico, do mais recente para tras.

    E a produtividade que `comment_history` ja permitia calcular sem esquema novo
    (ROADMAP 19, item 6): cada linha dele tem carimbo e o texto que passou a valer.

    As palavras sao as da traducao NOVA de cada edicao, e nao a diferenca em
    relacao a anterior. Diferenca seria negativa quando o revisor encurta um texto,
    e "produzi -40 palavras hoje" nao e uma metrica de trabalho — o que o tradutor
    mede e quanto texto passou pela mao dele.

    A mesma linha editada tres vezes no dia conta tres vezes, pelo mesmo motivo:
    sao tres passagens de revisao. O numero e de atividade, e nao de acervo.
    """
    linhas = cursor.execute(
        """
        SELECT DATE(created_at) AS dia, new_translation
        FROM comment_history
        WHERE created_at IS NOT NULL
        ORDER BY dia DESC
        """
    ).fetchall()

    por_dia = {}
    for dia, texto in linhas:
        if dia is None:
            continue
        edicoes, palavras = por_dia.get(dia, (0, 0))
        por_dia[dia] = (edicoes + 1, palavras + count_words(texto))

    ordenado = sorted(por_dia.items(), key=lambda item: item[0], reverse=True)
    return [(dia, edicoes, palavras) for dia, (edicoes, palavras) in ordenado[:limit]]


def get_database_stats(cursor):
    total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]

    # Agrupado pelo PAR, e nao so pelo destino: com a origem gravada, "12.000
    # traducoes em pt" esconde justamente a informacao que o usuario passou a
    # pedir — quantas vieram de cada lingua.
    per_language = cursor.execute("""
        SELECT
            source_language,
            target_language,
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0)
        FROM comments
        GROUP BY source_language, target_language
        ORDER BY target_language, source_language
    """).fetchall()

    verified_total, pending_total = cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0)
        FROM comments
    """).fetchone()

    return {
        "total": total,
        "verified_total": verified_total,
        "pending_total": pending_total,
        "per_language": per_language,
        # Progresso por obra (ROADMAP 18). Vem vazio num banco cujos arquivos
        # nunca foram processados desde a migracao 7, e a tela precisa dizer isso
        # em vez de mostrar um bloco em branco: a ausencia aqui e "ninguem
        # reprocessou ainda", nao "nao ha traducao".
        "per_file": get_file_progress(cursor),
    }


def fetch_export_rows(cursor, only_ids=None):
    """Cursor das linhas do CSV — deliberadamente NAO materializado.

    O `fetchall` que estava aqui construia uma lista com o banco inteiro antes
    de a primeira linha ser escrita: 102 MB residentes em 195.607 linhas, so
    para depois entregar tudo ao `csv.writerows`, que aceita qualquer iteravel.

    Quem quiser a lista chama `list(...)`; o exportador nao quer.

    O `id` vem PRIMEIRO (ROADMAP 19, item 8). Ele nao existia no CSV, e sem ele o
    unico jeito de reencontrar uma linha depois de editar a planilha e o texto do
    original — o que funciona ate alguem corrigir uma vírgula do original. Com o id
    na planilha, o round-trip passa a ser conferivel; a importacao continua casando
    por texto, e isso esta declarado como limite na SPEC.

    `only_ids` restringe a exportacao a uma lista de ids, que e o que a selecao em
    lote do editor usa (ROADMAP 19, item 9). Uma lista VAZIA nao e o mesmo que
    `None`: ela exporta zero linhas, porque foi isso que quem chamou pediu. Tratar
    as duas como a mesma coisa exportaria o banco inteiro para quem pediu nada.
    """
    if only_ids is None:
        return cursor.execute("""
            SELECT
                id,
                original_comment,
                translated_comment,
                source_language,
                target_language,
                verified,
                created_at,
                updated_at,
                verified_at,
                review_status,
                reviewer_note
            FROM comments
            ORDER BY id
        """)

    marcadores = ",".join("?" * len(only_ids))
    return cursor.execute(
        f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            source_language,
            target_language,
            verified,
            created_at,
            updated_at,
            verified_at,
            review_status,
            reviewer_note
        FROM comments
        WHERE id IN ({marcadores})
        ORDER BY id
        """,
        list(only_ids),
    )


def _review_where(
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    cursor=None,
    source_language=None,
    source_file=None,
):
    """Monta o `WHERE` compartilhado por contagem, paginacao e offset.

    `search_mode` decide COMO a busca filtra, e as duas formas existem por
    motivos diferentes (garantia R8):

    - `terms` usa o indice FTS5. Cada interacao passa a custar o tamanho da
      pagina, e nao o da tabela. Em troca, casa palavras inteiras: `bisp` so
      acha "bispo" com `bisp*`.
    - `substring` mantem o `LIKE '%x%'`, que acha qualquer trecho — inclusive no
      meio de uma palavra — ao preco de varrer a tabela. E o unico jeito de
      procurar por um pedaco literal, entao continua disponivel. LITERAL e a
      palavra: o que o usuario digita passa por `escape_like_pattern`, senao um
      `%` no texto dele viraria curinga.

    Cai para `substring` sozinho quando o indice nao existe ou o SQLite nao tem
    FTS5, e tambem quando a expressao nao sobra nenhum termo utilizavel. Um
    resultado correto e lento e melhor que um erro.

    `source_language` restringe ao idioma de ORIGEM. `None` significa "todos", e
    e diferente de `""`: a string vazia e um idioma de origem legitimo — o das
    linhas gravadas antes de o programa perguntar e o das execucoes em deteccao
    automatica —, entao filtrar por ela devolve exatamente essas. Tratar as duas
    como a mesma coisa faria o filtro "Nao informado" mostrar a tabela inteira.

    `source_file` restringe ao ARQUIVO de onde o comentario foi lido (ROADMAP 18).
    Duas decisoes moram nesta clausula, e as duas foram medidas:

    **Nao e um `JOIN`.** O mesmo comentario aparece trinta vezes no mesmo arquivo —
    "Diagram" aparece —, e um `JOIN` devolveria a mesma linha trinta vezes numa
    lista cuja identidade e o comentario.

    **E `IN`, e nao `EXISTS`.** Os dois dizem a mesma coisa (pertence ao conjunto,
    uma vez) e custam ordens de grandeza diferentes: o `EXISTS` e correlacionado,
    entao o SQLite varre `comments` e pergunta linha por linha, enquanto o `IN` com
    subconsulta independente vira uma lista que ele percorre pelo indice do
    arquivo, buscando cada comentario por `rowid`. Medido em 201.500 linhas com 200
    mil ocorrencias (banco sintetizado, ver o apendice do ROADMAP):

        pagina em ordem de leitura   EXISTS 831 ms   IN  1,6 ms
        total do filtro              EXISTS  70 ms   IN  0,6 ms

    O `EXISTS` foi a primeira escrita aqui, e a medicao e que o derrubou.
    """
    clauses = ["target_language = ?"]
    params = [target_language]

    if source_language is not None:
        clauses.append("source_language = ?")
        params.append(source_language)

    if source_file:
        clauses.append(
            f"id IN (SELECT comment_id FROM {OCCURRENCES_TABLE}"
            f" WHERE source_file = ?)"
        )
        params.append(source_file)

    if status_filter is None:
        status_filter = "pending" if only_unverified else "all"

    if status_filter == "pending":
        clauses.append("verified <> 1")
    elif status_filter == "verified":
        clauses.append("verified = 1")
    elif status_filter == REVIEW_STATUS_REJECTED:
        # `verified <> 1` junto com o status, e nao so o status: os dois campos
        # andam em lockstep (verificar limpa o status), e exigir os dois faz o filtro
        # continuar correto se algum dia um `UPDATE` de fora quebrar o par.
        clauses.append("verified <> 1 AND review_status = ?")
        params.append(REVIEW_STATUS_REJECTED)
    elif status_filter == REVIEW_STATUS_DOUBT:
        clauses.append("verified <> 1 AND review_status = ?")
        params.append(REVIEW_STATUS_DOUBT)
    elif status_filter == "warnings":
        # Usa a coluna materializada: contar e paginar "com aviso" vira uma
        # consulta indexada, em vez de ler a tabela inteira e avaliar em Python.
        clauses.append("quality_warning = 1")

    search_text = (search_text or "").strip()
    if search_text:
        expressao = None
        if search_mode == SEARCH_MODE_TERMS and cursor is not None and fts_index_ready(cursor):
            expressao = build_fts_match_query(search_text)

        if expressao is not None:
            clauses.append(
                f"id IN (SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?)"
            )
            params.append(expressao)
        else:
            clauses.append(LIKE_MATCH_SQL)
            pattern = f"%{escape_like_pattern(search_text)}%"
            params.extend([pattern, pattern])

    return " AND ".join(clauses), params


_OCCURRENCE_RANK_SQL = (
    f"(SELECT MIN(o.comment_index) FROM {OCCURRENCES_TABLE} o"
    f" WHERE o.comment_id = comments.id AND o.source_file = ?)"
)


def reads_in_occurrence_order(order, source_file):
    """A ordem de leitura vale? Ela exige o arquivo, e nao e capricho.

    Sem arquivo escolhido, "a proxima linha da obra" nao existe: o mesmo
    comentario aparece em varios arquivos, e ordenar pela PRIMEIRA ocorrencia de
    cada um pediria um minimo por comentario sobre a tabela inteira a cada pagina
    — O(n) por interacao, que e exatamente o que a garantia R5 proibe. Com um
    arquivo, o mesmo minimo custa uma busca indexada por linha da pagina.

    Devolver `False` em vez de recusar e deliberado: quem pediu ordem de leitura
    sem arquivo recebe a lista em ordem de id, que e uma lista correta.
    """
    return order == ORDER_BY_OCCURRENCE and bool(source_file)


def _review_order(order=None, source_file=None):
    """O `ORDER BY` da lista e os parametros dele.

    Paginar por `LIMIT/OFFSET` exige uma ordem TOTAL: duas linhas com a mesma
    chave podem trocar de lugar entre duas consultas, e ai uma aparece em duas
    paginas e a outra em nenhuma — sem erro em lugar nenhum.

    **O `id` do fim e, hoje, inalcancavel, e isto esta escrito para nao ser lido
    como protecao ativa.** `UNIQUE(source_file, comment_index)` faz os indices de
    um arquivo serem distintos, entao os minimos de dois comentarios diferentes
    tambem sao — o desempate nunca decide nada, e a mutacao que o remove sobrevive
    por isso. Ele fica porque o filtro por arquivo e de UM arquivo, e no dia em que
    for de uma obra inteira (varios arquivos) os minimos passam a poder empatar; o
    preco de deixar e uma clausula, e o de tirar e uma pagina que repete linha.
    """
    if reads_in_occurrence_order(order, source_file):
        return f"{_OCCURRENCE_RANK_SQL}, id", [source_file]
    return "id", []


def fetch_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
    order=None,
):
    """As linhas do editor, com o par de idiomas e o aviso de qualidade no fim.

    No fim de proposito, e nao no meio: o editor le as sete primeiras posicoes em
    varios pontos (`row_label`, `row_color`, a cache da linha atual), e inserir
    uma coluna deslocaria todas elas. Cada acrescimo entrou depois do anterior —
    hoje sao nove colunas, e a nona e `quality_warning`.

    O par esta aqui porque a avaliacao de qualidade precisa dele — a heuristica de
    terminologia e escopada por idioma (ROADMAP 16.1). Sem ele, a tela avaliaria
    sem par e a coluna materializada com par, e as duas divergiriam sem nada
    quebrar: e a garantia R6.

    `quality_warning` vem da COLUNA, e nao de avaliar o texto de novo em Python
    (ROADMAP 19, item 4). Sao a mesma resposta enquanto R6 valer, e usar a coluna e
    o que garante que o marcador da linha concorde com o filtro "Avisos QA" — que
    tambem le a coluna. Avaliar em Python daria uma tela em que a linha nao tem
    marcador e o filtro a mostra.
    """
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    order_sql, order_params = _review_order(order, source_file)
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at,
            source_language,
            target_language,
            quality_warning
        FROM comments
        WHERE {where_sql}
        ORDER BY {order_sql}
    """, params + order_params).fetchall()


def count_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql}
    """, params).fetchone()[0]


def review_status_counts_query(
    target_language,
    search_text="",
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
    cursor=None,
):
    """`(sql, params)` do resumo por status.

    Separada da execucao para que o teste do PLANO possa perguntar pelo mesmo
    SQL que a producao roda (ROADMAP 22.13). Com a consulta escrita dentro da
    funcao que a executa, o teste de `EXPLAIN QUERY PLAN` teria de transcreve-la
    — e passaria a medir a propria transcricao, que continuaria coberta enquanto
    a de verdade deixasse de ser.
    """
    where_sql, params = _review_where(
        target_language,
        search_text=search_text,
        status_filter="all",
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    sql = f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN quality_warning = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(
                CASE WHEN verified <> 1 AND review_status = '{REVIEW_STATUS_REJECTED}'
                THEN 1 ELSE 0 END
            ), 0),
            COALESCE(SUM(
                CASE WHEN verified <> 1 AND review_status = '{REVIEW_STATUS_DOUBT}'
                THEN 1 ELSE 0 END
            ), 0)
        FROM comments
        WHERE {where_sql}
    """
    return sql, params


def get_review_status_counts(
    cursor,
    target_language,
    search_text="",
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
):
    sql, params = review_status_counts_query(
        target_language,
        search_text=search_text,
        search_mode=search_mode,
        source_language=source_language,
        source_file=source_file,
        cursor=cursor,
    )
    total, pending, verified, warnings, rejected, doubt = cursor.execute(
        sql, params
    ).fetchone()
    return {
        "total": total,
        "pending": pending,
        "verified": verified,
        "warnings": warnings,
        # Subconjuntos de `pending`, e nao categorias ao lado dela: uma linha
        # rejeitada continua sendo uma linha que falta resolver, e some-la ao
        # pendente daria um total maior que a tabela (ROADMAP 19, item 12).
        REVIEW_STATUS_REJECTED: rejected,
        REVIEW_STATUS_DOUBT: doubt,
    }


# O total de cada filtro da lista ja esta dentro do resumo acima: as duas
# consultas varrem a mesma tabela com o mesmo `WHERE`, e a agregada so separa por
# status o que a outra conta inteiro. A correspondencia mora aqui, e nao
# espalhada pelo editor, para que o teste que a protege tenha um lugar so a que
# apontar — se os dois criterios divergirem, a lista pagina pelo numero errado
# sem nada quebrar na tela.
STATUS_COUNT_KEYS = {
    "all": "total",
    "pending": "pending",
    "verified": "verified",
    "warnings": "warnings",
    REVIEW_STATUS_REJECTED: REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_DOUBT: REVIEW_STATUS_DOUBT,
}


def count_from_status_counts(status_counts, status_filter=None, only_unverified=False):
    """O total do filtro, tirado do resumo ja calculado.

    Devolve `None` quando o resumo nao cobre o filtro pedido, para o chamador
    cair no `count_review_rows`. A ausencia e explicita de proposito: um zero
    devolvido por engano esvaziaria a lista sem erro nenhum.
    """
    if status_filter is None:
        status_filter = "pending" if only_unverified else "all"
    key = STATUS_COUNT_KEYS.get(status_filter)
    if key is None:
        return None
    return status_counts.get(key)


def fetch_review_row_ids(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
):
    """So os ids das linhas do filtro — todas, sem paginacao (ROADMAP 22.11).

    Existe para o "Marcar tudo" da selecao em lote. A barra so sabia marcar a
    PAGINA, e marcar os 3.000 resultados de um capitulo eram 30 idas ao botao
    mais 29 viradas de pagina — custo de interface, e nao de banco: o mesmo
    `WHERE` que a lista ja usa devolve os ids em milissegundos.

    **Sem `ORDER BY`.** O resultado alimenta um conjunto de ids marcados, e
    conjunto nao tem ordem; ordenar seria uma passada a mais em 200 mil linhas
    para um dado que ninguem le. E a razao de esta funcao nao aceitar `order`,
    que e o parametro que as outras tres desta familia recebem.
    """
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    return [
        linha[0]
        for linha in cursor.execute(
            f"SELECT id FROM comments WHERE {where_sql}", params
        ).fetchall()
    ]


def fetch_review_rows_page(
    cursor,
    target_language,
    only_unverified=False,
    limit=100,
    offset=0,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
    order=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    order_sql, order_params = _review_order(order, source_file)
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at,
            source_language,
            target_language,
            quality_warning
        FROM comments
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """, params + order_params + [limit, offset]).fetchall()


def get_review_row_offset(
    cursor,
    target_language,
    comment_id,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
    source_file=None,
    order=None,
):
    """A posicao da linha NA LISTA FILTRADA, ou `None` se ela nao esta nela.

    "Posicao" depende da ordem, e essa e a parte que nao da para esquecer: em
    ordem de id, quantas linhas tem id menor; em ordem de leitura, quantas
    aparecem ANTES no arquivo. Contar ids com a lista ordenada por ocorrencia
    devolveria um numero coerente e errado, e o "Ir para ID" pousaria noutra
    pagina — a mesma classe de defeito que a garantia R10 fechou.
    """
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
        source_file=source_file,
    )
    row = cursor.execute(f"""
        SELECT id
        FROM comments
        WHERE {where_sql} AND id = ?
    """, params + [comment_id]).fetchone()

    if row is None:
        return None

    if not reads_in_occurrence_order(order, source_file):
        return cursor.execute(f"""
            SELECT COUNT(*)
            FROM comments
            WHERE {where_sql} AND id < ?
        """, params + [comment_id]).fetchone()[0]

    # A comparacao por valor de linha (`(a, b) < (c, d)`) e o mesmo criterio do
    # `ORDER BY` de `_review_order`, escrito uma vez. Separar os dois em duas
    # expressoes que precisam concordar seria pedir para elas divergirem.
    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql}
          AND ({_OCCURRENCE_RANK_SQL}, id) < (
              (SELECT MIN(o.comment_index) FROM {OCCURRENCES_TABLE} o
               WHERE o.comment_id = ? AND o.source_file = ?), ?
          )
    """, params + [source_file, comment_id, source_file, comment_id]).fetchone()[0]


def fetch_translation_by_id(cursor, comment_id):
    # O par de idiomas vem no fim de proposito: quem le esta linha o faz por
    # posicao em varios pontos do editor, e acrescentar no meio deslocaria todos.
    return cursor.execute("""
        SELECT
            original_comment,
            translated_comment,
            created_at,
            updated_at,
            verified_at,
            source_language,
            target_language
        FROM comments
        WHERE id = ?
    """, (comment_id,)).fetchone()


def record_comment_history(
    cursor,
    comment_id,
    action,
    previous_translation,
    new_translation,
    previous_verified,
    new_verified,
):
    cursor.execute(
        """
        INSERT INTO comment_history (
            comment_id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            comment_id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
        ),
    )
    return cursor.lastrowid


def fetch_comment_history(cursor, comment_id, limit=50):
    return cursor.execute(
        """
        SELECT
            id,
            action,
            previous_translation,
            new_translation,
            previous_verified,
            new_verified,
            created_at
        FROM comment_history
        WHERE comment_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (comment_id, limit),
    ).fetchall()


def update_translation_by_id(
    cursor,
    comment_id,
    translated_comment,
    mark_verified=False,
    history_action=None,
):
    # O par de idiomas entra na leitura que esta funcao ja fazia. Sem ele, o
    # `quality_warning_flag` daqui avaliaria a terminologia como se o par fosse
    # desconhecido e a exibicao a avaliaria com o par da linha: a coluna
    # materializada divergiria da tela (garantia R6).
    existing = cursor.execute(
        """
        SELECT translated_comment, verified, original_comment,
               source_language, target_language
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    (
        previous_translation,
        previous_verified,
        original_comment,
        source_language,
        target_language,
    ) = existing
    previous_verified = 1 if previous_verified == 1 else 0
    new_verified = 1 if mark_verified else previous_verified

    if previous_translation == translated_comment and previous_verified == new_verified:
        return 0

    if history_action is None:
        translation_changed = previous_translation != translated_comment
        status_changed = previous_verified != new_verified
        if translation_changed and status_changed:
            history_action = "edit_verify"
        elif translation_changed:
            history_action = "edit"
        elif new_verified == 1:
            history_action = "verify"
        else:
            history_action = "status"

    # `review_status = ''` quando a gravacao verifica a linha: e o MESMO lockstep de
    # `set_translation_verified_by_id` (ROADMAP 19, item 12), e ele tem de valer nos
    # dois caminhos que ligam o `verified`. Este e o do "Salvar e verificar", e sem a
    # clausula aqui uma linha ficava verificada E em duvida ao mesmo tempo — estado
    # que nenhum filtro mostra direito, e que foi um teste da janela que encontrou.
    cursor.execute("""
        UPDATE comments
        SET translated_comment = ?,
            quality_warning = ?,
            verified = CASE WHEN ? THEN 1 ELSE verified END,
            review_status = CASE WHEN ? THEN '' ELSE review_status END,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE verified_at END
        WHERE id = ?
    """, (
        translated_comment,
        quality_warning_flag(
            original_comment, translated_comment, source_language, target_language
        ),
        1 if mark_verified else 0,
        1 if mark_verified else 0,
        1 if mark_verified else 0,
        comment_id,
    ))
    changed_rows = cursor.rowcount
    if changed_rows:
        record_comment_history(
            cursor,
            comment_id,
            history_action,
            previous_translation,
            translated_comment,
            previous_verified,
            new_verified,
        )
    return changed_rows


def overwrite_translation_by_id(cursor, comment_id, translated_comment, verified=False):
    """Sobrescreve uma traducao JA PREENCHIDA. E a excecao explicita a T1.

    `save_translation` nunca sobrescreve (garantia T1), e esse e o padrao certo
    para o worker: uma traducao gravada pode ter sido revisada a mao, e a API nao
    tem autoridade para desfazer isso. Mas o padrao virava um beco no fluxo de
    quem traduz um livro — exportar o CSV, corrigir 300 traducoes na planilha,
    importar — porque a importacao devolvia as 300 como "sem alteracao".

    O que muda aqui e de quem vem o texto: nao da API, e de uma decisao do
    usuario sobre um arquivo que ele mesmo editou. Sobrescrever passa a ser
    possivel, mas nunca por acidente — quem chama tem de pedir.

    **Nao faz nada quando o texto e igual ao gravado**, nem para mexer no
    `verified`. Um CSV montado a mao pode nao ter a coluna `verified`, e a
    ausencia dela nao e uma afirmacao de que nada foi revisado: tratada como
    afirmacao, uma importacao de rotina rebaixaria para "pendente" cada linha que
    voltou igual. Marcar linhas ja gravadas como verificadas continua possivel —
    por `set_translation_verified_by_id`, que so promove.

    **`verified` volta a zero quando o texto muda**, a nao ser que o CSV diga o
    contrario. Aqui a demissao e justificada e nao opcional: a revisao era do
    texto anterior. Manter a marca sobre um texto que ninguem leu e exatamente o
    que as garantias R9 e V1 existem para impedir, e e a mesma regra que
    `save_translation` aplica ao preencher uma linha vazia.

    A coluna `quality_warning` e reavaliada (garantia R6) e toda alteracao entra
    no historico (garantia R2), com acao propria: o usuario precisa poder ver o
    que a importacao passou por cima e voltar atras.
    """
    existing = cursor.execute(
        """
        SELECT translated_comment, verified, original_comment,
               source_language, target_language
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    (
        previous_translation,
        previous_verified,
        original_comment,
        source_language,
        target_language,
    ) = existing
    if previous_translation == translated_comment:
        return 0

    previous_verified = 1 if previous_verified == 1 else 0
    new_verified = 1 if verified else 0

    # A sobrescrita pelo CSV troca o TEXTO da linha, entao o status de revisao
    # anterior fala de um texto que nao existe mais: ele sai junto, verificada ou
    # nao. E o mesmo criterio com que ela rebaixa o `verified` — a revisao era do
    # texto anterior (ROADMAP 17.7, agora tambem para o item 12 da 19).
    cursor.execute(
        """
        UPDATE comments
        SET translated_comment = ?,
            quality_warning = ?,
            verified = ?,
            review_status = '',
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id = ?
        """,
        (
            translated_comment,
            quality_warning_flag(
                original_comment, translated_comment, source_language, target_language
            ),
            new_verified,
            new_verified,
            comment_id,
        ),
    )
    changed_rows = cursor.rowcount
    if changed_rows:
        record_comment_history(
            cursor,
            comment_id,
            "csv_overwrite",
            previous_translation,
            translated_comment,
            previous_verified,
            new_verified,
        )
    return changed_rows


def set_translation_verified_by_id(cursor, comment_id, verified=True):
    existing = cursor.execute(
        """
        SELECT translated_comment, verified
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    translation, previous_verified = existing
    previous_verified = 1 if previous_verified == 1 else 0
    new_verified = 1 if verified else 0
    if previous_verified == new_verified:
        return 0

    # Verificar LIMPA o status de revisao (ROADMAP 19, item 12): uma traducao aceita
    # nao esta "em duvida" nem "rejeitada". E a regra que mantem os dois campos em
    # lockstep, e ela vive aqui porque este e o unico caminho que liga o `verified`.
    cursor.execute("""
        UPDATE comments
        SET verified = ?,
            review_status = CASE WHEN ? THEN '' ELSE review_status END,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id = ?
    """, (
        1 if verified else 0,
        1 if verified else 0,
        1 if verified else 0,
        comment_id,
    ))
    changed_rows = cursor.rowcount
    if changed_rows:
        record_comment_history(
            cursor,
            comment_id,
            "verify" if verified else "mark_pending",
            translation,
            translation,
            previous_verified,
            new_verified,
        )
    return changed_rows


def set_review_status_by_id(cursor, comment_id, status, note=None):
    """Marca a linha como rejeitada, em duvida ou pendente. `1` se mudou algo.

    `note` a `None` deixa a nota como esta; uma string a substitui (inclusive por
    vazia, que e como se apaga). Sao duas coisas na mesma chamada porque na tela sao
    uma: quem rejeita escreve por que.

    **Um status alem de pendente derruba o `verified`.** Rejeitar uma traducao
    marcada como verificada e dizer que a verificacao estava errada — deixar o bit
    de pe manteria a linha fora do filtro de pendentes, e ela nunca voltaria para a
    fila de ninguem. O par de campos e mantido em lockstep aqui e em
    `set_translation_verified_by_id`, que sao os dois unicos lugares que escrevem
    qualquer um dos dois.
    """
    if status not in REVIEW_STATUSES:
        raise ValueError(f"status de revisao desconhecido: {status!r}")

    existing = cursor.execute(
        "SELECT review_status, reviewer_note, verified FROM comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    status_anterior, nota_anterior, verified_anterior = existing
    nota_nova = nota_anterior if note is None else note
    verified_novo = 0 if status else (1 if verified_anterior == 1 else 0)
    if (
        (status_anterior or "") == status
        and (nota_anterior or "") == (nota_nova or "")
        and (verified_anterior == 1) == (verified_novo == 1)
    ):
        return 0

    cursor.execute(
        """
        UPDATE comments
        SET review_status = ?,
            reviewer_note = ?,
            verified = ?,
            verified_at = CASE WHEN ? THEN verified_at ELSE NULL END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, nota_nova, verified_novo, verified_novo, comment_id),
    )
    return cursor.rowcount


def fetch_review_status_by_id(cursor, comment_id):
    """`(status, nota)` da linha, ou `("", "")` se ela nao existe."""
    linha = cursor.execute(
        "SELECT review_status, reviewer_note FROM comments WHERE id = ?",
        (comment_id,),
    ).fetchone()
    if linha is None:
        return REVIEW_STATUS_PENDING, ""
    return (linha[0] or REVIEW_STATUS_PENDING), (linha[1] or "")


def _exact_translation_matches(cursor, comment_id, exclude_self=False):
    """`(traducao, [(id, original)])` — a base da previa e da escrita.

    As duas leem daqui de proposito: se a previa e a gravacao montassem a
    consulta cada uma por si, elas poderiam discordar sem que nada quebrasse na
    tela — a armadilha dos itens 2.8, 3.6 e 11.1.

    `exclude_self` e a UNICA diferenca entre as duas, e ela existe por causa do
    que cada uma responde. A previa responde "o que mais isto vai marcar", e a
    propria linha nao e uma consequencia — o usuario acabou de pedir para
    verifica-la. A escrita responde "quais linhas deste par tem esta traducao", e
    ai a propria linha entra: chamada sem passar pelo editor (que ja a verifica
    antes), excluir-la deixaria o par metade verificado.
    """
    existing = cursor.execute(
        """
        SELECT translated_comment, source_language, target_language
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return None, []

    translation, source_language, target_language = existing
    if not translation:
        return translation, []

    # Dentro do mesmo PAR de idiomas. Verificar uma traducao vinda do espanhol
    # nao diz nada sobre a mesma frase vinda do ingles — e marcar as duas daria
    # por revisado o que o usuario nem viu, justamente na tela que ele abriu para
    # nao misturar as linguas.
    clauses = [
        "target_language = ?",
        "source_language = ?",
        "translated_comment = ?",
        "verified <> 1",
    ]
    params = [target_language, source_language, translation]
    if exclude_self:
        clauses.append("id <> ?")
        params.append(comment_id)

    rows = cursor.execute(
        f"""
        SELECT id, original_comment
        FROM comments
        WHERE {" AND ".join(clauses)}
        ORDER BY id
        """,
        params,
    ).fetchall()
    return translation, rows


def fetch_exact_translation_match_candidates(cursor, comment_id):
    """As OUTRAS linhas que a verificacao em massa marcaria, com o original de cada.

    Existe para que a propagacao possa ser mostrada antes de acontecer (garantia
    V1). Ela casa pela TRADUCAO, que e a unica propagacao possivel — originais
    identicos ja sao uma linha so, pela UNIQUE — e quase sempre e o que se quer;
    o risco esta nas traducoes curtas. Se o tradutor verteu "Checkmate." errado
    como "Empate.", verificar o "Draw." -> "Empate." legitimo marca a outra
    junto: da por revisado o que ninguem leu, que e exatamente o que a garantia
    R9 existe para impedir.

    Devolve `(id, original_comment)` por linha, em ordem de id. Cada uma tem um
    original DIFERENTE — dentro do par, a UNIQUE garante isso —, e e por isso que
    a contagem que interessa ao usuario e "quantos originais", e nao "quantas
    iguais".
    """
    _translation, rows = _exact_translation_matches(
        cursor, comment_id, exclude_self=True
    )
    return rows


def set_exact_translation_matches_verified(cursor, comment_id, only_ids=None):
    """Marca como verificadas as linhas do par com a MESMA traducao.

    `only_ids` restringe a propagacao ao subconjunto que o usuario aprovou na
    previa. `None` propaga para todas as candidatas, que e o que a chamada sem
    previa sempre fez.
    """
    translation, rows = _exact_translation_matches(cursor, comment_id)
    if only_ids is not None:
        permitidos = set(only_ids)
        rows = [row for row in rows if row[0] in permitidos]
    if not rows:
        return 0

    changed_rows = 0
    for matching_id, _original in rows:
        # Zero por construcao: o filtro da consulta e `verified <> 1`, e em SQL
        # um `NULL` nao satisfaz essa comparacao. Nao ha o que ler de volta.
        previous_verified = 0
        cursor.execute(
            """
            UPDATE comments
            SET verified = 1,
                review_status = '',
                updated_at = CURRENT_TIMESTAMP,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (matching_id,),
        )
        if cursor.rowcount:
            changed_rows += 1
            record_comment_history(
                cursor,
                matching_id,
                "verify_exact_match",
                translation,
                translation,
                previous_verified,
                1,
            )
    return changed_rows


def clear_all_translations(conn):
    """Esvazia o banco de traducoes e devolve quantas linhas havia.

    Derruba as tabelas e deixa a migracao reconstrui-las, em vez de um
    `DELETE FROM comments`. Nao e preferencia de estilo: cada linha apagada
    dispara o gatilho que tira os termos dela do `comments_fts`, e sao 201.607
    gatilhos para uma operacao cujo resultado e uma tabela vazia. Derrubando a
    tabela, o `rebuild` do indice acontece uma vez so — sobre nada.

    O `VACUUM` no fim e o que devolve o espaco ao disco. Sem ele o arquivo
    continua com os 115 MB que o usuario acabou de mandar apagar, e "zerar o
    banco" que nao libera um byte parece nao ter funcionado.

    Nao ha cancelamento no meio, e por isso quem chama pergunta antes: depois do
    `DROP TABLE` nao existe estado anterior para voltar. O que existe e o backup,
    criado pela ferramenta antes de chamar isto.

    As **ocorrencias** vao junto (garantia Z3). Elas apontam para linhas de
    `comments` por id, e o `AUTOINCREMENT` reinicia com a tabela: uma ocorrencia
    sobrevivente passaria a apontar para a PRIMEIRA traducao que fosse gravada
    depois — o comentario errado, no arquivo certo, sem erro nenhum na tela.
    """
    cursor = conn.cursor()
    try:
        total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    except sqlite3.Error:  # pragma: no cover - banco sem a tabela ainda
        total = 0

    # Os gatilhos referenciam `comments`; precisam sair antes dela.
    for trigger in ("comments_fts_insert", "comments_fts_delete", "comments_fts_update"):
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    cursor.execute("DROP TABLE IF EXISTS comments")
    cursor.execute("DROP TABLE IF EXISTS comment_history")
    cursor.execute(f"DROP TABLE IF EXISTS {OCCURRENCES_TABLE}")
    conn.commit()

    _migrate_database(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()

    try:
        conn.execute("VACUUM")
    except sqlite3.DatabaseError:  # pragma: no cover - defensivo
        pass

    return total


class AutomaticRulesCanceled(Exception):
    """A varredura das regras automaticas foi interrompida pelo usuario."""


def _automatic_rules_query(target_language, source_language=None):
    clauses = [
        "translated_comment IS NOT NULL",
        "translated_comment <> ''",
    ]
    params = []
    if target_language:
        clauses.append("target_language = ?")
        params.append(target_language)
    # `None` e "todas as origens"; `""` e a origem "nao informada", que e um
    # valor como qualquer outro (ver `_review_where`).
    if source_language is not None:
        clauses.append("source_language = ?")
        params.append(source_language)
    return " AND ".join(clauses), params


def _iter_automatic_rule_rows(
    cursor,
    target_language,
    progress_callback=None,
    should_cancel=None,
    progress_every=2000,
    source_language=None,
):
    """Itera as linhas candidatas SEM materializar a tabela.

    O `fetchall` anterior trazia 195.603 linhas de texto de uma vez — 80 MB de
    pico so nessa lista, e a lista era construida antes de a primeira linha ser
    examinada. Iterando o cursor, a memoria e constante e o progresso comeca a
    andar na hora.

    `progress_every` existe para nao pagar uma chamada de callback por linha: a
    interface nao precisa de 195 mil atualizacoes, e cada uma custa um
    `root.after`.
    """
    where_sql, params = _automatic_rules_query(target_language, source_language)
    total = cursor.execute(
        f"SELECT COUNT(*) FROM comments WHERE {where_sql}", params
    ).fetchone()[0]

    if progress_callback:
        progress_callback(0, total)

    lidas = 0
    for row in cursor.execute(
        f"""
        SELECT id, original_comment, translated_comment,
               source_language, target_language, verified
        FROM comments
        WHERE {where_sql}
        ORDER BY id
        """,
        params,
    ):
        lidas += 1
        if should_cancel is not None and lidas % 200 == 0 and should_cancel():
            raise AutomaticRulesCanceled()
        if progress_callback and (lidas % progress_every == 0 or lidas == total):
            progress_callback(lidas, total)
        yield row

    if progress_callback:
        progress_callback(total, total)


def _empty_automatic_stats(target_language, rules=0):
    return {
        "rules": rules,
        "scanned": 0,
        "changed": 0,
        "unchanged": 0,
        "target_language": target_language,
        "examples": [],
    }


def analyze_automatic_translation_updates(
    cursor,
    automatic_rules,
    apply_substitutions,
    target_language=None,
    sample_limit=10,
    progress_callback=None,
    should_cancel=None,
    source_language=None,
):
    if not automatic_rules:
        return _empty_automatic_stats(target_language)

    scanned = 0
    changed = 0
    examples = []
    for (
        comment_id,
        original,
        translation,
        _row_source_language,
        row_language,
        _verified,
    ) in _iter_automatic_rule_rows(
        cursor,
        target_language,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        source_language=source_language,
    ):
        scanned += 1
        updated_translation = apply_substitutions(translation, automatic_rules)
        if updated_translation != translation:
            changed += 1
            if len(examples) < sample_limit:
                examples.append(
                    {
                        "id": comment_id,
                        "original_comment": original,
                        "target_language": row_language,
                        "previous_translation": translation,
                        "new_translation": updated_translation,
                    }
                )

    return {
        "rules": len(automatic_rules),
        "scanned": scanned,
        "changed": changed,
        "unchanged": scanned - changed,
        "target_language": target_language,
        "examples": examples,
    }


def apply_automatic_translation_updates(
    cursor,
    automatic_rules,
    apply_substitutions,
    target_language=None,
    sample_limit=10,
    progress_callback=None,
    should_cancel=None,
    source_language=None,
):
    """Aplica as regras automaticas numa unica passagem.

    Antes, a primeira linha desta funcao era uma chamada a
    `analyze_automatic_translation_updates` — que percorre a tabela inteira
    aplicando as regras — e so depois vinha a passagem de escrita, que percorria
    tudo e aplicava as regras DE NOVO. Somada a previa que a interface ja tinha
    calculado para montar o dialogo de confirmacao, um clique no botao custava
    tres passagens completas: 38,1 s no banco real, com a janela travada.

    A previa continua existindo (o usuario precisa confirmar sabendo quantas
    linhas mudam), mas esta funcao nao a repete: ela calcula e grava no mesmo
    laco. Sao duas passagens em vez de tres.

    A escrita usa um cursor proprio: `UPDATE` no mesmo cursor que esta iterando
    o `SELECT` invalidaria a iteracao.
    """
    if not automatic_rules:
        return _empty_automatic_stats(target_language)

    write_cursor = cursor.connection.cursor()
    scanned = 0
    changed = 0
    examples = []

    for (
        comment_id,
        original_comment,
        previous_translation,
        row_source_language,
        row_language,
        previous_verified,
    ) in (
        _iter_automatic_rule_rows(
            cursor,
            target_language,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            source_language=source_language,
        )
    ):
        scanned += 1
        previous_verified = 1 if previous_verified == 1 else 0
        updated_translation = apply_substitutions(previous_translation, automatic_rules)
        if updated_translation == previous_translation:
            continue

        write_cursor.execute(
            """
            UPDATE comments
            SET translated_comment = ?,
                quality_warning = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                updated_translation,
                quality_warning_flag(
                    original_comment, updated_translation,
                    row_source_language, row_language,
                ),
                comment_id,
            ),
        )
        if write_cursor.rowcount:
            changed += 1
            if len(examples) < sample_limit:
                examples.append(
                    {
                        "id": comment_id,
                        "original_comment": original_comment,
                        "target_language": row_language,
                        "previous_translation": previous_translation,
                        "new_translation": updated_translation,
                    }
                )
            record_comment_history(
                write_cursor,
                comment_id,
                "automatic_rules",
                previous_translation,
                updated_translation,
                previous_verified,
                previous_verified,
            )

    return {
        "rules": len(automatic_rules),
        "scanned": scanned,
        "changed": changed,
        "unchanged": scanned - changed,
        "target_language": target_language,
        "examples": examples,
    }


class MoveNotationCanceled(Exception):
    """A varredura da correcao de lances foi interrompida pelo usuario."""


def _move_notation_where(source_language, include_unknown):
    """O `WHERE` das linhas em escopo, num lugar so.

    A previa e a aplicacao PRECISAM usar o mesmo criterio, e a primeira versao
    nao usava: a previa olhava so o par declarado, mas as linhas legadas ainda
    estavam como "origem nao informada" e so entravam no par durante a
    aplicacao. Resultado, a previa dizia "nenhuma traducao precisa de correcao"
    exatamente no caso para o qual a ferramenta existe.

    E a mesma armadilha dos itens 2.8 e 3.6: dois criterios em dois lugares nao
    quebram nada visivel — eles so discordam.
    """
    clauses = [
        "target_language = ?",
        "translated_comment IS NOT NULL",
        "translated_comment <> ''",
        "original_comment IS NOT NULL",
        "original_comment <> ''",
    ]
    params = [None]  # o destino, preenchido por quem chama
    if include_unknown:
        clauses.insert(1, "source_language IN (?, ?)")
        params.extend([source_language, SOURCE_LANGUAGE_UNKNOWN])
    else:
        clauses.insert(1, "source_language = ?")
        params.append(source_language)
    return " AND ".join(clauses), params


def _move_notation_rows(cursor, source_language, target_language, include_unknown):
    """As linhas em escopo que tem texto dos dois lados para comparar."""
    where_sql, params = _move_notation_where(source_language, include_unknown)
    params[0] = target_language
    return cursor.execute(
        f"""
        SELECT id, original_comment, translated_comment, verified
        FROM comments
        WHERE {where_sql}
        ORDER BY id
        """,
        params,
    )


def _move_notation_total(cursor, source_language, target_language, include_unknown):
    where_sql, params = _move_notation_where(source_language, include_unknown)
    params[0] = target_language
    return cursor.execute(
        f"SELECT COUNT(*) FROM comments WHERE {where_sql}", params
    ).fetchone()[0]


def count_adoptable_unknown_source(cursor, target_language, source_language):
    """Quantas linhas `adopt_unknown_source_language` de fato rotularia.

    Existe para a previa poder dizer o numero antes do "Sim". Rotular e a parte
    IRREVERSIVEL da correcao de lances — num banco com 200 mil linhas legadas, e
    afirmar "todo o meu acervo veio do espanhol" —, e ate agora esse numero so
    aparecia no dialogo de resultado, depois de feito.

    Nao e um `COUNT(*)` do escopo do `UPDATE`: aquele seria um teto, porque o
    `UPDATE OR IGNORE` pula a linha cuja adocao esbarraria na propria chave (ja
    existe o mesmo comentario no par declarado). O `NOT EXISTS` desconta
    exatamente essas, e usa o indice da UNIQUE. Um numero aproximado numa
    confirmacao que nao tem volta seria pior do que nenhum.

    Um `source_language` vazio nao rotula nada: "detectar automaticamente" nao e
    uma declaracao — a mesma regra da funcao que aplica.
    """
    if not source_language:
        return 0
    return cursor.execute(
        """
        SELECT COUNT(*)
        FROM comments AS legada
        WHERE legada.target_language = ?
          AND legada.source_language = ?
          AND NOT EXISTS (
              SELECT 1
              FROM comments AS declarada
              WHERE declarada.original_comment = legada.original_comment
                AND declarada.source_language = ?
                AND declarada.target_language = legada.target_language
          )
        """,
        (target_language, SOURCE_LANGUAGE_UNKNOWN, source_language),
    ).fetchone()[0]


def _empty_move_notation_stats(source_language, target_language, labeled=0):
    return {
        "source_language": source_language,
        "target_language": target_language,
        "labeled": labeled,
        "scanned": 0,
        "changed": 0,
        "moves": 0,
        "examples": [],
    }


def analyze_move_notation_updates(
    cursor,
    source_language,
    target_language,
    fix_notation,
    sample_limit=10,
    progress_callback=None,
    should_cancel=None,
    progress_every=2000,
    include_unknown=True,
):
    """Previa da correcao de lances: quantas linhas mudam, e alguns exemplos.

    `fix_notation(original, traduzido, origem, destino) -> (texto, quantos)` e
    injetada em vez de importada para manter `database.py` sem saber de xadrez —
    a mesma separacao que `apply_substitutions` tem nas regras automaticas.

    Nao grava nada. A previa existe porque o usuario precisa confirmar sabendo
    quantas linhas serao reescritas, e isto reescreve texto ja revisado.

    `labeled` vem preenchido com quantas linhas serao ROTULADAS — a parte que a
    previa nao dizia. So faz sentido quando as linhas sem origem estao no escopo:
    com `include_unknown=False` a ferramenta nao rotula nada, e o campo fica zero.
    """
    stats = _empty_move_notation_stats(source_language, target_language)
    if include_unknown:
        stats["labeled"] = count_adoptable_unknown_source(
            cursor, target_language, source_language
        )
    total = _move_notation_total(
        cursor, source_language, target_language, include_unknown
    )
    if progress_callback:
        progress_callback(0, total)

    lidas = 0
    for _id, original, traduzido, _verified in _move_notation_rows(
        cursor, source_language, target_language, include_unknown
    ):
        lidas += 1
        stats["scanned"] += 1
        if should_cancel is not None and lidas % 200 == 0 and should_cancel():
            raise MoveNotationCanceled()
        if progress_callback and (lidas % progress_every == 0 or lidas == total):
            progress_callback(lidas, total)

        novo, quantos = fix_notation(original, traduzido, source_language, target_language)
        if quantos and novo != traduzido:
            stats["changed"] += 1
            stats["moves"] += quantos
            if len(stats["examples"]) < sample_limit:
                stats["examples"].append(
                    {
                        "id": _id,
                        "original_comment": original,
                        "previous_translation": traduzido,
                        "new_translation": novo,
                    }
                )

    if progress_callback:
        progress_callback(total, total)
    return stats


def apply_move_notation_updates(
    cursor,
    source_language,
    target_language,
    fix_notation,
    sample_limit=10,
    progress_callback=None,
    should_cancel=None,
    progress_every=2000,
    include_unknown=True,
):
    """Aplica a correcao de lances nas traducoes ja gravadas do par.

    Calcula e grava no mesmo laco, com um cursor proprio para o `UPDATE` —
    escrever no cursor que esta iterando o `SELECT` invalidaria a iteracao. E a
    licao do item 2.7, e vale igual aqui.

    **A coluna `quality_warning` e reavaliada** (garantia R6): o texto mudou,
    entao o aviso derivado dele nao pode ficar como estava. E **toda alteracao
    entra no historico** (garantia R2), com acao propria — uma linha que o
    usuario revisou a mao e reescrita por aqui, e ele precisa poder ver o que
    era e voltar atras.

    O `verified` **nao** e mexido: corrigir a letra de um lance nao desfaz a
    revisao humana do resto do comentario, e rebaixar milhares de linhas para
    "pendente" seria devolver ao usuario um trabalho que ele ja fez.
    """
    write_cursor = cursor.connection.cursor()
    stats = _empty_move_notation_stats(source_language, target_language)
    total = _move_notation_total(
        cursor, source_language, target_language, include_unknown
    )
    if progress_callback:
        progress_callback(0, total)

    lidas = 0
    for row_id, original, traduzido, verified in _move_notation_rows(
        cursor, source_language, target_language, include_unknown
    ):
        lidas += 1
        stats["scanned"] += 1
        if should_cancel is not None and lidas % 200 == 0 and should_cancel():
            raise MoveNotationCanceled()
        if progress_callback and (lidas % progress_every == 0 or lidas == total):
            progress_callback(lidas, total)

        novo, quantos = fix_notation(original, traduzido, source_language, target_language)
        if not quantos or novo == traduzido:
            continue

        verified = 1 if verified == 1 else 0
        write_cursor.execute(
            """
            UPDATE comments
            SET translated_comment = ?,
                quality_warning = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                novo,
                quality_warning_flag(
                    original, novo, source_language, target_language
                ),
                row_id,
            ),
        )
        if write_cursor.rowcount:
            stats["changed"] += 1
            stats["moves"] += quantos
            if len(stats["examples"]) < sample_limit:
                stats["examples"].append(
                    {
                        "id": row_id,
                        "original_comment": original,
                        "previous_translation": traduzido,
                        "new_translation": novo,
                    }
                )
            record_comment_history(
                write_cursor,
                row_id,
                "move_notation",
                traduzido,
                novo,
                verified,
                verified,
            )

    if progress_callback:
        progress_callback(total, total)
    return stats
