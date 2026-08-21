# Session Preflight

- task_id: `MSSG-20260821-P2G-3XUI-DELETE-CONTRACT`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `mssg-3xui-delete-contract-20260821` → one PR → `main`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed in the parent remediation session
- memory_preflight: completed; BHM runtime healthy, native session attachment currently unverified
- upstream_source: `MHSanaei/3x-ui` v3.6.0
  `c377dca27c23549cdf84e0ffd2d287a16bee577c`

## Scope

- scope_in: resolve a local v3 client UUID to its current email through the
  authenticated client list before `clients/del/{email}`; retain v2 only if the
  v3 list/delete route is absent.
- scope_out: live deletion or list access, node/client/inbound/database/token
  mutation, credentials and production deployment.

## Risk and validation

- initial_risk: `high` — delete is destructive.
- containment: mocked request contracts only; a failed/malformed list response
  must make zero delete requests.
- validation_plan: focused client-v3 tests, full package gates, ShellCheck,
  `git diff --check` and mix-gate.
