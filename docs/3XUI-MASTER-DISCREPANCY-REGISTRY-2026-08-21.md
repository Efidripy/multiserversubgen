# Master-реестр расхождений и незакрытых границ — 2026-08-21

**Задача:** `TASK-20260821-3XUI-MASTER-DISCREPANCY-INVENTORY`

**Статус:** audit complete, no implementation in this record.
**Источники:** текущий `main` control-plane; upstream `MHSanaei/3x-ui`
`v3.6.0` (`c377dca`), OpenAPI и controller/service source; ранее
зафиксированный authenticated API audit установленной панели.
**Границы:** source/OpenAPI/mock evidence и уже существующие локальные records.
Ноды, клиенты, inbounds, трафик, SQLite, токены, credentials и production не
изменялись.

## Как читать реестр

- **confirmed** — текущий код расходится с документированным upstream-контрактом
  или может выполнить повторную mutation после reachable failure.
- **unverified high-risk** — route существует, но критичный payload/fallback/
  preservation contract не доказан текущими mock-тестами. Это не следует
  называть багом до mock-аудита.
- **feature gap** — upstream-возможность пока не экспонируется продуктом;
  отсутствие само по себе не является дефектом.
- **evidence/release gap** — код и локальные проверки уже есть, но отсутствует
  отдельное требуемое доказательство доставки или live acceptance. Это не повод
  повторно переписывать код и не разрешение тестировать production-данные.

`404/405` — единственный признак отсутствия route, который может разрешить
совместимый fallback. `401`, `5xx`, transport failure, malformed body и
`success: false` — operational failure: повторная mutation другим путём
запрещена.

## Закрыто и не входит в новый backlog

| ID | Состояние | Подтверждённый результат |
| --- | --- | --- |
| 3X-01 / 3X-02 | deployed | CSRF JSON login, read-path capability registry, modern online/traffic adapter и Xray 26 read-only audit. |
| 3X-03 | local mock proof | v3 client update read-merge-write, UUID→email/id и `inboundIds`. |
| 3X-04 | local mock proof | v3 single traffic reset, encoded email и safe legacy boundary. |
| 3X-05 | local mock proof | v3 delete resolves client identity before write. |
| 3X-06 | local mock proof | bulk reset cannot downgrade after reachable failure. |

Эти пункты всё ещё требуют отдельного authorised disposable-node/client live
receipt; это граница доказательства, а не открытый source mismatch.

## Confirmed discrepancy backlog

| ID | Priority | Область | Доказательство расхождения | Риск | Минимальное исправление и acceptance |
| --- | --- | --- | --- | --- | --- |
| 3X-07 | P1 | all traffic reset | `backend/client_manager.py:1011` вызывает несуществующий v3 путь `inbounds/resetAllTraffics/{id}`. Upstream имеет только `inbounds/{id}/resetTraffic` и global `inbounds/resetAllTraffics`. | Операция silently не сбрасывает выбранный inbound, а `200` учитывается без `success`. | Удалить dead adapter либо делегировать корректному inbound manager; exact URL/response mock contracts; затем отдельный disposable reset receipt. |
| 3X-08 | P0 | bulk destructive mutations | `backend/client_manager.py:339-351,759-783,1162-1174,1203-1248`: `bulkDel`, `delDepleted`, `bulkAdjust` переходят к другому write path после `5xx`, malformed JSON или `success:false`, а не только `404/405`. | Частично применённая bulk mutation может быть повторена поштучно: двойное удаление или повторное продление. | Один tri-state helper `supported/unsupported/failed`; fallback только on `404/405`; exact mock order for 404, 405, 503, exception, malformed/success:false and partial result. |
| 3X-09 | P1 | IP history DTO | Upstream v3 `clients/ips/{email}` возвращает `[]ClientIpInfo` (`ip,time,node`); `backend/client_manager.py:1281-1296` и UI ожидают `string[]`. `find-by-ip` сравнивает строку с object. | UI может рендерить object некорректно, а поиск IP пропускает совпадения. | Нормализовать backend DTO с backward-compatible string form; contracts for v3 object list, legacy strings, UI rendering and IP search. |
| 3X-10 | P1 | current ops routes | API tokens используют `/panel/setting/...` (`backend/server_monitor.py:1002-1030,1238-1257`) вместо v3 `/panel/api/setting/...`; outbound traffic использует `/panel/xray/getOutboundsTraffic` (`:1155-1166`) вместо `/panel/api/xray/...`; Xray config — undocumented `/xui/API/inbounds/get` (`:695-718`) вместо documented `GET /panel/api/server/getConfigJson`. | Активные административные экраны получают 404/пустой результат на current panel. Token mutation особенно чувствительна. | Разделить read-only and mutation/secret ops; exact route/schema mocks. Live read proof для list/outbound/config; token create/delete/enable только на disposable token по отдельному разрешению. |
| 3X-11 | P1 | restart safety | `backend/server_monitor.py:737-758` пробует legacy restart после любого modern failure, включая `success:false`, timeout и 5xx; v3 route documented as `POST /panel/api/server/restartXrayService`. | Возможен второй restart в момент сбоя и неконтролируемое продление downtime. | Modern-first tri-state, legacy only 404/405; mocked exact ordering. Live test — только maintenance window, не production node по умолчанию. |
| 3X-12 | P2 | client route hygiene | В `backend/client_manager.py:372,1267,1287,1304,1386,1400,1503,1522` email/group/subId подставляются в URL без `quote`. Затронуты traffic, links, IP, clear IP, attach/detach, groups и sub-links. | Валидные identifiers с `/`, `#`, `?`, `+` обрываются или меняют route; для mutation это небезопасно. | Общий encoded path-segment helper; mock prepared-request tests for special identifiers and current v3 response schema. |
| 3X-13 | P2 | last online semantics | `backend/client_manager.py:1310-1324` отправляет `{emails: [...]}`, хотя current upstream handler не принимает body и возвращает всю map; локальный public route обещает фильтр. | Лишний fleet payload/latency и ложная семантика фильтра. | Получать documented full map и filter locally with bound/limit, или скрыть feature; mock all-map/local-filter contracts and read-only live proof. |
| 3X-17 | P1 | client traffic identity | `ClientManager.get_client_traffic` получает `client_uuid` и вызывается с `client["id"]` (`backend/client_manager.py:793-817,875-879`), но в режиме v3 передаёт его в `clients/traffic/{email}`. Upstream controller принимает только `email`; `_get_traffic_v3` также не кодирует segment (`:369-383`). | Внутренние views/bulk-пути на v3 могут показывать нулевой трафик или ошибочно классифицировать клиента как depleted. | Resolve UUID/id to current email до read, one encoded v3 request; fallback лишь `404/405`; mock UUID, email, special characters, 503 and no second request. |
| 3X-19 | P3 | obsolete monitor facade | `ServerMonitor.get_server_status` (`backend/server_monitor.py:580-607`) делает `POST` к current `GET /panel/api/server/status`. Runtime collector использует `ThreeXUIMonitor`, поэтому это не подтверждённый active outage, но public class и tests сохраняют ложный contract. | Будущий вызов старой facade даст 405/ложный offline, а две реализации drift-уют. | Remove/deprecate facade or delegate to `ThreeXUIMonitor`; one GET-only regression. Live proof не нужен. |

## Unverified high-risk contracts

| ID | Priority | Область | Что не доказано | Plan |
| --- | --- | --- | --- | --- |
| 3X-14 | P1 | inbound lifecycle | `add/update/delete/setEnable/reset/delAllClients` в `backend/inbound_manager.py` не имеют полной v3 contract matrix. `update_inbound` выполняет read-modify-write полного inbound, а `setEnable` рассматривает только `404`, не `405`. Не доказано сохранение current XHTTP/Reality/unknown fields. | Mock DTO для VLESS, Trojan, Reality и XHTTP; route-absence/no-write contracts; затем one disposable-inbound live receipt. |
| 3X-15 | P2 | client add/auxiliary contracts | `_add_client_v3` (`backend/client_manager.py:171-193`) передаёт лишь subset `model.Client`; пользовательские `subId`, `flow`, comment/group/reset и protocol-specific data не закреплены contract test. Groups/attach/detach/clear IP имеют UI routes, но не current-v3 route/payload/read-only coverage. | Fixture from upstream `model.Client`; define supported fields and defaults; `404/405` policy; URL/response/RBAC/read-only contracts. |
| 3X-16 | P2 | server ops parity | DB import/export, panel/Xray update, logs, key generators, Telegram backup и API token adapter не имеют единой current contract matrix. | Read-only ops first; mutation and secret-generation APIs mock-first, then explicit disposable-node/rollback/cleanup maintenance plan. |

## Неполные, но не дефектные delivery/evidence gates

| ID | Priority | Текущее состояние | Что осталось, чтобы считать работу закрытой |
| --- | --- | --- | --- |
| 3X-03 … 3X-06 | P2 | Код, mock contracts и disposable live suite реализованы. | Закрыто для текущего v3 runtime; повторять только при изменении upstream contract. |
| PERF-05 | P2 | Backup Manager metadata-first реализован локально и прошёл package gates. | Rollback-first production rollout и authenticated browser waterfall: mount запрашивает только nodes metadata, bytes — только после явного действия. |
| BKP-01 | P2 | Формат restore валидируется до remote import; local contracts и disposable live restore pass. | Закрыто для текущего v3 runtime; повторять на новом upstream/runtime. |
| OPS-01 | P2 | Unit, systemd/template и installer guards реализованы. | Реальный Ubuntu install/update smoke до объявления least-privilege flow production-proven. |

Эта таблица намеренно не повышает приоритет реализации: это доказательные
границы уже написанного кода. Следующая code wave выбирается из confirmed
backlog выше.

## Feature gaps — не баги

Upstream v3.6.0 содержит больше возможностей, чем сейчас экспонирует
control-plane: `clients/bulkCreate`, `bulkAttach`, `bulkDetach`, `externalLinks`,
import/export, groups reset; inbound `list/slim`, `options`, `allLinks`, import,
fallbacks; server update-status/cert/Reality helpers и некоторые Xray metrics.

Они не попадают в bug backlog: добавлять их можно только после product decision,
UX specification и отдельного contract stream. Нельзя выдавать feature parity за
готовую только потому, что endpoint найден в upstream.

## Execution waves

1. **Wave A — P0/P1 mutation containment:** `3X-08`, `3X-11`; общий strict
   mutation result helper and scripted transport fixture. Это единственная
   wave, где при ошибке можно иначе повторить destructive action.
2. **Wave B — P1 functional data contracts:** `3X-17`, `3X-07`, `3X-09`,
   `3X-10`; identity-before-read, traffic/reset, IP DTO и active ops routes.
3. **Wave C — high-risk integrity:** `3X-14`, `3X-15`, `3X-12`; inbound/client
   preservation, 404/405 policy, associations and encoded path segments.
4. **Wave D — read/ops and hygiene:** `3X-13`, `3X-16`, `3X-19`; bounded
   local filtering, ops matrix and removal of stale facade.
5. **Live acceptance:** один explicitly authorised disposable node/client/inbound
   suite, backup/rollback/cleanup receipt. Existing production data is never
   a test fixture.

Каждая wave — отдельная ветка/PR, но общий registry остаётся источником
приоритета. Следующая задача выбирается из Wave A, а не по случайно найденному
endpoint.

## Evidence limitations

- Upstream tag and installed runtime могут расходиться; runtime `200/404/405`
  имеет приоритет над advertised OpenAPI.
- Нынешняя installed-panel documentation была ранее изучена authenticated;
  этот реестр не делает нового remote probe.
- Live proof ограничен явно авторизованным `cholera.kleva.ru/x7LaBlIoh2` и не
  распространяется на production `dev.kleva.ru`.

## Closure update — 2026-08-21

Волны A–D закрыты локально в одной change stream. Реализованы и покрыты
контрактными тестами:

- **3X-07** — reset all traffic теперь использует только документированные
  global/per-inbound routes через `ClientManager`/`InboundManager`.
- **3X-08** — bulk delete, depleted delete, bulk adjust, bulk reset и restart
  используют strict `supported/unsupported/failed`; второй write разрешён
  только после `404/405`.
- **3X-09** — IP history принимает v3 `{ip,time,node}` и legacy strings,
  отдаёт backward-compatible `ips` плюс `ip_details`; UI и find-by-ip работают
  по нормализованному IP.
- **3X-10** — server config, API tokens и outbound traffic переведены на
  current `/panel/api/...` routes с no-store для одноразового token response.
- **3X-11** — restart fallback ограничен отсутствием modern route (`404/405`).
- **3X-12** — opaque path segments кодируются единым helper, включая legacy
  update и links/группы/attach/detach/IP/sub-links.
- **3X-13** — `lastOnline` получает полный map и фильтрует локально.
- **3X-14** — inbound update выполняет deep merge nested DTO и сохраняет
  неизвестные XHTTP/Reality поля; failed read не приводит к write.
- **3X-15** — add/update client передают и сохраняют protocol-specific v3
  fields (`reverse`, `auth`, key material, `allowedIPs`, `preSharedKey`,
  `keepAlive`, `secret`, `adTag` и др.).
- **3X-16** — history metric/bucket валидируются до remote call; ops routes
  покрыты current v3 contract tests, logs учитывают `405` как route absence.
- **3X-17** — traffic lookup разрешает UUID/id в email до v3 request.
- **3X-19** — stale POST status facade делегирует canonical GET monitor.

Проверки closure: backend `306 passed`, Ruff, compileall, frontend Vitest,
ESLint, TypeScript, i18n и Vite build прошли. ShellCheck и workspace mix-gate
остаются финальными release gates. Все mutation/live/disposable-node receipts
намеренно вынесены за отдельное разрешение; production не использовался.

## Disposable live acceptance — 2026-08-21

После явного разрешения пользователя выполнен disposable-only прогон на
`cholera.kleva.ru/x7LaBlIoh2`. Production `dev.kleva.ru` не использовался.

- Backup до mutation: `229376` bytes,
  SHA-256 `da1686560b2fc340deccddbe2c844c11d81738c5ad9b41b0458b18aa61aa0e8c`.
- Read contracts: config, history (`cpu/360`), logs, outbound traffic, API
  token list, client links, IP history и `lastOnline` — pass.
- Mutation contracts: temporary API token create/enable/disable/delete;
  inbound add/update/setEnable/reset/delete; client add/update/email rename,
  single reset, bulk reset, finite-expiry bulk adjust и delete — pass.
- Inbound unknown nested marker сохранён после full update; runtime API version
  подтверждён как `v3`.
- Cleanup: temporary token/client/inbound удалены, `marker_remaining=false`,
  ошибок нет.

Receipt: `E:\GitHub\workspace\runtime\logs\projects\multiserversubgen\cholera-live-acceptance.json`.
Global reset всех inbound’ов, `delDepleted` и destructive database restore не
запускались в этом временном-object suite. После отдельного разрешения они
выполнены и восстановлены из свежего backup: baseline и final содержат 4
inbound и 6 клиентов, global reset дал нулевые counters, `delDepleted` — `0`,
restore — `success`, identity set и counters совпали с baseline за одну
попытку.

Destructive closure receipt:
`E:\GitHub\workspace\runtime\logs\projects\multiserversubgen\cholera-destructive-acceptance-20260821T173941Z.json`.
