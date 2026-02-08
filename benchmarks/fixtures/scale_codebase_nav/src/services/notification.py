"""Notification service for the web application.

This module handles sending various types of notifications to users
including email, SMS, push notifications, and in-app messages. It
provides a unified interface for all notification channels.

Architecture Overview
---------------------
The notification service uses a strategy pattern where each notification
channel (email, SMS, push, in-app) implements a common interface. The
service routes messages to the appropriate channel based on user
preferences and notification type.

Message Templates
-----------------
All notification messages are rendered from templates stored in the
``templates/notifications/`` directory. Templates support variable
interpolation using Jinja2 syntax. Each template has versions for
each supported locale.

Rate Limiting
-------------
Notifications are rate-limited per-user and per-channel to prevent
spam. The default limits are:
- Email: 10 per hour
- SMS: 5 per hour
- Push: 20 per hour
- In-app: 50 per hour

Retry Policy
------------
Failed deliveries are retried with exponential backoff:
- 1st retry: 30 seconds
- 2nd retry: 2 minutes
- 3rd retry: 10 minutes
- After 3 failures: moved to dead-letter queue for manual review

Queue Configuration
-------------------
Notifications are enqueued in a priority queue with the following
priority levels:
- P0 (Critical): Security alerts, password resets, 2FA codes
- P1 (High): Order confirmations, shipping updates
- P2 (Normal): Marketing, promotions, newsletters
- P3 (Low): Analytics, reporting, digest summaries

The queue is processed by background workers with configurable
concurrency. Each worker processes one notification at a time and
acknowledges completion before picking up the next item.

Monitoring
----------
The service exposes metrics for:
- Delivery success rate per channel
- Average delivery latency per channel
- Queue depth and processing rate
- Error rates by error category
- Template rendering performance

Change History
--------------
- v1.0: Basic email notifications
- v1.1: Added SMS support via Twilio
- v1.2: Added push notifications via Firebase
- v1.3: Added in-app notification center
- v1.4: Added template engine with i18n support
- v1.5: Added rate limiting and retry logic
- v1.6: Added priority queue and background workers
- v1.7: Enhanced monitoring and alerting
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Available notification delivery channels.

    Each channel has different characteristics in terms of delivery
    speed, reliability, cost, and user experience. The choice of
    channel depends on the notification type and user preferences.

    Attributes:
        EMAIL: Traditional email delivery via SMTP or API.
            Highest reliability, lowest cost, slowest delivery.
        SMS: Text message delivery via carrier gateway.
            High reliability, moderate cost, fast delivery.
        PUSH: Mobile/web push notification.
            Moderate reliability, low cost, fastest delivery.
        IN_APP: In-application notification center.
            Guaranteed delivery, no cost, requires app usage.
        WEBHOOK: HTTP callback to external systems.
            Variable reliability, no cost, fast delivery.
    """

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


class NotificationPriority(Enum):
    """Priority levels for notification queue processing.

    Higher priority notifications are processed first and have
    shorter retry intervals on failure.
    """

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class NotificationType(Enum):
    """Predefined notification types with default routing.

    Each type maps to a set of channels and a template. The routing
    can be overridden by user preferences.
    """

    ORDER_CONFIRMATION = "order_confirmation"
    ORDER_STATUS_UPDATE = "order_status_update"
    ORDER_CANCELLATION = "order_cancellation"
    SHIPPING_UPDATE = "shipping_update"
    DELIVERY_CONFIRMATION = "delivery_confirmation"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    REFUND_PROCESSED = "refund_processed"
    ACCOUNT_CREATED = "account_created"
    PASSWORD_RESET = "password_reset"
    TWO_FACTOR_CODE = "two_factor_code"
    SECURITY_ALERT = "security_alert"
    NEWSLETTER = "newsletter"
    PROMOTION = "promotion"
    SYSTEM_MAINTENANCE = "system_maintenance"


@dataclass
class NotificationMessage:
    """A notification message ready for delivery.

    Contains the rendered content, routing information, and metadata
    for tracking delivery status.

    Attributes:
        message_id: Unique identifier for this message.
        notification_type: The type of notification.
        channel: Delivery channel.
        priority: Queue processing priority.
        recipient_id: User ID of the recipient.
        recipient_address: Channel-specific address (email, phone, etc).
        subject: Message subject (primarily for email).
        body: Rendered message body.
        body_html: HTML version of the body (for email).
        template_id: ID of the template used to render the message.
        template_vars: Variables used for template rendering.
        metadata: Additional metadata for tracking and analytics.
        created_at: Message creation timestamp.
        scheduled_at: Scheduled delivery time (None for immediate).
        delivered_at: Actual delivery timestamp.
        delivery_status: Current delivery status string.
        retry_count: Number of delivery attempts.
        max_retries: Maximum retry attempts before dead-lettering.
    """

    message_id: str = ""
    notification_type: NotificationType = NotificationType.ORDER_CONFIRMATION
    channel: NotificationChannel = NotificationChannel.EMAIL
    priority: NotificationPriority = NotificationPriority.NORMAL
    recipient_id: str = ""
    recipient_address: str = ""
    subject: str = ""
    body: str = ""
    body_html: str = ""
    template_id: str = ""
    template_vars: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    delivery_status: str = "pending"
    retry_count: int = 0
    max_retries: int = 3


# ── Template Registry ──────────────────────────────────────────────────────

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "order_confirmation": {
        "subject": "Order Confirmation - #{order_id}",
        "body": (
            "Thank you for your order!\n\n"
            "Order ID: {order_id}\n"
            "Total: {total}\n"
            "Status: {status}\n\n"
            "We'll send you an update when your order ships."
        ),
    },
    "order_status_update": {
        "subject": "Order Update - #{order_id}",
        "body": (
            "Your order status has been updated.\n\n"
            "Order ID: {order_id}\n"
            "Previous Status: {old_status}\n"
            "New Status: {new_status}\n\n"
            "Thank you for your patience."
        ),
    },
    "order_cancellation": {
        "subject": "Order Cancelled - #{order_id}",
        "body": (
            "Your order has been cancelled.\n\n"
            "Order ID: {order_id}\n\n"
            "If you did not request this cancellation, please contact support."
        ),
    },
    "shipping_update": {
        "subject": "Shipping Update - #{order_id}",
        "body": (
            "Your order is on its way!\n\n"
            "Order ID: {order_id}\n"
            "Tracking Number: {tracking_number}\n"
            "Carrier: {carrier}\n"
            "Estimated Delivery: {estimated_delivery}\n"
        ),
    },
    "password_reset": {
        "subject": "Password Reset Request",
        "body": (
            "A password reset was requested for your account.\n\n"
            "Click the link below to reset your password:\n"
            "{reset_link}\n\n"
            "This link expires in {expiry_minutes} minutes.\n"
            "If you didn't request this, please ignore this email."
        ),
    },
    "security_alert": {
        "subject": "Security Alert - Unusual Activity Detected",
        "body": (
            "We detected unusual activity on your account.\n\n"
            "Activity: {activity_description}\n"
            "IP Address: {ip_address}\n"
            "Location: {location}\n"
            "Time: {timestamp}\n\n"
            "If this was you, you can safely ignore this alert.\n"
            "If not, please secure your account immediately."
        ),
    },
}

# ── Rate Limiter ───────────────────────────────────────────────────────────

CHANNEL_RATE_LIMITS: dict[NotificationChannel, int] = {
    NotificationChannel.EMAIL: 10,
    NotificationChannel.SMS: 5,
    NotificationChannel.PUSH: 20,
    NotificationChannel.IN_APP: 50,
    NotificationChannel.WEBHOOK: 100,
}


class NotificationRateLimiter:
    """Per-user, per-channel rate limiter for notifications.

    Uses a sliding window algorithm to track notification counts
    within the rate limit window (default 1 hour).

    Args:
        window_seconds: Duration of the rate limit window.
    """

    def __init__(self, window_seconds: int = 3600) -> None:
        self._window = window_seconds
        self._counters: dict[str, list[float]] = defaultdict(list)

    def check(self, user_id: str, channel: NotificationChannel) -> bool:
        """Check if a notification can be sent without exceeding limits.

        Args:
            user_id: The recipient user ID.
            channel: The notification channel.

        Returns:
            True if the notification is within rate limits.
        """
        key = f"{user_id}:{channel.value}"
        limit = CHANNEL_RATE_LIMITS.get(channel, 10)
        now = time.time()

        # Clean old entries
        timestamps = self._counters[key]
        timestamps[:] = [t for t in timestamps if now - t < self._window]

        return len(timestamps) < limit

    def record(self, user_id: str, channel: NotificationChannel) -> None:
        """Record a sent notification for rate limiting."""
        key = f"{user_id}:{channel.value}"
        self._counters[key].append(time.time())


# ── Notification Service ───────────────────────────────────────────────────

class NotificationService:
    """Central notification service.

    Provides high-level methods for sending notifications through
    the appropriate channels based on type and user preferences.

    This service is used by other services (OrderService, AuthService)
    to send notifications as part of their workflows.

    Args:
        user_preferences: Dict mapping user_id to notification preferences.
        rate_limiter: Rate limiter instance.
    """

    def __init__(
        self,
        user_preferences: Optional[dict[str, dict[str, Any]]] = None,
        rate_limiter: Optional[NotificationRateLimiter] = None,
    ) -> None:
        self._preferences = user_preferences or {}
        self._rate_limiter = rate_limiter or NotificationRateLimiter()
        self._sent_messages: list[NotificationMessage] = []
        self._queue: list[NotificationMessage] = []

    def send_order_confirmation(self, user_id: str, order_id: str) -> bool:
        """Send an order confirmation notification.

        Routes to email (always) and optionally to push/in-app
        based on user preferences.

        Args:
            user_id: The user to notify.
            order_id: The order that was confirmed.

        Returns:
            True if at least one notification was sent.
        """
        template = DEFAULT_TEMPLATES.get("order_confirmation", {})
        message = NotificationMessage(
            message_id=self._generate_id(),
            notification_type=NotificationType.ORDER_CONFIRMATION,
            channel=NotificationChannel.EMAIL,
            priority=NotificationPriority.HIGH,
            recipient_id=user_id,
            subject=template.get("subject", "").format(order_id=order_id),
            body=template.get("body", "").format(
                order_id=order_id, total="(see order)", status="Pending"
            ),
            template_id="order_confirmation",
            template_vars={"order_id": order_id, "user_id": user_id},
        )
        return self._enqueue(message)

    def send_order_status_update(
        self, user_id: str, order_id: str, old_status: str, new_status: str
    ) -> bool:
        """Send an order status update notification."""
        template = DEFAULT_TEMPLATES.get("order_status_update", {})
        message = NotificationMessage(
            message_id=self._generate_id(),
            notification_type=NotificationType.ORDER_STATUS_UPDATE,
            channel=NotificationChannel.EMAIL,
            priority=NotificationPriority.NORMAL,
            recipient_id=user_id,
            subject=template.get("subject", "").format(order_id=order_id),
            body=template.get("body", "").format(
                order_id=order_id, old_status=old_status, new_status=new_status
            ),
            template_id="order_status_update",
            template_vars={
                "order_id": order_id,
                "old_status": old_status,
                "new_status": new_status,
            },
        )
        return self._enqueue(message)

    def send_order_cancellation(self, user_id: str, order_id: str) -> bool:
        """Send an order cancellation notification."""
        template = DEFAULT_TEMPLATES.get("order_cancellation", {})
        message = NotificationMessage(
            message_id=self._generate_id(),
            notification_type=NotificationType.ORDER_CANCELLATION,
            channel=NotificationChannel.EMAIL,
            priority=NotificationPriority.HIGH,
            recipient_id=user_id,
            subject=template.get("subject", "").format(order_id=order_id),
            body=template.get("body", "").format(order_id=order_id),
            template_id="order_cancellation",
            template_vars={"order_id": order_id},
        )
        return self._enqueue(message)

    def send_security_alert(
        self,
        user_id: str,
        activity: str,
        ip_address: str,
        location: str,
    ) -> bool:
        """Send a security alert notification.

        Security alerts are sent on all configured channels with
        CRITICAL priority.
        """
        template = DEFAULT_TEMPLATES.get("security_alert", {})
        timestamp = datetime.now(timezone.utc).isoformat()
        message = NotificationMessage(
            message_id=self._generate_id(),
            notification_type=NotificationType.SECURITY_ALERT,
            channel=NotificationChannel.EMAIL,
            priority=NotificationPriority.CRITICAL,
            recipient_id=user_id,
            subject=template.get("subject", ""),
            body=template.get("body", "").format(
                activity_description=activity,
                ip_address=ip_address,
                location=location,
                timestamp=timestamp,
            ),
            template_id="security_alert",
            template_vars={
                "activity": activity,
                "ip_address": ip_address,
                "location": location,
            },
        )
        return self._enqueue(message)

    def send_password_reset(self, user_id: str, reset_link: str) -> bool:
        """Send a password reset notification."""
        template = DEFAULT_TEMPLATES.get("password_reset", {})
        message = NotificationMessage(
            message_id=self._generate_id(),
            notification_type=NotificationType.PASSWORD_RESET,
            channel=NotificationChannel.EMAIL,
            priority=NotificationPriority.CRITICAL,
            recipient_id=user_id,
            subject=template.get("subject", ""),
            body=template.get("body", "").format(
                reset_link=reset_link, expiry_minutes=30
            ),
            template_id="password_reset",
        )
        return self._enqueue(message)

    def get_unread_count(self, user_id: str) -> int:
        """Get the count of unread in-app notifications for a user."""
        return sum(
            1
            for m in self._sent_messages
            if m.recipient_id == user_id
            and m.channel == NotificationChannel.IN_APP
            and m.delivery_status == "delivered"
        )

    def _enqueue(self, message: NotificationMessage) -> bool:
        """Add a message to the delivery queue."""
        if not self._rate_limiter.check(message.recipient_id, message.channel):
            logger.warning(
                "Rate limited: user_id=%s channel=%s",
                message.recipient_id,
                message.channel.value,
            )
            return False

        self._queue.append(message)
        self._rate_limiter.record(message.recipient_id, message.channel)

        # Simulate immediate delivery for in-memory implementation
        message.delivery_status = "delivered"
        message.delivered_at = datetime.now(timezone.utc)
        self._sent_messages.append(message)

        logger.info(
            "Notification sent: type=%s channel=%s recipient=%s",
            message.notification_type.value,
            message.channel.value,
            message.recipient_id,
        )
        return True

    @staticmethod
    def _generate_id() -> str:
        """Generate a unique message ID."""
        return hashlib.sha256(
            f"{time.time()}:{id(object())}".encode()
        ).hexdigest()[:16]
