from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from .models import Address, CustomerProfile, ProducerProfile
from . import views as account_views
from .web_forms import POSTCODE_ERROR_MESSAGE

User = get_user_model()


class AccountsTestCases(TestCase):
    def producer_payload(self, **overrides):
        data = {
            "email": "jane.smith@bristolvalleyfarm.com",
            "phone": "01179123456",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role": User.Role.PRODUCER,
            "business_name": "Bristol Valley Farm",
            "contact_name": "Jane Smith",
            "business_address": "45 Valley Road, Bristol",
            "producer_postcode": "BS1 4DJ",
        }
        data.update(overrides)
        return data

    def customer_payload(self, **overrides):
        data = {
            "email": "robert.johnson@email.com",
            "phone": "07700900123",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role": User.Role.CUSTOMER,
            "full_name": "Robert Johnson",
            "customer_type_id": str(CustomerProfile.CustomerType.INDIVIDUAL),
            "line_1": "45 Park Street",
            "line_2": "",
            "city": "Bristol",
            "customer_postcode": "BS1 5JG",
            "accept_terms": "on",
        }
        data.update(overrides)
        return data

    def create_producer_user(self, email="producer@example.com", password="StrongPass123!"):
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            role=User.Role.PRODUCER,
        )
        ProducerProfile.objects.create(
            user=user,
            business_name="Demo Farm",
            contact_name="Producer User",
            business_address="1 Farm Lane, Bristol",
            postcode="BS1 4DJ",
        )
        return user

    def create_customer_user(self, email="customer@example.com", password="StrongPass123!"):
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            role=User.Role.CUSTOMER,
        )
        address = Address.objects.create(
            user=user,
            line_1="12 Test Street",
            line_2="",
            city="Bristol",
            postcode="BS1 5JG",
        )
        CustomerProfile.objects.create(
            user=user,
            customer_type_id=CustomerProfile.CustomerType.INDIVIDUAL,
            address=address,
        )
        return user

    def test_tc001_register_producer(self):
        response = self.client.post(
            reverse("register"),
            data=self.producer_payload(),
            follow=True,
        )

        self.assertRedirects(response, reverse("catalog:producer_products"))

        user = User.objects.get(email="jane.smith@bristolvalleyfarm.com")
        self.assertEqual(user.username, "jane.smith@bristolvalleyfarm.com")
        self.assertEqual(user.role, User.Role.PRODUCER)
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertTrue(user.check_password("StrongPass123!"))

        self.assertTrue(hasattr(user, "producer_profile"))
        self.assertEqual(user.producer_profile.business_name, "Bristol Valley Farm")
        self.assertEqual(user.producer_profile.contact_name, "Jane Smith")
        self.assertEqual(user.producer_profile.business_address, "45 Valley Road, Bristol")
        self.assertEqual(user.producer_profile.postcode, "BS1 4DJ")

        self.assertContains(response, "Account created successfully")
        self.assertIn("_auth_user_id", self.client.session)

    def test_tc002_register_customer(self):
        response = self.client.post(
            reverse("register"),
            data=self.customer_payload(),
            follow=True,
        )

        self.assertRedirects(response, reverse("customer_home"))

        user = User.objects.get(email="robert.johnson@email.com")
        self.assertEqual(user.username, "robert.johnson@email.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.first_name, "Robert")
        self.assertEqual(user.last_name, "Johnson")

        self.assertTrue(hasattr(user, "customer_profile"))
        self.assertEqual(
            user.customer_profile.customer_type_id,
            CustomerProfile.CustomerType.INDIVIDUAL,
        )
        self.assertEqual(user.customer_profile.address.line_1, "45 Park Street")
        self.assertEqual(user.customer_profile.address.city, "Bristol")
        self.assertEqual(user.customer_profile.address.postcode, "BS1 5JG")

        self.assertContains(response, "Account created successfully")
        self.assertIn("_auth_user_id", self.client.session)

    def test_tc022_password_policy_rejects_weak_password(self):
        response = self.client.post(
            reverse("register"),
            data=self.customer_payload(
                email="weak@example.com",
                password1="123",
                password2="123",
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())
        self.assertContains(response, "This password is too short")

    def test_tc022_login_errors_are_generic_and_password_is_hashed(self):
        user = self.create_customer_user(email="sec@example.com", password="StrongPass123!")

        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertTrue(user.check_password("StrongPass123!"))

        wrong_password_response = self.client.post(
            reverse("login"),
            data={
                "email": "sec@example.com",
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(wrong_password_response.status_code, 200)
        self.assertContains(wrong_password_response, account_views.GENERIC_LOGIN_ERROR)

        missing_user_response = self.client.post(
            reverse("login"),
            data={
                "email": "missing@example.com",
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(missing_user_response.status_code, 200)
        self.assertContains(missing_user_response, account_views.GENERIC_LOGIN_ERROR)

        wrong_role_response = self.client.post(
            reverse("login"),
            data={
                "email": "sec@example.com",
                "password": "StrongPass123!",
                "role": User.Role.PRODUCER,
            },
            follow=True,
        )
        self.assertEqual(wrong_role_response.status_code, 200)
        self.assertContains(wrong_role_response, account_views.GENERIC_LOGIN_ERROR)

    @patch("accounts.views.logger.warning")
    def test_tc022_failed_login_attempts_are_logged(self, mocked_warning):
        self.create_customer_user(email="logme@example.com", password="StrongPass123!")
        self.client.post(
            reverse("login"),
            data={
                "email": "logme@example.com",
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertTrue(mocked_warning.called)

    def test_tc022_bruteforce_lockout_and_success_resets_counter(self):
        email = "lockout@example.com"
        self.create_customer_user(email=email, password="StrongPass123!")
        cache_key = account_views._cache_lockout_key(email, "127.0.0.1")
        cache.delete(cache_key)

        # Prime failed attempts and then recover with a successful login.
        for _ in range(2):
            self.client.post(
                reverse("login"),
                data={
                    "email": email,
                    "password": "WrongPassword999!",
                    "role": User.Role.CUSTOMER,
                },
                follow=True,
            )
        success = self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "StrongPass123!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(success.status_code, 200)
        self.client.post(reverse("logout"), follow=True)

        # Counter should have reset; lockout should happen only after max failed attempts.
        for _ in range(account_views.MAX_LOGIN_ATTEMPTS):
            self.client.post(
                reverse("login"),
                data={
                    "email": email,
                    "password": "WrongPassword999!",
                    "role": User.Role.CUSTOMER,
                },
                follow=True,
            )
        locked = self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "StrongPass123!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertContains(locked, "Too many failed login attempts. Please try again later.")

    def test_tc022_failed_login_attempts_increment_session_and_cache_counters(self):
        email = "counter@example.com"
        self.create_customer_user(email=email, password="StrongPass123!")
        cache_key = account_views._cache_lockout_key(email, "127.0.0.1")
        cache.delete(cache_key)

        self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(self.client.session.get("failed_login_attempts"), 1)
        self.assertEqual(int(cache.get(cache_key, 0)), 1)

        self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(self.client.session.get("failed_login_attempts"), 2)
        self.assertEqual(int(cache.get(cache_key, 0)), 2)

    def test_tc022_successful_login_resets_failed_login_counters(self):
        email = "reset@example.com"
        self.create_customer_user(email=email, password="StrongPass123!")
        cache_key = account_views._cache_lockout_key(email, "127.0.0.1")
        cache.delete(cache_key)

        self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "WrongPassword999!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(self.client.session.get("failed_login_attempts"), 1)
        self.assertEqual(int(cache.get(cache_key, 0)), 1)

        self.client.post(
            reverse("login"),
            data={
                "email": email,
                "password": "StrongPass123!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertEqual(self.client.session.get("failed_login_attempts"), 0)
        self.assertEqual(self.client.session.get("last_failed_login_ts"), 0)
        self.assertIsNone(cache.get(cache_key))

    def test_tc022_logout_terminates_session(self):
        user = self.create_customer_user(email="logout-check@example.com")
        self.client.login(username=user.email, password="StrongPass123!")
        self.assertIn("_auth_user_id", self.client.session)

        self.client.post(reverse("logout"), follow=True)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_tc022_rbac_and_session_management(self):
        customer = self.create_customer_user(email="rbac-customer@example.com")
        producer = self.create_producer_user(email="rbac-producer@example.com")

        login_customer = self.client.post(
            reverse("login"),
            data={
                "email": customer.email,
                "password": "StrongPass123!",
                "role": User.Role.CUSTOMER,
            },
            follow=True,
        )
        self.assertRedirects(login_customer, reverse("customer_home"))
        self.assertTrue(self.client.session.get_expire_at_browser_close())

        denied_response = self.client.get(reverse("producer_home"))
        self.assertEqual(denied_response.status_code, 403)

        logout_response = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(logout_response, reverse("login"))

        protected_after_logout = self.client.get(reverse("producer_home"))
        self.assertRedirects(
            protected_after_logout,
            f"{reverse('login')}?next={reverse('producer_home')}",
        )

        login_producer = self.client.post(
            reverse("login"),
            data={
                "email": producer.email,
                "password": "StrongPass123!",
                "role": User.Role.PRODUCER,
                "remember_me": "on",
            },
            follow=True,
        )
        self.assertRedirects(login_producer, reverse("catalog:producer_products"))
        self.assertFalse(self.client.session.get_expire_at_browser_close())

        allowed_response = self.client.get(reverse("producer_home"))
        self.assertEqual(allowed_response.status_code, 200)

        final_logout = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(final_logout, reverse("login"))


class RoleRedirectTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="redirect-admin@example.com",
            email="redirect-admin@example.com",
            password="StrongPass123!",
            role=User.Role.ADMIN,
        )
        self.producer_user = User.objects.create_user(
            username="redirect-producer@example.com",
            email="redirect-producer@example.com",
            password="StrongPass123!",
            role=User.Role.PRODUCER,
        )
        self.customer_user = User.objects.create_user(
            username="redirect-customer@example.com",
            email="redirect-customer@example.com",
            password="StrongPass123!",
            role=User.Role.CUSTOMER,
        )

    def test_admin_login_redirects_to_admin_portal(self):
        response = self.client.post(
            reverse("login"),
            data={
                "email": self.admin_user.email,
                "password": "StrongPass123!",
                "role": User.Role.ADMIN,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_dashboard:dashboard"))

    def test_producer_login_redirects_to_producer_area(self):
        response = self.client.post(
            reverse("login"),
            data={
                "email": self.producer_user.email,
                "password": "StrongPass123!",
                "role": User.Role.PRODUCER,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("catalog:producer_products"))

    def test_customer_login_redirects_to_customer_marketplace(self):
        response = self.client.post(
            reverse("login"),
            data={
                "email": self.customer_user.email,
                "password": "StrongPass123!",
                "role": User.Role.CUSTOMER,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("catalog:product_list"))

    def test_django_admin_route_still_resolves(self):
        self.assertEqual(reverse("admin:index"), "/admin/")
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, [200, 302])

def test_tc017_register_community_group_account(self):
    response = self.client.post(
        reverse("register"),
        data={
            "email": "catering@stmarys-school.org.uk",
            "phone": "01179000000",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role": User.Role.CUSTOMER,
            "full_name": "School Catering",
            "customer_type_id": str(CustomerProfile.CustomerType.COMMUNITY_GROUP),
            "organisation_name": "St. Mary's School",
            "contact_person": "Kitchen Manager",
            "is_charity_or_education": "on",
            "default_delivery_instructions": "Delivery to kitchen entrance",
            "line_1": "45 School Lane",
            "line_2": "",
            "city": "Bristol",
            "customer_postcode": "BS1 5JG",
            "accept_terms": "on",
        },
        follow=True,
    )

    self.assertRedirects(response, reverse("customer_home"))
    user = User.objects.get(email="catering@stmarys-school.org.uk")
    profile = user.customer_profile

    self.assertEqual(profile.customer_type_id, CustomerProfile.CustomerType.COMMUNITY_GROUP)
    self.assertEqual(profile.organisation_name, "St. Mary's School")
    self.assertEqual(profile.contact_person, "Kitchen Manager")
    self.assertTrue(profile.is_charity_or_education)
    self.assertFalse(profile.is_business_verified)

def test_tc018_register_restaurant_account_requires_business_fields(self):
    response = self.client.post(
        reverse("register"),
        data={
            "email": "orders@cliftonkitchen.co.uk",
            "phone": "01179000001",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role": User.Role.CUSTOMER,
            "full_name": "Restaurant Owner",
            "customer_type_id": str(CustomerProfile.CustomerType.RESTAURANT),
            "line_1": "10 Clifton Road",
            "line_2": "",
            "city": "Bristol",
            "customer_postcode": "BS8 1AB",
            "accept_terms": "on",
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "This field is required for restaurant accounts.")

    def test_tc021_account_page_available_to_logged_in_customer(self):
        user = self.create_customer_user(email="history@example.com")
        self.client.login(username=user.email, password="StrongPass123!")

        response = self.client.get(reverse("account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Account")

    def test_producer_can_update_account_details(self):
        user = self.create_producer_user(email="producer-update@example.com")
        self.client.login(username=user.email, password="StrongPass123!")

        response = self.client.post(
            reverse("account"),
            data={
                "user-email": "updated-producer@example.com",
                "user-phone": "01179998877",
                "producer-business_name": "Updated Farm",
                "producer-contact_name": "Updated Producer",
                "producer-business_address": "99 Farm Lane, Bristol",
                "producer-postcode": "BS1 6AA",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account details updated successfully.")

        user.refresh_from_db()
        user.producer_profile.refresh_from_db()
        self.assertEqual(user.email, "updated-producer@example.com")
        self.assertEqual(user.username, "updated-producer@example.com")
        self.assertEqual(user.phone, "01179998877")
        self.assertEqual(user.producer_profile.business_name, "Updated Farm")
        self.assertEqual(user.producer_profile.contact_name, "Updated Producer")
        self.assertEqual(user.producer_profile.business_address, "99 Farm Lane, Bristol")
        self.assertEqual(user.producer_profile.postcode, "BS1 6AA")


class PostcodeValidationTests(TestCase):
    def create_producer_user(self, email="postcode-producer@example.com", password="StrongPass123!"):
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            role=User.Role.PRODUCER,
        )
        ProducerProfile.objects.create(
            user=user,
            business_name="Demo Farm",
            contact_name="Producer User",
            business_address="1 Farm Lane, Bristol",
            postcode="BS1 4DJ",
        )
        return user

    def test_register_rejects_invalid_producer_postcode(self):
        response = self.client.post(
            reverse("register"),
            data={
                "email": "invalid-producer@example.com",
                "phone": "01179123456",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "role": User.Role.PRODUCER,
                "business_name": "Bristol Valley Farm",
                "contact_name": "Jane Smith",
                "business_address": "45 Valley Road, Bristol",
                "producer_postcode": "usefhguihf",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, POSTCODE_ERROR_MESSAGE)
        self.assertFalse(User.objects.filter(email="invalid-producer@example.com").exists())

    def test_register_normalizes_customer_postcode_format(self):
        response = self.client.post(
            reverse("register"),
            data={
                "email": "normalized-customer@example.com",
                "phone": "07700900123",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "role": User.Role.CUSTOMER,
                "full_name": "Robert Johnson",
                "customer_type_id": str(CustomerProfile.CustomerType.INDIVIDUAL),
                "line_1": "45 Park Street",
                "line_2": "",
                "city": "Bristol",
                "customer_postcode": "bs13tb",
                "accept_terms": "on",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("customer_home"))
        user = User.objects.get(email="normalized-customer@example.com")
        self.assertEqual(user.customer_profile.address.postcode, "BS1 3TB")

    def test_account_update_rejects_invalid_producer_postcode(self):
        user = self.create_producer_user()
        self.client.login(username=user.email, password="StrongPass123!")

        response = self.client.post(
            reverse("account"),
            data={
                "user-email": user.email,
                "user-phone": "01179998877",
                "producer-business_name": "Updated Farm",
                "producer-contact_name": "Updated Producer",
                "producer-business_address": "99 Farm Lane, Bristol",
                "producer-postcode": "7yr98yfuih",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, POSTCODE_ERROR_MESSAGE)

        user.producer_profile.refresh_from_db()
        self.assertEqual(user.producer_profile.postcode, "BS1 4DJ")
