# Session Preflight

- task_id: `MSSG-20260821-P2C-3XUI-MUTATION-CONTRACT`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `mssg-3xui-mutation-contract-20260821` → one PR → `main`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed
- memory_preflight: completed; BHM runtime healthy, current MCP session identity unverified
- upstream_source: `MHSanaei/3x-ui` tag `v3.6.0`, commit `c377dca27c23549cdf84e0ffd2d287a16bee577c`

## Scope

- scope_in: one isolated P2-C correction and mock-contract tests for the
  current 3x-ui client update API: full read-merge-write update, v3 email
  identity resolution, and one-inbound mutation scope.
- scope_out: every production/live panel, node configuration, inbound/client
  data, credentials/tokens, SQLite schema/data, 3x-ui write probes and deploy.

## Confirmed risk

`POST /panel/api/clients/update/{email}` in current 3x-ui binds a complete
client object and replaces the target row. Sending a partial UI update can
erase retained fields; treating a UUID as the `{email}` route segment can
also turn a missing entity into a false legacy-version fallback. A targeted
inbound update is carried by optional `?inboundIds=<id>`; omitting it
propagates across every attachment.

## Decision and validation

Read the complete client record from the same authenticated panel session,
merge only explicit control-plane changes, and then call the scoped update.
Resolve the current email before the v3 update, preserve all fields of the
current `model.Client` record, and scope a single-inbound update explicitly.
A fallback is allowed only after the v3 list/update route itself is absent
(`404/405`); other failures must not trigger a write or downgrade a node
capability.

## Risk and containment

- initial_risk: `high` — an incorrectly shaped live update can replace remote
  client fields or affect every attached inbound.
- containment: no live write probe; the change is exercised exclusively with
  mocked request contracts and falls back only when the v3 route is absent.

## Validation Plan

- lint: backend Ruff; frontend ESLint and TypeScript.
- tests: full backend suite and frontend Vitest.
- smoke: frontend i18n/build, backend compileall, tracked-shell ShellCheck,
  `git diff --check` and workspace mix-gate.

## Start Status

- what: protect partial UI client edits from the v3 replacement contract.
- why: current 3x-ui accepts a full `model.Client`, not a PATCH body.
- risk: no production, node, client, inbound, SQLite or token state may be
  changed in this stream.
