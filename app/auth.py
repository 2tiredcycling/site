import json
from functools import wraps
import hmac
import secrets

from flask import abort, g, redirect, request, session, url_for

from app.models import ROLE_SUPER_ADMIN, User
from app.services import write_audit_log


def client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"


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


def can_edit(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_edit_content)


def can_review(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_review)


def can_manage_users(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_manage_users)


def can_view_analytics(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_view_analytics)


def can_view_security(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_view_security)


def can_view_audit_logs(user: User | None) -> bool:
    if not user:
        return False
    if user.role == ROLE_SUPER_ADMIN:
        return True
    return bool(user.perm_view_audit_logs)


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
