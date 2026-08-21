import base64
import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.operations import build_operations_router


class _NodeService:
    def list_nodes(self):
        return []


class _SnapshotCollector:
    def latest_snapshot(self):
        return {}


class _Monitor:
    def __init__(self):
        self.imports = []

    def import_database_backup(self, node, backup_data):
        self.imports.append((node, backup_data))
        return True


def _client():
    monitor = _Monitor()
    app = FastAPI()
    app.include_router(
        build_operations_router(
            check_auth=lambda _request: "admin",
            db_path=":memory:",
            node_service=_NodeService(),
            client_mgr=object(),
            server_monitor=monitor,
            get_node_or_404=lambda node_id: {"id": node_id, "name": "test-node"},
            snapshot_collector=_SnapshotCollector(),
        )
    )
    return TestClient(app), monitor


def test_backup_import_rejects_unknown_multipart_before_remote_restore():
    client, monitor = _client()

    response = client.post(
        "/api/v1/backup/node/1/import",
        files={"file": ("payload.db", b"not a database", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert monitor.imports == []


def test_backup_import_accepts_sqlite_database_signature():
    client, monitor = _client()
    database = b"SQLite format 3\x00" + b"\x00" * 64

    response = client.post(
        "/api/v1/backup/node/1/import",
        files={"file": ("backup.sqlite3", database, "application/x-sqlite3")},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert len(monitor.imports) == 1
    assert base64.b64decode(monitor.imports[0][1]) == database


def test_backup_import_accepts_sqlite_migration_dump_via_json_api():
    client, monitor = _client()
    dump = b"\xef\xbb\xbf \r\nBEGIN TRANSACTION;\nCREATE TABLE example (id INTEGER);\n"

    response = client.post(
        "/api/v1/backup/database/1",
        json={"backup_data": dump.decode("utf-8")},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert monitor.imports == [({"id": 1, "name": "test-node"}, dump.decode("utf-8"))]


def test_backup_import_rejects_unknown_json_payload_before_remote_restore():
    client, monitor = _client()

    response = client.post("/api/v1/backup/database/1", json={"backup_data": "not a backup"})

    assert response.status_code == 400
    assert monitor.imports == []
