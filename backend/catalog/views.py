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
    - user.role == "producer" / "PRODUCER"
    - user.is_producer == True
    - user.producerprofile exists
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
    """
    Customer-facing queryset:
    only products currently marked as AVAILABLE are shown publicly.
    """
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
def producer_products(request: HttpRequest) -> HttpResponse:
    """
    Producer dashboard page:
    shows only products owned by the logged-in producer.
    """
    if not _is_producer(request.user):
        raise PermissionDenied("Only producers can manage products.")

    products = (
        Product.objects.filter(producer=request.user)
        .select_related("producer")
        .order_by("-created_at")
    )

    return render(
        request,
        "pages/producer_products.html",
        {"products": products},
    )


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
            return redirect("catalog:producer_products")
        messages.error(request, "Please correct the errors below.")
    else:
        form = ProductForm()

    context = {
        "form": form,
        "form_title": "Add New Product",
        "form_subtitle": "Create a new listing for customers to browse and purchase.",
        "submit_label": "Save Product",
        "cancel_url": "catalog:producer_products",
    }
    return render(request, "pages/product_form.html", context)


@login_required
def product_update(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Producer can edit only their own products.
    Supports TC-011, TC-015, and TC-016 by allowing updates to:
    - stock_quantity
    - allergens
    - availability
    - and all other product details
    """
    if not _is_producer(request.user):
        raise PermissionDenied("Only producers can edit products.")

    product = get_object_or_404(Product, pk=pk)

    if product.producer != request.user:
        raise PermissionDenied("You can only edit your own products.")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated successfully.")
            return redirect("catalog:producer_products")
        messages.error(request, "Please correct the errors below.")
    else:
        form = ProductForm(instance=product)

    context = {
        "form": form,
        "product": product,
        "form_title": "Edit Product",
        "form_subtitle": "Update stock, allergens, seasonal availability, and other product details.",
        "submit_label": "Update Product",
        "cancel_url": "catalog:producer_products",
    }
    return render(request, "pages/product_form.html", context)