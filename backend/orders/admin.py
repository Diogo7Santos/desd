from django.contrib import admin
from .models import Order, ProducerOrder, OrderItem, OrderStatusHistory

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'customer', 'order_status', 'total_amount_gbp', 'created_at']
    list_filter = ['order_status', 'created_at']
    search_fields = ['customer__user__username']

@admin.register(ProducerOrder)
class ProducerOrderAdmin(admin.ModelAdmin):
    list_display = ['producer_order_id', 'order', 'producer', 'status', 'delivery_date', 'producer_payout_gbp']
    list_filter = ['status', 'delivery_date']

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order_item_id', 'producer_order', 'product_name_snapshot', 'quantity', 'line_total_gbp']

@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ['history_id', 'order', 'previous_status', 'new_status', 'changed_at', 'changed_by']
    list_filter = ['new_status', 'changed_at']