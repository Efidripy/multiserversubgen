# Telegram bot: staging runbook

## Scope and preconditions

This runbook enables only a staging bot against explicitly selected staging
nodes. It is not authority to deploy production, register a production
webhook, or perform real client writes outside that staging scope.

1. Rotate the bot token that was disclosed outside the runtime secret store.
   Store the replacement only in the staging secret provider; do not put it in
   Git, shell history, `.env` files or tickets.
2. Create a unique high-entropy webhook path suffix and webhook secret in the
   same secret provider.
3. Set `TELEGRAM_BOT_ENABLED=true`, `TELEGRAM_MODE=webhook`,
   `TELEGRAM_PRIMARY_ADMIN_ID`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_PATH_SUFFIX` and an HTTPS-only
   `TELEGRAM_PUBLIC_BASE_URL` on staging.
4. Keep both workers disabled initially:
   `TELEGRAM_PROVISIONING_WORKER_ENABLED=false` and
   `TELEGRAM_OUTBOX_WORKER_ENABLED=false`.
5. Verify the staging database backup and confirm that every intended staging
   node is enabled, non-read-only and has a compatible enabled VLESS
   `inbound_id=1` with flow capability.

## Smoke without remote writes

1. Restart only the staging application and confirm its health endpoint.
2. Send a signed test update to the secret webhook path. A wrong path must
   return `404`; a wrong `X-Telegram-Bot-Api-Secret-Token` must return `403`.
3. From a non-admin test account use `/start`, submit one optional
   introduction, and verify there is one pending application and one durable
   outbox event.
4. From the exact numeric primary admin account use `/admin`; verify that an
   untrusted username cannot expose admin controls.
5. Enable a selected staging node through the panel or `/admin`. Verify the
   policy cannot turn on if inbound `1` is not compatible.

## Notification delivery smoke

1. Set `TELEGRAM_OUTBOX_WORKER_ENABLED=true`; leave provisioning disabled.
2. Restart staging and verify an existing queued test event changes to `sent`.
3. Simulate a non-actionable test event only in staging and verify it becomes
   `dead_letter`, with no secret or URL stored in `last_error_code`.
4. Disable the outbox worker again if customer notification rollout is not yet
   approved.

## Remote-write smoke

Remote writes need a separate approval. Only then set both
`TELEGRAM_PROVISIONING_WORKER_ENABLED=true` and
`TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES=true` on staging.

1. Approve one test account on one selected TG-enabled staging node.
2. Verify the worker performs a strict read, creates only one client on
   inbound `1`, and uses `xtls-rprx-vision`.
3. Confirm the local binding contains the exact remote client id and sub id.
4. Test user token rotation, per-node pause/resume, global suspend/resume and
   delete. For each operation verify the remote state with a fresh read.
5. Record the smoke receipt, disable remote writes, and retain the staging
   database/worker logs according to the security policy.

## Rollback

Disable `TELEGRAM_BOT_ENABLED`, then disable both worker flags and restart the
staging application. Do not delete remote clients or SQLite records as a
rollback shortcut. Remove the webhook only through the approved operational
path after preserving pending-update intent.
