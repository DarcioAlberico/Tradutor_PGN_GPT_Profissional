"""As estatisticas do banco e o relatorio delas — a parte PURA (ROADMAP 28.11).

Calculo (`collect_database_stats`, numa thread de trabalho), formatacao do
relatorio e das tabelas, e a descricao das execucoes. Sem Tk: a janela que
mostra isto e `stats_window`, e quem a abre e `db_tools.show_db_stats`, que
continua re-exportando estes nomes.
"""

import os

from .app_config import language_label
from .database import (
    WordCountCanceled,
    count_words_by_pair,
    list_translation_runs,
    fetch_review_rows,
    get_daily_review_activity,
    get_database_stats,
    initialize_database,
)
from .background_task import TaskCanceled
from .review_quality import summarize_quality_warnings


# Paginas por passo da copia do SQLite. E o intervalo entre duas chances de
# reportar progresso ou de desistir: menor da uma barra mais fluida e mais
# chamadas de callback. 2048 paginas sao ~8 MB, que num banco de 80 MB dao ~10
# atualizacoes.



# Quantas obras o resumo lista por extenso. O resumo e um `messagebox`, que nao
# rola nem se copia (ROADMAP 19, item 7): uma pasta com 200 capitulos daria um
# dialogo mais alto que a tela e o usuario perderia as linhas de cima, que sao as
# que ele leu primeiro. O corte fica dito na ultima linha.
FILE_PROGRESS_LIMIT = 20


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


def format_file_progress(per_file, indent="  ", limit=FILE_PROGRESS_LIMIT):
    """O progresso por obra, como o resumo o mostra (ROADMAP 18).

    Sem nenhuma ocorrencia gravada a resposta nao e um bloco vazio: e a frase que
    explica POR QUE ele esta vazio. Um banco de 201.607 linhas migrado ontem nao
    tem procedencia nenhuma — nao havia de onde tirar — e ele ganha a primeira
    quando um arquivo for processado de novo. Sem essa linha, a leitura obvia da
    ausencia e "o programa nao registrou", que e a conclusao errada.

    A porcentagem e sobre COMENTARIOS distintos, e nao sobre posicoes: e a
    pergunta "quanto desta obra ja foi revisado" respondida em unidades de
    trabalho, que e o que o revisor gasta. As posicoes aparecem ao lado porque sao
    o tamanho do livro.
    """
    if not per_file:
        return (
            f"{indent}Nenhum arquivo registrado ainda. As traducoes ja gravadas nao\n"
            f"{indent}tem procedencia — ela e registrada ao processar o PGN de novo."
        )

    linhas = []
    for arquivo, posicoes, comentarios, verificadas, pendentes, avisos in per_file[:limit]:
        porcento = (verificadas / comentarios * 100) if comentarios else 0.0
        linhas.append(
            f"{indent}- {os.path.basename(arquivo)}: {posicoes} posicoes | "
            f"{comentarios} comentarios | verificadas: {verificadas} "
            f"({porcento:.0f}%) | pendentes: {pendentes} | QA: {avisos}"
        )
    if len(per_file) > limit:
        linhas.append(f"{indent}... e mais {len(per_file) - limit} arquivo(s).")
    return "\n".join(linhas)


def collect_database_stats(db_path, progress_callback=None, should_cancel=None):
    """Tudo o que a janela de estatisticas mostra, computado FORA da thread do Tk.

    Era o unico trabalho pesado do programa que continuava dentro do callback do
    botao (ROADMAP 19, item 7): ele materializa as linhas com aviso de todos os
    pares e agora tambem conta as palavras do banco inteiro. Aqui dentro nao ha
    widget nenhum — quem exibe e `show_db_stats`, na thread principal.

    A contagem de palavras vem por ultimo de proposito: e a parte mais longa, e
    cancelar no meio dela nao perde as anteriores (ninguem as ve, mas o
    cancelamento chega mais rapido do que se ela fosse a primeira).
    """
    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        stats = get_database_stats(cursor)

        quality_rows_by_language = {}
        all_quality_rows = []
        for source, target, _count, _verified, _pending in stats["per_language"]:
            if should_cancel is not None and should_cancel():
                raise TaskCanceled()
            # Só as linhas marcadas com aviso: o resumo exibido conta apenas
            # essas, entao carregar a tabela inteira era desperdicio puro
            # (~2 s de interface congelada e ~100 MB em 195 mil linhas).
            lang_rows = fetch_review_rows(
                cursor, target, status_filter="warnings", source_language=source
            )
            quality_rows_by_language[(source, target)] = lang_rows
            all_quality_rows.extend(lang_rows)

        stats["quality"] = summarize_quality_warnings(all_quality_rows)
        stats["quality_by_language"] = {
            par: summarize_quality_warnings(linhas)
            for par, linhas in quality_rows_by_language.items()
        }
        stats["daily"] = get_daily_review_activity(cursor)
        # As ultimas 30 execucoes (Z5): e onde se confere qual e "a ultima"
        # antes de reverter, e quanto cada motor inseriu.
        stats["runs"] = list_translation_runs(cursor, limit=30)

        try:
            por_par, total = count_words_by_pair(
                cursor,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
        except WordCountCanceled as exc:
            raise TaskCanceled() from exc
        stats["words_by_pair"] = por_par
        stats["words"] = total
        return stats
    finally:
        conn.close()


def format_word_counts(counts, indent="  "):
    """As contagens de palavras de um recorte, em quatro linhas.

    O original e a traducao aparecem separados porque servem a coisas diferentes: o
    tradutor orca pelo ORIGINAL (e o que o cliente manda) e mede o trabalho feito
    pela TRADUCAO. Os dois numeros juntos tambem dizem, de graca, quanto o idioma
    de destino incha o texto — em portugues sobre ingles, sempre incha.
    """
    return "\n".join([
        f"{indent}Palavras no original: {counts['original']:,}".replace(",", "."),
        f"{indent}Palavras na traducao: {counts['translated']:,}".replace(",", "."),
        f"{indent}Palavras verificadas: {counts['verified']:,}".replace(",", "."),
        f"{indent}Palavras pendentes: {counts['pending']:,}".replace(",", "."),
    ])


def format_daily_activity(daily, indent="  "):
    """Produtividade por dia, do historico de edicoes (ROADMAP 19, item 6)."""
    if not daily:
        return (
            f"{indent}Nenhuma edicao registrada. O historico guarda uma linha por\n"
            f"{indent}edicao feita no editor — traducao gravada pelo worker nao conta."
        )
    return "\n".join(
        f"{indent}- {dia}: {edicoes} edicao(oes) | {palavras} palavra(s)"
        for dia, edicoes, palavras in daily
    )


def format_database_stats(stats):
    """O relatorio inteiro, como texto. Puro: e o que a janela mostra e copia."""
    linhas = [
        f"Total de traducoes armazenadas: {stats['total']}",
        f"Verificadas: {stats['verified_total']}",
        f"Pendentes: {stats['pending_total']}",
        "",
        "Palavras (acervo inteiro):",
        format_word_counts(stats["words"]),
        "",
        "QA geral:",
        format_quality_stats(stats["quality"], "  "),
        "",
        "Por par de idiomas (origem -> destino):",
    ]
    for source, target, count, verified, pending in stats["per_language"]:
        resumo_qa = stats["quality_by_language"].get(
            (source, target), {"warning_rows": 0}
        )
        palavras = stats["words_by_pair"].get(
            (source, target),
            {"original": 0, "translated": 0, "verified": 0, "pending": 0},
        )
        linhas.append(
            f"  - {language_label(source)} -> {target}: {count} | "
            f"verificadas: {verified} | pendentes: {pending} | "
            f"QA: {resumo_qa['warning_rows']}"
        )
        linhas.append(
            f"      palavras: {palavras['original']} no original, "
            f"{palavras['translated']} na traducao"
        )

    # Por obra, e depois do par de idiomas: e a contagem que responde "quanto
    # falta do capitulo 7", que o total por idioma nunca respondeu (ROADMAP 18).
    linhas.extend([
        "",
        "Por arquivo de origem (obra):",
        format_file_progress(stats["per_file"]),
        "",
        "Atividade de revisao por dia:",
        format_daily_activity(stats["daily"]),
        "",
        "Ultimas execucoes (a primeira e a que \"Reverter execucao\" desfaz):",
        format_translation_runs(stats.get("runs") or []),
    ])
    return "\n".join(linhas)


def stats_tables(stats):
    """As tres tabelas do relatorio, prontas para virar CSV (ROADMAP 22.12).

    `[(titulo, cabecalho, linhas)]`, e nao um CSV: montar o arquivo e da janela,
    que e quem sabe onde ele vai. Aqui fica so o RECORTE — quais das estruturas
    que `collect_database_stats` devolve valem uma planilha.

    Sao as tres que respondem a perguntas de orcamento e de prazo: quanto falta
    de cada obra, quantas palavras por par de idiomas, e quanto se revisou por
    dia. O resto do relatorio e total e texto corrido, e o `.txt` ja o entrega.

    Pura: nao abre banco, nao abre janela.
    """
    por_arquivo = [
        (arquivo, posicoes, comentarios, verificadas, pendentes, avisos)
        for arquivo, posicoes, comentarios, verificadas, pendentes, avisos
        in stats.get("per_file") or []
    ]
    palavras = [
        (
            language_label(origem),
            destino,
            contagens.get("original", 0),
            contagens.get("translated", 0),
            contagens.get("verified", 0),
            contagens.get("pending", 0),
        )
        for (origem, destino), contagens in sorted(
            (stats.get("words_by_pair") or {}).items(),
            key=lambda item: (item[0][0] or "", item[0][1] or ""),
        )
    ]
    diario = [(dia, edicoes, palavras_dia) for dia, edicoes, palavras_dia in stats.get("daily") or []]

    return [
        (
            "progresso-por-obra",
            ["arquivo", "posicoes", "comentarios", "verificadas", "pendentes", "avisos"],
            por_arquivo,
        ),
        (
            "palavras-por-par",
            [
                "origem",
                "destino",
                "palavras_original",
                "palavras_traducao",
                "palavras_verificadas",
                "palavras_pendentes",
            ],
            palavras,
        ),
        ("atividade-por-dia", ["dia", "edicoes", "palavras"], diario),
    ]


RUN_OUTCOME_LABELS = {
    "running": "em andamento",
    "completed": "concluída",
    "failed": "concluída com falhas",
    "canceled": "cancelada",
    "aborted": "interrompida pela API",
    "crashed": "morreu sem terminar",
}


def describe_translation_run(run):
    """Uma execucao em uma linha: "#12  2026-09-15 19:14  concluída  en -> pt
    3 arquivo(s)  412 inseridas  0 falhas  google-gtx". Pura; e o que o
    relatorio de estatisticas lista e o que a pergunta de "Reverter" mostra."""
    quando = (run.get("started_at") or "")[:16].replace("T", " ")
    origem = run.get("source_language") or ""
    par = f"{language_label(origem)} -> {run.get('target_language') or ''}"
    return (
        f"#{run['id']}  {quando}  {RUN_OUTCOME_LABELS.get(run['outcome'], run['outcome'])}  "
        f"{par}  {len(run.get('files') or [])} arquivo(s)  "
        f"{run.get('inserted_count') or 0} inserida(s)  "
        f"{run.get('failed_count') or 0} falha(s)  {run.get('provider') or ''}"
    ).rstrip()


def format_translation_runs(runs, indent="  "):
    if not runs:
        return f"{indent}(nenhuma execução registrada desde a versão 10 do banco)"
    return "\n".join(f"{indent}{describe_translation_run(run)}" for run in runs)
