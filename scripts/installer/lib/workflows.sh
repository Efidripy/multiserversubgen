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

sanitize_domain_host() {
    local value="${1:-}"
    value="${value//$'\r'/}"
    value="$(printf "%s" "$value" | awk 'NF {last=$0} END {print last}')"
    value="$(printf "%s" "$value" | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g')"
    value="$(printf "%s" "$value" | sed -E 's/^[[:space:]]*[[]?[0-9;]*m?Default:[[:space:]]*//; s/^[[:space:]]*Default:[[:space:]]*//; s/^[[:space:]]*>[[:space:]]*//; s/[[:space:]]+$//')"
    value="${value#http://}"
    value="${value#https://}"
    value="${value%%/*}"
    value="${value%/}"
    value="$(printf "%s" "$value" | tr -cd '[:alnum:].-')"
    printf "%s" "$value"
}

sanitize_service_name() {
    local value="${1:-}"
    value="${value//$'\r'/}"
    value="$(printf "%s" "$value" | awk 'NF {last=$0} END {print last}')"
    value="$(printf "%s" "$value" | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g')"
    value="$(printf "%s" "$value" | sed -E 's/^[[:space:]]*[[]?[0-9;]*m?Default:[[:space:]]*//; s/^[[:space:]]*Default:[[:space:]]*//; s/^[[:space:]]*>[[:space:]]*//; s/[[:space:]]+$//')"
    value="$(printf "%s" "$value" | tr -cd '[:alnum:]_.-')"
    if [ -z "$value" ]; then
        value="sub-manager"
    fi
    printf "%s" "$value"
}

sanitize_path_token() {
    local value="${1:-}"
    value="$(printf "%s" "$value" | tr -cd '[:alnum:]')"
    if [ -z "$value" ]; then
        value="$(generate_random_path)"
    fi
    printf "%s" "$value"
}

declare -ga REPORT_MODULES=()
declare -ga REPORT_SYSTEMD_UNITS=()
declare -ga REPORT_NOTES=()
declare -gA REPORT_META=()
declare -gA REPORT_DOMAINS=()
declare -gA REPORT_FILES=()
declare -gA REPORT_SERVICE_FIELDS=()
declare -gA REPORT_CREDENTIALS=()

report_default_json_path() {
    if [ -d /root ] || [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
        printf "%s" "/root/.multiserversubgen-install-report.json"
    else
        printf "%s" "/tmp/.multiserversubgen-install-report.json"
    fi
}

report_default_env_path() {
    if [ -d /root ] || [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
        printf "%s" "/root/.multiserversubgen-install-report.env"
    else
        printf "%s" "/tmp/.multiserversubgen-install-report.env"
    fi
}

report_init() {
    REPORT_MODULES=()
    REPORT_SYSTEMD_UNITS=()
    REPORT_NOTES=()
    REPORT_META=()
    REPORT_DOMAINS=()
    REPORT_FILES=()
    REPORT_SERVICE_FIELDS=()
    REPORT_CREDENTIALS=()

    REPORT_META[created_at]="$(date -Iseconds 2>/dev/null || date)"
    REPORT_META[report_enabled]="true"
    REPORT_META[status]="in_progress"
    REPORT_META[project_name]="multiserversubgen"
    REPORT_META[report_json_path]="$(report_default_json_path)"
    REPORT_META[report_env_path]="$(report_default_env_path)"

    REPORT_FILES[install_report_json]="${REPORT_META[report_json_path]}"
    REPORT_FILES[install_report_env]="${REPORT_META[report_env_path]}"
}

report_is_active() {
    [ "${REPORT_META[report_enabled]:-false}" = "true" ]
}

report_set_meta() {
    local key="$1"
    local value="${2:-}"
    REPORT_META["$key"]="$value"
}

report_add_module() {
    local module_name="${1:-}"
    [ -n "$module_name" ] || return 0
    local existing
    for existing in "${REPORT_MODULES[@]}"; do
        [ "$existing" = "$module_name" ] && return 0
    done
    REPORT_MODULES+=("$module_name")
}

report_set_domain() {
    local key="$1"
    local value="${2:-}"
    REPORT_DOMAINS["$key"]="$value"
}

report_set_service_field() {
    local service="$1"
    local key="$2"
    local value="${3:-}"
    REPORT_SERVICE_FIELDS["${service}.${key}"]="$value"
}

report_set_credential() {
    local service="$1"
    local key="$2"
    local value="${3:-}"
    REPORT_CREDENTIALS["${service}.${key}"]="$value"
}

report_add_file() {
    local label="$1"
    local path="${2:-}"
    REPORT_FILES["$label"]="$path"
}

report_add_systemd_unit() {
    local unit_name="${1:-}"
    [ -n "$unit_name" ] || return 0
    local existing
    for existing in "${REPORT_SYSTEMD_UNITS[@]}"; do
        [ "$existing" = "$unit_name" ] && return 0
    done
    REPORT_SYSTEMD_UNITS+=("$unit_name")
}

report_add_note() {
    local note="${1:-}"
    [ -n "$note" ] || return 0
    REPORT_NOTES+=("$note")
}

report_mark_success() {
    REPORT_META[status]="success"
}

report_mark_failure() {
    REPORT_META[status]="failed"
}

report_emit_lines() {
    local item
    for item in "${!REPORT_META[@]}"; do
        printf "meta\t%s\t%s\n" "$item" "${REPORT_META[$item]}"
    done
    for item in "${!REPORT_DOMAINS[@]}"; do
        printf "domain\t%s\t%s\n" "$item" "${REPORT_DOMAINS[$item]}"
    done
    for item in "${REPORT_MODULES[@]}"; do
        printf "module\t_\t%s\n" "$item"
    done
    for item in "${!REPORT_SERVICE_FIELDS[@]}"; do
        printf "service\t%s\t%s\n" "$item" "${REPORT_SERVICE_FIELDS[$item]}"
    done
    for item in "${!REPORT_CREDENTIALS[@]}"; do
        printf "credential\t%s\t%s\n" "$item" "${REPORT_CREDENTIALS[$item]}"
    done
    for item in "${!REPORT_FILES[@]}"; do
        printf "file\t%s\t%s\n" "$item" "${REPORT_FILES[$item]}"
    done
    for item in "${REPORT_SYSTEMD_UNITS[@]}"; do
        printf "systemd\t_\t%s\n" "$item"
    done
    for item in "${REPORT_NOTES[@]}"; do
        printf "note\t_\t%s\n" "$item"
    done
}

report_finalize_json() {
    local report_path="${REPORT_META[report_json_path]:-$(report_default_json_path)}"
    local lines_path
    mkdir -p "$(dirname "$report_path")" 2>/dev/null || true
    lines_path="$(mktemp)"
    report_emit_lines > "$lines_path"
    python3 - "$report_path" "$lines_path" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
lines_path = Path(sys.argv[2])
data = {
    "meta": {},
    "domains": {},
    "modules": [],
    "services": {},
    "credentials": {},
    "files": {},
    "systemd_units": [],
    "notes": [],
}

for raw in lines_path.read_text(encoding="utf-8").splitlines():
    raw = raw.rstrip("\n")
    if not raw:
        continue
    parts = raw.split("\t", 2)
    if len(parts) != 3:
        continue
    section, key, value = parts
    if section == "meta":
        data["meta"][key] = value
    elif section == "domain":
        data["domains"][key] = value
    elif section == "module":
        data["modules"].append(value)
    elif section == "service":
        service, field = key.split(".", 1)
        data["services"].setdefault(service, {})[field] = value
    elif section == "credential":
        service, field = key.split(".", 1)
        data["credentials"].setdefault(service, {})[field] = value
    elif section == "file":
        data["files"][key] = value
    elif section == "systemd":
        data["systemd_units"].append(value)
    elif section == "note":
        data["notes"].append(value)

report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    rm -f "$lines_path"
    chmod 600 "$report_path" 2>/dev/null || true
}

report_finalize_env() {
    local env_path="${REPORT_META[report_env_path]:-$(report_default_env_path)}"
    mkdir -p "$(dirname "$env_path")" 2>/dev/null || true
    {
        printf "REPORT_CREATED_AT=%q\n" "${REPORT_META[created_at]:-}"
        printf "REPORT_STATUS=%q\n" "${REPORT_META[status]:-}"
        printf "INSTALL_MODE=%q\n" "${REPORT_META[install_mode]:-}"
        printf "PRESET_ID=%q\n" "${REPORT_META[preset_id]:-}"
        printf "PRESET_LABEL=%q\n" "${REPORT_META[preset_label]:-}"
        printf "PUBLIC_DOMAIN=%q\n" "${REPORT_DOMAINS[public_domain]:-}"
        printf "PUBLIC_SCHEME=%q\n" "${REPORT_DOMAINS[public_scheme]:-}"
        printf "WEB_PATH=%q\n" "${REPORT_DOMAINS[web_path]:-}"
        printf "XUI_DOMAIN=%q\n" "${REPORT_DOMAINS[xui_domain]:-}"
        printf "XUI_REALITY_DOMAIN=%q\n" "${REPORT_DOMAINS[xui_reality_domain]:-}"
        printf "PANEL_HOST_DOMAIN=%q\n" "${REPORT_DOMAINS[panel_host_domain]:-}"
        printf "SUB_MANAGER_URL=%q\n" "${REPORT_SERVICE_FIELDS[sub_manager.url]:-}"
        printf "XUI_URL=%q\n" "${REPORT_SERVICE_FIELDS[xui.url]:-}"
        printf "GRAFANA_URL=%q\n" "${REPORT_SERVICE_FIELDS[grafana.url]:-}"
        printf "XUI_USERNAME=%q\n" "${REPORT_CREDENTIALS[xui.username]:-}"
        printf "XUI_PASSWORD=%q\n" "${REPORT_CREDENTIALS[xui.password]:-}"
        printf "GRAFANA_USERNAME=%q\n" "${REPORT_CREDENTIALS[grafana.username]:-}"
        printf "GRAFANA_PASSWORD=%q\n" "${REPORT_CREDENTIALS[grafana.password]:-}"
        printf "ADGUARD_USERNAME=%q\n" "${REPORT_CREDENTIALS[adguard.username]:-}"
        printf "ADGUARD_PASSWORD=%q\n" "${REPORT_CREDENTIALS[adguard.password]:-}"
    } > "$env_path"
    chmod 600 "$env_path" 2>/dev/null || true
}

report_finalize_outputs() {
    report_finalize_json
    report_finalize_env
}

report_print_summary() {
    installer_message "Installation Summary" "Important final data from this run."
    printf "${UI_GREEN}Mode:${UI_RESET} %s\n" "${REPORT_META[install_mode]:-unknown}"
    printf "${UI_GREEN}Preset:${UI_RESET} %s\n" "${REPORT_META[preset_label]:-${REPORT_META[preset_id]:-unknown}}"
    if [ ${#REPORT_MODULES[@]} -gt 0 ]; then
        printf "${UI_GREEN}Modules:${UI_RESET} %s\n" "$(IFS=', '; printf "%s" "${REPORT_MODULES[*]}")"
    fi
    printf "${UI_GREEN}Panel URL:${UI_RESET} %s\n" "${REPORT_SERVICE_FIELDS[sub_manager.url]:-unknown}"
    if [ -n "${REPORT_SERVICE_FIELDS[xui.url]:-}" ]; then
        printf "${UI_GREEN}3x-ui URL:${UI_RESET} %s\n" "${REPORT_SERVICE_FIELDS[xui.url]}"
        printf "${UI_GREEN}3x-ui Login:${UI_RESET} %s\n" "${REPORT_CREDENTIALS[xui.username]:-unknown}"
        printf "${UI_GREEN}3x-ui Password:${UI_RESET} %s\n" "${REPORT_CREDENTIALS[xui.password]:-unknown}"
    fi
    if [ -n "${REPORT_SERVICE_FIELDS[grafana.url]:-}" ]; then
        printf "${UI_GREEN}Grafana URL:${UI_RESET} %s\n" "${REPORT_SERVICE_FIELDS[grafana.url]}"
        [ -n "${REPORT_CREDENTIALS[grafana.username]:-}" ] && printf "${UI_GREEN}Grafana Login:${UI_RESET} %s\n" "${REPORT_CREDENTIALS[grafana.username]}"
        [ -n "${REPORT_CREDENTIALS[grafana.password]:-}" ] && printf "${UI_GREEN}Grafana Password:${UI_RESET} %s\n" "${REPORT_CREDENTIALS[grafana.password]}"
    fi
    printf "${UI_GREEN}JSON Report:${UI_RESET} %s\n" "${REPORT_META[report_json_path]:-unknown}"
    printf "${UI_GREEN}ENV Report:${UI_RESET} %s\n" "${REPORT_META[report_env_path]:-unknown}"
    printf "\n${UI_YELLOW}Save these credentials and report files before leaving this host.${UI_RESET}\n\n"
}

report_capture_install_log() {
    local log_file="/opt/.sub_manager_install.log"
    local monitoring_enabled="false"
    local adguard_enabled="false"
    [ -f "$log_file" ] || return 0

    local key value
    while IFS='=' read -r key value; do
        case "$key" in
            PROJECT_NAME)
                report_set_meta project_service_name "$value"
                report_add_systemd_unit "${value}.service"
                report_add_file project_dir "/opt/${value}"
                ;;
            PROJECT_DIR)
                report_add_file project_dir "$value"
                ;;
            SELECTED_CFG)
                report_add_file nginx_site "$value"
                ;;
            PUBLIC_DOMAIN)
                report_set_domain public_domain "$value"
                report_set_domain panel_host_domain "$value"
                ;;
            PUBLIC_SCHEME)
                report_set_domain public_scheme "$value"
                ;;
            WEB_PATH)
                report_set_domain web_path "$value"
                ;;
            GRAFANA_WEB_PATH)
                [ "$monitoring_enabled" = "true" ] && report_set_domain grafana_web_path "$value"
                ;;
            MONITORING_ENABLED)
                if [ "$value" = "true" ]; then
                    monitoring_enabled="true"
                    report_set_service_field grafana enabled "true"
                    report_set_service_field prometheus enabled "true"
                else
                    monitoring_enabled="false"
                fi
                ;;
            ADGUARD_METRICS_ENABLED)
                if [ "$value" = "true" ]; then
                    adguard_enabled="true"
                    report_set_service_field adguard enabled "true"
                else
                    adguard_enabled="false"
                fi
                ;;
            ADGUARD_QUERYLOG_PATH)
                [ "$adguard_enabled" = "true" ] && [ -n "$value" ] && report_add_file adguard_querylog "$value"
                ;;
            ADGUARD_SYSTEMD_UNIT)
                [ "$adguard_enabled" = "true" ] && [ -n "$value" ] && report_add_systemd_unit "$value"
                ;;
        esac
    done < "$log_file"

    local scheme="${REPORT_DOMAINS[public_scheme]:-https}"
    local domain="${REPORT_DOMAINS[public_domain]:-}"
    local web_path="${REPORT_DOMAINS[web_path]:-}"
    local grafana_path="${REPORT_DOMAINS[grafana_web_path]:-}"

    if [ -n "$domain" ] && [ -n "$web_path" ]; then
        report_set_service_field sub_manager enabled "true"
        report_set_service_field sub_manager url "${scheme}://${domain}/${web_path}/"
        report_set_service_field sub_manager path "/${web_path}/"
    fi
    if [ -n "$domain" ] && [ -n "$grafana_path" ] && [ "${REPORT_SERVICE_FIELDS[grafana.enabled]:-false}" = "true" ]; then
        report_set_service_field grafana url "${scheme}://${domain}/${grafana_path}/"
        report_set_service_field grafana path "/${grafana_path}/"
    fi

    report_add_file install_log "$log_file"
    report_add_file nginx_snippet "/etc/nginx/snippets/${REPORT_META[project_service_name]:-${PROFILE_PROJECT_NAME:-sub-manager}}.conf"
    report_add_systemd_unit "nginx.service"
}

report_capture_xui_runtime() {
    local xui_db="/etc/x-ui/x-ui.db"

    if [ -z "${PROFILE_XUI_PANEL_PATH:-}" ] && [ -f "$xui_db" ] && command -v sqlite3 >/dev/null 2>&1; then
        PROFILE_XUI_PANEL_PATH="$(sudo sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='webBasePath' LIMIT 1;" 2>/dev/null | tr -d '\r' | tr -d '/' || true)"
    fi
    if [ -z "${PROFILE_XUI_PANEL_PORT:-}" ] && [ -f "$xui_db" ] && command -v sqlite3 >/dev/null 2>&1; then
        PROFILE_XUI_PANEL_PORT="$(sudo sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='webPort' LIMIT 1;" 2>/dev/null | tr -d '\r' || true)"
    fi
    if [ -z "${PROFILE_XUI_USERNAME:-}" ] && [ -f "$xui_db" ] && command -v sqlite3 >/dev/null 2>&1; then
        PROFILE_XUI_USERNAME="$(sudo sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='username' LIMIT 1;" 2>/dev/null | tr -d '\r' || true)"
    fi

    if [ -z "${PROFILE_XUI_USERNAME:-}" ] && [ -n "${PROFILE_XUI_GENERATED_USERNAME:-}" ]; then
        PROFILE_XUI_USERNAME="${PROFILE_XUI_GENERATED_USERNAME}"
    fi
    if [ -z "${PROFILE_XUI_PASSWORD:-}" ] && [ -n "${PROFILE_XUI_GENERATED_PASSWORD:-}" ]; then
        PROFILE_XUI_PASSWORD="${PROFILE_XUI_GENERATED_PASSWORD}"
    fi

    if [ -z "${PROFILE_XUI_PANEL_URL:-}" ] && [ -n "${PROFILE_XUI_DOMAIN:-}" ] && [ -n "${PROFILE_XUI_PANEL_PATH:-}" ]; then
        PROFILE_XUI_PANEL_URL="${PROFILE_PUBLIC_SCHEME:-https}://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_PANEL_PATH}/"
    fi

    local has_xui_context="false"
    if [ -n "${PROFILE_XUI_DOMAIN:-}" ] || \
       [ -n "${PROFILE_XUI_REALITY_DOMAIN:-}" ] || \
       [ -n "${PROFILE_XUI_PANEL_URL:-}" ] || \
       [ -n "${PROFILE_XUI_PANEL_PATH:-}" ] || \
       [ -n "${PROFILE_XUI_PANEL_PORT:-}" ] || \
       [ -n "${PROFILE_XUI_STATUS:-}" ] || \
       [ -n "${PROFILE_XUI_WEBSUB_URL:-}" ] || \
       [ -n "${PROFILE_XUI_SUB2SING_URL:-}" ] || \
       [ -n "${PROFILE_XUI_USERNAME:-}" ] || \
       [ -n "${PROFILE_XUI_PASSWORD:-}" ]; then
        has_xui_context="true"
    fi
    [ "$has_xui_context" = "true" ] || return 0

    [ -n "${PROFILE_XUI_DOMAIN:-}" ] && report_set_domain xui_domain "${PROFILE_XUI_DOMAIN}"
    [ -n "${PROFILE_XUI_REALITY_DOMAIN:-}" ] && report_set_domain xui_reality_domain "${PROFILE_XUI_REALITY_DOMAIN}"
    [ -n "${PROFILE_XUI_PANEL_URL:-}" ] && report_set_service_field xui url "${PROFILE_XUI_PANEL_URL}"
    [ -n "${PROFILE_XUI_PANEL_PATH:-}" ] && report_set_service_field xui path "/${PROFILE_XUI_PANEL_PATH}/"
    [ -n "${PROFILE_XUI_PANEL_PORT:-}" ] && report_set_service_field xui port "${PROFILE_XUI_PANEL_PORT}"
    [ -n "${PROFILE_XUI_STATUS:-}" ] && report_set_service_field xui status_hint "${PROFILE_XUI_STATUS}"
    [ -n "${PROFILE_XUI_WEBSUB_URL:-}" ] && report_set_service_field xui websub_url "${PROFILE_XUI_WEBSUB_URL}"
    [ -n "${PROFILE_XUI_SUB2SING_URL:-}" ] && report_set_service_field xui sub2sing_url "${PROFILE_XUI_SUB2SING_URL}"
    [ -n "${PROFILE_XUI_SUB2SING_STATUS:-}" ] && report_set_service_field xui sub2sing_status "${PROFILE_XUI_SUB2SING_STATUS}"
    [ -n "${PROFILE_XUI_USERNAME:-}" ] && report_set_credential xui username "${PROFILE_XUI_USERNAME}"
    [ -n "${PROFILE_XUI_PASSWORD:-}" ] && report_set_credential xui password "${PROFILE_XUI_PASSWORD}"
    report_set_service_field xui enabled "true"
    report_add_systemd_unit "x-ui.service"
    report_add_file xui_binary_dir "/usr/local/x-ui"
    report_add_file xui_db "/etc/x-ui/x-ui.db"
}

report_prepare_standard_profile() {
    report_init
    report_set_meta install_mode "legacy"
    report_set_meta preset_id "1"
    report_set_meta preset_label "1 Standard Install"
    report_add_module "core.nginx"
    report_add_module "core.tls"
    report_add_module "svc.sub-manager"
    [ "${PROFILE_MONITORING:-n}" = "y" ] && report_add_module "obs.metrics"
    [ "${PROFILE_MONITORING:-n}" = "y" ] && report_add_module "obs.grafana"
    [ "${PROFILE_ADGUARD_LOKI:-n}" = "y" ] && report_add_module "obs.logs"
    [ "${PROFILE_ADGUARD_METRICS:-n}" = "y" ] && report_add_module "obs.adguard"
    report_set_domain public_domain "${PROFILE_PUBLIC_DOMAIN:-}"
    report_set_domain public_scheme "${PROFILE_PUBLIC_SCHEME:-}"
}

report_prepare_sub_preset() {
    local profile="$1"
    report_init
    report_set_meta install_mode "advanced"
    case "$profile" in
        only) report_set_meta preset_id "2.1"; report_set_meta preset_label "2.1 Sub-Manager only" ;;
        monitoring) report_set_meta preset_id "2.2"; report_set_meta preset_label "2.2 Sub-Manager + Prometheus + Grafana" ;;
        logs) report_set_meta preset_id "2.3"; report_set_meta preset_label "2.3 Sub-Manager + Prometheus + Grafana + Loki + promtail" ;;
        adguard) report_set_meta preset_id "2.4"; report_set_meta preset_label "2.4 Sub-Manager + Monitoring + AdGuard" ;;
        custom) report_set_meta preset_id "2.5"; report_set_meta preset_label "2.5 Sub-Manager + Custom Extras" ;;
    esac
    report_add_module "core.nginx"
    report_add_module "core.tls"
    report_add_module "svc.sub-manager"
    report_set_domain public_domain "${PROFILE_PUBLIC_DOMAIN:-}"
    report_set_domain public_scheme "${PROFILE_PUBLIC_SCHEME:-}"
}

report_prepare_xui_preset() {
    local profile="$1"
    report_init
    report_set_meta install_mode "advanced"
    case "$profile" in
        only) report_set_meta preset_id "3.1"; report_set_meta preset_label "3.1 3x-ui + Sub-Manager only" ;;
        monitoring) report_set_meta preset_id "3.2"; report_set_meta preset_label "3.2 3x-ui + Sub-Manager + Prometheus + Grafana" ;;
        logs) report_set_meta preset_id "3.3"; report_set_meta preset_label "3.3 3x-ui + Sub-Manager + Prometheus + Grafana + Loki + promtail" ;;
        adguard) report_set_meta preset_id "3.4"; report_set_meta preset_label "3.4 3x-ui + Sub-Manager + Monitoring + AdGuard" ;;
        custom) report_set_meta preset_id "3.5"; report_set_meta preset_label "3.5 3x-ui + Sub-Manager + Custom Extras" ;;
    esac
    report_add_module "core.nginx"
    report_add_module "core.tls"
    report_add_module "svc.3xui"
    report_add_module "svc.sub-manager"
    report_set_domain public_domain "${PROFILE_PUBLIC_DOMAIN:-}"
    report_set_domain public_scheme "${PROFILE_PUBLIC_SCHEME:-}"
}

report_apply_profile_modules() {
    local profile="$1"
    case "$profile" in
        monitoring)
            report_add_module "obs.metrics"
            report_add_module "obs.grafana"
            ;;
        logs)
            report_add_module "obs.metrics"
            report_add_module "obs.grafana"
            report_add_module "obs.logs"
            ;;
        adguard)
            report_add_module "obs.metrics"
            report_add_module "obs.grafana"
            report_add_module "obs.logs"
            report_add_module "obs.adguard"
            ;;
        custom)
            [ "${PROFILE_MONITORING:-n}" = "y" ] && report_add_module "obs.metrics"
            [ "${PROFILE_MONITORING:-n}" = "y" ] && report_add_module "obs.grafana"
            [ "${PROFILE_ADGUARD_LOKI:-n}" = "y" ] && report_add_module "obs.logs"
            [ "${PROFILE_ADGUARD_METRICS:-n}" = "y" ] && report_add_module "obs.adguard"
            ;;
    esac
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

cleanup_malformed_nginx_site_entries() {
    local dir entry base_pair
    local -a bad_bases=()

    for dir in /etc/nginx/sites-available /etc/nginx/sites-enabled; do
        [ -d "$dir" ] || continue
        while IFS= read -r -d '' entry; do
            base_pair="$(basename "$entry")"
            case "$base_pair" in
                *Default:*|*\>*|*" "*)
                    bad_bases+=("$base_pair")
                    ;;
            esac
        done < <(sudo find "$dir" -maxdepth 1 -mindepth 1 -print0 2>/dev/null)
    done

    [ ${#bad_bases[@]} -gt 0 ] || return 0

    local base
    for base in "${bad_bases[@]}"; do
        sudo rm -f "/etc/nginx/sites-available/${base}" "/etc/nginx/sites-enabled/${base}" 2>/dev/null || true
    done

    report_add_note "Removed malformed nginx site entries containing invalid UI residue (Default:/spaces/>)."
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
    local status=0

    if [ "${INSTALLER_DRY_RUN:-false}" = "true" ]; then
        installer_message "Dry Run" "Would install 3x-ui using the internal core for ${xui_domain} and ${xui_reality_domain}."
        installer_pause
        return 0
    fi

    xui_tag="$(xui_pick_release_tag)"
    installer_message "Installing 3x-ui" "Running internal x-ui core for ${xui_domain} and ${xui_reality_domain}..."
    xui_install_binary "$xui_tag" || status=$?
    if [ "$status" -eq 0 ]; then
        xui_generate_seed_context "$xui_domain" "$xui_reality_domain"
        xui_install_sub2sing_box || status=$?
        if [ "$status" -eq 0 ]; then xui_render_sub_templates || status=$?; fi
        if [ "$status" -eq 0 ]; then xui_configure_nginx_and_tls "$xui_domain" "$xui_reality_domain" || status=$?; fi
        if [ "$status" -eq 0 ]; then xui_configure_panel "$xui_domain" "${PROFILE_XUI_CERT_PATH:-}" "${PROFILE_XUI_CERT_KEY_PATH:-}" || status=$?; fi
        if [ "$status" -eq 0 ]; then xui_seed_base_inbounds "$xui_domain" "$xui_reality_domain" || status=$?; fi
        if [ "$status" -eq 0 ]; then xui_collect_summary || status=$?; fi
        if [ "$status" -eq 0 ]; then xui_print_runtime_summary || status=$?; fi
    fi

    if [ "$status" -ne 0 ]; then
        return "$status"
    fi

    PROFILE_XUI_DOMAIN="${xui_domain}"
    PROFILE_XUI_REALITY_DOMAIN="${xui_reality_domain}"
    return 0
}

collect_common_settings() {
    local default_domain
    default_domain="$(hostname -f 2>/dev/null || hostname)"

    PROFILE_PROJECT_NAME="$(sanitize_service_name "$(installer_prompt_text "Project Name" "Service name for this install." "sub-manager")")"
    PROFILE_APP_PORT="$(installer_prompt_text "Application Port" "Local port for Sub-Manager." "666")"
    PROFILE_PUBLIC_DOMAIN="$(sanitize_domain_host "$(installer_prompt_text "Public Domain" "Public hostname without http/https." "${default_domain}")")"

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

collect_xui_common_settings() {
    local default_domain
    local xui_domain
    local xui_reality_domain

    default_domain="$(hostname -f 2>/dev/null || hostname)"

    PROFILE_PROJECT_NAME="$(sanitize_service_name "$(installer_prompt_text "Project Name" "Service name for this install." "sub-manager")")"
    PROFILE_APP_PORT="$(installer_prompt_text "Application Port" "Local port for Sub-Manager." "666")"

    while true; do
        xui_domain="$(sanitize_domain_host "$(installer_prompt_text "3x-ui Main Domain" "Enter MAIN domain manually (required)." "")")"
        xui_reality_domain="$(sanitize_domain_host "$(installer_prompt_text "3x-ui Reality Domain" "Enter SECOND domain manually (required)." "")")"

        if [ -z "$xui_domain" ] || [ -z "$xui_reality_domain" ]; then
            installer_message "Invalid Domains" "Both domains must be entered manually and cannot be empty."
            installer_pause
            continue
        fi
        if [ "$xui_domain" = "$xui_reality_domain" ]; then
            installer_message "Duplicate Domains" "The two 3x-ui domains must be different."
            installer_pause
            continue
        fi
        break
    done

    PROFILE_XUI_DOMAIN="$xui_domain"
    PROFILE_XUI_REALITY_DOMAIN="$xui_reality_domain"
    PROFILE_PUBLIC_DOMAIN="$PROFILE_XUI_DOMAIN"

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
    if [ -n "${PROFILE_XUI_DOMAIN:-}" ] || [ -n "${PROFILE_XUI_REALITY_DOMAIN:-}" ]; then
        printf "${UI_GREEN}3x-ui Main Domain:${UI_RESET} %s\n" "${PROFILE_XUI_DOMAIN:-n/a}"
        printf "${UI_GREEN}3x-ui Reality Domain:${UI_RESET} %s\n" "${PROFILE_XUI_REALITY_DOMAIN:-n/a}"
        printf "${UI_GREEN}Panel Host Domain:${UI_RESET} %s\n" "${PROFILE_PUBLIC_DOMAIN:-n/a}"
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
    printf "${UI_GREEN}Final Report:${UI_RESET} %s\n" "${REPORT_META[report_json_path]:-$(report_default_json_path)}"
    printf "\n"
}

run_install_with_answers() {
    local answers_file
    local selected_cfg=""
    local exact_cfg=""
    local status=0
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
    cleanup_malformed_nginx_site_entries
    for exact_cfg in \
        "/etc/nginx/sites-available/${PROFILE_PUBLIC_DOMAIN}" \
        "/etc/nginx/sites-available/${PROFILE_PUBLIC_DOMAIN}.conf"; do
        if [ -f "$exact_cfg" ]; then
            selected_cfg="$exact_cfg"
            break
        fi
    done

    local heartbeat_pid=""
    local start_ts now_ts elapsed

    start_ts="$(date +%s 2>/dev/null || printf '0')"
    (
        while true; do
            sleep 20 || break
            now_ts="$(date +%s 2>/dev/null || printf '0')"
            elapsed=$((now_ts - start_ts))
            printf "\n[installer] still running... %ss elapsed (build/install in progress)\n" "$elapsed" >&2
        done
    ) &
    heartbeat_pid="$!"

    set +e
    cat "$answers_file" | sudo env INSTALLER_AUTOMATION_STEPS="${INSTALLER_AUTOMATION_STEPS:-task}" \
        SELECTED_CFG="${selected_cfg}" \
        INSTALLER_EXISTING_ACTION="reinstall" \
        INSTALLER_VERBOSE_PROGRESS="1" \
        bash "${REPO_ROOT}/install.sh"
    status=$?
    set -e

    if [ -n "$heartbeat_pid" ]; then
        kill "$heartbeat_pid" >/dev/null 2>&1 || true
        wait "$heartbeat_pid" 2>/dev/null || true
    fi

    rm -f "$answers_file"
    if [ "$status" -eq 0 ]; then
        report_capture_install_log
        report_capture_xui_runtime
    fi
    return "$status"
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
        report_prepare_standard_profile
        report_add_note "Existing installation detected; standard mode switched to repair/update path."
        installer_message "Simple Install Over Existing" "Existing installation detected. Running repair/update path."
        sleep 1
        run_update_mode "1"
        local status=$?
        report_prepare_standard_profile
        report_add_note "Existing installation detected; standard mode switched to repair/update path."
        if [ "$status" -eq 0 ]; then
            report_capture_install_log
            report_capture_xui_runtime
        fi
        return "$status"
    fi

    collect_common_settings || return 0
    local monitoring_choice
    monitoring_choice="$(installer_prompt_yes_no "Monitoring" "Install Prometheus + Grafana with this deployment?" "y")"
    case "$monitoring_choice" in
        __QUIT__|__BACK__) return 0 ;;
    esac
    collect_monitoring_settings "$monitoring_choice" "n" "n" "false" || return 0
    report_prepare_standard_profile
    show_install_summary "Simple Install Over Existing" "Deploying Sub-Manager over the current server state."
    if [ -z "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        local confirm
        confirm="$(installer_prompt_yes_no "Confirm" "Proceed with this install profile?" "y")"
        [ "$confirm" = "y" ] || return 0
    fi
    run_install_with_answers
    return $?
}

run_sub_preset() {
    local profile="$1"
    if [ "${PROFILE_USE_EXISTING_COMMON_SETTINGS:-false}" = "true" ]; then
        PROFILE_USE_EXISTING_COMMON_SETTINGS="false"
    else
        collect_common_settings || return 0
    fi
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
    report_prepare_sub_preset "$profile"
    report_apply_profile_modules "$profile"
    show_install_summary "Install Sub-Manager" "Preset: ${profile}"
    if [ -z "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        local confirm
        confirm="$(installer_prompt_yes_no "Confirm" "Proceed with this install profile?" "y")"
        [ "$confirm" = "y" ] || return 0
    fi
    run_install_with_answers
    return $?
}

run_xui_preset() {
    local profile="$1"
    local xui_existing="false"
    if command -v x-ui >/dev/null 2>&1; then
        xui_existing="true"
    elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^x-ui\.service'; then
        xui_existing="true"
    fi
    collect_xui_common_settings || return 0
    report_prepare_xui_preset "$profile"
    report_apply_profile_modules "$profile"
    report_capture_xui_runtime

    if [ "$xui_existing" = "true" ]; then
        local reinstall_choice
        reinstall_choice="$(installer_prompt_yes_no "3x-ui Detected" "3x-ui already exists. Reinstall it before Sub-Manager?" "n")"
        case "$reinstall_choice" in
            __QUIT__|__BACK__) return 0 ;;
            y)
                run_internal_xui_install || return $?
                ;;
            n)
                report_add_note "3x-ui reuse mode: existing panel password is not recoverable from x-ui.db; report will include password only if generated in this run."
                ;;
        esac
    else
        local install_choice
        install_choice="$(installer_prompt_yes_no "Install 3x-ui" "Run the 3x-ui compatibility installer before Sub-Manager?" "y")"
        case "$install_choice" in
            __QUIT__|__BACK__) return 0 ;;
            y)
                run_internal_xui_install || return $?
                ;;
            n) return 0 ;;
        esac
    fi
    if [ ! -d /opt/sub-manager ]; then
        sudo rm -f /opt/.sub_manager_install.log /opt/sub_manager_install.log /opt/sub-manager/.sub_manager_install.log
        sudo rm -f /etc/systemd/system/sub-manager.service /lib/systemd/system/sub-manager.service
        sudo systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    PROFILE_USE_EXISTING_COMMON_SETTINGS="true"
    run_sub_preset "$profile" || return $?
    repair_xui_nginx_integration
    report_prepare_xui_preset "$profile"
    report_apply_profile_modules "$profile"
    report_capture_install_log
    report_capture_xui_runtime
    return $?
}
