"""Database utilities – thin wrapper around sqlite3 for the application.

Provides helpers for initialising the schema and obtaining connections.
All schema-creation statements live here so modules don't need to
duplicate them.

Usage::

    from core.database import init_db, get_connection

    init_db("/opt/sub-manager/admin.db")

    with get_connection("/opt/sub-manager/admin.db") as conn:
        rows = conn.execute("SELECT * FROM nodes").fetchall()
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS = [
    # Nodes table
    """
    CREATE TABLE IF NOT EXISTS nodes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT,
        ip           TEXT,
        port         TEXT,
        user         TEXT,
        password     TEXT,
        base_path    TEXT DEFAULT ''
    )
    """,
    # Subscription groups
    """
    CREATE TABLE IF NOT EXISTS subscription_groups (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT NOT NULL,
        identifier     TEXT NOT NULL UNIQUE,
        description    TEXT DEFAULT '',
        email_patterns TEXT DEFAULT '[]',
        node_filters   TEXT DEFAULT '[]',
        protocol_filter TEXT,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Node history (time-series snapshots)
    """
    CREATE TABLE IF NOT EXISTS node_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        ts             INTEGER NOT NULL,
        node_id        INTEGER NOT NULL,
        node_name      TEXT,
        available      INTEGER DEFAULT 0,
        xray_running   INTEGER DEFAULT 0,
        cpu            REAL DEFAULT 0.0,
        online_clients INTEGER DEFAULT 0,
        traffic_total  REAL DEFAULT 0.0,
        poll_ms        REAL DEFAULT 0.0
    )
    """,
    # AdGuard sources
    """
    CREATE TABLE IF NOT EXISTS adguard_sources (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        url          TEXT NOT NULL,
        username     TEXT DEFAULT '',
        password     TEXT DEFAULT '',
        enabled      INTEGER DEFAULT 1,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # AdGuard snapshots
    """
    CREATE TABLE IF NOT EXISTS adguard_snapshots (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            INTEGER NOT NULL,
        source_id     INTEGER NOT NULL,
        available     INTEGER DEFAULT 0,
        dns_queries   INTEGER DEFAULT 0,
        dns_blocked   INTEGER DEFAULT 0,
        block_rate    REAL DEFAULT 0.0,
        latency_ms    REAL DEFAULT 0.0,
        cache_hit_pct REAL DEFAULT 0.0,
        upstream_errors INTEGER DEFAULT 0,
        raw_json      TEXT DEFAULT '{}'
    )
    """,
    # Audit log
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         INTEGER NOT NULL,
        username   TEXT,
        action     TEXT,
        target     TEXT,
        ip         TEXT,
        details    TEXT DEFAULT '{}'
    )
    """,
]

# Optional ALTER TABLE migrations (non-fatal if column already exists)
_MIGRATIONS = [
    "ALTER TABLE nodes ADD COLUMN base_path TEXT DEFAULT ''",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """Create all tables if they don't exist and run non-destructive migrations.

    Safe to call on every application start.

    Args:
        db_path: Absolute path to the SQLite database file.
    """
    with sqlite3.connect(db_path) as conn:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()

    # Run optional migrations (ignore errors for existing columns etc.)
    with sqlite3.connect(db_path) as conn:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists or other benign error

    logger.debug("Database initialized at %s", db_path)


@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields an open :class:`sqlite3.Connection`.

    The connection uses :attr:`sqlite3.Row` as the row factory so columns
    are accessible by name.

    Args:
        db_path: Absolute path to the SQLite database file.

    Yields:
        An open connection that is committed and closed on exit.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
