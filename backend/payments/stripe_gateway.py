from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

import stripe


@dataclass(frozen=True)
class StripeCheckoutSession:
    session_id: str
    checkout_url: str
    payment_intent_id: str | None


class StripeGateway:
    """Stripe test-mode gateway for checkout session creation and webhook verification."""

    provider_name = "STRIPE_TEST"

    def __init__(self) -> None:
        secret_key = settings.STRIPE_SECRET_KEY
        if not secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured.")
        stripe.api_key = secret_key

    def create_checkout_session(
        self,
        *,
        amount_minor_units: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        transaction_reference: str,
        payment_record_id: int,
        description: str,
    ) -> StripeCheckoutSession:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": amount_minor_units,
                        "product_data": {"name": description},
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "transaction_reference": transaction_reference,
                "payment_record_id": str(payment_record_id),
            },
        )
        return StripeCheckoutSession(
            session_id=session.id,
            checkout_url=session.url,
            payment_intent_id=session.payment_intent,
        )

    def construct_webhook_event(self, payload: bytes, signature: str):
        webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        if not webhook_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured.")

        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=webhook_secret,
        )
