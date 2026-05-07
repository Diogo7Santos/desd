import logging
from datetime import date

from django.db import transaction
from django.db.models import Sum

from orders.models import Order

from .models import PaymentRecord, SettlementBatch, SettlementItem

logger = logging.getLogger(__name__)


def _final_fulfilled_statuses():
    statuses = {Order.Status.DELIVERED, Order.Status.READY}
    if hasattr(Order.Status, "COMPLETED"):
        statuses.add(Order.Status.COMPLETED)
    return statuses


def generate_settlements_for_week(*, week_start: date, week_end: date) -> dict:
    eligible_order_refs = Order.objects.filter(
        status__in=_final_fulfilled_statuses()
    ).values_list("order_number", flat=True)

    paid_records = (
        PaymentRecord.objects.filter(
            status=PaymentRecord.Status.PAID,
            paid_at__date__gte=week_start,
            paid_at__date__lte=week_end,
            settlement_item__isnull=True,
            order_reference__in=eligible_order_refs,
        )
        .values("producer_reference")
        .annotate(
            gross=Sum("gross_amount"),
            commission=Sum("commission_amount"),
            net=Sum("net_amount"),
        )
    )

    created_settlement_ids = []
    with transaction.atomic():
        for producer_group in paid_records:
            settlement, created = SettlementBatch.objects.get_or_create(
                producer_reference=producer_group["producer_reference"],
                week_start=week_start,
                week_end=week_end,
                defaults={
                    "total_gross": producer_group["gross"] or 0,
                    "total_commission": producer_group["commission"] or 0,
                    "total_net": producer_group["net"] or 0,
                },
            )
            if created:
                created_settlement_ids.append(settlement.id)

            producer_records = PaymentRecord.objects.filter(
                status=PaymentRecord.Status.PAID,
                paid_at__date__gte=week_start,
                paid_at__date__lte=week_end,
                producer_reference=producer_group["producer_reference"],
                order_reference__in=eligible_order_refs,
            )
            for record in producer_records:
                SettlementItem.objects.get_or_create(settlement=settlement, payment_record=record)

            totals = producer_records.aggregate(
                gross=Sum("gross_amount"),
                commission=Sum("commission_amount"),
                net=Sum("net_amount"),
            )
            SettlementBatch.objects.filter(id=settlement.id).update(
                total_gross=totals["gross"] or 0,
                total_commission=totals["commission"] or 0,
                total_net=totals["net"] or 0,
            )

    result = {"created_settlement_ids": created_settlement_ids, "count": len(created_settlement_ids)}
    logger.info(
        "Settlement generation completed for %s to %s. Created=%s IDs=%s",
        week_start,
        week_end,
        result["count"],
        result["created_settlement_ids"],
    )
    return result
