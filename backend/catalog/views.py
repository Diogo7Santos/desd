# backend/catalog/views.py

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Avg, Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .food_miles import food_miles_for_product
from .forms import ProductForm, ProductReviewForm
from .models import Product, ProductReview


def _is_producer(user) -> bool:
    """
    Best-effort producer check that works across common account designs.

    Supported patterns:
    - user.role == "producer" / "PRODUCER"
    - user.is_producer == True
    - user.producerprofile / user.producer_profile exists
    """
    if not user or not user.is_authenticated:
        return False

    role = getattr(user, "role", None)
    if isinstance(role, str) and role.lower() == "producer":
        return True

    if getattr(user, "is_producer", False) is True:
        return True

    if hasattr(user, "producerprofile") or hasattr(user, "producer_profile"):
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


def _customer_postcode_for_user(user) -> str:
    if not user or not user.is_authenticated or getattr(user, "role", None) != "CUSTOMER":
        return ""

    try:
        customer_profile = user.customer_profile
        address = customer_profile.address
    except ObjectDoesNotExist:
        return ""

    return getattr(address, "postcode", "")


def _attach_food_miles(products, customer_postcode: str):
    products = list(products)
    for product in products:
        product.food_miles = food_miles_for_product(product, customer_postcode)
    return products


def _customer_has_purchased_product(user, product) -> bool:
    if not user or not user.is_authenticated or getattr(user, "role", None) != "CUSTOMER":
        return False

    from orders.models import OrderItem

    return OrderItem.objects.filter(order__customer=user, product=product).exists()


def _is_review_eligible_order_item(order_item) -> bool:
    return order_item.status == "DELIVERED" or order_item.order.status == "DELIVERED"


def _eligible_review_order_item(user, product):
    if not user or not user.is_authenticated or getattr(user, "role", None) != "CUSTOMER":
        return None

    from orders.models import Order, OrderItem

    return (
        OrderItem.objects.select_related("order")
        .filter(order__customer=user, product=product)
        .filter(Q(status=Order.Status.DELIVERED) | Q(order__status=Order.Status.DELIVERED))
        .order_by("-order__delivery_date", "-order__created_at", "-id")
        .first()
    )


def _visible_reviews_for_product(product):
    return ProductReview.objects.filter(product=product, is_visible=True).select_related(
        "customer",
        "order_item__order",
    )


def _review_redirect_url(product, *, anchor="reviews") -> str:
    url = reverse("catalog:product_detail", kwargs={"pk": product.pk})
    return f"{url}#{anchor}" if anchor else url


def _product_review_context(product, user):
    reviews_qs = _visible_reviews_for_product(product)
    review_summary = reviews_qs.aggregate(
        average_rating=Avg("rating"),
        review_count=Count("id"),
    )
    average_rating = review_summary["average_rating"]
    review_count = review_summary["review_count"] or 0

    customer_review = None
    eligible_order_item = None
    if user.is_authenticated and getattr(user, "role", None) == "CUSTOMER":
        customer_review = ProductReview.objects.filter(product=product, customer=user).first()
        if customer_review is None:
            eligible_order_item = _eligible_review_order_item(user, product)

    return {
        "product_reviews": list(reviews_qs),
        "review_count": review_count,
        "average_rating": average_rating,
        "average_rating_display": f"{average_rating:.1f}" if average_rating is not None else None,
        "customer_review": customer_review,
        "eligible_review_order_item": eligible_order_item,
        "can_write_review": eligible_order_item is not None and customer_review is None,
        "can_respond_to_reviews": user.is_authenticated and user == product.producer,
    }


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


# ----------------------------
# Customer-facing views
# ----------------------------

def product_list(request: HttpRequest) -> HttpResponse:
    products = (
        _available_products_qs()
        .select_related("producer", "producer__producer_profile")
        .order_by("-created_at")
    )

    products, filter_context = _apply_catalog_filters(request, products)
    products = _attach_food_miles(products, _customer_postcode_for_user(request.user))

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
        .select_related("producer", "producer__producer_profile")
        .order_by("-created_at")
    )

    products, filter_context = _apply_catalog_filters(request, products)
    products = _attach_food_miles(products, _customer_postcode_for_user(request.user))

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
        qs = _available_products_qs().select_related("producer", "producer__producer_profile")

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

    products = _attach_food_miles(products, _customer_postcode_for_user(request.user))

    context = {
        "query": query,
        "products": products,
        "categories": Product.Category.choices,
    }
    return render(request, "pages/search_results.html", context)


def product_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(
        Product.objects.select_related("producer", "producer__producer_profile"),
        pk=pk,
    )

    if not product.is_available:
        if not (
            request.user.is_authenticated
            and (
                request.user == product.producer
                or _customer_has_purchased_product(request.user, product)
            )
        ):
            raise PermissionDenied("This product is not currently available.")

    food_miles = food_miles_for_product(product, _customer_postcode_for_user(request.user))
    review_context = _product_review_context(product, request.user)

    return render(
        request,
        "pages/product_detail.html",
        {"product": product, "food_miles": food_miles, **review_context},
    )


@login_required
def create_review(request: HttpRequest, product_id: int, order_item_id: int) -> HttpResponse:
    if getattr(request.user, "role", None) != "CUSTOMER":
        raise PermissionDenied("Only customers can write product reviews.")

    from orders.models import OrderItem

    product = get_object_or_404(Product, pk=product_id)
    order_item = get_object_or_404(
        OrderItem.objects.select_related("order", "product"),
        pk=order_item_id,
    )

    if order_item.order.customer_id != request.user.id or order_item.product_id != product.id:
        raise PermissionDenied("This review link does not match your delivered purchase.")

    if not _is_review_eligible_order_item(order_item):
        messages.error(request, "You can review this product after it has been delivered.")
        return redirect("orders:order_detail", order_id=order_item.order_id)

    existing_review = ProductReview.objects.filter(product=product, customer=request.user).first()
    if existing_review is not None:
        messages.info(request, "You have already reviewed this product.")
        return redirect(_review_redirect_url(product, anchor=f"review-{existing_review.id}"))

    if request.method == "POST":
        form = ProductReviewForm(
            request.POST,
            customer=request.user,
            product=product,
            order_item=order_item,
        )
        if form.is_valid():
            review = form.save()
            messages.success(request, "Thanks for sharing your review.")
            return redirect(_review_redirect_url(product, anchor=f"review-{review.id}"))
        messages.error(request, "Please correct the errors below.")
    else:
        form = ProductReviewForm(
            customer=request.user,
            product=product,
            order_item=order_item,
        )

    context = {
        "form": form,
        "product": product,
        "order_item": order_item,
        "order": order_item.order,
    }
    return render(request, "pages/review_form.html", context)


@login_required
def respond_to_review(request: HttpRequest, review_id: int) -> HttpResponse:
    if not _is_producer(request.user):
        raise PermissionDenied("Only producers can respond to reviews.")

    review = get_object_or_404(
        ProductReview.objects.select_related("product__producer"),
        pk=review_id,
    )
    if review.product.producer_id != request.user.id:
        raise PermissionDenied("You can only respond to reviews on your own products.")

    if request.method != "POST":
        return redirect(_review_redirect_url(review.product, anchor=f"review-{review.id}"))

    producer_response = (request.POST.get("producer_response") or "").strip()
    if not producer_response:
        messages.error(request, "Please enter a response before submitting.")
        return redirect(_review_redirect_url(review.product, anchor=f"review-{review.id}"))

    review.producer_response = producer_response
    review.responded_at = timezone.now()
    review.save(update_fields=["producer_response", "responded_at", "updated_at"])
    messages.success(request, "Review response saved.")
    return redirect(_review_redirect_url(review.product, anchor=f"review-{review.id}"))


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
