#!/usr/bin/env python3
"""
Demo script showing how to use the notification system.
This demonstrates the concept without making actual network calls.
"""

import asyncio
import sys
from unittest.mock import patch

# Add notifications to path
sys.path.insert(0, ".")

from notifications.notifiers.base import NotificationManager
from notifications.notifiers.slack import SlackNotificationProvider
from notifications.notifiers.teams import TeamsNotificationProvider


# Mock response for aiohttp
class MockResponse:
    def __init__(self, status=200, text="ok"):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# Mock aiohttp session
class MockSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, *args, **kwargs):
        return MockResponse()


async def demo_notification_system():
    """Demonstrate the notification system with mocked network calls."""

    print("🔔 DORA Notification System Demo")
    print("=" * 50)

    # Patch aiohttp to avoid actual network calls
    with patch("aiohttp.ClientSession", return_value=MockSession()):
        # Create notification manager
        manager = NotificationManager()

        # Add providers
        slack_provider = SlackNotificationProvider("https://hooks.slack.com/demo")
        teams_provider = TeamsNotificationProvider("https://outlook.office.com/webhook/demo")

        manager.add_provider(slack_provider)
        manager.add_provider(teams_provider)

        print(f"\n✅ Registered providers: {[p.__class__.__name__ for p in manager.providers]}")

        # Demo 1: Send simple message
        print("\n📝 Demo 1: Sending simple message")
        results = await manager.send_message(
            "🚀 Deployment pipeline completed successfully!",
            # Note: In real usage, you might pass platform-specific options here
        )

        for provider, result in zip(manager.providers, results, strict=True):
            status = "✅ Sent" if result else "❌ Failed"
            print(f"   {provider.__class__.__name__}: {status}")

        # Demo 2: Send formatted notification
        print("\n📊 Demo 2: Sending formatted notification")
        results = await manager.send_notification(
            title="DORA Alert: Lead Time Increase",
            content="Lead time for changes has exceeded the 30-day baseline for 3 consecutive days.",
            fields=[
                {"title": "Current Value", "value": "32.5 hours"},
                {"title": "30-Day Baseline", "value": "18.2 hours"},
                {"title": "Change", "value": "+79%"},
                {"title": "Trend", "value": "📈 Increasing"},
            ],
        )

        for provider, result in zip(manager.providers, results, strict=True):
            status = "✅ Sent" if result else "❌ Failed"
            print(f"   {provider.__class__.__name__}: {status}")

        # Demo 3: Show how to extend to other platforms
        print("\n🔌 Demo 3: Extensibility - Adding a custom provider")
        print("   To add support for other platforms (Discord, Mattermost, etc.):")
        print("   1. Create a new class inheriting from NotificationProvider")
        print("   2. Implement send_message() and send_notification() methods")
        print("   3. Add the provider to the NotificationManager")
        print("")
        print("   Example structure:")
        print("   class DiscordNotificationProvider(NotificationProvider):")
        print("       def __init__(self, webhook_url: str):")
        print("           self.webhook_url = webhook_url")
        print("       ")
        print("       async def send_message(self, message: str, **kwargs) -> bool:")
        print("           # Implement Discord webhook call")
        print("           pass")
        print("       ")
        print(
            "       async def send_notification(self, title: str, content: str, **kwargs) -> bool:"
        )
        print("           # Implement Discord embed format")
        print("           pass")


def show_file_structure():
    """Show the created file structure."""
    print("\n📁 Created File Structure:")
    print("   notifications/")
    print("   ├── digest/")
    print("   │   └── generate_digest.py          # Weekly digest generator")
    print("   ├── notifiers/")
    print("   │   ├── __init__.py                 # Package exports")
    print("   │   ├── base.py                     # Abstract base classes")
    print("   │   ├── slack.py                    # Slack provider")
    print("   │   └── teams.py                    # Teams provider (example)")
    print("   └── slack/")
    print("       └── slack_webhook.py            # Original Slack webhook (backward compatible)")
    print("")
    print("📄 Key Files:")
    print("   • notifications/digest/generate_digest.py")
    print("   • notifications/notifiers/base.py")
    print("   • notifications/notifiers/slack.py")
    print("   • notifications/notifiers/teams.py")
    print("   • notifications/slack/slack_webhook.py")


if __name__ == "__main__":
    print("🚀 Starting DORA Notification System Demo...")

    # Run the async demo
    asyncio.run(demo_notification_system())

    # Show file structure
    show_file_structure()

    print("\n" + "=" * 50)
    print("✨ Demo completed!")
    print("The notification system is ready for use in Issue #13.")
    print("=" * 50)
