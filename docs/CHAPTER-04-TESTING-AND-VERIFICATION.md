# Chapter 04: Testing And Verification

Date: 2026-06-06
Project: `multiserversubgen`
Branch: `codex/dashboard-api-service-layer`
Previous chapter: `docs/CHAPTER-03-SERVICE-EXTRACTION-AND-WIRING.md`

## Goal

Verify the Phase 3 dashboard service integration without relying on a working local backend.

This chapter focuses on:

- React render stability when dashboard API calls fail;
- fallback and network-error handling in `DashboardSummary`, `RegisteredFleetPanel`, and `NodeManager`;
- TypeScript data contracts between the new frontend service layer and dashboard component props;
- documenting backend environment blockers that prevent a real API e2e pass in this local run.

## Environment Constraint

Full e2e against the real backend is blocked in the current local environment.

Known blocker from the Chapter 03 mix gate:

- local backend health endpoint is unavailable: `127.0.0.1:666/health`;
- nginx/sub-manager smoke checks fail in this workstation state;
- Vite proxy calls to backend API routes fail while the dashboard still renders.

Phase 4 therefore treats backend failures as the test condition, not as a reason to skip UI verification.

## Fallback And Error Handling Status

`DashboardSummary`

- Calls `getDashboardSummary()`.
- On request failure, catches the error and renders normalized local fallback summary data.
- Keeps the loading spinner only for the initial pending state.
- Does not return a white screen when `/v1/dashboard/summary` fails.

`RegisteredFleetPanel`

- Calls `getRegisteredFleetOverview()`.
- If the node list request fails, catches the error, clears the node list, and renders an error empty state.
- If an individual per-node status request fails, the service marks only that node as `available: false` and stores the error on the node.
- Continues to publish a safe fleet summary to `App.tsx` even with zero nodes.

`NodeManager`

- Calls `getNodeDashboardOverview({ includeCounts })`.
- If node loading fails, catches the error, keeps any stale cached state if already present, clears the loading state, and records `nodes.loadFailed`.
- Phase 4 added a visible error banner for dashboard-only mode, where `showIntake=false` previously hid the existing error alert.
- Background panel-version/latency enrichment remains non-blocking and catches failures per node.

## Type Contract Verification

Fixed contract gaps found during Phase 4:

- `normalizeDashboardSummary()` now normalizes `nodes_total`, `clients_total`, `online_clients_total`, `traffic`, `online_by_node`, and `top_clients` into the exact `DashboardSummaryData` shape used by `DashboardSummary`.
- `listNodes()` now accepts common backend list envelopes (`NodeRecord[]`, `{ nodes: [...] }`, `{ data: [...] }`) and normalizes each item into `NodeRecord`.
- `NodeManager` now consumes `NodeRecord` directly instead of forcing `overview.nodes as Node[]` with stricter required `ip` and `port` fields.
- Node address and panel URL rendering now use safe helpers, so missing `ip` or `port` does not produce a runtime crash or `undefined:undefined` assumptions in action payloads.

No remaining TypeScript contract mismatch was found in the verified dashboard slice after these fixes.

## Render Smoke

Local smoke target:

- `http://127.0.0.1:5173/`

Observed with backend unavailable:

- `DashboardSummary` mounted.
- `RegisteredFleetPanel` mounted.
- `NodeManager` mounted.
- Dashboard body rendered non-empty content.
- API failures were visible as fallback/error states.
- No React white screen was observed.

Expected console noise in this environment:

- API calls through the Vite proxy fail because the backend is unavailable.
- Vite HMR websocket emitted a local dev-server warning in the browser session.

These are environment-level blockers, not dashboard render failures.

## Validation

Passed:

- `cd frontend && npm run build`
- `cd frontend && npm run lint`

Browser smoke:

- dashboard route rendered through Vite dev server with backend API failures;
- no uncaught render failure or blank root was observed.

Workspace gate:

- `validate-mix-gate.ps1 -ProjectName multiserversubgen` was run after the frontend checks.
- Result: failed on known workspace/backend environment blockers, not on the frontend lint slice.
- Gate log: `E:\GitHub\workspace\runtime\logs\projects\multiserversubgen\mix-gate-multiserversubgen-2026-06-06_04-47-15.log`
- Reported blockers:
  - routing drift: `bhm-codex-connector` project card mismatch in shared navigation docs;
  - tests: `scripts/ops/run-pytest-smoke.sh` could not open `/mnt/e/GitHub/repos/multiserversubgen/backend/requirements-dev.txt`;
  - smoke: local `sub-manager`, nginx config, `127.0.0.1:666/health`, frontend asset reference, and private panel reachability checks failed in the current local environment.

Not passed:

- full backend e2e against `127.0.0.1:666`;
- final mix gate, because the documented backend/nginx health blockers are still outside this frontend verification slice.

## Ready State

Frontend render stability: robust for the verified dashboard fallback path.

Ready for final sync:

- yes for frontend service integration and fallback verification;
- no claim is made that the backend environment is fixed.

Recommended next work:

- restore local backend health on `127.0.0.1:666/health`;
- rerun the full mix gate after backend/nginx smoke is green;
- add a focused component test harness for dashboard network-failure states once the project chooses Vitest/RTL or another React component test runner.
