"""
Slack notification provider implementation.
"""

import logging

import aiohttp

from .base import NotificationProvider

logger = logging.getLogger(__name__)


class SlackNotificationProvider(NotificationProvider):
    """Slack notification provider using incoming webhooks."""

    def __init__(self, webhook_url: str):
        """
        Initialize Slack notification provider.

        Args:
            webhook_url: Slack incoming webhook URL
        """
        self.webhook_url = webhook_url

    async def send_message(self, message: str, **kwargs) -> bool:
        """
        Send a simple text message to Slack.

        Args:
            message: The message text to send
            **kwargs: Additional parameters (ignored for basic message)

        Returns:
            True if message was sent successfully, False otherwise
        """
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
                    text = await response.text()
                    logger.error(f"Failed to send message to Slack: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending message to Slack: {e}", exc_info=True)
            return False

    async def send_notification(self, title: str, content: str, **kwargs) -> bool:
        """
        Send a formatted notification to Slack using Block Kit.

        Args:
            title: Notification title
            content: Notification content
            **kwargs: Additional parameters:
                - fields: List of dict with 'title' and 'value' for fields section
                - markdown: Whether to use mrkdwn formatting (default: True)
                - color: Attachment color (hex code, default: "#36a64f")

        Returns:
            True if notification was sent successfully, False otherwise
        """
        # Extract optional parameters
        fields = kwargs.get("fields", [])
        use_markdown = kwargs.get("markdown", True)
        color = kwargs.get("color", "#36a64f")

        # Format text based on markdown setting
        text_format = "mrkdwn" if use_markdown else "plain_text"

        # Build blocks for Block Kit formatting
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
            {"type": "section", "text": {"type": text_format, "text": content}},
        ]

        # Add fields if provided
        if fields:
            fields_block = {"type": "section", "fields": []}
            for field in fields:
                fields_block["fields"].append(
                    {
                        "type": text_format,
                        "text": f"*{field.get('title', '')}*\n{field.get('value', '')}",
                    }
                )
            blocks.append(fields_block)

        # Create attachment (alternative to blocks for simpler formatting)
        attachment = {"color": color, "blocks": blocks}

        payload = {"attachments": [attachment]}

        # Fallback text for notifications
        payload["text"] = f"{title}: {content}"

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
                        logger.info("Notification sent to Slack successfully")
                        return True
                    else:
                        logger.warning(
                            f"Unexpected Slack response: {response.status} - {response_text}"
                        )
                        return False
                else:
                    text = await response.text()
                    logger.error(
                        f"Failed to send notification to Slack: {response.status} - {text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Error sending notification to Slack: {e}", exc_info=True)
            return False


# Factory function for easy instantiation
def create_slack_provider(webhook_url: str) -> SlackNotificationProvider:
    """
    Create a Slack notification provider.

    Args:
        webhook_url: Slack incoming webhook URL

    Returns:
        Configured SlackNotificationProvider instance
    """
    return SlackNotificationProvider(webhook_url)
