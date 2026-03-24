#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/locale.sh"
source "${SCRIPT_DIR}/lib/ui.sh"
source "${SCRIPT_DIR}/lib/workflows.sh"

preview_screen() {
    local screen="${1:-main}"
    case "$screen" in
        main)
            installer_render_menu "Main Menu" "Press Enter for the standard install or choose another mode." 0 \
                "1. Standard Install" \
                "2. Advanced Install: Sub-Manager presets" \
                "3. Advanced Install: 3x-ui presets" \
                "4. Update Existing Installation" \
                "5. Remove Installation" \
                "0. Exit"
            ;;
        sub)
            installer_render_menu "Advanced Install: Sub-Manager" "Choose a preset without 3x-ui." 0 \
                "2.1 Sub-Manager only" \
                "2.2 Sub-Manager + Prometheus + Grafana" \
                "2.3 Sub-Manager + Prometheus + Grafana + Loki + promtail" \
                "2.4 Sub-Manager + Monitoring + AdGuard provisioning" \
                "2.5 Sub-Manager + Custom Extras" \
                "2.6 Back"
            ;;
        xui)
            installer_render_menu "Advanced Install: 3x-ui" "Choose a preset." 0 \
                "3.0 3x-ui" \
                "3.1 3x-ui + Sub-Manager only" \
                "3.2 3x-ui + Sub-Manager + Prometheus + Grafana" \
                "3.3 3x-ui + Sub-Manager + Prometheus + Grafana + Loki + promtail" \
                "3.4 3x-ui + Sub-Manager + Monitoring + AdGuard provisioning" \
                "3.5 3x-ui + Sub-Manager + Custom Extras" \
                "3.6 Back"
            ;;
        update)
            installer_render_menu "Update Existing Installation" "Choose what should be updated or repaired." 0 \
                "4.1 Full Update" \
                "4.2 Backend Only" \
                "4.3 Frontend Only" \
                "4.4 Nginx Config Only" \
                "4.5 Repair Current Installation" \
                "4.6 Back"
            ;;
        remove)
            installer_render_menu "Remove Installation" "Choose whether the database should be preserved." 0 \
                "5.1 Remove and Keep Database" \
                "5.2 Remove Including Database" \
                "5.3 Back"
            ;;
        *)
            echo "Unknown preview screen: $screen" >&2
            return 1
            ;;
    esac
}

show_execution_result() {
    local title="$1"
    local status="$2"
    if report_is_active; then
        if [ "$status" -eq 0 ]; then
            report_mark_success
            report_finalize_outputs
            if [ "${INSTALLER_SHOW_SUMMARY:-false}" = "true" ]; then
                report_print_summary
            fi
        else
            report_mark_failure
            report_finalize_outputs
            installer_message "$title" "Exited with status $status."
        fi
    else
        if [ "$status" -eq 0 ]; then
            installer_message "$title" "Completed successfully."
        else
            installer_message "$title" "Exited with status $status."
        fi
    fi
    installer_pause
}

run_with_result() {
    local title="$1"
    shift
    set +e
    "$@"
    local status=$?
    set -e
    show_execution_result "$title" "$status"
    if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] && ! installer_has_pending_automation; then
        printf "\n"
        exit "$status"
    fi
}

handle_xui_menu() {
    local choice
    choice="$(installer_select_menu \
        "Advanced Install: 3x-ui" \
        "Choose a preset." \
        "3.0 3x-ui" \
        "3.1 3x-ui + Sub-Manager only" \
        "3.2 3x-ui + Sub-Manager + Prometheus + Grafana" \
        "3.3 3x-ui + Sub-Manager + Prometheus + Grafana + Loki + promtail" \
        "3.4 3x-ui + Sub-Manager + Monitoring + AdGuard provisioning" \
        "3.5 3x-ui + Sub-Manager + Custom Extras" \
        "3.6 Back")"
    case "$choice" in
        0) run_with_result "3.0 Selected" run_xui_preset "minimal" ;;
        1) run_with_result "3.1 Selected" run_xui_preset "only" ;;
        2) run_with_result "3.2 Selected" run_xui_preset "monitoring" ;;
        3) run_with_result "3.3 Selected" run_xui_preset "logs" ;;
        4) run_with_result "3.4 Selected" run_xui_preset "adguard" ;;
        5) run_with_result "3.5 Selected" run_xui_preset "custom" ;;
        __QUIT__) exit 0 ;;
    esac
}

handle_sub_menu() {
    local choice
    choice="$(installer_select_menu \
        "Advanced Install: Sub-Manager" \
        "Choose a preset without 3x-ui." \
        "2.1 Sub-Manager only" \
        "2.2 Sub-Manager + Prometheus + Grafana" \
        "2.3 Sub-Manager + Prometheus + Grafana + Loki + promtail" \
        "2.4 Sub-Manager + Monitoring + AdGuard provisioning" \
        "2.5 Sub-Manager + Custom Extras" \
        "2.6 Back")"
    case "$choice" in
        0) run_with_result "2.1 Selected" run_sub_preset "only" ;;
        1) run_with_result "2.2 Selected" run_sub_preset "monitoring" ;;
        2) run_with_result "2.3 Selected" run_sub_preset "logs" ;;
        3) run_with_result "2.4 Selected" run_sub_preset "adguard" ;;
        4) run_with_result "2.5 Selected" run_sub_preset "custom" ;;
        __QUIT__) exit 0 ;;
    esac
}

handle_update_menu() {
    local choice
    choice="$(installer_select_menu \
        "Update Existing Installation" \
        "Choose what should be updated or repaired." \
        "● 4.1 Full Update (recommended)" \
        "4.2 Backend Only" \
        "4.3 Frontend Only" \
        "4.4 Nginx Config Only" \
        "4.5 Repair Current Installation" \
        "4.6 Back")"
    case "$choice" in
        0) run_with_result "4.1 Full Update" run_update_mode "1" ;;
        1) run_with_result "4.2 Backend Only" run_update_mode "2" ;;
        2) run_with_result "4.3 Frontend Only" run_update_mode "3" ;;
        3) run_with_result "4.4 Nginx Config Only" run_update_mode "4" ;;
        4) run_with_result "4.5 Repair Current Installation" run_update_mode "1" ;;
        __QUIT__) exit 0 ;;
    esac
}

handle_remove_menu() {
    local choice
    choice="$(installer_select_menu \
        "Remove Installation" \
        "Choose whether the database should be preserved." \
        "● 5.1 Full Cleanup + Keep Database (recommended)" \
        "5.2 Full Cleanup + Remove Database" \
        "5.3 Back")"
    case "$choice" in
        0) run_with_result "5.1 Full Cleanup + Keep Database" run_remove_mode "keep-db" ;;
        1) run_with_result "5.2 Full Cleanup + Remove Database" run_remove_mode "drop-db" ;;
        __QUIT__) exit 0 ;;
    esac
}

run_menu() {
    while true; do
        local choice
        choice="$(installer_select_menu \
            "Main Menu" \
            "Press Enter for the standard install or choose another mode." \
            "1. Standard Install" \
            "2. Advanced Install: Sub-Manager presets" \
            "3. Advanced Install: 3x-ui presets" \
            "4. Update Existing Installation" \
            "5. Remove Installation" \
            "0. Exit")"

        case "$choice" in
            0) run_with_result "1. Standard Install" run_simple_install_over_existing ;;
            1) handle_sub_menu ;;
            2) handle_xui_menu ;;
            3) handle_update_menu ;;
            4) handle_remove_menu ;;
            5|__QUIT__) printf "\n"; exit 0 ;;
            __BACK__) continue ;;
        esac
    done
}

if [ "${INSTALLER_PREVIEW:-}" != "" ]; then
    preview_screen "${INSTALLER_PREVIEW}"
    exit 0
fi

run_menu
