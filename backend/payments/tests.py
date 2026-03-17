from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from orders.models import Order
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import PaymentRecord, ProcessedWebhookEvent, SettlementBatch

User = get_user_model()


class PaymentRecordModelTests(APITestCase):
    def test_commission_and_net_are_computed(self):
        record = PaymentRecord.objects.create(
            order_reference="ORD-1",
            transaction_reference="TXN-1",
            producer_reference="producer-1",
            gross_amount=Decimal("100.00"),
            commission_rate=Decimal("0.1200"),
            status=PaymentRecord.Status.PAID,
            paid_at=timezone.now(),
        )
        self.assertEqual(record.commission_amount, Decimal("12.00"))
        self.assertEqual(record.net_amount, Decimal("88.00"))


class SettlementGenerationTests(APITestCase):
    def setUp(self):
        user = User.objects.create_user(
            username="payments-admin@example.com",
            email="payments-admin@example.com",
            password="strong-password-123",
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_generate_settlement_groups_paid_records_by_producer(self):
        paid_at = timezone.now()
        PaymentRecord.objects.create(
            order_reference="ORD-1",
            transaction_reference="TXN-1001",
            producer_reference="producer-1",
            gross_amount=Decimal("50.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )
        PaymentRecord.objects.create(
            order_reference="ORD-2",
            transaction_reference="TXN-1002",
            producer_reference="producer-1",
            gross_amount=Decimal("100.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )

        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)
        response = self.client.post(
            reverse("settlement-generate"),
            {"week_start": week_start, "week_end": week_end},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(SettlementBatch.objects.count(), 1)
        settlement = SettlementBatch.objects.first()
        self.assertEqual(settlement.total_gross, Decimal("150.00"))
        self.assertEqual(settlement.total_commission, Decimal("15.00"))
        self.assertEqual(settlement.total_net, Decimal("135.00"))


@override_settings(STRIPE_SECRET_KEY="sk_test_dummy", STRIPE_WEBHOOK_SECRET="whsec_dummy")
class StripePaymentFlowTests(APITestCase):
    def setUp(self):
        user = User.objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        self.user = user
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_create_checkout_session_creates_pending_record(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_123",
            url="https://checkout.stripe.com/pay/cs_test_123",
            payment_intent="pi_test_123",
        )
        PaymentRecord.objects.create(
            order_reference="ORD-STRIPE-1",
            transaction_reference="TXN-STRIPE-1A",
            producer_reference="producer-1",
            customer_reference=str(self.user.id),
            gross_amount=Decimal("42.50"),
            status=PaymentRecord.Status.PENDING,
        )

        response = self.client.post(
            reverse("stripe-checkout-session"),
            {
                "order_reference": "ORD-STRIPE-1",
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        record = PaymentRecord.objects.get(id=response.data["payment_record_ids"][0])
        self.assertEqual(record.status, PaymentRecord.Status.PENDING)
        self.assertEqual(record.payment_provider, "STRIPE_TEST")
        self.assertEqual(record.checkout_session_id, "cs_test_123")
        self.assertEqual(record.provider_payment_id, "pi_test_123")
        self.assertEqual(record.commission_amount, Decimal("2.13"))
        self.assertEqual(record.net_amount, Decimal("40.37"))

    @patch("payments.stripe_gateway.stripe.Webhook.construct_event")
    def test_webhook_marks_payment_paid(self, construct_event):
        order = Order.objects.create(
            customer=self.user,
            delivery_address="1 Street",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=Decimal("100.00"),
            status=Order.Status.PENDING_PAYMENT,
        )
        record = PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference="TXN-STRIPE-2",
            producer_reference="producer-2",
            customer_reference="customer-2",
            gross_amount=Decimal("100.00"),
            checkout_session_id="cs_test_paid",
            status=PaymentRecord.Status.PENDING,
        )

        construct_event.return_value = {
            "id": "evt_paid_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_paid",
                    "payment_intent": "pi_paid_1",
                    "metadata": {"transaction_reference": "TXN-STRIPE-2"},
                }
            },
        }

        response = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, PaymentRecord.Status.PAID)
        self.assertEqual(record.provider_payment_id, "pi_paid_1")
        self.assertIsNotNone(record.paid_at)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    @patch("payments.stripe_gateway.stripe.Webhook.construct_event")
    def test_duplicate_webhook_event_is_idempotent(self, construct_event):
        order = Order.objects.create(
            customer=self.user,
            delivery_address="1 Street",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=Decimal("30.00"),
            status=Order.Status.PENDING_PAYMENT,
        )
        PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference="TXN-STRIPE-3A",
            producer_reference="producer-a",
            customer_reference=str(self.user.id),
            gross_amount=Decimal("10.00"),
            checkout_session_id="cs_test_dupe",
            status=PaymentRecord.Status.PENDING,
        )
        PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference="TXN-STRIPE-3B",
            producer_reference="producer-b",
            customer_reference=str(self.user.id),
            gross_amount=Decimal("20.00"),
            checkout_session_id="cs_test_dupe",
            status=PaymentRecord.Status.PENDING,
        )

        construct_event.return_value = {
            "id": "evt_dupe_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_dupe",
                    "payment_intent": "pi_paid_dupe",
                }
            },
        }

        first = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )
        second = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ProcessedWebhookEvent.objects.filter(event_id="evt_dupe_1").count(), 1)
        self.assertEqual(
            PaymentRecord.objects.filter(checkout_session_id="cs_test_dupe", status=PaymentRecord.Status.PAID).count(),
            2,
        )

    def test_producer_only_sees_own_payment_records(self):
        producer = User.objects.create_user(
            username="producer@example.com",
            email="producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        producer_token = Token.objects.create(user=producer)
        PaymentRecord.objects.create(
            order_reference="ORD-RBAC-1",
            transaction_reference="TXN-RBAC-1",
            producer_reference=str(producer.id),
            customer_reference=str(self.user.id),
            gross_amount=Decimal("10.00"),
        )
        PaymentRecord.objects.create(
            order_reference="ORD-RBAC-2",
            transaction_reference="TXN-RBAC-2",
            producer_reference="999",
            customer_reference=str(self.user.id),
            gross_amount=Decimal("10.00"),
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {producer_token.key}")
        resp = self.client.get(reverse("payment-records"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
