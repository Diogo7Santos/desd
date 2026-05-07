from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Address, CustomerProfile, ProducerProfile
from cart.models import Cart, CartItem
from catalog.food_miles import food_miles_for_product, summarize_food_miles
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


class CartTC013FoodMilesTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="foodmiles-cart@example.com",
            email="foodmiles-cart@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        address = Address.objects.create(
            user=self.customer,
            line_1="45 Park Street",
            line_2="",
            city="Bristol",
            postcode="BS1 5JG",
        )
        CustomerProfile.objects.create(
            user=self.customer,
            customer_type_id=CustomerProfile.CustomerType.INDIVIDUAL,
            address=address,
        )

        self.producer = User.objects.create_user(
            username="cart-food-producer@example.com",
            email="cart-food-producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.producer,
            business_name="Bristol Valley Farm",
            contact_name="Jane Smith",
            business_address="45 Valley Road, Bristol",
            postcode="BS1 4DJ",
        )

        self.far_producer = User.objects.create_user(
            username="cart-far-producer@example.com",
            email="cart-far-producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.far_producer,
            business_name="Gloucester Orchard",
            contact_name="Morgan Price",
            business_address="10 Orchard Way, Gloucester",
            postcode="GL1 1AA",
        )

        self.local_product = Product.objects.create(
            producer=self.producer,
            name="Local Carrots",
            category=Product.Category.VEGETABLES,
            description="Fresh carrots",
            price=Decimal("2.50"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=10,
            allergens="none",
        )
        self.far_product = Product.objects.create(
            producer=self.far_producer,
            name="Gloucester Apples",
            category=Product.Category.SEASONAL,
            description="Travelled further",
            price=Decimal("4.00"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=6,
            allergens="none",
        )
        self.lookup_patch = patch("catalog.food_miles.lookup_postcode", side_effect=self.mock_lookup_postcode)
        self.lookup_patch.start()
        self.addCleanup(self.lookup_patch.stop)

    @staticmethod
    def mock_lookup_postcode(postcode: str):
        postcode_map = {
            "BS1 5JG": {"postcode": "BS1 5JG", "latitude": 51.4548, "longitude": -2.5970},
            "BS1 4DJ": {"postcode": "BS1 4DJ", "latitude": 51.4532, "longitude": -2.5905},
            "GL1 1AA": {"postcode": "GL1 1AA", "latitude": 51.8655, "longitude": -2.2459},
        }
        return postcode_map.get(postcode)

    def test_cart_page_displays_line_food_miles_and_total(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.local_product, quantity=2)
        CartItem.objects.create(cart=cart, product=self.far_product, quantity=1)

        local_result = food_miles_for_product(self.local_product, "BS1 5JG")
        far_result = food_miles_for_product(self.far_product, "BS1 5JG")
        summary = summarize_food_miles([local_result, far_result], expected_count=2)

        response = self.client.get(reverse("cart:view_cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Food Miles: {local_result.miles_display}")
        self.assertContains(response, f"Food Miles: {far_result.miles_display}")
        self.assertContains(response, summary.total_miles_display)
        self.assertContains(response, "Estimated Food Miles")
