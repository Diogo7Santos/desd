from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, ProductReview
from orders.models import Order, OrderItem

User = get_user_model()


class TC024ProductReviewTests(TestCase):
    def setUp(self):
        self.producer = User.objects.create_user(
            username="review-producer@example.com",
            email="review-producer@example.com",
            password="StrongPassword123!",
            role="PRODUCER",
        )
        self.customer = User.objects.create_user(
            username="review-customer@example.com",
            email="review-customer@example.com",
            password="StrongPassword123!",
            role="CUSTOMER",
        )
        self.other_customer = User.objects.create_user(
            username="review-customer-two@example.com",
            email="review-customer-two@example.com",
            password="StrongPassword123!",
            role="CUSTOMER",
        )
        self.product = Product.objects.create(
            producer=self.producer,
            name="Organic Tomatoes",
            category=Product.Category.VEGETABLES,
            description="Fresh organic tomatoes",
            price=Decimal("4.50"),
            unit="kg",
            availability=Product.Availability.AVAILABLE,
            stock_quantity=20,
            allergens="",
        )

        self.delivered_item = self._create_order_item(
            customer=self.customer,
            order_status=Order.Status.DELIVERED,
            item_status=Order.Status.DELIVERED,
        )
        self.pending_item = self._create_order_item(
            customer=self.customer,
            order_status=Order.Status.PENDING,
            item_status=Order.Status.PENDING,
        )
        self.other_delivered_item = self._create_order_item(
            customer=self.other_customer,
            order_status=Order.Status.DELIVERED,
            item_status=Order.Status.DELIVERED,
        )

    def _create_order_item(self, *, customer, order_status, item_status):
        order = Order.objects.create(
            customer=customer,
            delivery_address="10 Market Street",
            delivery_postcode="BS1 1AA",
            delivery_date=timezone.localdate() + timedelta(days=3),
            total_amount=self.product.price,
            status=order_status,
        )
        return OrderItem.objects.create(
            order=order,
            product=self.product,
            producer=self.producer,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=1,
            status=item_status,
        )

    def test_customer_can_submit_review_for_delivered_purchase(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        response = self.client.post(
            reverse(
                "catalog:create_review",
                kwargs={"product_id": self.product.id, "order_item_id": self.delivered_item.id},
            ),
            {
                "rating": 5,
                "title": "Excellent quality and flavour",
                "review_text": (
                    "These tomatoes were incredibly fresh and flavourful. "
                    "Perfect for our family's salads."
                ),
                "anonymous": False,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductReview.objects.count(), 1)

        review = ProductReview.objects.get()
        self.assertEqual(review.customer, self.customer)
        self.assertEqual(review.product, self.product)
        self.assertEqual(review.order_item, self.delivered_item)
        self.assertContains(response, "Excellent quality and flavour")
        self.assertContains(response, "Verified Purchase")
        self.assertContains(response, "5.0/5")

    def test_product_page_average_rating_updates(self):
        ProductReview.objects.create(
            product=self.product,
            customer=self.customer,
            order_item=self.delivered_item,
            rating=5,
            title="Excellent",
            review_text="Very fresh.",
        )
        ProductReview.objects.create(
            product=self.product,
            customer=self.other_customer,
            order_item=self.other_delivered_item,
            rating=3,
            title="Decent",
            review_text="Good but not perfect.",
        )

        response = self.client.get(reverse("catalog:product_detail", kwargs={"pk": self.product.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4.0/5")
        self.assertContains(response, "2 reviews")

    def test_customer_cannot_review_undelivered_product(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        response = self.client.post(
            reverse(
                "catalog:create_review",
                kwargs={"product_id": self.product.id, "order_item_id": self.pending_item.id},
            ),
            {
                "rating": 2,
                "title": "Too early",
                "review_text": "This should not be accepted yet.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProductReview.objects.count(), 0)

    def test_duplicate_review_is_blocked(self):
        ProductReview.objects.create(
            product=self.product,
            customer=self.customer,
            order_item=self.delivered_item,
            rating=4,
            title="First review",
            review_text="Original review text.",
        )
        second_delivered_item = self._create_order_item(
            customer=self.customer,
            order_status=Order.Status.DELIVERED,
            item_status=Order.Status.DELIVERED,
        )

        self.client.login(username=self.customer.username, password="StrongPassword123!")
        response = self.client.post(
            reverse(
                "catalog:create_review",
                kwargs={"product_id": self.product.id, "order_item_id": second_delivered_item.id},
            ),
            {
                "rating": 5,
                "title": "Second review attempt",
                "review_text": "Should not be saved.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductReview.objects.count(), 1)
        self.assertContains(response, "First review")

    def test_order_detail_shows_write_review_only_after_delivery(self):
        self.client.login(username=self.customer.username, password="StrongPassword123!")

        delivered_response = self.client.get(
            reverse("orders:order_detail", kwargs={"order_id": self.delivered_item.order_id})
        )
        pending_response = self.client.get(
            reverse("orders:order_detail", kwargs={"order_id": self.pending_item.order_id})
        )

        self.assertContains(delivered_response, "Write Review")
        self.assertContains(pending_response, "Available after delivery")

    def test_anonymous_review_hides_customer_name(self):
        ProductReview.objects.create(
            product=self.product,
            customer=self.customer,
            order_item=self.delivered_item,
            rating=5,
            title="Anonymous praise",
            review_text="Hidden author but still useful.",
            anonymous=True,
        )

        response = self.client.get(reverse("catalog:product_detail", kwargs={"pk": self.product.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anonymous")
        self.assertNotContains(response, self.customer.username)

    def test_producer_can_respond_to_review(self):
        review = ProductReview.objects.create(
            product=self.product,
            customer=self.customer,
            order_item=self.delivered_item,
            rating=4,
            title="Great tomatoes",
            review_text="Really solid quality.",
        )

        self.client.login(username=self.producer.username, password="StrongPassword123!")
        response = self.client.post(
            reverse("catalog:respond_review", kwargs={"review_id": review.id}),
            {"producer_response": "Thanks for ordering from our farm."},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.producer_response, "Thanks for ordering from our farm.")
        self.assertIsNotNone(review.responded_at)
        self.assertContains(response, "Producer Response")
        self.assertContains(response, "Thanks for ordering from our farm.")
