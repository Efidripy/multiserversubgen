# Совместимость с 3x-ui — 2026-08-21

**Задача:** `MSSG-20260821-3XUI-COMPAT`  
**Статус:** P0 deployed with production receipt.  
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

## Production rollout

- Source: merged `origin/main` commit `f10b153a455e6bd20d24726a874f2fab30eda32d`.
- Deployment: штатный immutable checkout и `scripts/deploy/server-deploy.sh`;
  rollback включён helper-ом.
- Rollback artifact:
  `/var/backups/sub-manager_deploy/project_20260821T113110Z-f10b153a455e.tgz`;
  SHA-256 проверен на production.
- После deployment: `sub-manager=active`, local health `200`, `nginx -t` OK;
  `admin.db integrity_check=ok`; counts сохранены (`nodes=9`,
  `node_snapshots=9`, `subscription_tokens=87`).
- SHA-256 deployed `xui_session.py` и `server_monitor.py` совпали с immutable
  source checkout.
- Authenticated browser smoke: dashboard и Monitoring отобразили `9/9` нод
  online и `39` current online clients. Публичная панель пять раз вернула
  HTTP 200 (p50 около 394 ms).
- Ноды, inbounds, clients, API tokens и записи БД не изменялись вручную;
  единственная работа с БД — штатный SQLite backup внутри deploy helper.

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

## P1 — runtime capability registry и полный adapter contract audit

**Статус:** deployed with production receipt.  Проверка контрактов не использует номер версии как feature gate:
одна установленная панель уже показала drift между OpenAPI и runtime.

### Capability registry

- Registry живёт только в памяти процесса и ключуется нормализованным node key
  без credentials, tokens или secret path values.
- Для compatibility operation сохраняются выбранный путь, HTTP status и
  исключительно coarse response shape (`success` type / `obj` type). Payload,
  emails, inbounds и HTTP bodies в registry не попадают.
- TTL по умолчанию — 3600 s.  При `404/405` cached route удаляется и та же
  операция пробует остальные documented variants; при изменении endpoint или
  credentials registry инвалидируется вместе с session/auth caches.
- `404/405` в compatibility probe больше не вызывает ложный re-login. Для
  одиночного panel API request сохраняется существующая однократная re-auth
  защита: панели иногда маскируют expired session как `404`.

### Adapter contract matrix

| Operation | Current-first contract | Legacy / compatibility behaviour | Runtime evidence / boundary |
| --- | --- | --- | --- |
| Credential login | `GET /csrf-token` → JSON `POST /login` + `X-CSRF-Token` | form-compatible `/panel/login` then `/login` only if CSRF route unavailable | CSRF JSON flow confirmed against installed panel; cached auth method re-probes after an upgrade. |
| Bearer validation | `GET /panel/api/inbounds/list` | no alternate route | validates both token and response schema; no token is returned or logged. |
| Inbound list | `GET /panel/api/inbounds/list` | same contract | authoritative read-only input for fleet/Xray audit. |
| Client list | `GET /panel/api/clients/list` | parse `settings.clients` from inbound list | v3 probe selects runtime capability; absent v3 route uses existing v2 projection. |
| Client add/update/delete | `POST /panel/api/clients/{add,update/{email},del/{email}}` | `inbounds/{addClient,updateClient,delClient}` | write paths are documented and regression-covered locally; never probed on production. |
| Bulk client operations | `bulkDel`, `delDepleted`, `bulkAdjust`, `bulkResetTraffic` | existing per-client/inbound sequence where implemented | mutation-only: no production probe in this audit. |
| Online clients | `POST /panel/api/clients/onlines` | `POST /panel/api/inbounds/onlines` | first P1 capability-pair; `404/405` selects/caches legacy route per node. |
| Client traffic | `GET /panel/api/clients/traffic/{email}` | `GET /panel/api/inbounds/getClientTraffics/{id}` / ById local legacy path | first P1 capability-pair; URL segment is encoded. |
| Inbound status/traffic | `GET /panel/api/server/status`, inbound counters from list | no safe semantic alternate | response normalization tolerates established metric-name variants. |
| Inbound lifecycle | `inbounds/{add,update/{id},del/{id},setEnable/{id},resetTraffic}` | full update for `setEnable` where supported by manager | mutation-only; no live probe. |
| Panel operational reads | `server/{history,getPanelUpdateInfo,xrayObservatory,getXrayVersion,xrayMetricsState,logs}` | selected older log routes | operational reads have independent contracts; avoid using config dump endpoints for compatibility audit. |
| Key generators | `server/getNewUUID`, `getNewX25519Cert`, `getNewVlessEnc`, `getNewmldsa65` | none | generators are user-initiated writes-of-secret material, excluded from probes and capability cache. |

The routes under `clients/groups/*`, `clients/{email}/attach|detach`, IP history,
subscription links and all DB/backup/import/update routes are feature-specific
contracts. They remain version-agnostic and must be tested only through an
explicit mutation-capable maintenance plan; P1 does not execute them remotely.

## P2 — client update mutation safety

The upstream v3.6.0 controller binds `model.Client` for
`POST /panel/api/clients/update/{email}`. It is a replacement contract, not a
PATCH. It also accepts optional `?inboundIds=<id>` to restrict a change to one
attachment; omitting it applies the update across the client's attachments.

The control-plane therefore performs a read-before-write within one existing
authenticated session: it obtains the v3 list record, maps its `uuid` to the
write-model `id`, preserves the current client fields and overlays only known
requested updates. A single-inbound edit includes `inboundIds`; bulk enable
keeps its intentional global scope. An absent v3 list route (`404/405`) still
uses the v2 adapter; malformed/error responses stop before any write.

The proof is mock-only in `backend/tests/test_client_v3_contract.py`. No live
panel, disposable node, client, inbound or production data was changed. A
live mutation check remains a separate authorised maintenance action with a
disposable node/client and an explicit cleanup receipt.

## P1 — read-only Xray 26 configuration audit

The audit consumes only the normalized result of `GET /panel/api/inbounds/list`
already gathered by the collector.  It never calls config dump, key-generator,
or write endpoints.  The collector persists a redacted aggregate in the
existing JSON snapshot; there is no schema migration or configuration mutation.

| Finding code | Detection | Operator action |
| --- | --- | --- |
| `xray_reality_finalmask_tcp` | REALITY + TCP + FinalMask | Critical: inspect and replace the incompatible combination in the panel; the control plane will not rewrite it. |
| `xray_xmc_legacy_usernames` | XMC legacy `usernames[]` | Re-save/migrate to current `profiles[]`. |
| `xray_xmc_incomplete_profiles` | missing/invalid profile shape | Complete profile metadata in the panel. |
| `xray_xhttp_legacy_session_keys` | `sessionPlacement` / `sessionKey` | Re-save/migrate to `sessionIDPlacement` / `sessionIDKey`. |
| `xray_xhttp_form_loss_risk` | current XHTTP session-ID/XMUX fields | Form editor preserves unknown fields; verify before intentionally changing transport settings. |
| `xray_wireguard_legacy_clients_shape` | generic `clients[]` used for WireGuard | Convert to current peer model. |
| `xray_wireguard_incomplete_peer` | missing peer/server shape | Repair peer/public-key/allowed-IP configuration in panel. |
| `xray_reality_settings_missing` / `malformed` | missing/non-object REALITY settings | Repair config manually; control plane makes no automatic normalization. |
| `xray_config_malformed` | settings or stream settings cannot be parsed as an object | Inspect the inbound in the node panel. |

Only code, severity and count are retained.  Keys, peer values, profile values,
client values, destinations and raw JSON are intentionally absent from snapshot,
WebSocket and browser contracts.

## P1 — production UI/performance walkthrough (read-only)

Authenticated browser traversal opened Dashboard, Inbound Manager, Client
Manager, Traffic Stats, Monitoring, Backup Manager and Subscriptions.  No
write/reset/export/import/key-generation action was clicked.  The one console
`401` occurred before the SPA created its authenticated session; after it all
observed API requests completed with `200`, with aborted requests corresponding
to intentional navigation away from a still-loading lazy section.

Observed cold-path signals (one controlled browser pass; not an SLA):

- static reload DOM/load: about 173/174 ms;
- node server-status fan-out: about 174–213 ms per node;
- Backup Manager `/backup/all`: about 17.4 s and 272 KB;
- Monitoring history: about 1.0 s and 287 KB;
- subscriptions list metadata: about 2.8–3.0 s.

The long Backup Manager response is the next optimization candidate: list
metadata must not require loading a whole backup body.  It is recorded here as
a P2 design change because changing that API contract must retain restore
semantics and gets a separate migration/rollback review.

## P1 production rollout receipt

- Merged source: `d293c2e050361b427daf7c5f9d5216586df78114` (PR #71).
- The deployment used an immutable detached source checkout and the existing
  `scripts/deploy/server-deploy.sh`; it did not run DDL or manually alter the
  database, node panel, inbound, client, subscription or token data.
- Rollback artifact:
  `/var/backups/sub-manager_deploy/project_20260821T121800Z-d293c2e05036.tgz`.
  Its SHA-256 sidecar validated on the production host before post-release
  checks.
- `sub-manager=active`, local health `200` and `nginx -t` succeeded. SQLite
  integrity remained `ok`; durable counts stayed `nodes=9`, `node_snapshots=9`
  and `subscription_tokens=87`.
- SHA-256 of deployed `xui_session.py` and
  `services/xray_compatibility.py` matched the immutable merged source.
- The first collector cycle evaluated all nine existing node snapshots without
  reading config dump/key-generator endpoints: eight were `ok`; one aggregate
  `xray_xhttp_legacy_session_keys` warning was recorded. This is a manual
  migration signal only—no configuration was changed.
- Public panel five-request check returned HTTP `200` each time, with a local
  host-side p50 about 43 ms (38.7–57.2 ms range). It measures reverse-proxy
  delivery, not a browser/API SLA.
