# DORA Wellbeing Survey

Quarterly developer wellbeing survey used by the [archetype classifier](archetype.py)
to improve classification confidence. Without wellbeing data, archetype classification
is capped at 0.65 confidence.

## The Four Questions

Each question is scored 1 (strongly disagree) to 5 (strongly agree):

| # | Question | Dimension |
|---|----------|-----------|
| 1 | I have sufficient time to do quality work without unsustainable pressure | Sustainable pace |
| 2 | My team has the autonomy to choose how we implement our work | Team autonomy |
| 3 | I feel motivated by the work my team delivers | Purpose & engagement |
| 4 | I am not at risk of burnout in my current role | Burnout risk (inverse) |

### Scoring

- **1–2**: Concerning — high risk of disengagement or burnout
- **3**: Neutral
- **4–5**: Healthy

A team's wellbeing score is the average of all respondent scores across all
four questions, normalised to 0–1.

## Submitting Responses

Send a structured event to the ingestion API:

```bash
curl -X POST https://ingest.ufawkes.dev/event \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $UFAWKES_API_TOKEN" \
  -d '{
    "schema_version": "1.0",
    "event_type": "wellbeing_survey",
    "repo": "paruff/uFawkesDORA",
    "occurred_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    "respondent_id": "developer@example.com",
    "survey_version": "2025.1",
    "q1_score": 4,
    "q2_score": 3,
    "q3_score": 5,
    "q4_score": 4,
    "free_text": "Optional — anything you want to share about team wellbeing"
  }'
```

The ingestion API writes the survey to the `wellbeing_surveys` table, which the
archetype classifier reads during quarterly classification.

## Response Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | yes | Must be `"1.0"` |
| `event_type` | string | yes | Must be `"wellbeing_survey"` |
| `repo` | string | yes | Repository/team identifier |
| `occurred_at` | string | yes | ISO 8601 timestamp |
| `respondent_id` | string | yes | Developer email or pseudonymous ID |
| `survey_version` | string | yes | Survey version, currently `"2025.1"` |
| `q1_score` | int | yes | 1–5 |
| `q2_score` | int | yes | 1–5 |
| `q3_score` | int | yes | 1–5 |
| `q4_score` | int | yes | 1–5 |
| `free_text` | string | no | Optional free-text response |

## Privacy & Aggregation

- Individual responses are never displayed in dashboards
- Only aggregate team scores are used for archetype classification
- Respondent IDs are stored to prevent duplicate submissions, not for individual tracking

## Schedule

The survey should be run **once per quarter**, ideally in the last two weeks
of the quarter so responses align with the quarterly archetype classification.
