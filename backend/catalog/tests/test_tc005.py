# backend/catalog/tests/test_tc005.py

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product


User = get_user_model()


class TC005ProductSearchTest(TestCase):
    """
    TC-005: Customer searches for products

    Validates:
    - Search endpoint exists and loads
    - Case-insensitive search
    - Partial match behavior (contains)
    - Searches name and description (and producer name if template/logic supports it)
    - Results include product name, price, producer, category (template-dependent)
    - Non-existent term shows graceful empty results
    - Only AVAILABLE products appear (aligned with your views filtering)
    """

    def setUp(self):
        # Producer
        self.producer = User.objects.create_user(
            username="producer_search",
            password="StrongPassword123!",
            first_name="Organic",
            last_name="Farmer",
        )
        if hasattr(self.producer, "role"):
            self.producer.role = "producer"
            self.producer.save()
        if hasattr(self.producer, "is_producer"):
            self.producer.is_producer = True
            self.producer.save()

        # Customer
        self.customer = User.objects.create_user(
            username="customer_search",
            password="StrongPassword123!",
        )

        # Products
        self.tomatoes = Product.objects.create(
            producer=self.producer,
            name="Cherry Tomatoes",
            category=Product.Category.VEGETABLES,
            description="Fresh tomatoes grown locally",
            price=Decimal("2.25"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=10,
            allergens="",
            harvest_date=date.today(),
        )

        self.organic_honey = Product.objects.create(
            producer=self.producer,
            name="Organic Honey",
            category=Product.Category.PRESERVES,
            description="Raw organic honey from local hives",
            price=Decimal("6.50"),
            unit="Jar",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=5,
            allergens="",
            harvest_date=date.today(),
        )

        # This should NOT appear in search results because it is not AVAILABLE
        self.out_of_season_tomatoes = Product.objects.create(
            producer=self.producer,
            name="Heirloom Tomatoes",
            category=Product.Category.VEGETABLES,
            description="Seasonal tomatoes - not currently available",
            price=Decimal("3.00"),
            unit="kg",
            availability=Product.Availability.OUT_OF_SEASON,
            stock_quantity=10,
            allergens="",
            harvest_date=date.today(),
        )

        self.search_url = reverse("catalog:product_search")

    def _get(self, q: str):
        return self.client.get(self.search_url, {"q": q})

    def test_search_page_loads_even_without_query(self):
        self.client.login(username="customer_search", password="StrongPassword123!")
        response = self.client.get(self.search_url)
        self.assertEqual(response.status_code, 200)

    def test_search_by_name_finds_tomatoes(self):
        self.client.login(username="customer_search", password="StrongPassword123!")

        response = self._get("tomatoes")
        self.assertEqual(response.status_code, 200)

        # Should include available tomatoes
        self.assertContains(response, "Cherry Tomatoes")

        # Should not include out-of-season tomatoes
        self.assertNotContains(response, "Heirloom Tomatoes")

    def test_search_is_case_insensitive(self):
        self.client.login(username="customer_search", password="StrongPassword123!")

        response = self._get("ToMaToEs")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cherry Tomatoes")

    def test_search_partial_match(self):
        self.client.login(username="customer_search", password="StrongPassword123!")

        # "tomat" should match "Tomatoes" if using icontains
        response = self._get("tomat")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cherry Tomatoes")

    def test_search_by_description_finds_organic(self):
        self.client.login(username="customer_search", password="StrongPassword123!")

        response = self._get("organic")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Organic Honey")

    def test_search_nonexistent_term_shows_no_results_gracefully(self):
        self.client.login(username="customer_search", password="StrongPassword123!")

        response = self._get("this-does-not-exist-xyz")
        self.assertEqual(response.status_code, 200)

        # You may show "No results found" in template.
        # We check either that message appears OR that none of the known products appear.
        # If you haven't added the message yet, add it to search_results.html.
        if b"No results" in response.content or b"no results" in response.content:
            self.assertTrue(True)
        else:
            self.assertNotContains(response, "Cherry Tomatoes")
            self.assertNotContains(response, "Organic Honey")

    def test_search_results_contain_key_info_template_dependent(self):
        """
        TC-005 expects result cards to show product name, price, producer, category.

        These assertions depend on your template output:
        - If you don't show producer.username/category label in search_results.html,
          update the template or adjust these asserts.
        """
        self.client.login(username="customer_search", password="StrongPassword123!")

        response = self._get("tomatoes")
        self.assertEqual(response.status_code, 200)

        # Name
        self.assertContains(response, "Cherry Tomatoes")
        # Price (string match)
        self.assertContains(response, "2.25")
        # Producer identifier (commonly username)
        self.assertContains(response, self.producer.username)
        # Category label (either key or display; display is nicer)
        # If you use get_category_display in template, it will be "Vegetables"
        self.assertTrue(
            ("Vegetables" in response.content.decode(errors="ignore"))
            or (Product.Category.VEGETABLES in response.content.decode(errors="ignore")),
            "Category not found in response (update template to display it).",
        )