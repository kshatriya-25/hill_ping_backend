# HillPing — Property, Room, Amenity models

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Numeric, Boolean, Text,
    ForeignKey, DateTime, Date, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class Amenity(Base):
    __tablename__ = "amenities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    icon = Column(String(50), nullable=True)
    category = Column(String(50), nullable=True)  # e.g. "basics", "facilities", "safety"
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    address = Column(Text, nullable=False)
    city = Column(String(100), nullable=False, index=True)
    state = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    property_type = Column(String(30), nullable=False, default="homestay")  # homestay, hotel, cottage, villa
    cancellation_policy = Column(String(20), nullable=False, default="flexible")  # flexible, moderate, strict
    status = Column(String(20), nullable=False, default="offline")  # online, offline, full
    is_verified = Column(Boolean, default=False, nullable=False)
    is_instant_confirm = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    # Relationships
    owner = relationship("User", backref="properties")
    rooms = relationship("Room", back_populates="property", cascade="all, delete-orphan")
    photos = relationship("PropertyPhoto", back_populates="property", cascade="all, delete-orphan", order_by="PropertyPhoto.display_order")
    amenities = relationship("PropertyAmenity", back_populates="property", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_properties_city_status", "city", "status"),
    )


class PropertyAmenity(Base):
    __tablename__ = "property_amenities"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    amenity_id = Column(Integer, ForeignKey("amenities.id", ondelete="CASCADE"), nullable=False)

    property = relationship("Property", back_populates="amenities")
    amenity = relationship("Amenity")

    __table_args__ = (
        UniqueConstraint("property_id", "amenity_id", name="uq_property_amenity"),
    )


class PropertyPhoto(Base):
    __tablename__ = "property_photos"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    is_cover = Column(Boolean, default=False, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    property = relationship("Property", back_populates="photos")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    room_type = Column(String(30), nullable=False, default="double")  # single, double, dormitory, suite
    capacity = Column(Integer, nullable=False, default=2)
    price_weekday = Column(Numeric(10, 2), nullable=False)
    price_weekend = Column(Numeric(10, 2), nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    property = relationship("Property", back_populates="rooms")


class DateBlock(Base):
    """Owner-blocked dates for offline bookings / maintenance / personal use."""
    __tablename__ = "date_blocks"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    block_date = Column(Date, nullable=False)
    reason = Column(String(50), nullable=True)  # offline_booking, maintenance, personal

    property = relationship("Property")

    __table_args__ = (
        UniqueConstraint("property_id", "room_id", "block_date", name="uq_date_block"),
        Index("ix_date_blocks_lookup", "property_id", "block_date"),
    )
