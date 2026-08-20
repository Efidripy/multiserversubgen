# Production rollout: stable subscription links

Дата: 2026-08-20 19:55 UTC<br>
Хост: `dev.kleva.ru`<br>
Сервис: `sub-manager`<br>
Путь панели: `/y4cooovh/`

## Релиз

- `e3df3f0` — стабильные opaque subscription tokens, redirects, ручная регенерация, локальный QR.
- `267c014` — миграция старых HMAC URL после потери ephemeral signing secret.
- Опубликована ветка `subscription-stable-links-20260820`.

## Операционный протокол

Выкладка выполнена штатным `scripts/deploy/server-deploy.sh` через временный удалённый worktree. Для каждого релиза helper:

1. собрал staged release;
2. остановил сервис и выполнил SQLite WAL checkpoint;
3. проверил `PRAGMA integrity_check`;
4. создал полный runtime backup и SHA-256;
5. перенёс БД через SQLite `.backup`;
6. проверил Nginx и readiness с rollback-on-fail.

Последний backup: `project_20260820T195526Z-b354e5fe5515.tgz` в `/var/backups/sub-manager_deploy/`; SHA-256 проверен на production.

## Live evidence

- `systemctl is-active sub-manager`: `active`.
- `http://127.0.0.1:666/health`: `200`.
- `nginx -t`: успешен.
- `admin.db`: `integrity_check=ok`; таблица `subscription_tokens` присутствует, 87 записей.
- Панель `https://dev.kleva.ru/y4cooovh/`: `200`.
- `/api/v1/emails` два последовательных вызова вернули одинаковый token для `D632-IOS`; token opaque, без точки.
- Старый именной URL и ранее выданный HMAC URL вернули `302` на один и тот же стабильный token.
- Стабильный URL дважды вернул `200` с одинаковым телом.
- QR modal отрисовал локальный `data:image/png;base64,...`; внешних QR-сервисов не используется.
- Playwright: боковое меню содержит `Backup Manager` и `Subscriptions`; console errors: `0`.
- Публичная latency-проба (5 запросов): panel p50 ~403 ms, subscription p50 ~417 ms.

## Важное ограничение миграции HMAC

Старая реализация генерировала HMAC secret в памяти процесса и не сохраняла его. Поэтому проверка подписи уже недоступного процесса невозможна. Для migration-only fallback принимается только корректно декодируемый формат с 64 hex-символами подписи, будущим TTL и реально существующим identifier; после этого выполняется немедленный redirect на текущий opaque token. Сам контент подписки отдаётся только по opaque token.

## Rollback

Последний архив и `.sha256` сохранены в `/var/backups/sub-manager_deploy/`. База и `.encryption_key` не удалялись и не перегенерировались.
