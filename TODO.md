# Issue #13: Notifications - Weekly Slack Digest + Regression Alerts to Slack

## Tasks

- [x] Create notifications/digest/generate_digest.py
- [x] Create notifications/slack/slack_webhook.py
- [x] Create GitHub workflow for weekly digest (Monday 8am UTC)
- [x] Test digest generation with sample data
- [x] Test Slack webhook integration
- [x] Document usage in README
- [x] Add any necessary tests
- [x] Created extensible notification provider system
- [x] Added Slack and Teams provider examples
- [x] Created notification manager for multiple providers

## Acceptance Criteria

### Weekly Digest
- [x] notifications/digest/generate_digest.py - queries latest dora_snapshots from Postgres, produces structured weekly digest
- [x] Digest content (per repo): five metrics current vs prior week, ✅/⚠️/❌ per metric, one "Focus this week" recommendation (worst-trending metric), Grafana link
- [x] Markdown output: notifications/digest/weekly-digest-YYYY-WW.md
- [x] notifications/slack/slack_webhook.py - posts digest to SLACK_WEBHOOK_URL; gracefully skips with logged warning if not configured
- [x] .github/workflows/weekly-digest.yml - runs Monday 8am UTC; manual dispatch also supported

### Alert Routing
- [x] Alertmanager routes: block in uFawkesObs routes dora_regression and leading_indicator alerts to a DORA_SLACK_WEBHOOK_URL distinct from other alert channels
- [x] Alert Slack message format: metric name, current value, 30d baseline, trend emoji, runbook link — NOT a wall of text
- [x] Evidence: inject a metric regression via synthetic Prometheus data → alert fires → Slack message received within 5 minutes

## Extensible Notification System
- [x] Created abstract NotificationProvider base class
- [x] Implemented SlackNotificationProvider
- [x] Added TeamsNotificationProvider as example extensibility
- [x] Created NotificationManager to handle multiple providers
- [x] Made system easy to extend to other platforms (Discord, Mattermost, email, SMS, etc.)

## Progress
All tasks for Issue #13 have been completed. The notification system provides:

1. **Weekly Digest Generator** - Creates formatted markdown digests comparing current vs prior week DORA metrics
2. **Flexible Notification System** - Abstract provider system allowing easy integration with any chat/platform
3. **Slack Integration** - Both webhook-based (slack_webhook.py) and provider-based (slack.py) implementations
4. **GitHub Actions Workflow** - Automated weekly delivery every Monday at 8:00 AM UTC
5. **Documentation** - Clear usage instructions and extensibility guidelines

The system is designed to be easily extended to support other team communication tools beyond Slack, fulfilling the requirement that "it might not be slack, [it] could be any team communication/chat tooling."
