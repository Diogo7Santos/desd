from django.db import models

class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    producer = models.ForeignKey('producer.ProducerProfile', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50)
    price_gbp = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)