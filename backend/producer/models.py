from django.db import models
from django.contrib.auth.models import User

class ProducerProfile(models.Model):
    producer_id = models.AutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    farm_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    business_postcode = models.CharField(max_length=20)
    lead_time_hours = models.IntegerField(default=24)
    verification_status = models.CharField(max_length=50, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)