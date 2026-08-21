# Project Map

`multiserversubgen` is a FastAPI control plane and a React/Vite management UI
for a fleet of XUI-compatible nodes. The repository also owns the Linux
installer, updater, systemd unit and deployment helpers.

## Runtime map

- `backend/` — FastAPI application, SQLite persistence, XUI adapters and API
  routers. Production composition root: `backend/main.py`.
- `frontend/` — React/Vite single-page application. Build output is consumed by
  the backend deployment flow.
- `scripts/installer/` — interactive install and update paths plus external
  component provisioning.
- `scripts/deploy/` — server deployment helpers. They are local operator tools,
  not CI release authority.
- `systemd/`, `nginx/`, `monitoring/` — host integration templates.
- `docs/` — tracked operator and engineering documentation.

## Canonical engineering records

- Current remediation source of truth:
  [`docs/REMEDIATION-ROADMAP-2026-08-10.md`](docs/REMEDIATION-ROADMAP-2026-08-10.md).
- Navigation/cache performance record:
  [`docs/PERF-01-NAVIGATION-CACHING-2026-08-17.md`](docs/PERF-01-NAVIGATION-CACHING-2026-08-17.md).
- Production UI cold-path record:
  [`docs/PERF-02-PRODUCTION-UI-COLD-PATH-2026-08-17.md`](docs/PERF-02-PRODUCTION-UI-COLD-PATH-2026-08-17.md).
- Backup Manager metadata-first record:
  [`docs/PERF-05-BACKUP-METADATA-FIRST-2026-08-21.md`](docs/PERF-05-BACKUP-METADATA-FIRST-2026-08-21.md).
- Historical improvement snapshot:
  [`docs/IMPROVEMENTS.md`](docs/IMPROVEMENTS.md). It is not the current
  remediation authority.

## Validation baseline

- Backend: `python -m pytest -p no:cacheprovider -q backend/tests`
- Backend lint: `ruff check backend`
- Frontend: `npm run lint`, `npx --no-install tsc --noEmit`,
  `npm run i18n:check`, `npm run build`
- Shell: `git ls-files -z '*.sh' | xargs -0r shellcheck -S error`

## Change boundaries

- Do not deploy, rotate external credentials, rewrite Git history or publish
  branches as part of a code change unless the operation is separately
  authorised and validated.
- Secrets must never be stored in tracked files, generated logs or systemd unit
  templates. Runtime secret values belong in host-managed root-only storage.
