"""Regression coverage for safe Promtail journal-source reconciliation."""

from pathlib import Path
import os
import shutil
import shlex
import subprocess


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts/ops/reconcile-promtail-config.sh"
BASE_TEMPLATE = REPO / "monitoring/promtail/promtail-config.yml"
JOURNAL_TEMPLATE = REPO / "monitoring/promtail/promtail-journal-scrape.yml"
USE_WSL = os.name == "nt" and shutil.which("wsl.exe") is not None


def _bash_command() -> list[str]:
    return ["wsl.exe", "--exec", "bash"] if USE_WSL else ["bash"]


def _bash_path(path: Path) -> str:
    return path.resolve().as_posix()


def _render(*, persistent: bool = False, runtime: bool = False) -> subprocess.CompletedProcess[str]:
    base_template = shlex.quote(_bash_path(BASE_TEMPLATE))
    journal_template = shlex.quote(_bash_path(JOURNAL_TEMPLATE))
    helper = shlex.quote(_bash_path(HELPER))
    convert_paths = "true" if USE_WSL else "false"
    script = rf'''
set -euo pipefail
work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
persistent_dir="$work_dir/persistent-journal"
runtime_dir="$work_dir/runtime-journal"
[[ "{str(persistent).lower()}" == "true" ]] && mkdir -p "$persistent_dir"
[[ "{str(runtime).lower()}" == "true" ]] && mkdir -p "$runtime_dir"
base_template={base_template}
journal_template={journal_template}
helper={helper}
if [[ "{convert_paths}" == "true" ]]; then
    base_template="$(wslpath -a "$base_template")"
    journal_template="$(wslpath -a "$journal_template")"
    helper="$(wslpath -a "$helper")"
fi
PROMTAIL_CONFIG_TEMPLATE="$base_template" \
PROMTAIL_JOURNAL_TEMPLATE="$journal_template" \
PROMTAIL_CONFIG_PATH="$work_dir/etc/promtail/config.yml" \
PROMTAIL_PERSISTENT_JOURNAL_DIR="$persistent_dir" \
PROMTAIL_RUNTIME_JOURNAL_DIR="$runtime_dir" \
ADGUARD_QUERYLOG_PATH="/srv/adguard/querylog.json" \
ADGUARD_SYSTEMD_UNIT="AdGuardHome.service" \
bash "$helper"
printf '%s\n' '--- rendered config ---'
cat "$work_dir/etc/promtail/config.yml"
'''
    return subprocess.run(
        [
            *_bash_command(),
            "-c",
            script,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_base_promtail_template_has_no_unconditional_journal_scrape():
    base = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert "adguard-querylog" in base
    assert "adguard-journal" not in base
    assert "path: /var/log/journal" not in base


def test_installer_and_updater_delegate_promtail_rendering_to_the_safe_reconciler():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = (REPO / relative_path).read_text(encoding="utf-8")

        assert "MSSG_PROMTAIL_RECONCILE_SCRIPT" in script
        assert "MSSG_PROMTAIL_JOURNAL_CONFIG" in script
        assert '"$MSSG_PROMTAIL_RECONCILE_SCRIPT"' in script
        assert "sed -i \"s|__ADGUARD_QUERYLOG_PATH__" not in script


def test_reconcile_skips_journal_when_neither_persistent_nor_runtime_journal_exists():
    result = _render()

    assert result.returncode == 0, result.stderr
    assert "Promtail journal scrape skipped: no journal directory found." in result.stdout
    assert "adguard-querylog" in result.stdout
    assert "/srv/adguard/querylog.json" in result.stdout
    assert "adguard-journal" not in result.stdout
    assert "__ADGUARD_" not in result.stdout
    assert "__PROMTAIL_" not in result.stdout


def test_reconcile_uses_persistent_journal_when_available():
    result = _render(persistent=True)

    assert result.returncode == 0, result.stderr
    assert "adguard-journal" in result.stdout
    assert "path: /tmp/" in result.stdout
    assert "/persistent-journal" in result.stdout


def test_reconcile_uses_runtime_journal_as_fallback_and_prefers_persistent():
    runtime_result = _render(runtime=True)
    preferred_result = _render(persistent=True, runtime=True)

    assert runtime_result.returncode == 0, runtime_result.stderr
    assert "/runtime-journal" in runtime_result.stdout
    assert preferred_result.returncode == 0, preferred_result.stderr
    assert "/persistent-journal" in preferred_result.stdout
    assert "/runtime-journal" not in preferred_result.stdout


def test_reconciler_never_enables_a_systemd_unit_and_only_restarts_explicitly_requested_services():
    helper = HELPER.read_text(encoding="utf-8")

    assert "systemctl enable" not in helper
    assert "--restart-active" in helper
    assert "systemctl reset-failed" in helper
    assert "systemctl is-enabled --quiet" in helper
