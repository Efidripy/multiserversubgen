import base64
import os
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", tempfile.gettempdir())
import main


def _basic_auth(username: str = "admin", password: str = "secret") -> dict:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def _build_test_app(*, monitoring_enabled: bool) -> FastAPI:
    app = FastAPI(title="Multi-Server Sub Manager", version="3.0", root_path=main.root_path)
    main.register_app_routers(
        app,
        snapshot_collector=main.snapshot_collector,
        render_metrics_response=main.render_metrics_response,
        deps_health_status=main.deps_health_status,
        check_auth=main.check_auth,
        verify_totp_code=main.verify_totp_code,
        get_user_role=main.get_user_role,
        mfa_totp_enabled=main.MFA_TOTP_ENABLED,
        monitoring_enabled=monitoring_enabled,
        get_node_or_404=main.partial(main.get_node_or_404, main.node_service),
        get_cached_traffic_stats=main.get_cached_traffic_stats,
        get_traffic_stats_by_period=main.get_traffic_stats_by_period,
        get_cached_online_clients=main.get_cached_online_clients,
        list_nodes=main.node_service.list_nodes,
        xui_monitor=main.xui_monitor,
        node_service=main.node_service,
        db_path=main.DB_PATH,
        encrypt=main.encrypt,
        requests_verify=main.REQUESTS_VERIFY,
        login_panel=main.login_panel,
        xui_request=main.xui_request,
        invalidate_subscription_cache=main.invalidate_subscription_cache,
        remove_node_metric_labels=main._remove_node_metric_labels,
        node_metric_labels_lock=main.node_metric_labels_lock,
        node_metric_labels_state=main.node_metric_labels_state,
        ws_manager=main.ws_manager,
        logger=main.logger,
        inbound_mgr=main.inbound_mgr,
        invalidate_live_stats_cache=main.invalidate_live_stats_cache,
        client_mgr=main.client_mgr,
        get_cached_clients=main.get_cached_clients,
        get_cached_inbounds=main.inbounds_runtime.get_cached_inbounds,
        check_subscription_rate_limit=main._check_subscription_rate_limit,
        get_emails=main.get_emails,
        get_links_filtered=main.get_links_filtered,
        verify_tls_default=main.VERIFY_TLS,
        list_adguard_sources=main.adguard_runtime.list_sources,
        collect_adguard_once=main.collect_adguard_once,
        adguard_latest=main.adguard_latest,
        adguard_latest_lock=main.adguard_latest_lock,
        adguard_collect_interval_sec=main.ADGUARD_COLLECT_INTERVAL_SEC,
        build_adguard_summary=main.adguard_runtime.build_summary,
        build_adguard_history=main.adguard_runtime.build_history,
        parse_basic_auth_pair=main.adguard_runtime.parse_basic_auth_pair,
        http_probe=main.adguard_runtime.http_probe,
        prom_query=main.adguard_runtime.prom_query,
        prometheus_url=main.PROMETHEUS_URL,
        loki_url=main.LOKI_URL,
        grafana_url=main.GRAFANA_URL,
        prometheus_basic_auth=main.PROMETHEUS_BASIC_AUTH,
        loki_basic_auth=main.LOKI_BASIC_AUTH,
        grafana_basic_auth=main.GRAFANA_BASIC_AUTH,
        web_path=main.WEB_PATH,
        grafana_web_path=main.GRAFANA_WEB_PATH,
        server_monitor=main.server_monitor,
        check_basic_auth_header=main.check_basic_auth_header,
        mfa_totp_ws_strict=main.MFA_TOTP_WS_STRICT,
        pam_authenticate=main.p.authenticate,
        handle_websocket_message=main.handle_websocket_message,
    )
    return app


def test_auth_required_for_nodes(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: False)
    client = TestClient(main.app)

    response = client.get("/api/v1/nodes")

    assert response.status_code == 401


def test_nodes_endpoint_returns_sanitized_rows(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: u == "admin" and p == "secret")
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 2, "name": "beta", "password": "hidden"},
            {"id": 1, "name": "alpha", "password": "hidden"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/nodes", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert [node["name"] for node in payload] == ["beta", "alpha"]
    assert all("password" not in node for node in payload)


def test_inbounds_endpoint_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443", "user": "root", "password": "enc"},
            {"id": 2, "name": "beta", "ip": "2.2.2.2", "port": "443", "user": "root", "password": "enc"},
        ],
    )
    monkeypatch.setattr(
        main.inbound_mgr,
        "get_all_inbounds",
        lambda nodes: [
            {"id": 11, "node_name": "alpha", "protocol": "vless", "security": "reality"},
            {"id": 12, "node_name": "beta", "protocol": "trojan", "security": "tls"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/inbounds?protocol=vless", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["inbounds"][0]["node_name"] == "alpha"


def test_clients_endpoint_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443", "user": "root", "password": "enc"},
        ],
    )
    monkeypatch.setattr(
        main.clients_runtime,
        "get_cached_clients",
        lambda nodes, email_filter=None: [
            {"email": "one@test.local", "node_name": "alpha"},
            {"email": "two@test.local", "node_name": "alpha"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/clients", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["clients"][0]["email"] == "one@test.local"


def test_snapshots_latest_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    main.snapshot_collector._latest = {
        "timestamp": 1234567890,
        "nodes": {
            "alpha": {"name": "alpha", "available": True},
            "beta": {"name": "beta", "available": False},
        },
    }
    client = TestClient(main.app)

    response = client.get("/api/v1/snapshots/latest", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["nodes"][0]["name"] == "alpha"


def test_monitoring_stack_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    client = TestClient(_build_test_app(monitoring_enabled=True))

    response = client.get("/api/v1/monitoring/stack", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert "services" in payload
    assert "prometheus" in payload["services"]
    assert "public_paths" in payload


def test_clients_find_by_ip_auth_required(monkeypatch):
    """find-by-ip requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.get("/api/v1/clients/find-by-ip?ip=1.2.3.4")
    assert response.status_code == 401


def test_clients_find_by_ip_missing_param(monkeypatch):
    """find-by-ip without ip param returns 400 or 422."""
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.get("/api/v1/clients/find-by-ip", headers=_basic_auth())
    # Either validation error (422) or our explicit 400
    assert response.status_code in (400, 422)


def test_clients_last_online_smoke(monkeypatch):
    """last-online returns results key."""
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: [])
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.post("/api/v1/clients/last-online", json={}, headers=_basic_auth())
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert "data" in body


def test_dashboard_summary_auth_required():
    """dashboard/summary requires auth (no credentials → 401)."""
    # Note: this endpoint uses middleware-set auth_user, so a bare test client
    # without the middleware will always get 401 — which is what we verify here.
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 401


def test_dashboard_summary_uses_snapshot_cache_without_xui_fetch(monkeypatch):
    nodes = [
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
    ]
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("traffic fetch must not run")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_online_clients",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("online fetch must not run")),
    )
    main.snapshot_collector._latest = {
        "timestamp": 1234567890.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "online_clients": 3,
                "traffic_total": 1000,
            },
            "beta": {
                "name": "beta",
                "node_id": 2,
                "available": False,
                "online_clients": 0,
                "traffic_total": 0,
            },
        },
    }
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    client = TestClient(app)
    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes_total"] == 2
    assert payload["nodes_online"] == 1
    assert payload["online_clients_total"] == 3
    assert payload["traffic"]["total"] == 1000
    assert payload["cache"]["source"] == "snapshot_collector"


def test_node_server_status_uses_snapshot_cache_without_xui_fetch(monkeypatch):
    node = {"id": 1, "name": "alpha"}
    monkeypatch.setattr(main.node_service, "get_node", lambda node_id: node if node_id == 1 else None)
    monkeypatch.setattr(
        main.xui_monitor,
        "get_server_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("xui fetch must not run")),
    )
    main.snapshot_collector._latest = {
        "timestamp": 1234567890.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "poll_ms": 42.0,
                "server_status": {
                    "node": "alpha",
                    "available": True,
                    "system": {"cpu": 11},
                    "xray": {"running": True},
                    "network": {"upload": 1, "download": 2},
                },
            },
        },
    }
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    client = TestClient(app)
    response = client.get("/api/v1/nodes/1/server-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["cached"] is True
    assert payload["poll_ms"] == 42.0
    assert payload["system"]["cpu"] == 11


def test_servers_status_routes_use_snapshot_cache_without_monitor_fetch(monkeypatch):
    nodes = [
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
    ]
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: nodes)
    monkeypatch.setattr(main.node_service, "get_node", lambda node_id: nodes[node_id - 1] if node_id in (1, 2) else None)

    def _fail_live_fetch(*_args, **_kwargs):
        raise AssertionError("server_monitor live fetch must not run")

    monkeypatch.setattr(main.server_monitor, "get_all_servers_status", _fail_live_fetch)
    monkeypatch.setattr(main.server_monitor, "get_server_status", _fail_live_fetch)
    monkeypatch.setattr(main.server_monitor, "check_server_availability", _fail_live_fetch)

    main.snapshot_collector._latest = {
        "timestamp": 1234567890.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "poll_ms": 12.5,
                "timestamp": 1234567890.0,
                "server_status": {
                    "node": "alpha",
                    "available": True,
                    "system": {"cpu": 8},
                    "xray": {"running": True},
                    "network": {"upload": 1, "download": 2},
                },
            },
            "beta": {
                "name": "beta",
                "node_id": 2,
                "available": False,
                "status": "offline",
                "reason": "timeout",
                "error": "Read timed out",
                "poll_ms": 3000,
                "timestamp": 1234567891.0,
            },
        },
    }
    client = TestClient(_build_test_app(monitoring_enabled=False))

    fleet = client.get("/api/v1/servers/status", headers=_basic_auth())
    single = client.get("/api/v1/servers/1/status", headers=_basic_auth())
    availability = client.get("/api/v1/servers/availability", headers=_basic_auth())

    assert fleet.status_code == 200
    assert fleet.json()["count"] == 2
    assert fleet.json()["servers"][0]["cached"] is True
    assert single.status_code == 200
    assert single.json()["system"]["cpu"] == 8
    assert availability.status_code == 200
    assert availability.json()["availability"][0]["latency_ms"] == 12.5


def test_inbound_update_auth_required():
    """PUT /inbounds/{node_id}/{id} requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.put("/api/v1/inbounds/1/1", json={"remark": "test"})
    assert response.status_code == 401


def test_xray_config_auth_required():
    """GET /nodes/{id}/xray-config requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.get("/api/v1/nodes/1/xray-config")
    assert response.status_code == 401


def test_inbound_reset_all_traffic_auth(monkeypatch):
    """POST inbounds/{id}/reset-all-traffics requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/1/reset-all-traffics")
    assert resp.status_code == 401


def test_inbound_del_all_clients_auth(monkeypatch):
    """POST inbounds/{id}/{id}/del-all-clients requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/1/1/del-all-clients")
    assert resp.status_code == 401


def test_collector_status_auth_required():
    """GET /collector/status requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/collector/status")
    assert resp.status_code == 401


def test_stop_xray_auth_required():
    """POST /nodes/{id}/stop-xray requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/nodes/1/stop-xray")
    assert resp.status_code == 401


def test_backup_all_auth_required():
    """GET /backup/all requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/backup/all")
    assert resp.status_code == 401


def test_automation_reset_all_traffic_auth_required():
    """POST /automation/reset-all-traffic requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/automation/reset-all-traffic", json={})
    assert resp.status_code == 401


def test_nodes_check_connection_auth_required():
    """POST /nodes/check-connection requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/nodes/check-connection", json={"url": "http://1.2.3.4"})
    assert resp.status_code == 401


def test_history_nodes_auth_required():
    """GET /history/nodes/{id} requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/history/nodes/1")
    assert resp.status_code == 401


def test_clients_count_auth_required():
    """GET /clients/count requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/count")
    assert resp.status_code == 401


def test_clients_count_with_node_id_auth(monkeypatch):
    """GET /clients/count?node_id=N requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/count?node_id=1")
    assert resp.status_code == 401


def test_nodes_xray_versions_auth_required():
    """GET /nodes/{id}/xray-versions requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/xray-versions")
    assert resp.status_code == 401


def test_nodes_generate_uuid_auth_required():
    """GET /nodes/{id}/generate-uuid requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/generate-uuid")
    assert resp.status_code == 401


def test_status_endpoint_public(monkeypatch):
    """GET /status is accessible without auth."""
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: [])
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert "nodes_total" in body
    assert "version" in body


def test_sub_grouped_cache_hit_avoids_sqlite(monkeypatch, tmp_path):
    from routers import subscriptions as subscriptions_router
    from routers.subscriptions import build_subscriptions_router
    from services.db_bootstrap import init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    app = FastAPI()
    calls = {"links": 0}

    class NodeServiceStub:
        def list_nodes(self):
            return [{"id": 1, "name": "node1", "ip": "1.2.3.4"}]

    def get_links_filtered(nodes, email, protocol):
        calls["links"] += 1
        return [f"{protocol}://{email}@node1"]

    app.include_router(
        build_subscriptions_router(
            check_auth=lambda request: "admin",
            db_path=db_path,
            node_service=NodeServiceStub(),
            check_subscription_rate_limit=lambda request, key: (True, 0),
            get_emails=lambda nodes: ["alpha@example.com"],
            get_links_filtered=get_links_filtered,
            invalidate_subscription_cache=lambda: None,
            logger=main.logger,
        )
    )
    client = TestClient(app)

    first = client.get("/api/v1/sub-grouped/alpha?protocol=vless&nodes=node1")
    assert first.status_code == 200
    assert first.headers["x-subscription-cache"] == "miss"
    assert base64.b64decode(first.text).decode() == "vless://alpha@example.com@node1"

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("SQLite must not be touched on subscription cache hit")

    monkeypatch.setattr(subscriptions_router, "connect", fail_connect)
    second = client.get("/api/v1/sub-grouped/alpha?protocol=vless&nodes=node1")

    assert second.status_code == 200
    assert second.headers["x-subscription-cache"] == "hit"
    assert second.text == first.text
    assert calls["links"] == 1


def test_sub_grouped_cache_key_includes_filters(tmp_path):
    from routers.subscriptions import build_subscriptions_router
    from services.db_bootstrap import init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    app = FastAPI()

    class NodeServiceStub:
        def list_nodes(self):
            return [{"id": 1, "name": "node1", "ip": "1.2.3.4"}]

    def get_links_filtered(nodes, email, protocol):
        return [f"{protocol}://{email}@node1"]

    app.include_router(
        build_subscriptions_router(
            check_auth=lambda request: "admin",
            db_path=db_path,
            node_service=NodeServiceStub(),
            check_subscription_rate_limit=lambda request, key: (True, 0),
            get_emails=lambda nodes: ["alpha@example.com"],
            get_links_filtered=get_links_filtered,
            invalidate_subscription_cache=lambda: None,
            logger=main.logger,
        )
    )
    client = TestClient(app)

    vless = client.get("/api/v1/sub-grouped/alpha?protocol=vless&nodes=node1")
    trojan = client.get("/api/v1/sub-grouped/alpha?protocol=trojan&nodes=node1")

    assert vless.status_code == 200
    assert trojan.status_code == 200
    assert vless.headers["x-subscription-cache"] == "miss"
    assert trojan.headers["x-subscription-cache"] == "miss"
    assert base64.b64decode(vless.text).decode() == "vless://alpha@example.com@node1"
    assert base64.b64decode(trojan.text).decode() == "trojan://alpha@example.com@node1"


def test_inbound_set_enable_auth_required():
    """POST /inbounds/{n}/{i}/set-enable requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/1/1/set-enable", json={"enable": True})
    assert resp.status_code == 401


def test_inbound_reset_traffic_auth_required():
    """POST /inbounds/{n}/{i}/reset-traffic requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/1/1/reset-traffic")
    assert resp.status_code == 401


def test_inbound_batch_enable_auth_required():
    """POST /inbounds/batch-enable requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/batch-enable", json={"inbound_ids": [1], "enable": True})
    assert resp.status_code == 401


def test_inbound_batch_update_auth_required():
    """POST /inbounds/batch-update requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.post("/api/v1/inbounds/batch-update", json={"inbound_ids": [1], "updates": {}})
    assert resp.status_code == 401


def test_nodes_generate_x25519_auth_required():
    """GET /nodes/{id}/generate-x25519 requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/generate-x25519")
    assert resp.status_code == 401


def test_nodes_generate_mldsa65_auth_required():
    """GET /nodes/{id}/generate-mldsa65 requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/generate-mldsa65")
    assert resp.status_code == 401


def test_nodes_outbounds_traffic_auth_required():
    """GET /nodes/{id}/outbounds-traffic requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/outbounds-traffic")
    assert resp.status_code == 401


def test_nodes_server_history_auth_required():
    """GET /nodes/{id}/server-history/{metric} requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/nodes/1/server-history/cpu")
    assert resp.status_code == 401


def test_clients_expired_auth_required():
    """GET /clients/expired requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/expired")
    assert resp.status_code == 401


def test_clients_depleted_auth_required():
    """GET /clients/depleted requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/depleted")
    assert resp.status_code == 401


def test_inbounds_stats_auth_required():
    """GET /inbounds/stats requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/inbounds/stats")
    assert resp.status_code == 401


def test_clients_search_auth_required():
    """GET /clients/search requires auth."""
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/search")
    assert resp.status_code == 401


def test_clients_search_with_auth(monkeypatch):
    """GET /clients/search returns paginated results."""
    monkeypatch.setenv("SM_API_USER", "admin")
    monkeypatch.setenv("SM_API_PASS", "secret")
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/search?q=test&limit=10&offset=0", auth=("admin", "secret"))
    assert resp.status_code == 200
    data = resp.json()
    assert "clients" in data
    assert "total" in data
    assert "limit" in data
    assert data["limit"] == 10
