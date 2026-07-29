"""Arquivos que ficaram com comentarios sem traduzir, para reprocessar so eles.

Terminada uma execucao com falhas, a orientacao era "reprocesse os arquivos".
Isso funciona, mas cobra uma passagem inteira: os comentarios que deram certo
voltam pelo cache (rapido, mas nao de graca) e os que falharam sao reencontrados
por varredura de tudo. Numa pasta com dezenas de PGN, reprocessar por causa de
dois arquivos e desproporcional.

O worker sabe exatamente quais arquivos ficaram devendo. Guardar essa lista e o
que transforma a reexecucao numa operacao de minutos (ROADMAP 7.3).

**Por que arquivos e nao comentarios.** Seria possivel guardar cada comentario
que falhou, mas nao adiantaria: o worker reextrai os comentarios do arquivo de
qualquer jeito, e os que deram certo saem do cache sem tocar a rede. O ganho real
vem de nao abrir os arquivos que nao devem nada — e para isso a lista de arquivos
basta. Menos estado persistido, menos coisa para ficar obsoleta.

Este modulo nao importa Tk: decidir o que reprocessar e separado de perguntar.
"""

import os

from .settings import load_settings, update_settings


FAILED_RUN_KEY = "failed_translation"


def build_failed_run_record(
    target_language,
    failed_files,
    failed_count,
    when=None,
    source_language="",
):
    """O registro a persistir, ou `None` quando nao ha o que reprocessar.

    `None` e o resultado certo para uma execucao limpa: nao existe "registro
    vazio", existe nao haver registro. Quem grava usa isso para apagar o antigo.

    O idioma de ORIGEM entra pela mesma razao que o de destino ja entrava: a
    lista foi montada traduzindo um par de idiomas, e reprocessa-la com outro par
    gravaria as traducoes numa gaveta diferente da dos comentarios que deram
    certo — o arquivo sairia dividido entre dois pares sem ninguem ter pedido.
    """
    arquivos = sorted({str(caminho) for caminho in (failed_files or []) if caminho})
    if not arquivos or not failed_count:
        return None
    return {
        "target_language": target_language,
        "source_language": source_language or "",
        "files": arquivos,
        "failed_count": int(failed_count),
        "when": when,
    }


def normalize_failed_run_record(record):
    """Devolve o registro so se ele tiver o minimo utilizavel.

    O arquivo de configuracoes e JSON editavel a mao e sobrevive a versoes do
    programa. Um registro truncado nao pode virar um reprocessamento de lista
    vazia, que pareceria ter funcionado.
    """
    if not isinstance(record, dict):
        return None
    arquivos = record.get("files")
    idioma = record.get("target_language")
    if not isinstance(arquivos, list) or not arquivos:
        return None
    if not isinstance(idioma, str) or not idioma:
        return None
    limpos = [str(caminho) for caminho in arquivos if caminho]
    if not limpos:
        return None
    # A origem e opcional na leitura: um registro gravado por uma versao anterior
    # nao a tem, e trata-lo como invalido descartaria uma lista de falhas
    # perfeitamente boa. Ausente, vale "nao informado" — que e exatamente o que
    # aquela execucao usou.
    origem = record.get("source_language")
    if not isinstance(origem, str):
        origem = ""
    return {
        "target_language": idioma,
        "source_language": origem,
        "files": limpos,
        "failed_count": record.get("failed_count") or 0,
        "when": record.get("when"),
    }


def split_existing_files(files, exists=os.path.exists):
    """`(ainda no disco, sumidos)`. O usuario pode ter movido ou apagado."""
    presentes = []
    ausentes = []
    for caminho in files or []:
        (presentes if exists(caminho) else ausentes).append(caminho)
    return presentes, ausentes


def describe_failed_run(record, exists=os.path.exists):
    """Texto de confirmacao, ja contando o que sumiu do disco."""
    record = normalize_failed_run_record(record)
    if record is None:
        return ""

    presentes, ausentes = split_existing_files(record["files"], exists)
    linhas = [
        f"Da ultima execucao ficaram {record['failed_count']} comentario(s) sem "
        f"traduzir, em {len(record['files'])} arquivo(s).",
        f"Idioma: {record['source_language'] or 'detectar'} -> "
        f"{record['target_language']}",
        "",
    ]
    linhas.extend(f"  - {os.path.basename(caminho)}" for caminho in presentes[:10])
    if len(presentes) > 10:
        linhas.append(f"  ... e mais {len(presentes) - 10}")
    if ausentes:
        linhas.append("")
        linhas.append(
            f"{len(ausentes)} arquivo(s) da lista nao estao mais no disco e serao "
            f"ignorados."
        )
    if not presentes:
        linhas.append("")
        linhas.append("Nenhum arquivo da lista existe mais.")
    return "\n".join(linhas)


def load_failed_run(path=None):
    settings = load_settings(path)
    return normalize_failed_run_record(settings.get(FAILED_RUN_KEY))


def save_failed_run(record, path=None):
    """Grava o registro, ou o remove quando `record` e `None`.

    Passa por `update_settings` (leitura do disco imediatamente antes de gravar)
    para nao apagar o que outra janela tenha escrito nesse meio tempo — os
    rascunhos de traducao vivem no mesmo arquivo (garantia R4).
    """
    def mutator(settings):
        if record is None:
            settings.pop(FAILED_RUN_KEY, None)
        else:
            settings[FAILED_RUN_KEY] = record
        return record

    return update_settings(mutator, path)


def clear_failed_run(path=None):
    return save_failed_run(None, path)
