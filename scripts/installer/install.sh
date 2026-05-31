#!/bin/bash

# --- КОНФИГУРАЦИЯ ---
LOG_FILE="/opt/.sub_manager_install.log"
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd "${INSTALLER_DIR}/../.." && pwd)"
source "${INSTALLER_DIR}/lib/locale.sh"
source "${INSTALLER_DIR}/lib/ui.sh"
source "${INSTALLER_DIR}/lib/resource_guard.sh"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
APT_DPKG_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

# Color accents for installer UI
C_RED='\033[1;31m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_WHITE='\033[1;37m'
C_RESET='\033[0m'

apt_update() {
    DEBIAN_FRONTEND=noninteractive apt-get update "${APT_DPKG_OPTS[@]}"
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_DPKG_OPTS[@]}" "$@"
}

apt_fix_broken() {
    DEBIAN_FRONTEND=noninteractive apt-get install -f -y "${APT_DPKG_OPTS[@]}"
}

clear_stale_install_markers() {
    local project_dir="/opt/${PROJECT_NAME:-sub-manager}"
    local stale_logs=(
        "/opt/.sub_manager_install.log"
        "/opt/sub_manager_install.log"
        "${project_dir}/.sub_manager_install.log"
    )

    [ -d "$project_dir" ] && return 0

    local marker_found="false"
    local marker
    for marker in "${stale_logs[@]}"; do
        if [ -f "$marker" ]; then
            marker_found="true"
            rm -f "$marker"
        fi
    done

    if [ "$marker_found" = "true" ]; then
        echo "Removed stale install markers for missing project dir: $project_dir"
    fi
}

has_real_existing_install() {
    local project_name="${PROJECT_NAME:-sub-manager}"
    local project_dir="/opt/${project_name}"
    local service_file="/etc/systemd/system/${project_name}.service"

    [ -d "$project_dir" ] && return 0
    if [ -f "$service_file" ]; then
        if grep -q "$project_dir" "$service_file" 2>/dev/null; then
            return 0
        fi
        return 1
    fi
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${project_name}\\.service"; then
        if systemctl cat "${project_name}.service" 2>/dev/null | grep -q "$project_dir"; then
            return 0
        fi
        return 1
    fi
    return 1
}

is_pkg_installed() {
    dpkg -s "$1" >/dev/null 2>&1
}

detect_preexisting_stack() {
    PREEXISTING_NGINX_INSTALLED="false"
    PREEXISTING_PROMETHEUS_INSTALLED="false"
    PREEXISTING_GRAFANA_INSTALLED="false"
    PREEXISTING_LOKI_INSTALLED="false"
    PREEXISTING_PROMTAIL_INSTALLED="false"

    if is_pkg_installed nginx; then PREEXISTING_NGINX_INSTALLED="true"; fi
    if is_pkg_installed prometheus; then PREEXISTING_PROMETHEUS_INSTALLED="true"; fi
    if is_pkg_installed grafana; then PREEXISTING_GRAFANA_INSTALLED="true"; fi
    if is_pkg_installed loki; then PREEXISTING_LOKI_INSTALLED="true"; fi
    if is_pkg_installed promtail; then PREEXISTING_PROMTAIL_INSTALLED="true"; fi
}

install_grafana_with_fallback_deb() {
    local arch
    arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
    local version="${GRAFANA_FALLBACK_VERSION:-11.6.0}"
    local urls=()

    if [ -n "${GRAFANA_DEB_URL:-}" ]; then
        urls+=("${GRAFANA_DEB_URL}")
    fi
    urls+=(
        "https://dl.grafana.com/oss/release/grafana_${version}_${arch}.deb"
        "https://dl.grafana.com/enterprise/release/grafana-enterprise_${version}_${arch}.deb"
    )

    local tmp_deb
    tmp_deb="$(mktemp --suffix=.deb)"
    local installed="false"

    for deb_url in "${urls[@]}"; do
        if curl -fL --retry 3 --retry-all-errors -A "Mozilla/5.0" "$deb_url" -o "$tmp_deb"; then
            if DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_DPKG_OPTS[@]}" "$tmp_deb" >/dev/null 2>&1 \
                || (apt_fix_broken >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_DPKG_OPTS[@]}" "$tmp_deb" >/dev/null 2>&1); then
                installed="true"
                break
            fi
        fi
    done

    rm -f "$tmp_deb"
    [ "$installed" = "true" ]
}

ensure_system_user() {
    local user_name="$1"
    local group_name="${2:-$1}"
    if ! getent group "$group_name" >/dev/null 2>&1; then
        groupadd --system "$group_name" >/dev/null 2>&1 || true
    fi
    if ! id -u "$user_name" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin -g "$group_name" "$user_name" >/dev/null 2>&1 || true
    fi
}

install_loki_promtail_with_fallback_binaries() {
    local arch
    arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
    if [ "$arch" != "amd64" ]; then
        echo "⚠️ Fallback binary install for Loki/promtail currently supports amd64 only."
        return 1
    fi

    local version="${LOKI_STACK_VERSION:-3.6.7}"
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    local loki_zip="${tmp_dir}/loki.zip"
    local promtail_zip="${tmp_dir}/promtail.zip"
    local loki_url="https://github.com/grafana/loki/releases/download/v${version}/loki-linux-amd64.zip"
    local promtail_url="https://github.com/grafana/loki/releases/download/v${version}/promtail-linux-amd64.zip"

    apt_install unzip >/dev/null 2>&1 || { rm -rf "$tmp_dir"; return 1; }
    if ! curl -fL --retry 3 --retry-all-errors -A "Mozilla/5.0" "$loki_url" -o "$loki_zip"; then
        rm -rf "$tmp_dir"
        return 1
    fi
    if ! curl -fL --retry 3 --retry-all-errors -A "Mozilla/5.0" "$promtail_url" -o "$promtail_zip"; then
        rm -rf "$tmp_dir"
        return 1
    fi

    unzip -o "$loki_zip" -d "$tmp_dir" >/dev/null 2>&1 || { rm -rf "$tmp_dir"; return 1; }
    unzip -o "$promtail_zip" -d "$tmp_dir" >/dev/null 2>&1 || { rm -rf "$tmp_dir"; return 1; }

    install -m 0755 "${tmp_dir}/loki-linux-amd64" /usr/local/bin/loki || { rm -rf "$tmp_dir"; return 1; }
    install -m 0755 "${tmp_dir}/promtail-linux-amd64" /usr/local/bin/promtail || { rm -rf "$tmp_dir"; return 1; }
    [ -x /usr/local/bin/loki ] || { rm -rf "$tmp_dir"; return 1; }
    [ -x /usr/local/bin/promtail ] || { rm -rf "$tmp_dir"; return 1; }

    ensure_system_user loki
    ensure_system_user promtail
    usermod -a -G adm,systemd-journal promtail >/dev/null 2>&1 || true

    mkdir -p /etc/loki /etc/promtail /var/lib/loki /var/lib/promtail
    chown -R loki:loki /var/lib/loki >/dev/null 2>&1 || true
    chown -R promtail:promtail /var/lib/promtail >/dev/null 2>&1 || true

    cat > /etc/systemd/system/loki.service <<'EOF'
[Unit]
Description=Loki service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/loki -config.file=/etc/loki/local-config.yaml
TimeoutSec=120
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/promtail.service <<'EOF'
[Unit]
Description=Promtail service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/promtail -config.file=/etc/promtail/config.yml
TimeoutSec=60
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    rm -rf "$tmp_dir"
    return 0
}

install_loki_promtail_stack() {
    if command -v loki >/dev/null 2>&1 && command -v promtail >/dev/null 2>&1; then
        return 0
    fi

    if apt-cache show promtail >/dev/null 2>&1 && apt_install loki promtail >/dev/null 2>&1; then
        return 0
    fi

    install_loki_promtail_with_fallback_binaries
}

ensure_grafana_repo() {
    if ! apt-cache show grafana >/dev/null 2>&1; then
        echo "Grafana package not found in current APT sources. Adding official Grafana repo..."
        apt_install ca-certificates gnupg apt-transport-https curl || return 1
        install -d -m 0755 /etc/apt/keyrings
        local key_fetched="false"
        local tmp_key_file
        local tmp_gpg_file
        tmp_key_file="$(mktemp)"
        tmp_gpg_file="$(mktemp)"
        local key_urls=(
            "https://apt.grafana.com/gpg.key"
            "https://packages.grafana.com/gpg.key"
        )
        for key_url in "${key_urls[@]}"; do
            if curl -fsSL --retry 3 --retry-all-errors -A "Mozilla/5.0" "$key_url" -o "$tmp_key_file" \
                && gpg --batch --yes --dearmor -o "$tmp_gpg_file" "$tmp_key_file" 2>/dev/null \
                && install -m 0644 "$tmp_gpg_file" /etc/apt/keyrings/grafana.gpg; then
                key_fetched="true"
                break
            fi
        done
        rm -f "$tmp_key_file" "$tmp_gpg_file"
        if [ "$key_fetched" != "true" ]; then
            echo "❌ Не удалось скачать GPG ключ Grafana (возможен блок/403)."
            return 1
        fi
        chmod a+r /etc/apt/keyrings/grafana.gpg
        cat > /etc/apt/sources.list.d/grafana.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main
EOF
        apt_update || return 1
    fi

    if ! apt-cache show grafana >/dev/null 2>&1; then
        echo "❌ Grafana package still unavailable after repo setup."
        return 1
    fi
    return 0
}

generate_random_path() {
    tr -dc 'a-z0-9' </dev/urandom | head -c 8
}

generate_random_secret() {
    local length="${1:-16}"
    tr -dc 'a-zA-Z0-9' </dev/urandom | head -c "$length"
}

extract_port_from_bind() {
    local bind="${1:-127.0.0.1:5353}"
    local port="${bind##*:}"
    if [[ ! "$port" =~ ^[0-9]+$ ]]; then
        port="5353"
    fi
    echo "$port"
}

extract_host_from_bind() {
    local bind="${1:-127.0.0.1:5353}"
    local host="${bind%:*}"
    if [ -z "$host" ] || [ "$host" = "$bind" ]; then
        host="127.0.0.1"
    fi
    echo "$host"
}

normalize_tcp_port() {
    local value="${1:-}"
    local default_port="${2:-22}"
    if [[ "$value" =~ ^[0-9]+$ ]] && [ "$value" -ge 1 ] && [ "$value" -le 65535 ]; then
        echo "$value"
    else
        echo "$default_port"
    fi
}

normalize_public_access_vars() {
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN#http://}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN#https://}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN%%/*}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN%/}"
    PUBLIC_SCHEME="$(echo "${PUBLIC_SCHEME:-https}" | tr '[:upper:]' '[:lower:]')"
    if [ "$PUBLIC_SCHEME" != "http" ] && [ "$PUBLIC_SCHEME" != "https" ]; then
        PUBLIC_SCHEME="https"
    fi
    if [ -z "${PUBLIC_DOMAIN:-}" ]; then
        PUBLIC_DOMAIN="$(hostname -f)"
    fi
}

detect_nginx_stream_tls_conflict() {
    shopt -s nullglob
    if [ "${PUBLIC_SCHEME:-https}" != "https" ]; then
        shopt -u nullglob
        return 1
    fi
    local stream_files=( /etc/nginx/stream-enabled/*.conf )
    if [ ${#stream_files[@]} -eq 0 ]; then
        shopt -u nullglob
        return 1
    fi
        if ! grep -qsE 'listen[[:space:]]+443([[:space:];]|$)' "${stream_files[@]}" 2>/dev/null; then
        shopt -u nullglob
        return 1
    fi
    if grep -qs "${PUBLIC_DOMAIN}" "${stream_files[@]}" 2>/dev/null; then
        shopt -u nullglob
        return 0
    fi
    shopt -u nullglob
    return 0
}

sanitize_nginx_sites_for_stream_443() {
    shopt -s nullglob

    local stream_files=( /etc/nginx/stream-enabled/*.conf )
    if [ ${#stream_files[@]} -eq 0 ] || ! grep -qsE 'listen[[:space:]]+443([[:space:];]|$)' "${stream_files[@]}" 2>/dev/null; then
        shopt -u nullglob
        return 0
    fi

    local removed_any="false"
    local cfg_entry
    for cfg_entry in /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.conf /etc/nginx/sites-enabled/default.*; do
        [ -e "$cfg_entry" ] || continue
        rm -f "$cfg_entry" 2>/dev/null || true
        removed_any="true"
    done

    local selected_base=""
    if [ -n "${SELECTED_CFG:-}" ]; then
        selected_base="$(basename "$SELECTED_CFG")"
    fi

    if [ -n "${PUBLIC_DOMAIN:-}" ]; then
        local domain_variant
        for domain_variant in "${PUBLIC_DOMAIN}" "${PUBLIC_DOMAIN}.conf"; do
            [ -n "$domain_variant" ] || continue
            [ "$domain_variant" = "$selected_base" ] && continue
            if [ -e "/etc/nginx/sites-enabled/${domain_variant}" ]; then
                rm -f "/etc/nginx/sites-enabled/${domain_variant}" 2>/dev/null || true
                removed_any="true"
            fi
        done
    fi

    if [ "$removed_any" = "true" ]; then
           echo "⚠️ Обнаружен stream listen 443: отключены конфликтующие nginx site entries (default/domain duplicates)."
    fi

    shopt -u nullglob
    return 0
}

selected_cfg_supports_stream_tls_mux() {
    local cfg_path="${1:-}"
    if [ -z "$cfg_path" ] || [ ! -f "$cfg_path" ]; then
        return 1
    fi
    if grep -qsE 'listen[[:space:]].*(7443|9443|10443).*ssl' "$cfg_path"; then
        return 0
    fi
    if grep -qs 'proxy_protocol' "$cfg_path"; then
        return 0
    fi
    return 1
}

ensure_stream_public_domain_route() {
    shopt -s nullglob
    [ "${PUBLIC_SCHEME:-https}" = "https" ] || { shopt -u nullglob; return 0; }
    [ -n "${PUBLIC_DOMAIN:-}" ] || { shopt -u nullglob; return 0; }
    selected_cfg_supports_stream_tls_mux "${SELECTED_CFG:-}" || { shopt -u nullglob; return 0; }

    local stream_files=( /etc/nginx/stream-enabled/*.conf )
    if [ ${#stream_files[@]} -eq 0 ]; then
        shopt -u nullglob
        return 0
    fi

    python3 - "${PUBLIC_DOMAIN}" "${stream_files[@]}" <<'PY'
from pathlib import Path
import re
import sys

domain = sys.argv[1]
paths = [Path(p) for p in sys.argv[2:]]

for path in paths:
    text = path.read_text()
    if "map $ssl_preread_server_name $sni_name" not in text or "upstream www" not in text:
        continue

    lines = text.splitlines()
    start = None
    end = None
    for idx, line in enumerate(lines):
        if re.search(r'map\s+\$ssl_preread_server_name\s+\$sni_name\s*\{', line):
            start = idx
            continue
        if start is not None and line.strip() == "}":
            end = idx
            break

    if start is None or end is None:
        continue

    replacement = f"    {domain} www;"
    changed = False

    for idx in range(start + 1, end):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(rf"{re.escape(domain)}\s+", stripped):
            if stripped != f"{domain} www;":
                lines[idx] = replacement
                changed = True
            break
    else:
        for idx in range(start + 1, end):
            if lines[idx].strip().startswith("default "):
                lines.insert(idx, replacement)
                changed = True
                break

    if changed:
        path.write_text("\n".join(lines) + "\n")
    break
PY

    nginx -t >/dev/null 2>&1 || { shopt -u nullglob; return 1; }
    systemctl reload nginx >/dev/null 2>&1 || { shopt -u nullglob; return 1; }
    shopt -u nullglob
    return 0
}

assert_https_reverse_proxy_compatibility() {
    if detect_nginx_stream_tls_conflict; then
        if selected_cfg_supports_stream_tls_mux "${SELECTED_CFG:-}"; then
            if ! ensure_stream_public_domain_route; then
                echo "⚠️ Не удалось автоматически обновить nginx stream route для ${PUBLIC_DOMAIN}. Продолжаем установку без остановки."
            fi
            return 0
        fi
        echo "❌ Обнаружен nginx stream/TLS mux на 443 для текущего хоста."
        echo "   Такой сервер перехватывает HTTPS до обычного http server block и ломает панель под ${PUBLIC_DOMAIN}."
        echo "   Решения:"
        echo "   - использовать http для панели,"
        echo "   - перенастроить stream routing,"
        echo "   - или ставить проект на машину без nginx stream 443 mux."
        return 1
    fi
}

write_install_log() {
    local keys=(
        PROJECT_NAME PROJECT_DIR SELECTED_CFG APP_PORT PUBLIC_DOMAIN PUBLIC_SCHEME WEB_PATH
        SSH_PORT
        USE_PROXY ALLOW_ORIGINS VERIFY_TLS CA_BUNDLE_PATH READ_ONLY_MODE
        SUB_RATE_LIMIT_COUNT SUB_RATE_LIMIT_WINDOW_SEC TRAFFIC_STATS_CACHE_TTL
        ONLINE_CLIENTS_CACHE_TTL TRAFFIC_STATS_STALE_TTL ONLINE_CLIENTS_STALE_TTL
        CLIENTS_CACHE_TTL CLIENTS_CACHE_STALE_TTL TRAFFIC_MAX_WORKERS
        COLLECTOR_BASE_INTERVAL_SEC COLLECTOR_MAX_INTERVAL_SEC COLLECTOR_MAX_PARALLEL
        REDIS_URL AUDIT_QUEUE_BATCH_SIZE ROLE_VIEWERS ROLE_OPERATORS
        MONITORING_ENABLED GRAFANA_WEB_PATH GRAFANA_HTTP_PORT
        ADGUARD_METRICS_ENABLED ADGUARD_METRICS_TARGETS ADGUARD_METRICS_PATH
        ADGUARD_LOKI_ENABLED ADGUARD_QUERYLOG_PATH ADGUARD_SYSTEMD_UNIT
        ADGUARD_INSTALL_ENABLED ADGUARD_DNS_BIND ADGUARD_WEB_PORT ADGUARD_WEB_PATH ADGUARD_DOH_PATH
        ADGUARD_ADMIN_USER ADGUARD_ADMIN_PASS
        SECURITY_MTLS_ENABLED SECURITY_MTLS_CA_PATH SECURITY_IP_ALLOWLIST
        MFA_TOTP_ENABLED MFA_TOTP_USERS MFA_TOTP_WS_STRICT
        PREEXISTING_NGINX_INSTALLED PREEXISTING_PROMETHEUS_INSTALLED
        PREEXISTING_GRAFANA_INSTALLED PREEXISTING_LOKI_INSTALLED PREEXISTING_PROMTAIL_INSTALLED
    )
    : > "$LOG_FILE"
    local key value
    for key in "${keys[@]}"; do
        value="${!key-}"
        printf '%s=%q\n' "$key" "$value" >> "$LOG_FILE"
    done
}

pick_free_local_port() {
    local port="${1:-43000}"
    while ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; do
        port=$((port + 1))
    done
    echo "$port"
}

sync_backend_files() {
    echo "Копирование бэкенда (все модули)..."
    mkdir -p "$PROJECT_DIR"
    cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
    for pkg in core modules integrations routers services shared; do
        if [ -d "$SCRIPT_DIR/backend/$pkg" ]; then
            rm -rf "$PROJECT_DIR/$pkg"
            cp -r "$SCRIPT_DIR/backend/$pkg" "$PROJECT_DIR/"
        fi
    done
}

ensure_tls_material() {
    NGINX_SSL_CERT=""
    NGINX_SSL_KEY=""

    if [ "${PUBLIC_SCHEME:-https}" != "https" ]; then
        return 0
    fi

    local letsencrypt_cert="/etc/letsencrypt/live/${PUBLIC_DOMAIN}/fullchain.pem"
    local letsencrypt_key="/etc/letsencrypt/live/${PUBLIC_DOMAIN}/privkey.pem"
    if [ -f "$letsencrypt_cert" ] && [ -f "$letsencrypt_key" ]; then
        NGINX_SSL_CERT="$letsencrypt_cert"
        NGINX_SSL_KEY="$letsencrypt_key"
        return 0
    fi

    should_use_letsencrypt_for_domain() {
        local domain="$1"
        local cert_mode="${TLS_CERT_MODE:-auto}"
        local server_ip
        local domain_ip

        case "$cert_mode" in
            self-signed) return 1 ;;
            letsencrypt) ;;
            auto) ;;
            *) cert_mode="auto" ;;
        esac

        command -v certbot >/dev/null 2>&1 || return 1

        server_ip="$(ip route get 8.8.8.8 2>/dev/null | grep -Po 'src \K\S+' | head -n 1 || true)"
        if [[ ! "$server_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            server_ip="$(curl -4 -fsS https://ipv4.icanhazip.com 2>/dev/null | tr -d '[:space:]' || true)"
        fi

        domain_ip="$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1 {print $1}')"

        [ -n "$server_ip" ] || return 1
        [ -n "$domain_ip" ] || return 1
        [ "$server_ip" = "$domain_ip" ] || return 1

        case "$server_ip" in
            10.*|127.*|169.254.*|192.168.*|100.64.*|100.65.*|100.66.*|100.67.*|100.68.*|100.69.*|100.7[0-9].*|100.8[0-9].*|100.9[0-9].*)
                return 1
                ;;
            172.1[6-9].*|172.2[0-9].*|172.3[0-1].*)
                return 1
                ;;
        esac

        return 0
    }

    if should_use_letsencrypt_for_domain "${PUBLIC_DOMAIN}"; then
        echo "TLS сертификаты для ${PUBLIC_DOMAIN} не найдены. Пытаемся получить Let's Encrypt..."
        systemctl stop nginx >/dev/null 2>&1 || true
        if certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email -d "${PUBLIC_DOMAIN}" >/dev/null 2>&1; then
            systemctl start nginx >/dev/null 2>&1 || true
            if [ -f "$letsencrypt_cert" ] && [ -f "$letsencrypt_key" ]; then
                NGINX_SSL_CERT="$letsencrypt_cert"
                NGINX_SSL_KEY="$letsencrypt_key"
                return 0
            fi
        fi
        systemctl start nginx >/dev/null 2>&1 || true
        echo "⚠️ Не удалось получить Let's Encrypt для ${PUBLIC_DOMAIN}. Переходим на self-signed."
    fi

    local tls_dir="/etc/ssl/${PROJECT_NAME}"
    NGINX_SSL_CERT="${tls_dir}/fullchain.pem"
    NGINX_SSL_KEY="${tls_dir}/privkey.pem"
    mkdir -p "$tls_dir"

    if [ ! -f "$NGINX_SSL_CERT" ] || [ ! -f "$NGINX_SSL_KEY" ]; then
        echo "TLS сертификаты для ${PUBLIC_DOMAIN} не найдены. Генерируем self-signed сертификат..."
        openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout "$NGINX_SSL_KEY" \
            -out "$NGINX_SSL_CERT" \
            -days 3650 \
            -subj "/CN=${PUBLIC_DOMAIN}" >/dev/null 2>&1 || return 1
        chmod 600 "$NGINX_SSL_KEY"
        chmod 644 "$NGINX_SSL_CERT"
    fi
}

generate_bootstrap_nginx_cfg() {
    local cfg_path="$1"
    local snippet_include="    include /etc/nginx/snippets/${PROJECT_NAME}.conf;"

    if [ "${PUBLIC_SCHEME:-https}" = "https" ]; then
        ensure_tls_material || return 1
        cat > "$cfg_path" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${PUBLIC_DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${PUBLIC_DOMAIN};

    ssl_certificate ${NGINX_SSL_CERT};
    ssl_certificate_key ${NGINX_SSL_KEY};
    port_in_redirect off;
    absolute_redirect off;

${snippet_include}
}
EOF
    else
        cat > "$cfg_path" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${PUBLIC_DOMAIN};

${snippet_include}
}
EOF
    fi
}

ensure_selected_nginx_cfg_https_ready() {
    local cfg_path="$1"

    [ -f "$cfg_path" ] || return 0
    [ "${PUBLIC_SCHEME:-https}" = "https" ] || return 0

    if grep -qsE '^[[:space:]]*listen[[:space:]].*443' "$cfg_path"; then
        return 0
    fi

    local base_name
    base_name="$(basename "$cfg_path")"
    if [ "$base_name" = "default" ] || grep -qs 'server_name _;' "$cfg_path"; then
        local backup_path="${cfg_path}.pre-sub-manager.bak"
        cp "$cfg_path" "$backup_path" 2>/dev/null || true
        echo "Selected nginx cfg lacks 443 listener. Rebuilding bootstrap HTTPS vhost: $cfg_path"
        generate_bootstrap_nginx_cfg "$cfg_path" || return 1
        ln -sf "$cfg_path" "/etc/nginx/sites-enabled/${base_name}"
    fi
}

select_or_bootstrap_nginx_cfg() {
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

    local configs=( /etc/nginx/sites-available/* )
    if [ "${configs[0]}" = "/etc/nginx/sites-available/*" ]; then
        configs=()
    fi

    if [ ${#configs[@]} -eq 0 ]; then
        SELECTED_CFG="/etc/nginx/sites-available/${PUBLIC_DOMAIN}.conf"
        echo "No nginx site config found. Creating bootstrap vhost: $SELECTED_CFG"
        generate_bootstrap_nginx_cfg "$SELECTED_CFG" || return 1
        ln -sf "$SELECTED_CFG" "/etc/nginx/sites-enabled/$(basename "$SELECTED_CFG")"
        return 0
    fi

    if [ -n "${SELECTED_CFG:-}" ] && [ -f "${SELECTED_CFG}" ]; then
        echo "Using preselected nginx config: ${SELECTED_CFG}"
        ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
        return 0
    fi

    local exact_candidates=(
        "/etc/nginx/sites-available/${PUBLIC_DOMAIN}"
        "/etc/nginx/sites-available/${PUBLIC_DOMAIN}.conf"
    )
    local exact_cfg
    for exact_cfg in "${exact_candidates[@]}"; do
        if [ -f "$exact_cfg" ]; then
            SELECTED_CFG="$exact_cfg"
            echo "Using exact nginx config for PUBLIC_DOMAIN: ${SELECTED_CFG}"
            ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
            return 0
        fi
    done

    local cfg
    for cfg in "${configs[@]}"; do
        case "$(basename "$cfg")" in
            "${PUBLIC_DOMAIN}"|"${PUBLIC_DOMAIN}.conf")
                SELECTED_CFG="$cfg"
                echo "Auto-selected nginx config for PUBLIC_DOMAIN: ${SELECTED_CFG}"
                ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
                return 0
                ;;
        esac
    done

    if [ ${#configs[@]} -eq 1 ]; then
        SELECTED_CFG="${configs[0]}"
        echo "Using the only available nginx config: ${SELECTED_CFG}"
        ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
        return 0
    fi

    if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ]; then
        SELECTED_CFG="/etc/nginx/sites-available/${PUBLIC_DOMAIN}.conf"
        if [ ! -f "$SELECTED_CFG" ]; then
            echo "Automation mode: creating dedicated nginx config for PUBLIC_DOMAIN: ${SELECTED_CFG}"
            generate_bootstrap_nginx_cfg "$SELECTED_CFG" || return 1
            ln -sf "$SELECTED_CFG" "/etc/nginx/sites-enabled/$(basename "$SELECTED_CFG")"
        else
            echo "Automation mode: using existing nginx config for PUBLIC_DOMAIN: ${SELECTED_CFG}"
        fi
        ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
        return 0
    fi

    echo -e "\nSelect nginx config from the list:"
    for i in "${!configs[@]}"; do echo "$i) $(basename "${configs[$i]}")"; done
    read -p "Enter index: " cfg_idx
    if ! [[ "$cfg_idx" =~ ^[0-9]+$ ]] || [ "$cfg_idx" -ge ${#configs[@]} ]; then
        echo "Invalid index."
        return 1
    fi
    SELECTED_CFG="${configs[$cfg_idx]}"
    ensure_selected_nginx_cfg_https_ready "${SELECTED_CFG}" || return 1
}

ensure_nginx_snippet_include_in_cfg() {
    local cfg_path="$1"
    local include_line="    include /etc/nginx/snippets/${PROJECT_NAME}.conf;"

    if [ ! -f "$cfg_path" ]; then
        echo "⚠️ Nginx cfg не найден: $cfg_path"
        return 1
    fi

    CFG_PATH="$cfg_path" INCLUDE_LINE="$include_line" python3 <<'PYTHON'
from pathlib import Path
import os

cfg_path = Path(os.environ["CFG_PATH"])
include_line = os.environ["INCLUDE_LINE"]
lines = cfg_path.read_text().splitlines()

cleaned = []
brace_depth = 0
server_depth = None
include_present = False

for line in lines:
    stripped = line.strip()
    comment = stripped.startswith('#')
    current_depth = brace_depth

    if stripped == include_line.strip():
        if not comment and server_depth is not None and current_depth >= server_depth:
            if not include_present:
                cleaned.append(include_line)
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
        result.append(include_line)
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
            result.insert(idx, include_line)
            inserted = True
            break

cfg_path.write_text('\n'.join(result) + '\n')
print("changed" if inserted else "unchanged")
PYTHON
}

ensure_nginx_http_mime_types() {
    local nginx_conf="/etc/nginx/nginx.conf"
    [ -f "$nginx_conf" ] || return 0

    NGINX_CONF_PATH="$nginx_conf" python3 <<'PYTHON'
from pathlib import Path
import re
import os

path = Path(os.environ["NGINX_CONF_PATH"])
text = path.read_text()

if re.search(r'(^|\n)\s*http\s*\{', text) is None:
    raise SystemExit(0)

if 'include /etc/nginx/mime.types;' in text:
    raise SystemExit(0)

lines = text.splitlines()
out = []
in_http = False
inserted = False
depth = 0

for line in lines:
    stripped = line.strip()
    if not in_http and re.match(r'^\s*http\s*\{\s*$', line):
        in_http = True
        depth = 1
        out.append(line)
        continue

    if in_http:
        if stripped.startswith('#'):
            out.append(line)
            continue

        opens = line.count('{')
        closes = line.count('}')

        if not inserted and 'default_type' in stripped:
            indent = re.match(r'^(\s*)', line).group(1)
            out.append(f"{indent}include /etc/nginx/mime.types;")
            inserted = True

        out.append(line)
        depth += opens - closes

        if depth <= 0:
            in_http = False
        continue

    out.append(line)

if not inserted:
    final = []
    in_http = False
    depth = 0
    for line in out:
        stripped = line.strip()
        if not in_http and re.match(r'^\s*http\s*\{\s*$', line):
            in_http = True
            depth = 1
            final.append(line)
            final.append('    include /etc/nginx/mime.types;')
            inserted = True
            continue
        final.append(line)
        if in_http and not stripped.startswith('#'):
            depth += line.count('{') - line.count('}')
            if depth <= 0:
                in_http = False
    out = final

if inserted:
    path.write_text("\n".join(out) + "\n")
PYTHON
}

install_adguard_home_binary() {
    if [ -x /opt/AdGuardHome/AdGuardHome ]; then
        return 0
    fi

    local arch
    arch="$(uname -m 2>/dev/null || echo x86_64)"
    case "$arch" in
        x86_64|amd64) arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        armv7l|armv7) arch="armv7" ;;
        *)
            echo "❌ Unsupported architecture for AdGuardHome auto-install: ${arch}"
            return 1
            ;;
    esac

    apt_install curl tar wget >/dev/null 2>&1 || true

    local tmp_dir
    local archive_path
    local download_url
    local download_ok="false"
    local -a download_urls
    tmp_dir="$(mktemp -d)"
    archive_path="${tmp_dir}/AdGuardHome.tar.gz"
    download_urls=(
        "https://static.adguard.com/adguardhome/release/AdGuardHome_linux_${arch}.tar.gz"
        "https://github.com/AdguardTeam/AdGuardHome/releases/latest/download/AdGuardHome_linux_${arch}.tar.gz"
    )

    for download_url in "${download_urls[@]}"; do
        echo "Скачивание AdGuard Home: ${download_url}"
        if curl -fL \
            --retry 3 \
            --retry-all-errors \
            --retry-delay 2 \
            --connect-timeout 15 \
            --max-time 300 \
            --speed-time 30 \
            --speed-limit 10240 \
            -A "Mozilla/5.0" \
            "$download_url" \
            -o "$archive_path"; then
            download_ok="true"
            break
        fi

        echo "⚠️ curl download failed or timed out for ${download_url}. Trying wget fallback..."
        if wget \
            --tries=3 \
            --timeout=30 \
            --read-timeout=120 \
            --user-agent="Mozilla/5.0" \
            -O "$archive_path" \
            "$download_url"; then
            download_ok="true"
            break
        fi
    done

    if [ "$download_ok" != "true" ]; then
        echo "❌ Не удалось скачать AdGuard Home архив (all mirrors failed)."
        rm -rf "$tmp_dir"
        return 1
    fi

    if ! tar -xzf "$archive_path" -C "$tmp_dir"; then
        rm -rf "$tmp_dir"
        return 1
    fi

    mkdir -p /opt
    rm -rf /opt/AdGuardHome
    cp -r "${tmp_dir}/AdGuardHome" /opt/AdGuardHome
    chmod +x /opt/AdGuardHome/AdGuardHome
    rm -rf "$tmp_dir"

    if ! /opt/AdGuardHome/AdGuardHome -s install >/dev/null 2>&1; then
        # Some hosts already have service skeletons; continue if binary is present.
        [ -x /opt/AdGuardHome/AdGuardHome ] || return 1
    fi

    return 0
}

configure_adguard_home() {
    if [ "${ADGUARD_INSTALL_ENABLED:-false}" != "true" ]; then
        return 0
    fi

    ADGUARD_WEB_PATH="$(echo "${ADGUARD_WEB_PATH:-$(generate_random_path)}" | tr -cd '[:alnum:]')"
    ADGUARD_DOH_PATH="$(echo "${ADGUARD_DOH_PATH:-$(generate_random_path)}" | tr -cd '[:alnum:]')"
    ADGUARD_ADMIN_USER="$(echo "${ADGUARD_ADMIN_USER:-adg$(generate_random_path)}" | tr -cd '[:alnum:]')"
    ADGUARD_ADMIN_PASS="${ADGUARD_ADMIN_PASS:-$(generate_random_secret 20)}"
    [ -n "$ADGUARD_WEB_PATH" ] || ADGUARD_WEB_PATH="$(generate_random_path)"
    [ -n "$ADGUARD_DOH_PATH" ] || ADGUARD_DOH_PATH="$(generate_random_path)"
    [ -n "$ADGUARD_ADMIN_USER" ] || ADGUARD_ADMIN_USER="adg$(generate_random_path)"

    local dns_host dns_port
    dns_host="$(extract_host_from_bind "${ADGUARD_DNS_BIND:-127.0.0.1:5353}")"
    dns_port="$(extract_port_from_bind "${ADGUARD_DNS_BIND:-127.0.0.1:5353}")"
    local adguard_setup_web_port
    adguard_setup_web_port=$((ADGUARD_WEB_PORT + 1))
    if [ "$adguard_setup_web_port" -le 0 ] || [ "$adguard_setup_web_port" -gt 65535 ]; then
        adguard_setup_web_port=3001
    fi

    echo "Настройка AdGuard Home..."
    if ! install_adguard_home_binary; then
        echo "❌ Не удалось установить AdGuard Home binary."
        return 1
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable AdGuardHome >/dev/null 2>&1 || true
    systemctl restart AdGuardHome >/dev/null 2>&1 || true

    local i status_code=""
    for i in 1 2 3 4 5 6 7 8 9 10; do
        status_code="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${ADGUARD_WEB_PORT}/" 2>/dev/null || true)"
        if [[ "$status_code" =~ ^(200|301|302|303|307|308)$ ]]; then
            break
        fi
        sleep 1
    done

    local setup_code=""
    setup_code="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${ADGUARD_WEB_PORT}/control/install/get_addresses" 2>/dev/null || true)"
    if [[ "$setup_code" =~ ^(200|204)$ ]]; then
        local payload
        payload="$(cat <<EOF
    {"web":{"ip":"127.0.0.1","port":${adguard_setup_web_port}},"dns":{"ip":"${dns_host}","port":${dns_port}},"username":"${ADGUARD_ADMIN_USER}","password":"${ADGUARD_ADMIN_PASS}"}
EOF
)"
        if ! curl -fsS -X POST "http://127.0.0.1:${ADGUARD_WEB_PORT}/control/install/configure" \
            -H "Content-Type: application/json" \
            --data "$payload" >/dev/null 2>&1; then
            echo "⚠️ Не удалось завершить первичный setup AdGuard через API (возможно уже настроен ранее)."
        fi
    fi

    # Ensure bcrypt is available so we can enforce generated credentials in YAML.
    if ! python3 -c 'import bcrypt' >/dev/null 2>&1; then
        apt_install python3-bcrypt >/dev/null 2>&1 || true
    fi
    if ! python3 -c 'import bcrypt' >/dev/null 2>&1; then
        echo "❌ Не удалось загрузить модуль bcrypt (python3-bcrypt)."
        echo "   Невозможно гарантировать синхронизацию сгенерированного пароля AdGuard."
        return 1
    fi

    # Enforce critical fields in YAML for idempotent reruns.
    python3 - "$dns_host" "$dns_port" "${ADGUARD_WEB_PORT}" "${ADGUARD_ADMIN_USER}" "${ADGUARD_ADMIN_PASS}" <<'PY'
from pathlib import Path
import re
import sys
import bcrypt

dns_host = sys.argv[1]
dns_port = sys.argv[2]
web_port = sys.argv[3]
admin_user = sys.argv[4]
admin_pass = sys.argv[5]
cfg = Path('/opt/AdGuardHome/AdGuardHome.yaml')

if not cfg.exists():
    raise SystemExit(0)

text = cfg.read_text(encoding='utf-8', errors='ignore')

def replace_block(text: str, key: str, replacement: str) -> str:
    pattern = rf'(?ms)^{re.escape(key)}:\n(?:^[ \t].*\n?)*'
    if re.search(pattern, text):
        return re.sub(pattern, replacement, text, count=1)
    if not text.endswith('\n'):
        text += '\n'
    return text + replacement

text = replace_block(text, 'http', f'http:\n  address: 127.0.0.1:{web_port}\n')
text = replace_block(text, 'dns', f'dns:\n  bind_hosts:\n    - {dns_host}\n  port: {dns_port}\n')
hashed_pass = bcrypt.hashpw(admin_pass.encode('utf-8'), bcrypt.gensalt(rounds=10)).decode('utf-8')
text = replace_block(text, 'users', f'users:\n  - name: {admin_user}\n    password: {hashed_pass}\n')

cfg.write_text(text, encoding='utf-8')
PY

    systemctl restart AdGuardHome >/dev/null 2>&1 || true

    local metrics_status=""
    metrics_status="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${ADGUARD_WEB_PORT}${ADGUARD_METRICS_PATH:-/control/prometheus/metrics}" 2>/dev/null || true)"
    if [[ "$metrics_status" =~ ^(200|401|403)$ ]]; then
        echo "✓ AdGuard Home поднят (metrics endpoint HTTP ${metrics_status})"
    else
        echo "⚠️ AdGuard Home запущен, но metrics endpoint вернул HTTP ${metrics_status:-000}"
    fi
}

configure_monitoring_stack() {
    if [ "${MONITORING_ENABLED:-true}" != "true" ]; then
        echo "Мониторинг отключен: пропускаем настройку Prometheus/Grafana."
        return 0
    fi

    echo "Настройка Prometheus + Grafana..."
    if ! ensure_grafana_repo; then
        echo "⚠️ Репозиторий Grafana недоступен. Пробуем fallback установку из .deb..."
    fi

    apt_install prometheus >/dev/null 2>&1 || {
        echo "❌ Не удалось установить prometheus."
        return 1
    }

    if ! apt_install grafana >/dev/null 2>&1; then
        echo "⚠️ Установка grafana через APT не удалась. Пробуем fallback .deb..."
        if ! install_grafana_with_fallback_deb; then
            echo "❌ Не удалось установить Grafana ни через APT, ни через .deb fallback."
            return 1
        fi
    fi

    local adguard_scrape_block=""
    local adguard_metrics_enabled="${ADGUARD_METRICS_ENABLED:-false}"
    local adguard_metrics_targets="${ADGUARD_METRICS_TARGETS:-}"
    local adguard_metrics_path="${ADGUARD_METRICS_PATH:-/control/prometheus/metrics}"
    local adguard_loki_enabled="${ADGUARD_LOKI_ENABLED:-false}"
    local adguard_querylog_path="${ADGUARD_QUERYLOG_PATH:-/opt/AdGuardHome/data/querylog.json}"
    local adguard_systemd_unit="${ADGUARD_SYSTEMD_UNIT:-AdGuardHome.service}"
    local has_adguard_targets="false"
    local loki_ready="false"

    if [ "$adguard_metrics_enabled" = "true" ] && [ -n "$adguard_metrics_targets" ]; then
        local adguard_targets_count=0
        adguard_scrape_block="
  - job_name: adguard-home
    metrics_path: ${adguard_metrics_path}
    scrape_interval: 30s
    static_configs:
      - targets:"
        IFS=',' read -ra _adguard_targets <<< "$adguard_metrics_targets"
        local target
        for target in "${_adguard_targets[@]}"; do
            target="$(echo "$target" | xargs)"
            if [ -n "$target" ]; then
                adguard_scrape_block="${adguard_scrape_block}
          - '${target}'"
                adguard_targets_count=$((adguard_targets_count + 1))
            fi
        done
        if [ "$adguard_targets_count" -gt 0 ]; then
            has_adguard_targets="true"
        else
            adguard_scrape_block=""
        fi
    fi

    mkdir -p /etc/prometheus/rules
    cp "$SCRIPT_DIR/monitoring/prometheus/rules.yml" /etc/prometheus/rules/sub-manager-rules.yml
    cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/rules/sub-manager-rules.yml

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['127.0.0.1:9090']

  - job_name: sub-manager
    metrics_path: /metrics
    static_configs:
      - targets: ['127.0.0.1:${APP_PORT}']
${adguard_scrape_block}
EOF

    mkdir -p /etc/grafana/provisioning/datasources
    mkdir -p /etc/grafana/provisioning/dashboards
    mkdir -p /var/lib/grafana/dashboards

    cat > /etc/grafana/provisioning/datasources/sub-manager-prometheus.yml <<'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
    editable: false
EOF

    if [ "$adguard_loki_enabled" = "true" ] && resource_guard_should_skip_optional_logs; then
        echo "⚠️ Very low-resource host detected. Skipping Loki/promtail to keep install stable."
        adguard_loki_enabled="false"
    fi

    if [ "$adguard_loki_enabled" = "true" ]; then
        if install_loki_promtail_stack; then
            mkdir -p /etc/loki /etc/promtail /var/lib/loki /var/lib/promtail
            cp "$SCRIPT_DIR/monitoring/loki/loki-config.yml" /etc/loki/config.yml
            cp "$SCRIPT_DIR/monitoring/loki/loki-config.yml" /etc/loki/local-config.yaml
            cp "$SCRIPT_DIR/monitoring/promtail/promtail-config.yml" /etc/promtail/config.yml
            sed -i "s|__ADGUARD_QUERYLOG_PATH__|${adguard_querylog_path}|g" /etc/promtail/config.yml
            sed -i "s|__ADGUARD_SYSTEMD_UNIT__|${adguard_systemd_unit}|g" /etc/promtail/config.yml
            chown -R loki /var/lib/loki >/dev/null 2>&1 || true
            chown -R promtail /var/lib/promtail >/dev/null 2>&1 || true
            chmod 0755 /var/lib/loki /var/lib/promtail >/dev/null 2>&1 || true
            resource_guard_restart_services_sequentially loki promtail
            loki_ready="true"
            echo "✓ Loki и promtail настроены."
        else
            echo "⚠️ Не удалось установить loki/promtail. Продолжаем без логов AdGuard."
        fi
    fi

    if [ "$loki_ready" = "true" ]; then
        cat > /etc/grafana/provisioning/datasources/sub-manager-prometheus.yml <<'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
    editable: false
  - name: Loki
    type: loki
    access: proxy
    url: http://127.0.0.1:3100
    editable: false
EOF
    fi

    cat > /etc/grafana/provisioning/dashboards/sub-manager-dashboard.yml <<'EOF'
apiVersion: 1
providers:
  - name: SubManager
    orgId: 1
    folder: SubManager
    type: file
    disableDeletion: false
    editable: true
    updateIntervalSeconds: 180
    options:
      path: /var/lib/grafana/dashboards
EOF

    cp "$SCRIPT_DIR/monitoring/grafana/sub-manager-dashboard.json" /var/lib/grafana/dashboards/sub-manager-dashboard.json
    if [ "$has_adguard_targets" = "true" ] || [ "$loki_ready" = "true" ]; then
        cp "$SCRIPT_DIR/monitoring/grafana/adguard-overview-dashboard.json" /var/lib/grafana/dashboards/adguard-overview-dashboard.json
    else
        rm -f /var/lib/grafana/dashboards/adguard-overview-dashboard.json
    fi
    chown -R grafana:grafana /var/lib/grafana/dashboards

    python3 <<PYTHON
import configparser
cfg = configparser.RawConfigParser()
cfg.read('/etc/grafana/grafana.ini')
if 'server' not in cfg:
    cfg['server'] = {}
cfg['server']['protocol'] = 'http'
cfg['server']['domain'] = '${PUBLIC_DOMAIN}'
cfg['server']['root_url'] = '${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${GRAFANA_WEB_PATH}/'
cfg['server']['serve_from_sub_path'] = 'true'
cfg['server']['http_addr'] = '127.0.0.1'
cfg['server']['http_port'] = '${GRAFANA_HTTP_PORT}'
if 'security' not in cfg:
    cfg['security'] = {}
cfg['security']['allow_embedding'] = 'true'
cfg['security']['cookie_samesite'] = 'lax'
if 'auth.anonymous' not in cfg:
    cfg['auth.anonymous'] = {}
cfg['auth.anonymous']['enabled'] = 'false'
if 'users' not in cfg:
    cfg['users'] = {}
cfg['users']['allow_sign_up'] = 'false'
if 'log' not in cfg:
    cfg['log'] = {}
cfg['log']['level'] = 'warn'
with open('/etc/grafana/grafana.ini', 'w') as f:
    cfg.write(f)
PYTHON

    systemctl daemon-reload
    resource_guard_restart_services_sequentially prometheus grafana-server

    local grafana_ready="false"
    local grafana_status=""
    local i
    for i in 1 2 3 4 5 6; do
        grafana_status="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GRAFANA_HTTP_PORT}/login" 2>/dev/null || true)"
        if [[ "$grafana_status" =~ ^(200|301|302)$ ]]; then
            grafana_ready="true"
            break
        fi
        sleep 2
    done

    if [ "$grafana_ready" != "true" ]; then
        echo "⚠️ Grafana upstream not ready after first start (HTTP ${grafana_status:-000}). Retrying restart once..."
        resource_guard_restart_services_sequentially grafana-server
        for i in 1 2 3 4 5 6; do
            grafana_status="$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GRAFANA_HTTP_PORT}/login" 2>/dev/null || true)"
            if [[ "$grafana_status" =~ ^(200|301|302)$ ]]; then
                grafana_ready="true"
                break
            fi
            sleep 2
        done
    fi

    if [ "$grafana_ready" = "true" ]; then
        echo "✓ Grafana upstream ready on 127.0.0.1:${GRAFANA_HTTP_PORT} (HTTP ${grafana_status})"
    else
        echo "⚠️ Grafana upstream is still not ready (HTTP ${grafana_status:-000}). Public /${GRAFANA_WEB_PATH}/ may return 502 until service stabilizes."
    fi
    echo "✓ Prometheus и Grafana настроены."
}

generate_nginx_snippet() {
    local snippet_file="$1"
    local mtls_directives=""
    local allowlist_directives=""

    if [ "${SECURITY_MTLS_ENABLED:-false}" = "true" ] && [ -n "${SECURITY_MTLS_CA_PATH:-}" ]; then
        mtls_directives="    ssl_client_certificate ${SECURITY_MTLS_CA_PATH};
    ssl_verify_client on;
    ssl_verify_depth 2;
    if (\$ssl_client_verify != SUCCESS) { return 403; }
"
    fi

    if [ -n "${SECURITY_IP_ALLOWLIST:-}" ]; then
        allowlist_directives="    allow 127.0.0.1;
    allow ::1;
"
        IFS=',' read -ra _allow_entries <<< "$SECURITY_IP_ALLOWLIST"
        for entry in "${_allow_entries[@]}"; do
            entry="$(echo "$entry" | xargs)"
            if [ -n "$entry" ]; then
                allowlist_directives="${allowlist_directives}    allow ${entry};
"
            fi
        done
        allowlist_directives="${allowlist_directives}    deny all;
"
    fi

cat > "$snippet_file" <<SNIPPET
# Generated by $PROJECT_NAME installer. Run ./update.sh -> option 4 to regenerate.
# DO NOT EDIT MANUALLY - changes will be overwritten on update.

# --- API proxy (must precede the UI catch-all location) ---
location ^~ /$WEB_PATH/api/ {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/api/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_intercept_errors off;
    proxy_buffering off;
    proxy_request_buffering off;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;
}

# --- WebSocket ---
location ^~ /$WEB_PATH/ws {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    add_header Cache-Control "no-store" always;
}

# --- Swagger UI / ReDoc docs ---
location = /$WEB_PATH/docs {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/docs;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /$WEB_PATH/docs/ {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/docs/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/openapi.json {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/openapi.json;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/redoc {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/redoc;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/health {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$APP_PORT/health;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
SNIPPET

    if [ "${MONITORING_ENABLED:-true}" = "true" ]; then
        cat >> "$snippet_file" <<SNIPPET

# --- Grafana under dedicated path ---
location = /$GRAFANA_WEB_PATH {
    return 301 /$GRAFANA_WEB_PATH/;
}
location ^~ /$GRAFANA_WEB_PATH/ {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$GRAFANA_HTTP_PORT;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
}
SNIPPET
    fi

    if [ "${ADGUARD_INSTALL_ENABLED:-false}" = "true" ]; then
        cat >> "$snippet_file" <<SNIPPET

# --- AdGuard Home panel under random path ---
location = /$ADGUARD_WEB_PATH {
    return 301 /$ADGUARD_WEB_PATH/;
}
location ^~ /$ADGUARD_WEB_PATH/ {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$ADGUARD_WEB_PORT/;
    absolute_redirect off;
    port_in_redirect off;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-Port \$server_port;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Script-Name /$ADGUARD_WEB_PATH;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_redirect ~^https?://[^/]+:7443/(.*)$ /\$1;
    proxy_redirect ~^https?://127\\.0\\.0\\.1(?::\d+)?/(.*)$ https://\$host/$ADGUARD_WEB_PATH/\$1;
    proxy_redirect / /$ADGUARD_WEB_PATH/;
}

# --- AdGuard Home DoH under random path ---
location = /$ADGUARD_DOH_PATH {
    return 307 /$ADGUARD_DOH_PATH/;
}
location ^~ /$ADGUARD_DOH_PATH/ {
${mtls_directives}${allowlist_directives}    proxy_pass http://127.0.0.1:$ADGUARD_WEB_PORT/dns-query;
    absolute_redirect off;
    port_in_redirect off;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-Port \$server_port;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_redirect ~^https?://[^/]+:7443/dns-query/?$ /$ADGUARD_DOH_PATH/;
    proxy_redirect ~^https?://127\\.0\\.0\\.1(?::\d+)?/(.*)$ https://\$host/$ADGUARD_DOH_PATH/\$1;
    proxy_redirect / /$ADGUARD_DOH_PATH/;
}
SNIPPET
    fi

    cat >> "$snippet_file" <<SNIPPET

# --- Root favicon fallback (browser requests /favicon.ico) ---
location = /favicon.ico {
    alias $PROJECT_DIR/build/favicon.ico;
    access_log off;
    log_not_found off;
    expires 1d;
}

# --- Canonical slash redirect for panel root ---
location = /$WEB_PATH {
    return 301 \$scheme://\$host/$WEB_PATH/;
}

# --- Panel index file ---
location = /$WEB_PATH/ {
    root $PROJECT_DIR/build;
    try_files /index.html =404;
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;
}

# --- Static assets (hashed, immutable cache, hard 404 on miss) ---
# MUST precede the SPA catch-all so missing assets never serve index.html,
# which would poison the service worker cache (white-screen-on-first-visit bug).
location ^~ /$WEB_PATH/assets/ {
    rewrite ^/$WEB_PATH/(.*)$ /\$1 break;
    root $PROJECT_DIR/build;
    try_files \$uri =404;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
    add_header X-Content-Type-Options "nosniff" always;
}

# --- React SPA (static files + SPA fallback) ---
location ^~ /$WEB_PATH/ {
    rewrite ^/$WEB_PATH/(.*)$ /\$1 break;
    root $PROJECT_DIR/build;
    try_files \$uri \$uri/ /index.html;
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;
}
SNIPPET
}

run_post_install_checks() {
    echo -e "\nПроверка запуска сервиса..."
    local failures=0

    resource_guard_detect_profile

    local health_status=""
    for i in 1 2 3 4 5; do
        sleep 2
        health_status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/health" 2>/dev/null)
        [ "$health_status" = "200" ] && break
    done
    if [ "$health_status" = "200" ]; then
        echo "✅ Health check: /health -> HTTP 200"
    else
        echo "❌ Health check: /health -> HTTP ${health_status:-000}"
        failures=$((failures + 1))
    fi

    local ws_status=""
    ws_status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Connection: Upgrade" \
        -H "Upgrade: websocket" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: SGVsbG8sV29ybGQhIQ==" \
        "http://127.0.0.1:${APP_PORT}/ws" 2>/dev/null)
    if [[ "$ws_status" =~ ^(101|400|401|403|426)$ ]]; then
        echo "✅ WebSocket upstream доступен (HTTP $ws_status)"
    else
        echo "⚠️ WebSocket upstream подозрительный ответ: HTTP ${ws_status:-000}"
        failures=$((failures + 1))
    fi

    local snippet_file="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    if [ -f "$snippet_file" ]; then
        if grep -q "rewrite \^/${GRAFANA_WEB_PATH}/" "$snippet_file"; then
            echo "❌ Обнаружен опасный rewrite для Grafana в snippet: $snippet_file"
        else
            echo "✅ Nginx snippet без rewrite-петли Grafana"
        fi
    fi

    if [ -f "$PROJECT_DIR/build/favicon.ico" ]; then
        echo "✅ favicon.ico присутствует в build"
    else
        echo "⚠️ favicon.ico отсутствует в build: $PROJECT_DIR/build/favicon.ico"
        failures=$((failures + 1))
    fi

    local panel_status=""
    panel_status=$(curl -ksS -o /dev/null -w "%{http_code}" "${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${WEB_PATH}/" 2>/dev/null || true)
    if [[ "$panel_status" =~ ^(200|301|302)$ ]]; then
        echo "✅ Публичная панель доступна (HTTP $panel_status)"
    else
        echo "❌ Публичная панель недоступна: HTTP ${panel_status:-000}"
        failures=$((failures + 1))
    fi

    if [ "${MONITORING_ENABLED:-false}" = "true" ]; then
        local g_status=""
        for i in 1 2 3 4 5; do
            g_status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GRAFANA_HTTP_PORT}/login" 2>/dev/null)
            if [[ "$g_status" =~ ^(200|301|302)$ ]]; then
                break
            fi
            sleep 2
        done
        if [[ "$g_status" =~ ^(200|301|302)$ ]]; then
            echo "✅ Grafana upstream доступен (HTTP $g_status)"
        else
            echo "⚠️ Grafana upstream недоступен или нестандартный код: HTTP ${g_status:-000}"
            if [ "${RESOURCE_LOW_RESOURCE_MODE:-false}" != "true" ]; then
                failures=$((failures + 1))
            fi
        fi
    fi

    if [ "${ADGUARD_INSTALL_ENABLED:-false}" = "true" ]; then
        local adg_panel_status=""
        local adg_doh_status=""
        adg_panel_status=$(curl -ksS -o /dev/null -w "%{http_code}" "${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${ADGUARD_WEB_PATH}/" 2>/dev/null || true)
        if [[ "$adg_panel_status" =~ ^(200|301|302)$ ]]; then
            echo "✅ AdGuard панель доступна (HTTP $adg_panel_status)"
        else
            echo "❌ AdGuard панель недоступна: HTTP ${adg_panel_status:-000}"
            failures=$((failures + 1))
        fi

        adg_doh_status=$(curl -ksS -o /dev/null -w "%{http_code}" "${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${ADGUARD_DOH_PATH}/" 2>/dev/null || true)
        if [[ "$adg_doh_status" =~ ^(200|302|307|308|400|401|403|404|405)$ ]]; then
            echo "✅ AdGuard DoH endpoint отвечает (HTTP $adg_doh_status)"
        else
            echo "⚠️ AdGuard DoH endpoint вернул неожиданный код: HTTP ${adg_doh_status:-000}"
            failures=$((failures + 1))
        fi
    fi

    return "$failures"
}

configure_fail2ban_security() {
    mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d

    local ssh_port_safe
    ssh_port_safe="$(normalize_tcp_port "${SSH_PORT:-22}" "22")"
    SSH_PORT="$ssh_port_safe"

    cat > /etc/fail2ban/filter.d/multi-manager-api.conf <<'EOF'
[Definition]
# Match auth failures from Sub-Manager API and WebSocket handshake.
failregex = ^<HOST> -.*"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) .*/api/v1/.*" (401|403)
            ^<HOST> -.*"GET .*/ws(\?.*)? HTTP/.*" (401|403)
EOF

    local panel_path_regex="$WEB_PATH"
    if [ "${MONITORING_ENABLED:-false}" = "true" ] && [ -n "${GRAFANA_WEB_PATH:-}" ]; then
        panel_path_regex="${panel_path_regex}|${GRAFANA_WEB_PATH}"
    fi
    if [ "${ADGUARD_INSTALL_ENABLED:-false}" = "true" ] && [ -n "${ADGUARD_WEB_PATH:-}" ]; then
        panel_path_regex="${panel_path_regex}|${ADGUARD_WEB_PATH}"
    fi
    panel_path_regex="${panel_path_regex}|admin|login|signin|auth"

    cat > /etc/fail2ban/filter.d/multi-panels-auth.conf <<EOF
[Definition]
# Broad panel auth protection for nginx-backed panels (Sub-Manager/Grafana/AdGuard/other login endpoints).
failregex = ^<HOST> -.*"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /(${panel_path_regex})(/.*)? HTTP/.*" (401|403)
EOF

    cat > /etc/fail2ban/jail.d/multi-manager.local <<EOF
[multi-manager-api]
enabled  = true
port     = http,https
filter   = multi-manager-api
logpath  = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime  = 300

[multi-panels-auth]
enabled  = true
port     = http,https
filter   = multi-panels-auth
logpath  = /var/log/nginx/access.log
maxretry = 8
findtime = 600
bantime  = 1800

[sshd-custom]
enabled  = true
port     = ${ssh_port_safe}
filter   = sshd
backend  = systemd
maxretry = 6
findtime = 600
bantime  = 3600
EOF

    systemctl enable fail2ban >/dev/null 2>&1 || true
    systemctl restart fail2ban >/dev/null 2>&1 || true
}

configure_ufw_firewall() {
    local ssh_port_safe
    ssh_port_safe="$(normalize_tcp_port "${SSH_PORT:-22}" "22")"
    SSH_PORT="$ssh_port_safe"

    apt_install ufw >/dev/null 2>&1 || true
    if ! command -v ufw >/dev/null 2>&1; then
        echo "⚠️ ufw не найден, пропускаем настройку firewall."
        return 0
    fi

    ufw --force default deny incoming >/dev/null 2>&1 || true
    ufw --force default allow outgoing >/dev/null 2>&1 || true
    ufw allow 80/tcp >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    ufw allow "${ssh_port_safe}/tcp" >/dev/null 2>&1 || true
    ufw --force enable >/dev/null 2>&1 || true
}

uninstall() {
    echo -e "\n--- Удаление и откат настроек ---"
    if [ ! -f "$LOG_FILE" ]; then echo "Лог не найден."; return 1; fi
    source "$LOG_FILE"
    systemctl stop "$PROJECT_NAME" 2>/dev/null
    systemctl disable "$PROJECT_NAME" 2>/dev/null
    rm -f "/etc/systemd/system/$PROJECT_NAME.service"
    rm -f "/etc/fail2ban/jail.d/multi-manager.local"
    rm -f "/etc/fail2ban/filter.d/multi-manager.conf"
    rm -f "/etc/fail2ban/filter.d/multi-manager-api.conf"
    rm -f "/etc/fail2ban/filter.d/multi-panels-auth.conf"
    systemctl daemon-reload
    systemctl restart fail2ban
    if [ -f "${SELECTED_CFG}.bak" ]; then
        mv "${SELECTED_CFG}.bak" "$SELECTED_CFG"
        sanitize_nginx_sites_for_stream_443
        nginx -t && systemctl restart nginx
    fi
    rm -rf "$PROJECT_DIR" "$LOG_FILE"
    echo "Система полностью очищена."
}

uninstall_nuke() {
    echo -e "\n--- ПОЛНОЕ УДАЛЕНИЕ ВСЕГО (NUKE) ---"
    if [ "$EUID" -ne 0 ]; then
        echo "Запустите от root!"
        return 1
    fi

    local project_name="${PROJECT_NAME:-sub-manager}"
    local project_dir="${PROJECT_DIR:-/opt/sub-manager}"
    local selected_cfg="${SELECTED_CFG:-}"

    if [ -f "$LOG_FILE" ]; then
        # shellcheck disable=SC1090
        source "$LOG_FILE"
        project_name="${PROJECT_NAME:-$project_name}"
        project_dir="${PROJECT_DIR:-$project_dir}"
        selected_cfg="${SELECTED_CFG:-$selected_cfg}"
    fi

    if [ -z "$selected_cfg" ]; then
        selected_cfg=$(grep -Rls "include /etc/nginx/snippets/${project_name}.conf" \
            /etc/nginx/sites-available /etc/nginx/conf.d 2>/dev/null | head -n1)
    fi

    echo "Будет удалено:"
    echo "  - сервис: ${project_name}"
    echo "  - каталог проекта: ${project_dir}"
    echo "  - nginx snippet: /etc/nginx/snippets/${project_name}.conf"
    echo "  - fail2ban rules multi-manager"
    echo "  - sub-manager provisioning для Prometheus/Grafana"
    echo "  - install log: $LOG_FILE"
    echo ""

    read -r -p "Подтвердите удаление (yes/no): " confirm1
    if [ "$confirm1" != "yes" ]; then
        echo "Отменено."
        return 0
    fi
    read -r -p "Введите фразу 'УДАЛИТЬ ВСЕ' для подтверждения: " confirm2
    if [ "$confirm2" != "УДАЛИТЬ ВСЕ" ]; then
        echo "Фраза не совпала. Отменено."
        return 1
    fi

    systemctl stop "$project_name" 2>/dev/null || true
    systemctl disable "$project_name" 2>/dev/null || true
    rm -f "/etc/systemd/system/${project_name}.service"
    systemctl daemon-reload

    rm -f "/etc/nginx/snippets/${project_name}.conf"
    if [ -n "$selected_cfg" ] && [ -f "${selected_cfg}.bak" ]; then
        mv -f "${selected_cfg}.bak" "$selected_cfg"
    fi
    nginx -t >/dev/null 2>&1 && systemctl restart nginx >/dev/null 2>&1 || true

    rm -f "/etc/fail2ban/jail.d/multi-manager.local"
    rm -f "/etc/fail2ban/filter.d/multi-manager.conf"
    rm -f "/etc/fail2ban/filter.d/multi-manager-api.conf"
    rm -f "/etc/fail2ban/filter.d/multi-panels-auth.conf"
    systemctl restart fail2ban >/dev/null 2>&1 || true

    rm -f /etc/prometheus/rules/sub-manager-rules.yml
    rm -f /etc/grafana/provisioning/datasources/sub-manager-prometheus.yml
    rm -f /etc/grafana/provisioning/dashboards/sub-manager-dashboard.yml
    rm -f /var/lib/grafana/dashboards/sub-manager-dashboard.json
    rm -f /var/lib/grafana/dashboards/adguard-overview-dashboard.json
    systemctl restart prometheus >/dev/null 2>&1 || true
    systemctl restart grafana-server >/dev/null 2>&1 || true

    rm -rf "$project_dir"
    rm -f "$LOG_FILE"

    local purge_candidates=()
    if [ "${PREEXISTING_PROMETHEUS_INSTALLED:-false}" != "true" ]; then purge_candidates+=("prometheus"); fi
    if [ "${PREEXISTING_GRAFANA_INSTALLED:-false}" != "true" ]; then purge_candidates+=("grafana"); fi
    if [ "${PREEXISTING_LOKI_INSTALLED:-false}" != "true" ]; then purge_candidates+=("loki"); fi
    if [ "${PREEXISTING_PROMTAIL_INSTALLED:-false}" != "true" ]; then purge_candidates+=("promtail"); fi

    if [ "${#purge_candidates[@]}" -eq 0 ]; then
        echo "Сторонние пакеты мониторинга были установлены до нас. apt purge пропущен."
        echo "✅ Полная очистка завершена."
        return 0
    fi

    echo "Кандидаты для apt purge (только то, что не было предустановлено): ${purge_candidates[*]}"
    read -r -p "Пробовать apt purge этих пакетов? (y/n, default: n): " purge_input
    purge_input=${purge_input:-n}
    if [[ "$purge_input" =~ ^[yYдД]$ ]]; then
        apt-get remove -y --purge "${purge_candidates[@]}" >/dev/null 2>&1 || true
        apt-get autoremove -y >/dev/null 2>&1 || true
    fi

    echo "✅ Полная очистка завершена."
}

update_project() {
    echo -e "\n--- Обновление проекта ---"
    if [ ! -f "$LOG_FILE" ]; then echo "Установка не найдена. Запустите установку сначала."; exit 1; fi
    source "$LOG_FILE"
    ALLOW_ORIGINS=${ALLOW_ORIGINS:-"http://localhost:5173,http://127.0.0.1:5173"}
    VERIFY_TLS=${VERIFY_TLS:-"true"}
    CA_BUNDLE_PATH=${CA_BUNDLE_PATH:-""}
    READ_ONLY_MODE=${READ_ONLY_MODE:-"false"}
    SUB_RATE_LIMIT_COUNT=${SUB_RATE_LIMIT_COUNT:-"30"}
    SUB_RATE_LIMIT_WINDOW_SEC=${SUB_RATE_LIMIT_WINDOW_SEC:-"60"}
    TRAFFIC_STATS_CACHE_TTL=${TRAFFIC_STATS_CACHE_TTL:-"20"}
    ONLINE_CLIENTS_CACHE_TTL=${ONLINE_CLIENTS_CACHE_TTL:-"20"}
    TRAFFIC_STATS_STALE_TTL=${TRAFFIC_STATS_STALE_TTL:-"120"}
    ONLINE_CLIENTS_STALE_TTL=${ONLINE_CLIENTS_STALE_TTL:-"60"}
    CLIENTS_CACHE_TTL=${CLIENTS_CACHE_TTL:-"20"}
    CLIENTS_CACHE_STALE_TTL=${CLIENTS_CACHE_STALE_TTL:-"180"}
    TRAFFIC_MAX_WORKERS=${TRAFFIC_MAX_WORKERS:-"6"}
    COLLECTOR_BASE_INTERVAL_SEC=${COLLECTOR_BASE_INTERVAL_SEC:-"10"}
    COLLECTOR_MAX_INTERVAL_SEC=${COLLECTOR_MAX_INTERVAL_SEC:-"60"}
    COLLECTOR_MAX_PARALLEL=${COLLECTOR_MAX_PARALLEL:-"4"}
    REDIS_URL=${REDIS_URL:-""}
    AUDIT_QUEUE_BATCH_SIZE=${AUDIT_QUEUE_BATCH_SIZE:-"200"}
    ROLE_VIEWERS=${ROLE_VIEWERS:-""}
    ROLE_OPERATORS=${ROLE_OPERATORS:-""}
    MONITORING_ENABLED=${MONITORING_ENABLED:-"true"}
    GRAFANA_WEB_PATH=${GRAFANA_WEB_PATH:-"grafana"}
    GRAFANA_HTTP_PORT=${GRAFANA_HTTP_PORT:-"43000"}
    ADGUARD_METRICS_ENABLED=${ADGUARD_METRICS_ENABLED:-"false"}
    ADGUARD_METRICS_TARGETS=${ADGUARD_METRICS_TARGETS:-""}
    ADGUARD_METRICS_PATH=${ADGUARD_METRICS_PATH:-"/control/prometheus/metrics"}
    ADGUARD_LOKI_ENABLED=${ADGUARD_LOKI_ENABLED:-"false"}
    ADGUARD_QUERYLOG_PATH=${ADGUARD_QUERYLOG_PATH:-"/opt/AdGuardHome/data/querylog.json"}
    ADGUARD_SYSTEMD_UNIT=${ADGUARD_SYSTEMD_UNIT:-"AdGuardHome.service"}
    ADGUARD_INSTALL_ENABLED=${ADGUARD_INSTALL_ENABLED:-"false"}
    ADGUARD_DNS_BIND=${ADGUARD_DNS_BIND:-"127.0.0.1:5353"}
    ADGUARD_WEB_PORT=${ADGUARD_WEB_PORT:-"3000"}
    ADGUARD_WEB_PATH=${ADGUARD_WEB_PATH:-""}
    ADGUARD_DOH_PATH=${ADGUARD_DOH_PATH:-""}
    ADGUARD_ADMIN_USER=${ADGUARD_ADMIN_USER:-""}
    ADGUARD_ADMIN_PASS=${ADGUARD_ADMIN_PASS:-""}
    SSH_PORT=${SSH_PORT:-"22"}
    PUBLIC_DOMAIN=${PUBLIC_DOMAIN:-"$(hostname -f)"}
    PUBLIC_SCHEME=${PUBLIC_SCHEME:-"https"}
    SECURITY_MTLS_ENABLED=${SECURITY_MTLS_ENABLED:-"false"}
    SECURITY_MTLS_CA_PATH=${SECURITY_MTLS_CA_PATH:-""}
    SECURITY_IP_ALLOWLIST=${SECURITY_IP_ALLOWLIST:-""}
    MFA_TOTP_ENABLED=${MFA_TOTP_ENABLED:-"false"}
    MFA_TOTP_USERS=${MFA_TOTP_USERS:-""}
    MFA_TOTP_WS_STRICT=${MFA_TOTP_WS_STRICT:-"false"}
    PREEXISTING_NGINX_INSTALLED=${PREEXISTING_NGINX_INSTALLED:-"false"}
    PREEXISTING_PROMETHEUS_INSTALLED=${PREEXISTING_PROMETHEUS_INSTALLED:-"false"}
    PREEXISTING_GRAFANA_INSTALLED=${PREEXISTING_GRAFANA_INSTALLED:-"false"}
    PREEXISTING_LOKI_INSTALLED=${PREEXISTING_LOKI_INSTALLED:-"false"}
    PREEXISTING_PROMTAIL_INSTALLED=${PREEXISTING_PROMTAIL_INSTALLED:-"false"}
    normalize_public_access_vars
    if [ -z "$WEB_PATH" ]; then
        VITE_BASE="/"
    else
        VITE_BASE="/${WEB_PATH}/"
    fi
    VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"
    
    echo "Остановка сервиса..."
    systemctl stop "$PROJECT_NAME"
    
    sync_backend_files
    
    echo "Обновление Python-зависимостей..."
    resource_guard_export_build_env
    resource_guard_require_free_mb "${INSTALL_PYTHON_MIN_FREE_MB:-900}" "before Python dependency refresh" "/" || exit 1
    resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
    resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements.txt"
    resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements-dev.txt"
    resource_guard_run_heavy "$PROJECT_DIR/venv/bin/python" -m pytest \
        "$SCRIPT_DIR/backend/tests/test_runtime_controls.py" \
        "$SCRIPT_DIR/backend/tests/test_security_hardening.py" \
        "$SCRIPT_DIR/backend/tests/test_api_smoke.py" \
        -q
    
    echo "Пересборка React фронтенда..."
    resource_guard_require_free_mb "${INSTALL_FRONTEND_MIN_FREE_MB:-900}" "before frontend rebuild" "/" || exit 1
    if ! resource_guard_run_heavy env PROJECT_DIR="$PROJECT_DIR" WEB_PATH="$WEB_PATH" GRAFANA_WEB_PATH="$GRAFANA_WEB_PATH" PUBLIC_SCHEME="$PUBLIC_SCHEME" PUBLIC_DOMAIN="$PUBLIC_DOMAIN" bash "$SCRIPT_DIR/scripts/deploy/build-and-publish-frontend.sh"; then
        echo "❌ Ошибка сборки/публикации фронтенда. Обновление прервано."
        exit 1
    fi
    
    echo "Запуск сервиса..."
    cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
        sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
        sed "s|666|$APP_PORT|g" | \
        sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH\"|g" | \
        sed "s|GRAFANA_WEB_PATH=.*|GRAFANA_WEB_PATH=$GRAFANA_WEB_PATH\"|g" | \
        sed "s|MONITORING_ENABLED=.*|MONITORING_ENABLED=$MONITORING_ENABLED\"|g" | \
        sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS\"|g" | \
        sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS\"|g" | \
        sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH\"|g" | \
        sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE\"|g" | \
        sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT\"|g" | \
        sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC\"|g" | \
        sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL\"|g" | \
        sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL\"|g" | \
        sed "s|TRAFFIC_STATS_STALE_TTL=.*|TRAFFIC_STATS_STALE_TTL=$TRAFFIC_STATS_STALE_TTL\"|g" | \
        sed "s|ONLINE_CLIENTS_STALE_TTL=.*|ONLINE_CLIENTS_STALE_TTL=$ONLINE_CLIENTS_STALE_TTL\"|g" | \
        sed "s|CLIENTS_CACHE_TTL=.*|CLIENTS_CACHE_TTL=$CLIENTS_CACHE_TTL\"|g" | \
        sed "s|CLIENTS_CACHE_STALE_TTL=.*|CLIENTS_CACHE_STALE_TTL=$CLIENTS_CACHE_STALE_TTL\"|g" | \
        sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS\"|g" | \
        sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC\"|g" | \
        sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC\"|g" | \
        sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL\"|g" | \
        sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL\"|g" | \
        sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE\"|g" | \
        sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS\"|g" | \
        sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS\"|g" | \
        sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED\"|g" | \
        sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS\"|g" | \
        sed "s|MFA_TOTP_WS_STRICT=.*|MFA_TOTP_WS_STRICT=$MFA_TOTP_WS_STRICT\"|g" > \
        "/etc/systemd/system/$PROJECT_NAME.service"
    systemctl daemon-reload
    systemctl start "$PROJECT_NAME"

    configure_monitoring_stack
    configure_adguard_home
    configure_fail2ban_security
    configure_ufw_firewall
    SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    mkdir -p /etc/nginx/snippets
    generate_nginx_snippet "$SNIPPET_FILE"
    ensure_nginx_http_mime_types
    sanitize_nginx_sites_for_stream_443
    nginx -t && systemctl restart nginx
    
    echo -e "\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!"
    echo -e "\033[1;35m******** ДОСТУПЫ ********\033[0m"
    echo -e "\033[1;36mПанель\033[0m"
    echo "  Путь: /$WEB_PATH/"
    echo "  Способ подключения: Nginx reverse proxy -> FastAPI (логин/пароль системы)"
    echo "  URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/$WEB_PATH/"
    if [ "$MONITORING_ENABLED" = "true" ]; then
        echo -e "\033[1;33mGrafana\033[0m"
        echo "  Путь: /$GRAFANA_WEB_PATH/"
        echo "  Способ подключения: Nginx reverse proxy -> Grafana (Grafana login)"
        echo "  URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/$GRAFANA_WEB_PATH/"
    fi
    if [ "${ADGUARD_INSTALL_ENABLED:-false}" = "true" ]; then
        echo -e "\033[1;34mAdGuard Home\033[0m"
        echo "  DNS bind: ${ADGUARD_DNS_BIND}"
        echo "  Panel path: /${ADGUARD_WEB_PATH}/"
        echo "  DoH path: /${ADGUARD_DOH_PATH}/"
        echo "  URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${ADGUARD_WEB_PATH}/"
        echo "  DoH URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${ADGUARD_DOH_PATH}/"
        echo "  Login: ${ADGUARD_ADMIN_USER}"
        echo "  Password: ${ADGUARD_ADMIN_PASS}"
    fi
    echo "Ops:"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/smoke-test.sh"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/backup-restore-check.sh"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/hardening-profile.sh audit"
    echo -e "\033[1;35m*************************\033[0m"
    systemctl status "$PROJECT_NAME" --no-pager
    exit 0
}

# Timestamp all output in automation/non-interactive mode (profiling + clean logs)
if [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] && [ -z "${INSTALLER_TS_FILTER_ACTIVE:-}" ]; then
    export INSTALLER_TS_FILTER_ACTIVE=1
    exec > >(while IFS= read -r line; do printf '[%s] %s\n' "$(date +%H:%M:%S)" "$line"; done) 2>&1
fi

clear_stale_install_markers

if [ -f "$LOG_FILE" ] && has_real_existing_install; then
    case "${INSTALLER_EXISTING_ACTION:-}" in
        reinstall)
            source "$LOG_FILE"
            uninstall
            unset SELECTED_CFG
            exec bash "$0" "$@"
            ;;
        update)
            source "$LOG_FILE"
            update_project
            ;;
        remove)
            source "$LOG_FILE"
            uninstall_nuke
            exit 0
            ;;
        exit)
            exit 0
            ;;
    esac
    [ -n "${INSTALLER_AUTOMATION_STEPS:-}" ] && exit 0
    source "$LOG_FILE"
    clear
    echo -e "${C_YELLOW}======================================================${C_RESET}"
    echo -e "${C_WHITE}    ОБНАРУЖЕНА УСТАНОВКА: ${PROJECT_NAME}${C_RESET}"
    echo -e "${C_YELLOW}======================================================${C_RESET}"
    echo -e "${C_GREEN}1) Переустановить полностью${C_RESET}"
    echo -e "${C_GREEN}2) Обновить (сохранить данные)${C_RESET}"
    echo -e "${C_WHITE}3) Выход${C_RESET}"
    echo -e "${C_RED}4) Удалить${C_RESET}"
    read -p "Выбор: " choice
    case $choice in
        1) uninstall; exec bash "$0" "$@" ;;
        2) update_project ;;
        4) uninstall_nuke; exit 0 ;;
        *) exit 0 ;;
    esac
fi

if [ "$EUID" -ne 0 ]; then echo "Запустите от root!"; exit 1; fi

# Находим текущую директорию скрипта
if [[ -z "$SCRIPT_DIR" ]]; then
    SCRIPT_DIR="$PWD"
fi

clear
echo -e "${C_YELLOW}======================================================${C_RESET}"
echo -e "${C_WHITE}    MULTI-SERVER MANAGER INSTALLER (v3.1 - 2026)${C_RESET}"
echo -e "${C_YELLOW}======================================================${C_RESET}"

read -p "Имя проекта/сервиса (sub-manager): " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-sub-manager}
read -p "Локальный порт Python (666): " APP_PORT
APP_PORT=${APP_PORT:-666}
read -p "SSH порт для fail2ban/UFW (22): " SSH_PORT
SSH_PORT="$(normalize_tcp_port "${SSH_PORT:-22}" "22")"
read -p "Публичный домен для ссылок (без http/https, Enter = auto): " PUBLIC_DOMAIN
read -p "Схема публичного URL (http/https, default: https): " PUBLIC_SCHEME
PUBLIC_SCHEME=${PUBLIC_SCHEME:-https}
normalize_public_access_vars
read -p "Сгенерировать случайный путь панели (8 символов)? (y/n, default: y): " PANEL_PATH_RANDOM_INPUT
PANEL_PATH_RANDOM_INPUT=${PANEL_PATH_RANDOM_INPUT:-y}
if [[ "$PANEL_PATH_RANDOM_INPUT" =~ ^[nNнН]$ ]]; then
    read -p "Путь панели в браузере (ручной ввод): " WEB_PATH
    WEB_PATH=${WEB_PATH:-$(generate_random_path)}
else
    WEB_PATH=$(generate_random_path)
    echo "Сгенерирован путь панели: /$WEB_PATH/"
fi
WEB_PATH=$(echo "$WEB_PATH" | tr -cd '[:alnum:]')
if [ -z "$WEB_PATH" ]; then
    WEB_PATH=$(generate_random_path)
fi
if [ -z "$WEB_PATH" ]; then
    VITE_BASE="/"
else
    VITE_BASE="/${WEB_PATH}/"
fi
VITE_GRAFANA_PATH="/grafana/"

# Базовые значения (используются в режиме "Быстрая установка")
ALLOW_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
VERIFY_TLS="true"
CA_BUNDLE_PATH=""
READ_ONLY_MODE="false"
SUB_RATE_LIMIT_COUNT="30"
SUB_RATE_LIMIT_WINDOW_SEC="60"
TRAFFIC_STATS_CACHE_TTL="20"
ONLINE_CLIENTS_CACHE_TTL="20"
TRAFFIC_STATS_STALE_TTL="120"
ONLINE_CLIENTS_STALE_TTL="60"
CLIENTS_CACHE_TTL="20"
CLIENTS_CACHE_STALE_TTL="180"
TRAFFIC_MAX_WORKERS="6"
COLLECTOR_BASE_INTERVAL_SEC="10"
COLLECTOR_MAX_INTERVAL_SEC="60"
COLLECTOR_MAX_PARALLEL="4"
REDIS_URL=""
AUDIT_QUEUE_BATCH_SIZE="200"
ROLE_VIEWERS=""
ROLE_OPERATORS=""
SECURITY_IP_ALLOWLIST=""
SECURITY_MTLS_ENABLED="false"
SECURITY_MTLS_CA_PATH=""
MFA_TOTP_ENABLED="false"
MFA_TOTP_USERS=""
MFA_TOTP_WS_STRICT="false"
USE_PROXY="y"
ADGUARD_METRICS_ENABLED="false"
ADGUARD_METRICS_TARGETS=""
ADGUARD_METRICS_PATH="/control/prometheus/metrics"
ADGUARD_LOKI_ENABLED="false"
ADGUARD_QUERYLOG_PATH="/opt/AdGuardHome/data/querylog.json"
ADGUARD_SYSTEMD_UNIT="AdGuardHome.service"
ADGUARD_INSTALL_ENABLED="${ADGUARD_INSTALL_ENABLED:-false}"
ADGUARD_DNS_BIND="${ADGUARD_DNS_BIND:-127.0.0.1:5353}"
ADGUARD_WEB_PORT="${ADGUARD_WEB_PORT:-3000}"
ADGUARD_WEB_PATH="${ADGUARD_WEB_PATH:-}"
ADGUARD_DOH_PATH="${ADGUARD_DOH_PATH:-}"
ADGUARD_ADMIN_USER="${ADGUARD_ADMIN_USER:-}"
ADGUARD_ADMIN_PASS="${ADGUARD_ADMIN_PASS:-}"

resource_guard_detect_profile
resource_guard_apply_runtime_defaults
resource_guard_print_summary "install"

read -p "Режим установки: Быстрая или Advanced? (b/a, default: b): " INSTALL_MODE_INPUT
INSTALL_MODE_INPUT=${INSTALL_MODE_INPUT:-b}
if [[ "$INSTALL_MODE_INPUT" =~ ^[aAфФ]$ ]]; then
    read -p "Разрешенные CORS origins (comma-separated, default: $ALLOW_ORIGINS): " ALLOW_ORIGINS_INPUT
    ALLOW_ORIGINS=${ALLOW_ORIGINS_INPUT:-$ALLOW_ORIGINS}
    read -p "Включить TLS verify к node panel узлам? (y/n, default: y): " VERIFY_TLS_INPUT
    VERIFY_TLS_INPUT=${VERIFY_TLS_INPUT:-y}
    if [[ "$VERIFY_TLS_INPUT" =~ ^[nNнН]$ ]]; then
        VERIFY_TLS="false"
    fi
    read -p "Путь к CA bundle (опционально, Enter = системный trust store): " CA_BUNDLE_PATH
    CA_BUNDLE_PATH=${CA_BUNDLE_PATH:-}
    read -p "Включить read-only режим API? (y/n, default: n): " READ_ONLY_INPUT
    READ_ONLY_INPUT=${READ_ONLY_INPUT:-n}
    if [[ "$READ_ONLY_INPUT" =~ ^[yYдД]$ ]]; then
        READ_ONLY_MODE="true"
    fi
    read -p "Лимит запросов для /sub/* в окно (default: $SUB_RATE_LIMIT_COUNT): " SUB_RATE_LIMIT_COUNT
    SUB_RATE_LIMIT_COUNT=${SUB_RATE_LIMIT_COUNT:-30}
    read -p "Окно лимита /sub/* в секундах (default: $SUB_RATE_LIMIT_WINDOW_SEC): " SUB_RATE_LIMIT_WINDOW_SEC
    SUB_RATE_LIMIT_WINDOW_SEC=${SUB_RATE_LIMIT_WINDOW_SEC:-60}
    read -p "TTL кэша /v1/traffic/stats (сек, default: $TRAFFIC_STATS_CACHE_TTL): " TRAFFIC_STATS_CACHE_TTL
    TRAFFIC_STATS_CACHE_TTL=${TRAFFIC_STATS_CACHE_TTL:-20}
    read -p "TTL кэша /v1/clients/online (сек, default: $ONLINE_CLIENTS_CACHE_TTL): " ONLINE_CLIENTS_CACHE_TTL
    ONLINE_CLIENTS_CACHE_TTL=${ONLINE_CLIENTS_CACHE_TTL:-20}
    read -p "Параллелизм сбора трафика по узлам (default: $TRAFFIC_MAX_WORKERS): " TRAFFIC_MAX_WORKERS
    TRAFFIC_MAX_WORKERS=${TRAFFIC_MAX_WORKERS:-6}
    read -p "Базовый интервал collector (сек, default: $COLLECTOR_BASE_INTERVAL_SEC): " COLLECTOR_BASE_INTERVAL_SEC
    COLLECTOR_BASE_INTERVAL_SEC=${COLLECTOR_BASE_INTERVAL_SEC:-10}
    read -p "Макс. интервал adaptive collector (сек, default: $COLLECTOR_MAX_INTERVAL_SEC): " COLLECTOR_MAX_INTERVAL_SEC
    COLLECTOR_MAX_INTERVAL_SEC=${COLLECTOR_MAX_INTERVAL_SEC:-60}
    read -p "Макс. параллельных poll collector (default: $COLLECTOR_MAX_PARALLEL): " COLLECTOR_MAX_PARALLEL
    COLLECTOR_MAX_PARALLEL=${COLLECTOR_MAX_PARALLEL:-4}
    read -p "Redis URL для кэша (опционально, пример redis://127.0.0.1:6379/0): " REDIS_URL
    REDIS_URL=${REDIS_URL:-}
    read -p "Размер batch audit worker (default: $AUDIT_QUEUE_BATCH_SIZE): " AUDIT_QUEUE_BATCH_SIZE
    AUDIT_QUEUE_BATCH_SIZE=${AUDIT_QUEUE_BATCH_SIZE:-200}
    read -p "Список viewer-пользователей через запятую (опционально): " ROLE_VIEWERS
    ROLE_VIEWERS=${ROLE_VIEWERS:-}
    read -p "Список operator-пользователей через запятую (опционально): " ROLE_OPERATORS
    ROLE_OPERATORS=${ROLE_OPERATORS:-}
    read -p "Включить IP allowlist для панели (CIDR через запятую, Enter = без ограничений): " SECURITY_IP_ALLOWLIST
    SECURITY_IP_ALLOWLIST=${SECURITY_IP_ALLOWLIST:-}
    read -p "Включить mTLS клиентских сертификатов для панели? (y/n, default: n): " SECURITY_MTLS_INPUT
    SECURITY_MTLS_INPUT=${SECURITY_MTLS_INPUT:-n}
    if [[ "$SECURITY_MTLS_INPUT" =~ ^[yYдД]$ ]]; then
        SECURITY_MTLS_ENABLED="true"
        read -p "Путь к CA сертификату для проверки клиентских сертификатов (обязательно): " SECURITY_MTLS_CA_PATH
        if [ -z "$SECURITY_MTLS_CA_PATH" ] || [ ! -f "$SECURITY_MTLS_CA_PATH" ]; then
            echo "❌ Файл CA не найден: $SECURITY_MTLS_CA_PATH"
            exit 1
        fi
    fi
    read -p "Включить TOTP 2FA для API/UI? (y/n, default: n): " MFA_TOTP_INPUT
    MFA_TOTP_INPUT=${MFA_TOTP_INPUT:-n}
    if [[ "$MFA_TOTP_INPUT" =~ ^[yYдД]$ ]]; then
        MFA_TOTP_ENABLED="true"
        read -p "MFA mapping username:BASE32[,user2:BASE32] (обязательно): " MFA_TOTP_USERS
        if [ -z "$MFA_TOTP_USERS" ]; then
            echo "❌ Для TOTP нужно указать MFA mapping."
            exit 1
        fi
    fi
fi

read -p "Установить и подключить Prometheus + Grafana? (y/n, default: y): " MONITORING_INPUT
MONITORING_INPUT=${MONITORING_INPUT:-y}
if [[ "$MONITORING_INPUT" =~ ^[nNнН]$ ]]; then
    MONITORING_ENABLED="false"
else
    MONITORING_ENABLED="true"
fi
if [ "$MONITORING_ENABLED" = "true" ]; then
    read -p "Сгенерировать случайный путь Grafana (8 символов)? (y/n, default: y): " GRAFANA_PATH_RANDOM_INPUT
    GRAFANA_PATH_RANDOM_INPUT=${GRAFANA_PATH_RANDOM_INPUT:-y}
    if [[ "$GRAFANA_PATH_RANDOM_INPUT" =~ ^[nNнН]$ ]]; then
        read -p "Путь Grafana в браузере (ручной ввод): " GRAFANA_WEB_PATH
        GRAFANA_WEB_PATH=${GRAFANA_WEB_PATH:-$(generate_random_path)}
    else
        GRAFANA_WEB_PATH=$(generate_random_path)
        echo "Сгенерирован путь Grafana: /$GRAFANA_WEB_PATH/"
    fi
    GRAFANA_WEB_PATH=$(echo "$GRAFANA_WEB_PATH" | tr -cd '[:alnum:]')
    if [ -z "$GRAFANA_WEB_PATH" ]; then
        GRAFANA_WEB_PATH=$(generate_random_path)
    fi
    GRAFANA_HTTP_PORT=$(pick_free_local_port 43000)
    VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"

    read -p "Включить AdGuard метрики в Prometheus? (y/n, default: n): " ADGUARD_METRICS_INPUT
    ADGUARD_METRICS_INPUT=${ADGUARD_METRICS_INPUT:-n}
    if [[ "$ADGUARD_METRICS_INPUT" =~ ^[yYдД]$ ]]; then
        ADGUARD_METRICS_ENABLED="true"
        read -p "Targets AdGuard через запятую (default: 127.0.0.1:3000): " ADGUARD_METRICS_TARGETS
        ADGUARD_METRICS_TARGETS=${ADGUARD_METRICS_TARGETS:-127.0.0.1:3000}
        read -p "Metrics path AdGuard (default: /control/prometheus/metrics): " ADGUARD_METRICS_PATH
        ADGUARD_METRICS_PATH=${ADGUARD_METRICS_PATH:-/control/prometheus/metrics}
    fi

    read -p "Включить сбор querylog AdGuard в Loki/promtail? (y/n, default: n): " ADGUARD_LOKI_INPUT
    ADGUARD_LOKI_INPUT=${ADGUARD_LOKI_INPUT:-n}
    if [[ "$ADGUARD_LOKI_INPUT" =~ ^[yYдД]$ ]]; then
        ADGUARD_LOKI_ENABLED="true"
        read -p "Путь к querylog.json (default: /opt/AdGuardHome/data/querylog.json): " ADGUARD_QUERYLOG_PATH
        ADGUARD_QUERYLOG_PATH=${ADGUARD_QUERYLOG_PATH:-/opt/AdGuardHome/data/querylog.json}
        read -p "Systemd unit AdGuard для journal (default: AdGuardHome.service): " ADGUARD_SYSTEMD_UNIT
        ADGUARD_SYSTEMD_UNIT=${ADGUARD_SYSTEMD_UNIT:-AdGuardHome.service}
    fi

    if [ "$ADGUARD_INSTALL_ENABLED" = "true" ]; then
        ADGUARD_WEB_PATH="${ADGUARD_WEB_PATH:-$(generate_random_path)}"
        ADGUARD_DOH_PATH="${ADGUARD_DOH_PATH:-$(generate_random_path)}"
        ADGUARD_ADMIN_USER="${ADGUARD_ADMIN_USER:-adg$(generate_random_path)}"
        ADGUARD_ADMIN_PASS="${ADGUARD_ADMIN_PASS:-$(generate_random_secret 20)}"
    fi
else
    GRAFANA_WEB_PATH="grafana"
    GRAFANA_HTTP_PORT=$(pick_free_local_port 43000)
    VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"
    ADGUARD_METRICS_ENABLED="false"
    ADGUARD_METRICS_TARGETS=""
    ADGUARD_METRICS_PATH="/control/prometheus/metrics"
    ADGUARD_LOKI_ENABLED="false"
    ADGUARD_QUERYLOG_PATH="/opt/AdGuardHome/data/querylog.json"
    ADGUARD_SYSTEMD_UNIT="AdGuardHome.service"
fi

if [ -f "$LOG_FILE" ]; then
    write_install_log
fi

PROJECT_DIR="/opt/$PROJECT_NAME"

# Snapshot what was installed before this installer touched the system.
detect_preexisting_stack

if [[ "$INSTALL_MODE_INPUT" =~ ^[aAфФ]$ ]]; then
    read -p "Использовать proxy_pass для API в Nginx? (y/n, по умолчанию y): " USE_PROXY
    USE_PROXY=${USE_PROXY:-y}
fi

echo "Установка системных пакетов и Python/Node.js..."
resource_guard_require_free_mb "${INSTALL_MIN_FREE_MB:-700}" "before system package install" "/" || exit 1
apt_update && apt_install \
    python3-pip \
    python3-venv \
    python3-dev \
    libpam0g-dev \
    build-essential \
    cpulimit \
    sqlite3 \
    nginx \
    fail2ban \
    psmisc \
    openssl \
    ca-certificates \
    curl \
    wget \
    git \
    certbot \
    python3-certbot-nginx

select_or_bootstrap_nginx_cfg || { echo "❌ Не удалось подготовить nginx site config."; exit 1; }
assert_https_reverse_proxy_compatibility || exit 1

# Сохранение параметров
write_install_log

cp "$SELECTED_CFG" "${SELECTED_CFG}.bak"

if [ "$MONITORING_ENABLED" = "true" ]; then
    if ! apt_install prometheus; then
        echo "⚠️ Не удалось установить prometheus. Продолжаем без мониторинга."
        MONITORING_ENABLED="false"
    fi
fi

echo "Установка Node.js 20 LTS..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - || { echo "❌ Не удалось добавить репозиторий NodeSource. Прерывание."; exit 1; }
apt_install nodejs || { echo "❌ Не удалось установить Node.js. Прерывание."; exit 1; }
echo "  → Node.js $(node --version), npm $(npm --version)"

mkdir -p "$PROJECT_DIR"

sync_backend_files

# Создание VENV и установка зависимостей
echo "Установка Python-зависимостей..."
resource_guard_export_build_env
resource_guard_require_free_mb "${INSTALL_PYTHON_MIN_FREE_MB:-900}" "before Python virtualenv and dependency install" "/" || exit 1
python3 -m venv "$PROJECT_DIR/venv"
resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/backend/requirements.txt"
resource_guard_run_heavy "$PROJECT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/backend/requirements-dev.txt"
resource_guard_run_heavy "$PROJECT_DIR/venv/bin/python" -m pytest \
    "$SCRIPT_DIR/backend/tests/test_runtime_controls.py" \
    "$SCRIPT_DIR/backend/tests/test_security_hardening.py" \
    "$SCRIPT_DIR/backend/tests/test_api_smoke.py" \
    -q

# Сборка React фронтенда
echo "Сборка React фронтенда..."
resource_guard_require_free_mb "${INSTALL_FRONTEND_MIN_FREE_MB:-900}" "before frontend build" "/" || exit 1
if ! resource_guard_run_heavy env PROJECT_DIR="$PROJECT_DIR" WEB_PATH="$WEB_PATH" GRAFANA_WEB_PATH="$GRAFANA_WEB_PATH" PUBLIC_SCHEME="$PUBLIC_SCHEME" PUBLIC_DOMAIN="$PUBLIC_DOMAIN" SKIP_LIVE_VERIFY=1 bash "$SCRIPT_DIR/scripts/deploy/build-and-publish-frontend.sh"; then
    echo "❌ Ошибка сборки/публикации фронтенда. Установка прервана."
    exit 1
fi
echo "✓ Frontend собран: $PROJECT_DIR/build"

# Создание systemd сервиса
echo "Настройка systemd..."
cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
    sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
    sed "s|666|$APP_PORT|g" | \
    sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH\"|g" | \
    sed "s|GRAFANA_WEB_PATH=.*|GRAFANA_WEB_PATH=$GRAFANA_WEB_PATH\"|g" | \
    sed "s|MONITORING_ENABLED=.*|MONITORING_ENABLED=$MONITORING_ENABLED\"|g" | \
    sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS\"|g" | \
    sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS\"|g" | \
    sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH\"|g" | \
    sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE\"|g" | \
    sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT\"|g" | \
    sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC\"|g" | \
    sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL\"|g" | \
    sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL\"|g" | \
    sed "s|TRAFFIC_STATS_STALE_TTL=.*|TRAFFIC_STATS_STALE_TTL=$TRAFFIC_STATS_STALE_TTL\"|g" | \
    sed "s|ONLINE_CLIENTS_STALE_TTL=.*|ONLINE_CLIENTS_STALE_TTL=$ONLINE_CLIENTS_STALE_TTL\"|g" | \
    sed "s|CLIENTS_CACHE_TTL=.*|CLIENTS_CACHE_TTL=$CLIENTS_CACHE_TTL\"|g" | \
    sed "s|CLIENTS_CACHE_STALE_TTL=.*|CLIENTS_CACHE_STALE_TTL=$CLIENTS_CACHE_STALE_TTL\"|g" | \
    sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS\"|g" | \
    sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC\"|g" | \
    sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC\"|g" | \
    sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL\"|g" | \
    sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL\"|g" | \
    sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE\"|g" | \
    sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS\"|g" | \
    sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS\"|g" | \
    sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED\"|g" | \
    sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS\"|g" | \
    sed "s|MFA_TOTP_WS_STRICT=.*|MFA_TOTP_WS_STRICT=$MFA_TOTP_WS_STRICT\"|g" > \
    "/etc/systemd/system/$PROJECT_NAME.service"

# Настройка Nginx
echo "Настройка Nginx..."

# Создать snippets директорию если не существует
mkdir -p /etc/nginx/snippets

SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"

# Создать/перезаписать snippet со всеми location блоками (идемпотентно)
generate_nginx_snippet "$SNIPPET_FILE"

echo "✓ Создан snippet: $SNIPPET_FILE"

echo "Проверка include snippet в выбранном nginx cfg..."
ensure_nginx_snippet_include_in_cfg "$SELECTED_CFG" >/dev/null || true
echo "✓ Include обработан в $SELECTED_CFG"

ensure_nginx_http_mime_types

sanitize_nginx_sites_for_stream_443
nginx -t && systemctl restart nginx

configure_fail2ban_security
configure_ufw_firewall

configure_monitoring_stack
configure_adguard_home

# Запуск сервиса
echo "Запуск сервиса..."
resource_guard_restart_services_sequentially "$PROJECT_NAME.service"

# ===== КРАСИВЫЙ ОТЧЕТ ВЫВОДА ВЫПОЛНЯЕТСЯ НИЖЕ =====
echo ""
# Красивый отчет с полной информацией о доступах
echo "Debug: Preparing to print installation report..."
print_installation_report \
    "$APP_PORT" \
    "$WEB_PATH" \
    "$PUBLIC_DOMAIN" \
    "$PUBLIC_SCHEME" \
    "${GRAFANA_WEB_PATH:-}" \
    "${MONITORING_ENABLED:-false}" \
    "${ADGUARD_WEB_PATH:-}" \
    "${ADGUARD_DOH_PATH:-}" \
    "${ADGUARD_ADMIN_USER:-}" \
    "${ADGUARD_ADMIN_PASS:-}" \
    "${ADGUARD_INSTALL_ENABLED:-false}" \
    "${SELECTED_CFG:-}"

if ! run_post_install_checks; then
    echo "❌ Пост-проверка установки не пройдена."
    exit 1
fi
