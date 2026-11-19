import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse

from .models import (
    CustomUser, UserProfile, CustomerAddress,
    ProductCategory, ProductSubCategory, Product, ProductOrder, OrderItem, Coupon, ReturnRequest,
    Category, SubCategory, QuickService, VendorProfile, ServiceBooking, ServiceTimeSlot,
    DeliveryPartnerProfile, DeliveryPayout, PayoutRequest
)


def super_admin_check(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff or getattr(user, 'role', '') == 'ADMIN')


# =====================================================================
# 4.A. DASHBOARD
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_dashboard(request):
    """
    Section 4.A: Dashboard
    4 Core Platform KPIs: Total Customers, Total Orders, Total Service Bookings, Total Revenue.
    Plus operational queues for pending orders & unassigned bookings.
    """
    total_customers = CustomUser.objects.filter(role__in=['CUSTOMER', 'USER']).count()
    total_orders = ProductOrder.objects.count()
    total_service_bookings = ServiceBooking.objects.count()

    ecom_revenue = ProductOrder.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')
    services_revenue = ServiceBooking.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')
    total_revenue = ecom_revenue + services_revenue

    # Operational metrics
    total_providers = CustomUser.objects.filter(role__in=['SERVICE_PROVIDER', 'VENDOR']).count()
    total_riders = DeliveryPartnerProfile.objects.count()
    pending_orders_count = ProductOrder.objects.filter(order_status='PENDING').count()
    packed_orders_count = ProductOrder.objects.filter(order_status='PACKED').count()
    unassigned_bookings_count = ServiceBooking.objects.filter(status='pending').count()

    recent_orders = ProductOrder.objects.select_related('customer', 'delivery_partner').order_by('-created_at')[:8]
    recent_bookings = ServiceBooking.objects.select_related('customer', 'vendor').order_by('-created_at')[:8]

    context = {
        'total_customers': total_customers,
        'total_orders': total_orders,
        'total_service_bookings': total_service_bookings,
        'total_revenue': total_revenue,
        'ecom_revenue': ecom_revenue,
        'services_revenue': services_revenue,
        'total_vendors': total_providers,
        'total_delivery_partners': total_riders,
        'pending_orders_count': pending_orders_count,
        'packed_orders_count': packed_orders_count,
        'unassigned_bookings_count': unassigned_bookings_count,
        'recent_orders': recent_orders,
        'recent_bookings': recent_bookings,
    }
    return render(request, 'superadmin/dashboard.html', context)


# =====================================================================
# 4.B. CUSTOMER MANAGEMENT
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_customers(request):
    """
    Section 4.B: Customer Management - List customers with search, filter, and block/unblock.
    """
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    customers_qs = CustomUser.objects.filter(role__in=['CUSTOMER', 'USER']).select_related('user_profile').order_by('-date_joined')

    if q:
        customers_qs = customers_qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(user_profile__phone_number__icontains=q)
        )

    if status_filter == 'active':
        customers_qs = customers_qs.filter(is_active=True)
    elif status_filter == 'blocked':
        customers_qs = customers_qs.filter(is_active=False)

    paginator = Paginator(customers_qs, 15)
    page_number = request.GET.get('page')
    customers = paginator.get_page(page_number)

    return render(request, 'superadmin/customers.html', {
        'customers': customers,
        'q': q,
        'status_filter': status_filter,
        'total_count': customers_qs.count()
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_customer_detail(request, user_id):
    """
    Section 4.B: View Customer Details, Addresses, Order History, Booking History.
    """
    customer = get_object_or_404(CustomUser.objects.select_related('user_profile'), pk=user_id, role__in=['CUSTOMER', 'USER'])
    addresses = CustomerAddress.objects.filter(user=customer)
    orders = ProductOrder.objects.filter(customer=customer).order_by('-created_at')[:10]
    bookings = ServiceBooking.objects.filter(customer=customer).order_by('-created_at')[:10]

    return render(request, 'superadmin/customer_detail.html', {
        'customer': customer,
        'addresses': addresses,
        'orders': orders,
        'bookings': bookings
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_customer_toggle(request, user_id):
    """
    Section 4.B: Block / Unblock Users.
    """
    customer = get_object_or_404(CustomUser, pk=user_id, role__in=['CUSTOMER', 'USER'])
    customer.is_active = not customer.is_active
    customer.save()
    action = "unblocked" if customer.is_active else "blocked"
    messages.success(request, f"Customer {customer.username} has been {action}.")
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('super_admin_customers')))


# =====================================================================
# 4.C. E-COMMERCE MANAGEMENT
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_categories(request):
    """
    Section 4.C: Category & Subcategory Management.
    """
    categories = ProductCategory.objects.prefetch_related('subcategories').annotate(
        product_count=Count('products')
    ).order_by('name')

    return render(request, 'superadmin/ecom_categories.html', {
        'categories': categories
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip() or name.lower().replace(' ', '-')
        description = request.POST.get('description', '').strip()
        icon = request.POST.get('icon', 'fa-box').strip()
        is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')

        if not name:
            messages.error(request, 'Category name is required.')
            return redirect('super_admin_ecom_categories')

        ProductCategory.objects.create(
            name=name, slug=slug, description=description,
            icon=icon, is_active=is_active, image=image
        )
        messages.success(request, f'Product category "{name}" created successfully.')
        return redirect('super_admin_ecom_categories')

    return render(request, 'superadmin/ecom_category_form.html', {'mode': 'create'})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_category_edit(request, cat_id):
    cat = get_object_or_404(ProductCategory, pk=cat_id)
    if request.method == 'POST':
        cat.name = request.POST.get('name', cat.name).strip()
        cat.slug = request.POST.get('slug', cat.slug).strip()
        cat.description = request.POST.get('description', cat.description).strip()
        cat.icon = request.POST.get('icon', cat.icon).strip()
        cat.is_active = request.POST.get('is_active') == 'on'
        if 'image' in request.FILES:
            cat.image = request.FILES['image']
        cat.save()
        messages.success(request, f'Category "{cat.name}" updated successfully.')
        return redirect('super_admin_ecom_categories')

    return render(request, 'superadmin/ecom_category_form.html', {'mode': 'edit', 'category': cat})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_category_delete(request, cat_id):
    cat = get_object_or_404(ProductCategory, pk=cat_id)
    name = cat.name
    cat.delete()
    messages.success(request, f'Category "{name}" deleted.')
    return redirect('super_admin_ecom_categories')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_products(request):
    """
    Section 4.C: Product Management & Inventory Management.
    """
    q = request.GET.get('q', '').strip()
    cat_id = request.GET.get('category', '').strip()
    stock_status = request.GET.get('stock', '').strip()

    products_qs = Product.objects.select_related('category', 'subcategory').order_by('-created_at')

    if q:
        products_qs = products_qs.filter(
            Q(title__icontains=q) |
            Q(sku__icontains=q) |
            Q(brand__icontains=q)
        )
    if cat_id:
        products_qs = products_qs.filter(category_id=cat_id)

    if stock_status == 'out':
        products_qs = products_qs.filter(stock_quantity__lte=0)
    elif stock_status == 'low':
        products_qs = products_qs.filter(stock_quantity__gt=0, stock_quantity__lte=10)
    elif stock_status == 'in_stock':
        products_qs = products_qs.filter(stock_quantity__gt=10)

    categories = ProductCategory.objects.all().order_by('name')

    paginator = Paginator(products_qs, 15)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    return render(request, 'superadmin/ecom_products.html', {
        'products': products,
        'categories': categories,
        'q': q,
        'selected_category': cat_id,
        'stock_status': stock_status,
        'total_count': products_qs.count()
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_product_create(request):
    categories = ProductCategory.objects.all().order_by('name')
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        cat_id = request.POST.get('category')
        price = Decimal(request.POST.get('price', '0'))
        mrp = Decimal(request.POST.get('mrp', '0') or price)
        stock_quantity = int(request.POST.get('stock_quantity', '0'))
        sku = request.POST.get('sku', '').strip() or f"SKU-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        brand = request.POST.get('brand', 'Sindhiga').strip()
        short_description = request.POST.get('short_description', '').strip()
        description = request.POST.get('description', '').strip()
        is_available = request.POST.get('is_available') == 'on'
        main_image = request.FILES.get('main_image')

        category = get_object_or_404(ProductCategory, pk=cat_id) if cat_id else None

        prod = Product.objects.create(
            title=title, category=category, price=price, mrp=mrp,
            stock_quantity=stock_quantity, sku=sku, brand=brand,
            short_description=short_description, description=description,
            is_available=is_available, main_image=main_image
        )
        messages.success(request, f'Product "{prod.title}" added to inventory.')
        return redirect('super_admin_ecom_products')

    return render(request, 'superadmin/ecom_product_form.html', {'mode': 'create', 'categories': categories})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_product_edit(request, product_id):
    prod = get_object_or_404(Product, pk=product_id)
    categories = ProductCategory.objects.all().order_by('name')
    if request.method == 'POST':
        prod.title = request.POST.get('title', prod.title).strip()
        cat_id = request.POST.get('category')
        if cat_id:
            prod.category_id = cat_id
        prod.price = Decimal(request.POST.get('price', prod.price))
        prod.mrp = Decimal(request.POST.get('mrp', prod.mrp))
        prod.stock_quantity = int(request.POST.get('stock_quantity', prod.stock_quantity))
        prod.sku = request.POST.get('sku', prod.sku).strip()
        prod.brand = request.POST.get('brand', prod.brand).strip()
        prod.short_description = request.POST.get('short_description', prod.short_description).strip()
        prod.description = request.POST.get('description', prod.description).strip()
        prod.is_available = request.POST.get('is_available') == 'on'
        if 'main_image' in request.FILES:
            prod.main_image = request.FILES['main_image']
        prod.save()
        messages.success(request, f'Product "{prod.title}" updated.')
        return redirect('super_admin_ecom_products')

    return render(request, 'superadmin/ecom_product_form.html', {'mode': 'edit', 'product': prod, 'categories': categories})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_product_delete(request, product_id):
    prod = get_object_or_404(Product, pk=product_id)
    title = prod.title
    prod.delete()
    messages.success(request, f'Product "{title}" deleted from catalog.')
    return redirect('super_admin_ecom_products')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_orders(request):
    """
    Section 4.C: Order Management.
    """
    status_filter = request.GET.get('status', '').strip()
    q = request.GET.get('q', '').strip()

    orders_qs = ProductOrder.objects.select_related('customer', 'delivery_partner').order_by('-created_at')

    if status_filter:
        orders_qs = orders_qs.filter(order_status=status_filter)
    if q:
        orders_qs = orders_qs.filter(
            Q(order_number__icontains=q) |
            Q(customer_name__icontains=q) |
            Q(customer_phone__icontains=q)
        )

    paginator = Paginator(orders_qs, 15)
    page_number = request.GET.get('page')
    orders = paginator.get_page(page_number)

    return render(request, 'superadmin/ecom_orders.html', {
        'orders': orders,
        'status_filter': status_filter,
        'q': q,
        'total_count': orders_qs.count()
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_order_detail(request, order_id):
    """
    Section 4.C: Order Detail with Packing & Delivery Assignment actions.
    """
    order = get_object_or_404(ProductOrder.objects.select_related('customer', 'delivery_partner'), pk=order_id)
    items = order.items.select_related('product')
    available_riders = DeliveryPartnerProfile.objects.select_related('user').filter(user__is_active=True, is_verified=True)

    return render(request, 'superadmin/ecom_order_detail.html', {
        'order': order,
        'items': items,
        'available_riders': available_riders
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_order_pack(request, order_id):
    """
    Mark an order as PACKED and ready for delivery partner assignment.
    """
    order = get_object_or_404(ProductOrder, pk=order_id)
    order.order_status = 'PACKED'
    order.packed_at = timezone.now()
    order.save()
    messages.success(request, f"Order #{order.order_number} marked as PACKED.")
    return redirect('super_admin_ecom_order_detail', order_id=order.id)


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_coupons(request):
    """
    Section 4.C: Coupon & Offer Management.
    """
    coupons = Coupon.objects.all().order_by('-id')
    return render(request, 'superadmin/ecom_coupons.html', {'coupons': coupons})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_coupon_create(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        discount_type = request.POST.get('discount_type', 'percentage')
        discount_value = Decimal(request.POST.get('discount_value', '0'))
        min_order_amount = Decimal(request.POST.get('min_order_value', '0'))
        valid_until = request.POST.get('valid_to')
        is_active = request.POST.get('is_active') == 'on'

        if not code or not discount_value:
            messages.error(request, 'Coupon code and discount value are required.')
            return redirect('super_admin_ecom_coupons')

        Coupon.objects.create(
            code=code, discount_type=discount_type, discount_value=discount_value,
            min_order_amount=min_order_amount,
            valid_until=valid_until if valid_until else timezone.now() + timezone.timedelta(days=30),
            is_active=is_active
        )
        messages.success(request, f'Coupon "{code}" created successfully.')
        return redirect('super_admin_ecom_coupons')

    return render(request, 'superadmin/ecom_coupon_form.html', {'mode': 'create'})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_returns(request):
    """
    Section 4.C: Return & Refund Management.
    """
    returns_qs = ReturnRequest.objects.select_related('order', 'customer').order_by('-created_at')
    return render(request, 'superadmin/ecom_returns.html', {'returns': returns_qs})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_ecom_return_action(request, return_id, action):
    ret = get_object_or_404(ReturnRequest, pk=return_id)
    if action == 'approve':
        ret.status = 'APPROVED'
        messages.success(request, f"Return request #{ret.id} approved.")
    elif action == 'reject':
        ret.status = 'REJECTED'
        messages.info(request, f"Return request #{ret.id} rejected.")
    elif action == 'refund':
        ret.status = 'REFUNDED'
        messages.success(request, f"Return request #{ret.id} processed for refund.")
    ret.save()
    return redirect('super_admin_ecom_returns')


# =====================================================================
# 4.D. SERVICE MANAGEMENT
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_categories(request):
    """
    Section 4.D: Service Category Management (Plumbing, Electrician, Cleaning, AC, etc.)
    """
    categories = Category.objects.annotate(service_count=Count('quickservice')).order_by('name')
    return render(request, 'superadmin/service_categories.html', {'categories': categories})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_catalog(request):
    """
    Section 4.D: Service Listing & Pricing.
    """
    services = QuickService.objects.select_related('category').order_by('title')
    return render(request, 'superadmin/service_catalog.html', {'services': services})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_providers(request):
    """
    Section 4.D: Service Provider Management.
    """
    providers_qs = CustomUser.objects.filter(role__in=['SERVICE_PROVIDER', 'VENDOR']).select_related('vendor_profile').order_by('-date_joined')
    return render(request, 'superadmin/service_providers.html', {'providers': providers_qs})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_bookings(request):
    """
    Section 4.D: Service Booking Management.
    """
    status_filter = request.GET.get('status', '').strip()
    bookings_qs = ServiceBooking.objects.select_related('customer', 'vendor').order_by('-created_at')

    if status_filter:
        bookings_qs = bookings_qs.filter(status=status_filter)

    paginator = Paginator(bookings_qs, 15)
    page_number = request.GET.get('page')
    bookings = paginator.get_page(page_number)

    available_providers = CustomUser.objects.filter(role__in=['SERVICE_PROVIDER', 'VENDOR'], is_active=True).select_related('vendor_profile')

    return render(request, 'superadmin/service_bookings.html', {
        'bookings': bookings,
        'status_filter': status_filter,
        'available_providers': available_providers
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_booking_assign(request, booking_id):
    """
    Section 4.D: Assign Service Provider to a booking.
    """
    booking = get_object_or_404(ServiceBooking, pk=booking_id)
    if request.method == 'POST':
        provider_id = request.POST.get('provider_id')
        provider = get_object_or_404(CustomUser, pk=provider_id, role__in=['SERVICE_PROVIDER', 'VENDOR'])
        booking.vendor = provider
        booking.status = 'confirmed'
        booking.assigned_at = timezone.now()
        booking.save()
        messages.success(request, f"Service Booking #{booking.booking_number} assigned to {provider.get_full_name() or provider.username}.")
    return redirect('super_admin_service_bookings')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_service_time_slots(request):
    """
    Section 4.D: Manage Time Slots.
    """
    slots = ServiceTimeSlot.objects.all().order_by('order')
    return render(request, 'superadmin/service_time_slots.html', {'slots': slots})


# =====================================================================
# 4.E. DELIVERY MANAGEMENT
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_delivery_partners(request):
    """
    Section 4.E: Delivery Partner Management.
    """
    partners = DeliveryPartnerProfile.objects.select_related('user').order_by('-created_at')
    return render(request, 'superadmin/delivery_partners.html', {'partners': partners})


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_delivery_assignments(request):
    """
    Section 4.E: Assign Delivery Partners (Queue of PACKED orders awaiting rider).
    """
    packed_orders = ProductOrder.objects.filter(order_status='PACKED').select_related('customer', 'delivery_partner').order_by('-created_at')
    available_riders = DeliveryPartnerProfile.objects.select_related('user').filter(user__is_active=True, is_verified=True)

    return render(request, 'superadmin/delivery_assignments.html', {
        'orders': packed_orders,
        'riders': available_riders
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_delivery_assign(request, order_id):
    """
    Section 4.E: Assign delivery partner to order.
    """
    order = get_object_or_404(ProductOrder, pk=order_id)
    if request.method == 'POST':
        rider_id = request.POST.get('rider_id')
        rider = get_object_or_404(CustomUser, pk=rider_id)
        order.delivery_partner = rider
        order.delivery_assignment_status = 'PENDING'
        order.save()
        messages.success(request, f"Order #{order.order_number} assigned to delivery partner {rider.get_full_name() or rider.username}.")
    return redirect('super_admin_delivery_assignments')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_delivery_tracking(request):
    """
    Section 4.E: Track Delivery Status.
    """
    active_deliveries = ProductOrder.objects.filter(
        order_status__in=['PACKED', 'SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED']
    ).select_related('customer', 'delivery_partner').order_by('-updated_at')

    return render(request, 'superadmin/delivery_tracking.html', {'deliveries': active_deliveries})


# =====================================================================
# 4.F. PAYMENT & REPORTS
# =====================================================================

@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_payments(request):
    """
    Section 4.F: Payment Management (Ledger of paid orders and services).
    """
    paid_orders = ProductOrder.objects.filter(payment_status='PAID').order_by('-created_at')[:20]
    paid_services = ServiceBooking.objects.filter(payment_status='PAID').order_by('-created_at')[:20]

    return render(request, 'superadmin/payments.html', {
        'paid_orders': paid_orders,
        'paid_services': paid_services
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_commissions(request):
    """
    Section 4.F: Commission Management.
    """
    return render(request, 'superadmin/commissions.html')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_payouts(request):
    """
    Section 4.F: Provider Payouts.
    """
    payouts = PayoutRequest.objects.select_related('vendor').order_by('-created_at')
    delivery_payouts = DeliveryPayout.objects.select_related('partner').order_by('-created_at')

    return render(request, 'superadmin/payouts.html', {
        'payouts': payouts,
        'delivery_payouts': delivery_payouts
    })


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_payout_action(request, payout_id, action):
    payout = get_object_or_404(PayoutRequest, pk=payout_id)
    if action == 'approve':
        payout.status = 'approved'
        payout.processed_at = timezone.now()
        messages.success(request, f"Payout #{payout.id} approved.")
    elif action == 'reject':
        payout.status = 'rejected'
        messages.info(request, f"Payout #{payout.id} rejected.")
    payout.save()
    return redirect('super_admin_payouts')


@user_passes_test(super_admin_check, login_url='/super-admin/login/')
def super_admin_reports(request):
    """
    Section 4.F: Sales & Booking Reports.
    """
    ecom_total = ProductOrder.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')
    services_total = ServiceBooking.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')
    grand_total = ecom_total + services_total

    orders_count = ProductOrder.objects.count()
    delivered_count = ProductOrder.objects.filter(order_status='DELIVERED').count()
    bookings_count = ServiceBooking.objects.count()
    completed_bookings = ServiceBooking.objects.filter(status='completed').count()

    return render(request, 'superadmin/reports.html', {
        'ecom_total': ecom_total,
        'services_total': services_total,
        'grand_total': grand_total,
        'orders_count': orders_count,
        'delivered_count': delivered_count,
        'bookings_count': bookings_count,
        'completed_bookings': completed_bookings
    })
