"""O log do programa passa pelo `logging` da biblioteca padrao (ROADMAP 28.11).

O que NAO muda: `app.log_message(texto)` continua sendo a porta — todo modulo
e todo teste falam por ela —, a fila `app.log_queue` continua sendo a ponte
de thread para o widget (C1: o worker escreve de outra thread, e o Tk drena
na dele), e o arquivo da execucao continua com o mesmo `[HH:MM:SS] texto`.

O que o `logging` acrescenta, e que a fila propria nao tinha:

- **Nivel por mensagem**, inferido do prefixo que o programa ja escreve:
  `[ERRO`/`[ABORTADO]` sao erro, `[FALHA]`/`[AVISO]`/`ATENCAO` sao aviso, o
  resto e informacao. Ninguem precisou trocar uma chamada.
- **`assertLogs`** nos testes, e um `Handler` unico com lock: antes duas
  threads podiam escrever o arquivo ao mesmo tempo.
- **O que as bibliotecas dizem.** O SDK da Anthropic e o `requests` avisam
  de retentativas e erros pelo `logging`, e antes ninguem ouvia: a partir de
  `WARNING`, o que qualquer biblioteca disser aparece no log do programa com
  o nome de quem falou (`[AVISO] anthropic._base_client: ...`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

LOGGER = logging.getLogger("tradutor_pgn")

# O que o programa ja escreve no comeco das mensagens, e o nivel que isso e.
PREFIX_LEVELS = (
    ("[ERRO", logging.ERROR),
    ("[ABORTADO]", logging.ERROR),
    ("[FALHA]", logging.WARNING),
    ("[AVISO]", logging.WARNING),
    ("ATENCAO", logging.WARNING),
)
# Bibliotecas de terceiros: so o que e aviso ou pior. O INFO delas e ruido
# (cada requisicao do SDK), e o DEBUG e de quem ligou `ANTHROPIC_LOG=debug`.
THIRD_PARTY_LEVEL = logging.WARNING
_LEVEL_LABELS = {logging.WARNING: "AVISO", logging.ERROR: "ERRO", logging.CRITICAL: "ERRO"}


def level_of(message: str) -> int:
    """O nivel de uma mensagem do programa, pelo prefixo dela."""
    texto = (message or "").lstrip(" -")
    for prefixo, nivel in PREFIX_LEVELS:
        if texto.startswith(prefixo):
            return nivel
    return logging.INFO


def format_record(record: logging.LogRecord) -> str:
    """O texto como vai para a tela e para o arquivo.

    As mensagens do programa saem como foram escritas. As de fora ganham o
    nivel em portugues e o nome de quem falou: um `[AVISO] urllib3...` no meio
    do log diz de onde veio, e o programa nunca escreve nesse formato.
    """
    texto = record.getMessage()
    if record.exc_info:
        texto += "\n" + logging.Formatter().formatException(record.exc_info)
    if _is_program_record(record):
        return texto
    rotulo = _LEVEL_LABELS.get(record.levelno, record.levelname)
    return f"[{rotulo}] {record.name}: {texto}"


def _is_program_record(record: logging.LogRecord) -> bool:
    return record.name == LOGGER.name or record.name.startswith(LOGGER.name + ".")


class AppLogHandler(logging.Handler):
    """Leva cada registro para a fila do widget e para o arquivo da execucao.

    `third_party_only`: o handler da raiz ignora os registros do proprio
    programa, que ja passaram pelo handler do logger `tradutor_pgn` — assim
    um `propagate` ligado por quem quer que seja nunca duplica uma linha.
    """

    def __init__(self, app: Any, level: int = logging.INFO, third_party_only: bool = False) -> None:
        super().__init__(level)
        self.app = app
        self.third_party_only = third_party_only

    def emit(self, record: logging.LogRecord) -> None:
        if self.third_party_only and _is_program_record(record):
            return
        texto = format_record(record)
        self.app.log_queue.put(texto)
        handle = getattr(self.app, "_log_file_handle", None)
        if handle is None:
            return
        try:
            handle.write(f"[{datetime.now().strftime('%H:%M:%S')}] {texto}\n")
            handle.flush()
        except (OSError, ValueError):
            # Disco cheio, arquivo fechado no meio: o log da tela continua, e
            # perder a copia em arquivo nao pode derrubar a execucao.
            pass


def install(app: Any) -> AppLogHandler:
    """Liga o log a este `app`; o handler de um app anterior sai.

    Dois handlers, porque sao dois niveis: o do programa (INFO, no logger
    `tradutor_pgn`, que nao propaga) e o dos terceiros (WARNING, na raiz).
    Um app por vez — a suite de janelas cria um por teste — e por isso os
    anteriores sao removidos, e nao acumulados.
    """
    raiz = logging.getLogger()
    for logger in (LOGGER, raiz):
        for antigo in list(logger.handlers):
            if isinstance(antigo, AppLogHandler):
                logger.removeHandler(antigo)
    handler = AppLogHandler(app, logging.INFO)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    LOGGER.addHandler(handler)
    raiz.addHandler(AppLogHandler(app, THIRD_PARTY_LEVEL, third_party_only=True))
    return handler


def log(message: str) -> None:
    """`app.log_message` por dentro: a mensagem, no nivel que o prefixo diz."""
    LOGGER.log(level_of(message), message)
