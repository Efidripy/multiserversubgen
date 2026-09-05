from __future__ import annotations

import logging
import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    """Открыть соединение с SQLite с оптимальными настройками.

    journal_mode=WAL персистентна (хранится в файле), synchronous=NORMAL — нет,
    поэтому выставляем её на каждом новом соединении.

    Используйте эту функцию везде вместо ``sqlite3.connect(db_path)`` напрямую.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    # SQLite does not enforce declared foreign keys unless every connection
    # explicitly enables it. Telegram lifecycle records rely on these
    # constraints to prevent dangling node/customer bindings.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
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
                      user TEXT,
                      password TEXT,
                      port TEXT DEFAULT '443',
                      base_path TEXT DEFAULT '',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      enabled INTEGER DEFAULT 1,
                      read_only INTEGER DEFAULT 0,
                      source_type TEXT DEFAULT 'xui',
                      access_path TEXT DEFAULT '',
                      api_base TEXT DEFAULT '',
                      ip TEXT DEFAULT '',
                      verify_tls INTEGER DEFAULT 1,
                      scheme TEXT DEFAULT 'https',
                      tags TEXT DEFAULT '[]')"""
        )

        node_columns = [r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()]
        if node_columns:
            migrations = [
                ("panel_url", "ALTER TABLE nodes ADD COLUMN panel_url TEXT"),
                ("username", "ALTER TABLE nodes ADD COLUMN username TEXT"),
                ("enabled", "ALTER TABLE nodes ADD COLUMN enabled INTEGER DEFAULT 1"),
                ("read_only", "ALTER TABLE nodes ADD COLUMN read_only INTEGER DEFAULT 0"),
                ("source_type", "ALTER TABLE nodes ADD COLUMN source_type TEXT DEFAULT 'xui'"),
                ("access_path", "ALTER TABLE nodes ADD COLUMN access_path TEXT DEFAULT ''"),
                ("api_base", "ALTER TABLE nodes ADD COLUMN api_base TEXT DEFAULT ''"),
                ("ip", "ALTER TABLE nodes ADD COLUMN ip TEXT DEFAULT ''"),
                ("verify_tls", "ALTER TABLE nodes ADD COLUMN verify_tls INTEGER DEFAULT 1"),
                ("user", "ALTER TABLE nodes ADD COLUMN user TEXT"),
                ("port", "ALTER TABLE nodes ADD COLUMN port TEXT DEFAULT '443'"),
                ("base_path", "ALTER TABLE nodes ADD COLUMN base_path TEXT DEFAULT ''"),
                ("scheme", "ALTER TABLE nodes ADD COLUMN scheme TEXT DEFAULT 'https'"),
                ("api_version", "ALTER TABLE nodes ADD COLUMN api_version TEXT DEFAULT NULL"),
                ("panel_version", "ALTER TABLE nodes ADD COLUMN panel_version TEXT DEFAULT NULL"),
                ("tags", "ALTER TABLE nodes ADD COLUMN tags TEXT DEFAULT '[]'"),
            ]
            for col_name, stmt in migrations:
                if col_name not in node_columns:
                    conn.execute(stmt)

            conn.execute(
                """
                UPDATE nodes
                SET user = username
                WHERE (user IS NULL OR user = '')
                  AND IFNULL(username, '') <> ''
                """
            )
            conn.execute(
                """
                UPDATE nodes
                SET username = user
                WHERE (username IS NULL OR username = '')
                  AND IFNULL(user, '') <> ''
                """
            )
            conn.execute(
                """
                UPDATE nodes
                SET base_path = access_path
                WHERE (base_path IS NULL OR base_path = '')
                  AND IFNULL(access_path, '') <> ''
                """
            )
            conn.execute(
                """
                UPDATE nodes
                SET scheme = 'https'
                WHERE scheme IS NULL OR scheme = ''
                """
            )
            conn.execute(
                """
                UPDATE nodes
                SET scheme = 'http'
                WHERE LOWER(IFNULL(panel_url, '')) LIKE 'http://%'
                """
            )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS backup_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      node_name TEXT,
                      backup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      status TEXT,
                      details TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS client_notes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      node_id INTEGER NOT NULL,
                      inbound_id INTEGER NOT NULL DEFAULT 0,
                      client_identifier TEXT NOT NULL,
                      email TEXT NOT NULL,
                      notes TEXT DEFAULT '',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE(node_id, inbound_id, client_identifier))"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_client_notes_email ON client_notes(email)")
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
            """CREATE TABLE IF NOT EXISTS subscription_tokens
                     (kind TEXT NOT NULL,
                      identifier TEXT NOT NULL,
                      token TEXT NOT NULL UNIQUE,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (kind, identifier))"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_subscription_tokens_token "
            "ON subscription_tokens(token)"
        )
        # Telegram integration is intentionally additive. These local records
        # are the authority for identity, lifecycle intent and retry state;
        # they do not replace or mutate remote 3x-ui clients by themselves.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS customers
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      email_display TEXT NOT NULL,
                      email_canonical TEXT NOT NULL,
                      origin TEXT NOT NULL CHECK(origin IN ('existing', 'telegram', 'manual')),
                      status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN (
                            'active', 'suspending', 'suspended', 'suspend_partial',
                            'resuming', 'resume_partial', 'deleting', 'delete_partial',
                            'deleted', 'conflict')),
                      public_code TEXT NOT NULL UNIQUE,
                      email_source TEXT NOT NULL
                        CHECK(email_source IN (
                            'telegram_username', 'telegram_name', 'fallback', 'admin', 'existing')),
                      row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      deleted_at TEXT DEFAULT NULL,
                      CHECK(length(trim(email_display)) > 0),
                      CHECK(length(trim(email_canonical)) > 0))"""
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_live_email_canonical "
            "ON customers(email_canonical) WHERE deleted_at IS NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customers_status_updated "
            "ON customers(status, updated_at DESC)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_identities
                     (telegram_user_id INTEGER PRIMARY KEY,
                      chat_id INTEGER NOT NULL,
                      customer_id INTEGER DEFAULT NULL,
                      username TEXT DEFAULT NULL,
                      first_name TEXT DEFAULT NULL,
                      last_name TEXT DEFAULT NULL,
                      locale TEXT NOT NULL DEFAULT 'ru' CHECK(locale IN ('ru', 'en')),
                      access_status TEXT NOT NULL DEFAULT 'eligible'
                        CHECK(access_status IN ('eligible', 'pending', 'approved', 'rejected', 'blocked')),
                      request_code TEXT DEFAULT NULL UNIQUE,
                      application_attempt INTEGER NOT NULL DEFAULT 0 CHECK(application_attempt >= 0),
                      requested_at TEXT DEFAULT NULL,
                      approved_at TEXT DEFAULT NULL,
                      rejected_at TEXT DEFAULT NULL,
                      blocked_at TEXT DEFAULT NULL,
                      unblocked_at TEXT DEFAULT NULL,
                      approved_by TEXT DEFAULT NULL,
                      decision_reason TEXT DEFAULT NULL,
                      blocked_from_status TEXT DEFAULT NULL
                        CHECK(blocked_from_status IS NULL OR blocked_from_status IN (
                            'eligible', 'pending', 'approved', 'rejected')),
                      row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_identities_access_requested "
            "ON telegram_identities(access_status, requested_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_identities_customer "
            "ON telegram_identities(customer_id)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_applications
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      telegram_user_id INTEGER NOT NULL,
                      application_attempt INTEGER NOT NULL CHECK(application_attempt > 0),
                      status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'approved', 'rejected', 'blocked', 'cancelled')),
                      introduction_text TEXT DEFAULT NULL CHECK(
                        introduction_text IS NULL OR length(introduction_text) <= 700),
                      introduction_submitted_at TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE(telegram_user_id, application_attempt),
                      FOREIGN KEY(telegram_user_id) REFERENCES telegram_identities(telegram_user_id)
                        ON DELETE CASCADE)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_applications_pending "
            "ON telegram_applications(status, created_at)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_node_policies
                     (node_id INTEGER PRIMARY KEY,
                      provisioning_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK(provisioning_enabled IN (0, 1)),
                      total_bytes INTEGER NOT NULL DEFAULT 0 CHECK(total_bytes >= 0),
                      validity_days INTEGER NOT NULL DEFAULT 0 CHECK(validity_days >= 0),
                      client_enabled INTEGER NOT NULL DEFAULT 1
                        CHECK(client_enabled IN (0, 1)),
                      policy_version INTEGER NOT NULL DEFAULT 1 CHECK(policy_version > 0),
                      updated_by TEXT NOT NULL DEFAULT '',
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_node_policies_enabled "
            "ON telegram_node_policies(provisioning_enabled, node_id)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_command_receipts
                     (scope TEXT NOT NULL,
                      idempotency_key TEXT NOT NULL,
                      payload_digest TEXT NOT NULL,
                      result_json TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY(scope, idempotency_key))"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS customer_node_bindings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      customer_id INTEGER NOT NULL,
                      node_id INTEGER NOT NULL,
                      inbound_id INTEGER NOT NULL DEFAULT 1 CHECK(inbound_id = 1),
                      remote_client_id TEXT DEFAULT NULL,
                      remote_sub_id TEXT DEFAULT NULL,
                      remote_email TEXT NOT NULL,
                      source TEXT NOT NULL
                        CHECK(source IN ('bot_provisioned', 'existing_bound', 'admin_confirmed')),
                      management_state TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK(management_state IN ('confirmed', 'missing', 'ambiguous', 'conflict')),
                      desired_enabled INTEGER NOT NULL DEFAULT 1 CHECK(desired_enabled IN (0, 1)),
                      last_enabled INTEGER DEFAULT NULL CHECK(last_enabled IN (0, 1)),
                      last_confirmed_at TEXT DEFAULT NULL,
                      row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE(customer_id, node_id, inbound_id),
                      UNIQUE(node_id, inbound_id, remote_client_id),
                      FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE RESTRICT)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_node_bindings_customer "
            "ON customer_node_bindings(customer_id, management_state, node_id)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_provisioning_jobs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      customer_id INTEGER NOT NULL,
                      trigger TEXT NOT NULL CHECK(trigger IN ('approve_new', 'manual_sync', 'node_backfill')),
                      idempotency_key TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued', 'running', 'partial', 'succeeded', 'failed', 'cancelled')),
                      policy_snapshot_digest TEXT NOT NULL,
                      created_by TEXT NOT NULL,
                      lease_owner TEXT DEFAULT NULL,
                      lease_until TEXT DEFAULT NULL,
                      attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                      next_attempt_at TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      finished_at TEXT DEFAULT NULL,
                      FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_provisioning_jobs_schedule "
            "ON telegram_provisioning_jobs(status, next_attempt_at, lease_until)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_provisioning_attempts
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      job_id INTEGER NOT NULL,
                      node_id INTEGER NOT NULL,
                      inbound_id INTEGER NOT NULL DEFAULT 1 CHECK(inbound_id = 1),
                      status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'reconciling', 'creating', 'succeeded', 'failed', 'ambiguous', 'skipped')),
                      desired_client_id TEXT NOT NULL,
                      desired_sub_id TEXT NOT NULL,
                      desired_flow TEXT NOT NULL DEFAULT 'xtls-rprx-vision',
                      desired_total_bytes INTEGER NOT NULL DEFAULT 0 CHECK(desired_total_bytes >= 0),
                      desired_validity_days INTEGER NOT NULL DEFAULT 0 CHECK(desired_validity_days >= 0),
                      desired_client_enabled INTEGER NOT NULL DEFAULT 1
                        CHECK(desired_client_enabled IN (0, 1)),
                      policy_version INTEGER NOT NULL CHECK(policy_version > 0),
                      remote_client_id TEXT DEFAULT NULL,
                      error_code TEXT DEFAULT NULL,
                      error_summary TEXT DEFAULT NULL,
                      attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                      next_attempt_at TEXT DEFAULT NULL,
                      last_checked_at TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      finished_at TEXT DEFAULT NULL,
                      UNIQUE(job_id, node_id, inbound_id),
                      FOREIGN KEY(job_id) REFERENCES telegram_provisioning_jobs(id) ON DELETE CASCADE,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE RESTRICT)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_provisioning_attempts_schedule "
            "ON telegram_provisioning_attempts(status, next_attempt_at)"
        )
        # `CREATE TABLE IF NOT EXISTS` cannot extend an already created
        # database. Keep these additive migrations next to the authority
        # schema so a deployed DB gains the immutable attempt contract before
        # a worker is ever allowed to perform remote I/O.
        provisioning_attempt_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(telegram_provisioning_attempts)").fetchall()
        }
        provisioning_attempt_migrations = [
            (
                "desired_flow",
                "ALTER TABLE telegram_provisioning_attempts "
                "ADD COLUMN desired_flow TEXT NOT NULL DEFAULT 'xtls-rprx-vision'",
            ),
            (
                "desired_total_bytes",
                "ALTER TABLE telegram_provisioning_attempts "
                "ADD COLUMN desired_total_bytes INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "desired_validity_days",
                "ALTER TABLE telegram_provisioning_attempts "
                "ADD COLUMN desired_validity_days INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "desired_client_enabled",
                "ALTER TABLE telegram_provisioning_attempts "
                "ADD COLUMN desired_client_enabled INTEGER NOT NULL DEFAULT 1",
            ),
        ]
        for column_name, statement in provisioning_attempt_migrations:
            if column_name not in provisioning_attempt_columns:
                conn.execute(statement)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_customer_operations
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      customer_id INTEGER NOT NULL,
                      operation_type TEXT NOT NULL CHECK(operation_type IN (
                          'suspend', 'resume', 'delete', 'add_node', 'suspend_node', 'resume_node')),
                      status TEXT NOT NULL DEFAULT 'previewed'
                        CHECK(status IN ('previewed', 'queued', 'running', 'partial', 'succeeded', 'failed')),
                      target_snapshot_digest TEXT NOT NULL,
                      expected_customer_version INTEGER NOT NULL CHECK(expected_customer_version > 0),
                      idempotency_key TEXT NOT NULL UNIQUE,
                      created_by TEXT NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      finished_at TEXT DEFAULT NULL,
                      FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_customer_operation_attempts
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      operation_id INTEGER NOT NULL,
                      binding_id INTEGER NOT NULL,
                      node_id INTEGER NOT NULL,
                      inbound_id INTEGER NOT NULL DEFAULT 1 CHECK(inbound_id = 1),
                      remote_client_id TEXT DEFAULT NULL,
                      remote_sub_id TEXT DEFAULT NULL,
                      action TEXT NOT NULL CHECK(action IN (
                          'set_enabled_false', 'restore_previous_enabled', 'delete_client')),
                      previous_enabled INTEGER DEFAULT NULL CHECK(previous_enabled IN (0, 1)),
                      status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'reconciling', 'writing', 'succeeded', 'missing',
                                         'ambiguous', 'conflict', 'blocked', 'failed')),
                      request_digest TEXT DEFAULT NULL,
                      response_digest TEXT DEFAULT NULL,
                      error_code TEXT DEFAULT NULL,
                      error_summary TEXT DEFAULT NULL,
                      attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                      next_attempt_at TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      finished_at TEXT DEFAULT NULL,
                      UNIQUE(operation_id, binding_id),
                      FOREIGN KEY(operation_id) REFERENCES telegram_customer_operations(id) ON DELETE CASCADE,
                      FOREIGN KEY(binding_id) REFERENCES customer_node_bindings(id) ON DELETE RESTRICT,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE RESTRICT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_updates
                     (update_id INTEGER PRIMARY KEY,
                      telegram_user_id INTEGER DEFAULT NULL,
                      update_type TEXT NOT NULL,
                      payload_digest TEXT NOT NULL,
                      status TEXT NOT NULL DEFAULT 'received'
                        CHECK(status IN ('received', 'processed', 'rejected', 'failed')),
                      received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      processed_at TEXT DEFAULT NULL,
                      FOREIGN KEY(telegram_user_id) REFERENCES telegram_identities(telegram_user_id)
                        ON DELETE SET NULL)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_updates_status_received "
            "ON telegram_updates(status, received_at)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_abuse_state
                     (telegram_user_id INTEGER PRIMARY KEY,
                      window_started_at TEXT DEFAULT NULL,
                      last_event_at TEXT DEFAULT NULL,
                      consecutive_noop_count INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_noop_count >= 0),
                      soft_limited_until TEXT DEFAULT NULL,
                      auto_block_count INTEGER NOT NULL DEFAULT 0 CHECK(auto_block_count >= 0),
                      last_auto_blocked_at TEXT DEFAULT NULL,
                      last_reason_code TEXT DEFAULT NULL,
                      row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
                      FOREIGN KEY(telegram_user_id) REFERENCES telegram_identities(telegram_user_id)
                        ON DELETE CASCADE)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_outbox
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      event_type TEXT NOT NULL,
                      entity_id TEXT NOT NULL,
                      dedupe_key TEXT NOT NULL UNIQUE,
                      payload_json TEXT NOT NULL DEFAULT '{}',
                      status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued', 'sending', 'sent', 'retry', 'dead_letter', 'cancelled')),
                      attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                      next_attempt_at TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      sent_at TEXT DEFAULT NULL)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_outbox_schedule "
            "ON telegram_outbox(status, next_attempt_at)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_audit_log
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      event_type TEXT NOT NULL,
                      actor_type TEXT NOT NULL CHECK(actor_type IN ('telegram_user', 'admin', 'system')),
                      actor_id TEXT DEFAULT NULL,
                      entity_type TEXT NOT NULL,
                      entity_id TEXT NOT NULL,
                      payload_digest TEXT DEFAULT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_audit_entity "
            "ON telegram_audit_log(entity_type, entity_id, created_at)"
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
        conn.execute(
            """CREATE TABLE IF NOT EXISTS node_snapshots
                     (node_id INTEGER PRIMARY KEY,
                      status_data TEXT NOT NULL,
                      is_online INTEGER NOT NULL DEFAULT 0,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_history_ts ON node_history(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_history_node_ts ON node_history(node_id, ts)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS traffic_stats_snapshots
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      group_by TEXT NOT NULL,
                      bucket_kind TEXT NOT NULL,
                      bucket_start INTEGER NOT NULL,
                      snapshot_ts INTEGER NOT NULL,
                      stats_json TEXT NOT NULL,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE(group_by, bucket_kind, bucket_start))"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_traffic_stats_snapshots_lookup "
            "ON traffic_stats_snapshots(group_by, bucket_kind, snapshot_ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_traffic_stats_snapshots_bucket "
            "ON traffic_stats_snapshots(group_by, bucket_kind, bucket_start)"
        )
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
    with connect(db_path) as conn:
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
