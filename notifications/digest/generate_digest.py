#!/usr/bin/env python3
"""
Weekly DORA Digest Generator.

Queries the latest DORA snapshots from PostgreSQL and generates
a weekly markdown digest showing week-over-week trends.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg

logger = logging.getLogger("ufawkesdora.notifications.digest")

# DORA 2025 metric names and their display formatting
DORA_METRICS = [
    {
        "db_column": "deployment_frequency",
        "display_name": "Deployment Frequency",
        "unit": "deploys/week",
        "format": lambda v: f"{v:.2f}",
        "higher_is_better": True,
    },
    {
        "db_column": "lead_time_hours",
        "display_name": "Lead Time for Changes",
        "unit": "hours",
        "format": lambda v: f"{v:.1f}",
        "higher_is_better": False,
    },
    {
        "db_column": "fdrt_hours",
        "display_name": "Failure Deployment Recovery Time (FDRT)",
        "unit": "hours",
        "format": lambda v: f"{v:.1f}",
        "higher_is_better": False,
    },
    {
        "db_column": "change_failure_rate",
        "display_name": "Change Failure Rate",
        "unit": "%",
        "format": lambda v: f"{v * 100:.1f}%",
        "higher_is_better": False,
    },
    {
        "db_column": "rework_rate_pct",
        "display_name": "Rework Rate",
        "unit": "%",
        "format": lambda v: f"{v * 100:.1f}%",
        "higher_is_better": False,
    },
]

# Trend thresholds (percentage change)
TREND_THRESHOLDS = {
    "improving": 5.0,  # >5% improvement
    "degrading": -5.0,  # >5% degradation (more negative)
}


class DigestDB:
    """Async PostgreSQL connection for digest generation."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        if self.dsn is None:
            raise ValueError("DATABASE_URL must be set or dsn argument provided")
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def get_latest_snapshots(
        self, team_id: str | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Get the most recent and previous week's snapshots for a team.

        Returns:
            Tuple of (latest_snapshot, previous_snapshot) as dicts,
            or (None, None) if no data found.
        """
        if not self.pool:
            await self.connect()

        # Build query conditions
        where_clause = "WHERE team_id = $1" if team_id else "WHERE 1=1"
        params = [team_id] if team_id else []

        async with self.pool.acquire() as conn:
            # Get the two most recent snapshots
            query = f"""
                SELECT *
                FROM dora_snapshots
                {where_clause}
                ORDER BY recorded_at DESC
                LIMIT 2
            """
            rows = await conn.fetch(query, *params)

            if not rows:
                return None, None
            elif len(rows) == 1:
                # Only one snapshot available
                return dict(rows[0]), None
            else:
                # Two or more snapshots available
                return dict(rows[0]), dict(rows[1])


def calculate_trend(current: float, previous: float | None) -> tuple[str, str]:
    """
    Calculate trend direction and percentage change.

    Returns:
        Tuple of (emoji, description) where emoji is one of:
        - ✅ improving (>5% improvement for positive metrics or >5% decrease for negative metrics)
        - ⚠️ stable (within ±5%)
        - ❌ degrading (>5% degradation for positive metrics or >5% increase for negative metrics)
    """
    if previous is None or previous == 0:
        return "⚠️", "no prior data"

    # Calculate percentage change
    pct_change = 0.0 if previous == 0 else ((current - previous) / abs(previous)) * 100

    # For metrics where lower is better (lead time, FDRT, CFR, Rework Rate),
    # we invert the interpretation of "improving"
    # Actually, we'll handle this in the metric config - higher_is_better flag

    # Check thresholds
    if pct_change >= TREND_THRESHOLDS["improving"]:
        return "✅", f"+{pct_change:.1f}%"
    elif pct_change <= TREND_THRESHOLDS["degrading"]:
        return "❌", f"{pct_change:.1f}%"
    else:
        return "⚠️", f"{pct_change:+.1f}%"


def determine_focus_metric(
    current: dict[str, Any], previous: dict[str, Any] | None
) -> tuple[str, str]:
    """
    Determine which metric has degraded the most (or improved the least).

    Returns:
        Tuple of (metric_display_name, reason)
    """
    if not previous:
        return "Deployment Frequency", "establishing baseline"

    worst_change = float("inf")
    worst_metric = None

    for metric in DORA_METRICS:
        col = metric["db_column"]
        current_val = current.get(col, 0)
        previous_val = previous.get(col, 0)

        if previous_val == 0:
            continue

        # Calculate percentage change
        pct_change = ((current_val - previous_val) / abs(previous_val)) * 100

        # For metrics where lower is better, we want to see negative changes as good
        # So we adjust: if higher_is_better is False, we invert the change for comparison
        if not metric["higher_is_better"]:
            pct_change = -pct_change

        # Look for the most negative change (worst performance)
        if pct_change < worst_change:
            worst_change = pct_change
            worst_metric = metric["display_name"]

    if worst_metric is None:
        return "Deployment Frequency", "no significant changes"

    # Generate reason based on actual change
    metric_cfg = next(m for m in DORA_METRICS if m["display_name"] == worst_metric)
    col = metric_cfg["db_column"]
    current_val = current.get(col, 0)
    previous_val = previous.get(col, 0)

    pct_change = (
        0 if previous_val == 0 else ((current_val - previous_val) / abs(previous_val)) * 100
    )

    if not metric_cfg["higher_is_better"]:
        pct_change = -pct_change  # Invert back for display

    if pct_change < -10 or pct_change < 0:
        reason = f"degraded {abs(pct_change):.1f}%"
    elif pct_change > 10:
        reason = f"improved {pct_change:.1f}% (but other metrics degraded more)"
    else:
        reason = f"changed {pct_change:+.1f}%"

    return worst_metric, reason


def format_metric_value(metric: dict[str, Any], value: Any) -> str:
    """Format a metric value for display."""
    formatter = metric.get("format", lambda v: str(v))
    return formatter(value)


def generate_markdown_digest(
    snapshots: tuple[dict[str, Any] | None, dict[str, Any] | None],
    team_id: str | None = None,
    grafana_url: str | None = None,
) -> str:
    """
    Generate a markdown digest from snapshot data.

    Args:
        snapshots: Tuple of (latest, previous) snapshot dicts
        team_id: Team identifier (optional)
        grafana_url: Base URL for Grafana dashboard (optional)

    Returns:
        Markdown formatted digest string
    """
    latest, previous = snapshots

    if not latest:
        return "# Weekly DORA Digest\n\nNo data available yet. Start collecting data to see your first digest.\n"

    # Determine team display
    team_display = team_id if team_id else "All Teams"

    # Header
    week_start = latest["snapshot_window_start"]
    week_end = latest["snapshot_window_end"]
    timestamp = latest["recorded_at"]

    lines = [
        f"# Weekly DORA Digest - {team_display}",
        "",
        f"*Week of {week_start.strftime('%B %d, %Y')} to {week_end.strftime('%B %d, %Y')}*",
        f"*Generated: {timestamp.strftime('%B %d, %Y at %I:%M %p UTC')}*",
        "",
    ]

    if grafana_url:
        lines.append(f"[View Full Dashboard]({grafana_url})")
        lines.append("")

    lines.append("## Metrics Overview")
    lines.append("")
    lines.append("| Metric | Current | Prior Week | Trend |")
    lines.append("|--------|---------|------------|-------|")

    # Track trends for focus determination
    metric_trends = []

    for metric in DORA_METRICS:
        col = metric["db_column"]
        current_val = latest.get(col)
        prior_val = previous.get(col) if previous else None

        # Format values
        current_str = format_metric_value(metric, current_val) if current_val is not None else "N/A"
        prior_str = format_metric_value(metric, prior_val) if prior_val is not None else "N/A"

        # Calculate trend
        if current_val is not None and prior_val is not None and prior_val != 0:
            emoji, trend_str = calculate_trend(current_val, prior_val)
            # Store for focus determination (use raw values for calculation)
            metric_trends.append(
                {
                    "name": metric["display_name"],
                    "current": current_val,
                    "prior": prior_val,
                    "higher_is_better": metric["higher_is_better"],
                }
            )
        else:
            emoji, trend_str = "⚠️", "N/A"

        lines.append(
            f"| {metric['display_name']} | {current_str} | {prior_str} | {emoji} {trend_str} |"
        )

    lines.append("")
    lines.append("## Focus This Week")
    lines.append("")

    if previous:
        focus_metric, reason = determine_focus_metric(latest, previous)
        lines.append(f"**{focus_metric}** - {reason}")
    else:
        lines.append("Establishing baseline - continue collecting data!")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This digest is generated automatically from your DORA metrics.*")
    lines.append("*To learn more about improving these metrics, see the DORA documentation.*")

    return "\n".join(lines)


def write_digest_to_file(content: str, team_id: str | None = None) -> str:
    """
    Write digest content to a file.

    Returns:
        Path to the written file
    """
    # Create notifications/digest directory if it doesn't exist
    os.makedirs("notifications/digest", exist_ok=True)

    # Generate filename: weekly-digest-YYYY-WW.md
    now = datetime.now(UTC)
    year_week = now.strftime("%Y-%W")  # Year-Week number
    team_suffix = f"-{team_id}" if team_id else ""
    filename = f"notifications/digest/weekly-digest{team_suffix}-{year_week}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Digest written to {filename}")
    return filename


async def send_notifications(
    digest_content: str, digest_file_path: str, slack_webhook: str | None = None
) -> None:
    """
    Send notifications about the generated digest.

    Args:
        digest_content: The full digest content
        digest_file_path: Path to where the digest was saved
        slack_webhook: Optional Slack webhook URL for backward compatibility
    """
    # Import notification providers
    try:
        from notifications.notifiers.base import NotificationManager
        from notifications.notifiers.slack import SlackNotificationProvider
    except ImportError as e:
        logger.warning(f"Could not import notification providers: {e}")
        # Fallback to legacy Slack-only behavior if new system not available
        if slack_webhook:
            await _legacy_post_to_slack(digest_content, slack_webhook)
        return

    # Create notification manager and add Slack provider if webhook provided
    manager = NotificationManager()

    if slack_webhook:
        try:
            slack_provider = SlackNotificationProvider(slack_webhook)
            manager.add_provider(slack_provider)
            logger.info("Added Slack notification provider")
        except Exception as e:
            logger.warning(f"Failed to initialize Slack provider: {e}")

    # If no providers were added (no webhook or import failed), log and return
    if len(manager.providers) == 0:
        logger.info("No notification providers configured - digest saved to file only")
        return

    # Send notification via all configured providers
    try:
        results = await manager.send_notification(
            title="Weekly DORA Digest Generated",
            content=f"The latest digest has been generated and saved to `{digest_file_path}`. "
            f"Check the file for the complete week-over-week analysis.",
        )

        # Log results
        for _, (provider, result) in enumerate(zip(manager.providers, results, strict=True)):
            status = "✅ Sent" if result else "❌ Failed"
            logger.info(f"Notification via {provider.__class__.__name__}: {status}")

    except Exception as e:
        logger.error(f"Error sending notifications: {e}")
        # Fallback to legacy Slack if specified
        if slack_webhook:
            await _legacy_post_to_slack(digest_content, slack_webhook)


async def _legacy_post_to_slack(content: str, webhook_url: str) -> None:
    """Legacy Slack posting function for backward compatibility."""
    from datetime import UTC

    import aiohttp

    # Slack has a message size limit, so we'll send a summary
    summary = (
        f"*Weekly DORA Digest Generated*\n"
        f"The latest digest has been generated and saved to `notifications/digest/`.\n"
        f"Check the file for the complete week-over-week analysis.\n"
        f"*Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}*"
    )

    payload = {"text": summary}

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(webhook_url, json=payload) as response,
        ):
            if response.status == 200:
                response_text = await response.text()
                if response_text == "ok":
                    logger.info("Legacy Slack notification sent successfully")
                else:
                    logger.warning(
                        f"Unexpected Slack response: {response.status} - {response_text}"
                    )
            else:
                response_text = await response.text()
                logger.error(
                    f"Failed to send message to Slack: {response.status} - {response_text}"
                )
    except Exception as e:
        logger.error(f"Error sending legacy Slack notification: {e}")


async def main():
    """Main entry point for digest generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate weekly DORA digest")
    parser.add_argument("--team", help="Team ID to generate digest for (default: all teams)")
    parser.add_argument(
        "--grafana-url",
        help="Base URL for Grafana dashboard links",
        default="http://localhost:3000",
    )
    parser.add_argument(
        "--output",
        help="Output file path (if not specified, uses weekly-digest-YYYY-WW.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print digest to stdout instead of writing to file",
    )
    parser.add_argument(
        "--slack-webhook",
        help="Slack webhook URL to post digest notification to",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        async with DigestDB() as db:
            latest, previous = await db.get_latest_snapshots(team_id=args.team)

            # Generate markdown
            markdown = generate_markdown_digest(
                snapshots=(latest, previous),
                team_id=args.team,
                grafana_url=args.grafana_url,
            )

            if args.dry_run or args.output:
                if args.dry_run:
                    print("\n" + "=" * 60)
                    print("WEEKLY DORA DIGEST (DRY-RUN)")
                    print("=" * 60)
                    print(markdown)
                    print("=" * 60 + "\n")
                else:
                    # Write to specified output file
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(markdown)
                    logger.info(f"Digest written to {args.output}")

                    # Send notifications if output file specified
                    if args.output:
                        await send_notifications(
                            digest_content=markdown,
                            digest_file_path=args.output,
                            slack_webhook=args.slack_webhook,
                        )
            else:
                # Write to default location
                filename = write_digest_to_file(markdown, team_id=args.team)
                print(f"✅ Digest written to {filename}")

                # Send notifications
                await send_notifications(
                    digest_content=markdown,
                    digest_file_path=filename,
                    slack_webhook=args.slack_webhook,
                )

    except Exception as e:
        logger.error(f"Failed to generate digest: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
