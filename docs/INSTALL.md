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

## Важные параметры

Во время установки задаются ключевые значения:

- `APP_PORT` (порт backend)
- `WEB_PATH` (путь панели, например `/my-panel/`)
- `PUBLIC_DOMAIN` и `PUBLIC_SCHEME`
- параметры мониторинга

## Проверка после установки

```bash
systemctl is-active sub-manager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:666/health
```

Публичная проверка:

```bash
curl -k -s -o /dev/null -w '%{http_code}\n' https://<your-domain>/<web-path>/
```

## Связанные документы

- [Обновление](./UPDATE.md)
- [Ops / эксплуатация](./OPS.md)
- [API](./API.md)
