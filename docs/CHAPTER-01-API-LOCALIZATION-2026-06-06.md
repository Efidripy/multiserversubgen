# Chapter 01: API Localization And New UI Baseline

Date: 2026-06-06
Project: `multiserversubgen`
Branch observed: `feature/admin-redesign-sprint2`
Mode: audit / baseline fixation

> Historical snapshot. The current API/security contract is maintained in
> [`API.md`](API.md) and the remediation record
> [`REMEDIATION-ROADMAP-2026-08-10.md`](REMEDIATION-ROADMAP-2026-08-10.md).
> The raw-email subscription links recorded below are superseded and must not
> be implemented or exposed.

## Why This Chapter Exists

This file starts a separate project chapter for the new admin/dashboard stack.

The previous answer was strict JSON because Phase 1 explicitly requested `STRICT JSON`.
That was useful as a machine-readable checkpoint, but it is not enough as a durable project report.
This chapter is the human-readable source for what was found during the first run and how the next runs should proceed.

## Chapter Goal

Build the new Figma/Variant4 admin experience without dragging old UI code forward.

The rule for this chapter:

- keep the new dashboard UI direction;
- extract only working API behavior from the old/pre-design state;
- move API calls into a clean domain service/query layer;
- do not import old visual components as a shortcut;
- keep every phase auditable.

## Run 01 Summary

Phase: `audit_and_localization`

Result:

- current UI readiness: `68%`
- extracted API operations: `91` unique method/path operations
- API source identified: yes
- ready for mapping: yes

No repository source code was changed during Run 01.
The only durable output before this file was BHM/session checkpointing.

## Current UI Baseline

The new UI is not empty and not just a mock shell. It already has a real Variant4-oriented dashboard structure.

Detected migrated or newly shaped files:

- `frontend/src/App.tsx`
  - owns the dashboard composition;
  - wires `DashboardSummary`, lower lanes, `RegisteredFleetPanel`;
  - controls dashboard shell state and topbar/fleet behavior.
- `frontend/src/App.css`
  - contains Variant4/dashboard-scoped layout;
  - includes `app-layout`, `dashboard-command-grid`, right rail, dashboard shell, responsive rules.
- `frontend/src/components/DashboardSummary.tsx`
  - closest migrated piece;
  - mission-control summary, KPI deck, traffic lane.
- `frontend/src/components/RegisteredFleetPanel.tsx`
  - right-side command rail;
  - fleet cards, degraded/error CTA, compact node signal.
- `frontend/src/components/Sidebar.tsx`
  - dashboard-shell navigation chrome.
- `frontend/src/components/ServerStatus.tsx`
  - has `dashboardMode`;
  - still contains legacy operational inspector weight.
- `frontend/src/components/NodeManager.tsx`
  - has `dashboardMode`;
  - still carries table/manager semantics.
- `frontend/src/contexts/ThemeContext.tsx`
  - activates `style-preset-3` / dark Variant4 direction.
- `docs/DASHBOARD-FIGMA-MIGRATION-2026-06-04.md`
  - documents current migration state and target direction.

## UI Readiness Assessment

Score: `68%`

Reasoning:

- shell and upper dashboard hierarchy are already substantially migrated;
- `DashboardSummary` and `RegisteredFleetPanel` are good foundations for the new direction;
- sidebar/topbar/dashboard chrome are aligned enough to continue;
- lower lanes are not finished;
- `ServerStatus` and `NodeManager` still need extraction from legacy interaction density;
- build/lint/smoke were not rerun in this audit pass.

Practical interpretation:

- good enough for API mapping and service extraction;
- not ready to call the dashboard visually complete;
- not ready to freeze UI without another browser/Figma comparison pass.

## API Source Of Truth For This Chapter

Usable source:

- `git:backup/working-state-before-design-migration:frontend/src/api.ts`
- `git:backup/working-state-before-design-migration:frontend/src/components/*.tsx`

Current matching source:

- `frontend/src/api.ts`
- `frontend/src/components/*.tsx`

Rejected sources:

- `frontend-deploy.tar.gz`
- `mssg_build.tar.gz`
- `mssg_build_flat.tar.gz`
- `backend/frontend-deploy.tar.gz`

Reason: these archives contain compiled production assets, not clean TypeScript API/client source.

## API Layer Findings

The project already has a central axios client:

- `frontend/src/api.ts`

It provides:

- `API_BASE` derived from `VITE_API_BASE_URL` or Vite `BASE_URL`;
- axios instance with `baseURL`;
- request activity tracking;
- TOTP header forwarding;
- GET response caching;
- mutation invalidation for nodes, clients, inbounds, traffic, emails;
- activity logging.

Problem:

- the transport client is centralized;
- domain methods are not centralized;
- business API calls still live inside React components.

Measured API footprint:

- current frontend request call-sites: `166`
- backup/pre-design request call-sites: `164`
- unique method/path operations in both current and backup: `91`
- added unique operations vs backup: `0`
- removed unique operations vs backup: `0`

This means the redesign did not lose the old API surface. The API behavior can be mapped safely before extraction.

## API Domains To Extract

Recommended service modules:

- `frontend/src/api/client.ts`
  - axios instance and interceptors, likely moved from current `api.ts`.
- `frontend/src/api/auth.ts`
  - features, auth verify, MFA status.
- `frontend/src/api/dashboard.ts`
  - dashboard summary, latest snapshot, header/dashboard aggregate calls.
- `frontend/src/api/nodes.ts`
  - nodes CRUD, connection check, server status, node-level operations.
- `frontend/src/api/clients.ts`
  - clients list, batch operations, traffic reset, online/last-online, links, IP lookup, groups.
- `frontend/src/api/inbounds.ts`
  - inbound list, create, clone, update, batch operations, reset/delete helpers.
- `frontend/src/api/traffic.ts`
  - traffic stats, stats by period, traffic fallback.
- `frontend/src/api/monitoring.ts`
  - health deps, AdGuard, monitoring stack, history, snapshots.
- `frontend/src/api/backup.ts`
  - node backup, all backup, restore/import, Telegram backup trigger.
- `frontend/src/api/subscriptions.ts`
  - emails, nodes for subscription filters, link builders.
- `frontend/src/api/serverOps.ts`
  - restart xray, logs, xray versions, panel update, observatory, config, metrics.

Optional next layer after services:

- `frontend/src/queries/*`
  - hooks/composition for React screens.

## Unique API Operations Found

### Auth And Features

- `GET /v1/features`
- `GET /v1/auth/mfa-status`
- `GET /v1/auth/verify`

### Dashboard And Snapshots

- `GET /v1/dashboard/summary`
- `GET /v1/snapshots/latest`

### Nodes

- `GET /v1/nodes`
- `GET /v1/nodes/`
- `GET /v1/nodes/list`
- `POST /v1/nodes`
- `PUT /v1/nodes/{param}`
- `DELETE /v1/nodes/{param}`
- `POST /v1/nodes/check-connection`
- `POST /v1/nodes/refresh-now`
- `GET /v1/nodes/{param}/server-status`
- `GET /v1/nodes/{param}/panel-update-info`
- `GET /v1/nodes/{param}/inbounds`
- `GET /v1/nodes/{param}/client-traffic`
- `GET /v1/nodes/{param}/client/{param}/traffic`
- `GET /v1/nodes/{param}/generate-{param}`
- `POST /v1/nodes/{param}/generate-keypair`

### Node Server Operations

- `GET /v1/servers/{param}/status`
- `POST /v1/servers/{param}/restart-xray`
- `GET /v1/nodes/{param}/xray-logs`
- `GET /v1/nodes/{param}/server-logs`
- `GET /v1/nodes/{param}/xray-versions`
- `POST /v1/nodes/{param}/install-xray/{param}`
- `POST /v1/nodes/{param}/stop-xray`
- `POST /v1/nodes/{param}/update-panel`
- `POST /v1/nodes/{param}/update-geofile`
- `GET /v1/nodes/{param}/outbounds-traffic`
- `GET /v1/nodes/{param}/xray-metrics`
- `GET /v1/nodes/{param}/xray-observatory`
- `GET /v1/nodes/{param}/xray-config`
- `GET /v1/nodes/{param}/server-history/{param}`
- `GET /v1/nodes/{param}/api-tokens`
- `POST /v1/nodes/{param}/api-tokens`
- `DELETE /v1/nodes/{param}/api-tokens/{param}`
- `POST /v1/nodes/{param}/api-tokens/{param}/set-enabled`

### Clients

- `GET /v1/clients`
- `GET /v1/clients/count`
- `GET /v1/clients/online`
- `POST /v1/clients/last-online`
- `GET /v1/clients/find-by-ip`
- `GET /v1/clients/{param}/ips`
- `GET /v1/clients/{param}/links`
- `POST /v1/clients/add-to-nodes`
- `POST /v1/clients/batch-add`
- `POST /v1/clients/batch-delete`
- `POST /v1/clients/bulk-adjust`
- `POST /v1/clients/bulk-enable`
- `POST /v1/clients/bulk-reset-traffic`
- `POST /v1/clients/del-depleted`
- `PUT /v1/clients/{param}`
- `DELETE /v1/clients/{param}`
- `POST /v1/clients/{param}/reset-traffic`
- `POST /v1/clients/{param}/clear-ips`
- `POST /v1/automation/reset-all-traffic`

### Client Groups

- `GET /v1/nodes/{param}/client-groups`
- `POST /v1/nodes/{param}/client-groups`
- `PUT /v1/nodes/{param}/client-groups/{param}`
- `DELETE /v1/nodes/{param}/client-groups/{param}`
- `GET /v1/nodes/{param}/client-groups/{param}/emails`
- `POST /v1/nodes/{param}/client-groups/{param}/add`
- `POST /v1/nodes/{param}/client-groups/{param}/remove`

### Inbounds

- `GET /v1/inbounds`
- `POST /v1/inbounds`
- `POST /v1/inbounds/clone`
- `PUT /v1/inbounds/{param}/{param}`
- `DELETE /v1/inbounds/{param}`
- `POST /v1/inbounds/batch-enable`
- `POST /v1/inbounds/batch-update`
- `POST /v1/inbounds/batch-delete`
- `POST /v1/inbounds/{param}/{param}/reset-traffic`
- `POST /v1/inbounds/{param}/{param}/del-all-clients`
- `POST /v1/inbounds/{param}/{param}/set-enable`
- `POST /v1/inbounds/{param}/reset-all-traffics`

### Traffic

- `GET /v1/traffic/stats`
- `GET /v1/traffic/stats-by-period`
- `FETCH /clients/stats/traffic?period=day`

### Monitoring And External Ops Panels

- `GET /v1/collector/status`
- `GET /v1/health/deps`
- `GET /v1/history/nodes/{param}`
- `GET /v1/adguard/sources`
- `POST /v1/adguard/sources`
- `GET /v1/adguard/overview`
- `GET /v1/adguard/history`
- `POST /v1/adguard/collect-now`
- `GET /v1/monitoring/stack`

### Backup And Restore

- `GET /v1/backup/all`
- `GET /v1/backup/node/{param}`
- `POST /v1/backup/node/{param}/import`
- `POST /v1/nodes/{param}/backup-telegram`

### Subscriptions

- `GET /v1/emails`
- historic link builder: `/v1/sub/{email}`
- historic link builder: `/v1/sub-grouped/{email}`

Current delivery links require signed tokens: `/api/v1/sub/{token}` and
`/api/v1/sub-grouped/{token}`.

### External Utility

- QR code rendering uses an external QR image URL in UI code.
- This is not part of the internal API layer and should be wrapped or isolated separately if retained.

## Blockers And Risks

- Working tree is dirty and partly staged.
- API domain behavior is embedded inside UI components.
- Some dashboard components are still transitional, especially lower lanes.
- Production build archives are not valid API extraction sources.
- Audit did not rerun build/lint/smoke.
- Previous memory indicates lint had known issues after the redesign preservation pass.
- `.local_project_docs/` is private-only and must not be copied into public docs.

## Working Rules For Next Runs

1. Do not rewrite old UI into the new stack.
2. Extract API behavior by domain first.
3. Keep `frontend/src/api.ts` or its successor as transport-only.
4. Move component request logic into services/query hooks incrementally.
5. Validate after every extraction slice.
6. Keep dashboard UI changes scoped to the dashboard unless explicitly expanded.
7. Use the backup ref only as API behavior reference, not as visual reference.
8. Record every phase in this chapter or a follow-up chapter file.

## Proposed Next Phases

### Phase 2: API Mapping

Output:

- service-module map;
- operation-to-component map;
- exact first extraction slice.

Recommended first slice:

- `auth`
- `dashboard`
- `nodes`
- `backup`

Reason:

- these are needed by the shell/dashboard and have clear boundaries.

### Phase 3: Service Extraction

Output:

- `frontend/src/api/*` modules;
- components call services instead of raw `api.get/post/...`;
- no behavior changes intended.

Validation:

- `cd frontend && npm run build`
- `cd frontend && npm run lint`

### Phase 4: Query/State Layer

Output:

- hooks or query helpers for dashboard data;
- less API wiring inside visual components;
- clear loading/error/empty state contracts.

### Phase 5: UI Completion

Output:

- lower dashboard lanes cleaned up;
- `ServerStatus` dashboard mode flattened;
- `NodeManager` dashboard mode converted to overview entries;
- browser smoke + visual check.

## Current Definition Of Ready For Phase 2

Ready: yes.

Reason:

- backup API source is identified;
- unique API operations are counted and grouped;
- current and backup API surfaces match;
- UI baseline is documented;
- old visual layer can be avoided.

Not ready for implementation freeze:

- no fresh build/lint/smoke from this run;
- worktree state must be handled carefully before committing or broad refactoring.
