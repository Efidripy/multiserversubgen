import json
import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
LIBRARY = "scripts/installer/lib/component_ownership.sh"


def _bash_path(path: Path) -> str:
    """Translate a Windows pytest tmp path for the WSL Bash test runner."""
    drive = path.drive.rstrip(":").lower()
    return f"/mnt/{drive}{path.as_posix()[2:]}"


def _run(script: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        ["bash", "-c", f'MSSG_OWNERSHIP_DIR="{_bash_path(state_dir)}"\n{script}'],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preexisting_components_are_recorded_as_external_and_fail_closed(tmp_path: Path):
    result = _run(
        f'''source "{LIBRARY}"
dpkg() {{ return 0; }}
dpkg-query() {{ printf '11.2.0'; }}
mssg_ownership_discover_monitoring
mssg_ownership_allow_monitoring_mutation
''',
        tmp_path / "state",
    )

    assert result.returncode != 0
    registry = json.loads((tmp_path / "state/component-ownership.json").read_text())
    assert registry["components"]["grafana"]["ownership"] == "external"
    assert registry["components"]["prometheus"]["ownership"] == "external"
    assert "will not modify it" in result.stderr


def test_registry_version_drift_is_a_fail_closed_part_of_the_monitoring_gate():
    library = (REPO / LIBRARY).read_text(encoding="utf-8")
    gate = library.split("mssg_ownership_allow_monitoring_mutation() {", 1)[1]

    assert "mssg_ownership_version_matches_registry" in gate
    assert "version differs from the ownership registry" in library
    assert "Treating it as externally maintained; no mutation is allowed." in library


def test_update_gates_monitoring_before_any_package_install_or_global_grafana_config():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = (REPO / relative_path).read_text(encoding="utf-8")
        function_start = script.index("configure_monitoring_stack() {")
        gate = script.index("mssg_ownership_allow_monitoring_mutation", function_start)
        prometheus_install = script.index("apt_install_missing prometheus", gate)
        grafana_install = script.index("apt_install_missing grafana", prometheus_install)

        assert gate < prometheus_install < grafana_install
        assert "apt_install_missing grafana" not in script[function_start : script.index("mssg_ownership_component_present grafana", gate)]
        assert "grafana.ini" not in script[function_start : script.index("prepare_monitoring_ownership()", function_start)]
        assert "component_ownership.sh" in script


def test_explicit_ownership_cli_does_not_offer_implicit_adoption():
    command = (REPO / "scripts/installer/component-ownership.sh").read_text(encoding="utf-8")

    assert "ADOPT_MSSG_MONITORING" in command
    assert "RELEASE_MSSG_MONITORING" in command
    assert "No packages, services, or configuration were changed." in command


def test_all_removal_paths_preserve_unproven_host_wide_components():
    remove = (REPO / "scripts/installer/remove.sh").read_text(encoding="utf-8")
    install = (REPO / "scripts/installer/install.sh").read_text(encoding="utf-8")

    assert "mssg_ownership_is_managed grafana" in remove
    assert "mssg_ownership_is_managed prometheus" in remove
    assert "apt-get purge" not in remove
    assert "Host-wide package/path purge is disabled by ownership policy." in remove
    assert "mssg_ownership_is_managed grafana" in install.split("uninstall_nuke()", 1)[1]
    assert "apt-get remove -y --purge" not in install.split("uninstall_nuke()", 1)[1].split("update_project()", 1)[0]


def test_xui_presets_do_not_reinstall_an_existing_3x_ui_or_upgrade_present_packages():
    workflows = (REPO / "scripts/installer/lib/workflows.sh").read_text(encoding="utf-8")
    xui_core = (REPO / "scripts/installer/lib/xui_core.sh").read_text(encoding="utf-8")

    assert "3x-ui Preserved" in workflows
    assert "minimal preset refuses to replace an existing panel" in workflows
    assert "Reinstall it before Sub-Manager?" not in workflows
    assert "xui_apt_install_missing()" in xui_core
    assert "apt-get install --reinstall" not in xui_core
