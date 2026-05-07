# backend/catalog/admin.py

from django.contrib import admin

from .models import Product, ProductReview


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Admin configuration for fast test data entry and debugging.

    Useful for:
    - Seeding categories (TC-004 preconditions)
    - Quickly verifying product fields (TC-003)
    - Checking availability filtering (TC-004/TC-005)
    """

    list_display = (
        "id",
        "name",
        "category",
        "availability",
        "price",
        "unit",
        "stock_quantity",
        "producer",
        "harvest_date",
        "created_at",
    )
    list_filter = ("category", "availability", "harvest_date", "created_at")
    search_fields = (
        "name",
        "description",
        "allergens",
        "producer__username",
        "producer__first_name",
        "producer__last_name",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    fieldsets = (
        ("Ownership", {"fields": ("producer",)}),
        (
            "Product Details",
            {
                "fields": (
                    "name",
                    "category",
                    "description",
                    "price",
                    "unit",
                    "availability",
                    "stock_quantity",
                )
            },
        ),
        ("Food Information", {"fields": ("allergens", "harvest_date")}),
        ("Media", {"fields": ("image",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "customer",
        "rating",
        "anonymous",
        "is_visible",
        "created_at",
        "responded_at",
    )
    list_filter = ("rating", "anonymous", "is_visible", "created_at", "responded_at")
    search_fields = (
        "product__name",
        "customer__username",
        "customer__email",
        "title",
        "review_text",
        "producer_response",
    )
    readonly_fields = ("created_at", "updated_at", "responded_at")
    ordering = ("-created_at",)

    fieldsets = (
        ("Links", {"fields": ("product", "customer", "order_item")}),
        ("Review", {"fields": ("rating", "title", "review_text", "anonymous", "is_visible")}),
        ("Producer Response", {"fields": ("producer_response", "responded_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
