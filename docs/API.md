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

- Basic Auth (PAM) для API-клиентов и первичного browser bootstrap
- `POST /api/v1/auth/session` создаёт восьмичасовую защищённую cookie; после
  этого SPA не хранит пароль в Web Storage. `POST /api/v1/auth/logout`
  удаляет сессию.
- для защищенных production-инсталляций рекомендуется HTTPS + ограничение доступа на уровне nginx
- `GET /health` и `GET /api/v1/auth/mfa-status` являются public health/status endpoints.
- `GET /api/v1/sub/{token}` и `GET /api/v1/sub-grouped/{token}` не используют
  Basic Auth: доступ даёт стабильный opaque token, который возвращают
  защищённые `/api/v1/emails` и `/api/v1/subscription-groups`. Ссылка меняется
  только после явной admin-регенерации.

## Смежные документы

- [Ops / эксплуатация](./OPS.md)
- [Обновление](./UPDATE.md)
