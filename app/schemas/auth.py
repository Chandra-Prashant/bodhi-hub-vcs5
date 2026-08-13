from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class RefreshIn(BaseModel):
    refresh_token: str


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    organization: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None


class UserCreateIn(BaseModel):
    """Admin-provisioned only. There is no self-registration path."""
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    organization: str = Field(min_length=1, max_length=200)
    initial_password: str = Field(min_length=12, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_email: str
    organization: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    ip_address: str | None
