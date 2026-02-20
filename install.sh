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
    
    echo "Остановка сервиса..."
    systemctl stop "$PROJECT_NAME"
    
    echo "Копирование обновленных файлов бэкенда..."
    cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
    
    echo "Обновление Python-зависимостей..."
    "$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
    "$PROJECT_DIR/venv/bin/pip" install --upgrade \
        fastapi \
        uvicorn[standard] \
        requests \
        python-pam \
        urllib3 \
        cryptography \
        python-multipart \
        aiofiles
    
    echo "Пересборка React фронтенда..."
    cd "$SCRIPT_DIR/frontend"
    npm install
    npm run build
    cp -r build/* "$PROJECT_DIR/build/"
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
read -p "Путь в браузере (my-panel): " WEB_PATH
WEB_PATH=${WEB_PATH:-my-panel}
WEB_PATH=$(echo $WEB_PATH | sed 's/\///g')  # Убираем слэши

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
    git \
    nodejs \
    npm

mkdir -p "$PROJECT_DIR"

# Копирование всех файлов бэкенда
echo "Копирование бэкенда (все модули)..."
cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"

# Создание VENV и установка зависимостей
echo "Установка Python-зависимостей..."
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
"$PROJECT_DIR/venv/bin/pip" install \
    fastapi \
    uvicorn[standard] \
    requests \
    python-pam \
    urllib3 \
    cryptography \
    python-multipart \
    aiofiles

# Сборка React фронтенда
echo "Сборка React фронтенда..."
cd "$SCRIPT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run build
cd - > /dev/null

# Создание systemd сервиса
echo "Настройка systemd..."
cat "$SCRIPT_DIR/systemd/sub-manager.service" | \
    sed "s|/opt/sub-manager|$PROJECT_DIR|g" | \
    sed "s|666|$APP_PORT|g" > \
    "/etc/systemd/system/$PROJECT_NAME.service"

# Настройка Nginx
echo "Настройка Nginx..."

# Создать snippets директорию если не существует
mkdir -p /etc/nginx/snippets

# Создать snippet с proxy_pass конфигурацией
if [[ "$USE_PROXY" == "y" || "$USE_PROXY" == "Y" ]]; then
    cat > "/etc/nginx/snippets/${PROJECT_NAME}-proxy.conf" <<SNIPPET
# Multi-Server Manager API Proxy Configuration
location ~ "^/$WEB_PATH/api(.*)\$" {
    proxy_pass http://127.0.0.1:$APP_PORT/api\$1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_intercept_errors off;
    proxy_buffering off;
    proxy_request_buffering off;
}
SNIPPET
    echo "✓ Создан snippet: /etc/nginx/snippets/${PROJECT_NAME}-proxy.conf"
fi

if grep -q "location \^~ /$WEB_PATH/" "$SELECTED_CFG"; then
    echo "Блок location уже существует. Пропускаем."
else
    # Инжектим конфиг после server_name
    python3 << PYTHON
import re
with open('$SELECTED_CFG', 'r') as f:
    content = f.read()

if '$USE_PROXY' in ['y', 'Y']:
    nginx_block = f'''location ~ "^/$WEB_PATH(.*)\$" {{
    alias $PROJECT_DIR/build\$1;
    try_files \$uri \$uri/ /$WEB_PATH/index.html;
    
    # Подключить proxy snippet для API
    include /etc/nginx/snippets/${PROJECT_NAME}-proxy.conf;
}}
'''
else:
    nginx_block = f'''location ~ "^/$WEB_PATH(.*)\$" {{
    alias $PROJECT_DIR/build\$1;
    try_files \$uri \$uri/ /$WEB_PATH/index.html;
}}
'''

pattern = r'(server_name\s+.+;)'
replacement = r'\1\n\n' + nginx_block
content = re.sub(pattern, replacement, content)

with open('$SELECTED_CFG', 'w') as f:
    f.write(content)
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