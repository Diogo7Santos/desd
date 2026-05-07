# backend/catalog/tests/test_tc004.py

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product


User = get_user_model()


class TC004CategoryBrowseTest(TestCase):
    """
    TC-004: Customer browses products by category

    Validates:
    - Category pages exist and load
    - Correct filtering by category
    - Only AVAILABLE products are shown (TC-004 acceptance criterion)
    - Key info appears in response (name, price, producer, availability)
    """

    def setUp(self):
        # Create a producer
        self.producer = User.objects.create_user(
            username="producer_browse",
            password="StrongPassword123!",
            first_name="Farm",
            last_name="Owner",
        )
        if hasattr(self.producer, "role"):
            self.producer.role = "producer"
            self.producer.save()
        if hasattr(self.producer, "is_producer"):
            self.producer.is_producer = True
            self.producer.save()

        # Create a customer
        self.customer = User.objects.create_user(
            username="customer_browse",
            password="StrongPassword123!",
        )

        # --- Seed products to meet TC-004 preconditions ---
        # At least 5 products in Vegetables (AVAILABLE)
        self.veg_products = []
        for i in range(1, 6):
            self.veg_products.append(
                Product.objects.create(
                    producer=self.producer,
                    name=f"Tomatoes {i}",
                    category=Product.Category.VEGETABLES,
                    description=f"Fresh tomatoes batch {i}",
                    price=Decimal("1.99"),
                    unit="kg",
                    availability=Product.Availability.AVAILABLE,
                    stock_quantity=10,
                    allergens="",
                    harvest_date=date.today(),
                )
            )

        # At least 3 products in Dairy (AVAILABLE)
        self.dairy_products = []
        for i in range(1, 4):
            self.dairy_products.append(
                Product.objects.create(
                    producer=self.producer,
                    name=f"Milk {i}",
                    category=Product.Category.DAIRY_EGGS,
                    description=f"Local milk bottle {i}",
                    price=Decimal("2.50"),
                    unit="Bottle",
                    availability=Product.Availability.AVAILABLE,
                    stock_quantity=20,
                    allergens="milk",
                    harvest_date=date.today(),
                )
            )

        # Create some products that should NOT appear:
        # - Out of season vegetable
        Product.objects.create(
            producer=self.producer,
            name="Out of Season Carrots",
            category=Product.Category.VEGETABLES,
            description="Should be hidden in TC-004",
            price=Decimal("1.10"),
            unit="kg",
            availability=Product.Availability.OUT_OF_SEASON,
            stock_quantity=10,
            harvest_date=date.today(),
        )

        # - Unavailable dairy
        Product.objects.create(
            producer=self.producer,
            name="Unavailable Cheese",
            category=Product.Category.DAIRY_EGGS,
            description="Should be hidden in TC-004",
            price=Decimal("4.00"),
            unit="Block",
            availability=Product.Availability.UNAVAILABLE,
            stock_quantity=10,
            harvest_date=date.today(),
        )

        # URLs
        self.list_url = reverse("catalog:product_list")
        self.veg_url = reverse("catalog:category_list", kwargs={"category": Product.Category.VEGETABLES})
        self.dairy_url = reverse("catalog:category_list", kwargs={"category": Product.Category.DAIRY_EGGS})

    def test_marketplace_homepage_shows_available_products(self):
        """
        Optional extra validation: homepage listing should show AVAILABLE products
        (your product_list view filters availability).
        """
        self.client.login(username="customer_browse", password="StrongPassword123!")

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)

        # Should contain at least one known available product
        self.assertContains(response, "Tomatoes 1")
        self.assertContains(response, "Milk 1")

        # Should not contain unavailable/out-of-season items
        self.assertNotContains(response, "Out of Season Carrots")
        self.assertNotContains(response, "Unavailable Cheese")

    def test_vegetables_category_filters_correctly(self):
        self.client.login(username="customer_browse", password="StrongPassword123!")

        response = self.client.get(self.veg_url)
        self.assertEqual(response.status_code, 200)

        # Should show vegetables (AVAILABLE)
        for p in self.veg_products:
            self.assertContains(response, p.name)

        # Should NOT show dairy products on vegetables page
        for p in self.dairy_products:
            self.assertNotContains(response, p.name)

        # Should NOT show out-of-season vegetable
        self.assertNotContains(response, "Out of Season Carrots")

    def test_dairy_category_filters_correctly(self):
        self.client.login(username="customer_browse", password="StrongPassword123!")

        response = self.client.get(self.dairy_url)
        self.assertEqual(response.status_code, 200)

        # Should show dairy (AVAILABLE)
        for p in self.dairy_products:
            self.assertContains(response, p.name)

        # Should NOT show vegetables on dairy page
        for p in self.veg_products:
            self.assertNotContains(response, p.name)

        # Should NOT show unavailable dairy
        self.assertNotContains(response, "Unavailable Cheese")

    def test_category_page_contains_key_info(self):
        """
        TC-004 expected results mention key info like name, price, producer, availability.
        We can only assert what your templates render, so this checks for common fields.

        If your templates don't currently show producer username or availability text,
        update the templates OR adjust these assertions.
        """
        self.client.login(username="customer_browse", password="StrongPassword123!")

        response = self.client.get(self.veg_url)
        self.assertEqual(response.status_code, 200)

        # Product name (should be present)
        self.assertContains(response, "Tomatoes 1")

        # Price (string match)
        self.assertContains(response, "1.99")

        # Producer identifier (commonly username)
        self.assertContains(response, self.producer.username)

        # Availability label text is optional depending on your template,
        # but TC-004 expects it to be displayed.
        # If your template uses Product.get_availability_display, this should appear:
        self.assertContains(response, "In Season", msg_prefix="Availability label not found in page output")

    def test_invalid_category_returns_404(self):
        self.client.login(username="customer_browse", password="StrongPassword123!")

        bad_url = reverse("catalog:category_list", kwargs={"category": "NOT_A_REAL_CATEGORY"})
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)