# backend/catalog/views.py

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ProductForm
from .models import Product


def _is_producer(user) -> bool:
    """
    Best-effort producer check that works across common account designs.

    Supported patterns:
    - user.role == "producer"
    - user.is_producer == True
    - user.producerprofile exists (OneToOne)
    """
    if not user or not user.is_authenticated:
        return False

    role = getattr(user, "role", None)
    if isinstance(role, str) and role.lower() == "producer":
        return True

    if getattr(user, "is_producer", False) is True:
        return True

    if hasattr(user, "producerprofile"):
        return True

    return False


def _available_products_qs():
    """TC-004: Only products marked as Available/In Season should be shown to customers."""
    return Product.objects.filter(availability=Product.Availability.AVAILABLE)


# ----------------------------
# Customer-facing views
# ----------------------------

def product_list(request: HttpRequest) -> HttpResponse:
    products = (
        _available_products_qs()
        .select_related("producer")
        .order_by("-created_at")
    )
    context = {
        "products": products,
        "selected_category": None,
        "categories": Product.Category.choices,
    }
    return render(request, "pages/product_list.html", context)


def category_list(request: HttpRequest, category: str) -> HttpResponse:
    valid_categories = {choice[0] for choice in Product.Category.choices}
    if category not in valid_categories:
        raise Http404("Unknown category")

    products = (
        _available_products_qs()
        .filter(category=category)
        .select_related("producer")
        .order_by("-created_at")
    )

    context = {
        "products": products,
        "selected_category": category,
        "categories": Product.Category.choices,
    }
    return render(request, "pages/product_list.html", context)


def product_search(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get("q") or "").strip()
    products = Product.objects.none()

    if query:
        qs = _available_products_qs().select_related("producer")

        producer_name_q = (
            Q(producer__username__icontains=query)
            | Q(producer__first_name__icontains=query)
            | Q(producer__last_name__icontains=query)
        )

        products = (
            qs.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | producer_name_q
            )
            .order_by("-created_at")
            .distinct()
        )

    context = {
        "query": query,
        "products": products,
        "categories": Product.Category.choices,
    }
    return render(request, "pages/search_results.html", context)


def product_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product.objects.select_related("producer"), pk=pk)

    if not product.is_available:
        if not (request.user.is_authenticated and request.user == product.producer):
            raise PermissionDenied("This product is not currently available.")

    return render(request, "pages/product_detail.html", {"product": product})


# ----------------------------
# Producer-facing views
# ----------------------------

@login_required
def product_create(request: HttpRequest) -> HttpResponse:
    if not _is_producer(request.user):
        raise PermissionDenied("Only producers can add products.")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.producer = request.user
            product.save()
            messages.success(request, "Product created successfully.")
            return redirect("catalog:product_detail", pk=product.pk)
        messages.error(request, "Please correct the errors below.")
    else:
        form = ProductForm()

    return render(request, "pages/product_form.html", {"form": form})