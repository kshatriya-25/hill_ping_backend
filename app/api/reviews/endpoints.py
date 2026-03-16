# HillPing — Review endpoints

import datetime
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ...database.session import getdb
from ...modals.masters import User
from ...modals.booking import Booking
from ...modals.review import Review
from ...modals.property import Property
from ...schemas.reviewSchema import ReviewCreate, ReviewResponse, OwnerResponseCreate
from ...utils.utils import get_current_user, require_guest, require_owner

router = APIRouter(tags=["reviews"])


@router.post("/", response_model=ReviewResponse)
def create_review(
    data: ReviewCreate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """
    Guest creates a review after checkout.
    Only allowed for completed bookings, 2 hours after checkout time.
    """
    booking = db.query(Booking).filter(
        Booking.id == data.booking_id,
        Booking.guest_id == current_user.id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "completed":
        raise HTTPException(status_code=400, detail="Can only review completed bookings")

    # Check 2-hour post-checkout window
    now = datetime.datetime.now(timezone.utc)
    checkout_dt = datetime.datetime.combine(booking.check_out, datetime.time(11, 0), tzinfo=timezone.utc)
    if now < checkout_dt + datetime.timedelta(hours=2):
        raise HTTPException(status_code=400, detail="Reviews can be submitted 2 hours after checkout")

    # Check duplicate
    existing = db.query(Review).filter(Review.booking_id == data.booking_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Review already submitted for this booking")

    overall = (data.rating_cleanliness + data.rating_accuracy + data.rating_value + data.rating_location) / 4.0

    review = Review(
        booking_id=data.booking_id,
        guest_id=current_user.id,
        property_id=booking.property_id,
        rating_cleanliness=data.rating_cleanliness,
        rating_accuracy=data.rating_accuracy,
        rating_value=data.rating_value,
        rating_location=data.rating_location,
        rating_overall=round(overall, 2),
        comment=data.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return _review_response(review, db)


@router.get("/property/{property_id}", response_model=list[ReviewResponse])
def property_reviews(
    property_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(getdb),
):
    """Public: list reviews for a property."""
    reviews = db.query(Review).filter(
        Review.property_id == property_id
    ).order_by(Review.created_at.desc()).offset(skip).limit(limit).all()

    return [_review_response(r, db) for r in reviews]


@router.get("/property/{property_id}/summary")
def review_summary(property_id: int, db: Session = Depends(getdb)):
    """Public: aggregate rating summary for a property."""
    stats = db.query(
        func.count(Review.id).label("total"),
        func.avg(Review.rating_overall).label("avg_overall"),
        func.avg(Review.rating_cleanliness).label("avg_cleanliness"),
        func.avg(Review.rating_accuracy).label("avg_accuracy"),
        func.avg(Review.rating_value).label("avg_value"),
        func.avg(Review.rating_location).label("avg_location"),
    ).filter(Review.property_id == property_id).first()

    return {
        "total_reviews": stats.total or 0,
        "avg_overall": round(float(stats.avg_overall or 0), 2),
        "avg_cleanliness": round(float(stats.avg_cleanliness or 0), 2),
        "avg_accuracy": round(float(stats.avg_accuracy or 0), 2),
        "avg_value": round(float(stats.avg_value or 0), 2),
        "avg_location": round(float(stats.avg_location or 0), 2),
    }


@router.post("/{review_id}/respond")
def respond_to_review(
    review_id: int,
    data: OwnerResponseCreate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner responds to a review on their property."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    prop = db.query(Property).filter(Property.id == review.property_id).first()
    if not prop or prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your property")

    if review.owner_response:
        raise HTTPException(status_code=400, detail="Already responded to this review")

    review.owner_response = data.response
    db.commit()
    return {"detail": "Response added"}


@router.get("/my", response_model=list[ReviewResponse])
def my_reviews(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """Guest views their submitted reviews."""
    reviews = db.query(Review).filter(
        Review.guest_id == current_user.id
    ).order_by(Review.created_at.desc()).all()
    return [_review_response(r, db) for r in reviews]


def _review_response(review: Review, db: Session) -> dict:
    guest = db.query(User).filter(User.id == review.guest_id).first()
    return {
        "id": review.id,
        "booking_id": review.booking_id,
        "guest_id": review.guest_id,
        "property_id": review.property_id,
        "rating_cleanliness": review.rating_cleanliness,
        "rating_accuracy": review.rating_accuracy,
        "rating_value": review.rating_value,
        "rating_location": review.rating_location,
        "rating_overall": review.rating_overall,
        "comment": review.comment,
        "owner_response": review.owner_response,
        "guest_name": guest.name if guest else None,
        "created_at": review.created_at,
    }
