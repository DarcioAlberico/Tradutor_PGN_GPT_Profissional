import os
import time
from tkinter import messagebox

from .database import initialize_database, load_translation_cache, save_translation
from .glossario import (
    apply_automatic_substitutions,
    clean_comment_for_translation,
    load_automatic_substitutions,
    load_cleanup_substitutions,
)
from .pgn_utils import (
    available_output_path,
    collect_pgn_files,
    create_comment_batches,
    extract_comments_from_file,
    generate_translated_pgn,
    translated_output_path,
)
from .translation_api import translate_text


def run_translation(app, source_path, target_language, process_subdirs):
    conn = None
    canceled = False

    try:
        app.log_message(f"Iniciando traducao para idioma: {target_language}")
        app.log_message(f"Banco de dados: {app.output_db}")

        conn = initialize_database(app.output_db)
        cursor = conn.cursor()
        app.translation_cache = load_translation_cache(cursor, target_language)
        app.log_message(f"Cache carregado: {len(app.translation_cache)} traducoes")
        cleanup_rules = load_cleanup_substitutions()
        if cleanup_rules:
            app.log_message(f"Regras de limpeza carregadas: {len(cleanup_rules)}")
        automatic_rules = load_automatic_substitutions()
        if automatic_rules:
            app.log_message(f"Regras automaticas carregadas: {len(automatic_rules)}")

        pgn_files, skipped_generated = collect_pgn_files(source_path, process_subdirs)
        if skipped_generated:
            app.log_message(f"Arquivos PGN gerados anteriormente ignorados: {skipped_generated}")

        if not pgn_files:
            app.log_message("Nenhum arquivo PGN encontrado.")
            return

        info_by_file = {}
        total_comments = 0

        for pgn_file in pgn_files:
            if app.cancel_flag.is_set():
                canceled = True
                app.log_message("Traducao cancelada antes da extracao completa.")
                return

            info = extract_comments_from_file(pgn_file, app.log_message)
            info_by_file[pgn_file] = info
            total_comments += len(info["comments"])

        if total_comments == 0:
            app.log_message("Nenhum comentario encontrado nos arquivos PGN.")
            return

        app.log_message(f"Total de comentarios detectados: {total_comments}")

        processed_comments = 0
        translated_count = 0
        filled_empty_count = 0
        cache_count = 0
        cleaned_empty_count = 0
        generated_files = 0

        def update_progress():
            value = (processed_comments / total_comments) * 100 if total_comments > 0 else 0
            app.root.after(0, lambda v=value: app.progress.set(v / 100))

        for pgn_index, pgn_file in enumerate(pgn_files, start=1):
            if app.cancel_flag.is_set():
                canceled = True
                app.log_message("Traducao cancelada pelo usuario.")
                return

            app.log_message(
                f"Processando arquivo {pgn_index}/{len(pgn_files)}: {os.path.basename(pgn_file)}"
            )
            info = info_by_file[pgn_file]
            comments = info["comments"]
            positions = info["positions"]

            if not comments:
                app.log_message("  - Nenhum comentario neste arquivo.")
                continue

            batches = create_comment_batches(comments)
            translated_map = {}

            for batch_idx, batch in enumerate(batches, start=1):
                while app.pause_flag.is_set() and not app.cancel_flag.is_set():
                    time.sleep(0.2)

                if app.cancel_flag.is_set():
                    canceled = True
                    conn.commit()
                    app.log_message("Traducao cancelada pelo usuario.")
                    return

                for comment in batch:
                    while app.pause_flag.is_set() and not app.cancel_flag.is_set():
                        time.sleep(0.2)

                    if app.cancel_flag.is_set():
                        canceled = True
                        conn.commit()
                        app.log_message("Traducao cancelada pelo usuario.")
                        return

                    if comment in app.translation_cache:
                        translated_map[comment] = app.translation_cache[comment]
                        cache_count += 1
                    else:
                        cleaned_comment = clean_comment_for_translation(
                            comment,
                            cleanup_rules,
                        )
                        if not cleaned_comment:
                            translated_map[comment] = ""
                            cleaned_empty_count += 1
                            processed_comments += 1
                            update_progress()
                            continue

                        translated = translate_text(
                            cleaned_comment,
                            target_language,
                            app.log_message,
                            app.cancel_flag
                        )
                        if translated:
                            translated = apply_automatic_substitutions(
                                translated,
                                automatic_rules,
                            )
                            app.translation_cache[comment] = translated
                            translated_map[comment] = translated

                            save_status = save_translation(
                                cursor,
                                comment,
                                translated,
                                target_language
                            )

                            if save_status == "inserted":
                                translated_count += 1
                            elif save_status == "filled_empty":
                                filled_empty_count += 1

                        time.sleep(0.20)

                    processed_comments += 1
                    update_progress()

                conn.commit()
                app.log_message(
                    f"  - Lote {batch_idx}/{len(batches)} concluido. "
                    f"Novas: {translated_count} | Preenchidas: {filled_empty_count} | Cache: {cache_count}"
                )

            if translated_map:
                preferred_output_pgn = translated_output_path(pgn_file, target_language)
                output_pgn = available_output_path(preferred_output_pgn)

                if output_pgn != preferred_output_pgn:
                    app.log_message(f"  - Arquivo de saida ja existia; usando: {output_pgn}")

                if generate_translated_pgn(
                    pgn_file,
                    output_pgn,
                    translated_map,
                    positions,
                    app.log_message
                ):
                    generated_files += 1
                    app.log_message(f"  - Arquivo traduzido gerado: {output_pgn}")

        conn.commit()

        app.log_message("====== TRADUCAO FINALIZADA ======")
        app.log_message(f"Total de comentarios: {total_comments}")
        app.log_message(f"Comentarios novos traduzidos nesta execucao: {translated_count}")
        app.log_message(f"Traducoes vazias preenchidas: {filled_empty_count}")
        app.log_message(f"Comentarios removidos por limpeza: {cleaned_empty_count}")
        app.log_message(f"Traducoes reutilizadas do cache: {cache_count}")
        app.log_message(f"Arquivos PGN traduzidos gerados: {generated_files}")
        app.log_message(f"Banco de dados: {app.output_db}")

        if not canceled:
            app.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Concluido",
                    f"Traducao finalizada!\n\n"
                    f"Total de comentarios: {total_comments}\n"
                    f"Novas traducoes: {translated_count}\n"
                    f"Vazias preenchidas: {filled_empty_count}\n"
                    f"Removidos por limpeza: {cleaned_empty_count}\n"
                    f"Reutilizados do cache: {cache_count}\n"
                    f"Arquivos gerados: {generated_files}"
                )
            )

    except Exception as e:
        app.log_message(f"[ERRO GERAL] {e}")
        app.root.after(
            0,
            lambda err=str(e): messagebox.showerror(
                "Erro",
                f"Ocorreu um erro durante o processamento:\n{err}"
            )
        )

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                app.log_message(f"[ERRO] Falha ao fechar banco de dados: {e}")

        app.is_processing = False
        app.pause_flag.clear()
        app.cancel_flag.clear()
        app.root.after(0, app._reset_buttons)
