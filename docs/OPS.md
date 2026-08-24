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

См. директории:

- `monitoring/prometheus/`
- `monitoring/grafana/`
- `monitoring/loki/`
- `monitoring/promtail/`

## Полезные скрипты

- `scripts/ops/smoke-test.sh`
- `scripts/ops/backup-restore-check.sh` — проверяет online SQLite backup/restore. Его verification-артефакты (`/var/backups/<project>_verify_<timestamp>/`) сохраняются по умолчанию. Проверить их объём: `sudo bash scripts/ops/backup-restore-check.sh list`. Для безопасного preview cleanup: `sudo bash scripts/ops/backup-restore-check.sh prune-verify-artifacts --older-than 30`; фактическое удаление требует отдельного `--apply`. Команда намеренно не выбирает обычные `<project>_backup_*` или deploy backups.
- `scripts/ops/hardening-profile.sh`
- `scripts/deploy/server-deploy.sh`

## Связанные документы

- [Установка](./INSTALL.md)
- [Обновление](./UPDATE.md)
- [API](./API.md)
