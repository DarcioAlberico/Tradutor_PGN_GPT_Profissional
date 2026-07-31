import csv
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from xml.sax.saxutils import escape as xml_escape

from . import __version__
from .app_config import language_label
from .chess_notation import fix_move_notation, supports_notation
from .database import (
    MoveNotationCanceled,
    QUALITY_VERSION_KEY,
    QualityReevaluationCanceled,
    WordCountCanceled,
    adopt_unknown_source_language,
    analyze_automatic_translation_updates,
    analyze_move_notation_updates,
    apply_automatic_translation_updates,
    apply_move_notation_updates,
    clear_all_translations,
    count_words_by_pair,
    fetch_export_rows,
    fetch_review_rows,
    get_daily_review_activity,
    get_database_stats,
    get_quality_heuristics_version,
    initialize_database,
    overwrite_translation_by_id,
    quality_heuristics_are_current,
    reevaluate_quality_warnings,
    save_translation,
    set_db_metadata,
    set_translation_verified_by_id,
)
from .backup_retention import prune_database_backups
from .background_task import TaskCanceled, run_with_progress
from .confirm_dialog import ask_typed_confirmation
from .database import AutomaticRulesCanceled
from .glossario import (
    GLOSSARY_RULE_AUTOMATIC,
    GLOSSARY_RULE_CLEANUP,
    GLOSSARY_RULE_SUGGESTION,
    apply_automatic_substitutions,
    create_glossary_backup,
    load_automatic_substitutions,
    load_glossary_entry_details,
    load_interactive_substitutions,
    save_glossary_entries,
)
from .review_quality import QUALITY_HEURISTICS_VERSION, summarize_quality_warnings
from .stats_window import StatsWindow


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

# Quantas obras o resumo lista por extenso. O resumo e um `messagebox`, que nao
# rola nem se copia (ROADMAP 19, item 7): uma pasta com 200 capitulos daria um
# dialogo mais alto que a tela e o usuario perderia as linhas de cima, que sao as
# que ele leu primeiro. O corte fica dito na ultima linha.
FILE_PROGRESS_LIMIT = 20


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
    """Copia o banco para `backups/` e devolve o caminho da copia.

    **A origem e aberta com `sqlite3.connect` puro, e nao com
    `initialize_database`.** A diferenca e o proposito de um backup: aquela
    funcao roda a migracao de schema e o backfill do `quality_warning`, entao a
    copia "de seguranca" feita antes de uma restauracao ALTERAVA o banco de
    trabalho antes de copia-lo — e capturava o estado pos-migracao. Se a migracao
    fosse a causa do problema que o usuario quer desfazer, o backup dela nao
    tinha mais volta. Um backup copia o que esta la, como esta.

    O `open_database` tambem esta fora por outro motivo: ele grava `journal_mode
    = WAL` no arquivo. Num banco antigo em modo `delete`, o "backup" mudaria o
    modo do original. Ler nao precisa de nenhum dos dois — a API de backup do
    SQLite ve o banco logico, `-wal` incluido (ver `_copy_database`).
    """
    source_path = Path(db_path)
    if backup_dir is None:
        backup_dir = source_path.parent / "backups"
    else:
        backup_dir = Path(backup_dir)

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = _unique_backup_path(backup_dir, source_path.stem, timestamp)

    source_conn = sqlite3.connect(str(source_path))
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
        # Subconjunto de `unchanged`: as linhas que o CSV ALTERARIA e que o modo
        # padrao deixa como estao (garantia T1). Contadas em separado porque a
        # previa precisa dizer o que a importacao vai deixar de fazer — era esse
        # o buraco: 300 traducoes corrigidas na planilha voltavam como "sem
        # alteracao" e o usuario descobria depois do trabalho feito.
        "overwritable": 0,
        # Das acima, quantas estao marcadas como verificadas. Sobrescrever uma
        # dessas apaga revisao humana, e e a unica parte desta operacao que o
        # backup nao devolve de graca.
        "overwritable_verified": 0,
        "overwritten": 0,
        # Linhas ja preenchidas que o CSV marca como verificadas e que ainda nao
        # estao. Sao aplicadas apenas no modo de sobrescrever, entao a previa as
        # conta em separado para nao prometer no padrao o que so o outro modo faz.
        "verified_on_existing": 0,
        "skipped": 0,
        "verified_applied": 0,
        "backup_path": backup_path,
    }


def _existing_row(cursor, original_comment, target_language, source_language=""):
    """`(id, traducao, verified)` da linha do CSV, ou `None`.

    Devolve as tres coisas de uma consulta so porque o modo de sobrescrever
    precisa das tres: o id para gravar, o texto para saber se ha o que gravar, e o
    `verified` anterior para nao contar como "verificada aplicada" uma linha que
    ja estava verificada.
    """
    return cursor.execute(
        """
        SELECT id, translated_comment, verified
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
    """Previa da importacao. `csv_rows` evita reler o arquivo (ROADMAP 2.10).

    Nao depende do modo de gravacao: ela conta as duas coisas de uma passagem so
    — o que a importacao padrao faria e o que ela deixaria de fazer
    (`overwritable`). E o que permite oferecer a sobrescrita no mesmo dialogo em
    que os numeros aparecem, em vez de fazer o usuario escolher antes de ver.
    """
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

            existing = _existing_row(
                cursor, original, target_language, row["source_language"]
            )
            if existing is None:
                stats["inserted"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
                continue

            _row_id, existing_translation, existing_verified = existing
            if existing_translation is None or existing_translation == "":
                stats["filled_empty"] += 1
                if row["verified"]:
                    stats["verified_applied"] += 1
            else:
                stats["unchanged"] += 1
                # Texto identico nao e uma sobrescrita: nao ha o que gravar, nem
                # em modo de sobrescrever. Contar essas linhas inflaria o numero
                # do dialogo com o que a exportacao devolveu igual — que num CSV
                # exportado e corrigido em parte e a grande maioria.
                if existing_translation != translated:
                    stats["overwritable"] += 1
                    if existing_verified == 1:
                        stats["overwritable_verified"] += 1
                if row["verified"] and existing_verified != 1:
                    stats["verified_on_existing"] += 1
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
    overwrite_existing=False,
):
    """Aplica a importacao. `csv_rows` evita reler o arquivo (ROADMAP 2.10).

    Reaproveitar as linhas da previa nao e so economia: e o que garante que o
    usuario confirmou exatamente o que sera gravado. Lendo duas vezes, um arquivo
    alterado entre a previa e o "Sim" aplicaria numeros diferentes dos exibidos.

    `overwrite_existing` e a decisao do usuario sobre as linhas que ja tem
    traducao. O padrao continua sendo T1 — nunca sobrescrever —, e ligado ele
    passa por `overwrite_translation_by_id`, que reavalia o aviso de qualidade
    (R6) e registra no historico (R2). O flag e explicito, e nao inferido do
    conteudo do CSV: um arquivo que difere em 300 linhas nao diz se aquilo e
    correcao ou uma exportacao velha.

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
            elif not overwrite_existing:
                stats["unchanged"] += 1
            else:
                # `save_translation` respeitou T1 e nao gravou nada; a
                # sobrescrita e um segundo passo, sobre a linha que ele
                # encontrou. Deixar as duas coisas em funcoes separadas e o que
                # mantem T1 valendo para o worker, que nunca chama esta.
                existente = _existing_row(
                    cursor, original, target_language, row["source_language"]
                )
                if existente is None:  # pragma: no cover - defensivo
                    stats["unchanged"] += 1
                    continue

                comment_id, existing_translation, existing_verified = existente
                ja_verificada = existing_verified == 1

                if overwrite_translation_by_id(
                    cursor, comment_id, translated, verified=row["verified"]
                ):
                    stats["overwritten"] += 1
                    # Contada aqui, e nao no bloco de baixo: a sobrescrita ja
                    # gravou o `verified` na mesma operacao. E so quando a linha
                    # NAO estava verificada — reafirmar o que ja valia nao e uma
                    # marca aplicada, e contar isso faria o numero do resultado
                    # nao bater com o da previa.
                    if row["verified"] and not ja_verificada:
                        stats["verified_applied"] += 1
                else:
                    # Texto igual ao que estava: nada a sobrescrever. Continua
                    # sendo "sem alteracao" — mas a coluna `verified` do CSV
                    # ainda pode ter algo a dizer, e era ela a outra metade do
                    # beco: editada na planilha, era descartada em silencio
                    # porque so linhas inseridas ou preenchidas a recebiam.
                    # Somente PROMOVE; ver `overwrite_translation_by_id`.
                    stats["unchanged"] += 1
                    if row["verified"]:
                        stats["verified_applied"] += set_translation_verified_by_id(
                            cursor,
                            comment_id,
                            True,
                        )

            if save_status in {"inserted", "filled_empty"} and row["verified"]:
                existente = _existing_row(
                    cursor, original, target_language, row["source_language"]
                )
                if existente is not None:
                    stats["verified_applied"] += set_translation_verified_by_id(
                        cursor,
                        existente[0],
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
    # O id abre a lista (ROADMAP 19, item 8): ele e a unica coluna que identifica a
    # linha sem depender do texto, e e o que torna o round-trip pela planilha
    # conferivel. A importacao NAO o usa para casar — ver a SPEC, secao 10.
    "id",
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
    # Status de revisao e nota (ROADMAP 19, item 12). Exportados para que nada do que
    # o revisor escreveu fique preso no programa; a importacao NAO os le de volta —
    # ver o limite na secao 10 da SPEC.
    "review_status",
    "reviewer_note",
]


def export_translations_to_csv(
    db_path,
    save_path,
    progress_callback=None,
    should_cancel=None,
    only_ids=None,
):
    """Escreve o CSV de traducoes. Devolve quantas linhas sairam.

    `only_ids` exporta so aquelas linhas — e a selecao em lote do editor (ROADMAP
    19, item 9). O total do progresso passa a ser o tamanho da selecao, senao a
    barra iria de 30 linhas contra 200 mil e ficaria parada no zero.

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
        if only_ids is None:
            total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        else:
            total = len(only_ids)
        if progress_callback is not None:
            progress_callback(0, total)

        escritas = 0
        try:
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(EXPORT_CSV_HEADERS)

                rows = fetch_export_rows(cursor, only_ids=only_ids)
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


# O idioma de uma linha sem origem declarada, no TMX. `und` e o codigo ISO 639-2
# de "indeterminado", e e a resposta certa para o balde que a secao 9.2 criou:
# `xml:lang=""` nao e valido, inventar `en` seria mentir, e pular as linhas
# deixaria de fora a maioria de um banco anterior aquela versao.
TMX_UNKNOWN_LANGUAGE = "und"

# O `srclang` do cabecalho. O acervo tem varios idiomas de origem ao mesmo tempo,
# e `*all*` e o valor que o proprio padrao TMX define para isso — cada `<tu>` diz o
# seu par nos `<tuv>`. Declarar um idioma so faria toda ferramenta importar o acervo
# inteiro como se fosse dele.
TMX_SOURCE_LANGUAGE = "*all*"

# Caracteres que o XML 1.0 nao aceita nem escapados: os controles C0, menos tab,
# LF e CR. Um deles no meio de um comentario produz um arquivo que nenhum parser
# abre — e o erro apareceria na ferramenta do usuario, nao aqui.
_XML_FORBIDDEN_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def tmx_language(code):
    return code or TMX_UNKNOWN_LANGUAGE


def tmx_segment(text):
    """Texto pronto para dentro de um `<seg>`: escapado e sem controle proibido."""
    return xml_escape(_XML_FORBIDDEN_RE.sub("", text or ""))


def tmx_translation_unit(row):
    """Um `<tu>` a partir da linha do banco, ou `None` se ela nao serve.

    A linha vem na ordem de `fetch_export_rows`. Sem traducao nao ha unidade de
    traducao: uma memoria com o lado de destino vazio nao ajuda ferramenta nenhuma
    e polui a busca por concordancia de quem a importar.

    O `tuid` e o `id` do banco (ROADMAP 19, item 8), que e o que permite reconhecer
    a mesma unidade depois de uma ida e volta pelo OmegaT.
    """
    (
        row_id, original, translated, source_language, target_language,
        _verified, created_at, updated_at, _verified_at,
    ) = row[:9]
    if not (translated or "").strip():
        return None

    # `changedate`/`creationdate` no formato do TMX (`YYYYMMDDThhmmssZ`) sairiam de
    # uma conversao dos carimbos do SQLite, que sao hora LOCAL sem fuso. Convertidos
    # como se fossem UTC, ficariam com o erro do fuso embutido; declarados como
    # locais, o padrao nao tem onde dizer isso. Ficam de fora, e o `id` continua
    # sendo o que identifica a unidade — ver o limite na SPEC.
    return (
        f'  <tu tuid="{xml_escape(str(row_id))}">\n'
        f'   <tuv xml:lang="{xml_escape(tmx_language(source_language))}">'
        f"<seg>{tmx_segment(original)}</seg></tuv>\n"
        f'   <tuv xml:lang="{xml_escape(tmx_language(target_language))}">'
        f"<seg>{tmx_segment(translated)}</seg></tuv>\n"
        f"  </tu>\n"
    )


def export_translations_to_tmx(
    db_path,
    save_path,
    progress_callback=None,
    should_cancel=None,
):
    """Escreve o acervo como TMX 1.4. Devolve quantas unidades sairam.

    O acervo revisado **e** uma memoria de traducao (ROADMAP 19, item 8), e ate aqui
    ela vivia num formato que so este programa le. TMX 1.4 abre em OmegaT, Trados e
    memoQ, e transforma o trabalho acumulado em ativo portavel.

    Escrito a mao, em blocos, e nao com `ElementTree`: montar a arvore de 200 mil
    unidades em memoria antes de gravar a primeira e exatamente o que o item 2.9 do
    ROADMAP tirou da exportacao de CSV. Aqui o custo seria maior, porque cada `<tu>`
    e um objeto com quatro filhos.

    Um arquivo cortado pelo meio e apagado, como o CSV: um TMX truncado nao fecha a
    tag `</body>`, entao ele nao abre em ferramenta nenhuma — mas o usuario so
    descobre isso na ferramenta, depois de ter contado com o arquivo.
    """
    conn = initialize_database(db_path)
    try:
        cursor = conn.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        if progress_callback is not None:
            progress_callback(0, total)

        lidas = 0
        unidades = 0
        try:
            with open(save_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<tmx version="1.4">\n'
                    ' <header creationtool="PGN Tradutor Pro"\n'
                    # A versao de verdade, e nao um "1.0" congelado: este
                    # cabecalho viaja para dentro do OmegaT/Trados de quem
                    # importar a memoria, e e por ele que se descobre com qual
                    # versao do programa um acervo foi exportado (ROADMAP 21.6).
                    f'         creationtoolversion="{__version__}"\n'
                    '         segtype="paragraph"\n'
                    '         o-tmf="PGN Tradutor Pro"\n'
                    '         adminlang="en"\n'
                    f'         srclang="{TMX_SOURCE_LANGUAGE}"\n'
                    '         datatype="plaintext"/>\n'
                    " <body>\n"
                )
                rows = fetch_export_rows(cursor)
                while True:
                    if should_cancel is not None and should_cancel():
                        raise TaskCanceled()
                    bloco = rows.fetchmany(EXPORT_CHUNK)
                    if not bloco:
                        break
                    unidades_do_bloco = [
                        tmx_translation_unit(linha) for linha in bloco
                    ]
                    f.write("".join(u for u in unidades_do_bloco if u))
                    unidades += sum(1 for u in unidades_do_bloco if u)
                    lidas += len(bloco)
                    if progress_callback is not None:
                        progress_callback(lidas, total)
                f.write(" </body>\n</tmx>\n")
        except BaseException:
            Path(save_path).unlink(missing_ok=True)
            raise
    finally:
        conn.close()

    return unidades


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
