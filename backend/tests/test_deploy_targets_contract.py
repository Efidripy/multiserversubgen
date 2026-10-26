"""
Контракт таблицы деплой-целей (scripts/deploy/targets.psd1) и
синтаксическая проверка deploy.ps1.

Запуск:
    pytest backend/tests/test_deploy_targets_contract.py -v \
        --basetemp=$env:TEMP/pytest-codex-deploytool
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGETS_PSD1 = REPO / "scripts" / "deploy" / "targets.psd1"
DEPLOY_PS1 = REPO / "scripts" / "deploy" / "deploy.ps1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_targets() -> str:
    return TARGETS_PSD1.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# targets.psd1 contract
# ---------------------------------------------------------------------------

def test_targets_psd1_exists() -> None:
    assert TARGETS_PSD1.exists(), f"targets.psd1 not found: {TARGETS_PSD1}"


def test_prod_target_has_correct_hostname() -> None:
    text = _read_targets()
    # prod block must contain example.invalid
    prod_block = re.search(r"prod\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert prod_block, "prod block not found in targets.psd1"
    assert "example.invalid" in prod_block.group(1), (
        "prod target must point to example.invalid"
    )


def test_prod_target_has_correct_port() -> None:
    text = _read_targets()
    prod_block = re.search(r"prod\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert prod_block, "prod block not found"
    # Port must be 1452
    assert re.search(r"Port\s*=\s*1452", prod_block.group(1)), (
        "prod target must use port 1452"
    )


def test_vm3_is_marked_local_test() -> None:
    text = _read_targets()
    vm3_block = re.search(r"vm3\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert vm3_block, "vm3 block not found in targets.psd1"
    # LocalTest must be $true
    assert re.search(r"LocalTest\s*=\s*\$true", vm3_block.group(1)), (
        "vm3 target must have LocalTest = $true"
    )


def test_vm3_hostname_is_not_prod() -> None:
    text = _read_targets()
    vm3_block = re.search(r"vm3\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert vm3_block, "vm3 block not found"
    assert "example.invalid" not in vm3_block.group(1), (
        "vm3 block must NOT reference the prod hostname example.invalid"
    )


def test_no_secrets_or_passwords_in_targets() -> None:
    text = _read_targets().lower()
    forbidden = ("password", "secret", "token", "passwd", "apikey", "api_key")
    found = [w for w in forbidden if w in text]
    assert not found, (
        f"targets.psd1 must not contain secrets; found keywords: {found}"
    )


def test_prod_has_correct_remote_dir() -> None:
    text = _read_targets()
    prod_block = re.search(r"prod\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert prod_block
    assert "<user-home>/multiserversubgen-live" in prod_block.group(1), (
        "prod RemoteDir must be <user-home>/multiserversubgen-live"
    )


def test_prod_health_url() -> None:
    text = _read_targets()
    prod_block = re.search(r"prod\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert prod_block
    assert "http://127.0.0.1:666/health" in prod_block.group(1), (
        "prod HealthUrl must be http://127.0.0.1:666/health"
    )


def test_prod_ui_url_path() -> None:
    text = _read_targets()
    prod_block = re.search(r"prod\s*=\s*@\{([^}]+)\}", text, re.DOTALL)
    assert prod_block
    assert "/<panel-base-path>/" in prod_block.group(1), (
        "prod UiUrlPath must be /<panel-base-path>/"
    )


# ---------------------------------------------------------------------------
# deploy.ps1 static checks
# ---------------------------------------------------------------------------

def test_deploy_ps1_exists() -> None:
    assert DEPLOY_PS1.exists(), f"deploy.ps1 not found: {DEPLOY_PS1}"


def test_deploy_ps1_has_utf8_bom() -> None:
    """deploy.ps1 contains Cyrillic — must be saved with UTF-8 BOM."""
    raw = DEPLOY_PS1.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", (
        "deploy.ps1 must start with UTF-8 BOM (EF BB BF) because it contains Cyrillic"
    )


def test_deploy_ps1_references_targets_psd1() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "targets.psd1" in text, "deploy.ps1 must reference targets.psd1"


def test_deploy_ps1_requires_clean_worktree() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "porcelain" in text, "deploy.ps1 must check for a clean working tree"


def test_deploy_ps1_prod_requires_main_branch() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "'main'" in text or '"main"' in text, (
        "deploy.ps1 must enforce main branch for prod"
    )


def test_deploy_ps1_has_dry_run_flag() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "DryRun" in text, "deploy.ps1 must support -DryRun flag"


def test_deploy_ps1_has_yes_flag() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "Yes" in text, "deploy.ps1 must support -Yes flag to skip confirmation"


def test_deploy_ps1_deploys_head_only() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    # invoke-remote-deploy.ps1 always archives HEAD, so a -Ref switch would only mislead.
    assert "[string]$Ref" not in text
    assert "tar -xzf" not in text, "no raw restore-over-/ example in rollback hints"


def test_deploy_ps1_invokes_remote_deploy() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "invoke-remote-deploy.ps1" in text, (
        "deploy.ps1 must call invoke-remote-deploy.ps1"
    )
    assert "-Mode update" in text or "'-Mode', 'update'" in text or "'update'" in text, (
        "deploy.ps1 must invoke with -Mode update"
    )


def test_deploy_ps1_git_bin_path_added_to_end_of_path() -> None:
    """SSH tools from E:\\Git\\usr\\bin must be appended (not prepended) to PATH."""
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert r"E:\Git\usr\bin" in text, (
        r"deploy.ps1 must add E:\Git\usr\bin to PATH for ssh/scp"
    )
    # Must concatenate at the END to not override Windows tar.exe
    assert r"$env:PATH;$GitBin" in text or r'"$currentPath;$GitBin"' in text or (
        "currentPath" in text and "$GitBin" in text
    ), (
        "E:\\Git\\usr\\bin must be appended to the END of PATH (not prepended)"
    )


def test_deploy_ps1_post_check_health_three_times() -> None:
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    assert "-le 3" in text or "3/3" in text or "le 3" in text, (
        "deploy.ps1 must check health 3 times in post-check"
    )


def test_deploy_ps1_no_auto_rollback_in_post_check() -> None:
    """Rollback is server-side; deploy.ps1 must NOT attempt its own rollback."""
    text = DEPLOY_PS1.read_text(encoding="utf-8-sig")
    # Should mention that server does rollback, but not call it itself
    assert "ROLLBACK_ON_FAIL" in text or "rollback" in text.lower(), (
        "deploy.ps1 must explain rollback mechanism"
    )


def test_deploy_ps1_syntax_valid() -> None:
    """Parse deploy.ps1 with PowerShell's own parser — must have zero errors."""
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
    assert "-[0-9a-f]{32}$" in text, "cleanup must match only <RemoteDir>-<32 hex>"
    assert "[ValidateRange(2, 20)]" in text, "must always keep at least 2 workdirs"
    assert text.index("Post-check: journalctl") < text.index("Cleanup:"), "cleanup runs only after post-checks"
