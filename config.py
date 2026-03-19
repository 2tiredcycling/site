import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _resolve_database_uri() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        return f"sqlite:///{(BASE_DIR / 'instance' / 'app.db').as_posix()}"

    if raw.startswith("sqlite:///"):
        db_path_raw = raw.replace("sqlite:///", "", 1)
        if db_path_raw == ":memory:":
            return raw
        db_path = Path(db_path_raw)
        if not db_path.is_absolute():
            db_path = (BASE_DIR / db_path).resolve()
        return f"sqlite:///{db_path.as_posix()}"

    return raw


def _resolve_upload_folder() -> str:
    raw = os.getenv("UPLOAD_FOLDER")
    if not raw:
        return str(BASE_DIR / "uploads" / "gpx")
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str((BASE_DIR / path).resolve())


class BaseConfig:
    APP_VERSION = (os.getenv("APP_VERSION", "v3.3.2") or "").strip()
    APP_DEPLOYED_AT = os.getenv("APP_DEPLOYED_AT", "")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-admin")
    DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", ADMIN_PASSWORD)
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = _resolve_upload_folder()
    SEED_DEMO_DATA = False
    BACKUP_DIR = os.getenv("BACKUP_DIR", str(BASE_DIR / "backups"))
    MAX_GPX_BYTES = int(os.getenv("MAX_GPX_BYTES", str(5 * 1024 * 1024)))
    MAX_MEDIA_BYTES = int(os.getenv("MAX_MEDIA_BYTES", str(10 * 1024 * 1024)))
    ALLOWED_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() == "true"
    REQUEST_CONSOLE_LOG_ENABLED = os.getenv("REQUEST_CONSOLE_LOG_ENABLED", "false").strip().lower() == "true"
    ACCESS_LOG_ASYNC = os.getenv("ACCESS_LOG_ASYNC", "true").strip().lower() == "true"
    ACCESS_LOG_BATCH_SIZE = int(os.getenv("ACCESS_LOG_BATCH_SIZE", "100"))
    ACCESS_LOG_FLUSH_INTERVAL = float(os.getenv("ACCESS_LOG_FLUSH_INTERVAL", "1.0"))
    ACCESS_LOG_QUEUE_MAX = int(os.getenv("ACCESS_LOG_QUEUE_MAX", "5000"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SEED_DEMO_DATA = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
