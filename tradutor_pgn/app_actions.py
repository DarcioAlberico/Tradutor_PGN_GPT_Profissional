from datetime import datetime
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from .backup_retention import (
    prune_database_backups,
    prune_glossary_backups,
    prune_log_files,
)
from .db_tools import backup_database as backup_database_file
from .db_tools import apply_automatic_rules_to_database as apply_auto_rules_to_database
from .db_tools import export_csv as export_translations_csv
from .db_tools import import_csv as import_translations_csv
from .db_tools import fix_move_notation_in_database
from .db_tools import reset_glossary as reset_glossary_file
from .db_tools import reset_translations as reset_translations_database
from .db_tools import restore_database as restore_database_file
from .db_tools import show_db_stats as show_database_stats
from .edit_window import open_translation_editor
from .failed_runs import (
    clear_failed_run,
    describe_failed_run,
    load_failed_run,
    split_existing_files,
)
from .glossario import load_interactive_substitutions, report_glossary_error
from .glossary_editor import open_glossary_editor
from .pgn_spellcheck import normalize_pgn_metadata_path
from .translation_worker import run_translation


def report_glossary_failure(app, message):
    """Handler do canal de erro do glossario: leva a falha para a interface.

    Garantia S5. Pode ser chamado da thread do worker (que carrega as regras de
    limpeza e automaticas), entao o `messagebox` vai por `root.after` — nenhum
    widget e tocado fora da thread do Tk (garantia C1).

    A mesma mensagem so abre o dialogo uma vez; as repeticoes ficam no log. Uma
    falha de carga se repete a cada recarregamento, e um modal por lote
    interromperia a traducao do inicio ao fim.
    """
    app.log_message(f"[GLOSSARIO] {message}")

    if getattr(app, "_glossary_error_shown", None) == message:
        return
    app._glossary_error_shown = message

    app.root.after(0, lambda texto=message: messagebox.showerror("Glossário", texto))


def load_interactive_glossary(app):
    """Carrega o glossario da janela principal sem derrubar a inicializacao.

    `load_interactive_substitutions` propaga o erro de parse. Chamada na
    construcao da janela, isso fazia o programa simplesmente nao abrir — e, com
    `pythonw`, sem nenhuma mensagem. Degradar para "sem sugestoes" e
    recuperavel; o motivo vai para a interface pelo canal do glossario.
    """
    try:
        return load_interactive_substitutions()
    except Exception as exc:
        report_glossary_error(
            f"Erro ao carregar o glossário: {exc}\n"
            "As sugestões não estarão disponíveis até o arquivo ser corrigido."
        )
        return []


def prune_generated_files(base_dir):
    """Aplica a retencao de `backups/` e `logs/`. Devolve o que foi removido.

    Funcao pura o bastante para ser testada com um diretorio temporario: nao
    toca em widget nem depende do app.

    Existe porque a retencao (garantia S8) so era avaliada como efeito de criar
    um backup novo. Quem parasse de editar o glossario ficava com a pilha
    inteira para sempre — a pasta media 663 arquivos e 228 MB quando isto foi
    escrito, dois dias depois de a politica existir. O acoplamento original
    tambem tinha razao de ser (a limpeza so acontece quando ja ha copia nova,
    entao nunca esvazia a pasta), entao esta chamada e ADICIONAL, e nao um
    substituto.
    """
    backup_dir = os.path.join(base_dir, "backups")
    log_dir = os.path.join(base_dir, "logs")

    removidos = {"glossario": [], "banco": [], "logs": []}
    removidos["glossario"] = prune_glossary_backups(backup_dir, "Substituicoes")
    removidos["banco"] = prune_database_backups(backup_dir, "traducoes")
    removidos["logs"] = prune_log_files(log_dir)
    return removidos


def run_startup_cleanup(app):
    """Roda a retencao na abertura, numa thread, sem incomodar o usuario.

    Numa pasta com anos de uso isto apaga centenas de arquivos, e nada disso
    interessa a quem esta abrindo o programa: o resultado vai so para o log da
    janela. Falhar aqui nao pode impedir o programa de abrir — a limpeza e
    conveniencia, nao funcionalidade.
    """
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    def worker():
        try:
            removidos = prune_generated_files(base_dir)
        except Exception as exc:  # pragma: no cover - defensivo
            app.log_queue.put(f"[LIMPEZA] Falhou: {exc}")
            return

        total = sum(len(lista) for lista in removidos.values())
        if not total:
            return
        app.log_queue.put(
            f"Limpeza automatica: {len(removidos['glossario'])} backup(s) do "
            f"glossario, {len(removidos['banco'])} do banco e "
            f"{len(removidos['logs'])} log(s) antigos removidos."
        )

    threading.Thread(target=worker, daemon=True).start()


def select_file(app):
    file_path = filedialog.askopenfilename(
        title="Selecione um arquivo PGN",
        filetypes=[("Arquivos PGN", "*.pgn"), ("Todos os arquivos", "*.*")],
    )
    if file_path:
        app.source_path.set(file_path)


def select_directory(app):
    dir_path = filedialog.askdirectory(title="Selecione uma pasta com arquivos PGN")
    if dir_path:
        app.source_path.set(dir_path)


def log_message(app, message: str):
    app.log_queue.put(message)
    log_handle = getattr(app, "_log_file_handle", None)
    if log_handle is not None:
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_handle.write(f"[{timestamp}] {message}\n")
            log_handle.flush()
        except OSError:
            pass


def update_log(app):
    try:
        while not app.log_queue.empty():
            try:
                msg = app.log_queue.get_nowait()
            except queue.Empty:
                break
            try:
                app.log_text.configure(state="normal")
                app.log_text.insert(tk.END, msg + "\n")
                app.log_text.see(tk.END)
                app.log_text.configure(state="disabled")
            except Exception:
                pass
    except Exception:
        pass
    finally:
        app.root.after(100, app.update_log)


def start_translation(app):
    if app.is_processing:
        return

    source_path = app.source_path.get().strip()
    if not source_path:
        messagebox.showerror("Erro", "Selecione um arquivo ou pasta PGN.")
        return

    if not os.path.exists(source_path):
        messagebox.showerror("Erro", "O caminho informado não existe.")
        return

    _begin_translation_run(app)

    target_language = app.target_language.get()
    process_subdirs = app.process_subdirs.get()

    threading.Thread(
        target=run_translation,
        args=(app, source_path, target_language, process_subdirs),
        kwargs={"source_language": app.source_language.get()},
        daemon=True,
    ).start()


def _begin_translation_run(app):
    """Preparo comum das duas formas de iniciar: log limpo, arquivo, botoes.

    Extraido para que "Reprocessar falhas" nao tenha uma copia disso. Esquecer um
    passo aqui — o `cancel_flag`, por exemplo — daria uma execucao que ja comeca
    querendo parar.
    """
    app.log_text.configure(state="normal")
    app.log_text.delete("1.0", tk.END)
    app.log_text.configure(state="disabled")

    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    log_dir = os.path.join(script_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    # Mesmo formato de carimbo dos backups (`AAAAMMDD-HHMMSS`), para que
    # `prune_log_files` reconheca o arquivo. Os logs antigos, com underscore,
    # nao casam com o padrao e por isso nunca sao removidos.
    log_filename = f"traducao-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    log_path = os.path.join(log_dir, log_filename)
    try:
        app._log_file_handle = open(log_path, "w", encoding="utf-8")
        app._log_file_path = log_path
    except OSError:
        app._log_file_handle = None
        app._log_file_path = None

    app.is_processing = True
    app.start_button.configure(state="disabled")
    app.pause_button.configure(state="normal")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="normal")
    app.progress.set(0)
    app.pause_flag.clear()
    app.cancel_flag.clear()


def retry_failed_translation(app):
    """Reprocessa apenas os arquivos que ficaram devendo (ROADMAP 7.3).

    Usa o idioma da execucao que falhou, e nao o selecionado agora: a lista foi
    montada traduzindo para aquele idioma, e reaproveita-la com outro produziria
    um arquivo misturado sem que ninguem tivesse pedido.
    """
    if app.is_processing:
        return

    record = load_failed_run()
    if record is None:
        messagebox.showinfo(
            "Reprocessar falhas",
            "Nenhuma execucao recente deixou comentarios sem traduzir.",
        )
        return

    presentes, _ausentes = split_existing_files(record["files"])
    if not presentes:
        if messagebox.askyesno(
            "Reprocessar falhas",
            describe_failed_run(record) + "\n\nRemover a lista?",
        ):
            clear_failed_run()
        return

    if not messagebox.askyesno(
        "Reprocessar falhas",
        describe_failed_run(record) + "\n\nReprocessar agora?",
    ):
        return

    idioma = record["target_language"]
    if idioma != app.target_language.get():
        app.target_language.set(idioma)
        app.log_message(f"Idioma ajustado para o da execucao com falhas: {idioma}")

    # O PAR inteiro vem do registro, e nao so o destino. Reprocessar declarando
    # outra origem gravaria as traducoes que faltam numa gaveta diferente da dos
    # comentarios que ja deram certo — o arquivo sairia dividido entre dois pares.
    origem = record["source_language"]
    if origem != app.source_language.get():
        app.source_language.set(origem)
        app.log_message(
            f"Idioma de origem ajustado para o da execucao com falhas: "
            f"{origem or 'detectar'}"
        )

    _begin_translation_run(app)
    threading.Thread(
        target=run_translation,
        args=(app, presentes[0], idioma, False),
        kwargs={"only_files": presentes, "source_language": origem},
        daemon=True,
    ).start()


def pause_translation(app):
    if app.is_processing and not app.pause_flag.is_set():
        app.pause_flag.set()
        app.pause_button.configure(state="disabled")
        app.resume_button.configure(state="normal")
        app.log_message("Pausa solicitada…")


def resume_translation(app):
    if app.is_processing and app.pause_flag.is_set():
        app.pause_flag.clear()
        app.pause_button.configure(state="normal")
        app.resume_button.configure(state="disabled")
        app.log_message("Continuação solicitada…")


def cancel_translation(app):
    if app.is_processing:
        app.cancel_flag.set()
        app.pause_flag.clear()
        app.pause_button.configure(state="disabled")
        app.resume_button.configure(state="disabled")
        app.cancel_button.configure(state="disabled")
        app.log_message("Cancelamento solicitado…")


def reset_buttons(app):
    app.start_button.configure(state="normal")
    app.pause_button.configure(state="disabled")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="disabled")
    log_handle = getattr(app, "_log_file_handle", None)
    if log_handle is not None:
        log_path = getattr(app, "_log_file_path", None)
        try:
            log_handle.close()
        except OSError:
            pass
        app._log_file_handle = None
        if log_path:
            app.log_queue.put(f"Log salvo em: {log_path}")


def show_db_stats(app):
    show_database_stats(app)


def export_csv(app):
    export_translations_csv(app)


def import_csv(app):
    import_translations_csv(app)


def backup_database(app):
    backup_database_file(app)


def restore_database(app):
    restore_database_file(app)


def apply_automatic_rules(app):
    apply_auto_rules_to_database(app, target_language=app.target_language.get())


def fix_move_notation(app):
    """Corrige os lances das traducoes ja gravadas do par selecionado.

    O par sai dos MESMOS seletores que dizem em que idioma estao os PGN. Nao ha
    dialogo proprio para escolher idioma porque nao ha uma segunda pergunta a
    fazer: "de que idioma vieram estas traducoes" e exatamente o que aqueles
    controles significam em todo o resto do programa.
    """
    if app.is_processing:
        messagebox.showinfo(
            "Corrigir Lances",
            "Há uma tradução em andamento. Aguarde ou cancele antes de corrigir "
            "as traduções já gravadas.",
        )
        return
    fix_move_notation_in_database(
        app,
        app.source_language.get(),
        app.target_language.get(),
    )


def reset_translations(app):
    if app.is_processing:
        messagebox.showinfo(
            "Zerar Traduções",
            "Há uma tradução em andamento. Aguarde ou cancele antes de zerar o banco.",
        )
        return
    reset_translations_database(app)


def reset_glossary(app):
    if app.is_processing:
        messagebox.showinfo(
            "Zerar Glossário",
            "Há uma tradução em andamento, e ela usa o glossário. Aguarde ou "
            "cancele antes de zerá-lo.",
        )
        return
    reset_glossary_file(app)


def _finish_metadata_normalization(app, summary=None, error=None):
    app.is_processing = False
    reset_buttons(app)
    if error:
        messagebox.showerror("Normalizar PGN", f"Erro ao normalizar PGN:\n{error}")
        app.log_message(f"[ERRO] Normalizacao PGN falhou: {error}")
        return

    app.progress.set(1)
    app.log_message(
        "Normalizacao PGN concluida: "
        f"{summary['changed_files']} arquivo(s) alterado(s), "
        f"{summary['unchanged_files']} sem alteracao, "
        f"{summary['changes']} correcao(oes)."
    )
    if summary["skipped_normalized"]:
        app.log_message(
            f"Arquivos -NORM.pgn ignorados: {summary['skipped_normalized']}"
        )
    messagebox.showinfo(
        "Normalizar PGN",
        (
            "Normalizacao concluida.\n\n"
            f"Arquivos analisados: {summary['files']}\n"
            f"Arquivos alterados: {summary['changed_files']}\n"
            f"Sem alteracao: {summary['unchanged_files']}\n"
            f"Correcoes aplicadas: {summary['changes']}"
        ),
    )


def normalize_pgn_metadata(app):
    if app.is_processing:
        return

    source_path = app.source_path.get().strip()
    if not source_path:
        messagebox.showerror("Erro", "Selecione um arquivo ou pasta PGN.")
        return

    if not os.path.exists(source_path):
        messagebox.showerror("Erro", "O caminho informado nao existe.")
        return

    confirmed = messagebox.askyesno(
        "Normalizar PGN",
        (
            "Corrigir metadados PGN usando spelling_ssp/spelling.ssp?\n\n"
            "Apenas tags White, Black, Site, Event e Round serao alteradas.\n"
            "Comentarios, lances e variacoes nao serao modificados.\n"
            "Os arquivos de saida serao criados com sufixo -NORM.pgn."
        ),
    )
    if not confirmed:
        return

    app.log_text.configure(state="normal")
    app.log_text.delete("1.0", tk.END)
    app.log_text.configure(state="disabled")

    app.is_processing = True
    app.start_button.configure(state="disabled")
    app.pause_button.configure(state="disabled")
    app.resume_button.configure(state="disabled")
    app.cancel_button.configure(state="disabled")
    app.progress.set(0)

    def worker():
        try:
            summary = normalize_pgn_metadata_path(
                source_path,
                process_subdirs=app.process_subdirs.get(),
                log_message=app.log_message,
                progress_callback=lambda value: app.root.after(
                    0,
                    lambda v=value: app.progress.set(v),
                ),
            )
        except Exception as exc:
            app.root.after(0, lambda e=exc: _finish_metadata_normalization(app, error=e))
            return

        app.root.after(
            0,
            lambda result=summary: _finish_metadata_normalization(app, summary=result),
        )

    threading.Thread(target=worker, daemon=True).start()


def open_edit_window(app):
    open_translation_editor(app)


def open_glossary_window(app):
    open_glossary_editor(app)
