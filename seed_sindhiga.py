import os
import django
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from myapp.models import (
    SiteBranding, ProductCategory, ProductSubCategory, Product,
    ServiceTimeSlot, Coupon, CustomUser, CustomerAddress
)

def seed():
    print("Seeding Sindhiga Enterprises initial data...")

    # 1. Site Branding
    branding, created = SiteBranding.objects.get_or_create(id=1)
    branding.site_title = "Sindhiga Enterprises"
    branding.tagline = "E-Commerce & Home Services Platform"
    branding.contact_email = "support@sindhiga.com"
    branding.support_phone = "+91 98765 01234"
    branding.address = "Sindhiga Towers, Namkum Main Road, Ranchi, Jharkhand"
    branding.copyright_text = "© 2026 Sindhiga Enterprises. All rights reserved."
    branding.save()
    print("✓ Site branding updated to Sindhiga Enterprises")

    # 2. Service Time Slots
    slots = [
        ("09:00 AM", "11:00 AM", "09:00 AM - 11:00 AM (Morning)", 1),
        ("11:00 AM", "01:00 PM", "11:00 AM - 01:00 PM (Late Morning)", 2),
        ("02:00 PM", "04:00 PM", "02:00 PM - 04:00 PM (Afternoon)", 3),
        ("04:00 PM", "06:00 PM", "04:00 PM - 06:00 PM (Evening)", 4),
        ("06:00 PM", "08:00 PM", "06:00 PM - 08:00 PM (Night)", 5),
    ]
    for start, end, label, order in slots:
        slot, _ = ServiceTimeSlot.objects.get_or_create(
            label=label,
            defaults={"start_time": start, "end_time": end, "order": order, "is_active": True}
        )
    print("✓ Service time slots populated")

    # 3. Coupons
    coupons = [
        {
            "code": "WELCOME50",
            "description": "Flat ₹50 OFF on your first e-commerce order",
            "discount_type": "fixed",
            "discount_value": 50.00,
            "min_order_amount": 299.00,
            "max_discount_amount": 50.00,
        },
        {
            "code": "SINDHIGA10",
            "description": "10% Instant OFF on all hardware and home care supplies",
            "discount_type": "percentage",
            "discount_value": 10.00,
            "min_order_amount": 499.00,
            "max_discount_amount": 200.00,
        },
        {
            "code": "SUPERDEAL",
            "description": "20% Super Saver discount on orders above ₹999",
            "discount_type": "percentage",
            "discount_value": 20.00,
            "min_order_amount": 999.00,
            "max_discount_amount": 500.00,
        },
    ]
    for cdata in coupons:
        coupon, _ = Coupon.objects.get_or_create(
            code=cdata["code"],
            defaults={
                "description": cdata["description"],
                "discount_type": cdata["discount_type"],
                "discount_value": cdata["discount_value"],
                "min_order_amount": cdata["min_order_amount"],
                "max_discount_amount": cdata["max_discount_amount"],
                "valid_until": timezone.now() + timedelta(days=365),
                "usage_limit": 1000,
                "is_active": True
            }
        )
    print("✓ Promotional coupons created")

    # 4. E-Commerce Categories & Subcategories
    catalog_structure = [
        {
            "name": "Home Appliances & Spares",
            "slug": "home-appliances-spares",
            "icon": "bi-cpu",
            "description": "Genuine replacement parts, filters, and maintenance spares for household appliances.",
            "subs": ["Filters & Purifier Spares", "AC & Cooler Parts", "Washing Machine Accessories"]
        },
        {
            "name": "Cleaning & Sanitation",
            "slug": "cleaning-sanitation",
            "icon": "bi-stars",
            "description": "Professional-grade cleaning solutions, sanitizers, floor mops, and household cleaners.",
            "subs": ["Deep Clean Chemicals & Sprays", "Brushes, Mops & Wipers", "Disinfectants & Repellents"]
        },
        {
            "name": "Electrical & Lighting",
            "slug": "electrical-lighting",
            "icon": "bi-lightbulb",
            "description": "Heavy-duty electrical fittings, modular switches, cables, and energy-saving LED illumination.",
            "subs": ["LED Bulbs & Smart Lighting", "Switches, Sockets & MCBs", "Cables & Wiring Essentials"]
        },
        {
            "name": "Plumbing & Bath Fittings",
            "slug": "plumbing-bath-fittings",
            "icon": "bi-droplet",
            "description": "Durable brass taps, CPVC pipes, flexible hoses, valves, and bathroom fixtures.",
            "subs": ["Taps & Faucets", "Pipes, Valves & Connectors", "Showers & Health Faucets"]
        },
        {
            "name": "Tools & Hardware",
            "slug": "tools-hardware",
            "icon": "bi-tools",
            "description": "Professional toolkit essentials, drills, measuring tapes, adhesives, and fastening hardware.",
            "subs": ["Hand Tool Kits", "Power Drills & Bits", "Adhesives & Sealants"]
        }
    ]

    sub_objects = {}
    for i, cat_info in enumerate(catalog_structure, 1):
        cat, _ = ProductCategory.objects.get_or_create(
            name=cat_info["name"],
            defaults={
                "slug": cat_info["slug"],
                "icon_class": cat_info["icon"],
                "description": cat_info["description"],
                "order": i,
                "status": "active"
            }
        )
        for j, sub_name in enumerate(cat_info["subs"], 1):
            sub_slug = sub_name.lower().replace(" & ", "-").replace(" ", "-").replace(",", "")
            sub, _ = ProductSubCategory.objects.get_or_create(
                category=cat,
                name=sub_name,
                defaults={
                    "slug": sub_slug,
                    "order": j,
                    "status": "active"
                }
            )
            sub_objects[sub_name] = (cat, sub)
    print("✓ E-Commerce categories and subcategories created")

    # 5. Products
    products_data = [
        {
            "title": "Universal RO Water Purifier Membrane (80 GPD)",
            "sub": "Filters & Purifier Spares",
            "brand": "Aquaflow",
            "description": "High-rejection 80 GPD reverse osmosis membrane suitable for all domestic water purifiers. Removes heavy metals and dissolved solids.",
            "specs": {"Capacity": "80 GPD", "Material": "Polyamide Thin Film", "Compatibility": "Universal domestic RO systems", "Warranty": "6 Months"},
            "mrp": 1299.00,
            "sale": 749.00,
            "stock": 45,
            "sku": "SND-RO-80GPD",
            "unit": "1 Piece",
            "rating": 4.9,
            "reviews_count": 38,
            "image_url": "https://images.unsplash.com/photo-1585338107529-13afc5f02586?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Anti-Vibration Rubber Washing Machine Pads (Set of 4)",
            "sub": "Washing Machine Accessories",
            "brand": "DampStop",
            "description": "Shock-absorbing anti-skid rubber feet pads to reduce noise and prevent front-load and top-load washing machines from walking.",
            "specs": {"Quantity": "4 Pads", "Material": "High-density Resin Rubber", "Load Capacity": "Up to 500 KG", "Color": "Grey/Black"},
            "mrp": 599.00,
            "sale": 299.00,
            "stock": 120,
            "sku": "SND-WASH-PAD4",
            "unit": "Pack of 4",
            "rating": 4.7,
            "reviews_count": 64,
            "image_url": "https://images.unsplash.com/photo-1626806787461-102c1bfaaea1?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Industrial Heavy-Duty Drain & Pipe Unblocker Cleaner Gel (1L)",
            "sub": "Deep Clean Chemicals & Sprays",
            "brand": "ClogFree Pro",
            "description": "Fast-acting thick caustic liquid gel that cuts through standing water to dissolve grease, hair, food debris, and soap scum in kitchen sinks and bathroom drains.",
            "specs": {"Volume": "1000 ml", "Form": "Thick Gel", "Action Time": "15-30 Minutes", "Safe On": "PVC, Ceramic, Cast Iron Pipes"},
            "mrp": 450.00,
            "sale": 279.00,
            "stock": 70,
            "sku": "SND-CLN-DRN1L",
            "unit": "1 Litre Bottle",
            "rating": 4.8,
            "reviews_count": 52,
            "image_url": "https://images.unsplash.com/photo-1585421514738-01798e348b17?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Microfiber 360 Spin Mop with Stainless Steel Wringer Bucket",
            "sub": "Brushes, Mops & Wipers",
            "brand": "Sindhiga CleanCare",
            "description": "Ergonomic stainless steel spinner bucket with dual wheels and 2 super-absorbent microfiber mop heads for spotless wet and dry floor wiping.",
            "specs": {"Bucket Material": "Stainless Steel + Virgin Plastic", "Handle": "Telescopic Stainless Steel", "Refills Included": "2 Heads", "Warranty": "1 Year"},
            "mrp": 1999.00,
            "sale": 1199.00,
            "stock": 35,
            "sku": "SND-MOP-SS360",
            "unit": "1 Complete Kit",
            "rating": 4.9,
            "reviews_count": 89,
            "image_url": "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Smart Wi-Fi 9W B22 Multi-Color LED Bulb",
            "sub": "LED Bulbs & Smart Lighting",
            "brand": "LumiSmart",
            "description": "16 million colors RGB + Tunable White LED bulb compatible with Alexa and Google Assistant. Schedule routines and adjust brightness from mobile.",
            "specs": {"Base Type": "B22", "Wattage": "9W", "Luminous Flux": "810 Lumens", "Connectivity": "2.4GHz Wi-Fi", "Warranty": "2 Years"},
            "mrp": 899.00,
            "sale": 449.00,
            "stock": 60,
            "sku": "SND-LED-SMT9W",
            "unit": "1 Piece",
            "rating": 4.8,
            "reviews_count": 41,
            "image_url": "https://images.unsplash.com/photo-1550985616-10810253b84d?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Double Pole 32A Miniature Circuit Breaker (MCB) C-Curve",
            "sub": "Switches, Sockets & MCBs",
            "brand": "VoltGuard",
            "description": "ISI certified dual pole MCB designed for air conditioner, geyser, and main domestic distribution board overload and short-circuit protection.",
            "specs": {"Poles": "2 Pole (DP)", "Rated Current": "32 Ampere", "Tripping Curve": "C-Type", "Breaking Capacity": "10 kA", "Certification": "IS/IEC 60898"},
            "mrp": 620.00,
            "sale": 389.00,
            "stock": 50,
            "sku": "SND-MCB-DP32A",
            "unit": "1 Piece",
            "rating": 4.9,
            "reviews_count": 27,
            "image_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Solid Brass High-Pressure Chrome Finish Health Faucet Hand Spray",
            "sub": "Showers & Health Faucets",
            "brand": "AquaElite",
            "description": "Premium mirror-chrome polished solid brass toilet spray gun with anti-burst 1.2m stainless steel flexible hose and wall holder bracket.",
            "specs": {"Material": "Solid Brass Body + SS 304 Hose", "Finish": "Multi-layer Chrome", "Hose Length": "1.2 Metres", "Pressure Rating": "Up to 5 Bar"},
            "mrp": 1250.00,
            "sale": 699.00,
            "stock": 80,
            "sku": "SND-PLM-HF01",
            "unit": "1 Set (Gun + Hose + Holder)",
            "rating": 4.8,
            "reviews_count": 73,
            "image_url": "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Heavy-Duty Multi-Bit Ratchet Screwdriver & 42-Piece Tool Set",
            "sub": "Hand Tool Kits",
            "brand": "ForgeMaster",
            "description": "Comprehensive domestic repair tool kit with claw hammer, combination pliers, precision bits, screwdriver, test pen, and insulating tape in a blow-mold case.",
            "specs": {"Pieces": "42 Tools", "Steel Grade": "Chrome Vanadium (CR-V)", "Case": "Impact Resistant Carry Box", "Warranty": "Lifetime on Hand Tools"},
            "mrp": 2499.00,
            "sale": 1399.00,
            "stock": 25,
            "sku": "SND-TOOL-KIT42",
            "unit": "1 Box Set",
            "rating": 4.9,
            "reviews_count": 95,
            "image_url": "https://images.unsplash.com/photo-1581147036324-c17ac41dfa6c?w=500&auto=format&fit=crop&q=60"
        },
        {
            "title": "Waterproof Silicone Bathroom & Kitchen Gap Sealant (280ml)",
            "sub": "Adhesives & Sealants",
            "brand": "SealPro",
            "description": "Anti-fungal waterproof neutral cure silicone sealant for sealing joints around kitchen sinks, bathtubs, tile joints, and window glass edges.",
            "specs": {"Volume": "280 ml", "Color": "Clear / Transparent", "Curing Time": "24 Hours Full Cure", "Temperature Resistance": "-40°C to +150°C"},
            "mrp": 380.00,
            "sale": 220.00,
            "stock": 90,
            "sku": "SND-ADH-SIL280",
            "unit": "1 Cartridge Tube",
            "rating": 4.7,
            "reviews_count": 31,
            "image_url": "https://images.unsplash.com/photo-1504148455328-c376907d081c?w=500&auto=format&fit=crop&q=60"
        }
    ]

    for p in products_data:
        cat, sub = sub_objects.get(p["sub"], (None, None))
        prod, created = Product.objects.get_or_create(
            sku=p["sku"],
            defaults={
                "title": p["title"],
                "category": cat,
                "subcategory": sub,
                "brand": p["brand"],
                "description": p["description"],
                "specifications": p["specs"],
                "mrp_price": p["mrp"],
                "sale_price": p["sale"],
                "stock_quantity": p["stock"],
                "unit": p["unit"],
                "rating": p["rating"],
                "reviews_count": p["reviews_count"],
                "image_url": p["image_url"],
                "status": "active",
                "is_featured": True
            }
        )
    print("✓ Initial product catalog seeded successfully")
    print("=== Sindhiga Enterprises Initial Seeding Completed ===")

if __name__ == "__main__":
    seed()
