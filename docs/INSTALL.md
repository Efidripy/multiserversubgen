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

Для сборки frontend installer проверяет реальный runtime-контракт: Node.js
`>=20 <25` и bundled npm `>=10 <12`. Если совместимая пара уже установлена,
он её не изменяет. Иначе installer подключает только подписанный NodeSource
APT-источник Node.js 22: ключ сверяется по pinned fingerprint, source использует
`signed-by`, а APT preference относится только к `nodejs`. Отдельный distro-пакет
`npm` installer не устанавливает, поскольку NodeSource поставляет npm вместе с
`nodejs`.

Уже существующие Grafana и Prometheus installer считает внешними и не
обновляет/не перенастраивает их автоматически. Детали и явный adoption-flow:
[ADR-0003](./ADR-0003-component-ownership.md).

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

Если Telegram включён, installer/update автоматически формирует
`TELEGRAM_PUBLIC_BASE_URL` из HTTPS `PUBLIC_DOMAIN` и активного `WEB_PATH`.
Ручное непустое значение остаётся override и не переписывается. Для
Telegram-enabled установки публичный `https://…/health` обязан вернуть `200`
с обычной TLS-проверкой.

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

## Вход через PAM

Сервис работает от непривилегированного пользователя `sub-manager`, поэтому вход в панель через PAM требует setgid-хелпера `/usr/sbin/unix_chkpwd` (есть по умолчанию в Debian/Ubuntu). Инсталлятор выводит предупреждение, если его нет. После установки проверьте вход вручную. Grafana получает случайный пароль администратора в `/etc/<project>/grafana-admin-password` (только для новой БД Grafana), Prometheus слушает только `127.0.0.1:9090`.
