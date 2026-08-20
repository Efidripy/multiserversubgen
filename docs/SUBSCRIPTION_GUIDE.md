# 🔗 Subscription System Guide - v3.1

Полное руководство по улучшенной системе генерации подписок с фильтрацией и группировкой.

---

## 📋 Обзор

Новая система подписок v3.1 предоставляет:
- ✅ Фильтрация по протоколу (vless, vmess, trojan)
- ✅ Фильтрация по узлам (nodes)
- ✅ Групповые подписки по идентификатору
- ✅ Два режима просмотра: Individual и Grouped
- ✅ Автоматическая группировка по домену и префиксу

---

## 🎯 Режимы работы

### 1. Individual Mode (Индивидуальные)
Стандартный режим - одна подписка для одного email.

**Особенности:**
- Каждый email имеет свою уникальную ссылку
- Статистика скачиваний для каждого
- Поддержка фильтрации

### 2. Grouped Mode (Групповые)
Автоматическая группировка клиентов по общим признакам.

**Группировка по:**
- **Домену:** Все email с одинаковым доменом
  - Пример: `user1@company.com`, `user2@company.com` → группа `company.com`
- **Префиксу:** Email с одинаковым началом (3+ символа)
  - Пример: `admin1@...`, `admin2@...` → группа `admin`

---

## 🔌 API Endpoints

### Security contract

Публичные endpoints `/api/v1/sub/{token}` и `/api/v1/sub-grouped/{token}` не требуют отдельного login-запроса от subscription-клиента. `{token}` — постоянный opaque bearer token, который сервер создаёт один раз и хранит в SQLite. Он не меняется при refresh панели или рестарте сервиса.

Старые URL с raw email/group identifier, а также ранее выданные HMAC URL, временно получают `302` redirect на текущую постоянную ссылку, если соответствующая подписка ещё существует. Новым клиентам выдаются только новые token URL.

Администратор получает подписанные токены через authenticated API:

```bash
# Ответ содержит subscription_tokens для email и subscription_token для групп.
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  https://your-domain/api/v1/emails
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  https://your-domain/api/v1/subscription-groups
```

Используйте выданные значения без изменения и не передавайте их сторонним QR/API-сервисам:

```bash
SUBSCRIPTION_TOKEN='<token-from-authenticated-api>'
curl "https://your-domain/api/v1/sub/$SUBSCRIPTION_TOKEN?protocol=vless"
```

Токены не имеют срока действия. Ротация выполняется только вручную кнопкой «Перегенерировать ссылку подписки» в панели (с подтверждением); прежняя ссылка после этого немедленно перестаёт работать. QR генерируется локально в браузере — ссылка не отправляется внешнему QR-сервису.

### 1. Индивидуальная подписка

#### `GET /api/v1/sub/{token}`

**Без фильтров:**
```bash
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN"
```

**С фильтром протокола:**
```bash
# Только VLESS
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?protocol=vless"

# Только VMess
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?protocol=vmess"

# Только Trojan
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?protocol=trojan"
```

**С фильтром узлов:**
```bash
# Только из узлов US и UK
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?nodes=US,UK"
```

**Комбинация фильтров:**
```bash
# VLESS только с узлов NL и DE
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?protocol=vless&nodes=NL,DE"
```

---

### 2. Групповая подписка

#### `GET /api/v1/sub-grouped/{token}`

**По домену:**
```bash
# Все клиенты с доменом @company.com
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN"
```

**По префиксу:**
```bash
# Все email начинающиеся с "admin"
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN"

# Все email содержащие "user"
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN"
```

**С фильтрами:**
```bash
# Все admin* только VLESS
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN?protocol=vless"

# Все company.com только с узлов US и UK
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN?nodes=US,UK"
```

---

## 💻 Использование в UI

### Фильтры

1. **Protocol Filter** - выпадающий список:
   - All Protocols (по умолчанию)
   - VLESS
   - VMess
   - Trojan

2. **Node Filter** - кнопки выбора узлов:
   - Клик по кнопке узла - добавить/убрать из фильтра
   - Кнопка "Clear" - очистить все выбранные узлы
   - Можно выбрать несколько узлов одновременно

3. **Режим просмотра:**
   - 👤 Individual - индивидуальные подписки
   - 📁 Grouped - групповые подписки

### Individual Mode

**Таблица отображает:**
- Email адрес клиента
- Количество скачиваний
- Дату последнего скачивания
- Ссылку подписки (с учетом фильтров)
- Кнопку Copy

**Ссылка автоматически обновляется** при изменении фильтров!

### Grouped Mode

**Карточки групп показывают:**
- Идентификатор группы (домен или префикс)
- Количество клиентов в группе
- Список всех email в группе
- Ссылку для групповой подписки
- Кнопку Copy

---

## 🎨 Примеры использования

### Сценарий 1: Корпоративные клиенты

**Задача:** Все сотрудники компании используют email @company.com

**Решение:**
```
Режим: Grouped
Идентификатор: company.com
Ссылка: https://your-domain/api/v1/sub-grouped/<signed-group-token>
```

Одна ссылка для всех сотрудников! При добавлении нового email @company.com он автоматически попадет в подписку.

---

### Сценарий 2: VIP клиенты только VLESS

**Задача:** VIP клиенты хотят только VLESS соединения

**Решение:**
```
Режим: Individual
Email: vip@example.com
Protocol Filter: VLESS
Ссылка: https://your-domain/api/v1/sub/<signed-email-token>?protocol=vless
```

---

### Сценарий 3: Географическое разделение

**Задача:** Европейские клиенты должны использовать только EU серверы

**Решение:**
```
Режим: Grouped
Идентификатор: eu
Node Filter: NL, DE, UK
Ссылка: https://your-domain/api/v1/sub-grouped/<signed-group-token>?nodes=NL,DE,UK
```

---

### Сценарий 4: Тестовые аккаунты

**Задача:** Все test* аккаунты должны использовать только один сервер

**Решение:**
```
Режим: Grouped
Идентификатор: test
Node Filter: TestServer
Protocol Filter: vmess
Ссылка: https://your-domain/api/v1/sub-grouped/<signed-group-token>?protocol=vmess&nodes=TestServer
```

---

## 🔧 Технические детали

### Кэширование

Система использует кэш для оптимизации:
- TTL: 60 секунд
- Кэш ключ: `email_protocol_nodes`
- Автоматическая инвалидация при изменении узлов

### Группировка (алгоритм)

1. **По домену:**
   - Извлечение части после `@`
   - Группы создаются для 2+ email с одинаковым доменом

2. **По префиксу:**
   - Regex: `^([a-zA-Z]{3,})`
   - Минимум 3 буквы до цифр/символов
   - Группы создаются для 2+ email с одинаковым префиксом

### Формат ответа

**Стандартный ответ (Base64):**
```
base64_encode(link1\nlink2\nlink3...)
```

Декодированный формат - стандартный subscription format для generic clients клиентов.

---

## 📊 Статистика

Система отслеживает для каждого email:
- `count` - общее количество скачиваний
- `last_download` - дата и время последнего скачивания (формат: `DD.MM HH:MM`)

**Важно:** Статистика обновляется и для групповых подписок - каждый email в группе получает +1 к счетчику.

---

## 🚨 Обработка ошибок

### 404 Not Found

**Когда возникает:**
- Email не существует в системе
- Identifier не соответствует ни одному email (grouped mode)
- После фильтрации не осталось клиентов

**Ответ:**
```
Status: 404
Content: "Not found" или "No matching clients found"
```

### Пустые фильтры

Если фильтры указаны, но результат пустой - возвращается 404.

---

## 💡 Лучшие практики

### 1. Используйте групповые подписки для организаций
```bash
# ✅ Хорошо - одна ссылка для отдела
/api/v1/sub-grouped/sales?nodes=US,EU

# ❌ Плохо - 20 индивидуальных ссылок
/api/v1/sub/<signed-email-token-1>
/api/v1/sub/<signed-email-token-2>
...
```

### 2. Применяйте фильтры для оптимизации

```bash
# ✅ Хорошо - только нужные серверы
/api/v1/sub/<signed-email-token>?nodes=FastServer

# ❌ Плохо - все серверы, включая медленные
/api/v1/sub/<signed-email-token>
```

### 3. Используйте протокол фильтр для совместимости

```bash
# ✅ Хорошо - для старых клиентов
/api/v1/sub/<signed-email-token>?protocol=vmess

# ✅ Хорошо - для новых клиентов
/api/v1/sub/<signed-email-token>?protocol=vless
```

### 4. Структурируйте email для группировки

```
✅ Хорошо:
- team1@company.com
- team2@company.com
→ Автоматически группируется по "company.com"

✅ Хорошо:
- admin-us@domain.com
- admin-eu@domain.com
→ Автоматически группируется по "admin"

❌ Плохо:
- u1@domain1.com
- user@domain2.com
- a@domain3.com
→ Нет общих признаков для группировки
```

---

## 🔐 Безопасность

### Публичный доступ

Эндпоинты `/sub/` и `/sub-grouped/` доступны subscription-клиентам без интерактивной авторизации, но требуют постоянный opaque token. Это bearer credential: не публикуйте его и вручную перевыпускайте при компрометации.

**Рекомендации:**
- Получайте токены только через authenticated API.
- Передавайте ссылки только по HTTPS и не вставляйте их во внешние QR/API-сервисы.
- При компрометации токенов ротируйте `SUBSCRIPTION_SIGNING_SECRET` и выдайте новые ссылки.

### Защита от брутфорса

Используется встроенный fail2ban:
- Лимит: 10 запросов/минуту на IP
- Блокировка: 1 час после превышения

---

## 📈 Миграция с v3.0

Старые ссылки с raw email/identifier больше не совместимы: это намеренное security-изменение.

```bash
# Получите новые значения через authenticated API.
# Individual:
/api/v1/sub/<signed-email-token>
/api/v1/sub/<signed-email-token>?protocol=vless

# Grouped:
/api/v1/sub-grouped/<signed-group-token>
```

Старые raw-ссылки должны быть заменены на токены из `/api/v1/emails` и `/api/v1/subscription-groups`.

---

## 🐛 Troubleshooting

### Проблема: Grouped подписка пустая

**Причина:** Недостаточно клиентов с совпадающим identifier

**Решение:**
```bash
# Проверить все email
curl -u admin:pass https://your-domain/api/v1/emails

# Убедиться что есть 2+ email с общим признаком
```

### Проблема: Фильтр по узлу не работает

**Причина:** Неправильное имя узла (case-sensitive!)

**Решение:**
```bash
# ✅ Правильно
?nodes=US,UK

# ❌ Неправильно
?nodes=us,uk  # имена должны точно совпадать
```

### Проблема: Ссылки не обновляются при изменении фильтров

**Причина:** Кэш браузера

**Решение:**
1. Обновить страницу (F5)
2. Или подождать 60 секунд (TTL кэша)

---

## 📞 API Reference

### Параметры запроса

| Параметр   | Тип     | Значения                    | Описание                           |
|------------|---------|-----------------------------|------------------------------------|
| `protocol` | string  | vless, vmess, trojan        | Фильтр по протоколу                |
| `nodes`    | string  | node1,node2,node3           | Список узлов через запятую         |

### Примеры curl

```bash
# Базовая подписка
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN"

# С протоколом
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?protocol=vless"

# С узлами
curl "https://your-domain/api/v1/sub/$EMAIL_TOKEN?nodes=US,EU"

# Групповая
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN"

# Групповая с фильтрами
curl "https://your-domain/api/v1/sub-grouped/$GROUP_TOKEN?protocol=trojan&nodes=SecureNode"
```

---

## 📝 Changelog v3.1

**Добавлено:**
- ✅ Фильтрация по протоколу (?protocol=)
- ✅ Фильтрация по узлам (?nodes=)
- ✅ Endpoint /sub-grouped/{identifier}
- ✅ UI с двумя режимами просмотра
- ✅ Автоматическая группировка клиентов
- ✅ Визуальные фильтры в UI
- ✅ Динамическое обновление ссылок

**Улучшено:**
- 🔧 Кэширование учитывает фильтры
- 🔧 Статистика для групповых подписок
- 🔧 UI с поддержкой тем

**Совместимость:**
- ✅ 100% обратная совместимость с v3.0
- ✅ Старые ссылки работают без изменений

---

**Версия:** 3.1  
**Дата:** 2026-02-20
