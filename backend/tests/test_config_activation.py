import os
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts" / "installer" / "lib" / "config_activation.sh"


def _bash() -> str:
    git_bash = Path("E:/Git/bin/bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    bash = shutil.which("bash")
    assert bash, "bash is required for installer activation contract tests"
    return bash


def _run_case(case: str) -> subprocess.CompletedProcess[str]:
    script = r'''
if command -v cygpath >/dev/null 2>&1; then
    helper="$(cygpath -u "$CONFIG_ACTIVATION_HELPER")"
    template="$(cygpath -u "$CONFIG_ACTIVATION_TEMPLATE")"
else
    helper="$CONFIG_ACTIVATION_HELPER"
    template="$CONFIG_ACTIVATION_TEMPLATE"
fi
source "$helper"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/bin" "$work/systemd" "$work/nginx/snippets" "$work/nginx/conf.d" "$work/nginx/sites-available"
export PATH="$work/bin:$PATH"
export CONFIG_ACTIVATION_RUNTIME_ROOT="$work/run"
export CONFIG_ACTIVATION_BACKUP_ROOT="$work/backups"
export CONFIG_ACTIVATION_SYSTEMD_DIR="$work/systemd"
export CONFIG_ACTIVATION_NGINX_ROOT="$work/nginx"

cat > "$work/bin/systemd-analyze" <<'MOCK'
#!/bin/bash
[ "${FAIL_SYSTEMD_VERIFY:-0}" != "1" ]
MOCK
cat > "$work/bin/systemctl" <<'MOCK'
#!/bin/bash
exit 0
MOCK
cat > "$work/bin/nginx" <<'MOCK'
#!/bin/bash
if [ "${FAIL_NGINX_TEST:-0}" = "1" ] && [ "${1:-}" = "-t" ]; then
    exit 1
fi
exit 0
MOCK
cat > "$work/bin/install" <<'MOCK'
#!/bin/bash
if [ "${1:-}" = "-d" ]; then
    shift
    if [ "${1:-}" = "-m" ]; then shift 2; fi
    mkdir -p -- "$@"
    exit 0
fi
if [ "${1:-}" = "-m" ]; then shift 2; fi
cp -- "$@"
MOCK
cat > "$work/bin/python3" <<'MOCK'
#!/bin/bash
exec python "$@"
MOCK
chmod 0755 "$work/bin/systemd-analyze" "$work/bin/systemctl" "$work/bin/nginx" "$work/bin/install" "$work/bin/python3"

runtime_require_safe_project_name() { :; }
runtime_require_expected_project_dir() { :; }
PROJECT_NAME="sub-manager"
PROJECT_DIR="/opt/sub-manager"
APP_PORT="666"
GRAFANA_HTTP_PORT="43000"
PUBLIC_DOMAIN="example.test"
WEB_PATH="panel"
GRAFANA_WEB_PATH="grafana"
MONITORING_ENABLED="false"
VERIFY_TLS="true"
READ_ONLY_MODE="false"
MFA_TOTP_ENABLED="false"
MFA_TOTP_WS_STRICT="true"
SECURITY_MTLS_ENABLED="false"
SUB_RATE_LIMIT_COUNT="30"
SUB_RATE_LIMIT_WINDOW_SEC="60"
TRAFFIC_STATS_CACHE_TTL="20"
TRAFFIC_STATS_STALE_TTL="120"
CLIENTS_CACHE_TTL="20"
CLIENTS_CACHE_STALE_TTL="180"
TRAFFIC_MAX_WORKERS="6"
COLLECTOR_BASE_INTERVAL_SEC="10"
COLLECTOR_MAX_INTERVAL_SEC="60"
COLLECTOR_MAX_PARALLEL="4"
AUDIT_QUEUE_BATCH_SIZE="200"
ALLOW_ORIGINS="http://localhost:5173"
CA_BUNDLE_PATH=""
ROLE_VIEWERS=""
ROLE_OPERATORS=""
SECURITY_IP_ALLOWLIST=""

selected="$work/nginx/sites-available/panel"
unit="$work/systemd/$PROJECT_NAME.service"
snippet="$work/nginx/snippets/$PROJECT_NAME.conf"
shield="$work/nginx/conf.d/$PROJECT_NAME-shield.conf"
printf 'old-unit\n' > "$unit"
printf 'old-snippet\n' > "$snippet"
printf 'old-shield\n' > "$shield"
printf 'server { }\n' > "$selected"

if [ "$1" = "absent-targets" ]; then
    rm -f -- "$unit" "$snippet" "$shield"
fi
if [ "$1" = "out-of-tree" ]; then
    selected="$work/nginx/conf.d/outside.conf"
    outside="$selected"
    printf 'outside\n' > "$outside"
fi

config_activation_begin
stage_unit="$CONFIG_ACTIVATION_STAGE_DIR/unit"
stage_snippet="$CONFIG_ACTIVATION_STAGE_DIR/snippet"
stage_shield="$CONFIG_ACTIVATION_STAGE_DIR/shield"
stage_site="$CONFIG_ACTIVATION_STAGE_DIR/site"
printf 'new-unit\n' > "$stage_unit"
printf 'new-snippet\n' > "$stage_snippet"
printf 'new-shield\n' > "$stage_shield"
printf 'server { include /etc/nginx/snippets/sub-manager.conf; }\n' > "$stage_site"

case "$1" in
    render-service)
        config_activation_render_service "$template" "$stage_unit"
        grep -qx 'Environment="APP_PORT=666"' "$stage_unit"
        grep -q -- '--port 666 --log-level warning' "$stage_unit"
        ;;
    happy)
        config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" true
        grep -qx 'new-unit' "$unit"
        grep -qx 'new-snippet' "$snippet"
        grep -qx 'new-shield' "$shield"
        grep -q 'include /etc/nginx/snippets/sub-manager.conf' "$selected"
        [ "$(wc -l < "$CONFIG_ACTIVATION_BACKUP_DIR/manifest")" -eq 4 ]
        ;;
    verify-failure)
        export FAIL_SYSTEMD_VERIFY=1
        if config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" true; then exit 1; fi
        grep -qx 'old-unit' "$unit"
        grep -qx 'old-snippet' "$snippet"
        grep -qx 'old-shield' "$shield"
        grep -qx 'server { }' "$selected"
        [ ! -s "$CONFIG_ACTIVATION_BACKUP_DIR/manifest" ]
        ;;
    nginx-failure)
        export FAIL_NGINX_TEST=1
        if config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" true; then exit 1; fi
        grep -qx 'old-unit' "$unit"
        grep -qx 'old-snippet' "$snippet"
        grep -qx 'old-shield' "$shield"
        grep -qx 'server { }' "$selected"
        ;;
    service-failure)
        if config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" false; then exit 1; fi
        grep -qx 'old-unit' "$unit"
        grep -qx 'old-snippet' "$snippet"
        grep -qx 'old-shield' "$shield"
        grep -qx 'server { }' "$selected"
        ;;
    absent-targets)
        export FAIL_NGINX_TEST=1
        if config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" true; then exit 1; fi
        [ ! -e "$unit" ]
        [ ! -e "$snippet" ]
        [ ! -e "$shield" ]
        grep -qx 'server { }' "$selected"
        ;;
    out-of-tree)
        if config_activation_activate "$stage_unit" "$stage_snippet" "$stage_shield" "$stage_site" "$selected" true; then exit 1; fi
        grep -qx 'old-unit' "$unit"
        grep -qx 'old-snippet' "$snippet"
        grep -qx 'old-shield' "$shield"
        ;;
    *) exit 2 ;;
esac
config_activation_cleanup
'''
    environment = os.environ | {
        "CONFIG_ACTIVATION_HELPER": str(HELPER),
        "CONFIG_ACTIVATION_TEMPLATE": str(REPO / "systemd" / "sub-manager.service"),
    }
    return subprocess.run(
        [_bash(), "-e", "-u", "-o", "pipefail", "-c", script, "config-activation", case],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_config_activation_happy_path_promotes_all_managed_targets():
    result = _run_case("happy")
    assert result.returncode == 0, result.stderr


def test_config_activation_renders_the_expected_systemd_unit_contract():
    result = _run_case("render-service")
    assert result.returncode == 0, result.stderr


def test_config_activation_rejects_invalid_staged_unit_before_mutation():
    result = _run_case("verify-failure")
    assert result.returncode == 0, result.stderr


def test_config_activation_nginx_failure_restores_every_target():
    result = _run_case("nginx-failure")
    assert result.returncode == 0, result.stderr


def test_config_activation_service_failure_restores_every_target():
    result = _run_case("service-failure")
    assert result.returncode == 0, result.stderr


def test_config_activation_removes_previously_absent_managed_targets_on_rollback():
    result = _run_case("absent-targets")
    assert result.returncode == 0, result.stderr


def test_config_activation_rejects_out_of_tree_selected_site_before_mutation():
    result = _run_case("out-of-tree")
    assert result.returncode == 0, result.stderr
