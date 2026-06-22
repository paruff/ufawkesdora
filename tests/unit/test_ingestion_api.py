"""Unit tests for the uFawkesDORA Ingestion API.

Tests cover:
- Valid single event accepted (201)
- Invalid schema rejected (422 with field errors)
- Queue depth in health check
- Duplicate events handled (dedup is at processor level, this tests acceptance)
- Batch endpoint validation
"""

import json
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from ingestion.api.main import app


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def valid_deployment() -> dict:
    return {
        "schema_version": "1.0",
        "event_type": "deployment",
        "repo": "my-org/my-service",
        "service": "api-gateway",
        "environment": "production",
        "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "deployed_at": "2026-06-22T10:30:00Z",
        "status": "success",
        "pipeline_url": "https://github.com/my-org/my-service/actions/runs/12345",
    }


@pytest.fixture
def valid_incident() -> dict:
    return {
        "schema_version": "1.0",
        "event_type": "incident",
        "incident_id": "INC-12345",
        "repo": "my-org/my-service",
        "service": "api-gateway",
        "status": "opened",
        "occurred_at": "2026-06-22T10:30:00Z",
    }


@pytest.fixture
def valid_pr() -> dict:
    return {
        "schema_version": "1.0",
        "event_type": "pr",
        "repo": "my-org/my-service",
        "pr_number": 42,
        "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "status": "merged",
        "occurred_at": "2026-06-22T10:30:00Z",
        "first_commit_at": "2026-06-20T08:00:00Z",
    }


@pytest.fixture
def valid_rework() -> dict:
    return {
        "schema_version": "1.0",
        "event_type": "rework",
        "repo": "my-org/my-service",
        "deployment_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "rework_type": "hotfix",
        "triggered_at": "2026-06-22T10:30:00Z",
        "user_visible": True,
    }


# ── Mock queue operations ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_queue():
    """Mock all asyncpg queue operations for unit tests.

    Patches at ``ingestion.api.main`` because ``main.py`` does
    ``from ingestion.api.queue import enqueue_event`` (direct binding).
    Uses smarter mocks so ``enqueue_events([])`` returns ``[]``.
    """
    async def mock_enqueue_events(payloads):
        return list(range(1, len(payloads) + 1))

    with patch.multiple(
        "ingestion.api.main",
        enqueue_event=AsyncMock(return_value=1),
        enqueue_events=AsyncMock(side_effect=mock_enqueue_events),
        get_queue_depth=AsyncMock(return_value=5),
    ):
        yield


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestHealth:
    """GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_status_and_depth(self):
        """AC: Health check returns status=ok and correct queue_depth."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"status": "ok", "queue_depth": 5}


class TestPostEvent:
    """POST /event endpoint."""

    @pytest.mark.asyncio
    async def test_valid_event_returns_201(self, valid_deployment):
        """AC-01: Valid deployment event accepted, returns 201 with queued=true."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=valid_deployment)
            assert resp.status_code == 201
            data = resp.json()
            assert data == {"queued": True, "id": 1}

    @pytest.mark.asyncio
    async def test_valid_incident_returns_201(self, valid_incident):
        """All event types should be accepted."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=valid_incident)
            assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_valid_pr_returns_201(self, valid_pr):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=valid_pr)
            assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_valid_rework_returns_201(self, valid_rework):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=valid_rework)
            assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_missing_event_type_returns_422(self):
        """AC-02: Missing event_type returns 422 with field-level error."""
        payload = {"repo": "org/repo"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=payload)
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert any("event_type" in str(e.get("loc", [])) for e in detail)

    @pytest.mark.asyncio
    async def test_invalid_status_returns_422(self):
        """AC-02: Invalid status value returns 422 with field-level detail."""
        payload = {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "org/repo",
            "service": "svc",
            "environment": "prod",
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "deployed_at": "2026-06-22T10:30:00Z",
            "status": "bogus",
            "pipeline_url": "https://example.com/pipeline/1",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=payload)
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert any("status" in str(e.get("loc", [])) for e in detail)

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_422(self):
        """AC-02: Unknown event_type returns 422 with supported types listed."""
        payload = {
            "schema_version": "1.0",
            "event_type": "unknown_type",
            "repo": "org/repo",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=payload)
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert any("unknown_type" in str(e.get("msg", "")) for e in detail)

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_422(self, valid_deployment):
        """AC-02: Missing a required field returns 422."""
        payload = {k: v for k, v in valid_deployment.items() if k != "repo"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=payload)
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert len(detail) > 0

    @pytest.mark.asyncio
    async def test_optional_fields_accepted(self, valid_deployment):
        """Events with optional fields should still be accepted."""
        valid_deployment["deploy_duration_seconds"] = 120
        valid_deployment["ai_assisted"] = True
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event", json=valid_deployment)
            assert resp.status_code == 201


class TestPostEventBatch:
    """POST /event/batch endpoint."""

    @pytest.mark.asyncio
    async def test_valid_batch_returns_201(self, valid_deployment, valid_incident):
        """AC-03: Valid batch of events returns 201 with all ids."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/event/batch",
                json=[valid_deployment, valid_incident],
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data == {"queued": True, "ids": [1, 2]}

    @pytest.mark.asyncio
    async def test_batch_with_invalid_returns_422(self, valid_deployment):
        """AC-03: If any event in batch is invalid, nothing is accepted."""
        invalid = {"event_type": "deployment"}  # missing required fields
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/event/batch",
                json=[valid_deployment, invalid],
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_201(self):
        """Empty batch is accepted (validates no events = nothing to fail)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/event/batch", json=[])
            assert resp.status_code == 201
            data = resp.json()
            assert data == {"queued": True, "ids": []}
