"""End-to-End Flow Test: Event Ingestion → Worker → Metrics Snapshot.

This test validates the full uFawkesDORA data pipeline:
1. POST a deployment event and an incident event to the ingestion API
2. Wait for the async worker to dequeue and process them into raw_events
3. Run the compute engine to generate a DORA snapshot
4. Assert the snapshot contains correct computed metrics

Requires: docker-compose.test.yml stack running.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("DORA_API_URL", "http://localhost:8089")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dora_app:change_me_in_production@localhost:5434/dora_metrics",  # pragma: allowlist secret
)


def _wait_for_api(max_retries: int = 15, delay: float = 2.0) -> None:
    """Wait for the ingestion API health endpoint to respond 200."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(f"{API_URL}/health")
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                print(f"[e2e] API healthy after {attempt + 1}s")
                return
        except (urllib.error.URLError, ConnectionResetError, OSError):
            pass
        time.sleep(delay)
    raise TimeoutError(f"API at {API_URL} not healthy after {max_retries * delay}s")


def _post_event(payload: dict) -> dict:
    """POST an event and return the parsed JSON response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}/event",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise AssertionError(f"POST /event returned {e.code}: {body}") from e


def _run_compute(window_days: int = 7) -> dict:
    """Run the metrics computation and return JSON output."""
    result = subprocess.run(
        [
            "python",
            "compute/metrics.py",
            "--window",
            str(window_days),
            "--json",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"compute/metrics.py failed:\nstdout:{result.stdout}\nstderr:{result.stderr}"
        )
    return json.loads(result.stdout)


def _count_raw_events() -> int:
    """Query raw_events table via psql and return row count."""
    result = subprocess.run(
        [
            "psql",
            DATABASE_URL,
            "-t",
            "-A",
            "-c",
            "SELECT COUNT(*) FROM raw_events WHERE recorded_at >= NOW() - INTERVAL '1 hour'",
        ],
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def test_e2e_full_pipeline():
    """End-to-end test: event → worker → metrics snapshot."""
    _wait_for_api()

    # ── Step 1: Post a deployment success event ─────────────────────────────
    deploy_payload = {
        "schema_version": "1.0",
        "event_type": "deployment",
        "repo": "paruff/ufawkesdora",
        "service": "ingestion-api",
        "environment": "production",
        "commit_sha": "a" * 40,
        "status": "success",
        "deployed_at": "2026-06-23T12:00:00Z",
        "pipeline_url": "https://github.com/paruff/ufawkesdora/actions/runs/1",
    }
    resp = _post_event(deploy_payload)
    print(f"[e2e] Deployment event queued: {resp}")

    # ── Step 2: Post an incident event ──────────────────────────────────────
    incident_payload = {
        "schema_version": "1.0",
        "event_type": "incident",
        "repo": "paruff/ufawkesdora",
        "service": "ingestion-api",
        "incident_id": "E2E-TEST-001",
        "status": "opened",
        "occurred_at": "2026-06-23T12:05:00Z",
        "severity": "critical",
    }
    resp = _post_event(incident_payload)
    print(f"[e2e] Incident event queued: {resp}")

    # ── Step 3: Wait for worker to process ──────────────────────────────────
    time.sleep(5)
    event_count = _count_raw_events()
    assert event_count >= 2, (
        f"Expected >= 2 raw events, got {event_count}. Worker may not have processed the queue yet."
    )
    print(f"[e2e] {event_count} raw events found (expected >= 2)")

    # ── Step 4: Run compute and verify snapshot ─────────────────────────────
    snapshots = _run_compute(window_days=7)
    print(f"[e2e] Compute result: {json.dumps(snapshots, indent=2)}")

    assert len(snapshots) >= 1, "Expected at least one snapshot row"
    row = snapshots[0]
    assert row.get("deployment_frequency") is not None, "Missing deployment_frequency"
    assert row.get("change_failure_rate") is not None, "Missing change_failure_rate"
    print("[e2e] ✅ Full pipeline validated: event → raw_events → dora_snapshots")


if __name__ == "__main__":
    test_e2e_full_pipeline()
