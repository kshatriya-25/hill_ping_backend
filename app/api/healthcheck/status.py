# OM VIGHNHARTAYE NAMO NAMAH :

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from ...database.session import getdb

router = APIRouter()

@router.get("/health", summary="Check API and DB health", tags=["health check"])
def check_health(db: Session = Depends(getdb)):
    """
    Returns server and database health status using sync SQLAlchemy Session.
    """
    health_status = {
        "server_status": "healthy",
        "database_status": "unknown",
    }

    try:
        # Try a lightweight DB query to check connection
        db.execute(text("SELECT 1"))
        health_status["database_status"] = "connected"
    except Exception as e:
        health_status["database_status"] = f"error: {str(e)}"

    return health_status
