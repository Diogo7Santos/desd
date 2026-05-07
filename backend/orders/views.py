import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile, ProducerProfile
from catalog.models import ProductReview
from cart.models import Cart
from payments.models import PaymentRecord
from payments.services import create_checkout_session_for_order

from .models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    RecurringOrder,
    RecurringOrderItem,
    RecurringOrderItemOverride,
    WEEKDAY_CHOICES,
)


logger = logging.getLogger(__name__)


def _safe_customer_profile(user):
    try:
        return user.customer_profile
    except CustomerProfile.DoesNotExist:
        return None


def _safe_producer_profile(user):
    try:
        return user.producer_profile
    except ProducerProfile.DoesNotExist:
        return None


def _is_restaurant_customer(user) -> bool:
    profile = _safe_customer_profile(user)
    return bool(
        profile and profile.customer_type_id == CustomerProfile.CustomerType.RESTAURANT
    )


def _is_community_group_customer(user) -> bool:
    profile = _safe_customer_profile(user)
    return bool(
        profile
        and profile.customer_type_id == CustomerProfile.CustomerType.COMMUNITY_GROUP
    )


def _can_manage_recurring_orders(user) -> bool:
    return user.is_authenticated and user.role == "CUSTOMER" and _is_restaurant_customer(user)


def _build_customer_summary(user):
    profile = _safe_customer_profile(user)
    if not profile:
        return {
            "display_name": user.username,
            "email": user.email,
            "phone": getattr(user, "phone", ""),
            "is_business_customer": False,
            "organisation_name": "",
            "contact_person": "",
            "customer_type_display": "Customer",
            "is_charity_or_education": False,
        }

    is_business = profile.customer_type_id in (
        CustomerProfile.CustomerType.RESTAURANT,
        CustomerProfile.CustomerType.COMMUNITY_GROUP,
    )
    display_name = profile.organisation_name or user.get_full_name() or user.username
    return {
        "display_name": display_name,
        "email": user.email,
        "phone": getattr(user, "phone", ""),
        "is_business_customer": is_business,
        "organisation_name": profile.organisation_name,
        "contact_person": profile.contact_person,
        "customer_type_display": profile.get_customer_type_id_display(),
        "is_charity_or_education": profile.is_charity_or_education,
        "default_delivery_instructions": profile.default_delivery_instructions,
    }


def _build_producer_contact(producer):
    profile = _safe_producer_profile(producer)
    business_name = profile.business_name if profile else producer.username
    contact_name = profile.contact_name if profile else (producer.get_full_name() or producer.username)
    return {
        "producer": producer,
        "business_name": business_name,
        "contact_name": contact_name,
        "email": producer.email,
        "postcode": profile.postcode if profile else "",
    }


def _build_producer_contacts(items_by_producer):
    return [_build_producer_contact(producer) for producer in items_by_producer]


def _is_reviewable_order_item(order_item) -> bool:
    return order_item.status == Order.Status.DELIVERED or order_item.order.status == Order.Status.DELIVERED


def _attach_customer_review_state(items_by_producer, customer):
    product_ids = []
    for data in items_by_producer.values():
        product_ids.extend(item.product_id for item in data["items"])

    review_lookup = {
        review.product_id: review
        for review in ProductReview.objects.filter(customer=customer, product_id__in=product_ids)
    }

    for data in items_by_producer.values():
        for item in data["items"]:
            item.customer_review = review_lookup.get(item.product_id)
            item.can_write_review = _is_reviewable_order_item(item) and item.customer_review is None
            if item.can_write_review:
                item.review_url = reverse(
                    "catalog:create_review",
                    kwargs={"product_id": item.product_id, "order_item_id": item.id},
                )
            elif item.customer_review is not None:
                item.review_url = (
                    reverse("catalog:product_detail", kwargs={"pk": item.product_id})
                    + f"#review-{item.customer_review.id}"
                )
            else:
                item.review_url = ""

    return items_by_producer


def _next_weekday_after(start_date, target_weekday, *, include_today=False):
    days_ahead = (target_weekday - start_date.weekday()) % 7
    if days_ahead == 0 and not include_today:
        days_ahead = 7
    return start_date + timedelta(days=days_ahead)


def _delivery_gap_days(order_weekday, delivery_weekday):
    return (delivery_weekday - order_weekday) % 7


def _calculate_next_recurring_dates(order_weekday, delivery_weekday, *, reference_date=None):
    reference_date = reference_date or timezone.localdate()
    next_order_date = _next_weekday_after(reference_date, order_weekday, include_today=False)
    delivery_gap = _delivery_gap_days(order_weekday, delivery_weekday)
    return next_order_date, next_order_date + timedelta(days=delivery_gap)


def _get_cart_line_items(cart):
    return [
        {"product": cart_item.product, "quantity": cart_item.quantity}
        for cart_item in cart.items.select_related("product__producer")
    ]


def _validate_line_items_for_order(line_items):
    errors = []
    for line_item in line_items:
        product = line_item["product"]
        quantity = line_item["quantity"]
        if not product.is_available:
            errors.append(f"{product.name} is no longer available.")
            continue
        if product.stock_quantity <= 0:
            errors.append(f"{product.name} is out of stock.")
            continue
        if quantity > product.stock_quantity:
            errors.append(
                f"Only {product.stock_quantity} {product.unit} of {product.name} are available."
            )
    return errors


def _create_order_and_payment_records(
    *,
    customer,
    line_items,
    delivery_address,
    delivery_postcode,
    delivery_date,
    delivery_instructions="",
    history_note,
):
    if not line_items:
        raise ValueError("Cannot create an order without line items.")

    total_amount = sum(
        (line_item["product"].price * line_item["quantity"] for line_item in line_items),
        Decimal("0.00"),
    )
    order = Order.objects.create(
        customer=customer,
        delivery_address=delivery_address,
        delivery_postcode=delivery_postcode,
        delivery_date=delivery_date,
        delivery_instructions=delivery_instructions,
        total_amount=total_amount,
        status=Order.Status.PENDING_PAYMENT,
    )

    producer_totals = defaultdict(lambda: Decimal("0.00"))
    for line_item in line_items:
        product = line_item["product"]
        quantity = line_item["quantity"]
        unit_price = product.price

        OrderItem.objects.create(
            order=order,
            product=product,
            producer=product.producer,
            product_name=product.name,
            unit_price=unit_price,
            quantity=quantity,
        )

        producer_totals[product.producer_id] += unit_price * quantity

    for producer_id, subtotal in producer_totals.items():
        transaction_ref = f"TXN-{order.order_number}-{uuid.uuid4().hex[:8].upper()}"
        PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference=transaction_ref,
            producer_reference=str(producer_id),
            customer_reference=str(customer.id),
            gross_amount=subtotal,
            payment_provider="STRIPE_TEST",
            status=PaymentRecord.Status.PENDING,
        )

    OrderStatusHistory.objects.create(
        order=order,
        status=Order.Status.PENDING_PAYMENT,
        changed_by=customer,
        notes=history_note,
    )
    return order


def _parse_recurring_setup(request):
    if request.POST.get("make_recurring") not in ("on", "true", "1"):
        return None

    if not _can_manage_recurring_orders(request.user):
        raise ValueError("Recurring orders are available for restaurant customer accounts only.")

    recurrence_interval = (request.POST.get("recurrence_interval") or "").strip()
    if recurrence_interval not in {
        RecurringOrder.Interval.WEEKLY,
        RecurringOrder.Interval.FORTNIGHTLY,
    }:
        raise ValueError("Please choose a valid recurring order frequency.")

    try:
        order_weekday = int(request.POST.get("order_weekday"))
        delivery_weekday = int(request.POST.get("delivery_weekday"))
    except (TypeError, ValueError):
        raise ValueError("Please choose valid order and delivery weekdays.")

    weekday_values = {value for value, _label in WEEKDAY_CHOICES}
    if order_weekday not in weekday_values or delivery_weekday not in weekday_values:
        raise ValueError("Please choose valid order and delivery weekdays.")

    if _delivery_gap_days(order_weekday, delivery_weekday) < 2:
        raise ValueError("Delivery day must be at least 48 hours after the order day.")

    template_name = (request.POST.get("recurring_name") or "").strip()
    if not template_name:
        template_name = "Weekly Restaurant Order"

    return {
        "template_name": template_name,
        "recurrence_interval": recurrence_interval,
        "order_weekday": order_weekday,
        "delivery_weekday": delivery_weekday,
    }


def _create_recurring_order_from_order(order, recurring_setup):
    next_order_date, next_delivery_date = _calculate_next_recurring_dates(
        recurring_setup["order_weekday"],
        recurring_setup["delivery_weekday"],
    )
    recurring_order = RecurringOrder.objects.create(
        customer=order.customer,
        template_name=recurring_setup["template_name"],
        recurrence_interval=recurring_setup["recurrence_interval"],
        order_weekday=recurring_setup["order_weekday"],
        delivery_weekday=recurring_setup["delivery_weekday"],
        delivery_address=order.delivery_address,
        delivery_postcode=order.delivery_postcode,
        delivery_instructions=order.delivery_instructions,
        next_order_date=next_order_date,
        next_delivery_date=next_delivery_date,
    )
    for order_item in order.items.select_related("product__producer"):
        RecurringOrderItem.objects.create(
            recurring_order=recurring_order,
            product=order_item.product,
            producer=order_item.producer,
            product_name=order_item.product_name,
            unit_price=order_item.unit_price,
            quantity=order_item.quantity,
        )
    return recurring_order


def _roll_forward_recurring_order(recurring_order):
    if recurring_order.status != RecurringOrder.Status.ACTIVE:
        return

    today = timezone.localdate()
    advanced = False
    while recurring_order.next_order_date < today:
        RecurringOrderItemOverride.objects.filter(
            recurring_item__recurring_order=recurring_order,
            scheduled_order_date=recurring_order.next_order_date,
        ).delete()
        recurring_order.next_order_date += timedelta(days=recurring_order.interval_days)
        recurring_order.next_delivery_date += timedelta(days=recurring_order.interval_days)
        advanced = True

    if advanced:
        recurring_order.save(update_fields=["next_order_date", "next_delivery_date", "updated_at"])


def _build_recurring_order_preview(recurring_order):
    overrides = {
        override.recurring_item_id: override
        for override in RecurringOrderItemOverride.objects.filter(
            recurring_item__recurring_order=recurring_order,
            scheduled_order_date=recurring_order.next_order_date,
        )
    }

    items = []
    grouped = defaultdict(lambda: {"items": [], "subtotal": Decimal("0.00")})
    total = Decimal("0.00")
    unavailable_items = []

    for recurring_item in recurring_order.items.select_related("product__producer"):
        override = overrides.get(recurring_item.id)
        quantity = override.quantity if override else recurring_item.quantity
        unit_price = recurring_item.product.price
        subtotal = unit_price * quantity
        preview_item = {
            "id": recurring_item.id,
            "template_item": recurring_item,
            "product": recurring_item.product,
            "product_name": recurring_item.product_name,
            "quantity": quantity,
            "template_quantity": recurring_item.quantity,
            "unit_price": unit_price,
            "subtotal": subtotal,
            "has_override": override is not None,
        }
        items.append(preview_item)
        grouped[recurring_item.product.producer]["items"].append(preview_item)
        grouped[recurring_item.product.producer]["subtotal"] += subtotal
        total += subtotal

        if not recurring_item.product.is_available:
            unavailable_items.append(f"{recurring_item.product_name} is unavailable.")
        elif quantity > recurring_item.product.stock_quantity:
            unavailable_items.append(
                f"{recurring_item.product_name} only has {recurring_item.product.stock_quantity} {recurring_item.product.unit} left."
            )

    return items, dict(grouped), total, unavailable_items


def _advance_recurring_order_schedule(recurring_order):
    current_schedule = recurring_order.next_order_date
    RecurringOrderItemOverride.objects.filter(
        recurring_item__recurring_order=recurring_order,
        scheduled_order_date=current_schedule,
    ).delete()
    recurring_order.next_order_date += timedelta(days=recurring_order.interval_days)
    recurring_order.next_delivery_date += timedelta(days=recurring_order.interval_days)
    recurring_order.save(update_fields=["next_order_date", "next_delivery_date", "updated_at"])


def _recurring_order_queryset_for_user(user):
    return RecurringOrder.objects.filter(customer=user).prefetch_related("items__product__producer")


def _payment_status_for_order(order):
    records = PaymentRecord.objects.filter(order_reference=order.order_number)
    if not records.exists():
        return "UNKNOWN"
    statuses = set(records.values_list("status", flat=True))
    if statuses == {PaymentRecord.Status.PAID}:
        return PaymentRecord.Status.PAID
    if PaymentRecord.Status.FAILED in statuses and PaymentRecord.Status.PAID not in statuses:
        return PaymentRecord.Status.FAILED
    return PaymentRecord.Status.PENDING


@login_required
def checkout(request):
    """
    TC-007/TC-008: Display checkout page with delivery form.
    TC-018: Offer recurring-order setup for restaurant customers.
    """
    if request.user.role != "CUSTOMER":
        messages.error(request, "Only customers can place orders.")
        if request.user.role == "PRODUCER":
            return redirect("orders:producer_dashboard")
        return redirect("catalog:product_list")

    try:
        cart = Cart.objects.get(user=request.user)
        if not cart.items.exists():
            messages.warning(request, "Your cart is empty.")
            return redirect("cart:view_cart")
    except Cart.DoesNotExist:
        messages.warning(request, "Your cart is empty.")
        return redirect("cart:view_cart")

    customer_profile = _safe_customer_profile(request.user)
    customer_address = None
    customer_postcode = None
    default_delivery_instructions = ""
    if customer_profile and hasattr(customer_profile, "address"):
        address = customer_profile.address
        customer_address = f"{address.line_1}, {address.city}"
        customer_postcode = address.postcode
        default_delivery_instructions = customer_profile.default_delivery_instructions

    min_delivery_date = (timezone.now() + timedelta(hours=48)).date()
    items_by_producer = cart.get_items_by_producer()

    context = {
        "cart": cart,
        "items_by_producer": items_by_producer,
        "total_price": cart.total_price,
        "producer_count": len(items_by_producer),
        "min_delivery_date": min_delivery_date,
        "customer_address": customer_address,
        "customer_postcode": customer_postcode,
        "customer_default_delivery_instructions": default_delivery_instructions,
        "can_create_recurring_orders": _can_manage_recurring_orders(request.user),
        "weekday_choices": WEEKDAY_CHOICES,
        "recurrence_choices": RecurringOrder.Interval.choices,
        "is_community_group_order": _is_community_group_customer(request.user),
    }

    return render(request, "orders/checkout.html", context)


@login_required
@transaction.atomic
def place_order(request):
    """
    TC-007: Single-vendor order
    TC-008: Multi-vendor order
    TC-017: Community group bulk checkout
    TC-018: Optional recurring restaurant order template creation
    """
    if request.user.role != "CUSTOMER":
        return HttpResponseForbidden("Only customers can place orders.")

    if request.method != "POST":
        return redirect("orders:checkout")

    try:
        cart = Cart.objects.get(user=request.user)
        if not cart.items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect("cart:view_cart")
    except Cart.DoesNotExist:
        messages.error(request, "Your cart is empty.")
        return redirect("cart:view_cart")

    delivery_address = request.POST.get("delivery_address")
    delivery_postcode = request.POST.get("delivery_postcode")
    delivery_date_str = request.POST.get("delivery_date")
    delivery_instructions = request.POST.get("delivery_instructions", "")

    if not all([delivery_address, delivery_postcode, delivery_date_str]):
        messages.error(request, "Please fill in all required fields.")
        return redirect("orders:checkout")

    try:
        delivery_date = datetime.strptime(delivery_date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Invalid delivery date format.")
        return redirect("orders:checkout")

    min_delivery = (timezone.now() + timedelta(hours=48)).date()
    if delivery_date < min_delivery:
        messages.error(
            request,
            f"Delivery date must be at least 48 hours from now (minimum: {min_delivery}).",
        )
        return redirect("orders:checkout")

    try:
        recurring_setup = _parse_recurring_setup(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("orders:checkout")

    line_items = _get_cart_line_items(cart)
    stock_errors = _validate_line_items_for_order(line_items)
    if stock_errors:
        messages.error(request, stock_errors[0])
        return redirect("orders:checkout")

    order = _create_order_and_payment_records(
        customer=request.user,
        line_items=line_items,
        delivery_address=delivery_address,
        delivery_postcode=delivery_postcode,
        delivery_date=delivery_date,
        delivery_instructions=delivery_instructions,
        history_note="Order placed by customer; awaiting payment",
    )

    success_url = request.build_absolute_uri(f"/orders/confirmation/{order.id}/")
    cancel_url = request.build_absolute_uri("/orders/checkout/")
    try:
        checkout = create_checkout_session_for_order(
            order_reference=order.order_number,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception:
        messages.error(request, "Unable to start payment session. Please try checkout again.")
        return redirect("orders:checkout")

    if recurring_setup:
        try:
            recurring_order = _create_recurring_order_from_order(order, recurring_setup)
        except Exception:
            logger.exception("Recurring order template creation failed for order %s.", order.order_number)
            messages.warning(
                request,
                "Your order was created, but the recurring order template could not be saved.",
            )
        else:
            messages.success(
                request,
                f"Recurring order '{recurring_order.template_name}' created successfully.",
            )

    return redirect(checkout["checkout_url"])


@login_required
def order_confirmation(request, order_id):
    """
    TC-007/TC-008: Display order confirmation page.
    TC-017: Include producer coordination details for community-group orders.
    """
    order = get_object_or_404(Order, id=order_id, customer=request.user)
    items_by_producer = order.get_items_by_producer()

    context = {
        'payment_status': _payment_status_for_order(order),
        "order": order,
        "items_by_producer": items_by_producer,
        "customer_summary": _build_customer_summary(order.customer),
        "producer_contacts": _build_producer_contacts(items_by_producer),
        "show_recurring_orders_link": _can_manage_recurring_orders(request.user),

    }

    return render(request, "orders/order_confirmation.html", context)


@login_required
def producer_dashboard(request):
    """
    TC-009: Producer order dashboard - shows only orders containing their products.
    TC-017: Surface business-contact and delivery details for larger institutional orders.
    """
    if request.user.role != "PRODUCER":
        messages.error(request, "Access denied. Producers only.")
        return redirect("catalog:product_list")

    orders = Order.objects.filter(items__producer=request.user).distinct().order_by("-created_at")

    orders_data = []
    for order in orders:
        producer_items = order.items.filter(producer=request.user)
        producer_subtotal = sum(item.subtotal for item in producer_items)
        orders_data.append(
            {
                "order": order,
                "items": producer_items,
                "subtotal": producer_subtotal,
                "customer_summary": _build_customer_summary(order.customer),
            }
        )

    context = {
        "orders_data": orders_data,
    }

    return render(request, "orders/producer_dashboard.html", context)


@login_required
def update_order_status(request, order_id):
    """
    TC-010: Producer updates order status for their items only.
    In multi-vendor orders, each producer manages their own items independently.
    """
    if request.user.role != "PRODUCER":
        messages.error(request, "Access denied. Producers only.")
        return redirect("catalog:product_list")

    order = get_object_or_404(Order, id=order_id)
    producer_items = order.items.filter(producer=request.user)

    if not producer_items.exists():
        messages.error(request, "You don't have items in this order.")
        return redirect("orders:producer_dashboard")

    if request.method == "POST":
        new_status = request.POST.get("status")
        notes = request.POST.get("notes", "")

        if new_status in dict(Order.Status.choices):
            producer_items.update(status=new_status)
            OrderStatusHistory.objects.create(
                order=order,
                status=new_status,
                changed_by=request.user,
                notes=(
                    f"Producer {request.user.username}: {notes}"
                    if notes
                    else f"Producer {request.user.username} updated their items to {new_status}"
                ),
            )
            _update_overall_order_status(order)
            messages.success(
                request,
                f"Your items in order {order.order_number} updated to {Order.Status(new_status).label}.",
            )
        else:
            messages.error(request, "Invalid status.")

    return redirect("orders:producer_dashboard")


def _update_overall_order_status(order):
    item_statuses = order.items.values_list("status", flat=True)

    if not item_statuses:
        return

    status_priority = {
        Order.Status.PENDING: 1,
        Order.Status.CONFIRMED: 2,
        Order.Status.READY: 3,
        Order.Status.DELIVERED: 4,
        Order.Status.CANCELLED: 5,
    }

    min_status = min(item_statuses, key=lambda status: status_priority.get(status, 0))

    if all(status == Order.Status.DELIVERED for status in item_statuses):
        order.status = Order.Status.DELIVERED
    elif Order.Status.CANCELLED in item_statuses:
        if all(status == Order.Status.CANCELLED for status in item_statuses):
            order.status = Order.Status.CANCELLED
        else:
            order.status = min_status
    else:
        order.status = min_status

    order.save()


@login_required
def order_history(request):
    """
    TC-021: Customer order history.
    """
    orders = (
        Order.objects.filter(customer=request.user)
        .exclude(status=Order.Status.PENDING_PAYMENT)
        .order_by('-created_at')
    )
    
    orders_data = []
    for order in orders:
        orders_data.append(
            {
                "order": order,
                "payment_status": _payment_status_for_order(order),
            }
        )

    context = {
        'orders_data': orders_data,
    }

    return render(request, "orders/order_history.html", context)


@login_required
def order_detail(request, order_id):
    """
    TC-021: View specific order details.
    """
    order = get_object_or_404(
        Order.objects.exclude(status=Order.Status.PENDING_PAYMENT),
        id=order_id,
        customer=request.user,
    )
    items_by_producer = order.get_items_by_producer()
    items_by_producer = _attach_customer_review_state(items_by_producer, request.user)

    context = {
        'order': order,
        'items_by_producer': items_by_producer,
        'payment_status': _payment_status_for_order(order),
    }

    return render(request, "orders/order_detail.html", context)


@login_required
@transaction.atomic
def reorder(request, order_id):
    """
    TC-021: Copy previous order items to cart.
    """
    order = get_object_or_404(
        Order.objects.exclude(status=Order.Status.PENDING_PAYMENT),
        id=order_id,
        customer=request.user,
    )
    
    # Get or create cart
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    added_count = 0
    unavailable_items = []

    for order_item in order.items.all():
        product = order_item.product

        if not product.is_available or product.stock_quantity < order_item.quantity:
            unavailable_items.append(product.name)
            continue

        from cart.models import CartItem

        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={"quantity": order_item.quantity},
        )

        if not item_created:
            cart_item.quantity += order_item.quantity
            if cart_item.quantity > product.stock_quantity:
                cart_item.quantity = product.stock_quantity
            cart_item.save()

        added_count += 1

    if added_count > 0:
        messages.success(request, f"Added {added_count} items from previous order to cart.")

    if unavailable_items:
        messages.warning(
            request,
            f"Some items are no longer available: {', '.join(unavailable_items)}",
        )

    return redirect("cart:view_cart")


@login_required
def recurring_orders(request):
    if not _can_manage_recurring_orders(request.user):
        return HttpResponseForbidden("Recurring orders are available for restaurant customer accounts only.")

    recurring_orders_qs = _recurring_order_queryset_for_user(request.user)
    recurring_orders_data = []
    for recurring_order in recurring_orders_qs:
        _roll_forward_recurring_order(recurring_order)
        items, items_by_producer, total, unavailable_items = _build_recurring_order_preview(recurring_order)
        recurring_orders_data.append(
            {
                "recurring_order": recurring_order,
                "items": items,
                "items_by_producer": items_by_producer,
                "total": total,
                "unavailable_items": unavailable_items,
                "producer_contacts": _build_producer_contacts(items_by_producer),
            }
        )

    return render(
        request,
        "orders/recurring_orders.html",
        {"recurring_orders_data": recurring_orders_data},
    )


@login_required
def recurring_order_detail(request, recurring_order_id):
    if not _can_manage_recurring_orders(request.user):
        return HttpResponseForbidden("Recurring orders are available for restaurant customer accounts only.")

    recurring_order = get_object_or_404(
        _recurring_order_queryset_for_user(request.user),
        id=recurring_order_id,
    )
    _roll_forward_recurring_order(recurring_order)
    items, items_by_producer, total, unavailable_items = _build_recurring_order_preview(recurring_order)

    context = {
        "recurring_order": recurring_order,
        "items": items,
        "items_by_producer": items_by_producer,
        "total": total,
        "unavailable_items": unavailable_items,
        "producer_contacts": _build_producer_contacts(items_by_producer),
    }
    return render(request, "orders/recurring_order_detail.html", context)


@login_required
@transaction.atomic
def update_recurring_order(request, recurring_order_id):
    if not _can_manage_recurring_orders(request.user):
        return HttpResponseForbidden("Recurring orders are available for restaurant customer accounts only.")

    recurring_order = get_object_or_404(
        _recurring_order_queryset_for_user(request.user),
        id=recurring_order_id,
    )
    if request.method != "POST":
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    if recurring_order.status == RecurringOrder.Status.CANCELLED:
        messages.error(request, "Cancelled recurring orders can no longer be edited.")
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    _roll_forward_recurring_order(recurring_order)

    template_name = (request.POST.get("template_name") or recurring_order.template_name).strip()
    if template_name != recurring_order.template_name:
        recurring_order.template_name = template_name
        recurring_order.save(update_fields=["template_name", "updated_at"])

    for recurring_item in recurring_order.items.all():
        raw_value = request.POST.get(f"quantity_{recurring_item.id}")
        if raw_value is None:
            continue
        try:
            quantity = int(raw_value)
        except ValueError:
            messages.error(request, "All next-order quantities must be whole numbers.")
            return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)
        if quantity < 1:
            messages.error(request, "Next-order quantities must be at least 1.")
            return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

        if quantity == recurring_item.quantity:
            RecurringOrderItemOverride.objects.filter(
                recurring_item=recurring_item,
                scheduled_order_date=recurring_order.next_order_date,
            ).delete()
        else:
            RecurringOrderItemOverride.objects.update_or_create(
                recurring_item=recurring_item,
                scheduled_order_date=recurring_order.next_order_date,
                defaults={"quantity": quantity},
            )

    messages.success(request, "Next scheduled order updated without changing the base template.")
    return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)


@login_required
@transaction.atomic
def update_recurring_order_status(request, recurring_order_id):
    if not _can_manage_recurring_orders(request.user):
        return HttpResponseForbidden("Recurring orders are available for restaurant customer accounts only.")

    recurring_order = get_object_or_404(
        _recurring_order_queryset_for_user(request.user),
        id=recurring_order_id,
    )
    if request.method != "POST":
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    new_status = request.POST.get("status")
    if new_status not in dict(RecurringOrder.Status.choices):
        messages.error(request, "Invalid recurring order status.")
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    recurring_order.status = new_status
    recurring_order.save(update_fields=["status", "updated_at"])
    if recurring_order.status == RecurringOrder.Status.ACTIVE:
        _roll_forward_recurring_order(recurring_order)

    messages.success(
        request,
        f"Recurring order marked as {RecurringOrder.Status(new_status).label}.",
    )
    return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)


@login_required
@transaction.atomic
def checkout_recurring_order(request, recurring_order_id):
    if not _can_manage_recurring_orders(request.user):
        return HttpResponseForbidden("Recurring orders are available for restaurant customer accounts only.")

    recurring_order = get_object_or_404(
        _recurring_order_queryset_for_user(request.user),
        id=recurring_order_id,
    )
    if request.method != "POST":
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    if recurring_order.status != RecurringOrder.Status.ACTIVE:
        messages.error(request, "Only active recurring orders can be checked out.")
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    _roll_forward_recurring_order(recurring_order)
    preview_items, _items_by_producer, _total, unavailable_items = _build_recurring_order_preview(recurring_order)
    if unavailable_items:
        messages.error(
            request,
            "This recurring order needs attention before checkout: "
            + "; ".join(unavailable_items),
        )
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    line_items = [
        {"product": preview_item["product"], "quantity": preview_item["quantity"]}
        for preview_item in preview_items
    ]
    order = _create_order_and_payment_records(
        customer=request.user,
        line_items=line_items,
        delivery_address=recurring_order.delivery_address,
        delivery_postcode=recurring_order.delivery_postcode,
        delivery_date=recurring_order.next_delivery_date,
        delivery_instructions=recurring_order.delivery_instructions,
        history_note=(
            f"Recurring order '{recurring_order.template_name or recurring_order.id}' generated; awaiting payment"
        ),
    )

    success_url = request.build_absolute_uri(f"/orders/confirmation/{order.id}/")
    cancel_url = request.build_absolute_uri(
        f"/orders/recurring/{recurring_order.id}/"
    )
    try:
        checkout = create_checkout_session_for_order(
            order_reference=order.order_number,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except Exception:
        messages.error(request, "Unable to start payment session for this recurring order.")
        return redirect("orders:recurring_order_detail", recurring_order_id=recurring_order.id)

    _advance_recurring_order_schedule(recurring_order)
    messages.success(
        request,
        "Recurring order prepared for checkout. The next scheduled cycle has been advanced.",
    )
    return redirect(checkout["checkout_url"])
