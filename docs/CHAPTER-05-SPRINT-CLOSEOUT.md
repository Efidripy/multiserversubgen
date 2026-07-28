# Chapter 05: Sprint Closeout And Memory Sync

Date: 2026-06-06
Project: `multiserversubgen`
Branch: `codex/dashboard-api-service-layer`
Previous chapter: `docs/CHAPTER-04-TESTING-AND-VERIFICATION.md`

## Sprint Result

Status: completed for the dashboard Figma migration sprint.

The sprint goal was to keep the redesigned dashboard direction while extracting working API behavior into a typed service layer and proving that the dashboard can render under backend failure conditions. That goal is complete for the verified dashboard slice.

What is complete:

- dashboard API calls are no longer embedded directly in the main dashboard lanes;
- `frontend/src/api/client.ts` owns the transport layer;
- domain wrappers exist for `authService`, `dashboard`, `nodes`, `backup`, and `serverOps`;
- dashboard-mode node loading uses `includeCounts=false` to avoid hidden count fan-out;
- node and dashboard payloads are normalized before reaching visual components;
- dashboard fallback/error states keep the UI rendered when the backend produces `Network Error`;
- Chapter 04 verified build, lint, and browser render stability for the frontend fallback path.

What is not claimed:

- the local backend/nginx environment is not fixed by this sprint;
- full backend e2e against `127.0.0.1:666` is still blocked by the environment issues documented in Chapter 04;
- the full-mode `ServerStatus` operational action extraction is still follow-up work.

## Integration Pattern Pipeline

Use this pipeline for the next Figma-to-admin module migrations.

1. Start from API inventory, not from visual component reuse.
   - Identify all endpoint operations used by the old working implementation.
   - Group them by domain before editing UI code.
   - Treat old visual components as behavior references only.

2. Create an isolated domain service before wiring a Figma screen.
   - Put endpoint ownership under `frontend/src/api/<domain>.ts`.
   - Keep `frontend/src/api/client.ts` transport-only.
   - Keep `frontend/src/api.ts` only as a temporary compatibility facade while migration is incomplete.

3. Keep auth API separate from runtime credential storage.
   - Use `frontend/src/api/authService.ts` for `/v1/auth/*` and `/v1/features`.
   - Do not create `frontend/src/api/auth.ts` while `frontend/src/auth.ts` is the runtime credential store.

4. Normalize every backend response at the service boundary.
   - Accept common envelopes such as raw arrays, `{ nodes: [...] }`, `{ data: [...] }`, `{ clients: [...] }`, and similar domain envelopes.
   - Return stable typed view data to React.
   - Never force component casts such as `as Node[]` to bridge backend drift.

5. Make hidden dashboard loads explicit and default them off.
   - Use options like `includeCounts`, `includeLiveStatus`, `includeCollectorStatus`, and `includePanelUpdateChecks`.
   - Dashboard overview mode should not pay for client/inbound counts, collector checks, or panel update checks unless the result is visible.
   - Full operational mode may opt in separately.

6. Make network failure a supported render state.
   - Components must catch service failures.
   - `Network Error` should produce fallback data, empty states, or scoped banners, not a blank React root.
   - Per-node enrichment failures should mark only the affected node as unavailable.

7. Validate after each meaningful slice.
   - For frontend service/UI changes run `cd frontend && npm run build`.
   - Run `cd frontend && npm run lint`.
   - Browser-smoke the migrated route with the backend unavailable when fallback behavior is part of the contract.
   - Run the workspace mix gate when code behavior changes, and document any environment blockers separately from frontend regressions.

## BHM Memory Vectors

These are the durable memory vectors saved for future agents and migrations.

### Figma Admin Migration Pipeline

When asked to migrate a `multiserversubgen` admin section from Figma, first build or verify the domain API service layer. Do not wire Figma visuals directly to raw `api.get/post` calls inside React components. Inventory endpoints, create `frontend/src/api/<domain>.ts`, normalize payloads at the service boundary, then connect the visual component to typed service functions.

### Auth Service Naming Rule

For `multiserversubgen` frontend API work, use `frontend/src/api/authService.ts` for auth and feature endpoint wrappers. Keep `frontend/src/auth.ts` as the runtime credential/TOTP store. Do not introduce `frontend/src/api/auth.ts`, because that name collides conceptually with the existing credential module.

### Dashboard Load Optimization Rule

For dashboard-mode admin components, every expensive or hidden data fan-out must be behind explicit flags such as `includeCounts=false`, `includeLiveStatus=false`, `includeCollectorStatus=false`, or `includePanelUpdateChecks=false`. Overview screens should fetch only data they render. Full operational tabs can opt into heavier enrichment.

### Envelope Normalization Rule

For `multiserversubgen` domain services, accept backend response envelopes before React sees data. Services should normalize raw arrays and common envelopes such as `{ nodes: [...] }`, `{ data: [...] }`, `{ clients: [...] }`, `{ inbounds: [...] }`, and return stable typed records. React components should not depend on backend envelope shape.

### Network Error Fallback Rule

Figma-migrated admin sections must treat `Network Error` as an expected local-dev/backend-down state. A failed request should render fallback metrics, an empty state, or a scoped error banner. It must not produce a white screen, uncaught render exception, or hidden failure when dashboard-specific props hide the legacy error area.

## Architecture Closeout

The sprint established a reusable migration standard:

- services own API contracts;
- components own visual state and interaction only;
- dashboard mode is explicitly lighter than full operations mode;
- fallback rendering is part of the contract;
- BHM stores the pattern so future Figma sections can trigger the same sequence automatically.

## Next Recommended Figma Module

Recommended next module: `Clients`.

Reason:

- the dashboard already depends on client aggregates (`clients_total`, `online_clients_total`, `top_clients`);
- the API inventory shows the clients domain has broad, high-value operations that are still outside the new service layer;
- `Clients` can reuse the proven pattern from nodes: domain service first, envelope normalization, opt-in heavy enrichment, then Figma UI wiring;
- extracting `clients.ts` will also improve future `Inbounds`, traffic, and subscriptions work because those screens share client state and links.

Suggested next slice:

1. Create `frontend/src/api/clients.ts`.
2. Normalize list/count/online/link/IP/group responses.
3. Move `ClientManager` read paths first.
4. Add flags for expensive batch/traffic enrichment.
5. Browser-smoke `Clients` with backend success and failure paths.
