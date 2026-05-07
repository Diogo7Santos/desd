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


def _producer_filter_options():
    """
    Producer dropdown options for the customer-facing catalog filter.
    Only includes producers who currently have available products.
    """
    return (
        _available_products_qs()
        .select_related("producer")
        .values("producer__id", "producer__username")
        .distinct()
        .order_by("producer__username")
    )


def _apply_catalog_filters(request: HttpRequest, products):
    """
    Applies customer-facing catalog filters:
    - search query
    - minimum price
    - maximum price
    - selected producer
    - organic certification status
    """
    search_query = (request.GET.get("q") or "").strip()
    min_price = (request.GET.get("min_price") or "").strip()
    max_price = (request.GET.get("max_price") or "").strip()
    selected_producer = (request.GET.get("producer") or "").strip()
    selected_organic = (request.GET.get("organic_status") or "").strip()

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(producer__username__icontains=search_query)
            | Q(producer__first_name__icontains=search_query)
            | Q(producer__last_name__icontains=search_query)
        )

    if min_price:
        products = products.filter(price__gte=min_price)

    if max_price:
        products = products.filter(price__lte=max_price)

    if selected_producer:
        products = products.filter(producer_id=selected_producer)

    if selected_organic:
        products = products.filter(organic_status=selected_organic)

    filter_context = {
        "search_query": search_query,
        "min_price": min_price,
        "max_price": max_price,
        "selected_producer": selected_producer,
        "selected_organic": selected_organic,
    }

    return products, filter_context


# Customer-facing views

def product_list(request: HttpRequest) -> HttpResponse:
    products = (
        _available_products_qs()
        .select_related("producer")
        .order_by("-created_at")
    )

    products, filter_context = _apply_catalog_filters(request, products)

    context = {
        "products": products,
        "selected_category": None,
        "categories": Product.Category.choices,
        "producers": _producer_filter_options(),
        **filter_context,
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

    products, filter_context = _apply_catalog_filters(request, products)

    context = {
        "products": products,
        "selected_category": category,
        "categories": Product.Category.choices,
        "producers": _producer_filter_options(),
        **filter_context,
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


# Producer-facing views

@login_required
def producer_products(request: HttpRequest) -> HttpResponse:
    """
    Producer dashboard page:
    shows only products owned by the logged-in producer.

    TC-023:
    also generates low stock alerts for products where stock is at or below
    the producer-defined low_stock_threshold.
    """
    if not _is_producer(request.user):
        raise PermissionDenied("Only producers can manage products.")

    products = (
        Product.objects.filter(producer=request.user)
        .select_related("producer")
        .order_by("-created_at")
    )

    low_stock_products = [
        product for product in products
        if product.is_low_stock or product.is_out_of_stock
    ]

    return render(
        request,
        "pages/producer_products.html",
        {
            "products": products,
            "low_stock_products": low_stock_products,
        },
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
    Supports TC-011, TC-015, TC-016, and TC-023 by allowing updates to:
    - stock_quantity
    - low_stock_threshold
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
        "form_subtitle": "Update stock, low stock threshold, allergens, seasonal availability, and other product details.",
        "submit_label": "Update Product",
        "cancel_url": "catalog:producer_products",
    }
    return render(request, "pages/product_form.html", context)