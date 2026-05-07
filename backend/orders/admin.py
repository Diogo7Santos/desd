from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer", "status", "total_amount", "delivery_date", "created_at")
    list_filter = ("status", "delivery_date", "created_at")
    search_fields = ("order_number", "customer__username", "customer__email", "delivery_postcode")
    readonly_fields = ("order_number", "created_at", "updated_at")


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "producer", "product_name", "quantity", "unit_price", "subtotal")
    list_filter = ("producer",)
    search_fields = ("order__order_number", "product_name", "producer__username")


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "changed_by", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("order__order_number", "changed_by__username", "notes")
