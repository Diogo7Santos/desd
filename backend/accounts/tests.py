from django.test import TestCase

# Create your tests here.
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class AccountsTestCases(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_tc001_register_producer(self):
        resp = self.client.post(
            "/api/accounts/register/producer/",
            {"email": "p@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        u = User.objects.get(email="p@example.com")
        self.assertEqual(u.role, User.Role.PRODUCER)

    def test_tc002_register_customer(self):
        resp = self.client.post(
            "/api/accounts/register/customer/",
            {"email": "c@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        u = User.objects.get(email="c@example.com")
        self.assertEqual(u.role, User.Role.CUSTOMER)

    def test_tc022_secure_authentication(self):
        # register customer
        resp = self.client.post(
            "/api/accounts/register/customer/",
            {"email": "sec@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

        u = User.objects.get(email="sec@example.com")

        # password must be hashed (not equal to raw)
        self.assertNotEqual(u.password, "StrongPass123!")
        self.assertTrue(u.check_password("StrongPass123!"))

        # unauthenticated access blocked
        me_resp = self.client.get("/api/accounts/me/")
        self.assertIn(me_resp.status_code, (401, 403))

        # authenticated access allowed
        token = resp.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        me_resp2 = self.client.get("/api/accounts/me/")
        self.assertEqual(me_resp2.status_code, 200)