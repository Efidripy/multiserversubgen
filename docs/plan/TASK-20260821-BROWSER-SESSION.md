# Session Preflight

- task_id: `TASK-20260821-MSSG-BROWSER-SESSION-01`
- intent: `debugging`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `codex/mssg-remediation-roadmap`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed; local BHM Core is healthy, native MCP tools are not attached to this session
- memory_preflight: started; repository/workspace evidence remains the active source of truth
- memory_queries: `security patterns`; deployment lookup will precede production rollout
- hybrid_session_record: required at closeout

## Scope

- scope_in: persist authenticated browser access across reloads for exactly eight hours using a server-issued signed cookie; preserve Basic Auth, RBAC, MFA and CSRF controls; add regression coverage and update the remediation record.
- scope_out: database/schema changes, password persistence in browser storage, secret rotation, SSO, server-side session revocation list, unrelated UI/performance changes.

## Risk

- initial_risk: high
- key_risks: authentication bypass, CSRF regression, cookie path mismatch behind the production subpath proxy, accidental interruption of existing Basic-Auth clients.
- rollback: deployment helper creates and verifies a release/database backup before service stop; local patch can be reverted as one commit.

## Validation Plan

- lint: `ruff check backend`; frontend ESLint and TypeScript.
- tests: focused backend auth/CSRF tests plus existing API smoke; frontend tests.
- smoke: production login, F5 preservation, logout and F5 after logout; service health and SQLite integrity only after local gates pass.

## Start Status

- what: replace memory-only browser credentials with an eight-hour signed secure cookie session.
- why: F5 clears the JS runtime and returns the operator to the common login form.
- risk: cookie authentication must not weaken MFA, RBAC or mutation CSRF protection.
