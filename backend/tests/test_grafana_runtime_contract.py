from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_install_and_update_preserve_the_grafana_runtime_directory():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = _read(relative_path)

        assert "ensure_grafana_runtime_directory()" in script
        assert "install -d -o grafana -g grafana -m 0750 /run/grafana" in script
        assert "d /run/grafana 0750 grafana grafana -" in script
        assert "ensure_grafana_runtime_directory || return 1" in script


def test_smoke_checks_the_grafana_unit_and_both_routing_hops_when_enabled():
    smoke = _read("scripts/ops/smoke-test.sh")

    assert 'check "systemd grafana-server active" systemctl is-active --quiet grafana-server' in smoke
    assert 'local Grafana /login is reachable' in smoke
    assert 'public Grafana URL is reachable' in smoke
    assert 'GRAFANA_HTTP_PORT < 1 || GRAFANA_HTTP_PORT > 65535' in smoke
