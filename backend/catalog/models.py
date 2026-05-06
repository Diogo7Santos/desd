# backend/catalog/models.py

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Product(models.Model):
    """
    Catalog product listing.

    Designed to support:
    - TC-003: Producer can create product with required fields (category, price, stock, allergens, harvest date, availability)
    - TC-004: Customer can browse by category and only see Available/In Season products
    - TC-005: Customer can search by product name/description/producer name (handled in views)
    """

    class Category(models.TextChoices):
        VEGETABLES = "VEGETABLES", "Vegetables"
        DAIRY_EGGS = "DAIRY_EGGS", "Dairy & Eggs"
        BAKERY = "BAKERY", "Bakery"
        PRESERVES = "PRESERVES", "Preserves"
        SEASONAL = "SEASONAL", "Seasonal Specialties"
        OTHER = "OTHER", "Other"

    class Availability(models.TextChoices):
        AVAILABLE = "AVAILABLE", "In Season (Available)"
        OUT_OF_SEASON = "OUT_OF_SEASON", "Out of Season"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    # --- Ownership ---
    # We keep this generic so it works whether you use Django's default User
    # or a custom user model in accounts.
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="catalog_products",
        help_text="The producer (seller) who owns this listing.",
    )

    # --- Core product fields (TC-003/004/005) ---
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=32, choices=Category.choices)
    description = models.TextField()

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Unit price in GBP (or your site currency).",
    )
    unit = models.CharField(
        max_length=40,
        help_text="e.g., 'kg', 'Dozen', 'Jar', 'Loaf'",
    )

    availability = models.CharField(
        max_length=20,
        choices=Availability.choices,
        default=Availability.AVAILABLE,
        help_text="Season / availability status shown to customers.",
    )

    stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Current inventory available for ordering.",
    )

    allergens = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Comma-separated allergens, e.g., 'eggs, milk'. Leave blank for none.",
    )

    harvest_date = models.DateField(
        null=True,
        blank=True,
        help_text="Harvest/collection date (if applicable).",
    )

    # Optional image upload (requires Pillow installed).
    # If your project doesn't want images yet, you can remove this field.
    image = models.ImageField(
        upload_to="catalog/products/",
        null=True,
        blank=True,
    )

    # --- Useful metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "availability"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (£{self.price})"

    # --------- Convenience helpers (used by views/templates) ---------

    @property
    def is_available(self) -> bool:
        """
        TC-004 requires: Only products marked as Available/In Season are displayed.
        """
        return self.availability == self.Availability.AVAILABLE

    @property
    def allergen_display(self) -> str:
        """
        TC-015 is separate, but for TC-003 we store allergens;
        this helper makes it easy to display "No common allergens" when empty.
        """
        cleaned = (self.allergens or "").strip()
        return cleaned if cleaned else "No common allergens"

    # --------- Model validation (helps avoid demo/test case failures) ---------

    def clean(self) -> None:
        """
        Basic business rules to prevent bad data getting into the DB.
        You can extend these later if your team agrees on extra logic.
        """
        super().clean()

        if self.price is None:
            raise ValidationError({"price": "Price is required."})

        # Prevent negative/zero pricing mistakes (common in demos).
        if self.price <= Decimal("0.00"):
            raise ValidationError({"price": "Price must be greater than 0."})

        # Stock is PositiveIntegerField, but this keeps it explicit.
        if self.stock_quantity is None:
            raise ValidationError({"stock_quantity": "Stock quantity is required."})

        # Optional: if marked available, you probably want stock > 0.
        # Comment out if your team wants 'available' with 0 stock.
        if self.availability == self.Availability.AVAILABLE and self.stock_quantity == 0:
            raise ValidationError(
                {"stock_quantity": "Available products should have stock greater than 0."}
            )

        # Optional: harvest date should not be in the future.
        if self.harvest_date and self.harvest_date > timezone.localdate():
            raise ValidationError({"harvest_date": "Harvest date cannot be in the future."})

    def save(self, *args, **kwargs):
        # Ensure model validation runs even if objects are created outside forms/admin.
        self.full_clean()
        return super().save(*args, **kwargs)


class ProductReview(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    review_text = models.TextField()
    anonymous = models.BooleanField(default=False)
    is_visible = models.BooleanField(default=True)
    producer_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "-created_at"]),
            models.Index(fields=["customer", "product"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="catalog_review_rating_between_1_and_5",
            ),
            models.UniqueConstraint(
                fields=["product", "customer"],
                name="catalog_unique_review_per_product_customer",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} review by {self.customer.username}"

    @property
    def customer_display_name(self) -> str:
        if self.anonymous:
            return "Anonymous"
        return self.customer.get_full_name() or self.customer.username

    @property
    def rating_stars(self) -> str:
        return ("\u2605" * self.rating) + ("\u2606" * (5 - self.rating))

    def clean(self) -> None:
        super().clean()

        if self.order_item_id and self.product_id and self.order_item.product_id != self.product_id:
            raise ValidationError({"order_item": "Review must match the purchased product."})

        if self.order_item_id and self.customer_id:
            if self.order_item.order.customer_id != self.customer_id:
                raise ValidationError({"order_item": "You can only review your own delivered purchases."})

            order_delivered = self.order_item.order.status == "DELIVERED"
            item_delivered = self.order_item.status == "DELIVERED"
            if not order_delivered and not item_delivered:
                raise ValidationError({"order_item": "Reviews can only be submitted after delivery."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
