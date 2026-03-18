# OM VIGHNHARTAYE NAMO NAMAH:
# backend/app/schemas/masterSchema.py

import re
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator, model_validator, Field


_PASSWORD_RE = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};:\'",.<>/?\\|`~]).{8,}$'
)

_PHONE_RE = re.compile(r'^\+?[\d\s\-]{7,15}$')


def _check_password(v: str) -> str:
    if not _PASSWORD_RE.match(v):
        raise ValueError(
            "Password must be at least 8 characters and include an uppercase letter, "
            "a lowercase letter, a digit, and a special character."
        )
    return v


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_.\-]+$')
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=15)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _PHONE_RE.match(v):
            raise ValueError("Invalid phone number format")
        return v


class UserCreate(UserBase):
    password: str
    role: str = Field(default="guest", pattern=r'^(guest|owner|mediator)$')

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _check_password(v)


class UserUpdate(BaseModel):
    """Partial update — all fields optional; validated when supplied."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, strip_whitespace=True)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=15)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _PHONE_RE.match(v):
            raise ValueError("Invalid phone number format")
        return v


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new(cls, v: str) -> str:
        return _check_password(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "PasswordChange":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password do not match")
        return self


class UserResponse(BaseModel):
    id: int
    name: str
    username: str
    email: EmailStr
    phone: Optional[str] = None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
