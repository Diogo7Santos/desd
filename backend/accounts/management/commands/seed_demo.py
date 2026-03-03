from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

DEMO_PASSWORD = "StrongPass123!"


class Command(BaseCommand):
    help = "Create demo users for development/testing."

    def handle(self, *args, **options):
        users = [
            # username, email, role
            ("customer_demo", "customer_demo@example.com", User.Role.CUSTOMER),
            ("producer_demo", "producer_demo@example.com", User.Role.PRODUCER),
            ("admin_demo", "admin_demo@example.com", getattr(User.Role, "ADMIN", "ADMIN")),
        ]

        for username, email, role in users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
            user.email = email

            # Set role if it exists (for compatibility with older versions)
            if hasattr(user, "role"):
                user.role = role

            # Make admin usable
            if role == "ADMIN":
                user.is_staff = True
                user.is_superuser = True

            user.save()
            self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} {username} ({role})"))

        self.stdout.write(self.style.SUCCESS(f"Demo password for all users: {DEMO_PASSWORD}"))