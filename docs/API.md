# API

Короткий вход в API-документацию проекта.

## Полная спецификация

- [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)

## Основные группы эндпоинтов

- health и readiness
- nodes / servers management
- inbounds
- clients (включая batch-операции)
- traffic stats
- backup / restore
- observability (`/metrics` и snapshots)
- auth / MFA / WebSocket ticket
- subscriptions and subscription groups

## Аутентификация

- Basic Auth (PAM)
- для защищенных production-инсталляций рекомендуется HTTPS + ограничение доступа на уровне nginx
- `GET /health` и `GET /api/v1/auth/mfa-status` являются public health/status endpoints.
- `GET /api/v1/sub/{token}` и `GET /api/v1/sub-grouped/{token}` не используют
  Basic Auth: доступ даёт краткоживущий подписанный token, который возвращают
  защищённые `/api/v1/emails` и `/api/v1/subscription-groups`.

## Смежные документы

- [Ops / эксплуатация](./OPS.md)
- [Обновление](./UPDATE.md)
