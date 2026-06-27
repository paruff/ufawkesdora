# Alert Routing Configuration for DORA Notifications

To properly route DORA alerts to Slack as specified in Issue #13, the following Alertmanager configuration should be added to the `uFawkesObs` repository.

## Overview

Issue #13 requires that DORA regression alerts and leading indicator alerts be routed to a dedicated Slack webhook (`DORA_SLACK_WEBHOOK_URL`) separate from other alert channels.

## Alert Categories

Based on the alert rules in this repository:

### DORA Regression Alerts
These alerts have labels indicating their category:
- `alertname`: Matches `DoraDeploymentFrequencyDrop`, `DoraLeadTimeIncreased`, `DOSpike`, `DoraCFRSpike`, `DoraReworkRateClimb`
- `category`: `dora_throughput` (for Deployment Frequency, Lead Time, FDRT) or `dora_stability` (for CFR, Rework Rate)

### Leading Indicator Alerts
These alerts have:
- `alertname`: Matches `DoraLeadingIndicatorPRCycle`, `DoraLeadingIndicatorPRSize`, `DoraLeadingIndicatorCIDuration`, `DoraLeadingIndicatorReworkTrend`, `DoraLeadingIndicatorBranchAge`
- `category`: `leading_indicator`

## Required Alertmanager Configuration

In the `uFawkesObs` repository, the Alertmanager configuration file (typically `alertmanager.yaml` or similar) should include:

```yaml
route:
  # Default route for non-DORA alerts
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service']

  routes:
    # Route DORA alerts to Slack
    - match_re:
        category: '(dora_.*|leading_indicator)'
      receiver: 'dora-slack'
      continue: true  # Continue to child routes if needed

    # ... other routes for infrastructure alerts, etc.

receivers:
  - name: 'default-receiver'
    # Existing receivers for non-DORA alerts (email, PagerDuty, etc.)

  - name: 'dora-slack'
    slack_configs:
      - api_url: '${DORA_SLACK_WEBHOOK_URL}'
        send_resolved: true
        title: '{{ .CommonLabels.alertname }}'
        text: |
          *Alert:* {{ .CommonLabels.alertname }}
          *Metric:* {{ .CommonLabels.metric_name }}
          *Current Value:* {{ .Value }}
          *30d Baseline:* {{ .Annotations.baseline_value }}
          *Change:* {{ if gt (sub .Value .Annotations.baseline_value) 0 }}▲{{ else }}▼{{ end }} {{ printf "%.1f" (math.Abs (sub .Value .Annotations.baseline_value)) | printf "%.1f" }}%
          *Timeline:* {{ .Annotations.duration }}
          <{{ .Annotations.runbook_url }}|View Runbook>
```

## Environment Variables

The following environment variable must be set in the `uFawkesObs` deployment:

- `DORA_SLACK_WEBHOOK_URL`: The Slack webhook URL for DORA alerts only

## Implementation Notes

1. The `continue: true` directive allows the alert to continue matching subsequent child routes if more specific routing is needed within the DORA category.

2. The slack configuration uses templating to access:
   - `.CommonLabels.alertname` - The alert name (e.g., DoraDeploymentFrequencyDrop)
   - `.CommonLabels.metric_name` - Should be added to alert rules if not present
   - `.Value` - The current value of the alert
   - `.Annotations.baseline_value` - The 30-day baseline value for comparison
   - `.Annotations.duration` - How long the condition has been true
   - `.Annotations.runbook_url` - Link to the runbook

3. To make this work with the existing alert rules in this repository, the alert rules should include these labels:
   ```yaml
   labels:
     category: "dora_throughput"  # or "dora_stability" or "leading_indicator"
   annotations:
     metric_name: "Deployment Frequency"  # Human-readable name
     baseline_value: "{{ <baseline query> }}"
     duration: "{{ $duration }}"
     runbook_url: "https://github.com/paruff/uFawkesDORA/blob/main/docs/runbooks/<name>.md"
   ```

## Testing the Configuration

To verify the routing works correctly:

1. Use `amtool` to test routing:
   ```bash
   amtool test rules alerts/*.yaml
   amtool test notify config/<alertmanager>.yml
   ```

2. Verify that:
   - Non-DORA alerts go to existing channels (email, PagerDuty, etc.)
   - DORA regression alerts go to the DORA Slack channel
   - Leading indicator alerts go to the DORA Slack channel
   - Respected alerts are properly silenced or routed accordingly

## Related Files in this Repository

- `alerts/dora-regression.yaml` - Contains the five DORA regression alerts
- `alerts/leading-indicator.yaml` - Contains leading indicator alerts
- `notifications/slack/slack_webhook.py` - Utility for sending formatted messages to Slack
