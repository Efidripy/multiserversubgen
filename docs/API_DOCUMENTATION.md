# Multi-Server Manager API Documentation v3.2

**Contract status:** production control-plane contract, verified against the
current production composition root on 2026-08-21. The experimental
`backend/modules/*` tree is not the production router authority.

## Аутентификация
Защищённые management endpoints принимают Basic Auth (PAM авторизация). Для
browser-панели Basic Auth используется только для bootstrap: успешный
`POST /api/v1/auth/session` создаёт восьмичасовую подписанную cookie с
`HttpOnly`, `Secure` и `SameSite=Strict`; после этого same-origin запросы
используют сессию без хранения пароля в browser storage. `POST
/api/v1/auth/logout` удаляет cookie.

Исключения: health (`/health`, `/api/v1/health`), MFA status
(`/api/v1/auth/mfa-status`) и subscription delivery endpoints. Последние
принимают постоянный opaque token, сохранённый сервером, а не raw email или
group id.

```bash
Authorization: Basic base64(username:password)
```

---

## 📊 Health Check

### `GET /api/v1/health`
Проверка работоспособности API

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-20T22:52:00"
}
```

---

## 🖥️ Server Management

### `GET /api/v1/nodes`
Получить список всех серверов

Ответ — JSON-массив. Пароль, bearer token и расшифрованные секреты намеренно
не возвращаются.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Server-NL",
    "ip": "123.45.67.89",
    "port": "443",
    "username": "admin",
    "panel_url": "https://123.45.67.89:443/path",
    "base_path": "path",
    "read_only": false,
    "tags": []
  }
]
```

### `POST /api/v1/nodes`
Добавить новый сервер

**Request:**
```json
{
  "name": "Server-DE",
  "url": "https://123.45.67.89:443/path/",
  "user": "admin",
  "password": "password123"
}
```

Нужен либо `bearer_token`, либо пара `user` + `password`. Одновременно
передавать bearer и credential-пару нельзя.

### `PUT /api/v1/nodes/{node_id}`

Частично обновить узел. Разрешены `name`, `url`, `user`, `password`,
`bearer_token`, `read_only` и `tags`.

- Пустые secret-поля означают ошибку, а отсутствующие secret-поля сохраняют
  текущие значения.
- `password` можно заменить без повторной передачи `user` для credential-node.
- Для замены bearer-а на credential-пару нужны одновременно `user` и
  `password`.
- При смене URL или способа аутентификации сбрасываются session/auth и
  capability cache этой ноды.

### `DELETE /api/v1/nodes/{node_id}`
Удалить сервер

---

## 📡 Inbound Management

### `GET /api/v1/inbounds?protocol=vless&security=reality`
Получить все инбаунды со всех серверов с фильтрацией

**Query Parameters:**
- `protocol` (optional): vless, vmess, trojan
- `security` (optional): reality, tls

**Response:**
```json
{
  "inbounds": [
    {
      "id": 1,
      "node_name": "Server-NL",
      "node_ip": "123.45.67.89",
      "protocol": "vless",
      "port": 443,
      "remark": "Main VLESS",
      "enable": true,
      "security": "reality",
      "is_reality": true
    }
  ],
  "count": 1
}
```

### `POST /api/v1/inbounds`
Добавить инбаунд на все серверы

**Request:**
```json
{
  "port": 8443,
  "protocol": "vless",
  "remark": "New Inbound",
  "settings": {},
  "streamSettings": {}
}
```

### `POST /api/v1/inbounds/clone`
Клонировать инбаунд с одного сервера на другие

**Request:**
```json
{
  "source_node_id": 1,
  "source_inbound_id": 2,
  "target_node_ids": [2, 3],
  "modifications": {
    "remark": "Cloned Inbound",
    "port": 8443
  }
}
```

### `DELETE /api/v1/inbounds/{inbound_id}?node_id=1`
Удалить инбаунд с сервера

---

## 👥 Client Management

### `GET /api/v1/clients?email=user@example.com`
Получить всех клиентов со всех серверов

**Query Parameters:**
- `email` (optional): фильтр по email

**Response:**
```json
{
  "clients": [
    {
      "id": "uuid",
      "email": "user@example.com",
      "enable": true,
      "expiryTime": 0,
      "totalGB": 100,
      "node_name": "Server-NL",
      "inbound_id": 1,
      "inbound_remark": "Main VLESS",
      "protocol": "vless"
    }
  ],
  "count": 1
}
```

### `POST /api/v1/clients/batch-add`
Массово добавить клиентов

**Request:**
```json
{
  "node_ids": [1, 2, 3],
  "clients": [
    {
      "email": "user@example.com",
      "inbound_id": 1,
      "totalGB": 100,
      "expiryTime": 1735689600000,
      "enable": true
    }
  ]
}
```

### `PUT /api/v1/clients/{client_uuid}`
Обновить параметры клиента

**Request:**
```json
{
  "node_id": 1,
  "inbound_id": 1,
  "updates": {
    "email": "newemail@example.com",
    "enable": false,
    "totalGB": 200
  }
}
```

### `DELETE /api/v1/clients/{client_uuid}?node_id=1&inbound_id=1`
Удалить клиента

### `POST /api/v1/clients/batch-delete`
Массово удалить клиентов с фильтрами

**Request:**
```json
{
  "node_ids": [1, 2],
  "email_pattern": "test",
  "expired_only": false,
  "depleted_only": false
}
```

**Response:**
```json
{
  "results": [
    {
      "node": "Server-NL",
      "deleted_count": 5,
      "errors": []
    }
  ]
}
```

### `POST /api/v1/clients/{client_uuid}/reset-traffic`
Сбросить трафик клиента

**Request:**
```json
{
  "node_id": 1,
  "inbound_id": 1,
  "email": "user@example.com"
}
```

### `GET /api/v1/clients/online`
Совместимый плоский список записей online из последнего snapshot Collector.
Не запускает новый опрос нод; один Email может иметь несколько записей только
если он действительно наблюдался online на нескольких конкретных нодах.

**Response:**
```json
{
  "online_clients": [
    {
      "email": "user@example.com",
      "node_id": "12",
      "node_name": "Server-NL"
    }
  ],
  "count": 1
}
```

### `GET /api/v1/clients/presence`

Лёгкая authenticated-проекция присутствия для списка клиентов. Она читает
только последний штатный snapshot Collector и **не** запускает новый опрос
подключённых 3x-ui панелей при открытии страницы.

`online_emails` и `last_seen` — агрегированные по Email данные для parent
группы и общего счётчика. `online_by_node` и `last_seen_by_node` привязывают
наблюдение к конкретной ноде: child record не отмечается online только потому,
что такой же Email online на другой ноде. `node_names` сопоставляет `node_id`
из этой проекции с отображаемым именем без отдельного запроса списка нод.
Timestamp — результат штатного
наблюдения Collector, не отдельного запроса к панели. Записи `last_seen`
удерживаются в памяти до 30 дней.

**Response:**

```json
{
  "projection": "client-presence-v1",
  "timestamp": 1735689600.0,
  "online_emails": ["user@example.com"],
  "online_by_node": {
    "12": ["user@example.com"]
  },
  "node_names": {
    "12": "nl-1"
  },
  "last_seen": {
    "user@example.com": 1735689600.0
  },
  "last_seen_by_node": {
    "12": {
      "user@example.com": 1735689600.0
    }
  }
}
```

---

## 📈 Traffic Statistics

### `GET /api/v1/traffic/stats?group_by=client`
Получить агрегированную статистику трафика

**Query Parameters:**
- `group_by`: client | inbound | node

**Response:**
```json
{
  "stats": {
    "user@example.com": {
      "up": 1073741824,
      "down": 5368709120,
      "total": 6442450944,
      "count": 3
    }
  },
  "group_by": "client"
}
```

---

## 🧭 Dashboard Summary

### `GET /api/v1/dashboard/summary?period=all_time`

Лёгкая сводка для Dashboard. Поддерживаемые значения `period`: `day`,
`week`, `month`, `all_time`. Ответ строится из уже собранной локальной
traffic projection и snapshots: этот endpoint не инициирует запросы к
подключённым 3x-ui панелям при открытии Dashboard.

Для `day`, `week` и `month` история может быть временно недоступна, пока не
появится baseline snapshot. В этом случае `traffic` и `top_clients` пустые,
а `traffic_note` объясняет состояние; all-time данные остаются доступны из
последней projection.

**Response:**
```json
{
  "nodes_total": 5,
  "nodes_online": 4,
  "clients_total": 24,
  "online_clients_total": 7,
  "online_by_node": {"nl-1": 3, "fi-1": 4},
  "traffic": {"upload": 1073741824, "download": 5368709120, "total": 6442450944},
  "traffic_period": "week",
  "traffic_note": null,
  "top_clients": [
    {"email": "user@example.com", "upload": 1048576, "download": 8388608, "total": 9437184}
  ]
}
```

### `GET /api/v1/dashboard/overview?period=all_time`

Канонический ответ для начальной загрузки Dashboard: объединяет summary и
лёгкий статус зарегистрированного fleet в одном запросе. Он читает только
локальные collector snapshots и traffic projection; remote 3x-ui probes не
запускаются. Поле `fleet` намеренно не содержит credentials, bearer tokens,
полные inbound/client inventories или raw panel responses.

```json
{
  "projection": "dashboard-v1",
  "summary": {"nodes_total": 5, "nodes_online": 4, "online_clients_total": 7},
  "fleet": [
    {
      "id": 1,
      "name": "nl-1",
      "panel_url": "https://nl-1.example.test/panel",
      "available": true,
      "online_clients": 3,
      "poll_ms": 42.1,
      "system": {"cpu": 12.5},
      "xray": {"running": true}
    }
  ]
}
```

### `GET /api/v1/snapshots/latest`

Возвращает тот же bounded `dashboard-v1` node projection для совместимых
экранов. Полный collector snapshot является внутренним runtime-артефактом;
для детальных inbound/client операций используйте специализированные API.

---

## 🔧 Automation

### `POST /api/v1/automation/reset-all-traffic`
Сбросить весь трафик на узлах

**Request:**
```json
{
  "node_ids": [1, 2],
  "inbound_id": 1
}
```

---

## 🖥️ Server Monitoring

### `GET /api/v1/servers/status`
Получить статус всех серверов (CPU, RAM, диск, core service)

**Response:**
```json
{
  "servers": [
    {
      "node": "Server-NL",
      "available": true,
      "timestamp": "2026-02-20T22:52:00",
      "system": {
        "cpu": 15.5,
        "mem": {
          "current": 2147483648,
          "total": 8589934592,
          "percent": 25.0
        },
        "disk": {
          "current": 21474836480,
          "total": 107374182400,
          "percent": 20.0
        },
        "uptime": 259200,
        "loads": [0.5, 0.7, 0.6]
      },
      "xray": {
        "state": "running",
        "running": true,
        "version": "1.8.6",
        "uptime": 86400
      },
      "network": {
        "upload": 1073741824,
        "download": 5368709120
      }
    }
  ],
  "count": 1
}
```

### `GET /api/v1/servers/{node_id}/status`
Получить детальный статус конкретного сервера

### `GET /api/v1/servers/availability`
Проверить доступность всех серверов (ping + latency)

**Response:**
```json
{
  "availability": [
    {
      "node": "Server-NL",
      "available": true,
      "latency_ms": 45.23,
      "status_code": 200,
      "timestamp": "2026-02-20T22:52:00"
    }
  ]
}
```

### `POST /api/v1/servers/{node_id}/restart-xray`
Перезапустить core service на сервере

### `GET /api/v1/servers/{node_id}/logs?count=100&level=info`
Получить логи с сервера

**Query Parameters:**
- `count`: количество строк (по умолчанию 100)
- `level`: debug | info | warning | error

---

## 💾 Backup & Restore

### `GET /api/v1/backup/database/{node_id}`
Получить резервную копию базы данных с сервера в JSON-обёртке с base64 body.
Это management/API-контракт, не лёгкий metadata endpoint.

**Response:**
```json
{
  "node": "Server-NL",
  "backup_b64": "base64_encoded_data",
  "encoding": "base64",
  "timestamp": "2026-02-20T22:52:00"
}
```

### `POST /api/v1/backup/database/{node_id}`
Импортировать резервную копию базы данных на сервер

**Request:**
```json
{
  "backup_data": "base64_sqlite_db_or_sqlite_migration_dump"
}
```

Перед удалённым restore API принимает только SQLite database с сигнатурой
`SQLite format 3` или SQLite migration dump, который после BOM/пробелов
начинается с `PRAGMA` либо `BEGIN TRANSACTION`. Полная integrity-проверка
остаётся обязанностью целевой панели перед заменой её БД.

### `GET /api/v1/backup/node/{node_id}`

Скачать один backup как binary SQLite-файл. Этот путь используется UI для
явного download и отдаёт `Cache-Control: no-store`.

### `POST /api/v1/backup/node/{node_id}/import`

Импортировать загруженный multipart-файл в поле `file`. Операция заменяет базу
ноды и требует явного подтверждения в UI. UI ограничивает file picker
расширениями `.db`, `.sqlite` и `.sqlite3`; сервер не доверяет filename и MIME
type, а проверяет первые 64 байта. Принимаются SQLite database или совместимый
SQLite migration dump (`PRAGMA`/`BEGIN TRANSACTION` после BOM/пробелов) размером
до 8 MiB; неподдерживаемый формат отклоняется до вызова restore на ноде.

### `GET /api/v1/backup/all`
Скачать ZIP с резервными копиями всех серверов. По умолчанию ответ — binary
ZIP. `?format=json` — legacy management режим, который содержит полные base64
database bodies для всех нод; он не должен использоваться для initial render
или списка в UI.

---

## 🔗 Subscriptions

### `GET /api/v1/emails`
Получить список всех email'ов клиентов

**Response:**
```json
{
  "emails": ["user1@example.com", "user2@example.com"],
  "stats": {
    "user1@example.com": {
      "count": 5,
      "last": "20.02 22:30"
    }
  }
}
```

`GET /api/v1/emails` is a protected management endpoint. Its
`subscription_tokens` map is the only supported way to obtain an email token.
Do not expose or construct subscription links from a raw email address.

### `GET /api/v1/sub/{token}`

Public subscription delivery endpoint. The opaque token is created once and
remains valid until an administrator explicitly regenerates it. Optional
`protocol` and `nodes` filters apply before the base64-encoded response is
returned. Requests are rate-limited and include no-cache headers. A legacy raw
email URL and a previously issued HMAC URL receive a temporary `302` redirect
to the current token URL when the matching active subscription exists.

### `GET /api/v1/sub-grouped/{token}`

Public grouped-subscription delivery endpoint. Its token is returned only by the
protected `GET /api/v1/subscription-groups` management endpoint.

### `/api/v1/subscription-groups`

`GET`, `POST`, `PUT /{group_id}` and `DELETE /{group_id}` require Basic Auth.
The `GET` response includes each group's stable `subscription_token`.

### `POST /api/v1/subscription-tokens/{kind}/{identifier}/regenerate`

Admin-only manual rotation for `kind=email` or `kind=group`. It returns a new
opaque token and invalidates the prior URL immediately. The panel asks for
confirmation before calling it; token refreshes never rotate links.
---

## Коды ошибок

- **200** - Успешно
- **400** - Неверный запрос
- **401** - Не авторизован
- **404** - Не найдено
- **500** - Внутренняя ошибка сервера

---

## Примеры использования

### cURL примеры

```bash
# Получить список серверов
curl -u admin:password https://your-domain.com/my-panel/api/v1/nodes

# Добавить клиента
curl -u admin:password -X POST https://your-domain.com/my-panel/api/v1/clients/batch-add \
  -H "Content-Type: application/json" \
  -d '{
    "node_ids": [1],
    "clients": [{
      "email": "test@example.com",
      "inbound_id": 1,
      "totalGB": 100
    }]
  }'

# Получить статус серверов
curl -u admin:password https://your-domain.com/my-panel/api/v1/servers/status

# Получить статистику трафика
curl -u admin:password https://your-domain.com/my-panel/api/v1/traffic/stats?group_by=client
```

### Python примеры

```python
import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "https://your-domain.com/my-panel"
auth = HTTPBasicAuth("admin", "password")

# Получить клиентов
response = requests.get(f"{BASE_URL}/api/v1/clients", auth=auth)
clients = response.json()

# Массовое добавление клиентов
data = {
    "node_ids": [1, 2],
    "clients": [
        {"email": f"user{i}@example.com", "inbound_id": 1, "totalGB": 50}
        for i in range(10)
    ]
}
response = requests.post(f"{BASE_URL}/api/v1/clients/batch-add", json=data, auth=auth)
```

---

**Версия:** 3.2
**Дата контракта:** 21.08.2026
