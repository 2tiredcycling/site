from functools import wraps
import hmac
import secrets

from flask import abort, g, redirect, request, session, url_for

from app.models import ROLE_ADMIN, ROLE_EDITOR, ROLE_REVIEWER, User


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
            return redirect(url_for("admin.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def role_required(*roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("admin.login", next=request.path))
            if user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def can_edit(user: User | None) -> bool:
    if not user:
        return False
    return user.role in (ROLE_ADMIN, ROLE_EDITOR)


def can_review(user: User | None) -> bool:
    if not user:
        return False
    return user.role in (ROLE_ADMIN, ROLE_REVIEWER)


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
