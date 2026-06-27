#!/usr/bin/env python3
"""
Test script demonstrating the notification system.

Shows how to use the generic notification provider system with
different platforms (Slack, Teams, etc.).
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the notifications directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from notifications.notifiers.base import NotificationManager
from notifications.notifiers.slack import SlackNotificationProvider
from notifications.notifiers.teams import TeamsNotificationProvider


async def test_notification_system():
    """Test the notification system with mock webhooks."""

    # Create notification manager
    manager = NotificationManager()

    # Add providers (using placeholder URLs for demo)
    # In real usage, these would come from environment variables or config
    slack_provider = SlackNotificationProvider(
        "https://hooks.slack.com/services/PLACEHOLDER/SLACK/WEBHOOK"
    )
    teams_provider = TeamsNotificationProvider(
        "https://outlook.office.com/webhook/PLACEHOLDER/TEAMS/WEBHOOK"
    )

    manager.add_provider(slack_provider)
    manager.add_provider(teams_provider)

    print("Testing notification system...")
    print(f"Registered providers: {[p.__class__.__name__ for p in manager.providers]}")

    # Test sending a simple message
    print("\n1. Testing simple message sending:")
    results = await manager.send_message(
        "This is a test message from the DORA notification system!",
        # Note: In real usage, you might pass platform-specific params here
    )

    for _, (provider, result) in enumerate(zip(manager.providers, results, strict=True)):
        status = "✅ Sent" if result else "❌ Failed"
        print(f"   {provider.__class__.__name__}: {status}")

    # Test sending a formatted notification
    print("\n2. Testing formatted notification:")
    results = await manager.send_notification(
        title="DORA Alert: Deployment Frequency Drop",
        content="Deployment frequency has dropped significantly below the 30-day baseline.",
        fields=[
            {"title": "Current Value", "value": "1.2 deploys/week"},
            {"title": "30-Day Baseline", "value": "3.5 deploys/week"},
            {"title": "Change", "value": "-65%"},
            {"title": "Trend", "value": "📉 Decreasing"},
        ],
    )

    for _, (provider, result) in enumerate(zip(manager.providers, results, strict=True)):
        status = "✅ Sent" if result else "❌ Failed"
        print(f"   {provider.__class__.__name__}: {status}")

    # Show how to use individual providers
    print("\n3. Testing individual provider usage:")

    # Slack-specific usage
    slack_result = await slack_provider.send_notification(
        title="Weekly DORA Digest",
        content="Your weekly DORA digest is ready for review.",
        fields=[
            {"title": "Deployment Frequency", "value": "2.5 ✅"},
            {"title": "Lead Time", "value": "4.2 hours ⚠️"},
            {"title": "Focus This Week", "value": "Reduce PR size to improve lead time"},
        ],
        color="#36a64f",  # Green color
    )
    print(f"   Slack notification: {'✅ Sent' if slack_result else '❌ Failed'}")

    # Teams-specific usage
    teams_result = await teams_provider.send_notification(
        title="DORA Metrics Summary",
        content="Here's your weekly DORA metrics summary.",
        facts=[
            {"name": "Deployment Frequency", "value": "2.5 deploys/week"},
            {"name": "Lead Time", "value": "4.2 hours"},
            {"name": "Change Failure Rate", "value": "2.1%"},
        ],
        theme_color="0076D7",  # Teams blue
    )
    print(f"   Teams notification: {'✅ Sent' if teams_result else '❌ Failed'}")


async def test_with_env_vars():
    """Test using environment variables for configuration."""
    print("\n4. Testing with environment variables:")

    # Set demo environment variables
    os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/PLACEHOLDER/SLACK/WEBHOOK"
    os.environ["TEAMS_WEBHOOK_URL"] = "https://outlook.office.com/webhook/PLACEHOLDER/TEAMS/WEBHOOK"

    # Create providers from environment
    slack_provider = SlackNotificationProvider(os.environ.get("SLACK_WEBHOOK_URL"))
    teams_provider = TeamsNotificationProvider(os.environ.get("TEAMS_WEBHOOK_URL"))

    manager = NotificationManager()
    manager.add_provider(slack_provider)
    manager.add_provider(teams_provider)

    print(
        f"   Created providers from env vars: {[p.__class__.__name__ for p in manager.providers]}"
    )

    # Test message
    results = await manager.send_message("Test from environment variable configuration")
    for _, (provider, result) in enumerate(zip(manager.providers, results, strict=True)):
        status = "✅ Sent" if result else "❌ Failed"
        print(f"     {provider.__class__.__name__}: {status}")


def show_usage_examples():
    """Show usage examples for developers."""
    print("\n" + "=" * 60)
    print("USAGE EXAMPLES FOR DEVELOPERS")
    print("=" * 60)

    print(
        """
# 1. Simple usage with Slack webhook
from notifications.notifiers.slack import SlackNotificationProvider

provider = SlackNotificationProvider("https://hooks.slack.com/services/...")
await provider.send_message("Hello from DORA!")

# 2. Using the notification manager for multiple platforms
from notifications.notifiers.base import NotificationManager
from notifications.notifiers.slack import SlackNotificationProvider
from notifications.notifiers.teams import TeamsNotificationProvider

manager = NotificationManager()
manager.add_provider(SlackNotificationProvider(slack_url))
manager.add_provider(TeamsNotificationProvider(teams_url))

# Send to all platforms simultaneously
results = await manager.send_notification(
    title="Alert: Deployment Frequency Drop",
    content="Deployment frequency is below baseline.",
    fields=[{"title": "Current", "value": "1.2/wk"}, {"title": "Baseline", "value": "3.5/wk"}]
)

# 3. Extending to other platforms
# To add support for Discord, Mattermost, etc., create a new class:
#
# class DiscordNotificationProvider(NotificationProvider):
#     def __init__(self, webhook_url: str):
#         self.webhook_url = webhook_url
#
#     async def send_message(self, message: str, **kwargs) -> bool:
#         # Discord webhook payload format
#         payload = {"content": message}
#         # ... send to Discord webhook
#
#     async def send_notification(self, title: str, content: str, **kwargs) -> bool:
#         # Discord embed format
#         payload = {
#             "embeds": [{
#                 "title": title,
#                 "description": content,
#                 "color": 0x00ff00  # Green
#             }]
#         }
#         # ... send to Discord webhook
"""
    )


async def main():
    """Main test function."""
    print("DORA Notification System Test")
    print("=" * 40)

    await test_notification_system()
    await test_with_env_vars()
    show_usage_examples()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
