# Session Preflight

- task_id: `MSSG-20260821-P2F-3XUI-TRAFFIC-RESET-CONTRACT`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `mssg-3xui-traffic-reset-contract-20260821` → one PR → `main`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed in the parent remediation session
- memory_preflight: completed; BHM runtime healthy, current MCP session identity unverified
- upstream_source: `MHSanaei/3x-ui` v3.6.0
  `c377dca27c23549cdf84e0ffd2d287a16bee577c`

## Scope

- scope_in: make the single-client traffic reset use current 3x-ui
  `POST /panel/api/clients/resetTraffic/{email}`; retain the v2 inbound route
  only if the documented v3 route is absent.
- scope_out: any live client traffic reset, node/client/inbound/database/token
  mutation, configuration change, credentials and production deployment.

## Risk and validation

- initial_risk: `high` — reset is a remote mutation and can re-enable a client.
- containment: mocked request contracts only; no real session or remote route
  is contacted.
- validation_plan: focused client-v3 tests, full backend/frontend gates,
  ShellCheck, `git diff --check` and workspace mix-gate.
