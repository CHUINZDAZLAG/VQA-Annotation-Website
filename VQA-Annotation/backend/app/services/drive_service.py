import io
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import select

from app.config.database import SessionLocal
from app.config.settings import settings
from app.models.google_drive import GoogleDriveConnection
from app.services.google_drive_oauth_service import decrypt_refresh_token

DRIVE_FILE_URL = "https://drive.google.com/file/d/{file_id}/view"
DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"


def service_account_file() -> Path:
    configured = settings.google_drive_service_account_file
    if not configured:
        raise RuntimeError("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE is not configured.")
    credentials_file = Path(configured).expanduser()
    if not credentials_file.is_absolute():
        credentials_file = (Path(__file__).resolve().parents[2] / credentials_file).resolve()
    if not credentials_file.is_file():
        raise RuntimeError(f"Google Drive service-account file was not found: {credentials_file}")
    try:
        metadata = json.loads(credentials_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Google Drive credentials file is not valid JSON: {credentials_file}") from error
    if not isinstance(metadata, dict) or metadata.get("type") != "service_account" or not metadata.get("client_email") or not metadata.get("private_key"):
        raise RuntimeError("Google Drive credentials must be a service-account JSON key.")
    return credentials_file


def _credentials(scopes: list[str], user_id: int | None = None):
    try:
        import google.auth
        from google.oauth2.credentials import Credentials
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error

    if user_id is not None:
        with SessionLocal() as database_session:
            connection = database_session.scalar(
                select(GoogleDriveConnection).where(GoogleDriveConnection.user_id == user_id)
            )
        if connection is None:
            raise RuntimeError("Connect Google Drive before using Drive files or folders.")
        if not settings.google_drive_oauth_client_id or not settings.google_drive_oauth_client_secret:
            raise RuntimeError("Google Drive OAuth client credentials are not configured.")
        return Credentials(
            token=None,
            refresh_token=decrypt_refresh_token(connection.encrypted_refresh_token),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_drive_oauth_client_id,
            client_secret=settings.google_drive_oauth_client_secret,
            scopes=scopes,
        )
    if settings.google_drive_service_account_file:
        return service_account.Credentials.from_service_account_file(
            str(service_account_file()),
            scopes=scopes,
        )
    oauth_values = (
        settings.google_client_id,
        settings.google_drive_oauth_client_secret,
        settings.google_drive_oauth_refresh_token,
    )
    if any(oauth_values[1:]):
        if not all(oauth_values):
            raise RuntimeError(
                "Google Drive OAuth configuration is incomplete. Set GOOGLE_CLIENT_ID, "
                "GOOGLE_DRIVE_OAUTH_CLIENT_SECRET, and GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN."
            )
        return Credentials(
            token=None,
            refresh_token=settings.google_drive_oauth_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_drive_oauth_client_secret,
            scopes=scopes,
        )
    try:
        credentials, _ = google.auth.default(scopes=scopes)
    except google.auth.exceptions.DefaultCredentialsError as error:
        raise RuntimeError(
            "Google Drive credentials are unavailable. Configure Application Default Credentials "
            "for the production runtime, or set GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE for local development."
        ) from error
    return credentials


def _service(scopes: list[str] | None = None, user_id: int | None = None):
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error
    credentials = _credentials(scopes or ["https://www.googleapis.com/auth/drive"], user_id=user_id)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def authentication_info(user_id: int | None = None) -> dict[str, str | None]:
    if user_id is not None:
        with SessionLocal() as database_session:
            connection = database_session.scalar(
                select(GoogleDriveConnection).where(GoogleDriveConnection.user_id == user_id)
            )
        if connection is None:
            return {"method": "not_connected", "account_email": None}
        return {"method": "user_oauth_refresh_token", "account_email": connection.google_email}
    if settings.google_drive_service_account_file:
        metadata = json.loads(service_account_file().read_text(encoding="utf-8"))
        return {"method": "service_account_file", "account_email": metadata.get("client_email")}
    if settings.google_drive_oauth_refresh_token:
        return {"method": "oauth_refresh_token", "account_email": settings.google_drive_account_email or None}
    return {"method": "application_default_credentials", "account_email": settings.google_drive_account_email or None}


def parse_drive_id(value: str, kind: str) -> str:
    patterns = {
        "folder": r"(?:/folders/|id=)([A-Za-z0-9_-]+)",
        "file": r"(?:/d/|id=)([A-Za-z0-9_-]+)",
    }
    match = re.search(patterns[kind], value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    raise ValueError(f"Invalid Google Drive {kind} ID or URL.")


def file_url(file_id: str) -> str:
    return DRIVE_FILE_URL.format(file_id=file_id)


def folder_url(folder_id: str) -> str:
    return DRIVE_FOLDER_URL.format(folder_id=parse_drive_id(folder_id, "folder"))


def verify_writable_folder(folder_id: str, user_id: int | None = None) -> str:
    service = _service(user_id=user_id)
    folder_id = parse_drive_id(folder_id, "folder")
    metadata = service.files().get(
        fileId=folder_id,
        fields="id,mimeType,capabilities(canAddChildren)",
        supportsAllDrives=True,
    ).execute()
    if metadata.get("mimeType") != "application/vnd.google-apps.folder":
        raise ValueError("The Google Drive destination is not a folder.")
    if not (metadata.get("capabilities") or {}).get("canAddChildren"):
        raise PermissionError(
            "Google Drive permission denied. Please share the destination folder "
            "with the configured Drive account with Editor access."
        )
    return folder_id


def list_pdf_files(folder_id: str, user_id: int | None = None) -> list[dict]:
    service = _service(user_id=user_id)
    folder_id = parse_drive_id(folder_id, "folder")
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        "(mimeType = 'application/pdf' or name contains '.pdf')"
    )
    result = service.files().list(
        q=query, fields="files(id,name,mimeType,size,modifiedTime,webViewLink)",
        orderBy="modifiedTime desc", pageSize=100,
    ).execute()
    return result.get("files", [])


def download_pdf(file_id: str, destination: Path, user_id: int | None = None) -> dict:
    service = _service(user_id=user_id)
    file_id = parse_drive_id(file_id, "file")
    metadata = service.files().get(fileId=file_id, fields="id,name,mimeType,size,parents,webViewLink").execute()
    if metadata.get("mimeType") != "application/pdf" and not metadata.get("name", "").lower().endswith(".pdf"):
        raise ValueError("Selected Google Drive file is not a PDF.")
    if settings.max_pdf_size_mb and int(metadata.get("size") or 0) > settings.max_pdf_size_mb * 1024 * 1024:
        raise ValueError(f"The PDF exceeds the {settings.max_pdf_size_mb} MB size limit.")
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error
    request = service.files().get_media(fileId=file_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    metadata["webViewLink"] = metadata.get("webViewLink") or file_url(file_id)
    return metadata


def upload_page(folder_id: str, file_name: str, content: bytes, user_id: int | None = None) -> dict:
    service = _service(user_id=user_id)
    try:
        from googleapiclient.http import MediaIoBaseUpload
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error
    folder_id = parse_drive_id(folder_id, "folder")
    query = f"'{folder_id}' in parents and name = '{file_name.replace(chr(39), chr(92) + chr(39))}' and trashed = false"
    existing = service.files().list(q=query, fields="files(id,name,webViewLink)", pageSize=10).execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype="image/png", resumable=True)
    metadata = {"name": file_name, "parents": [folder_id]}
    if existing:
        result = service.files().update(fileId=existing[0]["id"], body={"name": file_name}, media_body=media, fields="id,name,webViewLink").execute()
        result["created"] = False
    else:
        result = service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink").execute()
        result["created"] = True
    result["webViewLink"] = result.get("webViewLink") or file_url(result["id"])
    return result


def delete_files(file_ids: list[str], user_id: int | None = None) -> None:
    if not file_ids:
        return
    service = _service(user_id=user_id)
    for file_id in file_ids:
        service.files().delete(fileId=parse_drive_id(file_id, "file"), supportsAllDrives=True).execute()


def download_file_bytes(file_id: str, user_id: int | None = None) -> tuple[bytes, str]:
    service = _service(user_id=user_id)
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error
    request = service.files().get_media(fileId=parse_drive_id(file_id, "file"))
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return output.getvalue(), "image/png"


def delete_generated_pages(folder_id: str, image_prefix: str, user_id: int | None = None) -> None:
    service = _service(user_id=user_id)
    folder_id = parse_drive_id(folder_id, "folder")
    query = f"'{folder_id}' in parents and name contains '{image_prefix}' and trashed = false"
    files = service.files().list(q=query, fields="files(id,name)", pageSize=1000).execute().get("files", [])
    for item in files:
        if item["name"].startswith(image_prefix):
            service.files().delete(fileId=item["id"]).execute()


def upload_file(
    folder_id: str,
    file_name: str,
    content: bytes,
    output_format: str,
    user_id: int | None = None,
) -> tuple[str, str]:
    """Upload an export through the same backend-only Drive identity."""
    try:
        from googleapiclient.http import MediaIoBaseUpload
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error

    service = _service(["https://www.googleapis.com/auth/drive.file"], user_id=user_id)
    folder_id = parse_drive_id(folder_id, "folder")
    media_type = "text/csv" if output_format == "CSV" else "application/json"
    query = f"'{folder_id}' in parents and name = '{file_name.replace(chr(39), chr(92) + chr(39))}' and trashed = false"
    existing = service.files().list(
        q=query, fields="files(id,webViewLink)", pageSize=10,
    ).execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=media_type, resumable=False)
    if existing:
        result = service.files().update(
            fileId=existing[0]["id"], media_body=media, fields="id,webViewLink",
        ).execute()
    else:
        result = service.files().create(
            body={"name": file_name, "parents": [folder_id]},
            media_body=media, fields="id,webViewLink",
        ).execute()
    file_id = result["id"]
    return file_id, result.get("webViewLink") or f"https://drive.google.com/open?id={file_id}"
