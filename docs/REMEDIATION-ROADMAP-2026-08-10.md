# Remediation Roadmap — 2026-08-10

**Status:** active implementation record
**Task:** `TASK-20260810-MSSG-REMEDIATE-01`
**Base revision:** `f381794d0129fa7ec15ae3c6e2e6f3ddd8112fe1`
**Scope:** tracked source, tests, installers, unit templates, CI and documents.
**Out of scope:** production deployment, secret rotation on external systems,
Git-history rewrite and publication.

## Decision

The audit is accepted. Changes are delivered in one ordered stream: security
boundaries first, then runtime reliability, frontend lifecycle, operational
hardening and quality/documentation. A finding is marked complete only with a
focused regression check plus the owning subsystem's checks.

## Immediate operational gate

Before any Git-history rewrite, the credential formerly reachable from
`3756ca9:deploy_slice.py:25` must be rotated or revoked by its owner. Its value
is deliberately not reproduced in this repository or record. The rotation
receipt is an external prerequisite; code work can continue independently.

## Work items

| ID | Priority | Outcome | Acceptance evidence |
| --- | --- | --- | --- |
| SEC-01 | P1 | No Redis URL or TOTP seed is logged or embedded in a systemd unit. | Focused installer/update checks; secret file mode and migration documentation. |
| SEC-02 | P1 | Runtime signing and WS secrets survive restart. | Settings regression tests and documented one-time provisioning. |
| REL-01 | P1 | Blocking XUI/PAM/SQLite paths do not run in the FastAPI event loop. | Concurrency regression tests and route-level checks. |
| FE-01 | P1 | HTTP 401 performs one safe logout and closes all live transports. | Frontend unit tests. |
| FE-02 | P1 | Inactive tabs stop polling and subscriptions. | Hook/component tests and browser smoke where feasible. |
| OPS-01 | P2 | Service runs least-privilege and never kills an arbitrary port listener. | Unit/template assertions and install/update checks. |
| OPS-02 | P2 | Deploy rollback validates target and protects backups. | Shell tests/static checks. |
| SC-01 | P2 | Privileged downloads are reproducible and independently verified. | Pinned manifest/checksum tests. |
| ARC-01 | P2 | One production composition-root architecture is explicit. | ADR and executable migration boundary. |
| QLT-01 | P2 | CI exercises full tests/lint/type/build/shell/dependency gates. | Workflow checks. |
| DOC-01 | P2 | Entry points and API/ops documentation match runtime contracts. | Link and contract checks. |
| PERF-01 | P1 | Section navigation avoids duplicate cold fetches, per-node history fan-out and synchronous audit commits. | Focused backend/frontend performance regressions plus package checks. |
| PERF-02 | P1 | Traffic/Client cold paths defer remote fan-out, viewer UI avoids denied work and WebSocket reconnect observes RBAC/ticket lifecycle. | Focused frontend regressions, package checks and authenticated production waterfall. |
| PERF-03 | P1 | Cold section rendering has one owner per remote projection, and repeated realtime/cache-miss callers do not multiply a fleet fan-out. | Focused concurrency/component regressions, package checks and authenticated production waterfall. |
| PERF-04 | P1 | Dashboard shows last known top client traffic while summary rendering never starts a remote-node fan-out. | Projection-only route regression, runtime no-fetch regression and package checks. |
| SUB-01 | P1 | Subscription URLs are stable, legacy named URLs redirect safely, manual rotation is explicit, and QR generation stays local. | Token persistence/redirect tests, admin RBAC test, frontend build and local QR rendering. |
| UX-01 | P1 | Russian locale renders as UTF-8, and node editing can safely update an endpoint and credentials without exposing stored secrets. | Locale-integrity and node-edit unit tests; router contract tests; frontend/backend package gates and authenticated browser smoke after rollout. |
| 3X-01 | P0 | The control-plane authenticates against current 3x-ui and reads online/traffic data through supported API routes. | CSRF JSON-login regression, modern-first route regressions, upstream/live OpenAPI audit and production read-only smoke. |
| 3X-02 | P1 | Per-node runtime capabilities, redacted diagnostics and a read-only Xray 26 compatibility audit prevent panel-version drift from creating silent failures. | Capability cache/fallback/invalidation regressions, Xray analyzer regression, UI build and production snapshot/UI receipt. |

## Initial evidence

- Backend suite: `208 passed` at the audit revision.
- Frontend lint, TypeScript, i18n and production build passed.
- Full tracked-shell ShellCheck failed; CI did not cover the installer tree.
- Full-lock npm audit reported two high advisories; production-oriented audit
  reported one high advisory.
- BHM audit record: `mem_bhm_39ca5e08a9e742bc`; snapshot:
  `snapshot_bhm_33205254dcbf778d0914a35c`.

## Update protocol

Each implemented work item records changed files, regression evidence, backward
compatibility notes and any external blocker here. This document replaces
`docs/IMPROVEMENTS.md` as the live remediation source of truth; the older file
remains a historical snapshot.

## Execution record — 2026-08-10

| ID | State | Implemented evidence and remaining boundary |
| --- | --- | --- |
| SEC-01 / SEC-02 | implemented | Runtime secrets live in root-only `/etc/<project>/runtime-secrets.env`; the unit reads it through `EnvironmentFile` and production startup fails closed without signing secrets. Installer regression checks cover mode, no inline secret and no secret logging. Historical credential rotation remains an external prerequisite before history rewrite. |
| AUTH-01 | deployed with live cookie-flow proof | Browser access persists through F5 via an eight-hour signed `HttpOnly; Secure; SameSite=Strict` cookie derived from the runtime signing secret; no password is stored in Web Storage. Focused MFA, tamper, logout, CSRF and subpath-cookie tests pass. Atomic production rollout, backup SHA-256, service/health/SQLite and live HTTPS session → refresh verification → CSRF → logout flow passed. |
| REL-01 | implemented | XUI/PAM/cache paths are offloaded through `run_in_threadpool`; SQLite and monitoring handlers use synchronous FastAPI worker handlers so their transaction boundaries do not block the event loop. XUI sessions are cloned per caller, have a finite TTL and are invalidated on credential changes. If an updated node removes cached legacy login endpoints, the controller invalidates that auth-method cache entry and re-probes CSRF in the same request. Focused router/security checks cover the boundary. |
| FE-01 / FE-02 | implemented | Auth-required teardown is one-shot, inactive tabs unmount, WebSocket ownership is centralized and large managers are lazy chunks. Vitest contracts cover the critical lifecycle behaviour. |
| OPS-01 | implemented pending live-host proof | The service uses a dedicated system user, root-only secret input, sandbox controls and an explicit occupied-port preflight. A real Ubuntu install/update smoke remains required before production use. |
| OPS-02 | implemented with live-host proof | `server-deploy.sh` requires an already-checked-out immutable ref, validates `/opt/<project>`, stages a full release and takes a consistent SQLite `.backup` of `admin.db` only after stopping the service and checkpointing WAL. The staged release carries that verified database copy and `.encryption_key`; failure stops the service before atomic restoration. Live proof on `dev.kleva.ru` (2026-08-17) validated SHA-256 backups, SQLite integrity, runtime files, Uvicorn, Nginx and rollback recovery. The helper additionally bounds frontend heap, waits for readiness, repairs relocated venv entrypoints and preserves Nginx traversal/read permissions for public build assets. |
| SC-01 | implemented | `artifact_manifest.sh` pins reviewed release versions and SHA-256 values for Loki/Promtail, 3x-ui, AdGuard Home and sub2sing-box; installer verification fails closed and no longer asks GitHub `latest` APIs for digest values. |
| ARC-01 | implemented | ADR-0001 states and tests `backend/main.py` as the only production composition root. The registry remains experimental until a separately gated migration. |
| QLT-01 | implemented | CI uses Python hash locks, full backend tests and ShellCheck error gate; `ruff.toml` fixes the established `E4,E7,E9,F` lint baseline so a Ruff upgrade cannot silently widen CI to legacy style rules. The frontend lock now uses `vitest ^3.2.7`, resolving the nested vulnerable Vite/esbuild test chain; `brace-expansion` resolves to `5.0.9`. Frontend CI runs lint, Vitest, typecheck, i18n, build and production audit. |
| DOC-01 | implemented | `PROJECT.md`, `AGENTS.md`, roadmap, ADR, API auth/subscription contract and dynamic-port documentation are aligned. |
| PERF-01 | deployed with public latency receipt | `docs/PERF-01-NAVIGATION-CACHING-2026-08-17.md` is the detailed record. Frontend GET requests coalesce before cache warm-up; monitoring uses one bounded fleet-history read and defers auxiliary probes. Audit enqueue is bounded in memory with batch SQLite persistence; Redis has short timeout/circuit fallback; clients/inbounds cold fetches single-flight and client notes use a filtered projection. Production public panel, health and main asset have 20-request p50/p95 receipts; authenticated dashboard/API waterfall remains a separate read-only evidence gate. |
| PERF-02 | deployed with authenticated production receipt | `docs/PERF-02-PRODUCTION-UI-COLD-PATH-2026-08-17.md` records the production waterfall findings and the deferred-loading, cancellation, role-aware and WebSocket remediation. The 2026-08-17 rollout passed service/Nginx/SQLite backup/integrity gates and authenticated panel checks; PERF-03 closes the residual duplicate header projection and concurrent cold-cache fan-out found by that proof. |
| PERF-03 | deployed with authenticated production receipt | `docs/PERF-03-FANOUT-CONTROL-2026-08-17.md` records the duplicate-request, realtime-throttle and cache single-flight controls and their post-deploy proof. No schema, migration, DDL or SQLite data operation was made; verified backup, SQLite integrity/count and browser waterfall gates passed. |
| PERF-04 | deployed with authenticated production proof | Dashboard summary now reads client traffic solely from the existing Redis/process-memory/SQLite snapshot projection, sorts and limits the returned top clients, and never invokes the cache API that may fan out to XUI nodes. Commit `afdc4e2` was released through the rollback-first helper; the verified backup is `/var/backups/sub-manager_deploy/project_20260821T104650Z-afdc4e23f067.tgz`. Service, health, Nginx, SQLite integrity/count (`9` nodes, `9` snapshots, `87` subscription tokens) and deployed-file SHA-256 matched; authenticated browser reload showed five ranked clients with no console errors. No schema or SQLite data mutation was required. |
| SUB-01 | implemented locally; production rollout pending | Added idempotent `subscription_tokens` SQLite table, stable opaque tokens, admin-only manual regeneration, redirects from legacy named/HMAC URLs, and client-side QR generation via `qrcode`. Focused backend tests and frontend lint/typecheck/i18n/build pass. Production deployment is intentionally separate and requires backup/integrity/read-only smoke proof. |
| UX-01 | deployed with read-only production proof | Repaired the damaged `ru.json` selectively from Windows-1252 mojibake, replaced the unrecoverable `?` runs, and added locale parity/integrity tests. The node edit dialog now pre-fills only non-secret connection data; it updates URL, port, username, password or bearer token through partial `PUT`, and empty secret fields preserve stored credentials. The router validates canonical endpoint fields, permits password-only rotation for credential-based nodes, rejects empty/mixed auth updates and invalidates both old and new endpoint caches. The `Registered fleet` Edit action now passes the selected node to that dialog instead of incorrectly opening the add-node form. Atomic rollout of `4bbfa1d` created `/var/backups/sub-manager_deploy/project_20260821T110452Z-4bbfa1de1b80.tgz`; service, health, Nginx, SQLite integrity/count (`9` nodes, `9` snapshots, `87` tokens) and backup SHA-256 matched. Authenticated browser proof opened `185-RF-E` with populated label, URL, port and username; password remained blank and no node was saved or changed. |
| 3X-01 | deployed with production receipt | `docs/3XUI-COMPATIBILITY-AUDIT-2026-08-21.md` records the upstream v3.6.0 and installed-panel contract evidence. CSRF login sends JSON credentials, and monitoring prefers `clients/onlines` / `clients/traffic` with a bounded legacy fallback. `f10b153` was released through the rollback-first helper; backup SHA-256, service/health/Nginx, SQLite integrity/counts, deployed source hashes and authenticated browser Monitoring proof passed. No node/panel data or schema was changed. |
| 3X-02 | deployed with production receipt | Adds an ephemeral per-node capability registry with TTL and edit invalidation, treats probe `404/405` as endpoint absence rather than forced re-auth, emits redacted actionable failure codes, and scans existing inbound-list snapshots for Xray 26 compatibility. The scanner stores only aggregate finding codes/counts in existing snapshot JSON and preserves unknown current XHTTP fields in the form editor. Atomic `d293c2e` rollout validated its backup SHA, service/health/Nginx, SQLite integrity/counts and deployed source hashes; first read-only collector pass found eight `ok` snapshots and one XHTTP legacy-key migration warning. No config write, node mutation, DDL or schema migration occurred; detailed evidence is in `docs/3XUI-COMPATIBILITY-AUDIT-2026-08-21.md`. |

Current validation receipt: backend `228 passed`, Ruff and compileall pass;
frontend Vitest `9 passed`, ESLint, TypeScript, i18n, Vite build and production
`npm audit` pass (`0 vulnerabilities`). Full tracked-shell `shellcheck -S error`
and `git diff --check` pass. Workspace mix-gate: `21 PASS / 0 WARN / 0 FAIL`.
At validation time BHM health was healthy with native MCP attached; repository
index status reported fresh snapshot `snapshot_bhm_151e0a4d75cd31946722f1aa`
for the dirty remediation worktree. The later MCP transport detached while
closing the session; coverage endpoint timed out and graph freshness must be
treated as separate evidence. No deploy or live-host rollback proof was
performed.
