from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import uuid

from .models import Order, OrderItem, OrderStatusHistory
from cart.models import Cart
from payments.models import PaymentRecord


@login_required
def checkout(request):
    """
    TC-007/TC-008: Display checkout page with delivery form.
    Validates 48-hour lead time.
    Only customers can checkout.
    """
    # Only customers can checkout
    if request.user.role != 'CUSTOMER':
        messages.error(request, "Only customers can place orders.")
        if request.user.role == 'PRODUCER':
            return redirect('orders:producer_dashboard')
        return redirect('catalog:product_list')
    
    try:
        cart = Cart.objects.get(user=request.user)
        if not cart.items.exists():
            messages.warning(request, "Your cart is empty.")
            return redirect('cart:view_cart')
    except Cart.DoesNotExist:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:view_cart')
    
    # Get customer address if exists
    customer_address = None
    customer_postcode = None
    if hasattr(request.user, 'customer_profile') and hasattr(request.user.customer_profile, 'address'):
        try:
            address = request.user.customer_profile.address
            customer_address = f"{address.line_1}, {address.city}"
            customer_postcode = address.postcode
        except:
            pass
    
    # Calculate minimum delivery date (48 hours from now)
    min_delivery_date = (timezone.now() + timedelta(hours=48)).date()
    
    # Group items by producer for display
    items_by_producer = cart.get_items_by_producer()
    
    context = {
        'cart': cart,
        'items_by_producer': items_by_producer,
        'total_price': cart.total_price,
        'producer_count': len(items_by_producer),
        'min_delivery_date': min_delivery_date,
        'customer_address': customer_address,
        'customer_postcode': customer_postcode,
    }
    
    return render(request, 'orders/checkout.html', context)


@login_required
@transaction.atomic
def place_order(request):
    """
    TC-007: Single-vendor order
    TC-008: Multi-vendor order
    Creates Order, OrderItems, and PaymentRecords.
    Only customers can place orders.
    """
    # Only customers can place orders
    if request.user.role != 'CUSTOMER':
        return HttpResponseForbidden("Only customers can place orders.")
    
    if request.method != 'POST':
        return redirect('orders:checkout')
    
    try:
        cart = Cart.objects.get(user=request.user)
        if not cart.items.exists():
            messages.error(request, "Your cart is empty.")
            return redirect('cart:view_cart')
    except Cart.DoesNotExist:
        messages.error(request, "Your cart is empty.")
        return redirect('cart:view_cart')
    
    # Get form data
    delivery_address = request.POST.get('delivery_address')
    delivery_postcode = request.POST.get('delivery_postcode')
    delivery_date_str = request.POST.get('delivery_date')
    delivery_instructions = request.POST.get('delivery_instructions', '')
    
    # Validate required fields
    if not all([delivery_address, delivery_postcode, delivery_date_str]):
        messages.error(request, "Please fill in all required fields.")
        return redirect('orders:checkout')
    
    # Parse and validate delivery date
    from datetime import datetime
    try:
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, "Invalid delivery date format.")
        return redirect('orders:checkout')
    
    # Validate 48-hour lead time
    min_delivery = (timezone.now() + timedelta(hours=48)).date()
    if delivery_date < min_delivery:
        messages.error(request, f"Delivery date must be at least 48 hours from now (minimum: {min_delivery}).")
        return redirect('orders:checkout')
    
    # Create the order
    order = Order.objects.create(
        customer=request.user,
        delivery_address=delivery_address,
        delivery_postcode=delivery_postcode,
        delivery_date=delivery_date,
        delivery_instructions=delivery_instructions,
        total_amount=cart.total_price,
        status=Order.Status.PENDING,
    )
    
    # Create order items from cart
    producer_totals = {}  # Track total per producer for payment records
    
    for cart_item in cart.items.select_related('product__producer'):
        # Create order item
        OrderItem.objects.create(
            order=order,
            product=cart_item.product,
            producer=cart_item.product.producer,
            product_name=cart_item.product.name,
            unit_price=cart_item.product.price,
            quantity=cart_item.quantity,
        )
        
        # Track producer totals for payment records
        producer_id = cart_item.product.producer.id
        if producer_id not in producer_totals:
            producer_totals[producer_id] = Decimal('0.00')
        producer_totals[producer_id] += cart_item.subtotal
        
        # Decrement product stock
        cart_item.product.stock_quantity -= cart_item.quantity
        cart_item.product.save()
    
    # Create payment records (one per producer)
    for producer_id, subtotal in producer_totals.items():
        # Generate unique transaction reference
        transaction_ref = f"TXN-{order.order_number}-{uuid.uuid4().hex[:8].upper()}"
        
        PaymentRecord.objects.create(
            order_reference=order.order_number,
            transaction_reference=transaction_ref,
            producer_reference=str(producer_id),
            customer_reference=str(request.user.id),
            gross_amount=subtotal,
            payment_provider="STRIPE_TEST",
            status=PaymentRecord.Status.PENDING,
        )
    
    # Create initial status history
    OrderStatusHistory.objects.create(
        order=order,
        status=Order.Status.PENDING,
        changed_by=request.user,
        notes="Order placed by customer",
    )
    
    # Clear the cart
    cart.items.all().delete()
    
    messages.success(request, f"Order {order.order_number} placed successfully!")
    return redirect('orders:order_confirmation', order_id=order.id)


@login_required
def order_confirmation(request, order_id):
    """
    TC-007/TC-008: Display order confirmation page.
    """
    order = get_object_or_404(Order, id=order_id, customer=request.user)
    items_by_producer = order.get_items_by_producer()
    
    context = {
        'order': order,
        'items_by_producer': items_by_producer,
    }
    
    return render(request, 'orders/order_confirmation.html', context)


@login_required
def producer_dashboard(request):
    """
    TC-009: Producer order dashboard - shows only orders containing their products.
    """
    if request.user.role != 'PRODUCER':
        messages.error(request, "Access denied. Producers only.")
        return redirect('catalog:product_list')
    
    # Get all orders that contain this producer's products
    orders = Order.objects.filter(
        items__producer=request.user
    ).distinct().order_by('-created_at')
    
    # For each order, get only this producer's items
    orders_data = []
    for order in orders:
        producer_items = order.items.filter(producer=request.user)
        producer_subtotal = sum(item.subtotal for item in producer_items)
        
        orders_data.append({
            'order': order,
            'items': producer_items,
            'subtotal': producer_subtotal,
        })
    
    context = {
        'orders_data': orders_data,
    }
    
    return render(request, 'orders/producer_dashboard.html', context)


@login_required
def update_order_status(request, order_id):
    """
    TC-010: Producer updates order status.
    """
    if request.user.role != 'PRODUCER':
        messages.error(request, "Access denied. Producers only.")
        return redirect('catalog:product_list')
    
    order = get_object_or_404(Order, id=order_id)
    
    # Verify producer has items in this order
    if not order.items.filter(producer=request.user).exists():
        messages.error(request, "You don't have items in this order.")
        return redirect('orders:producer_dashboard')
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in dict(Order.Status.choices):
            order.status = new_status
            order.save()
            
            # Record status change
            OrderStatusHistory.objects.create(
                order=order,
                status=new_status,
                changed_by=request.user,
                notes=notes,
            )
            
            messages.success(request, f"Order {order.order_number} status updated to {order.get_status_display()}.")
        else:
            messages.error(request, "Invalid status.")
    
    return redirect('orders:producer_dashboard')


@login_required
def order_history(request):
    """
    TC-021: Customer order history.
    """
    orders = Order.objects.filter(customer=request.user).order_by('-created_at')
    
    context = {
        'orders': orders,
    }
    
    return render(request, 'orders/order_history.html', context)


@login_required
def order_detail(request, order_id):
    """
    TC-021: View specific order details.
    """
    order = get_object_or_404(Order, id=order_id, customer=request.user)
    items_by_producer = order.get_items_by_producer()
    
    context = {
        'order': order,
        'items_by_producer': items_by_producer,
    }
    
    return render(request, 'orders/order_detail.html', context)


@login_required
@transaction.atomic
def reorder(request, order_id):
    """
    TC-021: Copy previous order items to cart.
    """
    order = get_object_or_404(Order, id=order_id, customer=request.user)
    
    # Get or create cart
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    added_count = 0
    unavailable_items = []
    
    for order_item in order.items.all():
        product = order_item.product
        
        # Check if product is still available
        if not product.is_available or product.stock_quantity < order_item.quantity:
            unavailable_items.append(product.name)
            continue
        
        # Add to cart
        from cart.models import CartItem
        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': order_item.quantity}
        )
        
        if not item_created:
            # Update quantity if item already in cart
            cart_item.quantity += order_item.quantity
            if cart_item.quantity > product.stock_quantity:
                cart_item.quantity = product.stock_quantity
            cart_item.save()
        
        added_count += 1
    
    if added_count > 0:
        messages.success(request, f"Added {added_count} items from previous order to cart.")
    
    if unavailable_items:
        messages.warning(request, f"Some items are no longer available: {', '.join(unavailable_items)}")
    
    return redirect('cart:view_cart')