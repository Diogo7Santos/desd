from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from .models import ProducerProfile, CustomerProfile, Address

from .web_forms import LoginForm, RegisterForm

User = get_user_model()


def _has_role(user, role: str) -> bool:
    # Admin can be represented via role OR Django staff/superuser flags
    if role == User.Role.ADMIN:
        return user.is_staff or user.is_superuser or getattr(user, "role", None) == User.Role.ADMIN
    return getattr(user, "role", None) == role


def _redirect_by_user_role(user):
    if _has_role(user, User.Role.ADMIN):
        return redirect("admin_home")
    if _has_role(user, User.Role.PRODUCER):
        return redirect("producer_home")
    return redirect("customer_home")


def login_page(request):
    if request.user.is_authenticated:
        return _redirect_by_user_role(request.user)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            selected_role = form.cleaned_data["role"]

            user = authenticate(request, username=username, password=password)
            if user is None:
                messages.error(request, "Invalid username or password.")
            else:
                # Enforce role selection matches actual account role (FR2-style gate)
                if not _has_role(user, selected_role):
                    messages.error(request, "Role does not match this account.")
                else:
                    login(request, user)
                    return _redirect_by_user_role(user)
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def register_page(request):
    if request.user.is_authenticated:
        return _redirect_by_user_role(request.user)

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            email = form.cleaned_data["email"].lower()
            role = form.cleaned_data["role"]
            password = form.cleaned_data["password1"]
            phone = form.cleaned_data.get("phone", "")

            if User.objects.filter(username=username).exists():
                form.add_error("username", "Username already taken.")
            elif User.objects.filter(email=email).exists():
                form.add_error("email", "Email already registered.")
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                )
                user.role = role
                user.phone = phone

                if role == User.Role.ADMIN:
                    if not settings.DEBUG:
                        return HttpResponseForbidden("Admin registration is disabled.")
                    user.is_staff = True
                    user.is_superuser = True

                user.save()

                if role == User.Role.PRODUCER:
                    ProducerProfile.objects.create(
                        user=user,
                        business_name=form.cleaned_data["business_name"],
                        contact_name=form.cleaned_data["contact_name"],
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
                return _redirect_by_user_role(user)
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})

@login_required
def logout_page(request):
    logout(request)
    return redirect("login")


@login_required
def customer_home(request):
    if not _has_role(request.user, User.Role.CUSTOMER):
        return HttpResponseForbidden("Forbidden: customer only.")
    return render(request, "accounts/customer_home.html")


@login_required
def producer_home(request):
    if not _has_role(request.user, User.Role.PRODUCER):
        return HttpResponseForbidden("Forbidden: producer only.")
    return render(request, "accounts/producer_home.html")


@login_required
def admin_home(request):
    if not _has_role(request.user, User.Role.ADMIN):
        return HttpResponseForbidden("Forbidden: admin only.")
    return render(request, "accounts/admin_home.html")