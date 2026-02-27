from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import PaymentRecord, SettlementBatch

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
