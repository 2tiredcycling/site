import json
from functools import wraps
import hmac
import ipaddress
import secrets

from flask import abort, g, redirect, request, session, url_for

from app.models import (
    PAGE_ACCOUNTS,
    PAGE_ACTIVITIES,
    PAGE_ANALYTICS,
    PAGE_ANNOUNCEMENTS,
    PAGE_AUDIT_LOGS,
    PAGE_FEEDBACK,
    PAGE_KEYS,
    PAGE_KIT_PREORDERS,
    PAGE_PERMISSION_RANKS,
    PAGE_ROUTES,
    PAGE_SECURITY,
    PERMISSION_ADMIN,
    PERMISSION_NONE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    User,
)
from app.services import write_audit_log


def client_ip() -> str:
    # Prefer CDN-provided real client IP, then proxy chain, then direct source.
    candidates = [
        request.headers.get("CF-Connecting-IP"),
        request.headers.get("X-Forwarded-For"),
        request.headers.get("X-Real-IP"),
        request.remote_addr,
    ]
    for raw in candidates:
        value = _first_valid_ip(raw)
        if value:
            return value
    return "unknown"


def _first_valid_ip(raw: str | None) -> str | None:
    if not raw:
        return None
    for part in str(raw).split(","):
        value = part.strip()
        if not value:
            continue
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return None


def _build_unauth_detail() -> str:
    return json.dumps(
        {
            "path": request.path,
            "method": request.method,
            "ip": client_ip(),
            "user_agent": (request.user_agent.string or "")[:255],
            "query": request.query_string.decode("utf-8", errors="ignore")[:255],
        },
        ensure_ascii=False,
    )


def current_user() -> User | None:
    if hasattr(g, "current_user"):
        return g.current_user
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.filter_by(id=user_id, is_active=True).first()


def attach_current_user() -> None:
    g.current_user = current_user()


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user():
            write_audit_log(
                actor_id=None,
                action="auth.required_redirect",
                target_type="admin",
                target_id=request.path,
                detail=_build_unauth_detail(),
            )
            return redirect(url_for("admin.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def role_required(*roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                write_audit_log(
                    actor_id=None,
                    action="auth.required_redirect",
                    target_type="admin",
                    target_id=request.path,
                    detail=_build_unauth_detail(),
                )
                return redirect(url_for("admin.login", next=request.path))
            if user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def get_page_permission(user: User | None, page_key: str) -> str:
    if not user or not user.is_active or page_key not in PAGE_KEYS:
        return PERMISSION_NONE
    for item in user.page_permissions:
        if item.page_key == page_key:
            if item.permission_level in PAGE_PERMISSION_RANKS:
                return item.permission_level
            return PERMISSION_NONE
    return PERMISSION_NONE


def has_page_permission(user: User | None, page_key: str, required_level: str) -> bool:
    required_rank = PAGE_PERMISSION_RANKS.get(required_level, 0)
    actual_rank = PAGE_PERMISSION_RANKS.get(get_page_permission(user, page_key), 0)
    return actual_rank >= required_rank


def can_read_page(user: User | None, page_key: str) -> bool:
    return has_page_permission(user, page_key, PERMISSION_READ)


def can_write_page(user: User | None, page_key: str) -> bool:
    return has_page_permission(user, page_key, PERMISSION_WRITE)


def can_admin_page(user: User | None, page_key: str) -> bool:
    return has_page_permission(user, page_key, PERMISSION_ADMIN)


def can_edit(user: User | None) -> bool:
    if not user:
        return False
    return any(
        can_write_page(user, page_key)
        for page_key in (PAGE_ROUTES, PAGE_ACTIVITIES, PAGE_KIT_PREORDERS, PAGE_ANNOUNCEMENTS)
    )


def can_review(user: User | None) -> bool:
    if not user:
        return False
    return can_write_page(user, PAGE_FEEDBACK)


def can_manage_users(user: User | None) -> bool:
    if not user:
        return False
    return can_read_page(user, PAGE_ACCOUNTS)


def can_view_analytics(user: User | None) -> bool:
    if not user:
        return False
    return can_read_page(user, PAGE_ANALYTICS)


def can_view_security(user: User | None) -> bool:
    if not user:
        return False
    return can_read_page(user, PAGE_SECURITY)


def can_view_audit_logs(user: User | None) -> bool:
    if not user:
        return False
    return can_read_page(user, PAGE_AUDIT_LOGS)


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def validate_csrf_token(value: str | None) -> bool:
    if not value:
        return False
    token = session.get("csrf_token")
    if not token:
        return False
    return hmac.compare_digest(token, value)
