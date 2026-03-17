import logging
import os
from pathlib import Path

from flask import Flask, Response, redirect, request, url_for
from dotenv import load_dotenv

from app.models import AccessLog, db
from app.routes_admin import bp as admin_bp
from app.routes_api_v1 import bp as api_v1_bp
from app.routes_legacy import bp as legacy_bp
from app.routes_web import bp as web_bp
from app.security_monitor import is_probe_path, is_watchlist_probe_path, should_throttle_probe
from app.services import ensure_default_admin, ensure_schema_compat, ensure_seed_data


def create_app() -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    app = Flask(__name__, instance_relative_config=True)

    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        app.config.from_object("config.ProductionConfig")
    else:
        app.config.from_object("config.DevelopmentConfig")
    _validate_production_security(app, env)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    _ensure_sqlite_parent_dir(app)

    db.init_app(app)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_v1_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(legacy_bp)
    _setup_logging(app)

    with app.app_context():
        db.create_all()
        ensure_schema_compat()
        ensure_default_admin(
            app.config.get("DEFAULT_ADMIN_USERNAME", ""),
            app.config.get("DEFAULT_ADMIN_PASSWORD", ""),
        )
        if app.config.get("SEED_DEMO_DATA", False):
            ensure_seed_data(app)

    @app.before_request
    def guard_probe_requests():
        path = request.path or ""
        if path.startswith("/manage") or path.startswith("/static/"):
            return None

        user_agent = request.user_agent.string or ""
        allowed, retry_after = should_throttle_probe(path, user_agent)
        if not allowed:
            return Response("Too Many Requests", status=429, mimetype="text/plain", headers={"Retry-After": str(retry_after)})

        # Drop common probe paths early, before they hit expensive handlers.
        if is_probe_path(path):
            if is_watchlist_probe_path(path):
                app.logger.warning(
                    "security.watchlist_probe path=%s ip=%s ua=%s",
                    path,
                    request.headers.get("X-Forwarded-For", request.remote_addr),
                    (request.user_agent.string or "")[:200],
                )
            return Response("Not Found", status=404, mimetype="text/plain")
        return None

    @app.before_request
    def log_access() -> None:
        app.logger.info("access method=%s path=%s ip=%s", request.method, request.path, request.remote_addr)

    @app.after_request
    def persist_access_log(response):
        path = request.path or ""
        if path.startswith("/static/") or path == "/favicon.ico":
            return response

        try:
            forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            ip_address = forwarded or request.remote_addr or "unknown"
            db.session.add(
                AccessLog(
                    path=path[:255],
                    method=(request.method or "GET")[:16],
                    endpoint=(request.endpoint or "")[:128],
                    status_code=int(response.status_code or 0),
                    ip_address=ip_address[:64],
                    user_agent=(request.user_agent.string or "")[:255],
                    referer=(request.referrer or "")[:255],
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning("persist access log failed path=%s", path, exc_info=True)
        return response

    @app.get("/favicon.ico")
    def favicon_ico():
        return redirect(url_for("static", filename="favicon.svg"), code=302)

    return app


def _setup_logging(app: Flask) -> None:
    level = logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    app.logger.handlers.clear()
    app.logger.addHandler(stream_handler)
    app.logger.setLevel(level)


def _ensure_sqlite_parent_dir(app: Flask) -> None:
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///"):
        return
    db_path = uri.replace("sqlite:///", "", 1)
    if db_path == ":memory:":
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _validate_production_security(app: Flask, env: str) -> None:
    if env != "production":
        return

    secret_key = app.config.get("SECRET_KEY", "")
    admin_password = app.config.get("ADMIN_PASSWORD", "")
    default_admin_password = app.config.get("DEFAULT_ADMIN_PASSWORD", "")

    bad_secret = not secret_key or secret_key == "change-this-in-production"
    bad_admin = not admin_password or admin_password == "change-me-admin"
    bad_default_admin = _is_weak_password(default_admin_password)
    if bad_secret or bad_admin or bad_default_admin:
        raise RuntimeError(
            "Production security check failed: set strong SECRET_KEY, ADMIN_PASSWORD and DEFAULT_ADMIN_PASSWORD."
        )


def _is_weak_password(value: str) -> bool:
    if not value:
        return True
    common_bad = {
        "123456",
        "password",
        "admin",
        "admin123",
        "change-me-admin",
        "replace-with-strong-password",
        "replace-with-a-strong-admin-password-12plus",
        "replace-with-a-strong-legacy-password",
    }
    if value.lower() in common_bad:
        return True
    return len(value) < 12
