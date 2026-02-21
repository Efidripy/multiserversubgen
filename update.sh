#!/bin/bash

# --- СКРИПТ ОБНОВЛЕНИЯ MULTI-SERVER MANAGER v3.1 ---
LOG_FILE="/opt/.sub_manager_install.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Запустите от root!"
    exit 1
fi

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Установка не найдена. Сначала выполните ./install.sh"
    exit 1
fi

source "$LOG_FILE"

clear
echo "======================================================"
echo "    MULTI-SERVER MANAGER - ОБНОВЛЕНИЕ v3.1"
echo "======================================================"
echo "Проект: $PROJECT_NAME"
echo "Путь: $PROJECT_DIR"
echo "Порт: $APP_PORT"
echo "Web путь: /$WEB_PATH/"
echo "======================================================"
echo ""
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
        cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
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
        echo "  → Сборка Vite..."
        mkdir -p "$PROJECT_DIR/build"
        if ! npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
            echo "  ❌ Ошибка сборки фронтенда. Обновление прервано."
            exit 1
        fi
        cd - > /dev/null
        echo "  ✓ Frontend пересобран"
        
        echo "[5/5] Перезапуск сервиса..."
        systemctl daemon-reload
        systemctl start "$PROJECT_NAME"
        ;;
        
    2) # Только Backend
        echo "[1/3] Остановка сервиса..."
        systemctl stop "$PROJECT_NAME"
        
        echo "[2/3] Обновление модулей Backend..."
        cp "$SCRIPT_DIR/backend/"*.py "$PROJECT_DIR/"
        echo "  ✓ Скопировано $(ls -1 "$SCRIPT_DIR/backend/"*.py | wc -l) модулей"
        
        echo "  → Обновление зависимостей..."
        "$PROJECT_DIR/venv/bin/pip" install --upgrade -r "$SCRIPT_DIR/backend/requirements.txt" > /dev/null 2>&1
        
        echo "[3/3] Перезапуск сервиса..."
        systemctl start "$PROJECT_NAME"
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
        echo "  → Сборка Vite..."
        mkdir -p "$PROJECT_DIR/build"
        if ! npx --no-install vite build --outDir "$PROJECT_DIR/build" --emptyOutDir; then
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
        echo "  ✓ Обновлен snippet: $SNIPPET_FILE"

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
        echo "Адрес панели: https://$(hostname -f)/$WEB_PATH/"
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
fi

echo ""
echo "📦 Резервная копия сохранена: $BACKUP_DIR"
echo ""
echo "Для удаления старых бэкапов (>7 дней):"
echo "  find /var/backups/${PROJECT_NAME}_backup_* -type d -mtime +7 -exec rm -rf {} +"
echo ""
