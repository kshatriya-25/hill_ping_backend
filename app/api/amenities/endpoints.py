# HillPing — Amenity endpoints

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...modals.property import Amenity
from ...schemas.propertySchema import AmenityCreate, AmenityResponse
from ...utils.utils import require_admin

router = APIRouter(tags=["amenities"])


@router.get("/", response_model=list[AmenityResponse])
def list_amenities(db: Session = Depends(getdb)):
    """Public: list all active amenities."""
    return db.query(Amenity).filter(Amenity.is_active == True).order_by(Amenity.category, Amenity.name).all()


@router.post("/", response_model=AmenityResponse)
def create_amenity(
    data: AmenityCreate,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin: create a new amenity."""
    if db.query(Amenity).filter(Amenity.name == data.name).first():
        raise HTTPException(status_code=409, detail="Amenity already exists")
    amenity = Amenity(**data.model_dump())
    db.add(amenity)
    db.commit()
    db.refresh(amenity)
    return amenity


@router.patch("/{amenity_id}", response_model=AmenityResponse)
def update_amenity(
    amenity_id: int,
    data: AmenityCreate,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin: update an amenity."""
    amenity = db.query(Amenity).filter(Amenity.id == amenity_id).first()
    if not amenity:
        raise HTTPException(status_code=404, detail="Amenity not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(amenity, field, value)
    db.commit()
    db.refresh(amenity)
    return amenity


@router.delete("/{amenity_id}")
def delete_amenity(
    amenity_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin: soft-delete an amenity."""
    amenity = db.query(Amenity).filter(Amenity.id == amenity_id).first()
    if not amenity:
        raise HTTPException(status_code=404, detail="Amenity not found")
    amenity.is_active = False
    db.commit()
    return {"detail": "Amenity deactivated"}
