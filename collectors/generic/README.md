# uFawkesDORA Generic Collectors

Copy-paste-ready integrations for emitting DORA events from **any** CI/CD system
or from a terminal.

## When to Use These

| Source                                  | When                             | Recommended File                                                |
| --------------------------------------- | -------------------------------- | --------------------------------------------------------------- |
| Woodpecker CI (uFawkesPipe)             | Your pipeline runs on Woodpecker | [`pipeline-snippet.yml`](../woodpecker/pipeline-snippet.yml)    |
| GitLab CI / Jenkins / CircleCI / any CI | Your CI has `curl` and env vars  | [`curl-examples.sh`](curl-examples.sh)                          |
| Portainer (webhook on stack redeploy)   | You deploy stacks via Portainer  | See [Portainer section](#portainer-webhook) below               |
| Manual incident (no PagerDuty)          | An engineer gets paged           | [`declare-incident.sh`](../manual-incident/declare-incident.sh) |

---

## Quick Start

```bash
# 1. Set the ingestion API URL
export DORA_INGESTION_URL="https://dora.example.com"

# 2. (Optional) Set API key if auth is enabled
export DORA_API_KEY="your-api-key"  # pragma: allowlist secret

# 3. Send a deployment event
curl -X POST "${DORA_INGESTION_URL}/event" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "1.0",
    "event_type": "deployment",
    "repo": "my-org/my-service",
    "service": "my-service",
    "environment": "production",
    "commit_sha": "'"$(git rev-parse HEAD)"'",
    "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    "status": "success"
  }'

# Verify
echo "Check raw_events table for the new row"
```

---

## CI/CD Integration

### Per-Platform Environment Variable Mapping

Use this table to map your CI/CD system's built-in variables to the fields
required by the canonical event schemas.

| Event Field    | GitLab CI          | CircleCI                  | Jenkins        | Woodpecker         |
| -------------- | ------------------ | ------------------------- | -------------- | ------------------ |
| `commit_sha`   | `CI_COMMIT_SHA`    | `CIRCLE_SHA1`             | `GIT_COMMIT`   | `CI_COMMIT_SHA`    |
| `pipeline_url` | `CI_JOB_URL`       | `CIRCLE_BUILD_URL`        | `BUILD_URL`    | `CI_PIPELINE_URL`  |
| `repo`         | `CI_PROJECT_PATH`  | `CIRCLE_PROJECT_REPONAME` | From `GIT_URL` | `CI_REPO`          |
| `service`      | `CI_PROJECT_NAME`  | `CIRCLE_PROJECT_REPONAME` | `JOB_NAME`     | `CI_REPO_NAME`     |
| `branch`       | `CI_COMMIT_BRANCH` | `CIRCLE_BRANCH`           | `BRANCH_NAME`  | `CI_COMMIT_BRANCH` |
| `environment`  | Set manually       | Set manually              | Set manually   | Set manually       |

### Woodpecker CI

Add the [pipeline snippet](../woodpecker/pipeline-snippet.yml) to your
`.woodpecker/*.yml` configuration:

```yaml
steps:
  notify-dora:
    image: curlimages/curl:latest
    # ... see woodpecker/pipeline-snippet.yml for full example
```

The snippet uses Woodpecker's `from_secret` for credentials — add these secrets
in your Woodpecker repo settings:

| Secret Name          | Value                      |
| -------------------- | -------------------------- |
| `dora_ingestion_url` | `https://dora.example.com` |
| `dora_api_key`       | `your-api-key` (optional)  |

### GitLab CI

```yaml
notify-dora:
  image: curlimages/curl:latest
  variables:
    DORA_INGESTION_URL: $DORA_INGESTION_URL  # set in CI/CD settings
    DORA_API_KEY: $DORA_API_KEY               # set in CI/CD settings
  script:
    - curl -X POST "${DORA_INGESTION_URL}/event"
        -H "Content-Type: application/json"
        -d '{
          "schema_version": "1.0",
          "event_type": "deployment",
          "repo": "'"${CI_PROJECT_PATH}"'",
          "service": "'"${CI_PROJECT_NAME}"'",
          "commit_sha": "'"${CI_COMMIT_SHA}"'",
          "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
          "status": "'"${CI_JOB_STATUS}"'",
          "pipeline_url": "'"${CI_JOB_URL}"'"
        }'
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### Jenkins Pipeline

```groovy
stage('DORA Notification') {
    steps {
        sh """
            curl -X POST "${DORA_INGESTION_URL}/event" \
                -H "Content-Type: application/json" \
                -d '{
                    "schema_version": "1.0",
                    "event_type": "deployment",
                    "repo": "my-org/my-service",
                    "service": "my-service",
                    "commit_sha": "${GIT_COMMIT}",
                    "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
                    "status": "${currentBuild.result ?: 'success'}",
                    "pipeline_url": "${BUILD_URL}"
                }'
        """
    }
}
```

### CircleCI

```yaml
version: 2.1
jobs:
  deploy:
    docker:
      - image: curlimages/curl:latest
    steps:
      - run:
          name: Notify DORA
          command: |
            curl -X POST "${DORA_INGESTION_URL}/event" \
              -H "Content-Type: application/json" \
              -d '{
                "schema_version": "1.0",
                "event_type": "deployment",
                "repo": "'"${CIRCLE_PROJECT_REPONAME}"'",
                "service": "'"${CIRCLE_PROJECT_REPONAME}"'",
                "commit_sha": "'"${CIRCLE_SHA1}"'",
                "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
                "status": "success",
                "pipeline_url": "'"${CIRCLE_BUILD_URL}"'"
              }'
```

---

## Portainer Webhook

Portainer supports **outgoing webhooks** that trigger when a stack is redeployed.
You can configure it to POST a deployment event to the uFawkesDORA ingestion API.

### Portainer Webhook Configuration

1. In Portainer, go to **Settings → Webhooks**
2. Click **Add webhook**
3. Configure:

| Field               | Value                                           |
| ------------------- | ----------------------------------------------- |
| **Name**            | `uFawkesDORA Deployment Event`                  |
| **URL**             | `https://your-dora-ingestion.example.com/event` |
| **Method**          | `POST`                                          |
| **Request Headers** | `Content-Type: application/json`                |
| **Event Types**     | `Stack Deployment`                              |

### Portainer Webhook JSON Body

Portainer sends a POST request with the following JSON body when a stack
is deployed:

```json
{
  "event_type": "deployment",
  "stack_name": "my-stack",
  "stack_id": 42,
  "endpoint_id": 1,
  "environment": "production",
  "status": "success"
}
```

### Mapping to Canonical Schema

Portainer's webhook body doesn't include `commit_sha` or `pipeline_url` by
default. The ingestion API will accept the event with the fields Portainer
provides — missing optional fields are acceptable.

If you need `commit_sha`, configure your Portainer stack to include it in
environment labels, or accept that deployment events from Portainer will lack
commit-level granularity (set `commit_sha: "unknown"` in the webhook receiver).

### Configuring the Webhook Receiver

Portainer webhooks POST to a fixed URL — you can either:

1. **Point directly at the ingestion API** (`/event` endpoint) if Portainer's
   JSON body is acceptable as-is
2. **Use a lightweight transformer** (e.g., an AWS Lambda or a simple proxy)
   to map Portainer's fields to the canonical schema

For option 1, the payload sent by Portainer will be stored in `raw_events`
as-is. The DORA metrics computation can still extract meaningful data from
it (repo, service, status).

---

## Manual Incident Declaration

If your team doesn't use PagerDuty, Grafana OnCall, or any incident management
platform, use the manual scripts to declare and resolve incidents:

```bash
# Declare an incident (interactive)
./collectors/manual-incident/declare-incident.sh

# Declare an incident (flags, for runbooks/automation)
./collectors/manual-incident/declare-incident.sh \
    --incident_id=INC-123 \
    --service=api-gateway \
    --severity=critical

# Resolve the incident (use the SAME incident_id)
./collectors/manual-incident/resolve-incident.sh \
    --incident_id=INC-123
```

These scripts POST incident events to `$DORA_INGESTION_URL/event`. They are
critical for FDRT (Failure Deployment Recovery Time) — without incident events,
FDRT cannot be calculated.

### Incident Response Runbook Template

Add this to your incident response runbook:

```markdown
## 1. DECLARE the incident

ssh ops-box
export DORA_INGESTION_URL="https://dora.example.com"
./collectors/manual-incident/declare-incident.sh

## 2. Debug and fix

[... your debugging steps ...]

## 3. RESOLVE the incident

./collectors/manual-incident/resolve-incident.sh \
 --incident_id=<same-id-from-step-1>
```

---

## Troubleshooting

### Check events reached the database

```bash
# Using Docker Compose
docker compose -f docker-compose.dev.yml exec -T timescaledb \
    psql -U postgres -d dora_metrics \
    -c "SELECT recorded_at, event_type, status, service FROM raw_events ORDER BY recorded_at DESC LIMIT 20;"
```

### Common Issues

| Symptom                            | Likely Cause                     | Fix                                            |
| ---------------------------------- | -------------------------------- | ---------------------------------------------- |
| `curl: (6) Could not resolve host` | Wrong URL                        | Check `DORA_INGESTION_URL` includes `https://` |
| HTTP 422                           | Invalid JSON payload             | Validate against `events/*.schema.json`        |
| HTTP 401/403                       | Missing API key                  | Set `DORA_API_KEY`                             |
| HTTP 500                           | Ingestion API down               | Check API logs                                 |
| No rows in `raw_events`            | Event not sent or wrong database | Check curl output; verify `DATABASE_URL`       |
| `command not found: curl`          | No curl in CI image              | Use `curlimages/curl:latest` Docker image      |

### Verify Schema Compliance

```bash
# Validate a payload against the incident schema
python3 -c "
import json, jsonschema
with open('events/incident-event.schema.json') as f:
    schema = json.load(f)
payload = {
    'schema_version': '1.0',
    'event_type': 'incident',
    'incident_id': 'INC-123',
    'service': 'my-service',
    'repo': 'my-org/my-service',
    'status': 'opened',
    'reported_at': '2026-06-23T12:00:00Z',
    'severity': 'critical'
}
jsonschema.validate(payload, schema)
print('✅ Payload is valid')
"
```
