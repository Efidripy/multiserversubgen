# Telegram: опциональный локальный VLESS transport

## Назначение

Стандартная установка использует прямой HTTPS-доступ к Telegram Bot API и не
требует Xray sidecar. Это значение по умолчанию (`direct`) и оно не меняет
поведение существующих инсталляций.

`Local VLESS` — отдельная, необязательная опция для хоста, которому нужен
выделенный маршрут Bot API. Только запросы Telegram из `sub-manager` идут в
локальный HTTP CONNECT listener, затем через отдельный VLESS-клиент на
назначенный EU сервер. Трафик панели, нод, SSH и других сервисов не меняется.

Если Telegram не может установить входящее соединение с хостом (например,
webhook на РФ-хосте недоступен с его стороны), укажите
`TELEGRAM_MODE=polling`. В этом режиме `sub-manager` сам получает обновления
через тот же локальный transport; публичный webhook не используется.

```text
sub-manager → 127.0.0.1:<local-port> (HTTP CONNECT) → VLESS Reality → EU → Telegram Bot API
```

Локальный HTTP CONNECT выбран намеренно: Python runtime использует его без
глобальных proxy-переменных и сторонних SOCKS-обёрток. Если нужен SOCKS для
ручной диагностики, его можно добавить отдельным loopback inbound, но бот его
не использует.

## Контроль и секреты

- В панели `Telegram → Транспорт Bot API` есть `Напрямую` и `Локальный VLESS`.
- Нельзя включить `Локальный VLESS`, пока `TELEGRAM_LOCAL_PROXY_URL` не
  настроен и listener недоступен на loopback.
- URL локального proxy (включая при необходимости HTTP proxy login/password),
  UUID и Reality-параметры не возвращаются API и не хранятся в SQLite. Они
  живут только в root-owned runtime secrets/config.
- Если выбран `Локальный VLESS`, а sidecar недоступен, отправка Bot API
  завершается ошибкой. Прямого fallback нет.
- Polling перед первым чтением снимает ранее установленный webhook, но не
  сбрасывает ожидающие обновления. Поэтому пользовательский `/start` не
  теряется при переходе с webhook.
- Выбор режима хранится в SQLite как не-секретная настройка, начинается с
  `direct` и использует optimistic versioning.

## Подготовка сервера

Не выполнять это автоматически через installer/update. Sidecar устанавливает
администратор только на нужном хосте после проверки rollback.

### Вариант A: готовый loopback proxy уже есть

Если Xray уже слушает loopback HTTP CONNECT endpoint, его можно использовать
без создания второго процесса Xray. Сначала подтвердить, что порт принадлежит
только localhost и что тест Bot API через него проходит. Затем записать полный
URL, включая proxy authentication при её наличии, в runtime secrets и выбрать
`Локальный VLESS` в панели. Не менять существующий listener и не создавать
sidecar на том же порту.

### Вариант B: отдельный sidecar

Шаблон `ops/telegram-egress/telegram-egress.json.template` намеренно использует
порт `1082`, чтобы не конфликтовать с обычным локальным proxy на `1081`.

1. Подготовить отдельный Xray binary, не управляемый существующим X-UI.
2. Создать системного пользователя `telegram-egress`, каталоги
   `/var/lib/telegram-egress` и `/etc/sub-manager` с минимальными правами.
3. Скопировать `ops/telegram-egress/telegram-egress.json.template` в
   `/etc/sub-manager/telegram-egress.json`, заменить все `__...__` значениями
   отдельного EU VLESS Reality клиента и задать фактический порт EU inbound.
4. Сделать конфиг доступным для чтения только `root:telegram-egress` (`0640`).
5. Установить `ops/telegram-egress/telegram-egress.service` как
   `/etc/systemd/system/telegram-egress.service`, при необходимости указав
   корректный путь к выделенному Xray binary.
6. После `systemctl daemon-reload` сначала проверить синтаксис Xray config,
   затем запустить sidecar. До явного `enable` он не стартует при загрузке.
7. В `/etc/sub-manager/runtime-secrets.env` добавить:

   ```ini
   TELEGRAM_LOCAL_PROXY_URL=http://<proxy-user>:<proxy-password>@127.0.0.1:1082
   ```

   Если listener не требует HTTP proxy authentication, используются только
   `http://127.0.0.1:1082`. Для готового loopback proxy вместо `1082` указывают
   его фактический порт. Пароль должен быть percent-encoded, если в нём
   есть символы URL-разделителей.

8. Перезапустить только `sub-manager`, открыть панель и убедиться, что
   локальный transport помечен как готовый. Лишь затем переключить режим.

## Проверка и откат

Перед переключением панели проверить tunnel без Bot token, используя
локальный HTTP CONNECT endpoint. После переключения проверить `getMe` и
`getWebhookInfo`; provisioning нод остаётся отдельным выключенным interlock.

Откат: в панели выбрать `Напрямую`. Затем можно остановить
`telegram-egress.service` и удалить только его конфиг/юнит после отдельного
backup и подтверждения. SQLite и основные сервисы не требуют отката.
