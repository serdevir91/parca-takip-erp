"""Runtime settings, read from environment variables (see docker-compose.yml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://erp:erp@db:5432/erp"
    data_dir: Path = Path("/data")            # uploaded BOM files, drawings, thumbnails
    backup_dir: Path = Path("/backups")
    backup_keep_days: int = 14
    jwt_secret: str = "change-me"
    jwt_expire_hours: int = 12
    admin_user: str = "admin"
    admin_password: str = "admin"
    app_version: str = "1.0.0"
    # Optional URL of a JSON file {"version": "x.y.z", "notes": "..."} on the LAN
    update_feed_url: str = ""
    max_upload_mb: int = 2048

    @property
    def bom_dir(self) -> Path:
        return self.data_dir / "bom"

    @property
    def drawing_dir(self) -> Path:
        return self.data_dir / "drawings"

    @property
    def thumb_dir(self) -> Path:
        return self.data_dir / "thumbs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
