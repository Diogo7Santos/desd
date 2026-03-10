from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models


MONEY_PLACES = Decimal("0.01")


class PaymentRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    order_reference = models.CharField(max_length=100)
    transaction_reference = models.CharField(max_length=100, unique=True)
    producer_reference = models.CharField(max_length=100)
    customer_reference = models.CharField(max_length=100, blank=True)
    payment_provider = models.CharField(max_length=30, default="STRIPE_TEST")
    provider_payment_id = models.CharField(max_length=120, blank=True)
    checkout_session_id = models.CharField(max_length=120, blank=True)
    checkout_session_url = models.URLField(blank=True)
    currency = models.CharField(max_length=3, default="GBP")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0500"))
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.transaction_reference} ({self.status})"

    def clean(self) -> None:
        if self.commission_rate < Decimal("0") or self.commission_rate > Decimal("1"):
            raise ValidationError("commission_rate must be between 0 and 1.")
        self._recalculate_amounts()

    def save(self, *args, **kwargs):
        self._recalculate_amounts()
        return super().save(*args, **kwargs)

    def _recalculate_amounts(self) -> None:
        commission = (self.gross_amount * self.commission_rate).quantize(
            MONEY_PLACES,
            rounding=ROUND_HALF_UP,
        )
        self.commission_amount = commission
        self.net_amount = (self.gross_amount - commission).quantize(
            MONEY_PLACES,
            rounding=ROUND_HALF_UP,
        )


class SettlementBatch(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PAID = "PAID", "Paid"

    producer_reference = models.CharField(max_length=100)
    week_start = models.DateField()
    week_end = models.DateField()
    total_gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_commission = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["producer_reference", "week_start", "week_end"],
                name="unique_settlement_per_producer_week",
            )
        ]

    def __str__(self) -> str:
        return f"{self.producer_reference} ({self.week_start} -> {self.week_end})"


class SettlementItem(models.Model):
    settlement = models.ForeignKey(
        SettlementBatch,
        on_delete=models.CASCADE,
        related_name="items",
    )
    payment_record = models.OneToOneField(
        PaymentRecord,
        on_delete=models.CASCADE,
        related_name="settlement_item",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.settlement_id}:{self.payment_record_id}"
