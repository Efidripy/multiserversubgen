"""Activation worker for cancellable Telegram lifecycle schedules.

Schedules are deliberately not remote jobs.  At the grace deadline this worker
only queues the existing immutable lifecycle operation.  The lifecycle worker
remains the sole component allowed to contact or mutate a node.
"""

from __future__ import annotations

from dataclasses import dataclass
from services.telegram_registry import (
    LifecycleUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)


@dataclass(frozen=True)
class ScheduleRunResult:
    processed: bool
    schedule_id: int | None = None
    outcome: str | None = None


class TelegramScheduleWorker:
    """Claim one due schedule and fail closed if its preview is no longer valid."""

    def __init__(self, *, registry: TelegramRegistry, worker_id: str, now=None) -> None:
        self._registry = registry
        self._worker_id = worker_id
        self._now = now

    def run_once(self) -> ScheduleRunResult:
        claimed = self._registry.claim_due_lifecycle_schedule(
            worker_id=self._worker_id,
            now=self._now() if self._now is not None else None,
        )
        if claimed is None:
            return ScheduleRunResult(processed=False)
        try:
            result = self._registry.queue_customer_operation(
                customer_id=claimed.customer_id,
                operation_type=claimed.operation_type,
                expected_customer_version=claimed.expected_customer_version,
                target_snapshot_digest=claimed.target_snapshot_digest,
                idempotency_key=f"scheduled:{claimed.schedule_id}",
                created_by=f"schedule:{claimed.schedule_id}",
            )
        except (VersionConflictError, LifecycleUnavailableError):
            self._registry.complete_lifecycle_schedule(
                schedule_id=claimed.schedule_id, operation_id=None, outcome="stale"
            )
            return ScheduleRunResult(True, claimed.schedule_id, "stale")
        except TelegramRegistryError:
            self._registry.complete_lifecycle_schedule(
                schedule_id=claimed.schedule_id, operation_id=None, outcome="failed"
            )
            return ScheduleRunResult(True, claimed.schedule_id, "failed")
        self._registry.complete_lifecycle_schedule(
            schedule_id=claimed.schedule_id, operation_id=result.operation_id, outcome="queued"
        )
        return ScheduleRunResult(True, claimed.schedule_id, "queued")
