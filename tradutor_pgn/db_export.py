"""CSV e TMX do banco de traducoes — a parte PURA (ROADMAP 28.11).

Ler e analisar um CSV de importacao, gravar as linhas no banco, exportar CSV
e TMX: nada aqui abre janela nem dialogo. `db_tools` continua sendo a fachada
(re-exporta tudo isto e guarda a orquestracao com `messagebox`,
`filedialog` e `run_with_progress`), pela regra `app.py -> app_actions.py`:
quem importava de `db_tools` continua importando de la.
"""

import csv
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import __version__
from .database import (
    fetch_export_rows,
    initialize_database,
    overwrite_translation_by_id,
    save_translation,
    set_translation_verified_by_id,
)
from .background_task import TaskCanceled


# Paginas por passo da copia do SQLite. E o intervalo entre duas chances de
# reportar progresso ou de desistir: menor da uma barra mais fluida e mais
# chamadas de callback. 2048 paginas sao ~8 MB, que num banco de 80 MB dao ~10
# atualizacoes.
from .db_backup import create_database_backup



# Linhas por bloco na exportacao. O `csv.writerows` continua recebendo um bloco
# inteiro de uma vez — escrever linha a linha em Python custaria a economia que
# o item 2.9 conquistou.
EXPORT_CHUNK = 5000

# Linhas entre duas verificacoes de cancelamento na importacao.
IMPORT_PROGRESS_EVERY = 200


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
