"""Regression coverage for canonical and flat installer release layouts."""

from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts/installer/lib/source_layout.sh"
ENTRYPOINT_HELPER = REPO / "scripts/installer/lib/entrypoint_layout.sh"
GIT_BASH = Path("E:/Git/usr/bin/bash.exe")


CANONICAL_FILES = (
    "backend/main.py",
    "backend/requirements.txt",
    "frontend/package.json",
    "scripts/ops/lib/install_log.sh",
    "scripts/deploy/build-and-publish-frontend.sh",
    "scripts/deploy/verify-frontend-release.sh",
    "scripts/installer/lib/entrypoint_layout.sh",
    "monitoring/prometheus/rules.yml",
    "monitoring/loki/loki-config.yml",
    "monitoring/promtail/promtail-config.yml",
    "monitoring/grafana/sub-manager-dashboard.json",
    "monitoring/grafana/adguard-overview-dashboard.json",
    "systemd/sub-manager.service",
)

FLAT_FILES = (
    "main.py",
    "requirements.txt",
    "package.json",
    "ops/lib/install_log.sh",
    "deploy/build-and-publish-frontend.sh",
    "deploy/verify-frontend-release.sh",
    "installer/lib/entrypoint_layout.sh",
    "prometheus/rules.yml",
    "loki/loki-config.yml",
    "promtail/promtail-config.yml",
    "grafana/sub-manager-dashboard.json",
    "grafana/adguard-overview-dashboard.json",
    "sub-manager.service",
)


def _touch_layout(root: Path, files: tuple[str, ...]) -> None:
    for relative_path in files:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")


def _bash_command() -> str:
    """Prefer Git Bash over the Windows WSL launcher for local shell tests."""
    return str(GIT_BASH) if GIT_BASH.exists() else "bash"


def _bash_path(path: Path) -> str:
    return path.resolve().as_posix()


def _resolve(installer_dir: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "set -e\n"
        'source "$1"\n'
        'mssg_resolve_source_layout "$2"\n'
        'printf "%s|%s|%s|%s|%s\\n" "$MSSG_SOURCE_LAYOUT" "$MSSG_BACKEND_DIR" '
        '"$MSSG_FRONTEND_DIR" "$MSSG_OPS_DIR" "$MSSG_DEPLOY_DIR"\n'
    )
    return subprocess.run(
        [_bash_command(), "-c", script, "bash", _bash_path(HELPER), _bash_path(installer_dir)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_source_layout_resolves_canonical_checkout(tmp_path: Path):
    _touch_layout(tmp_path, CANONICAL_FILES)
    installer_dir = tmp_path / "scripts/installer"
    installer_dir.mkdir(parents=True, exist_ok=True)

    result = _resolve(installer_dir)

    assert result.returncode == 0, result.stderr
    layout, backend, frontend, ops, deploy = result.stdout.strip().split("|")
    source_root = backend.removesuffix("/backend")
    assert layout == "canonical"
    assert backend == f"{source_root}/backend"
    assert frontend == f"{source_root}/frontend"
    assert ops == f"{source_root}/scripts/ops"
    assert deploy == f"{source_root}/scripts/deploy"


def test_source_layout_resolves_complete_flat_release_bundle(tmp_path: Path):
    _touch_layout(tmp_path, FLAT_FILES)
    installer_dir = tmp_path / "installer"
    installer_dir.mkdir(exist_ok=True)

    result = _resolve(installer_dir)

    assert result.returncode == 0, result.stderr
    layout, backend, frontend, ops, deploy = result.stdout.strip().split("|")
    assert layout == "flat-release"
    assert backend == frontend
    assert ops == f"{backend}/ops"
    assert deploy == f"{backend}/deploy"


def test_source_layout_rejects_incomplete_release_before_runtime_actions(tmp_path: Path):
    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (tmp_path / "requirements.txt").write_text("fixture\n", encoding="utf-8")

    result = _resolve(installer_dir)

    assert result.returncode != 0
    assert "Unsupported installer source layout" in result.stderr


def _resolve_entrypoint(root: Path, name: str) -> subprocess.CompletedProcess[str]:
    script = 'set -e\nsource "$1"\nmssg_resolve_installer_entrypoint "$2" "$3"\n'
    return subprocess.run(
        [_bash_command(), "-c", script, "bash", _bash_path(ENTRYPOINT_HELPER), _bash_path(root), name],
        text=True,
        capture_output=True,
        check=False,
    )


def test_public_entrypoint_resolves_canonical_and_flat_release_layouts(tmp_path: Path):
    canonical = tmp_path / "canonical"
    flat = tmp_path / "flat"
    for path in (
        canonical / "scripts/installer/install.sh",
        canonical / "scripts/installer/update.sh",
        flat / "installer/install.sh",
        flat / "installer/update.sh",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    canonical_result = _resolve_entrypoint(canonical, "update")
    flat_result = _resolve_entrypoint(flat, "install")

    assert canonical_result.returncode == 0, canonical_result.stderr
    assert canonical_result.stdout.strip().endswith("/scripts/installer/update.sh")
    assert flat_result.returncode == 0, flat_result.stderr
    assert flat_result.stdout.strip().endswith("/installer/install.sh")


def test_public_entrypoint_rejects_unknown_layout(tmp_path: Path):
    result = _resolve_entrypoint(tmp_path, "update")

    assert result.returncode != 0
    assert "Unsupported installer entrypoint layout" in result.stderr


def test_root_wrappers_delegate_through_entrypoint_layout_guard():
    for relative_path in ("install.sh", "update.sh"):
        script = (REPO / relative_path).read_text(encoding="utf-8")

        assert "entrypoint_layout.sh" in script
        assert '"$SCRIPT_DIR/scripts/installer/lib/entrypoint_layout.sh"' in script
        assert '"$SCRIPT_DIR/installer/lib/entrypoint_layout.sh"' in script
