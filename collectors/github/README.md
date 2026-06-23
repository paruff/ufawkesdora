# uFawkesDORA — GitHub Actions Collectors

Emit deployment and pull request events from any GitHub repo to the
uFawkesDORA ingestion API. Zero new tooling — just add one `uses:` line to
your workflows.

## Prerequisites

1. You have access to a uFawkesDORA ingestion API endpoint.
2. Set `DORA_INGESTION_URL` as a [repository variable][gh-vars] in your repo:

   ```
   DORA_INGESTION_URL = https://dora-ingestion.ufawkes.dev
   ```

[gh-vars]: https://docs.github.com/en/actions/learn-github-actions/variables

---

## Deployment Events (10-minute wiring)

Add a single job to your existing release or deploy workflow:

```yaml
emit-deployment:
  steps:
    - uses: paruff/ufawkesdora/collectors/github/dora-deployment-event.yml@v1
      with:
        status: success
        environment: production
        pipeline_url: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

That's it. Every time your workflow runs, a deployment event is sent to
the ingestion API.

### Inputs

| Input                     | Required | Default                   | Description                          |
| ------------------------- | -------- | ------------------------- | ------------------------------------ |
| `status`                  | ✅       | —                         | `success`, `failed`, or `rollback`   |
| `environment`             | ✅       | —                         | e.g. `production`, `staging`, `dev`  |
| `pipeline_url`            | ✅       | —                         | Link to the CI/CD pipeline run       |
| `service`                 | ❌       | repository name           | Service or component name            |
| `deploy_duration_seconds` | ❌       | —                         | Total deployment duration in seconds |
| `ai_assisted`             | ❌       | `false`                   | Whether AI tooling was involved      |
| `ingestion_url`           | ❌       | `vars.DORA_INGESTION_URL` | Override the ingestion API URL       |

---

## PR Events (10-minute wiring)

Add a trigger for PR merges and call the PR collector:

```yaml
on:
  pull_request:
    types: [closed]

jobs:
  emit-pr:
    if: github.event.pull_request.merged == true
    steps:
      - uses: paruff/ufawkesdora/collectors/github/dora-pr-event.yml@v1
        with:
          pr_number: ${{ github.event.pull_request.number }}
```

The collector fetches the PR's commit timeline via the GitHub API to
determine `first_commit_at` (the oldest commit in the PR branch).

### Inputs

| Input           | Required | Default                   | Description                     |
| --------------- | -------- | ------------------------- | ------------------------------- |
| `pr_number`     | ✅       | —                         | Pull request number             |
| `status`        | ❌       | `merged`                  | `opened`, `merged`, or `closed` |
| `commit_sha`    | ❌       | fetched from API          | Override merge commit SHA       |
| `ai_assisted`   | ❌       | `false`                   | Whether AI tooling was used     |
| `ingestion_url` | ❌       | `vars.DORA_INGESTION_URL` | Override the ingestion API URL  |
| `repo`          | ❌       | `github.repository`       | Repository identifier           |

> **Permissions note**: The PR collector requires `pull-requests: read`
> permission to fetch the PR commit timeline. Include this in the caller
> workflow:
>
> ```yaml
> permissions:
>   pull-requests: read
> ```

---

## Testing Locally with cURL

You can test that the ingestion API accepts your events without running a
full workflow:

```bash
# Test a deployment event
curl -X POST "${DORA_INGESTION_URL}/event" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "1.0",
    "event_type": "deployment",
    "repo": "my-org/my-service",
    "service": "my-service",
    "environment": "production",
    "commit_sha": "abc123def456abc123def456abc123def456abc1",
    "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    "status": "success",
    "pipeline_url": "https://github.com/my-org/my-service/actions/runs/1"
  }'

# Test a PR event
curl -X POST "${DORA_INGESTION_URL}/event" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "1.0",
    "event_type": "pr",
    "repo": "my-org/my-service",
    "pr_number": 42,
    "commit_sha": "abc123def456abc123def456abc123def456abc1",
    "status": "merged",
    "occurred_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    "first_commit_at": "'"$(date -u -d '-3 days' +%Y-%m-%dT%H:%M:%SZ)"'"
  }'
```

---

## Event Schemas

Events are validated against canonical Draft-07 JSON schemas:

| Schema             | File                                  |
| ------------------ | ------------------------------------- |
| Deployment Event   | `events/deployment-event.schema.json` |
| Pull Request Event | `events/pr-event.schema.json`         |
| Incident Event     | `events/incident-event.schema.json`   |
| Rework Event       | `events/rework-event.schema.json`     |

See [`events/README.md`](../../events/README.md) for the full versioning
policy and field reference.

---

## Architecture

```
┌─────────────┐     ┌──────────────────────┐     ┌──────────────┐
│  Your Repo  │────▶│  uFawkesDORA          │────▶│  TimescaleDB  │
│  (workflow)  │     │  Ingestion API        │     │  (raw_events) │
│              │     │  POST /event          │     │               │
│  uses: ...   │     │  8088                 │     │  DORA metrics │
└─────────────┘     └──────────────────────┘     └──────────────┘
```

The collectors act as adapters between GitHub webhook payloads and the
uFawkesDORA canonical event schemas. They require no changes to your
existing CI/CD pipelines.
