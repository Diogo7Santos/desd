from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from .models import PaymentRecord
from .stripe_gateway import StripeGateway


def _to_minor_units(amount_major: Decimal) -> int:
    return int((amount_major * 100).to_integral_value())


def create_checkout_session_for_order(*, order_reference: str, success_url: str, cancel_url: str) -> dict:
    """Create one Stripe Checkout Session for all pending records in an order.

    Returns a dict containing checkout URL/session and the touched PaymentRecord ids.
    """
    with transaction.atomic():
        records = list(
            PaymentRecord.objects.select_for_update().filter(
                order_reference=order_reference,
                status=PaymentRecord.Status.PENDING,
            )
        )
        if not records:
            raise ValueError("No pending payment records found for order_reference.")

        # If session already created for this order, reuse it.
        existing = next((r for r in records if r.checkout_session_id), None)
        if existing and existing.checkout_session_url:
            return {
                "checkout_session_id": existing.checkout_session_id,
                "checkout_url": existing.checkout_session_url,
                "payment_record_ids": [r.id for r in records],
            }

        order_total = sum((r.gross_amount for r in records), Decimal("0.00"))
        txn_reference = f"ORDER-{order_reference}"

        gateway = StripeGateway()
        session = gateway.create_checkout_session(
            amount_minor_units=_to_minor_units(order_total),
            currency=records[0].currency,
            success_url=success_url,
            cancel_url=cancel_url,
            transaction_reference=txn_reference,
            payment_record_id=records[0].id,
            description=f"Order {order_reference}",
        )

        for record in records:
            record.checkout_session_id = session.session_id
            record.checkout_session_url = session.checkout_url
            record.provider_payment_id = session.payment_intent_id or ""
            record.payment_provider = gateway.provider_name
            record.save(
                update_fields=[
                    "checkout_session_id",
                    "checkout_session_url",
                    "provider_payment_id",
                    "payment_provider",
                    "updated_at",
                ]
            )

        return {
            "checkout_session_id": session.session_id,
            "checkout_url": session.checkout_url,
            "payment_record_ids": [r.id for r in records],
        }
