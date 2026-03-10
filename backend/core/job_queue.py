"""Background job queue with cron scheduling, retry and timeout support.

Usage::

    queue = JobQueue()

    # Register a recurring job
    @queue.schedule(cron="*/5 * * * *")
    async def collect_stats():
        ...

    # Register a one-shot task with retry
    @queue.task(retry=3, timeout=30)
    async def send_notification(user_id: int):
        ...

    await queue.start()
    # Later…
    await queue.stop()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobRecord:
    """Runtime record for a scheduled or one-shot job."""

    name: str
    status: JobStatus = JobStatus.PENDING
    last_run: Optional[float] = None
    last_error: Optional[str] = None
    run_count: int = 0
    error_count: int = 0


@dataclass
class _ScheduledJob:
    func: Callable[[], Coroutine]
    cron: str
    name: str
    retry: int = 0
    timeout: Optional[float] = None
    _interval_sec: float = field(init=False, default=60.0)
    _task: Optional[asyncio.Task] = field(init=False, default=None)


class JobQueue:
    """Lightweight background job scheduler.

    Supports:
    * Cron-like scheduling (limited ``*/n`` and ``n`` patterns for each field).
    * Retry with exponential back-off.
    * Per-job timeout.
    * Runtime status reporting via :meth:`status`.
    """

    def __init__(self) -> None:
        self._scheduled: List[_ScheduledJob] = []
        self._records: Dict[str, JobRecord] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Decorators / registration API
    # ------------------------------------------------------------------

    def schedule(
        self,
        cron: str,
        *,
        name: Optional[str] = None,
        retry: int = 0,
        timeout: Optional[float] = None,
    ) -> Callable:
        """Decorator – register an async function as a recurring job.

        Args:
            cron: Simplified cron expression.  Supported forms:
                ``"*/N * * * *"`` (every N minutes) or ``"@hourly"`` etc.
            name: Human-readable job name (defaults to function name).
            retry: Number of retry attempts on failure.
            timeout: Per-run timeout in seconds.
        """

        def decorator(func: Callable) -> Callable:
            job_name = name or func.__qualname__
            job = _ScheduledJob(
                func=func,
                cron=cron,
                name=job_name,
                retry=retry,
                timeout=timeout,
            )
            job._interval_sec = _cron_to_interval(cron)
            self._scheduled.append(job)
            self._records[job_name] = JobRecord(name=job_name)
            logger.debug("JobQueue: scheduled '%s' (cron=%s)", job_name, cron)
            return func

        return decorator

    def task(
        self,
        *,
        retry: int = 0,
        timeout: Optional[float] = None,
        name: Optional[str] = None,
    ) -> Callable:
        """Decorator – mark an async function as a one-shot task.

        The decorated function gains an ``.enqueue()`` method that can be
        called to submit it for immediate execution.
        """

        def decorator(func: Callable) -> Callable:
            task_name = name or func.__qualname__
            self._records.setdefault(task_name, JobRecord(name=task_name))

            async def _run(*args: Any, **kwargs: Any) -> Any:
                return await self._run_with_retry(
                    lambda: func(*args, **kwargs),
                    task_name,
                    retry=retry,
                    timeout=timeout,
                )

            func.enqueue = lambda *a, **kw: asyncio.ensure_future(_run(*a, **kw))
            return func

        return decorator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the scheduler loop for all registered jobs."""
        if self._running:
            return
        self._running = True
        for job in self._scheduled:
            task = asyncio.create_task(self._job_loop(job))
            job._task = task
            self._tasks.append(task)
        logger.info(
            "JobQueue: started with %d scheduled jobs", len(self._scheduled)
        )

    async def stop(self) -> None:
        """Cancel all running job loops."""
        self._running = False
        for job in self._scheduled:
            if job._task and not job._task.done():
                job._task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("JobQueue: stopped")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> List[dict]:
        """Return status records for all known jobs."""
        return [
            {
                "name": r.name,
                "status": r.status.value,
                "last_run": r.last_run,
                "last_error": r.last_error,
                "run_count": r.run_count,
                "error_count": r.error_count,
            }
            for r in self._records.values()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _job_loop(self, job: _ScheduledJob) -> None:
        """Run *job* repeatedly according to its interval."""
        record = self._records.setdefault(job.name, JobRecord(name=job.name))
        while self._running:
            await asyncio.sleep(job._interval_sec)
            if not self._running:
                break
            await self._run_with_retry(job.func, job.name, retry=job.retry, timeout=job.timeout)

    async def _run_with_retry(
        self,
        func: Callable[[], Coroutine],
        name: str,
        *,
        retry: int,
        timeout: Optional[float],
    ) -> Any:
        record = self._records.setdefault(name, JobRecord(name=name))
        attempts = retry + 1
        delay = 1.0

        for attempt in range(1, attempts + 1):
            record.status = JobStatus.RUNNING
            try:
                coro = func()
                if timeout:
                    result = await asyncio.wait_for(coro, timeout=timeout)
                else:
                    result = await coro
                record.status = JobStatus.COMPLETED
                record.last_run = time.time()
                record.run_count += 1
                return result
            except asyncio.CancelledError:
                record.status = JobStatus.CANCELLED
                raise
            except Exception as exc:
                record.error_count += 1
                record.last_error = str(exc)
                if attempt < attempts:
                    logger.warning(
                        "JobQueue: '%s' failed (attempt %d/%d): %s – retrying in %.1fs",
                        name,
                        attempt,
                        attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)  # exponential back-off, cap 60s
                else:
                    logger.error(
                        "JobQueue: '%s' failed after %d attempts: %s",
                        name,
                        attempts,
                        exc,
                    )
                    record.status = JobStatus.FAILED
        return None


# ---------------------------------------------------------------------------
# Cron → interval helper
# ---------------------------------------------------------------------------

def _cron_to_interval(cron: str) -> float:
    """Convert a simplified cron expression to an interval in seconds.

    Supported forms:
    * ``*/N * * * *``  – every N minutes
    * ``0 */N * * *``  – every N hours
    * ``@hourly``      – every 60 minutes
    * ``@daily``       – every 24 hours
    * ``@weekly``      – every 7 days
    * Plain integer    – treated as seconds (non-standard, for testing)

    Anything unrecognised defaults to 60 seconds.
    """
    specials = {
        "@hourly": 3600.0,
        "@daily": 86400.0,
        "@weekly": 604800.0,
        "@monthly": 2592000.0,
        "@yearly": 31536000.0,
        "@annually": 31536000.0,
    }
    cron = cron.strip()
    if cron in specials:
        return specials[cron]

    # Plain integer seconds (convenience form for testing)
    if re.fullmatch(r"\d+", cron):
        return float(cron)

    parts = cron.split()
    if len(parts) != 5:
        logger.warning("JobQueue: unrecognised cron '%s', defaulting to 60s", cron)
        return 60.0

    minute, hour = parts[0], parts[1]

    # */N in minute field
    m = re.fullmatch(r"\*/(\d+)", minute)
    if m and hour == "*":
        return float(m.group(1)) * 60.0

    # */N in hour field
    m = re.fullmatch(r"\*/(\d+)", hour)
    if m and minute in ("0", "*/60"):
        return float(m.group(1)) * 3600.0

    return 60.0
