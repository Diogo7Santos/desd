from django.db import models
from django.contrib.auth.models import AbstractUser



class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        PRODUCER = "PRODUCER", "Producer"
        ADMIN = "ADMIN", "Admin"

    # override email to enforce uniqueness
    email = models.EmailField(unique=True)

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"
# Create your models here.
