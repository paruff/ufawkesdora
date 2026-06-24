"""Unit tests for ingestion/api/queue.py.

All tests use MagicMock to mock asyncpg — no real database required.
Covers the entire public API: pool management, enqueue, dequeue, status updates.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingestion.api.queue import (
    close_pool,
    dequeue_next,
    enqueue_event,
    enqueue_events,
    get_pool,
    get_queue_depth,
    mark_done,
    mark_failed,
    write_raw_event,
)


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset the module-level _pool between tests."""
    import ingestion.api.queue as q

    q._pool = None
    yield
    q._pool = None


def _mock_async_context_manager(return_value):
    """Build an async context manager mock whose __aenter__ returns return_value."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ── Pool management ─────────────────────────────────────────────────────────


class TestGetPool:
    """Cover get_pool() — pool creation and reuse."""

    @pytest.mark.asyncio
    async def test_get_pool_creates_new_pool(self):
        """Lines 22-31: _pool is None, creates a new pool."""
        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False

        with patch(
            "ingestion.api.queue.asyncpg.create_pool", AsyncMock(return_value=mock_pool)
        ) as mock_create:
            pool = await get_pool(dsn="postgresql://localhost/test")

        assert pool is mock_pool
        mock_create.assert_awaited_once_with(
            "postgresql://localhost/test",
            min_size=2,
            max_size=10,
        )

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing(self):
        """Line 22: _pool exists and is not closing, reuse it."""
        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False

        import ingestion.api.queue as q

        q._pool = mock_pool

        with patch("ingestion.api.queue.asyncpg.create_pool") as mock_create:
            pool = await get_pool()

        assert pool is mock_pool
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_pool_recreates_when_closing(self):
        """Line 22: _pool exists but is closing, create a new one."""
        old_pool = MagicMock()
        old_pool.is_closing.return_value = True

        new_pool = MagicMock()
        new_pool.is_closing.return_value = False

        import ingestion.api.queue as q

        q._pool = old_pool

        with patch(
            "ingestion.api.queue.asyncpg.create_pool", AsyncMock(return_value=new_pool)
        ) as mock_create:
            pool = await get_pool(dsn="postgresql://localhost/test")

        assert pool is new_pool
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_pool_defaults_to_env(self):
        """Lines 23-26: when dsn is None, read DATABASE_URL from env."""
        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False

        with (
            patch("ingestion.api.queue.asyncpg.create_pool", AsyncMock(return_value=mock_pool)),
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://env/test"}),
        ):
            pool = await get_pool()

        assert pool is mock_pool


class TestClosePool:
    """Cover close_pool()."""

    @pytest.mark.asyncio
    async def test_close_pool_closes_existing(self):
        """Lines 38-40: pool exists and is NOT closing, close it."""
        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.close = AsyncMock()

        import ingestion.api.queue as q

        q._pool = mock_pool

        await close_pool()

        mock_pool.close.assert_awaited_once()
        assert q._pool is None

    @pytest.mark.asyncio
    async def test_close_pool_none(self):
        """Lines 38-40: _pool is None, no-op."""
        await close_pool()  # should not raise


# ── Enqueue operations ────────────────────────────────────────────────────


class TestEnqueueEvent:
    """Cover enqueue_event()."""

    @pytest.mark.asyncio
    async def test_enqueue_event_returns_id(self):
        """Lines 55-70: single event insertion returns the new id."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 42})

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        event_id = await enqueue_event(
            {"event_type": "deployment", "repo": "myapp", "status": "success"}
        )

        assert event_id == 42
        mock_conn.fetchrow.assert_awaited_once()


class TestEnqueueEvents:
    """Cover enqueue_events()."""

    @pytest.mark.asyncio
    async def test_enqueue_events_returns_ids(self):
        """Lines 82-101: batch insertion returns list of ids."""
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, {"id": 2}])
        mock_transaction_cm = MagicMock()
        mock_transaction_cm.__aenter__ = AsyncMock(return_value=None)
        mock_transaction_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_transaction_cm)

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        ids = await enqueue_events(
            [
                {"event_type": "deployment", "repo": "myapp"},
                {"event_type": "incident", "repo": "myapp"},
            ]
        )

        assert ids == [1, 2]


# ── Queue depth ───────────────────────────────────────────────────────────


class TestGetQueueDepth:
    """Cover get_queue_depth()."""

    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_count(self):
        """Lines 106-111: returns the count of pending events."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"cnt": 5})

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        count = await get_queue_depth()

        assert count == 5


# ── Dequeue ───────────────────────────────────────────────────────────────


class TestDequeueNext:
    """Cover dequeue_next()."""

    @pytest.mark.asyncio
    async def test_dequeue_next_returns_event(self):
        """Lines 124-149: dequeues and returns the next pending event."""
        mock_row = {
            "id": 1,
            "payload": '{"event_type": "deployment"}',
            "event_type": "deployment",
            "source": "myapp",
            "attempts": 0,
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        event = await dequeue_next()

        assert event == {
            "id": 1,
            "payload": {"event_type": "deployment"},
            "event_type": "deployment",
            "source": "myapp",
            "attempts": 0,
        }

    @pytest.mark.asyncio
    async def test_dequeue_next_empty(self):
        """Lines 141-142: no pending events returns None."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        event = await dequeue_next()

        assert event is None


# ── Status updates ────────────────────────────────────────────────────────


class TestMarkDone:
    """Cover mark_done()."""

    @pytest.mark.asyncio
    async def test_mark_done_executes_update(self):
        """Lines 154-163: marks event as done."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        await mark_done(42)

        mock_conn.execute.assert_awaited_once()


class TestMarkFailed:
    """Cover mark_failed()."""

    @pytest.mark.asyncio
    async def test_mark_failed_executes_update(self):
        """Lines 172-190: increments attempts and updates status."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        await mark_failed(42, max_attempts=3)

        mock_conn.execute.assert_awaited_once()


class TestWriteRawEvent:
    """Cover write_raw_event()."""

    @pytest.mark.asyncio
    async def test_write_raw_event_executes_insert(self):
        """Lines 202-217: inserts into raw_events."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.is_closing.return_value = False
        mock_pool.acquire.return_value = _mock_async_context_manager(mock_conn)

        import ingestion.api.queue as q

        q._pool = mock_pool

        await write_raw_event(
            event_queue_id=1,
            event_type="deployment",
            source="myapp",
            outcome="success",
            payload={"status": "success"},
            duration_seconds=30,
        )

        mock_conn.execute.assert_awaited_once()
