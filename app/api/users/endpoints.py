# backend/app/api/users/endpoints.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ...database.session import getdb
from ...modals.masters import User
from ...schemas.masterSchema import UserCreate, UserUpdate, UserResponse, PasswordChange
from ...utils.utils import (
    get_hashed_password,
    verify_password,
    response_strct,
    get_current_user,
    require_admin,
    revoke_all_user_refresh_tokens,
)

router = APIRouter()


# ── Bootstrap (one-time) ───────────────────────────────────────────────────────

@router.post("/create-superuser", tags=["bootstrap"])
def create_superuser(db: Session = Depends(getdb)):
    """
    One-time bootstrap: creates the initial admin account.
    The endpoint is idempotent — calling it a second time returns 400.
    IMPORTANT: Remove or protect this route in production after first use.
    """
    if db.query(User).filter(User.username == "admin").first():
        raise HTTPException(status_code=400, detail="Admin user already exists")

    # Admin password must be changed on first login — this is a placeholder.
    # Generate a secure random password and log/return it instead of hardcoding "123".
    import secrets, string
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    temp_password = "".join(secrets.choice(alphabet) for _ in range(16))

    admin_user = User(
        name="Super Admin",
        username="admin",
        email="admin@example.com",
        phone=None,
        password_hash=get_hashed_password(temp_password),
        role="admin",
    )

    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    return response_strct(
        status_code=201,
        detail="Superuser created. Store the one-time password securely — it will not be shown again.",
        data={
            "username": admin_user.username,
            "email": admin_user.email,
            "temporary_password": temp_password,  # shown once only
        },
    )


# ── User CRUD ──────────────────────────────────────────────────────────────────

@router.post("/users/", response_model=UserResponse, tags=["users"])
def create_user(
    user: UserCreate,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Create a new user (admin only)."""
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = User(
        name=user.name,
        username=user.username,
        email=user.email,
        phone=user.phone,
        password_hash=get_hashed_password(user.password),
        role=user.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/users/", response_model=List[UserResponse], tags=["users"])
def get_all_users(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """List all users (admin only)."""
    return db.query(User).all()


@router.get("/users/me", response_model=UserResponse, tags=["users"])
def get_own_profile(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's own profile."""
    return current_user


@router.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user(
    user_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Get a user by ID. Admins can see any user; others only themselves."""
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserResponse, tags=["users"])
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """
    Partially update a user.
    - Admins can update any user.
    - Users can only update their own name/email/phone.
    """
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this user")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.model_dump(exclude_none=True)

    if "email" in update_data and update_data["email"] != user.email:
        if db.query(User).filter(User.email == update_data["email"]).first():
            raise HTTPException(status_code=409, detail="Email already registered")

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/change-password", tags=["users"])
def change_password(
    user_id: int,
    body: PasswordChange,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """
    Change a user's password.
    Users can only change their own password; admins can change any user's.
    Revokes all existing refresh tokens on success.
    """
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    user.password_hash = get_hashed_password(body.new_password)
    db.commit()

    # Invalidate all sessions after password change
    revoke_all_user_refresh_tokens(user_id, db)

    return {"detail": "Password changed. All sessions have been revoked."}


@router.patch("/users/{user_id}/activate", tags=["users"])
def toggle_active(
    user_id: int,
    active: bool,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Enable or disable a user account (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = active
    if not active:
        revoke_all_user_refresh_tokens(user_id, db)
    db.commit()

    return {"detail": f"User {'activated' if active else 'deactivated'}."}


@router.delete("/users/{user_id}", tags=["users"])
def delete_user(
    user_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Delete a user (admin only). Also revokes all their refresh tokens."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)  # cascade deletes refresh_tokens via FK
    db.commit()

    return response_strct(
        status_code=status.HTTP_200_OK,
        detail="User deleted successfully",
        data={"deleted_user_id": user_id},
    )
