#!/bin/bash

# --- КОНФИГУРАЦИЯ ---
LOG_FILE="/opt/.sub_manager_install.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
    if [ -z "$WEB_PATH" ]; then
        VITE_BASE="/"
    else
        VITE_BASE="/${WEB_PATH}/"
    fi
    
    echo "Остановка сервиса..."
    systemctl stop "$PROJECT_NAME"
    
    echo "Копирование обновленных файлов бэкенда..."
    cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
    
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
    if ! VITE_BASE="$VITE_BASE" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
        echo "❌ Ошибка сборки фронтенда. Обновление прервано."
        exit 1
    fi
    cd - > /dev/null
    
    echo "Запуск сервиса..."
    systemctl daemon-reload
    systemctl start "$PROJECT_NAME"
    
    echo -e "\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!"
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
read -p "Путь в браузере (my-vpn): " WEB_PATH
WEB_PATH=${WEB_PATH:-my-vpn}
WEB_PATH=$(echo $WEB_PATH | sed 's/\///g')  # Убираем слэши
if [ -z "$WEB_PATH" ]; then
    VITE_BASE="/"
else
    VITE_BASE="/${WEB_PATH}/"
fi

PROJECT_DIR="/opt/$PROJECT_NAME"

# Спросить про proxy_pass для API
read -p "Использовать proxy_pass для API в Nginx? (y/n, по умолчанию y): " USE_PROXY
USE_PROXY=${USE_PROXY:-y}

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
EOF

cp "$SELECTED_CFG" "${SELECTED_CFG}.bak"

echo "Установка системных пакетов и Python/Node.js..."
apt update && apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    libpam0g-dev \
    build-essential \
    sqlite3 \
    nginx \
    fail2ban \
    psmisc \
    curl \
    wget \
    git

echo "Установка Node.js 20 LTS..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - || { echo "❌ Не удалось добавить репозиторий NodeSource. Прерывание."; exit 1; }
apt install -y nodejs || { echo "❌ Не удалось установить Node.js. Прерывание."; exit 1; }
echo "  → Node.js $(node --version), npm $(npm --version)"

mkdir -p "$PROJECT_DIR"

# Копирование всех файлов бэкенда
echo "Копирование бэкенда (все модули)..."
cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"

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
if ! VITE_BASE="$VITE_BASE" npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
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
    sed "s|WEB_PATH=.*|WEB_PATH=$WEB_PATH|g" > \
    "/etc/systemd/system/$PROJECT_NAME.service"

# Настройка Nginx
echo "Настройка Nginx..."

# Создать snippets директорию если не существует
mkdir -p /etc/nginx/snippets

SNIPPET_FILE="/etc/nginx/snippets/${PROJECT_NAME}.conf"

# Создать/перезаписать snippet со всеми location блоками (идемпотентно)
cat > "$SNIPPET_FILE" <<SNIPPET
# Generated by $PROJECT_NAME installer. Run ./update.sh -> option 4 to regenerate.
# DO NOT EDIT MANUALLY - changes will be overwritten on update.

# --- API proxy (must precede the UI catch-all location) ---
location ^~ /$WEB_PATH/api/ {
    proxy_pass http://127.0.0.1:$APP_PORT/api/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_intercept_errors off;
    proxy_buffering off;
    proxy_request_buffering off;
}

# --- Swagger UI / ReDoc docs ---
location = /$WEB_PATH/docs {
    proxy_pass http://127.0.0.1:$APP_PORT/docs;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /$WEB_PATH/docs/ {
    proxy_pass http://127.0.0.1:$APP_PORT/docs/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/openapi.json {
    proxy_pass http://127.0.0.1:$APP_PORT/openapi.json;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/redoc {
    proxy_pass http://127.0.0.1:$APP_PORT/redoc;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location = /$WEB_PATH/health {
    proxy_pass http://127.0.0.1:$APP_PORT/health;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

# --- React SPA (static files + SPA fallback) ---
location ^~ /$WEB_PATH/ {
    alias $PROJECT_DIR/build/;
    try_files \$uri \$uri/ /$WEB_PATH/index.html;
}
SNIPPET

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

# Запуск сервиса
echo "Запуск сервиса..."
systemctl daemon-reload
systemctl enable --now "$PROJECT_NAME.service"

echo -e "\n✅ УСТАНОВКА ЗАВЕРШЕНА!"
echo "Адрес: https://$(hostname -f)/$WEB_PATH/"
echo "Порт: $APP_PORT"

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