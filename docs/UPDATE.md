# Обновление

## Рекомендуемый путь

```bash
cd multiserversubgen
git pull
sudo ./update.sh
```

Запускайте updater из полного Git checkout или из проверенного flat release
bundle. Скрипт до остановки сервиса проверяет обязательные backend, frontend,
ops, deploy, monitoring и systemd файлы. Неполный или произвольный архив он
отклоняет до изменения runtime-state.

## Режимы `update.sh`

1. Полное обновление (backend + frontend)
2. Только backend
3. Только frontend
4. Только nginx-конфиг

## Рекомендация перед обновлением

Сделайте backup перед применением обновления:

```bash
curl -u admin:password https://<your-domain>/<web-path>/api/v1/backup/all -o backups_$(date +%Y%m%d).zip
```

## Проверка после обновления

```bash
systemctl is-active sub-manager
APP_PORT="${APP_PORT:-666}"
curl -s -o /dev/null -w 'health=%{http_code}\n' "http://127.0.0.1:${APP_PORT}/health"
curl -fsSL -o /dev/null -w 'panel=%{http_code}\n' https://<your-domain>/<web-path>/
```

## Частый кейс: 404 на assets после обновления

Если панель открывается, но JS/CSS 404:

1. пересоберите frontend с корректным base path (`VITE_BASE`)
2. опубликуйте новый `backend/build`
3. проверьте nginx routes для `/<web-path>/assets/`
4. очистите кэш браузера / Service Worker

Подробности: [OPS.md](./OPS.md)
