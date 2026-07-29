# glossario.py
# Carrega e manipula o arquivo Substituicoes.txt.

import ast
import csv
from datetime import datetime
from functools import lru_cache
import hashlib
import os
import re
import shutil
import sqlite3
import sys

from .backup_retention import prune_glossary_backups


SUBSTITUTION_VARIABLES = {"substituições", "substituicoes"}
GLOSSARY_RULE_SUGGESTION = "suggestion"
GLOSSARY_RULE_CLEANUP = "cleanup"
GLOSSARY_RULE_AUTOMATIC = "automatic"
GLOSSARY_RULE_TYPES = (
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_AUTOMATIC,
)
GLOSSARY_CSV_HEADERS = ["original", "replacement", "type", "priority"]
GLOSSARY_DB_FILENAME = "glossario.db"

# Prioridade explicita (ROADMAP 1.5, parte 2). Zero e "sem opiniao", e e o valor
# de toda regra que nao foi tocada — por isso o formato do arquivo so escreve o
# campo quando ele nao e zero: um glossario de 7 mil regras nao muda de tamanho
# por causa de uma decisao tomada em quatro delas.
GLOSSARY_PRIORITY_DEFAULT = 0

# Sobe quando o `glossario.db` ganha coluna, e tambem quando muda o significado
# das marcas que dizem de onde ele veio. Um banco gravado por uma versao anterior
# tem de ser reconstruido a partir do arquivo, e nao apenas alterado: a coluna
# nova entraria com o valor padrao para todas as regras, sem que nada no
# `Substituicoes.txt` tivesse mudado para acusar a diferenca.
#
# 3: `source_path` passou a ser relativo ao banco e `source_mtime` deu lugar a
# `source_hash`, para que o cache sobreviva a um clone (ROADMAP 3.7).
GLOSSARY_DB_SCHEMA_VERSION = 3


# ============================================================================
# Canal de erro do glossario (garantia S5)
#
# As falhas de carga so existiam como `print` em stdout. Num app Tkinter — e
# principalmente empacotado com `pythonw`, que nao tem console — esse print nao
# aparece em lugar nenhum: um `Substituicoes.txt` malformado desligava as 7 mil
# regras sem um unico aviso, e a traducao saia com a terminologia errada como se
# estivesse tudo certo.
#
# A interface registra um handler com `set_glossary_error_handler`. Este modulo
# nao importa Tk, entao quem registra e que decide como mostrar.
# ============================================================================

_glossary_error_handler = None
_last_glossary_error = None


def set_glossary_error_handler(handler):
    """Registra quem exibe as falhas de carga. Devolve o handler anterior.

    `handler` recebe a mensagem ja formatada. Pode ser chamado de qualquer
    thread (o worker de traducao carrega o glossario), entao cabe a ele
    agendar o que precisar na thread do Tk.
    """
    global _glossary_error_handler
    previous = _glossary_error_handler
    _glossary_error_handler = handler
    return previous


def last_glossary_error():
    """Ultima falha reportada, ou `None`. Util para quem abre depois do erro."""
    return _last_glossary_error


def clear_glossary_error():
    """Esquece a ultima falha, apos o glossario carregar bem."""
    global _last_glossary_error
    _last_glossary_error = None


def report_glossary_error(message):
    """Publica uma falha de carga: sempre no console, e na UI quando houver.

    Nunca deixa uma excecao do handler escapar — reportar um erro nao pode ser
    o motivo de um erro pior, e o chamador esta sempre num caminho de
    degradacao (ja vai devolver lista vazia ou cair para o arquivo).
    """
    global _last_glossary_error
    _last_glossary_error = message
    print(f"[GLOSSÁRIO] {message}")

    if _glossary_error_handler is None:
        return

    try:
        _glossary_error_handler(message)
    except Exception as exc:  # pragma: no cover - defensivo
        print(f"[GLOSSÁRIO] Falha ao exibir o erro anterior: {exc}")


def _default_substitutions_path():
    """Retorna o caminho padrão do arquivo Substituicoes.txt."""
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, "Substituicoes.txt")


def _default_glossary_db_path():
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, GLOSSARY_DB_FILENAME)


def _is_default_substitutions_path(path):
    return os.path.abspath(path) == os.path.abspath(_default_substitutions_path())


def _read_substitution_assignment(code, path):
    tree = ast.parse(code, filename=path)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in SUBSTITUTION_VARIABLES:
                value = ast.literal_eval(node.value)
                if not isinstance(value, (list, tuple)):
                    raise ValueError("A variável de substituições precisa ser uma lista.")
                return value

    raise ValueError("Variável 'substituições' ou 'substituicoes' não encontrada.")


# Como o tipo pode estar escrito no arquivo, que e editado a mao. O masculino
# (`automatico`) faltava e e o erro mais facil de cometer — a regra virava
# sugestao, deixava de rodar depois da API, e nada avisava (ROADMAP 14.6).
GLOSSARY_RULE_TYPE_ALIASES = {
    "sugestao": GLOSSARY_RULE_SUGGESTION,
    "sugestão": GLOSSARY_RULE_SUGGESTION,
    "sugestões": GLOSSARY_RULE_SUGGESTION,
    "suggestion": GLOSSARY_RULE_SUGGESTION,
    "limpeza": GLOSSARY_RULE_CLEANUP,
    "limpar": GLOSSARY_RULE_CLEANUP,
    "cleanup": GLOSSARY_RULE_CLEANUP,
    "clean": GLOSSARY_RULE_CLEANUP,
    "auto": GLOSSARY_RULE_AUTOMATIC,
    "automatica": GLOSSARY_RULE_AUTOMATIC,
    "automática": GLOSSARY_RULE_AUTOMATIC,
    "automatico": GLOSSARY_RULE_AUTOMATIC,
    "automático": GLOSSARY_RULE_AUTOMATIC,
    "automatic": GLOSSARY_RULE_AUTOMATIC,
}


def _rule_type_alias(value):
    """O tipo canonico de `value`, ou `None` quando ele nao e reconhecido.

    Separado de `_normalize_rule_type` porque as duas perguntas sao diferentes:
    aquela responde "com que tipo eu seguo em frente" (e o padrao serve), esta
    responde "isto e um tipo que eu conheco" — que e o que permite avisar em vez
    de degradar em silencio (garantia S13).
    """
    texto = "" if value is None else str(value).strip()
    if not texto:
        return None
    canonico = GLOSSARY_RULE_TYPE_ALIASES.get(texto.casefold(), texto)
    return canonico if canonico in GLOSSARY_RULE_TYPES else None


def _normalize_rule_type(rule_type):
    return _rule_type_alias(rule_type) or GLOSSARY_RULE_SUGGESTION


def _raw_rule_type(item):
    """O tipo COMO ESTA ESCRITO na entrada, sem normalizar."""
    if isinstance(item, dict):
        return item.get("type") or item.get("rule_type")
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        return item[2]
    return None


def unknown_rule_types(raw_items):
    """Os valores de tipo que o programa nao reconhece, sem repetir.

    Um tipo mal escrito continua degradando para sugestao — o arquivo e
    editavel a mao e sobrevive a versoes do programa, e uma regra torta nao pode
    desligar as outras milhares na carga (mesmo principio de S5). O que muda e
    que ele **avisa**: antes, `('x', 'y', 'automático')` virava sugestao, deixava
    de rodar depois da API, e nada na tela dizia por que.

    Devolve valores distintos, e nao um por regra: um arquivo com cem tipos
    tortos precisa de um aviso, nao de cem dialogos.
    """
    desconhecidos = []
    vistos = set()
    for item in raw_items:
        bruto = _raw_rule_type(item)
        texto = "" if bruto is None else str(bruto).strip()
        if not texto or texto in vistos:
            continue
        if _rule_type_alias(texto) is None:
            vistos.add(texto)
            desconhecidos.append(texto)
    return desconhecidos


def _entry_pair(item):
    if isinstance(item, dict):
        return str(item.get("original", "")), str(item.get("replacement", ""))
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return str(item[0]), str(item[1])
    return None


def _entry_rule_type(item):
    if isinstance(item, dict):
        return _normalize_rule_type(item.get("type") or item.get("rule_type"))
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        return _normalize_rule_type(item[2])
    return GLOSSARY_RULE_SUGGESTION


def normalize_glossary_priority(value):
    """Prioridade como inteiro, ou o padrao quando o valor nao serve.

    O `Substituicoes.txt` e o CSV sao editaveis a mao e sobrevivem a versoes do
    programa: uma prioridade escrita como `"alta"` nao pode virar excecao no
    meio da carga do glossario. Vale a mesma regra do `rule_type` — o que nao da
    para entender vira o padrao.
    """
    if isinstance(value, bool) or value is None:
        return GLOSSARY_PRIORITY_DEFAULT
    try:
        return int(value)
    except (TypeError, ValueError):
        return GLOSSARY_PRIORITY_DEFAULT


def _entry_priority(item):
    if isinstance(item, dict):
        return normalize_glossary_priority(item.get("priority"))
    if isinstance(item, (list, tuple)) and len(item) >= 4:
        return normalize_glossary_priority(item[3])
    return GLOSSARY_PRIORITY_DEFAULT


def _normalize_entries(entries):
    normalized = []
    for item in entries:
        pair = _entry_pair(item)
        if pair is not None:
            orig, new = pair
            normalized.append((str(orig), str(new)))
    return normalized


def _normalize_detailed_entries(entries):
    normalized = []
    for item in entries:
        pair = _entry_pair(item)
        if pair is not None:
            orig, new = pair
            normalized.append(
                (str(orig), str(new), _entry_rule_type(item), _entry_priority(item))
            )
    return normalized


def glossary_entry_pair(entry):
    return _entry_pair(entry) or ("", "")


def glossary_entry_type(entry):
    return _entry_rule_type(entry)


def glossary_entry_priority(entry):
    return _entry_priority(entry)


def _serialize_entries(entries):
    """Escreve o `Substituicoes.txt`, com o campo mais curto que basta.

    Cada campo so aparece quando tem algo a dizer: o tipo quando nao e sugestao,
    a prioridade quando nao e zero. Nao e economia de bytes — e que o arquivo
    tem 7 mil linhas e e versionado: escrever `, 0` em todas elas transformaria
    a decisao tomada em quatro regras num diff de 7 mil linhas.
    """
    lines = ["substituicoes = [\n"]
    for orig, new, rule_type, priority in _normalize_detailed_entries(entries):
        if priority != GLOSSARY_PRIORITY_DEFAULT:
            lines.append(f"    ({orig!r}, {new!r}, {rule_type!r}, {priority!r}),\n")
        elif rule_type == GLOSSARY_RULE_SUGGESTION:
            lines.append(f"    ({orig!r}, {new!r}),\n")
        else:
            lines.append(f"    ({orig!r}, {new!r}, {rule_type!r}),\n")
    lines.append("]\n")
    return "".join(lines)


def _unique_path(path):
    base, ext = os.path.splitext(path)
    candidate = path
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{base}-{counter}{ext}"
        counter += 1
    return candidate


def _ensure_parent_dir(path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)


def _source_fingerprint(path):
    """Impressao do **conteudo** do glossario, para saber se o cache ainda vale.

    Era o `mtime`, e o `mtime` nao sobrevive a um clone: o git nao guarda data de
    modificacao, entao o `Substituicoes.txt` recem baixado recebe a hora do
    checkout e o `glossario.db` versionado ao lado dele seria descartado na
    primeira carga — reconstruido do zero em toda maquina, que e o oposto de
    versiona-lo.

    O hash responde a pergunta que de fato importa — "este banco foi construido a
    partir deste arquivo?" — e a resposta e a mesma em qualquer maquina. Ele
    tambem e mais exato que o `mtime` para o caso oposto: reescrever o arquivo com
    o mesmo conteudo (o que uma gravacao atomica faz) mudava o `mtime` e forcava
    uma reconstrucao que nao mudava nada.
    """
    if not os.path.exists(path):
        return ""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            hasher.update(bloco)
    return hasher.hexdigest()


def _relative_source_path(source_path, db_path):
    """O caminho do glossario visto da pasta do banco, com `/` como separador.

    Absoluto, ele so valia na maquina que gravou: bastava o projeto estar em
    outra pasta para os caminhos diferirem e o cache ser reconstruido. Relativo
    ao proprio banco, os dois viajam juntos — e como eles ficam lado a lado na
    raiz do projeto, na pratica isto e `Substituicoes.txt`.

    O separador vira `/` porque o banco e versionado e pode ser lido em outro
    sistema, onde `os.sep` e outro. Se os dois estiverem em unidades diferentes
    do Windows nao existe caminho relativo: ai o absoluto e o melhor disponivel,
    e o comportamento antigo volta — restrito a esse caso.
    """
    try:
        relativo = os.path.relpath(
            os.path.abspath(source_path),
            os.path.dirname(os.path.abspath(db_path)),
        )
    except ValueError:
        return os.path.abspath(source_path).replace(os.sep, "/")
    return relativo.replace(os.sep, "/")


def _deduplicate_entries(entries):
    seen = set()
    deduplicated = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduplicated.append(entry)
    return deduplicated


def _load_glossary_entries_from_file(path, deduplicate=True):
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw_items = _read_substitution_assignment(f.read(), path)

    entries = _normalize_entries(raw_items)
    if deduplicate:
        entries = _deduplicate_entries(entries)

    return entries


def _load_glossary_entry_details_from_file(path, deduplicate=True):
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw_items = _read_substitution_assignment(f.read(), path)

    # Aqui, e nao no `glossario.db`: o banco guarda tipos ja normalizados, entao
    # o que estava mal escrito no arquivo nao existe mais quando ele e lido.
    # Quem ve a grafia original e so quem le o texto (garantia S13).
    desconhecidos = unknown_rule_types(raw_items)
    if desconhecidos:
        amostra = ", ".join(repr(valor) for valor in desconhecidos[:5])
        if len(desconhecidos) > 5:
            amostra += f", ... (+{len(desconhecidos) - 5})"
        report_glossary_error(
            f"Tipo de regra desconhecido no glossario, tratado como "
            f"'{GLOSSARY_RULE_SUGGESTION}': {amostra}. "
            f"Os tipos validos sao {', '.join(GLOSSARY_RULE_TYPES)}."
        )

    entries = _normalize_detailed_entries(raw_items)
    if deduplicate:
        entries = _deduplicate_entries(entries)

    return entries


def initialize_glossary_database(db_path=None):
    """Inicializa o banco SQLite exclusivo do glossário."""
    if db_path is None:
        db_path = _default_glossary_db_path()

    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS glossary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_text TEXT NOT NULL,
            replacement_text TEXT NOT NULL,
            rule_type TEXT NOT NULL DEFAULT 'suggestion',
            priority INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(glossary_entries)").fetchall()
    }
    if "rule_type" not in cols:
        conn.execute(
            """
            ALTER TABLE glossary_entries
            ADD COLUMN rule_type TEXT NOT NULL DEFAULT 'suggestion'
            """
        )
    if "priority" not in cols:
        conn.execute(
            """
            ALTER TABLE glossary_entries
            ADD COLUMN priority INTEGER NOT NULL DEFAULT 0
            """
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS glossary_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_glossary_original
        ON glossary_entries(original_text)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_glossary_replacement
        ON glossary_entries(replacement_text)
        """
    )
    conn.commit()
    return conn


def _get_glossary_metadata(conn, key):
    row = conn.execute(
        "SELECT value FROM glossary_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return row[0] if row else None


def _set_glossary_metadata(conn, key, value):
    conn.execute(
        """
        INSERT INTO glossary_metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def sync_glossary_database(entries, db_path=None, source_path=None):
    """Sincroniza o glossário persistente para o banco exclusivo glossario.db."""
    if db_path is None:
        db_path = _default_glossary_db_path()

    entries = _normalize_detailed_entries(entries)
    conn = initialize_glossary_database(db_path)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM glossary_entries")
        conn.executemany(
            """
            INSERT INTO glossary_entries (
                original_text,
                replacement_text,
                rule_type,
                priority,
                position,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (orig, new, rule_type, priority, index, now, now)
                for index, (orig, new, rule_type, priority) in enumerate(entries)
            ],
        )
        _set_glossary_metadata(conn, "entry_count", len(entries))
        _set_glossary_metadata(conn, "schema_version", GLOSSARY_DB_SCHEMA_VERSION)
        if source_path is not None:
            # Relativo e por conteudo: as duas marcas precisam valer num clone,
            # senao o `glossario.db` versionado e descartado ao ser aberto.
            _set_glossary_metadata(
                conn, "source_path", _relative_source_path(source_path, db_path)
            )
            _set_glossary_metadata(conn, "source_hash", _source_fingerprint(source_path))
        _set_glossary_metadata(conn, "synced_at", now)
        conn.commit()
    finally:
        conn.close()

    return {"synced": len(entries), "db_path": db_path}


def load_glossary_entries_from_db(db_path=None, deduplicate=True):
    """Carrega entradas do banco exclusivo do glossário."""
    if db_path is None:
        db_path = _default_glossary_db_path()

    if not os.path.exists(db_path):
        return []

    conn = initialize_glossary_database(db_path)
    try:
        rows = conn.execute(
            """
            SELECT original_text, replacement_text
            FROM glossary_entries
            ORDER BY position, id
            """
        ).fetchall()
    finally:
        conn.close()

    entries = [(row[0], row[1]) for row in rows]
    if deduplicate:
        entries = _deduplicate_entries(entries)
    return entries


def load_glossary_entry_details_from_db(db_path=None, deduplicate=True):
    """Carrega entradas detalhadas do glossario.db, incluindo o tipo da regra."""
    if db_path is None:
        db_path = _default_glossary_db_path()

    if not os.path.exists(db_path):
        return []

    conn = initialize_glossary_database(db_path)
    try:
        rows = conn.execute(
            """
            SELECT original_text, replacement_text, rule_type, priority
            FROM glossary_entries
            ORDER BY position, id
            """
        ).fetchall()
    finally:
        conn.close()

    entries = [
        (row[0], row[1], _normalize_rule_type(row[2]), normalize_glossary_priority(row[3]))
        for row in rows
    ]
    if deduplicate:
        entries = _deduplicate_entries(entries)
    return entries


def _glossary_database_needs_sync(path, db_path):
    if not os.path.exists(db_path):
        return True
    if not os.path.exists(path):
        return False

    conn = initialize_glossary_database(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM glossary_entries").fetchone()[0]
        source_path = _get_glossary_metadata(conn, "source_path")
        source_hash = _get_glossary_metadata(conn, "source_hash")
        schema = _get_glossary_metadata(conn, "schema_version")
    finally:
        conn.close()

    if count == 0:
        return True
    if schema != str(GLOSSARY_DB_SCHEMA_VERSION):
        # Um `glossario.db` gravado por uma versao anterior nao tem as colunas
        # novas. O `ALTER TABLE` acima cria a coluna com o padrao, e sem esta
        # checagem o banco continuaria valendo como cache: as regras seriam
        # lidas com prioridade zero enquanto o arquivo diz outra coisa. Errado,
        # e em silencio — nada no arquivo mudou para acusar.
        return True
    if source_path and source_path != _relative_source_path(path, db_path):
        return True
    return source_hash != _source_fingerprint(path)


def rebuild_glossary_database(path=None, db_path=None):
    """Reconstrói glossario.db a partir do Substituicoes.txt."""
    if path is None:
        path = _default_substitutions_path()
    if db_path is None:
        db_path = _default_glossary_db_path()

    entries = _load_glossary_entry_details_from_file(path, deduplicate=False)
    return sync_glossary_database(entries, db_path=db_path, source_path=path)


def load_glossary_entries(path=None, deduplicate=True, prefer_db=True, db_path=None):
    """Carrega entradas persistentes do glossário sem depender de traducoes.db."""
    if path is None:
        path = _default_substitutions_path()

    use_db = prefer_db and _is_default_substitutions_path(path)
    if db_path is not None:
        use_db = True
    elif use_db:
        db_path = _default_glossary_db_path()

    if use_db:
        try:
            if _glossary_database_needs_sync(path, db_path):
                rebuild_glossary_database(path, db_path)
            return load_glossary_entries_from_db(db_path, deduplicate=deduplicate)
        except Exception as exc:
            # O indice e derivado: da para seguir pelo arquivo texto. Mas o
            # usuario precisa saber que o glossario.db esta corrompido.
            report_glossary_error(f"Erro ao usar glossario.db: {exc}")

    return _load_glossary_entries_from_file(path, deduplicate=deduplicate)


def load_glossary_entry_details(path=None, deduplicate=True, prefer_db=True, db_path=None):
    """Carrega entradas do glossário incluindo o tipo da regra."""
    if path is None:
        path = _default_substitutions_path()

    use_db = prefer_db and _is_default_substitutions_path(path)
    if db_path is not None:
        use_db = True
    elif use_db:
        db_path = _default_glossary_db_path()

    if use_db:
        try:
            if _glossary_database_needs_sync(path, db_path):
                rebuild_glossary_database(path, db_path)
            return load_glossary_entry_details_from_db(db_path, deduplicate=deduplicate)
        except Exception as exc:
            # O indice e derivado: da para seguir pelo arquivo texto. Mas o
            # usuario precisa saber que o glossario.db esta corrompido.
            report_glossary_error(f"Erro ao usar glossario.db: {exc}")

    return _load_glossary_entry_details_from_file(path, deduplicate=deduplicate)


def create_glossary_backup(path=None, backup_dir=None, timestamp=None, prune=True, protect=()):
    """Cria uma cópia de segurança do glossário e retorna o caminho criado."""
    if path is None:
        path = _default_substitutions_path()

    if not os.path.exists(path):
        return None

    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")

    os.makedirs(backup_dir, exist_ok=True)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = os.path.splitext(os.path.basename(path))[0]
    backup_path = os.path.join(backup_dir, f"{stem}-{timestamp}.txt")
    backup_path = _unique_path(backup_path)
    shutil.copy2(path, backup_path)

    if prune:
        # `protected` garante que a copia recem criada sobrevive a propria
        # limpeza, mesmo se os limites estiverem configurados muito baixos.
        # `protect` adiciona o arquivo que o chamador ainda vai ler — numa
        # restauracao, a limpeza rodaria entre o backup de seguranca e a
        # leitura do backup escolhido, e poderia apagar justamente esse.
        prune_glossary_backups(
            backup_dir,
            stem,
            protected=(backup_path,) + tuple(protect),
        )

    return backup_path


def save_glossary_entries(
    entries,
    path=None,
    create_backup=True,
    backup_dir=None,
    timestamp=None,
    sync_db=True,
    db_path=None,
):
    """Salva o glossário no arquivo persistente do programa."""
    if path is None:
        path = _default_substitutions_path()

    _ensure_parent_dir(path)
    backup_path = None
    if create_backup:
        backup_path = create_glossary_backup(
            path,
            backup_dir=backup_dir,
            timestamp=timestamp,
        )

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(_serialize_entries(entries))
    os.replace(tmp_path, path)

    if sync_db and (db_path is not None or _is_default_substitutions_path(path)):
        sync_glossary_database(entries, db_path=db_path, source_path=path)

    return {
        "saved": len(_normalize_detailed_entries(entries)),
        "backup_path": backup_path,
    }


def build_glossary_lookup(entries):
    """Indice `orig -> [(new, posicao)]` para validar sem varrer o glossario.

    A validacao roda a cada tecla digitada no editor. Percorrer as ~7 mil
    entradas (e reconstruir a lista normalizada) a cada caractere trava a
    digitacao. Como as duas checagens de conflito exigem que o `orig` seja
    igual, indexar por `orig` da o mesmo resultado em tempo constante.
    """
    lookup = {}
    for index, (orig, new) in enumerate(_normalize_entries(entries)):
        lookup.setdefault(orig, []).append((new, index))
    return lookup


def validate_glossary_entry(
    orig,
    new,
    existing_entries=None,
    current_index=None,
    rule_type=None,
    existing_lookup=None,
):
    """Retorna avisos de validação para uma entrada do glossário.

    `existing_lookup` e o indice devolvido por `build_glossary_lookup`; quem
    valida repetidamente sobre o mesmo glossario deve monta-lo uma vez e
    reaproveitar. Sem ele, o indice e montado a partir de `existing_entries`.
    """
    warnings = []
    orig = "" if orig is None else str(orig)
    new = "" if new is None else str(new)
    rule_type = _normalize_rule_type(rule_type)

    if not orig.strip():
        warnings.append("Texto original vazio.")
    if not new.strip() and rule_type != GLOSSARY_RULE_CLEANUP:
        warnings.append("Texto de substituição vazio.")
    if orig == new and orig:
        warnings.append("Texto original igual à substituição.")
    if "\n" in orig or "\r" in orig or "\n" in new or "\r" in new:
        warnings.append("Entradas não podem conter quebras de linha.")

    if existing_lookup is None and existing_entries is not None:
        existing_lookup = build_glossary_lookup(existing_entries)

    if existing_lookup is not None:
        # Mesma ordem do laço original: vence a primeira entrada de mesmo
        # `orig`, seja ela duplicata exata ou conflito.
        for existing_new, index in existing_lookup.get(orig, ()):
            if current_index is not None and index == current_index:
                continue
            if new == existing_new:
                warnings.append("Entrada duplicada.")
            elif orig:
                warnings.append("Mesmo original com substituição diferente.")
            else:
                continue
            break

    return warnings


# Os conjuntos de regras que o programa de fato carrega juntos. Duas regras de
# mesmo padrao so disputam entre si dentro de um destes conjuntos: uma regra de
# limpeza e uma de sugestao nunca sao aplicadas ao mesmo texto, entao nao ha
# conflito entre elas por mais parecidas que sejam.
#
# `load_suggestion_substitutions` (so sugestoes) existe e e exportada, mas hoje
# nenhum caminho de producao a usa — a lista aqui e a do que roda, para que a
# mensagem exibida nao invente um contexto que nao existe.
GLOSSARY_RULE_CONTEXTS = (
    ("cleanup", "limpeza", (GLOSSARY_RULE_CLEANUP,)),
    ("automatic", "regras automáticas", (GLOSSARY_RULE_AUTOMATIC,)),
    (
        "interactive",
        "sugestões do editor",
        (GLOSSARY_RULE_SUGGESTION, GLOSSARY_RULE_AUTOMATIC),
    ),
)


def _rule_subsumes(orig_winner, orig_other):
    """Tudo o que `orig_other` casaria, `orig_winner` casa antes.

    Duas situacoes, e as duas terminam com a segunda regra nunca disparando —
    o congelamento de S4 impede que ela reveja o trecho:

    - **padroes identicos**, o caso que a garantia S9 sempre cobriu;
    - **o vencedor e insensivel a caixa** (escrito todo em minusculas, ver
      `_compiled_glossary_pattern`): ele casa qualquer variante de caixa do
      mesmo texto, entao engole `Black`, `BLACK` e o que mais caseie por
      `casefold`.

    O segundo caso era invisivel, e e o que a garantia S12 acrescenta.
    Agrupando por padrao exato, `'black'` e `'Black'` eram padroes DIFERENTES:
    a janela mostrava as duas lado a lado sem dizer que a segunda estava morta.
    Medido no glossario real, 210 regras nunca disparavam por isso.

    Nao e simetrico de proposito. Se a de caixa fixa vem primeiro, as duas
    vivem: `('Black', ...)` pega o texto capitalizado e `('black', ...)` pega o
    resto. O que mata e a insensivel chegar antes.
    """
    return orig_winner == orig_other or orig_winner == orig_winner.lower()


def glossary_conflicts(entries):
    """Regras que disputam o mesmo padrao, e qual delas o programa aplica.

    Duas regras que casam o mesmo texto com substituicoes diferentes nao
    empatam: uma delas vence sempre, e a outra nunca dispara. Quem decide e
    `_rule_sort_key`, a mesma funcao que ordena as regras na hora de aplicar:
    prioridade explicita (garantia S10), depois comprimento do padrao (garantia
    S3) e, por fim, a ordem do arquivo.

    "O mesmo texto" e mais largo do que "o mesmo padrao", e por isso o
    agrupamento e por `casefold` com `_rule_subsumes` decidindo quem engole
    quem (garantia S12). Para padroes identicos o comprimento empata sempre e o
    que separa e a prioridade e, sem ela, a posicao.

    **Uma regra sombreada so entra aqui quando perde algo.** A substituicao
    propaga a capitalizacao do texto encontrado, entao `('as pretas deve', 'as
    pretas devem')` aplicada a `"As pretas deve"` ja produz `"As pretas
    devem"` — exatamente o que a regra capitalizada ao lado dela queria. Ela
    esta morta e nao faz falta: e redundancia, nao conflito. A pergunta certa
    nao e "as substituicoes sao diferentes como texto", e sim "o que a
    vencedora PRODUZ aqui e diferente do que esta regra queria" — e quem
    responde e `case_adjusted_replacement`, a funcao que a aplicacao usa.
    Medido no glossario real: das 210 mortas, 166 sao redundancia e **44**
    perdem alguma coisa.

    O vencedor e **por contexto**: uma regra automatica e uma de sugestao com o
    mesmo padrao competem no editor (que carrega as duas), mas na aplicacao das
    regras automaticas so a automatica existe — e la ela vence mesmo estando
    depois no arquivo.

    Devolve `{indice: info}` apenas para os indices em disputa, onde `info` tem:

    - `pattern`: o padrao **desta** regra (com S12 os membros de um grupo podem
      ter padroes que diferem na caixa, e o que interessa na mensagem e o dela);
    - `group`: todos os indices que disputam com ele (o que "manter esta" remove);
    - `contexts`: **todos** os contextos que carregam este indice, cada um com
      `key`, `label`, `members`, `winner` e `disputed`.

    `winner` e relativo ao indice consultado: e a regra que dispara no lugar
    dele, ou ele mesmo quando dispara. Isso importa com mais de duas regras no
    grupo — em `('Black',…)`, `('black',…)`, `('BLACK',…)` a segunda e viva e a
    terceira e morta, e uma unica "vencedora do grupo" nao descreveria as duas.

    `contexts` inclui os contextos sem disputa de proposito. Uma regra pode
    perder a disputa num contexto e ser a unica do padrao em outro — e la ela
    aplica. Listar so os contextos disputados faria a mensagem dizer que ela
    nunca e aplicada, o que seria falso: e o caso real de `'/\\'`, cuja regra
    automatica perde no editor e vale nas regras automaticas.

    Os indices sao posicoes na lista recebida, para casarem com as do editor.
    """
    indices_by_key = {}
    rule_types = []
    replacements = []
    patterns = []
    rules = []
    for index, entry in enumerate(entries):
        orig, new = glossary_entry_pair(entry)
        patterns.append(orig)
        rule_types.append(glossary_entry_type(entry))
        replacements.append(new)
        rules.append(_as_rule(entry))
        if orig:
            indices_by_key.setdefault(orig.casefold(), []).append(index)

    def ordem_de_disputa(members):
        """Os membros na ordem em que disputam o texto — perguntando a producao.

        Os dois passos sao os mesmos dela, e nao uma imitacao: `_as_rule` e a
        conversao que `filter_glossary_entries_by_type` faz ao carregar o
        glossario, e `_specificity_order` e o criterio que
        `order_rules_by_specificity` usa para aplicar. Aqui nao ha uma segunda
        leitura do que "prioridade e ordem do arquivo" significam — se houvesse,
        ela poderia divergir e a janela anunciaria um vencedor que o texto nunca
        recebe.

        As posicoes passadas sao as **do contexto**, ja filtrado por tipo, que e
        a forma como a lista chega na aplicacao. Filtrar preserva a ordem
        relativa, entao a ordem entre estes membros e a mesma que sairia da
        lista inteira.
        """
        return [
            members[position]
            for position in _specificity_order([rules[index] for index in members])
        ]

    def perdedores_do_contexto(ordenados):
        """`{indice: vencedora}` para os membros que perdem ALGO neste contexto.

        Uma regra sombreada cuja vencedora produz exatamente o que ela queria e
        redundancia, nao conflito — ver o docstring da funcao.
        """
        perdas = {}
        for posicao, index in enumerate(ordenados):
            for anterior in ordenados[:posicao]:
                if not _rule_subsumes(patterns[anterior], patterns[index]):
                    continue
                produzido = case_adjusted_replacement(
                    patterns[index], replacements[anterior]
                )
                if produzido != replacements[index]:
                    perdas[index] = anterior
                break
        return perdas

    conflicts = {}
    for indices in indices_by_key.values():
        if len(indices) < 2:
            continue

        avaliados = []
        disputing = set()
        for key, label, context_types in GLOSSARY_RULE_CONTEXTS:
            members = [index for index in indices if rule_types[index] in context_types]
            if not members:
                continue
            ordenados = ordem_de_disputa(members)
            perdas = perdedores_do_contexto(ordenados)
            avaliados.append((key, label, members, perdas))
            for perdedor, vencedora in perdas.items():
                disputing.add(perdedor)
                disputing.add(vencedora)

        if not disputing:
            continue

        for index in sorted(disputing):
            contextos = [
                {
                    "key": key,
                    "label": label,
                    "members": members,
                    "winner": perdas.get(index, index),
                    "disputed": bool(perdas),
                }
                for key, label, members, perdas in avaliados
                if index in members
            ]
            # `group` e o que "Manter esta" remove, e ele NAO e o conjunto dos
            # que estao em disputa: e o dos que casam o mesmo texto nos
            # contextos onde ha disputa. A diferenca aparece com uma duplicata
            # exata ao lado — ela nao e conflito (a vencedora produz o mesmo que
            # ela queria), mas continua engolindo quem vem depois. Deixando-a
            # fora, "Manter esta" removeria a concorrente anunciada e a regra
            # escolhida continuaria morta, agora sem nada na tela explicando.
            #
            # Segue restrito aos contextos em disputa: uma regra de limpeza com
            # o mesmo padrao nunca competiu com uma de sugestao, e apaga-la
            # seria levar junto quem nao estava na briga.
            group = sorted(
                {
                    membro
                    for context in contextos
                    if context["disputed"]
                    for membro in context["members"]
                }
                or {index}
            )
            conflicts[index] = {
                "pattern": patterns[index],
                "group": group,
                "contexts": contextos,
            }

    return conflicts


def describe_glossary_conflict(entries, index, conflicts=None):
    """Frase que diz qual regra do conflito o programa aplica, e onde.

    String vazia quando o indice nao esta em disputa. Quem exibe para varias
    entradas deve passar `conflicts` pronto, senao cada chamada reagrupa o
    glossario inteiro.
    """
    if conflicts is None:
        conflicts = glossary_conflicts(entries)
    info = conflicts.get(index)
    if not info:
        return ""

    def alvo(winner):
        if winner == index:
            return "esta regra"
        _, novo = glossary_entry_pair(entries[winner])
        return f"a regra #{winner + 1} -> {novo!r}"

    contexts = info["contexts"]
    # Nomear o contexto so quando ele muda o resultado. Uma regra automatica em
    # disputa aparece nos dois contextos que a carregam, com o mesmo vencedor:
    # repetir a mesma frase com dois rotulos so atrapalha.
    vencedores = {context["winner"] for context in contexts}
    if len(vencedores) == 1:
        partes = [f"vence {alvo(contexts[0]['winner'])}"]
    else:
        partes = [
            f"em {context['label']} vence {alvo(context['winner'])}"
            for context in contexts
        ]

    frase = f"Conflito em {info['pattern']!r}: " + "; ".join(partes) + "."
    if index not in vencedores:
        frase += " Esta regra nunca é aplicada."
    return frase


def resolve_glossary_conflict(entries, index, conflicts=None):
    """Entradas com a regra `index` mantida e as que disputam com ela removidas.

    Devolve `None` quando o indice nao esta em disputa — nao ha nada a resolver e
    gravar seria reescrever o arquivo a toa.

    Remove so quem disputa: uma regra de outro contexto com o mesmo padrao (uma
    de limpeza ao lado de uma de sugestao) fica, porque ela nunca competiu.
    """
    if conflicts is None:
        conflicts = glossary_conflicts(entries)
    info = conflicts.get(index)
    if not info:
        return None

    removidos = set(info["group"]) - {index}
    return [entry for position, entry in enumerate(entries) if position not in removidos]


def promote_glossary_rule(entries, index, conflicts=None):
    """Entradas com a regra `index` priorizada acima de quem disputa com ela.

    E a resposta **nao destrutiva** ao conflito, e a razao de a prioridade
    existir (ROADMAP 1.5, parte 2). `resolve_glossary_conflict` tambem faz a
    regra escolhida vencer, mas apagando as outras: uma decisao que nao da para
    revisar depois, porque o que foi descartado nao esta mais no arquivo. Aqui as
    duas regras continuam la e a escolha e um numero — reversivel, e visivel no
    proprio glossario.

    Devolve `None` quando nao ha o que fazer: a regra nao esta em disputa, ou ja
    vence em todos os contextos que a carregam. Gravar nesses casos seria
    reescrever 7 mil linhas para nao mudar nada.

    A prioridade nova e a maior entre as concorrentes mais um — nao um valor
    fixo. Priorizar duas vezes a mesma regra e um no-op; priorizar a outra regra
    depois inverte a decisao, que e o comportamento que "priorizar" promete.
    """
    if conflicts is None:
        conflicts = glossary_conflicts(entries)
    info = conflicts.get(index)
    if not info:
        return None

    if all(context["winner"] == index for context in info["contexts"]):
        return None

    concorrentes = {
        membro
        for context in info["contexts"]
        for membro in context["members"]
        if membro != index
    }
    detalhadas = _normalize_detailed_entries(entries)
    maior = max(
        (glossary_entry_priority(detalhadas[membro]) for membro in concorrentes),
        default=GLOSSARY_PRIORITY_DEFAULT,
    )
    nova = max(maior + 1, glossary_entry_priority(detalhadas[index]) + 1)

    resultado = list(detalhadas)
    orig, new, rule_type, _antiga = resultado[index]
    resultado[index] = (orig, new, rule_type, nova)
    return resultado


def deduplicate_glossary_entries(entries):
    """Remove duplicatas exatas preservando a primeira ocorrência."""
    seen = set()
    result = []
    keep_details = any(
        isinstance(entry, dict) or (isinstance(entry, (list, tuple)) and len(entry) >= 3)
        for entry in entries
    )
    for entry in _normalize_detailed_entries(entries):
        pair = glossary_entry_pair(entry)
        if pair in seen:
            continue
        seen.add(pair)
        result.append(entry if keep_details else pair)
    return result


def normalize_glossary_text(value):
    """Remove espacos nas pontas de um lado da regra.

    Um espaco no fim do padrao e consumido pelo casamento, mas a substituicao
    normalmente nao o devolve — o resultado cola duas palavras
    (`' a-coluna '` -> `' coluna a'` transforma "na a-coluna aberta" em
    "na coluna aaberta"). Um espaco no inicio tambem desliga a checagem de
    fronteira de palavra daquele lado. Nenhum dos dois efeitos e intencional,
    entao as pontas sao normalizadas na gravacao.
    """
    return "" if value is None else str(value).strip()


def add_glossary_entry(
    orig, new, path=None, backup_dir=None, timestamp=None, rule_type=None, priority=None
):
    entries = load_glossary_entry_details(path, deduplicate=False)
    entry = (
        normalize_glossary_text(orig),
        normalize_glossary_text(new),
        _normalize_rule_type(rule_type),
        normalize_glossary_priority(priority),
    )
    # A prioridade fica de fora da checagem de duplicata: a mesma regra com
    # outra prioridade continua sendo a mesma regra, e inseri-la de novo daria
    # duas linhas identicas disputando entre si — exatamente o problema que a
    # prioridade existe para resolver.
    if entry[:3] in [item[:3] for item in entries]:
        return {"status": "unchanged", "backup_path": None, "entries": len(entries)}

    entries.append(entry)
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {"status": "inserted", **result}


def update_glossary_entry(
    index, orig, new, path=None, backup_dir=None, timestamp=None, rule_type=None,
    priority=None,
):
    entries = load_glossary_entry_details(path, deduplicate=False)
    index = int(index)
    if not (0 <= index < len(entries)):
        raise IndexError("Índice do glossário fora do intervalo.")

    current_type = glossary_entry_type(entries[index])
    entries[index] = (
        normalize_glossary_text(orig),
        normalize_glossary_text(new),
        _normalize_rule_type(rule_type or current_type),
        # `None` mantem a prioridade que a entrada ja tinha: quem chama sem
        # opinar sobre prioridade nao pode zera-la sem querer.
        glossary_entry_priority(entries[index])
        if priority is None
        else normalize_glossary_priority(priority),
    )
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {"status": "updated", **result}


def find_glossary_entry_index(entries, target, index_hint=None, match_type=True):
    """Posicao de `target` em `entries`, ou `None` se ela nao existir mais.

    `index_hint` e a posicao que quem chama acredita ser a certa. Se ela ainda
    contiver a entrada esperada, e ela que vale — assim, havendo duplicatas
    exatas, a operacao atinge a que estava na tela e nao a primeira do arquivo.
    So quando o palpite falha e que se procura, e ai a primeira ocorrencia e o
    melhor que da para fazer: as duplicatas sao indistinguiveis.

    `match_type=False` compara apenas o par (original, substituicao), para quem
    nao conhece o tipo da regra.

    **A prioridade nao entra na comparacao**, de proposito. Ela e uma decisao
    sobre a regra, nao parte da identidade dela: o editor localiza a entrada
    pelo estado que exibiu quando ela foi selecionada, e mudar a prioridade e
    justamente uma das coisas que "Salvar" faz. Se a prioridade contasse aqui,
    salvar uma prioridade nova nunca encontraria a entrada a atualizar.

    Os dois lados passam por `normalize_glossary_text` antes de serem
    comparados. Nao e detalhe: a gravacao normaliza as pontas (garantia S7),
    entao procurar pelo texto como o usuario digitou nao acha a entrada que
    acabou de ser gravada — `"  bishop  "` foi para o arquivo como `"bishop"`.
    Para as entradas ja em disco isto e um no-op, porque elas ja estao
    normalizadas.
    """
    candidates = _normalize_detailed_entries([target])
    if not candidates:
        return None

    def key(entry):
        orig, new, rule_type, _priority = entry
        pair = (normalize_glossary_text(orig), normalize_glossary_text(new))
        return pair + (rule_type,) if match_type else pair

    wanted = key(candidates[0])
    normalized = _normalize_detailed_entries(entries)

    try:
        hint = None if index_hint is None else int(index_hint)
    except (TypeError, ValueError):
        hint = None

    if hint is not None and 0 <= hint < len(normalized) and key(normalized[hint]) == wanted:
        return hint

    for index, entry in enumerate(normalized):
        if key(entry) == wanted:
            return index

    return None


def update_glossary_entry_by_entry(
    previous,
    orig,
    new,
    path=None,
    backup_dir=None,
    timestamp=None,
    rule_type=None,
    index_hint=None,
    priority=None,
):
    """Atualiza a entrada que ainda for igual a `previous`.

    `previous` e o estado que o editor exibiu quando a entrada foi selecionada.
    Existe pelo mesmo motivo de `delete_glossary_entry_by_pair` (garantia S6):
    a posicao guardada pela janela e capturada no carregamento, e a janela nao e
    avisada de alteracoes externas. Se o glossario mudar por fora — pelo editor
    de traducoes, ou por outra janela desta mesma tela — o indice passa a
    apontar para a entrada vizinha e "Salvar" sobrescreve a errada em silencio.

    Devolve `None` se a entrada nao existir mais no arquivo. Quem chama decide o
    que dizer ao usuario; o que nao se faz e gravar por cima de outra coisa.
    """
    entries = load_glossary_entry_details(path, deduplicate=False)
    index = find_glossary_entry_index(entries, previous, index_hint)
    if index is None:
        return None

    current_type = glossary_entry_type(entries[index])
    entries[index] = (
        normalize_glossary_text(orig),
        normalize_glossary_text(new),
        _normalize_rule_type(rule_type or current_type),
        glossary_entry_priority(entries[index])
        if priority is None
        else normalize_glossary_priority(priority),
    )
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {"status": "updated", "index": index, **result}


def delete_glossary_entry(index, path=None, backup_dir=None, timestamp=None):
    entries = load_glossary_entry_details(path, deduplicate=False)
    index = int(index)
    if not (0 <= index < len(entries)):
        raise IndexError("Índice do glossário fora do intervalo.")

    removed = entries.pop(index)
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {
        "status": "deleted",
        "removed": glossary_entry_pair(removed),
        "removed_entry": removed,
        **result,
    }


def delete_glossary_entry_by_pair(
    orig,
    new,
    path=None,
    backup_dir=None,
    timestamp=None,
    rule_type=None,
    index_hint=None,
):
    """Remove a entrada cujo par seja exatamente (orig, new).

    Existe porque excluir por indice e frágil: quem exibe a lista costuma usar a
    versao deduplicada, enquanto a exclusao opera na lista completa do arquivo.
    Uma unica duplicata antes do alvo desloca todos os indices seguintes e a
    entrada errada e removida em silencio (garantia S6 da SPEC.md).

    `rule_type` restringe o casamento ao tipo tambem, para quem conhece a
    entrada inteira; `index_hint` diz qual duplicata estava na tela. Sem os
    dois, remove a primeira ocorrencia do par. Devolve `None` se nao existir.
    """
    entries = load_glossary_entry_details(path, deduplicate=False)
    target = (str(orig), str(new), _normalize_rule_type(rule_type))
    index = find_glossary_entry_index(
        entries,
        target,
        index_hint,
        match_type=rule_type is not None,
    )
    if index is None:
        return None

    removed = entries.pop(index)
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {
        "status": "deleted",
        "removed": glossary_entry_pair(removed),
        "removed_entry": removed,
        "index": index,
        **result,
    }


def export_glossary_csv(csv_path, entries=None, path=None):
    """Exporta o glossário para CSV UTF-8 com BOM."""
    if entries is None:
        entries = load_glossary_entry_details(path, deduplicate=False)

    _ensure_parent_dir(csv_path)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(GLOSSARY_CSV_HEADERS)
        writer.writerows(_normalize_detailed_entries(entries))

    return {"exported": len(_normalize_detailed_entries(entries)), "csv_path": csv_path}


def read_glossary_csv(csv_path):
    """Lê pares de glossário de um CSV exportado ou equivalente."""
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []

        normalized_fields = {
            (field or "").strip().lower(): field
            for field in reader.fieldnames
        }
        original_field = (
            normalized_fields.get("original")
            or normalized_fields.get("orig")
            or normalized_fields.get("texto encontrado")
        )
        replacement_field = (
            normalized_fields.get("replacement")
            or normalized_fields.get("new")
            or normalized_fields.get("substituicao")
            or normalized_fields.get("substituição")
            or normalized_fields.get("substituir por")
        )
        type_field = (
            normalized_fields.get("type")
            or normalized_fields.get("rule_type")
            or normalized_fields.get("tipo")
        )
        # Sem coluna de prioridade toda regra entra com a padrao. Um CSV de
        # antes desta versao — ou montado a mao numa planilha com tres colunas —
        # continua importavel, que e o que o formato tem de garantir.
        priority_field = (
            normalized_fields.get("priority")
            or normalized_fields.get("prioridade")
        )
        if not original_field or not replacement_field:
            raise ValueError("CSV precisa conter colunas original e replacement.")

        rows = []
        for row in reader:
            rows.append(
                (
                    (row.get(original_field) or "").strip(),
                    (row.get(replacement_field) or "").strip(),
                    _normalize_rule_type(row.get(type_field) if type_field else None),
                    normalize_glossary_priority(
                        row.get(priority_field) if priority_field else None
                    ),
                )
            )
        return rows


def analyze_glossary_csv_import(path, csv_path, allow_conflicts=False):
    """Analisa um CSV antes de importar para o glossário persistente."""
    existing = load_glossary_entry_details(path, deduplicate=False)
    existing_pairs = set(_normalize_entries(existing))
    replacements_by_original = {}
    for orig, new in _normalize_entries(existing):
        replacements_by_original.setdefault(orig, set()).add(new)

    stats = {
        "total_rows": 0,
        "inserted": 0,
        "duplicates": 0,
        "conflicts": 0,
        "skipped": 0,
        "invalid": 0,
    }
    to_insert = []
    # Pares ja aceitos nesta importacao. Antes isto era
    # `pair in _normalize_entries(to_insert)`, que reconstruia a lista inteira e
    # fazia busca linear nela a cada linha do CSV — custo quadratico (~2,5 s
    # para 4 mil linhas, com a interface travada).
    inserted_pairs = set()

    for row_entry in read_glossary_csv(csv_path):
        orig, new = glossary_entry_pair(row_entry)
        rule_type = glossary_entry_type(row_entry)
        stats["total_rows"] += 1
        # Substituicao vazia e invalida em toda regra MENOS na de limpeza, onde
        # ela e o proprio ponto: apagar lixo de conversao (`'== StartFEN =='`)
        # antes de mandar o comentario para a API. O criterio e o mesmo de
        # `validate_glossary_entry`, e ate agora os dois discordavam: exportar o
        # glossario e reimporta-lo **descartava as regras de delecao**, em
        # silencio, porque aqui elas caiam em `invalid` (garantia S14).
        if not orig or (not new and rule_type != GLOSSARY_RULE_CLEANUP):
            stats["invalid"] += 1
            stats["skipped"] += 1
            continue

        pair = (orig, new)
        if pair in existing_pairs or pair in inserted_pairs:
            stats["duplicates"] += 1
            stats["skipped"] += 1
            continue

        has_conflict = orig in replacements_by_original and new not in replacements_by_original[orig]
        if has_conflict:
            stats["conflicts"] += 1
            if not allow_conflicts:
                stats["skipped"] += 1
                continue

        to_insert.append((orig, new, rule_type, glossary_entry_priority(row_entry)))
        inserted_pairs.add(pair)
        replacements_by_original.setdefault(orig, set()).add(new)
        stats["inserted"] += 1

    stats["entries"] = to_insert
    return stats


def import_glossary_csv(
    path,
    csv_path,
    allow_conflicts=False,
    backup_dir=None,
    timestamp=None,
    analysis=None,
):
    """Importa entradas novas de CSV, preservando as existentes.

    `analysis` reaproveita a previa ja calculada (ROADMAP 2.10). Nao e so
    economia de uma leitura: e o que garante que as entradas gravadas sao as que
    o usuario viu no dialogo. Recalculando, um CSV alterado entre a previa e o
    "Sim" importaria outra coisa.
    """
    stats = analysis
    if stats is None:
        stats = analyze_glossary_csv_import(
            path, csv_path, allow_conflicts=allow_conflicts
        )
    if not stats["entries"]:
        stats["backup_path"] = None
        return stats

    existing = load_glossary_entry_details(path, deduplicate=False)
    result = save_glossary_entries(
        existing + stats["entries"],
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    stats["backup_path"] = result["backup_path"]
    return stats


def restore_glossary_from_backup(path, backup_path, safety_backup_dir=None, timestamp=None):
    """Restaura o glossário a partir de um backup validado."""
    if path is None:
        path = _default_substitutions_path()

    load_glossary_entries(backup_path, deduplicate=False)
    safety_backup_path = create_glossary_backup(
        path,
        backup_dir=safety_backup_dir,
        timestamp=timestamp,
        protect=(backup_path,),
    )
    _ensure_parent_dir(path)
    shutil.copy2(backup_path, path)
    if _is_default_substitutions_path(path):
        rebuild_glossary_database(path)
    return {"safety_backup_path": safety_backup_path}


def load_substitutions(path=None):
    """
    Carrega a lista de substituições do arquivo Substituicoes.txt.

    Espera uma atribuição Python contendo uma lista de pares:
        substituições = [
            ('tower', 'torre'),
            ('pawn', 'peão'),
        ]
    """
    if path is None:
        path = _default_substitutions_path()

    if not os.path.exists(path):
        report_glossary_error(f"Arquivo não encontrado: {path}")
        return []

    try:
        substitutions = load_suggestion_substitutions(path)
    except Exception as e:
        # Devolver [] aqui e o que torna a falha invisivel: o programa segue
        # traduzindo sem nenhuma regra. O aviso e o que separa "sem glossario
        # porque o usuario quis" de "sem glossario porque o arquivo quebrou".
        report_glossary_error(
            f"Erro ao carregar {os.path.basename(path)}: {e}\n"
            "As regras do glossário NÃO serão aplicadas até o arquivo ser corrigido."
        )
        return []

    clear_glossary_error()
    print(f"[GLOSSÁRIO] Carregadas {len(substitutions)} entradas do glossário.")
    return substitutions


def _is_word_char(char):
    return bool(char) and (char.isalnum() or char == "_")


def _has_safe_match_boundary(text, start, end, pattern):
    if not pattern:
        return False

    if _is_word_char(pattern[0]) and start > 0 and _is_word_char(text[start - 1]):
        return False
    if _is_word_char(pattern[-1]) and end < len(text) and _is_word_char(text[end]):
        return False
    return True


@lru_cache(maxsize=32768)
def _compiled_glossary_pattern(orig):
    """Compila o padrão literal de uma regra, com cache.

    Usa `re` sobre o texto ORIGINAL em vez de `text.lower()`: `str.lower()` não
    preserva o comprimento em Unicode (`len('İ'.lower()) == 2`), e um índice
    obtido do texto minúsculo aplicado ao texto original desloca tudo à direita
    (garantia S2 da SPEC.md). O padrão é sempre escapado, nunca interpretado.
    """
    flags = re.IGNORECASE if orig == orig.lower() else 0
    return re.compile(re.escape(orig), flags)


def find_glossary_matches(text, orig):
    """Retorna ranges onde orig aparece sem capturar pedaços de palavras.

    Os ranges devolvidos são disjuntos e em ordem crescente (garantia S1): um
    match aceito faz a busca continuar a partir do seu fim, para que
    `('de de' -> 'de')` aplicado a `"de de de"` não devore o espaço
    compartilhado entre duas ocorrências sobrepostas.
    """
    if not text or not orig:
        return []

    pattern = _compiled_glossary_pattern(orig)
    matches = []
    position = 0

    while position <= len(text):
        found = pattern.search(text, position)
        if found is None:
            break

        start, end = found.start(), found.end()
        if _has_safe_match_boundary(text, start, end, orig):
            matches.append((start, end))
            position = end if end > start else start + 1
        else:
            # Fronteira inválida: continua logo depois do início, para não
            # perder uma ocorrência válida que comece no meio desta.
            position = start + 1

    return matches


def case_adjusted_replacement(matched_text, replacement):
    if not matched_text or not replacement:
        return replacement

    letters = [char for char in matched_text if char.isalpha()]
    if letters and all(char.isupper() for char in letters):
        return replacement.upper()
    if letters and letters[0].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _replace_glossary_matches(text, orig, new, count=0):
    matches = find_glossary_matches(text, orig)
    if count > 0:
        matches = matches[:count]
    if not matches:
        return text

    parts = []
    last = 0
    for start, end in matches:
        parts.append(text[last:start])
        parts.append(case_adjusted_replacement(text[start:end], new))
        last = end
    parts.append(text[last:])
    return "".join(parts)


def find_glossary_suggestions(text, substitutions, max_suggestions=80):
    """
    Retorna entradas do glossário que aparecem em text.

    Ordenadas por especificidade: além de ser a ordem em que serão aplicadas
    (garantia S3), garante que o corte em `max_suggestions` descarte as regras
    genéricas e não as específicas.
    """
    if not text:
        return []

    suggestions = []
    # Sem repetir o mesmo par: uma regra literal e a expansao de um `@casa@`
    # podem chegar aqui como a mesma sugestao, e oferece-la duas vezes na lista
    # nunca ajudou ninguem.
    vistos = set()
    # Indexado, e nao `for orig, new in ...`: uma regra priorizada chega aqui
    # com tres elementos. As sugestoes devolvidas continuam sendo pares — quem
    # as recebe aplica o par, nao reordena.
    for rule in order_rules_by_specificity(substitutions):
        orig, new = rule[0], rule[1]
        if (orig, new) in vistos:
            continue
        if find_glossary_matches(text, orig):
            vistos.add((orig, new))
            suggestions.append((orig, new))
            if len(suggestions) >= max_suggestions:
                break

    return suggestions


def _as_rule(entry):
    """Entrada detalhada -> regra `(orig, new)` ou `(orig, new, prioridade)`.

    A regra so ganha o terceiro elemento quando ha prioridade para carregar. E
    deliberado: `app.glossary_substitutions` e as listas de regras circulam por
    todo o programa e sao comparadas com pares literais em dezenas de lugares.
    Acrescentar um `0` a todas mudaria a forma de tudo para representar a
    ausencia de uma decisao.
    """
    orig, new = glossary_entry_pair(entry)
    priority = glossary_entry_priority(entry)
    if priority == GLOSSARY_PRIORITY_DEFAULT:
        return (orig, new)
    return (orig, new, priority)


# Placeholder de casa do tabuleiro (ROADMAP 14.7). Uma regra escrita com ele
# vale para as 64 casas: `('@casa@-torre', 'torre de @casa@')` e uma linha no
# arquivo e 64 regras na aplicacao.
#
# Existe porque 1.235 das 7.105 regras (17,4%) enumeravam casas a mao, e a
# enumeracao manual tem o defeito de toda enumeracao manual: **buracos**. Sete
# familias paravam em 56 regras — faltava a fileira 3 inteira —, `torre-<casa>`
# e `dama-<casa>` nunca existiram, e ninguem consegue ver isso lendo 7 mil
# linhas. A expansao nao tem como esquecer uma casa.
#
# Nao e regex, e a promessa da SPEC continua de pe: as regras que saem daqui sao
# literais, exatamente as que o usuario escreveria a mao. O que muda e quem as
# escreve.
GLOSSARY_SQUARE_PLACEHOLDER = "@casa@"
BOARD_SQUARES = tuple(
    f"{coluna}{fileira}" for coluna in "abcdefgh" for fileira in "12345678"
)


def expand_square_placeholder(rule):
    """Uma regra com `@casa@` -> as 64 regras literais; as outras, ela mesma.

    O ORIGINAL manda: se ele nao tem o placeholder, a regra sai intacta mesmo
    que a substituicao tenha — um `@casa@` sozinho na substituicao nao teria por
    onde ser resolvido, e inventar 64 regras iguais para um padrao unico
    mudaria o que a regra casa.

    A expansao acontece na conversao entrada -> regra, e nao na leitura do
    arquivo: o editor de glossario continua mostrando **uma** linha com o
    placeholder, que e o que da para editar. A ordenacao por comprimento (S3)
    ve o padrao ja expandido, com o tamanho real que ele tem no texto.
    """
    orig = rule[0]
    if GLOSSARY_SQUARE_PLACEHOLDER not in orig:
        return [rule]

    resto = tuple(rule[2:])
    return [
        (
            orig.replace(GLOSSARY_SQUARE_PLACEHOLDER, casa),
            rule[1].replace(GLOSSARY_SQUARE_PLACEHOLDER, casa),
        )
        + resto
        for casa in BOARD_SQUARES
    ]


def _rules_from_entries(entries, allowed_types):
    """Entradas -> regras aplicaveis, filtradas por tipo e com `@casa@` expandido."""
    regras = []
    for entry in _normalize_detailed_entries(entries):
        if glossary_entry_type(entry) in allowed_types:
            regras.extend(expand_square_placeholder(_as_rule(entry)))
    return regras


def filter_glossary_entries_by_type(entries, rule_type):
    return _rules_from_entries(entries, {_normalize_rule_type(rule_type)})


def load_cleanup_substitutions(path=None):
    return filter_glossary_entries_by_type(
        load_glossary_entry_details(path),
        GLOSSARY_RULE_CLEANUP,
    )


def load_suggestion_substitutions(path=None):
    return filter_glossary_entries_by_type(
        load_glossary_entry_details(path),
        GLOSSARY_RULE_SUGGESTION,
    )


def load_automatic_substitutions(path=None):
    return filter_glossary_entries_by_type(
        load_glossary_entry_details(path),
        GLOSSARY_RULE_AUTOMATIC,
    )


def load_interactive_substitutions(path=None):
    return _rules_from_entries(
        load_glossary_entry_details(path),
        {GLOSSARY_RULE_SUGGESTION, GLOSSARY_RULE_AUTOMATIC},
    )


def apply_substitution(text, orig, new):
    """Aplica uma substituição, na primeira ocorrência encontrada."""
    return _replace_glossary_matches(text, orig, new, count=1)


def rule_priority(rule):
    """Prioridade de uma regra `(orig, new[, prioridade])`.

    As regras que circulam pelo programa sao pares; as que vem do glossario
    trazem a prioridade num terceiro elemento. Um par escrito a mao continua
    valendo, com prioridade zero — e o que mantem `apply_all_substitutions`
    utilizavel com uma lista literal.
    """
    if isinstance(rule, (list, tuple)) and len(rule) >= 3:
        return normalize_glossary_priority(rule[2])
    return GLOSSARY_PRIORITY_DEFAULT


def _rule_sort_key(rule, position):
    """O criterio da disputa: prioridade, comprimento do padrao, ordem do arquivo.

    Existe uma vez so, e e por isso que ele e uma funcao em vez de um `key=`
    escrito na chamada. Duas partes do programa precisam desta mesma resposta —
    `order_rules_by_specificity`, para **aplicar**, e `glossary_conflicts`, para
    **anunciar** qual regra do conflito esta valendo — e enquanto cada uma tinha
    a sua copia, bastava mexer numa para a janela apontar uma regra e o texto
    receber outra. Uma mensagem errada e crivel e pior do que mensagem nenhuma.

    - `-prioridade` primeiro (garantia S10): a intencao declarada decide antes
      do texto.
    - `-comprimento` depois (garantia S3): a regra mais especifica roda antes,
      senao a curta consome o trecho que a longa pretendia casar.
    - `posicao` por ultimo: desempate deterministico, que preserva a ordem em
      que o autor escreveu.
    """
    return (-rule_priority(rule), -len(str(rule[0])), position)


def _specificity_order(rules):
    """As posicoes de `rules` na ordem em que as regras disputam o texto.

    Devolve posicoes, e nao as regras ordenadas: `glossary_conflicts` precisa
    saber **qual entrada** venceu, e duas regras podem ser identicas em conteudo
    (uma duplicata exata ao lado de uma terceira que diverge). A regra devolvida
    seria ambigua nesse caso; a posicao nunca e.
    """
    return sorted(
        range(len(rules)),
        key=lambda position: _rule_sort_key(rules[position], position),
    )


def _ordered_rules_cache_key(rules):
    """Chave estavel para o cache de ordenacao, ou `None` se nao der para gerar.

    Uma lista nao e hashavel, e o `id()` dela nao serve (uma lista nova pode
    reaproveitar o endereco de uma coletada). A tupla dos pares e hashavel e
    identifica o conteudo, que e exatamente do que a ordem depende.

    A prioridade entra na chave porque entra na ordem. Sem ela, duas listas com
    os mesmos pares e prioridades diferentes compartilhariam a entrada do cache
    e a segunda receberia a ordem da primeira — errado, e em silencio.
    """
    try:
        return tuple(
            (str(rule[0]), str(rule[1]), rule_priority(rule)) for rule in rules
        )
    except (TypeError, IndexError):
        return None


_ordered_rules_cache = {}
_ORDERED_RULES_CACHE_MAX = 8


def order_rules_by_specificity(rules):
    """Ordena regras da mais específica para a mais genérica.

    O resultado e memorizado por conteudo: as mesmas regras entram aqui muitas
    vezes seguidas e a ordem so depende delas. Sem o cache, `find_glossary_suggestions`
    reordenava as 7.008 regras de sugestao a cada linha carregada no editor
    (3,3 ms dos 12,5 ms que a operacao custava), e `apply_all_substitutions`
    reordenava as automaticas uma vez por traducao — 195.603 vezes por passagem.

    O cache guarda poucos conjuntos (sugestao, automatica, limpeza e pouco mais);
    o limite existe so para nao crescer sem teto se alguem chamar com listas
    variadas.

    A aplicação é em cascata sobre o texto já modificado, então uma regra curta
    que rode antes consome o trecho que uma regra longa pretendia casar:
    `('verificação' -> 'xeque')` antes de
    `('da verificação intermediária' -> 'do xeque intermediário')` faz a segunda
    nunca disparar. Ordenar por comprimento do padrão resolve (garantia S3).

    **A prioridade explícita vem antes do comprimento** (garantia S10). Era essa
    a queixa do item 1.5: a especificidade é derivada do texto, então adiantar
    uma regra exigia alongar o padrão — mudar o que a regra casa para mudar
    quando ela roda. Com a prioridade, a intenção é declarada, e o comprimento
    volta a decidir apenas entre regras que ninguém priorizou (prioridade zero,
    que é a de praticamente todas).

    O desempate mantém a ordem original do arquivo, para que o resultado seja
    determinístico e a intenção do autor seja preservada entre regras de mesmo
    tamanho.

    O critério em si está em `_rule_sort_key`, e não aqui: `glossary_conflicts`
    precisa da mesma resposta para anunciar quem vence, e as duas perguntam à
    mesma função. Mexer na ordem de aplicação muda o que a janela anuncia, na
    mesma edição.
    """
    chave = _ordered_rules_cache_key(rules)
    if chave is not None and chave in _ordered_rules_cache:
        return list(_ordered_rules_cache[chave])

    ordenadas = [rules[position] for position in _specificity_order(rules)]

    if chave is not None:
        if len(_ordered_rules_cache) >= _ORDERED_RULES_CACHE_MAX:
            _ordered_rules_cache.clear()
        _ordered_rules_cache[chave] = list(ordenadas)

    # Devolve sempre uma lista nova: quem chama pode mutar o resultado, e isso
    # nao pode contaminar o cache.
    return ordenadas


def apply_all_substitutions(
    text,
    suggestions,
    order_by_specificity=True,
    protect_replacements=True,
):
    """Aplica todas as substituições, da regra mais específica para a mais genérica.

    O texto já substituído por uma regra fica "congelado": regras seguintes só
    enxergam os trechos ainda intocados. Sem isso, duas regras contraditórias do
    glossário se desfazem uma à outra e o resultado passa a depender da ordem em
    que foram digitadas no arquivo. Exemplo real:

        ('Rei das brancas estão', 'Rei das brancas está')
        ('brancas está',          'brancas estão')

    Sem congelamento a segunda reverte a primeira; com congelamento, cada regra
    entrega exatamente o que declarou (garantia S3 da SPEC.md).

    `order_by_specificity=False` respeita a ordem recebida e
    `protect_replacements=False` volta ao encadeamento em cascata; ambos existem
    para casos em que o chamador quer o comportamento antigo.
    """
    rules = order_rules_by_specificity(suggestions) if order_by_specificity else list(suggestions)

    if not protect_replacements:
        for rule in rules:
            text = _replace_glossary_matches(text, rule[0], rule[1])
        return text

    # (trecho, congelado): um trecho congelado veio de uma substituição e não
    # pode ser reexaminado pelas regras seguintes.
    segments = [(text or "", False)]

    for rule in rules:
        # Indexado: uma regra priorizada tem tres elementos (ver `_as_rule`).
        orig, new = rule[0], rule[1]
        if not orig:
            continue

        updated = []
        for chunk, frozen in segments:
            if frozen or not chunk:
                updated.append((chunk, frozen))
                continue

            matches = find_glossary_matches(chunk, orig)
            if not matches:
                updated.append((chunk, frozen))
                continue

            last = 0
            for start, end in matches:
                if start > last:
                    updated.append((chunk[last:start], False))
                updated.append((case_adjusted_replacement(chunk[start:end], new), True))
                last = end
            if last < len(chunk):
                updated.append((chunk[last:], False))

        segments = updated

    return "".join(chunk for chunk, _ in segments)


def clean_comment_for_translation(text, cleanup_rules):
    cleaned = apply_all_substitutions(text or "", cleanup_rules)
    return " ".join(cleaned.split())


def apply_automatic_substitutions(text, automatic_rules):
    return apply_all_substitutions(text or "", automatic_rules)


def add_to_glossary(orig, new, path=None, rule_type=None):
    """
    Adiciona um par (orig, new) ao arquivo Substituicoes.txt.
    """
    if path is None:
        path = _default_substitutions_path()

    try:
        add_glossary_entry(orig, new, path, rule_type=rule_type)
        return True

    except Exception as e:
        print(f"[GLOSSÁRIO] Erro ao adicionar entrada: {e}")
        return False
