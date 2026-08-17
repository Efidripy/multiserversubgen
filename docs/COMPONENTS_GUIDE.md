# Multi-Server Manager v3.1 - Components Guide

## 📋 Обзор компонентов

Проект теперь включает полный набор React компонентов для управления мультисерверной системой node panel/core service.

---

## 🎨 Темы (Theme System)

### ThemeContext
**Файл:** `frontend/src/contexts/ThemeContext.tsx`

**Функционал:**
- Поддержка светлой и темной темы
- Автосохранение выбора в localStorage
- Единая цветовая схема для всех компонентов
- Переключатель темы в навигации и на странице входа

**Цветовые схемы:**
- **Dark Theme:** GitHub-стиль темная тема (по умолчанию)
- **Light Theme:** Светлая тема с мягкими цветами

---

## 📊 Dashboard (ServerStatus)

**Файл:** `frontend/src/components/ServerStatus.tsx`

**Возможности:**
- Real-time мониторинг всех серверов
- Отображение CPU, RAM, Disk usage с прогресс-барами
- Статус core service (версия, uptime, running/stopped)
- Сетевой трафик (upload/download)
- Кнопка перезапуска core service
- Auto-refresh с настраиваемым интервалом
- Индикация доступности серверов

**API Endpoints:**
- `GET /api/v1/servers/status` - статус всех серверов
- `POST /api/v1/servers/{node_id}/restart-xray` - перезапуск core service

---

## 📡 Inbound Manager

**Файл:** `frontend/src/components/InboundManager.tsx`

**Возможности:**
- Просмотр всех inbound со всех серверов
- Фильтрация по протоколу, security, узлу
- Клонирование inbound на другие серверы
- Удаление inbound
- Отображение Reality/TLS конфигураций
- Статус (Active/Disabled) для каждого inbound

**API Endpoints:**
- `GET /api/v1/inbounds` - список всех inbound
- `POST /api/v1/inbounds/clone` - клонирование
- `DELETE /api/v1/inbounds/{id}` - удаление

---

## 👥 Client Manager

**Файл:** `frontend/src/components/ClientManager.tsx`

**Возможности:**

### Просмотр и фильтрация:
- Поиск по email
- Фильтры по узлу, протоколу, статусу
- Статусы: Active, Disabled, Expired, Depleted
- Отображение трафика (upload/download/total)
- Даты истечения срока

### Batch операции:
- **Batch Add:** Добавление множества клиентов из списка
  - Email адреса (по одному на строку)
  - Total GB (опционально)
  - Expiry Days (опционально)
- **Batch Delete:** Удаление выбранных/истекших/исчерпанных клиентов
- **Reset Traffic:** Сброс трафика для одного или всех клиентов

### Экспорт данных:
- Экспорт в CSV с полной информацией
- Формат: Email, Node, Protocol, Status, Upload, Download, Total, Expiry

**API Endpoints:**
- `GET /api/v1/clients` - список всех клиентов
- `POST /api/v1/clients/batch-add` - массовое добавление
- `POST /api/v1/clients/batch-delete` - массовое удаление
- `POST /api/v1/clients/{id}/reset-traffic` - сброс трафика
- `POST /api/v1/automation/reset-all-traffic` - сброс всех

---

## 📈 Traffic Statistics

**Файл:** `frontend/src/components/TrafficStats.tsx`

**Возможности:**

### Визуализация (Chart.js):
- **Bar Chart:** Top N по трафику
  - Группировка: Client / Inbound / Node
  - Upload/Download раздельно
- **Pie Chart:** Распределение Upload/Download
- Адаптивные графики с поддержкой тем

### Статистика:
- Total Upload/Download/Traffic
- Количество онлайн клиентов
- Top N таблица с детальной информацией
- Список онлайн клиентов в реальном времени

### Настройки:
- Группировка: по клиенту, inbound или узлу
- Show Top: 5, 10, 20, 50

**API Endpoints:**
- `GET /api/v1/traffic/stats?group_by=client` - статистика трафика
- `GET /api/v1/clients/online` - онлайн клиенты

---

## 💾 Backup Manager

**Файл:** `frontend/src/components/BackupManager.tsx`

**Возможности:**

### Скачивание бэкапов:
- Индивидуальный backup для каждого сервера
- Скачивание всех backup одним архивом (ZIP)
- Прогресс-индикация для каждой операции
- Автоматическое именование: `backup_NodeName_YYYY-MM-DD.db`

### Восстановление:
- Выбор узла для восстановления
- Загрузка .db файла
- Предупреждения о замене БД
- Информация о размере файла

### Автоматизация:
- Инструкции по настройке cron для автобэкапа
- Пример команды с curl

**API Endpoints:**
- `GET /api/v1/backup/{node_id}` - скачать backup узла
- `GET /api/v1/backup/all` - скачать все backup (ZIP)
- `POST /api/v1/backup/{node_id}/import` - восстановить backup

---

## 🔗 Subscription Manager

**Файл:** `frontend/src/components/SubscriptionManager.tsx`

**Возможности:**
- Список всех email подписок
- Статистика скачиваний для каждого email
- Дата последнего скачивания
- Copy-кнопка для быстрого копирования URL
- Автогенерация ссылок: защищённый API возвращает краткоживущий signed token; ссылка имеет вид `https://your-domain/api/v1/sub/{token}`.

---

## 🖥️ Node (Server) Manager

**Файл:** `frontend/src/components/NodeManager.tsx`

**Возможности:**
- Добавление узлов node panel
- Список всех узлов с IP и портом
- Удаление узлов
- Форма добавления: Name, URL, Login, Password

---

## 🎯 Навигация (App.tsx)

**Вкладки:**
1. **📊 Dashboard** - ServerStatus с мониторингом
2. **🖥️ Servers** - NodeManager + ServerStatus
3. **📡 Inbounds** - InboundManager
4. **👥 Clients** - ClientManager
5. **📈 Traffic** - TrafficStats
6. **💾 Backup** - BackupManager
7. **🔗 Subscriptions** - SubscriptionManager

**Навигация:**
- Tab-based интерфейс
- Кнопка переключения темы (Light/Dark)
- Информация о пользователе
- Logout кнопка

---

## 📦 Зависимости

### Backend (Python):
```
fastapi
uvicorn[standard]
requests
python-pam
urllib3
cryptography
python-multipart
aiofiles
```

### Frontend (Node.js):
```
react
react-dom
axios
bootstrap
chart.js
react-chartjs-2
typescript
vite
```

### Системные (Ubuntu 24):
```
python3-pip
python3-venv
python3-dev
libpam0g-dev
build-essential
sqlite3
nginx
fail2ban
psmisc
curl
wget
git
nodejs
npm
```

---

## 🚀 Установка

```bash
chmod +x install.sh
sudo ./install.sh
```

Скрипт автоматически:
1. Установит все системные зависимости
2. Создаст Python venv с нужными пакетами
3. Соберет React фронтенд (включая Chart.js)
4. Настроит Nginx с proxy_pass
5. Создаст systemd сервис
6. Настроит fail2ban

---

## 🔄 Обновление

```bash
sudo ./update.sh
```

Или через install.sh выбрать опцию "Обновить (сохранить данные)".

---

## 🎨 Кастомизация темы

Для изменения цветовой схемы отредактируйте:
`frontend/src/contexts/ThemeContext.tsx`

```typescript
const lightTheme = {
  bg: { primary: '...', secondary: '...', tertiary: '...' },
  text: { primary: '...', secondary: '...' },
  accent: '...',
  success: '...',
  danger: '...',
  warning: '...',
  info: '...',
  border: '...'
};
```

---

## 📝 API Документация

Полная документация API доступна в файле: [`API_DOCUMENTATION.md`](./API_DOCUMENTATION.md)

Все эндпоинты требуют Basic Auth:
```bash
curl -u username:password https://your-domain/api/v1/...
```

---

## 🐛 Troubleshooting

### Фронтенд не собирается:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Backend не запускается:
```bash
systemctl status sub-manager
journalctl -u sub-manager -f
```

### Проблемы с темой:
Очистить localStorage:
```javascript
localStorage.removeItem('app_theme');
```

---

## 📧 Поддержка

Для отчетов об ошибках создайте issue с:
- Версией ОС
- Версией Node.js (`node --version`)
- Версией Python (`python3 --version`)
- Логами из journalctl
- Скриншотом ошибки (если frontend)
