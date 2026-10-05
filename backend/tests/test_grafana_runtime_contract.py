from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_install_and_update_keep_mssg_grafana_settings_in_a_dedicated_drop_in():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = _read(relative_path)

        assert "configure_grafana_pid_directory()" in script
        assert "install -d -o grafana -g grafana -m 0750 /var/lib/grafana" in script
        assert "/etc/systemd/system/grafana-server.service.d/40-sub-manager.conf" in script
        assert 'Environment="PID_FILE_DIR=/var/lib/grafana"' in script
        assert 'Environment="GF_SERVER_ROOT_URL=${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${GRAFANA_WEB_PATH}/"' in script
        assert "cfg.read('/etc/grafana/grafana.ini')" not in script
        assert "with open('/etc/grafana/grafana.ini', 'w')" not in script
        assert "configure_grafana_pid_directory || return 1" in script
        assert "wait_for_grafana_http()" in script


def test_install_and_update_fail_when_the_local_grafana_http_probe_never_becomes_ready():
    install = _read("scripts/installer/install.sh")
    update = _read("scripts/installer/update.sh")

    assert "wait_for_grafana_http || return 1" in install
    assert "wait_for_grafana_http || return 1" in update


def test_sub_manager_dashboard_provider_isolated_from_other_grafana_dashboards():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = _read(relative_path)

        assert "path: /var/lib/grafana/dashboards/sub-manager" in script
        assert "install -d -o grafana -g grafana -m 0750 /var/lib/grafana/dashboards/sub-manager" in script
        assert "/var/lib/grafana/dashboards/sub-manager/sub-manager-dashboard.json" in script
        assert "chown -R grafana:grafana /var/lib/grafana/dashboards/sub-manager" in script
        assert "chown -R grafana:grafana /var/lib/grafana/dashboards\n" not in script


def test_smoke_checks_the_grafana_unit_and_both_routing_hops_when_enabled():
    smoke = _read("scripts/ops/smoke-test.sh")

    assert 'check "systemd grafana-server active" systemctl is-active --quiet grafana-server' in smoke
    assert 'local Grafana /login is reachable' in smoke
    assert 'public Grafana URL is reachable' in smoke
    assert 'GRAFANA_HTTP_PORT < 1 || GRAFANA_HTTP_PORT > 65535' in smoke


def test_grafana_subpath_proxy_preserves_upstream_login_statuses():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = _read(relative_path)
        grafana_location = script.split("# --- Grafana under dedicated path ---", 1)[1].split("SNIPPET", 1)[0]

        assert "proxy_pass http://127.0.0.1:$GRAFANA_HTTP_PORT;" in grafana_location
        assert "proxy_intercept_errors off;" in grafana_location
