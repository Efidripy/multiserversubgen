from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_vm3_scenario_runner_is_locked_to_vm3_and_dry_run_by_default():
    script = (
        REPO / "scripts/installer/windows/vm3-scenarios.ps1"
    ).read_text(encoding="utf-8")

    assert "if ($Target -ne 'vm3')" in script
    assert "refusing '$Target'" in script
    assert "if (-not $Execute)" in script
    assert "$DryRun = $true" in script
    assert "-Target', 'vm3'" in script
    assert "windows-install.ps1" in script
    assert "windows-smoke.ps1" in script
    assert "-Target vm3 -DryRun" in script
    assert "invoke-remote-deploy" not in script
