import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from .database import (
    analyze_automatic_translation_updates,
    apply_automatic_translation_updates,
    fetch_export_rows,
    fetch_review_rows,
    get_database_stats,
    initialize_database,
    save_translation,
    set_translation_verified_by_id,
)
from .glossario import apply_automatic_substitutions, load_automatic_substitutions
from .review_quality import summarize_quality_warnings


def _unique_backup_path(backup_dir, stem, timestamp):
    base_name = f"{stem}-backup-{timestamp}.db"
    backup_path = backup_dir / base_name
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{stem}-backup-{timestamp}-{suffix}.db"
        suffix += 1
    return backup_path


def create_database_backup(db_path, backup_dir=None, timestamp=None):
    source_path = Path(db_path)
    if backup_dir is None:
        backup_dir = source_path.parent / "backups"
    else:
        backup_dir = Path(backup_dir)

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = _unique_backup_path(backup_dir, source_path.stem, timestamp)

    source_conn = initialize_database(str(source_path))
    target_conn = sqlite3.connect(str(backup_path))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    return str(backup_path)


def validate_restore_source(backup_path):
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup nao encontrado: {backup_path}")

    conn = sqlite3.connect(str(backup_path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Backup invalido: integrity_check retornou {integrity}")

        has_comments = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'comments'
            """
        ).fetchone()
        if has_comments is None:
            raise ValueError("Backup invalido: tabela comments nao encontrada")
    finally:
        conn.close()


def restore_database_from_backup(db_path, backup_path, safety_backup_dir=None):
    target_path = Path(db_path)
    backup_path = Path(backup_path)
    if target_path.resolve() == backup_path.resolve():
        raise ValueError("O backup selecionado e o banco atual sao o mesmo arquivo")

    validate_restore_source(backup_path)
    safety_backup_path = create_database_backup(
        target_path,
        backup_dir=safety_backup_dir,
    )

    source_conn = sqlite3.connect(str(backup_path))
    target_conn = sqlite3.connect(str(target_path))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    migrated_conn = initialize_database(str(target_path))
    try:
        integrity = migrated_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Banco restaurado invalido: integrity_check retornou {integrity}")
    finally:
        migrated_conn.close()

    return {
        "restored_path": str(target_path),
        "safety_backup_path": safety_backup_path,
    }


def _parse_verified(value):
    if value is None:
        return False
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "sim",
        "ok",
        "verified",
        "verificada",
        "verificado",
    }


def _fetch_comment_id(cursor, original_comment, target_language):
    row = cursor.execute(
        """
        SELECT id
        FROM comments
        WHERE original_comment = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, target_language),
    ).fetchone()
    return row[0] if row else None


def _read_translation_csv_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        required = {"original_comment", "translated_comment", "target_language"}
        missing = sorted(required - fieldnames)
        if missing:
            raise ValueError("CSV sem colunas obrigatorias: " + ", ".join(missing))
        return list(reader)


def _normalize_import_row(row):
    return {
        "original_comment": (row.get("original_comment") or "").strip(),
        "translated_comment": (row.get("translated_comment") or "").strip(),
        "target_language": (row.get("target_language") or "").strip(),
        "verified": _parse_verified(row.get("verified")),
    }


def _empty_import_stats(backup_path=None):
    return {
        "total_rows": 0,
        "inserted": 0,
        "filled_empty": 0,
        "unchanged": 0,
        "skipped": 0,
        "verified_applied": 0,
        "backup_path": backup_path,
    }


def _existing_translation(cursor, original_comment, target_language):
    return cursor.execute(
        """
        SELECT translated_comment
        FROM comments
        WHERE original_comment = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, target_language),
    ).fetchone()


def analyze_translations_csv_import(db_path, csv_path):
    csv_rows = _read_translation_csv_rows(csv_path)
    stats = _empty_import_stats()

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            row = _normalize_import_row(raw_row)
            original = row["original_comment"]
            translated = row["translated_comment"]
            target_language = row["target_language"]

            if not original or not translated or not target_language:
                stats["skipped"] += 1
                continue

            existing = _existing_translation(cursor, original, target_language)
            if existing is None:
                stats["inserted"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
                continue

            existing_translation = existing[0]
            if existing_translation is None or existing_translation == "":
                stats["filled_empty"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
            else:
                stats["unchanged"] += 1
    finally:
        conn.close()

    return stats


def import_translations_from_csv(
    db_path,
    csv_path,
    create_backup=True,
    backup_dir=None,
):
    csv_rows = _read_translation_csv_rows(csv_path)

    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    stats = _empty_import_stats(backup_path)

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            row = _normalize_import_row(raw_row)
            original = row["original_comment"]
            translated = row["translated_comment"]
            target_language = row["target_language"]

            if not original or not translated or not target_language:
                stats["skipped"] += 1
                continue

            save_status = save_translation(
                cursor,
                original,
                translated,
                target_language,
            )
            if save_status == "inserted":
                stats["inserted"] += 1
            elif save_status == "filled_empty":
                stats["filled_empty"] += 1
            else:
                stats["unchanged"] += 1

            if save_status in {"inserted", "filled_empty"} and row["verified"]:
                comment_id = _fetch_comment_id(cursor, original, target_language)
                if comment_id is not None:
                    stats["verified_applied"] += set_translation_verified_by_id(
                        cursor,
                        comment_id,
                        True,
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return stats


def analyze_database_automatic_rules(db_path, target_language=None, automatic_rules=None):
    if automatic_rules is None:
        automatic_rules = load_automatic_substitutions()

    conn = initialize_database(db_path)
    try:
        return analyze_automatic_translation_updates(
            conn.cursor(),
            automatic_rules,
            apply_automatic_substitutions,
            target_language=target_language,
        )
    finally:
        conn.close()


def apply_database_automatic_rules(
    db_path,
    target_language=None,
    automatic_rules=None,
    create_backup=True,
    backup_dir=None,
):
    if automatic_rules is None:
        automatic_rules = load_automatic_substitutions()

    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    conn = initialize_database(db_path)
    try:
        stats = apply_automatic_translation_updates(
            conn.cursor(),
            automatic_rules,
            apply_automatic_substitutions,
            target_language=target_language,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    stats["backup_path"] = backup_path
    return stats


def format_automatic_rules_scope(target_language):
    return f"idioma atual ({target_language})" if target_language else "todos os idiomas"


def _preview_line(value, limit=90):
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def format_automatic_rule_examples(examples, max_items=5):
    if not examples:
        return ""

    lines = ["Exemplos:"]
    for example in examples[:max_items]:
        lines.extend(
            [
                f"  ID {example['id']} ({example['target_language']}):",
                f"    Antes: {_preview_line(example['previous_translation'])}",
                f"    Depois: {_preview_line(example['new_translation'])}",
            ]
        )

    if len(examples) > max_items:
        lines.append(f"  ... mais {len(examples) - max_items} exemplo(s) na pre-analise.")

    return "\n".join(lines)


def apply_automatic_rules_to_database(app, target_language=None, parent=None):
    try:
        automatic_rules = load_automatic_substitutions()
        if not automatic_rules:
            messagebox.showinfo(
                "Substituicoes automaticas",
                "Nenhuma regra automatica cadastrada no glossario.",
                parent=parent,
            )
            return None

        preview = analyze_database_automatic_rules(
            app.output_db,
            target_language=target_language,
            automatic_rules=automatic_rules,
        )
        if preview["changed"] == 0:
            messagebox.showinfo(
                "Substituicoes automaticas",
                (
                    "Nenhuma traducao existente precisa ser atualizada.\n\n"
                    f"Escopo: {format_automatic_rules_scope(target_language)}\n"
                    f"Regras automaticas: {preview['rules']}\n"
                    f"Traducoes analisadas: {preview['scanned']}"
                ),
                parent=parent,
            )
            return preview

        confirmed = messagebox.askyesno(
            "Substituicoes automaticas",
            (
                "Aplicar regras automaticas nas traducoes existentes?\n\n"
                f"Escopo: {format_automatic_rules_scope(target_language)}\n"
                f"Regras automaticas: {preview['rules']}\n"
                f"Traducoes analisadas: {preview['scanned']}\n"
                f"Traducoes que serao alteradas: {preview['changed']}\n\n"
                f"{format_automatic_rule_examples(preview.get('examples', []))}\n\n"
                "Um backup do banco sera criado antes de alterar os dados."
            ),
            parent=parent,
        )
        if not confirmed:
            return None

        stats = apply_database_automatic_rules(
            app.output_db,
            target_language=target_language,
            automatic_rules=automatic_rules,
        )
        if hasattr(app, "translation_cache"):
            app.translation_cache.clear()

        messagebox.showinfo(
            "Substituicoes automaticas",
            (
                "Regras automaticas aplicadas com sucesso.\n\n"
                f"Escopo: {format_automatic_rules_scope(target_language)}\n"
                f"Regras automaticas: {stats['rules']}\n"
                f"Traducoes analisadas: {stats['scanned']}\n"
                f"Traducoes alteradas: {stats['changed']}\n"
                f"Sem alteracao: {stats['unchanged']}\n\n"
                f"Backup criado em:\n{stats['backup_path']}"
            ),
            parent=parent,
        )
        return stats
    except Exception as e:
        messagebox.showerror(
            "Erro",
            f"Erro ao aplicar substituicoes automaticas:\n{e}",
            parent=parent,
        )
        return None


def format_quality_stats(summary, indent=""):
    lines = [
        f"{indent}Com avisos QA: {summary['warning_rows']}",
        f"{indent}Pendentes com avisos QA: {summary['pending_warning_rows']}",
        f"{indent}Verificadas com avisos QA: {summary['verified_warning_rows']}",
        f"{indent}Total de avisos QA: {summary['warning_total']}",
    ]
    if summary["warning_counts"]:
        lines.append(f"{indent}Tipos de aviso:")
        for warning, count in list(summary["warning_counts"].items())[:5]:
            lines.append(f"{indent}  - {warning}: {count}")
    return "\n".join(lines)


def show_db_stats(app):
    conn = None
    try:
        conn = initialize_database(app.output_db)
        cursor = conn.cursor()
        stats = get_database_stats(cursor)
        quality_rows_by_language = {}
        all_quality_rows = []
        for lang, _count, _verified, _pending in stats["per_language"]:
            lang_rows = fetch_review_rows(cursor, lang)
            quality_rows_by_language[lang] = lang_rows
            all_quality_rows.extend(lang_rows)

        quality_summary = summarize_quality_warnings(all_quality_rows)

        msg = (
            f"Total de traducoes armazenadas: {stats['total']}\n"
            f"Verificadas: {stats['verified_total']}\n"
            f"Pendentes: {stats['pending_total']}\n\n"
            "QA geral:\n"
            f"{format_quality_stats(quality_summary, '  ')}\n\n"
            "Por idioma:\n"
        )
        for lang, count, verified, pending in stats["per_language"]:
            language_summary = summarize_quality_warnings(quality_rows_by_language[lang])
            msg += (
                f"  - {lang}: {count} | verificadas: {verified} | "
                f"pendentes: {pending} | QA: {language_summary['warning_rows']}\n"
            )

        messagebox.showinfo("Estatisticas do Banco de Dados", msg)

    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel acessar o banco de dados:\n{e}")
    finally:
        if conn is not None:
            conn.close()


def export_csv(app):
    conn = None
    try:
        save_path = filedialog.asksaveasfilename(
            title="Salvar CSV de traducoes",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")]
        )
        if not save_path:
            return

        conn = initialize_database(app.output_db)
        cursor = conn.cursor()
        rows = fetch_export_rows(cursor)

        with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                "original_comment",
                "translated_comment",
                "target_language",
                "verified",
                "created_at",
                "updated_at",
                "verified_at",
            ])
            writer.writerows(rows)

        messagebox.showinfo("Exportar CSV", f"CSV exportado com sucesso:\n{save_path}")

    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao exportar CSV:\n{e}")
    finally:
        if conn is not None:
            conn.close()


def import_csv(app):
    csv_path = filedialog.askopenfilename(
        title="Selecionar CSV de traducoes",
        filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
    )
    if not csv_path:
        return

    try:
        preview = analyze_translations_csv_import(app.output_db, csv_path)
        confirmed = messagebox.askyesno(
            "Importar CSV",
            (
                "Previa da importacao:\n\n"
                f"Linhas lidas: {preview['total_rows']}\n"
                f"Novas: {preview['inserted']}\n"
                f"Vazias a preencher: {preview['filled_empty']}\n"
                f"Sem alteracao: {preview['unchanged']}\n"
                f"Ignoradas: {preview['skipped']}\n"
                f"Verificadas a aplicar: {preview['verified_applied']}\n\n"
                "Um backup sera criado antes de alterar o banco.\n"
                "Traducoes existentes preenchidas nao serao sobrescritas.\n\n"
                "Deseja continuar?"
            ),
        )
        if not confirmed:
            return

        stats = import_translations_from_csv(app.output_db, csv_path)
        if hasattr(app, "translation_cache"):
            app.translation_cache.clear()
        messagebox.showinfo(
            "Importar CSV",
            (
                "CSV importado com sucesso.\n\n"
                f"Linhas lidas: {stats['total_rows']}\n"
                f"Novas: {stats['inserted']}\n"
                f"Vazias preenchidas: {stats['filled_empty']}\n"
                f"Sem alteracao: {stats['unchanged']}\n"
                f"Ignoradas: {stats['skipped']}\n"
                f"Verificadas aplicadas: {stats['verified_applied']}\n\n"
                f"Backup criado em:\n{stats['backup_path']}"
            ),
        )
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao importar CSV:\n{e}")


def backup_database(app):
    try:
        backup_path = create_database_backup(app.output_db)
        messagebox.showinfo(
            "Backup do Banco de Dados",
            f"Backup criado com sucesso:\n{backup_path}",
        )
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao criar backup do banco:\n{e}")


def restore_database(app):
    backup_path = filedialog.askopenfilename(
        title="Selecionar backup do banco",
        filetypes=[("Bancos SQLite", "*.db"), ("Todos os arquivos", "*.*")],
    )
    if not backup_path:
        return

    confirmed = messagebox.askyesno(
        "Restaurar Banco de Dados",
        (
            "Restaurar este backup vai substituir o banco atual.\n"
            "Um backup de seguranca sera criado antes da restauracao.\n\n"
            "Deseja continuar?"
        ),
    )
    if not confirmed:
        return

    try:
        result = restore_database_from_backup(app.output_db, backup_path)
        if hasattr(app, "translation_cache"):
            app.translation_cache.clear()
        messagebox.showinfo(
            "Restaurar Banco de Dados",
            (
                "Banco restaurado com sucesso.\n\n"
                f"Backup de seguranca criado em:\n{result['safety_backup_path']}"
            ),
        )
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao restaurar backup do banco:\n{e}")
