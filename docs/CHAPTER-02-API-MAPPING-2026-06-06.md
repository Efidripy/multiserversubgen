# Chapter 02: Dashboard API Mapping And Service Layer Design

Date: 2026-06-06
Project: `multiserversubgen`
Branch observed: `feature/admin-redesign-sprint2`
Mode: architecture mapping / service design
Previous chapter: `docs/CHAPTER-01-API-LOCALIZATION-2026-06-06.md`

## Why This Chapter Exists

Chapter 01 proved that the redesigned dashboard did not lose the existing API surface:

- current UI readiness: `68%`;
- unique API operations found: `91`;
- current and backup API surfaces match;
- the main problem is not missing API behavior, but API behavior embedded inside React components.

This chapter turns that inventory into an implementation map.

The goal is to decide how dashboard components should receive data, where domain API methods should live, and how the next code extraction phase should avoid dragging old UI structure into the new dashboard.

## Scope Of This Run

Included:

- map `DashboardSummary`, `RegisteredFleetPanel`, `Sidebar`, `ServerStatus` in `dashboardMode`, and `NodeManager` in `dashboardMode` to API domains;
- design the first service-layer file structure;
- define a safe call-site extraction plan;
- document the git tree resolution needed before code extraction.

Not included:

- no React component rewrites;
- no service files created yet;
- no build, lint, or browser smoke run;
- no cleanup of archives or untracked deployment artifacts.

## Current Git Tree Constraint

The repository is not clean.

Observed status:

- branch: `feature/admin-redesign-sprint2`;
- staged dashboard/UI documentation and implementation changes are present;
- unstaged changes are present in `ChoiceChips.tsx` and locale files;
- untracked files include Run 01 docs, dashboard comparison docs, deploy/build archives, Playwright config, and `PROJECT.md`;
- backup branch and tag already exist:
  - `backup/pre-cleanup-working-state`;
  - `backup-before-cleanup`.

Diff shape at the time of this phase:

- staged: 8 files, about 4998 insertions / 4311 deletions;
- unstaged: 3 files, 26 insertions / 2 deletions;
- untracked: multiple docs/scripts/build archives.

Safe resolution before coding:

1. Do not start service extraction while this tree is mixed.
2. Preserve the current redesign state as a deliberate WIP checkpoint or have the owner explicitly stash it.
3. Keep build archives out of the service-extraction commit.
4. Start Phase 3 from a dedicated branch or checkpointed state, for example `codex/dashboard-api-service-layer`, after the current dashboard migration edits are either committed or intentionally stashed.

The existing backup branch/tag are useful fallback anchors, but they do not preserve the current staged and unstaged dashboard work by themselves.

## Existing API Transport

Current file:

- `frontend/src/api.ts`

Current responsibilities:

- derives `API_BASE`;
- creates the shared axios instance;
- forwards TOTP header from `frontend/src/auth.ts`;
- tracks request activity;
- logs request/response activity;
- caches GET responses;
- invalidates related cache tags after mutations.

Decision:

- keep this behavior as the transport layer;
- move it later to `frontend/src/api/client.ts` or keep `api.ts` as a compatibility re-export during migration;
- do not add domain methods to the transport client.

`frontend/src/auth.ts` is not an API service. It is the local credential runtime store. The future `frontend/src/api/auth.ts` should only contain auth/feature endpoint wrappers.

## Proposed Service Layer

### `frontend/src/api/client.ts`

Role:

- transport-only axios client;
- owns interceptors, cache, request activity, API base URL, and common request config helpers.

Endpoint ownership:

- none; this file should not expose domain methods.

Migration note:

- because components currently import `../api`, keep `frontend/src/api.ts` as a temporary compatibility export until all components are moved to domain services.

### `frontend/src/api/auth.ts`

Role:

- app bootstrap, login verification, MFA status, feature flags.

Endpoints:

- `GET /v1/features`
- `GET /v1/auth/mfa-status`
- `GET /v1/auth/verify`

Primary callers:

- `App.tsx` bootstrap and login flow;
- `App.tsx` visible tab calculation for `Sidebar`.

### `frontend/src/api/dashboard.ts`

Role:

- dashboard aggregate read models;
- summary tiles;
- snapshot-backed dashboard header;
- composition helpers that combine nodes and latest snapshot into UI-ready structures.

Endpoints:

- `GET /v1/dashboard/summary`
- `GET /v1/snapshots/latest`
- composed read: `GET /v1/nodes` + `GET /v1/snapshots/latest`

Primary callers:

- `DashboardSummary`;
- `App.tsx` dashboard header summary;
- `ServerStatus` in `dashboardMode` for snapshot-first status loading.

### `frontend/src/api/nodes.ts`

Role:

- registered fleet CRUD;
- node health/status checks;
- dashboard node overview enrichment;
- connection testing.

Endpoints:

- `GET /v1/nodes`
- `GET /v1/nodes/`
- `GET /v1/nodes/list`
- `POST /v1/nodes`
- `PUT /v1/nodes/{id}`
- `DELETE /v1/nodes/{id}`
- `POST /v1/nodes/check-connection`
- `POST /v1/nodes/refresh-now`
- `GET /v1/nodes/{id}/server-status`
- `GET /v1/servers/{id}/status`
- `GET /v1/nodes/{id}/panel-update-info`
- `GET /v1/nodes/{id}/inbounds`
- `GET /v1/clients?node_id={id}`
- `GET /v1/clients/count?node_id={id}`

Primary callers:

- `RegisteredFleetPanel`;
- `NodeManager` in both full and dashboard modes;
- `ServerStatus` in `dashboardMode` for refresh and live status enrichment;
- `App.tsx` dashboard/backup/subscription header summaries.

### `frontend/src/api/backup.ts`

Role:

- backup download, import/restore, Telegram backup trigger.

Endpoints:

- `GET /v1/backup/all`
- `GET /v1/backup/node/{id}`
- `POST /v1/backup/node/{id}/import`
- `POST /v1/nodes/{id}/backup-telegram`

Primary callers:

- `BackupManager`;
- `NodeManager` selected-node backup action;
- `ServerStatus` full mode backup-to-Telegram action.

### `frontend/src/api/serverOps.ts`

Role:

- operational node actions that should not bloat the basic node CRUD service.

Endpoints:

- `POST /v1/servers/{id}/restart-xray`
- `GET /v1/nodes/{id}/xray-logs`
- `GET /v1/nodes/{id}/server-logs`
- `GET /v1/nodes/{id}/xray-versions`
- `POST /v1/nodes/{id}/install-xray/{version}`
- `POST /v1/nodes/{id}/stop-xray`
- `POST /v1/nodes/{id}/update-panel`
- `POST /v1/nodes/{id}/update-geofile`
- `GET /v1/nodes/{id}/outbounds-traffic`
- `GET /v1/nodes/{id}/xray-metrics`
- `GET /v1/nodes/{id}/xray-observatory`
- `GET /v1/nodes/{id}/xray-config`
- `GET /v1/nodes/{id}/server-history/{metric}`
- `GET /v1/nodes/{id}/api-tokens`
- `POST /v1/nodes/{id}/api-tokens`
- `DELETE /v1/nodes/{id}/api-tokens/{tokenId}`
- `POST /v1/nodes/{id}/api-tokens/{tokenId}/set-enabled`

Primary callers:

- mostly `ServerStatus` full mode;
- selected dashboard-mode log viewer and per-node refresh paths.

## Dashboard Component Mapping

### `DashboardSummary`

Current API call-sites:

- `1` raw request call-site.

Current endpoints:

- `GET /v1/dashboard/summary`

Future service:

- `frontend/src/api/dashboard.ts`

Target component contract:

- component calls `getDashboardSummary()`;
- service normalizes backend payload into `DashboardSummaryData`;
- fallback/demo data should not remain embedded in the visual component unless it is explicitly named as mock data for local design mode.

Extraction step:

- replace `api.get('/v1/dashboard/summary', { auth: getAuth() })` with `getDashboardSummary()`;
- move `normalizeSummary` to the service or to `frontend/src/api/types.ts` if reused.

### `RegisteredFleetPanel`

Current API call-sites:

- `2` raw request call-sites.

Current endpoints:

- `GET /v1/nodes`
- `GET /v1/nodes/{id}/server-status`

Future service:

- `frontend/src/api/nodes.ts`

Target component contract:

- component calls `getRegisteredFleetOverview()`;
- service returns `FleetNode[]` with `available`, `latency`, and `error` already attached;
- service owns auth config and status fan-out.

Extraction step:

- move `getAuth`, node list fetch, per-node status fan-out, and latency measurement out of the component;
- keep visual collapse/expand and summary callback in the component.

### `Sidebar`

Current API call-sites:

- `0` raw request call-sites inside `Sidebar.tsx`.

Current data dependency:

- `Sidebar` receives `items` from `App.tsx`;
- `App.tsx` decides visible tabs from `GET /v1/features`.

Future service:

- `frontend/src/api/auth.ts` for `getFeatureFlags()`;
- `Sidebar` itself should stay presentational.

Extraction step:

- move `App.tsx` feature flag request to `getFeatureFlags()`;
- keep `Sidebar` free of API imports.

### `ServerStatus` In `dashboardMode`

Current API call-sites in component file:

- `33` raw request call-sites.

Dashboard-reachable data paths:

- initial load:
  - `GET /v1/nodes`
  - `GET /v1/snapshots/latest`
  - `GET /v1/nodes/{id}/server-status`
  - `GET /v1/clients/online`
  - `GET /v1/collector/status`
  - `GET /v1/nodes/{id}/panel-update-info`
- manual dashboard refresh:
  - `POST /v1/nodes/refresh-now`
  - then the normal load path;
- per-node dashboard refresh:
  - `GET /v1/servers/{id}/status`
  - `GET /v1/clients/count?node_id={id}`;
- dashboard log viewer:
  - `GET /v1/nodes/{id}/server-logs`
  - `GET /v1/nodes/{id}/xray-logs`

Future services:

- `frontend/src/api/dashboard.ts` for snapshot-first dashboard status;
- `frontend/src/api/nodes.ts` for node status/live refresh;
- `frontend/src/api/serverOps.ts` for logs and operational actions.

Target component contract:

- component receives a `ServerStatusViewModel[]`;
- dashboard mode should not trigger hidden full-mode requests;
- full operational handlers should be extracted behind `serverOps`.

Extraction step:

1. Add `getDashboardServerDeck()` in `dashboard.ts`, composed from nodes + latest snapshot + optional live status enrichment.
2. Replace `loadServersStatus()` API internals with the service call.
3. Gate or remove `collector/status` and `panel-update-info` from dashboard mode unless the dashboard renders their result.
4. Move log loading to `serverOps.getNodeLogs()`.
5. Only after behavior is stable, split full-mode operational handlers out of `ServerStatus`.

### `NodeManager` In `dashboardMode`

Current API call-sites in component file:

- `15` raw request call-sites.

Dashboard-reachable data paths:

- initial load:
  - `GET /v1/nodes`
  - `GET /v1/nodes/{id}/server-status`
  - `GET /v1/nodes/{id}/panel-update-info`
  - `GET /v1/clients?node_id={id}`
  - `GET /v1/nodes/{id}/inbounds`
- dashboard edit flow:
  - `PUT /v1/nodes/{id}`

Full-mode-only or hidden paths that still live in the file:

- `POST /v1/nodes`
- `DELETE /v1/nodes/{id}`
- `POST /v1/nodes/check-connection`
- `GET /v1/backup/node/{id}`
- `POST /v1/servers/{id}/restart-xray`

Future services:

- `frontend/src/api/nodes.ts`;
- `frontend/src/api/backup.ts` for selected backup;
- `frontend/src/api/serverOps.ts` for selected restart.

Target component contract:

- dashboard mode calls `getNodeDashboardOverview()`;
- full mode calls separate CRUD/action methods;
- hidden dashboard-only render should not pay for client/inbound count requests unless those values are visible.

Extraction step:

1. Move shared snapshot/in-flight cache into `nodes.ts` or a later query hook.
2. Replace `loadNodes()` internals with `getNodeDashboardOverview({ includeCounts })`.
3. For `dashboardMode`, set `includeCounts=false` until client/inbound counts are rendered.
4. Move add/delete/check/backup/restart handlers to service calls without changing UI behavior.

## `App.tsx` Shell Mapping

`App.tsx` is not listed as a dashboard component, but it currently owns shell-level dashboard data:

- `GET /v1/features` controls visible tabs and therefore `Sidebar` content;
- `GET /v1/auth/mfa-status` and `GET /v1/auth/verify` control app bootstrap/login;
- dashboard header uses `GET /v1/nodes` + `GET /v1/snapshots/latest`;
- other tab headers use clients, inbounds, traffic, monitoring, backup, and subscriptions endpoints.

Service extraction should include `App.tsx` in Phase 3. Otherwise `Sidebar` becomes clean while the shell still owns raw API calls.

## Call-Site Removal Plan

Phase 3 should be incremental and avoid visual rewrites.

Recommended order:

1. Create `frontend/src/api/client.ts` and keep `frontend/src/api.ts` as a compatibility export.
2. Create typed services:
   - `frontend/src/api/auth.ts`
   - `frontend/src/api/dashboard.ts`
   - `frontend/src/api/nodes.ts`
   - `frontend/src/api/backup.ts`
   - `frontend/src/api/serverOps.ts`
3. Extract `App.tsx` auth/features first.
4. Extract `DashboardSummary` next because it has one endpoint and one fallback path.
5. Extract `RegisteredFleetPanel` using `getRegisteredFleetOverview()`.
6. Extract `NodeManager` read path before write path:
   - `getNodeDashboardOverview()`;
   - then CRUD;
   - then backup/restart actions.
7. Extract `ServerStatus` read path before operational handlers:
   - dashboard status deck;
   - refresh;
   - logs;
   - full-mode server operations.
8. Run validation after every meaningful slice:
   - `cd frontend && npm run build`
   - `cd frontend && npm run lint`

Do not combine this with styling cleanup.

## Problematic Or Unmapped Elements

- `ServerStatus` in `dashboardMode` still triggers some data that dashboard does not render, notably collector status and panel update checks.
- `NodeManager` in `dashboardMode` still triggers client and inbound count enrichment even though those counts are hidden in the dashboard card variant.
- `App.tsx` has shell-level raw API calls that influence `DashboardSummary` and `Sidebar` but are outside the component list.
- `dashboard-command-grid__legacy-intake` mounts another `NodeManager` with `showFleet={false}` inside the dashboard route; this should be explicitly kept, removed, or lazy-mounted before extraction proceeds.
- `frontend/src/auth.ts` and future `frontend/src/api/auth.ts` need clear naming rules to avoid confusing credential storage with API auth service.
- Existing build archives are untracked and should not be part of service-layer commits.

## Ready State

Mapping readiness:

- ready.

Code extraction readiness:

- not ready until git tree resolution is complete.

Reason:

- the service boundaries and first extraction order are clear;
- the current dirty tree makes code extraction risky without a WIP checkpoint, owner-approved stash, or dedicated branch from a known state.

## Next Phase

Phase 3 should be `service_extraction_slice_01`.

Recommended first implementation slice:

1. `client.ts` compatibility extraction;
2. `auth.ts` service wrappers;
3. `dashboard.ts` summary wrapper;
4. `DashboardSummary` migration;
5. build/lint validation.

Only after that should `nodes.ts`, `backup.ts`, and `serverOps.ts` be wired into the heavier dashboard lanes.
