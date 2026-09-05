# ADR-0002: Telegram identity and provisioning authority

## Context

The control plane already owns node connections and stable subscription tokens.
The Telegram integration must link a person to an existing or newly approved
customer without allowing Telegram metadata, a callback payload, or one remote
node to become the authority for the customer lifecycle.

## Decision

- `telegram_identities.telegram_user_id` is the only Telegram identity key.
  Telegram username, names, chat text and callback data are untrusted display
  metadata, never authorization input.
- `customers` is the local authority for approved service identity and lifecycle
  intent. Remote 3x-ui records are reconciled projections, not the source of
  access decisions.
- A bot-created remote client always uses `inbound_id=1` and
  `xtls-rprx-vision`. Per-node defaults are only traffic limit (`0` is
  unlimited), validity (`0` is unlimited) and initial enable state (`true`).
- `telegram_node_policies` is the single versioned policy source for both the
  panel `TG` control and Telegram administrator UI. A policy is independent of
  `nodes.enabled`; writes require both a valid enabled policy and a writable,
  compatible node.
- A customer may intentionally be on a subset of eligible nodes. Missing
  bindings on other eligible nodes mean `available_to_add`, never failure or
  drift.
- Admin approval of a new person is one SQLite transaction: it creates the
  canonical customer, changes the pending identity to `approved`, snapshots
  every currently eligible node policy, and creates one durable job with one
  attempt per node. It performs no remote I/O and creates no binding until a
  later worker has reconciled the remote client.
- The suggested customer email is derived from Telegram username, then display
  names, then a deterministic safe fallback. It is NFKC-normalized,
  transliterated, allowlisted and collision-checked. An administrator may
  replace it; the committed exact value becomes immutable remote `email`.
- Approval fails closed when no eligible local policy target exists. It must
  not label a person as ready merely because the administrator pressed approve.
- Linking an existing customer accepts its local `customer_id`, never a free
  email supplied by Telegram or an administrator. The customer must already
  have at least one exact confirmed local node binding; this link creates no
  provisioning job and does not mutate a remote node.
- Telegram update deduplication happens before abuse accounting. Only the 51st
  unique no-op action in a rolling ten-minute window auto-blocks an unapproved
  identity; the first 50 do not. Manual unblock resets the active window but
  leaves the audit trail intact.
- Each provisioning attempt also stores an absolute expiry timestamp before
  remote I/O. Reconciliation and retry cannot silently extend a limited
  customer's entitlement. The worker takes a recoverable SQLite job lease,
  reads the exact inbound first, and only writes when a verified empty result
  is available; read/add uncertainty becomes `ambiguous`, never a blind retry.
- The existing fleet dashboard reader is not a provisioning authority because
  it represents an unreachable node as an empty partial projection. A separate
  strict node read adapter fails closed on auth, transport and malformed API
  responses before the worker can attempt an add.
- Immediately before each write, the strict adapter re-reads `inbound_id=1`
  and requires an enabled VLESS inbound with TLS/Reality flow capability. A
  later policy toggle does not mutate a job snapshot, but an incompatible or
  unreadable current inbound still blocks that attempt safely.
- An administrator may queue `retry` or `reconcile` for a failed/partial job
  only with the latest job version and an idempotency key. The HTTP command
  does not perform remote I/O; it resets only non-succeeded attempts and the
  worker still begins its next execution with the same strict remote read.
- Provisioning and destructive lifecycle work run through durable jobs and
  exact binding identifiers. They reconcile before retry and never perform
  blind lookup or automatic destructive rollback.

## Consequences

The integration can be introduced behind a disabled feature flag while old
subscription URLs keep their current contract. Suspend changes remote enable
state without deleting the binding; delete is a later, explicit saga. Token
rotation remains a separate operation and cannot reset persisted usage. Admin
queue commands use optimistic row versions and idempotency receipts, so a
second browser tab either replays the same result or receives a conflict.

## Rollback

Set `TELEGRAM_BOT_ENABLED=false`, stop the adapter/worker and roll back only
the application release. Additive tables and already-created remote records are
preserved; database restore requires a separately approved recovery procedure.
