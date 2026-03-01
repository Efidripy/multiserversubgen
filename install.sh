#!/bin/bash

# --- КОНФИГУРАЦИЯ ---
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
    rewrite ^/$GRAFANA_WEB_PATH/(.*)\$ /\$1 break;
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
    TRAFFIC_STATS_CACHE_TTL=${TRAFFIC_STATS_CACHE_TTL:-"10"}
    ONLINE_CLIENTS_CACHE_TTL=${ONLINE_CLIENTS_CACHE_TTL:-"10"}
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
        sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH|g" | \
        sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS|g" | \
        sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS|g" | \
        sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH|g" | \
        sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE|g" | \
        sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT|g" | \
        sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC|g" | \
        sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL|g" | \
        sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL|g" | \
        sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS|g" | \
        sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC|g" | \
        sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC|g" | \
        sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL|g" | \
        sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL|g" | \
        sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE|g" | \
        sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS|g" | \
        sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS|g" | \
        sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED|g" | \
        sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS|g" > \
        "/etc/systemd/system/$PROJECT_NAME.service"
    systemctl daemon-reload
    systemctl start "$PROJECT_NAME"

    configure_monitoring_stack
    ensure_monitoring_auth_file
    SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"
    mkdir -p /etc/nginx/snippets
    generate_nginx_snippet "$SNIPPET_FILE"
    nginx -t && systemctl restart nginx
    
    echo -e "\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!"
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
    systemctl status "$PROJECT_NAME" --no-pager
    exit 0
}

if [ -f "$LOG_FILE" ]; then
    source "$LOG_FILE"
    clear
    echo "======================================================"
    echo "    ОБНАРУЖЕНА УСТАНОВКА: $PROJECT_NAME"
    echo "======================================================"
    echo "1) Удалить"
    echo "2) Переустановить полностью"
    echo "3) Обновить (сохранить данные)"
    echo "4) Выход"
    read -p "Выбор: " choice
    case $choice in
        1) uninstall; exit 0 ;;
        2) uninstall ;;
        3) update_project ;;
        *) exit 0 ;;
    esac
fi

if [ "$EUID" -ne 0 ]; then echo "Запустите от root!"; exit; fi

# Находим текущую директорию скрипта
if [[ -z "$SCRIPT_DIR" ]]; then
    SCRIPT_DIR="$PWD"
fi

clear
echo "======================================================"
echo "    MULTI-SERVER MANAGER INSTALLER (v3.1 - 2026)"
echo "======================================================"

read -p "Имя проекта/сервиса (sub-manager): " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-sub-manager}
read -p "Локальный порт Python (666): " APP_PORT
APP_PORT=${APP_PORT:-666}
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
TRAFFIC_STATS_CACHE_TTL="10"
ONLINE_CLIENTS_CACHE_TTL="10"
TRAFFIC_MAX_WORKERS="8"
COLLECTOR_BASE_INTERVAL_SEC="5"
COLLECTOR_MAX_INTERVAL_SEC="60"
COLLECTOR_MAX_PARALLEL="8"
REDIS_URL=""
AUDIT_QUEUE_BATCH_SIZE="200"
ROLE_VIEWERS=""
ROLE_OPERATORS=""
SECURITY_IP_ALLOWLIST=""
SECURITY_MTLS_ENABLED="false"
SECURITY_MTLS_CA_PATH=""
MFA_TOTP_ENABLED="false"
MFA_TOTP_USERS=""
USE_PROXY="y"

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
    TRAFFIC_STATS_CACHE_TTL=${TRAFFIC_STATS_CACHE_TTL:-10}
    read -p "TTL кэша /v1/clients/online (сек, default: $ONLINE_CLIENTS_CACHE_TTL): " ONLINE_CLIENTS_CACHE_TTL
    ONLINE_CLIENTS_CACHE_TTL=${ONLINE_CLIENTS_CACHE_TTL:-10}
    read -p "Параллелизм сбора трафика по узлам (default: $TRAFFIC_MAX_WORKERS): " TRAFFIC_MAX_WORKERS
    TRAFFIC_MAX_WORKERS=${TRAFFIC_MAX_WORKERS:-8}
    read -p "Базовый интервал collector (сек, default: $COLLECTOR_BASE_INTERVAL_SEC): " COLLECTOR_BASE_INTERVAL_SEC
    COLLECTOR_BASE_INTERVAL_SEC=${COLLECTOR_BASE_INTERVAL_SEC:-5}
    read -p "Макс. интервал adaptive collector (сек, default: $COLLECTOR_MAX_INTERVAL_SEC): " COLLECTOR_MAX_INTERVAL_SEC
    COLLECTOR_MAX_INTERVAL_SEC=${COLLECTOR_MAX_INTERVAL_SEC:-60}
    read -p "Макс. параллельных poll collector (default: $COLLECTOR_MAX_PARALLEL): " COLLECTOR_MAX_PARALLEL
    COLLECTOR_MAX_PARALLEL=${COLLECTOR_MAX_PARALLEL:-8}
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

    GRAFANA_AUTH_ENABLED="true"
    read -p "Логин для доступа к Grafana через Nginx (default: monitor): " GRAFANA_AUTH_USER
    GRAFANA_AUTH_USER=${GRAFANA_AUTH_USER:-monitor}
    while true; do
        read -s -p "Пароль для Grafana BasicAuth (минимум 10 символов): " GRAFANA_AUTH_PASSWORD
        echo ""
        if [ "${#GRAFANA_AUTH_PASSWORD}" -lt 10 ]; then
            echo "Пароль слишком короткий."
            continue
        fi
        read -s -p "Повторите пароль: " GRAFANA_AUTH_PASSWORD_CONFIRM
        echo ""
        if [ "$GRAFANA_AUTH_PASSWORD" != "$GRAFANA_AUTH_PASSWORD_CONFIRM" ]; then
            echo "Пароли не совпадают."
            continue
        fi
        break
    done
    GRAFANA_AUTH_HASH=$(openssl passwd -apr1 "$GRAFANA_AUTH_PASSWORD")
    unset GRAFANA_AUTH_PASSWORD GRAFANA_AUTH_PASSWORD_CONFIRM
else
    GRAFANA_WEB_PATH="grafana"
    GRAFANA_HTTP_PORT=$(pick_free_local_port 43000)
    VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH}/"
    GRAFANA_AUTH_ENABLED="false"
    GRAFANA_AUTH_USER=""
    GRAFANA_AUTH_HASH=""
fi

python3 <<PYTHON
from pathlib import Path
path = Path("$LOG_FILE")
if path.exists():
    data = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v.strip('"')
    data["MONITORING_ENABLED"] = "${MONITORING_ENABLED}"
    data["GRAFANA_AUTH_ENABLED"] = "${GRAFANA_AUTH_ENABLED}"
    with path.open("w") as f:
        for k, v in data.items():
            f.write(f'{k}="{v}"\\n')
PYTHON

PROJECT_DIR="/opt/$PROJECT_NAME"

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
EOF

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
        GRAFANA_AUTH_ENABLED="false"
    elif ! apt_install prometheus grafana; then
        echo "⚠️ Не удалось установить prometheus/grafana. Продолжаем без мониторинга."
        MONITORING_ENABLED="false"
        GRAFANA_AUTH_ENABLED="false"
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
    sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH|g" | \
    sed "s|ALLOW_ORIGINS=.*|ALLOW_ORIGINS=$ALLOW_ORIGINS|g" | \
    sed "s|VERIFY_TLS=.*|VERIFY_TLS=$VERIFY_TLS|g" | \
    sed "s|CA_BUNDLE_PATH=.*|CA_BUNDLE_PATH=$CA_BUNDLE_PATH|g" | \
    sed "s|READ_ONLY_MODE=.*|READ_ONLY_MODE=$READ_ONLY_MODE|g" | \
    sed "s|SUB_RATE_LIMIT_COUNT=.*|SUB_RATE_LIMIT_COUNT=$SUB_RATE_LIMIT_COUNT|g" | \
    sed "s|SUB_RATE_LIMIT_WINDOW_SEC=.*|SUB_RATE_LIMIT_WINDOW_SEC=$SUB_RATE_LIMIT_WINDOW_SEC|g" | \
    sed "s|TRAFFIC_STATS_CACHE_TTL=.*|TRAFFIC_STATS_CACHE_TTL=$TRAFFIC_STATS_CACHE_TTL|g" | \
    sed "s|ONLINE_CLIENTS_CACHE_TTL=.*|ONLINE_CLIENTS_CACHE_TTL=$ONLINE_CLIENTS_CACHE_TTL|g" | \
    sed "s|TRAFFIC_MAX_WORKERS=.*|TRAFFIC_MAX_WORKERS=$TRAFFIC_MAX_WORKERS|g" | \
    sed "s|COLLECTOR_BASE_INTERVAL_SEC=.*|COLLECTOR_BASE_INTERVAL_SEC=$COLLECTOR_BASE_INTERVAL_SEC|g" | \
    sed "s|COLLECTOR_MAX_INTERVAL_SEC=.*|COLLECTOR_MAX_INTERVAL_SEC=$COLLECTOR_MAX_INTERVAL_SEC|g" | \
    sed "s|COLLECTOR_MAX_PARALLEL=.*|COLLECTOR_MAX_PARALLEL=$COLLECTOR_MAX_PARALLEL|g" | \
    sed "s|REDIS_URL=.*|REDIS_URL=$REDIS_URL|g" | \
    sed "s|AUDIT_QUEUE_BATCH_SIZE=.*|AUDIT_QUEUE_BATCH_SIZE=$AUDIT_QUEUE_BATCH_SIZE|g" | \
    sed "s|ROLE_VIEWERS=.*|ROLE_VIEWERS=$ROLE_VIEWERS|g" | \
    sed "s|ROLE_OPERATORS=.*|ROLE_OPERATORS=$ROLE_OPERATORS|g" | \
    sed "s|MFA_TOTP_ENABLED=.*|MFA_TOTP_ENABLED=$MFA_TOTP_ENABLED|g" | \
    sed "s|MFA_TOTP_USERS=.*|MFA_TOTP_USERS=$MFA_TOTP_USERS|g" > \
    "/etc/systemd/system/$PROJECT_NAME.service"

# Настройка Nginx
echo "Настройка Nginx..."

# Создать snippets директорию если не существует
mkdir -p /etc/nginx/snippets

SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"

# Создать/перезаписать snippet со всеми location блоками (идемпотентно)
generate_nginx_snippet "$SNIPPET_FILE"
ensure_monitoring_auth_file

echo "✓ Создан snippet: $SNIPPET_FILE"

# Идемпотентно добавить include в выбранный конфиг nginx (внутри server {})
INCLUDE_LINE="    include /etc/nginx/snippets/${PROJECT_NAME}.conf;"
if grep -qF "$INCLUDE_LINE" "$SELECTED_CFG"; then
    echo "✓ Include уже присутствует в $SELECTED_CFG. Пропускаем."
else
    python3 << PYTHON
import re, sys

with open('$SELECTED_CFG', 'r') as f:
    content = f.read()

include_line = '\n    include /etc/nginx/snippets/${PROJECT_NAME}.conf;\n'

# Try to insert after the first server_name directive
pattern = r'(server_name\s+[^\n;]+;[ \t]*\n)'
new_content = re.sub(pattern, r'\1' + include_line, content, count=1)

if new_content == content:
    # Fallback: insert before the closing brace of the first server {} block
    server_match = re.search(r'\bserver\s*\{', content)
    if not server_match:
        print('ERROR: Could not find server {} block in $SELECTED_CFG', file=sys.stderr)
        sys.exit(1)
    start = server_match.end()
    depth = 1
    pos = start
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    insert_pos = pos - 1  # index of closing brace
    new_content = content[:insert_pos] + include_line + content[insert_pos:]

with open('$SELECTED_CFG', 'w') as f:
    f.write(new_content)
print('✓ Include добавлен в $SELECTED_CFG')
PYTHON
fi

nginx -t && systemctl restart nginx

# Fail2Ban
cat > /etc/fail2ban/filter.d/multi-manager.conf <<'EOF'
[Definition]
failregex = ^<HOST> -.*"GET .*/api/v1/.*" (401|403)
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
echo "  URL: http://$(hostname -f)/$WEB_PATH/"
if [ "$MONITORING_ENABLED" = "true" ]; then
    echo -e "\033[1;33mGrafana\033[0m"
    echo "  Путь: /$GRAFANA_WEB_PATH/"
    echo "  Способ подключения: Nginx reverse proxy -> Grafana (BasicAuth + Grafana login)"
    echo "  URL: http://$(hostname -f)/$GRAFANA_WEB_PATH/"
fi
echo -e "\033[1;35m*************************\033[0m"

# Self-test: проверка health endpoint
echo -e "\nПроверка запуска сервиса..."
HEALTH_STATUS=""
for i in 1 2 3 4 5; do
    sleep 2
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${APP_PORT}/health" 2>/dev/null)
    [ "$HEALTH_STATUS" = "200" ] && break
done
if [ "$HEALTH_STATUS" = "200" ]; then
    echo "✅ Health check пройден: /health → HTTP $HEALTH_STATUS"
else
    echo "❌ Health check не пройден (HTTP $HEALTH_STATUS). Проверьте логи:"
    echo "   journalctl -u $PROJECT_NAME -n 50 --no-pager"
fi
