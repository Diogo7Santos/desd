from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cart.models import Cart, CartItem
from catalog.models import Product

User = get_user_model()


class CartTC006Tests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cart-customer@example.com",
            email="cart-customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        self.producer = User.objects.create_user(
            username="cart-producer@example.com",
            email="cart-producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.producer_two = User.objects.create_user(
            username="cart-producer-two@example.com",
            email="cart-producer-two@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )

        self.available_product = Product.objects.create(
            producer=self.producer,
            name="Available Carrots",
            category=Product.Category.VEGETABLES,
            description="Fresh carrots",
            price=Decimal("2.50"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=10,
            allergens="none",
        )
        self.unavailable_product = Product.objects.create(
            producer=self.producer,
            name="Unavailable Honey",
            category=Product.Category.PRESERVES,
            description="Unavailable",
            price=Decimal("5.00"),
            unit="jar",
            availability=Product.Availability.UNAVAILABLE,
            stock_quantity=5,
            allergens="none",
        )
        self.out_of_stock_product = Product.objects.create(
            producer=self.producer,
            name="Out Of Stock Potatoes",
            category=Product.Category.VEGETABLES,
            description="Out of stock",
            price=Decimal("1.50"),
            unit="kg",
            availability=Product.Availability.UNAVAILABLE,
            stock_quantity=0,
            allergens="none",
        )
        self.second_producer_product = Product.objects.create(
            producer=self.producer_two,
            name="Eggs",
            category=Product.Category.DAIRY_EGGS,
            description="Eggs",
            price=Decimal("3.00"),
            unit="dozen",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=20,
            allergens="eggs",
        )

    def test_add_to_cart_success(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.available_product.id}),
            {"quantity": 2},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cart:view_cart"))
        item = CartItem.objects.get(cart__user=self.customer, product=self.available_product)
        self.assertEqual(item.quantity, 2)

    def test_unavailable_product_safe_redirect(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.unavailable_product.id}),
            {"quantity": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("catalog:product_detail", kwargs={"pk": self.unavailable_product.id}),
        )
        self.assertFalse(CartItem.objects.filter(cart__user=self.customer).exists())

    def test_out_of_stock_safe_redirect(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.out_of_stock_product.id}),
            {"quantity": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("catalog:product_detail", kwargs={"pk": self.out_of_stock_product.id}),
        )
        self.assertFalse(CartItem.objects.filter(cart__user=self.customer).exists())

    def test_quantity_exceeded_safe_redirect(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.available_product.id}),
            {"quantity": 999},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("catalog:product_detail", kwargs={"pk": self.available_product.id}),
        )
        self.assertFalse(CartItem.objects.filter(cart__user=self.customer).exists())

    def test_update_quantity_works(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=cart, product=self.available_product, quantity=1)
        response = self.client.post(
            reverse("cart:update_item", kwargs={"item_id": item.id}),
            {"quantity": 4},
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)

    def test_remove_item_works(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=cart, product=self.available_product, quantity=1)
        response = self.client.post(reverse("cart:remove_item", kwargs={"item_id": item.id}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_totals_calculated_correctly(self):
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.available_product, quantity=2)  # 5.00
        CartItem.objects.create(cart=cart, product=self.second_producer_product, quantity=3)  # 9.00
        self.assertEqual(cart.total_items, 5)
        self.assertEqual(cart.total_price, Decimal("14.00"))

    def test_grouping_by_producer(self):
        cart = Cart.objects.create(user=self.customer)
        item_a = CartItem.objects.create(cart=cart, product=self.available_product, quantity=2)
        item_b = CartItem.objects.create(cart=cart, product=self.second_producer_product, quantity=1)
        grouped = cart.get_items_by_producer()
        self.assertEqual(len(grouped), 2)
        self.assertIn(self.producer, grouped)
        self.assertIn(self.producer_two, grouped)
        self.assertIn(item_a, grouped[self.producer])
        self.assertIn(item_b, grouped[self.producer_two])

    def test_allergen_product_requires_acknowledgement_for_add_to_cart(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.second_producer_product.id}),
            {"quantity": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("catalog:product_detail", kwargs={"pk": self.second_producer_product.id}),
        )
        self.assertFalse(
            CartItem.objects.filter(
                cart__user=self.customer,
                product=self.second_producer_product,
            ).exists()
        )

    def test_allergen_product_can_be_added_with_acknowledgement(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.second_producer_product.id}),
            {"quantity": 1, "allergen_ack": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cart:view_cart"))
        self.assertTrue(
            CartItem.objects.filter(
                cart__user=self.customer,
                product=self.second_producer_product,
            ).exists()
        )

    def test_safe_product_can_be_added_without_acknowledgement(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.post(
            reverse("cart:add_to_cart", kwargs={"product_id": self.available_product.id}),
            {"quantity": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cart:view_cart"))
        self.assertTrue(
            CartItem.objects.filter(
                cart__user=self.customer,
                product=self.available_product,
            ).exists()
        )

    def test_cart_renders_allergen_warning_for_allergen_products(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.second_producer_product, quantity=1)
        response = self.client.get(reverse("cart:view_cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allergen Warning")
