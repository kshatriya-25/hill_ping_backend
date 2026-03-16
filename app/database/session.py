# OM VIGHNHARTAYE NAMO NAMAH:

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Generator
import uuid
from datetime import datetime
from ..core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=35,
    max_overflow=10
)


SessionLocal = sessionmaker(autocommit = False , autoflush=False , bind=engine)


def getdb(name = None) -> Generator:
    try:
        current_time = datetime.now()
        db = SessionLocal()
        conn_id = None
        conn_id = str(uuid.uuid4())
        start_tym = current_time
        yield db
    finally:
        print("db closed---" , conn_id , "------" , current_time - start_tym , "\n")
        db.close()