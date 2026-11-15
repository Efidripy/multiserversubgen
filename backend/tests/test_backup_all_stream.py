import base64
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import operations


def _client(fetch):
    app = FastAPI()
    nodes = [{"name": name} for name in ("first", "second", "third")]
    app.include_router(operations.build_operations_router(
        check_auth=lambda request: True,
        db_path=None,
        node_service=SimpleNamespace(list_nodes=lambda: nodes),
        client_mgr=None,
        server_monitor=SimpleNamespace(get_database_backup=fetch),
        get_node_or_404=None,
        snapshot_collector=None,
    ))
    return TestClient(app)


def test_fleet_archive_streams_and_closes_temporary_file(monkeypatch):
    files = []
    original = operations.tempfile.TemporaryFile

    def temporary_file():
        file = original()
        files.append(file)
        return file

    monkeypatch.setattr(operations.tempfile, "TemporaryFile", temporary_file)
    monkeypatch.setenv("MAX_FLEET_BACKUP_BYTES", "6")
    payloads = {"first": b"1234", "second": b"567", "third": b"89"}
    client = _client(lambda node: {
        "node": node["name"], "backup_b64": base64.b64encode(payloads[node["name"]]).decode(),
    })

    response = client.get("/api/v1/backup/all")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="all_backups_')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["first.db", "second.error.txt", "third.db"]
        assert archive.read("first.db") == b"1234"
        assert archive.read("third.db") == b"89"
        assert b"fleet backup size limit exceeded" in archive.read("second.error.txt")
    assert len(files) == 1 and files[0].closed


def test_fleet_archive_closes_temporary_file_on_error(monkeypatch):
    files = []
    original = operations.tempfile.TemporaryFile

    def temporary_file():
        file = original()
        files.append(file)
        return file

    monkeypatch.setattr(operations.tempfile, "TemporaryFile", temporary_file)
    monkeypatch.setattr(operations.zipfile.ZipFile, "writestr", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    client = _client(lambda node: {"node": node["name"], "backup_b64": "YQ=="})

    with pytest.raises(OSError, match="disk"):
        client.get("/api/v1/backup/all")
    assert len(files) == 1 and files[0].closed


def test_json_fleet_limit_preserves_response_shape(monkeypatch):
    monkeypatch.setenv("MAX_FLEET_BACKUP_BYTES", "1")
    client = _client(lambda node: {"node": node["name"], "backup_b64": "YQ=="})
    payload = client.get("/api/v1/backup/all?format=json").json()
    assert payload["count"] == 3
    assert payload["backups"][0]["backup_b64"] == "YQ=="
    assert payload["backups"][1]["error"] == "fleet backup size limit exceeded"
