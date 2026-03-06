from django.db import models
from django.contrib.auth.models import AbstractUser



# accounts/models.py
import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        PRODUCER = "PRODUCER", "Producer"
        ADMIN = "ADMIN", "Admin"

    class CustomerType(models.IntegerChoices):
        INDIVIDUAL = 0, "Individual"
        RESTAURANT = 1, "Restaurant"
        COMMUNITY_GROUP = 2, "Community Group"

    # Random user ID
    user_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)

    phone = models.CharField(max_length=30, blank=True)

    customer_type_id = models.IntegerField(
        choices=CustomerType.choices,
        null=True,
        blank=True,
    )

    @property
    def password_hash(self) -> str:
        return self.password  # Django hashed password column

    @property
    def created_at(self):
        return self.date_joined  # Django join timestamp
# Create your models here.
