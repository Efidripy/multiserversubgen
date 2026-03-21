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
