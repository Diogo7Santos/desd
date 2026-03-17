from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from catalog.models import Product
from decimal import Decimal
from datetime import timedelta
import uuid


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

    # Unique order identifier for payment references
    order_number = models.CharField(max_length=50, unique=True, editable=False)
    
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
        help_text="Customer who placed the order"
    )
    
    # Delivery information
    delivery_address = models.TextField(help_text="Full delivery address")
    delivery_postcode = models.CharField(max_length=20)
    delivery_date = models.DateField(
        help_text="Requested delivery date (must be 48+ hours from order)"
    )
    delivery_instructions = models.TextField(blank=True)
    
    # Order totals
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total order value (all items)"
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['order_number']),
        ]

    def __str__(self):
        return f"Order {self.order_number} - {self.customer.username}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            # Generate unique order number: ORD-YYYYMMDD-UUID
            date_part = timezone.now().strftime('%Y%m%d')
            uuid_part = str(uuid.uuid4())[:8].upper()
            self.order_number = f"ORD-{date_part}-{uuid_part}"
        super().save(*args, **kwargs)

    def clean(self):
        """
        TC-007/TC-008: Enforce 48-hour minimum lead time.
        """
        super().clean()
        if self.delivery_date:
            min_delivery = (timezone.now() + timedelta(hours=48)).date()
            if self.delivery_date < min_delivery:
                raise ValidationError({
                    'delivery_date': 'Delivery date must be at least 48 hours from now.'
                })

    def get_items_by_producer(self):
        """
        TC-008: Group order items by producer.
        Returns dict: {producer: {'items': [items], 'subtotal': Decimal}}
        """
        from collections import defaultdict
        grouped = defaultdict(lambda: {'items': [], 'subtotal': Decimal('0.00')})
        
        for item in self.items.select_related('product__producer'):
            producer = item.product.producer
            grouped[producer]['items'].append(item)
            grouped[producer]['subtotal'] += item.subtotal
        
        return dict(grouped)

    def get_producer_ids(self):
        """Returns list of unique producer IDs in this order"""
        return list(
            self.items.values_list('product__producer_id', flat=True).distinct()
        )


class OrderItem(models.Model):
    """
    Individual product within an order.
    TC-007/TC-008: Stores snapshot of product details at order time.
    Each item has its own status for multi-vendor order management.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,  # Don't delete products that have been ordered
        help_text="Product ordered"
    )
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_items_as_producer",
        help_text="Producer of this item (for TC-009 visibility)"
    )
    
    # Snapshot fields (preserve pricing at order time)
    product_name = models.CharField(max_length=120)
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per unit at time of order"
    )
    quantity = models.PositiveIntegerField()
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="quantity × unit_price"
    )
    
    # Item-level status for multi-vendor orders
    status = models.CharField(
        max_length=20,
        choices=Order.Status.choices,
        default=Order.Status.PENDING,
        help_text="Status of this item (managed by producer)"
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.product_name} (Order {self.order.order_number})"

    def save(self, *args, **kwargs):
        # Auto-populate snapshot fields from product
        if not self.product_name:
            self.product_name = self.product.name
        if not self.unit_price:
            self.unit_price = self.product.price
        if not self.producer_id:
            self.producer = self.product.producer
        
        # Calculate subtotal
        self.subtotal = Decimal(self.quantity) * self.unit_price
        
        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """
    TC-010: Track status changes with timestamps and notes.
    Optional but useful for audit trail.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history"
    )
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        help_text="Producer who updated the status"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name_plural = "Order status histories"

    def __str__(self):
        return f"{self.order.order_number} → {self.status}"
