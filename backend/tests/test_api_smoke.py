import base64
import hashlib
import hmac
import json
import os
import sqlite3
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
        issue_ws_ticket=main.auth_service.issue_ws_ticket,
        issue_web_session=main.auth_service.issue_web_session,
        web_session_cookie_name=main.WEB_SESSION_COOKIE_NAME,
        web_session_ttl_sec=main.WEB_SESSION_TTL_SEC,
        verify_ws_ticket=main.auth_service.verify_ws_ticket,
        mfa_totp_enabled=main.MFA_TOTP_ENABLED,
        monitoring_enabled=monitoring_enabled,
        get_node_or_404=main.partial(main.get_node_or_404, main.node_service),
        get_cached_traffic_stats=main.get_cached_traffic_stats,
        get_cached_traffic_stats_projection=main.get_cached_traffic_stats_projection,
        get_cached_traffic_stats_projection_by_period=main.get_cached_traffic_stats_projection_by_period,
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
        get_cached_slim_inbounds=main.inbounds_runtime.get_cached_slim_inbounds,
        get_cached_inbound_options=main.inbounds_runtime.get_cached_inbound_options,
        check_subscription_rate_limit=main._check_subscription_rate_limit,
        get_emails=main.get_emails,
        get_links_filtered=main.get_links_filtered,
        register_subscription_response_cache_invalidator=main.register_subscription_response_cache_invalidator,
        subscription_signing_secret=main.SUBSCRIPTION_SIGNING_SECRET,
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


def test_inbound_read_projection_endpoints_are_separate_from_full_dtos(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [{"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443"}],
    )
    monkeypatch.setattr(
        main.inbounds_runtime,
        "get_cached_slim_inbounds",
        lambda _nodes: [{"detail_level": "slim", "id": 11, "settings": {"clients": []}}],
    )
    monkeypatch.setattr(
        main.inbounds_runtime,
        "get_cached_inbound_options",
        lambda _nodes: [{"detail_level": "option", "id": 11, "protocol": "vless"}],
    )
    client = TestClient(_build_test_app(monitoring_enabled=False))

    slim = client.get("/api/v1/inbounds/slim", headers=_basic_auth())
    options = client.get("/api/v1/inbounds/options", headers=_basic_auth())

    assert slim.status_code == 200
    assert slim.json() == {"detail_level": "slim", "inbounds": [{"detail_level": "slim", "id": 11, "settings": {"clients": []}}], "count": 1}
    assert options.status_code == 200
    assert options.json() == {"detail_level": "option", "inbounds": [{"detail_level": "option", "id": 11, "protocol": "vless"}], "count": 1}


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
            "alpha": {
                "name": "alpha",
                "available": True,
                "inbounds": [{"clientStats": [{"email": "private@example.test"}]}],
                "server_status": {"token": "must-not-leak"},
            },
            "beta": {"name": "beta", "available": False},
        },
    }
    client = TestClient(main.app)

    response = client.get("/api/v1/snapshots/latest", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["nodes"][0]["name"] == "alpha"
    assert "inbounds" not in payload["nodes"][0]
    assert "server_status" not in payload["nodes"][0]


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


def test_client_presence_uses_collector_projection_without_fleet_scan(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main.snapshot_collector,
        "latest_client_presence",
        lambda: calls.append("presence") or {
            "projection": "client-presence-v1",
            "timestamp": 123.0,
            "online_emails": ["active@example.test"],
            "online_by_node": {"12": ["active@example.test"]},
            "node_names": {"12": "alpha"},
            "last_seen": {"active@example.test": 123.0},
            "last_seen_by_node": {"12": {"active@example.test": 123.0}},
        },
    )
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: (_ for _ in ()).throw(AssertionError("presence must not enumerate nodes")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_online_clients",
        lambda *_args: (_ for _ in ()).throw(AssertionError("presence must not start a fleet scan")),
    )
    unauthenticated_app = _build_test_app(monitoring_enabled=False)
    assert TestClient(unauthenticated_app).get("/api/v1/clients/presence").status_code == 401

    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/clients/presence")

    assert response.status_code == 200
    assert response.json() == {
        "projection": "client-presence-v1",
        "timestamp": 123.0,
        "online_emails": ["active@example.test"],
        "online_by_node": {"12": ["active@example.test"]},
        "node_names": {"12": "alpha"},
        "last_seen": {"active@example.test": 123.0},
        "last_seen_by_node": {"12": {"active@example.test": 123.0}},
    }
    online_response = TestClient(app).get("/api/v1/clients/online")
    assert online_response.status_code == 200
    assert online_response.json() == {
        "online_clients": [{"email": "active@example.test", "node_id": "12", "node_name": "alpha"}],
        "count": 1,
        "source": "snapshot_collector",
    }
    assert calls == ["presence", "presence"]


def test_dashboard_summary_auth_required():
    """dashboard/summary requires auth (no credentials → 401)."""
    # Note: this endpoint uses middleware-set auth_user, so a bare test client
    # without the middleware will always get 401 — which is what we verify here.
    client = TestClient(_build_test_app(monitoring_enabled=False))
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 401


def test_traffic_period_route_uses_projection_without_nodes_or_legacy_traffic_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy traffic fetch must not run")),
    )
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: (_ for _ in ()).throw(AssertionError("period read must not enumerate nodes")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda group_by, period: calls.append((group_by, period)) or {
            "stats": {
                "alpha": {"up": 1, "down": 9, "total": 10},
                "beta": {"up": 1, "down": 4, "total": 5},
            },
            "group_by": group_by,
            "period": period,
            "cache_source": "snapshot_collector",
            "cache_timestamp": 1234567890,
            "identity_stats": {"node:1": {"_display_key": "alpha", "total": 10}},
        },
    )
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/traffic/stats-by-period?group_by=node&period=week&limit=1")

    assert response.status_code == 200
    assert calls == [("node", "week")]
    payload = response.json()
    assert payload["stats"] == {"alpha": {"up": 1, "down": 9, "total": 10}}
    assert payload["summary"] == {"upload": 2, "download": 13, "total": 15, "count": 2}
    assert payload["cache_source"] == "snapshot_collector"
    assert "identity_stats" not in payload


def test_client_traffic_totals_reads_only_requested_projection_entries(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy traffic fetch must not run")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda group_by, period: calls.append((group_by, period)) or {
            "stats": {
                "Active@Example.Test": {"up": 2, "down": 3},
                "active@example.test": {"up": 30, "down": 40},
                "other@example.test": {"up": 40, "down": 60},
            },
        },
    )
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    client = TestClient(app)
    response = client.post("/api/v1/traffic/client-totals", json={
        "emails": [" active@example.test ", "missing@example.test"],
        "period": "week",
    })

    assert response.status_code == 200
    assert calls == [("client", "week")]
    assert response.json() == {
        "totals": {"active@example.test": 75},
        "missing": ["missing@example.test"],
        "period": "week",
    }
    assert client.post("/api/v1/traffic/client-totals", json={"emails": "not-a-list"}).status_code == 422


def test_client_traffic_stats_by_period_coalesces_case_variants_before_limit(monkeypatch):
    calls = []

    def projection(group_by, period):
        calls.append((group_by, period))
        if group_by == "client":
            return {
                "stats": {
                    "Active@Example.Test": {"up": 2, "down": 3, "total": 5, "count": 1},
                    "active@example.test": {"up": 30, "down": 40, "total": 70, "count": 1},
                    "other@example.test": {"up": 20, "down": 40, "total": 60, "count": 1},
                },
            }
        return {"stats": {"alpha": {"up": 1, "down": 9, "total": 10}}}

    monkeypatch.setattr(main, "get_cached_traffic_stats_projection_by_period", projection)
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    client = TestClient(app)
    response = client.get("/api/v1/traffic/stats-by-period?group_by=client&period=week&limit=1")

    assert response.status_code == 200
    assert calls == [("client", "week")]
    assert response.json()["stats"] == {
        "active@example.test": {"up": 32, "down": 43, "total": 75, "count": 2},
    }
    assert response.json()["summary"] == {"upload": 52, "download": 83, "total": 135, "count": 2}

    node_response = client.get("/api/v1/traffic/stats-by-period?group_by=node&period=week")
    assert node_response.status_code == 200
    assert node_response.json()["stats"] == {"alpha": {"up": 1, "down": 9, "total": 10}}


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
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection",
        lambda _group_by: {"stats": {}, "cache_source": "empty"},
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda _group_by, period: {
            "stats": {"alpha@example.test": {"up": 250, "down": 750, "total": 1000}},
            "current_count": 1,
            "period": period,
            "cache_source": "memory",
        },
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
    assert payload["online_by_node_id"] == {"1": 3, "2": 0}
    assert payload["traffic"] == {"upload": 250, "download": 750, "total": 1000}
    assert payload["traffic_period"] == "all_time"
    assert payload["cache"]["source"] == "snapshot_collector"


def test_dashboard_summary_returns_sorted_cached_top_clients_without_fleet_fetch(monkeypatch):
    nodes = [{"id": 1, "name": "alpha"}]
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dashboard must not trigger a fleet fetch")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection",
        lambda _group_by: {
            "stats": {
                "least@example.test": {"up": 2, "down": 3},
                "highest@example.test": {"up": 400, "down": 600, "total": 1000},
                "middle@example.test": {"up": 30, "down": 70, "total": 100},
                "system@example.test": {"up": 500, "down": 1500, "total": 2000},
                "bad@example.test": None,
            },
            "system_client_emails": ["SYSTEM@example.test"],
            "cache_source": "memory",
            "cache_timestamp": 1234567890.0,
        },
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda _group_by, period: {
            "stats": {
                "least@example.test": {"up": 2, "down": 3},
                "highest@example.test": {"up": 400, "down": 600, "total": 1000},
                "middle@example.test": {"up": 30, "down": 70, "total": 100},
                "system@example.test": {"up": 500, "down": 1500, "total": 2000},
                "bad@example.test": None,
            },
            "system_client_emails": ["SYSTEM@example.test"],
            "current_count": 5,
            "period": period,
            "cache_source": "memory",
            "cache_timestamp": 1234567890.0,
        },
    )
    main.snapshot_collector._latest = {"timestamp": 1234567890.0, "nodes": {}}
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clients_total"] == 5
    assert [client["email"] for client in payload["top_clients"]] == [
        "highest@example.test",
        "middle@example.test",
        "least@example.test",
    ]
    assert payload["top_clients"][0] == {
        "email": "highest@example.test",
        "upload": 400,
        "download": 600,
        "total": 1000,
    }
    assert payload["traffic"] == {"upload": 932, "download": 2173, "total": 3105}
    assert payload["cache"]["client_traffic_source"] == "memory"


def test_dashboard_summary_coalesces_case_variants_before_top_clients(monkeypatch):
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: [])
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dashboard must not trigger a fleet fetch")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection",
        lambda _group_by: {
            "stats": {
                "Active@Example.Test": {"up": 2, "down": 3, "total": 5},
                "active@example.test": {"up": 30, "down": 40, "total": 70},
                "other@example.test": {"up": 20, "down": 40, "total": 60},
            },
            "cache_source": "memory",
        },
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda _group_by, period: {
            "stats": {
                "Active@Example.Test": {"up": 2, "down": 3, "total": 5},
                "active@example.test": {"up": 30, "down": 40, "total": 70},
                "other@example.test": {"up": 20, "down": 40, "total": 60},
            },
            "period": period,
        },
    )
    main.snapshot_collector._latest = {"timestamp": 1234567890.0, "nodes": {}}
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    payload = TestClient(app).get("/api/v1/dashboard/summary").json()

    assert payload["top_clients"] == [
        {"email": "active@example.test", "upload": 32, "download": 43, "total": 75},
        {"email": "other@example.test", "upload": 20, "download": 40, "total": 60},
    ]


def test_dashboard_summary_rejects_unsupported_traffic_period(monkeypatch):
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: [])
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/dashboard/summary?period=year")

    assert response.status_code == 400


def test_dashboard_overview_is_one_projection_and_never_serializes_node_secrets(monkeypatch):
    nodes = [{
        "id": 1,
        "name": "alpha",
        "panel_url": "https://admin:panel-secret@alpha.example.test:5443/xui?ticket=private",
        "user": "admin",
        "password": "node-password",
        "bearer_token": "node-token",
        "enabled": True,
    }]
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("overview must not trigger a fleet fetch")),
    )
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda _group_by, period: {"stats": {}, "current_count": 0, "period": period, "cache_source": "memory"},
    )
    main.snapshot_collector._latest = {
        "timestamp": 1234567890.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "online_clients": 3,
                "inbounds": [{"settings": {"clients": [{"email": "private@example.test"}]}}],
                "inbounds_result": {"inbounds": [{"id": 1}]},
                "server_status": {"session": "private"},
            },
        },
    }
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/dashboard/overview?period=week")

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection"] == "dashboard-v1"
    assert payload["summary"]["traffic_period"] == "week"
    assert payload["fleet"][0]["name"] == "alpha"
    assert payload["fleet"][0]["panel_url"] == "https://alpha.example.test:5443/xui"
    serialized = response.text
    for forbidden in ("panel-secret", "node-password", "node-token", "private@example.test", "inbounds_result"):
        assert forbidden not in serialized


def test_dashboard_overview_does_not_treat_a_derived_node_url_as_panel_address(monkeypatch):
    nodes = [{
        "id": 1,
        "name": "emoji node",
        "url": "https://derived-from-node-name.invalid",
        "ip": "panel.example.test",
        "port": "5443",
        "scheme": "https",
        "base_path": "panel",
    }]
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        main,
        "get_cached_traffic_stats_projection_by_period",
        lambda _group_by, period: {"stats": {}, "current_count": 0, "period": period, "cache_source": "memory"},
    )
    main.snapshot_collector._latest = {"timestamp": 1234567890.0, "nodes": {}}
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/dashboard/overview")

    assert response.status_code == 200
    fleet_node = response.json()["fleet"][0]
    assert fleet_node["panel_url"] == ""
    assert fleet_node["ip"] == "panel.example.test"
    assert fleet_node["port"] == "5443"
    assert fleet_node["base_path"] == "panel"


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


def test_node_server_status_does_not_invent_telemetry_from_incomplete_snapshot(monkeypatch):
    node = {"id": 1, "name": "alpha"}
    monkeypatch.setattr(main.node_service, "get_node", lambda node_id: node if node_id == 1 else None)
    main.snapshot_collector._latest = {
        "timestamp": 1234567890.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "cpu": 7,
                "traffic_total": 987654,
            },
        },
    }
    app = _build_test_app(monitoring_enabled=False)

    @app.middleware("http")
    async def _inject_auth_user(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    response = TestClient(app).get("/api/v1/nodes/1/server-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert "system" not in payload
    assert "network" not in payload


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

    monkeypatch.setattr(main.server_monitor, "get_server_status", _fail_live_fetch)

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
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
            ("Alpha", "alpha", json.dumps(["alpha@example.com"]), json.dumps([])),
        )
        conn.commit()
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
            subscription_signing_secret="test-subscription-secret",
            invalidate_subscription_cache=lambda: None,
            logger=main.logger,
        )
    )
    client = TestClient(app)

    payload = base64.urlsafe_b64encode(b"group|alpha|4102444800").decode().rstrip("=")
    signature = hmac.new(b"test-subscription-secret", base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)), hashlib.sha256).hexdigest()
    token = f"{payload}.{signature}"
    first = client.get(f"/api/v1/sub-grouped/{token}?protocol=vless&nodes=node1")
    assert first.status_code == 200
    assert first.headers["x-subscription-cache"] == "miss"
    assert base64.b64decode(first.text).decode() == "vless://alpha@example.com@node1"

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("SQLite must not be touched on subscription cache hit")

    monkeypatch.setattr(subscriptions_router, "connect", fail_connect)
    second = client.get(f"/api/v1/sub-grouped/{token}?protocol=vless&nodes=node1")

    assert second.status_code == 200
    assert second.headers["x-subscription-cache"] == "hit"
    assert second.text == first.text
    assert calls["links"] == 1


def test_sub_grouped_cache_key_includes_filters(tmp_path):
    from routers.subscriptions import build_subscriptions_router
    from services.db_bootstrap import init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
            ("Alpha", "alpha", json.dumps(["alpha@example.com"]), json.dumps([])),
        )
        conn.commit()
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
            subscription_signing_secret="test-subscription-secret",
            invalidate_subscription_cache=lambda: None,
            logger=main.logger,
        )
    )
    client = TestClient(app)

    payload = base64.urlsafe_b64encode(b"group|alpha|4102444800").decode().rstrip("=")
    signature = hmac.new(b"test-subscription-secret", base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)), hashlib.sha256).hexdigest()
    token = f"{payload}.{signature}"
    vless = client.get(f"/api/v1/sub-grouped/{token}?protocol=vless&nodes=node1")
    trojan = client.get(f"/api/v1/sub-grouped/{token}?protocol=trojan&nodes=node1")

    assert vless.status_code == 200
    assert trojan.status_code == 200
    assert vless.headers["x-subscription-cache"] == "miss"
    assert trojan.headers["x-subscription-cache"] == "miss"
    assert base64.b64decode(vless.text).decode() == "vless://alpha@example.com@node1"
    assert base64.b64decode(trojan.text).decode() == "trojan://alpha@example.com@node1"


def test_sub_grouped_cache_is_cleared_by_shared_subscription_invalidation(tmp_path):
    from core.main_facades import build_subscription_links_facade
    from routers.subscriptions import build_subscriptions_router
    from services.db_bootstrap import init_db
    from services.subscription_tokens import ensure_tokens

    class SubscriptionLinksServiceStub:
        def __init__(self):
            self.invalidations = 0

        def configure_snapshot_db(self, _db_path):
            pass

        def invalidate_subscription_cache(self):
            self.invalidations += 1

        def fetch_inbounds(self, _node):
            return []

        def get_emails(self, _nodes):
            return []

        def get_links_filtered(self, _nodes, _email, _protocol=None):
            return []

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
            ("Alpha", "alpha", json.dumps(["alpha@example.com"]), json.dumps([])),
        )
        conn.commit()

    service = SubscriptionLinksServiceStub()
    (
        invalidate_subscription_cache,
        _,
        _,
        _,
        register_response_cache_invalidator,
    ) = build_subscription_links_facade(subscription_links_service=service, db_path=db_path)
    link_value = {"value": "vless://before"}
    app = FastAPI()
    app.include_router(
        build_subscriptions_router(
            check_auth=lambda _request: "admin",
            db_path=db_path,
            node_service=type("NodeServiceStub", (), {"list_nodes": lambda self: [{"name": "node1"}]})(),
            check_subscription_rate_limit=lambda _request, _key: (True, 0),
            get_emails=lambda _nodes: ["alpha@example.com"],
            get_links_filtered=lambda _nodes, _email, _protocol: [link_value["value"]],
            subscription_signing_secret="test-subscription-secret",
            invalidate_subscription_cache=invalidate_subscription_cache,
            register_subscription_response_cache_invalidator=register_response_cache_invalidator,
            logger=main.logger,
        )
    )
    token = ensure_tokens(db_path, "group", ["alpha"])["alpha"]
    client = TestClient(app)

    first = client.get(f"/api/v1/sub-grouped/{token}")
    second = client.get(f"/api/v1/sub-grouped/{token}")
    assert first.headers["x-subscription-cache"] == "miss"
    assert second.headers["x-subscription-cache"] == "hit"
    assert base64.b64decode(second.text).decode() == "vless://before"

    link_value["value"] = "vless://after"
    invalidate_subscription_cache()
    refreshed = client.get(f"/api/v1/sub-grouped/{token}")

    assert service.invalidations == 1
    assert refreshed.headers["x-subscription-cache"] == "miss"
    assert base64.b64decode(refreshed.text).decode() == "vless://after"


def test_inbound_update_invalidates_subscription_cache():
    from routers.inbounds import build_inbounds_router

    class InboundManagerStub:
        def update_inbound(self, _node, _inbound_id, _updates):
            return True

    invalidations = {"subscription": 0, "live_stats": 0}
    app = FastAPI()
    app.include_router(
        build_inbounds_router(
            check_auth=lambda _request: "admin",
            inbound_mgr=InboundManagerStub(),
            get_cached_inbounds=lambda _nodes: [],
            get_cached_slim_inbounds=lambda _nodes: [],
            get_cached_inbound_options=lambda _nodes: [],
            node_service=type("NodeServiceStub", (), {"list_nodes": lambda self: [{"id": 1, "name": "node1"}]})(),
            get_node_or_404=lambda _node_id: {"id": 1, "name": "node1"},
            invalidate_subscription_cache=lambda: invalidations.__setitem__("subscription", invalidations["subscription"] + 1),
            invalidate_live_stats_cache=lambda: invalidations.__setitem__("live_stats", invalidations["live_stats"] + 1),
            ws_manager=object(),
        )
    )

    response = TestClient(app).put("/api/v1/inbounds/1/42", json={"port": 8443})

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert invalidations == {"subscription": 1, "live_stats": 1}


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
    main.auth_cache.clear()
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: u == "admin" and p == "secret")
    client = TestClient(_build_test_app(monitoring_enabled=False))
    resp = client.get("/api/v1/clients/search?q=test&limit=10&offset=0", auth=("admin", "secret"))
    assert resp.status_code == 200
    data = resp.json()
    assert "clients" in data
    assert "total" in data
    assert "limit" in data
    assert data["limit"] == 10
