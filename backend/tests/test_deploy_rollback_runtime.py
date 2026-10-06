"""Execute production rollback functions against disposable files and fake services."""

from pathlib import Path
import re
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "scripts/deploy/server-deploy.sh"
GIT_BASH = Path("E:/Git/usr/bin/bash.exe")


def _functions() -> str:
    source = DEPLOY.read_text(encoding="utf-8")
    names = (
        "cleanup_stage",
        "restore_service_unit",
        "restore_previous",
        "rollback_and_exit",
        "on_error",
    )
    return "\n".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.M | re.S).group(0)
        for name in names
    )


@pytest.mark.parametrize("phase", ["before_swap", "quarantined", "after_swap"])
@pytest.mark.parametrize("failure", ["health_gate", "command"])
@pytest.mark.parametrize("cleanup_failure", ["none", "stage", "unit"])
@pytest.mark.parametrize("rollback_enabled", [False, True])
def test_failure_preserves_anchors_and_attempts_rollback(
    tmp_path: Path,
    phase: str,
    failure: str,
    cleanup_failure: str,
    rollback_enabled: bool,
):
    # These are opaque synthetic files, never a real SQLite DB or systemd unit.
    previous = tmp_path / "previous"
    project = tmp_path / "project"
    stage = tmp_path / "stage"
    old_root = project if phase == "before_swap" else previous
    old_root.mkdir()
    (old_root / "state.fixture").write_bytes(b"previous-state")
    if phase == "after_swap":
        project.mkdir()
        (project / "state.fixture").write_bytes(b"candidate-state")
    if phase != "after_swap" or cleanup_failure == "stage":
        stage.mkdir()
        (stage / "candidate.fixture").write_bytes(b"staged")
    (tmp_path / "unit.backup").write_bytes(b"previous-unit")
    (tmp_path / "unit").write_bytes(b"candidate-unit")
    (tmp_path / "archive.fixture").write_bytes(b"immutable-backup")
    if phase != "after_swap" or cleanup_failure == "unit":
        (tmp_path / "unit.next").write_bytes(b"staged-unit")

    setup = r"""
set -euo pipefail
export PATH="/usr/bin:/bin:$PATH"
cd "$1"
PROJECT_NAME=fixture
PROJECT_DIR="$PWD/project"
QUARANTINE_DIR="$PWD/previous"
STAGE_DIR="$PWD/stage"
STAGED_SERVICE_UNIT="$PWD/unit.next"
if [[ "$2" == after_swap && "$4" != unit ]]; then
  STAGED_SERVICE_UNIT=''
fi
HAD_PREVIOUS=1
SERVICE_UNIT_WAS_PRESENT=1
SERVICE_UNIT="$PWD/unit"
SERVICE_UNIT_ROLLBACK="$PWD/unit.backup"
PROMTAIL_CONFIG_WAS_PRESENT=0
PROMTAIL_CONFIG_ROLLBACK=''
ROLLBACK_ON_FAIL="$3"
CLEANUP_FAILURE="$4"
systemctl() { printf '%s\n' "$*" >> services.log; }
activate_runtime_ownership() { printf 'ownership\n' >> services.log; }
install() { command cp -- "$SERVICE_UNIT_ROLLBACK" "$SERVICE_UNIT"; }
rm() {
  if [[ "$CLEANUP_FAILURE" == stage && "${*: -1}" == "$STAGE_DIR" ]] ||
     [[ "$CLEANUP_FAILURE" == unit && "${*: -1}" == "$STAGED_SERVICE_UNIT" ]]; then
    return 17
  fi
  command rm "$@"
}
"""
    trigger = "rollback_and_exit" if failure == "health_gate" else "(exit 23)"
    result = subprocess.run(
        [
            str(GIT_BASH) if GIT_BASH.exists() else "bash",
            "-c",
            setup + _functions() + "\ntrap on_error ERR\n" + trigger,
            "bash",
            tmp_path.as_posix(),
            phase,
            str(int(rollback_enabled)),
            cleanup_failure,
        ],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == (1 if failure == "health_gate" else 23), result.stderr
    assert (tmp_path / "archive.fixture").read_bytes() == b"immutable-backup"
    assert (tmp_path / "unit.backup").read_bytes() == b"previous-unit"
    if rollback_enabled:
        assert (project / "state.fixture").read_bytes() == b"previous-state"
        assert (tmp_path / "unit").read_bytes() == b"previous-unit"
        assert not previous.exists()
        calls = (tmp_path / "services.log").read_text().splitlines()
        assert calls.count("stop fixture") == 1
        assert calls.count("start fixture") == 1
        assert calls.index("daemon-reload") < calls.index("start fixture")
        assert calls[-1] == "reload nginx"
    else:
        assert (old_root / "state.fixture").read_bytes() == b"previous-state"
        assert (tmp_path / "unit").read_bytes() == b"candidate-unit"
        assert not (tmp_path / "services.log").exists()
    assert stage.exists() == (cleanup_failure == "stage")
    assert (tmp_path / "unit.next").exists() == (cleanup_failure == "unit")
    if cleanup_failure != "none":
        assert "cleanup" in result.stderr.lower()
