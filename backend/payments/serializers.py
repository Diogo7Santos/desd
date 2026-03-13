from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from .models import PaymentRecord, SettlementBatch, SettlementItem


class PaymentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRecord
        fields = [
            "id",
            "order_reference",
            "transaction_reference",
            "producer_reference",
            "customer_reference",
            "payment_provider",
            "provider_payment_id",
            "checkout_session_id",
            "checkout_session_url",
            "currency",
            "gross_amount",
            "commission_rate",
            "commission_amount",
            "net_amount",
            "status",
            "paid_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "payment_provider",
            "provider_payment_id",
            "checkout_session_id",
            "checkout_session_url",
            "commission_amount",
            "net_amount",
            "created_at",
            "updated_at",
        ]


class StripeCheckoutSessionCreateSerializer(serializers.Serializer):
    order_reference = serializers.CharField(max_length=100)
    producer_reference = serializers.CharField(max_length=100)
    customer_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    gross_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=3, default="GBP")
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()

    def validate_currency(self, value: str) -> str:
        return value.upper()


class SettlementItemSerializer(serializers.ModelSerializer):
    payment_record = PaymentRecordSerializer(read_only=True)

    class Meta:
        model = SettlementItem
        fields = ["id", "payment_record", "created_at"]


class SettlementBatchSerializer(serializers.ModelSerializer):
    items = SettlementItemSerializer(many=True, read_only=True)

    class Meta:
        model = SettlementBatch
        fields = [
            "id",
            "producer_reference",
            "week_start",
            "week_end",
            "total_gross",
            "total_commission",
            "total_net",
            "status",
            "paid_at",
            "created_at",
            "items",
        ]


class SettlementGenerationRequestSerializer(serializers.Serializer):
    week_start = serializers.DateField()
    week_end = serializers.DateField()

    def validate(self, attrs):
        if attrs["week_start"] > attrs["week_end"]:
            raise serializers.ValidationError("week_start must be less than or equal to week_end.")
        return attrs


class CommissionReportQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError("start_date must be less than or equal to end_date.")
        return attrs


def commission_report_payload(start_date, end_date):
    records = PaymentRecord.objects.filter(
        paid_at__date__gte=start_date,
        paid_at__date__lte=end_date,
        status=PaymentRecord.Status.PAID,
    )

    totals = records.aggregate(
        gross=Sum("gross_amount"),
        commission=Sum("commission_amount"),
        net=Sum("net_amount"),
    )

    by_producer = (
        records.values("producer_reference")
        .annotate(
            gross=Sum("gross_amount"),
            commission=Sum("commission_amount"),
            net=Sum("net_amount"),
        )
        .order_by("producer_reference")
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "totals": {
            "gross": totals["gross"] or 0,
            "commission": totals["commission"] or 0,
            "net": totals["net"] or 0,
        },
        "by_producer": by_producer,
    }
