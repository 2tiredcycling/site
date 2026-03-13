import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

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

from app.auth import (
    attach_current_user,
    can_edit,
    can_review,
    get_csrf_token,
    login_required,
    role_required,
    validate_csrf_token,
)
from app.models import (
    FEEDBACK_APPROVED,
    FEEDBACK_PENDING,
    FEEDBACK_REJECTED,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_REVIEWER,
    ROLES,
    ROUTE_STATUSES,
    SITE_FEEDBACK_DONE,
    SITE_FEEDBACK_PENDING,
    STATUS_DRAFT,
    STATUS_OFFLINE,
    STATUS_PENDING_REVIEW,
    STATUS_PUBLISHED,
    Activity,
    AuditLog,
    ImportReport,
    Route,
    RouteFeedback,
    RouteVersion,
    SiteFeedback,
    User,
    db,
    utcnow,
)
from app.querying import query_routes_from_request
from app.gpx_utils import parse_gpx_points_and_stats
from app.route_ops import allowed_file, file_size_ok, parse_distance, save_gpx_file
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


def _to_local_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SH_TZ)


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


@bp.app_context_processor
def _inject_csrf_token():
    return {"csrf_token": get_csrf_token, "to_local_time": _to_local_time}


@bp.get("/login")
def login():
    if g.current_user:
        return redirect(url_for("admin.dashboard"))
    return render_template("manage_login.html")


@bp.post("/login")
def login_submit():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    user = User.query.filter_by(username=username, is_active=True).first()
    if not user or not check_password_hash(user.password, password):
        flash("用户名或密码错误", "error")
        return redirect(url_for("admin.login"))

    session["user_id"] = user.id
    write_audit_log(user.id, "auth.login", "user", str(user.id), "login success")
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
    pending_feedback_count = RouteFeedback.query.filter_by(status=FEEDBACK_PENDING).count()
    pending_site_feedback_count = SiteFeedback.query.filter_by(status=SITE_FEEDBACK_PENDING).count()
    audit_logs_pagination = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(
        page=log_page, per_page=5, error_out=False
    )
    latest_routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).limit(3).all()
    latest_activities = Activity.query.order_by(Activity.activity_time.desc()).limit(3).all()
    latest_feedback = RouteFeedback.query.order_by(RouteFeedback.created_at.desc()).limit(3).all()
    latest_site_feedback = SiteFeedback.query.order_by(SiteFeedback.created_at.desc()).limit(3).all()
    summary = {
        "route_total": Route.query.filter_by(is_deleted=False).count(),
        "route_deleted": Route.query.filter_by(is_deleted=True).count(),
        "activity_total": Activity.query.count(),
        "feedback_pending": pending_feedback_count,
        "site_feedback_pending": pending_site_feedback_count,
    }
    return render_template(
        "manage.html",
        summary=summary,
        audit_logs=audit_logs_pagination.items,
        audit_logs_pagination=audit_logs_pagination,
        latest_routes=latest_routes,
        latest_activities=latest_activities,
        latest_feedback=latest_feedback,
        latest_site_feedback=latest_site_feedback,
        can_review=can_review(g.current_user),
        can_manage_users=(g.current_user.role == ROLE_ADMIN),
    )


@bp.get("/audit-logs")
@login_required
def audit_logs_page():
    page = max(1, request.args.get("page", default=1, type=int))
    pagination = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("manage_audit_logs.html", logs=pagination.items, pagination=pagination)


@bp.get("/site-feedback")
@role_required(ROLE_ADMIN, ROLE_REVIEWER)
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
@role_required(ROLE_ADMIN, ROLE_REVIEWER)
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
    flash("网站反馈状态已更新", "success")

    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith(url_for("admin.site_feedback_page")):
        return redirect(next_url)
    return redirect(url_for("admin.site_feedback_page"))


@bp.get("/feedback")
@role_required(ROLE_ADMIN, ROLE_REVIEWER)
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
@role_required(ROLE_ADMIN, ROLE_EDITOR)
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
        back_label="返回路线管理",
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
    except Exception:
        return jsonify({"error": "gpx_parse_failed"}), 400

    if not points:
        return jsonify(
            {"route_id": route.id, "points": [], "bounds": None, "stats": stats, "elevation_profile": elevation_profile}
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
        {"route_id": route.id, "points": points, "bounds": bounds, "stats": stats, "elevation_profile": elevation_profile}
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
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def activity_new_page():
    routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all()
    return render_template("manage_activity_form.html", activity=None, routes=routes, can_edit=True)


@bp.get("/activities/<int:activity_id>/edit")
@login_required
def activity_edit_page(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))
    routes = Route.query.filter_by(is_deleted=False).order_by(Route.updated_at.desc()).all()
    return render_template(
        "manage_activity_form.html",
        activity=activity,
        routes=routes,
        can_edit=can_edit(g.current_user),
    )


@bp.get("/users")
@role_required(ROLE_ADMIN)
def users_page():
    page = max(1, request.args.get("page", default=1, type=int))
    pagination = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("manage_users.html", users=pagination.items, pagination=pagination)


@bp.get("/users/new")
@role_required(ROLE_ADMIN)
def user_new_page():
    return render_template("manage_user_form.html", user=None, roles=ROLES)


@bp.get("/users/<int:user_id>/edit")
@role_required(ROLE_ADMIN)
def user_edit_page(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("用户不存在", "error")
        return redirect(url_for("admin.users_page"))
    return render_template("manage_user_form.html", user=user, roles=ROLES)


def _route_from_form(route: Route | None = None) -> dict:
    raw_difficulty = (request.form.get("difficulty") or (route.difficulty if route else "3")).strip()
    normalized_difficulty = _normalize_difficulty(raw_difficulty)
    return {
        "route_name": (request.form.get("route_name") or (route.route_name if route else "")).strip(),
        "distance_km": parse_distance(request.form.get("distance_km") or (route.distance_km if route else "")),
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


@bp.post("/routes/create")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def create_route():
    payload = _route_from_form()
    gpx_file = request.files.get("gpx_file")

    if not payload["route_name"] or payload["distance_km"] is None or not gpx_file:
        flash("新增失败：请补齐名称、里程和 GPX 文件", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["status"] not in ROUTE_STATUSES:
        flash("新增失败：状态非法", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["suggested_duration_hours"] is None:
        flash("新增失败：建议用时不合法", "error")
        return redirect(url_for("admin.routes_page"))
    if not allowed_file(gpx_file.filename or "", {".gpx"}):
        flash("新增失败：仅支持 .gpx", "error")
        return redirect(url_for("admin.routes_page"))
    if not file_size_ok(gpx_file, current_app.config.get("MAX_GPX_BYTES", 5 * 1024 * 1024)):
        flash("新增失败：GPX 文件过大", "error")
        return redirect(url_for("admin.routes_page"))

    filename, path = save_gpx_file(gpx_file)
    if not filename:
        flash("新增失败：仅支持 .gpx", "error")
        return redirect(url_for("admin.routes_page"))

    try:
        route = Route(
            route_name=payload["route_name"],
            gpx_filename=filename,
            uploaded_at=utcnow(),
            distance_km=payload["distance_km"],
            difficulty=payload["difficulty"],
            category=payload["category"],
            description=payload["description"],
            status=payload["status"],
            is_active=(payload["status"] == STATUS_PUBLISHED),
            suggested_duration_hours=payload["suggested_duration_hours"],
            supply_points=payload["supply_points"],
            risk_warning=payload["risk_warning"],
            created_by=g.current_user.id,
            updated_by=g.current_user.id,
        )
        db.session.add(route)
        db.session.flush()
        create_route_version(route, g.current_user.id, change_note="create")
        db.session.commit()
        write_audit_log(g.current_user.id, "route.create", "route", str(route.id), route.route_name)
        flash("新增成功", "success")
    except Exception:
        if path and path.exists():
            path.unlink(missing_ok=True)
        db.session.rollback()
        flash("新增失败：数据库写入异常", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/update")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def update_route(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    payload = _route_from_form(route)
    if not payload["route_name"] or payload["distance_km"] is None or payload["status"] not in ROUTE_STATUSES:
        flash("更新失败：字段不合法", "error")
        return redirect(url_for("admin.routes_page"))
    if payload["suggested_duration_hours"] is None:
        flash("更新失败：建议用时不合法", "error")
        return redirect(url_for("admin.routes_page"))

    before = route_snapshot(route)
    gpx_file = request.files.get("gpx_file")
    old_filename = route.gpx_filename
    saved_path = None
    if gpx_file and gpx_file.filename:
        if not allowed_file(gpx_file.filename, {".gpx"}):
            flash("更新失败：仅支持 .gpx", "error")
            return redirect(url_for("admin.routes_page"))
        if not file_size_ok(gpx_file, current_app.config.get("MAX_GPX_BYTES", 5 * 1024 * 1024)):
            flash("更新失败：GPX 文件过大", "error")
            return redirect(url_for("admin.routes_page"))
        new_filename, saved_path = save_gpx_file(gpx_file)
        if not new_filename:
            flash("更新失败：仅支持 .gpx", "error")
            return redirect(url_for("admin.routes_page"))
        route.gpx_filename = new_filename

    try:
        route.route_name = payload["route_name"]
        route.distance_km = payload["distance_km"]
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
        flash("更新成功", "success")
    except Exception:
        db.session.rollback()
        if saved_path and saved_path.exists():
            saved_path.unlink(missing_ok=True)
        flash("更新失败：数据库写入异常", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/delete")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
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
        flash("已移入回收站", "success")
    except Exception:
        db.session.rollback()
        flash("删除失败", "error")

    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/restore")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
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
    flash("已从回收站恢复（状态为草稿）", "success")
    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/status")
@role_required(ROLE_ADMIN, ROLE_EDITOR, ROLE_REVIEWER)
def update_status(route_id: int):
    route = Route.query.filter_by(id=route_id, is_deleted=False).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    status = (request.form.get("status") or "").strip()
    if status not in ROUTE_STATUSES:
        flash("状态非法", "error")
        return redirect(url_for("admin.routes_page"))

    before = route_snapshot(route)
    route.status = status
    route.is_active = status == STATUS_PUBLISHED
    route.updated_by = g.current_user.id
    create_route_version(route, g.current_user.id, change_note=f"status:{status}")
    db.session.commit()
    write_field_audit_log(g.current_user.id, "route", str(route_id), before, route_snapshot(route))
    write_audit_log(g.current_user.id, "route.status", "route", str(route_id), status)
    flash("状态已更新", "success")
    return redirect(url_for("admin.routes_page"))


@bp.post("/routes/<int:route_id>/rollback")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def rollback_route(route_id: int):
    route = Route.query.filter_by(id=route_id).first()
    if not route:
        flash("路线不存在", "error")
        return redirect(url_for("admin.routes_page"))

    version_no_raw = (request.form.get("version_no") or "").strip()
    try:
        version_no = int(version_no_raw)
    except ValueError:
        flash("版本号非法", "error")
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
            flash("回滚失败：目标 GPX 文件不存在", "error")
        else:
            flash("回滚失败：版本数据非法", "error")
    return redirect(url_for("admin.routes_page"))


@bp.post("/feedback/<int:feedback_id>/review")
@role_required(ROLE_ADMIN, ROLE_REVIEWER)
def review_feedback(feedback_id: int):
    feedback = RouteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        flash("反馈不存在", "error")
        return redirect(url_for("admin.dashboard"))

    status = (request.form.get("status") or "").strip()
    note = (request.form.get("reviewer_note") or "").strip()
    if status not in (FEEDBACK_APPROVED, FEEDBACK_REJECTED):
        flash("审核状态非法", "error")
        return redirect(url_for("admin.dashboard"))

    feedback.status = status
    feedback.reviewer_note = note
    feedback.reviewer_id = g.current_user.id
    feedback.reviewed_at = utcnow()
    db.session.commit()

    write_audit_log(g.current_user.id, "feedback.review", "route_feedback", str(feedback.id), status)
    flash("反馈已审核", "success")
    next_page = (request.form.get("next") or "").strip()
    if next_page == "feedback":
        return redirect(url_for("admin.feedback_page"))
    return redirect(url_for("admin.dashboard"))


@bp.post("/feedback/<int:feedback_id>/reopen")
@role_required(ROLE_ADMIN, ROLE_REVIEWER)
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
    flash("已撤销审核，反馈回到待审核", "success")
    return redirect(url_for("admin.feedback_page"))


@bp.post("/feedback/<int:feedback_id>/delete")
@role_required(ROLE_ADMIN)
def delete_feedback(feedback_id: int):
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
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def create_activity():
    title = (request.form.get("title") or "").strip()
    participant_count = parse_distance(request.form.get("participant_count") or "0")
    weather = (request.form.get("weather") or "").strip()
    summary = (request.form.get("summary") or "").strip()
    route_ids = request.form.getlist("route_ids")

    if not title:
        flash("活动创建失败：标题不能为空", "error")
        return redirect(url_for("admin.activities_page"))

    parsed_activity_time = _parse_activity_time(request.form.get("activity_time"))

    activity = Activity(
        title=title,
        participant_count=int(participant_count or 0),
        weather=weather,
        summary=summary,
        created_by=g.current_user.id,
    )
    if parsed_activity_time:
        activity.activity_time = parsed_activity_time

    selected_routes = Route.query.filter(Route.id.in_(route_ids), Route.is_deleted.is_(False)).all() if route_ids else []
    activity.routes = selected_routes

    db.session.add(activity)
    db.session.commit()
    write_audit_log(g.current_user.id, "activity.create", "activity", str(activity.id), activity.title)
    flash("活动创建成功", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/activities/<int:activity_id>/update")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def update_activity(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    title = (request.form.get("title") or "").strip()
    if not title:
        flash("活动更新失败：标题不能为空", "error")
        return redirect(url_for("admin.activities_page"))

    participant_count = parse_distance(request.form.get("participant_count") or "0")
    weather = (request.form.get("weather") or "").strip()
    summary = (request.form.get("summary") or "").strip()
    route_ids = request.form.getlist("route_ids")
    parsed_activity_time = _parse_activity_time(request.form.get("activity_time"))

    activity.title = title
    activity.participant_count = int(participant_count or 0)
    activity.weather = weather
    activity.summary = summary
    if parsed_activity_time:
        activity.activity_time = parsed_activity_time

    selected_routes = Route.query.filter(Route.id.in_(route_ids), Route.is_deleted.is_(False)).all() if route_ids else []
    activity.routes = selected_routes

    db.session.commit()
    write_audit_log(g.current_user.id, "activity.update", "activity", str(activity.id), activity.title)
    flash("活动已更新", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/activities/<int:activity_id>/delete")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def delete_activity(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        flash("活动不存在", "error")
        return redirect(url_for("admin.activities_page"))

    title = activity.title
    db.session.delete(activity)
    db.session.commit()
    write_audit_log(g.current_user.id, "activity.delete", "activity", str(activity_id), title)
    flash("活动已删除", "success")
    return redirect(url_for("admin.activities_page"))


@bp.post("/users/create")
@role_required(ROLE_ADMIN)
def create_user():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or ROLE_EDITOR).strip()

    if not username or not password or role not in ROLES:
        flash("用户创建失败：参数不合法", "error")
        return redirect(url_for("admin.users_page"))
    if len(password) < 12:
        flash("用户创建失败：密码长度至少 12 位", "error")
        return redirect(url_for("admin.users_page"))

    if User.query.filter_by(username=username).first():
        flash("用户创建失败：用户名重复", "error")
        return redirect(url_for("admin.users_page"))

    user = User(username=username, password=generate_password_hash(password), role=role, is_active=True)
    db.session.add(user)
    db.session.commit()
    write_audit_log(g.current_user.id, "user.create", "user", str(user.id), username)
    flash("用户创建成功", "success")
    return redirect(url_for("admin.users_page"))


@bp.post("/users/<int:user_id>/update")
@role_required(ROLE_ADMIN)
def update_user(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("用户不存在", "error")
        return redirect(url_for("admin.users_page"))

    username = (request.form.get("username") or "").strip()
    role = (request.form.get("role") or ROLE_EDITOR).strip()
    is_active = (request.form.get("is_active") or "0").strip() == "1"
    password = (request.form.get("password") or "").strip()

    if not username or role not in ROLES:
        flash("用户更新失败：参数不合法", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if User.query.filter(User.id != user_id, User.username == username).first():
        flash("用户更新失败：用户名重复", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if password and len(password) < 12:
        flash("用户更新失败：密码长度至少 12 位", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))
    if user.id == g.current_user.id and not is_active:
        flash("不能停用当前登录账号", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))

    user.username = username
    user.role = role
    user.is_active = is_active
    if password:
        user.password = generate_password_hash(password)

    db.session.commit()
    write_audit_log(g.current_user.id, "user.update", "user", str(user.id), username)
    flash("用户已更新", "success")
    return redirect(url_for("admin.users_page"))


@bp.post("/users/<int:user_id>/delete")
@role_required(ROLE_ADMIN)
def delete_user(user_id: int):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        flash("用户不存在", "error")
        return redirect(url_for("admin.users_page"))
    if user.id == g.current_user.id:
        flash("不能删除当前登录账号", "error")
        return redirect(url_for("admin.user_edit_page", user_id=user_id))

    user.is_active = False
    db.session.commit()
    write_audit_log(g.current_user.id, "user.deactivate", "user", str(user.id), user.username)
    flash("账号已停用", "success")
    return redirect(url_for("admin.users_page"))


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


@bp.post("/bulk-import")
@role_required(ROLE_ADMIN, ROLE_EDITOR)
def bulk_import():
    csv_file = request.files.get("csv_file")
    if not csv_file or not (csv_file.filename or "").lower().endswith(".csv"):
        flash("导入失败：请上传 CSV", "error")
        return redirect(url_for("admin.routes_page"))

    csv_text = csv_file.stream.read().decode("utf-8-sig")
    reader = csv.DictReader(StringIO(csv_text))
    required = {
        "route_name",
        "gpx_filename",
        "distance_km",
        "difficulty",
        "category",
        "description",
        "status",
        "suggested_duration_hours",
        "supply_points",
        "risk_warning",
    }
    if not required.issubset(set(reader.fieldnames or [])):
        flash("导入失败：CSV 字段不完整", "error")
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
        distance = parse_distance(row.get("distance_km") or "")
        suggested_duration_hours = parse_distance(row.get("suggested_duration_hours") or "0")
        supply_points = (row.get("supply_points") or "").strip()
        risk_warning = (row.get("risk_warning") or "").strip()

        reason = ""
        if not route_name or not gpx_filename.lower().endswith(".gpx") or distance is None or status not in ROUTE_STATUSES:
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

        route = Route(
            route_name=route_name,
            gpx_filename=gpx_filename,
            distance_km=distance,
            difficulty=difficulty,
            category=category,
            description=description,
            status=status,
            is_active=(status == STATUS_PUBLISHED),
            uploaded_at=utcnow(),
            suggested_duration_hours=suggested_duration_hours,
            supply_points=supply_points,
            risk_warning=risk_warning,
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
        f"批量导入完成：新增 {created}，跳过 {skipped}。报告：{url_for('admin.download_import_report', token=report.report_token)}",
        "success",
    )
    return redirect(url_for("admin.routes_page"))


@bp.get("/import-report/<string:token>")
@role_required(ROLE_ADMIN, ROLE_EDITOR, ROLE_REVIEWER)
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





