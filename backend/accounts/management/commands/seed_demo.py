from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.models import ProducerProfile, CustomerProfile, Address

User = get_user_model()

DEMO_PASSWORD = "StrongPass123!"


class Command(BaseCommand):
    help = "Create demo users and related profiles for development/testing."

    @transaction.atomic
    def handle(self, *args, **options):
        self.create_admin()
        self.create_producer()
        self.create_customer_individual()
        self.create_customer_restaurant()
        self.create_customer_community_group()

        self.stdout.write(self.style.SUCCESS(f"\nDemo password for all users: {DEMO_PASSWORD}"))

    def create_admin(self):
        email = "admin_demo@example.com"

        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                "email": email,
                "role": User.Role.ADMIN,
                "phone": "01170000001",
                "is_staff": True,
                "is_superuser": True,
            },
        )

        user.email = email
        user.username = email
        user.role = User.Role.ADMIN
        user.phone = "01170000001"
        user.is_staff = True
        user.is_superuser = True
        user.set_password(DEMO_PASSWORD)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} admin user: {email}")
        )

    def create_producer(self):
        email = "producer_demo@example.com"

        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                "email": email,
                "role": User.Role.PRODUCER,
                "phone": "01170000002",
                "first_name": "Jane",
                "last_name": "Smith",
            },
        )

        user.email = email
        user.username = email
        user.role = User.Role.PRODUCER
        user.phone = "01170000002"
        user.first_name = "Jane"
        user.last_name = "Smith"
        user.set_password(DEMO_PASSWORD)
        user.save()

        ProducerProfile.objects.update_or_create(
            user=user,
            defaults={
                "business_name": "Bristol Valley Farm",
                "contact_name": "Jane Smith",
                "business_address": "45 Valley Road, Bristol",
                "postcode": "BS1 4DJ",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} producer user: {email}")
        )

    def create_customer_individual(self):
        self._create_customer(
            email="customer_demo@example.com",
            phone="07700900123",
            first_name="Robert",
            last_name="Johnson",
            customer_type=CustomerProfile.CustomerType.INDIVIDUAL,
            line_1="45 Park Street",
            line_2="",
            city="Bristol",
            postcode="BS1 5JG",
        )

    def create_customer_restaurant(self):
        self._create_customer(
            email="restaurant_demo@example.com",
            phone="07700900124",
            first_name="Olivia",
            last_name="Brown",
            customer_type=CustomerProfile.CustomerType.RESTAURANT,
            line_1="10 King Street",
            line_2="Unit 2",
            city="Bristol",
            postcode="BS1 6AA",
        )

    def create_customer_community_group(self):
        self._create_customer(
            email="community_demo@example.com",
            phone="07700900125",
            first_name="Ava",
            last_name="Wilson",
            customer_type=CustomerProfile.CustomerType.COMMUNITY_GROUP,
            line_1="22 Market Road",
            line_2="",
            city="Bristol",
            postcode="BS2 9ZZ",
        )

    def _create_customer(
        self,
        *,
        email,
        phone,
        first_name,
        last_name,
        customer_type,
        line_1,
        line_2,
        city,
        postcode,
    ):
        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                "email": email,
                "role": User.Role.CUSTOMER,
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name,
            },
        )

        user.email = email
        user.username = email
        user.role = User.Role.CUSTOMER
        user.phone = phone
        user.first_name = first_name
        user.last_name = last_name
        user.set_password(DEMO_PASSWORD)
        user.save()

        address, _ = Address.objects.update_or_create(
            user=user,
            defaults={
                "line_1": line_1,
                "line_2": line_2,
                "city": city,
                "postcode": postcode,
            },
        )

        CustomerProfile.objects.update_or_create(
            user=user,
            defaults={
                "customer_type_id": customer_type,
                "address": address,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} customer user: {email}")
        )