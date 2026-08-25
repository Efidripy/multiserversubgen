#!/bin/bash

# Transactional activation for the Sub-Manager's bounded configuration surface.
# This helper deliberately owns only the manager unit, snippet, shield, and the
# include line in the selected site config. It must not modify nginx.conf,
# stream configs, or arbitrary host configuration.

config_activation_fail() {
    echo "Config activation failed: $*" >&2
    return 1
}

config_activation_require_safe_value() {
    local name="$1"
    local value="${2:-}"
    if [[ "$value" == *$'\n'* || "$value" == *$'\r'* || "$value" == *'"'* || "$value" == *"'"* || "$value" == *'\\'* || "$value" == *'`'* ]]; then
        config_activation_fail "$name contains unsupported control or quoting characters"
        return 1
    fi
}

config_activation_require_port() {
    local name="$1"
    local value="${2:-}"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
        config_activation_fail "$name must be an integer from 1 to 65535"
        return 1
    fi
}

config_activation_require_positive_integer() {
    local name="$1"
    local value="${2:-}"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -gt 2147483647 ]; then
        config_activation_fail "$name must be a non-negative integer"
        return 1
    fi
}

config_activation_require_bool() {
    local name="$1"
    local value="${2:-}"
    if [[ "$value" != "true" && "$value" != "false" ]]; then
        config_activation_fail "$name must be true or false"
        return 1
    fi
}

config_activation_require_route_token() {
    local name="$1"
    local value="${2:-}"
    if [[ ! "$value" =~ ^[A-Za-z0-9]{1,128}$ ]]; then
        config_activation_fail "$name must contain only letters and digits"
        return 1
    fi
}

config_activation_require_public_domain() {
    local value="${1:-}"
    if [[ ! "$value" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || [[ "$value" == *..* ]]; then
        config_activation_fail "PUBLIC_DOMAIN must be a hostname or IP address without URL syntax"
        return 1
    fi
}

config_activation_require_allowlist() {
    local value="${1:-}"
    [ -z "$value" ] && return 0
    CONFIG_ACTIVATION_ALLOWLIST="$value" python3 - <<'PYTHON'
import ipaddress
import os

for raw in os.environ["CONFIG_ACTIVATION_ALLOWLIST"].split(","):
    item = raw.strip()
    if not item:
        raise SystemExit("empty SECURITY_IP_ALLOWLIST entry")
    try:
        ipaddress.ip_network(item, strict=False)
    except ValueError as exc:
        raise SystemExit(f"invalid SECURITY_IP_ALLOWLIST entry {item!r}: {exc}")
PYTHON
}

config_activation_validate_inputs() {
    runtime_require_safe_project_name || return 1
    runtime_require_expected_project_dir || return 1
    config_activation_require_port "APP_PORT" "${APP_PORT:-}" || return 1
    if [ "${MONITORING_ENABLED:-false}" = "true" ]; then
        config_activation_require_port "GRAFANA_HTTP_PORT" "${GRAFANA_HTTP_PORT:-}" || return 1
    fi
    config_activation_require_public_domain "${PUBLIC_DOMAIN:-}" || return 1
    config_activation_require_route_token "WEB_PATH" "${WEB_PATH:-}" || return 1
    config_activation_require_route_token "GRAFANA_WEB_PATH" "${GRAFANA_WEB_PATH:-}" || return 1

    local boolean_name
    for boolean_name in MONITORING_ENABLED VERIFY_TLS READ_ONLY_MODE MFA_TOTP_ENABLED MFA_TOTP_WS_STRICT SECURITY_MTLS_ENABLED; do
        config_activation_require_bool "$boolean_name" "${!boolean_name:-}" || return 1
    done

    local numeric_name
    for numeric_name in SUB_RATE_LIMIT_COUNT SUB_RATE_LIMIT_WINDOW_SEC TRAFFIC_STATS_CACHE_TTL TRAFFIC_STATS_STALE_TTL CLIENTS_CACHE_TTL CLIENTS_CACHE_STALE_TTL TRAFFIC_MAX_WORKERS COLLECTOR_BASE_INTERVAL_SEC COLLECTOR_MAX_INTERVAL_SEC COLLECTOR_MAX_PARALLEL AUDIT_QUEUE_BATCH_SIZE; do
        config_activation_require_positive_integer "$numeric_name" "${!numeric_name:-}" || return 1
    done

    local value_name
    for value_name in ALLOW_ORIGINS CA_BUNDLE_PATH ROLE_VIEWERS ROLE_OPERATORS; do
        config_activation_require_safe_value "$value_name" "${!value_name:-}" || return 1
    done
    config_activation_require_allowlist "${SECURITY_IP_ALLOWLIST:-}" || return 1

    if [ "${SECURITY_MTLS_ENABLED:-false}" = "true" ]; then
        if [ -z "${SECURITY_MTLS_CA_PATH:-}" ] || [ ! -f "$SECURITY_MTLS_CA_PATH" ] || [ -L "$SECURITY_MTLS_CA_PATH" ]; then
            config_activation_fail "SECURITY_MTLS_CA_PATH must be a regular file when mTLS is enabled"
            return 1
        fi
        config_activation_require_safe_value "SECURITY_MTLS_CA_PATH" "$SECURITY_MTLS_CA_PATH" || return 1
    fi
}

config_activation_begin() {
    config_activation_validate_inputs || return 1
    local runtime_root="${CONFIG_ACTIVATION_RUNTIME_ROOT:-/run}"
    local backup_root="${CONFIG_ACTIVATION_BACKUP_ROOT:-/var/backups}"
    install -d -m 0700 "$runtime_root" "$backup_root/$PROJECT_NAME/config-activation" || return 1
    CONFIG_ACTIVATION_STAGE_DIR="$(mktemp -d "$runtime_root/${PROJECT_NAME}.config.XXXXXX")" || return 1
    CONFIG_ACTIVATION_BACKUP_DIR="$(mktemp -d "$backup_root/$PROJECT_NAME/config-activation/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")" || {
        rm -rf -- "$CONFIG_ACTIVATION_STAGE_DIR"
        unset CONFIG_ACTIVATION_STAGE_DIR
        return 1
    }
    chmod 0700 "$CONFIG_ACTIVATION_STAGE_DIR" "$CONFIG_ACTIVATION_BACKUP_DIR"
    : > "$CONFIG_ACTIVATION_BACKUP_DIR/manifest"
}

config_activation_cleanup() {
    if [ -n "${CONFIG_ACTIVATION_STAGE_DIR:-}" ] && [ -d "$CONFIG_ACTIVATION_STAGE_DIR" ]; then
        rm -rf -- "$CONFIG_ACTIVATION_STAGE_DIR"
    fi
    unset CONFIG_ACTIVATION_STAGE_DIR
}

config_activation_assert_regular_target() {
    local target="$1"
    if [ -L "$target" ]; then
        config_activation_fail "refusing symlinked config target: $target"
        return 1
    fi
    if [ -e "$target" ] && [ ! -f "$target" ]; then
        config_activation_fail "config target is not a regular file: $target"
        return 1
    fi
}

config_activation_assert_selected_cfg() {
    local selected_cfg="$1"
    local nginx_root="${CONFIG_ACTIVATION_NGINX_ROOT:-/etc/nginx}"
    local canonical_cfg
    canonical_cfg="$(readlink -f -- "$selected_cfg")" || {
        config_activation_fail "SELECTED_CFG cannot be resolved"
        return 1
    }
    if [ "$canonical_cfg" != "$selected_cfg" ]; then
        config_activation_fail "SELECTED_CFG must not traverse or resolve through a symlink"
        return 1
    fi
    case "$canonical_cfg" in
        "$nginx_root"/sites-available/*) ;;
        *) config_activation_fail "SELECTED_CFG must remain under /etc/nginx/sites-available"; return 1 ;;
    esac
    [ -f "$canonical_cfg" ] && [ ! -L "$canonical_cfg" ] || {
        config_activation_fail "SELECTED_CFG must be an existing regular file"
        return 1
    }
}

config_activation_snapshot() {
    local label="$1"
    local target="$2"
    config_activation_assert_regular_target "$target" || return 1
    if [ -e "$target" ]; then
        cp -a -- "$target" "$CONFIG_ACTIVATION_BACKUP_DIR/$label" || return 1
        printf '%s|present|%s\n' "$label" "$target" >> "$CONFIG_ACTIVATION_BACKUP_DIR/manifest"
    else
        printf '%s|absent|%s\n' "$label" "$target" >> "$CONFIG_ACTIVATION_BACKUP_DIR/manifest"
    fi
}

config_activation_promote() {
    local staged="$1"
    local target="$2"
    local mode="$3"
    config_activation_assert_regular_target "$target" || return 1
    [ -f "$staged" ] && [ ! -L "$staged" ] || {
        config_activation_fail "staged config is missing or symlinked: $staged"
        return 1
    }
    local target_dir
    target_dir="$(dirname "$target")"
    install -d -m 0755 "$target_dir" || return 1
    local temp_target
    temp_target="$(mktemp "$target_dir/.${PROJECT_NAME}.activate.XXXXXX")" || return 1
    if ! install -m "$mode" "$staged" "$temp_target"; then
        rm -f -- "$temp_target"
        return 1
    fi
    mv -fT -- "$temp_target" "$target"
}

config_activation_restore() {
    local label target state temp_target
    while IFS='|' read -r label state target; do
        [ -n "$label" ] || continue
        if [ "$state" = "present" ]; then
            local target_dir
            target_dir="$(dirname "$target")"
            install -d -m 0755 "$target_dir" || return 1
            temp_target="$(mktemp "$target_dir/.${PROJECT_NAME}.restore.XXXXXX")" || return 1
            if ! cp -a -- "$CONFIG_ACTIVATION_BACKUP_DIR/$label" "$temp_target"; then
                rm -f -- "$temp_target"
                return 1
            fi
            mv -fT -- "$temp_target" "$target" || return 1
        else
            rm -f -- "$target" || return 1
        fi
    done < "$CONFIG_ACTIVATION_BACKUP_DIR/manifest"

    systemctl daemon-reload >/dev/null 2>&1 || true
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 || true
    fi
}

config_activation_render_service() {
    local template="$1"
    local destination="$2"
    [ -f "$template" ] || { config_activation_fail "service template not found: $template"; return 1; }
    python3 - "$template" "$destination" \
        "PROJECT_DIR=$PROJECT_DIR" "PROJECT_NAME=$PROJECT_NAME" "APP_PORT=$APP_PORT" "WEB_PATH=$WEB_PATH" \
        "GRAFANA_WEB_PATH=$GRAFANA_WEB_PATH" "MONITORING_ENABLED=$MONITORING_ENABLED" "ALLOW_ORIGINS=$ALLOW_ORIGINS" \
        "VERIFY_TLS=$VERIFY_TLS" "CA_BUNDLE_PATH=$CA_BUNDLE_PATH" "READ_ONLY_MODE=$READ_ONLY_MODE" \
        "SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT" "SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC" \
        "TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL" "TRAFFIC_STATS_STALE_TTL=$TRAFFIC_STATS_STALE_TTL" \
        "CLIENTS_CACHE_TTL=$CLIENTS_CACHE_TTL" "CLIENTS_CACHE_STALE_TTL=$CLIENTS_CACHE_STALE_TTL" \
        "TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS" "COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC" \
        "COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC" "COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL" \
        "AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE" "ROLE_VIEWERS=$ROLE_VIEWERS" "ROLE_OPERATORS=$ROLE_OPERATORS" \
        "MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED" "MFA_TOTP_WS_STRICT=$MFA_TOTP_WS_STRICT" <<'PYTHON'
from pathlib import Path
import re
import sys

template, destination, *items = sys.argv[1:]
values = dict(item.split("=", 1) for item in items)
text = Path(template).read_text(encoding="utf-8")
text = text.replace("/opt/sub-manager", values["PROJECT_DIR"])
text = text.replace("__PROJECT_NAME__", values["PROJECT_NAME"])
for key, value in values.items():
    if key in {"PROJECT_DIR", "PROJECT_NAME"}:
        continue
    pattern = rf'^Environment="{re.escape(key)}=.*"$'
    text, count = re.subn(pattern, f'Environment="{key}={value}"', text, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"expected exactly one Environment line for {key}, got {count}")
text = text.replace('Environment="APP_PORT=666"', f'Environment="APP_PORT={values["APP_PORT"]}"')
text = text.replace('sport = :666', f'sport = :{values["APP_PORT"]}')
text = text.replace('--port 666', f'--port {values["APP_PORT"]}')
Path(destination).write_text(text, encoding="utf-8")
PYTHON
}

config_activation_activate() {
    local staged_unit="$1"
    local staged_snippet="$2"
    local staged_shield="$3"
    local staged_site="$4"
    local selected_cfg="$5"
    shift 5

    local systemd_dir="${CONFIG_ACTIVATION_SYSTEMD_DIR:-/etc/systemd/system}"
    local nginx_root="${CONFIG_ACTIVATION_NGINX_ROOT:-/etc/nginx}"
    local unit_target="$systemd_dir/${PROJECT_NAME}.service"
    local snippet_target="$nginx_root/snippets/${PROJECT_NAME}.conf"
    local shield_target="$nginx_root/conf.d/${PROJECT_NAME}-shield.conf"

    config_activation_assert_selected_cfg "$selected_cfg" || return 1
    systemd-analyze verify "$staged_unit" || return 1

    config_activation_snapshot "unit" "$unit_target" || return 1
    config_activation_snapshot "snippet" "$snippet_target" || return 1
    config_activation_snapshot "shield" "$shield_target" || return 1
    config_activation_snapshot "site" "$selected_cfg" || return 1

    if ! config_activation_promote "$staged_unit" "$unit_target" 0644 \
        || ! config_activation_promote "$staged_snippet" "$snippet_target" 0644 \
        || ! config_activation_promote "$staged_shield" "$shield_target" 0644 \
        || ! config_activation_promote "$staged_site" "$selected_cfg" 0644 \
        || ! systemctl daemon-reload \
        || ! nginx -t \
        || ! systemctl reload nginx \
        || ! "$@"; then
        echo "Config activation failed; restoring the exact prior config snapshot." >&2
        config_activation_restore || true
        return 1
    fi
}
