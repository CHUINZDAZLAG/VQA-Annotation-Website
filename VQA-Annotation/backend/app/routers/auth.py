from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.config.database import get_db
from app.middleware.auth import get_current_user, require_admin
from app.models.user import SystemRole, User
from app.schemas.user import AdminLoginRequest, AuthenticationResponse, GoogleTokenRequest, TokenRefreshRequest, UserResponse
from app.services.auth_service import (
    GoogleIdentityError,
    UserIdentityConflict,
    create_access_token,
    create_admin_token,
    create_refresh_token,
    decode_application_token,
    find_or_create_google_user,
    verify_google_id_token,
    verify_admin_credentials,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
admin_auth_router = APIRouter(prefix="/api/admin/auth", tags=["admin-authentication"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/google", response_model=AuthenticationResponse)
def login_with_google(payload: GoogleTokenRequest, database_session=Depends(get_db)) -> AuthenticationResponse:
    try:
        user = find_or_create_google_user(database_session, verify_google_id_token(payload.id_token))
    except (GoogleIdentityError, UserIdentityConflict) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is inactive.")

    return AuthenticationResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
        user=user,
    )


@router.post("/refresh", response_model=AuthenticationResponse)
def refresh_application_tokens(
    payload: TokenRefreshRequest,
    database_session=Depends(get_db),
) -> AuthenticationResponse:
    try:
        token_payload = decode_application_token(payload.refresh_token, "refresh")
        user = database_session.get(User, int(token_payload["sub"]))
    except (GoogleIdentityError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid or expired.") from error

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account no longer exists.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is inactive.")

    return AuthenticationResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
        user=user,
    )


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(current_user: CurrentUser) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: CurrentUser) -> None:
    return None


@admin_auth_router.post("/login", response_model=AuthenticationResponse)
def admin_login(payload: AdminLoginRequest, database_session=Depends(get_db)) -> AuthenticationResponse:
    if not verify_admin_credentials(payload.email, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials.")

    user = database_session.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        user = User(
            google_id=None,
            email=payload.email.lower(),
            name="Administrator",
            avatar_url=None,
            system_role=SystemRole.ADMIN,
            is_active=True,
        )
        database_session.add(user)
    else:
        user.system_role = SystemRole.ADMIN
        user.is_active = True
    database_session.commit()
    database_session.refresh(user)
    return AuthenticationResponse(
        access_token=create_admin_token(user),
        refresh_token=create_refresh_token(user),
        user=user,
    )


@admin_auth_router.get("/me", response_model=UserResponse)
def admin_me(current_user: Annotated[User, Depends(require_admin)]) -> User:
    return current_user


@admin_auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def admin_logout(_: Annotated[User, Depends(require_admin)]) -> None:
    return None


@admin_auth_router.post("/refresh", response_model=AuthenticationResponse)
def admin_refresh(
    payload: TokenRefreshRequest,
    database_session=Depends(get_db),
) -> AuthenticationResponse:
    try:
        token_payload = decode_application_token(payload.refresh_token, "refresh")
        user = database_session.get(User, int(token_payload["sub"]))
    except (GoogleIdentityError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid or expired.") from error
    if user is None or user.system_role != SystemRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")
    return AuthenticationResponse(
        access_token=create_admin_token(user),
        refresh_token=create_refresh_token(user),
        user=user,
    )
