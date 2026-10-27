"""Backup e restauracao do banco de traducoes — a parte PURA (ROADMAP 28.11).

A copia pela API de backup online do SQLite (consistente com o worker
escrevendo), o nome unico do arquivo, a validacao do que se restaura. Sem Tk;
a orquestracao com dialogos continua em `db_tools`, que re-exporta isto.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from .database import (
    initialize_database,
)
from .backup_retention import prune_database_backups
from .background_task import TaskCanceled


# Paginas por passo da copia do SQLite. E o intervalo entre duas chances de
# reportar progresso ou de desistir: menor da uma barra mais fluida e mais
# chamadas de callback. 2048 paginas sao ~8 MB, que num banco de 80 MB dao ~10
# atualizacoes.


BACKUP_PAGES_PER_STEP = 2048


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
