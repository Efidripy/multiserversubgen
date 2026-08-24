# Установка

Этот документ содержит подробную установку `multiserversubgen` в production-режиме.

## Требования

- Ubuntu 20.04+ (рекомендуется 24.04)
- root-доступ
- доступный домен/поддомен для панели
- Nginx (устанавливается и/или настраивается через installer)

## Базовая установка

```bash
git clone https://github.com/Efidripy/multiserversubgen
cd multiserversubgen
chmod +x install.sh
sudo ./install.sh
```

## Что делает `install.sh`

- разворачивает backend (FastAPI + venv)
- собирает frontend (Vite) и публикует в `backend/build`
- настраивает systemd-сервис
- настраивает nginx для subpath-панели
- применяет базовые security-настройки (включая fail2ban, если включено в профиле)
- опционально настраивает мониторинг (Prometheus/Grafana, AdGuard-интеграция)

## XUI / 3x-ui: безопасное владение web и Nginx-конфигурацией

Внутренний XUI-профиль размещает landing-page только в
`/var/www/multiserversubgen-xui-root`; стандартный `/var/www/html` установщик
не очищает и не изменяет. Его Nginx-файлы имеют префикс
`multiserversubgen-xui-` и маркировку `managed-by: multiserversubgen-xui`.

Перед изменением installer сохраняет проверяемые rollback-архивы web-root и
своих Nginx-файлов в `/var/backups/multiserversubgen/`. Если обнаружен чужой
`listen 443` или unmanaged `stream` block, установка останавливается с
перечнем конфликтующих файлов — она не удаляет `default*` и не перезаписывает
чужую конфигурацию. Сначала разрешите конфликт вручную, затем повторите запуск.

## Важные параметры

Во время установки задаются ключевые значения:

- `APP_PORT` (порт backend)
- `WEB_PATH` (путь панели, например `/my-panel/`)
- `PUBLIC_DOMAIN` и `PUBLIC_SCHEME`
- параметры мониторинга

## Проверка после установки

```bash
systemctl is-active sub-manager
APP_PORT="${APP_PORT:-666}"
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${APP_PORT}/health"
```

Публичная проверка:

```bash
curl -fsSL -o /dev/null -w '%{http_code}\n' https://<your-domain>/<web-path>/
```

## Связанные документы

- [Обновление](./UPDATE.md)
- [Ops / эксплуатация](./OPS.md)
- [API](./API.md)
