# HillPing — Wishlist endpoints

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...database.session import getdb
from ...modals.masters import User
from ...modals.property import Property, PropertyPhoto, Room
from ...modals.wishlist import Wishlist
from ...schemas.wishlistSchema import WishlistAdd, WishlistResponse
from ...utils.utils import require_guest

router = APIRouter(tags=["wishlist"])


@router.post("/", response_model=WishlistResponse, status_code=201)
def add_to_wishlist(
    data: WishlistAdd,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """Add a property to the guest's wishlist."""
    prop = db.query(Property).filter(Property.id == data.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    existing = db.query(Wishlist).filter(
        Wishlist.user_id == current_user.id,
        Wishlist.property_id == data.property_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Property already in wishlist")

    item = Wishlist(user_id=current_user.id, property_id=data.property_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{property_id}")
def remove_from_wishlist(
    property_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """Remove a property from the guest's wishlist."""
    item = db.query(Wishlist).filter(
        Wishlist.user_id == current_user.id,
        Wishlist.property_id == property_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Property not in wishlist")
    db.delete(item)
    db.commit()
    return {"detail": "Removed from wishlist"}


@router.get("/")
def list_wishlist(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """List all wishlisted properties for the current guest."""
    items = db.query(Wishlist).filter(
        Wishlist.user_id == current_user.id
    ).order_by(Wishlist.created_at.desc()).all()

    result = []
    for item in items:
        prop = item.property
        if not prop:
            continue
        cover = db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == prop.id, PropertyPhoto.is_cover == True
        ).first()
        from ...services.pricing import room_min_guest_nightly

        rooms_avail = db.query(Room).filter(
            Room.property_id == prop.id, Room.is_available == True
        ).all()
        min_price = min((room_min_guest_nightly(r) for r in rooms_avail), default=None) if rooms_avail else None
        result.append({
            "id": prop.id,
            "name": prop.name,
            "city": prop.city,
            "state": prop.state,
            "property_type": prop.property_type,
            "status": prop.status,
            "is_verified": prop.is_verified,
            "is_instant_confirm": prop.is_instant_confirm,
            "cover_photo": cover.url if cover else None,
            "price_min": float(min_price) if min_price is not None else None,
            "rating_avg": None,
            "owner_name": prop.owner.name if prop.owner else None,
            "latitude": prop.latitude,
            "longitude": prop.longitude,
            "wishlisted_at": item.created_at,
        })
    return result


@router.get("/check/{property_id}")
def check_wishlist(
    property_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """Check if a property is in the guest's wishlist."""
    exists = db.query(Wishlist).filter(
        Wishlist.user_id == current_user.id,
        Wishlist.property_id == property_id,
    ).first()
    return {"wishlisted": exists is not None}
