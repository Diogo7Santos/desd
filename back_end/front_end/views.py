from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .models import Product, Category


def home(request):
    featured_products = Product.objects.filter(is_available=True)[:8]
    categories = Category.objects.all()

    return render(
        request,
        "front_end/home.html",
        {
            "featured_products": featured_products,
            "categories": categories,
        },
    )


def login_view(request):
    """
    Basic login view:
    - Supports ?next= redirect
    - Optional 'remember_me' checkbox (session expires on browser close if unchecked)
    - Shows a generic error message for invalid credentials
    """
    next_url = request.GET.get("next") or request.POST.get("next")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        remember_me = request.POST.get("remember_me")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # If "remember me" is not checked, expire session when browser closes.
            if not remember_me:
                request.session.set_expiry(0)

            return redirect(next_url or "dashboard")

        messages.error(request, "Invalid username or password")

    return render(request, "front_end/login.html", {"next": next_url})


@login_required
def dashboard(request):
    """
    Simple dashboard page.

    This template expects:
    - role: 'customer' / 'producer' / 'admin'
    - recent_orders: optional list (only used for customers)
    """
    # Default role (safe)
    role = "customer"

    # If you're using Django staff/superuser as "admin"
    if request.user.is_superuser or request.user.is_staff:
        role = "admin"

    # If you have a Producer profile attached to the User, treat as producer
    # (Adjust attribute name to match your actual models)
    if hasattr(request.user, "producerprofile"):
        role = "producer"

    context = {
        "role": role,
        # Leave empty for now unless you have an Order model and want to show recent orders
        "recent_orders": [],
    }

    return render(request, "front_end/dashboard.html", context)


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("home")


def error_page(request, error_title="Error", error_message="An unexpected error occurred.", error_code=None):
    """
    Generic error page renderer. Useful for permission errors, invalid links, etc.
    """
    return render(
        request,
        "front_end/error.html",
        {
            "error_title": error_title,
            "error_message": error_message,
            "error_code": error_code,
        },
        status=400,
    )
