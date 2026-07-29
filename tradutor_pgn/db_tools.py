import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from .app_config import language_label
from .database import (
    analyze_automatic_translation_updates,
    apply_automatic_translation_updates,
    clear_all_translations,
    fetch_export_rows,
    fetch_review_rows,
    get_database_stats,
    initialize_database,
    save_translation,
    set_translation_verified_by_id,
)
from .backup_retention import prune_database_backups
from .background_task import TaskCanceled, run_with_progress
from .confirm_dialog import ask_typed_confirmation
from .database import AutomaticRulesCanceled
from .glossario import (
    apply_automatic_substitutions,
    create_glossary_backup,
    load_automatic_substitutions,
    save_glossary_entries,
)
from .review_quality import summarize_quality_warnings


# Paginas por passo da copia do SQLite. E o intervalo entre duas chances de
# reportar progresso ou de desistir: menor da uma barra mais fluida e mais
# chamadas de callback. 2048 paginas sao ~8 MB, que num banco de 80 MB dao ~10
# atualizacoes.
BACKUP_PAGES_PER_STEP = 2048

# Linhas por bloco na exportacao. O `csv.writerows` continua recebendo um bloco
# inteiro de uma vez — escrever linha a linha em Python custaria a economia que
# o item 2.9 conquistou.
EXPORT_CHUNK = 5000

# Linhas entre duas verificacoes de cancelamento na importacao.
IMPORT_PROGRESS_EVERY = 200


def _cancelable(work):
    """Traduz o cancelamento das funcoes de banco para o do `background_task`.

    `database.py` sinaliza desistencia com `AutomaticRulesCanceled` e nao pode
    conhecer o `background_task` — aquele modulo importa Tk, e manter o banco
    livre disso e o que permite testa-lo sem display.

    Sem esta traducao a excecao chega ao `run_with_progress` como uma falha
    qualquer, e quem clicou em "Cancelar" recebe um dialogo de ERRO dizendo que
    a operacao falhou. Era o que acontecia com "Aplicar automaticas".
    """
    def wrapper(task):
        try:
            return work(task)
        except AutomaticRulesCanceled:
            raise TaskCanceled() from None

    return wrapper


def _copy_database(source_conn, target_conn, progress_callback=None, should_cancel=None):
    """Copia um banco no outro pela API de backup online do SQLite.

    Nao e `shutil.copy` de proposito: em WAL o arquivo `.db` sozinho nao contem
    as transacoes que ainda estao no `-wal` (ver 6.2). A API de backup ve o
    banco logico e resolve isso.

    `pages=` existe para poder reportar progresso e aceitar um cancelamento no
    meio: sem ele a copia e uma unica chamada que so retorna no fim.
    """
    def passo(_status, remaining, total):
        if should_cancel is not None and should_cancel():
            raise TaskCanceled()
        if progress_callback is not None and total:
            progress_callback(total - remaining, total)

    source_conn.backup(target_conn, pages=BACKUP_PAGES_PER_STEP, progress=passo)
    target_conn.commit()


def _unique_backup_path(backup_dir, stem, timestamp):
    base_name = f"{stem}-backup-{timestamp}.db"
    backup_path = backup_dir / base_name
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{stem}-backup-{timestamp}-{suffix}.db"
        suffix += 1
    return backup_path


def create_database_backup(
    db_path,
    backup_dir=None,
    timestamp=None,
    prune=True,
    protect=(),
    progress_callback=None,
    should_cancel=None,
):
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
        _copy_database(source_conn, target_conn, progress_callback, should_cancel)
    except BaseException:
        # A copia interrompida no meio e um banco incompleto com cara de
        # backup. Apagar e obrigatorio: o proximo "Restaurar backup" ofereceria
        # este arquivo na lista como qualquer outro.
        target_conn.close()
        source_conn.close()
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        target_conn.close()
        source_conn.close()

    if prune:
        # A copia recem criada e o arquivo que o chamador ainda vai ler (numa
        # restauracao, o backup escolhido) ficam fora do alcance da limpeza.
        prune_database_backups(
            str(backup_dir),
            source_path.stem,
            protected=(str(backup_path),) + tuple(str(item) for item in protect),
        )

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


def restore_database_from_backup(
    db_path,
    backup_path,
    safety_backup_dir=None,
    progress_callback=None,
):
    """Substitui o banco atual pelo backup, com uma copia de seguranca antes.

    Nao aceita cancelamento, e a razao esta na terceira etapa: interromper a
    copia no meio deixaria o banco de trabalho como um arquivo incompleto — e
    aqui nao ha o recurso do `create_database_backup`, que simplesmente apaga o
    que escreveu pela metade. O que da para desistir e antes de comecar.
    """
    target_path = Path(db_path)
    backup_path = Path(backup_path)
    if target_path.resolve() == backup_path.resolve():
        raise ValueError("O backup selecionado e o banco atual sao o mesmo arquivo")

    # Tres etapas de peso parecido; o progresso e por etapa, e nao por pagina,
    # porque so a ultima sabe dizer quantas paginas tem.
    if progress_callback is not None:
        progress_callback(0, 3)
    validate_restore_source(backup_path)

    if progress_callback is not None:
        progress_callback(1, 3)
    safety_backup_path = create_database_backup(
        target_path,
        backup_dir=safety_backup_dir,
        protect=(backup_path,),
    )

    if progress_callback is not None:
        progress_callback(2, 3)
    source_conn = sqlite3.connect(str(backup_path))
    target_conn = sqlite3.connect(str(target_path))
    try:
        _copy_database(source_conn, target_conn)
    finally:
        target_conn.close()
        source_conn.close()

    if progress_callback is not None:
        progress_callback(3, 3)

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


def _fetch_comment_id(cursor, original_comment, target_language, source_language=""):
    row = cursor.execute(
        """
        SELECT id
        FROM comments
        WHERE original_comment = ?
          AND source_language = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, source_language, target_language),
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
    # `source_language` e OPCIONAL na leitura, pelo mesmo motivo que a coluna
    # `priority` do CSV do glossario e: um arquivo exportado por uma versao
    # anterior — ou montado numa planilha — continua importavel, e a ausencia da
    # coluna significa a mesma coisa que a coluna vazia, "origem nao informada".
    return {
        "original_comment": (row.get("original_comment") or "").strip(),
        "translated_comment": (row.get("translated_comment") or "").strip(),
        "target_language": (row.get("target_language") or "").strip(),
        "source_language": (row.get("source_language") or "").strip(),
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


def _existing_translation(cursor, original_comment, target_language, source_language=""):
    return cursor.execute(
        """
        SELECT translated_comment
        FROM comments
        WHERE original_comment = ?
          AND source_language = ?
          AND target_language = ?
        ORDER BY id
        LIMIT 1
        """,
        (original_comment, source_language, target_language),
    ).fetchone()


def _report_import_progress(stats, total, progress_callback, should_cancel):
    """Progresso e cancelamento das duas passagens do CSV, no mesmo ritmo."""
    lidas = stats["total_rows"]
    if should_cancel is not None and lidas % IMPORT_PROGRESS_EVERY == 0 and should_cancel():
        raise TaskCanceled()
    if progress_callback is not None and (
        lidas % IMPORT_PROGRESS_EVERY == 0 or lidas == total
    ):
        progress_callback(lidas, total)


def analyze_translations_csv_import(
    db_path,
    csv_path,
    csv_rows=None,
    progress_callback=None,
    should_cancel=None,
):
    """Previa da importacao. `csv_rows` evita reler o arquivo (ROADMAP 2.10)."""
    if csv_rows is None:
        csv_rows = _read_translation_csv_rows(csv_path)
    stats = _empty_import_stats()
    total = len(csv_rows)

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            _report_import_progress(stats, total, progress_callback, should_cancel)
            row = _normalize_import_row(raw_row)
            original = row["original_comment"]
            translated = row["translated_comment"]
            target_language = row["target_language"]

            if not original or not translated or not target_language:
                stats["skipped"] += 1
                continue

            existing = _existing_translation(
                cursor, original, target_language, row["source_language"]
            )
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
    csv_rows=None,
    progress_callback=None,
    should_cancel=None,
):
    """Aplica a importacao. `csv_rows` evita reler o arquivo (ROADMAP 2.10).

    Reaproveitar as linhas da previa nao e so economia: e o que garante que o
    usuario confirmou exatamente o que sera gravado. Lendo duas vezes, um arquivo
    alterado entre a previa e o "Sim" aplicaria numeros diferentes dos exibidos.

    Cancelar faz `rollback`: o banco fica como estava, e nao com metade das
    linhas do CSV aplicadas. O backup criado antes da importacao permanece —
    e uma copia valida, e apaga-lo seria destruir o unico registro de que a
    operacao chegou a comecar.
    """
    if csv_rows is None:
        csv_rows = _read_translation_csv_rows(csv_path)

    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    stats = _empty_import_stats(backup_path)
    total = len(csv_rows)

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        for raw_row in csv_rows:
            stats["total_rows"] += 1
            _report_import_progress(stats, total, progress_callback, should_cancel)
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
                row["source_language"],
            )
            if save_status == "inserted":
                stats["inserted"] += 1
            elif save_status == "filled_empty":
                stats["filled_empty"] += 1
            else:
                stats["unchanged"] += 1

            if save_status in {"inserted", "filled_empty"} and row["verified"]:
                comment_id = _fetch_comment_id(
                    cursor, original, target_language, row["source_language"]
                )
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


EXPORT_CSV_HEADERS = [
    "original_comment",
    "translated_comment",
    # Entre a traducao e o destino, na mesma ordem em que `fetch_export_rows`
    # devolve as colunas: a exportacao escreve o cursor direto no `writerows`,
    # entao cabecalho e SELECT precisam concordar posicao a posicao.
    "source_language",
    "target_language",
    "verified",
    "created_at",
    "updated_at",
    "verified_at",
]


def export_translations_to_csv(
    db_path,
    save_path,
    progress_callback=None,
    should_cancel=None,
):
    """Escreve o CSV de traducoes. Devolve quantas linhas sairam.

    Estava embutida no callback do botao, entao exportar as 195.607 linhas
    congelava a janela por ~1,1 s sem nenhum sinal de vida. Extraida, ela roda
    na thread de trabalho e nao conhece widget nenhum.

    A leitura continua em blocos e o `csv.writerows` continua recebendo o bloco
    inteiro (ROADMAP 2.9): trocar por um laco Python linha a linha para ter onde
    checar o cancelamento devolveria o custo que aquele item tirou. O bloco e o
    lugar de checar.
    """
    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        if progress_callback is not None:
            progress_callback(0, total)

        escritas = 0
        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(EXPORT_CSV_HEADERS)

                rows = fetch_export_rows(cursor)
                while True:
                    if should_cancel is not None and should_cancel():
                        raise TaskCanceled()
                    bloco = rows.fetchmany(EXPORT_CHUNK)
                    if not bloco:
                        break
                    writer.writerows(bloco)
                    escritas += len(bloco)
                    if progress_callback is not None:
                        progress_callback(escritas, total)
        except BaseException:
            # Um CSV cortado no meio nao se distingue de um completo: ele abre,
            # tem cabecalho e linhas validas. Deixa-lo em disco depois de um
            # "Cancelar" seria oferecer um arquivo que mente sobre o que tem.
            Path(save_path).unlink(missing_ok=True)
            raise
    finally:
        conn.close()

    return escritas


def analyze_database_automatic_rules(
    db_path,
    target_language=None,
    automatic_rules=None,
    progress_callback=None,
    should_cancel=None,
    source_language=None,
):
    if automatic_rules is None:
        automatic_rules = load_automatic_substitutions()

    conn = initialize_database(db_path)
    try:
        return analyze_automatic_translation_updates(
            conn.cursor(),
            automatic_rules,
            apply_automatic_substitutions,
            target_language=target_language,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            source_language=source_language,
        )
    finally:
        conn.close()


def apply_database_automatic_rules(
    db_path,
    target_language=None,
    automatic_rules=None,
    create_backup=True,
    backup_dir=None,
    progress_callback=None,
    should_cancel=None,
    source_language=None,
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
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            source_language=source_language,
        )
        conn.commit()
    except Exception:
        # Vale tambem para o cancelamento: `AutomaticRulesCanceled` sobe por aqui
        # e o rollback desfaz o que ja tinha sido alterado. Cancelar deixa o
        # banco como estava, nao pela metade.
        conn.rollback()
        raise
    finally:
        conn.close()

    stats["backup_path"] = backup_path
    return stats


def format_automatic_rules_scope(target_language, source_language=None):
    """O escopo, em texto, para o dialogo de confirmacao.

    Nomeia a ORIGEM tambem quando ha filtro dela: confirmar "vou alterar 12.000
    traducoes do idioma pt" enquanto a janela mostra so as vindas do espanhol
    daria um numero que nao bate com nada na tela.
    """
    destino = f"idioma atual ({target_language})" if target_language else "todos os idiomas"
    if source_language is None:
        return destino
    return f"{destino}, origem {language_label(source_language)}"


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


def _format_automatic_preview(target_language, preview, source_language=None):
    return (
        "Aplicar regras automaticas nas traducoes existentes?\n\n"
        f"Escopo: {format_automatic_rules_scope(target_language, source_language)}\n"
        f"Regras automaticas: {preview['rules']}\n"
        f"Traducoes analisadas: {preview['scanned']}\n"
        f"Traducoes que serao alteradas: {preview['changed']}\n\n"
        f"{format_automatic_rule_examples(preview.get('examples', []))}\n\n"
        "Um backup do banco sera criado antes de alterar os dados."
    )


def _format_automatic_result(target_language, stats, source_language=None):
    return (
        "Regras automaticas aplicadas com sucesso.\n\n"
        f"Escopo: {format_automatic_rules_scope(target_language, source_language)}\n"
        f"Regras automaticas: {stats['rules']}\n"
        f"Traducoes analisadas: {stats['scanned']}\n"
        f"Traducoes alteradas: {stats['changed']}\n"
        f"Sem alteracao: {stats['unchanged']}\n\n"
        f"Backup criado em:\n{stats['backup_path']}"
    )


def apply_automatic_rules_to_database(
    app,
    target_language=None,
    parent=None,
    on_finish=None,
    source_language=None,
):
    """Aplica as regras automaticas, com previa, backup e confirmacao.

    As duas varreduras (previa e escrita) rodam FORA da thread do Tk, cada uma
    com barra de progresso e cancelamento: sao 38 s de janela travada no banco
    real, sem nenhum sinal de vida, se rodarem no proprio callback do botao.

    Isso obriga o resultado a chegar por callback. `on_finish(stats)` e chamado
    na thread principal quando tudo termina — com `None` se o usuario cancelou,
    se nao havia regras ou se nada mudou. Quem chama sem `on_finish` (a janela
    principal) so quer disparar a operacao e nao precisa do resultado.
    """
    janela = parent if parent is not None else app.root

    def falhou(erro):
        messagebox.showerror(
            "Erro",
            f"Erro ao aplicar substituicoes automaticas:\n{erro}",
            parent=parent,
        )
        if on_finish is not None:
            on_finish(None)

    def cancelado(_valor=None):
        messagebox.showinfo(
            "Substituicoes automaticas",
            "Operacao cancelada. Nenhuma traducao foi alterada.",
            parent=parent,
        )
        if on_finish is not None:
            on_finish(None)

    try:
        automatic_rules = load_automatic_substitutions()
    except Exception as exc:
        falhou(exc)
        return None

    if not automatic_rules:
        messagebox.showinfo(
            "Substituicoes automaticas",
            "Nenhuma regra automatica cadastrada no glossario.",
            parent=parent,
        )
        if on_finish is not None:
            on_finish(None)
        return None

    def aplicar(preview):
        def trabalho(task):
            return apply_database_automatic_rules(
                app.output_db,
                target_language=target_language,
                automatic_rules=automatic_rules,
                progress_callback=task.report,
                should_cancel=task.cancelado,
                source_language=source_language,
            )

        def aplicado(stats):
            if hasattr(app, "translation_cache"):
                app.translation_cache.clear()
            messagebox.showinfo(
                "Substituicoes automaticas",
                _format_automatic_result(target_language, stats, source_language),
                parent=parent,
            )
            if on_finish is not None:
                on_finish(stats)

        run_with_progress(
            janela,
            "Aplicando regras automaticas",
            _cancelable(trabalho),
            on_success=aplicado,
            on_error=falhou,
            on_cancel=cancelado,
            message=(
                f"Aplicando {preview['rules']} regra(s) em "
                f"{preview['changed']} traducao(oes)..."
            ),
        )

    def analisado(preview):
        if preview["changed"] == 0:
            messagebox.showinfo(
                "Substituicoes automaticas",
                (
                    "Nenhuma traducao existente precisa ser atualizada.\n\n"
                    f"Escopo: {format_automatic_rules_scope(target_language, source_language)}\n"
                    f"Regras automaticas: {preview['rules']}\n"
                    f"Traducoes analisadas: {preview['scanned']}"
                ),
                parent=parent,
            )
            if on_finish is not None:
                on_finish(preview)
            return

        if not messagebox.askyesno(
            "Substituicoes automaticas",
            _format_automatic_preview(target_language, preview, source_language),
            parent=parent,
        ):
            if on_finish is not None:
                on_finish(None)
            return

        aplicar(preview)

    def analisar(task):
        return analyze_database_automatic_rules(
            app.output_db,
            target_language=target_language,
            automatic_rules=automatic_rules,
            progress_callback=task.report,
            should_cancel=task.cancelado,
            source_language=source_language,
        )

    run_with_progress(
        janela,
        "Substituicoes automaticas",
        _cancelable(analisar),
        on_success=analisado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Analisando as traducoes existentes...",
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
        for source, target, _count, _verified, _pending in stats["per_language"]:
            # Só as linhas marcadas com aviso: o resumo exibido conta apenas
            # essas, entao carregar a tabela inteira era desperdicio puro
            # (~2 s de interface congelada e ~100 MB em 195 mil linhas).
            lang_rows = fetch_review_rows(
                cursor, target, status_filter="warnings", source_language=source
            )
            quality_rows_by_language[(source, target)] = lang_rows
            all_quality_rows.extend(lang_rows)

        quality_summary = summarize_quality_warnings(all_quality_rows)

        msg = (
            f"Total de traducoes armazenadas: {stats['total']}\n"
            f"Verificadas: {stats['verified_total']}\n"
            f"Pendentes: {stats['pending_total']}\n\n"
            "QA geral:\n"
            f"{format_quality_stats(quality_summary, '  ')}\n\n"
            "Por par de idiomas (origem -> destino):\n"
        )
        for source, target, count, verified, pending in stats["per_language"]:
            language_summary = summarize_quality_warnings(
                quality_rows_by_language[(source, target)]
            )
            par = f"{language_label(source)} -> {target}"
            msg += (
                f"  - {par}: {count} | verificadas: {verified} | "
                f"pendentes: {pending} | QA: {language_summary['warning_rows']}\n"
            )

        messagebox.showinfo("Estatisticas do Banco de Dados", msg)

    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel acessar o banco de dados:\n{e}")
    finally:
        if conn is not None:
            conn.close()


def _database_task_callbacks(app, titulo, erro_prefixo, on_finish=None):
    """Os tres desfechos de uma operacao de banco, iguais para as quatro.

    `on_finish(resultado)` existe pelo mesmo motivo do
    `apply_automatic_rules_to_database`: a operacao virou assincrona, entao quem
    precisa do resultado nao pode mais receber um `return`. Recebe `None`
    quando deu errado ou o usuario desistiu.
    """
    def falhou(erro):
        messagebox.showerror("Erro", f"{erro_prefixo}\n{erro}")
        if on_finish is not None:
            on_finish(None)

    def cancelado(_valor=None):
        messagebox.showinfo(titulo, "Operacao cancelada.")
        if on_finish is not None:
            on_finish(None)

    return falhou, cancelado


def export_csv(app, on_finish=None):
    save_path = filedialog.asksaveasfilename(
        title="Salvar CSV de traducoes",
        defaultextension=".csv",
        filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
    )
    if not save_path:
        return

    falhou, cancelado = _database_task_callbacks(
        app, "Exportar CSV", "Erro ao exportar CSV:", on_finish
    )

    def trabalho(task):
        return export_translations_to_csv(
            app.output_db,
            save_path,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    def exportado(linhas):
        messagebox.showinfo(
            "Exportar CSV",
            f"CSV exportado com sucesso ({linhas} linhas):\n{save_path}",
        )
        if on_finish is not None:
            on_finish(linhas)

    run_with_progress(
        app.root,
        "Exportar CSV",
        trabalho,
        on_success=exportado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Escrevendo as traducoes no arquivo...",
    )


def import_csv(app, on_finish=None):
    csv_path = filedialog.askopenfilename(
        title="Selecionar CSV de traducoes",
        filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
    )
    if not csv_path:
        return

    falhou, cancelado = _database_task_callbacks(
        app, "Importar CSV", "Erro ao importar CSV:", on_finish
    )

    try:
        # Lido uma vez so: a previa e a aplicacao trabalham sobre as MESMAS
        # linhas, entao o que o usuario confirma e o que e gravado (ROADMAP 2.10).
        # Fica aqui, e nao na thread, porque e o unico passo barato — o custo do
        # CSV esta nas duas varreduras do banco, nao em ler o arquivo.
        csv_rows = _read_translation_csv_rows(csv_path)
    except Exception as exc:
        falhou(exc)
        return

    def aplicar():
        def trabalho(task):
            return import_translations_from_csv(
                app.output_db,
                csv_path,
                csv_rows=csv_rows,
                progress_callback=task.report,
                should_cancel=task.cancelado,
            )

        def importado(stats):
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
            if on_finish is not None:
                on_finish(stats)

        run_with_progress(
            app.root,
            "Importar CSV",
            trabalho,
            on_success=importado,
            on_error=falhou,
            on_cancel=cancelado,
            message=f"Gravando {len(csv_rows)} linha(s) no banco...",
        )

    def analisado(preview):
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
            if on_finish is not None:
                on_finish(None)
            return
        aplicar()

    def analisar(task):
        return analyze_translations_csv_import(
            app.output_db,
            csv_path,
            csv_rows=csv_rows,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    run_with_progress(
        app.root,
        "Importar CSV",
        analisar,
        on_success=analisado,
        on_error=falhou,
        on_cancel=cancelado,
        message=f"Conferindo {len(csv_rows)} linha(s) do arquivo...",
    )


def backup_database(app, on_finish=None):
    falhou, cancelado = _database_task_callbacks(
        app, "Backup do Banco de Dados", "Erro ao criar backup do banco:", on_finish
    )

    def trabalho(task):
        return create_database_backup(
            app.output_db,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    def pronto(backup_path):
        messagebox.showinfo(
            "Backup do Banco de Dados",
            f"Backup criado com sucesso:\n{backup_path}",
        )
        if on_finish is not None:
            on_finish(backup_path)

    run_with_progress(
        app.root,
        "Backup do Banco de Dados",
        trabalho,
        on_success=pronto,
        on_error=falhou,
        on_cancel=cancelado,
        message="Copiando o banco...",
    )


def restore_database(app, on_finish=None):
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
            "A restauracao nao pode ser interrompida no meio.\n\n"
            "Deseja continuar?"
        ),
    )
    if not confirmed:
        return

    falhou, _cancelado = _database_task_callbacks(
        app,
        "Restaurar Banco de Dados",
        "Erro ao restaurar backup do banco:",
        on_finish,
    )

    def trabalho(task):
        return restore_database_from_backup(
            app.output_db, backup_path, progress_callback=task.report
        )

    def restaurado(result):
        if hasattr(app, "translation_cache"):
            app.translation_cache.clear()
        messagebox.showinfo(
            "Restaurar Banco de Dados",
            (
                "Banco restaurado com sucesso.\n\n"
                f"Backup de seguranca criado em:\n{result['safety_backup_path']}"
            ),
        )
        if on_finish is not None:
            on_finish(result)

    # `allow_cancel=False`: ver `restore_database_from_backup`. Oferecer o botao
    # e ignora-lo seria pior do que nao oferecer — o usuario clicaria achando
    # que parou, e a copia seguiria substituindo o banco de trabalho.
    run_with_progress(
        app.root,
        "Restaurar Banco de Dados",
        trabalho,
        on_success=restaurado,
        on_error=falhou,
        message="Restaurando o banco (nao interrompa)...",
        allow_cancel=False,
    )

def _count_translations(db_path):
    """Quantas linhas o banco tem hoje, para a pergunta dizer o que sera perdido."""
    conn = None
    try:
        conn = initialize_database(db_path)
        return conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()


def reset_translations(app, on_finish=None):
    """Zera o banco de traducoes, apos backup e confirmacao digitada.

    **O backup vem antes de perguntar, e nao depois de confirmar.** Custa 0,4 s
    no banco real e e a unica forma de desfazer isto — deixa-lo para depois do
    "Apagar" significaria que uma falha entre a confirmacao e a copia apaga tudo
    sem rede. Feito antes, o pior caso e uma copia a mais em `backups/` para quem
    desistiu, e a retencao (garantia S8) cuida dela.

    Sem cancelamento no meio (`allow_cancel=False`), pela mesma razao da
    restauracao: depois do `DROP TABLE` nao ha estado anterior para voltar, e um
    botao que nao pode ser honrado e pior do que nenhum botao. A hora de desistir
    e o dialogo.
    """
    total = _count_translations(app.output_db)
    if total == 0:
        messagebox.showinfo("Zerar Traduções", "O banco de traduções já está vazio.")
        return

    quantas = "um numero desconhecido de" if total is None else f"{total:,}".replace(",", ".")
    falhou, _cancelado = _database_task_callbacks(
        app, "Zerar Traduções", "Erro ao zerar o banco de traducoes:", on_finish
    )

    try:
        backup_path = create_database_backup(app.output_db)
    except Exception as exc:
        falhou(exc)
        return

    confirmado = ask_typed_confirmation(
        app.root,
        "Zerar Traduções",
        (
            f"Isto apaga {quantas} tradução(ões) e todo o histórico de edições.\n\n"
            "O glossário não é afetado.\n\n"
            "Um backup acabou de ser criado em:\n"
            f"{backup_path}\n\n"
            "É por ele que dá para voltar atrás — depois de apagar, não há outro caminho."
        ),
    )
    if not confirmado:
        app.log_message(
            f"Zerar traducoes cancelado. O backup criado ficou em: {backup_path}"
        )
        if on_finish is not None:
            on_finish(None)
        return

    def trabalho(task):
        task.report(0, 1)
        conn = initialize_database(app.output_db)
        try:
            apagadas = clear_all_translations(conn)
        finally:
            conn.close()
        task.report(1, 1)
        return apagadas

    def pronto(apagadas):
        if hasattr(app, "translation_cache"):
            # O cache em memoria tem precedencia sobre o banco: deixado como
            # estava, a proxima traducao reaproveitaria exatamente o que o
            # usuario acabou de mandar apagar.
            app.translation_cache.clear()
        app.log_message(
            f"Banco de traducoes zerado: {apagadas} linha(s) removidas. "
            f"Backup em: {backup_path}"
        )
        messagebox.showinfo(
            "Zerar Traduções",
            (
                f"Banco de traduções zerado ({apagadas} linha(s) removidas).\n\n"
                f"O backup anterior está em:\n{backup_path}"
            ),
        )
        if on_finish is not None:
            on_finish(apagadas)

    run_with_progress(
        app.root,
        "Zerar Traduções",
        trabalho,
        on_success=pronto,
        on_error=falhou,
        message="Apagando as traducoes (nao interrompa)...",
        allow_cancel=False,
    )


def reset_glossary(app, on_finish=None):
    """Zera o glossario: `Substituicoes.txt` vazio e `glossario.db` reconstruido.

    Sincrono, ao contrario de zerar as traducoes, e a diferenca e de escala e nao
    de estilo: gravar uma lista vazia num arquivo de 334 KB e reconstruir um
    indice sem nenhuma regra custa milissegundos. Uma barra de progresso para
    isso seria um piscar de janela.

    O backup sai de `save_glossary_entries`, que ja o faz em toda gravacao
    (garantia S8) — nao ha um caminho especial aqui, e e melhor assim: zerar usa
    exatamente a mesma escrita atomica que salvar uma regra usa.
    """
    total = len(app.glossary_substitutions or [])

    backup_path = None
    try:
        backup_path = create_glossary_backup()
    except Exception as exc:
        messagebox.showerror("Erro", f"Erro ao criar backup do glossario:\n{exc}")
        if on_finish is not None:
            on_finish(None)
        return

    confirmado = ask_typed_confirmation(
        app.root,
        "Zerar Glossário",
        (
            f"Isto apaga as {total} regras do glossário: substituições, limpezas "
            "e automáticas.\n\n"
            "O banco de traduções não é afetado.\n\n"
            + (
                f"Um backup acabou de ser criado em:\n{backup_path}\n\n"
                "É por ele que dá para voltar atrás — depois de apagar, não há outro caminho."
                if backup_path
                else "ATENÇÃO: não havia arquivo de glossário para copiar antes."
            )
        ),
    )
    if not confirmado:
        if backup_path:
            app.log_message(
                f"Zerar glossario cancelado. O backup criado ficou em: {backup_path}"
            )
        if on_finish is not None:
            on_finish(None)
        return

    try:
        # `create_backup=False`: a copia acima ja foi feita, antes de perguntar.
        # Fazer outra aqui deixaria duas copias identicas na pasta e faria a
        # retencao descartar uma versao mais antiga de verdade para caber.
        save_glossary_entries([], create_backup=False)
    except Exception as exc:
        messagebox.showerror("Erro", f"Erro ao zerar o glossario:\n{exc}")
        if on_finish is not None:
            on_finish(None)
        return

    app.glossary_substitutions = []
    # As janelas abertas recarregam sozinhas: o editor de traducoes ainda mostra
    # as sugestoes das regras que acabaram de deixar de existir, e a lista do
    # editor de glossario ainda mostra as regras.
    for callback in list(getattr(app, "glossary_change_callbacks", [])):
        try:
            callback([])
        except Exception:  # pragma: no cover - defensivo
            pass

    app.log_message(f"Glossario zerado: {total} regra(s) removidas. Backup em: {backup_path}")
    messagebox.showinfo(
        "Zerar Glossário",
        (
            f"Glossário zerado ({total} regra(s) removidas).\n\n"
            f"O backup anterior está em:\n{backup_path}"
        ),
    )
    if on_finish is not None:
        on_finish(total)
