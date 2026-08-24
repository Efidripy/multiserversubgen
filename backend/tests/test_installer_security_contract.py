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
        assert 'source "${INSTALLER_DIR}/lib/config_activation.sh"' in script
        assert "activate_manager_config()" in script
        assert "REDIS_URL=.*|REDIS_URL=$REDIS_URL" not in script
        assert "MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS" not in script
        assert "chmod 0600 \"$LOG_FILE\"" in script
        assert "runtime_ensure_service_user" in script

    assert 'echo "REDIS_URL: ${REDIS_URL:-<none>}"' not in update
    assert 'echo "REDIS_URL: <redacted>"' in update


def test_manager_config_activation_is_staged_transactional_and_used_by_all_active_paths():
    helper = _read("scripts/installer/lib/config_activation.sh")
    install = _read("scripts/installer/install.sh")
    update = _read("scripts/installer/update.sh")

    assert "config_activation_snapshot \"unit\"" in helper
    assert "config_activation_snapshot \"snippet\"" in helper
    assert "config_activation_snapshot \"shield\"" in helper
    assert "config_activation_snapshot \"site\"" in helper
    assert "systemd-analyze verify \"$staged_unit\"" in helper
    assert "mv -fT -- \"$temp_target\" \"$target\"" in helper
    assert "config_activation_restore || true" in helper
    assert "must not traverse or resolve through a symlink" in helper
    assert "config_activation_render_service" in helper

    for script in (install, update):
        assert 'cat "$SCRIPT_DIR/systemd/sub-manager.service"' not in script
        assert 'ensure_nginx_snippet_include_in_cfg "$SELECTED_CFG" >/dev/null || true' not in script
        assert "config_activation_activate \"$stage_unit\"" in script

    assert install.count("activate_manager_config ") >= 2
    assert update.count("activate_manager_config ") >= 3


def test_runtime_secret_writer_is_root_only_and_atomic():
    helper = _read("scripts/installer/lib/runtime_secrets.sh")

    assert "runtime_require_safe_project_name()" in helper
    assert "runtime_require_expected_project_dir()" in helper
    assert '[[ ! "$project_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]' in helper
    assert 'runtime_require_safe_project_name || return 1' in helper
    assert 'local expected_project_dir="/opt/$PROJECT_NAME"' in helper
    assert 'if [ "${PROJECT_DIR:-}" != "$expected_project_dir" ]; then' in helper
    assert "install -d -m 0700" in helper
    assert "mktemp" in helper
    assert "chmod 0600 \"$temp_file\"" in helper
    assert 'if [ -L "$secret_file" ]; then' in helper
    assert 'refusing to overwrite symlinked runtime secrets' in helper
    assert 'mv -fT -- "$temp_file" "$secret_file"' in helper
    assert "runtime_ensure_service_user" in helper
    assert "useradd --system" in helper
    assert "chown -R -- \"$service_user:$service_user\" \"$service_dir\"" in helper
    assert 'source "$secret_file"' not in helper
    assert 'secure_source_file "$secret_file" "runtime secrets"' in helper


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
    launcher = _read("scripts/installer/launcher.sh")

    assert 'REMOVE_SCOPE="${REMOVE_SCOPE:-soft}"' in remove
    assert 'REMOVE_SCOPE="${REMOVE_SCOPE:-hard}"' not in remove
    assert "REMOVE_FORCE" not in remove
    assert 'REMOVE_MODE="$mode" REMOVE_SCOPE=soft bash "${INSTALLER_DIR}/remove.sh"' in workflows
    assert "REMOVE_SCOPE=hard" not in workflows
    assert "Full Cleanup" not in launcher
    assert "Remove Application + Keep Database" in launcher


def test_host_wide_cleanup_requires_an_exact_typed_acknowledgement():
    remove = _read("scripts/installer/remove.sh")
    workflows = _read("scripts/installer/lib/workflows.sh")

    assert 'HOST_WIDE_ACK_PHRASE="ERASE_HOST_WIDE_STACK"' in remove
    assert "require_supported_scope()" in remove
    assert "soft|hard) ;;" in remove
    assert "require_host_wide_acknowledgement()" in remove
    assert 'read -r -p "Type ${HOST_WIDE_ACK_PHRASE} to continue: " acknowledgement' in remove
    assert '[ "$acknowledgement" != "$HOST_WIDE_ACK_PHRASE" ]' in remove
    assert "Host-wide acknowledgement did not match; no removal performed." in remove
    main = remove.split("main() {", 1)[1]
    assert main.index("require_host_wide_acknowledgement") < main.index("confirm_or_die")
    assert "REMOVE_SCOPE=hard" not in workflows


def test_remove_requires_verified_install_state_before_any_mutation():
    remove = _read("scripts/installer/remove.sh")

    assert 'PROJECT_NAME="sub-manager"' not in remove
    assert 'PROJECT_DIR="/opt/sub-manager"' not in remove
    assert 'source "${SCRIPT_DIR}/lib/runtime_secrets.sh"' in remove
    assert "require_verified_install_state()" in remove
    assert 'if [ ! -f "$LOG_FILE" ]; then' in remove
    assert 'if ! install_log_source "$LOG_FILE"; then' in remove
    assert "if ! runtime_require_safe_project_name; then" in remove
    assert 'if [ "${PROJECT_DIR:-}" != "/opt/$PROJECT_NAME" ]; then' in remove
    state_guard = remove.split("require_verified_install_state() {", 1)[1].split("\n}\n\nrequire_verified_install_state", 1)[0]
    assert state_guard.count("no removal performed.") == 4

    state_gate = remove.index("\nrequire_verified_install_state\n")
    assert state_gate < remove.index('timestamp="$(date')
    assert state_gate < remove.index("confirm_or_die()")
    assert state_gate < remove.index('rm -rf "$PROJECT_DIR"')


def test_project_cleanup_preserves_evidence_and_supports_dry_run():
    script = _read("scripts/ops/project-cleanup.sh")
    safe_cleanup = script.split("cleanup_safe()", 1)[1].split("cleanup_deep()", 1)[0]

    assert 'GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"' in script
    assert 'cleanup refused: resolved path is not the project Git root' in script
    assert 'CLEANUP_DRY_RUN="${CLEANUP_DRY_RUN:-false}"' in script
    assert '".tmp"' not in safe_cleanup
    assert 'log "would remove: $path"' in script
    assert '  - .tmp/' in script
    assert '  - .vscode/' in script
    assert 'remove_if_exists ".vscode"' not in script
    assert "cleanup_python_caches" in script


def test_installation_report_uses_dynamic_repository_root():
    ui = _read("scripts/installer/lib/ui.sh")

    assert "/root/multiserversubgen-live/scripts/ops/" not in ui
    assert '"${SCRIPT_DIR}/scripts/ops/smoke-test.sh"' in ui
    assert '"${SCRIPT_DIR}/scripts/ops/backup-restore-check.sh"' in ui
    assert '"${SCRIPT_DIR}/scripts/ops/hardening-profile.sh" audit' in ui


def test_ops_scripts_validate_installer_log_before_sourcing():
    helper = _read("scripts/ops/lib/install_log.sh")
    for relative_path in (
        "scripts/ops/backup-restore-check.sh",
        "scripts/ops/smoke-test.sh",
    ):
        script = _read(relative_path)
        assert '\n  source "$LOG_FILE"' not in script
        assert "install_log_source \"$LOG_FILE\"" in script
        assert "lib/install_log.sh" in script

    assert "[[ ! -L \"$source_file\" ]]" in helper
    assert "stat -c '%u'" in helper
    assert "stat -c '%a'" in helper
    assert '[[ "$owner" == "0" && "$mode" == "600" ]]' in helper


def test_installer_scripts_validate_log_before_sourcing():
    helper = _read("scripts/ops/lib/install_log.sh")
    for relative_path in (
        "scripts/installer/install.sh",
        "scripts/installer/update.sh",
        "scripts/installer/remove.sh",
    ):
        script = _read(relative_path)
        assert '\n    source "$LOG_FILE"' not in script
        assert '\nsource "$LOG_FILE"' not in script
        assert "install_log_source \"$LOG_FILE\"" in script
        assert "scripts/ops/lib/install_log.sh" in script

    assert 'source "$source_file"' in helper
    assert 'secure_source_file()' in helper


def test_update_aborts_when_runtime_secrets_fail_security_validation():
    update = _read("scripts/installer/update.sh")

    assert "if ! runtime_require_safe_project_name; then" in update
    assert update.index("runtime_require_safe_project_name") < update.index("runtime_secrets_load")
    assert "if ! runtime_secrets_load; then" in update
    assert "Runtime secrets file failed security validation. Update aborted." in update
    assert "exit 1" in update


def test_update_aborts_when_installer_log_fails_security_validation():
    update = _read("scripts/installer/update.sh")

    guard = 'if ! install_log_source "$LOG_FILE"; then'
    assert guard in update
    assert "Installation state log failed security validation. Update aborted." in update

    guard_start = update.index(guard)
    guard_end = update.index("fi", guard_start)
    assert "exit 1" in update[guard_start:guard_end]
    assert update.index("runtime_require_safe_project_name") > guard_end
    assert update.index("runtime_require_expected_project_dir") > guard_end
    assert update.index("runtime_secrets_load") > guard_end
    assert update.index("runtime_secrets_write") > guard_end
    assert update.index("systemctl stop") > guard_end


def test_state_driven_installer_paths_require_exact_project_identity():
    install = _read("scripts/installer/install.sh")
    update = _read("scripts/installer/update.sh")
    uninstall_nuke = install.split("uninstall_nuke()", 1)[1].split("update_project()", 1)[0]

    assert install.count("runtime_require_expected_project_dir || return 1") == 2
    assert install.count("runtime_require_expected_project_dir || exit 1") == 5
    assert 'local project_name="${PROJECT_NAME:-sub-manager}"' not in uninstall_nuke
    assert 'local project_dir="${PROJECT_DIR:-/opt/sub-manager}"' not in uninstall_nuke
    assert 'rm -rf "$project_dir"' in uninstall_nuke
    assert uninstall_nuke.index("runtime_require_expected_project_dir || return 1") < uninstall_nuke.index('rm -rf "$project_dir"')
    assert "if ! runtime_require_expected_project_dir; then" in update
    assert update.index("runtime_require_expected_project_dir") < update.index("runtime_secrets_load")


def test_installer_validates_project_name_before_path_construction():
    install = _read("scripts/installer/install.sh")

    assert "if ! runtime_require_safe_project_name; then" in install
    validation = install.index("if ! runtime_require_safe_project_name; then", install.index('read -p "Имя проекта/сервиса'))
    assert validation < install.index('PROJECT_DIR="/opt/$PROJECT_NAME"')
    assert "runtime_require_expected_project_dir || exit 1" in install


def test_resource_guard_cleanup_is_project_scoped():
    guard = _read("scripts/installer/lib/resource_guard.sh")

    assert "resource_guard_project_root()" in guard
    assert 'project_root="$(resource_guard_project_root 2>/dev/null || true)"' in guard
    assert "/var/tmp/*" not in guard
    assert "/tmp/npm-*" not in guard
    assert "/tmp/vite-*" not in guard
    assert '"${PWD}/frontend"' not in guard
    assert "journalctl --vacuum-size" not in guard
    assert '"$project_root/frontend/node_modules"' in guard


def test_xui_installer_owns_only_its_dedicated_web_root_and_nginx_files():
    xui = _read("scripts/installer/lib/xui_core.sh")

    assert 'local target_dir="/var/www/multiserversubgen-xui-root"' in xui
    assert ".multiserversubgen-xui-root" in xui
    assert "Refusing to replace unowned XUI web root" in xui
    assert "Refusing symlinked XUI web root or ownership marker" in xui
    assert "xui_backup_owned_web_root" in xui
    assert "sha256sum -c" in xui
    assert "tar -tzf" in xui
    assert "xui_restore_owned_web_root" in xui
    assert "/var/www/html" not in xui
    assert "xui_install_root_landing_template || true" not in xui

    for path in (
        "multiserversubgen-xui-includes.conf",
        "multiserversubgen-xui-stream.conf",
        "multiserversubgen-xui-redirect.conf",
        "multiserversubgen-xui-main.conf",
        "multiserversubgen-xui-reality.conf",
    ):
        assert path in xui
    assert "# managed-by: multiserversubgen-xui" in xui
    assert "/etc/nginx/sites-enabled/default.*" not in xui
    assert 'Dpkg::Options::="--force-confnew"' not in xui
    assert 'Dpkg::Options::="--force-confold"' in xui
    configure = xui.split("xui_configure_nginx_and_tls()", 1)[1]
    assert configure.index('xui_backup_managed_nginx_files "$domain" "$reality_domain"') < configure.index(
        "xui_ensure_system_prerequisites"
    )


def test_stream_mux_conflicts_fail_closed_without_deleting_unmanaged_sites():
    xui = _read("scripts/installer/lib/xui_core.sh")

    assert "xui_assert_no_unmanaged_nginx_443_conflicts" in xui
    assert "Refusing to replace unmanaged Nginx listener(s) on port 443" in xui
    assert "Refusing to modify an unmanaged Nginx stream block" in xui

    for relative_path in (
        "scripts/installer/install.sh",
        "scripts/installer/update.sh",
    ):
        script = _read(relative_path)
        assert "/etc/nginx/sites-enabled/default.*" not in script
        assert "Refusing to remove unmanaged Nginx site listener(s) on port 443" in script
        assert script.count("sanitize_nginx_sites_for_stream_443 || exit 1") == 3
