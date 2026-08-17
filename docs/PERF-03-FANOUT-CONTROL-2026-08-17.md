# PERF-03 — единый владелец cold-path и защита от fan-out

**Статус:** implemented locally; production verification pending
**Task:** `MSSG-PROD-PERF-REMEDIATION-20260817`
**Связь:** продолжает `PERF-02-PRODUCTION-UI-COLD-PATH-2026-08-17.md`.

## Baseline

Authenticated production waterfall после PERF-02 показал, что cache снижает
повторный визит до долей секунды, но cold переход по-прежнему запускал лишние
дорогие запросы:

| Раздел | Наблюдение до PERF-03 | Причина |
| --- | --- | --- |
| Inbounds | два запроса `/v1/inbounds` и отдельный `/v1/inbounds/stats` | header и вкладка строили один и тот же remote projection |
| Clients | два запроса `/v1/clients` | header и `ClientManager` владели одинаковым cold path |
| Traffic | header добавлял `/v1/clients/online` и `/v1/traffic/stats` к period query | KPI header запускал независимый fleet fan-out |

Это не является признаком React StrictMode или SQLite migration. Cold remote
fan-out выполняется внешними node adapters; отмена HTTP клиента не прерывает
уже начатую работу в backend thread pool.

## Реализация

| Область | Изменение | Контракт |
| --- | --- | --- |
| Shared header | Для `inbounds`, `clients` и `traffic` header выводит только описание вкладки, без собственного remote query | На cold path у remote projection один владелец — активная вкладка |
| ClientManager | Один `AbortSignal` передаётся в nodes, clients и inbounds | Уход со страницы отменяет все ещё не начатые HTTP запросы одного refresh |
| Backend cache | Для каждого `group_by` добавлен lock и повторная проверка Redis/in-memory cache после ожидания | Одновременные cold callers выполняют один fleet fetch и получают один cache value |
| Traffic realtime | Silent WebSocket/fallback updates работают trailing-throttle не чаще раза в 60 секунд | Burst не создаёт параллельные server-side fan-out; ручной refresh и смена period/group не задерживаются |

## Регрессии и границы

- Backend regression создаёт двух одновременных cold callers и требует ровно
  один вызов `get_traffic_stats`.
- Frontend regression закрепляет throttle, cleanup timer и явные navigation
  reasons для group/period.
- Не меняются SQLite schema, миграции, DDL, данные, роли, секреты и API
  contracts.
- Данные period projection могут быть последней доступной cache версией в
  течение throttle window. Это намеренный компромисс: управление остаётся
  мгновенным, скрытый повторный fleet scan исключён.

## Production acceptance

Перед rollout: чистый immutable checkout, backup receipt SHA-256, SQLite
`integrity_check`, текущие счётчики и disk space. После rollout: exact source
commit, service/Nginx/health, повторная SQLite integrity/count check и чистый
authenticated browser waterfall всех доступных разделов. Результат заполняется
только по фактическому post-deploy receipt.
