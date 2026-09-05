# Telegram bot: безопасность, конфигурация и rollout

## Граница первого rollout

По умолчанию бот выключен. Включение допускается только на staging после
отдельно проверенного нового bot token и тестовых нод. Production, webhook,
BotFather и реальные remote clients этот репозиторный срез не меняет.

## Runtime configuration

| Variable | Contract |
| --- | --- |
| `TELEGRAM_BOT_ENABLED` | `false` by default. If `true`, missing mandatory variables abort startup. |
| `TELEGRAM_BOT_TOKEN` | Root-owned runtime secret. Never put it in Git, docs, `.env.example`, logs or audit. Rotate any token disclosed outside the runtime secret store before first launch. |
| `TELEGRAM_PRIMARY_ADMIN_ID` | Positive signed 64-bit integer. Authorization uses only the exact numeric Telegram `from.id`. |
| `TELEGRAM_MODE` | Only `webhook` is supported when the feature is enabled; polling is rejected until separately implemented. |
| `TELEGRAM_WEBHOOK_SECRET` | Exact value required in `X-Telegram-Bot-Api-Secret-Token`; an absent or incorrect value is rejected. |
| `TELEGRAM_WEBHOOK_PATH_SUFFIX` | High-entropy path component; it is compared exactly and never logged. |
| `TELEGRAM_PUBLIC_BASE_URL` | Public HTTPS origin used for controlled webhook registration; no HTTP or implicit local fallback. |
| `TELEGRAM_PROVISIONING_WORKER_ENABLED` | `false` by default. Starts the durable job worker only when remote writes are separately permitted. |
| `TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES` | Separate explicit interlock. The application fails startup if the worker is requested without this value set to `true`. |
| `TELEGRAM_PROVISIONING_WORKER_INTERVAL_SEC` | Idle poll interval, 1–300 seconds; default `5`. |
| `TELEGRAM_OUTBOX_WORKER_ENABLED` | `false` by default. Enables only delivery of already persisted Telegram notifications; it does not permit remote node writes. |
| `TELEGRAM_OUTBOX_WORKER_INTERVAL_SEC` | Idle poll interval for notification delivery, 1–300 seconds; default `5`. |

The adapter validates every required setting fail-closed at startup and has no
implicit development fallback.

Enabling the worker is a staging operation, not a deployment instruction. It
requires a separately approved staging target, fresh node compatibility proof,
and a smoke receipt before the same interlocks may be considered for production.

Notification delivery is separately opt-in. The outbox leases one event at a
time, records transient delivery failures with bounded retry/backoff and moves
malformed or exhausted events to `dead_letter`. Delivery is at-least-once:
after a transport timeout the Bot API outcome is unknowable, so a later retry
may duplicate a notification but never repeats a customer or node mutation.
Approved users can disable background delivery in the bot settings. This only
cancels future non-interactive outbox notifications; it never suppresses a
reply to the user's own command or alters access, audit, lifecycle or node
state.

## Threat model and controls

| Threat | Required control |
| --- | --- |
| Forged username, callback or chat text | Trust exact `from.id` only after Telegram transport validation; resolve callback state server-side. |
| Bot token disclosure | Runtime-only secret, redaction, pre-launch rotation, no token in events/audit/frontend. |
| Callback replay / update duplication | Persist `update_id`, idempotency keys and optimistic row versions before mutations. |
| Registration spam | One active application, per-user throttling, durable no-op counter and auto-block on the 51st unique no-op in ten minutes. |
| Unsafe node write | Node policy plus `nodes.enabled`, `read_only`, inbound and flow checks; durable target snapshot and read-after-write reconcile. |
| Accidental lifecycle loss | Preview, exact binding IDs, append-only audit, retry/reconcile; no blind delete or automatic destructive rollback. |
| User privacy leak | Neutral unapproved onboarding; do not reveal node inventory, subscription URLs, internal errors or technical service terms before approval. |

## Data retention

- Full raw Telegram updates are not stored. `telegram_updates` keeps only the
  update id, typed status and a digest needed for dedupe/replay diagnosis.
- Pending applications are retained for 30 days; rejected application metadata
  for 90 days. A future retention worker must purge or compact them without
  deleting an active customer, binding or audit chain.
- Introduction and future support/appeal text are untrusted plain text and are
  never copied into audit, metrics or application logs. Their retention and
  deletion must be explicit domain jobs.
- Durable audit stores identifiers, actor class, timestamps and digests—not bot
  tokens, subscription URLs, remote credentials or raw message bodies.

## Operational rollback

1. Disable `TELEGRAM_BOT_ENABLED` and stop only Telegram adapter/worker.
2. Remove webhook using a controlled operations command without dropping pending updates unless emergency response explicitly requires it.
3. Roll back application code while retaining additive SQLite tables.
4. Do not delete remote clients as a rollback action.
5. Restore SQLite only after an approved backup/recovery decision and integrity proof.
