import json
import secrets
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction

from .models import (
    CustomUser, AuthToken, CustomerAddress, Category, SubCategory,
    QuickService, ServiceBooking, ServiceTimeSlot, ServiceReview
)
from .sindhiga_ecommerce_views import _auth_user, _get_payload


# =====================================================================
# TIME SLOTS & CATALOG
# =====================================================================

def service_time_slots_api(request):
    """List available service booking time slots."""
    slots = ServiceTimeSlot.objects.filter(is_active=True).order_by('order', 'start_time')
    result = []
    for s in slots:
        result.append({
            'id': s.id,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'label': s.label
        })
    return JsonResponse({'status': 'success', 'time_slots': result})


def service_catalog_api(request):
    """List active service categories, subcategories, and offerings."""
    categories = Category.objects.filter(is_active=True).order_by('order', 'name')
    cat_list = []
    for cat in categories:
        subs = cat.subcategories.filter(is_active=True).order_by('order', 'name')
        sub_list = []
        for s in subs:
            services_qs = QuickService.objects.filter(subcategory=s, status='active')
            srv_list = []
            for srv in services_qs:
                srv_list.append({
                    'id': srv.id,
                    'title': srv.title,
                    'price': float(srv.base_price) if srv.base_price else 0.0,
                    'duration': srv.duration or '45 mins',
                    'rating': 4.8
                })
            sub_list.append({
                'id': s.id,
                'name': s.name,
                'services': srv_list
            })
        cat_list.append({
            'id': cat.id,
            'name': cat.name,
            'icon': cat.icon_class or 'bi-wrench',
            'subcategories': sub_list
        })
    return JsonResponse({'status': 'success', 'catalog': cat_list})


# =====================================================================
# SERVICE BOOKING & TRACKING APIS
# =====================================================================

@csrf_exempt
@transaction.atomic
def book_service_with_slot_api(request):
    """
    Creates a new home service booking with date and time slot selection.
    Parameters:
    - service_id: int (QuickService ID)
    - booking_date: YYYY-MM-DD
    - time_slot_id: int (or time_slot_label)
    - address_id: int (CustomerAddress ID)
    - payment_method: 'COD' or 'ONLINE' (default 'COD')
    - customer_notes: str (optional)
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    data = _get_payload(request)
    service_id = data.get('service_id') or data.get('quick_service_id')
    if not service_id:
        return JsonResponse({'status': 'error', 'message': 'service_id is required.'}, status=400)

    service = QuickService.objects.filter(id=service_id).first()
    if not service:
        return JsonResponse({'status': 'error', 'message': 'Selected service not found or unavailable.'}, status=404)

    booking_date_str = data.get('booking_date')
    if not booking_date_str:
        return JsonResponse({'status': 'error', 'message': 'booking_date (YYYY-MM-DD) is required.'}, status=400)

    time_slot_id = data.get('time_slot_id')
    slot_obj = None
    slot_label = data.get('time_slot', '')

    if time_slot_id:
        slot_obj = ServiceTimeSlot.objects.filter(id=time_slot_id).first()
        if slot_obj:
            slot_label = slot_obj.label

    address_id = data.get('address_id')
    address_obj = None
    if address_id:
        address_obj = CustomerAddress.objects.filter(id=address_id, user=user).first()
    if not address_obj:
        address_obj = CustomerAddress.objects.filter(user=user, is_default=True).first() or CustomerAddress.objects.filter(user=user).first()

    customer_phone = data.get('customer_phone') or getattr(user, 'phone_number', '') or '9876543210'
    addr_text = f"{address_obj.address_line_1}, {address_obj.address_line_2 or ''}".strip(', ') if address_obj else data.get('address', 'Customer Address')

    # Generate 6-digit verification OTP
    otp_code = f"{secrets.randbelow(900000) + 100000}"

    booking = ServiceBooking.objects.create(
        customer=user,
        vendor=None,
        quick_service=service,
        package_name=service.title,
        scheduled_date=booking_date_str,
        time_slot=slot_label,
        service_address=addr_text,
        total_amount=getattr(service, 'base_price', Decimal('299.00')) or Decimal('299.00'),
        payment_method=data.get('payment_method', 'COD').upper(),
        payment_status='PAID' if data.get('payment_method', '').upper() == 'ONLINE' else 'pending',
        status='pending',
        otp_code=otp_code,
        customer_notes=data.get('customer_notes', '')
    )

    return JsonResponse({
        'status': 'success',
        'message': 'Service booking created successfully! We will assign the nearest professional.',
        'booking_id': booking.id,
        'service_title': booking.package_name,
        'booking_date': str(booking.scheduled_date),
        'time_slot': booking.time_slot,
        'otp_code': booking.otp_code,
        'status': booking.status,
        'status_display': booking.get_status_display(),
        'total_amount': float(booking.total_amount)
    })


def customer_bookings_list_api(request):
    """List customer service bookings with optional filter by status."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    qs = ServiceBooking.objects.filter(customer=user)
    tab = request.GET.get('tab', 'all')
    if tab == 'pending':
        qs = qs.filter(status__in=['pending', 'assigned'])
    elif tab == 'active':
        qs = qs.filter(status__in=['accepted', 'heading', 'in_progress'])
    elif tab == 'completed':
        qs = qs.filter(status='completed')

    bookings = []
    for b in qs.order_by('-scheduled_date', '-created_at'):
        bookings.append({
            'booking_id': b.id,
            'service_title': b.package_name or (b.quick_service.title if b.quick_service else 'Home Service'),
            'booking_date': b.scheduled_date.strftime('%Y-%m-%d') if b.scheduled_date else '',
            'time_slot': b.time_slot or 'Standard Slot',
            'status': b.status,
            'status_display': b.get_status_display(),
            'total_amount': float(b.total_amount),
            'otp_code': b.otp_code,
            'created_at': b.created_at.strftime('%Y-%m-%d %H:%M')
        })

    return JsonResponse({'status': 'success', 'tab': tab, 'bookings': bookings})


def customer_booking_detail_api(request, booking_id):
    """Complete tracking timeline and provider details for a service booking."""
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        booking = ServiceBooking.objects.get(id=booking_id, customer=user)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Service booking not found'}, status=404)

    provider_info = None
    if booking.vendor:
        vp = getattr(booking.vendor, 'vendor_profile', None)
        provider_info = {
            'name': booking.vendor.get_full_name() or booking.vendor.username,
            'phone': vp.mobile if vp else getattr(booking.vendor, 'phone_number', ''),
            'photo': vp.profile_image.url if vp and vp.profile_image else None,
            'rating': float(vp.rating) if vp and vp.rating else 4.8,
            'experience': f"{vp.experience} years" if vp and vp.experience else 'Certified Expert'
        }

    status_weights = {
        'pending': 1,
        'assigned': 2,
        'accepted': 3,
        'heading': 4,
        'in_progress': 5,
        'completed': 6,
        'cancelled': 0,
        'rejected': 0
    }
    cur_w = status_weights.get(booking.status, 1)

    timeline = [
        {'step': 'Booking Placed', 'code': 'pending', 'done': cur_w >= 1},
        {'step': 'Provider Assigned', 'code': 'assigned', 'done': cur_w >= 2},
        {'step': 'Provider Accepted', 'code': 'accepted', 'done': cur_w >= 3},
        {'step': 'On The Way', 'code': 'heading', 'done': cur_w >= 4},
        {'step': 'Work In Progress', 'code': 'in_progress', 'done': cur_w >= 5},
        {'step': 'Completed', 'code': 'completed', 'done': cur_w >= 6},
    ]

    return JsonResponse({
        'status': 'success',
        'booking': {
            'booking_id': booking.id,
            'service_title': booking.package_name or (booking.quick_service.title if booking.quick_service else 'Home Service'),
            'booking_date': booking.scheduled_date.strftime('%Y-%m-%d') if booking.scheduled_date else '',
            'time_slot': booking.time_slot or 'Standard Slot',
            'status': booking.status,
            'status_display': booking.get_status_display(),
            'total_amount': float(booking.total_amount),
            'otp_code': booking.otp_code,
            'payment_method': booking.payment_method or 'COD',
            'payment_status': booking.payment_status or 'pending',
            'service_location': booking.service_address,
            'provider': provider_info,
            'timeline': timeline,
            'can_cancel': booking.status in ['pending', 'assigned'],
            'created_at': booking.created_at.strftime('%Y-%m-%d %H:%M')
        }
    })


@csrf_exempt
def customer_booking_cancel_api(request, booking_id):
    """Customer cancels service booking before provider accepts/starts."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
    user = _auth_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

    try:
        booking = ServiceBooking.objects.get(id=booking_id, customer=user)
    except ServiceBooking.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Service booking not found'}, status=404)

    if booking.status not in ['pending', 'assigned']:
        return JsonResponse({'status': 'error', 'message': f'Cannot cancel booking once in {booking.status} status.'}, status=400)

    data = _get_payload(request)
    booking.status = 'cancelled'
    booking.rejection_reason = data.get('reason', 'Cancelled by customer')
    booking.save(update_fields=['status', 'rejection_reason'])

    return JsonResponse({'status': 'success', 'message': 'Service booking cancelled successfully.'})
