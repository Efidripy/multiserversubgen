#!/bin/bash

# Runtime secrets are intentionally kept outside the install-state log and the
# world-readable systemd unit. The caller must set PROJECT_NAME first.

runtime_require_safe_project_name() {
    local project_name="${PROJECT_NAME:-}"
    if [[ ! "$project_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        printf 'invalid PROJECT_NAME: %s\n' "$project_name" >&2
        return 1
    fi
}

runtime_require_expected_project_dir() {
    runtime_require_safe_project_name || return 1

    local expected_project_dir="/opt/$PROJECT_NAME"
    if [ "${PROJECT_DIR:-}" != "$expected_project_dir" ]; then
        printf 'invalid PROJECT_DIR for %s: %s\n' "$PROJECT_NAME" "${PROJECT_DIR:-<empty>}" >&2
        return 1
    fi
}

runtime_secrets_file() {
    runtime_require_safe_project_name || return 1
    printf '/etc/%s/runtime-secrets.env\n' "$PROJECT_NAME"
}

runtime_secret_generate() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        python3 -c 'import secrets; print(secrets.token_hex(32))'
    fi
}

runtime_secrets_load() {
    local secret_file
    secret_file="$(runtime_secrets_file)" || return 1
    if [ -f "$secret_file" ]; then
        # This root-owned 0600 file uses shell-escaped values written below.
        secure_source_file "$secret_file" "runtime secrets"
    fi
}

runtime_telegram_public_base_url_is_valid() {
    local value="${1:-}"

    TELEGRAM_PUBLIC_BASE_URL_TO_VALIDATE="$value" python3 - <<'PYTHON'
import os
from urllib.parse import urlparse

value = os.environ["TELEGRAM_PUBLIC_BASE_URL_TO_VALIDATE"]
try:
    parsed = urlparse(value)
    hostname = parsed.hostname
    _ = parsed.port
except ValueError:
    raise SystemExit(1)

if (
    parsed.scheme != "https"
    or not hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)
PYTHON
}

runtime_derive_telegram_public_base_url() {
    local public_scheme="${PUBLIC_SCHEME:-}"
    local public_domain="${PUBLIC_DOMAIN:-}"
    local web_path="${WEB_PATH:-}"

    [ "$public_scheme" = "https" ] || return 1
    [[ "$public_domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || return 1
    [[ "$public_domain" != *..* ]] || return 1
    web_path="${web_path#/}"
    web_path="${web_path%/}"
    [ -z "$web_path" ] || [[ "$web_path" =~ ^[A-Za-z0-9]{1,128}$ ]] || return 1

    if [ -n "$web_path" ]; then
        printf 'https://%s/%s\n' "$public_domain" "$web_path"
    else
        printf 'https://%s\n' "$public_domain"
    fi
}

runtime_resolve_telegram_public_base_url() {
    local configured_value="${TELEGRAM_PUBLIC_BASE_URL:-}"
    local recorded_auto_value="${TELEGRAM_PUBLIC_BASE_URL_AUTO_VALUE:-}"
    local derived_value=""

    configured_value="${configured_value%/}"
    recorded_auto_value="${recorded_auto_value%/}"

    if [ -n "$configured_value" ] \
        && { [ "${TELEGRAM_PUBLIC_BASE_URL_SOURCE:-}" != "auto" ] || [ -z "$recorded_auto_value" ] || [ "$configured_value" != "$recorded_auto_value" ]; }; then
        runtime_telegram_public_base_url_is_valid "$configured_value" || {
            printf 'TELEGRAM_PUBLIC_BASE_URL must be an HTTPS URL without credentials, query or fragment\n' >&2
            return 1
        }
        TELEGRAM_PUBLIC_BASE_URL="$configured_value"
        TELEGRAM_PUBLIC_BASE_URL_SOURCE="manual"
        TELEGRAM_PUBLIC_BASE_URL_AUTO_VALUE=""
        return 0
    fi

    derived_value="$(runtime_derive_telegram_public_base_url)" || {
        if [ "${TELEGRAM_BOT_ENABLED:-false}" = "true" ]; then
            printf 'Telegram is enabled but TELEGRAM_PUBLIC_BASE_URL is unset and the canonical panel origin is not HTTPS\n' >&2
            return 1
        fi
        TELEGRAM_PUBLIC_BASE_URL=""
        TELEGRAM_PUBLIC_BASE_URL_SOURCE=""
        TELEGRAM_PUBLIC_BASE_URL_AUTO_VALUE=""
        return 0
    }
    runtime_telegram_public_base_url_is_valid "$derived_value" || return 1
    TELEGRAM_PUBLIC_BASE_URL="$derived_value"
    TELEGRAM_PUBLIC_BASE_URL_SOURCE="auto"
    TELEGRAM_PUBLIC_BASE_URL_AUTO_VALUE="$derived_value"
}

runtime_verify_telegram_public_base_url_health() {
    local base_url="${TELEGRAM_PUBLIC_BASE_URL:-}"
    local health_url status attempt

    [ "${TELEGRAM_BOT_ENABLED:-false}" = "true" ] || return 0
    runtime_telegram_public_base_url_is_valid "$base_url" || {
        printf 'Telegram is enabled but TELEGRAM_PUBLIC_BASE_URL is not a valid HTTPS URL\n' >&2
        return 1
    }
    health_url="${base_url%/}/health"
    for attempt in 1 2 3 4 5; do
        status="$(curl --fail --silent --show-error --max-time 5 --output /dev/null --write-out '%{http_code}' "$health_url" 2>/dev/null || true)"
        [ "$status" = "200" ] && return 0
        sleep 2
    done
    printf 'Telegram public URL health check failed (expected HTTPS /health -> 200)\n' >&2
    return 1
}

runtime_secrets_write() {
    local secret_file temp_file runtime_key
    local -a telegram_runtime_keys=(
        TELEGRAM_BOT_ENABLED
        TELEGRAM_BOT_TOKEN
        TELEGRAM_PRIMARY_ADMIN_ID
        TELEGRAM_MODE
        TELEGRAM_WEBHOOK_SECRET
        TELEGRAM_WEBHOOK_PATH_SUFFIX
        TELEGRAM_PUBLIC_BASE_URL
        TELEGRAM_PUBLIC_BASE_URL_SOURCE
        TELEGRAM_PUBLIC_BASE_URL_AUTO_VALUE
        TELEGRAM_LOCAL_PROXY_URL
        TELEGRAM_POLLING_TIMEOUT_SEC
        TELEGRAM_INTRODUCTION_MAX_CHARS
        TELEGRAM_PROVISIONING_WORKER_ENABLED
        TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES
        TELEGRAM_PROVISIONING_WORKER_INTERVAL_SEC
        TELEGRAM_OUTBOX_WORKER_ENABLED
        TELEGRAM_OUTBOX_WORKER_INTERVAL_SEC
        TELEGRAM_RETENTION_WORKER_ENABLED
        TELEGRAM_RETENTION_WORKER_INTERVAL_SEC
    )
    secret_file="$(runtime_secrets_file)" || return 1
    if [ -L "$secret_file" ]; then
        printf 'refusing to overwrite symlinked runtime secrets: %s\n' "$secret_file" >&2
        return 1
    fi
    install -d -m 0700 "$(dirname "$secret_file")"
    temp_file="$(mktemp "${secret_file}.tmp.XXXXXX")"
    chmod 0600 "$temp_file"

    WS_AUTH_SECRET="${WS_AUTH_SECRET:-$(runtime_secret_generate)}"
    SUBSCRIPTION_SIGNING_SECRET="${SUBSCRIPTION_SIGNING_SECRET:-$(runtime_secret_generate)}"
    runtime_resolve_telegram_public_base_url || return 1

    {
        printf 'REDIS_URL=%q\n' "${REDIS_URL:-}"
        printf 'MFA_TOTP_USERS=%q\n' "${MFA_TOTP_USERS:-}"
        printf 'WS_AUTH_SECRET=%q\n' "$WS_AUTH_SECRET"
        printf 'SUBSCRIPTION_SIGNING_SECRET=%q\n' "$SUBSCRIPTION_SIGNING_SECRET"
        # Telegram remains opt-in, but once configured it must survive the
        # regular installer/updater rewrite of this 0600 runtime secret file.
        for runtime_key in "${telegram_runtime_keys[@]}"; do
            if [ -n "${!runtime_key-}" ]; then
                printf '%s=%q\n' "$runtime_key" "${!runtime_key}"
            fi
        done
    } > "$temp_file"
    mv -fT -- "$temp_file" "$secret_file"
}

runtime_ensure_service_user() {
    runtime_require_safe_project_name || return 1
    local service_user="$PROJECT_NAME"
    local service_dir="${PROJECT_DIR:?PROJECT_DIR is required}"

    if ! getent group "$service_user" >/dev/null 2>&1; then
        groupadd --system "$service_user"
    fi
    if ! id -u "$service_user" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin --gid "$service_user" "$service_user"
    fi

    # nginx serves the deliberately public frontend build below this directory.
    # Grant only traversal to non-service users: they cannot list or read runtime
    # files, while the nginx worker can reach build/ assets (which have their own
    # explicit public modes).
    install -d -o "$service_user" -g "$service_user" -m 0711 "$service_dir"
    chown -R -- "$service_user:$service_user" "$service_dir"
}
