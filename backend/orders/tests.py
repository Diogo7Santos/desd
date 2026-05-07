from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Address, CustomerProfile, ProducerProfile
from cart.models import Cart, CartItem
from catalog.models import Product
from orders.models import (
    Order,
    OrderItem,
    RecurringOrder,
    RecurringOrderItem,
    RecurringOrderItemOverride,
)
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
    def test_multi_producer_checkout_stores_per_producer_delivery_dates_and_notes(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_multi_schedule_1",
            url="https://checkout.stripe.com/pay/cs_test_multi_schedule_1",
            payment_intent="pi_test_multi_schedule_1",
        )
        ProducerProfile.objects.create(
            user=self.producer_a,
            business_name="Producer A Farm",
            contact_name="Alice Grower",
            business_address="1 Orchard Lane",
            postcode="BS1 4DJ",
            lead_time_days=2,
        )
        ProducerProfile.objects.create(
            user=self.producer_b,
            business_name="Producer B Dairy",
            contact_name="Ben Farmer",
            business_address="2 Valley Road",
            postcode="BS3 2AA",
            lead_time_days=5,
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=2)
        CartItem.objects.create(cart=cart, product=self.product_b, quantity=1)

        producer_a_date = timezone.localdate() + timedelta(days=3)
        producer_b_date = timezone.localdate() + timedelta(days=6)
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "25 Delivery Square, Bristol",
                "delivery_postcode": "BS1 2AB",
                "delivery_instructions": "Reception will coordinate separate arrivals.",
                f"producer_{self.producer_a.id}_delivery_date": producer_a_date.isoformat(),
                f"producer_{self.producer_a.id}_delivery_notes": "Call when arriving at the front gate.",
                f"producer_{self.producer_b.id}_delivery_date": producer_b_date.isoformat(),
                f"producer_{self.producer_b.id}_delivery_notes": "Unload beside the cold-storage entrance.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("checkout.stripe.com", response.url)

        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.delivery_date, producer_a_date)
        item_a = OrderItem.objects.get(order=order, producer=self.producer_a)
        item_b = OrderItem.objects.get(order=order, producer=self.producer_b)
        self.assertEqual(item_a.producer_delivery_date, producer_a_date)
        self.assertEqual(item_b.producer_delivery_date, producer_b_date)
        self.assertEqual(item_a.producer_delivery_notes, "Call when arriving at the front gate.")
        self.assertEqual(item_b.producer_delivery_notes, "Unload beside the cold-storage entrance.")

        grouped = order.get_items_by_producer()
        self.assertEqual(grouped[self.producer_a]["delivery_date"], producer_a_date)
        self.assertEqual(grouped[self.producer_b]["delivery_date"], producer_b_date)
        self.assertEqual(
            grouped[self.producer_b]["delivery_notes"],
            "Unload beside the cold-storage entrance.",
        )

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
        order.status = Order.Status.PENDING
        order.save(update_fields=["status", "updated_at"])

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

    def test_customer_order_detail_shows_latest_status_note_only(self):
        order = Order.objects.create(
            customer=self.customer,
            delivery_address="9 Update Lane, Bristol",
            delivery_postcode="BS1 1AA",
            delivery_date=(timezone.now() + timedelta(days=3)).date(),
            delivery_instructions="",
            total_amount=Decimal("6.00"),
            status=Order.Status.PENDING,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product_a,
            producer=self.producer_a,
            product_name=self.product_a.name,
            unit_price=self.product_a.price,
            quantity=2,
            status=Order.Status.PENDING,
        )

        self.client.login(username=self.producer_a.username, password="strong-password-123")
        first_update_response = self.client.post(
            reverse("orders:update_status", kwargs={"order_id": order.id}),
            {
                "status": Order.Status.CONFIRMED,
                "notes": "Initial scheduling note.",
            },
        )
        self.assertEqual(first_update_response.status_code, 302)
        second_update_response = self.client.post(
            reverse("orders:update_status", kwargs={"order_id": order.id}),
            {
                "status": Order.Status.READY,
                "notes": "Delivery van will arrive after 10am.",
            },
        )
        self.assertEqual(second_update_response.status_code, 302)

        self.client.logout()
        self.client.login(username=self.customer.username, password="strong-password-123")
        detail_response = self.client.get(reverse("orders:order_detail", kwargs={"order_id": order.id}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Latest Status Update")
        self.assertContains(detail_response, "Delivery van will arrive after 10am.")
        self.assertNotContains(detail_response, "Initial scheduling note.")
        self.assertContains(detail_response, self.producer_a.username)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_producer_dashboard_excludes_pending_payment_orders(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_hidden_unpaid_prod_1",
            url="https://checkout.stripe.com/pay/cs_test_hidden_unpaid_prod_1",
            payment_intent="pi_test_hidden_unpaid_prod_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "4 Hidden Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        self.client.logout()
        self.client.login(username=self.producer_a.username, password="strong-password-123")
        response = self.client.get(reverse("orders:producer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["orders_data"]), 0)
        self.assertNotContains(response, order.order_number)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_customer_order_history_excludes_pending_payment_orders(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_hidden_unpaid_cust_1",
            url="https://checkout.stripe.com/pay/cs_test_hidden_unpaid_cust_1",
            payment_intent="pi_test_hidden_unpaid_cust_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "5 Hidden Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        history = self.client.get(reverse("orders:order_history"))
        self.assertEqual(history.status_code, 200)
        self.assertNotContains(history, order.order_number)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_order_detail_blocks_pending_payment_order(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_block_detail_1",
            url="https://checkout.stripe.com/pay/cs_test_block_detail_1",
            payment_intent="pi_test_block_detail_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "6 Hidden Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        detail = self.client.get(reverse("orders:order_detail", kwargs={"order_id": order.id}))
        self.assertEqual(detail.status_code, 404)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_reorder_blocks_pending_payment_order(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_block_reorder_1",
            url="https://checkout.stripe.com/pay/cs_test_block_reorder_1",
            payment_intent="pi_test_block_reorder_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=1)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "7 Hidden Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        reorder_response = self.client.post(reverse("orders:reorder", kwargs={"order_id": order.id}))
        self.assertEqual(reorder_response.status_code, 404)

    @patch("payments.stripe_gateway.stripe.Webhook.construct_event")
    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_webhook_success_moves_order_to_fulfilment_and_surfaces_paid_state(self, stripe_create, construct_event):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_paid_state_1",
            url="https://checkout.stripe.com/pay/cs_test_paid_state_1",
            payment_intent="pi_test_paid_state_1",
        )

        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product_a, quantity=2)
        delivery_date = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "10 Paid State Road",
                "delivery_postcode": "BS1 1AA",
                "delivery_date": delivery_date,
                "delivery_instructions": "",
            },
        )
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        construct_event.return_value = {
            "id": "evt_paid_state_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_paid_state_1",
                    "payment_intent": "pi_test_paid_state_1",
                }
            },
        }
        webhook_response = self.client.post(
            reverse("stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )
        self.assertEqual(webhook_response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertNotEqual(order.status, Order.Status.PENDING_PAYMENT)

        self.client.logout()
        self.client.login(username=self.producer_a.username, password="strong-password-123")
        producer_dashboard = self.client.get(reverse("orders:producer_dashboard"))
        self.assertEqual(producer_dashboard.status_code, 200)
        self.assertContains(producer_dashboard, "Payment: PAID")
        self.assertContains(producer_dashboard, "Pending")
        self.assertNotContains(producer_dashboard, "Pending Payment")

        self.client.logout()
        self.client.login(username=self.customer.username, password="strong-password-123")
        order_history = self.client.get(reverse("orders:order_history"))
        self.assertEqual(order_history.status_code, 200)
        self.assertContains(order_history, "PAID")
        self.assertNotContains(order_history, "Pending Payment")

        order_detail = self.client.get(reverse("orders:order_detail", kwargs={"order_id": order.id}))
        self.assertEqual(order_detail.status_code, 200)
        self.assertContains(order_detail, "Payment")
        self.assertContains(order_detail, "PAID")
        self.assertNotContains(order_detail, "Pending Payment")

class BusinessOrderFlowTests(TestCase):
    def setUp(self):
        self.restaurant_user = User.objects.create_user(
            username="restaurant@example.com",
            email="restaurant@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        restaurant_address = Address.objects.create(
            user=self.restaurant_user,
            line_1="10 Clifton Road",
            line_2="",
            city="Bristol",
            postcode="BS8 1AB",
        )
        CustomerProfile.objects.create(
            user=self.restaurant_user,
            customer_type_id=CustomerProfile.CustomerType.RESTAURANT,
            address=restaurant_address,
            organisation_name="The Clifton Kitchen",
            contact_person="Restaurant Owner",
            default_delivery_instructions="Deliver to rear kitchen door",
            is_business_verified=True,
        )

        self.community_user = User.objects.create_user(
            username="community@example.com",
            email="community@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        community_address = Address.objects.create(
            user=self.community_user,
            line_1="45 School Lane",
            line_2="",
            city="Bristol",
            postcode="BS1 5JG",
        )
        CustomerProfile.objects.create(
            user=self.community_user,
            customer_type_id=CustomerProfile.CustomerType.COMMUNITY_GROUP,
            address=community_address,
            organisation_name="St. Mary's School",
            contact_person="Kitchen Manager",
            default_delivery_instructions="Delivery to kitchen entrance",
            is_charity_or_education=True,
        )

        self.producer_a = User.objects.create_user(
            username="farm-a@example.com",
            email="farm-a@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.producer_a,
            business_name="Bristol Valley Farm",
            contact_name="Jane Smith",
            business_address="1 Farm Lane",
            postcode="BS1 4DJ",
        )
        self.producer_b = User.objects.create_user(
            username="farm-b@example.com",
            email="farm-b@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.producer_b,
            business_name="Clifton Dairy",
            contact_name="Mark Lewis",
            business_address="2 Milk Yard",
            postcode="BS3 2AA",
        )
        self.producer_c = User.objects.create_user(
            username="farm-c@example.com",
            email="farm-c@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.producer_c,
            business_name="Harbourside Bakery",
            contact_name="Sofia Reed",
            business_address="3 Bread Wharf",
            postcode="BS2 9ZZ",
        )

        self.product_potatoes = Product.objects.create(
            producer=self.producer_a,
            name="Stored Potatoes",
            category=Product.Category.VEGETABLES,
            description="Bulk potatoes",
            price=Decimal("1.80"),
            unit="kg",
            stock_quantity=120,
            availability=Product.Availability.AVAILABLE,
        )
        self.product_milk = Product.objects.create(
            producer=self.producer_b,
            name="Whole Milk",
            category=Product.Category.DAIRY_EGGS,
            description="Fresh milk",
            price=Decimal("2.40"),
            unit="litre",
            stock_quantity=80,
            availability=Product.Availability.AVAILABLE,
        )
        self.product_carrots = Product.objects.create(
            producer=self.producer_c,
            name="Organic Carrots",
            category=Product.Category.VEGETABLES,
            description="Catering carrots",
            price=Decimal("1.60"),
            unit="kg",
            stock_quantity=90,
            availability=Product.Availability.AVAILABLE,
        )

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_tc017_community_group_bulk_order_confirmation_includes_producer_contacts(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_tc017",
            url="https://checkout.stripe.com/pay/cs_test_tc017",
            payment_intent="pi_test_tc017",
        )
        self.client.login(username=self.community_user.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.community_user)
        CartItem.objects.create(cart=cart, product=self.product_potatoes, quantity=50)
        CartItem.objects.create(cart=cart, product=self.product_milk, quantity=30)
        CartItem.objects.create(cart=cart, product=self.product_carrots, quantity=20)

        delivery_date = (timezone.now() + timedelta(days=4)).date().isoformat()
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "45 School Lane, Bristol",
                "delivery_postcode": "BS1 5JG",
                "delivery_date": delivery_date,
                "delivery_instructions": "Delivery to kitchen entrance, contact kitchen manager",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(customer=self.community_user)
        confirm = self.client.get(reverse("orders:order_confirmation", kwargs={"order_id": order.id}))
        self.assertContains(confirm, "Producer Coordination Contacts")
        self.assertContains(confirm, "St. Mary's School")
        self.assertContains(confirm, "Jane Smith")
        self.assertContains(confirm, "Clifton Dairy")
        self.assertEqual(PaymentRecord.objects.filter(order_reference=order.order_number).count(), 3)

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_tc018_restaurant_checkout_can_create_recurring_order_template(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_tc018_create",
            url="https://checkout.stripe.com/pay/cs_test_tc018_create",
            payment_intent="pi_test_tc018_create",
        )
        self.client.login(username=self.restaurant_user.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.restaurant_user)
        CartItem.objects.create(cart=cart, product=self.product_potatoes, quantity=10)
        CartItem.objects.create(cart=cart, product=self.product_milk, quantity=12)
        CartItem.objects.create(cart=cart, product=self.product_carrots, quantity=8)

        delivery_date = (timezone.now() + timedelta(days=5)).date().isoformat()
        response = self.client.post(
            reverse("orders:place_order"),
            {
                "delivery_address": "10 Clifton Road, Bristol",
                "delivery_postcode": "BS8 1AB",
                "delivery_date": delivery_date,
                "delivery_instructions": "Deliver to rear kitchen door",
                "make_recurring": "on",
                "recurring_name": "Weekly Kitchen Staples",
                "recurrence_interval": RecurringOrder.Interval.WEEKLY,
                "order_weekday": "0",
                "delivery_weekday": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        recurring_order = RecurringOrder.objects.get(customer=self.restaurant_user)
        self.assertEqual(recurring_order.template_name, "Weekly Kitchen Staples")
        self.assertEqual(recurring_order.recurrence_interval, RecurringOrder.Interval.WEEKLY)
        self.assertEqual(recurring_order.order_weekday, 0)
        self.assertEqual(recurring_order.delivery_weekday, 2)
        self.assertEqual(recurring_order.items.count(), 3)

    def test_tc018_next_scheduled_quantity_override_does_not_change_template(self):
        recurring_order = RecurringOrder.objects.create(
            customer=self.restaurant_user,
            template_name="Weekly Kitchen Staples",
            recurrence_interval=RecurringOrder.Interval.WEEKLY,
            order_weekday=0,
            delivery_weekday=2,
            delivery_address="10 Clifton Road, Bristol",
            delivery_postcode="BS8 1AB",
            delivery_instructions="Deliver to rear kitchen door",
            next_order_date=(timezone.now() + timedelta(days=5)).date(),
            next_delivery_date=(timezone.now() + timedelta(days=7)).date(),
        )
        recurring_item = RecurringOrderItem.objects.create(
            recurring_order=recurring_order,
            product=self.product_potatoes,
            producer=self.producer_a,
            product_name=self.product_potatoes.name,
            unit_price=self.product_potatoes.price,
            quantity=10,
        )

        self.client.login(username=self.restaurant_user.username, password="strong-password-123")
        response = self.client.post(
            reverse("orders:update_recurring_order", kwargs={"recurring_order_id": recurring_order.id}),
            {
                "template_name": recurring_order.template_name,
                f"quantity_{recurring_item.id}": "14",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        recurring_item.refresh_from_db()
        self.assertEqual(recurring_item.quantity, 10)
        override = RecurringOrderItemOverride.objects.get(recurring_item=recurring_item)
        self.assertEqual(override.quantity, 14)
        self.assertContains(response, "Next scheduled order updated")

    @patch("payments.stripe_gateway.stripe.checkout.Session.create")
    def test_tc018_checkout_recurring_order_advances_schedule_and_uses_override_quantity(self, stripe_create):
        stripe_create.return_value = SimpleNamespace(
            id="cs_test_tc018_checkout",
            url="https://checkout.stripe.com/pay/cs_test_tc018_checkout",
            payment_intent="pi_test_tc018_checkout",
        )
        next_order_date = (timezone.now() + timedelta(days=5)).date()
        next_delivery_date = next_order_date + timedelta(days=2)
        recurring_order = RecurringOrder.objects.create(
            customer=self.restaurant_user,
            template_name="Weekly Kitchen Staples",
            recurrence_interval=RecurringOrder.Interval.WEEKLY,
            order_weekday=0,
            delivery_weekday=2,
            delivery_address="10 Clifton Road, Bristol",
            delivery_postcode="BS8 1AB",
            delivery_instructions="Deliver to rear kitchen door",
            next_order_date=next_order_date,
            next_delivery_date=next_delivery_date,
        )
        recurring_item = RecurringOrderItem.objects.create(
            recurring_order=recurring_order,
            product=self.product_potatoes,
            producer=self.producer_a,
            product_name=self.product_potatoes.name,
            unit_price=self.product_potatoes.price,
            quantity=10,
        )
        RecurringOrderItemOverride.objects.create(
            recurring_item=recurring_item,
            scheduled_order_date=next_order_date,
            quantity=13,
        )

        self.client.login(username=self.restaurant_user.username, password="strong-password-123")
        response = self.client.post(
            reverse("orders:checkout_recurring_order", kwargs={"recurring_order_id": recurring_order.id}),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(customer=self.restaurant_user)
        order_item = OrderItem.objects.get(order=order)
        self.assertEqual(order_item.quantity, 13)
        recurring_order.refresh_from_db()
        self.assertEqual(recurring_order.next_order_date, next_order_date + timedelta(days=7))
        self.assertFalse(
            RecurringOrderItemOverride.objects.filter(
                recurring_item=recurring_item,
                scheduled_order_date=next_order_date,
            ).exists()
        )
