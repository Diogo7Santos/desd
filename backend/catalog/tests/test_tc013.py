from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Address, CustomerProfile, ProducerProfile
from catalog.food_miles import calculate_food_miles, food_miles_for_product
from catalog.models import Product

User = get_user_model()


class TC013FoodMilesLookupTests(SimpleTestCase):
    @patch("catalog.food_miles.lookup_postcode")
    def test_bs7_postcode_is_supported(self, mocked_lookup):
        mocked_lookup.side_effect = [
            {"postcode": "BS1 3TB", "latitude": 51.454, "longitude": -2.588},
            {"postcode": "BS7 0SJ", "latitude": 51.487, "longitude": -2.580},
        ]

        result = calculate_food_miles("BS1 3TB", "BS7 0SJ")

        self.assertIsNotNone(result)
        self.assertGreater(result.miles, 0)
        self.assertRegex(result.miles_display, r"^\d+\.\d$")

    @patch("catalog.food_miles.lookup_postcode")
    def test_calculation_uses_live_lookup_coordinates_when_available(self, mocked_lookup):
        mocked_lookup.side_effect = [
            {"postcode": "BS1 3TB", "latitude": 51.454, "longitude": -2.588},
            {"postcode": "BS7 0SJ", "latitude": 51.487, "longitude": -2.580},
        ]

        result = calculate_food_miles("BS1 3TB", "BS7 0SJ")

        self.assertIsNotNone(result)
        self.assertGreater(result.miles, 0)

    @patch("catalog.food_miles.lookup_postcode")
    def test_calculation_returns_none_when_lookup_is_unavailable(self, mocked_lookup):
        mocked_lookup.return_value = None

        result = calculate_food_miles("BS1 3TB", "BS7 0SJ")

        self.assertIsNone(result)


class TC013FoodMilesTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="foodmiles-customer@example.com",
            email="foodmiles-customer@example.com",
            password="StrongPassword123!",
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

        self.near_producer = User.objects.create_user(
            username="near-farm@example.com",
            email="near-farm@example.com",
            password="StrongPassword123!",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.near_producer,
            business_name="Bristol Valley Farm",
            contact_name="Near Farmer",
            business_address="45 Valley Road, Bristol",
            postcode="BS1 4DJ",
        )

        self.far_producer = User.objects.create_user(
            username="far-farm@example.com",
            email="far-farm@example.com",
            password="StrongPassword123!",
            role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=self.far_producer,
            business_name="Gloucester Orchard",
            contact_name="Far Farmer",
            business_address="10 Orchard Way, Gloucester",
            postcode="GL1 1AA",
        )

        self.near_product = Product.objects.create(
            producer=self.near_producer,
            name="Local Carrots",
            category=Product.Category.VEGETABLES,
            description="Fresh and nearby",
            price=Decimal("2.50"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=8,
            allergens="",
        )
        self.far_product = Product.objects.create(
            producer=self.far_producer,
            name="Orchard Apples",
            category=Product.Category.SEASONAL,
            description="Travelled further",
            price=Decimal("3.20"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=12,
            allergens="",
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

    def test_product_list_displays_food_miles_for_customer(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)

        near_food_miles = food_miles_for_product(self.near_product, "BS1 5JG")
        far_food_miles = food_miles_for_product(self.far_product, "BS1 5JG")

        self.assertIsNotNone(near_food_miles)
        self.assertIsNotNone(far_food_miles)
        self.assertLess(near_food_miles.miles, far_food_miles.miles)

        self.assertContains(response, f"Food Miles: {near_food_miles.miles_display}")
        self.assertContains(response, f"Food Miles: {far_food_miles.miles_display}")

    def test_product_detail_shows_local_radius_message(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        near_response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": self.near_product.pk})
        )
        self.assertEqual(near_response.status_code, 200)
        self.assertContains(near_response, "Food Miles")
        self.assertContains(near_response, "Within 20-mile radius")

        far_response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": self.far_product.pk})
        )
        self.assertEqual(far_response.status_code, 200)
        self.assertContains(far_response, "Outside 20-mile radius")

    def test_search_results_keep_food_miles_visible(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        response = self.client.get(reverse("catalog:product_search"), {"q": "carrots"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Carrots")
        self.assertContains(response, "Food Miles")
