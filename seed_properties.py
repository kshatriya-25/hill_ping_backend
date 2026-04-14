"""
Seed script — creates 25 properties near Yercaud (13.040672, 80.243477)
with rooms, amenities, and photos. All owned by the first owner in the DB.

Usage: python seed_properties.py
"""

import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database.session import SessionLocal
from app.modals.masters import User
from app.modals.property import Property, Room, Amenity, PropertyAmenity, PropertyPhoto

# Center coordinates
CENTER_LAT = 13.040672
CENTER_LNG = 80.243477

PROPERTIES = [
    {"name": "Sunrise Hill Cottage", "type": "cottage", "desc": "Charming cottage with panoramic sunrise views. Perfect for couples and small families.", "addr": "Sunrise Point Road, Yercaud"},
    {"name": "Green Valley Resort", "type": "hotel", "desc": "Full-service resort nestled in lush greenery with restaurant and pool.", "addr": "Green Valley Lane, Yercaud"},
    {"name": "Hilltop Inn", "type": "homestay", "desc": "Cozy hilltop homestay run by a local family. Authentic home-cooked meals.", "addr": "Hilltop Colony, Yercaud"},
    {"name": "Lake View Residency", "type": "hotel", "desc": "Modern hotel overlooking the Yercaud Lake. Walking distance to town centre.", "addr": "Lake Road, Yercaud"},
    {"name": "Misty Mountain Lodge", "type": "cottage", "desc": "Secluded mountain lodge surrounded by coffee plantations. Pure tranquility.", "addr": "Coffee Estate Road, Yercaud"},
    {"name": "The Pepper House", "type": "homestay", "desc": "Heritage bungalow converted to a boutique homestay. Vintage charm meets comfort.", "addr": "Pepper Garden, Yercaud"},
    {"name": "Silver Oak Hotel", "type": "hotel", "desc": "Premium hotel with conference facilities, spa, and multi-cuisine restaurant.", "addr": "Main Road, Yercaud"},
    {"name": "Windmill Cottage", "type": "cottage", "desc": "Quaint cottage near the windmill viewpoint. Stunning sunset views every evening.", "addr": "Windmill Road, Yercaud"},
    {"name": "Rose Garden Villa", "type": "villa", "desc": "Spacious 4-bedroom villa with private garden. Ideal for large groups.", "addr": "Rose Garden Lane, Yercaud"},
    {"name": "Cloud9 Backpackers", "type": "homestay", "desc": "Budget-friendly dorm and private rooms. Great for solo travelers and backpackers.", "addr": "Bus Stand Area, Yercaud"},
    {"name": "Magnolia Resort", "type": "hotel", "desc": "Family resort with kids play area, bonfire spot, and trekking arrangements.", "addr": "Magnolia Drive, Yercaud"},
    {"name": "The Planter's Bungalow", "type": "villa", "desc": "Colonial-era planter's bungalow with 5 bedrooms, sprawling lawns, and a caretaker.", "addr": "Estate Road, Yercaud"},
    {"name": "Bamboo Nest Cottage", "type": "cottage", "desc": "Eco-friendly bamboo cottage with minimal footprint. Solar powered.", "addr": "Forest Edge, Yercaud"},
    {"name": "Panorama Heights Hotel", "type": "hotel", "desc": "360-degree panoramic views from every room. Rooftop restaurant.", "addr": "Shevaroy Hills, Yercaud"},
    {"name": "Jasmine Homestay", "type": "homestay", "desc": "Simple, clean rooms in a family home. Jasmine garden and home-cooked breakfast.", "addr": "Temple Street, Yercaud"},
    {"name": "Emerald Bay Resort", "type": "hotel", "desc": "Luxury resort with infinity pool, spa, and private dining.", "addr": "Emerald Bay Road, Yercaud"},
    {"name": "Cedar Wood Lodge", "type": "cottage", "desc": "Log cabin style lodge made entirely of cedar wood. Fireplace in every room.", "addr": "Cedar Valley, Yercaud"},
    {"name": "The Tea House", "type": "homestay", "desc": "Charming stay amidst tea gardens. Complimentary tea tasting experience.", "addr": "Tea Garden Road, Yercaud"},
    {"name": "Summit View Hotel", "type": "hotel", "desc": "Mid-range hotel at the highest point of Yercaud. Excellent value for money.", "addr": "Summit Road, Yercaud"},
    {"name": "Orchid Valley Cottage", "type": "cottage", "desc": "Hidden gem in the orchid valley. Private waterfall trail from the property.", "addr": "Orchid Valley, Yercaud"},
    {"name": "Royal Crest Hotel", "type": "hotel", "desc": "Grand hotel with ballroom, banquet hall, and royal-themed suites.", "addr": "Main Bazaar Road, Yercaud"},
    {"name": "Fern Hill Homestay", "type": "homestay", "desc": "Peaceful stay among ferns and wildflowers. Bird watching paradise.", "addr": "Fern Hill, Yercaud"},
    {"name": "Golden Sunrise Villa", "type": "villa", "desc": "Private villa with heated pool, BBQ area, and dedicated cook.", "addr": "Sunrise Estate, Yercaud"},
    {"name": "Blue Mountain Hotel", "type": "hotel", "desc": "Business-class hotel with high-speed WiFi, work desks, and meeting rooms.", "addr": "IT Park Road, Yercaud"},
    {"name": "Wildflower Retreat", "type": "cottage", "desc": "Artist's retreat with painting studio, nature trails, and meditation space.", "addr": "Wildflower Lane, Yercaud"},
]

ROOM_TYPES = [
    {"name": "Standard Room", "type": "double", "cap": 2, "weekday": (800, 1500), "weekend": (1200, 2000)},
    {"name": "Deluxe Room", "type": "double", "cap": 2, "weekday": (1500, 2500), "weekend": (2000, 3500)},
    {"name": "Family Suite", "type": "suite", "cap": 4, "weekday": (2500, 4500), "weekend": (3500, 6000)},
    {"name": "Dormitory Bed", "type": "dormitory", "cap": 1, "weekday": (300, 600), "weekend": (500, 900)},
    {"name": "Single Room", "type": "single", "cap": 1, "weekday": (600, 1000), "weekend": (900, 1500)},
    {"name": "Premium Suite", "type": "suite", "cap": 3, "weekday": (3500, 6000), "weekend": (5000, 8000)},
    {"name": "Cottage Room", "type": "double", "cap": 2, "weekday": (1800, 3000), "weekend": (2500, 4000)},
]

AMENITY_LIST = [
    ("WiFi", "wifi", "basics"),
    ("Hot Water", "droplets", "basics"),
    ("Parking", "car", "basics"),
    ("AC", "snowflake", "basics"),
    ("TV", "tv", "basics"),
    ("Restaurant", "utensils", "facilities"),
    ("Room Service", "bell", "facilities"),
    ("Laundry", "shirt", "facilities"),
    ("Pet Friendly", "dog", "facilities"),
    ("Swimming Pool", "waves", "facilities"),
    ("Bonfire", "flame", "facilities"),
    ("Garden", "flower2", "facilities"),
    ("Power Backup", "zap", "safety"),
    ("CCTV", "camera", "safety"),
    ("First Aid", "heart-pulse", "safety"),
]

PHOTO_URLS = [
    "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800",
    "https://images.unsplash.com/photo-1582719508461-905c673771fd?w=800",
    "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800",
    "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800",
    "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800",
    "https://images.unsplash.com/photo-1564501049412-61c2a3083791?w=800",
    "https://images.unsplash.com/photo-1445019980597-93fa8acb246c?w=800",
    "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800",
]

CANCEL_POLICIES = ["flexible", "moderate", "strict"]


def seed():
    db = SessionLocal()

    try:
        # Find an owner to assign properties to
        owner = db.query(User).filter(User.role == "owner").first()
        if not owner:
            print("No owner found. Creating a default owner...")
            from app.utils.utils import get_hashed_password
            owner = User(
                name="Demo Owner",
                username="demo_owner",
                email="owner@hillping.demo",
                phone="+919876543210",
                password_hash=get_hashed_password("Rama@2026"),
                role="owner",
                is_active=True,
            )
            db.add(owner)
            db.flush()
            print(f"  Created owner: @demo_owner (id={owner.id})")

        # Seed amenities if they don't exist
        existing_amenities = {a.name for a in db.query(Amenity).all()}
        amenity_map = {}
        for name, icon, category in AMENITY_LIST:
            if name not in existing_amenities:
                a = Amenity(name=name, icon=icon, category=category)
                db.add(a)
                db.flush()
                amenity_map[name] = a.id
            else:
                a = db.query(Amenity).filter(Amenity.name == name).first()
                amenity_map[name] = a.id
        print(f"  {len(amenity_map)} amenities ready")

        # Create properties
        created = 0
        for i, p in enumerate(PROPERTIES):
            # Check if already exists
            if db.query(Property).filter(Property.name == p["name"]).first():
                print(f"  Skipping '{p['name']}' (already exists)")
                continue

            # Random offset from center (within ~5km)
            lat_offset = random.uniform(-0.03, 0.03)
            lng_offset = random.uniform(-0.03, 0.03)

            prop = Property(
                owner_id=owner.id,
                name=p["name"],
                description=p["desc"],
                address=p["addr"],
                city="Yercaud",
                state="Tamil Nadu",
                latitude=round(CENTER_LAT + lat_offset, 6),
                longitude=round(CENTER_LNG + lng_offset, 6),
                property_type=p["type"],
                cancellation_policy=random.choice(CANCEL_POLICIES),
                status="online",
                is_verified=True,
                is_instant_confirm=random.random() > 0.7,
            )
            db.add(prop)
            db.flush()

            # Add 2-4 rooms per property
            num_rooms = random.randint(2, 4)
            room_templates = random.sample(ROOM_TYPES, min(num_rooms, len(ROOM_TYPES)))
            for j, rt in enumerate(room_templates):
                weekday_price = random.randint(*rt["weekday"])
                weekend_price = random.randint(*rt["weekend"])
                room = Room(
                    property_id=prop.id,
                    name=f"{rt['name']} {j+1}" if num_rooms > 1 else rt["name"],
                    room_type=rt["type"],
                    capacity=rt["cap"],
                    total_rooms=1,
                    price_weekday=weekday_price,
                    price_weekend=weekend_price,
                    is_available=True,
                )
                db.add(room)

            # Add 4-8 random amenities
            num_amenities = random.randint(4, 8)
            chosen_amenities = random.sample(list(amenity_map.keys()), min(num_amenities, len(amenity_map)))
            for a_name in chosen_amenities:
                pa = PropertyAmenity(
                    property_id=prop.id,
                    amenity_id=amenity_map[a_name],
                )
                db.add(pa)

            # Add 2-4 photos
            num_photos = random.randint(2, 4)
            chosen_photos = random.sample(PHOTO_URLS, num_photos)
            for k, url in enumerate(chosen_photos):
                photo = PropertyPhoto(
                    property_id=prop.id,
                    url=url,
                    is_cover=(k == 0),
                    display_order=k,
                )
                db.add(photo)

            created += 1
            print(f"  [{created}] {p['name']} ({p['type']}) — {prop.latitude}, {prop.longitude}")

        db.commit()
        print(f"\nDone! Created {created} properties near Yercaud ({CENTER_LAT}, {CENTER_LNG})")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
