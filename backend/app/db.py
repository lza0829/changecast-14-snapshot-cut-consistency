from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import DATA_DIR, DB_FILENAME

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / DB_FILENAME


def connect() -> sqlite3.Connection:
    # isolation_level=None -> the driver does not open implicit transactions;
    # all write paths use explicit BEGIN IMMEDIATE / COMMIT so that a single
    # batch stays atomic and a reader can pin one committed snapshot.
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    # WAL lets a cut reader see the last committed projection while an
    # application transaction is still open (uncommitted rows stay invisible).
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def immediate_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialized write transaction. Used by application batches and cuts."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def snapshot_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Read transaction pinned to a single committed snapshot (WAL)."""
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
