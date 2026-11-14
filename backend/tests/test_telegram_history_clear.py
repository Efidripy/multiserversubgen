from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.telegram_admin import build_telegram_admin_router
from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry


def _registry(tmp_path):
    path = str(tmp_path / "history.db")
    init_db(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (1, 'edge-test', 1, 0)")
    return TelegramRegistry(path), path


def test_operation_clear_keeps_partial_and_is_idempotent(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = registry.create_customer(email_display="history-user", origin="manual", email_source="admin", public_code="history-code")
    with connect(path) as conn:
        for status, finished in (("succeeded", "CURRENT_TIMESTAMP"), ("partial", "NULL")):
            conn.execute(
                f"INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by, finished_at) VALUES (?, 'suspend_node', ?, 'digest', 1, ?, 'test', {finished})",
                (customer_id, status, f"key-{status}"),
            )
    assert registry.clear_customer_operation_history(idempotency_key="clear-1", cleared_by="admin") == 1
    assert registry.clear_customer_operation_history(idempotency_key="clear-1", cleared_by="admin") == 1
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations WHERE status = 'partial'").fetchone()[0] == 1


def test_history_overview_reports_sections(tmp_path):
    registry, _path = _registry(tmp_path)
    overview = registry.history_overview()
    assert set(overview) == {"jobs", "operations", "drift", "missing_bindings", "audit"}
    assert overview["operations"]["needs_attention"] == 0


def test_history_retention_removes_only_old_safe_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "60")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "30")
    registry, path = _registry(tmp_path)
    customer_id = registry.create_customer(email_display="retention-user", origin="manual", email_source="admin", public_code="retention-code")
    with connect(path) as conn:
        for status, age, key in (("succeeded", "-90 days", "old-success"), ("succeeded", "-10 days", "young-success"), ("partial", "-90 days", "old-partial"), ("failed", "-90 days", "old-failed"), ("queued", "-90 days", "old-queued"), ("running", "-90 days", "old-running")):
            conn.execute(
                "INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by, created_at, updated_at, finished_at) VALUES (?, 'suspend_node', ?, 'digest', 1, ?, 'test', datetime('now', ?), datetime('now', ?), CASE WHEN ? = 'succeeded' THEN datetime('now', ?) ELSE NULL END)",
                (customer_id, status, key, age, age, status, age),
            )
        conn.execute("INSERT INTO customer_node_bindings(customer_id,node_id,remote_client_id,remote_sub_id,remote_email,source,management_state) VALUES (?,1,'remote','','retention-user','admin_confirmed','confirmed')", (customer_id,))
        conn.execute("INSERT INTO telegram_customer_operation_attempts(operation_id,binding_id,node_id,action,status) SELECT o.id,b.id,1,'set_enabled_false','succeeded' FROM telegram_customer_operations o JOIN customer_node_bindings b ON b.customer_id=o.customer_id WHERE o.idempotency_key='old-success'")
        for status, age, key in (("resolved", "-90 days", "resolved-old"), ("adopted", "-90 days", "adopted-old"), ("open", "-90 days", "open-old")):
            conn.execute(
                "INSERT INTO telegram_drift_findings(finding_key, kind, customer_id, node_id, remote_email, remote_client_id, remote_sub_id, status, last_seen_at, resolved_at) VALUES (?, 'binding_missing', ?, 1, 'retention-user', ?, '', ?, datetime('now', ?), CASE WHEN ? IN ('resolved','adopted') THEN datetime('now', ?) ELSE NULL END)",
                (key, customer_id, key, status, age, status, age),
            )
        for status, age, key in (("succeeded", "-90 days", "job-old"), ("succeeded", "-10 days", "job-young"), ("failed", "-90 days", "job-failed")):
            conn.execute(
                "INSERT INTO telegram_provisioning_jobs(customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by, created_at, updated_at, finished_at) VALUES (?, 'manual_sync', ?, ?, 'digest', 'test', datetime('now', ?), datetime('now', ?), datetime('now', ?))",
                (customer_id, key, status, age, age, age),
            )
        conn.execute("INSERT INTO telegram_audit_log(event_type, actor_type, actor_id, entity_type, entity_id, created_at) VALUES ('old', 'system', '1', 'test', '1', datetime('now', '-90 days'))")
        conn.execute("INSERT INTO telegram_audit_log(event_type, actor_type, actor_id, entity_type, entity_id) VALUES ('young', 'system', '1', 'test', '2')")

    result = registry.run_history_retention()
    assert result["operations"] == 1
    assert result["findings"] == 2
    assert result["jobs"] == 0
    assert result["audit"] == 1
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operation_attempts").fetchone()[0] == 0
        assert {row[0] for row in conn.execute("SELECT status FROM telegram_customer_operations")} == {"succeeded", "partial", "failed", "queued", "running"}
        assert {row[0] for row in conn.execute("SELECT status FROM telegram_drift_findings")} == {"open"}
        assert {row[0] for row in conn.execute("SELECT idempotency_key FROM telegram_provisioning_jobs")} == {"job-old", "job-young", "job-failed"}
        assert conn.execute("SELECT COUNT(*) FROM telegram_audit_log").fetchone()[0] == 1


def test_history_retention_zero_only_resolves_safe_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "0")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer_id = registry.create_customer(email_display="ignored-user", origin="manual", email_source="admin", public_code="ignored-code")
    with connect(path) as conn:
        conn.execute("INSERT INTO customer_node_bindings(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state) VALUES (?, 1, 'remote', '', 'ignored-user', 'admin_confirmed', 'confirmed')", (customer_id,))
        conn.execute("INSERT INTO telegram_drift_findings(finding_key, kind, customer_id, node_id, remote_email, remote_client_id, remote_sub_id, status) VALUES ('ignored-safe', 'binding_missing', ?, 1, 'ignored-user', 'remote', '', 'ignored')", (customer_id,))
        conn.execute("INSERT INTO telegram_customer_operations(customer_id,operation_type,status,target_snapshot_digest,expected_customer_version,idempotency_key,created_by,finished_at) VALUES (?,'suspend_node','succeeded','digest',1,'old','test',datetime('now','-500 days'))", (customer_id,))
        conn.execute("INSERT INTO telegram_provisioning_jobs(customer_id,trigger,idempotency_key,status,policy_snapshot_digest,created_by,finished_at) VALUES (?,'manual_sync','old','succeeded','digest','test',datetime('now','-500 days'))", (customer_id,))
        conn.execute("INSERT INTO telegram_drift_findings(finding_key,kind,customer_id,node_id,remote_email,remote_client_id,remote_sub_id,status,resolved_at) VALUES ('old','binding_missing',?,1,'ignored-user','old','','resolved',datetime('now','-500 days'))", (customer_id,))
        conn.execute("INSERT INTO telegram_audit_log(event_type,actor_type,entity_type,entity_id,created_at) VALUES ('old','system','test','1',datetime('now','-500 days'))")
    registry.run_history_retention()
    with connect(path) as conn:
        assert conn.execute("SELECT status FROM telegram_drift_findings WHERE finding_key='ignored-safe'").fetchone()[0] == "resolved"
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM telegram_drift_findings WHERE finding_key='old'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM telegram_audit_log WHERE event_type='old'").fetchone()[0] == 1


def test_forget_missing_bindings_is_scoped_and_keeps_customer_and_traffic(tmp_path):
    registry, path = _registry(tmp_path)
    with connect(path) as conn:
        conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (2, 'edge-test-2', 1, 0)")
    customer_id = registry.create_customer(email_display="forget-user", origin="manual", email_source="admin", public_code="forget-code")
    with connect(path) as conn:
        for node_id, state in ((1, "missing"), (2, "missing"),):
            conn.execute("INSERT INTO customer_node_bindings(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state) VALUES (?, ?, ?, '', 'forget-user', 'admin_confirmed', ?)", (customer_id, node_id, f"remote-{node_id}", state))
        conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (3, 'edge-test-3', 1, 0), (4, 'edge-test-4', 1, 0)")
        for node_id, state in ((3, "confirmed"), (4, "conflict")):
            conn.execute("INSERT INTO customer_node_bindings(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state) VALUES (?, ?, ?, '', 'forget-user', 'admin_confirmed', ?)", (customer_id, node_id, f"remote-{node_id}", state))
        conn.execute("INSERT INTO customer_traffic_ledger(customer_id, lifetime_bytes, last_observed_bytes) VALUES (?, 99, 12)", (customer_id,))
        conn.execute("INSERT INTO customer_traffic_binding_ledger(customer_id, node_id, inbound_id, last_observed_bytes) VALUES (?, 1, 1, 12)", (customer_id,))
    assert registry.forget_all_missing_bindings(node_id=1, actor="admin", idempotency_key="forget-node")["forgotten"] == 1
    assert registry.forget_all_missing_bindings(node_id=None, actor="admin", idempotency_key="forget-all")["forgotten"] == 1
    with connect(path) as conn:
        assert {r[0] for r in conn.execute("SELECT management_state FROM customer_node_bindings")} == {"confirmed", "conflict"}
        assert conn.execute("SELECT COUNT(*) FROM customers WHERE id = ?", (customer_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT lifetime_bytes FROM customer_traffic_ledger WHERE customer_id = ?", (customer_id,)).fetchone()[0] == 99
        assert conn.execute("SELECT last_observed_bytes FROM customer_traffic_binding_ledger WHERE customer_id = ?", (customer_id,)).fetchone()[0] == 12


def test_history_clear_permissions(tmp_path):
    registry, path = _registry(tmp_path)
    app = FastAPI()
    app.include_router(build_telegram_admin_router(
        check_auth=lambda request: "admin", get_user_role=lambda username: "admin",
        db_path=path, list_nodes=lambda: [], get_cached_inbound_options=lambda nodes: [],
        client_mgr=None, is_owner=lambda username: False,
    ))
    client = TestClient(app)
    for url in ("jobs/history/clear", "history/operations/clear", "history/drift/clear", "history/bindings/forget"):
        assert client.post("/api/v1/telegram/" + url, json={"idempotency_key": "denied"}).status_code == 403
    assert client.get("/api/v1/telegram/history/clear-count", params={"section": "bindings"}).status_code == 403
    assert registry.history_overview()["audit"]["total"] == 0


def test_counts_clear_replay_and_audit(tmp_path):
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="count-user", origin="manual", email_source="admin", public_code="count-code")
    with connect(path) as conn:
        for state in ("succeeded", "partial", "failed", "queued", "running"):
            conn.execute("INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by) VALUES (?, 'suspend_node', ?, 'digest', 1, ?, 'test')", (customer, state, state))
        for state in ("resolved", "adopted", "open", "ignored"):
            conn.execute("INSERT INTO telegram_drift_findings(finding_key, kind, customer_id, node_id, remote_email, remote_client_id, remote_sub_id, status) VALUES (?, 'binding_conflict', ?, 1, 'count-user', ?, '', ?)", (state, customer, state, state))
        conn.execute("INSERT INTO telegram_provisioning_jobs(customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by) VALUES (?, 'manual_sync', 'job', 'succeeded', 'digest', 'test')", (customer,))
        conn.execute("INSERT INTO customer_node_bindings(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state) VALUES (?, 1, 'remote', '', 'count-user', 'admin_confirmed', 'missing')", (customer,))
    actions = [
        ("jobs", lambda: registry.clear_terminal_provisioning_history(idempotency_key="clear", cleared_by="admin"), "provisioning_history_cleared"),
        ("operations", lambda: registry.clear_customer_operation_history(idempotency_key="clear", cleared_by="admin"), "customer_operation_history_cleared"),
        ("drift", lambda: registry.clear_drift_history(idempotency_key="clear", cleared_by="admin"), "drift_history_cleared"),
        ("bindings", lambda: registry.forget_all_missing_bindings(node_id=1, actor="admin", idempotency_key="clear")["forgotten"], "missing_bindings_forgotten"),
    ]
    for section, action, event in actions:
        count = registry.history_clear_count(section, 1 if section == "bindings" else None)
        assert count > 0
        assert action() == count
        assert action() == count
        assert registry.history_clear_count(section, 1 if section == "bindings" else None) == 0
        with connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM telegram_audit_log WHERE event_type=?", (event,)).fetchone()[0] == 1
    with connect(path) as conn:
        assert {r[0] for r in conn.execute("SELECT status FROM telegram_customer_operations")} == {"partial", "failed", "queued", "running"}
        assert conn.execute("SELECT COUNT(*) FROM telegram_drift_findings WHERE status='open'").fetchone()[0] == 1


def test_ignored_finding_stays_ignored_while_binding_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "0")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="missing-user", origin="manual", email_source="admin", public_code="missing-code")
    with connect(path) as conn:
        conn.execute("INSERT INTO customer_node_bindings(customer_id,node_id,remote_client_id,remote_sub_id,remote_email,source,management_state) VALUES (?,1,'remote','','missing-user','admin_confirmed','missing')", (customer,))
        conn.execute("INSERT INTO telegram_drift_findings(finding_key,kind,customer_id,node_id,remote_email,remote_client_id,remote_sub_id,status) VALUES ('missing','binding_missing',?,1,'missing-user','remote','','ignored')", (customer,))
    registry.run_history_retention()
    with connect(path) as conn:
        assert conn.execute("SELECT status FROM telegram_drift_findings").fetchone()[0] == "ignored"
        conn.execute("UPDATE customer_node_bindings SET management_state='confirmed'")
    registry.run_history_retention()
    with connect(path) as conn:
        assert conn.execute("SELECT status FROM telegram_drift_findings").fetchone()[0] == "resolved"


def test_missing_count_excludes_busy_binding(tmp_path):
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="busy-user", origin="manual", email_source="admin", public_code="busy-code")
    with connect(path) as conn:
        conn.execute("INSERT INTO customer_node_bindings(customer_id,node_id,remote_client_id,remote_sub_id,remote_email,source,management_state) VALUES (?,1,'remote','','busy-user','admin_confirmed','missing')", (customer,))
        conn.execute("INSERT INTO telegram_customer_operations(customer_id,operation_type,status,target_snapshot_digest,expected_customer_version,idempotency_key,created_by) VALUES (?,'suspend_node','partial','digest',1,'busy','test')", (customer,))
        conn.execute("INSERT INTO telegram_customer_operation_attempts(operation_id,binding_id,node_id,action,status) SELECT o.id,b.id,1,'set_enabled_false','failed' FROM telegram_customer_operations o JOIN customer_node_bindings b ON b.customer_id=o.customer_id")
    assert registry.history_clear_count("bindings", 1) == 0
    assert registry.forget_all_missing_bindings(node_id=1, actor="admin", idempotency_key="busy") == {"forgotten": 0, "busy": 1}
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM customer_node_bindings").fetchone()[0] == 1


def test_ignored_orphan_remote_is_kept_by_retention_and_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "0")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="orphan-user", origin="manual", email_source="admin", public_code="orphan-code")
    with connect(path) as conn:
        conn.execute("INSERT INTO telegram_drift_findings(finding_key,kind,customer_id,node_id,remote_email,remote_client_id,remote_sub_id,status) VALUES ('orphan','orphan_remote',?,1,'orphan-user','remote','','ignored')", (customer,))
    registry.run_history_retention()
    assert registry.history_clear_count("drift") == 0
    registry.clear_drift_history(idempotency_key="orphan-clear-1", cleared_by="admin")
    with connect(path) as conn:
        assert conn.execute("SELECT status FROM telegram_drift_findings WHERE finding_key='orphan'").fetchone()[0] == "ignored"


def test_suspend_operation_still_referenced_by_a_binding_survives_retention_and_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "30")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="suspended-user", origin="manual", email_source="admin", public_code="suspended-code")
    with connect(path) as conn:
        op_id = conn.execute(
            "INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by, finished_at) VALUES (?, 'suspend', 'succeeded', 'digest', 1, 'old-suspend', 'test', datetime('now','-400 days'))",
            (customer,),
        ).lastrowid
        conn.execute(
            "INSERT INTO customer_node_bindings(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state, desired_enabled, suspended_by_operation_id) VALUES (?, 1, 'remote', '', 'suspended-user', 'admin_confirmed', 'confirmed', 0, ?)",
            (customer, op_id),
        )
    registry.run_history_retention()
    assert registry.history_clear_count("operations") == 0
    registry.clear_customer_operation_history(idempotency_key="suspended-clear-1", cleared_by="admin")
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations WHERE id=?", (op_id,)).fetchone()[0] == 1
        conn.execute("UPDATE customer_node_bindings SET suspended_by_operation_id=NULL, desired_enabled=1")
    registry.run_history_retention()
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations WHERE id=?", (op_id,)).fetchone()[0] == 0


def test_history_operations_endpoint_marks_dismissed_operations(tmp_path):
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="dismiss-user", origin="manual", email_source="admin", public_code="dismiss-code")
    with connect(path) as conn:
        for key, dismissed in (("a", "NULL"), ("b", "CURRENT_TIMESTAMP")):
            conn.execute(
                f"INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by, dismissed_at) VALUES (?, 'suspend_node', 'partial', 'digest', 1, ?, 'test', {dismissed})",
                (customer, key),
            )
        ids = {row[0]: row[1] for row in conn.execute("SELECT idempotency_key, id FROM telegram_customer_operations").fetchall()}
    assert registry.dismissed_operation_ids(list(ids.values())) == {ids["b"]}
    assert registry.dismissed_operation_ids([]) == set()


def test_latest_expiry_provisioning_job_survives_retention_and_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "30")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="expiry-user", origin="manual", email_source="admin", public_code="expiry-code")
    job_ids = []
    with connect(path) as conn:
        for key in ("older", "latest"):
            job = conn.execute(
                "INSERT INTO telegram_provisioning_jobs(customer_id,trigger,idempotency_key,status,policy_snapshot_digest,created_by,finished_at) VALUES (?,'manual_sync',?,'succeeded','digest','test',datetime('now','-400 days'))",
                (customer, key),
            ).lastrowid
            conn.execute(
                "INSERT INTO telegram_provisioning_attempts(job_id,node_id,status,desired_client_id,desired_sub_id,desired_expiry_time,policy_version) VALUES (?,1,'succeeded','client','sub',4102444800000,1)",
                (job,),
            )
            job_ids.append(job)
    registry.run_history_retention()
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 2
    assert registry.history_clear_count("jobs") == 1
    registry.clear_terminal_provisioning_history(idempotency_key="expiry-clear-1", cleared_by="admin")
    with connect(path) as conn:
        left = [row[0] for row in conn.execute("SELECT id FROM telegram_provisioning_jobs ORDER BY id").fetchall()]
    assert left == [job_ids[1]]


def test_retention_keeps_finite_quota_snapshot_and_failed_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "30")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="quota-user", origin="manual", email_source="admin", public_code="quota-code")
    with connect(path) as conn:
        quota_job = conn.execute(
            "INSERT INTO telegram_provisioning_jobs(customer_id,trigger,idempotency_key,status,policy_snapshot_digest,created_by,finished_at) VALUES (?,'manual_sync','quota','succeeded','digest','test',datetime('now','-400 days'))",
            (customer,),
        ).lastrowid
        conn.execute(
            "INSERT INTO telegram_provisioning_attempts(job_id,node_id,status,desired_client_id,desired_sub_id,desired_expiry_time,desired_total_bytes,policy_version,remote_client_id) VALUES (?,1,'succeeded','client','sub',0,1073741824,1,'remote')",
            (quota_job,),
        )
        failed_job = conn.execute(
            "INSERT INTO telegram_provisioning_jobs(customer_id,trigger,idempotency_key,status,policy_snapshot_digest,created_by,finished_at) VALUES (?,'approve_new','failed','failed','digest','test',datetime('now','-400 days'))",
            (customer,),
        ).lastrowid
    registry.run_history_retention()
    with connect(path) as conn:
        left = {row[0] for row in conn.execute("SELECT id FROM telegram_provisioning_jobs").fetchall()}
    assert left == {quota_job, failed_job}


def test_cancelled_job_holding_latest_succeeded_attempt_is_kept(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_HISTORY_RETENTION_DAYS", "30")
    monkeypatch.setenv("TELEGRAM_AUDIT_RETENTION_DAYS", "0")
    registry, path = _registry(tmp_path)
    customer = registry.create_customer(email_display="dismissed-job-user", origin="manual", email_source="admin", public_code="dismissed-job-code")
    with connect(path) as conn:
        job = conn.execute(
            "INSERT INTO telegram_provisioning_jobs(customer_id,trigger,idempotency_key,status,policy_snapshot_digest,created_by,finished_at) VALUES (?,'manual_sync','dismissed','cancelled','digest','test',datetime('now','-400 days'))",
            (customer,),
        ).lastrowid
        conn.execute(
            "INSERT INTO telegram_provisioning_attempts(job_id,node_id,status,desired_client_id,desired_sub_id,desired_total_bytes,policy_version,remote_client_id) VALUES (?,1,'succeeded','client','sub',1073741824,1,'remote')",
            (job,),
        )
    registry.run_history_retention()
    assert registry.history_clear_count("jobs") == 0
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE id=?", (job,)).fetchone()[0] == 1
