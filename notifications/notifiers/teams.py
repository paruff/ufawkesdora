"""
Microsoft Teams notification provider implementation.
Example showing how other platforms can be integrated.
"""

import logging

import aiohttp

from .base import NotificationProvider

logger = logging.getLogger(__name__)


class TeamsNotificationProvider(NotificationProvider):
    """Microsoft Teams notification provider using incoming webhooks."""

    def __init__(self, webhook_url: str):
        """
        Initialize Teams notification provider.

        Args:
            webhook_url: Teams incoming webhook URL
        """
        self.webhook_url = webhook_url

    async def send_message(self, message: str, **kwargs) -> bool:
        """
        Send a simple text message to Teams.

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
                if response.status in (200, 202):  # Teams accepts 200 or 202
                    logger.info("Message sent to Teams successfully")
                    return True
                else:
                    text = await response.text()
                    logger.error(f"Failed to send message to Teams: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending message to Teams: {e}", exc_info=True)
            return False

    async def send_notification(self, title: str, content: str, **kwargs) -> bool:
        """
        Send a formatted notification to Teams using Office 365 connector card format.

        Args:
            title: Notification title
            content: Notification content
            **kwargs: Additional parameters:
                - facts: List of dict with 'name' and 'value' for facts section
                - theme_color: Theme color (hex code without #, default: "0076D7")
                - markdown: Whether to support markdown (limited in Teams)

        Returns:
            True if notification was sent successfully, False otherwise
        """
        # Extract optional parameters
        facts = kwargs.get("facts", [])
        theme_color = kwargs.get("theme_color", "0076D7")  # Default blue

        # Build facts array for Teams card
        facts_array = []
        for fact in facts:
            facts_array.append(
                {"name": f"{fact.get('name', '')}:", "value": str(fact.get("value", ""))}
            )

        # Create the Office 365 connector card payload
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": title,
            "themeColor": theme_color,
            "title": title,
            "text": content,
            "sections": [],
        }

        # Add facts section if provided
        if facts:
            payload["sections"].append({"activityTitle": "Details", "facts": facts_array})

        # Markdown note: Teams has limited markdown support in cards
        # For full markdown, would need to use different card types or HTML

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as response,
            ):
                if response.status in (200, 202):  # Teams accepts 200 or 202
                    logger.info("Notification sent to Teams successfully")
                    return True
                else:
                    text = await response.text()
                    logger.error(
                        f"Failed to send notification to Teams: {response.status} - {text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Error sending notification to Teams: {e}", exc_info=True)
            return False


# Factory function for easy instantiation
def create_teams_provider(webhook_url: str) -> TeamsNotificationProvider:
    """
    Create a Teams notification provider.

    Args:
        webhook_url: Teams incoming webhook URL

    Returns:
        Configured TeamsNotificationProvider instance
    """
    return TeamsNotificationProvider(webhook_url)
