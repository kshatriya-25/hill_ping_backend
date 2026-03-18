# HillPing — Visit Request endpoints (V2)

import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...database.redis import get_visit_hold_ttl
from ...modals.masters import User
from ...schemas.visitSchema import (
    VisitRequestCreate,
    VisitPassRequest,
    VisitRequestResponse,
)
from ...services.visit import (
    create_visit_request,
    arrive_at_property,
    book_from_visit,
    pass_visit,
    extend_visit,
    release_hold_by_owner,
    get_active_visits_for_mediator,
    VisitError,
)
from ...utils.utils import require_role, get_current_user

router = APIRouter(tags=["visit"])
logger = logging.getLogger(__name__)


def _enrich_response(visit, db) -> dict:
    """Add hold_remaining_seconds to visit response."""
    data = VisitRequestResponse.model_validate(visit).model_dump()
    remaining = get_visit_hold_ttl(visit.visit_ref)
    data["hold_remaining_seconds"] = max(remaining, 0) if remaining > 0 else 0
    return data


# ── Create visit request ──────────────────────────────────────────────────────

@router.post("/request", status_code=201)
def request_visit(
    data: VisitRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Request a property visit (creates 45-minute room hold)."""
    try:
        visit = create_visit_request(
            mediator_id=current_user.id,
            property_id=data.property_id,
            room_id=data.room_id,
            guest_id=data.guest_id,
            guest_count=data.guest_count,
            eta_minutes=data.eta_minutes,
            ping_session_id=data.ping_session_id,
            tour_session_id=None,
            tour_stop_order=None,
            db=db,
        )
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # Notify owner via WebSocket (background)
    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        visit.owner_id,
        {
            "type": "visit_requested",
            "visit_ref": visit.visit_ref,
            "mediator_id": current_user.id,
            "property_id": data.property_id,
            "guest_count": data.guest_count,
            "eta_minutes": data.eta_minutes,
        },
    )

    return _enrich_response(visit, db)


# ── Mark arrived ──────────────────────────────────────────────────────────────

@router.post("/{visit_ref}/arrive")
def mark_arrived(
    visit_ref: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Mediator arrived at the property."""
    try:
        visit = arrive_at_property(visit_ref, current_user.id, db)
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        visit.owner_id,
        {"type": "visit_arrived", "visit_ref": visit_ref},
    )

    return _enrich_response(visit, db)


# ── Book from visit ───────────────────────────────────────────────────────────

@router.post("/{visit_ref}/book")
def book_visit(
    visit_ref: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Tourist liked the property — convert visit to booking intent."""
    try:
        visit = book_from_visit(visit_ref, current_user.id, db)
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        visit.owner_id,
        {"type": "visit_booked", "visit_ref": visit_ref},
    )

    return _enrich_response(visit, db)


# ── Pass (reject) ────────────────────────────────────────────────────────────

@router.post("/{visit_ref}/pass")
def pass_on_visit(
    visit_ref: str,
    data: VisitPassRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Tourist rejected the property — release hold."""
    try:
        visit = pass_visit(visit_ref, current_user.id, data.reason, db)
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        visit.owner_id,
        {"type": "visit_passed", "visit_ref": visit_ref, "reason": data.reason},
    )

    return _enrich_response(visit, db)


# ── Extend hold ──────────────────────────────────────────────────────────────

@router.post("/{visit_ref}/extend")
def extend_hold(
    visit_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Extend visit hold by 15 minutes (once per visit)."""
    try:
        visit = extend_visit(visit_ref, current_user.id, db)
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return _enrich_response(visit, db)


# ── Get visit status ─────────────────────────────────────────────────────────

@router.get("/{visit_ref}/status")
def get_visit_status(
    visit_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Get visit request status (mediator or owner)."""
    from ...modals.visit import VisitRequest

    visit = db.query(VisitRequest).filter(
        VisitRequest.visit_ref == visit_ref,
    ).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if current_user.id not in (visit.mediator_id, visit.owner_id) and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    return _enrich_response(visit, db)


# ── My active visits ─────────────────────────────────────────────────────────

@router.get("/my-active")
def my_active_visits(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get mediator's active visits (auto-expires stale holds)."""
    visits = get_active_visits_for_mediator(current_user.id, db)
    return [_enrich_response(v, db) for v in visits]


# ── Owner: Incoming visits ────────────────────────────────────────────────────

@router.get("/owner-incoming")
def owner_incoming_visits(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner")),
):
    """Owner views active visit requests on their properties."""
    from ...modals.visit import VisitRequest
    from ...modals.property import Property

    visits = db.query(VisitRequest).filter(
        VisitRequest.owner_id == current_user.id,
        VisitRequest.status.in_(["requested", "en_route", "arrived"]),
    ).order_by(VisitRequest.created_at.desc()).all()

    result = []
    for v in visits:
        prop = db.query(Property).filter(Property.id == v.property_id).first()
        remaining = get_visit_hold_ttl(v.visit_ref)
        result.append({
            "visit_ref": v.visit_ref,
            "property_id": v.property_id,
            "property_name": prop.name if prop else None,
            "mediator_id": v.mediator_id,
            "guest_count": v.guest_count,
            "eta_minutes": v.eta_minutes,
            "status": v.status,
            "hold_expires_at": v.hold_expires_at.isoformat() if v.hold_expires_at else None,
            "hold_remaining_seconds": max(remaining, 0) if remaining > 0 else 0,
            "arrived_at": v.arrived_at.isoformat() if v.arrived_at else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })

    return result


# ── Owner: Release hold ──────────────────────────────────────────────────────

@router.post("/{visit_ref}/release")
def owner_release_hold(
    visit_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner")),
):
    """Owner releases a hold early (mediator no-show)."""
    try:
        visit = release_hold_by_owner(visit_ref, current_user.id, db)
    except VisitError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return _enrich_response(visit, db)
