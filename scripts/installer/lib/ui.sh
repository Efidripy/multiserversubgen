#!/bin/bash

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/locale.sh"

UI_RED='\033[1;31m'
UI_WHITE='\033[1;37m'
UI_DIM='\033[0;37m'
UI_CYAN='\033[1;36m'
UI_GREEN='\033[1;32m'
UI_YELLOW='\033[1;33m'
UI_RESET='\033[0m'
UI_CLEAR='\033[2J\033[H'

INSTALLER_AUTOMATION_STEPS="${INSTALLER_AUTOMATION_STEPS:-}"
INSTALLER_AUTOMATION_FILE="${INSTALLER_AUTOMATION_FILE:-}"
INSTALLER_AUTOMATION_VALUE=""

if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] && [ -z "${INSTALLER_AUTOMATION_FILE:-}" ]; then
    INSTALLER_AUTOMATION_FILE="$(mktemp)"
    printf "%s" "$INSTALLER_AUTOMATION_STEPS" | tr '|' '\n' >"$INSTALLER_AUTOMATION_FILE"
    export INSTALLER_AUTOMATION_FILE
fi

installer_banner() {
    cat <<'EOF'
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
    printf "${UI_WHITE}[${UI_RED}+${UI_WHITE}]${UI_RESET}"
}

installer_empty_cursor() {
    printf "${UI_WHITE}[ ]${UI_RESET}"
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

    printf "${UI_CLEAR}"
    installer_banner
    printf "\n${UI_CYAN}%s${UI_RESET}\n" "$title"
    if [ -n "$subtitle" ]; then
        printf "${UI_DIM}%s${UI_RESET}\n" "$subtitle"
    fi
    printf "\n"

    local idx=0
    local item
    for item in "$@"; do
        printf "  "
        if [ "$idx" -eq "$selected" ]; then
            installer_cursor
        else
            installer_empty_cursor
        fi
        printf " %s\n" "$item"
        idx=$((idx + 1))
    done

    printf "\n${UI_DIM}Controls: Up/Down move   Enter select   Esc back   q quit${UI_RESET}\n"
}

installer_select_menu() {
    local title="$1"
    local subtitle="$2"
    shift 2
    local items=("$@")
    local selected=0
    local key
    installer_automation_next || true
    if [ -n "${INSTALLER_AUTOMATION_VALUE:-}" ]; then
        printf "%s" "$INSTALLER_AUTOMATION_VALUE"
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
                if [ "$numeric" -lt "${#items[@]}" ]; then
                    echo "$numeric"
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
    printf "\n${UI_DIM}Press any key to continue...${UI_RESET}"
    IFS= read -rsn1 _
}

installer_message() {
    local title="$1"
    local body="$2"
    printf "${UI_CLEAR}"
    installer_banner
    printf "\n${UI_CYAN}%s${UI_RESET}\n" "$title"
    if [ -n "$body" ]; then
        printf "${UI_DIM}%s${UI_RESET}\n" "$body"
    fi
    printf "\n"
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
        printf "${UI_YELLOW}Default:${UI_RESET} %s\n\n" "$default_value"
    fi
    printf "> "
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
    local options=("Yes" "No")
    local selected=""
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
