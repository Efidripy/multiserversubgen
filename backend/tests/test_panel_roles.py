import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.auth.service import AuthService
from routers.users import RoleBody, build_users_router
from services.db_bootstrap import init_db
from services.panel_roles import PanelRoleStore


def _router(store, audit, role="admin"):
    return build_users_router(
        check_auth=lambda _request: "admin",
        get_user_role=lambda _username: role,
        panel_roles=store,
        role_admins=set(),
        role_operators=set(),
        role_owners=set(),
        enqueue_audit_event=audit.append,
    )


def _endpoint(router, path, method):
    return next(route.endpoint for route in router.routes if route.path == path and method in route.methods)


def test_db_priority_and_role_changes_are_immediate(tmp_path):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    service = AuthService(
        role_admins={"admin"},
        role_operators={"operator"},
        role_lookup=store.get_role,
    )
    store.set_on_change(service.invalidate_role_cache)

    store.set_role("admin", "viewer", "admin")
    assert service.get_user_role("admin") == "viewer"
    store.set_role("operator", "admin", "admin")
    assert service.get_user_role("operator") == "admin"
    store.set_role("user", "operator", "admin")
    assert service.get_user_role("user") == "operator"
    store.set_role("user", "viewer", "admin")
    assert service.get_user_role("user") == "viewer"


def test_users_router_writes_and_audits(tmp_path, monkeypatch):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    audit = []
    router = _router(store, audit)
    monkeypatch.setattr("routers.users.pwd.getpwnam", lambda _name: SimpleNamespace())
    request = SimpleNamespace()

    put = _endpoint(router, "/api/v1/users/{username}/role", "PUT")
    assert put("paneluser", RoleBody(role="operator"), request) == {
        "username": "paneluser",
        "role": "operator",
        "source": "db",
    }
    assert audit[-1]["target"] == "paneluser"
    assert audit[-1]["new_role"] == "operator"

    delete = _endpoint(router, "/api/v1/users/{username}/role", "DELETE")
    assert delete("paneluser", request) == {"username": "paneluser", "removed": True}


def test_users_router_rejects_invalid_and_locked_users(tmp_path):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    router = build_users_router(
        check_auth=lambda _request: "admin",
        get_user_role=lambda _username: "admin",
        panel_roles=store,
        role_admins={"admin"},
        role_operators=set(),
        role_owners=set(),
        enqueue_audit_event=lambda _event: None,
    )
    put = _endpoint(router, "/api/v1/users/{username}/role", "PUT")
    with pytest.raises(HTTPException) as invalid:
        put("Bad Name", RoleBody(role="viewer"), SimpleNamespace())
    assert invalid.value.status_code == 422
    with pytest.raises(HTTPException) as locked:
        put("admin", RoleBody(role="viewer"), SimpleNamespace())
    assert locked.value.status_code == 409


def test_users_router_requires_admin(tmp_path):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    viewer_router = _router(store, [], role="viewer")
    list_endpoint = _endpoint(viewer_router, "/api/v1/users", "GET")
    with pytest.raises(HTTPException) as forbidden:
        list_endpoint(SimpleNamespace())
    assert forbidden.value.status_code == 403

    admin_router = _router(store, [])
    assert list_endpoint is not _endpoint(admin_router, "/api/v1/users", "GET")
    assert _endpoint(admin_router, "/api/v1/users", "GET")(SimpleNamespace())["users"] == []


def test_users_router_unknown_system_user_and_self_change(tmp_path, monkeypatch):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    router = _router(PanelRoleStore(db_path), [])
    put = _endpoint(router, "/api/v1/users/{username}/role", "PUT")

    def missing(_name):
        raise KeyError(_name)

    monkeypatch.setattr("routers.users.pwd.getpwnam", missing)
    with pytest.raises(HTTPException) as unknown:
        put("ghost", RoleBody(role="viewer"), SimpleNamespace())
    assert unknown.value.status_code == 404
    # The caller ("admin" in _router) may not change their own role, even when not in env.
    with pytest.raises(HTTPException) as own:
        put("admin", RoleBody(role="viewer"), SimpleNamespace())
    assert own.value.status_code == 409


def test_owner_and_env_users_follow_new_mutation_rules(tmp_path, monkeypatch):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    admins = {"admin", "envadmin"}
    operators = {"envoperator"}
    owners = {"owner"}
    service = AuthService(
        role_admins=admins,
        role_operators=operators,
        role_owners=owners,
        role_lookup=store.get_role,
    )
    store.set_on_change(service.invalidate_role_cache)
    router = build_users_router(
        check_auth=lambda _request: "admin",
        get_user_role=service.get_user_role,
        panel_roles=store,
        role_admins=lambda: admins,
        role_operators=lambda: operators,
        role_owners=lambda: owners,
        enqueue_audit_event=lambda _event: None,
    )
    monkeypatch.setattr("routers.users.pwd.getpwnam", lambda _name: SimpleNamespace())
    request = SimpleNamespace()
    put = _endpoint(router, "/api/v1/users/{username}/role", "PUT")
    delete = _endpoint(router, "/api/v1/users/{username}/role", "DELETE")

    for username in ("owner", "admin"):
        with pytest.raises(HTTPException) as locked:
            put(username, RoleBody(role="viewer"), request)
        assert locked.value.status_code == 409
    put("envadmin", RoleBody(role="viewer"), request)
    put("envoperator", RoleBody(role="admin"), request)
    assert service.get_user_role("envadmin") == "viewer"
    assert service.get_user_role("envoperator") == "admin"
    assert delete("envadmin", request) == {"username": "envadmin", "removed": True}
    assert delete("envoperator", request) == {"username": "envoperator", "removed": True}
    assert service.get_user_role("envadmin") == "admin"
    assert service.get_user_role("envoperator") == "operator"


def test_users_router_lists_env_and_db_users_with_candidates(tmp_path, monkeypatch):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    store = PanelRoleStore(db_path)
    store.set_role("viewer1", "viewer", "root")
    store.set_role("op1", "operator", "root")
    router = build_users_router(
        check_auth=lambda _request: "root",
        get_user_role=lambda name: "admin" if name == "root" else "viewer",
        panel_roles=store,
        role_admins={"root"},
        role_operators=set(),
        role_owners={"root"},
        enqueue_audit_event=lambda _event: None,
    )
    fake_users = [
        SimpleNamespace(pw_name="root", pw_uid=0),
        SimpleNamespace(pw_name="alice", pw_uid=1001),
        SimpleNamespace(pw_name="op1", pw_uid=1002),
        SimpleNamespace(pw_name="nobody", pw_uid=65534),
    ]
    monkeypatch.setattr("routers.users.pwd.getpwall", lambda: fake_users)

    result = _endpoint(router, "/api/v1/users", "GET")(SimpleNamespace())

    assert result["candidates"] == ["alice"]
    assert result["me"] == {"username": "root", "owner": True}
    assert [(u["username"], u["source"], u["owner"], u["locked"]) for u in result["users"]][0] == (
        "root", "env", True, True
    )
    by_name = {u["username"]: u for u in result["users"]}
    assert by_name["root"]["env_role"] == "admin"
    assert by_name["op1"]["env_role"] is None
    assert by_name["viewer1"]["env_role"] is None
    assert {u["username"] for u in result["users"]} == {"root", "viewer1", "op1"}


def test_stale_inflight_lookup_cannot_restore_revoked_role():
    calls = []
    service = AuthService()

    def lookup(_name):
        calls.append(1)
        # A demotion commits and invalidates the cache while this lookup is still running.
        service.invalidate_role_cache()
        return "admin"

    service.role_lookup = lookup
    assert service.get_user_role("alice") == "admin"  # the in-flight caller still sees what it read
    service.role_lookup = lambda _name: "viewer"
    assert service.get_user_role("alice") == "viewer"  # but the stale value was not cached


def test_role_lookup_failure_falls_back_to_environment_role():
    service = AuthService(
        role_admins={"envadmin"},
        role_operators={"envoperator"},
        role_lookup=lambda _name: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )
    assert service.get_user_role("envadmin") == "admin"
    assert service.get_user_role("envoperator") == "operator"
    assert service.get_user_role("unknown") == "viewer"


def test_candidates_skip_names_the_api_would_reject(tmp_path, monkeypatch):
    db_path = os.fspath(tmp_path / "admin.db")
    init_db(db_path)
    router = _router(PanelRoleStore(db_path), [])
    monkeypatch.setattr(
        "routers.users.pwd.getpwall",
        lambda: [SimpleNamespace(pw_name="john.doe", pw_uid=1001), SimpleNamespace(pw_name="jane", pw_uid=1002)],
    )
    assert _endpoint(router, "/api/v1/users", "GET")(SimpleNamespace())["candidates"] == ["jane"]


def test_websocket_manager_closes_sockets_whose_role_changed():
    import asyncio

    from websocket_manager import ConnectionManager

    class FakeSocket:
        def __init__(self):
            self.closed = None

        async def accept(self):
            pass

        async def close(self, code=1000):
            self.closed = code

    async def scenario():
        manager = ConnectionManager()
        kept, demoted = FakeSocket(), FakeSocket()
        await manager.connect(kept, accept=False, user="a", role="admin")
        await manager.connect(demoted, accept=False, user="b", role="operator")
        count = await asyncio.to_thread(
            manager.close_sockets_with_changed_role, lambda user: "admin" if user == "a" else "viewer"
        )
        await asyncio.sleep(0.05)
        return count, kept.closed, demoted.closed

    assert asyncio.run(scenario()) == (1, None, 1008)
