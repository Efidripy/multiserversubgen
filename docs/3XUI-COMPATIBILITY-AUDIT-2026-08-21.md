# Совместимость с 3x-ui — 2026-08-21

**Задача:** `MSSG-20260821-3XUI-COMPAT`  
**Статус:** P0 реализован локально; production rollout ожидает package gates и
backup-first release.  
**Границы:** API/auth adapter control-plane, безопасные authenticated GET/POST
read-only probes. Не входят изменение конфигураций нод, токенов, inbound/client
данных, миграции или DDL.

## Источники и доказательства

| Источник | Наблюдение |
| --- | --- |
| `MHSanaei/3x-ui` tag `v3.6.0` | OpenAPI 3.0.3, 160 маршрутов; API защищён либо bearer token, либо session cookie. |
| Установленная панель `cholera` | После CSRF session login OpenAPI 3.0.3 содержит 170 маршрутов. До session login `/panel/api-docs` отдаёт SPA `Sign in`, поэтому документация/OpenAPI больше не являются public probe. |
| Установленная панель `cholera` | `GET /csrf-token` → `POST /login` с `Content-Type: application/json` и `X-CSRF-Token` → `GET /panel/api/inbounds/list` завершились `200` / `success=true`. |
| Установленная панель `cholera` | Современный `POST /panel/api/clients/onlines` завершился `200` с массивом. Устаревший `POST /panel/api/inbounds/onlines` завершился `404`. |

Не включаются в запись URL, учётные данные, cookie, bearer tokens, содержимое
inbounds или список клиентов.

## Сверка контрактов

| Область | Ранее в control-plane | Актуальный контракт | Решение |
| --- | --- | --- | --- |
| Session login | CSRF flow отправлял form data | `POST /login` принимает JSON credentials | P0: CSRF branch теперь использует `json=credentials`; legacy flow остаётся form-compatible. |
| Online clients | Только `/panel/api/inbounds/onlines` | Современный `/panel/api/clients/onlines`; legacy маршрут может отсутствовать | P0: modern-first, затем fallback только при `404/405`. |
| Client traffic | `inbounds/getClientTraffics/{email}` | Современный `clients/traffic/{email}`; legacy маршрут не описан в v3.6 OpenAPI | P0: modern-first и legacy fallback. |
| Inbounds / clients CRUD | Вызовы `inbounds/list/add/update`, `clients/list/add/update` | Те же базовые маршруты присутствуют в upstream OpenAPI | Подтверждено документом; write-contract не выполнялся на production в рамках инспекции. |
| Bearer token | Token хранится control-plane при добавлении ноды | Upstream не возвращает уже созданные node API tokens | Совместимо: control-plane не пытается читать существующий token из 3x-ui. |

## Реализация P0

- `backend/xui_session.py`: CSRF-login передаёт JSON body, как требует
  актуальный 3x-ui.
- `backend/server_monitor.py`: добавлен один bounded helper выбора маршрута;
  online и traffic используют modern-first compatibility pair.
- `backend/tests/test_backend_resilience.py`: regression для JSON CSRF-login.
- `backend/tests/test_server_monitor_and_traffic.py`: modern endpoint и
  fallback-контракты.

## Оставшиеся границы

1. `404` на `/panel/api/*` может обозначать как отсутствующий маршрут, так и
   скрытую панелью истёкшую сессию. Адаптер сохраняет существующую однократную
   re-auth проверку до перехода к legacy route.
2. Спецификация установленной панели и runtime не всегда совпадают буквально;
   runtime `200/404` имеет приоритет над advertised path. Поэтому feature parity
   должна расширяться парами `modern → legacy fallback`, а не жёстким version
   gate.
3. Операции, изменяющие clients, inbounds, panel database или node API tokens,
   не проверялись: для них требуется отдельное разрешение и backup plan.
