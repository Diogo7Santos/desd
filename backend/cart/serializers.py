from rest_framework import serializers
from .models import Cart, CartItem
from product.models import Product

class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(source='product.price_gbp', max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = CartItem
        fields = ['cart_item_id', 'cart', 'product', 'product_name', 'product_price', 'quantity', 'unit_price_snapshot', 'added_at']
        read_only_fields = ['cart_item_id', 'added_at', 'unit_price_snapshot']

class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    
    class Meta:
        model = Cart
        fields = ['cart_id', 'customer', 'status', 'created_at', 'updated_at', 'items', 'total_items', 'total_price']
        read_only_fields = ['cart_id', 'created_at', 'updated_at']
    
    def get_total_items(self, obj):
        return obj.items.count()
    
    def get_total_price(self, obj):
        return sum(item.quantity * item.unit_price_snapshot for item in obj.items.all())