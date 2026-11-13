import os
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts/installer/lib/runtime_secrets.sh"
GIT_BASH = Path("E:/Git/usr/bin/bash.exe")
FLAG = "--web.listen-address=127.0.0.1:9090"
DEBIAN_UNIT = "ExecStart=/usr/bin/prometheus $ARGS\n"
OVERRIDE_UNIT = (
    DEBIAN_UNIT
    + "ExecStart=\n"
    + "ExecStart=/usr/bin/prometheus --config.file=/etc/prometheus/prometheus.yml\n"
)
DROPIN_NAME = "90-sub-manager-loopback.conf"


def _bind(tmp_path: Path, unit_text: str, defaults: str | None = None):
    defaults_file = tmp_path / "prometheus"
    if defaults is not None:
        defaults_file.write_text(defaults, encoding="utf-8")
    dropin_dir = tmp_path / "prometheus.service.d"
    unit_file = tmp_path / "unit"
    unit_file.write_text(unit_text, encoding="utf-8")
    reload_marker = tmp_path / "reloaded"
    env = os.environ.copy()
    env.update(
        {
            "MSSG_PROMETHEUS_DEFAULTS": defaults_file.as_posix(),
            "MSSG_PROMETHEUS_DROPIN_DIR": dropin_dir.as_posix(),
            "UNIT_FILE": unit_file.as_posix(),
            "RELOAD_MARKER": reload_marker.as_posix(),
        }
    )
    script = (
        'source "$1"; '
        'systemctl() { if [ "$1" = cat ]; then cat "$UNIT_FILE"; '
        'else : > "$RELOAD_MARKER"; fi; }; '
        "bind_prometheus_loopback"
    )
    bash = str(GIT_BASH) if GIT_BASH.exists() else "bash"
    result = subprocess.run(
        [bash, "-c", script, "bash", HELPER.as_posix()],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return defaults_file, dropin_dir / DROPIN_NAME, reload_marker


@pytest.mark.parametrize(
    ("defaults", "expected"),
    [
        (None, f'ARGS="{FLAG}"\n'),
        ('ARGS=""\n', f'ARGS=" {FLAG}"\n'),
        (f'ARGS="{FLAG}"\n', f'ARGS="{FLAG}"\n'),
        ('ARGS="--web.listen-address=0.0.0.0:9090"\n', f'ARGS=" {FLAG}"\n'),
        ('ARGS="--a=1 --web.listen-address :9090 --b=2"\n', f'ARGS="--a=1 --b=2 {FLAG}"\n'),
    ],
)
def test_stock_unit_is_bound_through_args_without_a_dropin(tmp_path, defaults, expected):
    defaults_file, dropin, reload_marker = _bind(tmp_path, DEBIAN_UNIT, defaults)

    assert defaults_file.read_text(encoding="utf-8") == expected
    assert not dropin.exists()
    assert not reload_marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Git Bash install cannot use Windows drive paths in environment variables")
def test_override_without_args_gets_a_later_dropin_keeping_its_command(tmp_path):
    _, dropin, reload_marker = _bind(tmp_path, OVERRIDE_UNIT, 'ARGS=""\n')

    assert dropin.read_text(encoding="utf-8") == (
        "[Service]\nExecStart=\n"
        f"ExecStart=/usr/bin/prometheus --config.file=/etc/prometheus/prometheus.yml {FLAG}\n"
    )
    assert reload_marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Git Bash install cannot use Windows drive paths in environment variables")
def test_override_with_a_public_address_is_rebound_to_loopback(tmp_path):
    public = DEBIAN_UNIT + (
        "ExecStart=\nExecStart=/usr/bin/prometheus --web.listen-address=0.0.0.0:9090 --a=1\n"
    )

    _, dropin, reload_marker = _bind(tmp_path, public, 'ARGS=""\n')

    assert dropin.read_text(encoding="utf-8") == (
        f"[Service]\nExecStart=\nExecStart=/usr/bin/prometheus --a=1 {FLAG}\n"
    )
    assert reload_marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Git Bash install cannot use Windows drive paths in environment variables")
def test_override_reading_args_loses_its_address_without_repeating_the_flag(tmp_path):
    public = DEBIAN_UNIT + (
        "ExecStart=\nExecStart=/usr/bin/prometheus --web.listen-address=:9090 $ARGS\n"
    )

    _, dropin, _ = _bind(tmp_path, public, 'ARGS=""\n')

    assert dropin.read_text(encoding="utf-8") == (
        "[Service]\nExecStart=\nExecStart=/usr/bin/prometheus $ARGS\n"
    )


def test_rerun_does_not_add_a_second_listen_address(tmp_path):
    bound = OVERRIDE_UNIT + f"ExecStart=\nExecStart=/usr/bin/prometheus {FLAG}\n"

    _, dropin, reload_marker = _bind(tmp_path, bound, 'ARGS=""\n')

    assert not dropin.exists()
    assert not reload_marker.exists()
