"""Async queue operations for the event_queue table.

Uses asyncpg for connection pooling and the SKIP LOCKED pattern for
worker-safe dequeueing.
"""

import json
from typing import Any

import asyncpg


# ── Connection pool ────────────────────────────────────────────────────────────

_pool: asyncpg.Pool | None = None


async def get_pool(dsn: str | None = None, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Get or create the asyncpg connection pool.

    If ``dsn`` is ``None``, uses the ``DATABASE_URL`` environment variable.
    """
    global _pool
    if _pool is None or _pool.is_closing():
        if dsn is None:
            import os
            dsn = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dora_metrics")
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
        )
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool and not _pool.is_closing():
        await _pool.close()
    _pool = None


# ── Queue operations ───────────────────────────────────────────────────────────


async def enqueue_event(payload: dict) -> int:
    """Insert an event into the event_queue and return its id.

    Args:
        payload: The validated event payload (dict).

    Returns:
        The id of the newly inserted event_queue row.
    """
    pool = await get_pool()
    event_type: str = payload.get("event_type", "unknown")
    source: str = payload.get("repo", "unknown")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO event_queue (event_type, source, payload)
            VALUES ($1, $2, $3::jsonb)
            RETURNING id
            """,
            event_type,
            source,
            json.dumps(payload),
        )
        return row["id"]


async def enqueue_events(payloads: list[dict]) -> list[int]:
    """Insert multiple events in a single transaction.

    Args:
        payloads: List of validated event payloads.

    Returns:
        List of ids for the newly inserted rows.
    """
    pool = await get_pool()
    ids: list[int] = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for payload in payloads:
                event_type: str = payload.get("event_type", "unknown")
                source: str = payload.get("repo", "unknown")
                row = await conn.fetchrow(
                    """
                    INSERT INTO event_queue (event_type, source, payload)
                    VALUES ($1, $2, $3::jsonb)
                    RETURNING id
                    """,
                    event_type,
                    source,
                    json.dumps(payload),
                )
                ids.append(row["id"])

    return ids


async def get_queue_depth() -> int:
    """Return the number of pending (not yet processed) events."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM event_queue WHERE status = 'pending'"
        )
        return row["cnt"]


# ── Worker operations ──────────────────────────────────────────────────────────


async def dequeue_next() -> dict | None:
    """Claim the next pending event using SKIP LOCKED.

    Returns:
        A dict with ``id``, ``payload``, ``event_type``, ``source``, and
        ``attempts`` keys, or ``None`` if no pending events exist.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE event_queue
            SET status = 'processing'
            WHERE id = (
                SELECT id
                FROM event_queue
                WHERE status = 'pending'
                ORDER BY received_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, payload, event_type, source, attempts
            """
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "payload": json.loads(row["payload"]),
            "event_type": row["event_type"],
            "source": row["source"],
            "attempts": row["attempts"],
        }


async def mark_done(event_id: int):
    """Mark an event as successfully processed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE event_queue
            SET status = 'done', processed_at = NOW()
            WHERE id = $1
            """,
            event_id,
        )


async def mark_failed(event_id: int, max_attempts: int = 3):
    """Increment attempts and mark as 'error' if max_attempts reached.

    If the event still has attempts remaining, it is set back to 'pending'
    so another worker can retry it.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE event_queue
            SET attempts = attempts + 1,
                status = CASE
                    WHEN attempts + 1 >= $2 THEN 'error'
                    ELSE 'pending'
                END,
                processed_at = CASE
                    WHEN attempts + 1 >= $2 THEN NOW()
                    ELSE processed_at
                END
            WHERE id = $1
            """,
            event_id,
            max_attempts,
        )


async def write_raw_event(
    event_queue_id: int,
    event_type: str,
    source: str,
    outcome: str,
    payload: dict,
    duration_seconds: int | None = None,
):
    """Write a processed event to the raw_events table."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO raw_events
                (event_queue_id, event_type, source, outcome,
                 duration_seconds, metadata, recorded_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            """,
            event_queue_id,
            event_type,
            source,
            outcome,
            duration_seconds,
            json.dumps(payload),
        )
