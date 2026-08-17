from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_deploy_uses_immutable_local_ref_and_atomic_stage_rollback():
    script = (REPO / "scripts/deploy/server-deploy.sh").read_text(encoding="utf-8")

    assert "git -C \"$REPO_DIR\" pull" not in script
    assert "DEPLOY_REF" in script
    assert "checkout must already be at immutable DEPLOY_REF" in script
    assert '[[ "$PROJECT_DIR" == /opt/* && "$PROJECT_DIR" != /opt ]]' in script
    assert 'tar -C "$PROJECT_PARENT" -czf "$BACKUP_TAR" -- "$PROJECT_BASENAME"' in script
    assert 'tar -xzf "$BACKUP_TAR" -C /' not in script
    assert 'sha256sum "$BACKUP_TAR" > "$BACKUP_SHA"' in script
    assert 'mv -- "$STAGE_DIR" "$PROJECT_DIR"' in script
    assert 'mv -- "$QUARANTINE_DIR" "$PROJECT_DIR"' in script
    assert 'STATE_DB="${PROJECT_DIR}/admin.db"' in script
    assert '".backup \'$STAGE_DIR/admin.db\'"' in script
    assert 'PRAGMA wal_checkpoint(TRUNCATE);' in script
    assert 'staged runtime database backup integrity check failed' in script
    assert 'install -m 0600 "$PROJECT_DIR/.encryption_key" "$STAGE_DIR/.encryption_key"' in script
    assert "umask 077" in script
