#!/bin/bash

# Runtime secrets are intentionally kept outside the install-state log and the
# world-readable systemd unit. The caller must set PROJECT_NAME first.

runtime_secrets_file() {
    printf '/etc/%s/runtime-secrets.env\n' "${PROJECT_NAME:?PROJECT_NAME is required}"
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
    secret_file="$(runtime_secrets_file)"
    if [ -f "$secret_file" ]; then
        # This root-owned 0600 file uses shell-escaped values written below.
        # shellcheck disable=SC1090
        source "$secret_file"
    fi
}

runtime_secrets_write() {
    local secret_file temp_file
    secret_file="$(runtime_secrets_file)"
    install -d -m 0700 "$(dirname "$secret_file")"
    temp_file="$(mktemp "${secret_file}.tmp.XXXXXX")"
    chmod 0600 "$temp_file"

    WS_AUTH_SECRET="${WS_AUTH_SECRET:-$(runtime_secret_generate)}"
    SUBSCRIPTION_SIGNING_SECRET="${SUBSCRIPTION_SIGNING_SECRET:-$(runtime_secret_generate)}"

    {
        printf 'REDIS_URL=%q\n' "${REDIS_URL:-}"
        printf 'MFA_TOTP_USERS=%q\n' "${MFA_TOTP_USERS:-}"
        printf 'WS_AUTH_SECRET=%q\n' "$WS_AUTH_SECRET"
        printf 'SUBSCRIPTION_SIGNING_SECRET=%q\n' "$SUBSCRIPTION_SIGNING_SECRET"
    } > "$temp_file"
    install -m 0600 "$temp_file" "$secret_file"
    rm -f "$temp_file"
}

runtime_ensure_service_user() {
    local service_user="${PROJECT_NAME:?PROJECT_NAME is required}"
    local service_dir="${PROJECT_DIR:?PROJECT_DIR is required}"

    if ! getent group "$service_user" >/dev/null 2>&1; then
        groupadd --system "$service_user"
    fi
    if ! id -u "$service_user" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin --gid "$service_user" "$service_user"
    fi

    install -d -o "$service_user" -g "$service_user" -m 0750 "$service_dir"
    chown -R -- "$service_user:$service_user" "$service_dir"
}
