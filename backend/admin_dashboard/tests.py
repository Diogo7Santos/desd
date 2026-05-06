from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from payments.models import PaymentRecord, SettlementBatch

User = get_user_model()


class AdminDashboardAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="strong-password-123",
            role="ADMIN",
        )
        self.producer = User.objects.create_user(
            username="producer@example.com",
            email="producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.customer = User.objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

    def test_admin_can_access_portal(self):
        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_producer_denied(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_customer_denied(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirected_to_login(self):
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class AdminDashboardDataTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin2@example.com",
            email="admin2@example.com",
            password="strong-password-123",
            role="ADMIN",
        )
        self.customer = User.objects.create_user(
            username="customer2@example.com",
            email="customer2@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        self.producer = User.objects.create_user(
            username="producer2@example.com",
            email="producer2@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )

        self.order = Order.objects.create(
            customer=self.customer,
            delivery_address="1 Test Road",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=Decimal("100.00"),
            status=Order.Status.PENDING,
        )

        self.record_pending = PaymentRecord.objects.create(
            order_reference=self.order.order_number,
            transaction_reference="TXN-ADMIN-1",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("100.00"),
            commission_rate=Decimal("0.0500"),
            status=PaymentRecord.Status.PENDING,
        )
        self.record_failed = PaymentRecord.objects.create(
            order_reference=self.order.order_number,
            transaction_reference="TXN-ADMIN-2",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("50.00"),
            commission_rate=Decimal("0.0500"),
            status=PaymentRecord.Status.FAILED,
        )
        self.settlement = SettlementBatch.objects.create(
            producer_reference=str(self.producer.id),
            week_start=timezone.now().date() - timedelta(days=7),
            week_end=timezone.now().date(),
            total_gross=Decimal("150.00"),
            total_commission=Decimal("7.50"),
            total_net=Decimal("142.50"),
            status=SettlementBatch.Status.OPEN,
        )

    def test_dashboard_context_contains_required_kpis(self):
        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertEqual(response.status_code, 200)

        context = response.context
        self.assertEqual(context["total_users"], 3)
        self.assertEqual(context["total_producers"], 1)
        self.assertEqual(context["total_customers"], 1)
        self.assertEqual(context["total_orders"], 1)
        self.assertEqual(context["total_payment_value"], Decimal("150.00"))
        self.assertEqual(context["total_commission"], Decimal("7.50"))
        self.assertEqual(context["pending_payments"], 1)
        self.assertEqual(context["failed_payments"], 1)
        self.assertEqual(context["settlement_count"], 1)

    def test_quick_links_render(self):
        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin_dashboard:dashboard"))
        self.assertContains(response, reverse("admin-financial-report"))
        self.assertContains(response, reverse("admin-financial-report-csv"))
        self.assertContains(response, reverse("payments-records-page"))
        self.assertContains(response, reverse("payments-settlements-page"))
        self.assertContains(response, reverse("admin:index"))

    def test_existing_payment_and_financial_routes_still_resolve(self):
        self.assertTrue(reverse("admin-financial-report"))
        self.assertTrue(reverse("admin-financial-report-csv"))
        self.assertTrue(reverse("payments-records-page"))
        self.assertTrue(reverse("payments-settlements-page"))
