import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ProducerProfile, CustomerProfile, Address
from .web_forms import LoginForm, RegisterForm
from django.db import transaction
from .web_forms import (
    LoginForm, RegisterForm,
    UserAccountForm, ProducerAccountForm,
    CustomerAccountForm, AddressForm,
)

logger = logging.getLogger(__name__)
User = get_user_model()

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def _has_role(user, role: str) -> bool:
    if role == User.Role.ADMIN:
        return user.is_staff or user.is_superuser or getattr(user, "role", None) == User.Role.ADMIN
    return getattr(user, "role", None) == role


def _redirect_by_user_role(user):
    if _has_role(user, User.Role.ADMIN):
        return redirect("admin_home")
    if _has_role(user, User.Role.PRODUCER):
        return redirect("catalog:producer_products")
    return redirect("catalog:product_list")


def _is_locked_out(request):
    attempts = request.session.get("failed_login_attempts", 0)
    last_failed = request.session.get("last_failed_login_ts")

    if attempts < MAX_LOGIN_ATTEMPTS or not last_failed:
        return False

    if timezone.now().timestamp() - last_failed < LOCKOUT_SECONDS:
        return True

    request.session["failed_login_attempts"] = 0
    request.session["last_failed_login_ts"] = 0
    return False


def _record_failed_login(request, email):
    request.session["failed_login_attempts"] = request.session.get("failed_login_attempts", 0) + 1
    request.session["last_failed_login_ts"] = timezone.now().timestamp()
    logger.warning("Failed login attempt for email=%s", email)


def _clear_failed_logins(request):
    request.session["failed_login_attempts"] = 0
    request.session["last_failed_login_ts"] = 0


def login_page(request):
    if request.user.is_authenticated:
        return _redirect_by_user_role(request.user)

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        password = form.cleaned_data["password"]
        selected_role = form.cleaned_data["role"]
        remember_me = form.cleaned_data.get("remember_me", False)

        if _is_locked_out(request):
            messages.error(request, "Too many failed login attempts. Please try again later.")
            return render(request, "accounts/login.html", {"form": form})

        user = authenticate(request, username=email, password=password)

        if user is None:
            _record_failed_login(request, email)
            messages.error(request, "Invalid email or password.")
        elif not _has_role(user, selected_role):
            messages.error(request, "Role does not match this account.")
        else:
            _clear_failed_logins(request)
            login(request, user)

            if remember_me:
                request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            else:
                request.session.set_expiry(0)

            messages.success(request, "Login successful.")
            return _redirect_by_user_role(user)

    return render(request, "accounts/login.html", {"form": form})


def register_page(request):
    if request.user.is_authenticated:
        return _redirect_by_user_role(request.user)

    form = RegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        role = form.cleaned_data["role"]
        password = form.cleaned_data["password1"]
        phone = form.cleaned_data["phone"]

        if User.objects.filter(email=email).exists():
            form.add_error("email", "Email already registered.")
            return render(request, "accounts/register.html", {"form": form})

        full_name = form.cleaned_data.get("full_name", "").strip()
        first_name = ""
        last_name = ""
        if full_name:
            name_parts = full_name.split(maxsplit=1)
            first_name = name_parts[0]
            if len(name_parts) > 1:
                last_name = name_parts[1]

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        user.role = role
        user.phone = phone
        user.save()

        if role == User.Role.PRODUCER:
            ProducerProfile.objects.create(
                user=user,
                business_name=form.cleaned_data["business_name"],
                contact_name=form.cleaned_data["contact_name"],
                business_address=form.cleaned_data["business_address"],
                postcode=form.cleaned_data["producer_postcode"],
            )

        elif role == User.Role.CUSTOMER:
            full_name = form.cleaned_data.get("full_name", "").strip()
            if full_name and not user.first_name:
                parts = full_name.split(maxsplit=1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ""
                user.save()

            address = Address.objects.create(
                user=user,
                line_1=form.cleaned_data["line_1"],
                line_2=form.cleaned_data.get("line_2", ""),
                city=form.cleaned_data["city"],
                postcode=form.cleaned_data["customer_postcode"],
            )

            customer_type_id = int(form.cleaned_data["customer_type_id"])

            CustomerProfile.objects.create(
                user=user,
                customer_type_id=customer_type_id,
                address=address,
                organisation_name=form.cleaned_data.get("organisation_name", ""),
                contact_person=form.cleaned_data.get("contact_person", ""),
                is_charity_or_education=form.cleaned_data.get("is_charity_or_education", False),
                default_delivery_instructions=form.cleaned_data.get("default_delivery_instructions", ""),
                is_business_verified=(customer_type_id == CustomerProfile.CustomerType.INDIVIDUAL),
            )

        login(request, user)
        messages.success(request, "Account created successfully.")
        return _redirect_by_user_role(user)

    return render(request, "accounts/register.html", {"form": form})


@login_required
@require_POST
def logout_page(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("/")

@login_required
def customer_home(request):
    if not _has_role(request.user, User.Role.CUSTOMER):
        return HttpResponseForbidden("Forbidden: customer only.")
    return render(
        request,
        "accounts/customer_home.html",
        {"customer_profile": getattr(request.user, "customer_profile", None)},
    )


@login_required
def producer_home(request):
    if not _has_role(request.user, User.Role.PRODUCER):
        return HttpResponseForbidden("Forbidden: producer only.")
    return render(
        request,
        "accounts/producer_home.html",
        {"producer_profile": getattr(request.user, "producer_profile", None)},
    )


@login_required
def admin_home(request):
    if not _has_role(request.user, User.Role.ADMIN):
        return HttpResponseForbidden("Forbidden: admin only.")
    return render(request, "accounts/admin_home.html")

@login_required
def account_page(request):
    user = request.user
    producer_profile = getattr(user, "producer_profile", None)
    customer_profile = getattr(user, "customer_profile", None)
    address = customer_profile.address if customer_profile else None

    if request.method == "POST":
        user_form = UserAccountForm(request.POST, instance=user, prefix="user")
        producer_form = (
            ProducerAccountForm(request.POST, instance=producer_profile, prefix="producer")
            if producer_profile else None
        )
        customer_form = (
            CustomerAccountForm(request.POST, instance=customer_profile, prefix="customer")
            if customer_profile else None
        )
        address_form = (
            AddressForm(request.POST, instance=address, prefix="address")
            if address else None
        )

        forms_valid = user_form.is_valid()
        if producer_form is not None:
            forms_valid = forms_valid and producer_form.is_valid()
        if customer_form is not None:
            forms_valid = forms_valid and customer_form.is_valid()
        if address_form is not None:
            forms_valid = forms_valid and address_form.is_valid()

        if forms_valid:
            with transaction.atomic():
                user = user_form.save(commit=False)
                user.username = user.email
                user.save()

                if producer_form is not None:
                    producer_form.save()
                if customer_form is not None:
                    customer_form.save()
                if address_form is not None:
                    address_form.save()

            messages.success(request, "Account details updated successfully.")
            return redirect("account")
        else:
            messages.error(request, "Please correct the errors below.")

    else:
        user_form = UserAccountForm(instance=user, prefix="user")
        producer_form = (
            ProducerAccountForm(instance=producer_profile, prefix="producer")
            if producer_profile else None
        )
        customer_form = (
            CustomerAccountForm(instance=customer_profile, prefix="customer")
            if customer_profile else None
        )
        address_form = (
            AddressForm(instance=address, prefix="address")
            if address else None
        )

    return render(
        request,
        "accounts/account.html",
        {
            "user_form": user_form,
            "producer_form": producer_form,
            "customer_form": customer_form,
            "address_form": address_form,
        },
    )

def is_verified_business_customer(user):
    return (
        user.is_authenticated
        and getattr(user, "role", None) == User.Role.CUSTOMER
        and hasattr(user, "customer_profile")
        and user.customer_profile.customer_type_id in [
            CustomerProfile.CustomerType.RESTAURANT,
            CustomerProfile.CustomerType.COMMUNITY_GROUP,
        ]
        and user.customer_profile.is_business_verified
    )

def is_restaurant_customer(user):
    return (
        user.is_authenticated
        and getattr(user, "role", None) == User.Role.CUSTOMER
        and hasattr(user, "customer_profile")
        and user.customer_profile.customer_type_id == CustomerProfile.CustomerType.RESTAURANT
    )

def is_community_group_customer(user):
    return (
        user.is_authenticated
        and getattr(user, "role", None) == User.Role.CUSTOMER
        and hasattr(user, "customer_profile")
        and user.customer_profile.customer_type_id == CustomerProfile.CustomerType.COMMUNITY_GROUP
    )