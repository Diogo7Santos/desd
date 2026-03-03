from django.db import models
from django.contrib.auth.models import User

class CustomerProfile(models.Model):
    customer_id = models.AutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    default_address = models.ForeignKey('address.Address', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)