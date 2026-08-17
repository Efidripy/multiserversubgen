# PERF-02 — cold-path production UI

**Статус:** deployed with authenticated production receipt; остаточные источники fan-out вынесены в PERF-03
**Task:** `MSSG-PROD-PERF-REMEDIATION-20260817`
**Связь:** дополняет `PERF-01-NAVIGATION-CACHING-2026-08-17.md` и не заменяет его.

## Подтверждённые причины

Browser waterfall на `dev.kleva.ru` показал, что задержку разделов создаёт не
первичный рендер React и не SQLite сам по себе, а cold remote-node fan-out:

- Traffic Stats одновременно запрашивал period statistics, полный online list и
  второй period projection c `limit=1000`;
- Client Manager запускал online scan, `POST /clients/last-online` и до 20
  per-client traffic запросов при mount;
- viewer-сессия подписывалась на operator-only WebSocket каналы, что приводило
  к policy close/reconnect noise;
- Inbound Manager не передавал `AbortSignal` основным запросам при уходе со
  страницы.

## Реализованное решение

| Область | Изменение | Контракт |
| --- | --- | --- |
| Traffic Stats | local stale projection отображается до сети; online list и `limit=1000` запрашиваются только после явного refresh блока online | первый render не ждёт полный online fan-out; refresh остаётся явным |
| Client Manager | убран mount-time `POST /clients/last-online`, online scan и prefetch 20 live traffic rows | нет заведомо запрещённого viewer POST; traffic detail начинается только после раскрытия строки |
| Inbounds | `nodes`, `inbounds`, `inbounds/stats` получают общий `AbortSignal` | навигация/новый refresh отменяют устаревшую работу |
| RBAC UI | роль из `/auth/verify` хранится только в runtime memory; admin-only Backup/Subscriptions не монтируются для viewer/operator | серверный RBAC mapping не меняется этой задачей |
| WebSocket | viewer не подписывается на `clients`/`inbounds`; при одном `1008` выполняется ticket refresh, повторный policy failure останавливает reconnect | в console не должен оставаться бесконечный reconnect loop |

## Границы и риски

- Никаких миграций, DDL, reset/restore/delete SQLite или изменений существующего
  серверного role mapping нет.
- Данные в deferred panels могут быть устаревшими до явного refresh; это
  намеренно и безопаснее, чем скрытый fleet scan. UI сохраняет обычную кнопку
  refresh.
- Production-проверка rollout PERF-02 пройдена: штатный deploy helper создал и
  проверил backup SQLite, `integrity_check` вернул `ok`, сервис/Nginx/health
  были доступны, а authenticated browser не зафиксировал console errors.
- Этот замер выявил следующий узкий остаток: shared header повторно запускал
  remote projection активной вкладки. Его устранение и отдельная повторная
  production-проверка описаны в `PERF-03-FANOUT-CONTROL-2026-08-17.md`.

## Локальная проверка

- `npm test -- --run` — 9 tests passed;
- `npm run lint`, `npx --no-install tsc --noEmit`, `npm run i18n:check`;
- `npm run build`.
