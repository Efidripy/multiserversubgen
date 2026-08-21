# Session Preflight

- task_id: `MSSG-20260821-P2-BACKUP-API`
- intent: `delivery`
- repository: `E:\GitHub\repos\multiserversubgen`
- change_stream: `codex/p2-backup-api-docs` → one PR → `main`
- single_integrator: Codex `/root`
- memory_project: `multiserversubgen`
- memory_bootstrap: completed
- memory_preflight: completed; native BHM runtime is healthy, but no BHM MCP tool is attached to this Codex turn
- memory_queries: `multiserversubgen checkpoint status known issues next`; `multiserversubgen project conventions validation commands`
- hybrid_session_record: required at closeout

## Scope

- scope_in: remove automatic full-database backup fetch from the Backup Manager cold path; retain explicit per-node and all-node download/import behaviour; update canonical API documentation and focused contract coverage.
- scope_out: database schema/data migrations; production deployment; node configuration, inbound/client/subscription/token changes; 3x-ui mutation probes; credential rotation; Git-history rewrite.

## Risk

- initial_risk: medium
- key_risks: accidental regression in restore/download actions; exposing raw backup data in a metadata/list response; documentation drift from the actual production router.

## Validation Plan

- lint: `ruff check backend`, frontend ESLint, TypeScript and i18n checks.
- tests: focused backend route tests and frontend component tests, then full backend/frontend suites.
- smoke: Vite production build, project smoke script, documentation link/contract review, `git diff --check` and secret scan.

## Start Status

- what: make the Backup Manager metadata-first and make its documented API match current routes/auth/session behaviour.
- why: `GET /api/v1/backup/all?format=json` currently fetches full databases from every node solely to render a list; measured cold path is about 17.4 seconds.
- risk: no automatic production action; rollback is the Git branch/PR until a separately authorised rollback-first deployment.
