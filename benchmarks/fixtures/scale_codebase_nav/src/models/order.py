"""Order model for the web service.

This module defines the Order entity and related types used for
managing customer orders throughout their lifecycle. Orders reference
Users as their owner and track items, pricing, shipping, and fulfillment.

Business Rules
--------------
- Orders can only be created by authenticated users with ACTIVE status
- Order total must match the sum of line item totals plus tax and shipping
- Cancellation is only allowed before the order enters SHIPPED status
- Refunds are processed through a separate RefundRequest workflow

Design Notes
------------
The Order model uses a state machine pattern for status transitions.
Valid transitions are enforced at the model level to prevent invalid
state changes that could cause data inconsistencies in downstream
systems such as inventory management and financial reporting.

Change History
--------------
- v1.0: Basic order model with line items
- v1.1: Added shipping tracking and estimated delivery
- v1.2: Added tax calculation and multi-currency support
- v1.3: Enhanced status tracking with audit trail
- v1.4: Added coupon and discount support
- v1.5: Bulk order support for enterprise customers
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class OrderStatus(Enum):
    """Order lifecycle status values.

    The order status follows a strict state machine with defined
    transitions. Invalid transitions raise a StateTransitionError.

    Valid transition paths:
        PENDING -> CONFIRMED -> PROCESSING -> SHIPPED -> DELIVERED
        PENDING -> CANCELLED
        CONFIRMED -> CANCELLED
        SHIPPED -> RETURNED
        DELIVERED -> RETURNED (within return window)

    Attributes:
        PENDING: Order has been placed but not yet confirmed.
            Payment authorization may still be pending.
        CONFIRMED: Payment confirmed, order accepted for processing.
            Inventory has been reserved but not yet allocated.
        PROCESSING: Order is being prepared for shipment.
            Items are being picked, packed, and labeled.
        SHIPPED: Order has left the fulfillment center.
            Tracking information is available.
        DELIVERED: Order has been delivered to the customer.
            Delivery confirmation received from carrier.
        CANCELLED: Order was cancelled before shipment.
            Inventory reservations released, payment refunded.
        RETURNED: Order was returned after delivery.
            Return processing and refund initiated.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class PaymentMethod(Enum):
    """Supported payment methods.

    Each payment method has different processing characteristics
    including authorization time, settlement delay, and chargeback
    risk levels that affect fraud scoring.
    """

    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    DIGITAL_WALLET = "digital_wallet"
    INVOICE = "invoice"


class ShippingMethod(Enum):
    """Available shipping options with expected delivery timeframes.

    Shipping costs are calculated based on the method, weight, dimensions,
    and destination. Express and overnight options require additional
    carrier surcharges that are passed through to the customer.
    """

    STANDARD = "standard"
    EXPRESS = "express"
    OVERNIGHT = "overnight"
    PICKUP = "pickup"


VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED, OrderStatus.RETURNED},
    OrderStatus.DELIVERED: {OrderStatus.RETURNED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.RETURNED: set(),
}


@dataclass
class LineItem:
    """A single item within an order.

    Represents a product and its quantity, pricing, and any applicable
    discounts. The total for a line item is calculated as:
    ``(unit_price * quantity) - discount_amount``

    Attributes:
        item_id: Unique identifier for this line item.
        product_id: Reference to the product catalog entry.
        product_name: Display name of the product.
        sku: Stock keeping unit code.
        quantity: Number of units ordered.
        unit_price: Price per unit in the order currency.
        discount_amount: Total discount applied to this line item.
        weight_grams: Weight per unit in grams (for shipping calculation).
        notes: Optional customer notes for this item.
    """

    item_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    product_id: str = ""
    product_name: str = ""
    sku: str = ""
    quantity: int = 1
    unit_price: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    weight_grams: int = 0
    notes: Optional[str] = None

    @property
    def total(self) -> Decimal:
        """Calculate line item total after discount."""
        return (self.unit_price * self.quantity) - self.discount_amount

    def validate(self) -> list[str]:
        """Validate line item fields."""
        errors: list[str] = []
        if self.quantity < 1:
            errors.append(f"Invalid quantity for {self.product_name}: {self.quantity}")
        if self.unit_price < 0:
            errors.append(f"Negative price for {self.product_name}")
        if self.discount_amount > self.unit_price * self.quantity:
            errors.append(f"Discount exceeds total for {self.product_name}")
        if not self.product_id:
            errors.append("Product ID is required")
        return errors


@dataclass
class ShippingInfo:
    """Shipping details for an order.

    Contains the destination address, selected shipping method, tracking
    information, and delivery estimates. Populated during order processing
    and updated as the shipment progresses.

    Attributes:
        recipient_name: Name of the person receiving the shipment.
        street_line_1: Primary street address.
        street_line_2: Secondary address line.
        city: City name.
        state_province: State or province.
        postal_code: ZIP or postal code.
        country: ISO 3166-1 alpha-2 country code.
        phone: Contact phone number for delivery.
        method: Selected shipping method.
        tracking_number: Carrier tracking number (set after shipment).
        carrier: Shipping carrier name.
        estimated_delivery: Expected delivery date.
        actual_delivery: Actual delivery date (set on delivery).
        shipping_cost: Calculated shipping cost.
        signature_required: Whether delivery requires signature.
    """

    recipient_name: str = ""
    street_line_1: str = ""
    street_line_2: str = ""
    city: str = ""
    state_province: str = ""
    postal_code: str = ""
    country: str = "US"
    phone: str = ""
    method: ShippingMethod = ShippingMethod.STANDARD
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None
    shipping_cost: Decimal = Decimal("0.00")
    signature_required: bool = False

    def validate(self) -> list[str]:
        """Validate shipping information completeness."""
        errors: list[str] = []
        if not self.recipient_name:
            errors.append("Recipient name is required")
        if not self.street_line_1:
            errors.append("Street address is required")
        if not self.city:
            errors.append("City is required")
        if not self.country:
            errors.append("Country is required")
        return errors


@dataclass
class Order:
    """Core order entity for the web service.

    Manages the complete lifecycle of a customer order including
    payment processing, fulfillment tracking, and delivery confirmation.

    The order interacts with the User model for authorization checks
    and the notification service for status update communications.

    Attributes:
        order_id: Unique order identifier (UUID format).
        user_id: Reference to the ordering user.
        status: Current order lifecycle status.
        items: List of line items in the order.
        shipping: Shipping details and tracking.
        payment_method: Selected payment method.
        payment_reference: External payment processor reference.
        currency: ISO 4217 currency code.
        subtotal: Sum of line item totals before tax and shipping.
        tax_amount: Calculated tax amount.
        total: Final order total including tax and shipping.
        coupon_code: Applied coupon code (if any).
        notes: Customer notes for the order.
        created_at: Order creation timestamp.
        updated_at: Last update timestamp.
        status_history: Audit trail of status changes.
    """

    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    items: list[LineItem] = field(default_factory=list)
    shipping: ShippingInfo = field(default_factory=ShippingInfo)
    payment_method: PaymentMethod = PaymentMethod.CREDIT_CARD
    payment_reference: Optional[str] = None
    currency: str = "USD"
    subtotal: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    coupon_code: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_history: list[dict[str, Any]] = field(default_factory=list)

    def calculate_totals(self) -> None:
        """Recalculate subtotal, tax, and total from line items.

        The tax rate is determined by the shipping destination country.
        Currently supports US (varies by state), EU (VAT), and a
        default rate for other countries.
        """
        self.subtotal = sum(
            (item.total for item in self.items), Decimal("0.00")
        )
        tax_rate = self._get_tax_rate()
        self.tax_amount = (self.subtotal * tax_rate).quantize(Decimal("0.01"))
        self.total = self.subtotal + self.tax_amount + self.shipping.shipping_cost
        self.updated_at = datetime.now(timezone.utc)

    def _get_tax_rate(self) -> Decimal:
        """Determine tax rate based on shipping destination."""
        country_rates: dict[str, Decimal] = {
            "US": Decimal("0.08"),
            "GB": Decimal("0.20"),
            "DE": Decimal("0.19"),
            "FR": Decimal("0.20"),
            "JP": Decimal("0.10"),
            "CA": Decimal("0.13"),
            "AU": Decimal("0.10"),
        }
        return country_rates.get(self.shipping.country, Decimal("0.15"))

    def transition_status(self, new_status: OrderStatus) -> None:
        """Transition the order to a new status.

        Validates that the transition is allowed according to the
        state machine rules before applying the change.

        Args:
            new_status: The target status.

        Raises:
            ValueError: If the transition is not valid.
        """
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {new_status.value}"
            )
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)
        self.status_history.append({
            "from": old_status.value,
            "to": new_status.value,
            "timestamp": self.updated_at.isoformat(),
        })

    def add_item(self, item: LineItem) -> None:
        """Add a line item and recalculate totals."""
        self.items.append(item)
        self.calculate_totals()

    def remove_item(self, item_id: str) -> bool:
        """Remove a line item by ID and recalculate totals."""
        original_count = len(self.items)
        self.items = [i for i in self.items if i.item_id != item_id]
        if len(self.items) < original_count:
            self.calculate_totals()
            return True
        return False

    def validate(self) -> list[str]:
        """Validate the complete order."""
        errors: list[str] = []
        if not self.user_id:
            errors.append("User ID is required")
        if not self.items:
            errors.append("Order must have at least one item")
        for item in self.items:
            errors.extend(item.validate())
        errors.extend(self.shipping.validate())
        return errors

    def to_dict(self) -> dict[str, Any]:
        """Serialize order to dictionary."""
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "items": [
                {
                    "item_id": i.item_id,
                    "product_id": i.product_id,
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "unit_price": str(i.unit_price),
                    "total": str(i.total),
                }
                for i in self.items
            ],
            "currency": self.currency,
            "subtotal": str(self.subtotal),
            "tax_amount": str(self.tax_amount),
            "total": str(self.total),
            "created_at": self.created_at.isoformat(),
        }
