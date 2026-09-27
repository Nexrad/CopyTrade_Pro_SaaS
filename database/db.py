"""
database/db.py
-----------------
One connection helper, used by every module. Rows come back as
sqlite3.Row (dict-like access by column name) so calling code never
depends on column order.
"""

import os
import sqlite3
import threading

from config import settings

_local = threading.local()


def _connect():
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn():
    """Thread-local connection - safe for the multi-threaded dev HTTP server."""
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    return _local.conn


def init_db(schema_path: str = None):
    schema_path = schema_path or os.path.join(settings.BASE_DIR, "database", "schema.sql")
    conn = get_conn()
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def reset_db_for_tests():
    """Used only by tests/ - wipes and recreates all tables."""
    conn = get_conn()
    # A prior test that raised mid-transaction leaves this connection with
    # an open transaction. SQLite silently ignores "PRAGMA foreign_keys"
    # while a transaction is open, so without this rollback the DROP
    # TABLE loop below intermittently fails with FOREIGN KEY constraint
    # errors depending on what the previous test happened to leave behind.
    conn.rollback()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r["name"] for r in cur.fetchall()]
    conn.execute("PRAGMA foreign_keys = OFF")
    for t in tables:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    init_db()
