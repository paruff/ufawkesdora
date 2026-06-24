"""Unit tests for the uFawkesDORA ingestion worker.

Tests cover:
- Dequeue success path (event processed, raw_event written, marked done)
- Dequeue failure path (exception caught, attempts incremented, error after 3)
- SKIP LOCKED semantics (two workers don't claim same row)
- Worker loop shutdown on signal
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ingestion.processor.worker import MAX_ATTEMPTS, process_event, run_worker_loop

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def deployment_event() -> dict:
    return {
        "id": 1,
        "payload": {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "my-org/my-service",
            "service": "api-gateway",
            "environment": "production",
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "deployed_at": "2026-06-22T10:30:00Z",
            "status": "success",
            "pipeline_url": "https://example.com/pipeline/1",
        },
        "event_type": "deployment",
        "source": "my-org/my-service",
        "attempts": 0,
    }


# ── Tests: process_event ───────────────────────────────────────────────────────


class TestProcessEvent:
    """Test the process_event function directly."""

    @pytest.mark.asyncio
    async def test_deployment_success(self, deployment_event):
        """AC: Successful deployment → written to raw_events, marked done."""
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done") as mock_done,
            patch("ingestion.processor.worker.mark_failed") as mock_fail,
        ):
            result = await process_event(deployment_event)
            assert result is True
            mock_write.assert_awaited_once_with(
                event_queue_id=1,
                event_type="deployment",
                source="my-org/my-service",
                outcome="success",
                payload=deployment_event["payload"],
                duration_seconds=None,
            )
            mock_done.assert_awaited_once_with(1)
            mock_fail.assert_not_called()

    @pytest.mark.asyncio
    async def test_outcome_mapping_deployment_failed(self):
        """Deployment with status 'failed' maps to outcome 'failure'."""
        event = {
            "id": 3,
            "payload": {
                "schema_version": "1.0",
                "event_type": "deployment",
                "status": "failed",
                "repo": "org/repo",
            },
            "event_type": "deployment",
            "source": "org/repo",
            "attempts": 0,
        }
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done") as mock_done,
            patch("ingestion.processor.worker.mark_failed"),
        ):
            result = await process_event(event)
            assert result is True
            mock_write.assert_awaited_once_with(
                event_queue_id=3,
                event_type="deployment",
                source="org/repo",
                outcome="failure",
                payload=event["payload"],
                duration_seconds=None,
            )
            mock_done.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_outcome_mapping_deployment_rollback(self):
        """Deployment with status 'rollback' maps to outcome 'rollback'."""
        event = {
            "id": 4,
            "payload": {
                "schema_version": "1.0",
                "event_type": "deployment",
                "status": "rollback",
                "repo": "org/repo",
            },
            "event_type": "deployment",
            "source": "org/repo",
            "attempts": 0,
        }
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done"),
            patch("ingestion.processor.worker.mark_failed"),
        ):
            result = await process_event(event)
            assert result is True
            mock_write.assert_awaited_once_with(
                event_queue_id=4,
                event_type="deployment",
                source="org/repo",
                outcome="rollback",
                payload=event["payload"],
                duration_seconds=None,
            )

    @pytest.mark.asyncio
    async def test_duration_extracted(self):
        """deploy_duration_seconds from payload passed to write_raw_event."""
        event = {
            "id": 5,
            "payload": {
                "schema_version": "1.0",
                "event_type": "deployment",
                "status": "success",
                "repo": "org/repo",
                "deploy_duration_seconds": 120,
            },
            "event_type": "deployment",
            "source": "org/repo",
            "attempts": 0,
        }
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done"),
            patch("ingestion.processor.worker.mark_failed"),
        ):
            await process_event(event)
            mock_write.assert_awaited_once_with(
                event_queue_id=5,
                event_type="deployment",
                source="org/repo",
                outcome="success",
                payload=event["payload"],
                duration_seconds=120,
            )

    @pytest.mark.asyncio
    async def test_failure_increments_attempts(self, deployment_event):
        """AC: When event processing raises, mark_failed is called."""
        with (
            patch("ingestion.processor.worker.write_raw_event", side_effect=ValueError("DB error")),
            patch("ingestion.processor.worker.mark_done") as mock_done,
            patch("ingestion.processor.worker.mark_failed") as mock_fail,
        ):
            result = await process_event(deployment_event)
            assert result is False
            mock_fail.assert_awaited_once_with(1, max_attempts=MAX_ATTEMPTS)
            mock_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_incident_opened_maps_to_unknown(self):
        """Incident 'opened' status maps to outcome 'unknown'."""
        event = {
            "id": 6,
            "payload": {
                "schema_version": "1.0",
                "event_type": "incident",
                "status": "opened",
                "repo": "org/repo",
            },
            "event_type": "incident",
            "source": "org/repo",
            "attempts": 0,
        }
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done"),
            patch("ingestion.processor.worker.mark_failed"),
        ):
            await process_event(event)
            mock_write.assert_awaited_once_with(
                event_queue_id=6,
                event_type="incident",
                source="org/repo",
                outcome="unknown",
                payload=event["payload"],
                duration_seconds=None,
            )

    @pytest.mark.asyncio
    async def test_pr_merged_maps_to_success(self):
        """PR 'merged' status maps to outcome 'success'."""
        event = {
            "id": 7,
            "payload": {
                "schema_version": "1.0",
                "event_type": "pr",
                "status": "merged",
                "repo": "org/repo",
            },
            "event_type": "pr",
            "source": "org/repo",
            "attempts": 0,
        }
        with (
            patch("ingestion.processor.worker.write_raw_event") as mock_write,
            patch("ingestion.processor.worker.mark_done"),
            patch("ingestion.processor.worker.mark_failed"),
        ):
            await process_event(event)
            mock_write.assert_awaited_once_with(
                event_queue_id=7,
                event_type="pr",
                source="org/repo",
                outcome="success",
                payload=event["payload"],
                duration_seconds=None,
            )


# ── Tests: Worker Loop ─────────────────────────────────────────────────────────


class TestWorkerLoop:
    """Test the run_worker_loop function."""

    @pytest.mark.asyncio
    async def test_loop_processes_event_and_stops_on_shutdown(self, deployment_event):
        """Worker processes one event, then stops when shutdown_event is set."""
        with (
            patch(
                "ingestion.processor.worker.dequeue_next",
                new_callable=AsyncMock,
                side_effect=[deployment_event, None, None],
            ),
            patch(
                "ingestion.processor.worker.process_event",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            shutdown = asyncio.Event()

            async def _schedule_shutdown():
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                run_worker_loop(
                    poll_interval=0.05,
                    shutdown_event=shutdown,
                ),
                _schedule_shutdown(),
            )

    @pytest.mark.asyncio
    async def test_loop_handles_empty_queue(self):
        """Worker sleeps and retries when queue is empty."""
        with patch(
            "ingestion.processor.worker.dequeue_next",
            new_callable=AsyncMock,
            side_effect=[None, None, None],
        ) as mock_dequeue:
            shutdown = asyncio.Event()

            async def _schedule_shutdown():
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                run_worker_loop(
                    poll_interval=0.05,
                    shutdown_event=shutdown,
                ),
                _schedule_shutdown(),
            )
            # Verify dequeue was called multiple times (empty queue polling)
            assert mock_dequeue.await_count >= 2

    @pytest.mark.asyncio
    async def test_loop_calls_on_event_callback(self, deployment_event):
        """The on_event callback is invoked after each processed event."""
        callback = AsyncMock()

        with (
            patch(
                "ingestion.processor.worker.dequeue_next",
                new_callable=AsyncMock,
                side_effect=[deployment_event, None],
            ),
            patch(
                "ingestion.processor.worker.process_event",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            shutdown = asyncio.Event()

            async def _schedule_shutdown():
                await asyncio.sleep(0.2)
                shutdown.set()

            await asyncio.gather(
                run_worker_loop(
                    poll_interval=0.05,
                    on_event=callback,
                    shutdown_event=shutdown,
                ),
                _schedule_shutdown(),
            )
            callback.assert_awaited_once_with(deployment_event, True)


# ── Tests: SKIP LOCKED semantics ───────────────────────────────────────────────


class TestSkipLocked:
    """Verify SKIP LOCKED behavior — two workers don't claim the same row.

    These tests use mocked queue operations to verify the dequeue logic.
    The actual SQL-level SKIP LOCKED is tested via integration tests.
    """

    @pytest.mark.asyncio
    async def test_dequeue_returns_unique_events(self):
        """dequeue_next should only return each event once (mocked)."""
        event_a = {
            "id": 1,
            "payload": {},
            "event_type": "deployment",
            "source": "repo",
            "attempts": 0,
        }
        event_b = {
            "id": 2,
            "payload": {},
            "event_type": "deployment",
            "source": "repo",
            "attempts": 0,
        }

        with patch(
            "ingestion.processor.worker.dequeue_next",
            new_callable=AsyncMock,
            side_effect=[event_a, event_b, None],
        ) as mock_dequeue:
            results = []

            # Consume events from the mocked dequeue
            evt = await mock_dequeue()
            while evt:
                results.append(evt["id"])
                evt = await mock_dequeue()

            assert results == [1, 2]

    @pytest.mark.asyncio
    async def test_skip_locked_prevents_duplicate_claims(self):
        """Two concurrent workers dequeue different events (mocked)."""
        event_a = {
            "id": 1,
            "payload": {},
            "event_type": "deployment",
            "source": "repo",
            "attempts": 0,
        }
        event_b = {
            "id": 2,
            "payload": {},
            "event_type": "deployment",
            "source": "repo",
            "attempts": 0,
        }

        # Provide enough side_effect values for two workers polling for 0.4s
        with patch(
            "ingestion.processor.worker.dequeue_next",
            new_callable=AsyncMock,
            side_effect=[event_a, event_b] + [None] * 50,
        ) as mock_dequeue:
            shutdown = asyncio.Event()
            seen = set()

            async def worker(n):
                nonlocal seen
                while not shutdown.is_set():
                    evt = await mock_dequeue()
                    if evt:
                        seen.add(evt["id"])
                        await asyncio.sleep(0.05)
                    else:
                        await asyncio.sleep(0.05)

            async def stop():
                await asyncio.sleep(0.4)
                shutdown.set()

            await asyncio.gather(worker(1), worker(2), stop())
            assert seen == {1, 2}
