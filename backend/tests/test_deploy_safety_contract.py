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


def test_linux_only_uvloop_extra_is_pinned_and_hashed_for_require_hashes_deploys():
    expected = 'uvloop==0.22.1 ; sys_platform != "win32"'
    expected_hash = "--hash=sha256:7b5b1ac819a3f946d3b2ee07f09149578ae76066d70b44df3fa990add49a82e4"

    for relative_path in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        lockfile = (REPO / relative_path).read_text(encoding="utf-8")
        assert expected in lockfile
        assert expected_hash in lockfile


def test_windows_remote_deploy_stages_only_clean_committed_source_without_shell_trace():
    script = (REPO / "scripts/installer/windows/invoke-remote-deploy.ps1").read_text(encoding="utf-8")

    assert 'git -C $RepoRoot rev-parse --verify HEAD' in script
    assert 'git -C $RepoRoot status --porcelain=v1 --untracked-files=all' in script
    assert 'Refusing to deploy a dirty source worktree' in script
    assert 'git -C $RepoRoot archive --format=tar.gz' in script
    assert '.deploy-source-commit' in script
    assert r'printf %s\\n $deployCommit' in script
    assert 'bash -x' not in script
    assert 'sudo bash ./install.sh' in script
    assert 'sudo NONINTERACTIVE=true UPDATE_CHOICE=$UpdateChoice bash ./update.sh' in script


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
