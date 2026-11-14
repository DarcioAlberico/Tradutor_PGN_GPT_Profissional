"""Prazo de espera compartilhado por processos na mesma pasta de dados."""

import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DEFAULT_REQUESTS_PER_MINUTE = 60
DEFAULT_REQUESTS_PER_DAY = 3000
MAX_REQUESTS_PER_MINUTE = 600
MAX_REQUESTS_PER_DAY = 100000


class ReservationDelay(float):
    """Prazo numérico compatível com reserve, com motivo para observabilidade."""

    def __new__(cls, seconds, reason):
        result = super().__new__(cls, seconds)
        result.reason = reason
        return result


class GoogleCooldown:
    """Persiste prazos, limites e horários de tentativas, sem textos ou chaves."""

    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=5)
        try:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS cooldown (id INTEGER PRIMARY KEY CHECK (id=1), deadline REAL NOT NULL)'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS quota_limits (id INTEGER PRIMARY KEY CHECK (id=1), '
                'per_minute INTEGER NOT NULL, per_day INTEGER NOT NULL)'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS request_reservations (occurred_at REAL NOT NULL)'
            )
            connection.execute(
                'CREATE INDEX IF NOT EXISTS request_reservations_time ON request_reservations (occurred_at)'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS quota_clock (id INTEGER PRIMARY KEY CHECK (id=1), '
                'wall REAL NOT NULL, monotonic REAL NOT NULL)'
            )
            return connection
        except BaseException:
            connection.close()
            raise

    def defer(self, seconds, *, now=None):
        if math.isnan(seconds) or seconds < 0:
            raise ValueError('invalid cooldown')
        with closing(self._connect()) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                current = time.time() if now is None else now
                monotonic = time.monotonic() if now is None else now
                current = self._check_clock(connection, current, monotonic)
                deadline = current + seconds
                connection.execute(
                    'INSERT INTO cooldown (id, deadline) VALUES (1, ?) '
                    'ON CONFLICT(id) DO UPDATE SET deadline = MAX(deadline, excluded.deadline)',
                    (deadline,),
                )

    def remaining(self, *, now=None):
        with closing(self._connect()) as connection:
            row = connection.execute('SELECT deadline FROM cooldown WHERE id=1').fetchone()
        if row is None:
            return 0.0
        deadline = float(row[0])
        if math.isnan(deadline):
            raise ValueError('invalid cooldown state')
        return max(0.0, deadline - (time.time() if now is None else now))

    @staticmethod
    def _validate_limits(per_minute, per_day):
        if (type(per_minute) is not int or type(per_day) is not int or
                not 1 <= per_minute <= MAX_REQUESTS_PER_MINUTE or
                not 1 <= per_day <= MAX_REQUESTS_PER_DAY):
            raise ValueError('invalid Google request limits')

    def get_limits(self):
        with closing(self._connect()) as connection:
            row = connection.execute('SELECT per_minute, per_day FROM quota_limits WHERE id=1').fetchone()
        if row is None:
            return DEFAULT_REQUESTS_PER_MINUTE, DEFAULT_REQUESTS_PER_DAY
        self._validate_limits(*row)
        return row[0], row[1]

    def configure_limits(self, per_minute, per_day):
        self._validate_limits(per_minute, per_day)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(
                    'INSERT INTO quota_limits (id, per_minute, per_day) VALUES (1, ?, ?) '
                    'ON CONFLICT(id) DO UPDATE SET per_minute=excluded.per_minute, per_day=excluded.per_day',
                    (per_minute, per_day),
                )

    @staticmethod
    def _check_clock(connection, current, monotonic):
        if not math.isfinite(current) or not math.isfinite(monotonic):
            raise ValueError('invalid clock value')
        row = connection.execute('SELECT wall, monotonic FROM quota_clock WHERE id=1').fetchone()
        effective = current
        if row:
            wall, previous_monotonic = map(float, row)
            if not math.isfinite(wall) or not math.isfinite(previous_monotonic):
                raise ValueError('invalid clock state')
            elapsed = monotonic - previous_monotonic
            if elapsed < 0 or current < wall - 2 or current - wall > elapsed + 5:
                # Após reinício ou mudança do relógio, preserve as reservas por
                # uma nova janela: evita liberação prematura quando não sabemos
                # quanto tempo real transcorreu.
                connection.execute('UPDATE request_reservations SET occurred_at=?', (current,))
                cooldown = connection.execute('SELECT deadline FROM cooldown WHERE id=1').fetchone()
                if cooldown:
                    deadline = float(cooldown[0])
                    if math.isnan(deadline):
                        raise ValueError('invalid cooldown state')
                    remaining = max(0.0, deadline - wall)
                    connection.execute('UPDATE cooldown SET deadline=? WHERE id=1', (current + remaining,))
            else:
                # Pequenos adiantamentos não podem se acumular nem liberar uma
                # reserva antes do tempo monotônico efetivamente transcorrido.
                effective = min(current, wall + elapsed)
        connection.execute(
            'INSERT INTO quota_clock (id, wall, monotonic) VALUES (1, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET wall=excluded.wall, monotonic=excluded.monotonic',
            (effective, monotonic),
        )
        return effective

    def reserve(self, *, now=None, monotonic_now=None):
        """Reserva uma tentativa ou retorna quantos segundos aguardar."""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                current = time.time() if now is None else now
                monotonic = (time.monotonic() if now is None else now) if monotonic_now is None else monotonic_now
                current = self._check_clock(connection, current, monotonic)
                row = connection.execute('SELECT deadline FROM cooldown WHERE id=1').fetchone()
                deadline = float(row[0]) if row else 0.0
                if math.isnan(deadline):
                    raise ValueError('invalid cooldown state')
                cooldown = max(0.0, deadline - current) if row else 0.0
                limits = connection.execute('SELECT per_minute, per_day FROM quota_limits WHERE id=1').fetchone()
                per_minute, per_day = limits or (DEFAULT_REQUESTS_PER_MINUTE, DEFAULT_REQUESTS_PER_DAY)
                self._validate_limits(per_minute, per_day)
                connection.execute('DELETE FROM request_reservations WHERE occurred_at <= ?', (current - 86400,))
                delay = cooldown
                quota_blocked = False
                for window, limit in ((60, per_minute), (86400, per_day)):
                    row = connection.execute(
                        'SELECT occurred_at FROM request_reservations WHERE occurred_at > ? '
                        'ORDER BY occurred_at DESC LIMIT 1 OFFSET ?', (current - window, limit - 1)
                    ).fetchone()
                    if row:
                        quota_blocked = True
                        delay = max(delay, float(row[0]) + window - current)
                if delay > 0:
                    reason = 'both' if cooldown > 0 and quota_blocked else 'cooldown' if cooldown > 0 else 'quota'
                    return ReservationDelay(delay, reason)
                connection.execute('INSERT INTO request_reservations (occurred_at) VALUES (?)', (current,))
                return 0.0

    def wait(self, cancel_flag=None, on_wait=None, on_delay=None):
        """False indica cancelamento ou prazo indefinido; erros não liberam envio."""
        announced = False
        while True:
            if cancel_flag is not None and cancel_flag.is_set():
                return False
            remaining = self.reserve()
            if cancel_flag is not None and cancel_flag.is_set():
                return False
            if remaining <= 0:
                return True
            if not announced and on_wait is not None:
                on_wait()
                announced = True
            if not math.isfinite(remaining):
                return False
            delay = min(remaining, 1.0)
            wait = getattr(cancel_flag, 'wait', None)
            started = time.monotonic() if on_delay is not None else 0.0
            try:
                if callable(wait):
                    if wait(delay):
                        return False
                else:
                    time.sleep(delay)
            finally:
                if on_delay is not None:
                    on_delay(getattr(remaining, 'reason', None), max(0.0, time.monotonic() - started))
