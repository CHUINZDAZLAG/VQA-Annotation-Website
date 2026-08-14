from functools import cached_property
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VQA Dataset Annotation Platform"
    environment: str = "development"
    database_url: str
    google_client_id: str = ""
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    admin_email: str = ""
    admin_password: str = ""
    frontend_url: str = "http://localhost:5173"
    google_drive_service_account_file: str = ""
    google_drive_oauth_client_id: str = ""
    google_drive_oauth_client_secret: str = ""
    google_drive_oauth_redirect_uri: str = ""
    google_drive_oauth_refresh_token: str = ""
    google_drive_account_email: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    storage_root: str = "storage"
    max_pdf_size_mb: int = 0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("secret_key")
    @classmethod
    def require_secret_key(cls, value: str) -> str:
        if len(value.encode("utf-8")) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 random bytes.")
        return value

    @cached_property
    def cors_origins(self) -> list[str]:
        configured = [
            origin.strip().rstrip("/")
            for origin in self.frontend_url.split(",")
            if origin.strip()
        ]
        if self.environment != "production":
            configured.extend(["http://localhost:5173", "http://127.0.0.1:5173"])
        return list(dict.fromkeys(configured))


settings = Settings()
