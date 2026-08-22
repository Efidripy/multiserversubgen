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
- `docs/` — tracked user/operator documentation and the enforced composition-root ADR.

## Documentation boundary

- Public user/operator documentation: [`docs/README.md`](docs/README.md).
- Local working queue and completion log: ignored `.local_project_docs/TODO.md`
  and `.local_project_docs/DONE.md` in the maintained workspace.
- Historical audit, sprint, rollout, performance and design records: ignored
  `.local_project_docs/archive/`. They are not expected in a clean Git clone
  and must be revalidated before being reused as a source of truth.

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
