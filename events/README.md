# uFawkesDORA Event Schemas

Canonical JSON Schemas for all DORA metric event sources.

These schemas define the API contract between any CI/CD system (GitHub Actions,
GitLab CI, Jenkins, ArgoCD, etc.) and uFawkesDORA. Every event that enters the
platform must conform to one of these schemas.

## Event Types

| Schema File | `event_type` | Purpose |
|---|---|---|
| `deployment-event.schema.json` | `deployment` | Deployment lifecycle (success, failure, rollback) |
| `incident-event.schema.json` | `incident` | Incident lifecycle (opened, resolved) |
| `pr-event.schema.json` | `pr` | Pull request lifecycle (opened, merged, closed) |
| `rework-event.schema.json` | `rework` | Corrective deployments (hotfix, rollback, patch) |

## Versioning Policy

All schemas carry a `schema_version` field in `MAJOR.MINOR` format.

| Change | Version Bump | Collector Impact |
|---|---|---|
| Adding an optional field | Minor (e.g., `1.0` → `1.1`) | None — backward compatible |
| Adding a new required field | Major (e.g., `1.0` → `2.0`) | Collectors must be updated to supply the field |
| Removing a field | Major (e.g., `1.0` → `2.0`) | Collectors must stop sending the removed field |
| Changing a field type | Major (e.g., `1.0` → `2.0`) | Collectors must adapt to the new type |
| Constraining an enum (removing a value) | Major (e.g., `1.0` → `2.0`) | Collectors must stop emitting the removed value |
| Expanding an enum (adding a value) | Minor (e.g., `1.0` → `1.1`) | None — new values are additive |

All schemas start at version `"1.0"`.

A schema file that does not explicitly carry a `schema_version` field should be
treated as version `"0.0"` (pre-release — may change without notice). All
canonical production schemas MUST specify a version.

## Determining Rework vs Normal Deployment

A deployment is considered **rework** if it is primarily corrective rather than
forward-progress. Use these heuristics:

| If the deployment is... | Event type to emit |
|---|---|
| A new feature or standard release | `deployment` |
| A hotfix addressing a production bug | `rework` with `rework_type: "hotfix"` |
| A rollback to a prior version | `rework` with `rework_type: "rollback"` |
| A patch release (security or bug fix) | `rework` with `rework_type: "patch"` |

The same commit SHA may appear in both a `deployment` event and a `rework`
event — collectors should emit both when a deployment is rework.

## Field Reference

### Common Fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `string` (`MAJOR.MINOR`) | Schema version for compatibility checking |
| `event_type` | `string` (enum) | Discriminant for event routing |

### Deployment Event (`deployment-event.schema.json`)

| Field | Required | Type | Description |
|---|---|---|---|
| `repo` | Yes | `string` | Repository identifier (`org/repo`) |
| `service` | Yes | `string` | Service or component name |
| `environment` | Yes | `string` | Target environment |
| `commit_sha` | Yes | `string` (hex, 40 chars) | Deployed commit SHA |
| `deployed_at` | Yes | `string` (ISO 8601) | Deployment completion timestamp |
| `status` | Yes | `enum` | `success`, `failed`, `rollback` |
| `pipeline_url` | Yes | `string` (URI) | CI/CD pipeline run URL |
| `deploy_duration_seconds` | No | `integer` | Deployment duration |
| `ai_assisted` | No | `boolean` | AI involvement flag |

### Incident Event (`incident-event.schema.json`)

| Field | Required | Type | Description |
|---|---|---|---|
| `incident_id` | Yes | `string` | Incident management system ID |
| `repo` | Yes | `string` | Repository identifier |
| `service` | Yes | `string` | Affected service |
| `status` | Yes | `enum` | `opened`, `resolved` |
| `occurred_at` | Yes | `string` (ISO 8601) | Event timestamp |
| `linked_deployment_sha` | No | `string` (hex, 40 chars) | Related deployment SHA |
| `severity` | No | `string` | Severity level |

### PR Event (`pr-event.schema.json`)

| Field | Required | Type | Description |
|---|---|---|---|
| `repo` | Yes | `string` | Repository identifier |
| `pr_number` | Yes | `integer` | Pull request number |
| `commit_sha` | Yes | `string` (hex, 40 chars) | Latest commit SHA |
| `status` | Yes | `enum` | `opened`, `merged`, `closed` |
| `occurred_at` | Yes | `string` (ISO 8601) | Event timestamp |
| `first_commit_at` | Yes | `string` (ISO 8601) | First commit timestamp |
| `lines_added` | No | `integer` | Lines added |
| `lines_deleted` | No | `integer` | Lines deleted |
| `ai_assisted` | No | `boolean` | AI involvement flag |

### Rework Event (`rework-event.schema.json`)

| Field | Required | Type | Description |
|---|---|---|---|
| `deployment_sha` | Yes | `string` (hex, 40 chars) | Rework deployment SHA |
| `rework_type` | Yes | `enum` | `hotfix`, `rollback`, `patch` |
| `triggered_at` | Yes | `string` (ISO 8601) | Deployment timestamp |
| `user_visible` | Yes | `boolean` | End-user impact flag |

## Contributing

1. Make schema changes in a feature branch.
2. Bump `schema_version` per the versioning policy above.
3. Update the corresponding test fixtures in `tests/unit/test_event_schemas.py`.
4. Run `make test-unit` to verify all schemas validate.
5. Open a PR — schema changes require review from at least one other team member.
