import ast
import io
import logging
import runpy
from pathlib import Path

import pytest
import requests

from client_manager import ClientManager
from shared.logging import _RedactFilter


ROOT = Path(__file__).resolve().parents[2]
GUARD = runpy.run_path(str(ROOT / "scripts/ci/check-no-prod-data"))


@pytest.mark.parametrize("value", ["192.0.2.1", "203.0.113.2", "10.1.2.3", "172.16.0.1", "192.168.0.1", "127.1.2.3"])
def test_security_guard_allows_documentation_and_private_ranges(value):
    assert not GUARD["unsafe"](value)


@pytest.mark.parametrize("value", ["8." * 3 + "8", "123456789:" + "a" * 35, "-----BEGIN " + "PRIVATE KEY-----", "AKIA" + "A" * 16, "sk-" + "a" * 32])
def test_security_guard_detects_public_addresses_and_keys(value):
    assert GUARD["unsafe"](value)


@pytest.mark.parametrize("value", ["198.51.100.10", "0.0.0.0", "255.255.255.255", "version 1.2.3.4", "version: 1.2.3.4", '"version": "1.2.3.4"', "v1.2.3.4", "package==1.2.3.4", "package>=1.2.3.4", "8." * 3 + "8 # prod-data-ok: public resolver"])
def test_security_guard_allows_explicit_exceptions(value):
    assert not GUARD["unsafe"](value)


def test_security_guard_still_checks_other_addresses_and_invalid_exceptions():
    address = "8." * 3 + "8"
    assert GUARD["unsafe"]("version 1.2.3.4 " + address)
    assert GUARD["unsafe"](address + " # prod-data-ok: ")
    assert GUARD["unsafe"](address + " prod-data-ok: reason")


def test_security_guard_skips_dependencies_locks_and_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    address = "8." * 3 + "8"
    paths = ["frontend/node_modules/pkg/index.js", "package-lock.json", "data.bin", "invalid.bin"]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((b"\xff" if name == "invalid.bin" else b"\0" if name.endswith(".bin") else b"") + address.encode())
    monkeypatch.setattr(GUARD["subprocess"], "check_output", lambda *a, **kw: ("\0".join(paths) + "\0").encode())
    assert GUARD["main"]() == 0


def test_security_guard_checks_changed_pinned_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    name = "backend/integrations/xui/openapi/3x-ui-3.x.openapi.json"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    original = (ROOT / name).read_bytes()
    path.write_bytes(original)
    monkeypatch.setattr(GUARD["subprocess"], "check_output", lambda *a, **kw: (name + "\0").encode())
    assert GUARD["main"]() == 0
    path.write_bytes(original + ("\n" + "8." * 3 + "8").encode())
    assert GUARD["main"]() == 1


def test_security_guard_reports_location_without_value(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    address = "8." * 3 + "8"
    (tmp_path / "sample.txt").write_text(address + "\n", encoding="utf-8")
    monkeypatch.setattr(GUARD["subprocess"], "check_output", lambda *a, **kw: b"sample.txt\0")
    assert GUARD["main"]() == 1
    output = capsys.readouterr().err
    assert "sample.txt:1" in output
    assert address not in output


def test_security_guard_checks_ips_by_path_and_secrets_everywhere(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    address = "8." * 3 + "8"
    paths = ["backend/app.py", "backend/tests/sample.py", "docs/sample.md"]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(address, encoding="utf-8")
    monkeypatch.setattr(GUARD["subprocess"], "check_output", lambda *a, **kw: ("\0".join(paths) + "\0").encode())
    assert GUARD["main"]() == 1
    output = capsys.readouterr().err
    assert "backend/app.py:1" in output
    assert "backend/tests/sample.py" not in output
    assert "docs/sample.md" not in output

    (tmp_path / paths[0]).write_text("safe", encoding="utf-8")
    assert GUARD["main"]() == 0
    (tmp_path / paths[1]).write_text("123456789:" + "a" * 35, encoding="utf-8")
    (tmp_path / paths[2]).write_text("123456789:" + "a" * 35, encoding="utf-8")
    assert GUARD["main"]() == 1
    output = capsys.readouterr().err
    assert "backend/tests/sample.py:1" in output
    assert "docs/sample.md:1" in output


def test_redact_node_connection_exception(monkeypatch):
    import client_manager

    address = "node.example.test"
    password = "test-password-value"
    def fail(**kwargs):
        raise requests.ConnectionError(f"https://user:{password}@{address}/login")

    monkeypatch.setattr(client_manager, "get_authenticated_session", fail)
    monkeypatch.setattr(client_manager, "extract_node_auth", lambda *args: ("user", password, None))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(_RedactFilter())
    client_manager.logger.addHandler(handler)
    try:
        ClientManager(lambda value: value)._get_session({"name": "test", "panel_url": "https://example.test"})
    finally:
        client_manager.logger.removeHandler(handler)
    assert "Failed to login" in stream.getvalue()
    assert address not in stream.getvalue()
    assert password not in stream.getvalue()


def _mutation_routes():
    tree = ast.parse((ROOT / "backend/routers/telegram_admin.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router"
                    and decorator.func.attr in {"post", "put", "delete"}):
                yield pytest.param(node, id=f"{decorator.func.attr}:{ast.literal_eval(decorator.args[0])}")


@pytest.mark.parametrize("route", list(_mutation_routes()))
def test_telegram_admin_mutations_require_capability(route):
    def checks(node):
        return {call.func.id for call in ast.walk(node) if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name) and call.func.id in {"require_admin", "require_owner", "require_capability"}}

    dependencies = [value for value in route.args.defaults if isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name) and value.func.id == "Depends"]
    if dependencies:
        assert all(isinstance(value.args[0], ast.Name) and value.args[0].id == "require_admin" for value in dependencies)
        return
    statements = [item for item in route.body if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))]
    first_checks = checks(statements[0])
    if not first_checks and len(statements) > 1:
        first_checks = checks(statements[1])
    assert first_checks & {"require_admin", "require_capability"}
    if route.name == "queue_bulk_lifecycle":
        assert "require_owner" in first_checks
    if "require_capability" in first_checks:
        assert any(isinstance(node, ast.Constant) and node.value == "provisioning_history_clear"
                   for node in ast.walk(statements[0]))
