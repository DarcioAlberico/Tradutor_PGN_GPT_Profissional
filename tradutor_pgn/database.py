import sqlite3

from .review_quality import evaluate_translation_quality


# Incrementar sempre que o schema mudar. Enquanto o PRAGMA user_version do
# arquivo bater com este valor, initialize_database pula toda a migracao.
SCHEMA_VERSION = 4

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


def quality_warning_flag(original, translated):
    """1 se a traducao tem algum aviso de qualidade, 0 caso contrario.

    Materializado na coluna `quality_warning` para que contar e paginar por
    "com aviso" seja uma consulta SQL, e nao uma varredura da tabela inteira em
    Python a cada troca de pagina. Precisa ser a MESMA funcao que a interface
    usa para exibir os avisos, senao a contagem diverge do que aparece na tela.
    """
    return 1 if evaluate_translation_quality(original, translated) else 0


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

        _migrate_database(conn)
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
        UNIQUE(original_comment, source_language, target_language)
    )
"""


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


def _migrate_database(conn):
    cursor = conn.cursor()

    # Num banco novo isto ja cria o schema final; num que existe e um no-op, e
    # quem acerta a tabela antiga sao os `ALTER TABLE` e a reconstrucao abaixo.
    cursor.execute(_COMMENTS_TABLE_SQL.format(name="IF NOT EXISTS comments"))

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
    # Indice de cobertura para get_review_status_counts: com ele o SQLite le so
    # o indice (33 ms em 200 mil linhas), sem tocar na tabela (83 ms).
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_counts
        ON comments(target_language, verified, quality_warning)
    """)
    # O mesmo, para quando ha filtro de origem. Sem ele o indice acima deixa de
    # cobrir a consulta — `source_language` esta no `WHERE` e nao no indice —, e
    # a agregada volta a tocar a tabela: medido no banco real, 34,9 ms sem filtro
    # de origem contra 78,7 ms com ele. Seria uma regressao da garantia R5
    # introduzida justamente pelo filtro que este item veio dar.
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_pair_counts
        ON comments(target_language, source_language, verified, quality_warning)
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

    conn.commit()
    backfill_quality_warnings(conn)
    return conn


def backfill_quality_warnings(conn, batch_size=5000):
    """Preenche `quality_warning` nas linhas que ainda estao com NULL.

    So roda no upgrade de schema; depois disso a coluna e mantida em cada
    escrita. Devolve quantas linhas foram preenchidas.
    """
    cursor = conn.cursor()
    total = 0

    while True:
        rows = cursor.execute(
            """
            SELECT id, original_comment, translated_comment
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
                (quality_warning_flag(original, translated), row_id)
                for row_id, original, translated in rows
            ],
        )
        conn.commit()
        total += len(rows)

    return total


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
                quality_warning_flag(original_comment, translated_comment),
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
                quality_warning_flag(original_comment, translated_comment),
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
    }


def fetch_export_rows(cursor):
    """Cursor das linhas do CSV — deliberadamente NAO materializado.

    O `fetchall` que estava aqui construia uma lista com o banco inteiro antes
    de a primeira linha ser escrita: 102 MB residentes em 195.607 linhas, so
    para depois entregar tudo ao `csv.writerows`, que aceita qualquer iteravel.

    Quem quiser a lista chama `list(...)`; o exportador nao quer.
    """
    return cursor.execute("""
        SELECT
            original_comment,
            translated_comment,
            source_language,
            target_language,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        ORDER BY id
    """)


def _review_where(
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    cursor=None,
    source_language=None,
):
    """Monta o `WHERE` compartilhado por contagem, paginacao e offset.

    `search_mode` decide COMO a busca filtra, e as duas formas existem por
    motivos diferentes (garantia R8):

    - `terms` usa o indice FTS5. Cada interacao passa a custar o tamanho da
      pagina, e nao o da tabela. Em troca, casa palavras inteiras: `bisp` so
      acha "bispo" com `bisp*`.
    - `substring` mantem o `LIKE '%x%'`, que acha qualquer trecho — inclusive no
      meio de uma palavra — ao preco de varrer a tabela. E o unico jeito de
      procurar por um pedaco literal, entao continua disponivel.

    Cai para `substring` sozinho quando o indice nao existe ou o SQLite nao tem
    FTS5, e tambem quando a expressao nao sobra nenhum termo utilizavel. Um
    resultado correto e lento e melhor que um erro.

    `source_language` restringe ao idioma de ORIGEM. `None` significa "todos", e
    e diferente de `""`: a string vazia e um idioma de origem legitimo — o das
    linhas gravadas antes de o programa perguntar e o das execucoes em deteccao
    automatica —, entao filtrar por ela devolve exatamente essas. Tratar as duas
    como a mesma coisa faria o filtro "Nao informado" mostrar a tabela inteira.
    """
    clauses = ["target_language = ?"]
    params = [target_language]

    if source_language is not None:
        clauses.append("source_language = ?")
        params.append(source_language)

    if status_filter is None:
        status_filter = "pending" if only_unverified else "all"

    if status_filter == "pending":
        clauses.append("verified <> 1")
    elif status_filter == "verified":
        clauses.append("verified = 1")
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
            clauses.append("(original_comment LIKE ? OR translated_comment LIKE ?)")
            pattern = f"%{search_text}%"
            params.extend([pattern, pattern])

    return " AND ".join(clauses), params


def fetch_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
    )
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        WHERE {where_sql}
        ORDER BY id
    """, params).fetchall()


def count_review_rows(
    cursor,
    target_language,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
    )
    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql}
    """, params).fetchone()[0]


def get_review_status_counts(
    cursor,
    target_language,
    search_text="",
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
):
    where_sql, params = _review_where(
        target_language,
        search_text=search_text,
        status_filter="all",
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
    )
    total, pending, verified, warnings = cursor.execute(f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN verified <> 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN quality_warning = 1 THEN 1 ELSE 0 END), 0)
        FROM comments
        WHERE {where_sql}
    """, params).fetchone()
    return {
        "total": total,
        "pending": pending,
        "verified": verified,
        "warnings": warnings,
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
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
    )
    return cursor.execute(f"""
        SELECT
            id,
            original_comment,
            translated_comment,
            verified,
            created_at,
            updated_at,
            verified_at
        FROM comments
        WHERE {where_sql}
        ORDER BY id
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()


def get_review_row_offset(
    cursor,
    target_language,
    comment_id,
    only_unverified=False,
    search_text="",
    status_filter=None,
    search_mode=SEARCH_MODE_SUBSTRING,
    source_language=None,
):
    where_sql, params = _review_where(
        target_language,
        only_unverified,
        search_text,
        status_filter,
        search_mode=search_mode,
        cursor=cursor,
        source_language=source_language,
    )
    row = cursor.execute(f"""
        SELECT id
        FROM comments
        WHERE {where_sql} AND id = ?
    """, params + [comment_id]).fetchone()

    if row is None:
        return None

    return cursor.execute(f"""
        SELECT COUNT(*)
        FROM comments
        WHERE {where_sql} AND id < ?
    """, params + [comment_id]).fetchone()[0]


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
    existing = cursor.execute(
        """
        SELECT translated_comment, verified, original_comment
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    previous_translation, previous_verified, original_comment = existing
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

    cursor.execute("""
        UPDATE comments
        SET translated_comment = ?,
            quality_warning = ?,
            verified = CASE WHEN ? THEN 1 ELSE verified END,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE verified_at END
        WHERE id = ?
    """, (
        translated_comment,
        quality_warning_flag(original_comment, translated_comment),
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

    cursor.execute("""
        UPDATE comments
        SET verified = ?,
            updated_at = CURRENT_TIMESTAMP,
            verified_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id = ?
    """, (1 if verified else 0, 1 if verified else 0, comment_id))
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


def set_exact_translation_matches_verified(cursor, comment_id):
    existing = cursor.execute(
        """
        SELECT translated_comment, source_language, target_language
        FROM comments
        WHERE id = ?
        """,
        (comment_id,),
    ).fetchone()
    if existing is None:
        return 0

    translation, source_language, target_language = existing
    if not translation:
        return 0

    # Dentro do mesmo PAR de idiomas. Verificar uma traducao vinda do espanhol
    # nao diz nada sobre a mesma frase vinda do ingles — e marcar as duas daria
    # por revisado o que o usuario nem viu, justamente na tela que ele abriu para
    # nao misturar as linguas.
    rows = cursor.execute(
        """
        SELECT id, verified
        FROM comments
        WHERE target_language = ?
          AND source_language = ?
          AND translated_comment = ?
          AND verified <> 1
        ORDER BY id
        """,
        (target_language, source_language, translation),
    ).fetchall()
    if not rows:
        return 0

    changed_rows = 0
    for matching_id, previous_verified in rows:
        previous_verified = 1 if previous_verified == 1 else 0
        cursor.execute(
            """
            UPDATE comments
            SET verified = 1,
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
        SELECT id, original_comment, translated_comment, target_language, verified
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
    for comment_id, original, translation, row_language, _verified in _iter_automatic_rule_rows(
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

    for comment_id, original_comment, previous_translation, row_language, previous_verified in (
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
                quality_warning_flag(original_comment, updated_translation),
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
    """
    stats = _empty_move_notation_stats(source_language, target_language)
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
            (novo, quality_warning_flag(original, novo), row_id),
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
