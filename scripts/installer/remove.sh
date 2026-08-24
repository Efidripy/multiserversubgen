#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/lib/locale.sh"
# shellcheck source=../ops/lib/install_log.sh
source "${REPO_ROOT}/scripts/ops/lib/install_log.sh"
# shellcheck source=lib/runtime_secrets.sh
source "${SCRIPT_DIR}/lib/runtime_secrets.sh"
LOG_FILE="/opt/.sub_manager_install.log"

REMOVE_MODE="${REMOVE_MODE:-keep-db}"
REMOVE_FORCE="${REMOVE_FORCE:-false}"
# Direct invocation is conservative. The installer launcher passes `hard`
# explicitly for the operator-selected full cleanup workflow.
REMOVE_SCOPE="${REMOVE_SCOPE:-soft}"

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
    if [ "$REMOVE_FORCE" = "true" ]; then
        return 0
    fi
    local answer=""
    read -r -p "Confirm removal of ${PROJECT_NAME} (${REMOVE_MODE})? (yes/no): " answer
    [ "$answer" = "yes" ] || exit 1
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
    rm -f /etc/prometheus/rules/sub-manager-rules.yml
    rm -f /etc/grafana/provisioning/datasources/sub-manager-prometheus.yml
    rm -f /etc/grafana/provisioning/dashboards/sub-manager-dashboard.yml
    rm -f /var/lib/grafana/dashboards/sub-manager-dashboard.json
    rm -f /var/lib/grafana/dashboards/adguard-overview-dashboard.json
    systemctl restart prometheus >/dev/null 2>&1 || true
    systemctl restart grafana-server >/dev/null 2>&1 || true
}

hard_cleanup_stack() {
    local services=(
        "$PROJECT_NAME"
        nginx
        x-ui
        AdGuardHome
        prometheus
        grafana-server
        loki
        promtail
        sub2sing-box
        fail2ban
    )

    local units=(
        "/etc/systemd/system/${PROJECT_NAME}.service"
        "/etc/systemd/system/x-ui.service"
        "/etc/systemd/system/AdGuardHome.service"
        "/etc/systemd/system/loki.service"
        "/etc/systemd/system/promtail.service"
        "/etc/systemd/system/sub2sing-box.service"
    )

    local purge_candidates=(
        nginx
        nginx-common
        nginx-core
        nginx-full
        libnginx-mod-stream
        prometheus
        prometheus-node-exporter
        prometheus-node-exporter-collectors
        grafana
        grafana-enterprise
        loki
        promtail
        certbot
        python3-certbot-nginx
        fail2ban
    )

    local cleanup_paths=(
        "$PROJECT_DIR"
        /usr/local/x-ui
        /usr/local/bin/x-ui
        /usr/bin/x-ui
        /etc/x-ui
        /opt/AdGuardHome
        /etc/AdGuardHome
        /var/lib/AdGuardHome
        /var/log/AdGuardHome
        /etc/nginx
        /var/log/nginx
        /etc/grafana
        /etc/prometheus
        /etc/loki
        /etc/promtail
        /etc/letsencrypt
        /etc/ssl/sub-manager
        /var/lib/grafana
        /var/lib/loki
        /var/lib/promtail
        /var/log/prometheus
        /var/log/grafana
        /var/log/loki
        /var/log/promtail
        /var/www/html
        /etc/fail2ban
        /usr/local/bin/loki
        /usr/local/bin/promtail
        /usr/local/bin/sub2sing-box
    )

    local service
    for service in "${services[@]}"; do
        systemctl stop "$service" >/dev/null 2>&1 || true
        systemctl disable "$service" >/dev/null 2>&1 || true
    done

    local unit
    for unit in "${units[@]}"; do
        rm -f "$unit"
    done
    systemctl daemon-reload

    apt-get purge -y "${purge_candidates[@]}" >/dev/null 2>&1 || true
    apt-get autoremove -y >/dev/null 2>&1 || true
    apt-get clean >/dev/null 2>&1 || true

    local path
    for path in "${cleanup_paths[@]}"; do
        rm -rf "$path"
    done
}

main() {
    ensure_root
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
