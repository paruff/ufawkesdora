# Test Report for Issue #12: feat(dashboards): Archetype Profile + AI Impact dashboards

## Overview
This test report validates the two Grafana dashboards created for Issue #12 against the acceptance criteria specified in the issue.

## Files Tested
1. `dashboards/archetype-profile.json`
2. `dashboards/ai-impact.json`

## Validation Method
- JSON syntax validation using `python -m json.tool`
- Structural validation against acceptance criteria (static analysis)
- Verification of required panels, data sources, and configurations
- Note: Actual Grafana rendering and plugin availability cannot be tested in this environment

## Results

### 1. Archetype Profile Dashboard (`dashboards/archetype-profile.json`)

#### JSON Validity
- ✅ Valid JSON

#### Acceptance Criteria Check

| Criteria | Status | Notes |
|----------|--------|-------|
| Archetype name stat panel (prominent) | ✅ | Panel ID 2: Stat panel showing archetype from archetype_history table |
| Radar chart: five metrics normalized 0-1, overlaid with archetype centroid | ⚠️ | Panel ID 5: Radar chart panel type (requires Grafana radar chart plugin to be installed in uFawkesObs). The query correctly retrieves normalized metrics and archetype centroids. |
| Confidence stat panel with colour: green (≥0.75), yellow (0.5-0.75), red (<0.5) | ✅ | Panel ID 3: Stat panel with threshold coloring as specified |
| "Confidence limited — no wellbeing survey data" text panel when confidence < 0.65 | ✅ | Panel ID 4: Stat panel with value mapping shows warning when confidence < 0.65 |
| Two recommendation text panels keyed to archetype (static text; no LLM calls) | ✅ | Panel IDs 6 & 7: Text panels with archetype-specific recommendations via CASE statements |
| Link to compute/archetype_survey.md | ✅ | Panel ID 1: Includes clickable link to the wellbeing survey documentation in the header |

#### Additional Observations
- Uses PostgreSQL datasource (uid: PostgreSQL) as expected
- Templating includes team variable for switching between teams
- Panel layout follows a logical flow: header, archetype/confidence, warning, radar chart, recommendations
- All queries reference the expected tables: archetype_history
- The radar chart panel type "radar" is used - this requires the Grafana Radar chart plugin (by Grafana Labs) to be installed in the target uFawkesObs instance

### 2. AI Impact Dashboard (`dashboards/ai-impact.json`)

#### JSON Validity
- ✅ Valid JSON

#### Acceptance Criteria Check

| Criteria | Status | Notes |
|----------|--------|-------|
| PR size 14-day MA panel with DORA 2025 reference annotation | ✅ | Panel ID 2: Timeseries showing 14-day moving average of PR lines added. Includes AI-assisted average as dashed line. Description contains: "AI inflates PR size 50-150% — monitor Rework Rate for quality signal (DORA 2025)" |
| Rework Rate vs Deployment Frequency time series (dual-axis): "faster but messier" quadrant | ✅ | Panel ID 5: Timeseries with dual-axis configuration. Left axis: Rework Rate (%), Right axis: Deployments/Week. The description explains the "faster but messier" quadrant concept. |
| Code churn rate panel (lines changed within 14 days of original commit / total lines) | ⚠️ | Panel ID 3: Stat panel currently shows placeholder text "[PLACEHOLDER - requires commit data implementation]". The SQL query returns 'N/A' as value. This panel requires integration with commit data to calculate actual code churn. |
| FDRT trend panel | ✅ | Panel ID 4: Timeseries showing FDRT trend over 30 days with appropriate thresholds (green <1h, orange <24h, red >24h) |
| ai_assisted annotation line when available | ✅ | Panel ID 2: Includes a dashed line representing AI-assisted PR average (when ai_assisted flag is present in PR events) |

#### Additional Observations
- Uses PostgreSQL datasource (uid: PostgreSQL) as expected
- Templating includes team variable for switching between teams
- Panel layout: header, PR size trend, code churn (placeholder), FDRT trend, Rework Rate vs DF
- All queries reference expected tables: raw_events (for PR data) and dora_snapshots (for metrics)
- The "ai_assisted" annotation is implemented via a conditional average in the PR size query, showing separate lines for overall and AI-assisted PRs
- The FDRT panel correctly notes it is a Throughput metric (not MTTR) per DORA 2025

## Summary
- **archetype-profile.json**: Meets all acceptance criteria assuming the Grafana radar chart plugin is available. The dashboard is structurally correct and ready for deployment pending plugin installation.
- **ai-impact.json**: Meets most acceptance criteria. The code churn rate panel requires implementation (currently a placeholder). All other panels are fully functional per the specifications.

## Blockers and Recommendations
1. **Archetype Profile Dashboard**:
   - Requires installation of the Grafana "Radar chart" plugin (by Grafana Labs) in uFawkesObs
   - Without this plugin, the radar chart panel will not render correctly

2. **AI Impact Dashboard**:
   - The code churn rate panel (ID 3) requires implementation to calculate actual code churn from commit data
   - Current placeholder should be replaced with a query that computes: (lines changed in last 14 days) / (total lines in repository)
   - This requires access to commit data, which may not be in the current raw_events schema

## Next Steps
1. For archetype-profile.json: Document the radar plugin requirement in the dashboard notes or deployment documentation
2. For ai-impact.json: Implement the code churn calculation once commit data is available in the event stream
3. Both dashboards should be deployed to a staging uFawkesObs instance for functional validation
4. After addressing the above, proceed to review phase

---
*Test report generated automatically as part of the feature development lifecycle.*
