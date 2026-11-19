import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction

from .models import (
    CustomUser, AuthToken, VendorProfile, VendorKYC,
    ServiceBooking, VendorWallet, WalletTransaction
)
from .sindhiga_ecommerce_views import _auth_user, _get_payload


def _get_provider_profile(request):
    """Authenticates user and returns their VendorProfile."""
    user = _auth_user(request)
    if not user:
        return None, JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)
    
    profile, _ = VendorProfile.objects.get_or_create(user=user)
    return profile, None


# =====================================================================
# SERVICE PROVIDER PROFILE & AVAILABILITY APIS
# =====================================================================

@csrf_exempt
def provider_profile_api(request):
    """View and update service provider profile details and KYC status."""
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    if request.method == 'POST':
        data = _get_payload(request)
        if 'business_name' in data or 'company_name' in data:
            profile.company_name = data.get('business_name') or data.get('company_name')
        if 'contact_phone' in data or 'mobile' in data:
            profile.mobile = data.get('contact_phone') or data.get('mobile')
        if 'experience_years' in data or 'experience' in data:
            try:
                profile.experience = int(data.get('experience_years') or data.get('experience'))
            except Exception:
                pass
        if 'bio' in data or 'about' in data:
            profile.about = data.get('bio') or data.get('about')
        if 'city' in data:
            profile.city = data['city']

        if request.FILES.get('profile_image'):
            profile.profile_image = request.FILES['profile_image']

        profile.save()
        return JsonResponse({'status': 'success', 'message': 'Provider profile updated successfully'})

    # GET profile
    u = profile.user
    kyc = getattr(u, 'kyc', None)
    kyc_status = kyc.status if kyc else 'not_submitted'

    return JsonResponse({
        'status': 'success',
        'provider': {
            'id': profile.id,
            'name': u.get_full_name() or u.username,
            'business_name': profile.company_name or '',
            'email': u.email,
            'phone': profile.mobile or getattr(u, 'phone_number', ''),
            'city': profile.city or 'Ranchi',
            'category': profile.category or 'General',
            'experience_years': profile.experience,
            'bio': profile.about or '',
            'profile_image': profile.profile_image.url if profile.profile_image else None,
            'is_verified': kyc_status == 'approved',
            'is_available': profile.is_online,
            'kyc_status': kyc_status,
            'rating': float(profile.rating) if profile.rating else 4.8
        }
    })


@csrf_exempt
def provider_toggle_availability_api(request):
    """Toggle online availability for receiving new service bookings."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    data = _get_payload(request)
    if 'is_available' in data or 'is_online' in data:
        val = data.get('is_available') if 'is_available' in data else data.get('is_online')
        profile.is_online = str(val).lower() in ['true', '1', 'yes']
    else:
        profile.is_online = not profile.is_online

    profile.save(update_fields=['is_online'])
    return JsonResponse({
        'status': 'success',
        'is_available': profile.is_online,
        'message': f"Status set to {'ONLINE & AVAILABLE' if profile.is_online else 'OFFLINE'}"
    })


# =====================================================================
# SERVICE BOOKINGS FEED & ACTIONS APIS
# =====================================================================

def provider_bookings_list_api(request):
    """
    List bookings assigned to this provider.
    Query param: 'tab' = 'pending' | 'active' | 'completed' | 'all'
    """
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    user = profile.user
    tab = request.GET.get('tab', 'all')
    qs = ServiceBooking.objects.filter(vendor=user)

    if tab == 'pending':
        qs = qs.filter(status='assigned')
    elif tab == 'active':
        qs = qs.filter(status__in=['accepted', 'heading', 'in_progress'])
    elif tab == 'completed':
        qs = qs.filter(status='completed')

    bookings = []
    for b in qs.order_by('-scheduled_date', '-created_at'):
        service_name = b.package_name or (b.quick_service.title if b.quick_service else 'Home Service')
        slot_label = b.time_slot or 'Standard Slot'
        bookings.append({
            'booking_id': b.id,
            'service_name': service_name,
            'customer_name': b.customer.get_full_name() or b.customer.username,
            'customer_phone': getattr(b.customer, 'phone_number', '') or '',
            'service_location': b.service_address or '',
            'booking_date': b.scheduled_date.strftime('%Y-%m-%d') if b.scheduled_date else '',
            'time_slot': slot_label,
            'status': b.status,
            'status_display': b.get_status_display(),
            'total_amount': float(b.total_amount),
            'payment_mode': b.payment_method or 'Cash After Service',
            'payment_status': b.payment_status or 'Pending',
            'created_at': b.created_at.strftime('%Y-%m-%d %H:%M')
        })

    return JsonResponse({
        'status': 'success',
        'tab': tab,
        'count': len(bookings),
        'bookings': bookings
    })


@csrf_exempt
def provider_respond_booking_api(request, booking_id):
    """Service provider accepts or rejects an assigned booking."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    try:
        booking = ServiceBooking.objects.get(id=booking_id, vendor=profile.user)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Assigned booking not found'}, status=404)

    data = _get_payload(request)
    action = data.get('action', '').lower()

    if action == 'accept':
        booking.status = 'accepted'
        booking.save(update_fields=['status'])
        return JsonResponse({'status': 'success', 'message': 'Booking accepted. Customer has been notified.'})

    elif action == 'reject':
        reason = data.get('reason', 'Provider unavailable')
        booking.status = 'rejected'
        booking.rejection_reason = reason
        booking.vendor = None  # Release back to admin for reassignment
        booking.save(update_fields=['status', 'rejection_reason', 'vendor'])
        return JsonResponse({'status': 'success', 'message': 'Booking declined and released for reassignment.'})

    return JsonResponse({'status': 'error', 'message': "Invalid action. Use 'accept' or 'reject'."}, status=400)


@csrf_exempt
def provider_update_job_status_api(request, booking_id):
    """
    Update real-time job execution status:
    - 'heading': On the way to customer location
    - 'in_progress': Started performing the service
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    try:
        booking = ServiceBooking.objects.get(id=booking_id, vendor=profile.user)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Booking not found'}, status=404)

    data = _get_payload(request)
    new_status = data.get('status', '').lower()

    if new_status not in ['heading', 'in_progress']:
        return JsonResponse({'status': 'error', 'message': "Status must be 'heading' or 'in_progress'. Use verify-complete to finish."}, status=400)

    booking.status = new_status
    booking.save(update_fields=['status'])

    status_messages = {
        'heading': 'Status updated: You are on the way to the customer location.',
        'in_progress': 'Status updated: Service work started.'
    }

    return JsonResponse({
        'status': 'success',
        'message': status_messages.get(new_status, 'Status updated'),
        'booking_status': booking.status
    })


@csrf_exempt
@transaction.atomic
def provider_complete_service_api(request, booking_id):
    """
    Verify customer OTP and complete the service booking.
    Credits provider earnings to VendorWallet.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    try:
        booking = ServiceBooking.objects.get(id=booking_id, vendor=profile.user)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Booking not found'}, status=404)

    data = _get_payload(request)
    otp = str(data.get('otp', '')).strip()

    if booking.otp_code and otp != booking.otp_code:
        return JsonResponse({'status': 'error', 'message': 'Invalid OTP entered. Please ask the customer for the verification OTP.'}, status=400)

    booking.status = 'completed'
    booking.payment_status = 'PAID'
    booking.save(update_fields=['status', 'payment_status'])

    # Calculate provider payout (80% of booking amount, 20% platform commission)
    total_val = booking.total_amount or Decimal('500.00')
    provider_payout = total_val * Decimal('0.80')

    wallet, _ = VendorWallet.objects.get_or_create(vendor=profile.user)
    current_bal = Decimal(str(wallet.available_balance or '0.00'))
    current_earned = Decimal(str(wallet.total_earned or '0.00'))
    wallet.available_balance = current_bal + provider_payout
    wallet.total_earned = current_earned + provider_payout
    wallet.save(update_fields=['available_balance', 'total_earned'])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type='credit',
        amount=provider_payout,
        description=f"Earnings for Service Booking #{booking.id}",
        related_quick_service=booking.quick_service
    )

    return JsonResponse({
        'status': 'success',
        'message': f'Service marked as Completed! ₹{provider_payout:.2f} credited to your wallet.',
        'payout_credited': float(provider_payout),
        'wallet_balance': float(wallet.available_balance)
    })


# =====================================================================
# PROVIDER EARNINGS & WALLET SUMMARY
# =====================================================================

def provider_earnings_api(request):
    """View provider wallet balance, recent credit transactions, and job metrics."""
    profile, err_resp = _get_provider_profile(request)
    if err_resp:
        return err_resp

    wallet, _ = VendorWallet.objects.get_or_create(vendor=profile.user)
    txns = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:20]

    txn_list = []
    for t in txns:
        txn_list.append({
            'id': t.id,
            'amount': float(t.amount),
            'type': t.transaction_type,
            'description': t.description,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M')
        })

    completed_count = ServiceBooking.objects.filter(vendor=profile.user, status='completed').count()

    return JsonResponse({
        'status': 'success',
        'summary': {
            'wallet_balance': float(wallet.available_balance),
            'total_earned': float(wallet.total_earned),
            'completed_bookings': completed_count,
            'rating': float(profile.rating) if profile.rating else 4.8
        },
        'transactions': txn_list
    })
