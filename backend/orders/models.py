from django.db import models

class Order(models.Model):
    order_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey('customer.CustomerProfile', on_delete=models.CASCADE)
    delivery_address = models.ForeignKey('address.Address', on_delete=models.SET_NULL, null=True)
    order_status = models.CharField(max_length=50)
    subtotal_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'orders'

class ProducerOrder(models.Model):
    producer_order_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='producer_orders')
    producer = models.ForeignKey('producer.ProducerProfile', on_delete=models.CASCADE)
    delivery_date = models.DateField()
    subtotal_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    producer_payout_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

class OrderItem(models.Model):
    order_item_id = models.AutoField(primary_key=True)
    producer_order = models.ForeignKey(ProducerOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE)
    product_name_snapshot = models.CharField(max_length=255)
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total_gbp = models.DecimalField(max_digits=10, decimal_places=2)

class OrderStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    previous_status = models.CharField(max_length=50, null=True, blank=True)
    new_status = models.CharField(max_length=50)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)