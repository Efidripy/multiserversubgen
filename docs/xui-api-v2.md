# 3x-ui Panel API — v2

Панели версии **< 3.0**. Клиенты хранятся внутри inbound как JSON-строка в поле `settings`.

## Auth

```
POST {base_url}/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin
```
Cookie сессии устанавливается в ответе. CSRF-токен **не требуется**.

---

## Server

### Статус сервера
```
GET /panel/api/server/status
```
Поле `panelVersion` **отсутствует** — признак v2.

Ответ obj содержит: cpu, cpuCores, mem{current,total}, swap, disk, xray{state,version}, uptime, loads[], tcpCount, netIO{up,down}, netTraffic{sent,recv}, publicIP{ipv4,ipv6}

### Перезапустить Xray
```
POST /panel/api/server/restartXrayService
```

### Логи Xray
```
GET /panel/api/server/logs/{count}
```

---

## Inbounds

### Список всех inbound
```
GET /panel/api/inbounds/list
```
Возвращает массив obj[]. Клиенты вложены в settings как **JSON-строка** — нужен json.loads().
Поля inbound: id, remark, enable, protocol, port, settings(JSON-str), streamSettings, up, down, total, expiryTime, clientStats[]

### Добавить inbound
```
POST /panel/api/inbounds/add
{"remark":"name","protocol":"vless","port":443,"enable":true,
 "settings":"{\"clients\":[],\"decryption\":\"none\"}",
 "streamSettings":"{\"network\":\"tcp\",\"security\":\"tls\"}",
 "sniffing":"{\"enabled\":true}","total":0,"expiryTime":0}
```

### Удалить inbound
```
POST /panel/api/inbounds/del/{id}
```

### Обновить inbound
```
POST /panel/api/inbounds/update/{id}
{ ...те же поля что при add... }
```

### Включить/выключить inbound
Нет отдельного endpoint. Схема: GET /list → изменить enable → POST /update/{id}

### Сбросить трафик inbound
```
POST /panel/api/inbounds/{id}/resetTraffic
POST /panel/api/inbounds/resetAllTraffics
```

### Удалить всех клиентов из inbound
```
POST /panel/api/inbounds/{id}/delAllClients
```

---

## Clients (вложены в inbound.settings)

### Добавить клиента
```
POST /panel/api/inbounds/addClient
{
  "id": <inbound_id>,
  "settings": "{\"clients\":[{\"id\":\"uuid4\",\"email\":\"user@x\",\"enable\":true,\"flow\":\"\",\"limitIp\":0,\"totalGB\":0,\"expiryTime\":0,\"reset\":0,\"subId\":\"\",\"tgId\":\"\"}]}"
}
```
UUID обязателен. `id` — ID inbound.

### Обновить клиента
```
POST /panel/api/inbounds/updateClient/{uuid}
{"id":<inbound_id>,"settings":"{\"clients\":[{...updated fields...}]}"}
```

### Удалить клиента
```
POST /panel/api/inbounds/{inbound_id}/delClient/{uuid}
```

### Онлайн-клиенты
```
POST /panel/api/inbounds/onlines
```
Ответ: {"success":true,"obj":["email1","email2"]}

### Трафик клиента
```
GET /panel/api/inbounds/getClientTraffics/{email}
GET /panel/api/inbounds/getClientTrafficsById/{uuid}
```
Ответ obj: id, inboundId, email, up, down, total, expiryTime, reset

### Сбросить трафик клиента
```
POST /panel/api/inbounds/resetClientTraffic/{email}
POST /panel/api/inbounds/resetAllTraffics/{inbound_id}
```

---

## Ключевые особенности v2

| Особенность | Описание |
|---|---|
| Клиенты в settings | JSON-строка внутри inbound, нужен json.loads() |
| Нет panelVersion | Отсутствует в /server/status — признак v2 |
| Auth | Cookie session, без CSRF |
| ID клиента | UUID, не email |
| Нет bulk API | Поштучные операции |
| Детект v2 | /panel/api/clients/list возвращает 404 |
