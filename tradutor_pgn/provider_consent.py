"""Consentimentos versionados, com gravação atômica entre processos."""

import sqlite3
from contextlib import closing
from pathlib import Path


class ConsentStore:
    def __init__(self, path):
        self.path = Path(path)

    def accepted(self, provider, version):
        if not self.path.exists():
            return False
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=5)) as conn:
            row = conn.execute('SELECT version FROM consents WHERE provider=?', (provider,)).fetchone()
        return row is not None and type(row[0]) is int and row[0] == version

    def accept(self, provider, version):
        with closing(sqlite3.connect(str(self.path), timeout=5)) as conn:
            with conn:
                conn.execute('CREATE TABLE IF NOT EXISTS consents (provider TEXT PRIMARY KEY, version INTEGER NOT NULL)')
                conn.execute(
                    'INSERT INTO consents (provider, version) VALUES (?, ?) '
                    'ON CONFLICT(provider) DO UPDATE SET version=excluded.version',
                    (provider, version),
                )
