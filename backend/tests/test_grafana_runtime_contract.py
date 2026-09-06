from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_install_and_update_use_a_persistent_grafana_pid_directory():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = _read(relative_path)

        assert "configure_grafana_pid_directory()" in script
        assert "install -d -o grafana -g grafana -m 0750 /var/lib/grafana" in script
        assert "PID_FILE_DIR=/var/lib/grafana" in script
        assert "rm -f /etc/tmpfiles.d/grafana-runtime.conf" in script
        assert "configure_grafana_pid_directory || return 1" in script
        assert "wait_for_grafana_http()" in script


def test_install_and_update_fail_when_the_local_grafana_http_probe_never_becomes_ready():
    install = _read("scripts/installer/install.sh")
    update = _read("scripts/installer/update.sh")

    assert "wait_for_grafana_http || return 1" in install
    assert "wait_for_grafana_http || return 1" in update


def test_smoke_checks_the_grafana_unit_and_both_routing_hops_when_enabled():
    smoke = _read("scripts/ops/smoke-test.sh")

    assert 'check "systemd grafana-server active" systemctl is-active --quiet grafana-server' in smoke
    assert 'local Grafana /login is reachable' in smoke
    assert 'public Grafana URL is reachable' in smoke
    assert 'GRAFANA_HTTP_PORT < 1 || GRAFANA_HTTP_PORT > 65535' in smoke
