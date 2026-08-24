from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_systemd_template_uses_external_secret_file():
    unit = _read("systemd/sub-manager.service")

    assert "EnvironmentFile=/etc/__PROJECT_NAME__/runtime-secrets.env" in unit
    assert 'Environment="REDIS_URL=' not in unit
    assert 'Environment="MFA_TOTP_USERS=' not in unit
    assert "fuser -k" not in unit
    assert "User=root" not in unit
    assert "User=__PROJECT_NAME__" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=full" in unit
    assert "ExecStartPre=" in unit
    assert "already in use" in unit


def test_installers_do_not_render_or_log_secret_values():
    install = _read("scripts/installer/install.sh")
    update = _read("scripts/installer/update.sh")

    for script in (install, update):
        assert "runtime_secrets_write" in script
        assert 'sed "s|__PROJECT_NAME__|$PROJECT_NAME|g"' in script
        assert "REDIS_URL=.*|REDIS_URL=$REDIS_URL" not in script
        assert "MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS" not in script
        assert "chmod 0600 \"$LOG_FILE\"" in script
        assert "runtime_ensure_service_user" in script

    assert 'echo "REDIS_URL: ${REDIS_URL:-<none>}"' not in update
    assert 'echo "REDIS_URL: <redacted>"' in update


def test_runtime_secret_writer_is_root_only_and_atomic():
    helper = _read("scripts/installer/lib/runtime_secrets.sh")

    assert "install -d -m 0700" in helper
    assert "mktemp" in helper
    assert "chmod 0600 \"$temp_file\"" in helper
    assert "install -m 0600 \"$temp_file\" \"$secret_file\"" in helper
    assert "runtime_ensure_service_user" in helper
    assert "useradd --system" in helper
    assert "chown -R -- \"$service_user:$service_user\" \"$service_dir\"" in helper


def test_privileged_runtime_install_uses_only_hashed_production_lock():
    for relative_path in (
        "scripts/installer/install.sh",
        "scripts/installer/update.sh",
    ):
        script = _read(relative_path)

        assert "install --require-hashes -r \"$SCRIPT_DIR/backend/requirements.txt\"" in script
        assert "backend/requirements-dev.txt" not in script
        assert "install --upgrade pip" not in script

    smoke = _read("scripts/ops/run-pytest-smoke.sh")
    assert 'pip install --require-hashes -r "$REQ_FILE"' in smoke


def test_privileged_binary_downloads_use_checked_in_digest_manifest():
    manifest = _read("scripts/installer/lib/artifact_manifest.sh")
    install = _read("scripts/installer/install.sh")
    xui = _read("scripts/installer/lib/xui_core.sh")

    for component in ("LOKI", "PROMTAIL", "XUI", "ADGUARD", "SUB2SING"):
        assert f"ARTIFACT_{component}" in manifest

    for arch in ("386", "AMD64", "ARM64", "ARMV5", "ARMV6", "ARMV7", "S390X"):
        assert f"ARTIFACT_XUI_{arch}_SHA256" in manifest

    assert "source \"${INSTALLER_DIR}/lib/artifact_manifest.sh\"" in install
    assert "artifact_verify_file LOKI amd64" in install
    assert "artifact_verify_file ADGUARD" in install
    assert "releases/latest/download/AdGuardHome" not in install
    assert "api.github.com/repos/AdguardTeam/AdGuardHome/releases/latest" not in install
    assert "artifact_verify_file XUI" in xui
    assert "artifact_verify_file SUB2SING" in xui
    assert "releases/latest" not in xui


def test_xui_seed_matches_v3_hosts_contract():
    manifest = _read("scripts/installer/lib/artifact_manifest.sh")
    template = _read("scripts/installer/templates/xui-pro/base-inbounds.sql.tpl")

    assert 'ARTIFACT_XUI_VERSION="v3.6.0"' in manifest
    assert 'INSERT INTO hosts ("inbound_id","group_id"' in template
    assert "__GROUP_REALITY__" in template
    assert "__GROUP_WS__" in template
    assert "__GROUP_XHTTP__" in template
    assert "__GROUP_TROJAN__" in template
    assert '"externalProxy"' not in template


def test_remove_script_defaults_to_conservative_scope():
    remove = _read("scripts/installer/remove.sh")
    workflows = _read("scripts/installer/lib/workflows.sh")

    assert 'REMOVE_SCOPE="${REMOVE_SCOPE:-soft}"' in remove
    assert 'REMOVE_SCOPE="${REMOVE_SCOPE:-hard}"' not in remove
    assert 'REMOVE_MODE="$mode" REMOVE_SCOPE=hard REMOVE_FORCE=true' in workflows


def test_project_cleanup_preserves_evidence_and_supports_dry_run():
    script = _read("scripts/ops/project-cleanup.sh")
    safe_cleanup = script.split("cleanup_safe()", 1)[1].split("cleanup_deep()", 1)[0]

    assert 'CLEANUP_DRY_RUN="${CLEANUP_DRY_RUN:-false}"' in script
    assert '".tmp"' not in safe_cleanup
    assert 'log "would remove: $path"' in script
    assert '  - .tmp/' in script
    assert "cleanup_python_caches" in script
