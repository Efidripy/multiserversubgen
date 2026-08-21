# PERF-05 — Backup Manager: metadata-first cold path

**Status:** implemented locally; production rollout pending
**Scope:** Backup Manager render path and its truthful API contract.
**Out of scope:** SQLite schema/data, node configuration, 3x-ui mutation, deployment.

## Observed bottleneck

The former initial render called `GET /api/v1/backup/all?format=json`. That
route contacts every configured node, retrieves each full database and embeds
all of their base64 bodies in the response. It is an export operation, not a
backup inventory API. The observed cold path was approximately 17.4 seconds.

## Decision

Opening Backup Manager now requests only `GET /api/v1/nodes`. The page shows
configured nodes and marks backup transfer as on-demand; it does not keep
database bodies in browser memory.

Full database transfer remains available only after an explicit operator
action:

- `GET /api/v1/backup/node/{node_id}` for one binary download;
- `GET /api/v1/backup/all` for the all-node ZIP;
- node Telegram delivery;
- file-based import to a selected node.

`GET /api/v1/backup/all?format=json` is retained as a legacy management
contract for API clients, but is forbidden in the UI cold path.

## Local evidence

- `frontend/tests/backup-manager.test.tsx` proves mount loads metadata only and
  a per-node export starts only after the download action.
- `frontend/tests/performance-regressions.test.ts` rejects a return of the
  legacy full-body request to the component.
- Frontend lint, typecheck, i18n check, tests and production build are required
  before integration; backend suite and lint guard the unchanged routes.

## Production acceptance and rollback

This change requires a separately authorised rollback-first rollout. Before
release create and verify the normal deployment artifact and SQLite integrity
receipt, without schema or data mutation. In an authenticated browser
waterfall verify that Backup Manager's initial navigation requests node
metadata only, a per-node action produces exactly one node-backup request, and
the all-node action alone requests the ZIP endpoint. Check for console errors
and retain the pre-release artifact as rollback evidence.
