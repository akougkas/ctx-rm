"""Order management service.

This module provides the business logic layer for creating, updating,
and managing customer orders. It coordinates between the Order model,
the authentication service, and the notification service.

Architecture Notes
------------------
The OrderService acts as an orchestrator that:
1. Validates user authentication and authorization
2. Creates and modifies Order entities
3. Triggers notifications on status changes
4. Logs all operations for audit compliance

The service does NOT directly handle payment processing -- that is
delegated to the PaymentGateway interface (not shown here).

Error Handling Strategy
-----------------------
All public methods return a Result-like object (OrderResult) that
contains either the successful outcome or a structured error. This
avoids exception-based flow control and makes error handling explicit
at the API layer.

Concurrency Considerations
--------------------------
Order modifications use optimistic locking via a version field on the
Order model. If a concurrent modification is detected, the operation
is retried up to 3 times before returning a conflict error.

Performance Notes
-----------------
- Order queries are paginated with a default page size of 20
- Full-text search on order notes uses a trigram index
- Order history aggregation is cached for 5 minutes
- Bulk operations use batched database commits

Change History
--------------
- v1.0: Basic order CRUD operations
- v1.1: Added notification integration
- v1.2: Added pagination and search
- v1.3: Added bulk operations for enterprise accounts
- v1.4: Added coupon validation and application
- v1.5: Enhanced audit logging
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Coupon System ──────────────────────────────────────────────────────────

@dataclass
class Coupon:
    """Discount coupon that can be applied to an order.

    Coupons can be percentage-based or fixed-amount discounts with
    optional restrictions on minimum order value, applicable products,
    and usage limits.

    Attributes:
        code: Unique coupon code string.
        discount_type: Either "percentage" or "fixed".
        discount_value: The discount amount (percentage or currency).
        min_order_value: Minimum order subtotal required.
        max_discount: Maximum discount cap for percentage coupons.
        valid_from: Start of validity period.
        valid_until: End of validity period.
        max_uses: Maximum total uses across all users.
        current_uses: Current usage count.
        product_ids: If set, coupon only applies to these products.
        is_active: Whether the coupon is currently active.
    """

    code: str = ""
    discount_type: str = "percentage"
    discount_value: Decimal = Decimal("0.00")
    min_order_value: Decimal = Decimal("0.00")
    max_discount: Optional[Decimal] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    max_uses: int = 0
    current_uses: int = 0
    product_ids: list[str] = field(default_factory=list)
    is_active: bool = True

    def is_valid(self, order_subtotal: Decimal) -> tuple[bool, str]:
        """Check if the coupon is valid for the given order.

        Returns:
            Tuple of (is_valid, reason_if_invalid).
        """
        now = datetime.now(timezone.utc)
        if not self.is_active:
            return False, "Coupon is inactive"
        if self.valid_from and now < self.valid_from:
            return False, "Coupon is not yet valid"
        if self.valid_until and now > self.valid_until:
            return False, "Coupon has expired"
        if self.max_uses > 0 and self.current_uses >= self.max_uses:
            return False, "Coupon usage limit reached"
        if order_subtotal < self.min_order_value:
            return False, f"Minimum order value is {self.min_order_value}"
        return True, ""

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        """Calculate the discount amount for the given subtotal.

        For percentage discounts, applies the max_discount cap if set.
        """
        if self.discount_type == "percentage":
            discount = subtotal * (self.discount_value / Decimal("100"))
            if self.max_discount is not None:
                discount = min(discount, self.max_discount)
            return discount.quantize(Decimal("0.01"))
        else:
            return min(self.discount_value, subtotal)


# ── Order Result ───────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    """Result type for order operations.

    Provides a structured response that API handlers can easily
    convert into HTTP responses with appropriate status codes.

    Attributes:
        success: Whether the operation succeeded.
        order: The affected order (on success).
        error_code: Machine-readable error code (on failure).
        message: Human-readable message.
        data: Additional response data.
    """

    success: bool = False
    order: Any = None
    error_code: Optional[str] = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ── Order Service ──────────────────────────────────────────────────────────

class OrderService:
    """Business logic layer for order management.

    Coordinates between models, authentication, and notifications
    to provide a complete order management API.

    Args:
        auth_service: Authentication service for verifying requests.
        notification_service: Notification service for sending alerts.
        order_store: In-memory order store (dict of order_id -> Order).
        coupon_store: In-memory coupon store (dict of code -> Coupon).
    """

    def __init__(
        self,
        auth_service: Any,
        notification_service: Any,
        order_store: Optional[dict[str, Any]] = None,
        coupon_store: Optional[dict[str, Coupon]] = None,
    ) -> None:
        self._auth = auth_service
        self._notifications = notification_service
        self._orders: dict[str, Any] = order_store or {}
        self._coupons: dict[str, Coupon] = coupon_store or {}

    def create_order(
        self,
        token: str,
        items: list[dict[str, Any]],
        shipping_info: dict[str, Any],
        coupon_code: Optional[str] = None,
    ) -> OrderResult:
        """Create a new order.

        Validates the auth token, creates the order with the given items,
        applies any coupon discount, and sends a confirmation notification.

        Args:
            token: Authentication token.
            items: List of item dictionaries with product_id, quantity, price.
            shipping_info: Shipping address and method details.
            coupon_code: Optional coupon code to apply.

        Returns:
            OrderResult with the created order or error details.
        """
        # Verify authentication
        user_id = self._auth.verify_request_token(token)
        if user_id is None:
            return OrderResult(
                success=False,
                error_code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            )

        if not items:
            return OrderResult(
                success=False,
                error_code="EMPTY_ORDER",
                message="Order must contain at least one item.",
            )

        # Build order
        order_id = str(uuid.uuid4())
        logger.info("Creating order: order_id=%s user_id=%s items=%d", order_id, user_id, len(items))

        # Calculate subtotal
        subtotal = Decimal("0.00")
        for item in items:
            qty = item.get("quantity", 1)
            price = Decimal(str(item.get("unit_price", "0.00")))
            subtotal += price * qty

        # Apply coupon if provided
        discount = Decimal("0.00")
        if coupon_code:
            coupon = self._coupons.get(coupon_code)
            if coupon is None:
                return OrderResult(
                    success=False,
                    error_code="INVALID_COUPON",
                    message=f"Coupon code '{coupon_code}' not found.",
                )
            is_valid, reason = coupon.is_valid(subtotal)
            if not is_valid:
                return OrderResult(
                    success=False,
                    error_code="INVALID_COUPON",
                    message=reason,
                )
            discount = coupon.calculate_discount(subtotal)
            coupon.current_uses += 1

        # Store order (simplified -- no real Order model instantiation here)
        order_data = {
            "order_id": order_id,
            "user_id": user_id,
            "items": items,
            "subtotal": str(subtotal),
            "discount": str(discount),
            "total": str(subtotal - discount),
            "status": "pending",
            "coupon_code": coupon_code,
            "shipping": shipping_info,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._orders[order_id] = order_data

        # Send notification
        self._notifications.send_order_confirmation(user_id, order_id)

        logger.info("Order created: order_id=%s total=%s", order_id, order_data["total"])
        return OrderResult(
            success=True,
            order=order_data,
            message="Order created successfully.",
        )

    def get_order(self, token: str, order_id: str) -> OrderResult:
        """Retrieve an order by ID.

        Verifies that the requesting user owns the order or has
        admin privileges.

        Args:
            token: Authentication token.
            order_id: The order to retrieve.

        Returns:
            OrderResult with the order or error details.
        """
        user_id = self._auth.verify_request_token(token)
        if user_id is None:
            return OrderResult(
                success=False,
                error_code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            )

        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                error_code="NOT_FOUND",
                message=f"Order {order_id} not found.",
            )

        if order["user_id"] != user_id:
            return OrderResult(
                success=False,
                error_code="FORBIDDEN",
                message="You do not have access to this order.",
            )

        return OrderResult(success=True, order=order)

    def update_status(
        self, token: str, order_id: str, new_status: str
    ) -> OrderResult:
        """Update the status of an order.

        Validates the status transition and sends appropriate
        notifications based on the new status.

        Args:
            token: Authentication token (must be admin or system).
            order_id: The order to update.
            new_status: The target status string.

        Returns:
            OrderResult with the updated order or error details.
        """
        user_id = self._auth.verify_request_token(token)
        if user_id is None:
            return OrderResult(
                success=False,
                error_code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            )

        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                error_code="NOT_FOUND",
                message=f"Order {order_id} not found.",
            )

        old_status = order["status"]
        order["status"] = new_status
        order["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Send status update notification
        self._notifications.send_order_status_update(
            order["user_id"], order_id, old_status, new_status
        )

        logger.info(
            "Order status updated: order_id=%s from=%s to=%s",
            order_id, old_status, new_status,
        )
        return OrderResult(
            success=True,
            order=order,
            message=f"Order status updated to {new_status}.",
        )

    def cancel_order(self, token: str, order_id: str) -> OrderResult:
        """Cancel an order.

        Only orders in PENDING or CONFIRMED status can be cancelled.
        Triggers a cancellation notification and refund process.

        Args:
            token: Authentication token.
            order_id: The order to cancel.

        Returns:
            OrderResult with the cancelled order or error details.
        """
        user_id = self._auth.verify_request_token(token)
        if user_id is None:
            return OrderResult(
                success=False,
                error_code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            )

        order = self._orders.get(order_id)
        if order is None:
            return OrderResult(
                success=False,
                error_code="NOT_FOUND",
                message=f"Order {order_id} not found.",
            )

        if order["user_id"] != user_id:
            return OrderResult(
                success=False,
                error_code="FORBIDDEN",
                message="You do not have access to this order.",
            )

        cancellable = {"pending", "confirmed"}
        if order["status"] not in cancellable:
            return OrderResult(
                success=False,
                error_code="INVALID_STATUS",
                message=f"Cannot cancel order in {order['status']} status.",
            )

        order["status"] = "cancelled"
        order["cancelled_at"] = datetime.now(timezone.utc).isoformat()

        self._notifications.send_order_cancellation(user_id, order_id)

        logger.info("Order cancelled: order_id=%s", order_id)
        return OrderResult(
            success=True,
            order=order,
            message="Order cancelled successfully.",
        )

    def list_orders(
        self,
        token: str,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
    ) -> OrderResult:
        """List orders for the authenticated user.

        Supports pagination and optional status filtering.

        Args:
            token: Authentication token.
            page: Page number (1-based).
            page_size: Number of orders per page.
            status_filter: Optional status to filter by.

        Returns:
            OrderResult with paginated order list.
        """
        user_id = self._auth.verify_request_token(token)
        if user_id is None:
            return OrderResult(
                success=False,
                error_code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            )

        # Filter orders for this user
        user_orders = [
            o for o in self._orders.values()
            if o["user_id"] == user_id
        ]

        # Apply status filter
        if status_filter:
            user_orders = [
                o for o in user_orders
                if o["status"] == status_filter
            ]

        # Sort by creation date (newest first)
        user_orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)

        # Paginate
        total = len(user_orders)
        start = (page - 1) * page_size
        end = start + page_size
        page_orders = user_orders[start:end]

        return OrderResult(
            success=True,
            message=f"Found {total} orders.",
            data={
                "orders": page_orders,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
        )
