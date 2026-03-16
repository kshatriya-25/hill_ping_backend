# HillPing — Platform Configuration (admin-tunable settings stored in DB)

import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime
from ..database.base_class import Base


class PlatformConfig(Base):
    """
    Key-value config store for admin-tunable platform settings.
    These override the defaults in config.py and can be changed
    from the admin panel without redeploying.
    """
    __tablename__ = "platform_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(String(500), nullable=False)
    description = Column(String(500), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
