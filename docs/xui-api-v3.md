# 3x-ui Panel API — v3

Панели версии **>= 3.0**. Клиенты — first-class объекты с собственными endpoint'ами.

## Auth

```
POST {base_url}/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin
```
Ответ содержит CSRF-токен в теле JSON (поле `token`) или заголовке `X-CSRF-Token`.

**Все POST-запросы обязаны передавать:**
```
X-CSRF-Token: <token>
```
GET работает без токена. POST без токена → 404 (без сообщения об ошибке).

---

## Server

### Статус сервера
```
GET /panel/api/server/status
```
Ответ obj содержит те же поля что v2 + **panelVersion: "3.2.0"** — признак v3.

### Перезапустить Xray
```
POST /panel/api/server/restartXrayService
X-CSRF-Token: <token>
```

---

## Clients (first-class API)

### Список всех клиентов
```
GET /panel/api/clients/list
```
Ответ obj[]: id(uuid), email, enable, inboundId, flow, limitIp, totalGB, expiryTime, reset, subId, tgId, up, down

### Добавить клиента
```
POST /panel/api/clients/add
X-CSRF-Token: <token>
{
  "clients": [{
    "id":"uuid4","email":"user@x","enable":true,
    "flow":"","limitIp":0,"totalGB":0,"expiryTime":0,
    "reset":0,"subId":"","tgId":"","inboundId":1
  }]
}
```

### Обновить клиента
```
POST /panel/api/clients/update/{email}
X-CSRF-Token: <token>
{"id":"uuid","email":"user@x","enable":true,"flow":"","limitIp":0,"totalGB":0,"expiryTime":0,"reset":0,"subId":"","tgId":""}
```

### Удалить клиента
```
POST /panel/api/clients/del/{email}
X-CSRF-Token: <token>
```

### Массовое удаление
```
POST /panel/api/clients/bulkDel
X-CSRF-Token: <token>
{"emails": ["user1@x", "user2@x"]}
```

### Удалить исчерпавших лимит
```
POST /panel/api/clients/delDepleted
X-CSRF-Token: <token>
```

### Онлайн-клиенты
```
POST /panel/api/clients/onlines
X-CSRF-Token: <token>
```
Ответ: {"success":true,"obj":["email1","email2"]}

### Трафик клиента
```
GET /panel/api/clients/traffic/{email}
```
Ответ obj: email, up, down, total, expiryTime

### Сбросить трафик клиента
```
POST /panel/api/clients/resetClientTraffic/{email}
X-CSRF-Token: <token>
```

### Массовый сброс трафика
```
POST /panel/api/clients/bulkResetTraffic
X-CSRF-Token: <token>
{"emails": ["user1@x", "user2@x"]}
```

### Массовое изменение параметров
```
POST /panel/api/clients/bulkAdjust
X-CSRF-Token: <token>
{"emails":["user1@x"],"totalGB":10,"expiryTime":1700000000000,"enable":true,"reset":0}
```

### Последнее время онлайн
```
POST /panel/api/clients/lastOnline
X-CSRF-Token: <token>
{"emails": ["user1@x"]}
```

### Ссылки подключения
```
GET /panel/api/clients/links/{email}
```

### IP-адреса клиента
```
POST /panel/api/clients/ips/{email}
POST /panel/api/clients/clearIps/{email}    (X-CSRF-Token required)
```

### Subscription links по subId
```
GET /panel/api/clients/subLinks/{subId}
```

### Привязать/отвязать от inbound
```
POST /panel/api/clients/{email}/attach
{"inboundIds": [1, 2]}

POST /panel/api/clients/{email}/detach
{"inboundIds": [1]}
```
Оба требуют X-CSRF-Token.

---

## Groups (только v3)

```
GET  /panel/api/clients/groups
POST /panel/api/clients/groups/create       {"name":"group"}
POST /panel/api/clients/groups/rename       {"oldName":"old","newName":"new"}
POST /panel/api/clients/groups/delete       {"name":"group"}
POST /panel/api/clients/groups/bulkAdd      {"groupName":"g","emails":["user@x"]}
POST /panel/api/clients/groups/bulkRemove   {"groupName":"g","emails":["user@x"]}
GET  /panel/api/clients/groups/{name}/emails
```
Все POST требуют X-CSRF-Token.

---

## Inbounds

```
GET  /panel/api/inbounds/list
POST /panel/api/inbounds/add                {...inbound fields...}
POST /panel/api/inbounds/del/{id}
POST /panel/api/inbounds/update/{id}        {...inbound fields...}
POST /panel/api/inbounds/setEnable/{id}     {"enable":true}    ← новый в v3
POST /panel/api/inbounds/{id}/resetTraffic
POST /panel/api/inbounds/resetAllTraffics
POST /panel/api/inbounds/{id}/delAllClients
```
Все POST требуют X-CSRF-Token.

---

## Ключевые отличия от v2

| Особенность | v2 | v3 |
|---|---|---|
| panelVersion в status | Отсутствует | "3.x.x" |
| CSRF-токен | Не нужен | Обязателен на всех POST |
| ID клиента | UUID | Email |
| Хранение клиентов | JSON-строка в settings inbound | Отдельная таблица |
| Bulk операции | Нет | bulkDel, bulkAdjust, bulkResetTraffic |
| Groups | Нет | Есть |
| setEnable inbound | Нет (через update) | Есть |
| Детект | 404 на /clients/list | 200 на /clients/list, panelVersion >= 3 |
