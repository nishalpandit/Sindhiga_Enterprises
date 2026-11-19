import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Avg, Count

from .models import (
    CustomUser, AuthToken, CustomerAddress,
    ProductCategory, ProductSubCategory, Product, ProductImage,
    Cart, Wishlist, Coupon, ProductOrder, OrderItem, ReturnRequest, ProductReview
)

def _auth_user(request):
    """Robust helper for mobile Bearer token, header, param, and session auth."""
    auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
    token_key = None
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() in ['bearer', 'token']:
            token_key = parts[1]
        elif len(parts) == 1:
            token_key = parts[0]

    if not token_key:
        token_key = request.GET.get('token') or request.POST.get('token')
    
    if not token_key and request.body:
        try:
            body_json = json.loads(request.body.decode('utf-8'))
            token_key = body_json.get('token')
        except Exception:
            pass

    if token_key:
        token_obj = AuthToken.objects.filter(key=token_key).select_related('user').first()
        if token_obj and token_obj.user.is_active:
            return token_obj.user

    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        return request.user
    return None


def _get_payload(request):
    """Extracts payload regardless of JSON, multipart form data, or URL-encoded."""
    data = {}
    content_type = (request.content_type or '').lower()
    if 'application/json' in content_type:
        try:
            if request.body:
                data = json.loads(request.body.decode('utf-8'))
        except Exception:
            pass
    if not data:
        data = {k: v for k, v in request.POST.items()}
    if not data and request.method == 'GET':
        data = {k: v for k, v in request.GET.items()}
    return data


# =====================================================================
# PRODUCT CATALOG APIS
# =====================================================================

def categories_list_api(request):
    """List all active product categories and subcategories with product counts."""
    categories = ProductCategory.objects.filter(status='active').order_by('order', 'name')
    result = []
    for cat in categories:
        subs = cat.subcategories.filter(status='active').order_by('order', 'name')
        sub_list = []
        for s in subs:
            p_count = Product.objects.filter(subcategory=s, status='active').count()
            sub_list.append({
                'id': s.id,
                'name': s.name,
                'slug': s.slug,
                'image': s.image.url if s.image else None,
                'products_count': p_count
            })
        cat_p_count = Product.objects.filter(category=cat, status='active').count()
        result.append({
            'id': cat.id,
            'name': cat.name,
            'slug': cat.slug,
            'description': cat.description,
            'icon_class': cat.icon_class,
            'image': cat.image.url if cat.image else None,
            'products_count': cat_p_count,
            'subcategories': sub_list
        })
    return JsonResponse({'status': 'success', 'categories': result})


def products_list_api(request):
    """
    Filterable & searchable products list.
    Query params:
    - category_id: int
    - subcategory_id: int
    - search: string
    - brand: string
    - min_price, max_price: float
    - sort: 'price_low_high', 'price_high_low', 'rating', 'newest'
    """
    qs = Product.objects.filter(status='active')
    
    cat_id = request.GET.get('category_id')
    if cat_id:
        qs = qs.filter(category_id=cat_id)
        
    sub_id = request.GET.get('subcategory_id')
    if sub_id:
        qs = qs.filter(subcategory_id=sub_id)
        
    search = request.GET.get('search')
    if search:
        qs = qs.filter(
            Q(title__icontains=search) |
            Q(brand__icontains=search) |
            Q(description__icontains=search) |
            Q(sku__icontains=search)
        )
        
    brand = request.GET.get('brand')
    if brand:
        qs = qs.filter(brand__iexact=brand)
        
    min_p = request.GET.get('min_price')
    if min_p:
        try:
            qs = qs.filter(sale_price__gte=Decimal(min_p))
        except Exception:
            pass
            
    max_p = request.GET.get('max_price')
    if max_p:
        try:
            qs = qs.filter(sale_price__lte=Decimal(max_p))
        except Exception:
            pass
            
    sort = request.GET.get('sort', 'newest')
    if sort == 'price_low_high':
        qs = qs.order_by('sale_price')
    elif sort == 'price_high_low':
        qs = qs.order_by('-sale_price')
    elif sort == 'rating':
        qs = qs.order_by('-rating', '-reviews_count')
    else:
        qs = qs.order_by('-created_at')

    products = []
    for p in qs:
        img_url = p.image.url if p.image else (p.image_url or '')
        products.append({
            'id': p.id,
            'title': p.title,
            'brand': p.brand or '',
            'category_id': p.category_id,
            'category_name': p.category.name if p.category else '',
            'subcategory_id': p.subcategory_id,
            'subcategory_name': p.subcategory.name if p.subcategory else '',
            'mrp_price': float(p.mrp_price),
            'sale_price': float(p.sale_price),
            'discount_percent': p.discount_percent,
            'unit': p.unit,
            'stock_quantity': p.stock_quantity,
            'in_stock': p.in_stock,
            'rating': float(p.rating),
            'reviews_count': p.reviews_count,
            'image': img_url,
            'sku': p.sku or '',
            'is_featured': p.is_featured
        })

    return JsonResponse({
        'status': 'success',
        'count': len(products),
        'products': products
    })


def product_detail_api(request, product_id):
    """Detailed view for a single product including specifications, gallery, and reviews."""
    try:
        p = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

    primary_img = p.image.url if p.image else (p.image_url or '')
    gallery = [img.image.url for img in p.gallery_images.all()]
    if primary_img and primary_img not in gallery:
        gallery.insert(0, primary_img)

    reviews = []
    for r in p.reviews.all()[:10]:
        reviews.append({
            'id': r.id,
            'customer_name': r.customer.get_full_name() or r.customer.username,
            'rating': r.rating,
            'review_text': r.review_text or '',
            'created_at': r.created_at.strftime('%Y-%m-%d')
        })

    # Related products in same subcategory
    related_qs = Product.objects.filter(subcategory=p.subcategory, status='active').exclude(id=p.id)[:4]
    related = []
    for rel in related_qs:
        rel_img = rel.image.url if rel.image else (rel.image_url or '')
        related.append({
            'id': rel.id,
            'title': rel.title,
            'sale_price': float(rel.sale_price),
            'mrp_price': float(rel.mrp_price),
            'discount_percent': rel.discount_percent,
            'image': rel_img,
            'rating': float(rel.rating)
        })

    return JsonResponse({
        'status': 'success',
        'product': {
            'id': p.id,
            'title': p.title,
            'brand': p.brand or '',
            'category_id': p.category_id,
            'category_name': p.category.name if p.category else '',
            'subcategory_id': p.subcategory_id,
            'subcategory_name': p.subcategory.name if p.subcategory else '',
            'mrp_price': float(p.mrp_price),
            'sale_price': float(p.sale_price),
            'discount_percent': p.discount_percent,
            'unit': p.unit,
            'stock_quantity': p.stock_quantity,
            'in_stock': p.in_stock,
            'rating': float(p.rating),
            'reviews_count': p.reviews_count,
            'description': p.description or '',
            'specifications': p.specifications or {},
            'sku': p.sku or '',
            'image': primary_img,
            'gallery': gallery,
            'reviews': reviews,
            'related_products': related
        }
    })


# =====================================================================
# CART & WISHLIST APIS
# =====================================================================

@csrf_exempt
def cart_get_api(request):
    """View customer's cart with subtotal calculation."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    items = Cart.objects.filter(user=user).select_related('product')
    item_list = []
    subtotal = Decimal('0.00')

    for item in items:
        p = item.product
        item_total = p.sale_price * item.quantity
        subtotal += item_total
        img = p.image.url if p.image else (p.image_url or '')
        item_list.append({
            'cart_item_id': item.id,
            'product_id': p.id,
            'title': p.title,
            'brand': p.brand or '',
            'unit': p.unit,
            'unit_price': float(p.sale_price),
            'mrp_price': float(p.mrp_price),
            'quantity': item.quantity,
            'stock_quantity': p.stock_quantity,
            'in_stock': p.in_stock,
            'total_price': float(item_total),
            'image': img
        })

    delivery_fee = Decimal('0.00') if subtotal >= Decimal('499.00') or subtotal == 0 else Decimal('40.00')
    grand_total = subtotal + delivery_fee

    return JsonResponse({
        'status': 'success',
        'items': item_list,
        'item_count': sum(i['quantity'] for i in item_list),
        'subtotal': float(subtotal),
        'delivery_fee': float(delivery_fee),
        'free_delivery_threshold': 499.00,
        'grand_total': float(grand_total)
    })


@csrf_exempt
def cart_add_api(request):
    """Add a product to cart or increment quantity."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    data = _get_payload(request)
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 1))

    if not product_id or quantity <= 0:
        return JsonResponse({'status': 'error', 'message': 'Valid product_id and quantity required'}, status=400)

    try:
        product = Product.objects.get(id=product_id, status='active')
    except Product.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Product not found or unavailable'}, status=404)

    if product.stock_quantity < quantity:
        return JsonResponse({'status': 'error', 'message': f'Only {product.stock_quantity} units available in stock'}, status=400)

    cart_item, created = Cart.objects.get_or_create(user=user, product=product, defaults={'quantity': quantity})
    if not created:
        new_qty = cart_item.quantity + quantity
        if new_qty > product.stock_quantity:
            return JsonResponse({'status': 'error', 'message': f'Cannot add more. Stock limit: {product.stock_quantity}'}, status=400)
        cart_item.quantity = new_qty
        cart_item.save()

    return JsonResponse({
        'status': 'success',
        'message': f'Added {product.title} to cart',
        'cart_item_id': cart_item.id,
        'current_quantity': cart_item.quantity
    })


@csrf_exempt
def cart_update_api(request):
    """Update quantity of a specific cart item."""
    if request.method not in ['POST', 'PUT']:
        return JsonResponse({'status': 'error', 'message': 'POST/PUT method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    data = _get_payload(request)
    product_id = data.get('product_id')
    cart_item_id = data.get('cart_item_id')
    quantity = int(data.get('quantity', 1))

    item = None
    if cart_item_id:
        item = Cart.objects.filter(id=cart_item_id, user=user).first()
    elif product_id:
        item = Cart.objects.filter(product_id=product_id, user=user).first()

    if not item:
        return JsonResponse({'status': 'error', 'message': 'Cart item not found'}, status=404)

    if quantity <= 0:
        item.delete()
        return JsonResponse({'status': 'success', 'message': 'Item removed from cart', 'removed': True})

    if quantity > item.product.stock_quantity:
        return JsonResponse({'status': 'error', 'message': f'Only {item.product.stock_quantity} units available'}, status=400)

    item.quantity = quantity
    item.save()
    return JsonResponse({
        'status': 'success',
        'message': 'Quantity updated',
        'cart_item_id': item.id,
        'quantity': item.quantity,
        'total_price': float(item.total_price)
    })


@csrf_exempt
def cart_remove_api(request):
    """Remove a product from cart."""
    if request.method not in ['POST', 'DELETE']:
        return JsonResponse({'status': 'error', 'message': 'POST/DELETE method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    data = _get_payload(request)
    product_id = data.get('product_id')
    cart_item_id = data.get('cart_item_id')

    if cart_item_id:
        Cart.objects.filter(id=cart_item_id, user=user).delete()
    elif product_id:
        Cart.objects.filter(product_id=product_id, user=user).delete()
    else:
        return JsonResponse({'status': 'error', 'message': 'cart_item_id or product_id required'}, status=400)

    return JsonResponse({'status': 'success', 'message': 'Item removed from cart'})


@csrf_exempt
def cart_clear_api(request):
    """Clear all items from customer's cart."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    Cart.objects.filter(user=user).delete()
    return JsonResponse({'status': 'success', 'message': 'Cart emptied successfully'})


@csrf_exempt
def wishlist_toggle_api(request):
    """Toggle a product in customer's wishlist."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    data = _get_payload(request)
    product_id = data.get('product_id')
    if not product_id:
        return JsonResponse({'status': 'error', 'message': 'product_id required'}, status=400)

    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

    item = Wishlist.objects.filter(user=user, product=product).first()
    if item:
        item.delete()
        return JsonResponse({'status': 'success', 'is_in_wishlist': False, 'message': 'Removed from wishlist'})
    else:
        Wishlist.objects.create(user=user, product=product)
        return JsonResponse({'status': 'success', 'is_in_wishlist': True, 'message': 'Added to wishlist'})


def wishlist_list_api(request):
    """View customer's wishlist items."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    items = Wishlist.objects.filter(user=user).select_related('product')
    results = []
    for item in items:
        p = item.product
        img = p.image.url if p.image else (p.image_url or '')
        results.append({
            'wishlist_id': item.id,
            'product_id': p.id,
            'title': p.title,
            'brand': p.brand or '',
            'sale_price': float(p.sale_price),
            'mrp_price': float(p.mrp_price),
            'discount_percent': p.discount_percent,
            'in_stock': p.in_stock,
            'image': img
        })
    return JsonResponse({'status': 'success', 'wishlist': results})


# =====================================================================
# COUPONS & OFFERS
# =====================================================================

def coupons_list_api(request):
    """List all available active promotional coupons."""
    now = timezone.now()
    coupons = Coupon.objects.filter(
        is_active=True
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=now)
    )
    result = []
    for c in coupons:
        result.append({
            'code': c.code,
            'description': c.description or '',
            'discount_type': c.discount_type,
            'discount_value': float(c.discount_value),
            'min_order_amount': float(c.min_order_amount),
            'max_discount_amount': float(c.max_discount_amount) if c.max_discount_amount else None,
            'valid_until': c.valid_until.strftime('%Y-%m-%d %H:%M') if c.valid_until else 'No expiry'
        })
    return JsonResponse({'status': 'success', 'coupons': result})


@csrf_exempt
def coupon_apply_api(request):
    """Validate and compute discount for a promo code."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    data = _get_payload(request)
    code = data.get('code', '').strip().upper()
    try:
        amount = Decimal(str(data.get('order_amount', '0')))
    except Exception:
        amount = Decimal('0.00')

    coupon = Coupon.objects.filter(code__iexact=code).first()
    if not coupon:
        return JsonResponse({'status': 'error', 'message': 'Invalid coupon code.'}, status=400)

    valid, reason = coupon.is_valid_for_amount(amount)
    if not valid:
        return JsonResponse({'status': 'error', 'message': reason}, status=400)

    discount = coupon.calculate_discount(amount)
    final_amount = max(Decimal('0.00'), amount - Decimal(str(discount)))

    return JsonResponse({
        'status': 'success',
        'code': coupon.code,
        'discount_type': coupon.discount_type,
        'discount_amount': float(discount),
        'original_amount': float(amount),
        'final_amount': float(final_amount),
        'message': f"Coupon '{coupon.code}' applied successfully!"
    })


# =====================================================================
# CHECKOUT & ORDER MANAGEMENT APIS
# =====================================================================

@csrf_exempt
@transaction.atomic
def checkout_order_api(request):
    """
    Places an e-commerce order from items in user's cart.
    Parameters:
    - address_id: int (or shipping details directly)
    - payment_method: 'COD' or 'ONLINE' (default 'COD')
    - coupon_code: string (optional)
    - delivery_notes: string (optional)
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    cart_items = Cart.objects.filter(user=user).select_related('product')
    if not cart_items.exists():
        return JsonResponse({'status': 'error', 'message': 'Your cart is empty.'}, status=400)

    data = _get_payload(request)
    address_id = data.get('address_id')
    address_obj = None

    if address_id:
        address_obj = CustomerAddress.objects.filter(id=address_id, user=user).first()
        if not address_obj:
            return JsonResponse({'status': 'error', 'message': 'Selected shipping address not found.'}, status=404)
    else:
        # Check default address
        address_obj = CustomerAddress.objects.filter(user=user, is_default=True).first() or CustomerAddress.objects.filter(user=user).first()

    customer_name = data.get('customer_name') or user.get_full_name() or user.username
    customer_phone = data.get('customer_phone') or getattr(user, 'phone_number', '') or '9876543210'

    if address_obj:
        addr_text = f"{address_obj.address_line_1}, {address_obj.address_line_2 or ''}".strip(', ')
        city = address_obj.city or 'Ranchi'
        state = address_obj.state or 'Jharkhand'
        pincode = address_obj.pincode or '834001'
    else:
        addr_text = data.get('address_text', 'Standard Delivery Address')
        city = data.get('city', 'Ranchi')
        state = data.get('state', 'Jharkhand')
        pincode = data.get('pincode', '834001')

    # Verify inventory stock
    subtotal = Decimal('0.00')
    for item in cart_items:
        if item.quantity > item.product.stock_quantity:
            return JsonResponse({
                'status': 'error',
                'message': f"Insufficient stock for '{item.product.title}'. Only {item.product.stock_quantity} left."
            }, status=400)
        subtotal += item.product.sale_price * item.quantity

    # Coupon validation
    coupon_code = data.get('coupon_code', '').strip().upper()
    coupon_obj = None
    coupon_discount = Decimal('0.00')
    if coupon_code:
        coupon = Coupon.objects.filter(code__iexact=coupon_code).first()
        if coupon:
            valid, _ = coupon.is_valid_for_amount(subtotal)
            if valid:
                coupon_obj = coupon
                coupon_discount = Decimal(str(coupon.calculate_discount(subtotal)))
                coupon.usage_count += 1
                coupon.save(update_fields=['usage_count'])

    # Delivery fee
    delivery_fee = Decimal('0.00') if subtotal >= Decimal('499.00') else Decimal('40.00')
    total_amount = max(Decimal('0.00'), subtotal - coupon_discount + delivery_fee)

    payment_method = data.get('payment_method', 'COD').upper()
    if payment_method not in ['COD', 'ONLINE']:
        payment_method = 'COD'

    # Create Order
    order = ProductOrder.objects.create(
        customer=user,
        shipping_address=address_obj,
        customer_name=customer_name,
        customer_phone=customer_phone,
        delivery_address_text=addr_text,
        delivery_city=city,
        delivery_state=state,
        delivery_pincode=pincode,
        items_subtotal=subtotal,
        coupon=coupon_obj,
        coupon_discount=coupon_discount,
        delivery_fee=delivery_fee,
        total_amount=total_amount,
        payment_method=payment_method,
        payment_status='PAID' if payment_method == 'ONLINE' else 'PENDING',
        order_status='PENDING',
        delivery_notes=data.get('delivery_notes', '')
    )

    # Create line items and deduct stock
    for item in cart_items:
        p = item.product
        img = p.image.url if p.image else (p.image_url or '')
        OrderItem.objects.create(
            order=order,
            product=p,
            product_title=p.title,
            product_image=img,
            unit_price=p.sale_price,
            quantity=item.quantity,
            total_price=p.sale_price * item.quantity
        )
        p.stock_quantity -= item.quantity
        if p.stock_quantity <= 0:
            p.status = 'out_of_stock'
        p.save(update_fields=['stock_quantity', 'status'])

    # Empty Cart
    cart_items.delete()

    return JsonResponse({
        'status': 'success',
        'message': 'Order placed successfully!',
        'order_id': order.id,
        'order_number': order.order_number,
        'delivery_otp': order.delivery_otp,
        'total_amount': float(order.total_amount),
        'payment_method': order.payment_method,
        'payment_status': order.payment_status,
        'order_status': order.order_status,
        'created_at': order.created_at.strftime('%Y-%m-%d %H:%M')
    })


def orders_list_api(request):
    """List customer orders with status filter."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    qs = ProductOrder.objects.filter(customer=user)
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(order_status__iexact=status_filter)

    orders = []
    for o in qs:
        item_count = o.items.count()
        first_item = o.items.first()
        orders.append({
            'order_id': o.id,
            'order_number': o.order_number,
            'order_status': o.order_status,
            'status_display': o.get_order_status_display(),
            'total_amount': float(o.total_amount),
            'item_count': item_count,
            'first_item_title': first_item.product_title if first_item else '',
            'first_item_image': first_item.product_image if first_item else '',
            'payment_method': o.payment_method,
            'payment_status': o.payment_status,
            'delivery_otp': o.delivery_otp,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return JsonResponse({'status': 'success', 'orders': orders})


def order_detail_api(request, order_id):
    """Comprehensive details for a single order, tracking timeline, and delivery partner."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        if str(order_id).isdigit():
            order = ProductOrder.objects.get(id=int(order_id), customer=user)
        else:
            order = ProductOrder.objects.get(order_number=order_id, customer=user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    items = []
    for it in order.items.all():
        items.append({
            'id': it.id,
            'product_id': it.product_id,
            'product_title': it.product_title,
            'product_image': it.product_image or '',
            'unit_price': float(it.unit_price),
            'quantity': it.quantity,
            'total_price': float(it.total_price)
        })

    partner_info = None
    if order.delivery_partner:
        dp = getattr(order.delivery_partner, 'delivery_profile', None)
        partner_info = {
            'name': order.delivery_partner.get_full_name() or order.delivery_partner.username,
            'phone': dp.phone_number if dp else '',
            'vehicle': f"{dp.vehicle_type} ({dp.vehicle_number})" if dp and dp.vehicle_number else 'Delivery Executive',
            'rating': float(dp.rating) if dp else 5.0
        }

    timeline = [
        {'step': 'Placed', 'status': 'PENDING', 'done': True, 'timestamp': order.created_at.strftime('%Y-%m-%d %H:%M')},
        {'step': 'Confirmed', 'status': 'CONFIRMED', 'done': order.confirmed_at is not None, 'timestamp': order.confirmed_at.strftime('%Y-%m-%d %H:%M') if order.confirmed_at else None},
        {'step': 'Packed', 'status': 'PACKED', 'done': order.packed_at is not None, 'timestamp': order.packed_at.strftime('%Y-%m-%d %H:%M') if order.packed_at else None},
        {'step': 'Picked Up', 'status': 'PICKED_UP', 'done': order.picked_up_at is not None, 'timestamp': order.picked_up_at.strftime('%Y-%m-%d %H:%M') if order.picked_up_at else None},
        {'step': 'Out for Delivery', 'status': 'OUT_FOR_DELIVERY', 'done': order.order_status in ['OUT_FOR_DELIVERY', 'DELIVERED'], 'timestamp': None},
        {'step': 'Delivered', 'status': 'DELIVERED', 'done': order.delivered_at is not None, 'timestamp': order.delivered_at.strftime('%Y-%m-%d %H:%M') if order.delivered_at else None},
    ]

    return JsonResponse({
        'status': 'success',
        'order': {
            'order_id': order.id,
            'order_number': order.order_number,
            'order_status': order.order_status,
            'status_display': order.get_order_status_display(),
            'delivery_otp': order.delivery_otp,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': f"{order.delivery_address_text}, {order.delivery_city}, {order.delivery_state} - {order.delivery_pincode}",
            'items_subtotal': float(order.items_subtotal),
            'coupon_discount': float(order.coupon_discount),
            'delivery_fee': float(order.delivery_fee),
            'total_amount': float(order.total_amount),
            'payment_method': order.payment_method,
            'payment_status': order.payment_status,
            'items': items,
            'delivery_partner': partner_info,
            'timeline': timeline,
            'can_cancel': order.order_status in ['PENDING', 'CONFIRMED'],
            'can_return': order.order_status == 'DELIVERED',
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M')
        }
    })


@csrf_exempt
def order_cancel_api(request, order_id):
    """Customer cancels order if still in PENDING or CONFIRMED status."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        order = ProductOrder.objects.get(id=order_id, customer=user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    if order.order_status not in ['PENDING', 'CONFIRMED']:
        return JsonResponse({'status': 'error', 'message': f'Cannot cancel order in {order.order_status} stage.'}, status=400)

    data = _get_payload(request)
    order.order_status = 'CANCELLED'
    order.cancellation_reason = data.get('reason', 'Cancelled by customer')
    order.save(update_fields=['order_status', 'cancellation_reason'])

    # Restore inventory stock
    for it in order.items.all():
        if it.product:
            it.product.stock_quantity += it.quantity
            if it.product.status == 'out_of_stock' and it.product.stock_quantity > 0:
                it.product.status = 'active'
            it.product.save(update_fields=['stock_quantity', 'status'])

    return JsonResponse({'status': 'success', 'message': 'Order cancelled successfully and stock restored.'})


@csrf_exempt
def order_return_api(request, order_id):
    """Customer requests return/refund for a DELIVERED order."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        order = ProductOrder.objects.get(id=order_id, customer=user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    if order.order_status != 'DELIVERED':
        return JsonResponse({'status': 'error', 'message': 'Return requests can only be made for delivered orders.'}, status=400)

    data = _get_payload(request)
    reason = data.get('reason', '').strip()
    if not reason:
        return JsonResponse({'status': 'error', 'message': 'Please provide a reason for return.'}, status=400)

    ret, created = ReturnRequest.objects.get_or_create(
        order=order,
        customer=user,
        defaults={
            'reason': reason,
            'refund_amount': order.total_amount,
            'status': 'REQUESTED'
        }
    )
    order.order_status = 'RETURN_REQUESTED'
    order.save(update_fields=['order_status'])

    return JsonResponse({
        'status': 'success',
        'message': 'Return request submitted successfully. Our team will review and schedule pickup.',
        'return_id': ret.id
    })


@csrf_exempt
def product_review_add_api(request, product_id):
    """Customer adds a rating and review for a purchased product."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

    data = _get_payload(request)
    try:
        rating = int(data.get('rating', 5))
        rating = max(1, min(5, rating))
    except Exception:
        rating = 5
    review_text = data.get('review_text', '').strip()

    review, _ = ProductReview.objects.update_or_create(
        product=product,
        customer=user,
        defaults={
            'rating': rating,
            'review_text': review_text
        }
    )

    # Recompute aggregate rating
    agg = product.reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    product.rating = Decimal(str(round(agg['avg'] or 5.0, 1)))
    product.reviews_count = agg['count'] or 1
    product.save(update_fields=['rating', 'reviews_count'])

    return JsonResponse({
        'status': 'success',
        'message': 'Review submitted successfully',
        'new_rating': float(product.rating),
        'reviews_count': product.reviews_count
    })
