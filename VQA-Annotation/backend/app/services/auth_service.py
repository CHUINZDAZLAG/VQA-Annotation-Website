from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.user import SystemRole, User


class GoogleIdentityError(ValueError):
    pass


class UserIdentityConflict(ValueError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    google_id: str
    email: str
    name: str
    avatar_url: str | None


def verify_google_id_token(token: str) -> GoogleIdentity:
    if not settings.google_client_id:
        raise GoogleIdentityError("GOOGLE_CLIENT_ID is not configured.")

    try:
        payload = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as error:
        raise GoogleIdentityError("Google ID token is invalid or expired.") from error

    if payload.get("aud") != settings.google_client_id:
        raise GoogleIdentityError("Google ID token was issued for another client.")

    if payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleIdentityError("Google ID token has an invalid issuer.")

    expiration = payload.get("exp")
    if not isinstance(expiration, (int, float)) or expiration <= datetime.now(timezone.utc).timestamp():
        raise GoogleIdentityError("Google ID token is expired.")

    google_id = payload.get("sub")
    email = payload.get("email")
    email_verified = payload.get("email_verified")

    if not isinstance(google_id, str) or not isinstance(email, str) or email_verified is not True:
        raise GoogleIdentityError("Google did not return a verified email identity.")

    name = payload.get("name")
    picture = payload.get("picture")
    return GoogleIdentity(
        google_id=google_id,
        email=email.lower(),
        name=name if isinstance(name, str) and name else email,
        avatar_url=picture if isinstance(picture, str) else None,
    )


def create_access_token(user: User) -> str:
    return _create_application_token(
        user_id=user.id,
        token_type="access",
        expires_in=timedelta(minutes=settings.access_token_expire_minutes),
        role=user.system_role.value,
    )


def create_refresh_token(user: User) -> str:
    return _create_application_token(
        user_id=user.id,
        token_type="refresh",
        expires_in=timedelta(days=settings.refresh_token_expire_days),
    )


def create_admin_token(user: User) -> str:
    return _create_application_token(
        user_id=user.id,
        token_type="access",
        expires_in=timedelta(minutes=settings.access_token_expire_minutes),
        role=SystemRole.ADMIN.value,
    )


def verify_admin_credentials(email: str, password: str) -> bool:
    return bool(settings.admin_email and settings.admin_password) and hmac.compare_digest(
        email.lower(), settings.admin_email.lower()
    ) and hmac.compare_digest(password, settings.admin_password)


def decode_application_token(token: str, expected_type: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise GoogleIdentityError("Application token is invalid or expired.") from error

    if payload.get("token_type") != expected_type:
        raise GoogleIdentityError("Application token has an invalid type.")
    if not isinstance(payload.get("sub"), str) or not payload["sub"].isdigit():
        raise GoogleIdentityError("Application token has an invalid subject.")
    return payload


def _create_application_token(
    user_id: int,
    token_type: str,
    expires_in: timedelta,
    role: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "token_type": token_type,
        "iat": now,
        "exp": now + expires_in,
    }
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def find_or_create_google_user(database_session: Session, identity: GoogleIdentity) -> User:
    user = database_session.scalar(
        select(User).where(User.google_id == identity.google_id)
    )
    if user is not None:
        user.email = identity.email
        user.name = identity.name
        user.avatar_url = identity.avatar_url
        database_session.commit()
        database_session.refresh(user)
        return user

    existing_email_user = database_session.scalar(
        select(User).where(User.email == identity.email)
    )
    if existing_email_user is not None:
        raise UserIdentityConflict("This email is already linked to another Google account.")

    user = User(
        google_id=identity.google_id,
        email=identity.email,
        name=identity.name,
        avatar_url=identity.avatar_url,
        system_role=SystemRole.USER,
        is_active=False,
    )
    database_session.add(user)
    database_session.commit()
    database_session.refresh(user)
    return user


__all__ = [
    "GoogleIdentityError",
    "UserIdentityConflict",
    "create_access_token",
    "create_admin_token",
    "create_refresh_token",
    "decode_application_token",
    "find_or_create_google_user",
    "verify_admin_credentials",
    "verify_google_id_token",
]
