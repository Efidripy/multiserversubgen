#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/lib/locale.sh"
# shellcheck source=../ops/lib/install_log.sh
source "${REPO_ROOT}/scripts/ops/lib/install_log.sh"
# shellcheck source=lib/runtime_secrets.sh
source "${SCRIPT_DIR}/lib/runtime_secrets.sh"
source "${SCRIPT_DIR}/lib/component_ownership.sh"
LOG_FILE="/opt/.sub_manager_install.log"

REMOVE_MODE="${REMOVE_MODE:-keep-db}"
REMOVE_SCOPE="${REMOVE_SCOPE:-soft}"
HOST_WIDE_ACK_PHRASE="ERASE_HOST_WIDE_STACK"

PROJECT_NAME=""
PROJECT_DIR=""
SELECTED_CFG=""

require_verified_install_state() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "Installation state log is missing; no removal performed." >&2
        exit 1
    fi

    # shellcheck disable=SC1090
    if ! install_log_source "$LOG_FILE"; then
        echo "Installation state log failed validation; no removal performed." >&2
        exit 1
    fi

    if ! runtime_require_safe_project_name; then
        echo "Installation state log has an invalid project name; no removal performed." >&2
        exit 1
    fi

    if [ "${PROJECT_DIR:-}" != "/opt/$PROJECT_NAME" ]; then
        echo "Installation state log has an unexpected project directory; no removal performed." >&2
        exit 1
    fi
}

require_verified_install_state

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="/var/backups/${PROJECT_NAME}_remove_${timestamp}"

confirm_or_die() {
    local answer=""
    read -r -p "Confirm removal of ${PROJECT_NAME} (${REMOVE_MODE})? (yes/no): " answer
    [ "$answer" = "yes" ] || exit 1
}

require_supported_scope() {
    case "$REMOVE_SCOPE" in
        soft|hard) ;;
        *)
            echo "Unsupported removal scope; no removal performed." >&2
            exit 1
            ;;
    esac
}

require_host_wide_acknowledgement() {
    [ "$REMOVE_SCOPE" = "hard" ] || return 0

    local acknowledgement=""
    echo "WARNING: hard cleanup removes host-wide services, packages, and paths."
    read -r -p "Type ${HOST_WIDE_ACK_PHRASE} to continue: " acknowledgement
    if [ "$acknowledgement" != "$HOST_WIDE_ACK_PHRASE" ]; then
        echo "Host-wide acknowledgement did not match; no removal performed." >&2
        exit 1
    fi
}

ensure_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Run as root."
        exit 1
    fi
}

restore_nginx_if_needed() {
    local snippet_file="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    rm -f "$snippet_file"
    if [ -n "${SELECTED_CFG:-}" ] && [ -f "${SELECTED_CFG}.bak" ]; then
        mv -f "${SELECTED_CFG}.bak" "$SELECTED_CFG"
    fi
    nginx -t >/dev/null 2>&1 && systemctl restart nginx >/dev/null 2>&1 || true
}

backup_databases_if_requested() {
    [ "$REMOVE_MODE" = "keep-db" ] || return 0
    mkdir -p "$backup_dir"
    if [ -d "$PROJECT_DIR" ]; then
        find "$PROJECT_DIR" -maxdepth 1 -type f -name '*.db' -exec cp {} "$backup_dir/" \; 2>/dev/null || true
    fi
}

remove_monitoring_artifacts() {
    # No registry means no proof that a host-wide service belongs to MSSG.
    # Preserve external monitoring intact, including its running service.
    if mssg_ownership_is_managed prometheus; then
        rm -f /etc/prometheus/rules/sub-manager-rules.yml
        systemctl restart prometheus >/dev/null 2>&1 || true
    fi
    if mssg_ownership_is_managed grafana; then
        rm -f /etc/grafana/provisioning/datasources/sub-manager-prometheus.yml
        rm -f /etc/grafana/provisioning/dashboards/sub-manager-dashboard.yml
        rm -f /etc/systemd/system/grafana-server.service.d/40-sub-manager.conf
        rmdir /etc/systemd/system/grafana-server.service.d 2>/dev/null || true
        rm -rf /var/lib/grafana/dashboards/sub-manager
        systemctl daemon-reload
        systemctl restart grafana-server >/dev/null 2>&1 || true
    fi
}

hard_cleanup_stack() {
    # `hard` historically removed arbitrary host-wide packages and paths.
    # That made a reinstall capable of deleting an independently maintained
    # Grafana, 3x-ui or nginx. Keep the explicit acknowledgement, but retire
    # the destructive behaviour: shared components must be removed by their
    # owner with that component's own runbook.
    echo "Host-wide package/path purge is disabled by ownership policy."
    echo "Only Sub-Manager and registry-proven monitoring fragments were removed."
}

main() {
    ensure_root
    require_supported_scope
    require_host_wide_acknowledgement
    confirm_or_die

    systemctl stop "$PROJECT_NAME" >/dev/null 2>&1 || true
    systemctl disable "$PROJECT_NAME" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/${PROJECT_NAME}.service"
    rm -f "/etc/${PROJECT_NAME}/runtime-secrets.env"
    rmdir "/etc/${PROJECT_NAME}" 2>/dev/null || true
    systemctl daemon-reload

    backup_databases_if_requested

    rm -f "/etc/fail2ban/jail.d/multi-manager.local"
    rm -f "/etc/fail2ban/filter.d/multi-manager.conf"
    systemctl restart fail2ban >/dev/null 2>&1 || true

    remove_monitoring_artifacts
    restore_nginx_if_needed

    rm -rf "$PROJECT_DIR"
    rm -f "$LOG_FILE"

    if [ "$REMOVE_SCOPE" = "hard" ]; then
        hard_cleanup_stack
    fi

    echo "Removal complete."
    echo "Removal scope: $REMOVE_SCOPE"
    if [ "$REMOVE_MODE" = "keep-db" ]; then
        if [ -d "$backup_dir" ] && [ -n "$(find "$backup_dir" -maxdepth 1 -type f -name '*.db' -print -quit)" ]; then
            echo "Database backup preserved in: $backup_dir"
        else
            echo "No database files were found to preserve."
        fi
    fi
}

main "$@"
