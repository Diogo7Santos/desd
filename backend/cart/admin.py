from django.contrib import admin
from .models import Cart, CartItem

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['cart_id', 'customer', 'status', 'created_at', 'updated_at']
    list_filter = ['status', 'created_at']
    search_fields = ['customer__user__username']

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['cart_item_id', 'cart', 'product', 'quantity', 'unit_price_snapshot', 'added_at']
    list_filter = ['added_at']
    search_fields = ['product__name']