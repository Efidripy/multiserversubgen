import os
import subprocess
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts/installer/lib/loki_config.sh"
GIT_BASH = Path("E:/Git/usr/bin/bash.exe")


def _bash_path(path: Path) -> str:
    return path.resolve().as_posix()


def _bash_command() -> str:
    return str(GIT_BASH) if GIT_BASH.exists() else "bash"


def _run_reconcile(
    *, source: Path, config_dir: Path, loki_bin: Path, backup_dir: Path
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "LOKI_BIN": _bash_path(loki_bin),
            "MSSG_LOKI_CONFIG_BACKUP_DIR": _bash_path(backup_dir),
        }
    )
    return subprocess.run(
        [
            _bash_command(),
            "-lc",
            'source "$1"; mssg_reconcile_loki_config "$2" "$3"',
            "bash",
            _bash_path(HELPER),
            _bash_path(source),
            _bash_path(config_dir),
        ],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_loki_template_uses_server_log_level_and_tsdb_retention_contract():
    config = yaml.safe_load(
        (REPO / "monitoring/loki/loki-config.yml").read_text(encoding="utf-8")
    )

    assert config["server"]["log_level"] == "warn"
    assert config["limits_config"]["retention_period"] == "336h"
    assert config["compactor"]["retention_enabled"] is True
    assert config["compactor"]["compaction_interval"] == "30m"
    assert "table_manager" not in config


def test_install_and_update_validate_loki_candidate_before_service_restart():
    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = (REPO / relative_path).read_text(encoding="utf-8")
        reconcile = script.index('mssg_reconcile_loki_config "$MSSG_LOKI_CONFIG"')
        restart = script.index(
            "resource_guard_restart_services_sequentially loki promtail", reconcile
        )

        assert "lib/loki_config.sh" in script
        assert reconcile < restart


def test_loki_reconcile_helper_preserves_live_config_until_validation_passes():
    helper = (REPO / "scripts/installer/lib/loki_config.sh").read_text(
        encoding="utf-8"
    )

    validation = helper.index('"$loki_bin" -config.file="$candidate" -verify-config')
    activation = helper.index('mv -f "$candidate" "$config_dir/local-config.yaml"')

    assert validation < activation
    assert "Loki rejected the candidate configuration; live configuration was preserved." in helper
    assert "MSSG_LOKI_CONFIG_BACKUP_DIR" in helper


def test_loki_reconcile_validates_before_atomic_activation_and_keeps_backup(tmp_path: Path):
    source = tmp_path / "source.yml"
    source.write_text("new: config\n", encoding="utf-8")
    config_dir = tmp_path / "etc-loki"
    config_dir.mkdir()
    active = config_dir / "local-config.yaml"
    active.write_text("old: config\n", encoding="utf-8")
    fake_loki = tmp_path / "loki"
    fake_loki.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_loki.chmod(0o755)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    result = _run_reconcile(
        source=source,
        config_dir=config_dir,
        loki_bin=fake_loki,
        backup_dir=backup_dir,
    )

    assert result.returncode == 0, result.stderr
    assert active.read_text(encoding="utf-8") == "new: config\n"
    assert (config_dir / "config.yml").read_text(encoding="utf-8") == "new: config\n"
    assert [item.read_text(encoding="utf-8") for item in backup_dir.iterdir()] == [
        "old: config\n"
    ]


def test_loki_reconcile_rejection_preserves_active_config(tmp_path: Path):
    source = tmp_path / "source.yml"
    source.write_text("new: config\n", encoding="utf-8")
    config_dir = tmp_path / "etc-loki"
    config_dir.mkdir()
    active = config_dir / "local-config.yaml"
    active.write_text("old: config\n", encoding="utf-8")
    fake_loki = tmp_path / "loki"
    fake_loki.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_loki.chmod(0o755)

    result = _run_reconcile(
        source=source,
        config_dir=config_dir,
        loki_bin=fake_loki,
        backup_dir=tmp_path / "backups",
    )

    assert result.returncode != 0
    assert active.read_text(encoding="utf-8") == "old: config\n"
