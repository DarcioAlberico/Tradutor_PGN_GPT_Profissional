# glossario.py
# Carrega e manipula o arquivo Substituicoes.txt.

import ast
import csv
from datetime import datetime
import os
import shutil
import sqlite3
import sys


SUBSTITUTION_VARIABLES = {"substituições", "substituicoes"}
GLOSSARY_RULE_SUGGESTION = "suggestion"
GLOSSARY_RULE_CLEANUP = "cleanup"
GLOSSARY_RULE_AUTOMATIC = "automatic"
GLOSSARY_RULE_TYPES = (
    GLOSSARY_RULE_SUGGESTION,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_AUTOMATIC,
)
GLOSSARY_CSV_HEADERS = ["original", "replacement", "type"]
GLOSSARY_DB_FILENAME = "glossario.db"


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


def _normalize_rule_type(rule_type):
    value = "" if rule_type is None else str(rule_type).strip()
    aliases = {
        "sugestao": GLOSSARY_RULE_SUGGESTION,
        "sugestão": GLOSSARY_RULE_SUGGESTION,
        "suggestion": GLOSSARY_RULE_SUGGESTION,
        "limpeza": GLOSSARY_RULE_CLEANUP,
        "cleanup": GLOSSARY_RULE_CLEANUP,
        "automatica": GLOSSARY_RULE_AUTOMATIC,
        "automática": GLOSSARY_RULE_AUTOMATIC,
        "automatic": GLOSSARY_RULE_AUTOMATIC,
    }
    normalized = aliases.get(value.casefold(), value)
    return normalized if normalized in GLOSSARY_RULE_TYPES else GLOSSARY_RULE_SUGGESTION


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
            normalized.append((str(orig), str(new), _entry_rule_type(item)))
    return normalized


def glossary_entry_pair(entry):
    return _entry_pair(entry) or ("", "")


def glossary_entry_type(entry):
    return _entry_rule_type(entry)


def _serialize_entries(entries):
    lines = ["substituicoes = [\n"]
    for orig, new, rule_type in _normalize_detailed_entries(entries):
        if rule_type == GLOSSARY_RULE_SUGGESTION:
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


def _source_mtime(path):
    if not os.path.exists(path):
        return ""
    return str(os.path.getmtime(path))


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
                position,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (orig, new, rule_type, index, now, now)
                for index, (orig, new, rule_type) in enumerate(entries)
            ],
        )
        _set_glossary_metadata(conn, "entry_count", len(entries))
        if source_path is not None:
            _set_glossary_metadata(conn, "source_path", os.path.abspath(source_path))
            _set_glossary_metadata(conn, "source_mtime", _source_mtime(source_path))
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
            SELECT original_text, replacement_text, rule_type
            FROM glossary_entries
            ORDER BY position, id
            """
        ).fetchall()
    finally:
        conn.close()

    entries = [
        (row[0], row[1], _normalize_rule_type(row[2]))
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
        source_mtime = _get_glossary_metadata(conn, "source_mtime")
    finally:
        conn.close()

    if count == 0:
        return True
    if source_path and os.path.abspath(source_path) != os.path.abspath(path):
        return True
    return source_mtime != _source_mtime(path)


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
            print(f"[GLOSSÁRIO] Erro ao usar glossario.db: {exc}")

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
            print(f"[GLOSSÁRIO] Erro ao usar glossario.db: {exc}")

    return _load_glossary_entry_details_from_file(path, deduplicate=deduplicate)


def create_glossary_backup(path=None, backup_dir=None, timestamp=None):
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


def validate_glossary_entry(orig, new, existing_entries=None, current_index=None, rule_type=None):
    """Retorna avisos de validação para uma entrada do glossário."""
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

    if existing_entries is not None:
        for index, entry in enumerate(_normalize_entries(existing_entries)):
            if current_index is not None and index == current_index:
                continue
            existing_orig, existing_new = entry
            if (orig, new) == (existing_orig, existing_new):
                warnings.append("Entrada duplicada.")
                break
            if orig and orig == existing_orig and new != existing_new:
                warnings.append("Mesmo original com substituição diferente.")
                break

    return warnings


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


def add_glossary_entry(orig, new, path=None, backup_dir=None, timestamp=None, rule_type=None):
    entries = load_glossary_entry_details(path, deduplicate=False)
    entry = (str(orig), str(new), _normalize_rule_type(rule_type))
    if entry in entries:
        return {"status": "unchanged", "backup_path": None, "entries": len(entries)}

    entries.append(entry)
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {"status": "inserted", **result}


def update_glossary_entry(index, orig, new, path=None, backup_dir=None, timestamp=None, rule_type=None):
    entries = load_glossary_entry_details(path, deduplicate=False)
    index = int(index)
    if not (0 <= index < len(entries)):
        raise IndexError("Índice do glossário fora do intervalo.")

    current_type = glossary_entry_type(entries[index])
    entries[index] = (str(orig), str(new), _normalize_rule_type(rule_type or current_type))
    result = save_glossary_entries(
        entries,
        path,
        backup_dir=backup_dir,
        timestamp=timestamp,
    )
    return {"status": "updated", **result}


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
        if not original_field or not replacement_field:
            raise ValueError("CSV precisa conter colunas original e replacement.")

        rows = []
        for row in reader:
            rows.append(
                (
                    (row.get(original_field) or "").strip(),
                    (row.get(replacement_field) or "").strip(),
                    _normalize_rule_type(row.get(type_field) if type_field else None),
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

    for row_entry in read_glossary_csv(csv_path):
        orig, new = glossary_entry_pair(row_entry)
        rule_type = glossary_entry_type(row_entry)
        stats["total_rows"] += 1
        if not orig or not new:
            stats["invalid"] += 1
            stats["skipped"] += 1
            continue

        pair = (orig, new)
        if pair in existing_pairs or pair in _normalize_entries(to_insert):
            stats["duplicates"] += 1
            stats["skipped"] += 1
            continue

        has_conflict = orig in replacements_by_original and new not in replacements_by_original[orig]
        if has_conflict:
            stats["conflicts"] += 1
            if not allow_conflicts:
                stats["skipped"] += 1
                continue

        to_insert.append((orig, new, rule_type))
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
):
    """Importa entradas novas de CSV, preservando as existentes."""
    stats = analyze_glossary_csv_import(path, csv_path, allow_conflicts=allow_conflicts)
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
        print(f"[GLOSSÁRIO] Arquivo não encontrado: {path}")
        return []

    try:
        substitutions = load_suggestion_substitutions(path)

        print(f"[GLOSSÁRIO] Carregadas {len(substitutions)} entradas do glossário.")
        return substitutions

    except Exception as e:
        print(f"[GLOSSÁRIO] Erro ao carregar Substituicoes.txt: {e}")
        return []


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


def find_glossary_matches(text, orig):
    """Retorna ranges onde orig aparece sem capturar pedaços de palavras."""
    if not text or not orig:
        return []

    matches = []
    start = 0
    while True:
        index = text.find(orig, start)
        if index == -1:
            break

        end = index + len(orig)
        if _has_safe_match_boundary(text, index, end, orig):
            matches.append((index, end))
        start = index + 1

    return matches


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
        parts.append(new)
        last = end
    parts.append(text[last:])
    return "".join(parts)


def find_glossary_suggestions(text, substitutions, max_suggestions=80):
    """
    Retorna entradas do glossário que aparecem em text.
    """
    if not text:
        return []

    suggestions = []
    for orig, new in substitutions:
        if find_glossary_matches(text, orig):
            suggestions.append((orig, new))
            if len(suggestions) >= max_suggestions:
                break

    return suggestions


def filter_glossary_entries_by_type(entries, rule_type):
    rule_type = _normalize_rule_type(rule_type)
    return [
        glossary_entry_pair(entry)
        for entry in _normalize_detailed_entries(entries)
        if glossary_entry_type(entry) == rule_type
    ]


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


def apply_substitution(text, orig, new):
    """Aplica uma substituição, na primeira ocorrência encontrada."""
    return _replace_glossary_matches(text, orig, new, count=1)


def apply_all_substitutions(text, suggestions):
    """Aplica todas as substituições sugeridas em sequência."""
    for orig, new in suggestions:
        text = _replace_glossary_matches(text, orig, new)
    return text


def clean_comment_for_translation(text, cleanup_rules):
    cleaned = apply_all_substitutions(text or "", cleanup_rules)
    return " ".join(cleaned.split())


def apply_automatic_substitutions(text, automatic_rules):
    return apply_all_substitutions(text or "", automatic_rules)


def add_to_glossary(orig, new, path=None):
    """
    Adiciona um par (orig, new) ao arquivo Substituicoes.txt.
    """
    if path is None:
        path = _default_substitutions_path()

    try:
        add_glossary_entry(orig, new, path)
        return True

    except Exception as e:
        print(f"[GLOSSÁRIO] Erro ao adicionar entrada: {e}")
        return False
