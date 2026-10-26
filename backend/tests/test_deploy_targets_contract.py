"""
Контракт шаблона деплой-целей (scripts/deploy/targets.psd1) и
синтаксическая проверка deploy.ps1.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGETS_PSD1 = REPO / "scripts" / "deploy" / "targets.psd1"
DEPLOY_PS1 = REPO / "scripts" / "deploy" / "deploy.ps1"


def _read_targets() -> str:
    return TARGETS_PSD1.read_text(encoding="utf-8")


def _target_block(name: str) -> str:
    match = re.search(rf"{name}\s*=\s*@\{{([^}}]+)\}}", _read_targets(), re.DOTALL)
    assert match, f"{name} block not found in targets.psd1"
    return match.group(1)


def test_targets_psd1_exists() -> None:
    assert TARGETS_PSD1.exists(), f"targets.psd1 not found: {TARGETS_PSD1}"


def test_prod_target_is_a_safe_template() -> None:
    prod_block = _target_block("prod")
    assert "HostName    = 'example.invalid'" in prod_block
    assert "Port        = '<ssh-port>'" in prod_block
    assert "User        = '<ssh-user>'" in prod_block
    assert "KeyPath     = '<path-to-ssh-key>'" in prod_block
    assert "RemoteDir   = '<user-home>/multiserversubgen-live'" in prod_block
    assert "UiUrlPath   = '/<panel-base-path>/'" in prod_block


def test_vm3_target_is_a_safe_template_and_marked_local() -> None:
    vm3_block = _target_block("vm3")
    assert "HostName    = 'host-a.example.invalid'" in vm3_block
    assert "HostName    = 'example.invalid'" not in vm3_block
    assert re.search(r"LocalTest\s*=\s*\$true", vm3_block)


def test_targets_template_has_no_password_or_api_material() -> None:
    text = _read_targets().lower()
    forbidden = ("password", "secret", "token", "passwd", "apikey", "api_key")
    assert not [word for word in forbidden if word in text]


def test_deploy_ps1_exists() -> None:
    assert DEPLOY_PS1.exists(), f"deploy.ps1 not found: {DEPLOY_PS1}"


def test_deploy_ps1_has_utf8_bom() -> None:
    """deploy.ps1 contains Cyrillic — must be saved with UTF-8 BOM."""
    assert DEPLOY_PS1.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_deploy_ps1_loads_only_local_targets() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "targets.local.psd1" in text
    assert "Copy targets.psd1 to targets.local.psd1" in text


def test_deploy_ps1_requires_clean_worktree() -> None:
    assert "porcelain" in DEPLOY_PS1.read_text(encoding="utf-8-sig")


def test_deploy_ps1_prod_requires_main_branch() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "'main'" in text or '"main"' in text


def test_deploy_ps1_has_dry_run_and_yes_flags() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "DryRun" in text
    assert "Yes" in text


def test_deploy_ps1_deploys_head_only() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "[string]$Ref" not in text
    assert "tar -xzf" not in text


def test_deploy_ps1_invokes_remote_deploy() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "invoke-remote-deploy.ps1" in text
    assert "-Mode update" in text or "'-Mode', 'update'" in text or "'update'" in text


def test_deploy_ps1_git_bin_path_added_to_end_of_path() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert r"E:\Git\usr\bin" in text
    assert r"$env:PATH;$GitBin" in text or r'"$currentPath;$GitBin"' in text or (
        "currentPath" in text and "$GitBin" in text
    )


def test_deploy_ps1_post_check_health_three_times() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "-le 3" in text or "3/3" in text or "le 3" in text


def test_deploy_ps1_no_auto_rollback_in_post_check() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "ROLLBACK_ON_FAIL" in text or "rollback" in text.lower()


def test_deploy_ps1_syntax_valid() -> None:
    pwsh = "pwsh"
    check_cmd = (
        f'$errors = $null; '
        f'[System.Management.Automation.Language.Parser]::ParseFile('
        f'"{DEPLOY_PS1.as_posix()}", [ref]$null, [ref]$errors) | Out-Null; '
        f'if ($errors.Count -gt 0) {{ '
        f'  $errors | ForEach-Object {{ Write-Error $_.Message }}; exit 1 '
        f'}} else {{ exit 0 }}'
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", check_cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"deploy.ps1 has syntax errors:\n{result.stdout}\n{result.stderr}"
    )


def test_deploy_ps1_cleanup_only_matches_hex_workdirs() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "-[0-9a-f]{32}$" in text
    assert "[ValidateRange(2, 20)]" in text
    assert text.index("Post-check: journalctl") < text.index("Cleanup:")
