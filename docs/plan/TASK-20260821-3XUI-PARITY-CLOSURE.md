# Session Preflight

- task_id: `TASK-20260821-3XUI-PARITY-CLOSURE`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: one local implementation stream; final integrator is Codex; publication only through protected-branch PR
- single_integrator: Codex
- memory_project: `multiserversubgen`
- memory_bootstrap: completed
- memory_preflight: completed; native BHM MCP attached and healthy
- memory_queries: `3x-ui mutation fallback 404 405`, `client identity email traffic`, `inbound XHTTP Reality preservation`, `deployment checklist`
- hybrid_session_record: required at closeout

## Scope

- scope_in: Wave A--D implementation from the master 3x-ui registry: strict
  mutation fallback, client/inbound contracts, current routes/DTOs, encoded
  path segments, read/ops diagnostics, focused regression coverage and
  documentation status.
- scope_out: production deployment, SSH/live probes, real node/client/inbound
  mutations, production SQLite/data/schema changes, token creation/deletion,
  credential rotation and feature-gap expansion.

## Risk

- initial_risk: high
- key_risks: repeat mutations after partial remote success; loss of unknown
  inbound fields; accidental production action; route/runtime drift from
  upstream v3.6.0.
- containment: mock-only deterministic transport tests; fallback only after
  `404/405`; no live mutation; production data is never a test fixture; each
  operation returns terminal failure for operational errors.

## Validation Plan

- lint: `ruff check backend`, frontend ESLint, TypeScript and i18n checks.
- tests: focused adapter contracts followed by full backend pytest and frontend
  Vitest.
- smoke: local API/static checks only; no remote node calls.
- release: `git diff --check`, tracked-shell ShellCheck, workspace mix gate,
  protected-branch PR checks.

## Start Status

- what: close the confirmed and high-risk compatibility debt as dependency
  ordered waves rather than individual opportunistic fixes.
- why: current adapters can silently lose traffic data, fail current v3 routes
  and, in Wave A, risk a second destructive mutation.
- risk: no deployment or live acceptance is authorised by this task; those
  remain explicit disposable-node follow-ups.
