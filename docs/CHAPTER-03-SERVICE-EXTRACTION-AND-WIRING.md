# Chapter 03: Service Extraction And Wiring

Date: 2026-06-06
Project: `multiserversubgen`
Branch: `codex/dashboard-api-service-layer`
Previous chapter: `docs/CHAPTER-02-API-MAPPING-2026-06-06.md`

## Goal

Resolve the Phase 2 blockers and move the redesigned dashboard from component-owned API calls toward a typed frontend service layer.

## Git Resolution

Before code extraction, the mixed working tree from the dashboard migration was preserved as a WIP checkpoint:

- source branch before extraction: `feature/admin-redesign-sprint2`;
- WIP commit: `3756ca9 chore: checkpoint dashboard migration state before API extraction`;
- active extraction branch: `codex/dashboard-api-service-layer`;
- untracked build archives were excluded locally through `.git/info/exclude` and were not committed into the service layer stream.

This resolves the `ready_for_code_extraction: false` blocker from Chapter 02.

## Service Layer Created

Created:

- `frontend/src/api/client.ts` - transport-only axios client, preserving base URL, interceptors, request activity, TOTP header forwarding, GET cache, and mutation invalidation;
- `frontend/src/api.ts` - compatibility facade that re-exports the transport client for older imports;
- `frontend/src/api/authService.ts` - auth/features API wrappers, intentionally not named `auth.ts` to avoid conflict with `frontend/src/auth.ts`;
- `frontend/src/api/dashboard.ts` - dashboard summary, shell header aggregates, latest snapshot, and dashboard server deck composition;
- `frontend/src/api/nodes.ts` - node list/status, registered fleet overview, dashboard node overview, CRUD, connection checks, and refresh;
- `frontend/src/api/backup.ts` - backup download/import and Telegram backup wrappers;
- `frontend/src/api/serverOps.ts` - server logs and operational node actions.

## Call-Sites Removed

`App.tsx`

- Replaced raw auth/features calls with `authService`:
  - `/v1/features`;
  - `/v1/auth/mfa-status`;
  - `/v1/auth/verify` for bootstrap and login.
- Replaced raw shell header summary calls with `dashboard.ts` aggregate fetchers:
  - dashboard nodes/snapshot summary;
  - inbounds header source;
  - clients header source;
  - traffic header source;
  - monitoring header source;
  - backup header source;
  - subscriptions header source.
- Result: `App.tsx` no longer imports the raw API transport, except for the compatibility `API_BASE` constant used to display the resolved API URL.

`DashboardSummary`

- Replaced the raw `GET /v1/dashboard/summary` call with `getDashboardSummary()`.
- Moved payload normalization into `dashboard.ts`.
- Kept the existing fallback data path in the component to avoid changing visual/demo behavior in this slice.

`RegisteredFleetPanel`

- Replaced raw `GET /v1/nodes` and per-node `GET /v1/nodes/{id}/server-status` fan-out with `getRegisteredFleetOverview()`.
- The component now owns only loading/error state, collapse behavior, summary callback, and rendering.

`NodeManager`

- Replaced raw transport imports with `nodes.ts`, `backup.ts`, and `serverOps.ts`.
- Replaced node list/status loading with `getNodeDashboardOverview()`.
- Replaced create/update/delete/check actions with service calls.
- Replaced selected backup download and selected Xray restart actions with domain services.
- Added `includeCounts?: boolean`; dashboard wiring passes `includeCounts={false}`.

`ServerStatus`

- Added dashboard-mode flags:
  - `includeCounts`;
  - `includeCollectorStatus`;
  - `includePanelUpdateChecks`;
  - `includeLiveStatus`.
- Dashboard wiring passes false for counts, collector status, and panel update checks.
- Added `getDashboardServerDeck()` for dashboard-mode initial server deck loading.
- Replaced dashboard-refresh path with `refreshNodesNow()`.
- Replaced log loading with `serverOps.getNodeLogs()`.
- Replaced selected restart path with `serverOps.restartXray()`.
- Remaining raw `api.*` call-sites are isolated to full-mode legacy operational actions in `ServerStatus` and should be handled in a later full-mode extraction slice.

## Blocker Decisions

`frontend/src/auth.ts` naming conflict:

- resolved by creating `frontend/src/api/authService.ts`;
- `frontend/src/auth.ts` remains the runtime credential store only.

`dashboard-command-grid__legacy-intake`:

- removed from dashboard route;
- the dashboard now mounts one `NodeManager` in dashboard mode and one `RegisteredFleetPanel` rail;
- this avoids a hidden second `NodeManager` paying the full intake/fleet load cost.

Hidden dashboard data loads:

- `ServerStatus` dashboard mode no longer loads `collector/status`;
- `ServerStatus` dashboard mode no longer loads online client counts or panel update checks;
- `NodeManager` dashboard mode no longer loads client/inbound counts.

## Validation

Passed:

- `cd frontend && npm run build`
- `cd frontend && npm run lint`

Lint gate needed two narrow non-behavioral fixes:

- `frontend/playwright.config.ts` added to ESLint ignore list because it is outside `tsconfig.json` project scope;
- stale `react-hooks/exhaustive-deps` disable removed from `src/services/useTrafficStatsSubscription.ts`.

Workspace gate:

- `validate-mix-gate.ps1 -ProjectName multiserversubgen` was run.
- Result: failed on workspace routing drift and environment-dependent tests/smoke, not on the frontend build/lint slice.
- Gate log: `E:\GitHub\workspace\runtime\logs\projects\multiserversubgen\mix-gate-multiserversubgen-2026-06-06_04-29-40.log`
- Reported blockers:
  - routing drift: `bhm-codex-connector` project card mismatch in shared navigation docs;
  - tests: `scripts/ops/run-pytest-smoke.sh` could not find `/mnt/e/GitHub/repos/multiserversubgen/backend/requirements-dev.txt`;
  - smoke: local `sub-manager`, nginx config, `127.0.0.1:666/health`, frontend asset reference, and private panel reachability checks failed in the current local environment.

## Remaining Work

- Extract the remaining full-mode operational raw `api.*` calls from `ServerStatus` into `serverOps.ts`, `backup.ts`, and later domain services.
- Split the large legacy components after service boundaries are stable.
- Add component-level tests or lightweight smoke coverage for dashboard loading once the test harness is selected.
