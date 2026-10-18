# Ops / Эксплуатация

## Полезные команды

### Статус и логи

```bash
systemctl status sub-manager
journalctl -u sub-manager -f
```

### Browser-сессия и рестарты

Подписанный browser cookie живёт до 8 часов и переживает reload только при
стабильном signing key. Production systemd должен загружать
`/etc/sub-manager/runtime-secrets.env` через `EnvironmentFile` и включать
`REQUIRE_PERSISTENT_SECRETS=true`; файл должен иметь режим `0600` и содержать
`WS_AUTH_SECRET` и `SUBSCRIPTION_SIGNING_SECRET`. `scripts/deploy/server-deploy.sh`
проверяет этот контракт до staging/перезапуска. Если контракт нарушен, deploy
останавливается без изменения рабочей директории и базы данных.

После успешного browser bootstrap Dashboard использует ту же защищённую
HttpOnly session cookie для периодического refresh. Basic Auth остаётся нужен
для исходного API bootstrap и внешних API-клиентов, но не должен повторяться
в minute-poll Dashboard.

### Graceful shutdown и deploy

`sub-manager` перед остановкой закрывает admission новых фоновых операций и
ждёт terminal result уже начатых SQLite, Telegram, XUI, collector, audit и
AdGuard операций. `TimeoutStopSec=120` ограничивает ожидание systemd. Если
остановка не стала успешной и inactive, canonical deploy завершится до SQLite
checkpoint, backup, swap или restore/start. Не пытайтесь обходить это ручным
checkpoint, restart или восстановлением БД: сначала требуется отдельный
incident recovery с проверенным rollback anchor.
### Безопасное удаление установки

`scripts/installer/remove.sh`, legacy-ветки удаления в `install.sh` и
`update.sh` выполняют destructive/update-операции только при наличии
`/opt/.sub_manager_install.log`: это должен быть обычный (не symlink) файл
`root:root` с режимом `0600`. Скрипт получает из него имя и каталог проекта и
проверяет, что каталог строго равен `/opt/<PROJECT_NAME>`. Если state-log
отсутствует, повреждён, имеет неверные owner/mode или содержит неожиданную
identity, скрипт завершится до подтверждения и до любых изменений в системе с
сообщением `no removal performed`.

Не подменяйте state-log переменными окружения и не запускайте автоматическое
удаление «по умолчанию». Для legacy/orphan установки сначала восстановите
подтверждённую identity из резервной копии или проведите отдельно рассмотренный
ручной recovery.

Пункты **Remove Installation** в лаунчере всегда используют
project-scoped режим (`REMOVE_SCOPE=soft`) и обязательно запрашивают `yes`.
Они не запускают host-wide cleanup: не удаляют системные пакеты и общие
каталоги nginx, Let's Encrypt, XUI, Grafana или Prometheus.
Сценарий аварийного host-wide recovery не доступен из меню: он требует прямого
запуска `remove.sh` с `REMOVE_SCOPE=hard`, точного ввода
`ERASE_HOST_WIDE_STACK`, а затем обычного `yes`. Используйте его только на
выделенном хосте после проверенного backup: этот режим намеренно может удалить
общие сервисы и данные хоста.

### Проверки

```bash
APP_PORT="${APP_PORT:-666}"
curl -s -o /dev/null -w 'health=%{http_code}\n' "http://127.0.0.1:${APP_PORT}/health"
curl -fsSL -o /dev/null -w 'panel=%{http_code}\n' https://<your-domain>/<web-path>/
```

### Nginx

```bash
nginx -t
systemctl reload nginx
tail -f /var/log/nginx/error.log
```

## Frontend subpath и `VITE_BASE`

Для subpath-деплоя frontend должен быть собран с корректным base:

`scripts/deploy/server-deploy.sh` по умолчанию читает действующие `WEB_PATH` и
`GRAFANA_WEB_PATH` из systemd unit до сборки. Поэтому обычный update сохраняет
установленные приватные пути; передавать эти переменные вручную допустимо только
для контролируемой миграции путей. Если effective unit не содержит корректный
путь, deploy прекращается до замены release.

```bash
cd frontend
VITE_BASE="/<web-path>/" npm run build
```

Артефакты публикуются в `backend/build`.

## Диагностика 404 по JS/CSS

Проверить, какие URL реально в `index.html`:

```bash
grep -E 'script|stylesheet' backend/build/index.html
```

Проверить доступность assets:

```bash
curl -fsSL -o /dev/null -w '%{http_code}\n' https://<your-domain>/<web-path>/assets/<file>.js
```

### Совместимость со старым кэшем

Если пользователи уже закэшировали старый `index.html`, можно временно держать compatibility-route для `/assets/*` в nginx.

## Monitoring

### OBS-001: bounded request attribution

`OBSERVABILITY_ATTRIBUTION_ENABLED` выключен по умолчанию. При явном включении
в разрешённой среде он добавляет passive Prometheus counters и histograms для
разложения запроса на admission, cache source, SQLite и node RPC. Он не меняет
response, cache value, SQLite query или node request.

`admission` измеряет путь до передачи управления route handler: authentication,
RBAC, CSRF и read-only gate. SQLite — длительность каждого вызова
`Connection.execute`, включая результат `locked`/`busy`; это не полное время
query/fetch/commit и не отдельное измерение lock wait. Node RPC — длительность
проверки destination и одной HTTP attempt; retry фиксируется как отдельная
attempt, а не как wire-time удалённого узла.

Единственные metric labels — bounded enum: endpoint class, component,
operation, outcome и cache source. Raw URLs, SQL, database paths, node
names/IDs, emails, tokens, cookies, credentials и request IDs никогда не
становятся labels. Correlation остаётся в `X-Request-ID`; `Server-Timing`
показывает aggregate component durations, bounded cache source и `unaccounted` — только консервативный остаток после суммы компонентов. Компоненты могут перекрываться; `unaccounted` не является lock/thread wait или полной классификацией очереди.

Для воспроизводимого cold/warm browser waterfall без MSSG runtime, node или
external network access запустите local fixture из checkout worktree:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\run-obs001-browser-baseline.ps1
```

Fixture принимает только loopback, отдаёт CSP `connect-src 'self'`, использует
временную SQLite БД и проверяет `memory_miss` для cold и `memory_fresh` для warm
policy read. Он завершается ошибкой при ненулевом fake-node counter,
неожиданных fixture routes или ненулевом exit code каждого Playwright step.
Все временные browser artifacts удаляются runner-ом после прогона. Это fixture
acceptance, а не доказательство production p95, browser UX реальных операторов
или отсутствия egress у сторонних расширений браузера. Для rollback выключите
feature flag или удалите collectors: request behavior не меняется.

### Cadence collector

По умолчанию `COLLECTOR_ACTIVE_INTERVAL_SEC=90`: после warming и при active
WebSocket-сессии следующий node poll не растягивается стабильными snapshot-ами
дольше 90 секунд. `COLLECTOR_IDLE_INTERVAL_SEC=300`: без active-сессии collector
переходит на node poll раз в 5 минут. После `COLLECTOR_IDLE_AFTER_SEC` (default
900 секунд без WebSocket-activity) active режим также возвращается в idle;
`force_poll` остаётся немедленным.

Это интервал remote snapshot/persistence node poll, а не выключатель control
loop. Когда все известные `next_poll` находятся в будущем, collector перечитывает
локальный inventory не чаще одного раза в 60 секунд; более ранний известный
`next_poll` сохраняет свой deadline. Добавление или удаление node поэтому видны
не позднее следующего 60-секундного recheck. WebSocket-activity может немедленно
разбудить loop только для пересчёта режима, но не становится `force_poll`;
явный `force_poll` остаётся немедленным. Изменение cadence не меняет bounded
fan-out, SQLite policy, XUI fallback или dashboard snapshot-first contract. Для
rollback верните изолированный source commit; schema и persistent runtime state
не затрагиваются.

### Фоновые collector/audit metrics

Эти метрики включены всегда и passive: они не делают новых SQLite-запросов, не
меняют bounded fan-out collector-а и не изменяют поведение audit worker. Ошибка
экспортёра метрик не должна менять outcome polling, SQLite batch или audit queue.

- `sub_manager_collector_poll_cycle_duration_seconds` — длительность только
  успешно завершённого poll cycle, в котором был хотя бы один due node. Использует
  monotonic `perf_counter` и включает bounded polling, snapshot persistence и
  completed-snapshot callback. Idle/no-due и оборванные error cycles не наблюдаются.
- `sub_manager_collector_poll_cycles_total{mode,trigger}` — число завершённых
  poll cycle с хотя бы одним due node. `mode` — режим, зафиксированный после
  проверки WebSocket-activity в начале цикла; `trigger` имеет только
  `scheduled` и `force_poll`. Рост этого счётчика сам по себе не доказывает
  active cadence: нормальные сроки `next_poll` у разных nodes могут быть
  разнесены.
- `sub_manager_collector_poll_cycle_due_nodes{mode,trigger}` — histogram числа
  due nodes в таких же завершённых cycle. Это кандидаты до polling attempt, а
  не число успешных XUI snapshots. Вместе с предыдущей series он отделяет
  количество cycle от размера работы, не добавляя SQLite read.
- В authenticated `collector.runtime_status().last_cycle` также сохраняются
  тот же `mode` и `trigger` последнего завершённого loop cycle, включая cycle
  без due node. Это bounded operational receipt без WebSocket count, node ID,
  URL или user data.
- `sub_manager_sqlite_batch_rows{operation}` — количество строк в semantic SQLite
  batch после commit. Единственные фиксированные `operation`:
  `collector_snapshot_upsert`, `node_history_insert`, `audit_memory_persist`,
  `audit_event_drain`. Это не измерение SQL duration, fetch/commit latency, lock
  wait или физических disk bytes.
- `sub_manager_audit_memory_queue_depth` — приблизительный `qsize` process-local
  bounded audit queue после изменения состояния. Это не durable backlog таблицы
  `audit_events` и не повод делать дополнительный `COUNT(*)`.
- `sub_manager_audit_events_dropped_total{reason}` — отброшенные события с
  фиксированными `reason`: `full`, `closed`, `persist_error`.

В labels не попадают SQL, database path, URL, node/user/request ID, email, token
или другая приватная runtime data. Эти signals помогают разделить collector/audit
pulse; они не доказывают production p95, distributed trace или alert delivery.

### Деградация недоступных XUI nodes

Collector хранит последний успешный snapshot node в памяти. Если очередной
background XUI transport attempt не отвечает, node остаётся `available=false`,
но её предыдущие агрегаты не обнуляются: в dashboard projection появляются
`stale=true`, `last_success_at` и `last_attempt_at`. Это означает «сейчас
недоступна, показаны последние подтверждённые значения», а не отсутствие
клиентов, inbounds или трафика. Для node, у которой ещё не было успешного
snapshot, `stale=false` и новых значений не создаётся.

Только обычный scheduled poll получает node-local backoff после подряд идущих
transport failures: 300 секунд после первого, 600 после второго и 900 после
третьего и последующих. `force_poll` намеренно обходит этот backoff; healthy
nodes, общий cadence, bounded fan-out и SQLite policy не меняются. Успешный
completed snapshot сбрасывает failure state и возвращает node к обычному
режиму.

Для collector-initiated poll raw adapter diagnostics подавляются только в его
process-local `ContextVar`: интерактивные/API XUI calls сохраняют прежние
warnings. Вместо потока одинаковых сообщений collector пишет один redacted
warning при первом transport failure, затем не чаще одного агрегированного
warning на node за 900 секунд и один recovery info при успехе. Сообщения не
содержат URL, node ID/name, credentials, token, клиента или request path.

Этот state не имеет SQLite schema и очищается при restart. Он не меняет XUI,
клиентов, subscription, provisioning, Telegram, RBAC или durable job/outbox
семантику. Для rollback достаточно вернуть изолированный source commit; данные
и runtime migration не требуются.

См. директории:

- `monitoring/prometheus/`
- `monitoring/grafana/`
- `monitoring/loki/`
- `monitoring/promtail/`

Promtail собирает AdGuard querylog всегда, когда включён Loki-профиль. Journal
scrape добавляется только при наличии читаемого `/var/log/journal` или, как
fallback, `/run/log/journal`; отсутствие обоих каталогов — нормальный режим,
который не должен приводить к перезапускам сервиса. Для ручной сверки после
изменения monitoring-конфига используйте `systemctl status promtail` и
`journalctl -u promtail -n 50 --no-pager`.

## Полезные скрипты

- `scripts/ops/smoke-test.sh`
- `scripts/ops/backup-restore-check.sh` — проверяет online SQLite backup/restore. Его verification-артефакты (`/var/backups/<project>_verify_<timestamp>/`) сохраняются по умолчанию. Проверить их объём: `sudo bash scripts/ops/backup-restore-check.sh list`. Для безопасного preview cleanup: `sudo bash scripts/ops/backup-restore-check.sh prune-verify-artifacts --older-than 30`; фактическое удаление требует отдельного `--apply`. Команда намеренно не выбирает обычные `<project>_backup_*` или deploy backups.
- `scripts/ops/hardening-profile.sh`
- `scripts/deploy/server-deploy.sh`

## Связанные документы

- [Установка](./INSTALL.md)
- [Обновление](./UPDATE.md)
- [API](./API.md)
