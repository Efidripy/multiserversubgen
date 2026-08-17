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
| REL-01 | implemented | XUI/PAM/cache paths are offloaded through `run_in_threadpool`; SQLite and monitoring handlers use synchronous FastAPI worker handlers so their transaction boundaries do not block the event loop. XUI sessions are cloned per caller, have a finite TTL and are invalidated on credential changes. Focused router/security checks cover the boundary. |
| FE-01 / FE-02 | implemented | Auth-required teardown is one-shot, inactive tabs unmount, WebSocket ownership is centralized and large managers are lazy chunks. Vitest contracts cover the critical lifecycle behaviour. |
| OPS-01 | implemented pending live-host proof | The service uses a dedicated system user, root-only secret input, sandbox controls and an explicit occupied-port preflight. A real Ubuntu install/update smoke remains required before production use. |
| OPS-02 | implemented pending live-host proof | `server-deploy.sh` requires an already-checked-out immutable ref, validates `/opt/<project>`, stages a full release and takes a consistent SQLite `.backup` of `admin.db` only after stopping the service and checkpointing WAL. The staged release carries that verified database copy and `.encryption_key`; failure stops the service before atomic restoration. It is static-tested only in this checkout. |
| SC-01 | implemented | `artifact_manifest.sh` pins reviewed release versions and SHA-256 values for Loki/Promtail, 3x-ui, AdGuard Home and sub2sing-box; installer verification fails closed and no longer asks GitHub `latest` APIs for digest values. |
| ARC-01 | implemented | ADR-0001 states and tests `backend/main.py` as the only production composition root. The registry remains experimental until a separately gated migration. |
| QLT-01 | implemented | CI uses Python hash locks, Ruff, full backend tests and ShellCheck error gate; frontend CI runs lint, Vitest, typecheck, i18n, build and production audit. |
| DOC-01 | implemented | `PROJECT.md`, `AGENTS.md`, roadmap, ADR, API auth/subscription contract and dynamic-port documentation are aligned. |
| PERF-01 | implemented locally, pending live receipt | `docs/PERF-01-NAVIGATION-CACHING-2026-08-17.md` is the detailed record. Frontend GET requests coalesce before cache warm-up; monitoring uses one bounded fleet-history read and defers auxiliary probes. Audit enqueue is bounded in memory with batch SQLite persistence; Redis has short timeout/circuit fallback; clients/inbounds cold fetches single-flight and client notes use a filtered projection. Local regressions cover these contracts. Browser p95 and active production concurrency require separate read-only evidence. |

Current validation receipt: backend `221 passed`, Ruff and compileall pass;
frontend Vitest `5 passed`, ESLint, TypeScript, i18n, Vite build and production
`npm audit` pass (`0 vulnerabilities`). Full tracked-shell `shellcheck -S error`
and `git diff --check` pass. Workspace mix-gate: `21 PASS / 0 WARN / 0 FAIL`.
At validation time BHM health was healthy with native MCP attached; repository
index status reported fresh snapshot `snapshot_bhm_151e0a4d75cd31946722f1aa`
for the dirty remediation worktree. The later MCP transport detached while
closing the session; coverage endpoint timed out and graph freshness must be
treated as separate evidence. No deploy or live-host rollback proof was
performed.
