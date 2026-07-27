"""Politica de retencao dos arquivos em `backups/`.

Cada salvamento do glossario copia o `Substituicoes.txt` inteiro (~334 KB) para
`backups/`, e nada nunca era removido: 213 arquivos e 68 MB em 4 dias de uso.
Aqui fica a decisao de o que descartar, separada da remocao em si para poder ser
testada sem tocar no disco.

Duas regras, nesta ordem:

1. **Quantidade** — so os `keep_count` mais novos sobrevivem; o resto sai
   independentemente da idade. E esta regra que segura o crescimento, porque o
   volume vem da frequencia de gravacao, nao da passagem do tempo.
2. **Idade** — dos que sobraram, sai quem for mais velho que `max_age_days`,
   exceto os `keep_minimum` mais novos. Sem esse piso, uma pasta parada por
   meses ficaria sem backup nenhum justamente quando ele e mais necessario.
"""

import os
import re
from datetime import datetime, timedelta

from .app_config import (
    BACKUP_KEEP_MINIMUM,
    BACKUP_MAX_AGE_DAYS,
    DATABASE_BACKUP_KEEP_COUNT,
    GLOSSARY_BACKUP_KEEP_COUNT,
    LOG_KEEP_COUNT,
    LOG_MAX_AGE_DAYS,
)


# Carimbo gravado no nome por quem cria o backup: "20260725-143012".
_TIMESTAMP_RE = re.compile(r"(\d{8}-\d{6})")
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
# Sufixo de desempate que `_unique_path` acrescenta quando dois backups caem no
# mesmo segundo: "-1", "-2", ...
_UNIQUENESS_RE = re.compile(r"^-(\d+)$")


def backup_timestamp(name):
    """Data de criacao lida do NOME do arquivo, ou `None` se nao houver.

    Deliberadamente nao usa `mtime`: `create_glossary_backup` copia com
    `shutil.copy2`, que preserva o mtime da origem. Todos os backups do
    glossario carregam a data do `Substituicoes.txt`, entao ordenar por mtime
    daria uma ordem arbitraria — e a ordem e o que decide quem e descartado.
    """
    match = _TIMESTAMP_RE.search(os.path.basename(str(name)))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), _TIMESTAMP_FORMAT)
    except ValueError:
        return None


def uniqueness_suffix(name):
    """Numero do desempate no nome; 0 quando o arquivo nao tem sufixo.

    Dois backups do mesmo segundo so se distinguem por ele, e a ordem importa
    porque decide quem e descartado primeiro. Comparar os nomes como texto
    daria a ordem errada: em `Substituicoes-20260725-120000.txt` vs
    `...-120000-2.txt`, o "." (0x2E) e maior que o "-" (0x2D), entao o arquivo
    SEM sufixo — o mais antigo dos tres — pareceria o mais novo.
    """
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    match = _TIMESTAMP_RE.search(stem)
    if not match:
        return 0
    suffix = _UNIQUENESS_RE.match(stem[match.end():])
    return int(suffix.group(1)) if suffix else 0


def is_backup_of_family(name, prefix, extension):
    """Diz se o arquivo foi gerado por um criador de backup especifico.

    `backups/` guarda as duas familias juntas (`.txt` do glossario e `.db` do
    banco). Sem esse filtro, salvar o glossario 30 vezes apagaria todos os
    backups do banco. Arquivos que o usuario tenha colocado ali por conta
    propria nao casam com familia nenhuma e nunca sao tocados.
    """
    base = os.path.basename(str(name))
    if prefix and not base.startswith(prefix):
        return False
    if extension and not base.lower().endswith(extension.lower()):
        return False
    return backup_timestamp(base) is not None


def select_backups_to_delete(
    names,
    keep_count=GLOSSARY_BACKUP_KEEP_COUNT,
    max_age_days=BACKUP_MAX_AGE_DAYS,
    keep_minimum=BACKUP_KEEP_MINIMUM,
    now=None,
    protected=(),
):
    """Decide quais backups descartar. Funcao pura: nao acessa o disco.

    `names` ja deve vir filtrado por familia (ver `is_backup_of_family`).
    Arquivos sem carimbo no nome sao ignorados — nunca entram na lista de
    remocao. `protected` guarda nomes que jamais podem sair (o backup recem
    criado, por exemplo), mas eles continuam ocupando posicao na contagem.

    Um limite `None` (ou <= 0) desliga a regra correspondente.
    """
    now = now or datetime.now()
    protected_names = {os.path.basename(str(item)) for item in protected}

    dated = []
    for name in names:
        stamp = backup_timestamp(name)
        if stamp is None:
            continue
        base = os.path.basename(str(name))
        dated.append((stamp, uniqueness_suffix(base), base, name))

    # Mais novo primeiro. Empate de segundo e resolvido pelo sufixo numerico,
    # que cresce com a ordem de criacao (ver `uniqueness_suffix`).
    dated.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    keep_minimum = max(0, keep_minimum or 0)
    cutoff = None
    if max_age_days is not None and max_age_days > 0:
        cutoff = now - timedelta(days=max_age_days)

    doomed = []
    for rank, (stamp, _suffix, base, name) in enumerate(dated):
        if base in protected_names:
            continue
        if keep_count is not None and keep_count > 0 and rank >= keep_count:
            doomed.append(name)
        elif cutoff is not None and stamp < cutoff and rank >= keep_minimum:
            doomed.append(name)

    return doomed


def prune_backups(
    backup_dir,
    prefix,
    extension,
    keep_count=GLOSSARY_BACKUP_KEEP_COUNT,
    max_age_days=BACKUP_MAX_AGE_DAYS,
    keep_minimum=BACKUP_KEEP_MINIMUM,
    now=None,
    protected=(),
):
    """Aplica a politica em `backup_dir` e devolve os caminhos removidos.

    Nunca levanta: a limpeza e um efeito secundario da criacao de um backup, e
    um arquivo em uso ou sem permissao nao pode derrubar o backup que acabou de
    ser gravado.
    """
    if not backup_dir or not os.path.isdir(backup_dir):
        return []

    try:
        candidates = [
            name
            for name in os.listdir(backup_dir)
            if is_backup_of_family(name, prefix, extension)
            and os.path.isfile(os.path.join(backup_dir, name))
        ]
    except OSError:
        return []

    removed = []
    for name in select_backups_to_delete(
        candidates,
        keep_count=keep_count,
        max_age_days=max_age_days,
        keep_minimum=keep_minimum,
        now=now,
        protected=protected,
    ):
        target = os.path.join(backup_dir, name)
        try:
            os.remove(target)
        except OSError:
            continue
        removed.append(target)

    return removed


def prune_glossary_backups(backup_dir, stem, **kwargs):
    """Retencao dos backups do glossario (`<stem>-<carimbo>.txt`)."""
    kwargs.setdefault("keep_count", GLOSSARY_BACKUP_KEEP_COUNT)
    return prune_backups(backup_dir, f"{stem}-", ".txt", **kwargs)


def prune_database_backups(backup_dir, stem, **kwargs):
    """Retencao dos backups do banco (`<stem>-backup-<carimbo>.db`).

    O limite e menor que o do glossario porque cada copia e o banco inteiro.
    """
    kwargs.setdefault("keep_count", DATABASE_BACKUP_KEEP_COUNT)
    return prune_backups(backup_dir, f"{stem}-backup-", ".db", **kwargs)


def prune_log_files(log_dir, **kwargs):
    """Retencao de `logs/` (`traducao-<carimbo>.log`).

    Os logs sempre tiveram o mesmo formato de carimbo dos backups, mas com
    UNDERSCORE (`traducao_20260725_143012.log`), e `_TIMESTAMP_RE` espera hifen.
    Em vez de parametrizar o separador, os logs novos passaram a usar o formato
    dos backups. Os antigos deixam de casar com o padrao e, pela regra "nada
    fora do padrao e apagado", **sobrevivem** — que e o comportamento certo:
    uma politica de retencao nova nao deve estrear apagando o passado do
    usuario.
    """
    kwargs.setdefault("keep_count", LOG_KEEP_COUNT)
    kwargs.setdefault("max_age_days", LOG_MAX_AGE_DAYS)
    return prune_backups(log_dir, "traducao-", ".log", **kwargs)
