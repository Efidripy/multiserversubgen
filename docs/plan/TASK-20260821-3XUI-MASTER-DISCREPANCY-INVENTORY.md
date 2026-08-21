# Session Preflight

- task_id: `TASK-20260821-3XUI-MASTER-DISCREPANCY-INVENTORY`
- intent: `audit`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: read-only audit on `main`; one final integrator is Codex
- single_integrator: Codex
- memory_project: `multiserversubgen`
- memory_bootstrap: completed
- memory_preflight: completed; native BHM MCP is attached and healthy
- memory_queries: `3x-ui compatibility audit remaining mutation adapters deferred contracts production boundaries`
- hybrid_session_record: required at closeout

## Scope

- scope_in: all control-plane adapter routes and payloads used by the product,
  upstream 3x-ui v3.6.0 OpenAPI/controller, prior installed-panel API evidence,
  regression coverage and existing compatibility records.
- scope_out: implementation, live probes or mutations, production deployment,
  remote node/data/configuration changes, SQLite/data/schema, secrets/tokens.

## Risk

- initial_risk: medium
- key_risks: treating undocumented drift as a confirmed bug; treating an
  OpenAPI route as runtime proof; proposing a fallback that repeats a mutation.
- containment: source/OpenAPI/mock-test evidence only; findings explicitly
  distinguish confirmed mismatch, verified compatibility and unknown/live gate.

## Validation Plan

- static: deterministic inventory of actual adapter routes against the upstream
  OpenAPI/controller; file/line references; review of existing regressions.
- evidence: cross-check prior documented installed-panel observations; no remote
  API call is authorised in this audit.
- output: one canonical discrepancy registry, a deduplicated P0--P3 backlog,
  and a dependency-ordered execution plan.

## Start Status

- what: replace task-by-task selection with one bounded master inventory.
- why: outstanding compatibility debt needs a single auditable queue before
  further fixes are chosen.
- risk: no code will be changed; any unresolved contract remains visibly marked
  as unknown rather than assumed compatible.
