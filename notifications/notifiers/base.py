"""
Base classes for notification providers.
"""

import abc
import logging

logger = logging.getLogger(__name__)


class NotificationProvider(abc.ABC):
    """Abstract base class for notification providers."""

    @abc.abstractmethod
    async def send_message(self, message: str, **kwargs) -> bool:
        """
        Send a message via this notification provider.

        Args:
            message: The message content to send
            **kwargs: Additional provider-specific parameters

        Returns:
            True if message was sent successfully, False otherwise
        """
        pass

    @abc.abstractmethod
    async def send_notification(self, title: str, content: str, **kwargs) -> bool:
        """
        Send a formatted notification via this provider.

        Args:
            title: Notification title/summary
            content: Notification content/body
            **kwargs: Additional provider-specific parameters

        Returns:
            True if notification was sent successfully, False otherwise
        """
        pass


class NotificationManager:
    """Manages multiple notification providers."""

    def __init__(self):
        self.providers: list[NotificationProvider] = []

    def add_provider(self, provider: NotificationProvider) -> None:
        """Add a notification provider."""
        self.providers.append(provider)

    def remove_provider(self, provider: NotificationProvider) -> None:
        """Remove a notification provider."""
        if provider in self.providers:
            self.providers.remove(provider)

    async def send_message(self, message: str, **kwargs) -> list[bool]:
        """
        Send a message via all registered providers.

        Args:
            message: The message content to send
            **kwargs: Additional parameters passed to each provider

        Returns:
            List of boolean results from each provider (in same order as providers)
        """
        results = []
        for provider in self.providers:
            try:
                result = await provider.send_message(message, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Error sending message via {provider.__class__.__name__}: {e}")
                results.append(False)
        return results

    async def send_notification(self, title: str, content: str, **kwargs) -> list[bool]:
        """
        Send a notification via all registered providers.

        Args:
            title: Notification title/summary
            content: Notification content/body
            **kwargs: Additional parameters passed to each provider

        Returns:
            List of boolean results from each provider (in same order as providers)
        """
        results = []
        for provider in self.providers:
            try:
                result = await provider.send_notification(title, content, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Error sending notification via {provider.__class__.__name__}: {e}")
                results.append(False)
        return results
