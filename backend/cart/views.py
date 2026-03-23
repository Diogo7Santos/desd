from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from catalog.models import Product
from .models import Cart, CartItem


@login_required
def add_to_cart(request, product_id):
    """
    TC-006: Add product to cart or update quantity if already exists.
    Only customers can add items to cart.
    """
    # Only customers can add to cart
    if request.user.role != 'CUSTOMER':
        messages.error(request, "Only customers can shop and place orders.")
        return redirect('catalog:product_list')
    
    product = get_object_or_404(Product, id=product_id)
    
    # Check product availability
    if not product.is_available:
        messages.error(request, f"{product.name} is currently unavailable.")
        return redirect('catalog:product_detail', product_id=product_id)
    
    # Check stock
    if product.stock_quantity <= 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect('catalog:product_detail', product_id=product_id)
    
    # Get or create cart for user
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    # Get quantity from request (default 1)
    quantity = int(request.POST.get('quantity', 1))
    
    # Validate quantity against stock
    if quantity > product.stock_quantity:
        messages.error(request, f"Only {product.stock_quantity} {product.unit} available.")
        return redirect('catalog:product_detail', product_id=product_id)
    
    # Add or update cart item
    cart_item, item_created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': quantity}
    )
    
    if not item_created:
        # Item already exists, update quantity
        new_quantity = cart_item.quantity + quantity
        if new_quantity > product.stock_quantity:
            messages.error(request, f"Cannot add more. Only {product.stock_quantity} {product.unit} available.")
            return redirect('cart:view_cart')
        cart_item.quantity = new_quantity
        cart_item.save()
        messages.success(request, f"Updated {product.name} quantity to {cart_item.quantity}.")
    else:
        messages.success(request, f"Added {product.name} to cart.")
    
    return redirect('cart:view_cart')


@login_required
def view_cart(request):
    """
    TC-006: Display cart contents grouped by producer.
    TC-008: Show multi-vendor grouping for checkout awareness.
    Only customers can view cart.
    """
    # Only customers can view cart
    if request.user.role != 'CUSTOMER':
        messages.error(request, "Only customers can access the shopping cart.")
        if request.user.role == 'PRODUCER':
            return redirect('orders:producer_dashboard')
        return redirect('catalog:product_list')
    
    try:
        cart = Cart.objects.get(user=request.user)
        items_by_producer = cart.get_items_by_producer()
        total_price = cart.total_price
        total_items = cart.total_items
    except Cart.DoesNotExist:
        items_by_producer = {}
        total_price = 0
        total_items = 0
    
    context = {
        'items_by_producer': items_by_producer,
        'total_price': total_price,
        'total_items': total_items,
        'producer_count': len(items_by_producer),
    }
    
    return render(request, 'cart/cart.html', context)


@login_required
def update_cart_item(request, item_id):
    """
    TC-006: Update quantity of cart item.
    Only customers can update cart items.
    """
    # Only customers can update cart
    if request.user.role != 'CUSTOMER':
        return HttpResponseForbidden("Only customers can modify cart.")
    
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        
        # Validate quantity
        if quantity <= 0:
            messages.error(request, "Quantity must be at least 1.")
            return redirect('cart:view_cart')
        
        if quantity > cart_item.product.stock_quantity:
            messages.error(request, f"Only {cart_item.product.stock_quantity} {cart_item.product.unit} available.")
            return redirect('cart:view_cart')
        
        cart_item.quantity = quantity
        cart_item.save()
        messages.success(request, f"Updated {cart_item.product.name} quantity to {quantity}.")
    
    return redirect('cart:view_cart')


@login_required
def remove_from_cart(request, item_id):
    """
    TC-006: Remove item from cart.
    Only customers can remove cart items.
    """
    # Only customers can remove cart items
    if request.user.role != 'CUSTOMER':
        return HttpResponseForbidden("Only customers can modify cart.")
    
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    product_name = cart_item.product.name
    cart_item.delete()
    messages.success(request, f"Removed {product_name} from cart.")
    
    return redirect('cart:view_cart')


@login_required
def clear_cart(request):
    """
    Optional: Clear entire cart.
    Only customers can clear cart.
    """
    # Only customers can clear cart
    if request.user.role != 'CUSTOMER':
        return HttpResponseForbidden("Only customers can modify cart.")
    
    try:
        cart = Cart.objects.get(user=request.user)
        cart.items.all().delete()
        messages.success(request, "Cart cleared.")
    except Cart.DoesNotExist:
        pass
    
    return redirect('cart:view_cart')