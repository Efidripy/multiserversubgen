from __future__ import annotations

import logging
import sqlite3


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if columns and "role" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'viewer'")

        conn.execute(
            """CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE,
                      password TEXT,
                      role TEXT DEFAULT 'viewer',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS nodes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT,
                      panel_url TEXT,
                      username TEXT,
                      password TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      enabled INTEGER DEFAULT 1,
                      read_only INTEGER DEFAULT 0,
                      source_type TEXT DEFAULT 'xui',
                      access_path TEXT DEFAULT '',
                      api_base TEXT DEFAULT '',
                      ip TEXT DEFAULT '',
                      verify_tls INTEGER DEFAULT 1)"""
        )

        node_columns = [r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()]
        if node_columns:
            migrations = [
                ("enabled", "ALTER TABLE nodes ADD COLUMN enabled INTEGER DEFAULT 1"),
                ("read_only", "ALTER TABLE nodes ADD COLUMN read_only INTEGER DEFAULT 0"),
                ("source_type", "ALTER TABLE nodes ADD COLUMN source_type TEXT DEFAULT 'xui'"),
                ("access_path", "ALTER TABLE nodes ADD COLUMN access_path TEXT DEFAULT ''"),
                ("api_base", "ALTER TABLE nodes ADD COLUMN api_base TEXT DEFAULT ''"),
                ("ip", "ALTER TABLE nodes ADD COLUMN ip TEXT DEFAULT ''"),
                ("verify_tls", "ALTER TABLE nodes ADD COLUMN verify_tls INTEGER DEFAULT 1"),
            ]
            for col_name, stmt in migrations:
                if col_name not in node_columns:
                    conn.execute(stmt)

        conn.execute(
            """CREATE TABLE IF NOT EXISTS backup_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      node_name TEXT,
                      backup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      status TEXT,
                      details TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS subscription_groups
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT UNIQUE NOT NULL,
                      identifier TEXT UNIQUE NOT NULL,
                      description TEXT,
                      email_patterns TEXT,
                      node_filters TEXT,
                      protocol_filter TEXT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_events
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      payload TEXT NOT NULL)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS node_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts INTEGER NOT NULL,
                      node_id INTEGER NOT NULL,
                      node_name TEXT NOT NULL,
                      available INTEGER NOT NULL,
                      xray_running INTEGER NOT NULL,
                      cpu REAL NOT NULL,
                      online_clients INTEGER NOT NULL,
                      traffic_total REAL NOT NULL,
                      poll_ms REAL NOT NULL)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_history_ts ON node_history(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_history_node_ts ON node_history(node_id, ts)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS adguard_sources
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL,
                      admin_url TEXT NOT NULL,
                      dns_url TEXT DEFAULT '',
                      username TEXT NOT NULL,
                      password TEXT NOT NULL,
                      verify_tls INTEGER NOT NULL DEFAULT 1,
                      enabled INTEGER NOT NULL DEFAULT 1,
                      last_error TEXT DEFAULT '',
                      last_success_ts INTEGER DEFAULT 0,
                      last_collected_ts INTEGER DEFAULT 0,
                      api_base TEXT DEFAULT '',
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS adguard_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts INTEGER NOT NULL,
                      source_id INTEGER NOT NULL,
                      source_name TEXT NOT NULL,
                      available INTEGER NOT NULL,
                      queries_total REAL NOT NULL,
                      blocked_total REAL NOT NULL,
                      blocked_rate REAL NOT NULL,
                      cache_hit_ratio REAL NOT NULL,
                      avg_latency_ms REAL NOT NULL,
                      upstream_errors REAL NOT NULL,
                      extra_json TEXT DEFAULT '',
                      FOREIGN KEY(source_id) REFERENCES adguard_sources(id) ON DELETE CASCADE)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adguard_history_ts ON adguard_history(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adguard_history_source_ts ON adguard_history(source_id, ts)")
        conn.commit()


def sync_node_history_names_with_nodes(db_path: str, logger: logging.Logger) -> None:
    with sqlite3.connect(db_path) as conn:
        result = conn.execute(
            """
            UPDATE node_history
            SET node_name = (
                SELECT n.name
                FROM nodes n
                WHERE n.id = node_history.node_id
            )
            WHERE EXISTS (
                SELECT 1
                FROM nodes n
                WHERE n.id = node_history.node_id
                  AND IFNULL(n.name, '') <> IFNULL(node_history.node_name, '')
            )
            """
        )
        conn.commit()
    if result.rowcount:
        logger.info(f"node_history names synchronized: {result.rowcount} rows updated")
