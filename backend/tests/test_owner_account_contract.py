import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "scripts" / "installer" / "lib" / "owner_account.sh"


def _bash() -> str:
    git_bash = Path("E:/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("bash is unavailable")
    return bash


def _bash_path(path: Path) -> str:
    bash = _bash()
    if Path(bash).name.lower() == "bash.exe":
        converted = subprocess.run(
            [bash, "-lc", "cygpath -u \"$1\"", "cygpath", str(path)],
            text=True,
            capture_output=True,
            check=True,
        )
        return converted.stdout.strip()
    return str(path)


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash(), "-euo", "pipefail", "-c", script, "owner-account", _bash_path(LIBRARY)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def test_random_owner_credentials_have_required_shape():
    result = _run(
        r'''
source "$1"
first="$(owner_account_generate_username)"
second="$(owner_account_generate_username)"
password="$(owner_account_generate_password)"
[[ "$first" =~ ^[a-z_][a-z0-9_-]{7,15}$ ]]
[[ "$second" =~ ^[a-z_][a-z0-9_-]{7,15}$ ]]
[[ "$first" != "$second" ]]
[[ "$password" =~ ^[a-zA-Z0-9]{16}$ ]]
'''
    )
    assert result.returncode == 0, result.stderr


def test_owner_and_role_owner_validation():
    result = _run(
        r'''
source "$1"
owner_account_validate_username alice_1
owner_account_validate_username _service-user
! owner_account_validate_username 'BadName'
! owner_account_validate_username 'user name'
owner_account_validate_role_owners alice,bob-2,_service
! owner_account_validate_role_owners 'alice, bob'
! owner_account_validate_role_owners 'alice;$HOME'
! owner_account_validate_role_owners 'alice\nbob'
'''
    )
    assert result.returncode == 0, result.stderr


def test_chpasswd_receives_password_only_on_stdin():
    source = LIBRARY.read_text(encoding="utf-8")
    assert re.search(r"printf .*\| chpasswd", source)
    assert not re.search(r"chpasswd\s+[^|\n]*\$OWNER_ACCOUNT_PASSWORD", source)
    assert not re.search(r"echo .*password.*>>|>>.*password", source, re.IGNORECASE)


def test_role_owners_is_rendered_and_validated():
    template = (REPO / "systemd" / "sub-manager.service").read_text(encoding="utf-8")
    activation = (REPO / "scripts" / "installer" / "lib" / "config_activation.sh").read_text(
        encoding="utf-8"
    )
    assert 'Environment="ROLE_OWNERS=' in template
    assert "ROLE_OWNERS" in activation
