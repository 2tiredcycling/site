import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import StringIO
import mimetypes
from pathlib import Path
import re
import secrets

from sqlalchemy import or_
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.auth import (
    attach_current_user,
    can_edit,
    can_manage_users,
    can_review,
    can_view_analytics,
    can_view_audit_logs,
    can_view_security,
    client_ip,
    get_csrf_token,
    login_required,
    validate_csrf_token,
)
from app.models import (
    CONTENT_STATUS_DRAFT,
    CONTENT_STATUS_OFFLINE,
    CONTENT_STATUS_PUBLISHED,
    FEEDBACK_APPROVED,
    FEEDBACK_PENDING,
    FEEDBACK_REJECTED,
    ROLE_CONTENT_ADMIN,
    ROLE_OPS_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_VIEWER,
    ROLES,
    ROUTE_STATUSES,
    SITE_FEEDBACK_DONE,
    SITE_FEEDBACK_PENDING,
    STATUS_DRAFT,
    STATUS_OFFLINE,
    STATUS_PENDING_REVIEW,
    STATUS_PUBLISHED,
    Activity,
    ActivityRouteOption,
    AccessLog,
    AuditLog,
    Announcement,
    ImportReport,
    MediaAsset,
    Route,
    RouteFeedback,
    RouteVersion,
    SiteFeedback,
    User,
    db,
    utcnow,
)
from app.querying import query_routes_from_request
from app.gpx_utils import parse_gpx_points_and_stats, parse_gpx_waypoints
from app.route_ops import allowed_file, file_size_ok, parse_distance, save_gpx_file
from app.security_monitor import WATCHLIST_PROBE_PATHS, build_non_probe_filters
from app.security_limits import check_lock, clear_state, register_failure
from app.services import (
    approved_rating_summary,
    create_route_version,
    rollback_route_to_version,
    route_snapshot,
    save_import_report,
    write_audit_log,
    write_field_audit_log,
)

bp = Blueprint("admin", __name__, url_prefix="/manage")
SH_TZ = timezone(timedelta(hours=8))
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
PERMISSION_FIELDS = (
    "perm_view_analytics",
    "perm_view_security",
    "perm_review",
    "perm_edit_content",
    "perm_manage_users",
    "perm_view_audit_logs",
)
ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "super_admin（最高权限）",
    ROLE_OPS_ADMIN: "ops_admin（安全运维）",
    ROLE_CONTENT_ADMIN: "content_admin（内容维护）",
    ROLE_VIEWER: "viewer（只读）",
}
ACTIVITY_ROUTE_LEVELS = (
    ("beginner", "初级"),
    ("intermediate", "中级"),
    ("advanced", "高级"),
)


def _display_app_version() -> str:
    raw = str(current_app.config.get("APP_VERSION", "") or "").strip()
    if not raw:
        return "unknown"
    if re.fullmatch(r"\d+\.\d+\.\d+", raw):
        return f"v{raw}"
    return raw


def _to_local_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SH_TZ)


def _deployed_at_utc() -> datetime | None:
    raw = (current_app.config.get("APP_DEPLOYED_AT") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SH_TZ)
    return parsed.astimezone(timezone.utc)


def _resolve_period_start(days: int, scope: str, now: datetime) -> tuple[str, datetime, str]:
    deployed = _deployed_at_utc()
    if scope == "post_deploy" and deployed is not None:
        local = _to_local_time(deployed)
        return "post_deploy", deployed, f"上线后（{local.strftime('%Y-%m-%d %H:%M')}）"
    start = now - timedelta(days=days)
    return "recent", start, f"最近 {days} 天"


def _watchlist_probe_expression():
    conditions = [AccessLog.path.in_(WATCHLIST_PROBE_PATHS), AccessLog.path.like("/wordpress/wp-admin/%")]
    return or_(*conditions)


def _probe_expression():
    suffixes = (".php", ".asp", ".aspx", ".jsp", ".bak", ".sql", ".zip", ".tar.gz")
    prefixes = ("/wp-", "/wordpress", "/xmlrpc.php", "/phpmyadmin", "/pma", "/.git", "/.env", "/vendor", "/cgi-bin")
    conditions = [AccessLog.path.like(f"{prefix}%") for prefix in prefixes]
    conditions.extend([AccessLog.path.like(f"%{suffix}") for suffix in suffixes])
    conditions.append(AccessLog.path.like("%../%"))
    conditions.append(AccessLog.path.ilike("%2e%2e%"))
    conditions.append(_watchlist_probe_expression())
    return or_(*conditions)


def _default_permissions_for_role(role: str) -> dict[str, bool]:
    role = (role or "").strip()
    if role == ROLE_SUPER_ADMIN:
        return {item: True for item in PERMISSION_FIELDS}
    if role == ROLE_CONTENT_ADMIN:
        return {
            "perm_view_analytics": True,
            "perm_view_security": False,
            "perm_review": True,
            "perm_edit_content": True,
            "perm_manage_users": False,
            "perm_view_audit_logs": False,
        }
    if role == ROLE_OPS_ADMIN:
        return {
            "perm_view_analytics": True,
            "perm_view_security": True,
            "perm_review": True,
            "perm_edit_content": False,
            "perm_manage_users": False,
            "perm_view_audit_logs": True,
        }
    return {
        "perm_view_analytics": False,
        "perm_view_security": False,
        "perm_review": False,
        "perm_edit_content": False,
        "perm_manage_users": False,
        "perm_view_audit_logs": False,
    }


def _permissions_from_form(role: str) -> dict[str, bool]:
    defaults = _default_permissions_for_role(role)
    if role == ROLE_SUPER_ADMIN:
        return defaults
    result: dict[str, bool] = {}
    for field in PERMISSION_FIELDS:
        result[field] = (request.form.get(field) or "0").strip() == "1"
    if not any(result.values()):
        return defaults
    return result


def _save_activity_media(activity_id: int, uploads, activity_route_option_id: int | None = None) -> int:
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    media_dir.mkdir(parents=True, exist_ok=True)
    allowed_exts = {str(item).lower() for item in current_app.config.get("ALLOWED_MEDIA_EXTENSIONS", set())}
    max_media_bytes = int(current_app.config.get("MAX_MEDIA_BYTES", 10 * 1024 * 1024))

    saved_count = 0
    for upload in uploads:
        if not upload or not (upload.filename or "").strip():
            continue
        original_name = secure_filename(Path(upload.filename).name)
        ext = Path(original_name).suffix.lower()
        if not original_name or ext not in allowed_exts:
            continue
        if not file_size_ok(upload, max_media_bytes):
            continue

        token = f"activity_{activity_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{secrets.token_hex(4)}{ext}"
        target_path = media_dir / token
        upload.save(target_path)
        mime_type = (upload.mimetype or "").strip() or (mimetypes.guess_type(original_name)[0] or "application/octet-stream")
        db.session.add(
            MediaAsset(
                activity_id=activity_id,
                activity_route_option_id=activity_route_option_id,
                original_filename=original_name[:255],
                storage_path=token,
                mime_type=mime_type[:128],
                size_bytes=int(target_path.stat().st_size),
                created_at=utcnow(),
            )
        )
        saved_count += 1
    return saved_count


@bp.before_app_request
def _load_user():
    attach_current_user()


@bp.before_request
def _verify_csrf_for_post():
    if request.method != "POST":
        return
    token = request.form.get("csrf_token")
    if not validate_csrf_token(token):
        abort(400, description="Invalid CSRF token")


@bp.before_request
def _enforce_permission_matrix():
    if not getattr(g, "current_user", None):
        return
    path = request.path or ""
    if path in {"/manage/login"}:
        return
    user = g.current_user
    if path.startswith("/manage/users") and not can_manage_users(user):
        abort(403)
    if path.startswith("/manage/analytics") and not can_view_analytics(user):
        abort(403)
    if path.startswith("/manage/security") and not can_view_security(user):
        abort(403)
    if path.startswith("/manage/audit-logs") and not can_view_audit_logs(user):
        abort(403)
    if (
        path.startswith("/manage/routes")
        or path.startswith("/manage/activities")
        or path.startswith("/manage/announcements")
        or path.startswith("/manage/bulk-import")
    ) and not can_edit(user):
        abort(403)
    if (
        path.startswith("/manage/feedback")
        or path.startswith("/manage/site-feedback")
    ) and not can_review(user):
        abort(403)
    if path.startswith("/manage/import-report") and not (can_edit(user) or can_review(user)):
        abort(403)


@bp.app_context_processor
def _inject_csrf_token():
    return {
        "csrf_token": get_csrf_token,
        "to_local_time": _to_local_time,
        "app_version": _display_app_version(),
    }


@bp.get("/login")
def login():
    if g.current_user:
        return redirect(url_for("admin.dashboard"))
    return render_template("manage_login.html")


@bp.post("/login")
def login_submit():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    source_ip = client_ip()
    user_agent = (request.user_agent.string or "")[:255]
    request_path = request.path
    login_subject = f"{source_ip}:{username.lower() or '_'}"

    retry_after = check_lock("admin_login", login_subject, LOGIN_WINDOW_SECONDS)
    if retry_after > 0:
        flash(f"登录过于频繁，请 {retry_after} 秒后再试", "error")
        return redirect(url_for("admin.login"))

    user = User.query.filter_by(username=username, is_active=True).first()
    if not user or not check_password_hash(user.password, password):
        retry_after = register_failure(
            "admin_login",
            login_subject,
            max_attempts=LOGIN_MAX_FAILURES,
            window_seconds=LOGIN_WINDOW_SECONDS,
            lock_seconds=LOGIN_LOCK_SECONDS,
        )
        if retry_after > 0:
            flash(f"登录过于频繁，请 {retry_after} 秒后再试", "error")
        else:
            flash("用户名或密码错误", "error")
        write_audit_log(
            None,
            "auth.login_failed",
            "user",
            username or None,
            f'ip={source_ip};path={request_path};ua="{user_agent}";retry_after={retry_after}',
        )
        return redirect(url_for("admin.login"))

    clear_state("admin_login", login_subject)
    session["user_id"] = user.id
    write_audit_log(
        user.id,
        "auth.login",
        "user",
        str(user.id),
        f'ip={source_ip};path={request_path};ua="{user_agent}"',
    )
    return redirect(url_for("admin.dashboard"))


@bp.post("/logout")
@login_required
def logout():
    actor_id = g.current_user.id if g.current_user else None
    session.pop("user_id", None)
    write_audit_log(actor_id, "auth.logout", "user", str(actor_id) if actor_id else None, "logout")
    return redirect(url_for("admin.login"))


@bp.get("")
@login_required
def dashboard():
    log_page = max(1, request.args.get("log_page", default=1, type=int))
    now = utcnow()
    start_24h = now - timedelta(hours=24)
    can_view_analytics_flag = can_view_analytics(g.current_user)
    can_view_security_flag = can_view_security(g.current_user)
    can_review_flag = can_review(g.current_user)
    can_manage_users_flag = can_manage_users(g.current_user)
    can_view_audit_logs_flag = can_view_audit_logs(g.current_user)
    can_edit_flag = can_edit(g.current_user)

    pending_feedback_count = RouteFeedback.query.filter_by(status=FEEDBACK_PENDING).count() if can_review_flag else 0
    pending_site_feedback_count = SiteFeedback.query.filter_by(status=SITE_FEEDBACK_PENDING).count() if can_review_flag else 0
    audit_logs_pagination = (
        AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(page=log_page, per_page=5, error_out=False)
        if can_view_audit_logs_flag
        else None
    )
    latest_routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).limit(3).all() if can_edit_flag else []
    latest_activities = Activity.query.order_by(Activity.activity_time.desc()).limit(3).all() if can_edit_flag else []
    latest_announcements = (
        Announcement.query.order_by(
            Announcement.is_pinned.desc(),
            Announcement.sort_order.desc(),
            db.func.coalesce(Announcement.published_at, Announcement.updated_at).desc(),
        )
        .limit(3)
        .all()
        if can_edit_flag
        else []
    )
    latest_feedback = RouteFeedback.query.order_by(RouteFeedback.created_at.desc()).limit(3).all() if can_review_flag else []
    latest_site_feedback = SiteFeedback.query.order_by(SiteFeedback.created_at.desc()).limit(3).all() if can_review_flag else []
    summary = {
        "route_total": Route.query.filter_by(is_deleted=False).count(),
        "route_deleted": Route.query.filter_by(is_deleted=True).count(),
        "activity_total": Activity.query.count(),
        "announcement_total": Announcement.query.count(),
        "feedback_pending": pending_feedback_count,
        "site_feedback_pending": pending_site_feedback_count,
    }
    security_summary = {"probe_24h": 0, "watchlist_24h": 0, "blocked_429_24h": 0, "probe_ip_24h": 0}
    if can_view_security_flag:
        probe_filter_24h = (
            AccessLog.created_at >= start_24h,
            ~AccessLog.path.like("/manage%"),
            _probe_expression(),
        )
        security_summary = {
            "probe_24h": AccessLog.query.filter(*probe_filter_24h).count(),
            "watchlist_24h": AccessLog.query.filter(
                AccessLog.created_at >= start_24h,
                ~AccessLog.path.like("/manage%"),
                _watchlist_probe_expression(),
            ).count(),
            "blocked_429_24h": AccessLog.query.filter(
                AccessLog.created_at >= start_24h,
                ~AccessLog.path.like("/manage%"),
                AccessLog.status_code == 429,
            ).count(),
            "probe_ip_24h": int(
                db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
                .filter(*probe_filter_24h)
                .scalar()
                or 0
            ),
        }
    analytics_summary = {"pv_24h": 0, "uv_24h": 0, "active_5m": 0}
    if can_view_analytics_flag:
        analytics_summary = {
            "pv_24h": AccessLog.query.filter(
                AccessLog.created_at >= start_24h,
                *build_non_probe_filters(AccessLog),
            ).count(),
            "uv_24h": int(
                db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
                .filter(
                    AccessLog.created_at >= start_24h,
                    *build_non_probe_filters(AccessLog),
                )
                .scalar()
                or 0
            ),
            "active_5m": int(
                db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
                .filter(
                    AccessLog.created_at >= (now - timedelta(minutes=5)),
                    *build_non_probe_filters(AccessLog),
                )
                .scalar()
                or 0
            ),
        }
    return render_template(
        "manage.html",
        summary=summary,
        analytics_summary=analytics_summary,
        audit_logs=audit_logs_pagination.items if audit_logs_pagination else [],
        audit_logs_pagination=audit_logs_pagination,
        latest_routes=latest_routes,
        latest_activities=latest_activities,
        latest_announcements=latest_announcements,
        latest_feedback=latest_feedback,
        latest_site_feedback=latest_site_feedback,
        security_summary=security_summary,
        can_review=can_review_flag,
        can_manage_users=can_manage_users_flag,
        can_view_analytics=can_view_analytics_flag,
        can_view_security=can_view_security_flag,
        can_view_audit_logs=can_view_audit_logs_flag,
        can_edit=can_edit_flag,
    )


@bp.get("/audit-logs")
@login_required
def audit_logs_page():
    page = max(1, request.args.get("page", default=1, type=int))
    pagination = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("manage_audit_logs.html", logs=pagination.items, pagination=pagination)


@bp.get("/analytics")
@login_required
def analytics_page():
    days = request.args.get("days", default=7, type=int)
    if days not in {1, 7, 30}:
        days = 7
    scope = (request.args.get("scope") or "recent").strip()
    if scope not in {"recent", "post_deploy"}:
        scope = "recent"

    now = utcnow()
    scope, start_recent, period_label = _resolve_period_start(days, scope, now)
    start_recent_date = _to_local_time(start_recent).date()
    today_local = _to_local_time(now).date()

    recent_base_filter = (AccessLog.created_at >= start_recent, *build_non_probe_filters(AccessLog))
    recent_raw_filter = (
        AccessLog.created_at >= start_recent,
        ~AccessLog.path.like("/manage%"),
    )
    total_base_filter = (
        AccessLog.created_at >= start_recent,
        *build_non_probe_filters(AccessLog),
    ) if scope == "post_deploy" else build_non_probe_filters(AccessLog)
    total_raw_filter = (
        AccessLog.created_at >= start_recent,
        ~AccessLog.path.like("/manage%"),
    ) if scope == "post_deploy" else (~AccessLog.path.like("/manage%"),)
    recent_pv = AccessLog.query.filter(*recent_base_filter).count()
    recent_uv = (
        db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
        .filter(*recent_base_filter)
        .scalar()
        or 0
    )
    recent_errors_4xx = AccessLog.query.filter(
        *recent_base_filter,
        AccessLog.status_code >= 400,
        AccessLog.status_code < 500,
    ).count()
    recent_errors_5xx = AccessLog.query.filter(
        *recent_base_filter,
        AccessLog.status_code >= 500,
    ).count()
    recent_downloads = AccessLog.query.filter(
        *recent_base_filter,
        AccessLog.path.like("/download/%"),
        AccessLog.status_code == 200,
    ).count()
    recent_raw_requests = AccessLog.query.filter(*recent_raw_filter).count()
    recent_probe_excluded = max(0, recent_raw_requests - recent_pv)
    recent_probe_ratio = round((recent_probe_excluded / recent_raw_requests) * 100, 2) if recent_raw_requests else 0.0

    total_pv = AccessLog.query.filter(*total_base_filter).count()
    total_uv = (
        db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
        .filter(*total_base_filter)
        .scalar()
        or 0
    )
    total_errors_4xx = AccessLog.query.filter(
        *total_base_filter,
        AccessLog.status_code >= 400,
        AccessLog.status_code < 500,
    ).count()
    total_errors_5xx = AccessLog.query.filter(
        *total_base_filter,
        AccessLog.status_code >= 500,
    ).count()
    total_downloads = AccessLog.query.filter(
        *total_base_filter,
        AccessLog.path.like("/download/%"),
        AccessLog.status_code == 200,
    ).count()
    total_raw_requests = AccessLog.query.filter(*total_raw_filter).count()
    total_probe_excluded = max(0, total_raw_requests - total_pv)
    total_probe_ratio = round((total_probe_excluded / total_raw_requests) * 100, 2) if total_raw_requests else 0.0

    top_pages_rows = (
        db.session.query(
            AccessLog.path,
            db.func.count(AccessLog.id).label("hits"),
        )
        .filter(*recent_base_filter)
        .group_by(AccessLog.path)
        .order_by(db.text("hits DESC"))
        .limit(10)
        .all()
    )
    top_pages = [{"path": row[0], "hits": int(row[1] or 0)} for row in top_pages_rows]

    logs_recent = (
        db.session.query(AccessLog.created_at, AccessLog.path, AccessLog.status_code)
        .filter(*recent_base_filter)
        .all()
    )
    daily_map: dict = defaultdict(lambda: {"pv": 0, "downloads": 0})
    for created_at, path, status_code in logs_recent:
        local_day = _to_local_time(created_at).date()
        daily_map[local_day]["pv"] += 1
        if (path or "").startswith("/download/") and status_code == 200:
            daily_map[local_day]["downloads"] += 1

    daily_stats = []
    current = start_recent_date
    while current <= today_local:
        row = daily_map[current]
        daily_stats.append({"date": current.strftime("%Y-%m-%d"), "pv": row["pv"], "downloads": row["downloads"]})
        current += timedelta(days=1)

    return render_template(
        "manage_analytics.html",
        days=days,
        scope=scope,
        period_label=period_label,
        can_view_security=can_view_security(g.current_user),
        recent={
            "pv": recent_pv,
            "uv": int(recent_uv),
            "errors_4xx": recent_errors_4xx,
            "errors_5xx": recent_errors_5xx,
            "downloads": recent_downloads,
            "raw_requests": recent_raw_requests,
            "probe_excluded": recent_probe_excluded,
            "probe_ratio": recent_probe_ratio,
        },
        total={
            "pv": total_pv,
            "uv": int(total_uv),
            "errors_4xx": total_errors_4xx,
            "errors_5xx": total_errors_5xx,
            "downloads": total_downloads,
            "raw_requests": total_raw_requests,
            "probe_excluded": total_probe_excluded,
            "probe_ratio": total_probe_ratio,
        },
        top_pages=top_pages,
        daily_stats=daily_stats,
    )


@bp.get("/security")
@login_required
def security_page():
    days = request.args.get("days", default=7, type=int)
    if days not in {1, 7, 30}:
        days = 7
    scope = (request.args.get("scope") or "recent").strip()
    if scope not in {"recent", "post_deploy"}:
        scope = "recent"

    now = utcnow()
    scope, start_recent, period_label = _resolve_period_start(days, scope, now)
    start_recent_date = _to_local_time(start_recent).date()
    today_local = _to_local_time(now).date()
    base_filter = (
        AccessLog.created_at >= start_recent,
        ~AccessLog.path.like("/manage%"),
    )
    probe_expr = _probe_expression()
    watchlist_expr = _watchlist_probe_expression()
    security_expr = or_(probe_expr, AccessLog.status_code == 429)

    recent_probe = AccessLog.query.filter(*base_filter, probe_expr).count()
    recent_watchlist = AccessLog.query.filter(*base_filter, watchlist_expr).count()
    recent_throttled = AccessLog.query.filter(*base_filter, AccessLog.status_code == 429).count()
    recent_errors_4xx = AccessLog.query.filter(
        *base_filter,
        AccessLog.status_code >= 400,
        AccessLog.status_code < 500,
    ).count()
    recent_errors_5xx = AccessLog.query.filter(*base_filter, AccessLog.status_code >= 500).count()
    recent_probe_ip = int(
        db.session.query(db.func.count(db.distinct(AccessLog.ip_address)))
        .filter(*base_filter, security_expr)
        .scalar()
        or 0
    )

    top_paths_rows = (
        db.session.query(AccessLog.path, db.func.count(AccessLog.id).label("hits"))
        .filter(*base_filter, security_expr)
        .group_by(AccessLog.path)
        .order_by(db.text("hits DESC"))
        .limit(10)
        .all()
    )
    top_ips_rows = (
        db.session.query(AccessLog.ip_address, db.func.count(AccessLog.id).label("hits"))
        .filter(*base_filter, security_expr)
        .group_by(AccessLog.ip_address)
        .order_by(db.text("hits DESC"))
        .limit(10)
        .all()
    )
    top_uas_rows = (
        db.session.query(AccessLog.user_agent, db.func.count(AccessLog.id).label("hits"))
        .filter(*base_filter, security_expr, AccessLog.user_agent != "")
        .group_by(AccessLog.user_agent)
        .order_by(db.text("hits DESC"))
        .limit(10)
        .all()
    )

    top_paths = [{"path": row[0], "hits": int(row[1] or 0)} for row in top_paths_rows]
    top_ips = [{"ip": row[0] or "unknown", "hits": int(row[1] or 0)} for row in top_ips_rows]
    top_uas = [{"ua": row[0] or "-", "hits": int(row[1] or 0)} for row in top_uas_rows]

    event_page = max(1, request.args.get("event_page", default=1, type=int))
    event_type = (request.args.get("event_type") or "all").strip().lower()
    if event_type not in {"all", "watchlist", "probe", "throttled"}:
        event_type = "all"
    event_status = (request.args.get("event_status") or "all").strip().lower()
    if event_status not in {"all", "4xx", "5xx", "429"}:
        event_status = "all"
    event_q = (request.args.get("event_q") or "").strip()

    event_query = AccessLog.query.filter(*base_filter, security_expr)
    if event_type == "watchlist":
        event_query = event_query.filter(watchlist_expr)
    elif event_type == "probe":
        event_query = event_query.filter(probe_expr)
    elif event_type == "throttled":
        event_query = event_query.filter(AccessLog.status_code == 429)

    if event_status == "4xx":
        event_query = event_query.filter(AccessLog.status_code >= 400, AccessLog.status_code < 500)
    elif event_status == "5xx":
        event_query = event_query.filter(AccessLog.status_code >= 500)
    elif event_status == "429":
        event_query = event_query.filter(AccessLog.status_code == 429)

    if event_q:
        pattern = f"%{event_q}%"
        event_query = event_query.filter(
            or_(
                AccessLog.path.ilike(pattern),
                AccessLog.ip_address.ilike(pattern),
                AccessLog.user_agent.ilike(pattern),
            )
        )

    events_pagination = event_query.order_by(AccessLog.created_at.desc()).paginate(
        page=event_page, per_page=50, error_out=False
    )
    logs_recent = events_pagination.items
    logs_for_trend = (
        db.session.query(AccessLog.created_at, AccessLog.path, AccessLog.status_code)
        .filter(*base_filter, security_expr)
        .all()
    )
    watchlist_set = {item.lower() for item in WATCHLIST_PROBE_PATHS}
    event_rows = []
    for item in logs_recent:
        normalized = (item.path or "").lower()
        is_watchlist = normalized in watchlist_set or normalized.startswith("/wordpress/wp-admin/")
        event_rows.append(
            {
                "created_at": item.created_at,
                "path": item.path,
                "ip": item.ip_address or "unknown",
                "status_code": item.status_code,
                "user_agent": item.user_agent or "-",
                "event_type": "watchlist" if is_watchlist else ("throttled" if item.status_code == 429 else "probe"),
            }
        )

    daily_map: dict = defaultdict(lambda: {"probe": 0, "watchlist": 0, "throttled": 0})
    for created_at, path, status_code in logs_for_trend:
        local_day = _to_local_time(created_at).date()
        normalized = (path or "").lower()
        if normalized in watchlist_set or normalized.startswith("/wordpress/wp-admin/"):
            daily_map[local_day]["watchlist"] += 1
        elif status_code == 429:
            daily_map[local_day]["throttled"] += 1
        else:
            daily_map[local_day]["probe"] += 1

    daily_stats = []
    current = start_recent_date
    while current <= today_local:
        row = daily_map[current]
        daily_stats.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "probe": row["probe"],
                "watchlist": row["watchlist"],
                "throttled": row["throttled"],
            }
        )
        current += timedelta(days=1)

    return render_template(
        "manage_security.html",
        days=days,
        scope=scope,
        period_label=period_label,
        can_view_analytics=can_view_analytics(g.current_user),
        recent={
            "probe": recent_probe,
            "watchlist": recent_watchlist,
            "throttled": recent_throttled,
            "probe_ip": recent_probe_ip,
            "errors_4xx": recent_errors_4xx,
            "errors_5xx": recent_errors_5xx,
        },
        top_paths=top_paths,
        top_ips=top_ips,
        top_uas=top_uas,
        daily_stats=daily_stats,
        events=event_rows,
        events_pagination=events_pagination,
        event_filters={
            "event_type": event_type,
            "event_status": event_status,
            "event_q": event_q,
        },
    )


@bp.get("/site-feedback")
@login_required
def site_feedback_page():
    keyword = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "all").strip()
    category_filter = (request.args.get("category") or "all").strip()
    page = max(1, request.args.get("page", default=1, type=int))
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if status_filter not in {"all", SITE_FEEDBACK_PENDING, SITE_FEEDBACK_DONE}:
        status_filter = "all"
    if category_filter not in {"all", "bug", "suggestion", "data", "other"}:
        category_filter = "all"

    query = SiteFeedback.query
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                SiteFeedback.content.ilike(pattern),
                SiteFeedback.contact.ilike(pattern),
                SiteFeedback.source_page.ilike(pattern),
            )
        )
    if status_filter != "all":
        query = query.filter(SiteFeedback.status == status_filter)
    if category_filter != "all":
        query = query.filter(SiteFeedback.category == category_filter)

    if start_date:
        try:
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=SH_TZ)
            query = query.filter(SiteFeedback.created_at >= start_local.astimezone(timezone.utc))
        except ValueError:
            start_date = ""
    if end_date:
        try:
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=SH_TZ) + timedelta(days=1)
            query = query.filter(SiteFeedback.created_at < end_local.astimezone(timezone.utc))
        except ValueError:
            end_date = ""

    pagination = query.order_by(SiteFeedback.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template(
        "manage_site_feedback.html",
        feedback_list=pagination.items,
        pagination=pagination,
        filters={
            "q": keyword,
            "status": status_filter,
            "category": category_filter,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@bp.post("/site-feedback/<int:feedback_id>/status")
@login_required
def site_feedback_update_status(feedback_id: int):
    target_status = (request.form.get("status") or "").strip()
    if target_status not in {SITE_FEEDBACK_PENDING, SITE_FEEDBACK_DONE}:
        flash("状态无效", "error")
        return redirect(url_for("admin.site_feedback_page"))

    feedback = SiteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        flash("反馈不存在", "error")
        return redirect(url_for("admin.site_feedback_page"))

    old_status = feedback.status
    feedback.status = target_status
    feedback.updated_at = utcnow()
    db.session.commit()
    write_audit_log(
        g.current_user.id if g.current_user else None,
        "site_feedback.status_update",
        "site_feedback",
        str(feedback.id),
        f"{old_status}->{target_status}",
    )
    flash("反馈状态已更新", "success")

    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith(url_for("admin.site_feedback_page")):
        return redirect(next_url)
    return redirect(url_for("admin.site_feedback_page"))


@bp.get("/feedback")
@login_required
def feedback_page():
    keyword = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "all").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    if status_filter not in {"all", FEEDBACK_PENDING, FEEDBACK_APPROVED, FEEDBACK_REJECTED}:
        status_filter = "all"

    base_query = RouteFeedback.query.outerjoin(Route, Route.id == RouteFeedback.route_id)
    if keyword:
        pattern = f"%{keyword}%"
        base_query = base_query.filter(
            or_(
                Route.route_name.ilike(pattern),
                RouteFeedback.comment.ilike(pattern),
                RouteFeedback.road_condition_update.ilike(pattern),
            )
        )
    if start_date:
        try:
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=SH_TZ)
            base_query = base_query.filter(RouteFeedback.created_at >= start_local.astimezone(timezone.utc))
        except ValueError:
            start_date = ""
    if end_date:
        try:
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=SH_TZ) + timedelta(days=1)
            base_query = base_query.filter(RouteFeedback.created_at < end_local.astimezone(timezone.utc))
        except ValueError:
            end_date = ""

    pending_page = max(1, request.args.get("pending_page", default=1, type=int))
    reviewed_page = max(1, request.args.get("reviewed_page", default=1, type=int))

    pending_query = base_query.filter(RouteFeedback.status == FEEDBACK_PENDING)
    if status_filter in {FEEDBACK_APPROVED, FEEDBACK_REJECTED}:
        pending_query = pending_query.filter(db.text("1=0"))

    reviewed_query = base_query.filter(RouteFeedback.status.in_([FEEDBACK_APPROVED, FEEDBACK_REJECTED]))
    if status_filter in {FEEDBACK_APPROVED, FEEDBACK_REJECTED}:
        reviewed_query = reviewed_query.filter(RouteFeedback.status == status_filter)
    elif status_filter == FEEDBACK_PENDING:
        reviewed_query = reviewed_query.filter(db.text("1=0"))

    pending_pagination = pending_query.order_by(RouteFeedback.created_at.desc()).paginate(page=pending_page, per_page=12, error_out=False)
    reviewed_pagination = reviewed_query.order_by(RouteFeedback.reviewed_at.desc(), RouteFeedback.created_at.desc()).paginate(
        page=reviewed_page, per_page=12, error_out=False
    )
    return render_template(
        "manage_feedback.html",
        pending_feedback=pending_pagination.items,
        reviewed_feedback=reviewed_pagination.items,
        pending_pagination=pending_pagination,
        reviewed_pagination=reviewed_pagination,
        filters={"q": keyword, "status": status_filter, "start_date": start_date, "end_date": end_date},
    )


@bp.get("/routes")
@login_required
def routes_page():
    query, filters = query_routes_from_request(include_unpublished=True)
    pagination = query.paginate(page=filters["page"], per_page=filters["per_page"], error_out=False)
    recycle_routes = Route.query.filter_by(is_deleted=True).order_by(Route.deleted_at.desc()).all()
    return render_template(
        "manage_routes.html",
        routes=pagination.items,
        recycle_routes=recycle_routes,
        pagination=pagination,
        filters=filters,
        statuses=ROUTE_STATUSES,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/routes/new")
@login_required
def route_new_page():
    return render_template("manage_route_form.html", route=None, statuses=ROUTE_STATUSES, can_edit=True)


@bp.get("/routes/<int:route_id>/edit")
@login_required
def route_edit_page(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))
    versions = (
        RouteVersion.query.filter_by(route_id=route_id)
        .order_by(RouteVersion.version_no.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "manage_route_form.html",
        route=route,
        statuses=ROUTE_STATUSES,
        versions=versions,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/routes/<int:route_id>/view")
@login_required
def route_detail_manage(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        abort(404, description="Route not found")
    avg_rating, rating_count = approved_rating_summary(route.id)
    return render_template(
        "route_detail.html",
        route=route,
        rating_info={"avg_rating": avg_rating, "rating_count": rating_count},
        preview_endpoint=url_for("admin.route_preview_manage", route_id=route.id),
        back_url=url_for("admin.routes_page"),
        back_label="返回列表",
    )



@bp.get("/routes/<int:route_id>/preview")
@login_required
def route_preview_manage(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        return jsonify({"error": "route_not_found"}), 404

    file_path = Path(current_app.config["UPLOAD_FOLDER"]) / route.gpx_filename
    if not file_path.exists():
        return jsonify({"error": "gpx_missing"}), 404

    try:
        points, stats, elevation_profile = parse_gpx_points_and_stats(file_path)
        waypoints = parse_gpx_waypoints(file_path)
    except Exception:
        return jsonify({"error": "gpx_parse_failed"}), 400

    if not points:
        return jsonify(
            {
                "route_id": route.id,
                "points": [],
                "bounds": None,
                "stats": stats,
                "elevation_profile": elevation_profile,
                "waypoints": waypoints,
            }
        )

    lats = [item[0] for item in points]
    lons = [item[1] for item in points]
    bounds = {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
    }
    return jsonify(
        {
            "route_id": route.id,
            "points": points,
            "bounds": bounds,
            "stats": stats,
            "elevation_profile": elevation_profile,
            "waypoints": waypoints,
        }
    )

@bp.get("/activities")
@login_required
def activities_page():
    page = max(1, request.args.get("page", default=1, type=int))
    activities_pagination = Activity.query.order_by(Activity.activity_time.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template(
        "manage_activities.html",
        activities=activities_pagination.items,
        pagination=activities_pagination,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/activities/new")
@login_required
def activity_new_page():
    routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all()
    return render_template(
        "manage_activity_form.html",
        activity=None,
        routes=routes,
        media_assets=[],
        route_option_items=[],
        route_option_map={},
        legacy_selected_ids=[],
        can_edit=True,
    )


@bp.get("/activities/<int:activity_id>/edit")
@login_required
def activity_edit_page(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))
    routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all()
    media_assets = MediaAsset.query.filter_by(activity_id=activity.id).order_by(MediaAsset.created_at.desc()).all()
    route_option_items = (
        ActivityRouteOption.query.filter_by(activity_id=activity.id)
        .order_by(ActivityRouteOption.sort_order.asc(), ActivityRouteOption.id.asc())
        .all()
    )
    route_option_map = {
        item.level_key: {
            "route_id": item.route_id,
            "participant_count": int(item.participant_count or 0),
            "activity_time": item.activity_time,
        }
        for item in route_option_items
    }
    if not route_option_map:
        legacy_levels = [key for key, _label in ACTIVITY_ROUTE_LEVELS]
        for index, route in enumerate(activity.routes[: len(legacy_levels)]):
            route_option_map[legacy_levels[index]] = {
                "route_id": route.id,
                "participant_count": int(activity.participant_count or 0),
                "activity_time": activity.activity_time,
            }
    return render_template(
        "manage_activity_form.html",
        activity=activity,
        routes=routes,
        media_assets=media_assets,
        route_option_items=route_option_items,
        route_option_map=route_option_map,
        legacy_selected_ids=[route.id for route in activity.routes],
        can_edit=can_edit(g.current_user),
    )


@bp.get("/announcements")
@login_required
def announcements_page():
    page = max(1, request.args.get("page", default=1, type=int))
    pagination = Announcement.query.order_by(
        Announcement.is_pinned.desc(),
        Announcement.sort_order.desc(),
        db.func.coalesce(Announcement.published_at, Announcement.updated_at).desc(),
    ).paginate(page=page, per_page=20, error_out=False)
    return render_template(
        "manage_announcements.html",
        announcements=pagination.items,
        pagination=pagination,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/announcements/new")
@login_required
def announcement_new_page():
    routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all()
    activities = Activity.query.order_by(Activity.activity_time.desc()).all()
    return render_template(
        "manage_announcement_form.html",
        announcement=None,
        routes=routes,
        activities=activities,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/announcements/<int:announcement_id>/edit")
@login_required
def announcement_edit_page(announcement_id: int):
    announcement = Announcement.query.filter_by(id=announcement_id).first()
    if not announcement:
        flash("公告不存在", "error")
        return redirect(url_for("admin.announcements_page"))
    return render_template(
        "manage_announcement_form.html",
        announcement=announcement,
        routes=Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all(),
        activities=Activity.query.order_by(Activity.activity_time.desc()).all(),
        can_edit=can_edit(g.current_user),
    )


@bp.get("/users")
@login_required
def users_page():
    page = max(1, request.args.get("page", default=1, type=int))
    pagination = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template(
        "manage_users.html",
        users=pagination.items,
        pagination=pagination,
        role_labels=ROLE_LABELS,
    )


@bp.get("/users/new")
@login_required
def user_new_page():
    return render_template(
        "manage_user_form.html",
        user=None,
        roles=ROLES,
        role_labels=ROLE_LABELS,
        permission_defaults=_default_permissions_for_role(ROLE_CONTENT_ADMIN),
    )


@bp.get("/users/<int:user_id>/edit")
@login_required
def user_edit_page(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("管理员不存在", "error")
        return redirect(url_for("admin.users_page"))
    return render_template(
        "manage_user_form.html",
        user=user,
        roles=ROLES,
        role_labels=ROLE_LABELS,
        permission_defaults={
            "perm_view_analytics": bool(user.perm_view_analytics),
            "perm_view_security": bool(user.perm_view_security),
            "perm_review": bool(user.perm_review),
            "perm_edit_content": bool(user.perm_edit_content),
            "perm_manage_users": bool(user.perm_manage_users),
            "perm_view_audit_logs": bool(user.perm_view_audit_logs),
        },
    )


def _route_from_form(route: Route | None = None) -> dict:
    raw_difficulty = (request.form.get("difficulty") or (route.difficulty if route else "3")).strip()
    normalized_difficulty = _normalize_difficulty(raw_difficulty)
    return {
        "route_name": (request.form.get("route_name") or (route.route_name if route else "")).strip(),
        "distance_km": route.distance_km if route else 0.0,
        "difficulty": normalized_difficulty,
        "category": "cycling",
        "description": (request.form.get("description") or (route.description if route else "")).strip(),
        "status": (request.form.get("status") or (route.status if route else STATUS_PENDING_REVIEW)).strip(),
        "suggested_duration_hours": parse_distance(
            request.form.get("suggested_duration_hours") or (route.suggested_duration_hours if route else "0")
        ),
        "supply_points": (request.form.get("supply_points") or (route.supply_points if route else "")).strip(),
        "risk_warning": (request.form.get("risk_warning") or (route.risk_warning if route else "")).strip(),
    }


def _compute_route_stats(gpx_path: Path) -> dict:
    _points, stats, _elevation_profile = parse_gpx_points_and_stats(gpx_path)
    return {
        "distance_km": float(stats.get("distance_km") or 0.0),
        "ascent_m": stats.get("ascent_m"),
        "descent_m": stats.get("descent_m"),
        "min_ele_m": stats.get("min_ele_m"),
        "max_ele_m": stats.get("max_ele_m"),
    }


def _apply_route_stats(route: Route, gpx_path: Path) -> dict:
    stats = _compute_route_stats(gpx_path)
    route.distance_km = stats["distance_km"]
    route.ascent_m = stats["ascent_m"]
    route.descent_m = stats["descent_m"]
    route.min_ele_m = stats["min_ele_m"]
    route.max_ele_m = stats["max_ele_m"]
    return stats


def _normalize_difficulty(raw: str) -> str:
    if raw in {"1", "2", "3", "4", "5"}:
        return raw
    # Backward compatibility for legacy values.
    # We map `hard` to 4 to avoid over-stating routes as 5-star by default.
    if raw == "easy":
        return "2"
    if raw == "medium":
        return "3"
    if raw == "hard":
        return "4"
    return "3"


def _parse_activity_time(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        parsed = None

    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SH_TZ)

    return parsed.astimezone(timezone.utc)


def _announcement_from_form(announcement: Announcement | None = None) -> dict:
    title = (request.form.get("title") or (announcement.title if announcement else "")).strip()
    content = (request.form.get("content") or (announcement.content if announcement else "")).strip()
    status = (request.form.get("status") or (announcement.status if announcement else CONTENT_STATUS_DRAFT)).strip()
    if status not in {CONTENT_STATUS_DRAFT, CONTENT_STATUS_PUBLISHED, CONTENT_STATUS_OFFLINE}:
        status = CONTENT_STATUS_DRAFT
    sort_order_raw = (request.form.get("sort_order") or (announcement.sort_order if announcement else "0")).strip()
    try:
        sort_order = int(sort_order_raw)
    except (TypeError, ValueError):
        sort_order = 0
    is_pinned = (request.form.get("is_pinned") or "0").strip() == "1"
    published_at = _parse_activity_time(request.form.get("published_at"))
    offline_at = _parse_activity_time(request.form.get("offline_at"))
    if published_at and offline_at and offline_at <= published_at:
        offline_at = published_at + timedelta(minutes=1)
    activity_ids = [item for item in request.form.getlist("activity_ids") if str(item).strip()]
    route_ids = [item for item in request.form.getlist("route_ids") if str(item).strip()]
    return {
        "title": title,
        "content": content,
        "status": status,
        "sort_order": sort_order,
        "is_pinned": is_pinned,
        "published_at": published_at,
        "offline_at": offline_at,
        "activity_ids": activity_ids,
        "route_ids": route_ids,
    }


def _activity_route_options_from_form() -> list[dict]:
    items: list[dict] = []
    for sort_order, (level_key, level_label) in enumerate(ACTIVITY_ROUTE_LEVELS, start=1):
        raw = (request.form.get(f"route_option_{level_key}") or "").strip()
        if not raw:
            continue
        try:
            route_id = int(raw)
        except ValueError:
            continue
        participant_count = parse_distance(request.form.get(f"route_option_{level_key}_participants") or "0")
        option_time = _parse_activity_time(request.form.get(f"route_option_{level_key}_time"))
        items.append(
            {
                "level_key": level_key,
                "level_label": level_label,
                "sort_order": sort_order,
                "route_id": route_id,
                "participant_count": int(participant_count or 0),
                "activity_time": option_time,
            }
        )
    return items


def _sync_activity_route_options(activity: Activity, option_items: list[dict]) -> None:
    existing_options = ActivityRouteOption.query.filter_by(activity_id=activity.id).all()
    existing_by_level = {item.level_key: item for item in existing_options}
    next_levels = {item["level_key"] for item in option_items}

    for item in option_items:
        option = existing_by_level.get(item["level_key"])
        if option is None:
            db.session.add(
                ActivityRouteOption(
                    activity_id=activity.id,
                    route_id=item["route_id"],
                    level_key=item["level_key"],
                    level_label=item["level_label"],
                    activity_time=item.get("activity_time"),
                    participant_count=int(item.get("participant_count") or 0),
                    sort_order=item["sort_order"],
                )
            )
            continue
        option.route_id = item["route_id"]
        option.level_label = item["level_label"]
        option.activity_time = item.get("activity_time")
        option.participant_count = int(item.get("participant_count") or 0)
        option.sort_order = item["sort_order"]

    for option in existing_options:
        if option.level_key in next_levels:
            continue
        MediaAsset.query.filter_by(activity_route_option_id=option.id).update(
            {MediaAsset.activity_route_option_id: None},
            synchronize_session=False,
        )
        db.session.delete(option)


@bp.post("/routes/create")
@login_required
def create_route():
    payload = _route_from_form()
    gpx_file = request.files.get("gpx_file")

    if not payload["route_name"] or not gpx_file:
        flash("参数错误：请填写路线名并上传 GPX 文件", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["status"] not in ROUTE_STATUSES:
        flash("参数错误：状态无效", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["suggested_duration_hours"] is None:
        flash("参数错误：预计用时格式错误", "error")
        return redirect(url_for("admin.routes_page"))
    if not allowed_file(gpx_file.filename or "", {".gpx"}):
        flash("参数错误：仅支持 .gpx 文件", "error")
        return redirect(url_for("admin.routes_page"))
    if not file_size_ok(gpx_file, current_app.config.get("MAX_GPX_BYTES", 5 * 1024 * 1024)):
        flash("参数错误：GPX 文件过大", "error")
        return redirect(url_for("admin.routes_page"))

    filename, path = save_gpx_file(gpx_file)
    if not filename:
        flash("参数错误：仅支持 .gpx 文件", "error")
        return redirect(url_for("admin.routes_page"))

    try:
        computed_stats = _compute_route_stats(path)
    except Exception:
        if path and path.exists():
            path.unlink(missing_ok=True)
        flash("参数错误：GPX 解析失败，无法计算路线统计信息", "error")
        return redirect(url_for("admin.routes_page"))

    try:
        route = Route(
            route_name=payload["route_name"],
            gpx_filename=filename,
            uploaded_at=utcnow(),
            distance_km=computed_stats["distance_km"],
            difficulty=payload["difficulty"],
            category=payload["category"],
            description=payload["description"],
            status=payload["status"],
            is_active=(payload["status"] == STATUS_PUBLISHED),
            suggested_duration_hours=payload["suggested_duration_hours"],
            supply_points=payload["supply_points"],
            risk_warning=payload["risk_warning"],
            ascent_m=computed_stats["ascent_m"],
            descent_m=computed_stats["descent_m"],
            min_ele_m=computed_stats["min_ele_m"],
            max_ele_m=computed_stats["max_ele_m"],
            created_by=g.current_user.id,
            updated_by=g.current_user.id,
        )
        db.session.add(route)
        db.session.flush()
        create_route_version(route, g.current_user.id, change_note="create")
        db.session.commit()
        write_audit_log(g.current_user.id, "route.create", "route", str(route.id), route.route_name)
        flash("路线创建成功", "success")
    except Exception:
        if path and path.exists():
            path.unlink(missing_ok=True)
        db.session.rollback()
        flash("系统错误：保存路线失败", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/update")
@login_required
def update_route(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    payload = _route_from_form(route)
    if not payload["route_name"] or payload["status"] not in ROUTE_STATUSES:
        flash("参数错误：请检查必填项", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["suggested_duration_hours"] is None:
        flash("参数错误：预计用时格式错误", "error")
        return redirect(url_for("admin.routes_page"))

    before = route_snapshot(route)
    gpx_file = request.files.get("gpx_file")
    old_filename = route.gpx_filename
    saved_path = None
    stats_path = Path(current_app.config["UPLOAD_FOLDER"]) / route.gpx_filename
    if gpx_file and gpx_file.filename:
        if not allowed_file(gpx_file.filename, {".gpx"}):
            flash("参数错误：仅支持 .gpx 文件", "error")
            return redirect(url_for("admin.routes_page"))
        if not file_size_ok(gpx_file, current_app.config.get("MAX_GPX_BYTES", 5 * 1024 * 1024)):
            flash("参数错误：GPX 文件过大", "error")
            return redirect(url_for("admin.routes_page"))
        new_filename, saved_path = save_gpx_file(gpx_file)
        if not new_filename:
            flash("参数错误：仅支持 .gpx 文件", "error")
            return redirect(url_for("admin.routes_page"))
        route.gpx_filename = new_filename
        stats_path = saved_path

    try:
        _apply_route_stats(route, stats_path)
        route.route_name = payload["route_name"]
        route.difficulty = payload["difficulty"]
        route.category = payload["category"]
        route.description = payload["description"]
        route.status = payload["status"]
        route.is_active = payload["status"] == STATUS_PUBLISHED
        route.uploaded_at = utcnow()
        route.updated_by = g.current_user.id
        route.suggested_duration_hours = payload["suggested_duration_hours"]
        route.supply_points = payload["supply_points"]
        route.risk_warning = payload["risk_warning"]
        create_route_version(route, g.current_user.id, change_note="update")
        db.session.commit()

        if old_filename != route.gpx_filename:
            old_path = Path(current_app.config["UPLOAD_FOLDER"]) / old_filename
            old_path.unlink(missing_ok=True)

        write_field_audit_log(g.current_user.id, "route", str(route.id), before, route_snapshot(route))
        write_audit_log(g.current_user.id, "route.update", "route", str(route.id), route.route_name)
        flash("路线更新成功", "success")
    except Exception:
        db.session.rollback()
        if saved_path and saved_path.exists():
            saved_path.unlink(missing_ok=True)
        flash("系统错误：更新路线失败", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/recalculate-stats")
@login_required
def recalculate_route_stats(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    gpx_path = Path(current_app.config["UPLOAD_FOLDER"]) / route.gpx_filename
    if not gpx_path.exists() or not gpx_path.is_file():
        flash("GPX 文件不存在，无法更新统计", "error")
        return redirect(url_for("admin.route_edit_page", route_id=route_id))

    before = route_snapshot(route)
    try:
        stats = _apply_route_stats(route, gpx_path)
        route.updated_by = g.current_user.id
        route.updated_at = utcnow()
        create_route_version(route, g.current_user.id, change_note="recalculate_stats")
        db.session.commit()
        write_field_audit_log(g.current_user.id, "route", str(route.id), before, route_snapshot(route))
        write_audit_log(
            g.current_user.id,
            "route.recalculate_stats",
            "route",
            str(route.id),
            f"distance_km={stats['distance_km']}",
        )
        flash("已根据 GPX 自动更新里程与爬升统计", "success")
    except Exception:
        db.session.rollback()
        flash("统计更新失败：GPX 解析异常", "error")
    return redirect(url_for("admin.route_edit_page", route_id=route_id))


@bp.post("/routes/<int:route_id>/delete")
@login_required
def delete_route(route_id: int):
    route = Route.query.filter_by(id=route_id).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    try:
        route.is_deleted = True
        route.deleted_at = utcnow()
        route.deleted_by = g.current_user.id
        route.status = STATUS_OFFLINE
        route.is_active = False
        route.updated_by = g.current_user.id
        create_route_version(route, g.current_user.id, change_note="soft_delete")
        db.session.commit()
        write_audit_log(g.current_user.id, "route.soft_delete", "route", str(route_id), route.gpx_filename)
        flash("路线已移入回收站", "success")
    except Exception:
        db.session.rollback()
        flash("操作失败", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/restore")
@login_required
def restore_route(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=True).first()
    if not route:
        flash("回收站中未找到路线", "error")
        return redirect(url_for("admin.routes_page"))

    route.is_deleted = False
    route.deleted_at = None
    route.deleted_by = None
    route.status = STATUS_DRAFT
    route.is_active = False
    route.updated_by = g.current_user.id
    create_route_version(route, g.current_user.id, change_note="restore")
    db.session.commit()
    write_audit_log(g.current_user.id, "route.restore", "route", str(route.id), route.route_name)
    flash("路线已恢复（状态为草稿）", "success")
    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/status")
@login_required
def update_status(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    status = (request.form.get("status") or "").strip()
    if status not in ROUTE_STATUSES:
        flash("状态无效", "error")
        return redirect(url_for("admin.routes_page"))

    before = route_snapshot(route)
    route.status = status
    route.is_active = status == STATUS_PUBLISHED
    route.updated_by = g.current_user.id
    create_route_version(route, g.current_user.id, change_note=f"status:{status}")
    db.session.commit()
    write_field_audit_log(g.current_user.id, "route", str(route_id), before, route_snapshot(route))
    write_audit_log(g.current_user.id, "route.status", "route", str(route_id), status)
    flash("状态更新成功", "success")
    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/rollback")
@login_required
def rollback_route(route_id: int):
    route = Route.query.filter_by(id=route_id).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    version_no_raw = (request.form.get("version_no") or "").strip()
    try:
        version_no = int(version_no_raw)
    except ValueError:
        flash("版本号无效", "error")
        return redirect(url_for("admin.routes_page"))

    version = RouteVersion.query.filter_by(route_id=route_id, version_no=version_no).first()
    if not version:
        flash("目标版本不存在", "error")
        return redirect(url_for("admin.routes_page"))

    try:
        rollback_route_to_version(route, version, g.current_user.id)
        db.session.commit()
        write_audit_log(g.current_user.id, "route.rollback", "route", str(route.id), f"to_v{version_no}")
        flash(f"已回滚到版本 {version_no}", "success")
    except ValueError as exc:
        db.session.rollback()
        if str(exc).startswith("gpx_not_found:"):
            flash("回滚失败：对应 GPX 文件不存在", "error")
        else:
            flash("回滚失败：版本数据异常", "error")
    return redirect(url_for("admin.routes_page"))


@bp.post("/feedback/<int:feedback_id>/review")
@login_required
def review_feedback(feedback_id: int):
    feedback = RouteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        flash("反馈不存在", "error")
        return redirect(url_for("admin.dashboard"))

    status = (request.form.get("status") or "").strip()
    note = (request.form.get("reviewer_note") or "").strip()
    if status not in (FEEDBACK_APPROVED, FEEDBACK_REJECTED):
        flash("审核状态无效", "error")
        return redirect(url_for("admin.dashboard"))

    feedback.status = status
    feedback.reviewer_note = note
    feedback.reviewer_id = g.current_user.id
    feedback.reviewed_at = utcnow()
    db.session.commit()

    write_audit_log(g.current_user.id, "feedback.review", "route_feedback", str(feedback.id), status)
    flash("审核完成", "success")
    next_page = (request.form.get("next") or "").strip()
    if next_page == "feedback":
        return redirect(url_for("admin.feedback_page"))
    return redirect(url_for("admin.dashboard"))


@bp.post("/feedback/<int:feedback_id>/reopen")
@login_required
def reopen_feedback(feedback_id: int):
    feedback = RouteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        flash("反馈不存在", "error")
        return redirect(url_for("admin.feedback_page"))

    feedback.status = FEEDBACK_PENDING
    feedback.reviewer_note = ""
    feedback.reviewer_id = None
    feedback.reviewed_at = None
    db.session.commit()
    write_audit_log(g.current_user.id, "feedback.reopen", "route_feedback", str(feedback.id), "reopen_to_pending")
    flash("已重新打开反馈，状态改为待审核", "success")
    return redirect(url_for("admin.feedback_page"))


@bp.post("/feedback/<int:feedback_id>/delete")
@login_required
def delete_feedback(feedback_id: int):
    if g.current_user.role != ROLE_SUPER_ADMIN:
        abort(403)
    feedback = RouteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        flash("反馈不存在", "error")
        return redirect(url_for("admin.feedback_page"))

    route_id = feedback.route_id
    db.session.delete(feedback)
    db.session.commit()
    write_audit_log(g.current_user.id, "feedback.delete", "route_feedback", str(feedback_id), f"route={route_id}")
    flash("反馈已删除", "success")
    return redirect(url_for("admin.feedback_page"))


@bp.post("/activities/create")
@login_required
def create_activity():
    title = (request.form.get("title") or "").strip()
    option_items = _activity_route_options_from_form()
    selected_route_ids = [item["route_id"] for item in option_items]
    selected_route_ids = list(dict.fromkeys(selected_route_ids))

    if not title:
        flash("参数错误：活动标题不能为空", "error")
        return redirect(url_for("admin.activities_page"))

    activity = Activity(
        title=title,
        participant_count=0,
        weather="",
        summary="",
        created_by=g.current_user.id,
    )

    selected_routes = (
        Route.query.filter(Route.id.in_(selected_route_ids), Route.is_deleted.is_(False)).all()
        if selected_route_ids
        else []
    )
    activity.routes = selected_routes

    db.session.add(activity)
    db.session.commit()
    valid_route_ids = {route.id for route in selected_routes}
    option_items = [item for item in option_items if item["route_id"] in valid_route_ids]
    option_times = [item.get("activity_time") for item in option_items if item.get("activity_time")]
    activity.activity_time = min(option_times) if option_times else activity.activity_time
    activity.participant_count = int(sum(int(item.get("participant_count") or 0) for item in option_items))
    _sync_activity_route_options(activity, option_items)
    db.session.flush()
    option_map = {item.level_key: item for item in ActivityRouteOption.query.filter_by(activity_id=activity.id).all()}
    uploaded_count = 0
    for level_key, _label in ACTIVITY_ROUTE_LEVELS:
        option = option_map.get(level_key)
        if not option:
            continue
        uploaded_count += _save_activity_media(
            activity.id,
            request.files.getlist(f"media_files_{level_key}"),
            activity_route_option_id=option.id,
        )
    db.session.commit()
    write_audit_log(g.current_user.id, "activity.create", "activity", str(activity.id), activity.title)
    if uploaded_count > 0:
        flash(f"活动创建成功，已上传媒体文件 {uploaded_count} 个", "success")
    else:
        flash("活动创建成功", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/activities/<int:activity_id>/update")
@login_required
def update_activity(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    title = (request.form.get("title") or "").strip()
    if not title:
        flash("参数错误：活动标题不能为空", "error")
        return redirect(url_for("admin.activities_page"))

    option_items = _activity_route_options_from_form()
    selected_route_ids = [item["route_id"] for item in option_items]
    selected_route_ids = list(dict.fromkeys(selected_route_ids))

    activity.title = title
    activity.weather = ""
    activity.summary = ""

    selected_routes = (
        Route.query.filter(Route.id.in_(selected_route_ids), Route.is_deleted.is_(False)).all()
        if selected_route_ids
        else []
    )
    activity.routes = selected_routes

    valid_route_ids = {route.id for route in selected_routes}
    option_items = [item for item in option_items if item["route_id"] in valid_route_ids]
    option_times = [item.get("activity_time") for item in option_items if item.get("activity_time")]
    activity.activity_time = min(option_times) if option_times else activity.activity_time
    activity.participant_count = int(sum(int(item.get("participant_count") or 0) for item in option_items))
    _sync_activity_route_options(activity, option_items)
    db.session.flush()
    option_map = {item.level_key: item for item in ActivityRouteOption.query.filter_by(activity_id=activity.id).all()}
    uploaded_count = 0
    for level_key, _label in ACTIVITY_ROUTE_LEVELS:
        option = option_map.get(level_key)
        if not option:
            continue
        uploaded_count += _save_activity_media(
            activity.id,
            request.files.getlist(f"media_files_{level_key}"),
            activity_route_option_id=option.id,
        )
    db.session.commit()
    write_audit_log(g.current_user.id, "activity.update", "activity", str(activity.id), activity.title)
    if uploaded_count > 0:
        flash(f"活动更新成功，新增媒体文件 {uploaded_count} 个", "success")
    else:
        flash("活动更新成功", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/activities/<int:activity_id>/delete")
@login_required
def delete_activity(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    title = activity.title
    media_assets = MediaAsset.query.filter_by(activity_id=activity.id).all()
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    media_paths = [media_dir / item.storage_path for item in media_assets if item.storage_path]
    for item in media_assets:
        db.session.delete(item)
    db.session.delete(activity)
    db.session.commit()
    _cleanup_paths(media_paths)
    write_audit_log(g.current_user.id, "activity.delete", "activity", str(activity_id), title)
    flash("活动删除成功", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/activities/<int:activity_id>/media/<int:asset_id>/delete")
@login_required
def delete_activity_media(activity_id: int, asset_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    asset = MediaAsset.query.filter_by(id=asset_id, activity_id=activity_id).first()
    if not asset:
        flash("媒体文件不存在", "error")
        return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))

    target_path = Path(current_app.config["MEDIA_UPLOAD_FOLDER"]) / (asset.storage_path or "")
    db.session.delete(asset)
    db.session.commit()
    _cleanup_paths([target_path])
    write_audit_log(
        g.current_user.id,
        "activity.media.delete",
        "media_asset",
        str(asset_id),
        f"activity={activity_id}",
    )
    flash("媒体文件已删除", "success")
    return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))


@bp.post("/activities/<int:activity_id>/media/<int:asset_id>/assign")
@login_required
def assign_activity_media(activity_id: int, asset_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    asset = MediaAsset.query.filter_by(id=asset_id, activity_id=activity_id).first()
    if not asset:
        flash("媒体文件不存在", "error")
        return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))

    option_raw = (request.form.get("activity_route_option_id") or "").strip()
    option_id = None
    if option_raw:
        try:
            option_id = int(option_raw)
        except ValueError:
            flash("路线分配参数无效", "error")
            return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))
        option = ActivityRouteOption.query.filter_by(id=option_id, activity_id=activity_id).first()
        if not option:
            flash("目标路线不存在或不属于当前活动", "error")
            return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))

    asset.activity_route_option_id = option_id
    db.session.commit()
    write_audit_log(
        g.current_user.id,
        "activity.media.assign",
        "media_asset",
        str(asset_id),
        f"activity={activity_id},route_option={option_id or 'none'}",
    )
    flash("媒体路线归属已更新", "success")
    return redirect(url_for("admin.activity_edit_page", activity_id=activity_id))


@bp.post("/announcements/create")
@login_required
def create_announcement():
    payload = _announcement_from_form()
    if not payload["title"]:
        flash("参数错误：公告标题不能为空", "error")
        return redirect(url_for("admin.announcements_page"))

    announcement = Announcement(
        title=payload["title"],
        content=payload["content"],
        status=payload["status"],
        is_pinned=payload["is_pinned"],
        sort_order=payload["sort_order"],
        created_by=g.current_user.id,
        updated_by=g.current_user.id,
    )
    selected_activities = (
        Activity.query.filter(Activity.id.in_(payload["activity_ids"])).all()
        if payload["activity_ids"]
        else []
    )
    selected_routes = (
        Route.query.filter(Route.id.in_(payload["route_ids"]), Route.is_deleted.is_(False)).all()
        if payload["route_ids"]
        else []
    )
    announcement.activities = selected_activities
    announcement.routes = selected_routes
    if payload["status"] == CONTENT_STATUS_PUBLISHED:
        announcement.published_at = payload["published_at"] or utcnow()
    else:
        announcement.published_at = payload["published_at"]
    announcement.offline_at = payload["offline_at"]

    db.session.add(announcement)
    db.session.commit()
    write_audit_log(g.current_user.id, "announcement.create", "announcement", str(announcement.id), announcement.title)
    flash("公告创建成功", "success")
    return redirect(url_for("admin.announcements_page"))


@bp.post("/announcements/<int:announcement_id>/update")
@login_required
def update_announcement(announcement_id: int):
    announcement = Announcement.query.filter_by(id=announcement_id).first()
    if not announcement:
        flash("公告不存在", "error")
        return redirect(url_for("admin.announcements_page"))

    payload = _announcement_from_form(announcement)
    if not payload["title"]:
        flash("参数错误：公告标题不能为空", "error")
        return redirect(url_for("admin.announcement_edit_page", announcement_id=announcement_id))

    announcement.title = payload["title"]
    announcement.content = payload["content"]
    announcement.status = payload["status"]
    announcement.is_pinned = payload["is_pinned"]
    announcement.sort_order = payload["sort_order"]
    announcement.updated_by = g.current_user.id
    announcement.activities = (
        Activity.query.filter(Activity.id.in_(payload["activity_ids"])).all()
        if payload["activity_ids"]
        else []
    )
    announcement.routes = (
        Route.query.filter(Route.id.in_(payload["route_ids"]), Route.is_deleted.is_(False)).all()
        if payload["route_ids"]
        else []
    )
    if payload["status"] == CONTENT_STATUS_PUBLISHED:
        announcement.published_at = payload["published_at"] or announcement.published_at or utcnow()
    else:
        announcement.published_at = payload["published_at"]
    announcement.offline_at = payload["offline_at"]

    db.session.commit()
    write_audit_log(g.current_user.id, "announcement.update", "announcement", str(announcement.id), announcement.title)
    flash("公告更新成功", "success")
    return redirect(url_for("admin.announcements_page"))


@bp.post("/announcements/<int:announcement_id>/delete")
@login_required
def delete_announcement(announcement_id: int):
    announcement = Announcement.query.filter_by(id=announcement_id).first()
    if not announcement:
        flash("公告不存在", "error")
        return redirect(url_for("admin.announcements_page"))

    title = announcement.title
    db.session.delete(announcement)
    db.session.commit()
    write_audit_log(g.current_user.id, "announcement.delete", "announcement", str(announcement_id), title)
    flash("公告删除成功", "success")
    return redirect(url_for("admin.announcements_page"))


@bp.post("/users/create")
@login_required
def create_user():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or ROLE_CONTENT_ADMIN).strip()

    if not username or not password or role not in ROLES:
        flash("参数错误：请检查用户名/密码/角色", "error")
        return redirect(url_for("admin.users_page"))
    if len(password) < 6:
        flash("参数错误：密码长度至少 6 位", "error")
        return redirect(url_for("admin.users_page"))

    if User.query.filter_by(username=username).first():
        flash("参数错误：用户名已存在", "error")
        return redirect(url_for("admin.users_page"))

    perms = _permissions_from_form(role)
    user = User(
        username=username,
        password=generate_password_hash(password),
        role=role,
        is_active=True,
        perm_view_analytics=perms["perm_view_analytics"],
        perm_view_security=perms["perm_view_security"],
        perm_review=perms["perm_review"],
        perm_edit_content=perms["perm_edit_content"],
        perm_manage_users=perms["perm_manage_users"],
        perm_view_audit_logs=perms["perm_view_audit_logs"],
    )
    db.session.add(user)
    db.session.commit()
    write_audit_log(g.current_user.id, "user.create", "user", str(user.id), username)
    flash("管理员创建成功", "success")
    return redirect(url_for("admin.users_page"))


@bp.post("/users/<int:user_id>/update")
@login_required
def update_user(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("管理员不存在", "error")
        return redirect(url_for("admin.users_page"))

    username = (request.form.get("username") or "").strip()
    role = (request.form.get("role") or ROLE_CONTENT_ADMIN).strip()
    is_active = (request.form.get("is_active") or "0").strip() == "1"
    password = (request.form.get("password") or "").strip()

    if not username or role not in ROLES:
        flash("参数错误：请检查用户名和角色", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if User.query.filter(User.id != user_id, User.username == username).first():
        flash("参数错误：用户名已存在", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if password and len(password) < 6:
        flash("参数错误：密码长度至少 6 位", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if user.id == g.current_user.id and not is_active:
        flash("不能停用当前登录账号", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))

    user.username = username
    user.role = role
    user.is_active = is_active
    perms = _permissions_from_form(role)
    user.perm_view_analytics = perms["perm_view_analytics"]
    user.perm_view_security = perms["perm_view_security"]
    user.perm_review = perms["perm_review"]
    user.perm_edit_content = perms["perm_edit_content"]
    user.perm_manage_users = perms["perm_manage_users"]
    user.perm_view_audit_logs = perms["perm_view_audit_logs"]
    if password:
        user.password = generate_password_hash(password)

    db.session.commit()
    write_audit_log(g.current_user.id, "user.update", "user", str(user.id), username)
    flash("管理员更新成功", "success")
    return redirect(url_for("admin.users_page"))


@bp.post("/users/<int:user_id>/delete")
@login_required
def delete_user(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("管理员不存在", "error")
        return redirect(url_for("admin.users_page"))
    if user.id == g.current_user.id:
        flash("不能删除当前登录账号", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))

    user.is_active = False
    db.session.commit()
    write_audit_log(g.current_user.id, "user.deactivate", "user", str(user.id), user.username)
    flash("管理员已停用", "success")
    return redirect(url_for("admin.users_page"))


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


@bp.post("/bulk-import")
@login_required
def bulk_import():
    csv_file = request.files.get("csv_file")
    if not csv_file or not (csv_file.filename or "").lower().endswith(".csv"):
        flash("参数错误：请上传 CSV 文件", "error")
        return redirect(url_for("admin.routes_page"))

    csv_text = csv_file.stream.read().decode("utf-8-sig")
    reader = csv.DictReader(StringIO(csv_text))
    required = {
        "route_name",
        "gpx_filename",
        "difficulty",
        "category",
        "description",
        "status",
        "suggested_duration_hours",
        "supply_points",
        "risk_warning",
    }
    if not required.issubset(set(reader.fieldnames or [])):
        flash("参数错误：CSV 缺少必要列", "error")
        return redirect(url_for("admin.routes_page"))
    rows = list(reader)

    extra_gpx_files = request.files.getlist("gpx_files")
    uploaded_name_map: dict[str, str] = {}
    uploaded_paths: dict[str, Path] = {}
    for gpx in extra_gpx_files:
        if not gpx or not gpx.filename:
            continue
        if not allowed_file(gpx.filename, {".gpx"}):
            continue
        if not file_size_ok(gpx, current_app.config.get("MAX_GPX_BYTES", 5 * 1024 * 1024)):
            continue

        original_name = Path(gpx.filename).name
        saved_name, saved_path = save_gpx_file(gpx)
        if not saved_name or not saved_path:
            continue
        uploaded_name_map[original_name] = saved_name
        uploaded_paths[saved_name] = saved_path

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    created = 0
    skipped = 0
    used_uploaded_names: set[str] = set()
    report_rows: list[dict] = []

    for index, row in enumerate(rows, start=1):
        route_name = (row.get("route_name") or "").strip()
        gpx_filename = (row.get("gpx_filename") or "").strip()
        gpx_filename = uploaded_name_map.get(gpx_filename, gpx_filename)
        difficulty = (row.get("difficulty") or "medium").strip()
        category = (row.get("category") or "hiking").strip()
        description = (row.get("description") or "").strip()
        status = (row.get("status") or STATUS_OFFLINE).strip()
        suggested_duration_hours = parse_distance(row.get("suggested_duration_hours") or "0")
        supply_points = (row.get("supply_points") or "").strip()
        risk_warning = (row.get("risk_warning") or "").strip()

        reason = ""
        if not route_name or not gpx_filename.lower().endswith(".gpx") or status not in ROUTE_STATUSES:
            reason = "invalid_fields"
        elif suggested_duration_hours is None:
            reason = "invalid_duration"
        elif Route.query.filter((Route.gpx_filename == gpx_filename) | (Route.route_name == route_name)).first():
            reason = "duplicated"
        elif not (upload_folder / gpx_filename).exists():
            reason = "gpx_not_found"

        if reason:
            skipped += 1
            report_rows.append(
                {
                    "row": index,
                    "route_name": route_name,
                    "gpx_filename": gpx_filename,
                    "status": "failed",
                    "reason": reason,
                }
            )
            continue

        gpx_path = upload_folder / gpx_filename
        try:
            computed_stats = _compute_route_stats(gpx_path)
        except Exception:
            skipped += 1
            report_rows.append(
                {
                    "row": index,
                    "route_name": route_name,
                    "gpx_filename": gpx_filename,
                    "status": "failed",
                    "reason": "gpx_parse_error",
                }
            )
            continue

        route = Route(
            route_name=route_name,
            gpx_filename=gpx_filename,
            distance_km=computed_stats["distance_km"],
            difficulty=difficulty,
            category=category,
            description=description,
            status=status,
            is_active=(status == STATUS_PUBLISHED),
            uploaded_at=utcnow(),
            suggested_duration_hours=suggested_duration_hours,
            supply_points=supply_points,
            risk_warning=risk_warning,
            ascent_m=computed_stats["ascent_m"],
            descent_m=computed_stats["descent_m"],
            min_ele_m=computed_stats["min_ele_m"],
            max_ele_m=computed_stats["max_ele_m"],
            created_by=g.current_user.id,
            updated_by=g.current_user.id,
        )
        db.session.add(route)
        db.session.flush()
        create_route_version(route, g.current_user.id, change_note="bulk_import")
        created += 1
        report_rows.append(
            {
                "row": index,
                "route_name": route_name,
                "gpx_filename": gpx_filename,
                "status": "success",
                "reason": "",
            }
        )
        if gpx_filename in uploaded_paths:
            used_uploaded_names.add(gpx_filename)

    try:
        db.session.commit()
        report = save_import_report(g.current_user.id, report_rows, created, skipped)
    except Exception:
        db.session.rollback()
        _cleanup_paths(list(uploaded_paths.values()))
        flash("批量导入失败：数据库写入异常", "error")
        return redirect(url_for("admin.routes_page"))

    orphan_paths = [path for name, path in uploaded_paths.items() if name not in used_uploaded_names]
    _cleanup_paths(orphan_paths)

    write_audit_log(g.current_user.id, "route.bulk_import", "route", None, f"created={created},skipped={skipped}")
    flash(
        f"批量导入完成：成功 {created}，跳过 {skipped}。报告：{url_for('admin.download_import_report', token=report.report_token)}",
        "success",
    )
    return redirect(url_for("admin.routes_page"))


@bp.get("/import-report/<string:token>")
@login_required
def download_import_report(token: str):
    report = ImportReport.query.filter_by(report_token=token).first()
    if not report:
        abort(404, description="报告不存在")

    report_dir = Path(current_app.instance_path) / "import_reports"
    report_path = report_dir / report.report_filename
    if not report_path.exists():
        abort(404, description="报告文件不存在")

    return send_from_directory(
        str(report_dir),
        report.report_filename,
        as_attachment=True,
        download_name=report.report_filename,
        mimetype="text/csv",
    )






