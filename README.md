# 🚀 Multi-Server Subscription Manager v3.1

Комплексная система управления несколькими серверами с современным React интерфейсом.

## ✨ Что нового в v3.1

### 🎨 Система тем
- ☀️ Светлая и 🌙 темная тема
- Автоматическое сохранение выбора
- Переключатель в навигации
- [Screenshots](./screens.md)

### 📊 Новые компоненты

#### 1. **ClientManager** - Управление клиентами
- ✅ Batch добавление клиентов (множественная загрузка)
- 🗑️ Массовое удаление (по статусу: expired, depleted)
- 🔄 Сброс трафика (индивидуально или всех)
- 🔍 Фильтрация по узлам, протоколам, статусу
- 📥 Экспорт в CSV
- ✔️ Множественный выбор с чекбоксами

#### 2. **TrafficStats** - Визуализация трафика
- 📊 Bar charts (Top N клиентов/серверов)
- 🥧 Pie charts (Upload/Download распределение)
- 📈 Группировка по: Client / Inbound / Node
- 🟢 Список онлайн клиентов в реальном времени
- 📉 Адаптивные графики с Chart.js

#### 3. **BackupManager** - Бэкап/Восстановление
- 💾 Скачивание backup с каждого сервера
- 📦 Массовое скачивание всех backup (ZIP архив)
- 📤 Восстановление database из .db файла
- ⚠️ Предупреждения при операциях
- 🤖 Инструкции по автоматизации (cron)

#### 4. **ServerStatus** - Мониторинг
- 🖥️ CPU, RAM, Disk usage с прогресс-барами
- ⚡ Статус core-сервиса (версия, uptime)
- 🔄 Перезапуск core-сервиса одной кнопкой
- 🌐 Сетевой трафик в реальном времени
- ♻️ Auto-refresh с настраиваемым интервалом

#### 6. **AdGuard Integration** - DNS аналитика без агентов
- 🔌 Подключение удалённых AdGuard Home по `admin URL + login/password`
- 📈 Сбор DNS KPI: queries, blocked rate, latency, cache hit ratio, upstream errors
- 🧠 Top blocked domains и top clients
- 🗃️ История snapshots сохраняется локально в `admin.db` (`adguard_history`)
- 🛡️ Пароли источников шифруются тем же ключом, что и для узлов node panel

#### 5. **InboundManager** - Управление Inbound
- 📡 Просмотр всех inbound со всех серверов
- 🎯 Фильтрация по протоколу, security, узлу
- 📋 Клонирование inbound на другие серверы
- 🔒 Отображение Reality/TLS конфигураций

## 🏗️ Архитектура

```
┌─────────────────────────────────────────┐
│         React Frontend (Vite)           │
│  - 8 табов навигации                    │
│  - Chart.js графики                      │
│  - Light/Dark theme                      │
│  - Bootstrap UI                          │
└────────────┬────────────────────────────┘
             │ REST API (Basic Auth)
┌────────────▼────────────────────────────┐
│      FastAPI Backend (Python)           │
│  - 27+ API endpoints                    │
│  - PAM авторизация                      │
│  - Multi-threaded requests              │
└────────────┬────────────────────────────┘
             │
    ┌────────┴────────┬────────────────┐
    │                 │                │
┌───▼───┐      ┌──────▼──┐      ┌─────▼──┐
│ node panel │      │ node panel   │      │ node panel  │
│ Node1 │      │ Node2   │      │ Node3  │
└───────┘      └─────────┘      └────────┘
```

## 🚀 Быстрый старт

### Требования
- Ubuntu 24.04 (или 20.04+)
- Root доступ
- Nginx установлен и настроен
- Node.js 20+ (устанавливается автоматически скриптом install.sh)

### Установка
```bash
git clone https://github.com/Efidripy/multiserversubgen
cd multiserversubgen
chmod +x install.sh
sudo ./install.sh
```

Скрипт установит:
- ✅ Python 3 + venv + все зависимости
- ✅ Node.js + npm + React сборку
- ✅ Nginx конфигурацию с proxy_pass
- ✅ Systemd сервис
- ✅ Fail2ban защиту
- ✅ Prometheus + Grafana (опционально, по вопросу в установщике)
  - доступ к Grafana закрыт BasicAuth (логин/пароль задаются в install.sh)

### Обновление (рекомендуемый порядок)
```bash
git pull
sudo ./update.sh
```

Рекомендуется перед обновлением сделать backup:
```bash
curl -u admin:password https://your-domain/my-panel/api/v1/backup/all \
  -o backups_$(date +%Y%m%d).zip
```

В `update.sh` доступны режимы:
1. Полное обновление (backend + frontend)
2. Только backend
3. Только frontend
4. Только Nginx конфиг

## 📁 Структура проекта

```
multiserversubgen/
├── backend/
│   ├── main.py                # FastAPI приложение
│   ├── client_manager.py      # Управление клиентами
│   ├── inbound_manager.py     # Управление inbound
│   ├── server_monitor.py      # Мониторинг серверов
│   ├── websocket_manager.py   # WebSocket слой
│   ├── services/              # Collector + AdGuard сервисы
│   ├── routers/               # Отдельные роутеры API
│   └── tests/                 # Unit/регрессионные тесты
│
├── frontend/
│   ├── src/
│   │   ├── contexts/
│   │   │   └── ThemeContext.tsx     # Система тем
│   │   ├── components/
│   │   │   ├── ClientManager.tsx    # Управление клиентами
│   │   │   ├── TrafficStats.tsx     # Статистика трафика
│   │   │   ├── BackupManager.tsx    # Бэкапы
│   │   │   ├── ServerStatus.tsx     # Мониторинг
│   │   │   ├── InboundManager.tsx   # Inbound
│   │   │   ├── NodeManager.tsx      # Серверы
│   │   │   └── SubscriptionManager.tsx  # Подписки
│   │   ├── App.tsx                  # Главное приложение
│   │   └── main.tsx
│   └── package.json
│
├── install.sh              # Установщик
├── update.sh              # Обновление
├── API_DOCUMENTATION.md   # API документация
└── COMPONENTS_GUIDE.md    # Руководство по компонентам
```

## 🔧 Конфигурация

### Backend
- Порт: `666` (настраивается при установке)
- Путь: `/opt/sub-manager/` (или custom)
- Лог: `journalctl -u sub-manager -f`
- Runtime hardening env:
  - `ALLOW_ORIGINS` — CORS whitelist (через запятую)
  - `VERIFY_TLS` (`true/false`) — проверка TLS к node panel узлам
  - `CA_BUNDLE_PATH` — путь к кастомному CA bundle (опционально)
  - `READ_ONLY_MODE` (`true/false`) — блокирует `POST/PUT/DELETE/PATCH` для `/api/v1/*`
  - `SUB_RATE_LIMIT_COUNT` + `SUB_RATE_LIMIT_WINDOW_SEC` — лимит запросов к `/api/v1/sub/*`
  - `TRAFFIC_STATS_CACHE_TTL`, `ONLINE_CLIENTS_CACHE_TTL` — короткий cache для метрик в реальном времени
  - `TRAFFIC_MAX_WORKERS` — параллелизм сбора статистики по узлам
  - `COLLECTOR_BASE_INTERVAL_SEC`, `COLLECTOR_MAX_INTERVAL_SEC`, `COLLECTOR_MAX_PARALLEL` — adaptive background collector
  - `REDIS_URL` — optional Redis cache backend (для переживания рестартов процесса)
  - `AUDIT_QUEUE_BATCH_SIZE` — batch size для фонового дренажа persistent audit queue
  - `ROLE_VIEWERS`, `ROLE_OPERATORS` — RBAC списки пользователей через запятую (`admin` по умолчанию для остальных)
  - `MFA_TOTP_ENABLED`, `MFA_TOTP_USERS` — optional TOTP 2FA для всех защищённых `/api/v1/*` и WebSocket (`username:BASE32` через запятую)

Рекомендуемый профиль для снижения нагрузки (без заметной деградации UI):
- `TRAFFIC_STATS_CACHE_TTL=20`
- `ONLINE_CLIENTS_CACHE_TTL=20`
- `TRAFFIC_MAX_WORKERS=6`
- `COLLECTOR_BASE_INTERVAL_SEC=10`
- `COLLECTOR_MAX_PARALLEL=4`

### Observability
- `GET /metrics` — Prometheus-метрики HTTP (request count + latency)
- `GET /api/v1/snapshots/latest` — последний snapshot от background collector
- `GET /api/v1/health/deps` — readiness зависимостей (collector/redis)

Monitoring assets:
- `monitoring/prometheus/rules.yml` — alert rules (p95 latency, 5xx rate)
- `monitoring/grafana/sub-manager-dashboard.json` — базовый dashboard
- `monitoring/grafana/adguard-overview-dashboard.json` — dashboard для AdGuard (Prometheus + Loki)
- `monitoring/loki/loki-config.yml` — локальный single-node Loki
- `monitoring/promtail/promtail-config.yml` — сбор querylog/journal AdGuard в Loki
- Install/update scripts автоматически:
  - создают scrape для `http://127.0.0.1:<APP_PORT>/metrics`
  - при включении `ADGUARD_METRICS_ENABLED=true` добавляют scrape AdGuard:
    - targets из `ADGUARD_METRICS_TARGETS` (через запятую, например `127.0.0.1:3000,10.0.0.12:3000`)
    - path из `ADGUARD_METRICS_PATH` (по умолчанию `/control/prometheus/metrics`)
  - при включении `ADGUARD_LOKI_ENABLED=true` устанавливают `loki` + `promtail` и подключают datasource `Loki` в Grafana
    - `ADGUARD_QUERYLOG_PATH` (по умолчанию `/opt/AdGuardHome/data/querylog.json`)
    - `ADGUARD_SYSTEMD_UNIT` (по умолчанию `AdGuardHome.service`)
  - включают provisioning datasource/dashboard в Grafana
  - публикуют Grafana через subpath `/$WEB_PATH/grafana/` в Nginx
  - отключают `auth.anonymous` в Grafana и биндуют её на `127.0.0.1:3000`
  - поддерживают IP allowlist и optional mTLS (клиентские сертификаты) для путей панели

Быстрая проверка после включения AdGuard-интеграции:
```bash
sudo systemctl status prometheus grafana-server loki promtail --no-pager
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health:.health}'
curl -s http://127.0.0.1:3100/ready
```

### Frontend
- Сборка: `backend/build/`
- Путь в браузере: `https://your-domain/my-panel/` (настраивается)
- API прокси через Nginx
- Subpath поддержка: установщик автоматически выставляет `VITE_BASE` на основе введённого пути. Для ручной сборки используйте `VITE_BASE="/my-panel/" npm run build`

### API Base URL (subpath deployment)

Фронтенд определяет базовый URL для API автоматически:

| Переменная | Приоритет | Описание |
|---|---|---|
| `VITE_API_BASE_URL` | 1 (выше) | Явный override. Пример: `https://api.example.com` |
| `BASE_URL` (= `VITE_BASE`) | 2 (по умолчанию) | Автоматически выводится из пути деплоя |

**Примеры:**

| `VITE_BASE` | Итоговый `API_BASE` | URL API-запросов |
|---|---|---|
| `/` (по умолчанию) | `/api` | `https://domain/api/v1/...` |
| `/my-panel/` | `/my-panel/api` | `https://domain/my-panel/api/v1/...` |
| `/panel/` | `/panel/api` | `https://domain/panel/api/v1/...` |

Nginx-сниппет, генерируемый установщиком, автоматически совпадает с этими путями:
```nginx
location ^~ /my-panel/api/ { proxy_pass http://127.0.0.1:666/api/; ... }
location ^~ /my-panel/      { alias /opt/sub-manager/build/; ... }
```

> **⚠️ Важно:** Не открывайте `/api/` на корневом уровне в nginx без необходимости.
> Это раскрывает API на корне домена и является риском безопасности.
> Если нужна совместимость, добавьте отдельный location `/api/` явно в vhost-конфиг
> с пометкой — но это не рекомендуется для production-деплоя.

### База данных
- SQLite: `/opt/sub-manager/nodes.db`
- Автоматическое создание при первом запуске
- Backup через API или BackupManager UI

## 🔐 Безопасность

- ✅ PAM авторизация (системные пользователи)
- ✅ Basic Auth для всех API эндпоинтов
- ✅ Fail2ban интеграция (защита от брутфорса)
- ✅ Nginx rate limiting
- ⚠️ HTTPS обязателен для production

## 📚 Документация

- **API Documentation:** [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)
  - 27+ эндпоинтов
  - Примеры cURL и Python
  - Описание всех параметров

- **Components Guide:** [COMPONENTS_GUIDE.md](./COMPONENTS_GUIDE.md)
  - Детальное описание каждого компонента
  - Список возможностей
  - API endpoints для каждого компонента
  - Troubleshooting

## 🎯 API Примеры

> Замените `your-domain/my-panel` на ваш домен и путь деплоя.

### Получить статус серверов
```bash
curl -u admin:password https://your-domain/my-panel/api/v1/servers/status
```

### Batch добавление клиентов
```bash
curl -u admin:password -X POST https://your-domain/my-panel/api/v1/clients/batch-add \
  -H "Content-Type: application/json" \
  -d '{
    "inbound_id": 1,
    "clients": [
      {"email": "user1@example.com", "total_gb": 50, "expiry_days": 30},
      {"email": "user2@example.com", "total_gb": 100, "expiry_days": 60}
    ]
  }'
```

### Статистика трафика
```bash
curl -u admin:password "https://your-domain/my-panel/api/v1/traffic/stats?group_by=client"
```

### Скачать все backup
```bash
curl -u admin:password https://your-domain/my-panel/api/v1/backup/all \
  -o backups_$(date +%Y%m%d).zip
```

## 🧪 Локальная проверка

### Backend
```bash
cd /opt/sub-manager
source venv/bin/activate
python3 backend/main.py
```

### Frontend (dev mode)
```bash
cd /opt/sub-manager/frontend
npm run dev
# Откройте http://localhost:5173
```

### Production build
```bash
cd /opt/sub-manager/frontend
VITE_BASE="/my-panel/" npm run build
# Файлы собираются в /opt/sub-manager/backend/build
# Для размещения в корне: npm run build (VITE_BASE по умолчанию "/")
```

### Тесты и линт
```bash
# Frontend lint + build
cd /opt/sub-manager/frontend
npm run lint
npm run build

# Backend unit-тесты
cd /opt/sub-manager
source venv/bin/activate
pip install -r backend/requirements-dev.txt
pytest -q backend/tests
```

## 🛠️ Диагностика

- Логи backend: `journalctl -u sub-manager -f`
- Логи Nginx: `tail -f /var/log/nginx/error.log`
- Проверка состояния сервиса: `systemctl status sub-manager`
- Проверка API health: `curl -u admin:password https://your-domain/my-panel/api/v1/health/deps`

## 👥 Участие в разработке

1. Fork репозитория
2. Создайте feature branch
3. Commit изменения
4. Push в branch
5. Создайте Pull Request

## 📄 Лицензия

MIT License - используйте свободно!

## 🙏 Благодарности

- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://react.dev/)
- [Chart.js](https://www.chartjs.org/)
- [Vite](https://vitejs.dev/)
- [Bootstrap](https://getbootstrap.com/)

---

**Multi-Server Manager v3.1**
