"""uFawkesDORA Ingestion API — stateless FastAPI ingestion endpoint.

Accepts events on ``POST /event``, validates against canonical schemas,
and enqueues to Postgres using the event_queue table.

Endpoints:
    POST /event       — Accept a single event, validate, enqueue.
    POST /event/batch — Accept multiple events, validate all, enqueue in a transaction.
    GET  /health      — Health check with queue depth.
"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ingestion.api.queue import close_pool, enqueue_event, enqueue_events, get_queue_depth
from ingestion.api.validator import validate_payload, validate_payloads


# ── Lifecycle ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup: pool is lazy-initialized on first use
    yield
    # Shutdown: close the connection pool
    await close_pool()


app = FastAPI(
    title="uFawkesDORA Ingestion API",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Exception handlers ─────────────────────────────────────────────────────────


@app.exception_handler(HTTPException)
async def validation_exception_handler(request: Request, exc: HTTPException):
    """Ensure 422 errors carry structured field-level detail."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns ``{"status": "ok", "queue_depth": N}`` where N is the number
    of pending events in the queue.
    """
    depth = await get_queue_depth()
    return {"status": "ok", "queue_depth": depth}


@app.post("/event", status_code=201)
async def post_event(payload: dict[str, Any]):
    """Accept a single event, validate, and enqueue.

    Returns ``{"queued": true, "id": N}`` on success.
    Returns ``422`` with field-level errors on validation failure.
    """
    result = validate_payload(payload)
    if not result.valid:
        raise HTTPException(status_code=422, detail=result.to_error_response()["detail"])

    event_id = await enqueue_event(payload)
    return {"queued": True, "id": event_id}


@app.post("/event/batch", status_code=201)
async def post_events(payloads: list[dict[str, Any]]):
    """Accept multiple events, validate all, enqueue in one transaction.

    Returns ``{"queued": true, "ids": [N, ...]}`` on success.
    If *any* event fails validation, none are enqueued and a ``422`` with
    per-event field-level errors is returned.
    """
    results = validate_payloads(payloads)

    # Collect all validation errors grouped by index
    errors_by_index: dict[int, list] = {}
    all_valid = True
    for i, result in enumerate(results):
        if not result.valid:
            all_valid = False
            errors_by_index[i] = result.to_error_response()["detail"]

    if not all_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "One or more events failed validation. None were enqueued.",
                "errors": errors_by_index,
            },
        )

    ids = await enqueue_events(payloads)
    return {"queued": True, "ids": ids}
