from pathlib import Path
from urllib.parse import quote

import requests

from app.config.settings import settings


class LocalStorage:
    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.storage_root).resolve()

    def task_root(self, task_id: int) -> Path:
        return self.root / "tasks" / str(task_id)

    def save_document(self, task_id: int, filename: str, content: bytes) -> Path:
        destination = self.task_root(task_id) / "documents" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def slide_path(self, task_id: int, slide_name: str, page_number: int) -> Path:
        return self.task_root(task_id) / "slides" / f"{slide_name}_page_{page_number:02d}.png"

    def remove_task_files(self, task_id: int) -> None:
        task_root = self.task_root(task_id)
        if task_root.exists():
            for path in sorted(task_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            task_root.rmdir()

    def remove_stale_slide_files(self, task_id: int, valid_paths: set[Path]) -> None:
        slides_root = self.task_root(task_id) / "slides"
        if not slides_root.exists():
            return
        resolved_valid = {path.resolve() for path in valid_paths}
        for path in slides_root.glob("*.png"):
            if path.resolve() not in resolved_valid:
                path.unlink()


storage = LocalStorage()


class SupabaseImageStorage:
    def __init__(self) -> None:
        self.base_url = settings.supabase_url.rstrip("/")
        self.service_role_key = settings.supabase_service_role_key
        self.bucket = settings.supabase_storage_bucket

    def require_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.base_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.service_role_key),
                ("SUPABASE_STORAGE_BUCKET", self.bucket),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Supabase Storage is not configured: {', '.join(missing)}")

    def image_path(self, task_id: int, image_id: str) -> str:
        return f"{task_id}/{image_id}.png"

    def _object_url(self, storage_path: str) -> str:
        self.require_configuration()
        return (
            f"{self.base_url}/storage/v1/object/{quote(self.bucket, safe='')}"
            f"/{quote(storage_path, safe='/')}"
        )

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def upload_image(self, task_id: int, image_id: str, content: bytes) -> str:
        storage_path = self.image_path(task_id, image_id)
        response = requests.post(
            self._object_url(storage_path),
            headers={**self._headers("image/png"), "x-upsert": "true"},
            data=content,
            timeout=60,
        )
        if response.status_code == 404:
            raise RuntimeError(f"Supabase Storage bucket '{self.bucket}' does not exist.")
        response.raise_for_status()
        return storage_path

    def download_image(self, storage_path: str) -> bytes:
        response = requests.get(
            self._object_url(storage_path),
            headers=self._headers(),
            timeout=30,
        )
        if response.status_code == 404:
            raise FileNotFoundError(storage_path)
        response.raise_for_status()
        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"Stored slide image is not a valid PNG: {storage_path}")
        return response.content

    def delete_images(self, storage_paths: list[str]) -> None:
        if not storage_paths:
            return
        self.require_configuration()
        response = requests.delete(
            f"{self.base_url}/storage/v1/object/{quote(self.bucket, safe='')}",
            headers=self._headers("application/json"),
            json={"prefixes": storage_paths},
            timeout=30,
        )
        response.raise_for_status()


supabase_storage = SupabaseImageStorage()
