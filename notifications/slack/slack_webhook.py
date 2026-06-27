#!/usr/bin/env python3
"""
Slack webhook notification sender for DORA digests and alerts.

This module provides a simple interface for sending messages to Slack via
incoming webhooks. It's designed to be used by the digest generator and
Alertmanager for sending notifications.

Note: While this implementation is Slack-specific, the underlying webhook
mechanism can be adapted for other chat platforms by modifying the payload
format. See notifications/notifiers/ for a more generic notification system.
"""

import logging
import os

import aiohttp

logger = logging.getLogger("ufawkesdora.notifications.slack")


class SlackWebhook:
    """
    Client for sending messages to Slack via incoming webhook.

    Simple wrapper that sends JSON payloads to a Slack webhook URL.
    Handles basic error cases and logging.
    """

    def __init__(self, webhook_url: str | None = None):
        """
        Initialize Slack webhook client.

        Args:
            webhook_url: Slack webhook URL. If not provided, reads from
                        SLACK_WEBHOOK_URL environment variable.
        """
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured. Notifications will be skipped.")

    async def send(self, message: str) -> bool:
        """
        Send a simple text message to Slack.

        Args:
            message: The text message to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.debug("Skipping Slack notification: no webhook URL configured")
            return False

        payload = {"text": message}

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as response,
            ):
                if response.status == 200:
                    response_text = await response.text()
                    if response_text == "ok":
                        logger.info("Message sent to Slack successfully")
                        return True
                    else:
                        logger.warning(
                            f"Unexpected Slack response: {response.status} - {response_text}"
                        )
                        return False
                else:
                    response_text = await response.text()
                    logger.error(
                        f"Failed to send message to Slack: {response.status} - {response_text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Error sending message to Slack: {e}")
            return False

    async def send_blocks(self, blocks: list[dict]) -> bool:
        """
        Send a message with Block Kit formatting to Slack.

        Args:
            blocks: List of Block Kit block objects

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.debug("Skipping Slack notification: no webhook URL configured")
            return False

        payload = {"blocks": blocks}

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as response,
            ):
                if response.status == 200:
                    response_text = await response.text()
                    if response_text == "ok":
                        logger.info("Block message sent to Slack successfully")
                        return True
                    else:
                        logger.warning(
                            f"Unexpected Slack response: {response.status} - {response_text}"
                        )
                        return False
                else:
                    response_text = await response.text()
                    logger.error(
                        f"Failed to send block message to Slack: {response.status} - {response_text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Error sending block message to Slack: {e}")
            return False

    async def send_digest_notification(self, digest_content: str, digest_file_path: str) -> bool:
        """
        Send a notification that a digest has been generated.

        Sends a brief message indicating the digest is available since
        the full digest is stored in a file.

        Args:
            digest_content: The full digest content (for reference)
            digest_file_path: Path to where the digest was saved

        Returns:
            True if notification sent successfully
        """
        if not self.webhook_url:
            logger.debug("Skipping Slack digest notification: no webhook URL configured")
            return False

        # Extract title from digest content
        lines = digest_content.split("\n")
        title_line = next((line for line in lines if line.startswith("# ")), "Weekly DORA Digest")
        title = title_line[2:] if title_line.startswith("# ") else "Weekly DORA Digest"

        # Extract time period if available
        week_line = next((line for line in lines if "*Week of" in line and "*" in line), "")

        message = (
            f"*{title}*\nThe latest digest has been generated and saved to:\n`{digest_file_path}`\n"
        )
        if week_line:
            # Clean up markdown formatting
            clean_week = week_line.strip("*")
            message += f"{clean_week}\n"

        message += f"_Generated: {self._get_timestamp()}_"

        return await self.send(message)

    async def send_alert_notification(
        self,
        alert_name: str,
        metric_name: str,
        current_value: float,
        baseline_value: float,
        trend_emoji: str,
        runbook_url: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> bool:
        """
        Send a formatted alert notification to Slack.

        Args:
            alert_name: Name of the alert (e.g., DoraDeploymentFrequencyDrop)
            metric_name: Human-readable metric name
            current_value: Current value of the metric
            baseline_value: 30-day baseline value
            trend_emoji: Emoji indicating trend (📈, 📉, →)
            runbook_url: URL to runbook for this alert
            labels: Optional alert labels from Alertmanager
            annotations: Optional alert annotations from Alertmanager

        Returns:
            True if notification sent successfully
        """
        if not self.webhook_url:
            logger.debug("Skipping Slack alert notification: no webhook URL configured")
            return False

        # Calculate change percentage
        if baseline_value == 0:
            change_pct = 0.0
            change_str = "N/A"
        else:
            change_pct = ((current_value - baseline_value) / abs(baseline_value)) * 100
            if abs(change_pct) >= 0.01:  # Avoid showing 0.0% for tiny changes
                sign = "+" if change_pct > 0 else ""
                change_str = f"{sign}{change_pct:.1f}%"
            else:
                change_str = "0.0%"

        # Format values based on metric type
        formatted_current = self._format_metric_value(metric_name, current_value)
        formatted_baseline = self._format_metric_value(metric_name, baseline_value)

        # Build Slack blocks for rich formatting
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":rotating_light: DORA Alert: {alert_name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Metric:*\n{metric_name}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Current Value:*\n{formatted_current}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*30d Baseline:*\n{formatted_baseline}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Change:*\n{trend_emoji} {change_str}",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<{runbook_url}|View Runbook>",
                    }
                ],
            },
        ]

        # Add labels if provided
        if labels:
            label_text = ", ".join([f"{k}: {v}" for k, v in labels.items()])
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Labels:* {label_text}",
                        }
                    ],
                }
            )

        # Add annotations if provided
        if annotations:
            annotation_text = "; ".join([f'{k}: "{v}"' for k, v in annotations.items()])
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Details:* {annotation_text}",
                        }
                    ],
                }
            )

        # Fallback text for notifications
        fallback_text = (
            f"DORA Alert: {alert_name}\n"
            f"Metric: {metric_name}\n"
            f"Current: {formatted_current}\n"
            f"Baseline: {formatted_baseline}\n"
            f"Change: {trend_emoji} {change_str}\n"
            f"Runbook: {runbook_url}"
        )

        # Try to send with blocks, fall back to plain text if needed
        try:
            return await self.send_blocks(blocks)
        except Exception as e:
            logger.error(f"Error sending Slack block message: {e}")
            # Fall back to simple text message
            return await self.send(fallback_text)

    def _format_metric_value(self, metric_name: str, value: float) -> str:
        """Format a metric value for display based on its type."""
        metric_name_lower = metric_name.lower()
        if "frequency" in metric_name_lower or "deployment" in metric_name_lower:
            return f"{value:.2f} deploys/week"
        elif "time" in metric_name_lower or "hour" in metric_name_lower:
            return f"{value:.1f} hours"
        elif "rate" in metric_name_lower or "percent" in metric_name_lower:
            return f"{value * 100:.1f}%"
        else:
            return f"{value:.2f}"

    def _get_timestamp(self) -> str:
        """Get current timestamp string for display."""
        from datetime import UTC, datetime

        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


# Convenience functions for backward compatibility and ease of use


async def send_slack_message(webhook_url: str, message: str) -> bool:
    """
    Send a simple message to Slack webhook.

    Args:
        webhook_url: Slack webhook URL
        message: Message text to send

    Returns:
        True if sent successfully
    """
    webhook = SlackWebhook(webhook_url)
    return await webhook.send(message)


async def send_slack_digest_notification(
    webhook_url: str, digest_content: str, digest_file_path: str
) -> bool:
    """
    Send a digest availability notification to Slack.

    Args:
        webhook_url: Slack webhook URL
        digest_content: Full digest content
        digest_file_path: Path to saved digest file

    Returns:
        True if sent successfully
    """
    webhook = SlackWebhook(webhook_url)
    return await webhook.send_digest_notification(digest_content, digest_file_path)


async def send_slack_alert_notification(
    webhook_url: str,
    alert_name: str,
    metric_name: str,
    current_value: float,
    baseline_value: float,
    trend_emoji: str,
    runbook_url: str,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> bool:
    """
    Send a formatted alert notification to Slack.

    Args:
        webhook_url: Slack webhook URL
        alert_name: Name of the alert
        metric_name: Human-readable metric name
        current_value: Current value of the metric
        baseline_value: 30-day baseline value
        trend_emoji: Trend emoji indicator
        runbook_url: URL to runbook
        labels: Optional alert labels
        annotations: Optional alert annotations

    Returns:
        True if sent successfully
    """
    webhook = SlackWebhook(webhook_url)
    return await webhook.send_alert_notification(
        alert_name=alert_name,
        metric_name=metric_name,
        current_value=current_value,
        baseline_value=baseline_value,
        trend_emoji=trend_emoji,
        runbook_url=runbook_url,
        labels=labels,
        annotations=annotations,
    )


if __name__ == "__main__":
    # Simple test when run directly
    import asyncio

    async def test():
        import os

        if "SLACK_WEBHOOK_URL" in os.environ:
            webhook = SlackWebhook()
            await webhook.send("Test message from DORA notifications")
            print("✅ Test message sent!")
        else:
            print("⚠️  Set SLACK_WEBHOOK_URL environment variable to test")

    asyncio.run(test())
