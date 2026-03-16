# HillPing — Review model

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, ForeignKey,
    DateTime, CheckConstraint, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True)
    guest_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    rating_cleanliness = Column(Integer, nullable=False)
    rating_accuracy = Column(Integer, nullable=False)
    rating_value = Column(Integer, nullable=False)
    rating_location = Column(Integer, nullable=False)
    rating_overall = Column(Float, nullable=False)  # computed avg of the 4

    comment = Column(Text, nullable=True)
    owner_response = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    booking = relationship("Booking")
    guest = relationship("User", foreign_keys=[guest_id])
    property = relationship("Property")

    __table_args__ = (
        CheckConstraint("rating_cleanliness BETWEEN 1 AND 5", name="ck_rating_cleanliness"),
        CheckConstraint("rating_accuracy BETWEEN 1 AND 5", name="ck_rating_accuracy"),
        CheckConstraint("rating_value BETWEEN 1 AND 5", name="ck_rating_value"),
        CheckConstraint("rating_location BETWEEN 1 AND 5", name="ck_rating_location"),
    )
