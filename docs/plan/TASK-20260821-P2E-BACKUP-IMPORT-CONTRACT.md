# Session Preflight

- task_id: `MSSG-20260821-P2E-BACKUP-IMPORT-CONTRACT`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `mssg-backup-import-contract-20260821` → one PR → `main`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed in the parent remediation session
- memory_preflight: completed; BHM runtime healthy, current MCP session identity unverified
- memory_query: `security patterns backup import validation file upload SQLite`
- upstream_source: `MHSanaei/3x-ui` v3.6.0
  `c377dca27c23549cdf84e0ffd2d287a16bee577c`

## Scope

- scope_in: reject unsupported backup bytes before forwarding a restore to a
  node; accept the current 3x-ui SQLite database signature and SQLite
  migration-dump prefixes; add router contracts and update canonical API docs.
- scope_out: parsing or restoring the database locally; live backup/restore,
  node/client/inbound/token changes, SQLite schema/data changes, credentials
  and production deployment.

## Patch Contract

- input: authenticated JSON `backup_data` or multipart `file` body.
- broken boundary: non-empty arbitrary bytes reach `server_monitor` and then a
  destructive remote import request.
- invariant: remote import is never called unless the first 64 bytes match
  upstream's supported SQLite DB or migration-dump signatures.
- preserved behaviour: a `SQLite format 3` database, and a BOM/whitespace
  prefixed `PRAGMA` or `BEGIN TRANSACTION` SQLite dump, remain accepted.
- rejected behaviour: arbitrary non-empty data returns `400` and produces no
  remote import call.

## Risk and validation

- initial_risk: `high` — restore is destructive if an unsafe body is forwarded.
- containment: tests use a local stub monitor only; no node or database is
  opened, written, imported or restored.
- validation_plan: focused router contracts, full backend suite, Ruff,
  compileall, frontend checks, ShellCheck, `git diff --check` and mix-gate.
