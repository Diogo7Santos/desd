from django.db import models
from django.conf import settings
from catalog.models import Product
from decimal import Decimal


class Cart(models.Model):
    """
    Shopping cart for a customer.
    TC-006: Customer can add products, modify quantities, view cart.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
        help_text="Cart owner (logged-in customer)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.username}"

    @property
    def total_items(self):
        """Total number of items (sum of quantities)"""
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        """Total cart value"""
        return sum(item.subtotal for item in self.items.all())

    def get_items_by_producer(self):
        """
        TC-008: Group cart items by producer for multi-vendor checkout display.
        Returns dict: {producer: [items]}
        """
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in self.items.select_related('product__producer', 'product__producer__producer_profile'):
            grouped[item.product.producer].append(item)
        return dict(grouped)


class CartItem(models.Model):
    """
    Individual product in a cart.
    TC-006: Tracks quantity and calculates subtotal.
    """
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        help_text="Product being added to cart"
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product')  # Prevent duplicate products in same cart
        ordering = ['added_at']

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def subtotal(self):
        """Calculate item subtotal (quantity × current product price)"""
        return Decimal(self.quantity) * self.product.price

    @property
    def producer(self):
        """Convenience property for grouping by producer"""
        return self.product.producer
