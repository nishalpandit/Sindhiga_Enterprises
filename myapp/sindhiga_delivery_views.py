import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction

from .models import (
    CustomUser, AuthToken, DeliveryPartnerProfile, ProductOrder, DeliveryPayout
)
from .sindhiga_ecommerce_views import _auth_user, _get_payload


def _get_delivery_partner(request):
    """Authenticates user and ensures they have a DeliveryPartnerProfile."""
    user = _auth_user(request)
    if not user:
        return None, JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)
    
    # Auto-create profile if role is DELIVERY_PARTNER
    profile, _ = DeliveryPartnerProfile.objects.get_or_create(user=user)
    return profile, None


# =====================================================================
# DELIVERY PARTNER PROFILE & STATUS APIS
# =====================================================================

@csrf_exempt
def delivery_profile_api(request):
    """Get or update delivery partner profile, vehicle info, and documents."""
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    if request.method == 'POST':
        data = _get_payload(request)
        if 'phone_number' in data:
            profile.phone_number = data['phone_number']
        if 'vehicle_type' in data:
            profile.vehicle_type = data['vehicle_type']
        if 'vehicle_number' in data:
            profile.vehicle_number = data['vehicle_number']
        if 'driving_license_number' in data:
            profile.driving_license_number = data['driving_license_number']
        if 'city' in data:
            profile.city = data['city']
            
        # File uploads if multipart
        if request.FILES.get('driving_license_doc'):
            profile.driving_license_doc = request.FILES['driving_license_doc']
        if request.FILES.get('id_proof_doc'):
            profile.id_proof_doc = request.FILES['id_proof_doc']
        if request.FILES.get('profile_image'):
            profile.profile_image = request.FILES['profile_image']

        profile.save()
        return JsonResponse({'status': 'success', 'message': 'Profile updated successfully'})

    # GET profile
    u = profile.user
    return JsonResponse({
        'status': 'success',
        'partner': {
            'id': profile.id,
            'partner_code': profile.partner_code,
            'name': u.get_full_name() or u.username,
            'email': u.email,
            'phone_number': profile.phone_number or getattr(u, 'phone_number', ''),
            'vehicle_type': profile.vehicle_type,
            'vehicle_number': profile.vehicle_number or '',
            'driving_license_number': profile.driving_license_number or '',
            'license_uploaded': bool(profile.driving_license_doc),
            'id_proof_uploaded': bool(profile.id_proof_doc),
            'profile_image': profile.profile_image.url if profile.profile_image else None,
            'city': profile.city,
            'is_verified': profile.is_verified,
            'is_online': profile.is_online,
            'current_status': profile.current_status,
            'rating': float(profile.rating),
            'total_deliveries': profile.total_deliveries,
            'total_earnings': float(profile.total_earnings),
            'wallet_balance': float(profile.wallet_balance)
        }
    })


@csrf_exempt
def delivery_toggle_online_api(request):
    """Toggle online/offline duty status and update GPS coordinates."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    data = _get_payload(request)
    if 'is_online' in data:
        is_online_val = data['is_online']
        profile.is_online = str(is_online_val).lower() in ['true', '1', 'yes']
    else:
        profile.is_online = not profile.is_online

    profile.current_status = 'available' if profile.is_online else 'offline'

    lat = data.get('latitude')
    lng = data.get('longitude')
    if lat and lng:
        try:
            profile.current_latitude = Decimal(str(lat))
            profile.current_longitude = Decimal(str(lng))
        except Exception:
            pass

    profile.save()
    return JsonResponse({
        'status': 'success',
        'is_online': profile.is_online,
        'current_status': profile.current_status,
        'message': f"Duty status switched to {'ONLINE' if profile.is_online else 'OFFLINE'}"
    })


# =====================================================================
# ASSIGNED DELIVERIES MANAGEMENT APIS
# =====================================================================

def delivery_orders_list_api(request):
    """
    List deliveries assigned to this delivery partner.
    Filter param: 'tab' = 'pending' | 'active' | 'completed' | 'all'
    """
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    user = profile.user
    tab = request.GET.get('tab', 'all')
    qs = ProductOrder.objects.filter(delivery_partner=user)

    if tab == 'pending':
        qs = qs.filter(delivery_assignment_status='PENDING', order_status__in=['PACKED', 'ASSIGNED'])
    elif tab == 'active':
        qs = qs.filter(delivery_assignment_status='ACCEPTED', order_status__in=['ASSIGNED', 'PICKED_UP', 'OUT_FOR_DELIVERY'])
    elif tab == 'completed':
        qs = qs.filter(order_status='DELIVERED')

    orders = []
    for o in qs.order_by('-created_at'):
        orders.append({
            'order_id': o.id,
            'order_number': o.order_number,
            'order_status': o.order_status,
            'order_status_display': o.get_order_status_display(),
            'assignment_status': o.delivery_assignment_status,
            'customer_name': o.customer_name,
            'customer_phone': o.customer_phone,
            'delivery_address': f"{o.delivery_address_text}, {o.delivery_city} - {o.delivery_pincode}",
            'total_amount': float(o.total_amount),
            'payment_method': o.payment_method,
            'payment_status': o.payment_status,
            'collect_cash': float(o.total_amount) if o.payment_method == 'COD' and o.payment_status != 'PAID' else 0.0,
            'items_count': o.items.count(),
            'delivery_notes': o.delivery_notes or '',
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M')
        })

    return JsonResponse({
        'status': 'success',
        'tab': tab,
        'count': len(orders),
        'orders': orders
    })


@csrf_exempt
def delivery_respond_order_api(request, order_id):
    """Delivery partner accepts or rejects an assigned delivery."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    try:
        order = ProductOrder.objects.get(id=order_id, delivery_partner=profile.user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Assigned order not found'}, status=404)

    data = _get_payload(request)
    action = data.get('action', '').lower()  # 'accept' or 'reject'

    if action == 'accept':
        order.delivery_assignment_status = 'ACCEPTED'
        order.order_status = 'ASSIGNED'
        order.save(update_fields=['delivery_assignment_status', 'order_status'])
        profile.current_status = 'busy'
        profile.save(update_fields=['current_status'])
        return JsonResponse({'status': 'success', 'message': f'Order #{order.order_number} accepted. Please proceed to pick up.'})

    elif action == 'reject':
        reason = data.get('reason', 'Rejected by partner')
        order.delivery_assignment_status = 'REJECTED'
        order.delivery_partner = None
        order.order_status = 'PACKED'
        order.delivery_notes = f"Previously rejected by {profile.partner_code}: {reason}"
        order.save(update_fields=['delivery_assignment_status', 'delivery_partner', 'order_status', 'delivery_notes'])
        profile.current_status = 'available'
        profile.save(update_fields=['current_status'])
        return JsonResponse({'status': 'success', 'message': f'Order #{order.order_number} assignment declined.'})

    return JsonResponse({'status': 'error', 'message': "Invalid action. Use 'accept' or 'reject'."}, status=400)


@csrf_exempt
def delivery_mark_picked_up_api(request, order_id):
    """Mark package as picked up from the hub/warehouse."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    try:
        order = ProductOrder.objects.get(id=order_id, delivery_partner=profile.user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    order.order_status = 'PICKED_UP'
    order.picked_up_at = timezone.now()
    order.save(update_fields=['order_status', 'picked_up_at'])

    return JsonResponse({
        'status': 'success',
        'message': f'Order #{order.order_number} marked as Picked Up. You may start delivery.',
        'order_status': order.order_status
    })


@csrf_exempt
def delivery_mark_out_for_delivery_api(request, order_id):
    """Mark package as out for delivery."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    try:
        order = ProductOrder.objects.get(id=order_id, delivery_partner=profile.user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    order.order_status = 'OUT_FOR_DELIVERY'
    order.save(update_fields=['order_status'])

    return JsonResponse({
        'status': 'success',
        'message': f'Order #{order.order_number} is now Out for Delivery.',
        'order_status': order.order_status
    })


@csrf_exempt
@transaction.atomic
def delivery_verify_and_complete_api(request, order_id):
    """
    Verify customer OTP and mark order as DELIVERED.
    Credits delivery payout (standard ₹40 per completed delivery) to delivery partner wallet.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    try:
        order = ProductOrder.objects.get(id=order_id, delivery_partner=profile.user)
    except ProductOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)

    data = _get_payload(request)
    otp = str(data.get('otp', '')).strip()

    if not otp:
        return JsonResponse({'status': 'error', 'message': 'Delivery OTP is required.'}, status=400)

    if order.delivery_otp and otp != order.delivery_otp:
        return JsonResponse({'status': 'error', 'message': 'Invalid OTP entered. Please verify with the customer.'}, status=400)

    # Successfully verified!
    order.order_status = 'DELIVERED'
    order.delivery_assignment_status = 'COMPLETED'
    order.delivered_at = timezone.now()
    if order.payment_method == 'COD':
        order.payment_status = 'PAID'
    order.save(update_fields=['order_status', 'delivery_assignment_status', 'delivered_at', 'payment_status'])

    # Credit Delivery Partner Earnings
    payout_amount = Decimal('40.00')
    DeliveryPayout.objects.create(
        delivery_partner=profile.user,
        order=order,
        amount=payout_amount,
        payout_type='delivery_fee',
        status='paid'
    )

    profile.total_deliveries += 1
    profile.total_earnings += payout_amount
    profile.wallet_balance += payout_amount
    profile.current_status = 'available'
    profile.save(update_fields=['total_deliveries', 'total_earnings', 'wallet_balance', 'current_status'])

    return JsonResponse({
        'status': 'success',
        'message': f'Order #{order.order_number} delivered successfully! ₹{payout_amount} credited to your wallet.',
        'delivered_at': order.delivered_at.strftime('%Y-%m-%d %H:%M'),
        'payout_credited': float(payout_amount),
        'new_wallet_balance': float(profile.wallet_balance)
    })


# =====================================================================
# EARNINGS & PAYOUT SUMMARY APIS
# =====================================================================

def delivery_earnings_api(request):
    """View earnings breakdown, delivery stats, and recent payout records."""
    profile, err_resp = _get_delivery_partner(request)
    if err_resp:
        return err_resp

    payouts = DeliveryPayout.objects.filter(delivery_partner=profile.user).order_by('-created_at')[:20]
    payout_list = []
    for p in payouts:
        payout_list.append({
            'id': p.id,
            'order_number': p.order.order_number if p.order else 'N/A',
            'amount': float(p.amount),
            'payout_type': p.get_payout_type_display() if hasattr(p, 'get_payout_type_display') else p.payout_type,
            'status': p.status,
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M')
        })

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_payouts = DeliveryPayout.objects.filter(delivery_partner=profile.user, created_at__gte=today_start)
    today_earnings = sum(p.amount for p in today_payouts)

    return JsonResponse({
        'status': 'success',
        'summary': {
            'total_deliveries': profile.total_deliveries,
            'total_earnings': float(profile.total_earnings),
            'wallet_balance': float(profile.wallet_balance),
            'today_earnings': float(today_earnings),
            'rating': float(profile.rating)
        },
        'payout_history': payout_list
    })
