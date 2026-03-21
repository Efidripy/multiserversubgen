# API

Короткий вход в API-документацию проекта.

## Полная спецификация

- [API_DOCUMENTATION.md](../API_DOCUMENTATION.md)

## Основные группы эндпоинтов

- health и readiness
- nodes / servers management
- inbounds
- clients (включая batch-операции)
- traffic stats
- backup / restore
- observability (`/metrics` и snapshots)

## Аутентификация

- Basic Auth (PAM)
- для защищенных production-инсталляций рекомендуется HTTPS + ограничение доступа на уровне nginx

## Смежные документы

- [Ops / эксплуатация](./OPS.md)
- [Обновление](./UPDATE.md)
