# HillPing — Notification Preference model

from sqlalchemy import Column, Integer, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    booking_updates = Column(Boolean, default=True, nullable=False)
    ping_alerts = Column(Boolean, default=True, nullable=False)
    review_alerts = Column(Boolean, default=True, nullable=False)
    promotional = Column(Boolean, default=False, nullable=False)
    email_notifications = Column(Boolean, default=True, nullable=False)
    push_notifications = Column(Boolean, default=True, nullable=False)

    user = relationship("User")
