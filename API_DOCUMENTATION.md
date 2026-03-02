# Multi-Server Manager API Documentation v3.1

## Аутентификация
Все API endpoints требуют Basic Auth (PAM авторизация).

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

**Response:**
```json
[
  {
    "id": 1,
    "name": "Server-NL",
    "ip": "123.45.67.89",
    "port": "443",
    "user": "admin",
    "password": "decrypted_password",
    "base_path": ""
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
Получить список онлайн клиентов

**Response:**
```json
{
  "online_clients": [
    {
      "email": "user@example.com",
      "node": "Server-NL"
    }
  ],
  "count": 1
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
Получить резервную копию базы данных с сервера

**Response:**
```json
{
  "node": "Server-NL",
  "backup": "base64_encoded_data",
  "timestamp": "2026-02-20T22:52:00"
}
```

### `POST /api/v1/backup/database/{node_id}`
Импортировать резервную копию базы данных на сервер

**Request:**
```json
{
  "backup_data": "base64_or_sql_data"
}
```

### `GET /api/v1/backup/all`
Получить резервные копии баз данных со всех серверов

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

### `GET /api/v1/sub/{email}`
Получить подписку для email'а (без авторизации, base64 encoded)

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

**Версия:** 3.1  
**Дата:** 20.02.2026
