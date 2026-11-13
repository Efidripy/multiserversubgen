"""Lifespan-managed periodic Telegram drift scans."""

from core.lifecycle_work import LifecycleWorkAdmissionClosed


async def run_drift_worker(worker_tracker, scanner, interval_sec, logger):
    if not interval_sec or not await worker_tracker.wait_or_stop(60):
        return
    while worker_tracker.accepting:
        try:
            result = await worker_tracker.run("telegram.drift.scan", scanner.scan_if_idle)
            if result is not None:
                scan_result, new_findings = result
                if scan_result.unavailable_node_ids:
                    logger.warning("Telegram drift scan skipped unavailable nodes")
                else:
                    logger.info(
                        "Telegram drift scan completed: nodes=%d findings=%d",
                        len(scan_result.scanned_node_ids), new_findings,
                    )
        except LifecycleWorkAdmissionClosed:
            return
        except Exception:
            logger.warning("Telegram drift scan failed")
        if not await worker_tracker.wait_or_stop(interval_sec):
            return
