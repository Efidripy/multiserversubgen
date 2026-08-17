# PERF-03 — единый владелец cold-path и защита от fan-out

**Статус:** deployed with authenticated production receipt
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

## Production receipt

Rollout exact commit `17274e2de10a80dba04d2e69e397f1498b0a8bea` прошёл через
штатный `server-deploy.sh` после clean source/service/Nginx/SQLite preflight.
Helper создал backup, его SHA-256 прошёл проверку, а archive manifest содержит
`admin.db`. До и после deploy SQLite `integrity_check` вернул `ok`; счётчики
`nodes/users/node_snapshots` остались `10/0/10`.

После rollout runtime `main.py` совпал с exact source commit, `sub-manager`
active, `nginx -t` успешен, localhost health вернул `200` за ~5 ms, public
panel — `200` за ~37 ms. Authenticated browser проверил все доступные
root-сессии разделы: Dashboard, Inbounds, Clients, Traffic и Monitoring.

Cold navigation зафиксировала единственный владеющий projection: Inbounds
выполнил `/v1/inbounds` и `/v1/inbounds/stats`, Clients — один `/v1/clients`,
Traffic — один `/v1/traffic/stats-by-period`. В Traffic и Monitoring после
ожидания completion ошибок приложения не было. Ранние отменённые HTTP при
искусственно быстром переходе между вкладками исключены из результата: они
проверяют cancellation path, а не отказ панели.
