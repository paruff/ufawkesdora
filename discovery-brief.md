---
date: 2026-06-23
persona: team-lead
jtbd: "When my team gets paged for a production incident and we don't have an incident management platform, I want engineering to declare the incident with one shell command from any terminal, so that uFawkesDORA can measure FDRT without requiring PagerDuty or Grafana OnCall."
riskiest_assumption: "We assume engineers under incident pressure will remember to run declare-incident.sh before debugging. What if the cognitive load of incident response makes running a shell script the first thing they skip?"
acceptance_criterion: "Given the ingestion API is running at $DORA_INGESTION_URL, when an engineer runs ./collectors/manual-incident/declare-incident.sh --incident_id=INC-123 --service=my-service --severity=critical, then the API returns HTTP 201 and a row with event_type='incident' appears in raw_events."
dora_ai_capability: "Cap2: Healthy data ecosystems"
dora_core_capability: "Change Failure Rate (CFR) and FDRT"
metric: "fdrt_hours"
measurement_source: "uFawkesDORA compute/metrics.py"
baseline: "unknown — no incident events currently being collected"
prior_art: "events/incident-event.schema.json defines the canonical schema; collectors/github/ has the reference implementation for GitHub Actions"
status: ready-for-spec
---

# Discovery Brief: Non-GitHub Collector Patterns

## Job to Be Done

"When my team gets paged for a production incident and we don't have an incident
management platform, I want engineering to declare the incident with one shell
command from any terminal, so that uFawkesDORA can measure FDRT without requiring
PagerDuty or Grafana OnCall."

## Riskiest Assumption

**We assume engineers under incident pressure will remember to run
`declare-incident.sh` (and `resolve-incident.sh` later) before debugging.**
What if the cognitive load of incident response makes running a shell script
the first thing they skip?

_Mitigation:_ The script must be trivial — one command, no install step,
copy-paste from a runbook. Output must include a confirmation URL for audit.
Future iteration could add Slack integration.

## Acceptance Criterion

> **Given** the ingestion API is running at `$DORA_INGESTION_URL`,
> **when** an engineer runs
> `./collectors/manual-incident/declare-incident.sh --incident_id=INC-123 --service=my-service --severity=critical`,
> **then** the API returns HTTP 201 and a row with `event_type='incident'`
> appears in `raw_events`.

## DORA Outcome Target

| Field           | Value                                                       |
| --------------- | ----------------------------------------------------------- |
| Capability      | Cap2: Healthy data ecosystems                               |
| Core Capability | Change Failure Rate (CFR) and FDRT                          |
| Metric          | FDRT hours — currently unmeasurable without incident events |
| Baseline        | unknown — no incident events being collected                |
| Target          | Establish baseline within first month of use                |
| Measurement     | uFawkesDORA `compute/metrics.py` FDRT query                 |

## Deliverables

1. **`collectors/woodpecker/pipeline-snippet.yml`** — Woodpecker CI pipeline step
   that POSTs a deployment-event on pipeline success/failure. Uses `from_secret`
   for `DORA_INGESTION_URL` and `DORA_API_KEY` (if auth enabled). Follows the
   same HTTP POST pattern as the GitHub collector, adapted for Woodpecker's YAML
   syntax and variable substitution.

2. **`collectors/generic/curl-examples.sh`** — Collection of well-commented,
   copy-paste-ready curl commands for all 4 event types:

   - deployment (success/failed)
   - incident (opened/resolved)
   - rework (hotfix/rollback)
   - PR (opened/merged)
     Documents which CI-provided env vars map to which fields for common systems
     (Jenkins, GitLab CI, CircleCI).

3. **`collectors/manual-incident/declare-incident.sh`** — Shell script for teams
   without PagerDuty/Grafana OnCall. Accepts `--incident_id`, `--service`,
   `--severity` as flags (or prompts interactively). POSTs incident-event to
   the ingestion API. Companion `resolve-incident.sh` posts the resolution
   (needed for FDRT calculation — FDRT = time between opened and resolved).

4. **`collectors/generic/README.md`** — Documentation covering:

   - Generic curl examples reference
   - Woodpecker snippet wiring guide
   - Portainer webhook integration (Portainer supports outgoing webhooks on
     stack redeploy — document the exact JSON format and how to configure it)
   - Per-platform env var mapping table

5. **Evidence:** Run `declare-incident.sh` against the running ingestion API
   and verify HTTP 201 + row in `raw_events`.

## Prior Art

- **`events/incident-event.schema.json`** — canonical schema exists at version 1.0;
  the script must produce payloads matching `event_type: "incident"`, required
  fields (`incident_id`, `status`, `service`, `reported_at`, etc.)
- **`collectors/github/`** — reference implementation for GitHub Actions; same
  HTTP POST pattern, different CI variable syntax
- **`collectors/github/dora-deployment-event.yml`** — reusable workflow that
  maps GitHub event payload fields to the canonical schema; the curl examples
  follow the same mapping but use different variable sources
- No prior art found in the uFawkes suite for Woodpecker, Portainer, or manual
  incident declaration

## Design Constraints

- Shell scripts must be POSIX-sh compatible (not bash-specific) for maximum
  portability across environments
- Woodpecker snippet uses `from_secret` syntax for secrets (`DORA_INGESTION_URL`,
  `DORA_API_KEY`)
- curl examples must document CI-provided env vars per platform (e.g.,
  `CI_COMMIT_SHA` for GitLab CI, `CIRCLE_SHA1` for CircleCI)
- All collectors POST to `$DORA_INGESTION_URL/event` with
  `Content-Type: application/json`
- Non-201 responses log a warning, not a hard failure (same pattern as GitHub
  collectors)
- `declare-incident.sh` must support both flag and interactive modes:
  `--incident_id INC-123` (non-interactive) or no flags (prompts for each field)
- `resolve-incident.sh` marks status=`resolved` and sets `resolved_at` to now;
  must reference the same `incident_id`
- Portainer webhook section must include the Portainer webhook URL format and
  the expected JSON body structure

## Notes

The manual incident script has the highest verification risk because it requires
a live ingestion API to test. The curl examples and Woodpecker snippet can be
verified by shellcheck + inspection of the generated JSON payload.

Blocks Issue 10: FDRT computation (no incident events → no FDRT data to query).
