# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**multiserversubgen** — Multi-Server Sub Manager v3.0. Web panel for managing multiple 3x-ui/xray VPN nodes: clients, inbounds, subscriptions, traffic stats, AdGuard monitoring, DB backups, RBAC, TOTP MFA.

Stack: **FastAPI** (Python, PAM auth) + **React/TypeScript/Vite** (Bootstrap 5, i18next, Chart.js). Frontend builds into `backend/build/`.

## Mandatory AgentMemory MCP Usage

If MCP `agentmemory` is available in the current session, use it for every non-trivial task in this repository.

Required workflow:
- search/read relevant memories before code cleanup, security work, architecture changes, audits, and convention changes;
- write durable decisions, important findings, and cross-session handoff context back to memory;
- keep repository docs and workspace docs as source of truth, using AgentMemory as persistent searchable context;
- if the local AgentMemory runtime is running but not exposed through active MCP tools/resources/templates, report that and continue with file-based context.

Known local runtime hints:
- engine: `ws://localhost:49134`
- OTel endpoint: `ws://localhost:49134/otel`
- viewer: `http://localhost:3113`

### AgentMemory Token-Saving Checkpoints

Save a compact AgentMemory checkpoint after each meaningful cleanup, audit, security, architecture, or implementation iteration.

Use this shape:

```text
multiserversubgen checkpoint:
done: ...
current debt/status: ...
next: ...
checks: ...
risks/notes: ...
```

Save project status, next target, changed files, validation results, i18n debt counts, security decisions, and known pitfalls.

Do not save source dumps, secrets, private `.local_project_docs` content, raw logs, or unverified guesses.

## Development Commands

### Backend
```bash
cd backend
pip install -r requirements.txt          # prod deps
pip install -r requirements-dev.txt      # + dev/test deps

uvicorn main:app --reload --port 666     # dev server (if main.py exists at root)
# or via the app factory:
# APP_PORT=666 PROJECT_DIR=/opt/sub-manager python -m uvicorn ...

# Tests
pytest backend/tests/                    # all tests
pytest backend/tests/test_utils.py       # single file
pytest backend/tests/ -k "test_rbac"     # single test
```

### Frontend
```bash
cd frontend
npm install

npm run dev          # Vite dev server (proxies /api → localhost:666)
npm run build        # TypeScript check + i18n check + Vite build → backend/build/
npm run lint         # ESLint (0 warnings allowed)
npm run i18n:check   # check for hardcoded strings not in i18n
npm run i18n:baseline # regenerate i18n baseline
```

Frontend env vars:
- `VITE_BASE` — URL base path (e.g. `/my-panel/`)
- `VITE_BACKEND_TARGET` — backend address for dev proxy (default `http://localhost:666`)

### Key env vars (backend)
| Variable | Default | Purpose |
|---|---|---|
| `PROJECT_DIR` | `/opt/sub-manager` | DB and data root |
| `APP_PORT` | `666` | Listen port |
| `WEB_PATH` | `""` | URL subpath prefix |
| `VERIFY_TLS` | `true` | TLS verification for outbound requests |
| `REDIS_URL` | `""` | Redis (optional, for caching) |
| `ALLOW_ORIGINS` | `localhost:5173` | CORS origins |
| `ROLE_VIEWERS` | `""` | Comma-separated usernames with viewer role |
| `ROLE_OPERATORS` | `""` | Comma-separated usernames with operator role |
| `MFA_TOTP_ENABLED` | `false` | Enable TOTP MFA |
| `MFA_TOTP_USERS` | `""` | Users who must use TOTP |
| `READ_ONLY_MODE` | `false` | Disable all write operations |

## Architecture

### Backend module system

All features live in `backend/modules/<name>/`. Each module extends `BaseModule` (`core/base_module.py`) and must implement `initialize(container)`, `start()`, `stop()`, `health_check()`. Optional hooks: `register_routes(app)`, `register_events(event_bus)`, `register_jobs(job_queue)`.

`ModuleRegistry` (`core/module_registry.py`) handles topological dependency ordering, lifecycle orchestration, and health aggregation.

`Container` (`core/container.py`) is a simple DI container — register factories/instances, resolve by name. Used in module `initialize()` to get shared services.

`EventBus` (`core/event_bus.py`) — async pub/sub for cross-module events.

`JobQueue` (`core/job_queue.py`) — background job scheduling.

App startup: `core/lifespan.py` wires audit worker, snapshot collector, and AdGuard collector as async tasks around the ASGI lifespan.

Modules enabled/disabled via `backend/config/modules.yaml`. Feature flags at runtime via `backend/config/feature_flags.yaml`.

### Modules
- **auth** — PAM-based Basic Auth middleware + TOTP MFA + RBAC (viewer/operator roles via env)
- **nodes** — CRUD for VPN nodes (stored in SQLite `admin.db`)
- **polling** — adaptive polling scheduler, collects snapshots from all nodes via 3x-ui API
- **statistics** — traffic/performance/availability collectors with hourly/daily/monthly aggregators
- **subscriptions** — generates VLESS/VMESS/Trojan subscription URLs per email (rate-limited, no auth)
- **monitoring** — health checks, Prometheus/Loki/Grafana observability stack integration
- **adguard** — periodic collection from AdGuard Home sources

### Integrations
- `backend/integrations/xui/` — 3x-ui panel API client (per-node)
- `backend/integrations/redis/` — optional Redis client for distributed caching

### Legacy service layer
`backend/services/` and `backend/routers/` contain older service implementations that coexist with the new module system. The module system is the intended main path.

### Frontend structure
- `App.tsx` — root: login, tab routing, WebSocket listener, header stat summaries
- `frontend/src/components/` — one component per domain tab (NodeManager, ClientManager, InboundManager, TrafficStats, SubscriptionManager, MonitoringDashboard, BackupManager)
- `frontend/src/hooks/useWebSocket.ts` — WebSocket hook for real-time updates (snapshot_delta, inbound_update channels)
- `frontend/src/services/` — caching (staleCache, IndexedDB), polling scheduler, service worker, performance monitoring
- `frontend/src/contexts/ThemeContext.tsx` — three-mode theme (dark/light/cycle)
- `frontend/src/i18n/` — i18next with `en` and `ru` locales; all user-visible strings must go through `t()`
- `frontend/src/auth.ts` — credentials stored in localStorage; TOTP code via `X-TOTP-Code` header

Authentication flow: Basic Auth on every API request. Frontend sends credentials on each axios call via `{ auth: { username, password } }`. Subscription endpoint `/api/v1/sub/{email}` is unauthenticated.

### API base URL
`frontend/src/api.ts` derives `API_BASE` from `VITE_BASE`. In dev, Vite proxies `<base>/api/` → `localhost:666/api/`.

## Project-Specific Rules (from CODEX_INSPECTION_RULE.md)

Before cleanup changes, create a backup branch `backup/pre-cleanup-working-state` or tag `backup-before-cleanup`. The old working implementation must remain as an isolated, clearly-marked fallback until the new path is proven stable. Inspection results should follow the Critical / High / Medium / Cleanup / Suggested patch severity format.
