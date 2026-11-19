import os
import django
import json
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from django.test import RequestFactory
from django.utils import timezone
from myapp.models import (
    CustomUser, AuthToken, ProductCategory, Product, Cart, Coupon,
    ProductOrder, DeliveryPartnerProfile, ServiceBooking, ServiceTimeSlot,
    QuickService, VendorProfile, VendorWallet, DeliveryPayout
)
from myapp import sindhiga_ecommerce_views as ecom_api
from myapp import sindhiga_delivery_views as delivery_api
from myapp import sindhiga_provider_views as provider_api
from myapp import sindhiga_services_views as services_api
from myapp import sindhiga_admin_views as admin_api

def run_tests():
    rf = RequestFactory()
    print("==================================================")
    print("SINDHIGA ENTERPRISES COMPLETE FLOW TEST SUITE")
    print("==================================================")

    # 1. Setup Users
    admin_user, _ = CustomUser.objects.get_or_create(username='sindhiga_admin', defaults={'is_staff': True, 'is_superuser': True, 'role': 'ADMIN'})
    customer_user, _ = CustomUser.objects.get_or_create(username='sindhiga_customer', defaults={'role': 'CUSTOMER'})
    provider_user, _ = CustomUser.objects.get_or_create(username='sindhiga_provider', defaults={'role': 'SERVICE_PROVIDER'})
    delivery_user, _ = CustomUser.objects.get_or_create(username='sindhiga_rider', defaults={'role': 'DELIVERY_PARTNER'})

    cust_token, _ = AuthToken.objects.get_or_create(user=customer_user)
    prov_token, _ = AuthToken.objects.get_or_create(user=provider_user)
    deliv_token, _ = AuthToken.objects.get_or_create(user=delivery_user)
    admin_token, _ = AuthToken.objects.get_or_create(user=admin_user)

    DeliveryPartnerProfile.objects.get_or_create(user=delivery_user, defaults={'phone_number': '9876500003', 'vehicle_type': 'Motorcycle', 'vehicle_number': 'JH-01-AB-1234', 'is_verified': True})
    VendorProfile.objects.get_or_create(user=provider_user, defaults={'mobile': '9876500002', 'company_name': 'Ranchi Pro Care', 'location': 'Namkum, Ranchi'})

    # Test 1: Category & Product Listing
    req = rf.get('/api/ecommerce/categories/')
    resp = ecom_api.categories_list_api(req)
    assert resp.status_code == 200, "Categories API failed"
    data = json.loads(resp.content)
    assert len(data['categories']) > 0, "No categories returned"
    print(f"✓ E-Commerce Categories Listing: {len(data['categories'])} categories verified.")

    # Test 2: Product Listing & Search
    req = rf.get('/api/ecommerce/products/?search=RO')
    resp = ecom_api.products_list_api(req)
    assert resp.status_code == 200, "Products API failed"
    pdata = json.loads(resp.content)
    assert len(pdata['products']) > 0, "No products matched 'RO'"
    sample_product_id = pdata['products'][0]['id']
    initial_stock = pdata['products'][0]['stock_quantity']
    print(f"✓ Products Search API: Found '{pdata['products'][0]['title']}' (Stock: {initial_stock}).")

    # Test 3: Add to Cart
    Cart.objects.filter(user=customer_user).delete()
    req = rf.post(
        '/api/ecommerce/cart/add/',
        data=json.dumps({'product_id': sample_product_id, 'quantity': 2}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {cust_token.key}"
    )
    resp = ecom_api.cart_add_api(req)
    assert resp.status_code == 200, "Cart add failed"
    print("✓ Cart Add API: Successfully added 2 units to customer cart.")

    # Test 4: Checkout Order with Coupon
    req = rf.post(
        '/api/ecommerce/checkout/',
        data=json.dumps({
            'customer_name': 'Sindhiga Customer',
            'customer_phone': '9876500001',
            'address_text': 'Flat 402, Namkum Greens, Ranchi',
            'city': 'Ranchi',
            'coupon_code': 'WELCOME50',
            'payment_method': 'COD'
        }),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {cust_token.key}"
    )
    resp = ecom_api.checkout_order_api(req)
    assert resp.status_code == 200, f"Checkout failed: {resp.content}"
    order_data = json.loads(resp.content)
    order_id = order_data['order_id']
    delivery_otp = order_data['delivery_otp']
    print(f"✓ Checkout Order API: Created Order #{order_data['order_number']} (OTP: {delivery_otp}, Amount: ₹{order_data['total_amount']}).")

    # Verify stock deduction
    refreshed_p = Product.objects.get(id=sample_product_id)
    assert refreshed_p.stock_quantity == initial_stock - 2, "Stock deduction mismatch"
    print(f"✓ Stock Inventory Check: Stock decremented correctly to {refreshed_p.stock_quantity}.")

    # Test 5: Admin Confirms & Packs Order
    req = rf.post(
        f'/api/admin/orders/{order_id}/status/',
        data=json.dumps({'status': 'PACKED'}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {admin_token.key}"
    )
    resp = admin_api.admin_order_update_status_api(req, order_id)
    assert resp.status_code == 200, "Admin pack order failed"
    print("✓ Admin Pack Order API: Order status transitioned to PACKED.")

    # Test 6: Admin Assigns Delivery Partner
    req = rf.post(
        f'/api/admin/orders/{order_id}/assign-delivery/',
        data=json.dumps({'partner_id': delivery_user.id}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {admin_token.key}"
    )
    resp = admin_api.admin_assign_delivery_partner_api(req, order_id)
    assert resp.status_code == 200, "Admin assign delivery partner failed"
    print(f"✓ Admin Assign Partner API: Assigned to {delivery_user.username}.")

    # Test 7: Delivery Partner Accepts Order
    req = rf.post(
        f'/api/delivery/orders/{order_id}/respond/',
        data=json.dumps({'action': 'accept'}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {deliv_token.key}"
    )
    resp = delivery_api.delivery_respond_order_api(req, order_id)
    assert resp.status_code == 200, "Delivery partner accept failed"
    print("✓ Delivery Partner Respond API: Partner accepted order.")

    # Test 8: Delivery Partner Marks Picked Up & Out For Delivery
    req = rf.post(f'/api/delivery/orders/{order_id}/pickup/', HTTP_AUTHORIZATION=f"Bearer {deliv_token.key}")
    resp = delivery_api.delivery_mark_picked_up_api(req, order_id)
    assert resp.status_code == 200

    req = rf.post(f'/api/delivery/orders/{order_id}/out-for-delivery/', HTTP_AUTHORIZATION=f"Bearer {deliv_token.key}")
    resp = delivery_api.delivery_mark_out_for_delivery_api(req, order_id)
    assert resp.status_code == 200
    print("✓ Delivery Logistics: Successfully updated to PICKED_UP and OUT_FOR_DELIVERY.")

    # Test 9: Delivery Verification with OTP & Payout
    req = rf.post(
        f'/api/delivery/orders/{order_id}/verify-complete/',
        data=json.dumps({'otp': delivery_otp}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {deliv_token.key}"
    )
    resp = delivery_api.delivery_verify_and_complete_api(req, order_id)
    assert resp.status_code == 200, f"Delivery verify failed: {resp.content}"
    deliv_res = json.loads(resp.content)
    print(f"✓ Delivery Verification & OTP API: Delivered! Payout of ₹{deliv_res['payout_credited']} credited to partner.")

    # Test 10: Customer Service Booking with Time Slot
    slot = ServiceTimeSlot.objects.filter(is_active=True).first()
    quick_service = QuickService.objects.first()
    if not quick_service:
        quick_service = QuickService.objects.create(vendor=provider_user, title="AC Servicing & Gas Top-up", base_price=Decimal('499.00'), status='active')

    req = rf.post(
        '/api/services/book-with-slot/',
        data=json.dumps({
            'service_id': quick_service.id,
            'booking_date': '2026-11-20',
            'time_slot_id': slot.id if slot else None,
            'address': 'Main Road, Namkum, Ranchi'
        }),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {cust_token.key}"
    )
    resp = services_api.book_service_with_slot_api(req)
    assert resp.status_code == 200, f"Service booking failed: {resp.content}"
    sb_data = json.loads(resp.content)
    booking_id = sb_data['booking_id']
    service_otp = sb_data['otp_code']
    print(f"✓ Home Service Booking API: Created Booking #{booking_id} with slot '{sb_data['time_slot']}' (OTP: {service_otp}).")

    # Test 11: Admin Assigns Service Provider
    req = rf.post(
        f'/api/admin/service-bookings/{booking_id}/assign-provider/',
        data=json.dumps({'provider_id': provider_user.id}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {admin_token.key}"
    )
    resp = admin_api.admin_assign_service_provider_api(req, booking_id)
    assert resp.status_code == 200, "Admin assign provider failed"
    print(f"✓ Admin Assign Service Provider: Assigned to {provider_user.username}.")

    # Test 12: Service Provider Accepts & Updates Status to Heading, In-Progress
    req = rf.post(
        f'/api/provider/bookings/{booking_id}/respond/',
        data=json.dumps({'action': 'accept'}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {prov_token.key}"
    )
    resp = provider_api.provider_respond_booking_api(req, booking_id)
    assert resp.status_code == 200

    req = rf.post(
        f'/api/provider/bookings/{booking_id}/status/',
        data=json.dumps({'status': 'heading'}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {prov_token.key}"
    )
    resp = provider_api.provider_update_job_status_api(req, booking_id)
    assert resp.status_code == 200

    req = rf.post(
        f'/api/provider/bookings/{booking_id}/status/',
        data=json.dumps({'status': 'in_progress'}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {prov_token.key}"
    )
    resp = provider_api.provider_update_job_status_api(req, booking_id)
    assert resp.status_code == 200
    print("✓ Service Provider Status Lifecycle: heading -> in_progress verified.")

    # Test 13: Service Provider Completes Service with OTP
    req = rf.post(
        f'/api/provider/bookings/{booking_id}/complete/',
        data=json.dumps({'otp': service_otp}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f"Bearer {prov_token.key}"
    )
    resp = provider_api.provider_complete_service_api(req, booking_id)
    assert resp.status_code == 200, f"Provider complete failed: {resp.content}"
    prov_res = json.loads(resp.content)
    print(f"✓ Service Provider OTP Verification: Completed! Payout of ₹{prov_res['payout_credited']} credited to vendor wallet.")

    # Test 14: Admin Platform KPIs
    req = rf.get('/api/admin/kpis/', HTTP_AUTHORIZATION=f"Bearer {admin_token.key}")
    resp = admin_api.admin_kpis_api(req)
    assert resp.status_code == 200
    kpis = json.loads(resp.content)['kpis']
    print(f"✓ Admin KPIs: Orders={kpis['total_orders']}, Services={kpis['total_service_bookings']}, Delivered={kpis['delivered_orders']}, Revenue=₹{kpis['total_revenue']}.")

    print("==================================================")
    print("ALL 14 SINDHIGA END-TO-END FLOW TESTS PASSED! 100% SUCCESS")
    print("==================================================")

if __name__ == '__main__':
    run_tests()
