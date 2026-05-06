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
    business_address = models.CharField(max_length=255)
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
        YOUNG_PROFESSIONAL = 3, "Young Professional"
        FAMILIES = 4, "Families"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_profile")
    customer_type_id = models.IntegerField(choices=CustomerType.choices)
    address = models.OneToOneField(Address, on_delete=models.CASCADE, related_name="customer_profile")

    organisation_name = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    is_charity_or_education = models.BooleanField(default=False)
    is_business_verified = models.BooleanField(default=False)
    default_delivery_instructions = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_customer_type_id_display()})"

    @property
    def is_restaurant(self):
        return self.customer_type_id == self.CustomerType.RESTAURANT

    @property
    def is_community_group(self):
        return self.customer_type_id == self.CustomerType.COMMUNITY_GROUP
    
    @property
    def is_young_professional(self):
        return self.customer_type_id == self.CustomerType.YOUNG_PROFESSIONAL

    @property
    def is_families(self):
        return self.customer_type_id == self.CustomerType.FAMILIES
# Create your models here.
