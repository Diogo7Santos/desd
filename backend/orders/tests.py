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
from orders.models import Order, OrderItem
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

        # Before webhook payment confirmation, stock and cart are unchanged.
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, 100)
        self.assertEqual(self.product_b.stock_quantity, 100)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 2)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_single_producer_checkout_creates_one_order_and_one_payment_record(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_single_1",
            url="https://checkout.stripe.com/pay/cs_test_single_1",
            payment_intent="pi_test_single_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=2)

        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "99 Single Lane, Bristol",
                "delivery_postcode": "BS2 2BB",
                "delivery_date": delivery_date,
                "delivery_instructions": "Leave at porch",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout.stripe.com", response.url)

        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 1)
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.delivery_address, "99 Single Lane, Bristol")
        self.assertEqual(order.delivery_postcode, "BS2 2BB")
        self.assertEqual(order.delivery_instructions, "Leave at porch")

        self.assertEqual(OrderItem.objects.filter(order=order).count(), 1)
        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.product, self.product_a)
        self.assertEqual(item.quantity, 2)

        records = PaymentRecord.objects.filter(order_reference=order.order_number)
        self.assertEqual(records.count(), 1)
        record = records.get()
        self.assertEqual(record.producer_reference, str(self.producer_a.id))
        self.assertEqual(record.gross_amount, Decimal("6.00"))

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_multi_producer_checkout_creates_one_order_and_split_payment_records(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_multi_1",
            url="https://checkout.stripe.com/pay/cs_test_multi_1",
            payment_intent="pi_test_multi_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=3)  # 9.00
        CartItem.objects.create(cart=cart, product=self.product_b, quantity=2)  # 8.00

        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "12 Split Road, Bath",
                "delivery_postcode": "BA1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout.stripe.com", response.url)

        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 1)
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)

        records = PaymentRecord.objects.filter(order_reference=order.order_number)
        self.assertEqual(records.count(), 2)
        by_producer = {r.producer_reference: r for r in records}
        self.assertSetEqual(set(by_producer.keys()), {str(self.producer_a.id), str(self.producer_b.id)})
        self.assertEqual(by_producer[str(self.producer_a.id)].gross_amount, Decimal("9.00"))
        self.assertEqual(by_producer[str(self.producer_b.id)].gross_amount, Decimal("8.00"))

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_order_items_grouped_by_producer_breakdown(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_grouping_1",
            url="https://checkout.stripe.com/pay/cs_test_grouping_1",
            payment_intent="pi_test_grouping_1",
        )

        product_a2 = Product.objects.create(
            producer=self.producer_a,
            name="Potatoes",
            category=Product.Category.VEGETABLES,
            description="Fresh potatoes",
            price=Decimal("2.00"),
            unit="kg",
            stock_quantity=100,
            availability=Product.Availability.AVAILABLE,
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)   # 3.00
        CartItem.objects.create(cart=cart, product=product_a2, quantity=3)       # 6.00
        CartItem.objects.create(cart=cart, product=self.product_b, quantity=1)  # 4.00

        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "77 Grouping Ave, Bristol",
                "delivery_postcode": "BS3 3CC",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )

        order = Order.objects.get(customer=self.customer)
        grouped = order.get_items_by_producer()
        self.assertSetEqual(set(grouped.keys()), {self.producer_a, self.producer_b})
        self.assertEqual(len(grouped[self.producer_a]["items"]), 2)
        self.assertEqual(len(grouped[self.producer_b]["items"]), 1)
        self.assertEqual(grouped[self.producer_a]["subtotal"], Decimal("9.00"))
        self.assertEqual(grouped[self.producer_b]["subtotal"], Decimal("4.00"))

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_producer_dashboard_shows_only_logged_in_producer_items(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_dashboard_1",
            url="https://checkout.stripe.com/pay/cs_test_dashboard_1",
            payment_intent="pi_test_dashboard_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=2)
        CartItem.objects.create(cart=cart, product=self.product_b, quantity=1)

        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "88 Producer St, Bristol",
                "delivery_postcode": "BS4 4DD",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )

        order = Order.objects.get(customer=self.customer)

        self.client.logout()
        self.client.login(username=self.producer_a.username, password="strong-password-123")
        response_a = self.client.get(reverse("orders:producer_dashboard"))
        self.assertEqual(response_a.status_code, 200)
        orders_data_a = response_a.context["orders_data"]
        self.assertEqual(len(orders_data_a), 1)
        self.assertEqual(orders_data_a[0]["order"].id, order.id)
        items_a = list(orders_data_a[0]["items"])
        self.assertTrue(items_a)
        self.assertTrue(all(i.producer_id == self.producer_a.id for i in items_a))
        self.assertTrue(all(i.product.producer_id != self.producer_b.id for i in items_a))

        self.client.logout()
        self.client.login(username=self.producer_b.username, password="strong-password-123")
        response_b = self.client.get(reverse("orders:producer_dashboard"))
        self.assertEqual(response_b.status_code, 200)
        orders_data_b = response_b.context["orders_data"]
        self.assertEqual(len(orders_data_b), 1)
        self.assertEqual(orders_data_b[0]["order"].id, order.id)
        items_b = list(orders_data_b[0]["items"])
        self.assertTrue(items_b)
        self.assertTrue(all(i.producer_id == self.producer_b.id for i in items_b))
        self.assertTrue(all(i.product.producer_id != self.producer_a.id for i in items_b))

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_customer_cannot_access_another_customer_order_detail(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_authz_detail_1",
            url="https://checkout.stripe.com/pay/cs_test_authz_detail_1",
            payment_intent="pi_test_authz_detail_1",
        )
        other_customer = User.objects.create_user(
            username="other-customer@example.com",
            email="other-customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "1 Owner Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.client.logout()

        self.client.login(username=other_customer.username, password="strong-password-123")
        response = self.client.get(reverse("orders:order_detail", kwargs={"order_id": order.id}))
        self.assertEqual(response.status_code, 404)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_customer_cannot_access_another_customer_order_confirmation(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_authz_confirm_1",
            url="https://checkout.stripe.com/pay/cs_test_authz_confirm_1",
            payment_intent="pi_test_authz_confirm_1",
        )
        other_customer = User.objects.create_user(
            username="other-customer-2@example.com",
            email="other-customer-2@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "2 Owner Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.client.logout()

        self.client.login(username=other_customer.username, password="strong-password-123")
        response = self.client.get(reverse("orders:order_confirmation", kwargs={"order_id": order.id}))
        self.assertEqual(response.status_code, 404)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_customer_cannot_reorder_another_customer_order(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_authz_reorder_1",
            url="https://checkout.stripe.com/pay/cs_test_authz_reorder_1",
            payment_intent="pi_test_authz_reorder_1",
        )
        other_customer = User.objects.create_user(
            username="other-customer-3@example.com",
            email="other-customer-3@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "3 Owner Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.client.logout()

        self.client.login(username=other_customer.username, password="strong-password-123")
        response = self.client.post(reverse("orders:reorder", kwargs={"order_id": order.id}), follow=True)
        self.assertEqual(response.status_code, 404)
