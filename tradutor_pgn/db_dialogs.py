import csv
from tkinter import filedialog, messagebox

from .database import fetch_export_rows, fetch_review_rows, get_database_stats, initialize_database
from .db_backup import create_database_backup, restore_database_from_backup
from .db_csv import analyze_translations_csv_import, import_translations_from_csv
from .review_quality import summarize_quality_warnings


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

        with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
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
