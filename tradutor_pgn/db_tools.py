import os
import sqlite3
from tkinter import filedialog, messagebox

from .app_config import language_label
from .chess_notation import fix_move_notation, supports_notation
from .prose_fixes import normalize_prose
from .database import (
    MoveNotationCanceled,
    QUALITY_VERSION_KEY,
    QualityReevaluationCanceled,
    adopt_unknown_source_language,
    analyze_automatic_translation_updates,
    analyze_move_notation_updates,
    apply_automatic_translation_updates,
    apply_move_notation_updates,
    clear_all_translations,
    count_unreviewed_file_translations,
    discard_unreviewed_file_translations,
    list_translation_runs,
    get_quality_heuristics_version,
    initialize_database,
    quality_heuristics_are_current,
    reevaluate_quality_warnings,
    set_db_metadata,
)
from .background_task import TaskCanceled, run_with_progress
from .confirm_dialog import ask_typed_confirmation
from .database import AutomaticRulesCanceled
from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    apply_automatic_substitutions,
    create_glossary_backup,
    filter_glossary_entries_by_type,
    glossary_entry_pair,
    glossary_entry_scope,
    load_automatic_substitutions,
    load_glossary_entry_details,
    load_interactive_substitutions,
    save_glossary_entries,
    scope_languages,
)
from .review_quality import QUALITY_HEURISTICS_VERSION
from .stats_window import StatsWindow


# Paginas por passo da copia do SQLite. E o intervalo entre duas chances de
# reportar progresso ou de desistir: menor da uma barra mais fluida e mais
# chamadas de callback. 2048 paginas sao ~8 MB, que num banco de 80 MB dao ~10
# atualizacoes.
# As partes puras moram em modulos proprios (ROADMAP 28.11); este continua
# sendo a porta por onde o resto do programa e os testes as importam.
from .db_backup import (
    BACKUP_PAGES_PER_STEP,  # noqa: F401 - fachada
    _copy_database,  # noqa: F401 - fachada
    _unique_backup_path,  # noqa: F401 - fachada
    create_database_backup,  # noqa: F401 - fachada
    restore_database_from_backup,  # noqa: F401 - fachada
    validate_restore_source,  # noqa: F401 - fachada
)
from .db_export import (
    EXPORT_CHUNK,  # noqa: F401 - fachada
    EXPORT_CSV_HEADERS,  # noqa: F401 - fachada
    IMPORT_PROGRESS_EVERY,  # noqa: F401 - fachada
    TMX_SOURCE_LANGUAGE,  # noqa: F401 - fachada
    TMX_UNKNOWN_LANGUAGE,  # noqa: F401 - fachada
    _XML_FORBIDDEN_RE,  # noqa: F401 - fachada
    _empty_import_stats,  # noqa: F401 - fachada
    _existing_row,  # noqa: F401 - fachada
    _normalize_import_row,  # noqa: F401 - fachada
    _parse_verified,  # noqa: F401 - fachada
    _read_translation_csv_rows,  # noqa: F401 - fachada
    _report_import_progress,  # noqa: F401 - fachada
    analyze_translations_csv_import,  # noqa: F401 - fachada
    export_translations_to_csv,  # noqa: F401 - fachada
    export_translations_to_tmx,  # noqa: F401 - fachada
    import_translations_from_csv,  # noqa: F401 - fachada
    tmx_language,  # noqa: F401 - fachada
    tmx_segment,  # noqa: F401 - fachada
    tmx_translation_unit,  # noqa: F401 - fachada
)
from .db_stats import (
    FILE_PROGRESS_LIMIT,  # noqa: F401 - fachada
    RUN_OUTCOME_LABELS,  # noqa: F401 - fachada
    collect_database_stats,  # noqa: F401 - fachada
    describe_translation_run,  # noqa: F401 - fachada
    format_daily_activity,  # noqa: F401 - fachada
    format_database_stats,  # noqa: F401 - fachada
    format_file_progress,  # noqa: F401 - fachada
    format_quality_stats,  # noqa: F401 - fachada
    format_translation_runs,  # noqa: F401 - fachada
    format_word_counts,  # noqa: F401 - fachada
    stats_tables,  # noqa: F401 - fachada
)




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


def export_tmx(app, on_finish=None):
    """Botao "Exportar TMX": pergunta o caminho e exporta em segundo plano."""
    save_path = filedialog.asksaveasfilename(
        title="Exportar memoria de traducao (TMX)",
        defaultextension=".tmx",
        filetypes=[("Memoria de traducao TMX", "*.tmx"), ("Todos os arquivos", "*.*")],
    )
    if not save_path:
        if on_finish is not None:
            on_finish()
        return None

    falhou, cancelado = _database_task_callbacks(
        app, "Exportar TMX", "Erro ao exportar TMX", on_finish
    )

    def trabalho(task):
        return export_translations_to_tmx(
            app.output_db,
            save_path,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    def exportado(unidades):
        messagebox.showinfo(
            "Exportar TMX",
            f"{unidades} unidade(s) de traducao exportada(s) para:\n{save_path}\n\n"
            "Linhas sem traducao nao entram: uma memoria com o lado de destino "
            "vazio nao serve para concordancia.",
        )
        if on_finish is not None:
            on_finish()

    return run_with_progress(
        app.root,
        "Exportar TMX",
        _cancelable(trabalho),
        on_success=exportado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Escrevendo a memoria de traducao...",
    )


def analyze_database_automatic_rules(
    db_path,
    target_language=None,
    automatic_rules=None,
    progress_callback=None,
    should_cancel=None,
    source_language=None,
    only_pending=False,
    source_file=None,
):
    if automatic_rules is None:
        automatic_rules = load_automatic_substitutions(
            source_language=source_language, target_language=target_language
        )

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
            only_pending=only_pending,
            source_file=source_file,
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
    only_pending=False,
    source_file=None,
):
    if automatic_rules is None:
        automatic_rules = load_automatic_substitutions(
            source_language=source_language, target_language=target_language
        )

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
            only_pending=only_pending,
            source_file=source_file,
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


def format_automatic_rules_scope(
    target_language, source_language=None, source_file=None, include_verified=False
):
    """O escopo, em texto, para o dialogo de confirmacao.

    Nomeia a ORIGEM tambem quando ha filtro dela: confirmar "vou alterar 12.000
    traducoes do idioma pt" enquanto a janela mostra so as vindas do espanhol
    daria um numero que nao bate com nada na tela. O ARQUIVO e as VERIFICADAS
    entram pela mesma razao (garantia S19): o escopo padrao deixa as verificadas
    de fora, e o dialogo diz isso em vez de deixar o usuario supor.
    """
    destino = f"idioma atual ({target_language})" if target_language else "todos os idiomas"
    partes = [destino]
    if source_language is not None:
        partes.append(f"origem {language_label(source_language)}")
    if source_file:
        partes.append(f"arquivo {os.path.basename(source_file) or source_file}")
    partes.append("pendentes e verificadas" if include_verified else "s\u00f3 pendentes")
    return ", ".join(partes)


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


def _format_automatic_preview(
    target_language, preview, source_language=None, source_file=None, include_verified=False
):
    escopo = format_automatic_rules_scope(
        target_language, source_language, source_file, include_verified
    )
    return (
        "Aplicar regras automaticas nas traducoes existentes?\n\n"
        f"Escopo: {escopo}\n"
        f"Regras automaticas: {preview['rules']}\n"
        f"Traducoes analisadas: {preview['scanned']}\n"
        f"Traducoes que serao alteradas: {preview['changed']}\n\n"
        f"{format_automatic_rule_examples(preview.get('examples', []))}\n\n"
        "Um backup do banco sera criado antes de alterar os dados."
    )


def _format_automatic_result(
    target_language, stats, source_language=None, source_file=None, include_verified=False
):
    escopo = format_automatic_rules_scope(
        target_language, source_language, source_file, include_verified
    )
    return (
        "Regras automaticas aplicadas com sucesso.\n\n"
        f"Escopo: {escopo}\n"
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
    source_file=None,
    include_verified=False,
    automatic_rules=None,
):
    """Aplica as regras automaticas, com previa, backup e confirmacao.

    As duas varreduras (previa e escrita) rodam FORA da thread do Tk, cada uma
    com barra de progresso e cancelamento: sao 38 s de janela travada no banco
    real, sem nenhum sinal de vida, se rodarem no proprio callback do botao.

    Isso obriga o resultado a chegar por callback. `on_finish(stats)` e chamado
    na thread principal quando tudo termina — com `None` se o usuario cancelou,
    se nao havia regras ou se nada mudou. Quem chama sem `on_finish` (a janela
    principal) so quer disparar a operacao e nao precisa do resultado.

    **O escopo padrao e "so pendentes"** (garantia S19, ROADMAP 28.5). A
    ferramenta reescrevia tambem as linhas que o revisor ja tinha aprovado, e
    promover uma regra na linha 500 desfazia a revisao das 499 anteriores. A
    linha verificada so entra com `include_verified=True`, e quem passa isso
    tem de ter perguntado antes. `source_file` restringe as linhas com
    ocorrencia naquele arquivo — o escopo que o editor mostra na tela.

    `automatic_rules` permite aplicar UMA regra recem-criada (a de "Trocas
    repetidas") em vez de todas as do glossario.
    """
    janela = parent if parent is not None else app.root
    only_pending = not include_verified

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

    if automatic_rules is None:
        try:
            automatic_rules = load_automatic_substitutions(
                source_language=source_language, target_language=target_language
            )
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
                only_pending=only_pending,
                source_file=source_file,
            )

        def aplicado(stats):
            if hasattr(app, "translation_cache"):
                app.translation_cache.clear()
            messagebox.showinfo(
                "Substituicoes automaticas",
                _format_automatic_result(
                    target_language, stats, source_language, source_file, include_verified
                ),
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
            escopo = format_automatic_rules_scope(
                target_language, source_language, source_file, include_verified
            )
            messagebox.showinfo(
                "Substituicoes automaticas",
                (
                    "Nenhuma traducao existente precisa ser atualizada.\n\n"
                    f"Escopo: {escopo}\n"
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
            _format_automatic_preview(
                target_language, preview, source_language, source_file, include_verified
            ),
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
            only_pending=only_pending,
            source_file=source_file,
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


def automatic_rule_scan_scope(entry):
    """`(origem, destino)` das linhas que uma regra alcanca, pelo escopo dela.

    Escopo `en>pt` -> so as linhas desse par; `pt` -> todo destino `pt`; `*` ->
    o banco inteiro. `None` e "sem filtro" nos dois lugares, que e o que
    `_automatic_rules_query` entende por "todas".
    """
    origem, destino = scope_languages(glossary_entry_scope(entry))
    return (origem or None), (destino or None)


def format_promotion_preview(entry, preview, max_items=10):
    """O texto do dialogo "Promover a automática?" (garantia S20).

    Traz o NUMERO e a AMOSTRA — e o que o item existe para dar: a memoria da
    revisao de terminologia pediu "nao aplicar em massa sem ver", e a revisao
    critica mostrou o que a palavra inteira faria (`Black esta bem` -> `as
    pretas esta bem`). Dez exemplos e o que cabe num dialogo e o que basta para
    ver a regra errar.
    """
    orig, new = glossary_entry_pair(entry)
    if preview["changed"] == 0:
        efeito = (
            "Esta regra n\u00e3o alteraria nenhuma tradu\u00e7\u00e3o pendente "
            f"({preview['scanned']} analisadas)."
        )
    else:
        efeito = (
            f"Esta regra alteraria {preview['changed']} tradu\u00e7\u00e3o(\u00f5es) "
            f"pendente(s) de {preview['scanned']} analisadas."
        )
    partes = [
        f"Promover {orig!r} -> {new!r} a autom\u00e1tica?",
        "",
        efeito,
    ]
    exemplos = format_automatic_rule_examples(preview.get("examples", []), max_items)
    if exemplos:
        partes.extend(["", exemplos])
    partes.extend(
        [
            "",
            "Uma regra autom\u00e1tica \u00e9 aplicada a toda tradu\u00e7\u00e3o nova "
            "sem confirma\u00e7\u00e3o. As linhas verificadas n\u00e3o entram nesta "
            "contagem nem em \"Aplicar Automaticas\".",
        ]
    )
    return "\n".join(partes)


def preview_automatic_rule_impact(app, entry, parent=None, on_decision=None):
    """Mostra o impacto de promover `entry` a `automatic` e pergunta (S20).

    `entry` e a entrada detalhada `(orig, new, tipo, prioridade, escopo)` como o
    formulario a gravaria. A contagem e a MESMA varredura de "Aplicar
    Automaticas" (`analyze_automatic_translation_updates`, so pendentes, com a
    regra sozinha e o `@casa@` expandido), e roda por `run_with_progress`: a
    varredura parecida de 2.7 segurou a interface por 38 s.

    `on_decision(True)` quando o usuario confirmou; `on_decision(False)` quando
    recusou, cancelou a varredura ou ela falhou. Falhar NAO promove: uma regra
    automatica reescreve sem perguntar, e "nao consegui medir" nao e licenca.
    """
    janela = parent if parent is not None else app.root

    def decidir(promover):
        if on_decision is not None:
            on_decision(bool(promover))

    def falhou(erro):
        messagebox.showerror(
            "Promover a autom\u00e1tica",
            f"N\u00e3o foi poss\u00edvel medir o impacto da regra:\n{erro}",
            parent=parent,
        )
        decidir(False)

    def cancelado(_valor=None):
        decidir(False)

    regras = filter_glossary_entries_by_type([entry], GLOSSARY_RULE_AUTOMATIC)
    origem, destino = automatic_rule_scan_scope(entry)

    def analisar(task):
        return analyze_database_automatic_rules(
            app.output_db,
            target_language=destino,
            automatic_rules=regras,
            progress_callback=task.report,
            should_cancel=task.cancelado,
            source_language=origem,
            only_pending=True,
        )

    def analisado(preview):
        decidir(
            messagebox.askyesno(
                "Promover a autom\u00e1tica",
                format_promotion_preview(entry, preview),
                parent=parent,
            )
        )

    run_with_progress(
        janela,
        "Promover a autom\u00e1tica",
        _cancelable(analisar),
        on_success=analisado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Medindo quantas tradu\u00e7\u00f5es pendentes a regra alteraria...",
    )


def show_db_stats(app):
    """Abre a janela de estatisticas, computando o conteudo em segundo plano."""
    def pronto(stats):
        # As tabelas vao junto do texto (ROADMAP 22.12): o `.txt` corrido serve
        # para ler e colar num recado, e o CSV para a planilha de orcamento.
        StatsWindow(app, format_database_stats(stats), tables=stats_tables(stats))

    def falhou(erro):
        messagebox.showerror(
            "Erro", f"Nao foi possivel acessar o banco de dados:\n{erro}"
        )

    run_with_progress(
        app.root,
        "Estatisticas do Banco de Dados",
        _cancelable(
            lambda task: collect_database_stats(
                app.output_db,
                progress_callback=task.report,
                should_cancel=task.cancelado,
            )
        ),
        on_success=pronto,
        on_error=falhou,
        on_cancel=lambda _valor=None: None,
        message="Somando as traducoes e contando as palavras...",
    )


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


OVERWRITE_CHOICE_MESSAGE = (
    "Sim: importar SOBRESCREVENDO as traducoes que diferem.\n"
    "Nao: importar sem sobrescrever (so novas e vazias).\n"
    "Cancelar: nao importar nada."
)


def format_import_preview(preview):
    """A previa da importacao, com o que ela NAO faria por padrao.

    A linha das sobrescritiveis e o item: sem ela, um CSV com 300 traducoes
    corrigidas na planilha aparecia como "Sem alteracao: 300" — verdade literal, e
    a informacao que importa (o arquivo tem 300 correcoes prontas, e elas serao
    descartadas) nao estava escrita em lugar nenhum.
    """
    linhas = [
        "Previa da importacao:",
        "",
        f"Linhas lidas: {preview['total_rows']}",
        f"Novas: {preview['inserted']}",
        f"Vazias a preencher: {preview['filled_empty']}",
        f"Sem alteracao: {preview['unchanged']}",
        f"Ignoradas: {preview['skipped']}",
        f"Verificadas a aplicar: {preview['verified_applied']}",
    ]
    if preview["overwritable"]:
        linhas.extend(
            [
                "",
                f"{preview['overwritable']} traducao(oes) do arquivo DIFEREM do que "
                f"esta gravado.",
            ]
        )
        if preview["overwritable_verified"]:
            linhas.append(
                f"Dessas, {preview['overwritable_verified']} estao marcadas como "
                f"VERIFICADAS — sobrescrever apaga a revisao."
            )
        if preview["verified_on_existing"]:
            linhas.append(
                f"Sobrescrevendo, {preview['verified_on_existing']} linha(s) ja "
                f"gravada(s) tambem passam a verificadas pelo CSV."
            )
    else:
        linhas.extend(
            ["", "Traducoes existentes preenchidas nao serao sobrescritas."]
        )
    linhas.extend(["", "Um backup sera criado antes de alterar o banco."])
    return "\n".join(linhas)


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

    def aplicar(overwrite_existing=False):
        def trabalho(task):
            return import_translations_from_csv(
                app.output_db,
                csv_path,
                csv_rows=csv_rows,
                progress_callback=task.report,
                should_cancel=task.cancelado,
                overwrite_existing=overwrite_existing,
            )

        def importado(stats):
            if hasattr(app, "translation_cache"):
                app.translation_cache.clear()
            linha_sobrescritas = (
                f"Sobrescritas: {stats['overwritten']}\n"
                if overwrite_existing
                else ""
            )
            messagebox.showinfo(
                "Importar CSV",
                (
                    "CSV importado com sucesso.\n\n"
                    f"Linhas lidas: {stats['total_rows']}\n"
                    f"Novas: {stats['inserted']}\n"
                    f"Vazias preenchidas: {stats['filled_empty']}\n"
                    f"{linha_sobrescritas}"
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
        if not preview["overwritable"]:
            confirmed = messagebox.askyesno(
                "Importar CSV",
                format_import_preview(preview) + "\n\nDeseja continuar?",
            )
            if not confirmed:
                if on_finish is not None:
                    on_finish(None)
                return
            aplicar()
            return

        # Tres desfechos, e por isso tres botoes: importar sobrescrevendo,
        # importar respeitando T1, ou nao importar. Reduzir a um "sim/nao" era o
        # que fazia o fluxo natural — exportar, corrigir na planilha, importar —
        # terminar em "Sem alteracao" para tudo, com o trabalho da planilha
        # jogado fora sem que nada tivesse falhado.
        escolha = messagebox.askyesnocancel(
            "Importar CSV",
            format_import_preview(preview) + "\n\n" + OVERWRITE_CHOICE_MESSAGE,
        )
        if escolha is None:
            if on_finish is not None:
                on_finish(None)
            return
        aplicar(overwrite_existing=bool(escolha))

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


def _count_unreviewed_in_file(db_path, source_file, target_language, source_language):
    """Quantas linhas o descarte apagaria, para a pergunta dizer o que sera perdido."""
    conn = None
    try:
        conn = initialize_database(db_path)
        return count_unreviewed_file_translations(
            conn.cursor(), source_file, target_language, source_language
        )
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()


def discard_unreviewed_translations(
    app,
    source_file,
    target_language,
    source_language=None,
    parent=None,
    on_finish=None,
):
    """"Descartar as nao revisadas deste arquivo", apos backup e palavra digitada.

    A rede de seguranca do ROADMAP 28.6 (garantia Z4): o que um motor deixou
    num livro e que ninguem tocou pode ser jogado fora para traduzir de novo,
    sem perder uma linha revisada. O criterio e um so e mora em
    `database._unreviewed_file_rows_query`; aqui e a orquestracao, que segue
    "Zerar Traducoes" passo a passo — **o backup antes da pergunta** (Z1), a
    palavra digitada (Z2), sem cancelamento no meio, o cache em memoria limpo.

    `on_finish(apagadas)` chega na thread do Tk; `None` quando nao havia o que
    apagar, o usuario desistiu ou deu erro. `parent` e a janela do editor, para
    os dialogos nao cairem atras dela.
    """
    janela = parent if parent is not None else app.root
    nome = os.path.basename(source_file) or source_file
    titulo = "Descartar não revisadas"

    falhou, _cancelado = _database_task_callbacks(
        app, titulo, "Erro ao descartar as traducoes nao revisadas:", on_finish
    )

    total = _count_unreviewed_in_file(
        app.output_db, source_file, target_language, source_language
    )
    if total == 0:
        messagebox.showinfo(
            titulo,
            (
                f"Não há o que descartar em {nome}: toda tradução "
                "deste arquivo foi verificada, tem status ou nota, foi editada "
                "ou é usada por outro arquivo."
            ),
            parent=parent,
        )
        if on_finish is not None:
            on_finish(None)
        return

    quantas = "um numero desconhecido de" if total is None else f"{total:,}".replace(",", ".")

    try:
        backup_path = create_database_backup(app.output_db)
    except Exception as exc:
        falhou(exc)
        return

    confirmado = ask_typed_confirmation(
        janela,
        titulo,
        (
            f"Isto apaga {quantas} tradução(ões) de {nome} "
            f"({language_label(target_language)}).\n\n"
            "Ficam de fora as verificadas, as com status ou nota, as que têm "
            "histórico de edição e as que outro arquivo também usa. "
            "As ocorrências dessas linhas neste arquivo vão junto.\n\n"
            "Um backup acabou de ser criado em:\n"
            f"{backup_path}\n\n"
            "É por ele que dá para voltar atrás."
        ),
    )
    if not confirmado:
        app.log_message(
            f"Descarte das nao revisadas de {nome} cancelado. "
            f"O backup criado ficou em: {backup_path}"
        )
        if on_finish is not None:
            on_finish(None)
        return

    def trabalho(task):
        task.report(0, 1)
        conn = initialize_database(app.output_db)
        try:
            apagadas = discard_unreviewed_file_translations(
                conn.cursor(), source_file, target_language, source_language
            )
            conn.commit()
        finally:
            conn.close()
        task.report(1, 1)
        return apagadas

    def pronto(apagadas):
        if hasattr(app, "translation_cache"):
            # Pela razao de "Zerar Traducoes": o cache em memoria tem
            # precedencia sobre o banco, e deixado como estava a proxima
            # execucao reaproveitaria o que acabou de ser descartado.
            app.translation_cache.clear()
        app.log_message(
            f"Descartadas {apagadas} traducao(oes) nao revisadas de {nome}. "
            f"Backup em: {backup_path}"
        )
        messagebox.showinfo(
            titulo,
            (
                f"{apagadas} tradução(ões) de {nome} descartada(s).\n\n"
                f"O backup anterior está em:\n{backup_path}"
            ),
            parent=parent,
        )
        if on_finish is not None:
            on_finish(apagadas)

    run_with_progress(
        janela,
        titulo,
        trabalho,
        on_success=pronto,
        on_error=falhou,
        message="Descartando as traducoes nao revisadas (nao interrompa)...",
        allow_cancel=False,
    )


GLOSSARY_TYPE_NAMES = (
    (GLOSSARY_RULE_SUGGESTION, "sugestão", "sugestões"),
    (GLOSSARY_RULE_AUTOMATIC, "automática", "automáticas"),
    (GLOSSARY_RULE_CLEANUP, "limpeza", "limpezas"),
)


def count_glossary_entries_by_type(path=None):
    """`(total, {tipo: quantas})` do ARQUIVO de glossario (ROADMAP 22.12).

    `deduplicate=False` de proposito: e a mesma fonte do "Total" que o editor de
    glossario mostra, e o numero anunciado por um dialogo que apaga tem de ser o
    numero que ele apaga. Deduplicar aqui daria um terceiro numero, diferente dos
    outros dois — que era exatamente a doenca.
    """
    entradas = load_glossary_entry_details(path, deduplicate=False)
    por_tipo = {}
    for entrada in entradas:
        tipo = entrada[2] if len(entrada) > 2 else GLOSSARY_RULE_SUGGESTION
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
    return len(entradas), por_tipo


def describe_glossary_types(por_tipo):
    """"5.674 sugestões, 186 automáticas e 50 limpezas".

    So os tipos que EXISTEM aparecem: "0 limpezas" num glossario que nunca teve
    uma e ruido num dialogo que ja e longo. Pura, e por isso conferivel sem
    abrir janela.
    """
    partes = []
    for tipo, singular, plural in GLOSSARY_TYPE_NAMES:
        quantas = por_tipo.get(tipo, 0)
        if quantas:
            partes.append(f"{quantas} {singular if quantas == 1 else plural}")
    if not partes:
        return "nenhuma regra"
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + f" e {partes[-1]}"


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
    # **O que vai ser apagado, e nao o que esta em uso** (ROADMAP 22.12).
    # `len(app.glossary_substitutions)` conta a lista APLICAVEL, que e outra
    # coisa: ela expande `@casa@` (uma linha vira 64 regras), soma as 232 da
    # semente — que zerar NAO apaga, porque a semente vem com o programa — e
    # exclui as de limpeza, que zerar apaga. Medido no glossario real: o arquivo
    # tinha 5.910 entradas e o dialogo anunciava 7.325.
    total, por_tipo = count_glossary_entries_by_type()

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
            f"Isto apaga as {total} regras do arquivo de glossário "
            f"({describe_glossary_types(por_tipo)}).\n\n"
            "As regras de fábrica que vêm com o programa continuam valendo: "
            "elas não estão no arquivo.\n\n"
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

    # **Recarrega, e nao esvazia** (ROADMAP 22.12). `app.glossary_substitutions = []`
    # deixava a sessao sem sugestao nenhuma e a proxima abertura com 232 — a
    # semente, que toda carga de regras mescla (garantia S15). Na pratica o
    # programa "recuperava" sozinho um glossario que o usuario acabou de zerar,
    # e so no dia seguinte. Recarregar do disco e o que `update_app_glossary` do
    # editor ja fazia; o que sai daqui e o estado de verdade.
    app.glossary_substitutions = load_interactive_substitutions()
    restantes = len(app.glossary_substitutions)
    # As janelas abertas recarregam sozinhas: o editor de traducoes ainda mostra
    # as sugestoes das regras que acabaram de deixar de existir, e a lista do
    # editor de glossario ainda mostra as regras.
    for callback in list(getattr(app, "glossary_change_callbacks", [])):
        try:
            callback(app.glossary_substitutions)
        except Exception:  # pragma: no cover - defensivo
            pass

    app.log_message(
        f"Glossario zerado: {total} regra(s) do arquivo removidas "
        f"({describe_glossary_types(por_tipo)}). "
        f"Restam {restantes} regra(s) de fabrica. Backup em: {backup_path}"
    )
    messagebox.showinfo(
        "Zerar Glossário",
        (
            f"Glossário zerado: {total} regra(s) removidas "
            f"({describe_glossary_types(por_tipo)}).\n\n"
            f"Continuam valendo {restantes} regra(s) de fábrica, que vêm com o "
            "programa e não estão no arquivo.\n\n"
            f"O backup anterior está em:\n{backup_path}"
        ),
    )
    if on_finish is not None:
        on_finish(total)

def _cancelable_quality(work):
    """O mesmo tradutor de `_cancelable`, para a reavaliacao de qualidade."""
    def wrapper(task):
        try:
            return work(task)
        except QualityReevaluationCanceled:
            raise TaskCanceled() from None

    return wrapper


def reevaluate_database_quality(
    db_path,
    progress_callback=None,
    should_cancel=None,
):
    """Reavalia os avisos e, SO se terminar, grava a versao das heuristicas.

    A ordem e o item (garantia Q2). Gravar a versao antes de reavaliar — ou
    depois de um cancelamento — diria que o banco esta em dia com um veredito que
    metade das linhas nao recebeu, e ninguem descobriria depois: a coluna nao tem
    como acusar que esta velha. Cancelar deixa a marca antiga, e a proxima
    abertura oferece de novo.

    Nao faz backup, e e a unica escrita em massa sem um. `quality_warning` e
    coluna DERIVADA: ela nao guarda nada que o usuario tenha escrito, e o que ela
    contem pode ser recalculado a partir do texto a qualquer momento — que e
    exatamente o que esta funcao faz. Um backup de 115 MB para proteger um bit
    por linha, recomputavel, seria custo sem risco correspondente.
    """
    conn = initialize_database(db_path)
    try:
        stats = reevaluate_quality_warnings(
            conn,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        set_db_metadata(conn, QUALITY_VERSION_KEY, QUALITY_HEURISTICS_VERSION)
        conn.commit()
    finally:
        conn.close()

    stats["version"] = QUALITY_HEURISTICS_VERSION
    return stats


def reevaluate_quality_in_database(app, on_finish=None, announce_when_current=True):
    """Reavalia os avisos de qualidade do banco, com progresso e cancelamento.

    `announce_when_current=False` e para a chamada da abertura: se o banco ja esta
    em dia, ela nao pode abrir dialogo nenhum — seria um aviso por sessao dizendo
    que nada aconteceu.
    """
    conn = None
    try:
        conn = initialize_database(app.output_db)
        em_dia = quality_heuristics_are_current(conn)
        versao_gravada = get_quality_heuristics_version(conn)
        total = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    except Exception as exc:
        messagebox.showerror("Avisos QA", f"Nao foi possivel ler o banco:\n{exc}")
        if on_finish is not None:
            on_finish(None)
        return
    finally:
        if conn is not None:
            conn.close()

    if em_dia:
        if announce_when_current:
            messagebox.showinfo(
                "Avisos QA",
                (
                    "Os avisos de qualidade ja estao na versao atual das "
                    f"heuristicas (v{QUALITY_HEURISTICS_VERSION}).\n\n"
                    f"Traducoes avaliadas: {total}"
                ),
            )
        if on_finish is not None:
            on_finish(None)
        return

    if total == 0:
        # Banco vazio: nao ha o que reavaliar, e a marca pode ser gravada na
        # hora. Sem este atalho, toda primeira abertura — e todo banco recem
        # zerado — abriria uma janela de progresso modal para varrer zero linha.
        # E o caminho de um banco NOVO, que e o mais comum de todos.
        try:
            conn = initialize_database(app.output_db)
            try:
                set_db_metadata(conn, QUALITY_VERSION_KEY, QUALITY_HEURISTICS_VERSION)
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - defensivo
            app.log_message(f"[AVISO] Nao foi possivel marcar a versao do QA: {exc}")
        if on_finish is not None:
            on_finish(None)
        return

    falhou, cancelado = _database_task_callbacks(
        app, "Avisos QA", "Erro ao reavaliar os avisos de qualidade:", on_finish
    )

    def trabalho(task):
        return reevaluate_database_quality(
            app.output_db,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    def pronto(stats):
        app.log_message(
            f"Avisos QA reavaliados (heuristicas v{stats['version']}): "
            f"{stats['scanned']} traducao(oes) examinadas, "
            f"{stats['changed']} com veredito alterado."
        )
        messagebox.showinfo(
            "Avisos QA",
            (
                "Avisos de qualidade reavaliados.\n\n"
                f"Heuristicas: v{versao_gravada or 'anterior'} -> "
                f"v{stats['version']}\n"
                f"Traducoes examinadas: {stats['scanned']}\n"
                f"Avisos que mudaram: {stats['changed']}"
            ),
        )
        if on_finish is not None:
            on_finish(stats)

    app.log_message(
        f"As heuristicas de avisos QA mudaram (v{versao_gravada or 'anterior'} -> "
        f"v{QUALITY_HEURISTICS_VERSION}); reavaliando {total} traducao(oes)."
    )
    run_with_progress(
        app.root,
        "Avisos QA",
        _cancelable_quality(trabalho),
        on_success=pronto,
        on_error=falhou,
        on_cancel=cancelado,
        message=f"Reavaliando {total} traducao(oes)...",
    )


def _cancelable_notation(work):
    """O mesmo tradutor de `_cancelable`, para a correcao de lances.

    `database.py` sinaliza desistencia com a sua propria excecao e nao pode
    conhecer o `background_task` — aquele modulo importa Tk, e e essa separacao
    que permite testar o banco sem display.
    """
    def wrapper(task):
        try:
            return work(task)
        except MoveNotationCanceled:
            raise TaskCanceled() from None

    return wrapper


def analyze_database_move_notation(
    db_path,
    source_language,
    target_language,
    progress_callback=None,
    should_cancel=None,
):
    conn = initialize_database(db_path)
    try:
        return analyze_move_notation_updates(
            conn.cursor(),
            source_language,
            target_language,
            fix_move_notation,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
    finally:
        conn.close()


def apply_database_move_notation(
    db_path,
    source_language,
    target_language,
    create_backup=True,
    backup_dir=None,
    label_unknown=True,
    progress_callback=None,
    should_cancel=None,
):
    """Rotula o idioma de origem e corrige os lances, nessa ordem.

    A ordem e o item: enquanto as linhas estiverem como "origem nao informada"
    elas nao pertencem a par nenhum, e a correcao — que precisa saber o que `R`
    significa no original — nao teria como alcanca-las. Rotular primeiro e o que
    poe as traducoes legadas dentro de um par onde a correcao trabalha.

    Cancelar faz `rollback`, e ai o rotulo tambem volta atras: as duas coisas
    acontecem na mesma transacao de proposito. Uma metade aplicada — linhas
    rotuladas com os lances ainda errados — seria um estado que o usuario nao
    pediu e que ele nao teria como distinguir do estado correto.
    """
    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        rotuladas = 0
        if label_unknown:
            rotuladas = adopt_unknown_source_language(
                cursor, target_language, source_language, None
            )
        stats = apply_move_notation_updates(
            cursor,
            source_language,
            target_language,
            fix_move_notation,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        stats["labeled"] = rotuladas
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    stats["backup_path"] = backup_path
    return stats


def format_move_notation_scope(source_language, target_language):
    return f"{language_label(source_language)} -> {target_language}"


def _format_move_notation_preview(stats):
    linhas = [
        "Corrigir as letras das pecas nas traducoes ja gravadas?",
        "",
        f"Par de idiomas: {format_move_notation_scope(stats['source_language'], stats['target_language'])}",
        f"Traducoes analisadas: {stats['scanned']}",
        f"Traducoes que serao alteradas: {stats['changed']}",
        f"Lances corrigidos: {stats['moves']}",
    ]
    if stats.get("labeled"):
        # A parte irreversivel, e a que faltava aqui. Corrigir reescreve texto
        # que o backup desfaz; rotular declara de que idioma veio o acervo
        # inteiro, e num banco com 200 mil linhas legadas esse "Sim" era dado sem
        # que o numero tivesse aparecido em lugar nenhum. Antes so era dito no
        # dialogo de RESULTADO, depois de feito.
        linhas.append(
            f"Linhas sem origem que serao rotuladas como "
            f"'{stats['source_language']}': {stats['labeled']}"
        )
    if stats["examples"]:
        linhas.append("")
        linhas.append("Exemplos:")
        for exemplo in stats["examples"][:5]:
            linhas.extend(
                [
                    f"  ID {exemplo['id']}:",
                    f"    Antes: {_preview_line(exemplo['previous_translation'])}",
                    f"    Depois: {_preview_line(exemplo['new_translation'])}",
                ]
            )
    linhas.extend(["", "Um backup do banco sera criado antes de alterar os dados."])
    return "\n".join(linhas)


def analyze_database_prose(
    db_path, source_language, target_language, progress_callback=None, should_cancel=None
):
    """Previa da passada de prosa: so as linhas PENDENTES do par (garantia P6)."""
    conn = initialize_database(db_path)
    try:
        return analyze_move_notation_updates(
            conn.cursor(),
            source_language,
            target_language,
            normalize_prose,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            only_pending=True,
        )
    finally:
        conn.close()


def apply_database_prose(
    db_path,
    source_language,
    target_language,
    create_backup=True,
    backup_dir=None,
    progress_callback=None,
    should_cancel=None,
):
    """Aplica as normalizacoes de prosa as traducoes pendentes ja gravadas.

    E o mesmo laco da correcao de lances (P4), com tres diferencas que sao o
    item: a funcao injetada e `normalize_prose`; o escopo e `verified = 0` —
    uma linha que o revisor aprovou como esta nao e reescrita por aqui; e a
    acao do historico e `prose_fix`. Nao rotula origem nenhuma: rotular e a
    declaracao de "Corrigir Lances", e esta ferramenta nao a repete.
    """
    backup_path = None
    if create_backup:
        backup_path = create_database_backup(db_path, backup_dir=backup_dir)

    conn = initialize_database(db_path)
    try:
        stats = apply_move_notation_updates(
            conn.cursor(),
            source_language,
            target_language,
            normalize_prose,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            only_pending=True,
            history_action="prose_fix",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    stats["backup_path"] = backup_path
    return stats


def _format_prose_preview(stats):
    linhas = [
        "Consertar a prosa das traducoes PENDENTES ja gravadas?",
        "",
        "O que muda: espaco entre numero/reticencia e lance, 'cavalo-d5' -> "
        "'cavalo de d5', espaco de largura zero, e 'depois' -> 'depois de' no "
        "fim de fragmento — sempre guiado pelo comentario original.",
        "As traducoes ja verificadas nao sao tocadas.",
        "",
        f"Par de idiomas: {format_move_notation_scope(stats['source_language'], stats['target_language'])}",
        f"Traducoes pendentes analisadas: {stats['scanned']}",
        f"Traducoes que serao alteradas: {stats['changed']}",
        f"Consertos: {stats['moves']}",
    ]
    if stats["examples"]:
        linhas.append("")
        linhas.append("Exemplos:")
        for exemplo in stats["examples"][:5]:
            linhas.extend(
                [
                    f"  ID {exemplo['id']}:",
                    f"    Antes: {_preview_line(exemplo['previous_translation'])}",
                    f"    Depois: {_preview_line(exemplo['new_translation'])}",
                ]
            )
    linhas.extend(["", "Um backup do banco sera criado antes de alterar os dados."])
    return "\n".join(linhas)


def normalize_prose_in_database(app, source_language, target_language, on_finish=None):
    """Aplica as normalizacoes de prosa ao que ja esta gravado (garantia P6).

    O pipeline conserta so o que passa pela traducao (P5, P7); o que ja estava
    no banco fica como a maquina deixou — a secao 11 do ROADMAP nasceu porque a
    correcao de lances tinha exatamente esse buraco. Medido no banco de
    desenvolvimento: 84 traducoes pendentes de 6.500.
    """
    janela = app.root
    falhou, cancelado = _database_task_callbacks(
        app, "Consertar Prosa", "Erro ao consertar a prosa:", on_finish
    )

    def aplicar(preview):
        def trabalho(task):
            return apply_database_prose(
                app.output_db,
                source_language,
                target_language,
                progress_callback=task.report,
                should_cancel=task.cancelado,
            )

        def aplicado(stats):
            if hasattr(app, "translation_cache"):
                # O cache em memoria tem o texto de ANTES e vence o banco na
                # proxima traducao — a mesma razao de "Corrigir Lances".
                app.translation_cache.clear()
            app.log_message(
                f"Prosa consertada: {stats['moves']} conserto(s) em "
                f"{stats['changed']} traducao(oes) pendente(s)."
            )
            messagebox.showinfo(
                "Consertar Prosa",
                (
                    "Consertos concluidos.\n\n"
                    f"Traduções alteradas: {stats['changed']}\n"
                    f"Consertos: {stats['moves']}\n\n"
                    f"Backup criado em:\n{stats['backup_path']}"
                ),
            )
            if on_finish is not None:
                on_finish(stats)

        run_with_progress(
            janela,
            "Consertando a prosa",
            _cancelable_notation(trabalho),
            on_success=aplicado,
            on_error=falhou,
            on_cancel=cancelado,
            message=f"Reescrevendo {preview['changed']} traducao(oes)...",
        )

    def analisado(preview):
        if preview["changed"] == 0:
            messagebox.showinfo(
                "Consertar Prosa",
                (
                    "Nenhuma tradução pendente precisa de conserto.\n\n"
                    f"Par de idiomas: "
                    f"{format_move_notation_scope(source_language, target_language)}\n"
                    f"Traduções pendentes analisadas: {preview['scanned']}"
                ),
            )
            if on_finish is not None:
                on_finish(preview)
            return

        if not messagebox.askyesno("Consertar Prosa", _format_prose_preview(preview)):
            if on_finish is not None:
                on_finish(None)
            return

        aplicar(preview)

    def analisar(task):
        return analyze_database_prose(
            app.output_db,
            source_language,
            target_language,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    run_with_progress(
        janela,
        "Consertar Prosa",
        _cancelable_notation(analisar),
        on_success=analisado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Analisando as traducoes pendentes...",
    )


NO_SOURCE_LANGUAGE_MESSAGE = (
    "Escolha o idioma de origem em 'Idioma de Tradução' antes.\n\n"
    "A correção lê os lances do comentário original para saber que peça cada "
    "letra nomeia, e 'Detectar' não diz isso — o R do inglês é Torre e o do "
    "português é Rei. Declarar o idioma é o que separa corrigir de chutar."
)


def fix_move_notation_in_database(app, source_language, target_language, on_finish=None):
    """Corrige os lances das traducoes ja gravadas de um par de idiomas.

    A correcao automatica (garantia P3) so alcanca o que passa pela traducao; o
    que ja estava no banco antes dela continua com as letras que o tradutor
    deixou. Medido no banco real: 4.144 de 201.603 traducoes.

    Rotula tambem as linhas sem idioma de origem, porque sem isso a correcao nao
    teria como alcanca-las — as duas coisas sao a mesma decisao do usuario,
    tomada uma vez.
    """
    janela = app.root

    if not supports_notation(source_language):
        messagebox.showinfo("Corrigir Lances", NO_SOURCE_LANGUAGE_MESSAGE)
        if on_finish is not None:
            on_finish(None)
        return

    falhou, cancelado = _database_task_callbacks(
        app, "Corrigir Lances", "Erro ao corrigir os lances:", on_finish
    )

    def aplicar(preview):
        def trabalho(task):
            return apply_database_move_notation(
                app.output_db,
                source_language,
                target_language,
                progress_callback=task.report,
                should_cancel=task.cancelado,
            )

        def aplicado(stats):
            if hasattr(app, "translation_cache"):
                # O cache em memoria guarda o texto de ANTES da correcao e tem
                # precedencia sobre o banco: a proxima traducao reescreveria os
                # lances errados de volta no PGN gerado.
                app.translation_cache.clear()
            app.log_message(
                f"Lances corrigidos: {stats['moves']} em {stats['changed']} "
                f"traducao(oes); {stats['labeled']} linha(s) rotuladas como "
                f"'{source_language}'."
            )
            messagebox.showinfo(
                "Corrigir Lances",
                (
                    "Correção concluída.\n\n"
                    f"Traduções alteradas: {stats['changed']}\n"
                    f"Lances corrigidos: {stats['moves']}\n"
                    f"Linhas rotuladas como '{source_language}': {stats['labeled']}\n\n"
                    f"Backup criado em:\n{stats['backup_path']}"
                ),
            )
            if on_finish is not None:
                on_finish(stats)

        run_with_progress(
            janela,
            "Corrigindo lances",
            _cancelable_notation(trabalho),
            on_success=aplicado,
            on_error=falhou,
            on_cancel=cancelado,
            message=f"Reescrevendo {preview['changed']} traducao(oes)...",
        )

    def analisado(preview):
        if preview["changed"] == 0:
            messagebox.showinfo(
                "Corrigir Lances",
                (
                    "Nenhuma tradução precisa de correção.\n\n"
                    f"Par de idiomas: "
                    f"{format_move_notation_scope(source_language, target_language)}\n"
                    f"Traduções analisadas: {preview['scanned']}"
                ),
            )
            if on_finish is not None:
                on_finish(preview)
            return

        if not messagebox.askyesno(
            "Corrigir Lances", _format_move_notation_preview(preview)
        ):
            if on_finish is not None:
                on_finish(None)
            return

        aplicar(preview)

    def analisar(task):
        return analyze_database_move_notation(
            app.output_db,
            source_language,
            target_language,
            progress_callback=task.report,
            should_cancel=task.cancelado,
        )

    run_with_progress(
        janela,
        "Corrigir Lances",
        _cancelable_notation(analisar),
        on_success=analisado,
        on_error=falhou,
        on_cancel=cancelado,
        message="Analisando as traducoes ja gravadas...",
    )
