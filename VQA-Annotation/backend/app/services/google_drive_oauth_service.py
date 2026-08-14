import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from google_auth_oauthlib.flow import Flow
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.google_drive import GoogleDriveConnection, GoogleDriveOAuthState

DRIVE_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive",
)
STATE_TTL_MINUTES = 10


def require_oauth_configuration() -> None:
    missing = [
        name
        for name, value in (
            ("GOOGLE_DRIVE_OAUTH_CLIENT_ID", settings.google_drive_oauth_client_id),
            ("GOOGLE_DRIVE_OAUTH_CLIENT_SECRET", settings.google_drive_oauth_client_secret),
            ("GOOGLE_DRIVE_OAUTH_REDIRECT_URI", settings.google_drive_oauth_redirect_uri),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Google Drive OAuth is not configured: {', '.join(missing)}")


def _client_config() -> dict:
    require_oauth_configuration()
    return {
        "web": {
            "client_id": settings.google_drive_oauth_client_id,
            "client_secret": settings.google_drive_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_drive_oauth_redirect_uri],
        }
    }


def _flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=list(DRIVE_SCOPES), state=state)
    flow.redirect_uri = settings.google_drive_oauth_redirect_uri
    return flow


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_refresh_token(refresh_token: str) -> str:
    return _fernet().encrypt(refresh_token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(encrypted_refresh_token: str) -> str:
    try:
        return _fernet().decrypt(encrypted_refresh_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as error:
        raise RuntimeError("The stored Google Drive connection cannot be decrypted.") from error


def authorization_url(database_session: Session, user_id: int, return_path: str) -> str:
    safe_return_path = return_path if return_path.startswith("/") and not return_path.startswith("//") else "/annotator"
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    database_session.execute(delete(GoogleDriveOAuthState).where(GoogleDriveOAuthState.expires_at <= now))
    database_session.add(GoogleDriveOAuthState(
        state_hash=_state_hash(state),
        user_id=user_id,
        return_path=safe_return_path,
        expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
    ))
    database_session.commit()
    url, _ = _flow(state).authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return url


def complete_authorization(database_session: Session, state: str, code: str) -> tuple[int, str]:
    now = datetime.now(timezone.utc)
    state_record = database_session.scalar(
        select(GoogleDriveOAuthState).where(
            GoogleDriveOAuthState.state_hash == _state_hash(state),
            GoogleDriveOAuthState.expires_at > now,
        )
    )
    if state_record is None:
        raise ValueError("Google Drive OAuth state is invalid or expired.")

    user_id = state_record.user_id
    return_path = state_record.return_path

    flow = _flow(state)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise RuntimeError("Google did not return a refresh token. Reconnect and grant consent again.")

    response = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=20,
    )
    response.raise_for_status()
    google_email = response.json().get("email")

    connection = database_session.scalar(
        select(GoogleDriveConnection).where(GoogleDriveConnection.user_id == user_id)
    )
    if connection is None:
        connection = GoogleDriveConnection(user_id=user_id)
        database_session.add(connection)
    connection.google_email = google_email if isinstance(google_email, str) else None
    connection.encrypted_refresh_token = encrypt_refresh_token(credentials.refresh_token)
    connection.scopes = " ".join(credentials.scopes or DRIVE_SCOPES)
    database_session.delete(state_record)
    database_session.commit()
    return user_id, return_path


def frontend_redirect(return_path: str, status: str, detail: str | None = None) -> str:
    base = settings.frontend_url.split(",")[0].strip().rstrip("/")
    query = {"drive": status}
    if detail:
        query["detail"] = detail
    return f"{base}{return_path}?{urlencode(query)}"