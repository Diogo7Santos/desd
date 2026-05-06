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
    - TC-003: Producer can create product with required fields
    - TC-004: Customer can browse by category and only see Available/In Season products
    - TC-005: Customer can search by product name/description/producer name
    - TC-014: Customer can filter products by organic certification
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

    # NEW: Organic certification support (TC-014)
    class OrganicStatus(models.TextChoices):
        CERTIFIED = "CERTIFIED", "Certified Organic"
        NON_CERTIFIED = "NON_CERTIFIED", "Not Certified Organic"

    # --- Ownership ---
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="catalog_products",
        help_text="The producer (seller) who owns this listing.",
    )

    # --- Core product fields ---
    name = models.CharField(max_length=120)

    category = models.CharField(
        max_length=32,
        choices=Category.choices
    )

    # NEW FIELD
    organic_status = models.CharField(
        max_length=20,
        choices=OrganicStatus.choices,
        default=OrganicStatus.NON_CERTIFIED,
        help_text="Organic certification status for filtering and display.",
    )

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
            models.Index(fields=["organic_status"]),  # NEW INDEX
        ]

    def __str__(self) -> str:
        return f"{self.name} (£{self.price})"

    # --------- Convenience helpers ---------

    @property
    def is_available(self) -> bool:
        """
        TC-004 requires:
        Only products marked as Available/In Season are displayed.
        """
        return self.availability == self.Availability.AVAILABLE

    @property
    def is_certified_organic(self) -> bool:
        """
        TC-014 helper for templates/views.
        """
        return self.organic_status == self.OrganicStatus.CERTIFIED

    @property
    def allergen_display(self) -> str:
        """
        Makes it easy to display
        "No common allergens" when empty.
        """
        cleaned = (self.allergens or "").strip()
        return cleaned if cleaned else "No common allergens"

    # --------- Model validation ---------

    def clean(self) -> None:
        """
        Basic business rules to prevent bad data getting into the DB.
        """
        super().clean()

        if self.price is None:
            raise ValidationError({"price": "Price is required."})

        if self.price <= Decimal("0.00"):
            raise ValidationError({"price": "Price must be greater than 0."})

        if self.stock_quantity is None:
            raise ValidationError(
                {"stock_quantity": "Stock quantity is required."}
            )

        if (
            self.availability == self.Availability.AVAILABLE
            and self.stock_quantity == 0
        ):
            raise ValidationError(
                {
                    "stock_quantity":
                        "Available products should have stock greater than 0."
                }
            )

        if (
            self.harvest_date
            and self.harvest_date > timezone.localdate()
        ):
            raise ValidationError(
                {"harvest_date": "Harvest date cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        # Ensure model validation runs even if objects are created outside forms/admin.
        self.full_clean()
        return super().save(*args, **kwargs)