from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product

User = get_user_model()


class TC015AllergenSafetyTests(TestCase):
    def setUp(self):
        self.producer = User.objects.create_user(
            username="tc015-producer@example.com",
            email="tc015-producer@example.com",
            password="strong-password-123",
            role="PRODUCER",
        )
        self.customer = User.objects.create_user(
            username="tc015-customer@example.com",
            email="tc015-customer@example.com",
            password="strong-password-123",
            role="CUSTOMER",
        )
        self.with_allergen = Product.objects.create(
            producer=self.producer,
            name="Milk Product",
            category=Product.Category.DAIRY_EGGS,
            description="Contains milk",
            price=Decimal("2.20"),
            unit="bottle",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=10,
            allergens="milk",
        )
        self.without_allergen = Product.objects.create(
            producer=self.producer,
            name="Safe Carrots",
            category=Product.Category.VEGETABLES,
            description="No known allergens",
            price=Decimal("1.20"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=10,
            allergens="none",
        )

    def test_blank_allergen_rejected(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Blank Allergen Product",
                "category": Product.Category.VEGETABLES,
                "description": "Test",
                "price": "3.00",
                "unit": "kg",
                "availability": Product.Availability.AVAILABLE,
                "stock_quantity": 10,
                "allergens": "   ",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(name="Blank Allergen Product").exists())

    def test_none_is_accepted(self):
        self.client.login(username=self.producer.username, password="strong-password-123")
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "None Accepted Product",
                "category": Product.Category.VEGETABLES,
                "description": "Test",
                "price": "3.00",
                "unit": "kg",
                "availability": Product.Availability.AVAILABLE,
                "stock_quantity": 10,
                "allergens": "None",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = Product.objects.get(name="None Accepted Product")
        self.assertEqual(created.allergens, "none")

    def test_allergen_warning_renders_on_product_list(self):
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allergen Warning")

    def test_allergen_warning_renders_on_product_detail(self):
        self.client.login(username=self.customer.username, password="strong-password-123")
        response = self.client.get(reverse("catalog:product_detail", kwargs={"pk": self.with_allergen.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allergen Warning")
        self.assertContains(response, "I acknowledge the allergen warning")

    def test_filter_with_allergens(self):
        response = self.client.get(reverse("catalog:product_list"), {"allergen_filter": "with_allergens"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.with_allergen.name)
        self.assertNotContains(response, self.without_allergen.name)

    def test_filter_without_allergens(self):
        response = self.client.get(reverse("catalog:product_list"), {"allergen_filter": "without_allergens"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.without_allergen.name)
        self.assertNotContains(response, self.with_allergen.name)
