# 🚀 Multi-Server Subscription Manager v3.1

Комплексная система управления несколькими серверами 3X-UI/Xray с современным React интерфейсом.

## ✨ Что нового в v3.1

### 🎨 Система тем
- ☀️ Светлая и 🌙 темная тема
- Автоматическое сохранение выбора
- Переключатель в навигации

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
- ⚡ Статус Xray (версия, uptime)
- 🔄 Перезапуск Xray одной кнопкой
- 🌐 Сетевой трафик в реальном времени
- ♻️ Auto-refresh с настраиваемым интервалом

#### 5. **InboundManager** - Управление Inbound
- 📡 Просмотр всех inbound со всех серверов
- 🎯 Фильтрация по протоколу, security, узлу
- 📋 Клонирование inbound на другие серверы
- 🔒 Отображение Reality/TLS конфигураций

## 🏗️ Архитектура

```
┌─────────────────────────────────────────┐
│         React Frontend (Vite)           │
│  - 7 табов навигации                    │
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
│ 3X-UI │      │ 3X-UI   │      │ 3X-UI  │
│ Node1 │      │ Node2   │      │ Node3  │
└───────┘      └─────────┘      └────────┘
```

## 🚀 Быстрый старт

### Требования
- Ubuntu 24.04 (или 20.04+)
- Root доступ
- Nginx установлен и настроен

### Установка
```bash
git clone <repo-url>
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

### Обновление
```bash
sudo ./update.sh
```

Выберите режим:
1. Полное обновление (backend + frontend)
2. Только backend
3. Только frontend
4. Только Nginx конфиг

## 📁 Структура проекта

```
multiserversubgen/
├── backend/
│   ├── main.py              # FastAPI приложение
│   ├── client_manager.py    # Управление клиентами
│   ├── inbound_manager.py   # Управление inbound
│   ├── server_monitor.py    # Мониторинг серверов
│   └── db.py               # База данных
│
├── frontend/
│   ├── src/
│   │   ├── contexts/
│   │   │   └── ThemeContext.tsx     # Система тем
│   │   ├── components/
│   │   │   ├── App.tsx              # Главное приложение
│   │   │   ├── ClientManager.tsx    # Управление клиентами
│   │   │   ├── TrafficStats.tsx     # Статистика трафика
│   │   │   ├── BackupManager.tsx    # Бэкапы
│   │   │   ├── ServerStatus.tsx     # Мониторинг
│   │   │   ├── InboundManager.tsx   # Inbound
│   │   │   ├── NodeManager.tsx      # Серверы
│   │   │   └── SubscriptionManager.tsx  # Подписки
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

### Frontend
- Сборка: `backend/build/`
- Путь в браузере: `https://your-domain/my-vpn/` (настраивается)
- API прокси через Nginx

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

### Получить статус серверов
```bash
curl -u admin:password https://your-domain/api/v1/servers/status
```

### Batch добавление клиентов
```bash
curl -u admin:password -X POST https://your-domain/api/v1/clients/batch-add \
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
curl -u admin:password "https://your-domain/api/v1/traffic/stats?group_by=client"
```

### Скачать все backup
```bash
curl -u admin:password https://your-domain/api/v1/backup/all \
  -o backups_$(date +%Y%m%d).zip
```

## 🧪 Тестирование

### Backend
```bash
cd /opt/sub-manager
source venv/bin/activate
python3 main.py
```

### Frontend (dev mode)
```bash
cd frontend
npm run dev
# Откройте http://localhost:5173
```

### Production build
```bash
cd frontend
npm run build
# Файлы в build/
```

## 🐛 Известные проблемы

1. **Chart.js не отображается:**
   - Проверьте, установлен ли `chart.js` и `react-chartjs-2`
   - Пересоберите фронтенд: `npm run build`

2. **API возвращает 401:**
   - Проверьте учетные данные PAM
   - Убедитесь, что пользователь существует в системе

3. **Backup не скачивается:**
   - Проверьте доступ к 3X-UI серверам
   - Убедитесь в правильности credentials

## 🔄 Миграция с v3.0

1. Создайте backup текущей базы
2. Запустите `sudo ./install.sh` и выберите "Обновить"
3. Frontend автоматически пересоберется с новыми компонентами
4. Все данные сохранятся

## 📈 Roadmap

- [ ] WebSocket для real-time обновлений
- [ ] Групповые операции с inbound
- [ ] Улучшенная subscription генерация (группировка)
- [ ] Push уведомления
- [ ] Multi-language support
- [ ] Mobile приложение

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
- [3X-UI](https://github.com/MHSanaei/3x-ui)
- [Vite](https://vitejs.dev/)
- [Bootstrap](https://getbootstrap.com/)

---

**Multi-Server Manager v3.1** - Made with ❤️ by developers, for developers
