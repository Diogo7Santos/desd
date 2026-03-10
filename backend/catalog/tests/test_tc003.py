# backend/catalog/tests/test_tc003.py

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product


User = get_user_model()


class TC003ProductCreateTest(TestCase):
    """
    TC-003: Producer lists a new product

    Validates:
    - Only authenticated producers can create products
    - Product saves correctly
    - Product is linked to producer
    - Required fields enforced
    """

    def setUp(self):
        # Create a producer user
        self.producer = User.objects.create_user(
            username="producer1",
            password="StrongPassword123!",
        )

        # If your project uses a role field:
        if hasattr(self.producer, "role"):
            self.producer.role = "producer"
            self.producer.save()

        # If your project uses boolean flag:
        if hasattr(self.producer, "is_producer"):
            self.producer.is_producer = True
            self.producer.save()

        # Create a normal customer user
        self.customer = User.objects.create_user(
            username="customer1",
            password="StrongPassword123!",
        )

        self.url = reverse("catalog:product_create")

    # ---------------------------------------------------
    # SUCCESS CASE
    # ---------------------------------------------------

    def test_producer_can_create_product(self):
        self.client.login(username="producer1", password="StrongPassword123!")

        response = self.client.post(
            self.url,
            {
                "name": "Organic Free Range Eggs",
                "category": Product.Category.DAIRY_EGGS,
                "description": "Fresh organic eggs from free-range hens",
                "price": "3.50",
                "unit": "Dozen",
                "availability": Product.Availability.AVAILABLE,
                "stock_quantity": 50,
                "allergens": "eggs",
                "harvest_date": date.today(),
            },
        )

        # Should redirect after success
        self.assertEqual(response.status_code, 302)

        self.assertEqual(Product.objects.count(), 1)

        product = Product.objects.first()

        self.assertEqual(product.name, "Organic Free Range Eggs")
        self.assertEqual(product.producer, self.producer)
        self.assertEqual(product.price, Decimal("3.50"))
        self.assertEqual(product.stock_quantity, 50)
        self.assertTrue(product.is_available)

    # ---------------------------------------------------
    # PERMISSION CHECK
    # ---------------------------------------------------

    def test_customer_cannot_create_product(self):
        self.client.login(username="customer1", password="StrongPassword123!")

        response = self.client.post(
            self.url,
            {
                "name": "Should Fail Product",
                "category": Product.Category.BAKERY,
                "description": "Invalid attempt",
                "price": "2.00",
                "unit": "Loaf",
                "availability": Product.Availability.AVAILABLE,
                "stock_quantity": 10,
            },
        )

        # Should be forbidden
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Product.objects.count(), 0)

    # ---------------------------------------------------
    # VALIDATION CHECK
    # ---------------------------------------------------

    def test_invalid_product_missing_required_fields(self):
        self.client.login(username="producer1", password="StrongPassword123!")

        response = self.client.post(
            self.url,
            {
                # Missing name, price, etc.
                "category": Product.Category.VEGETABLES,
                "stock_quantity": 10,
            },
        )

        # Should NOT redirect
        self.assertEqual(response.status_code, 200)

        # Product should not be created
        self.assertEqual(Product.objects.count(), 0)

    # ---------------------------------------------------
    # STOCK RULE CHECK
    # ---------------------------------------------------

    def test_available_product_cannot_have_zero_stock(self):
        self.client.login(username="producer1", password="StrongPassword123!")

        response = self.client.post(
            self.url,
            {
                "name": "Zero Stock Item",
                "category": Product.Category.VEGETABLES,
                "description": "Invalid zero stock",
                "price": "1.00",
                "unit": "kg",
                "availability": Product.Availability.AVAILABLE,
                "stock_quantity": 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.objects.count(), 0)