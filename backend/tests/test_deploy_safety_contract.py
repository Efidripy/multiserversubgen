from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_deploy_uses_immutable_local_ref_and_atomic_stage_rollback():
    script = (REPO / "scripts/deploy/server-deploy.sh").read_text(encoding="utf-8")

    assert "git -C \"$REPO_DIR\" pull" not in script
    assert "DEPLOY_REF" in script
    assert "checkout must already be at immutable DEPLOY_REF" in script
    assert '[[ "$PROJECT_DIR" == /opt/* && "$PROJECT_DIR" != /opt ]]' in script
    assert 'tar -C "$PROJECT_PARENT" -czf "$BACKUP_TAR" -- "$PROJECT_BASENAME"' in script
    assert 'tar -tzf "$BACKUP_TAR" > "$BACKUP_CONTENTS"' in script
    assert 'grep -qx "${PROJECT_BASENAME}/" "$BACKUP_CONTENTS"' in script
    assert 'tar -xzf "$BACKUP_TAR" -C /' not in script
    assert 'sha256sum "$BACKUP_TAR" > "$BACKUP_SHA"' in script
    assert 'mv -- "$STAGE_DIR" "$PROJECT_DIR"' in script
    assert 'mv -- "$QUARANTINE_DIR" "$PROJECT_DIR"' in script
    assert 'STATE_DB="${PROJECT_DIR}/admin.db"' in script
    assert 'RUNTIME_SECRETS_FILE="/etc/${PROJECT_NAME}/runtime-secrets.env"' in script
    assert 'validate_persistent_runtime_secrets()' in script
    assert 'WS_AUTH_SECRET is missing from runtime secrets' in script
    assert 'persistent runtime secrets must use mode 0600' in script
    assert 'systemd unit does not load persistent runtime secrets' in script
    assert 'Environment=REQUIRE_PERSISTENT_SECRETS=true' in script
    assert 'for pkg in core modules integrations routers services shared; do' in script
    assert 'for pkg in config core modules integrations routers services shared; do' not in script
    assert '".backup \'$STAGE_DIR/admin.db\'"' in script
    assert 'PRAGMA wal_checkpoint(TRUNCATE);' in script
    assert 'staged runtime database backup integrity check failed' in script
    assert 'install -m 0600 "$PROJECT_DIR/.encryption_key" "$STAGE_DIR/.encryption_key"' in script
    assert 'FRONTEND_NODE_OPTIONS="${FRONTEND_NODE_OPTIONS:---max-old-space-size=512}"' in script
    assert 'wait_for_health()' in script
    assert 'for attempt in {1..30}; do' in script
    assert 'health check did not become ready within 30 seconds' in script
    assert '[[ -x "$STAGE_DIR/venv/bin/uvicorn" ]]' in script
    assert '"$STAGE_DIR/venv/bin/uvicorn" --version >/dev/null' in script
    assert 'sed -i "1s|^#!.*$|#!${PROJECT_DIR}/venv/bin/python|" "$PROJECT_DIR/venv/bin/uvicorn"' in script
    assert 'chmod 0755 "$PROJECT_DIR"' in script
    assert '"$PROJECT_DIR/venv/bin/uvicorn" --version >/dev/null' in script
    assert 'rollback_and_exit' in script
    frontend_build = (REPO / "scripts/deploy/build-and-publish-frontend.sh").read_text(encoding="utf-8")
    assert 'export NODE_OPTIONS="$FRONTEND_NODE_OPTIONS"' in frontend_build
    assert 'find "$TARGET_BUILD_DIR" -type d -exec chmod 0755 {} +' in frontend_build
    assert 'find "$TARGET_BUILD_DIR" -type f -exec chmod 0644 {} +' in frontend_build
    assert "umask 077" in script


def test_nginx_generation_routes_the_telegram_webhook_before_the_ui_catch_all():
    expected_route = 'location ^~ /$WEB_PATH/telegram/ {'
    expected_upstream = 'proxy_pass http://127.0.0.1:$APP_PORT/telegram/;'
    expected_rate_limit = 'limit_req zone=telegram_webhook_zone burst=20 nodelay;'

    for relative_path in ("scripts/installer/install.sh", "scripts/installer/update.sh"):
        script = (REPO / relative_path).read_text(encoding="utf-8")
        assert 'limit_req_zone \\$binary_remote_addr zone=telegram_webhook_zone:10m rate=10r/s;' in script
        assert expected_route in script
        assert expected_upstream in script
        assert expected_rate_limit in script
        assert script.index(expected_route) < script.index('location ^~ /$WEB_PATH/ {')


def test_runtime_secret_rewrites_preserve_configured_telegram_settings():
    script = (REPO / "scripts/installer/lib/runtime_secrets.sh").read_text(encoding="utf-8")

    assert "local -a telegram_runtime_keys=(" in script
    for key in (
        "TELEGRAM_BOT_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_PRIMARY_ADMIN_ID",
        "TELEGRAM_WEBHOOK_SECRET",
        "TELEGRAM_WEBHOOK_PATH_SUFFIX",
        "TELEGRAM_PUBLIC_BASE_URL",
        "TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES",
        "TELEGRAM_OUTBOX_WORKER_ENABLED",
    ):
        assert key in script
    assert 'printf \'%s=%q\\n\' "$runtime_key" "${!runtime_key}"' in script


def test_linux_only_uvloop_extra_is_pinned_and_hashed_for_require_hashes_deploys():
    expected = 'uvloop==0.22.1 ; sys_platform != "win32"'
    expected_hash = "--hash=sha256:7b5b1ac819a3f946d3b2ee07f09149578ae76066d70b44df3fa990add49a82e4"

    for relative_path in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        lockfile = (REPO / relative_path).read_text(encoding="utf-8")
        assert expected in lockfile
        assert expected_hash in lockfile


def test_python_pam_runtime_compatibility_keeps_six_pinned():
    direct_requirements = (REPO / "backend/requirements.in").read_text(encoding="utf-8")
    assert "python-pam\n" in direct_requirements
    assert "six\n" in direct_requirements

    expected = "six==1.17.0"
    expected_hash = "--hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274"

    for relative_path in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        lockfile = (REPO / relative_path).read_text(encoding="utf-8")
        assert expected in lockfile
        assert expected_hash in lockfile


def test_windows_smoke_requires_exact_subpath_asset_prefix():
    script = (REPO / "scripts/windows/validate-project-smoke.ps1").read_text(encoding="utf-8")

    assert '"${basePath}assets/"' in script
    assert '"$basePathassets/"' not in script


def test_windows_project_smoke_keeps_remote_http_check_explicit_opt_in():
    script = (REPO / "scripts/windows/validate-project-smoke.ps1").read_text(encoding="utf-8")

    assert "[switch]$CheckRemote" in script
    assert "if ($CheckRemote)" in script
    assert "-CheckRemote requires PLAYWRIGHT_BASE_URL to be configured" in script
    assert script.index("if ($CheckRemote)") < script.index("curl.exe -k -L --max-time 10")


def test_legacy_windows_wrappers_propagate_canonical_script_exit_codes():
    expected_targets = {
        "scripts/windows/invoke-remote-deploy.ps1": "invoke-remote-deploy.ps1",
        "scripts/windows/windows-install.ps1": "windows-install.ps1",
        "scripts/windows/windows-update.ps1": "windows-update.ps1",
        "scripts/windows/windows-smoke.ps1": "windows-smoke.ps1",
    }

    for relative_path, target_name in expected_targets.items():
        script = (REPO / relative_path).read_text(encoding="utf-8")
        invocation = "& powershell -NoProfile -ExecutionPolicy Bypass -File $target @RemainingArgs"

        assert f'"{target_name}"' in script
        assert invocation in script
        assert "exit $LASTEXITCODE" in script
        assert script.index(invocation) < script.index("exit $LASTEXITCODE")


def test_canonical_windows_entrypoints_propagate_remote_deploy_exit_codes():
    entrypoints = (
        "scripts/installer/windows/windows-install.ps1",
        "scripts/installer/windows/windows-update.ps1",
        "scripts/installer/windows/windows-smoke.ps1",
    )
    invocation = "& powershell -NoProfile -ExecutionPolicy Bypass -File $deployScript @invokeParams"

    for relative_path in entrypoints:
        script = (REPO / relative_path).read_text(encoding="utf-8")

        assert '"invoke-remote-deploy.ps1"' in script
        assert invocation in script
        assert "exit $LASTEXITCODE" in script
        assert script.index(invocation) < script.index("exit $LASTEXITCODE")


def test_windows_remote_deploy_stages_only_clean_committed_source_without_shell_trace():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    assert 'git -C $RepoRoot rev-parse --verify HEAD' in script
    assert 'git -C $RepoRoot status --porcelain=v1 --untracked-files=all' in script
    assert 'Refusing to deploy a dirty source worktree' in script
    assert 'git -C $RepoRoot archive --format=tar.gz' in script
    assert "$requiredEntries = @(" in script
    assert '"$leaf/install.sh"' in script
    assert '"$leaf/update.sh"' in script
    assert '"$leaf/backend/main.py"' in script
    assert '"$leaf/backend/requirements.txt"' in script
    assert '"$leaf/scripts/installer/update.sh"' in script
    assert '"$leaf/scripts/installer/lib/entrypoint_layout.sh"' in script
    assert '"$leaf/scripts/installer/lib/source_layout.sh"' in script
    assert '"$leaf/scripts/ops/lib/install_log.sh"' in script
    assert '"$leaf/systemd/sub-manager.service"' in script
    assert '& tar.exe -tzf $ArchivePath' in script
    assert "Source archive is incomplete; missing required entries:" in script
    assert '.deploy-source-commit' in script
    assert r'printf %s\\n $deployCommit' in script
    assert 'bash -x' not in script
    assert 'sudo bash ./install.sh' in script
    assert 'sudo NONINTERACTIVE=true UPDATE_CHOICE=$UpdateChoice bash ./update.sh' in script


def test_windows_remote_deploy_skip_sync_uses_explicit_prepared_workdir():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    assert '[switch]$SkipSync' in script
    assert '$remoteWorkDir = if ($SkipSync) { $RemoteDir } else { "$RemoteDir-$runId" }' in script
    assert script.index('$remoteWorkDir = if ($SkipSync)') < script.index('if (-not $SkipSync)')
    assert "if (-not $SkipSync)" in script
    assert "cd $remoteWorkDir && sudo bash ./install.sh" in script
    assert "cd $remoteWorkDir && sudo NONINTERACTIVE=true UPDATE_CHOICE=$UpdateChoice bash ./update.sh" in script
    assert "cd $remoteWorkDir && sudo bash scripts/ops/smoke-test.sh" in script


def test_windows_remote_deploy_fails_closed_on_native_transport_errors():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    assert "function Invoke-NativeChecked" in script
    assert "& $FilePath @ArgumentList" in script
    assert "if ($LASTEXITCODE -ne 0)" in script
    assert 'throw "$Action failed with exit code $LASTEXITCODE."' in script
    assert 'Invoke-NativeChecked -Action "PuTTY remote command" -FilePath $Transport.Plink -ArgumentList $args' in script
    assert 'Invoke-NativeChecked -Action "OpenSSH remote command" -FilePath $Transport.Ssh -ArgumentList $args' in script
    assert 'Invoke-NativeChecked -Action "PuTTY remote copy" -FilePath $Transport.Pscp -ArgumentList $args' in script
    assert 'Invoke-NativeChecked -Action "OpenSSH remote copy" -FilePath $Transport.Scp -ArgumentList $args' in script


def test_windows_openssh_rejects_unsupported_hostkey_pins_and_keeps_known_hosts_pinning():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    openssh_transport = script.index('Type    = "openssh"')
    unsupported_pin = script.index("OpenSSH deployments do not support -HostKey pinning.")

    assert unsupported_pin < openssh_transport
    assert "HostKeyAlgorithms=" not in script
    assert script.count('"StrictHostKeyChecking=yes"') == 2
    assert script.count('"UserKnownHostsFile=$knownHosts"') == 2
    assert script.count('@("-hostkey", $Transport.HostKey)') == 2


def test_windows_remote_deploy_cleans_password_file_after_setup_failure():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    password_file_init = script.index("$passwordFile = $null")
    protected_setup = script.index("try {", password_file_init)
    password_setup = script.index("if ($Password) {", password_file_init)
    transport_setup = script.index("$transport = Get-Transport", password_file_init)
    cleanup = script.index("finally {", password_file_init)

    assert password_file_init < protected_setup < password_setup < transport_setup < cleanup
    assert "Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue" in script[cleanup:]


def test_windows_remote_deploy_cleans_local_archive_after_sync_or_failure():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    archive_init = script.index('$archivePath = Join-Path')
    archive_use = script.index('New-Archive -RepoRoot $repoRoot -ArchivePath $archivePath')
    cleanup = script.index("finally {", archive_init)
    archive_cleanup = script.index(
        'Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue',
        cleanup,
    )

    assert archive_init < archive_use < cleanup < archive_cleanup
    assert 'if ($archivePath -and (Test-Path -LiteralPath $archivePath))' in script[cleanup:]


def test_ops_backup_check_uses_consistent_runtime_database_backup():
    script = (REPO / "scripts/ops/backup-restore-check.sh").read_text(encoding="utf-8")

    assert 'DB_FILE="${DB_FILE:-${PROJECT_DIR}/admin.db}"' in script
    assert 'cp -a "$DB_FILE"' not in script
    assert "PRAGMA wal_checkpoint(PASSIVE);" not in script
    assert '".backup \'$BACKUP_FILE\'"' in script
    assert '".restore \'$BACKUP_FILE\'"' in script
    assert "admin.db.bak" in script
    assert "umask 077" in script
    assert 'mkdir -p -m 0700 "$OUT_DIR"' in script
    assert 'chmod 0600 "$BACKUP_FILE"' in script
    assert 'chmod 0600 "$RESTORE_FILE"' in script
    assert 'prune-verify-artifacts --older-than <days> [--apply]' in script
    assert 'VERIFY_ARTIFACT_GLOB="${PROJECT_NAME}_verify_' in script
    assert 'find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name "$VERIFY_ARTIFACT_GLOB"' in script
    assert 'rm -rf --one-file-system -- "$artifact"' in script
    assert '[[ "$APPLY_PRUNE" != "true" ]]' in script

    update = (REPO / "scripts/installer/update.sh").read_text(encoding="utf-8")
    assert 'backup-restore-check.sh list' in update
    assert 'prune-verify-artifacts --older-than 30' in update
