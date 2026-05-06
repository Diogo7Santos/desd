import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from catalog.models import Product


WEEKDAY_CHOICES = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)


class Order(models.Model):
    """
    Customer order (may contain items from multiple producers).
    TC-007: Single-vendor order
    TC-008: Multi-vendor order
    TC-021: Order history
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment"
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        READY = "READY", "Ready for Collection/Delivery"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(max_length=50, unique=True, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
        help_text="Customer who placed the order",
    )
    delivery_address = models.TextField(help_text="Full delivery address")
    delivery_postcode = models.CharField(max_length=20)
    delivery_date = models.DateField(
        help_text="Requested delivery date (must be 48+ hours from order)"
    )
    delivery_instructions = models.TextField(blank=True)
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total order value (all items)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["order_number"]),
        ]

    def __str__(self):
        return f"Order {self.order_number} - {self.customer.username}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            date_part = timezone.now().strftime("%Y%m%d")
            uuid_part = str(uuid.uuid4())[:8].upper()
            self.order_number = f"ORD-{date_part}-{uuid_part}"
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.delivery_date:
            min_delivery = (timezone.now() + timedelta(hours=48)).date()
            if self.delivery_date < min_delivery:
                raise ValidationError(
                    {"delivery_date": "Delivery date must be at least 48 hours from now."}
                )

    def get_items_by_producer(self):
        """
        TC-008: Group order items by producer.
        Returns dict: {producer: {'items': [items], 'subtotal': Decimal}}
        """
        from collections import defaultdict

        grouped = defaultdict(lambda: {"items": [], "subtotal": Decimal("0.00")})

        for item in self.items.select_related("product__producer"):
            producer = item.product.producer
            grouped[producer]["items"].append(item)
            grouped[producer]["subtotal"] += item.subtotal

        return dict(grouped)

    def get_producer_ids(self):
        return list(self.items.values_list("product__producer_id", flat=True).distinct())


class OrderItem(models.Model):
    """
    Individual product within an order.
    TC-007/TC-008: Stores snapshot of product details at order time.
    Each item has its own status for multi-vendor order management.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        help_text="Product ordered",
    )
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_items_as_producer",
        help_text="Producer of this item (for TC-009 visibility)",
    )
    product_name = models.CharField(max_length=120)
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per unit at time of order",
    )
    quantity = models.PositiveIntegerField()
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="quantity x unit_price",
    )
    status = models.CharField(
        max_length=20,
        choices=Order.Status.choices,
        default=Order.Status.PENDING,
        help_text="Status of this item (managed by producer)",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity}x {self.product_name} (Order {self.order.order_number})"

    def save(self, *args, **kwargs):
        if not self.product_name:
            self.product_name = self.product.name
        if not self.unit_price:
            self.unit_price = self.product.price
        if not self.producer_id:
            self.producer = self.product.producer

        self.subtotal = Decimal(self.quantity) * self.unit_price
        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """
    TC-010: Track status changes with timestamps and notes.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        help_text="Producer who updated the status",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "Order status histories"

    def __str__(self):
        return f"{self.order.order_number} -> {self.status}"


class RecurringOrder(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        CANCELLED = "CANCELLED", "Cancelled"

    class Interval(models.TextChoices):
        WEEKLY = "WEEKLY", "Weekly"
        FORTNIGHTLY = "FORTNIGHTLY", "Fortnightly"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recurring_orders",
        help_text="Restaurant customer who owns this recurring order template",
    )
    template_name = models.CharField(max_length=120, blank=True)
    recurrence_interval = models.CharField(
        max_length=12,
        choices=Interval.choices,
        default=Interval.WEEKLY,
    )
    order_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    delivery_weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    delivery_address = models.TextField()
    delivery_postcode = models.CharField(max_length=20)
    delivery_instructions = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    next_order_date = models.DateField()
    next_delivery_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["next_order_date"]),
        ]

    def __str__(self):
        return self.template_name or f"Recurring order for {self.customer.username}"

    @property
    def interval_days(self) -> int:
        return 14 if self.recurrence_interval == self.Interval.FORTNIGHTLY else 7

    @property
    def order_weekday_label(self) -> str:
        return dict(WEEKDAY_CHOICES).get(self.order_weekday, "")

    @property
    def delivery_weekday_label(self) -> str:
        return dict(WEEKDAY_CHOICES).get(self.delivery_weekday, "")


class RecurringOrderItem(models.Model):
    recurring_order = models.ForeignKey(
        RecurringOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="recurring_order_items",
    )
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recurring_order_items_as_producer",
    )
    product_name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity}x {self.product_name} ({self.recurring_order_id})"

    def save(self, *args, **kwargs):
        if not self.product_name:
            self.product_name = self.product.name
        if not self.unit_price:
            self.unit_price = self.product.price
        if not self.producer_id:
            self.producer = self.product.producer
        super().save(*args, **kwargs)


class RecurringOrderItemOverride(models.Model):
    recurring_item = models.ForeignKey(
        RecurringOrderItem,
        on_delete=models.CASCADE,
        related_name="overrides",
    )
    scheduled_order_date = models.DateField()
    quantity = models.PositiveIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["recurring_item_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_item", "scheduled_order_date"],
                name="unique_recurring_item_override_per_schedule",
            )
        ]

    def __str__(self):
        return f"{self.recurring_item_id}@{self.scheduled_order_date}"
