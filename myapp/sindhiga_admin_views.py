import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Sum, Count, Q

from .models import (
    CustomUser, ProductOrder, ServiceBooking, DeliveryPartnerProfile,
    VendorProfile, ReturnRequest, Product, Coupon
)
from .sindhiga_ecommerce_views import _auth_user, _get_payload


def _is_admin(user):
    return user and (user.is_superuser or user.is_staff or getattr(user, 'role', '') == 'ADMIN')


# =====================================================================
# ADMIN METRICS & DASHBOARD KPIS
# =====================================================================

def admin_kpis_api(request):
    """Platform-wide operational KPIs for Admin dashboard."""
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    total_customers = CustomUser.objects.filter(role__in=['CUSTOMER', 'USER']).count()
    total_providers = CustomUser.objects.filter(role__in=['SERVICE_PROVIDER', 'VENDOR']).count()
    total_delivery = DeliveryPartnerProfile.objects.count()

    # E-Commerce Metrics
    total_orders = ProductOrder.objects.count()
    pending_orders = ProductOrder.objects.filter(order_status='PENDING').count()
    packed_orders = ProductOrder.objects.filter(order_status='PACKED').count()
    delivered_orders = ProductOrder.objects.filter(order_status='DELIVERED').count()
    ecom_revenue = ProductOrder.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')

    # Home Services Metrics
    total_service_bookings = ServiceBooking.objects.count()
    unassigned_bookings = ServiceBooking.objects.filter(status='pending').count()
    completed_bookings = ServiceBooking.objects.filter(status='completed').count()
    services_revenue = ServiceBooking.objects.filter(payment_status='PAID').aggregate(sum=Sum('total_amount'))['sum'] or Decimal('0.00')

    total_revenue = ecom_revenue + services_revenue

    return JsonResponse({
        'status': 'success',
        'kpis': {
            'total_customers': total_customers,
            'total_service_providers': total_providers,
            'total_delivery_partners': total_delivery,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'packed_orders': packed_orders,
            'delivered_orders': delivered_orders,
            'total_service_bookings': total_service_bookings,
            'unassigned_service_bookings': unassigned_bookings,
            'completed_service_bookings': completed_bookings,
            'ecommerce_revenue': float(ecom_revenue),
            'services_revenue': float(services_revenue),
            'total_revenue': float(total_revenue)
        }
    })


# =====================================================================
# ADMIN E-COMMERCE ORDER MANAGEMENT & DELIVERY ASSIGNMENT
# =====================================================================

def admin_orders_list_api(request):
    """Admin view of all customer orders with filtering."""
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    qs = ProductOrder.objects.all().order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(order_status=status_filter)

    orders = []
    for o in qs[:50]:
        orders.append({
            'order_id': o.id,
            'order_number': o.order_number,
            'customer_name': o.customer_name,
            'customer_phone': o.customer_phone,
            'city': o.delivery_city,
            'total_amount': float(o.total_amount),
            'payment_method': o.payment_method,
            'payment_status': o.payment_status,
            'order_status': o.order_status,
            'order_status_display': o.get_order_status_display(),
            'delivery_partner': o.delivery_partner.get_full_name() if o.delivery_partner else None,
            'assignment_status': o.delivery_assignment_status,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M')
        })

    return JsonResponse({'status': 'success', 'count': len(orders), 'orders': orders})


@csrf_exempt
def admin_order_update_status_api(request, order_id):
    """Update order status (e.g. CONFIRMED, PACKED)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    try:
        order = ProductOrder.objects.get(id=order_id)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    data = _get_payload(request)
    new_status = data.get('status', '').upper()

    valid_transitions = {
        'CONFIRMED': ('confirmed_at', timezone.now()),
        'PACKED': ('packed_at', timezone.now())
    }

    if new_status in valid_transitions:
        field, val = valid_transitions[new_status]
        order.order_status = new_status
        setattr(order, field, val)
        order.save()
        return JsonResponse({'status': 'success', 'message': f'Order status updated to {new_status}'})

    return JsonResponse({'status': 'error', 'message': 'Invalid status transition.'}, status=400)


@csrf_exempt
def admin_assign_delivery_partner_api(request, order_id):
    """
    Assign a verified delivery partner to a PACKED order.
    Sets delivery_assignment_status to PENDING (waiting for partner to accept).
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    try:
        order = ProductOrder.objects.get(id=order_id)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    data = _get_payload(request)
    partner_id = data.get('partner_id') or data.get('delivery_partner_id')
    if not partner_id:
        return JsonResponse({'status': 'error', 'message': 'partner_id is required.'}, status=400)

    try:
        partner_user = CustomUser.objects.get(id=partner_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Delivery partner user not found'}, status=404)

    order.delivery_partner = partner_user
    order.delivery_assignment_status = 'PENDING'
    order.order_status = 'ASSIGNED'
    order.save(update_fields=['delivery_partner', 'delivery_assignment_status', 'order_status'])

    return JsonResponse({
        'status': 'success',
        'message': f"Order #{order.order_number} successfully assigned to delivery partner {partner_user.get_full_name() or partner_user.username}.",
        'assignment_status': order.delivery_assignment_status
    })


# =====================================================================
# ADMIN SERVICE BOOKINGS & PROVIDER ASSIGNMENT
# =====================================================================

def admin_service_bookings_list_api(request):
    """Admin view of all service bookings."""
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    qs = ServiceBooking.objects.all().order_by('-scheduled_date', '-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    bookings = []
    for b in qs[:50]:
        slot_label = b.time_slot or 'Standard Slot'
        bookings.append({
            'booking_id': b.id,
            'service_title': b.package_name or (b.quick_service.title if b.quick_service else 'Service'),
            'customer_name': b.customer.get_full_name() or b.customer.username,
            'customer_phone': getattr(b.customer, 'phone_number', '') or '',
            'booking_date': b.scheduled_date.strftime('%Y-%m-%d') if b.scheduled_date else '',
            'time_slot': slot_label,
            'status': b.status,
            'status_display': b.get_status_display(),
            'assigned_provider': b.vendor.get_full_name() if b.vendor else 'Unassigned',
            'total_amount': float(b.total_amount),
            'otp_code': b.otp_code
        })

    return JsonResponse({'status': 'success', 'count': len(bookings), 'bookings': bookings})


@csrf_exempt
def admin_assign_service_provider_api(request, booking_id):
    """Assign or reassign a service provider to a customer booking."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    try:
        booking = ServiceBooking.objects.get(id=booking_id)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Service booking not found'}, status=404)

    data = _get_payload(request)
    provider_id = data.get('provider_id') or data.get('vendor_id')
    if not provider_id:
        return JsonResponse({'status': 'error', 'message': 'provider_id is required.'}, status=400)

    try:
        provider_user = CustomUser.objects.get(id=provider_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Service provider not found'}, status=404)

    booking.vendor = provider_user
    booking.status = 'assigned'
    booking.rejection_reason = None
    booking.save(update_fields=['vendor', 'status', 'rejection_reason'])

    return JsonResponse({
        'status': 'success',
        'message': f"Booking #{booking.id} assigned to provider {provider_user.get_full_name() or provider_user.username}.",
        'booking_status': booking.status
    })


# =====================================================================
# ADMIN RETURN & REFUND MANAGEMENT
# =====================================================================

def admin_returns_list_api(request):
    """Admin view of all customer return/refund requests."""
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    returns = ReturnRequest.objects.all().order_by('-created_at')
    result = []
    for r in returns:
        result.append({
            'return_id': r.id,
            'order_id': r.order.id,
            'order_number': r.order.order_number,
            'customer_name': r.customer.get_full_name() or r.customer.username,
            'reason': r.reason,
            'status': r.status,
            'status_display': r.get_status_display(),
            'refund_amount': float(r.refund_amount),
            'admin_notes': r.admin_notes or '',
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return JsonResponse({'status': 'success', 'returns': result})


@csrf_exempt
def admin_return_action_api(request, return_id):
    """Approve, reject, or process refund for a return request."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    try:
        ret = ReturnRequest.objects.get(id=return_id)
    except ReturnRequest.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Return request not found'}, status=404)

    data = _get_payload(request)
    action = data.get('action', '').lower()
    notes = data.get('notes', '')

    if action == 'approve':
        ret.status = 'APPROVED'
        ret.admin_notes = notes or 'Return approved by admin. Pickup scheduled.'
        ret.save(update_fields=['status', 'admin_notes'])
        return JsonResponse({'status': 'success', 'message': 'Return approved. Pickup scheduled.'})

    elif action == 'reject':
        ret.status = 'REJECTED'
        ret.admin_notes = notes or 'Return request rejected.'
        ret.save(update_fields=['status', 'admin_notes'])
        ret.order.order_status = 'DELIVERED'
        ret.order.save(update_fields=['order_status'])
        return JsonResponse({'status': 'success', 'message': 'Return request rejected.'})

    elif action == 'refund':
        ret.status = 'REFUNDED'
        ret.admin_notes = notes or 'Refund processed to customer source account.'
        ret.save(update_fields=['status', 'admin_notes'])
        ret.order.order_status = 'RETURNED'
        ret.order.payment_status = 'REFUNDED'
        ret.order.save(update_fields=['order_status', 'payment_status'])
        return JsonResponse({'status': 'success', 'message': 'Refund completed successfully.'})

    return JsonResponse({'status': 'error', 'message': "Invalid action. Use 'approve', 'reject', or 'refund'."}, status=400)


# =====================================================================
# ADMIN DELIVERY FLEET MANAGEMENT
# =====================================================================

def admin_delivery_partners_list_api(request):
    """List all delivery partners, verification state, and active metrics."""
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    partners = DeliveryPartnerProfile.objects.all().order_by('-created_at')
    result = []
    for p in partners:
        u = p.user
        result.append({
            'partner_id': p.id,
            'user_id': u.id,
            'partner_code': p.partner_code,
            'name': u.get_full_name() or u.username,
            'phone': p.phone_number or getattr(u, 'phone_number', ''),
            'vehicle': f"{p.vehicle_type} - {p.vehicle_number or 'No plate'}",
            'license_number': p.driving_license_number or '',
            'license_doc': p.driving_license_doc.url if p.driving_license_doc else None,
            'id_doc': p.id_proof_doc.url if p.id_proof_doc else None,
            'is_verified': p.is_verified,
            'is_online': p.is_online,
            'current_status': p.current_status,
            'rating': float(p.rating),
            'total_deliveries': p.total_deliveries,
            'total_earnings': float(p.total_earnings)
        })

    return JsonResponse({'status': 'success', 'count': len(result), 'partners': result})


@csrf_exempt
def admin_verify_delivery_partner_api(request, partner_id):
    """Approve and verify a delivery partner's license & profile."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not _is_admin(user):
        return JsonResponse({'status': 'error', 'message': 'Admin privileges required'}, status=403)

    try:
        partner = DeliveryPartnerProfile.objects.get(id=partner_id)
    except DeliveryPartnerProfile.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Delivery partner profile not found'}, status=404)

    data = _get_payload(request)
    verify = str(data.get('is_verified', 'true')).lower() in ['true', '1', 'yes']
    partner.is_verified = verify
    partner.save(update_fields=['is_verified'])

    return JsonResponse({
        'status': 'success',
        'message': f"Delivery partner {partner.partner_code} {'approved & verified' if verify else 'unverified'}.",
        'is_verified': partner.is_verified
    })
