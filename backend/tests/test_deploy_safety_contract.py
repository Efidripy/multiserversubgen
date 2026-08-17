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
    assert 'for pkg in config core modules integrations routers services shared; do' in script
    assert '".backup \'$STAGE_DIR/admin.db\'"' in script
    assert 'PRAGMA wal_checkpoint(TRUNCATE);' in script
    assert 'staged runtime database backup integrity check failed' in script
    assert 'install -m 0600 "$PROJECT_DIR/.encryption_key" "$STAGE_DIR/.encryption_key"' in script
    assert 'FRONTEND_NODE_OPTIONS="${FRONTEND_NODE_OPTIONS:---max-old-space-size=512}"' in script
    frontend_build = (REPO / "scripts/deploy/build-and-publish-frontend.sh").read_text(encoding="utf-8")
    assert 'export NODE_OPTIONS="$FRONTEND_NODE_OPTIONS"' in frontend_build
    assert "umask 077" in script


def test_linux_only_uvloop_extra_is_pinned_and_hashed_for_require_hashes_deploys():
    expected = 'uvloop==0.22.1 ; sys_platform != "win32"'
    expected_hash = "--hash=sha256:7b5b1ac819a3f946d3b2ee07f09149578ae76066d70b44df3fa990add49a82e4"

    for relative_path in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        lockfile = (REPO / relative_path).read_text(encoding="utf-8")
        assert expected in lockfile
        assert expected_hash in lockfile
