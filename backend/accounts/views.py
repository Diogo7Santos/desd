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
        return redirect("producer_home")
    return redirect("customer_home")


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
            address = Address.objects.create(
                user=user,
                line_1=form.cleaned_data["line_1"],
                line_2=form.cleaned_data.get("line_2", ""),
                city=form.cleaned_data["city"],
                postcode=form.cleaned_data["customer_postcode"],
            )

            CustomerProfile.objects.create(
                user=user,
                customer_type_id=int(form.cleaned_data["customer_type_id"]),
                address=address,
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
    return redirect("login")


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