#!/bin/bash

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/locale.sh"

UI_RED=$'\033[1;31m'
UI_WHITE=$'\033[1;37m'
UI_DIM=$'\033[0;37m'
UI_CYAN=$'\033[1;36m'
UI_GREEN=$'\033[1;32m'
UI_YELLOW=$'\033[1;33m'
UI_RESET=$'\033[0m'
UI_CLEAR=$'\033[2J\033[H'

INSTALLER_AUTOMATION_STEPS="${INSTALLER_AUTOMATION_STEPS:-}"
INSTALLER_AUTOMATION_FILE="${INSTALLER_AUTOMATION_FILE:-}"
INSTALLER_AUTOMATION_VALUE=""

if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] && [ -z "${INSTALLER_AUTOMATION_FILE:-}" ]; then
    INSTALLER_AUTOMATION_FILE="$(mktemp)"
    printf "%s" "$INSTALLER_AUTOMATION_STEPS" | tr '|' '\n' >"$INSTALLER_AUTOMATION_FILE"
    export INSTALLER_AUTOMATION_FILE
fi

installer_banner() {
    cat >&2 <<'EOF'
+--------------------------------------------------------------+
|  __  __       _ _   _                                       |
| |  \/  |_   _| | |_(_)___  ___ _ ____   _____ _ __ ___      |
| | |\/| | | | | | __| / __|/ _ \ '__\ \ / / _ \ '__/ __|     |
| | |  | | |_| | | |_| \__ \  __/ |   \ V /  __/ |  \__ \     |
| |_|  |_|\__,_|_|\__|_|___/\___|_|    \_/ \___|_|  |___/     |
|                                                              |
|              Sub-Manager Installer / Update Tool             |
+--------------------------------------------------------------+
EOF
}

installer_cursor() {
    printf "%b" "${UI_WHITE}[${UI_RED}+${UI_WHITE}]${UI_RESET}" >&2
}

installer_empty_cursor() {
    printf "%b" "${UI_WHITE}[ ]${UI_RESET}" >&2
}

installer_automation_next() {
    INSTALLER_AUTOMATION_VALUE=""
    if [ -z "${INSTALLER_AUTOMATION_FILE:-}" ] || [ ! -f "${INSTALLER_AUTOMATION_FILE}" ]; then
        return 1
    fi
    if [ ! -s "${INSTALLER_AUTOMATION_FILE}" ]; then
        return 1
    fi
    INSTALLER_AUTOMATION_VALUE="$(head -n 1 "${INSTALLER_AUTOMATION_FILE}")"
    printf "%s" "$(tail -n +2 "${INSTALLER_AUTOMATION_FILE}" 2>/dev/null)" > "${INSTALLER_AUTOMATION_FILE}"
    return 0
}

installer_has_pending_automation() {
    if [ -z "${INSTALLER_AUTOMATION_FILE:-}" ] || [ ! -f "${INSTALLER_AUTOMATION_FILE}" ]; then
        return 1
    fi
    [ -s "${INSTALLER_AUTOMATION_FILE}" ]
}

installer_render_menu() {
    local title="$1"
    local subtitle="$2"
    local selected="$3"
    shift 3

    printf "%b" "${UI_CLEAR}" >&2
    installer_banner
    printf "%b\n" "\n${UI_CYAN}${title}${UI_RESET}" >&2
    if [ -n "$subtitle" ]; then
        printf "%b\n" "${UI_DIM}${subtitle}${UI_RESET}" >&2
    fi
    printf "\n" >&2

    local idx=0
    local item
    for item in "$@"; do
        printf "  " >&2
        if [ "$idx" -eq "$selected" ]; then
            installer_cursor
        else
            installer_empty_cursor
        fi
        printf " %s\n" "$item" >&2
        idx=$((idx + 1))
    done

    printf "%b\n" "\n${UI_DIM}Controls: Up/Down move   Enter select   Esc back   q quit${UI_RESET}" >&2
}

installer_use_line_menu() {
    case "${INSTALLER_UI_MODE:-line}" in
        line) return 0 ;;
        arrows) return 1 ;;
    esac

    if [ "${TERM:-}" = "dumb" ]; then
        return 0
    fi

    # Git Bash / MSYS terminals often handle raw single-key reads unreliably.
    if [ -n "${MSYSTEM:-}" ] || [ -n "${MINGW_PREFIX:-}" ] || [ -n "${CYGWIN:-}" ]; then
        return 0
    fi

    return 1
}

installer_select_menu_line_mode() {
    local title="$1"
    local subtitle="$2"
    shift 2
    local items=("$@")
    local idx=0
    local display_idx=1
    local zero_item_idx=""
    local choice

    if [ ! -t 0 ]; then
        echo "__QUIT__"
        return 0
    fi

    while true; do
        installer_message "$title" "$subtitle"
        idx=0
        display_idx=1
        zero_item_idx=""
        for item in "${items[@]}"; do
            if printf '%s' "$item" | grep -Eq '^[[:space:]]*0([.)]|[[:space:]])'; then
                zero_item_idx="$idx"
            fi
            printf "  %s) %s\n" "$display_idx" "$item" >&2
            idx=$((idx + 1))
            display_idx=$((display_idx + 1))
        done
        printf "%b" "\n${UI_DIM}Enter option number (1..${#items[@]}), 'b' for back, 'q' to quit${UI_RESET}" >&2
        if [ -n "$zero_item_idx" ]; then
            printf "%b" "${UI_DIM}; 0 for the explicit '0.*' item${UI_RESET}" >&2
        fi
        printf "%b" "${UI_DIM}:${UI_RESET} " >&2
        IFS= read -r choice

        case "$choice" in
            q|Q)
                echo "__QUIT__"
                return 0
                ;;
            b|B)
                echo "__BACK__"
                return 0
                ;;
            '')
                echo "0"
                return 0
                ;;
            *[!0-9]*)
                continue
                ;;
            *)
                if [ "$choice" -eq 0 ] && [ -n "$zero_item_idx" ]; then
                    echo "$zero_item_idx"
                    return 0
                fi
                if [ "$choice" -ge 1 ] && [ "$choice" -le "${#items[@]}" ]; then
                    echo $((choice - 1))
                    return 0
                fi
                ;;
        esac
    done
}

installer_select_menu() {
    local title="$1"
    local subtitle="$2"
    shift 2
    local items=("$@")
    local selected=0
    local zero_item_idx=""
    local idx=0
    local key

    for idx in "${!items[@]}"; do
        if printf '%s' "${items[$idx]}" | grep -Eq '^[[:space:]]*0([.)]|[[:space:]])'; then
            zero_item_idx="$idx"
            break
        fi
    done

    installer_automation_next || true
    if [ -n "${INSTALLER_AUTOMATION_VALUE:-}" ]; then
        printf "%s" "$INSTALLER_AUTOMATION_VALUE"
        return 0
    fi

    # No automation value and no terminal — cannot do interactive input; exit cleanly.
    if [ ! -t 0 ]; then
        echo "__QUIT__"
        return 0
    fi

    if installer_use_line_menu; then
        installer_select_menu_line_mode "$title" "$subtitle" "${items[@]}"
        return 0
    fi

    while true; do
        installer_render_menu "$title" "$subtitle" "$selected" "${items[@]}"
        IFS= read -rsn1 key
        case "$key" in
            q|Q)
                echo "__QUIT__"
                return 0
                ;;
            "")
                echo "$selected"
                return 0
                ;;
            $'\x1b')
                IFS= read -rsn2 -t 0.05 key || true
                case "$key" in
                    "[A")
                        selected=$((selected - 1))
                        if [ "$selected" -lt 0 ]; then
                            selected=$((${#items[@]} - 1))
                        fi
                        ;;
                    "[B")
                        selected=$((selected + 1))
                        if [ "$selected" -ge "${#items[@]}" ]; then
                            selected=0
                        fi
                        ;;
                    *)
                        echo "__BACK__"
                        return 0
                        ;;
                esac
                ;;
            [0-9])
                local numeric=$((10#$key))
                if [ "$numeric" -eq 0 ] && [ -n "$zero_item_idx" ]; then
                    echo "$zero_item_idx"
                    return 0
                fi
                if [ "$numeric" -ge 1 ] && [ "$numeric" -le "${#items[@]}" ]; then
                    echo $((numeric - 1))
                    return 0
                fi
                ;;
        esac
    done
}

installer_pause() {
    if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        return 0
    fi
    printf "%b" "\n${UI_DIM}Press any key to continue...${UI_RESET}" >&2
    IFS= read -rsn1 _
}

installer_message() {
    local title="$1"
    local body="$2"
    printf "%b" "${UI_CLEAR}" >&2
    installer_banner
    printf "%b\n" "\n${UI_CYAN}${title}${UI_RESET}" >&2
    if [ -n "$body" ]; then
        printf "%b\n" "${UI_DIM}${body}${UI_RESET}" >&2
    fi
    printf "\n" >&2
}

installer_prompt_text() {
    local title="$1"
    local prompt="$2"
    local default_value="${3:-}"
    local value=""
    installer_automation_next || true
    if [ -n "${INSTALLER_AUTOMATION_VALUE:-}" ]; then
        if [ -z "$INSTALLER_AUTOMATION_VALUE" ]; then
            INSTALLER_AUTOMATION_VALUE="$default_value"
        fi
        printf "%s" "$INSTALLER_AUTOMATION_VALUE"
        return 0
    fi

    installer_message "$title" "$prompt"
    if [ -n "$default_value" ]; then
        printf "%b\n\n" "${UI_YELLOW}Default:${UI_RESET} $default_value" >&2
    fi
    printf "> " >&2
    IFS= read -r value
    if [ -z "$value" ]; then
        value="$default_value"
    fi
    printf "%s" "$value"
}

installer_prompt_yes_no() {
    local title="$1"
    local prompt="$2"
    local default_choice="${3:-y}"
    local options
    local selected=""
    
    # Add marker (●) to default option
    if [ "$default_choice" = "y" ]; then
        options=("● Yes (default)" "No")
    else
        options=("Yes" "● No (default)")
    fi
    
    installer_automation_next || true
    if [ -n "${INSTALLER_AUTOMATION_VALUE:-}" ]; then
        printf "%s" "$INSTALLER_AUTOMATION_VALUE"
        return 0
    fi

    selected="$(installer_select_menu "$title" "$prompt" "${options[@]}")"
    case "$selected" in
        __QUIT__|__BACK__)
            printf "%s" "$selected"
            ;;
        0) printf "y" ;;
        1) printf "n" ;;
        *) printf "%s" "$default_choice" ;;
    esac
}

# Красивый отчет установки с полной информацией о доступах
print_installation_report() {
    local app_port="$1"
    local xui_path="$2"
    local xui_domain="$3"
    local scheme="$4"
    local grafana_path="${5:-}"
    local ops_dir="${MSSG_OPS_DIR:-${SCRIPT_DIR}/scripts/ops}"
    local grafana_enabled="${6:-false}"
    local adguard_path="${7:-}"
    local adguard_doh_path="${8:-}"
    local adguard_user="${9:-}"
    local adguard_pass="${10:-}"
    local adguard_enabled="${11:-false}"
    local selected_cfg="${12:-}"
    
    local sub_manager_url="${scheme}://${xui_domain}/${xui_path}/"
    local adguard_panel_url=""
    local adguard_doh_url=""
    local xui_panel_url="${PROFILE_XUI_PANEL_URL:-${XUI_PANEL_URL:-}}"
    local xui_user="${PROFILE_XUI_USERNAME:-${XUI_USERNAME:-}}"
    local xui_pass="${PROFILE_XUI_PASSWORD:-${XUI_PASSWORD:-}}"
    local xui_present="false"
    local xui_db="/etc/x-ui/x-ui.db"

    if [ -n "$adguard_path" ]; then
        adguard_panel_url="${scheme}://${xui_domain}/${adguard_path}/"
    fi
    if [ -n "$adguard_doh_path" ]; then
        adguard_doh_url="${scheme}://${xui_domain}/${adguard_doh_path}/"
    fi

    cat >&2 <<EOF

╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║        ${UI_GREEN}✅ УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!${UI_RESET}                 ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

${UI_YELLOW}┌─ ОСНОВНЫЕ ПАРАМЕТРЫ ─────────────────────────────────────┐${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}│${UI_RESET}  API Port: ${UI_CYAN}${app_port}${UI_RESET}
${UI_YELLOW}│${UI_RESET}  Protocol: ${UI_CYAN}${scheme}${UI_RESET}
${UI_YELLOW}│${UI_RESET}  Domain:   ${UI_CYAN}${xui_domain}${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}└───────────────────────────────────────────────────────────┘${UI_RESET}

${UI_GREEN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${UI_RESET}
${UI_GREEN}┃                 📋 ДОСТУПНЫЕ СЕРВИСЫ                   ┃${UI_RESET}
${UI_GREEN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${UI_RESET}

${UI_CYAN}--- Sub-Manager ---${UI_RESET}
    URL:  ${UI_GREEN}${sub_manager_url}${UI_RESET}
    Путь: /${xui_path}/
    Вход: Системные учетные данные (логин/пароль)

EOF

    if [ -n "$xui_panel_url" ] || [ -n "$xui_user" ] || [ -n "$xui_pass" ] || \
       [ -f "/etc/systemd/system/x-ui.service" ] || [ -d "/etc/x-ui" ]; then
        xui_present="true"
    fi

    # Fallback: extract 3x-ui context from runtime DB / x-ui CLI when env vars are missing
    # (common in mixed reinstall flows where install.sh is invoked without full xui context).
    if [ "$xui_present" = "true" ] && [ -f "$xui_db" ] && command -v sqlite3 >/dev/null 2>&1; then
        if [ -z "$xui_user" ]; then
            xui_user="$(sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='username' LIMIT 1;" 2>/dev/null | tr -d '\r' || true)"
        fi

        if [ -z "$xui_pass" ]; then
            xui_pass="$(sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='password' LIMIT 1;" 2>/dev/null | tr -d '\r' || true)"
        fi

        if [ -z "$xui_panel_url" ]; then
            local db_panel_path=""
            db_panel_path="$(sqlite3 "$xui_db" "SELECT value FROM settings WHERE key='webBasePath' LIMIT 1;" 2>/dev/null | tr -d '\r' | tr -d '/' || true)"
            if [ -n "$db_panel_path" ]; then
                xui_panel_url="${scheme}://${xui_domain}/${db_panel_path}/"
            fi
        fi
    fi

    if [ "$xui_present" = "true" ] && { [ -z "$xui_panel_url" ] || [ -z "$xui_user" ] || [ -z "$xui_pass" ]; }; then
        local xui_cli=""
        if [ -x "/usr/local/x-ui/x-ui" ]; then
            xui_cli="/usr/local/x-ui/x-ui"
        elif command -v x-ui >/dev/null 2>&1; then
            xui_cli="$(command -v x-ui)"
        fi

        if [ -n "$xui_cli" ]; then
            local xui_settings_raw=""
            local cli_panel_path=""
            local cli_username=""
            local cli_password=""
            xui_settings_raw="$($xui_cli setting -show true 2>/dev/null || true)"

            if [ -n "$xui_settings_raw" ]; then
                cli_panel_path="$(printf "%s\n" "$xui_settings_raw" | sed -nE "s/.*[Ww]eb[Bb]ase[Pp]ath[^a-zA-Z0-9_\/-]*([a-zA-Z0-9_\/-]+).*/\1/p" | head -n 1 | tr -d '/' )"
                cli_username="$(printf "%s\n" "$xui_settings_raw" | sed -nE "s/.*[Uu]ser[Nn]ame[^a-zA-Z0-9_\.-]*([a-zA-Z0-9_\.-]+).*/\1/p" | head -n 1)"
                cli_password="$(printf "%s\n" "$xui_settings_raw" | sed -nE "s/.*[Pp]ass[Ww]ord[^a-zA-Z0-9_\.-]*([a-zA-Z0-9_\.-]+).*/\1/p" | head -n 1)"

                if [ -z "$xui_panel_url" ] && [ -n "$cli_panel_path" ]; then
                    xui_panel_url="${scheme}://${xui_domain}/${cli_panel_path}/"
                fi
                if [ -z "$xui_user" ] && [ -n "$cli_username" ]; then
                    xui_user="$cli_username"
                fi
                if [ -z "$xui_pass" ] && [ -n "$cli_password" ]; then
                    xui_pass="$cli_password"
                fi
            fi
        fi
    fi

    if [ "$xui_present" = "true" ]; then
        cat >&2 <<EOF
${UI_CYAN}--- 3x-ui ---${UI_RESET}
    URL:  ${UI_GREEN}${xui_panel_url:-unknown}${UI_RESET}
    Вход: ${UI_CYAN}${xui_user:-unknown}${UI_RESET} / ${UI_CYAN}${xui_pass:-unknown}${UI_RESET}

EOF
    fi

    if [ "$grafana_enabled" = "true" ] && [ -n "$grafana_path" ]; then
        cat >&2 <<EOF
${UI_CYAN}--- Grafana ---${UI_RESET}
   URL:  ${UI_GREEN}${scheme}://${xui_domain}/${grafana_path}/${UI_RESET}
   Путь: /${grafana_path}/
    Вход: Grafana пользователь (admin/admin)

EOF
    fi

    if [ "$adguard_enabled" = "true" ] && [ -n "$adguard_path" ]; then
        cat >&2 <<EOF
${UI_CYAN}--- AdGuard Home ---${UI_RESET}
    Panel URL: ${UI_GREEN}${adguard_panel_url}${UI_RESET}
    DoH URL:   ${UI_GREEN}${adguard_doh_url}${UI_RESET}
   DNS Bind:  127.0.0.1:5353
   Login:     ${UI_CYAN}${adguard_user}${UI_RESET}
   Password:  stored in protected service configuration

EOF
    fi

    cat >&2 <<EOF
${UI_YELLOW}┌─ ПОЛЕЗНЫЕ КОМАНДЫ ───────────────────────────────────┐${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}│${UI_RESET}  Проверка здоровья сервиса:
${UI_YELLOW}│${UI_RESET}  ${UI_DIM}sudo bash "${ops_dir}/smoke-test.sh"${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}│${UI_RESET}  Резервная копия & восстановление:
${UI_YELLOW}│${UI_RESET}  ${UI_DIM}sudo bash "${ops_dir}/backup-restore-check.sh"${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}│${UI_RESET}  Проверка безопасности:
${UI_YELLOW}│${UI_RESET}  ${UI_DIM}sudo bash "${ops_dir}/hardening-profile.sh" audit${UI_RESET}
${UI_YELLOW}│${UI_RESET}
${UI_YELLOW}└───────────────────────────────────────────────────────┘${UI_RESET}

${UI_GREEN}✓ Все компоненты установлены и запущены${UI_RESET}
${UI_GREEN}✓ Система полностью готова к использованию${UI_RESET}

EOF
}
