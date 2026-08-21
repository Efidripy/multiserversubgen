# Session Preflight

- task_id: `TASK-20260821-P2H-3XUI-BULK-RESET-CONTRACT`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `mssg-3xui-bulk-reset-contract-20260821` → one squash PR
- single_integrator: Codex
- memory_project: `multiserversubgen`
- memory_bootstrap: completed
- memory_preflight: completed; native BHM MCP attached and healthy
- memory_queries: `3x-ui bulk reset traffic fallback mutation contract`
- hybrid_session_record: required at closeout

## Scope

- scope_in: current 3x-ui bulk traffic-reset route, narrowly safe fallback,
  mock-only regression tests and compatibility/remediation records.
- scope_out: live reset, nodes, clients, inbounds, SQLite/data, tokens,
  credentials and production deployment.

## Risk

- initial_risk: high
- key_risks: a traffic reset changes remote counters and can re-enable a client;
  an outage or malformed response must never trigger a second write through a
  guessed legacy route.
- containment: all verification uses mocked XUI requests; no external node is
  contacted and no database is opened or modified.

## Validation Plan

- lint: focused Ruff, `compileall`, `git diff --check` and full mix gate.
- tests: focused v3 contract tests and full backend suite.
- smoke: frontend lint, typecheck, i18n and production build; no live mutation
  smoke is authorised.

## Start Status

- what: replace the invalid bulk fallback route with documented v3 semantics.
- why: upstream 3x-ui v3.6.0 exposes `clients/bulkResetTraffic` and
  `clients/resetTraffic/{email}`, not a global `clients/resetClientTraffic`.
- risk: a reachable failing bulk request must be reported as failed, not retried
  via another mutation route.
