#!/bin/bash

# --- КОНФИГУРАЦИЯ ---
LOG_FILE="/opt/.sub_manager_install.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
            if dpkg -i "$tmp_deb" >/dev/null 2>&1 || (apt_fix_broken >/dev/null 2>&1 && dpkg -i "$tmp_deb" >/dev/null 2>&1); then
                installed="true"
                break
            fi
        fi
    done

    rm -f "$tmp_deb"
    [ "$installed" = "true" ]
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

write_install_log() {
    local keys=(
        PROJECT_NAME PROJECT_DIR SELECTED_CFG APP_PORT PUBLIC_DOMAIN PUBLIC_SCHEME WEB_PATH
        USE_PROXY ALLOW_ORIGINS VERIFY_TLS CA_BUNDLE_PATH READ_ONLY_MODE
        SUB_RATE_LIMIT_COUNT SUB_RATE_LIMIT_WINDOW_SEC TRAFFIC_STATS_CACHE_TTL
        ONLINE_CLIENTS_CACHE_TTL TRAFFIC_STATS_STALE_TTL ONLINE_CLIENTS_STALE_TTL
        CLIENTS_CACHE_TTL CLIENTS_CACHE_STALE_TTL TRAFFIC_MAX_WORKERS
        COLLECTOR_BASE_INTERVAL_SEC COLLECTOR_MAX_INTERVAL_SEC COLLECTOR_MAX_PARALLEL
        REDIS_URL AUDIT_QUEUE_BATCH_SIZE ROLE_VIEWERS ROLE_OPERATORS
        MONITORING_ENABLED GRAFANA_WEB_PATH GRAFANA_HTTP_PORT
        ADGUARD_METRICS_ENABLED ADGUARD_METRICS_TARGETS ADGUARD_METRICS_PATH
        ADGUARD_LOKI_ENABLED ADGUARD_QUERYLOG_PATH ADGUARD_SYSTEMD_UNIT
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
    for pkg in routers services; do
        if [ -d "$SCRIPT_DIR/backend/$pkg" ]; then
            rm -rf "$PROJECT_DIR/$pkg"
            cp -r "$SCRIPT_DIR/backend/$pkg" "$PROJECT_DIR/"
        fi
    done
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
import re

cfg_path = Path(os.environ["CFG_PATH"])
include_line = os.environ["INCLUDE_LINE"]
text = cfg_path.read_text()

out = []
i = 0
n = len(text)
changed = False

while i < n:
    m = re.search(r'\bserver\s*\{', text[i:])
    if not m:
        out.append(text[i:])
        break
    start = i + m.start()
    open_brace = i + m.end() - 1
    out.append(text[i:start])
    depth = 1
    j = open_brace + 1
    while j < n and depth > 0:
        ch = text[j]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        j += 1
    if depth != 0:
        out.append(text[start:])
        break

    block = text[start:j]
    if include_line not in block:
        insert_at = block.rfind('}')
        if insert_at != -1:
            if not block[:insert_at].endswith('\n'):
                block = block[:insert_at] + '\n' + block[insert_at:]
                insert_at = block.rfind('}')
            block = block[:insert_at] + include_line + "\n" + block[insert_at:]
            changed = True
    out.append(block)
    i = j

new_text = ''.join(out)
if changed and new_text != text:
    cfg_path.write_text(new_text)
print("changed" if changed else "unchanged")
PYTHON
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

    if [ "$adguard_loki_enabled" = "true" ]; then
        if apt_install loki promtail >/dev/null 2>&1; then
            mkdir -p /etc/loki /etc/promtail /var/lib/loki /var/lib/promtail
            cp "$SCRIPT_DIR/monitoring/loki/loki-config.yml" /etc/loki/local-config.yaml
            cp "$SCRIPT_DIR/monitoring/promtail/promtail-config.yml" /etc/promtail/config.yml
            sed -i "s|__ADGUARD_QUERYLOG_PATH__|${adguard_querylog_path}|g" /etc/promtail/config.yml
            sed -i "s|__ADGUARD_SYSTEMD_UNIT__|${adguard_systemd_unit}|g" /etc/promtail/config.yml
            systemctl enable --now loki >/dev/null 2>&1 || true
            systemctl enable --now promtail >/dev/null 2>&1 || true
            systemctl restart loki >/dev/null 2>&1 || true
            systemctl restart promtail >/dev/null 2>&1 || true
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
    updateIntervalSeconds: 30
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
cfg['server']['root_url'] = '%(protocol)s://%(domain)s/${GRAFANA_WEB_PATH}/'
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
with open('/etc/grafana/grafana.ini', 'w') as f:
    cfg.write(f)
PYTHON

    systemctl daemon-reload
    systemctl enable --now prometheus >/dev/null 2>&1 || true
    systemctl enable --now grafana-server >/dev/null 2>&1 || true
    systemctl restart prometheus >/dev/null 2>&1 || true
    systemctl restart grafana-server >/dev/null 2>&1 || true
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

# --- Compression for text/API payloads ---
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_types text/plain text/css text/javascript application/javascript application/json application/xml application/rss+xml image/svg+xml;

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
    return 301 $scheme://$host/$WEB_PATH/;
}

# --- React SPA (static files + SPA fallback) ---
location ^~ /$WEB_PATH/ {
    alias $PROJECT_DIR/build/;
    try_files \$uri \$uri/ /$WEB_PATH/index.html;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;
}
SNIPPET
}

run_post_install_checks() {
    echo -e "\nПроверка запуска сервиса..."

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
        fi
    fi
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
    systemctl daemon-reload
    systemctl restart fail2ban
    if [ -f "${SELECTED_CFG}.bak" ]; then
        mv "${SELECTED_CFG}.bak" "$SELECTED_CFG"
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
    "$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
    "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements.txt"
    
    echo "Пересборка React фронтенда..."
    cd "$SCRIPT_DIR/frontend"
    if [ -f "package-lock.json" ]; then
        npm ci
    else
        npm install
    fi
    echo "  → TypeScript проверка..."
    if ! npx --no-install tsc; then
        echo "❌ Ошибка компиляции TypeScript. Обновление прервано."
        exit 1
    fi
    echo "  → Сборка Vite (VITE_BASE=$VITE_BASE)..."
    mkdir -p "$PROJECT_DIR/build"
    if ! VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
        echo "❌ Ошибка сборки фронтенда. Обновление прервано."
        exit 1
    fi
    cd - > /dev/null
    
    echo "Запуск сервиса..."
    cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
        sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
        sed "s|666|$APP_PORT|g" | \
        sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH\"|g" | \
        sed "s|GRAFANA_WEB_PATH=.*|GRAFANA_WEB_PATH=$GRAFANA_WEB_PATH\"|g" | \
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
    SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    mkdir -p /etc/nginx/snippets
    generate_nginx_snippet "$SNIPPET_FILE"
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
    echo "Ops:"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/smoke-test.sh"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/backup-restore-check.sh"
    echo "  sudo bash $SCRIPT_DIR/scripts/ops/hardening-profile.sh audit"
    echo -e "\033[1;35m*************************\033[0m"
    systemctl status "$PROJECT_NAME" --no-pager
    exit 0
}

if [ -f "$LOG_FILE" ]; then
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
        1) uninstall ;;
        2) update_project ;;
        4) uninstall_nuke; exit 0 ;;
        *) exit 0 ;;
    esac
fi

if [ "$EUID" -ne 0 ]; then echo "Запустите от root!"; exit; fi

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

echo -e "\nВыберите конфиг Nginx из списка:"
configs=( /etc/nginx/sites-available/* )
if [ ${#configs[@]} -eq 0 ]; then
    echo "Nginx конфиги не найдены."
    exit 1
fi
for i in "${!configs[@]}"; do echo "$i) $(basename "${configs[$i]}")"; done
read -p "Введите номер: " cfg_idx
if ! [[ "$cfg_idx" =~ ^[0-9]+$ ]] || [ "$cfg_idx" -ge ${#configs[@]} ]; then
    echo "Неверный номер."
    exit 1
fi
SELECTED_CFG="${configs[$cfg_idx]}"

# Сохранение параметров
write_install_log

cp "$SELECTED_CFG" "${SELECTED_CFG}.bak"

echo "Установка системных пакетов и Python/Node.js..."
apt_update && apt_install \
    python3-pip \
    python3-venv \
    python3-dev \
    libpam0g-dev \
    build-essential \
    sqlite3 \
    nginx \
    fail2ban \
    psmisc \
    openssl \
    curl \
    wget \
    git

if [ "$MONITORING_ENABLED" = "true" ]; then
    if ! ensure_grafana_repo; then
        echo "⚠️ Grafana repo недоступен. Продолжаем без мониторинга."
        MONITORING_ENABLED="false"
    elif ! apt_install prometheus grafana; then
        echo "⚠️ Не удалось установить prometheus/grafana. Продолжаем без мониторинга."
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
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
"$PROJECT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/backend/requirements.txt"

# Сборка React фронтенда
echo "Сборка React фронтенда..."
mkdir -p "$PROJECT_DIR/build"
cd "$SCRIPT_DIR/frontend"
if [ -f "package-lock.json" ]; then
    npm ci
else
    npm install
fi
echo "  → TypeScript проверка..."
if ! npx --no-install tsc; then
    echo "❌ Ошибка компиляции TypeScript. Установка прервана."
    exit 1
fi
echo "  → Сборка Vite (VITE_BASE=$VITE_BASE)..."
if ! VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
    echo "❌ Ошибка сборки фронтенда. Установка прервана."
    exit 1
fi
cd - > /dev/null
echo "✓ Frontend собран: $PROJECT_DIR/build"

# Создание systemd сервиса
echo "Настройка systemd..."
cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
    sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
    sed "s|666|$APP_PORT|g" | \
    sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH\"|g" | \
    sed "s|GRAFANA_WEB_PATH=.*|GRAFANA_WEB_PATH=$GRAFANA_WEB_PATH\"|g" | \
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

nginx -t && systemctl restart nginx

# Fail2Ban
cat > /etc/fail2ban/filter.d/multi-manager.conf <<'EOF'
[Definition]
# Match real auth failures across API methods and WebSocket handshake.
failregex = ^<HOST> -.*"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) .*/api/v1/.*" (401|403)
            ^<HOST> -.*"GET .*/ws(\?.*)? HTTP/.*" (401|403)
EOF

cat > /etc/fail2ban/jail.d/multi-manager.local <<EOF
[multi-manager]
enabled  = true
port     = 0-65535
filter   = multi-manager
logpath  = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime  = 300
EOF

systemctl restart fail2ban

configure_monitoring_stack

# Запуск сервиса
echo "Запуск сервиса..."
systemctl daemon-reload
systemctl enable --now "$PROJECT_NAME.service"

echo -e "\n✅ УСТАНОВКА ЗАВЕРШЕНА!"
echo "Порт API: $APP_PORT"
echo -e "\n\033[1;35m******** ДОСТУПЫ ********\033[0m"
echo -e "\033[1;36mПанель\033[0m"
echo "  Путь: /$WEB_PATH/"
echo "  Способ подключения: Nginx reverse proxy -> FastAPI (логин/пароль системы)"
echo "  URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/$WEB_PATH/"
echo "  Каноничный URL панели: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/$WEB_PATH/"
echo "  Используйте именно этот URL (без /my-panel, если путь сгенерирован случайно)."
if [ "$MONITORING_ENABLED" = "true" ]; then
    echo -e "\033[1;33mGrafana\033[0m"
    echo "  Путь: /$GRAFANA_WEB_PATH/"
    echo "  Способ подключения: Nginx reverse proxy -> Grafana (Grafana login)"
    echo "  URL: ${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/$GRAFANA_WEB_PATH/"
fi
echo "Ops:"
echo "  sudo bash $SCRIPT_DIR/scripts/ops/smoke-test.sh"
echo "  sudo bash $SCRIPT_DIR/scripts/ops/backup-restore-check.sh"
echo "  sudo bash $SCRIPT_DIR/scripts/ops/hardening-profile.sh audit"
echo -e "\033[1;35m*************************\033[0m"

run_post_install_checks
