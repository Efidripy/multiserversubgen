#!/bin/bash
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${INSTALLER_DIR}/../.." && pwd)"

source "${INSTALLER_DIR}/lib/locale.sh"
source "${INSTALLER_DIR}/lib/ui.sh"
source "${INSTALLER_DIR}/lib/xui_core.sh"

generate_random_path() {
    tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 8
}

sanitize_path_token() {
    local value="${1:-}"
    value="$(printf "%s" "$value" | tr -cd '[:alnum:]')"
    if [ -z "$value" ]; then
        value="$(generate_random_path)"
    fi
    printf "%s" "$value"
}

clear_stale_install_markers() {
    local project_name="${PROFILE_PROJECT_NAME:-sub-manager}"
    local project_dir="/opt/${project_name}"
    local stale_logs=(
        "/opt/.sub_manager_install.log"
        "/opt/sub_manager_install.log"
        "${project_dir}/.sub_manager_install.log"
    )

    [ -d "$project_dir" ] && return 0

    local marker
    for marker in "${stale_logs[@]}"; do
        [ -f "$marker" ] && sudo rm -f "$marker"
    done

    return 0
}

ensure_sub_manager_nginx_include() {
    local site_file="$1"
    [ -f "$site_file" ] || return 0

    sudo python3 - "$site_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
insert = '    include /etc/nginx/snippets/sub-manager.conf;'

cleaned = []
brace_depth = 0
server_depth = None
include_present = False

for line in lines:
    stripped = line.strip()
    comment = stripped.startswith('#')

    current_depth = brace_depth

    if stripped == insert.strip():
        if not comment and server_depth is not None and current_depth >= server_depth:
            if not include_present:
                cleaned.append(insert)
                include_present = True
        continue

    cleaned.append(line)

    if comment:
        continue

    opens = line.count('{')
    closes = line.count('}')

    if server_depth is None and stripped.startswith('server') and '{' in line:
        server_depth = brace_depth + 1

    brace_depth += opens
    brace_depth -= closes

    if server_depth is not None and brace_depth < server_depth:
        server_depth = None

brace_depth = 0
server_depth = None
inserted = include_present
result = []

for line in cleaned:
    stripped = line.strip()
    comment = stripped.startswith('#')

    if not comment and server_depth is not None and stripped == '}' and brace_depth == server_depth and not inserted:
        result.append(insert)
        inserted = True

    result.append(line)

    if comment:
        continue

    opens = line.count('{')
    closes = line.count('}')

    if server_depth is None and stripped.startswith('server') and '{' in line:
        server_depth = brace_depth + 1

    brace_depth += opens
    brace_depth -= closes

    if server_depth is not None and brace_depth < server_depth:
        server_depth = None

if not inserted:
    for idx in range(len(result) - 1, -1, -1):
        if result[idx].strip() == '}':
            result.insert(idx, insert)
            inserted = True
            break

path.write_text('\n'.join(result) + '\n')
PY
}

repair_xui_nginx_integration() {
    local domains=()
    local domain
    local site_file

    [ -f /etc/nginx/snippets/sub-manager.conf ] || return 0

    for domain in "${PROFILE_PUBLIC_DOMAIN:-}" "${PROFILE_XUI_DOMAIN:-}" "${PROFILE_XUI_REALITY_DOMAIN:-}"; do
        [ -n "$domain" ] || continue
        case " ${domains[*]} " in
            *" ${domain} "*) ;;
            *) domains+=("$domain") ;;
        esac
    done

    for domain in "${domains[@]}"; do
        site_file="/etc/nginx/sites-available/${domain}"
        ensure_sub_manager_nginx_include "$site_file"
    done

    if command -v nginx >/dev/null 2>&1; then
        sudo nginx -t
        sudo systemctl reload nginx
    fi
}

run_internal_xui_install() {
    local xui_domain="${PROFILE_XUI_DOMAIN:-vm1.kleva.ru}"
    local xui_reality_domain="${PROFILE_XUI_REALITY_DOMAIN:-vm2.kleva.ru}"
    local xui_tag

    if [ "${INSTALLER_DRY_RUN:-false}" = "true" ]; then
        installer_message "Dry Run" "Would install 3x-ui using the internal core for ${xui_domain} and ${xui_reality_domain}."
        installer_pause
        return 0
    fi

    xui_tag="$(xui_pick_release_tag)"
    installer_message "Installing 3x-ui" "Running internal x-ui core for ${xui_domain} and ${xui_reality_domain}..."
    xui_install_binary "$xui_tag"
    xui_generate_seed_context "$xui_domain" "$xui_reality_domain"
    xui_install_sub2sing_box
    xui_render_sub_templates
    xui_configure_nginx_and_tls "$xui_domain" "$xui_reality_domain"
    xui_configure_panel "$xui_domain" "${PROFILE_XUI_CERT_PATH:-}" "${PROFILE_XUI_CERT_KEY_PATH:-}"
    xui_seed_base_inbounds "$xui_domain" "$xui_reality_domain"
    xui_collect_summary
    xui_print_runtime_summary

    PROFILE_XUI_DOMAIN="${xui_domain}"
    PROFILE_XUI_REALITY_DOMAIN="${xui_reality_domain}"
}

collect_common_settings() {
    local default_domain
    default_domain="$(hostname -f 2>/dev/null || hostname)"

    PROFILE_PROJECT_NAME="$(installer_prompt_text "Project Name" "Service name for this install." "sub-manager")"
    PROFILE_APP_PORT="$(installer_prompt_text "Application Port" "Local port for Sub-Manager." "666")"
    PROFILE_PUBLIC_DOMAIN="$(installer_prompt_text "Public Domain" "Public hostname without http/https." "${default_domain}")"

    local scheme_choice
    scheme_choice="$(installer_select_menu \
        "Public URL Scheme" \
        "Choose how the public URLs should be generated." \
        "https" \
        "http")"
    case "$scheme_choice" in
        __QUIT__|__BACK__) return 1 ;;
        1) PROFILE_PUBLIC_SCHEME="http" ;;
        *) PROFILE_PUBLIC_SCHEME="https" ;;
    esac

    local panel_random
    panel_random="$(installer_prompt_yes_no \
        "Panel Path" \
        "Generate a random panel path?" \
        "y")"
    case "$panel_random" in
        __QUIT__|__BACK__) return 1 ;;
        y)
            PROFILE_PANEL_RANDOM="y"
            PROFILE_WEB_PATH=""
            ;;
        n)
            PROFILE_PANEL_RANDOM="n"
            PROFILE_WEB_PATH="$(sanitize_path_token "$(installer_prompt_text "Panel Path" "Manual browser path for the panel." "$(generate_random_path)")")"
            ;;
    esac
    return 0
}

collect_monitoring_settings() {
    PROFILE_MONITORING="y"
    PROFILE_GRAFANA_RANDOM="y"
    PROFILE_GRAFANA_PATH=""
    PROFILE_ADGUARD_METRICS="n"
    PROFILE_ADGUARD_METRICS_TARGETS=""
    PROFILE_ADGUARD_METRICS_PATH=""
    PROFILE_ADGUARD_LOKI="n"
    PROFILE_ADGUARD_QUERYLOG_PATH=""
    PROFILE_ADGUARD_SYSTEMD_UNIT=""

    if [ "${1:-y}" = "n" ]; then
        PROFILE_MONITORING="n"
        return 0
    fi

    local grafana_random
    grafana_random="$(installer_prompt_yes_no \
        "Grafana Path" \
        "Generate a random Grafana path?" \
        "y")"
    case "$grafana_random" in
        __QUIT__|__BACK__) return 1 ;;
        y)
            PROFILE_GRAFANA_RANDOM="y"
            ;;
        n)
            PROFILE_GRAFANA_RANDOM="n"
            PROFILE_GRAFANA_PATH="$(sanitize_path_token "$(installer_prompt_text "Grafana Path" "Manual browser path for Grafana." "$(generate_random_path)")")"
            ;;
    esac

    if [ "${2:-n}" = "y" ]; then
        PROFILE_ADGUARD_LOKI="y"
        PROFILE_ADGUARD_QUERYLOG_PATH="/opt/AdGuardHome/data/querylog.json"
        PROFILE_ADGUARD_SYSTEMD_UNIT="AdGuardHome.service"
    fi

    if [ "${3:-n}" = "y" ]; then
        PROFILE_ADGUARD_METRICS="y"
        PROFILE_ADGUARD_METRICS_TARGETS="127.0.0.1:3000"
        PROFILE_ADGUARD_METRICS_PATH="/control/prometheus/metrics"
    fi

    if [ "${4:-false}" = "true" ]; then
        local enable_metrics enable_loki
        enable_metrics="$(installer_prompt_yes_no "AdGuard Metrics" "Enable AdGuard metrics provisioning for Prometheus?" "${PROFILE_ADGUARD_METRICS}")"
        case "$enable_metrics" in
            __QUIT__|__BACK__) return 1 ;;
            y)
                PROFILE_ADGUARD_METRICS="y"
                PROFILE_ADGUARD_METRICS_TARGETS="$(installer_prompt_text "AdGuard Targets" "Comma-separated AdGuard targets." "${PROFILE_ADGUARD_METRICS_TARGETS:-127.0.0.1:3000}")"
                PROFILE_ADGUARD_METRICS_PATH="$(installer_prompt_text "AdGuard Metrics Path" "Prometheus metrics path for AdGuard." "${PROFILE_ADGUARD_METRICS_PATH:-/control/prometheus/metrics}")"
                ;;
            n)
                PROFILE_ADGUARD_METRICS="n"
                PROFILE_ADGUARD_METRICS_TARGETS=""
                PROFILE_ADGUARD_METRICS_PATH=""
                ;;
        esac

        enable_loki="$(installer_prompt_yes_no "AdGuard Querylog" "Enable Loki/promtail provisioning for AdGuard querylog?" "${PROFILE_ADGUARD_LOKI}")"
        case "$enable_loki" in
            __QUIT__|__BACK__) return 1 ;;
            y)
                PROFILE_ADGUARD_LOKI="y"
                PROFILE_ADGUARD_QUERYLOG_PATH="$(installer_prompt_text "AdGuard Querylog Path" "Path to querylog.json." "${PROFILE_ADGUARD_QUERYLOG_PATH:-/opt/AdGuardHome/data/querylog.json}")"
                PROFILE_ADGUARD_SYSTEMD_UNIT="$(installer_prompt_text "AdGuard Systemd Unit" "Systemd unit name for AdGuard." "${PROFILE_ADGUARD_SYSTEMD_UNIT:-AdGuardHome.service}")"
                ;;
            n)
                PROFILE_ADGUARD_LOKI="n"
                PROFILE_ADGUARD_QUERYLOG_PATH=""
                PROFILE_ADGUARD_SYSTEMD_UNIT=""
                ;;
        esac
    fi
    return 0
}

show_install_summary() {
    installer_message "$1" "$2"
    printf "${UI_GREEN}Project:${UI_RESET} %s\n" "$PROFILE_PROJECT_NAME"
    printf "${UI_GREEN}Port:${UI_RESET} %s\n" "$PROFILE_APP_PORT"
    printf "${UI_GREEN}Domain:${UI_RESET} %s\n" "$PROFILE_PUBLIC_DOMAIN"
    printf "${UI_GREEN}Scheme:${UI_RESET} %s\n" "$PROFILE_PUBLIC_SCHEME"
    if [ "$PROFILE_PANEL_RANDOM" = "y" ]; then
        printf "${UI_GREEN}Panel Path:${UI_RESET} random\n"
    else
        printf "${UI_GREEN}Panel Path:${UI_RESET} /%s/\n" "$PROFILE_WEB_PATH"
    fi
    if [ "${PROFILE_MONITORING:-n}" = "y" ]; then
        printf "${UI_GREEN}Monitoring:${UI_RESET} enabled\n"
        if [ "$PROFILE_GRAFANA_RANDOM" = "y" ]; then
            printf "${UI_GREEN}Grafana Path:${UI_RESET} random\n"
        else
            printf "${UI_GREEN}Grafana Path:${UI_RESET} /%s/\n" "$PROFILE_GRAFANA_PATH"
        fi
        printf "${UI_GREEN}AdGuard Metrics:${UI_RESET} %s\n" "$PROFILE_ADGUARD_METRICS"
        printf "${UI_GREEN}AdGuard Loki:${UI_RESET} %s\n" "$PROFILE_ADGUARD_LOKI"
    else
        printf "${UI_GREEN}Monitoring:${UI_RESET} disabled\n"
    fi
    if [ -n "${PROFILE_XUI_PANEL_URL:-}" ]; then
        printf "${UI_GREEN}3x-ui Panel:${UI_RESET} %s\n" "$PROFILE_XUI_PANEL_URL"
        printf "${UI_GREEN}3x-ui Username:${UI_RESET} %s\n" "${PROFILE_XUI_USERNAME:-unknown}"
        printf "${UI_GREEN}3x-ui Password:${UI_RESET} %s\n" "${PROFILE_XUI_PASSWORD:-unknown}"
        if [ -n "${PROFILE_XUI_WEBSUB_URL:-}" ]; then
            printf "${UI_GREEN}3x-ui Web Sub:${UI_RESET} %s\n" "${PROFILE_XUI_WEBSUB_URL}"
        fi
        if [ -n "${PROFILE_XUI_SUB2SING_URL:-}" ]; then
            printf "${UI_GREEN}3x-ui sub2sing:${UI_RESET} %s\n" "${PROFILE_XUI_SUB2SING_URL}"
        fi
    fi
    printf "\n"
}

run_install_with_answers() {
    local answers_file
    local selected_cfg=""
    local exact_cfg=""
    answers_file="$(mktemp)"
    {
        printf "%s\n" "$PROFILE_PROJECT_NAME"
        printf "%s\n" "$PROFILE_APP_PORT"
        printf "%s\n" "$PROFILE_PUBLIC_DOMAIN"
        printf "%s\n" "$PROFILE_PUBLIC_SCHEME"
        printf "%s\n" "$PROFILE_PANEL_RANDOM"
        if [ "$PROFILE_PANEL_RANDOM" = "n" ]; then
            printf "%s\n" "$PROFILE_WEB_PATH"
        fi
        printf "b\n"
        printf "%s\n" "${PROFILE_MONITORING:-n}"
        if [ "${PROFILE_MONITORING:-n}" = "y" ]; then
            printf "%s\n" "$PROFILE_GRAFANA_RANDOM"
            if [ "$PROFILE_GRAFANA_RANDOM" = "n" ]; then
                printf "%s\n" "$PROFILE_GRAFANA_PATH"
            fi
            printf "%s\n" "$PROFILE_ADGUARD_METRICS"
            if [ "$PROFILE_ADGUARD_METRICS" = "y" ]; then
                printf "%s\n" "$PROFILE_ADGUARD_METRICS_TARGETS"
                printf "%s\n" "$PROFILE_ADGUARD_METRICS_PATH"
            fi
            printf "%s\n" "$PROFILE_ADGUARD_LOKI"
            if [ "$PROFILE_ADGUARD_LOKI" = "y" ]; then
                printf "%s\n" "$PROFILE_ADGUARD_QUERYLOG_PATH"
                printf "%s\n" "$PROFILE_ADGUARD_SYSTEMD_UNIT"
            fi
        fi
    } >"$answers_file"

    if [ "${INSTALLER_DRY_RUN:-false}" = "true" ]; then
        installer_message "Dry Run" "Would execute installer with the generated preset answers."
        cat "$answers_file"
        printf "\n"
        installer_pause
        rm -f "$answers_file"
        return 0
    fi

    clear_stale_install_markers
    for exact_cfg in \
        "/etc/nginx/sites-available/${PROFILE_PUBLIC_DOMAIN}" \
        "/etc/nginx/sites-available/${PROFILE_PUBLIC_DOMAIN}.conf"; do
        if [ -f "$exact_cfg" ]; then
            selected_cfg="$exact_cfg"
            break
        fi
    done

    if [ -z "$selected_cfg" ] && [ -n "${SELECTED_CFG:-}" ]; then
        selected_cfg="${SELECTED_CFG}"
    fi
    cat "$answers_file" | sudo env -u INSTALLER_AUTOMATION_STEPS \
        SELECTED_CFG="${selected_cfg}" \
        INSTALLER_EXISTING_ACTION="reinstall" \
        bash "${REPO_ROOT}/install.sh"
    rm -f "$answers_file"
}

run_update_mode() {
    local update_choice="$1"
    if [ "${INSTALLER_DRY_RUN:-false}" = "true" ]; then
        installer_message "Dry Run" "Would run update.sh with UPDATE_CHOICE=${update_choice} in non-interactive mode."
        installer_pause
        return 0
    fi
    NONINTERACTIVE=true UPDATE_CHOICE="$update_choice" bash "${REPO_ROOT}/update.sh"
}

run_remove_mode() {
    local mode="$1"
    if [ "${INSTALLER_DRY_RUN:-false}" = "true" ]; then
        installer_message "Dry Run" "Would run remove.sh with REMOVE_MODE=${mode}."
        installer_pause
        return 0
    fi
    REMOVE_MODE="$mode" REMOVE_FORCE=true bash "${INSTALLER_DIR}/remove.sh"
}

run_simple_install_over_existing() {
    clear_stale_install_markers
    if [ -f /opt/sub-manager/.sub_manager_install.log ] || [ -f /opt/sub-manager_install.log ] || [ -f /opt/.sub_manager_install.log ]; then
        installer_message "Simple Install Over Existing" "Existing installation detected. Running repair/update path."
        sleep 1
        run_update_mode "1"
        return 0
    fi

    collect_common_settings || return 0
    local monitoring_choice
    monitoring_choice="$(installer_prompt_yes_no "Monitoring" "Install Prometheus + Grafana with this deployment?" "y")"
    case "$monitoring_choice" in
        __QUIT__|__BACK__) return 0 ;;
    esac
    collect_monitoring_settings "$monitoring_choice" "n" "n" "false" || return 0
    show_install_summary "Simple Install Over Existing" "Deploying Sub-Manager over the current server state."
    if [ -z "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        local confirm
        confirm="$(installer_prompt_yes_no "Confirm" "Proceed with this install profile?" "y")"
        [ "$confirm" = "y" ] || return 0
    fi
    run_install_with_answers
}

run_sub_preset() {
    local profile="$1"
    collect_common_settings || return 0
    case "$profile" in
        only)
            collect_monitoring_settings "n" "n" "n" "false" || return 0
            ;;
        monitoring)
            collect_monitoring_settings "y" "n" "n" "false" || return 0
            ;;
        logs)
            collect_monitoring_settings "y" "y" "n" "false" || return 0
            ;;
        adguard)
            collect_monitoring_settings "y" "y" "y" "false" || return 0
            ;;
        custom)
            local monitoring_choice
            monitoring_choice="$(installer_prompt_yes_no "Monitoring" "Install Prometheus + Grafana?" "y")"
            case "$monitoring_choice" in
                __QUIT__|__BACK__) return 0 ;;
            esac
            if [ "$monitoring_choice" = "y" ]; then
                collect_monitoring_settings "y" "n" "n" "true" || return 0
            else
                collect_monitoring_settings "n" "n" "n" "false" || return 0
            fi
            ;;
    esac
    show_install_summary "Install Sub-Manager" "Preset: ${profile}"
    if [ -z "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        local confirm
        confirm="$(installer_prompt_yes_no "Confirm" "Proceed with this install profile?" "y")"
        [ "$confirm" = "y" ] || return 0
    fi
    run_install_with_answers
}

run_xui_preset() {
    local profile="$1"
    local xui_existing="false"
    if command -v x-ui >/dev/null 2>&1; then
        xui_existing="true"
    elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^x-ui\.service'; then
        xui_existing="true"
    fi
    if [ "$xui_existing" = "true" ]; then
        local reinstall_choice
        reinstall_choice="$(installer_prompt_yes_no "3x-ui Detected" "3x-ui already exists. Reinstall it before Sub-Manager?" "n")"
        case "$reinstall_choice" in
            __QUIT__|__BACK__) return 0 ;;
            y)
                run_internal_xui_install
                ;;
        esac
    else
        local install_choice
        install_choice="$(installer_prompt_yes_no "Install 3x-ui" "Run the 3x-ui compatibility installer before Sub-Manager?" "y")"
        case "$install_choice" in
            __QUIT__|__BACK__) return 0 ;;
            y)
                run_internal_xui_install
                ;;
            n) return 0 ;;
        esac
    fi
    if [ ! -d /opt/sub-manager ]; then
        sudo rm -f /opt/.sub_manager_install.log /opt/sub_manager_install.log /opt/sub-manager/.sub_manager_install.log
        sudo rm -f /etc/systemd/system/sub-manager.service /lib/systemd/system/sub-manager.service
        sudo systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    run_sub_preset "$profile"
    repair_xui_nginx_integration
}
