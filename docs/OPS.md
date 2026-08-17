# Ops / Эксплуатация

## Полезные команды

### Статус и логи

```bash
systemctl status sub-manager
journalctl -u sub-manager -f
```

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
- `scripts/ops/backup-restore-check.sh`
- `scripts/ops/hardening-profile.sh`
- `scripts/deploy/server-deploy.sh`

## Связанные документы

- [Установка](./INSTALL.md)
- [Обновление](./UPDATE.md)
- [API](./API.md)
