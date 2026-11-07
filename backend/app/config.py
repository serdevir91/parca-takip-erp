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
    password_min_length: int = 8
    login_attempts: int = 5
    login_lock_minutes: int = 15
    disabled_modules: list[str] = []
    admin_user: str = "admin"
    admin_password: str = "admin"
    # Interactive API docs at /api/docs (off by default: they map the whole API without a login)
    api_docs: bool = False
    app_version: str = "1.9.4"
    # Optional URL of a JSON file {"version": "x.y.z", "notes": "..."} on the LAN
    update_feed_url: str = ""
    max_upload_mb: int = 2048
    # Daily backup time (HH:MM) for "backup --daemon" and "serve"
    backup_time: str = "02:00"
    # Built SPA (frontend/dist) served by the backend itself when running without Docker/nginx.
    # Empty: use ../frontend/dist next to the backend folder if it exists (never true inside the image).
    static_dir: Path | None = None

    @property
    def spa_dir(self) -> Path | None:
        d = self.static_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist"
        return d if (d / "index.html").is_file() else None

    @property
    def bom_dir(self) -> Path:
        return self.data_dir / "bom"

    @property
    def drawing_dir(self) -> Path:
        return self.data_dir / "drawings"

    @property
    def thumb_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def photo_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def chat_dir(self) -> Path:
        return self.data_dir / "chat"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    ensure_jwt_secret(s)
    return s


WEAK_SECRETS = {"", "change-me", "changeme", "secret", "please-change-me", "erp", "parca-takip",
                "degistir-bunu-uzun-rastgele-bir-anahtar"}


def ensure_jwt_secret(cfg: Settings) -> None:
    """Replace a missing, default or short JWT secret with a random one kept in data_dir/.jwt_secret.

    A known secret lets anyone forge admin tokens, so installs that copied .env.example or left the
    default still get a private key. The file survives restarts; deleting it logs everyone out.
    """
    import secrets

    if cfg.jwt_secret not in WEAK_SECRETS and len(cfg.jwt_secret) >= 32:
        return
    f = cfg.data_dir / ".jwt_secret"
    try:
        stored = f.read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    if len(stored) < 32:
        stored = secrets.token_urlsafe(48)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(stored, encoding="utf-8")
            f.chmod(0o600)
        except OSError:  # read-only data dir: the secret lasts until the next restart
            pass
    cfg.jwt_secret = stored

