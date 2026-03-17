# HillPing — Property & Room endpoints

import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from ...database.session import getdb
from ...modals.masters import User
from ...modals.property import Property, Room, PropertyPhoto, PropertyAmenity, Amenity, DateBlock
from ...schemas.propertySchema import (
    PropertyCreate, PropertyUpdate, PropertyResponse, PropertyListItem,
    StatusUpdate, RoomCreate, RoomUpdate, RoomResponse,
    PropertyPhotoResponse, DateBlockCreate, DateBlockResponse,
)
from ...core.config import settings
from ...utils.utils import get_current_user, require_owner, require_admin, require_role

router = APIRouter(tags=["properties"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_property_or_404(property_id: int, db: Session) -> Property:
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _check_ownership(prop: Property, user: User):
    if user.role != "admin" and prop.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this property")


def _build_list_item(prop: Property, db: Session) -> dict:
    """Build a PropertyListItem dict from a Property ORM object."""
    cover = db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == prop.id, PropertyPhoto.is_cover == True
    ).first()
    min_price = db.query(func.min(Room.price_weekday)).filter(
        Room.property_id == prop.id, Room.is_available == True
    ).scalar()
    return {
        "id": prop.id,
        "name": prop.name,
        "city": prop.city,
        "state": prop.state,
        "property_type": prop.property_type,
        "status": prop.status,
        "is_verified": prop.is_verified,
        "is_instant_confirm": prop.is_instant_confirm,
        "cover_photo": cover.url if cover else None,
        "price_min": min_price,
        "rating_avg": None,  # TODO: compute from reviews
        "owner_name": prop.owner.name if prop.owner else None,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
    }


# ── Property CRUD ─────────────────────────────────────────────────────────────

@router.post("/", response_model=PropertyResponse)
def create_property(
    data: PropertyCreate,
    owner_id: Optional[int] = Query(default=None),
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """
    Owner creates a new property listing.
    Admin can create on behalf of an owner by passing ?owner_id=<id>.
    """
    if current_user.role == "admin":
        if not owner_id:
            raise HTTPException(status_code=400, detail="Admin must specify owner_id")
        target_owner = db.query(User).filter(User.id == owner_id, User.role == "owner").first()
        if not target_owner:
            raise HTTPException(status_code=404, detail="Owner not found")
        resolved_owner_id = owner_id
    elif current_user.role == "owner":
        resolved_owner_id = current_user.id
    else:
        raise HTTPException(status_code=403, detail="Only owners and admins can create properties")

    prop = Property(
        owner_id=resolved_owner_id,
        name=data.name,
        description=data.description,
        address=data.address,
        city=data.city,
        state=data.state,
        latitude=data.latitude,
        longitude=data.longitude,
        property_type=data.property_type,
        cancellation_policy=data.cancellation_policy,
        status="offline",
    )
    db.add(prop)
    db.flush()

    # Attach amenities
    if data.amenity_ids:
        existing = db.query(Amenity.id).filter(Amenity.id.in_(data.amenity_ids)).all()
        existing_ids = {a.id for a in existing}
        for aid in data.amenity_ids:
            if aid in existing_ids:
                db.add(PropertyAmenity(property_id=prop.id, amenity_id=aid))

    db.commit()
    db.refresh(prop)
    return _property_response(prop, db)


@router.get("/{property_id}/check-availability")
def check_availability(
    property_id: int,
    check_in: str = Query(...),
    check_out: str = Query(...),
    guests: int = Query(default=1, ge=1),
    db: Session = Depends(getdb),
):
    """
    Public: check if a property has available rooms for given dates.
    No authentication required.
    """
    import datetime as dt

    prop = _get_property_or_404(property_id, db)

    if prop.status not in ("online", "full"):
        return {"available": False, "reason": "Property is currently offline"}

    try:
        ci = dt.date.fromisoformat(check_in)
        co = dt.date.fromisoformat(check_out)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if co <= ci:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in")

    # Get all rooms
    rooms = db.query(Room).filter(
        Room.property_id == property_id,
        Room.is_available == True,
    ).all()

    if not rooms:
        return {"available": False, "reason": "No rooms available"}

    # Filter by capacity
    suitable_rooms = [r for r in rooms if r.capacity >= guests]
    if not suitable_rooms:
        return {
            "available": False,
            "reason": f"No rooms available for {guests} guest(s). Max capacity: {max(r.capacity for r in rooms)}",
        }

    # Check date blocks
    stay_dates = []
    d = ci
    while d < co:
        stay_dates.append(d)
        d += dt.timedelta(days=1)

    available_rooms = []
    for room in suitable_rooms:
        blocked = db.query(DateBlock).filter(
            DateBlock.property_id == property_id,
            DateBlock.block_date.in_(stay_dates),
            (DateBlock.room_id == room.id) | (DateBlock.room_id == None),
        ).first()

        if not blocked:
            available_rooms.append({
                "id": room.id,
                "name": room.name,
                "room_type": room.room_type,
                "capacity": room.capacity,
                "price_weekday": float(room.price_weekday),
                "price_weekend": float(room.price_weekend),
            })

    if not available_rooms:
        return {"available": False, "reason": "All rooms are blocked for selected dates"}

    return {
        "available": True,
        "rooms": available_rooms,
        "nights": len(stay_dates),
        "check_in": check_in,
        "check_out": check_out,
    }


@router.get("/", response_model=list[PropertyListItem])
def list_properties(
    city: Optional[str] = None,
    property_type: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    guests: Optional[int] = None,
    ne_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    ne_lng: Optional[float] = Query(default=None, ge=-180, le=180),
    sw_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    sw_lng: Optional[float] = Query(default=None, ge=-180, le=180),
    sort_by: str = Query(default="created_at", pattern=r'^(created_at|price|rating)$'),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(getdb),
):
    """Public: browse available properties with filters."""
    q = db.query(Property).filter(Property.status.in_(["online", "full"]))

    if city:
        q = q.filter(func.lower(Property.city) == city.lower())
    if property_type:
        q = q.filter(Property.property_type == property_type)

    # Map bounds filter
    if all(v is not None for v in [ne_lat, ne_lng, sw_lat, sw_lng]):
        q = q.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None),
            Property.latitude.between(sw_lat, ne_lat),
            Property.longitude.between(sw_lng, ne_lng),
        )

    # Filter by room price/capacity
    if price_min is not None or price_max is not None or guests is not None:
        room_q = db.query(Room.property_id).filter(Room.is_available == True)
        if price_min is not None:
            room_q = room_q.filter(Room.price_weekday >= price_min)
        if price_max is not None:
            room_q = room_q.filter(Room.price_weekday <= price_max)
        if guests is not None:
            room_q = room_q.filter(Room.capacity >= guests)
        matching_ids = [r.property_id for r in room_q.distinct().all()]
        q = q.filter(Property.id.in_(matching_ids))

    if sort_by == "price":
        # Sort by minimum room price
        q = q.outerjoin(Room).group_by(Property.id).order_by(func.min(Room.price_weekday).asc())
    else:
        q = q.order_by(Property.created_at.desc())

    properties = q.offset(skip).limit(limit).all()
    return [_build_list_item(p, db) for p in properties]


@router.get("/my", response_model=list[PropertyListItem])
def my_properties(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner's own properties."""
    props = db.query(Property).filter(Property.owner_id == current_user.id).order_by(Property.created_at.desc()).all()
    return [_build_list_item(p, db) for p in props]


@router.get("/{property_id}", response_model=PropertyResponse)
def get_property(property_id: int, db: Session = Depends(getdb)):
    """Public: view property detail."""
    prop = _get_property_or_404(property_id, db)
    return _property_response(prop, db)


@router.patch("/{property_id}", response_model=PropertyResponse)
def update_property(
    property_id: int,
    data: PropertyUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Owner or admin updates a property."""
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)

    update_data = data.model_dump(exclude_unset=True)
    amenity_ids = update_data.pop("amenity_ids", None)

    for field, value in update_data.items():
        setattr(prop, field, value)

    # Replace amenities if provided
    if amenity_ids is not None:
        db.query(PropertyAmenity).filter(PropertyAmenity.property_id == prop.id).delete()
        existing = db.query(Amenity.id).filter(Amenity.id.in_(amenity_ids)).all()
        existing_ids = {a.id for a in existing}
        for aid in amenity_ids:
            if aid in existing_ids:
                db.add(PropertyAmenity(property_id=prop.id, amenity_id=aid))

    db.commit()
    db.refresh(prop)
    return _property_response(prop, db)


@router.patch("/{property_id}/status")
def update_status(
    property_id: int,
    data: StatusUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Owner or admin toggles property status: online / offline / full."""
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    prop.status = data.status
    db.commit()
    return {"detail": f"Property status set to {data.status}"}


@router.delete("/{property_id}")
def delete_property(
    property_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Owner or admin deletes a property."""
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    db.delete(prop)
    db.commit()
    return {"detail": "Property deleted"}


# ── Rooms ─────────────────────────────────────────────────────────────────────

@router.post("/{property_id}/rooms", response_model=RoomResponse)
def add_room(
    property_id: int,
    data: RoomCreate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    room = Room(property_id=prop.id, **data.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.patch("/{property_id}/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    property_id: int,
    room_id: int,
    data: RoomUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    room = db.query(Room).filter(Room.id == room_id, Room.property_id == prop.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/{property_id}/rooms/{room_id}")
def delete_room(
    property_id: int,
    room_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    room = db.query(Room).filter(Room.id == room_id, Room.property_id == prop.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    db.delete(room)
    db.commit()
    return {"detail": "Room deleted"}


# ── Date Blocks ───────────────────────────────────────────────────────────────

@router.post("/{property_id}/blocks", response_model=DateBlockResponse)
def block_date(
    property_id: int,
    data: DateBlockCreate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    block = DateBlock(property_id=prop.id, **data.model_dump())
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


@router.get("/{property_id}/blocks", response_model=list[DateBlockResponse])
def list_blocks(
    property_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    return db.query(DateBlock).filter(DateBlock.property_id == prop.id).all()


@router.delete("/{property_id}/blocks/{block_id}")
def unblock_date(
    property_id: int,
    block_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    prop = _get_property_or_404(property_id, db)
    _check_ownership(prop, current_user)
    block = db.query(DateBlock).filter(DateBlock.id == block_id, DateBlock.property_id == prop.id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Date block not found")
    db.delete(block)
    db.commit()
    return {"detail": "Date block removed"}


# ── Photos ────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/{property_id}/photos", response_model=PropertyPhotoResponse)
async def upload_photo(
    property_id: int,
    file: UploadFile = File(...),
    is_cover: bool = Query(default=False),
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Upload a photo for a property. Owner or admin."""
    prop = _get_property_or_404(property_id, db)
    if current_user.role != "admin":
        _check_ownership(prop, current_user)

    # Validate extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed. Use: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read & validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 5 MB.")

    # Save file
    upload_dir = os.path.join(settings.PROPERTY_PHOTO_DIR, str(property_id))
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as f:
        f.write(content)

    # If marking as cover, unset previous cover
    if is_cover:
        db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.is_cover == True,
        ).update({"is_cover": False})

    # Get next display order
    max_order = db.query(func.max(PropertyPhoto.display_order)).filter(
        PropertyPhoto.property_id == property_id
    ).scalar() or 0

    photo = PropertyPhoto(
        property_id=property_id,
        url=f"/uploads/property_photos/{property_id}/{filename}",
        is_cover=is_cover,
        display_order=max_order + 1,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


@router.get("/{property_id}/photos", response_model=list[PropertyPhotoResponse])
def list_photos(property_id: int, db: Session = Depends(getdb)):
    """List all photos for a property."""
    _get_property_or_404(property_id, db)
    return db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == property_id
    ).order_by(PropertyPhoto.display_order).all()


@router.patch("/{property_id}/photos/{photo_id}/cover")
def set_cover_photo(
    property_id: int,
    photo_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Set a photo as the cover image."""
    prop = _get_property_or_404(property_id, db)
    if current_user.role != "admin":
        _check_ownership(prop, current_user)

    photo = db.query(PropertyPhoto).filter(
        PropertyPhoto.id == photo_id,
        PropertyPhoto.property_id == property_id,
    ).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Unset previous cover
    db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == property_id,
        PropertyPhoto.is_cover == True,
    ).update({"is_cover": False})

    photo.is_cover = True
    db.commit()
    return {"detail": "Cover photo updated"}


@router.delete("/{property_id}/photos/{photo_id}")
def delete_photo(
    property_id: int,
    photo_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Delete a property photo."""
    prop = _get_property_or_404(property_id, db)
    if current_user.role != "admin":
        _check_ownership(prop, current_user)

    photo = db.query(PropertyPhoto).filter(
        PropertyPhoto.id == photo_id,
        PropertyPhoto.property_id == property_id,
    ).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Delete file from disk
    filepath = os.path.join(os.getcwd(), photo.url.lstrip("/"))
    if os.path.exists(filepath):
        os.remove(filepath)

    db.delete(photo)
    db.commit()
    return {"detail": "Photo deleted"}


# ── Response builder ──────────────────────────────────────────────────────────

def _property_response(prop: Property, db: Session) -> dict:
    """Build a full PropertyResponse dict with nested amenities."""
    amenity_links = db.query(PropertyAmenity).filter(PropertyAmenity.property_id == prop.id).all()
    amenities = []
    for link in amenity_links:
        a = db.query(Amenity).filter(Amenity.id == link.amenity_id).first()
        if a:
            amenities.append(a)

    owner_info = None
    if prop.owner:
        owner_info = {
            "id": prop.owner.id,
            "name": prop.owner.name,
            "is_verified_owner": prop.owner.is_verified_owner,
        }

    return {
        "id": prop.id,
        "name": prop.name,
        "description": prop.description,
        "address": prop.address,
        "city": prop.city,
        "state": prop.state,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "property_type": prop.property_type,
        "cancellation_policy": prop.cancellation_policy,
        "status": prop.status,
        "is_verified": prop.is_verified,
        "is_instant_confirm": prop.is_instant_confirm,
        "created_at": prop.created_at,
        "rooms": prop.rooms,
        "photos": prop.photos,
        "amenities": amenities,
        "owner": owner_info,
    }
