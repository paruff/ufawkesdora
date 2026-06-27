"""
Notification providers package.

This package contains implementations for various notification platforms.
Each provider implements the NotificationProvider interface from the base module.
"""

from .base import NotificationProvider

# Available providers
try:
    from .slack import SlackNotificationProvider
except ImportError:
    SlackNotificationProvider = None

try:
    from .teams import TeamsNotificationProvider
except ImportError:
    TeamsNotificationProvider = None

__all__ = [
    "NotificationProvider",
]

# Add available providers to exports
if SlackNotificationProvider is not None:
    __all__.append("SlackNotificationProvider")

if TeamsNotificationProvider is not None:
    __all__.append("TeamsNotificationProvider")
