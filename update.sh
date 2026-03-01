#!/bin/bash

# --- СКРИПТ ОБНОВЛЕНИЯ MULTI-SERVER MANAGER v3.1 ---
LOG_FILE="/opt/.sub_manager_install.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APT_DPKG_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

apt_update() {
    DEBIAN_FRONTEND=noninteractive apt-get update "${APT_DPKG_OPTS[@]}"
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_DPKG_OPTS[@]}" "$@"
}

apt_fix_broken() {
    DEBIAN_FRONTEND=noninteractive apt-get install -f -y "${APT_DPKG_OPTS[@]}"
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
            echo "  ❌ Не удалось скачать GPG ключ Grafana (возможен блок/403)."
            return 1
        fi
        chmod a+r /etc/apt/keyrings/grafana.gpg
        cat > /etc/apt/sources.list.d/grafana.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main
EOF
        apt_update || return 1
    fi

    if ! apt-cache show grafana >/dev/null 2>&1; then
        echo "  ❌ Grafana package still unavailable after repo setup."
        return 1
    fi
    return 0
}

generate_random_path() {
    tr -dc 'a-z0-9' </dev/urandom | head -c 8
}

pick_free_local_port() {
    local port="${1:-43000}"
    while ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; do
        port=$((port + 1))
    done
    echo "$port"
}

sync_backend_files() {
    mkdir -p "$PROJECT_DIR"
    cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
    for pkg in routers services; do
        if [ -d "$SCRIPT_DIR/backend/$pkg" ]; then
            rm -rf "$PROJECT_DIR/$pkg"
            cp -r "$SCRIPT_DIR/backend/$pkg" "$PROJECT_DIR/"
        fi
    done
}

ensure_monitoring_auth_file() {
    if [ "${MONITORING_ENABLED:-true}" != "true" ]; then
        return 0
    fi
    if [ "${GRAFANA_AUTH_ENABLED:-true}" != "true" ]; then
        return 0
    fi

    if [ -z "${GRAFANA_AUTH_USER:-}" ]; then
        GRAFANA_AUTH_USER="monitor"
    fi
    if [ -z "${GRAFANA_AUTH_HASH:-}" ]; then
        if ! command -v openssl >/dev/null 2>&1; then
            apt_update >/dev/null 2>&1 && apt_install openssl >/dev/null 2>&1
        fi
        local generated_password
        generated_password=$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-20)
        GRAFANA_AUTH_HASH=$(openssl passwd -apr1 "$generated_password")
        echo "⚠️ Сгенерирован новый пароль Grafana BasicAuth для пользователя '$GRAFANA_AUTH_USER': $generated_password"
        echo "⚠️ Сохраните его в безопасном месте."
    fi

    local auth_file="/etc/nginx/.${PROJECT_NAME}_grafana.htpasswd"
    printf '%s:%s\n' "$GRAFANA_AUTH_USER" "$GRAFANA_AUTH_HASH" > "$auth_file"
    chmod 640 "$auth_file"
    chown root:www-data "$auth_file" 2>/dev/null || chown root:root "$auth_file"

    if [ -f "$LOG_FILE" ]; then
        python3 <<PYTHON
from pathlib import Path
path = Path("$LOG_FILE")
data = {}
for line in path.read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        data[k] = v.strip('"')
data["GRAFANA_AUTH_ENABLED"] = "${GRAFANA_AUTH_ENABLED}"
data["GRAFANA_AUTH_USER"] = "${GRAFANA_AUTH_USER}"
data["GRAFANA_AUTH_HASH"] = "${GRAFANA_AUTH_HASH}"
with path.open("w") as f:
    for k, v in data.items():
        f.write(f'{k}="{v}"\\n')
PYTHON
    fi
}

configure_monitoring_stack() {
    if [ "${MONITORING_ENABLED:-true}" != "true" ]; then
        echo "Мониторинг отключен: пропуск настройки Prometheus/Grafana."
        return 0
    fi

    echo "Настройка Prometheus + Grafana..."
    if ! ensure_grafana_repo; then
        echo "  ⚠️ Репозиторий Grafana недоступен. Пробуем fallback установку из .deb..."
    fi

    apt_install prometheus >/dev/null 2>&1 || {
        echo "  ❌ Не удалось установить prometheus."
        return 1
    }

    if ! apt_install grafana >/dev/null 2>&1; then
        echo "  ⚠️ Установка grafana через APT не удалась. Пробуем fallback .deb..."
        if ! install_grafana_with_fallback_deb; then
            echo "  ❌ Не удалось установить Grafana ни через APT, ни через .deb fallback."
            return 1
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

    systemctl enable --now prometheus >/dev/null 2>&1 || true
    systemctl enable --now grafana-server >/dev/null 2>&1 || true
    systemctl restart prometheus >/dev/null 2>&1 || true
    systemctl restart grafana-server >/dev/null 2>&1 || true
    echo "  ✓ Prometheus и Grafana настроены"
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
${mtls_directives}${allowlist_directives}    auth_basic "Restricted Monitoring";
    auth_basic_user_file /etc/nginx/.${PROJECT_NAME}_grafana.htpasswd;
    proxy_pass http://127.0.0.1:$GRAFANA_HTTP_PORT;
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

run_post_update_checks() {
    echo ""
    echo "Пост-проверка после обновления:"

    local health_status=""
    health_status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/health" 2>/dev/null)
    if [ "$health_status" = "200" ]; then
        echo "  ✅ /health -> HTTP 200"
    else
        echo "  ❌ /health -> HTTP ${health_status:-000}"
    fi

    local ws_status=""
    ws_status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/ws" 2>/dev/null)
    if [[ "$ws_status" =~ ^(400|401|403|404|405|426)$ ]]; then
        echo "  ✅ /ws reachable (HTTP $ws_status)"
    else
        echo "  ⚠️ /ws unexpected HTTP: ${ws_status:-000}"
    fi

    local snippet_file="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    if [ -f "$snippet_file" ]; then
        if grep -q "rewrite \^/${GRAFANA_WEB_PATH}/" "$snippet_file"; then
            echo "  ❌ Найден потенциальный redirect-loop rewrite в $snippet_file"
        else
            echo "  ✅ snippet без Grafana rewrite-loop"
        fi
        if grep -q "location = /favicon.ico" "$snippet_file"; then
            echo "  ✅ root favicon fallback присутствует"
        else
            echo "  ⚠️ root favicon fallback не найден в snippet"
        fi
    fi

    if [ "${MONITORING_ENABLED:-false}" = "true" ]; then
        local g_status=""
        g_status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GRAFANA_HTTP_PORT}/login" 2>/dev/null)
        if [[ "$g_status" =~ ^(200|301|302)$ ]]; then
            echo "  ✅ Grafana upstream -> HTTP $g_status"
        else
            echo "  ⚠️ Grafana upstream -> HTTP ${g_status:-000}"
        fi
    fi
}

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Запустите от root!"
    exit 1
fi

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Установка не найдена. Сначала выполните ./install.sh"
    exit 1
fi

source "$LOG_FILE"
ALLOW_ORIGINS=${ALLOW_ORIGINS:-"http://localhost:5173,http://127.0.0.1:5173"}
VERIFY_TLS=${VERIFY_TLS:-"true"}
CA_BUNDLE_PATH=${CA_BUNDLE_PATH:-""}
READ_ONLY_MODE=${READ_ONLY_MODE:-"false"}
SUB_RATE_LIMIT_COUNT=${SUB_RATE_LIMIT_COUNT:-"30"}
SUB_RATE_LIMIT_WINDOW_SEC=${SUB_RATE_LIMIT_WINDOW_SEC:-"60"}
TRAFFIC_STATS_CACHE_TTL=${TRAFFIC_STATS_CACHE_TTL:-"10"}
ONLINE_CLIENTS_CACHE_TTL=${ONLINE_CLIENTS_CACHE_TTL:-"10"}
TRAFFIC_STATS_STALE_TTL=${TRAFFIC_STATS_STALE_TTL:-"120"}
ONLINE_CLIENTS_STALE_TTL=${ONLINE_CLIENTS_STALE_TTL:-"60"}
CLIENTS_CACHE_TTL=${CLIENTS_CACHE_TTL:-"20"}
CLIENTS_CACHE_STALE_TTL=${CLIENTS_CACHE_STALE_TTL:-"180"}
TRAFFIC_MAX_WORKERS=${TRAFFIC_MAX_WORKERS:-"8"}
COLLECTOR_BASE_INTERVAL_SEC=${COLLECTOR_BASE_INTERVAL_SEC:-"5"}
COLLECTOR_MAX_INTERVAL_SEC=${COLLECTOR_MAX_INTERVAL_SEC:-"60"}
COLLECTOR_MAX_PARALLEL=${COLLECTOR_MAX_PARALLEL:-"8"}
REDIS_URL=${REDIS_URL:-""}
AUDIT_QUEUE_BATCH_SIZE=${AUDIT_QUEUE_BATCH_SIZE:-"200"}
ROLE_VIEWERS=${ROLE_VIEWERS:-""}
ROLE_OPERATORS=${ROLE_OPERATORS:-""}
MONITORING_ENABLED=${MONITORING_ENABLED:-"true"}
GRAFANA_WEB_PATH=${GRAFANA_WEB_PATH:-"grafana"}
GRAFANA_HTTP_PORT=${GRAFANA_HTTP_PORT:-"43000"}
GRAFANA_AUTH_ENABLED=${GRAFANA_AUTH_ENABLED:-"true"}
GRAFANA_AUTH_USER=${GRAFANA_AUTH_USER:-"monitor"}
GRAFANA_AUTH_HASH=${GRAFANA_AUTH_HASH:-""}
SECURITY_MTLS_ENABLED=${SECURITY_MTLS_ENABLED:-"false"}
SECURITY_MTLS_CA_PATH=${SECURITY_MTLS_CA_PATH:-""}
SECURITY_IP_ALLOWLIST=${SECURITY_IP_ALLOWLIST:-""}
MFA_TOTP_ENABLED=${MFA_TOTP_ENABLED:-"false"}
MFA_TOTP_USERS=${MFA_TOTP_USERS:-""}
MFA_TOTP_WS_STRICT=${MFA_TOTP_WS_STRICT:-"false"}

# Обновить сохранённые параметры (добавляет новые поля на старых установках)
cat <<EOF > "$LOG_FILE"
PROJECT_NAME="$PROJECT_NAME"
PROJECT_DIR="$PROJECT_DIR"
SELECTED_CFG="$SELECTED_CFG"
APP_PORT="$APP_PORT"
WEB_PATH="$WEB_PATH"
USE_PROXY="$USE_PROXY"
ALLOW_ORIGINS="$ALLOW_ORIGINS"
VERIFY_TLS="$VERIFY_TLS"
CA_BUNDLE_PATH="$CA_BUNDLE_PATH"
READ_ONLY_MODE="$READ_ONLY_MODE"
SUB_RATE_LIMIT_COUNT="$SUB_RATE_LIMIT_COUNT"
SUB_RATE_LIMIT_WINDOW_SEC="$SUB_RATE_LIMIT_WINDOW_SEC"
TRAFFIC_STATS_CACHE_TTL="$TRAFFIC_STATS_CACHE_TTL"
ONLINE_CLIENTS_CACHE_TTL="$ONLINE_CLIENTS_CACHE_TTL"
TRAFFIC_STATS_STALE_TTL="$TRAFFIC_STATS_STALE_TTL"
ONLINE_CLIENTS_STALE_TTL="$ONLINE_CLIENTS_STALE_TTL"
CLIENTS_CACHE_TTL="$CLIENTS_CACHE_TTL"
CLIENTS_CACHE_STALE_TTL="$CLIENTS_CACHE_STALE_TTL"
TRAFFIC_MAX_WORKERS="$TRAFFIC_MAX_WORKERS"
COLLECTOR_BASE_INTERVAL_SEC="$COLLECTOR_BASE_INTERVAL_SEC"
COLLECTOR_MAX_INTERVAL_SEC="$COLLECTOR_MAX_INTERVAL_SEC"
COLLECTOR_MAX_PARALLEL="$COLLECTOR_MAX_PARALLEL"
REDIS_URL="$REDIS_URL"
AUDIT_QUEUE_BATCH_SIZE="$AUDIT_QUEUE_BATCH_SIZE"
ROLE_VIEWERS="$ROLE_VIEWERS"
ROLE_OPERATORS="$ROLE_OPERATORS"
MONITORING_ENABLED="$MONITORING_ENABLED"
GRAFANA_WEB_PATH="$GRAFANA_WEB_PATH"
GRAFANA_HTTP_PORT="$GRAFANA_HTTP_PORT"
GRAFANA_AUTH_ENABLED="$GRAFANA_AUTH_ENABLED"
GRAFANA_AUTH_USER="$GRAFANA_AUTH_USER"
GRAFANA_AUTH_HASH="$GRAFANA_AUTH_HASH"
SECURITY_MTLS_ENABLED="$SECURITY_MTLS_ENABLED"
SECURITY_MTLS_CA_PATH="$SECURITY_MTLS_CA_PATH"
SECURITY_IP_ALLOWLIST="$SECURITY_IP_ALLOWLIST"
MFA_TOTP_ENABLED="$MFA_TOTP_ENABLED"
MFA_TOTP_USERS="$MFA_TOTP_USERS"
MFA_TOTP_WS_STRICT="$MFA_TOTP_WS_STRICT"
EOF

# Compute VITE_BASE from stored WEB_PATH
if [ -z "$WEB_PATH" ]; then
    VITE_BASE="/"
else
    VITE_BASE="/${WEB_PATH}/"
fi
VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"

clear
echo "======================================================"
echo "    MULTI-SERVER MANAGER - ОБНОВЛЕНИЕ v3.1"
echo "======================================================"
echo "Проект: $PROJECT_NAME"
echo "Путь: $PROJECT_DIR"
echo "Порт: $APP_PORT"
echo "Путь панели: /$WEB_PATH/"
echo "Путь Grafana: /$GRAFANA_WEB_PATH/"
echo "Локальный порт Grafana: $GRAFANA_HTTP_PORT"
echo "VERIFY_TLS: $VERIFY_TLS"
echo "READ_ONLY_MODE: $READ_ONLY_MODE"
echo "TRAFFIC_STATS_CACHE_TTL: $TRAFFIC_STATS_CACHE_TTL"
echo "ONLINE_CLIENTS_CACHE_TTL: $ONLINE_CLIENTS_CACHE_TTL"
echo "TRAFFIC_STATS_STALE_TTL: $TRAFFIC_STATS_STALE_TTL"
echo "ONLINE_CLIENTS_STALE_TTL: $ONLINE_CLIENTS_STALE_TTL"
echo "CLIENTS_CACHE_TTL: $CLIENTS_CACHE_TTL"
echo "CLIENTS_CACHE_STALE_TTL: $CLIENTS_CACHE_STALE_TTL"
echo "TRAFFIC_MAX_WORKERS: $TRAFFIC_MAX_WORKERS"
echo "COLLECTOR_BASE_INTERVAL_SEC: $COLLECTOR_BASE_INTERVAL_SEC"
echo "COLLECTOR_MAX_INTERVAL_SEC: $COLLECTOR_MAX_INTERVAL_SEC"
echo "COLLECTOR_MAX_PARALLEL: $COLLECTOR_MAX_PARALLEL"
echo "REDIS_URL: ${REDIS_URL:-<none>}"
echo "AUDIT_QUEUE_BATCH_SIZE: $AUDIT_QUEUE_BATCH_SIZE"
echo "ROLE_VIEWERS: ${ROLE_VIEWERS:-<none>}"
echo "ROLE_OPERATORS: ${ROLE_OPERATORS:-<none>}"
echo "MONITORING_ENABLED: $MONITORING_ENABLED"
echo "GRAFANA_AUTH_ENABLED: $GRAFANA_AUTH_ENABLED"
echo "GRAFANA_AUTH_USER: ${GRAFANA_AUTH_USER:-<none>}"
echo "SECURITY_MTLS_ENABLED: $SECURITY_MTLS_ENABLED"
echo "SECURITY_MTLS_CA_PATH: ${SECURITY_MTLS_CA_PATH:-<none>}"
echo "SECURITY_IP_ALLOWLIST: ${SECURITY_IP_ALLOWLIST:-<none>}"
echo "MFA_TOTP_ENABLED: $MFA_TOTP_ENABLED"
echo "MFA_TOTP_WS_STRICT: $MFA_TOTP_WS_STRICT"
echo "======================================================"
echo ""
read -p "Изменить настройки 2-го уровня защиты (mTLS/IP allowlist/TOTP)? (y/n, default: n): " harden_choice
harden_choice=${harden_choice:-n}
if [[ "$harden_choice" =~ ^[yYдД]$ ]]; then
    read -p "IP allowlist для панели (CIDR через запятую, Enter = без ограничений): " SECURITY_IP_ALLOWLIST
    SECURITY_IP_ALLOWLIST=${SECURITY_IP_ALLOWLIST:-}

    read -p "Включить mTLS клиентских сертификатов для панели? (y/n, default: n): " SECURITY_MTLS_INPUT
    SECURITY_MTLS_INPUT=${SECURITY_MTLS_INPUT:-n}
    if [[ "$SECURITY_MTLS_INPUT" =~ ^[yYдД]$ ]]; then
        SECURITY_MTLS_ENABLED="true"
        read -p "Путь к CA сертификату для mTLS (обязательно): " SECURITY_MTLS_CA_PATH
        if [ -z "$SECURITY_MTLS_CA_PATH" ] || [ ! -f "$SECURITY_MTLS_CA_PATH" ]; then
            echo "❌ Файл CA не найден: $SECURITY_MTLS_CA_PATH"
            exit 1
        fi
    else
        SECURITY_MTLS_ENABLED="false"
        SECURITY_MTLS_CA_PATH=""
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
    else
        MFA_TOTP_ENABLED="false"
        MFA_TOTP_USERS=""
    fi
fi

read -p "Изменить web-пути панели/Grafana? (y/n, default: n): " path_choice
path_choice=${path_choice:-n}
if [[ "$path_choice" =~ ^[yYдД]$ ]]; then
    read -p "Сгенерировать случайный путь панели (8 символов)? (y/n, default: y): " PANEL_PATH_RANDOM_INPUT
    PANEL_PATH_RANDOM_INPUT=${PANEL_PATH_RANDOM_INPUT:-y}
    if [[ "$PANEL_PATH_RANDOM_INPUT" =~ ^[nNнН]$ ]]; then
        read -p "Новый путь панели: " WEB_PATH
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

    if [ "$MONITORING_ENABLED" = "true" ]; then
        read -p "Сгенерировать случайный путь Grafana (8 символов)? (y/n, default: y): " GRAFANA_PATH_RANDOM_INPUT
        GRAFANA_PATH_RANDOM_INPUT=${GRAFANA_PATH_RANDOM_INPUT:-y}
        if [[ "$GRAFANA_PATH_RANDOM_INPUT" =~ ^[nNнН]$ ]]; then
            read -p "Новый путь Grafana: " GRAFANA_WEB_PATH
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
    fi
    VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"
fi

# Сохранить параметры после возможного изменения hardening-настроек
cat <<EOF > "$LOG_FILE"
PROJECT_NAME="$PROJECT_NAME"
PROJECT_DIR="$PROJECT_DIR"
SELECTED_CFG="$SELECTED_CFG"
APP_PORT="$APP_PORT"
WEB_PATH="$WEB_PATH"
USE_PROXY="$USE_PROXY"
ALLOW_ORIGINS="$ALLOW_ORIGINS"
VERIFY_TLS="$VERIFY_TLS"
CA_BUNDLE_PATH="$CA_BUNDLE_PATH"
READ_ONLY_MODE="$READ_ONLY_MODE"
SUB_RATE_LIMIT_COUNT="$SUB_RATE_LIMIT_COUNT"
SUB_RATE_LIMIT_WINDOW_SEC="$SUB_RATE_LIMIT_WINDOW_SEC"
TRAFFIC_STATS_CACHE_TTL="$TRAFFIC_STATS_CACHE_TTL"
ONLINE_CLIENTS_CACHE_TTL="$ONLINE_CLIENTS_CACHE_TTL"
TRAFFIC_STATS_STALE_TTL="$TRAFFIC_STATS_STALE_TTL"
ONLINE_CLIENTS_STALE_TTL="$ONLINE_CLIENTS_STALE_TTL"
CLIENTS_CACHE_TTL="$CLIENTS_CACHE_TTL"
CLIENTS_CACHE_STALE_TTL="$CLIENTS_CACHE_STALE_TTL"
TRAFFIC_MAX_WORKERS="$TRAFFIC_MAX_WORKERS"
COLLECTOR_BASE_INTERVAL_SEC="$COLLECTOR_BASE_INTERVAL_SEC"
COLLECTOR_MAX_INTERVAL_SEC="$COLLECTOR_MAX_INTERVAL_SEC"
COLLECTOR_MAX_PARALLEL="$COLLECTOR_MAX_PARALLEL"
REDIS_URL="$REDIS_URL"
AUDIT_QUEUE_BATCH_SIZE="$AUDIT_QUEUE_BATCH_SIZE"
ROLE_VIEWERS="$ROLE_VIEWERS"
ROLE_OPERATORS="$ROLE_OPERATORS"
MONITORING_ENABLED="$MONITORING_ENABLED"
GRAFANA_WEB_PATH="$GRAFANA_WEB_PATH"
GRAFANA_HTTP_PORT="$GRAFANA_HTTP_PORT"
GRAFANA_AUTH_ENABLED="$GRAFANA_AUTH_ENABLED"
GRAFANA_AUTH_USER="$GRAFANA_AUTH_USER"
GRAFANA_AUTH_HASH="$GRAFANA_AUTH_HASH"
SECURITY_MTLS_ENABLED="$SECURITY_MTLS_ENABLED"
SECURITY_MTLS_CA_PATH="$SECURITY_MTLS_CA_PATH"
SECURITY_IP_ALLOWLIST="$SECURITY_IP_ALLOWLIST"
MFA_TOTP_ENABLED="$MFA_TOTP_ENABLED"
MFA_TOTP_USERS="$MFA_TOTP_USERS"
MFA_TOTP_WS_STRICT="$MFA_TOTP_WS_STRICT"
EOF

echo "Выберите режим обновления:"
echo "  1) Полное обновление (Backend + Frontend)"
echo "  2) Только Backend модули"
echo "  3) Только Frontend"
echo "  4) Обновить Nginx конфигурацию"
echo "  5) Выход"
echo ""
read -p "Ваш выбор [1-5]: " update_choice

if [[ "$update_choice" == "5" ]]; then
    echo "Выход."
    exit 0
fi

# Бекап перед обновлением
BACKUP_DIR="/var/backups/${PROJECT_NAME}_backup_$(date +%Y%m%d_%H%M%S)"
echo ""
echo "🔄 Создание резервной копии..."
mkdir -p "$BACKUP_DIR"
cp -r "$PROJECT_DIR"/*.py "$BACKUP_DIR/" 2>/dev/null
for pkg in routers services; do
    if [ -d "$PROJECT_DIR/$pkg" ]; then
        cp -r "$PROJECT_DIR/$pkg" "$BACKUP_DIR/"
    fi
done
if [ -f "/etc/systemd/system/$PROJECT_NAME.service" ]; then
    cp "/etc/systemd/system/$PROJECT_NAME.service" "$BACKUP_DIR/"
fi
echo "  ✓ Резервная копия: $BACKUP_DIR"

echo ""

# Обновление
case $update_choice in
    1) # Полное обновление
        echo "[1/5] Остановка сервиса..."
        systemctl stop "$PROJECT_NAME"
        
        echo "[2/5] Обновление всех модулей Backend..."
        sync_backend_files
        echo "  ✓ Скопировано $(ls -1 "$SCRIPT_DIR/backend/"*.py | wc -l) модулей"
        
        echo "[3/5] Обновление Python-зависимостей..."
        "$PROJECT_DIR/venv/bin/pip" install --upgrade pip > /dev/null 2>&1
        "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements.txt" > /dev/null 2>&1
        echo "  ✓ Зависимости обновлены"
        
        echo "[4/5] Пересборка Frontend..."
        cd "$SCRIPT_DIR/frontend"
        if [ -f "package-lock.json" ]; then
            npm ci
        else
            npm install
        fi
        echo "  → TypeScript проверка..."
        if ! npx --no-install tsc; then
            echo "  ❌ Ошибка компиляции TypeScript. Обновление прервано."
            exit 1
        fi
        echo "  → Сборка Vite (VITE_BASE=$VITE_BASE)..."
        mkdir -p "$PROJECT_DIR/build"
        if ! VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
            echo "  ❌ Ошибка сборки фронтенда. Обновление прервано."
            exit 1
        fi
        cd - > /dev/null
        echo "  ✓ Frontend пересобран"
        
        echo "[5/5] Перезапуск сервиса..."
        cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
            sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
            sed "s|666|$APP_PORT|g" | \
            sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH|g" | \
            sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS|g" | \
            sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS|g" | \
            sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH|g" | \
            sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE|g" | \
            sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT|g" | \
            sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC|g" | \
            sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL|g" | \
            sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL|g" | \
            sed "s|TRAFFIC_STATS_STALE_TTL=.*|TRAFFIC_STATS_STALE_TTL=$TRAFFIC_STATS_STALE_TTL|g" | \
            sed "s|ONLINE_CLIENTS_STALE_TTL=.*|ONLINE_CLIENTS_STALE_TTL=$ONLINE_CLIENTS_STALE_TTL|g" | \
            sed "s|CLIENTS_CACHE_TTL=.*|CLIENTS_CACHE_TTL=$CLIENTS_CACHE_TTL|g" | \
            sed "s|CLIENTS_CACHE_STALE_TTL=.*|CLIENTS_CACHE_STALE_TTL=$CLIENTS_CACHE_STALE_TTL|g" | \
            sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS|g" | \
            sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC|g" | \
            sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC|g" | \
            sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL|g" | \
            sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL|g" | \
            sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE|g" | \
            sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS|g" | \
            sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS|g" | \
            sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED|g" | \
            sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS|g" | \
            sed "s|MFA_TOTP_WS_STRICT=.*|MFA_TOTP_WS_STRICT=$MFA_TOTP_WS_STRICT|g" > \
            "/etc/systemd/system/$PROJECT_NAME.service"
        systemctl daemon-reload
        systemctl start "$PROJECT_NAME"
        configure_monitoring_stack
        ensure_monitoring_auth_file
        SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
        mkdir -p /etc/nginx/snippets
        generate_nginx_snippet "$SNIPPET_FILE"
        nginx -t && systemctl restart nginx
        ;;
        
    2) # Только Backend
        echo "[1/3] Остановка сервиса..."
        systemctl stop "$PROJECT_NAME"
        
        echo "[2/3] Обновление модулей Backend..."
        sync_backend_files
        echo "  ✓ Скопировано $(ls -1 "$SCRIPT_DIR/backend/"*.py | wc -l) модулей"
        
        echo "  → Обновление зависимостей..."
        "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements.txt" > /dev/null 2>&1
        
        echo "[3/3] Перезапуск сервиса..."
        cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
            sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
            sed "s|666|$APP_PORT|g" | \
            sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH|g" | \
            sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS|g" | \
            sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS|g" | \
            sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH|g" | \
            sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE|g" | \
            sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT|g" | \
            sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC|g" | \
            sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL|g" | \
            sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL|g" | \
            sed "s|TRAFFIC_STATS_STALE_TTL=.*|TRAFFIC_STATS_STALE_TTL=$TRAFFIC_STATS_STALE_TTL|g" | \
            sed "s|ONLINE_CLIENTS_STALE_TTL=.*|ONLINE_CLIENTS_STALE_TTL=$ONLINE_CLIENTS_STALE_TTL|g" | \
            sed "s|CLIENTS_CACHE_TTL=.*|CLIENTS_CACHE_TTL=$CLIENTS_CACHE_TTL|g" | \
            sed "s|CLIENTS_CACHE_STALE_TTL=.*|CLIENTS_CACHE_STALE_TTL=$CLIENTS_CACHE_STALE_TTL|g" | \
            sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS|g" | \
            sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC|g" | \
            sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC|g" | \
            sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL|g" | \
            sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL|g" | \
            sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE|g" | \
            sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS|g" | \
            sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS|g" | \
            sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED|g" | \
            sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS|g" | \
            sed "s|MFA_TOTP_WS_STRICT=.*|MFA_TOTP_WS_STRICT=$MFA_TOTP_WS_STRICT|g" > \
            "/etc/systemd/system/$PROJECT_NAME.service"
        systemctl daemon-reload
        systemctl start "$PROJECT_NAME"
        configure_monitoring_stack
        ensure_monitoring_auth_file
        SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
        mkdir -p /etc/nginx/snippets
        generate_nginx_snippet "$SNIPPET_FILE"
        nginx -t && systemctl restart nginx
        ;;
        
    3) # Только Frontend
        echo "[1/2] Пересборка Frontend..."
        cd "$SCRIPT_DIR/frontend"
        if [ -f "package-lock.json" ]; then
            npm ci
        else
            npm install
        fi
        echo "  → TypeScript проверка..."
        if ! npx --no-install tsc; then
            echo "  ❌ Ошибка компиляции TypeScript. Обновление прервано."
            exit 1
        fi
        echo "  → Сборка Vite (VITE_BASE=$VITE_BASE)..."
        mkdir -p "$PROJECT_DIR/build"
        if ! VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
            echo "  ❌ Ошибка сборки фронтенда. Обновление прервано."
            exit 1
        fi
        cd - > /dev/null
        echo "  ✓ Сборка завершена"
        
        echo "[2/2] Frontend обновлён."
        echo "  ✓ Frontend обновлён (может потребоваться очистка кэша браузера Ctrl+Shift+R)"
        ;;
        
    4) # Nginx конфиг
        echo "[1/2] Обновление Nginx конфигурации..."
        cp "$SELECTED_CFG" "${SELECTED_CFG}.bak.$(date +%Y%m%d_%H%M%S)"
        echo "  ✓ Создан бэкап конфига"

        SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
        mkdir -p /etc/nginx/snippets

        generate_nginx_snippet "$SNIPPET_FILE"
        echo "  ✓ Обновлен snippet: $SNIPPET_FILE"
        configure_monitoring_stack
        ensure_monitoring_auth_file

        echo "[2/2] Тестирование и перезагрузка Nginx..."
        if nginx -t 2>/dev/null; then
            systemctl restart nginx
            echo "  ✓ Nginx успешно перезагружен"
        else
            echo "  ❌ Ошибка в конфигурации Nginx. Подробности:"
            nginx -t
        fi
        ;;
esac

echo ""
echo "======================================================"

# Проверка статуса (для режимов 1-2)
if [[ "$update_choice" =~ ^[12]$ ]]; then
    sleep 2
    if systemctl is-active --quiet "$PROJECT_NAME"; then
        echo "✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО!"
        echo "======================================================"
        echo ""
        echo "Статус сервиса:"
        systemctl status "$PROJECT_NAME" --no-pager -l | head -n 10
        echo ""
        echo -e "\033[1;35m******** ДОСТУПЫ ********\033[0m"
        echo -e "\033[1;36mПанель\033[0m"
        echo "  Путь: /$WEB_PATH/"
        echo "  Способ подключения: Nginx reverse proxy -> FastAPI (логин/пароль системы)"
        echo "  URL: http://$(hostname -f)/$WEB_PATH/"
        if [ "$MONITORING_ENABLED" = "true" ]; then
            echo -e "\033[1;33mGrafana\033[0m"
            echo "  Путь: /$GRAFANA_WEB_PATH/"
            echo "  Способ подключения: Nginx reverse proxy -> Grafana (BasicAuth + Grafana login)"
            echo "  URL: http://$(hostname -f)/$GRAFANA_WEB_PATH/"
        fi
        echo -e "\033[1;35m*************************\033[0m"
    else
        echo "❌ ОШИБКА! Сервис не запущен"
        echo "======================================================"
        echo ""
        echo "Проверьте логи командой:"
        echo "  journalctl -u $PROJECT_NAME -n 50 --no-pager"
        echo ""
        echo "Резервная копия доступна: $BACKUP_DIR"
        echo ""
        read -p "Восстановить из резервной копии? (y/n): " rollback
        if [[ "$rollback" =~ ^[yYдД]$ ]]; then
            echo "Восстановление..."
            systemctl stop "$PROJECT_NAME"
            cp "$BACKUP_DIR"/*.py "$PROJECT_DIR/"
            for pkg in routers services; do
                if [ -d "$BACKUP_DIR/$pkg" ]; then
                    rm -rf "$PROJECT_DIR/$pkg"
                    cp -r "$BACKUP_DIR/$pkg" "$PROJECT_DIR/"
                fi
            done
            systemctl start "$PROJECT_NAME"
            sleep 1
            if systemctl is-active --quiet "$PROJECT_NAME"; then
                echo "✓ Резервная копия восстановлена, сервис запущен"
            else
                echo "❌ Ошибка восстановления. Проверьте логи."
            fi
        fi
    fi
else
    echo "✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!"
    echo "======================================================"
    echo -e "\033[1;35m******** ДОСТУПЫ ********\033[0m"
    echo -e "\033[1;36mПанель\033[0m"
    echo "  Путь: /$WEB_PATH/"
    echo "  Способ подключения: Nginx reverse proxy -> FastAPI (логин/пароль системы)"
    echo "  URL: http://$(hostname -f)/$WEB_PATH/"
    if [ "$MONITORING_ENABLED" = "true" ]; then
        echo -e "\033[1;33mGrafana\033[0m"
        echo "  Путь: /$GRAFANA_WEB_PATH/"
        echo "  Способ подключения: Nginx reverse proxy -> Grafana (BasicAuth + Grafana login)"
        echo "  URL: http://$(hostname -f)/$GRAFANA_WEB_PATH/"
    fi
    echo -e "\033[1;35m*************************\033[0m"
fi

run_post_update_checks

echo ""
echo "📦 Резервная копия сохранена: $BACKUP_DIR"
echo ""
echo "Для удаления старых бэкапов (>7 дней):"
echo "  find /var/backups/${PROJECT_NAME}_backup_* -type d -mtime +7 -exec rm -rf {} +"
echo ""
