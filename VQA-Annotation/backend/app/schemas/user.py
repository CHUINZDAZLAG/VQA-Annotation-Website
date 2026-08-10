from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import SystemRole


class GoogleTokenRequest(BaseModel):
    id_token: str


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    google_id: str | None
    email: str
    name: str
    avatar_url: str | None
    system_role: SystemRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRoleUpdate(BaseModel):
    system_role: SystemRole


class UserStatusUpdate(BaseModel):
    is_active: bool


class AuthenticationResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
