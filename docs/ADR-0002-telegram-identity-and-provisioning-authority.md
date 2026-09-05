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
- Provisioning and destructive lifecycle work run through durable jobs and
  exact binding identifiers. They reconcile before retry and never perform
  blind lookup or automatic destructive rollback.

## Consequences

The integration can be introduced behind a disabled feature flag while old
subscription URLs keep their current contract. Suspend changes remote enable
state without deleting the binding; delete is a later, explicit saga. Token
rotation remains a separate operation and cannot reset persisted usage.

## Rollback

Set `TELEGRAM_BOT_ENABLED=false`, stop the adapter/worker and roll back only
the application release. Additive tables and already-created remote records are
preserved; database restore requires a separately approved recovery procedure.
