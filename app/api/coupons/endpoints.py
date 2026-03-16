# HillPing — Coupon endpoints

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...modals.coupon import Coupon
from ...modals.property import Property
from ...schemas.couponSchema import (
    CouponCreate, CouponUpdate, CouponResponse,
    CouponValidateRequest, CouponValidateResponse,
)
from ...services.coupon import validate_coupon, apply_coupon, CouponError
from ...utils.utils import get_current_user, require_admin, require_role

router = APIRouter(tags=["coupons"])


@router.post("/", response_model=CouponResponse)
def create_coupon(
    data: CouponCreate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("admin", "owner")),
):
    """
    Admin creates platform-wide coupons.
    Owner creates property-specific coupons (max 3 active).
    """
    if current_user.role == "owner":
        if data.property_id is None:
            raise HTTPException(status_code=400, detail="Owners must specify a property_id")
        prop = db.query(Property).filter(
            Property.id == data.property_id, Property.owner_id == current_user.id
        ).first()
        if not prop:
            raise HTTPException(status_code=403, detail="Not your property")

        # Max 3 active coupons per owner
        active_count = db.query(Coupon).filter(
            Coupon.created_by == current_user.id, Coupon.is_active == True
        ).count()
        if active_count >= 3:
            raise HTTPException(status_code=400, detail="Maximum 3 active coupons allowed per owner")

    # Check unique code
    existing = db.query(Coupon).filter(Coupon.code == data.code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Coupon code already exists")

    coupon = Coupon(
        **data.model_dump(),
        created_by=current_user.id,
    )
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/", response_model=list[CouponResponse])
def list_coupons(
    active_only: bool = Query(default=True),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lists all coupons."""
    q = db.query(Coupon)
    if active_only:
        q = q.filter(Coupon.is_active == True)
    return q.order_by(Coupon.created_at.desc()).all()


@router.get("/my", response_model=list[CouponResponse])
def my_coupons(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner")),
):
    """Owner views their created coupons."""
    return db.query(Coupon).filter(
        Coupon.created_by == current_user.id
    ).order_by(Coupon.created_at.desc()).all()


@router.post("/validate", response_model=CouponValidateResponse)
def validate_coupon_endpoint(
    data: CouponValidateRequest,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Guest validates a coupon code before booking."""
    try:
        coupon = validate_coupon(data.code, current_user.id, data.booking_amount, data.property_id, db)
        discount = apply_coupon(coupon, data.booking_amount)
        return CouponValidateResponse(
            valid=True,
            discount_amount=discount,
            message=f"You save ₹{discount} with this coupon!",
        )
    except CouponError as e:
        return CouponValidateResponse(valid=False, message=e.detail)


@router.patch("/{coupon_id}", response_model=CouponResponse)
def update_coupon(
    coupon_id: int,
    data: CouponUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("admin", "owner")),
):
    """Update a coupon."""
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if current_user.role == "owner" and coupon.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your coupon")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(coupon, field, value)

    db.commit()
    db.refresh(coupon)
    return coupon


@router.delete("/{coupon_id}")
def deactivate_coupon(
    coupon_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("admin", "owner")),
):
    """Deactivate a coupon."""
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    if current_user.role == "owner" and coupon.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your coupon")

    coupon.is_active = False
    db.commit()
    return {"detail": "Coupon deactivated"}
