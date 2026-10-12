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
```

Loopback подтверждает только внутреннюю готовность приложения. Canonical FQDN,
DNS и TLS проверяются после deploy с внешнего observer (Windows host или
разрешённый CI runner), а не из той же VM:

```bash
PUBLIC_BASE_URL="https://<your-domain>/<web-path>" bash scripts/ops/external-health-check.sh
```

На Windows host используйте observer с обычной системной DNS- и TLS-политикой:

```powershell
$env:PUBLIC_BASE_URL = "https://<your-domain>/<web-path>"
powershell -NoProfile -File scripts/ops/external-health-check.ps1
```

Оба observer принимают только HTTPS FQDN и требуют HTTP `200` у `/health`.
Windows-скрипт использует обычный resolver Windows и не изменяет hosts или DNS
настройки. Он не устанавливает certificate callback и не меняет trust store;
если сертификату не доверяет Windows, проверка остаётся неуспешной.

Проверка завершается ошибкой при DNS, TLS или HTTP ошибке и не использует
`--resolve`, `/etc/hosts`, literal IP либо отключение certificate validation.
Она доказывает только canonical HTTPS health приложения; browser hydration,
assets и внешние AdGuard journeys требуют отдельных acceptance scopes.

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
- `scripts/ops/external-health-check.sh` — внешний Bash/CI observer
- `scripts/ops/external-health-check.ps1` — внешний Windows observer с системной TLS-политикой
- `scripts/ops/backup-restore-check.sh` — проверяет online SQLite backup/restore. Его verification-артефакты (`/var/backups/<project>_verify_<timestamp>/`) сохраняются по умолчанию. Проверить их объём: `sudo bash scripts/ops/backup-restore-check.sh list`. Для безопасного preview cleanup: `sudo bash scripts/ops/backup-restore-check.sh prune-verify-artifacts --older-than 30`; фактическое удаление требует отдельного `--apply`. Команда намеренно не выбирает обычные `<project>_backup_*` или deploy backups.
- `scripts/ops/hardening-profile.sh`
- `scripts/deploy/server-deploy.sh`

## Связанные документы

- [Установка](./INSTALL.md)
- [Обновление](./UPDATE.md)
- [API](./API.md)
