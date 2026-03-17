from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cart.models import Cart, CartItem
from catalog.models import Product
from orders.models import Order
from payments.models import PaymentRecord

User = get_user_model()


class OrderStripeIntegrationTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        self.producer_a = User.objects.create_user(
            username="producer-a@example.com",
            email="producer-a@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.producer_b = User.objects.create_user(
            username="producer-b@example.com",
            email="producer-b@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )

        self.product_a = Product.objects.create(
            producer=self.producer_a,
            name="Carrots",
            category=Product.Category.VEGETABLES,
            description="Fresh carrots",
            price=Decimal("3.00"),
            unit="kg",
            stock_quantity=100,
            availability=Product.Availability.AVAILABLE,
        )
        self.product_b = Product.objects.create(
            producer=self.producer_b,
            name="Eggs",
            category=Product.Category.DAIRY_EGGS,
            description="Free-range eggs",
            price=Decimal("4.00"),
            unit="dozen",
            stock_quantity=100,
            availability=Product.Availability.AVAILABLE,
        )

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_cart_to_place_order_redirects_to_stripe_checkout(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_integration_1",
            url="https://checkout.stripe.com/pay/cs_test_integration_1",
            payment_intent="pi_test_integration_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=2)
        CartItem.objects.create(cart=cart, product=self.product_b, quantity=1)

        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "1 Test Road, Bristol",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "Ring bell",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout.stripe.com", response.url)

        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        records = PaymentRecord.objects.filter(order_reference=order.order_number).order_by("producer_reference")
        self.assertEqual(records.count(), 2)
        self.assertTrue(all(r.checkout_session_id == "cs_test_integration_1" for r in records))
        self.assertTrue(all(r.payment_provider == "STRIPE_TEST" for r in records))
