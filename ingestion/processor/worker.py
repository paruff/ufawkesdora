"""Background worker that consumes events from the event_queue.

Dequeues pending events using the SKIP LOCKED pattern, processes them,
and writes results to the raw_events hypertable.

Can be run as a standalone process or as a background task.
"""

import asyncio
import logging
import os
from collections.abc import Callable

from ingestion.api.queue import (
    close_pool,
    dequeue_next,
    get_pool,
    mark_done,
    mark_failed,
    write_raw_event,
)

logger = logging.getLogger(__name__)

# Default poll interval when queue is empty (seconds)
DEFAULT_POLL_INTERVAL = 1.0

# Maximum attempts before marking as failed
MAX_ATTEMPTS = 3


# ── Event processing ───────────────────────────────────────────────────────────


def _extract_outcome(payload: dict) -> str:
    """Map event status to raw_events outcome.

    Handles different event types:
    - deployment: success→success, failed→failure, rollback→rollback
    - incident: opened→unknown, resolved→success
    - pr: merged→success, closed→unknown, opened→unknown
    - rework: always→success (rework is a deployment type)
    """
    event_type = payload.get("event_type", "")
    status = payload.get("status", "")

    if event_type == "deployment":
        mapping = {"success": "success", "failed": "failure", "rollback": "rollback"}
        return mapping.get(status, "unknown")
    elif event_type == "incident":
        return "success" if status == "resolved" else "unknown"
    elif event_type == "pr":
        return "success" if status == "merged" else "unknown"
    elif event_type == "rework":
        return "success"
    return "unknown"


def _extract_duration(payload: dict) -> int | None:
    """Extract duration_seconds from an event payload if available."""
    return payload.get("deploy_duration_seconds")


# ── Processor callback ─────────────────────────────────────────────────────────


async def process_event(event: dict) -> bool:
    """Process a single dequeued event.

    Args:
        event: Dict with keys ``id``, ``payload``, ``event_type``, ``source``, ``attempts``.

    Returns:
        True if processing succeeded, False otherwise.
    """
    try:
        payload = event["payload"]
        outcome = _extract_outcome(payload)
        duration = _extract_duration(payload)

        await write_raw_event(
            event_queue_id=event["id"],
            event_type=event["event_type"],
            source=event["source"],
            outcome=outcome,
            payload=payload,
            duration_seconds=duration,
        )

        await mark_done(event["id"])
        logger.info("Processed event %d (%s)", event["id"], event["event_type"])
        return True

    except Exception:
        logger.exception("Failed to process event %d", event["id"])
        await mark_failed(event["id"], max_attempts=MAX_ATTEMPTS)
        return False


# ── Main loop ──────────────────────────────────────────────────────────────────


async def run_worker_loop(
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    on_event: Callable | None = None,
    shutdown_event: asyncio.Event | None = None,
):
    """Run the worker dequeue loop.

    Args:
        poll_interval: Seconds to wait between polls when queue is empty.
        on_event: Optional async callback invoked with the event dict after
            processing completes. Signature: ``callable(event, success: bool)``.
        shutdown_event: Optional event that signals the loop to stop.
    """
    logger.info("Worker starting (poll_interval=%.1fs)", poll_interval)

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("Worker shutting down")
            break

        try:
            event = await dequeue_next()
        except Exception:
            logger.exception("Error during dequeue, retrying")
            await asyncio.sleep(poll_interval)
            continue

        if event is None:
            await asyncio.sleep(poll_interval)
            continue

        success = await process_event(event)

        if on_event:
            await on_event(event, success)


# ── CLI entrypoint ─────────────────────────────────────────────────────────────


def main():
    """CLI entrypoint for standalone worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def _run():
        # Ensure pool is initialized
        dsn = os.environ.get("DATABASE_URL")
        await get_pool(dsn)
        try:
            await run_worker_loop()
        finally:
            await close_pool()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
