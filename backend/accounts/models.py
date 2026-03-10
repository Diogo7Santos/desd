import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser

# accounts/models.py
class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        PRODUCER = "PRODUCER", "Producer"
        ADMIN = "ADMIN", "Admin"

    user_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(max_length=30, blank=True)

    @property
    def password_hash(self) -> str:
        return self.password

    @property
    def created_at(self):
        return self.date_joined

    def __str__(self):
        return self.username


class ProducerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="producer_profile")
    business_name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255)
    postcode = models.CharField(max_length=20)

    def __str__(self):
        return self.business_name


class Address(models.Model):
    address_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    line_1 = models.CharField(max_length=255)
    line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    postcode = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.line_1}, {self.city}, {self.postcode}"


class CustomerProfile(models.Model):
    class CustomerType(models.IntegerChoices):
        INDIVIDUAL = 0, "Individual"
        RESTAURANT = 1, "Restaurant"
        COMMUNITY_GROUP = 2, "Community Group"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_profile")
    customer_type_id = models.IntegerField(choices=CustomerType.choices)
    address = models.OneToOneField(Address, on_delete=models.CASCADE, related_name="customer_profile")

    def __str__(self):
        return f"{self.user.username} ({self.get_customer_type_id_display()})"
# Create your models here.
