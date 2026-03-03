from rest_framework import serializers
from .models import Order, ProducerOrder, OrderItem, OrderStatusHistory

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['order_item_id', 'producer_order', 'product', 'product_name_snapshot', 'unit_price_snapshot', 'quantity', 'line_total_gbp']
        read_only_fields = ['order_item_id']

class ProducerOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = ProducerOrder
        fields = ['producer_order_id', 'order', 'producer', 'delivery_date', 'subtotal_gbp', 'producer_payout_gbp', 'status', 'created_at', 'items']
        read_only_fields = ['producer_order_id', 'created_at']

class OrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True)
    
    class Meta:
        model = OrderStatusHistory
        fields = ['history_id', 'order', 'previous_status', 'new_status', 'changed_at', 'changed_by', 'changed_by_username']
        read_only_fields = ['history_id', 'changed_at']

class OrderSerializer(serializers.ModelSerializer):
    producer_orders = ProducerOrderSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    
    class Meta:
        model = Order
        fields = ['order_id', 'customer', 'delivery_address', 'order_status', 'subtotal_gbp', 'commission_rate', 'commission_amount_gbp', 'total_amount_gbp', 'created_at', 'producer_orders', 'status_history']
        read_only_fields = ['order_id', 'created_at']