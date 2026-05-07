import csv
import io
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from cart.models import Cart, CartItem
from catalog.models import Product
from orders.models import Order
from orders.models import OrderItem
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import PaymentRecord, ProcessedWebhookEvent, SettlementBatch
from .services_settlements import generate_settlements_for_week
from .tasks import generate_weekly_settlements

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
            role="ADMIN",
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.customer = User.objects.create_user(
            username="settlement-customer@example.com",
            email="settlement-customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

    def _create_order(self, *, status, total=Decimal("100.00")):
        return Order.objects.create(
            customer=self.customer,
            delivery_address="1 Settlement Street",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=total,
            status=status,
        )

    def test_generate_settlement_groups_paid_records_by_producer(self):
        paid_at = timezone.now()
        delivered_a = self._create_order(status=Order.Status.DELIVERED)
        delivered_b = self._create_order(status=Order.Status.DELIVERED)
        PaymentRecord.objects.create(
            order_reference=delivered_a.order_number,
            transaction_reference="TXN-1001",
            producer_reference="producer-1",
            gross_amount=Decimal("50.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )
        PaymentRecord.objects.create(
            order_reference=delivered_b.order_number,
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

    def test_paid_and_delivered_is_included(self):
        paid_at = timezone.now()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        eligible = PaymentRecord.objects.create(
            order_reference=delivered.order_number,
            transaction_reference="TXN-ELIGIBLE",
            producer_reference="producer-a",
            gross_amount=Decimal("25.00"),
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
        settlement = SettlementBatch.objects.get(producer_reference="producer-a")
        self.assertEqual(settlement.items.count(), 1)
        self.assertEqual(settlement.items.first().payment_record_id, eligible.id)

    def test_paid_and_ready_is_included(self):
        paid_at = timezone.now()
        ready = self._create_order(status=Order.Status.READY)
        eligible = PaymentRecord.objects.create(
            order_reference=ready.order_number,
            transaction_reference="TXN-ELIGIBLE-READY",
            producer_reference="producer-ready",
            gross_amount=Decimal("45.00"),
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
        settlement = SettlementBatch.objects.get(producer_reference="producer-ready")
        self.assertEqual(settlement.items.count(), 1)
        self.assertEqual(settlement.items.first().payment_record_id, eligible.id)

    def test_paid_but_not_ready_or_delivered_is_excluded(self):
        paid_at = timezone.now()
        pending = self._create_order(status=Order.Status.PENDING)
        PaymentRecord.objects.create(
            order_reference=pending.order_number,
            transaction_reference="TXN-PAID-NOT-READY-DELIVERED",
            producer_reference="producer-b",
            gross_amount=Decimal("30.00"),
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
        self.assertFalse(SettlementBatch.objects.filter(producer_reference="producer-b").exists())

    def test_unpaid_ready_is_excluded(self):
        paid_at = timezone.now()
        ready = self._create_order(status=Order.Status.READY)
        PaymentRecord.objects.create(
            order_reference=ready.order_number,
            transaction_reference="TXN-READY-NOT-PAID",
            producer_reference="producer-ready-unpaid",
            gross_amount=Decimal("35.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PENDING,
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
        self.assertFalse(SettlementBatch.objects.filter(producer_reference="producer-ready-unpaid").exists())

    def test_not_paid_but_delivered_is_excluded(self):
        paid_at = timezone.now()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        PaymentRecord.objects.create(
            order_reference=delivered.order_number,
            transaction_reference="TXN-DELIVERED-NOT-PAID",
            producer_reference="producer-c",
            gross_amount=Decimal("35.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PENDING,
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
        self.assertFalse(SettlementBatch.objects.filter(producer_reference="producer-c").exists())

    def test_already_settled_ready_is_excluded(self):
        from .models import SettlementItem

        paid_at = timezone.now()
        ready = self._create_order(status=Order.Status.READY)
        settled_record = PaymentRecord.objects.create(
            order_reference=ready.order_number,
            transaction_reference="TXN-ALREADY-SETTLED-READY",
            producer_reference="producer-d",
            gross_amount=Decimal("40.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )

        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)
        existing = SettlementBatch.objects.create(
            producer_reference="producer-d",
            week_start=week_start,
            week_end=week_end,
            total_gross=Decimal("40.00"),
            total_commission=Decimal("4.00"),
            total_net=Decimal("36.00"),
        )
        SettlementItem.objects.create(settlement=existing, payment_record=settled_record)

        response = self.client.post(
            reverse("settlement-generate"),
            {"week_start": week_start, "week_end": week_end},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(SettlementBatch.objects.filter(producer_reference="producer-d").count(), 1)
        self.assertEqual(existing.items.count(), 1)

    def test_totals_remain_correct_per_producer(self):
        paid_at = timezone.now()
        delivered_a = self._create_order(status=Order.Status.DELIVERED)
        delivered_b = self._create_order(status=Order.Status.DELIVERED)
        PaymentRecord.objects.create(
            order_reference=delivered_a.order_number,
            transaction_reference="TXN-TOTAL-1",
            producer_reference="producer-e",
            gross_amount=Decimal("40.00"),
            commission_rate=Decimal("0.0500"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )
        PaymentRecord.objects.create(
            order_reference=delivered_b.order_number,
            transaction_reference="TXN-TOTAL-2",
            producer_reference="producer-e",
            gross_amount=Decimal("60.00"),
            commission_rate=Decimal("0.0500"),
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
        settlement = SettlementBatch.objects.get(producer_reference="producer-e")
        self.assertEqual(settlement.total_gross, Decimal("100.00"))
        self.assertEqual(settlement.total_commission, Decimal("5.00"))
        self.assertEqual(settlement.total_net, Decimal("95.00"))


class SettlementServiceAndTaskTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="settlement-task-customer@example.com",
            email="settlement-task-customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

    def _create_order(self, *, status, total=Decimal("100.00")):
        return Order.objects.create(
            customer=self.customer,
            delivery_address="2 Settlement Street",
            delivery_postcode="BS2 2BB",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=total,
            status=status,
        )

    def _create_paid_record(self, *, order, producer_reference, transaction_reference, paid_at):
        return PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference=transaction_reference,
            producer_reference=producer_reference,
            gross_amount=Decimal("50.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )

    def test_shared_service_creates_settlement_for_paid_and_delivered(self):
        paid_at = timezone.now()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered,
            producer_reference="producer-service",
            transaction_reference="TXN-SERVICE-1",
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)

        result = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["created_settlement_ids"]), 1)
        settlement = SettlementBatch.objects.get(producer_reference="producer-service")
        self.assertEqual(settlement.items.count(), 1)

    def test_shared_service_creates_settlement_for_paid_and_ready(self):
        paid_at = timezone.now()
        ready = self._create_order(status=Order.Status.READY)
        self._create_paid_record(
            order=ready,
            producer_reference="producer-service-ready",
            transaction_reference="TXN-SERVICE-READY-1",
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)

        result = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(result["count"], 1)
        settlement = SettlementBatch.objects.get(producer_reference="producer-service-ready")
        self.assertEqual(settlement.items.count(), 1)

    def test_task_creates_settlements_for_previous_week(self):
        fake_today = timezone.datetime(2026, 5, 20).date()  # Wednesday
        previous_week_start = fake_today - timedelta(days=fake_today.weekday() + 7)
        paid_at = timezone.make_aware(timezone.datetime(2026, 5, 12, 10, 0, 0))
        delivered = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered,
            producer_reference="producer-task-week",
            transaction_reference="TXN-TASK-WEEK-1",
            paid_at=paid_at,
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 1)
        settlement = SettlementBatch.objects.get(producer_reference="producer-task-week")
        self.assertEqual(settlement.week_start, previous_week_start)
        self.assertEqual(settlement.week_end, previous_week_start + timedelta(days=6))

    def test_task_creates_settlements_for_previous_week_ready_order(self):
        fake_today = timezone.datetime(2026, 5, 20).date()  # Wednesday
        previous_week_start = fake_today - timedelta(days=fake_today.weekday() + 7)
        paid_at = timezone.make_aware(timezone.datetime(2026, 5, 12, 10, 0, 0))
        ready = self._create_order(status=Order.Status.READY)
        self._create_paid_record(
            order=ready,
            producer_reference="producer-task-week-ready",
            transaction_reference="TXN-TASK-WEEK-READY-1",
            paid_at=paid_at,
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 1)
        settlement = SettlementBatch.objects.get(producer_reference="producer-task-week-ready")
        self.assertEqual(settlement.week_start, previous_week_start)
        self.assertEqual(settlement.week_end, previous_week_start + timedelta(days=6))

    def test_task_excludes_unpaid_records(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        PaymentRecord.objects.create(
            order_reference=delivered.order_number,
            transaction_reference="TXN-TASK-UNPAID",
            producer_reference="producer-task-unpaid",
            gross_amount=Decimal("50.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PENDING,
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 12, 9, 0, 0)),
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 0)
        self.assertFalse(SettlementBatch.objects.filter(producer_reference="producer-task-unpaid").exists())

    def test_task_excludes_orders_not_ready_or_delivered(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        pending = self._create_order(status=Order.Status.PENDING)
        self._create_paid_record(
            order=pending,
            producer_reference="producer-task-undelivered",
            transaction_reference="TXN-TASK-UNDELIVERED",
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 12, 11, 0, 0)),
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 0)
        self.assertFalse(SettlementBatch.objects.filter(producer_reference="producer-task-undelivered").exists())

    def test_task_excludes_already_settled_ready_records(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        ready = self._create_order(status=Order.Status.READY)
        paid_record = self._create_paid_record(
            order=ready,
            producer_reference="producer-task-settled",
            transaction_reference="TXN-TASK-SETTLED",
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 12, 11, 30, 0)),
        )
        week_start = fake_today - timedelta(days=fake_today.weekday() + 7)
        week_end = week_start + timedelta(days=6)
        existing = SettlementBatch.objects.create(
            producer_reference="producer-task-settled",
            week_start=week_start,
            week_end=week_end,
            total_gross=Decimal("50.00"),
            total_commission=Decimal("5.00"),
            total_net=Decimal("45.00"),
        )
        existing.items.create(payment_record=paid_record)

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 0)
        self.assertEqual(SettlementBatch.objects.filter(producer_reference="producer-task-settled").count(), 1)

    def test_task_is_idempotent_on_rerun(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered,
            producer_reference="producer-task-idempotent",
            transaction_reference="TXN-TASK-IDEMPOTENT",
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 12, 12, 0, 0)),
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            first = generate_weekly_settlements()
        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            second = generate_weekly_settlements()

        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 0)
        self.assertEqual(SettlementBatch.objects.filter(producer_reference="producer-task-idempotent").count(), 1)
        self.assertEqual(SettlementBatch.objects.get(producer_reference="producer-task-idempotent").items.count(), 1)

    def test_task_multi_producer_grouping_remains_correct(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        delivered_a = self._create_order(status=Order.Status.DELIVERED)
        delivered_b = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered_a,
            producer_reference="producer-task-a",
            transaction_reference="TXN-TASK-A",
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 12, 13, 0, 0)),
        )
        self._create_paid_record(
            order=delivered_b,
            producer_reference="producer-task-b",
            transaction_reference="TXN-TASK-B",
            paid_at=timezone.make_aware(timezone.datetime(2026, 5, 13, 13, 0, 0)),
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 2)
        self.assertTrue(SettlementBatch.objects.filter(producer_reference="producer-task-a").exists())
        self.assertTrue(SettlementBatch.objects.filter(producer_reference="producer-task-b").exists())

    def test_existing_batch_with_zero_items_gets_repaired(self):
        paid_at = timezone.now()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered,
            producer_reference="producer-repair-zero",
            transaction_reference="TXN-REPAIR-ZERO-1",
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)
        settlement = SettlementBatch.objects.create(
            producer_reference="producer-repair-zero",
            week_start=week_start,
            week_end=week_end,
            total_gross=Decimal("0.00"),
            total_commission=Decimal("0.00"),
            total_net=Decimal("0.00"),
        )

        result = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(result["count"], 0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.items.count(), 1)
        self.assertEqual(settlement.total_gross, Decimal("50.00"))
        self.assertEqual(settlement.total_commission, Decimal("5.00"))
        self.assertEqual(settlement.total_net, Decimal("45.00"))

    def test_existing_batch_with_partial_items_links_only_missing_records(self):
        from .models import SettlementItem

        paid_at = timezone.now()
        delivered_a = self._create_order(status=Order.Status.DELIVERED)
        delivered_b = self._create_order(status=Order.Status.DELIVERED)
        first = self._create_paid_record(
            order=delivered_a,
            producer_reference="producer-repair-partial",
            transaction_reference="TXN-REPAIR-PARTIAL-1",
            paid_at=paid_at,
        )
        second = self._create_paid_record(
            order=delivered_b,
            producer_reference="producer-repair-partial",
            transaction_reference="TXN-REPAIR-PARTIAL-2",
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)
        settlement = SettlementBatch.objects.create(
            producer_reference="producer-repair-partial",
            week_start=week_start,
            week_end=week_end,
            total_gross=Decimal("50.00"),
            total_commission=Decimal("5.00"),
            total_net=Decimal("45.00"),
        )
        SettlementItem.objects.create(settlement=settlement, payment_record=first)

        result = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(result["count"], 0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.items.count(), 2)
        self.assertTrue(settlement.items.filter(payment_record=first).exists())
        self.assertTrue(settlement.items.filter(payment_record=second).exists())

    def test_rerunning_generation_does_not_duplicate_settlement_items(self):
        paid_at = timezone.now()
        delivered = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered,
            producer_reference="producer-no-dup-items",
            transaction_reference="TXN-NO-DUP-ITEMS-1",
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)

        first = generate_settlements_for_week(week_start=week_start, week_end=week_end)
        second = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 0)
        settlement = SettlementBatch.objects.get(producer_reference="producer-no-dup-items")
        self.assertEqual(settlement.items.count(), 1)

    def test_totals_are_corrected_for_existing_batch_after_linking(self):
        paid_at = timezone.now()
        delivered_a = self._create_order(status=Order.Status.DELIVERED)
        delivered_b = self._create_order(status=Order.Status.DELIVERED)
        self._create_paid_record(
            order=delivered_a,
            producer_reference="producer-correct-totals",
            transaction_reference="TXN-CORRECT-TOTALS-1",
            paid_at=paid_at,
        )
        PaymentRecord.objects.create(
            order_reference=delivered_b.order_number,
            transaction_reference="TXN-CORRECT-TOTALS-2",
            producer_reference="producer-correct-totals",
            gross_amount=Decimal("80.00"),
            commission_rate=Decimal("0.1000"),
            status=PaymentRecord.Status.PAID,
            paid_at=paid_at,
        )
        week_start = (paid_at - timedelta(days=paid_at.weekday())).date()
        week_end = week_start + timedelta(days=6)
        settlement = SettlementBatch.objects.create(
            producer_reference="producer-correct-totals",
            week_start=week_start,
            week_end=week_end,
            total_gross=Decimal("1.00"),
            total_commission=Decimal("1.00"),
            total_net=Decimal("1.00"),
        )

        result = generate_settlements_for_week(week_start=week_start, week_end=week_end)

        self.assertEqual(result["count"], 0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.items.count(), 2)
        self.assertEqual(settlement.total_gross, Decimal("130.00"))
        self.assertEqual(settlement.total_commission, Decimal("13.00"))
        self.assertEqual(settlement.total_net, Decimal("117.00"))

    def test_task_repairs_existing_batch_missing_items_via_shared_logic(self):
        fake_today = timezone.datetime(2026, 5, 20).date()
        previous_week_start = fake_today - timedelta(days=fake_today.weekday() + 7)
        previous_week_end = previous_week_start + timedelta(days=6)
        paid_at = timezone.make_aware(timezone.datetime(2026, 5, 12, 15, 0, 0))
        ready = self._create_order(status=Order.Status.READY)
        self._create_paid_record(
            order=ready,
            producer_reference="producer-task-repair-shared",
            transaction_reference="TXN-TASK-REPAIR-SHARED-1",
            paid_at=paid_at,
        )
        settlement = SettlementBatch.objects.create(
            producer_reference="producer-task-repair-shared",
            week_start=previous_week_start,
            week_end=previous_week_end,
            total_gross=Decimal("0.00"),
            total_commission=Decimal("0.00"),
            total_net=Decimal("0.00"),
        )

        with patch("payments.tasks.timezone.localdate", return_value=fake_today):
            result = generate_weekly_settlements()

        self.assertEqual(result["count"], 0)
        settlement.refresh_from_db()
        self.assertEqual(settlement.items.count(), 1)
        self.assertEqual(settlement.total_gross, Decimal("50.00"))


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
        self.producer = User.objects.create_user(
            username="producer@example.com",
            email="producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.product = Product.objects.create(
            producer=self.producer,
            name="Apples",
            category=Product.Category.VEGETABLES,
            description="Fresh apples",
            price=Decimal("5.00"),
            unit="kg",
            stock_quantity=30,
            availability=Product.Availability.AVAILABLE,
        )

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
        OrderItem.objects.create(
            order=order,
            product=self.product,
            producer=self.producer,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=3,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)

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
        self.assertNotEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 27)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)

    @patch("payments.stripe_gateway.stripe.Webhook.construct_event")
    def test_webhook_failed_does_not_change_stock_or_cart(self, construct_event):
        order = Order.objects.create(
            customer=self.user,
            delivery_address="2 Street",
            delivery_postcode="BS1 2AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=Decimal("10.00"),
            status=Order.Status.PENDING_PAYMENT,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            producer=self.producer,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=2,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        record = PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference="TXN-STRIPE-FAILED-1",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.user.id),
            gross_amount=Decimal("10.00"),
            checkout_session_id="cs_test_failed",
            status=PaymentRecord.Status.PENDING,
        )

        construct_event.return_value = {
            "id": "evt_failed_1",
            "type": "checkout.session.expired",
            "data": {
                "object": {
                    "id": "cs_test_failed",
                    "payment_intent": "pi_failed_1",
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
        self.assertEqual(record.status, PaymentRecord.Status.FAILED)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 30)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 1)

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

    @patch("payments.stripe_gateway.stripe.Webhook.construct_event")
    def test_multiple_success_webhooks_do_not_decrement_stock_twice(self, construct_event):
        order = Order.objects.create(
            customer=self.user,
            delivery_address="3 Street",
            delivery_postcode="BS1 3AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=Decimal("15.00"),
            status=Order.Status.PENDING_PAYMENT,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            producer=self.producer,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=2,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference="TXN-STRIPE-DOUBLE-1",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.user.id),
            gross_amount=Decimal("15.00"),
            checkout_session_id="cs_test_double_success",
            status=PaymentRecord.Status.PENDING,
        )

        construct_event.return_value = {
            "id": "evt_double_success_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_double_success",
                    "payment_intent": "pi_double_1",
                }
            },
        }
        first = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        # A second successful event with a different event id for the same session
        # should not re-run stock/cart finalisation.
        construct_event.return_value = {
            "id": "evt_double_success_2",
            "type": "checkout.session.async_payment_succeeded",
            "data": {
                "object": {
                    "id": "cs_test_double_success",
                    "payment_intent": "pi_double_1",
                }
            },
        }
        second = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 28)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)


class PaymentsWebRBACTests(TestCase):
    def setUp(self):
        self.producer = User.objects.create_user(
            username="producer-web@example.com",
            email="producer-web@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.admin = User.objects.create_user(
            username="admin-web@example.com",
            email="admin-web@example.com",
            password="strong-password-123",
            role="ADMIN",
        )
        self.customer = User.objects.create_user(
            username="customer-web@example.com",
            email="customer-web@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

        now = timezone.now()
        PaymentRecord.objects.create(
            order_reference="ORD-WEB-1",
            transaction_reference="TXN-WEB-1",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("20.00"),
            status=PaymentRecord.Status.PAID,
            paid_at=now,
        )
        PaymentRecord.objects.create(
            order_reference="ORD-WEB-2",
            transaction_reference="TXN-WEB-2",
            producer_reference="999999",
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("30.00"),
            status=PaymentRecord.Status.PAID,
            paid_at=now,
        )

        SettlementBatch.objects.create(
            producer_reference=str(self.producer.id),
            week_start=(now - timedelta(days=7)).date(),
            week_end=now.date(),
            total_gross=Decimal("20.00"),
            total_commission=Decimal("1.00"),
            total_net=Decimal("19.00"),
        )
        SettlementBatch.objects.create(
            producer_reference="999999",
            week_start=(now - timedelta(days=7)).date(),
            week_end=now.date(),
            total_gross=Decimal("30.00"),
            total_commission=Decimal("1.50"),
            total_net=Decimal("28.50"),
        )

    def test_producer_sees_only_own_payment_records(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.get(reverse("payments-records-page"))
        self.assertEqual(response.status_code, 200)
        records = list(response.context["records"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].producer_reference, str(self.producer.id))

    def test_producer_sees_only_own_settlements(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.get(reverse("payments-settlements-page"))
        self.assertEqual(response.status_code, 200)
        settlements = list(response.context["settlements"])
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0].producer_reference, str(self.producer.id))

    def test_producer_commission_report_is_scoped(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.get(reverse("payments-report-page"))
        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        self.assertEqual(report["totals"]["gross"], Decimal("20.00"))
        self.assertEqual(report["totals"]["commission"], Decimal("1.00"))
        self.assertEqual(report["totals"]["net"], Decimal("19.00"))
        self.assertEqual(len(list(report["by_producer"])), 1)

    def test_admin_sees_all_data(self):
        self.client.login(username=self.admin.username, password="strong-password-123")
        records_response = self.client.get(reverse("payments-records-page"))
        settlements_response = self.client.get(reverse("payments-settlements-page"))
        report_response = self.client.get(reverse("payments-report-page"))
        self.assertEqual(records_response.status_code, 200)
        self.assertEqual(settlements_response.status_code, 200)
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(len(list(records_response.context["records"])), 2)
        self.assertEqual(len(list(settlements_response.context["settlements"])), 2)
        self.assertEqual(report_response.context["report"]["totals"]["commission"], Decimal("2.50"))

    def test_customer_forbidden_on_payment_web_pages(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        pages = [
            "payments-dashboard",
            "payments-records-page",
            "payments-settlements-page",
            "payments-report-page",
        ]
        for page in pages:
            with self.subTest(page=page):
                response = self.client.get(reverse(page))
                self.assertEqual(response.status_code, 403)


class PaymentsApiRBACTests(APITestCase):
    def setUp(self):
        self.producer = User.objects.create_user(
            username="producer-api@example.com",
            email="producer-api@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.admin = User.objects.create_user(
            username="admin-api@example.com",
            email="admin-api@example.com",
            password="strong-password-123",
            role="ADMIN",
        )
        self.customer = User.objects.create_user(
            username="customer-api@example.com",
            email="customer-api@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        now = timezone.now()
        PaymentRecord.objects.create(
            order_reference="ORD-API-1",
            transaction_reference="TXN-API-1",
            producer_reference=str(self.producer.id),
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("40.00"),
            status=PaymentRecord.Status.PAID,
            paid_at=now,
        )
        PaymentRecord.objects.create(
            order_reference="ORD-API-2",
            transaction_reference="TXN-API-2",
            producer_reference="999999",
            customer_reference=str(self.customer.id),
            gross_amount=Decimal("60.00"),
            status=PaymentRecord.Status.PAID,
            paid_at=now,
        )

    def test_customer_forbidden_from_commission_report_api(self):
        token = Token.objects.create(user=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        resp = self.client.get(
            reverse("commission-report"),
            {"start_date": timezone.now().date(), "end_date": timezone.now().date()},
        )
        self.assertEqual(resp.status_code, 403)

    def test_producer_commission_report_api_is_scoped(self):
        token = Token.objects.create(user=self.producer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        resp = self.client.get(
            reverse("commission-report"),
            {"start_date": timezone.now().date(), "end_date": timezone.now().date()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.data["totals"]["gross"])), Decimal("40.00"))
        self.assertEqual(Decimal(str(resp.data["totals"]["commission"])), Decimal("2.00"))

    def test_admin_commission_report_api_is_global(self):
        token = Token.objects.create(user=self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        resp = self.client.get(
            reverse("commission-report"),
            {"start_date": timezone.now().date(), "end_date": timezone.now().date()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.data["totals"]["gross"])), Decimal("100.00"))
        self.assertEqual(Decimal(str(resp.data["totals"]["commission"])), Decimal("5.00"))

    def test_producer_cannot_query_other_producer_payment_records(self):
        token = Token.objects.create(user=self.producer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        resp = self.client.get(
            reverse("payment-records"),
            {"producer_reference": "999999"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)

    def test_producer_cannot_query_other_producer_settlements(self):
        SettlementBatch.objects.create(
            producer_reference="999999",
            week_start=(timezone.now() - timedelta(days=7)).date(),
            week_end=timezone.now().date(),
            total_gross=Decimal("100.00"),
            total_commission=Decimal("5.00"),
            total_net=Decimal("95.00"),
        )
        SettlementBatch.objects.create(
            producer_reference=str(self.producer.id),
            week_start=(timezone.now() - timedelta(days=7)).date(),
            week_end=timezone.now().date(),
            total_gross=Decimal("40.00"),
            total_commission=Decimal("2.00"),
            total_net=Decimal("38.00"),
        )
        token = Token.objects.create(user=self.producer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        resp = self.client.get(
            reverse("settlement-list"),
            {"producer_reference": "999999"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)


class AdminFinancialReportingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="finance-admin@example.com",
            email="finance-admin@example.com",
            password="strong-password-123",
            role="ADMIN",
        )
        self.producer_a = User.objects.create_user(
            username="producer-fin-a@example.com",
            email="producer-fin-a@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.producer_b = User.objects.create_user(
            username="producer-fin-b@example.com",
            email="producer-fin-b@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.customer = User.objects.create_user(
            username="customer-fin@example.com",
            email="customer-fin@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

    def _create_order_with_payments(self, *, grosses_by_producer, paid_at, order_status=Order.Status.PENDING):
        order = Order.objects.create(
            customer=self.customer,
            delivery_address="10 Market Street",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            total_amount=sum(grosses_by_producer.values(), Decimal("0.00")),
            status=order_status,
        )
        for producer, gross in grosses_by_producer.items():
            OrderItem.objects.create(
                order=order,
                product=Product.objects.create(
                    producer=producer,
                    name=f"Item-{producer.id}-{gross}",
                    category=Product.Category.OTHER,
                    description="Report test item",
                    price=gross,
                    unit="unit",
                    stock_quantity=10,
                    availability=Product.Availability.AVAILABLE,
                ),
                producer=producer,
                product_name=f"Item-{producer.id}",
                unit_price=gross,
                quantity=1,
            )
            PaymentRecord.objects.create(
                order_reference=order.order_number,
                transaction_reference=f"TXN-{order.order_number}-{producer.id}",
                producer_reference=str(producer.id),
                customer_reference=str(self.customer.id),
                gross_amount=gross,
                status=PaymentRecord.Status.PAID,
                paid_at=paid_at,
            )
        return order

    def test_admin_only_financial_report_access(self):
        producer = self.producer_a
        self.client.login(username=producer.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"))
        self.assertEqual(response.status_code, 403)
        csv_response = self.client.get(reverse("admin-financial-report-csv"))
        self.assertEqual(csv_response.status_code, 403)

        self.client.logout()
        self.client.login(username=self.customer.username, password="strong-password-123")
        customer_response = self.client.get(reverse("admin-financial-report"))
        self.assertEqual(customer_response.status_code, 403)
        customer_csv = self.client.get(reverse("admin-financial-report-csv"))
        self.assertEqual(customer_csv.status_code, 403)

    def test_admin_role_can_access_financial_report_and_csv(self):
        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"))
        csv_response = self.client.get(reverse("admin-financial-report-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(csv_response.status_code, 200)

    def test_superuser_without_admin_role_is_denied_finance_report(self):
        outsider = User.objects.create_user(
            username="superuser-outsider@example.com",
            email="superuser-outsider@example.com",
            password="strong-password-123",
            role="CUSTOMER",
            is_superuser=True,
            is_staff=True,
        )
        self.client.login(username=outsider.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"))
        self.assertEqual(response.status_code, 403)

    def test_financial_report_single_and_multi_vendor_calculations(self):
        now = timezone.now()
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("100.00")},
            paid_at=now,
        )
        self._create_order_with_payments(
            grosses_by_producer={
                self.producer_a: Decimal("80.00"),
                self.producer_b: Decimal("70.00"),
            },
            paid_at=now,
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"), {"range": "current_month"})
        self.assertEqual(response.status_code, 200)

        report = response.context["report"]
        self.assertEqual(report["totals"]["gross"], Decimal("250.00"))
        self.assertEqual(report["totals"]["commission"], Decimal("12.50"))
        self.assertEqual(report["totals"]["net"], Decimal("237.50"))
        self.assertEqual(report["processed_payment_count"], 3)
        self.assertEqual(report["processed_order_count"], 2)

        multi_rows = [r for r in report["rows"] if r["is_multi_vendor"]]
        self.assertEqual(len(multi_rows), 2)
        self.assertEqual(sorted([r["commission_amount"] for r in multi_rows]), [Decimal("3.50"), Decimal("4.00")])
        self.assertEqual(sorted([r["net_amount"] for r in multi_rows]), [Decimal("66.50"), Decimal("76.00")])

    def test_financial_report_date_filtering(self):
        now = timezone.now()
        old = now - timedelta(days=60)
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("50.00")},
            paid_at=old,
        )
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("100.00")},
            paid_at=now,
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"), {"range": "current_month"})
        report = response.context["report"]
        self.assertEqual(report["totals"]["gross"], Decimal("100.00"))
        self.assertEqual(report["totals"]["commission"], Decimal("5.00"))

    def test_financial_report_csv_export_and_rounding(self):
        now = timezone.now()
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("42.50")},
            paid_at=now,
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report-csv"), {"range": "current_month"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        payload = response.content.decode("utf-8")
        self.assertIn("Total Commission (5%),2.13", payload)
        self.assertIn("Total Producer Payout (95%),40.37", payload)
        self.assertIn(",42.50,2.13,40.37,", payload)

    def test_financial_report_status_and_producer_filters(self):
        now = timezone.now()
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("40.00")},
            paid_at=now,
            order_status=Order.Status.CONFIRMED,
        )
        order = self._create_order_with_payments(
            grosses_by_producer={self.producer_b: Decimal("60.00")},
            paid_at=now,
            order_status=Order.Status.CANCELLED,
        )
        record = PaymentRecord.objects.filter(order_reference=order.order_number).first()
        record.status = PaymentRecord.Status.FAILED
        record.save(update_fields=["status", "updated_at"])

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(
            reverse("admin-financial-report"),
            {
                "range": "current_month",
                "producer_reference": str(self.producer_a.id),
                "payment_status": "PAID",
                "order_status": "CONFIRMED",
            },
        )
        report = response.context["report"]
        self.assertEqual(report["totals"]["gross"], Decimal("40.00"))
        self.assertEqual(report["processed_payment_count"], 1)

    def test_financial_report_previous_2_weeks_filtering(self):
        now = timezone.now()
        within_two_weeks = now - timedelta(days=3)
        outside_two_weeks = now - timedelta(days=30)

        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("70.00")},
            paid_at=within_two_weeks,
        )
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("30.00")},
            paid_at=outside_two_weeks,
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(reverse("admin-financial-report"), {"range": "previous_2_weeks"})
        self.assertEqual(response.status_code, 200)

        report = response.context["report"]
        self.assertEqual(report["range_mode"], "previous_2_weeks")
        self.assertEqual(report["totals"]["gross"], Decimal("70.00"))
        self.assertEqual(report["totals"]["commission"], Decimal("3.50"))
        self.assertEqual(report["totals"]["net"], Decimal("66.50"))
        self.assertEqual(report["processed_order_count"], 1)

    def test_processed_order_count_matches_distinct_orders_in_filtered_paid_records(self):
        now = timezone.now()
        order_one = self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("20.00")},
            paid_at=now,
            order_status=Order.Status.CONFIRMED,
        )
        self._create_order_with_payments(
            grosses_by_producer={
                self.producer_a: Decimal("30.00"),
                self.producer_b: Decimal("50.00"),
            },
            paid_at=now,
            order_status=Order.Status.CONFIRMED,
        )
        order_failed = self._create_order_with_payments(
            grosses_by_producer={self.producer_b: Decimal("90.00")},
            paid_at=now,
            order_status=Order.Status.CONFIRMED,
        )
        PaymentRecord.objects.filter(order_reference=order_failed.order_number).update(
            status=PaymentRecord.Status.FAILED
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(
            reverse("admin-financial-report"),
            {
                "range": "current_month",
                "order_status": "CONFIRMED",
                "payment_status": "PAID",
            },
        )
        self.assertEqual(response.status_code, 200)
        report = response.context["report"]

        filtered_refs = {
            row["order_reference"]
            for row in report["rows"]
        }
        self.assertIn(order_one.order_number, filtered_refs)
        self.assertEqual(report["processed_order_count"], len(filtered_refs))
        self.assertEqual(report["processed_order_count"], 2)

    def test_financial_report_csv_export_respects_active_filters(self):
        now = timezone.now()
        self._create_order_with_payments(
            grosses_by_producer={self.producer_a: Decimal("55.00")},
            paid_at=now,
            order_status=Order.Status.CONFIRMED,
        )
        filtered_out_order = self._create_order_with_payments(
            grosses_by_producer={self.producer_b: Decimal("80.00")},
            paid_at=now,
            order_status=Order.Status.CANCELLED,
        )
        PaymentRecord.objects.filter(order_reference=filtered_out_order.order_number).update(
            status=PaymentRecord.Status.FAILED
        )

        self.client.login(username=self.admin.username, password="strong-password-123")
        response = self.client.get(
            reverse("admin-financial-report-csv"),
            {
                "range": "current_month",
                "producer_reference": str(self.producer_a.id),
                "payment_status": "PAID",
                "order_status": "CONFIRMED",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.content.decode("utf-8")
        reader = list(csv.reader(io.StringIO(payload)))

        # Summary key/value section
        summary = {row[0]: row[1] for row in reader if len(row) >= 2 and row[0]}
        self.assertEqual(summary["Range"], "current_month")
        self.assertEqual(summary["Total Gross"], "55.00")
        self.assertEqual(summary["Total Commission (5%)"], "2.75")
        self.assertEqual(summary["Total Producer Payout (95%)"], "52.25")
        self.assertEqual(summary["Processed Orders"], "1")

        # Locate tabular section and parse data rows structurally.
        header = [
            "Payment ID",
            "Transaction",
            "Order Ref",
            "Order Status",
            "Producer Ref",
            "Producer Share",
            "Gross",
            "Commission",
            "Payout",
            "Payment Status",
            "Paid At",
            "Multi Vendor",
        ]
        header_idx = next(i for i, row in enumerate(reader) if row == header)
        data_rows = [row for row in reader[header_idx + 1 :] if row and any(cell.strip() for cell in row)]
        dict_rows = [dict(zip(header, row)) for row in data_rows]

        # Included producer row is present with expected filtered values.
        self.assertEqual(len(dict_rows), 1)
        included = dict_rows[0]
        self.assertEqual(included["Order Status"], "CONFIRMED")
        self.assertEqual(included["Producer Ref"], str(self.producer_a.id))
        self.assertEqual(included["Producer Share"], "55.00")
        self.assertEqual(included["Gross"], "55.00")
        self.assertEqual(included["Commission"], "2.75")
        self.assertEqual(included["Payout"], "52.25")
        self.assertEqual(included["Payment Status"], "PAID")

        # Excluded producer has no rows in filtered CSV output.
        producer_refs = {row["Producer Ref"] for row in dict_rows}
        self.assertNotIn(str(self.producer_b.id), producer_refs)
