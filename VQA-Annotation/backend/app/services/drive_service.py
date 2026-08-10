import io
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config.settings import settings

DRIVE_FILE_URL = "https://drive.google.com/file/d/{file_id}/view"
DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"


def _service():
    credentials_file = settings.google_drive_service_account_file
    if not credentials_file:
        raise RuntimeError("Google Drive service account is not configured.")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


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


def list_pdf_files(folder_id: str) -> list[dict]:
    service = _service()
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


def download_pdf(file_id: str, destination: Path) -> dict:
    service = _service()
    file_id = parse_drive_id(file_id, "file")
    metadata = service.files().get(fileId=file_id, fields="id,name,mimeType,size,parents,webViewLink").execute()
    if metadata.get("mimeType") != "application/pdf" and not metadata.get("name", "").lower().endswith(".pdf"):
        raise ValueError("Selected Google Drive file is not a PDF.")
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


def upload_page(folder_id: str, file_name: str, content: bytes) -> dict:
    service = _service()
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
    else:
        result = service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink").execute()
    result["webViewLink"] = result.get("webViewLink") or file_url(result["id"])
    return result


def download_file_bytes(file_id: str) -> tuple[bytes, str]:
    service = _service()
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


def delete_generated_pages(folder_id: str, image_prefix: str) -> None:
    service = _service()
    folder_id = parse_drive_id(folder_id, "folder")
    query = f"'{folder_id}' in parents and name contains '{image_prefix}' and trashed = false"
    files = service.files().list(q=query, fields="files(id,name)", pageSize=1000).execute().get("files", [])
    for item in files:
        if item["name"].startswith(image_prefix):
            service.files().delete(fileId=item["id"]).execute()


def upload_file(folder_id: str, file_name: str, content: bytes, output_format: str) -> tuple[str, str]:
    """Upload using a backend-only service-account file when configured."""
    credentials_file = settings.google_drive_service_account_file
    if not credentials_file:
        raise RuntimeError("Google Drive service account is not configured.")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
    except ImportError as error:
        raise RuntimeError("Google Drive dependencies are not installed.") from error

    credentials = service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    media_type = "text/csv" if output_format == "CSV" else "application/json"
    metadata = {"name": file_name, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=media_type, resumable=False)
    result = service.files().create(body=metadata, media_body=media, fields="id,webViewLink").execute()
    file_id = result["id"]
    return file_id, result.get("webViewLink") or f"https://drive.google.com/open?id={file_id}"
