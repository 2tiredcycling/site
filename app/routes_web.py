from datetime import timedelta, timezone
import csv
from io import StringIO
from pathlib import Path
import re
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from app.auth import client_ip
from app.models import (
    CONTENT_STATUS_PUBLISHED,
    FEEDBACK_APPROVED,
    Activity,
    Announcement,
    Route,
    RouteFeedback,
    SITE_FEEDBACK_PENDING,
    STATUS_PUBLISHED,
    MediaAsset,
    SiteFeedback,
    SitePage,
    db,
    utcnow,
)
from app.querying import query_routes_from_request
from app.security_limits import consume_fixed_window

bp = Blueprint("web", __name__)
SH_TZ = timezone(timedelta(hours=8))
SITE_FEEDBACK_LIMIT_PER_MINUTE = 5
SITE_FEEDBACK_WINDOW_SECONDS = 60


def _to_local_time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SH_TZ)


@bp.app_context_processor
def _inject_time_helpers():
    return {"to_local_time": _to_local_time}


def _rating_summary_map(route_ids: list[int]) -> dict[int, dict]:
    if not route_ids:
        return {}
    rows = (
        db.session.query(
            RouteFeedback.route_id,
            db.func.avg(RouteFeedback.rating).label("avg_rating"),
            db.func.count(RouteFeedback.id).label("rating_count"),
        )
        .filter(RouteFeedback.route_id.in_(route_ids), RouteFeedback.status == FEEDBACK_APPROVED)
        .group_by(RouteFeedback.route_id)
        .all()
    )
    result = {route_id: {"avg_rating": 0.0, "rating_count": 0} for route_id in route_ids}
    for route_id, avg_rating, rating_count in rows:
        result[route_id] = {
            "avg_rating": round(float(avg_rating or 0), 2),
            "rating_count": int(rating_count or 0),
        }
    return result


def _published_site_page(slug: str) -> SitePage | None:
    return SitePage.query.filter_by(slug=slug, status=CONTENT_STATUS_PUBLISHED).first()


def _activity_pagination(page: int, per_page: int):
    return Activity.query.order_by(Activity.activity_time.desc()).paginate(page=page, per_page=per_page, error_out=False)


def _activity_detail_or_404(activity_id: int) -> Activity:
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        abort(404, description="Activity not found")
    return activity


def _format_lastmod(value) -> str:
    if value is None:
        return ""
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date().isoformat()


@bp.get("/")
def index() -> str:
    latest_activities = Activity.query.order_by(Activity.activity_time.desc()).limit(5).all()
    latest_routes = (
        Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False)
        .order_by(Route.updated_at.desc())
        .limit(5)
        .all()
    )
    route_total = Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False).count()
    announcements = (
        Announcement.query.filter_by(status=CONTENT_STATUS_PUBLISHED)
        .order_by(
            Announcement.is_pinned.desc(),
            db.func.coalesce(Announcement.published_at, Announcement.updated_at).desc(),
            Announcement.updated_at.desc(),
        )
        .limit(5)
        .all()
    )
    return render_template(
        "index.html",
        latest_activities=latest_activities,
        latest_routes=latest_routes,
        route_total=route_total,
        announcements=announcements,
        meta_description="2Tired 骑行社官网：活动信息、路线共享、社团介绍与反馈入口。",
    )


@bp.get("/about")
def about_page() -> str:
    page = _published_site_page("about")
    return render_template(
        "about.html",
        page=page,
        meta_description="2Tired 骑行社社团介绍：宗旨、发展历程与加入方式。",
    )


@bp.get("/team")
def team_page() -> str:
    page = _published_site_page("team")
    return render_template(
        "team.html",
        page=page,
        meta_description="2Tired 骑行社管理团队与职责分工。",
    )


@bp.get("/contact")
def contact_page() -> str:
    page = _published_site_page("contact")
    return render_template(
        "contact.html",
        page=page,
        meta_description="联系 2Tired 骑行社：活动咨询、合作与反馈渠道。",
    )


@bp.get("/feedback")
def site_feedback() -> str:
    source = (request.args.get("source") or "").strip()
    return render_template("site_feedback.html", source=source)


@bp.post("/feedback")
def site_feedback_submit():
    category = (request.form.get("category") or "bug").strip().lower()
    content = (request.form.get("content") or "").strip()
    contact = (request.form.get("contact") or "").strip()
    source = (request.form.get("source") or "").strip()
    source_ip = client_ip()

    allowed, retry_after = consume_fixed_window(
        "site_feedback_submit",
        source_ip,
        limit=SITE_FEEDBACK_LIMIT_PER_MINUTE,
        window_seconds=SITE_FEEDBACK_WINDOW_SECONDS,
    )
    if not allowed:
        return render_template(
            "site_feedback.html",
            source=source,
            error_message=f"提交过于频繁，请 {retry_after} 秒后再试。",
            form_data={"category": category, "content": content, "contact": contact},
        )

    allowed_categories = {"bug", "suggestion", "data", "other"}
    if category not in allowed_categories:
        category = "other"

    if len(content) < 5:
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="反馈内容至少 5 个字。",
            form_data={"category": category, "content": content, "contact": contact},
        )
    if len(content) > 2000:
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="反馈内容不能超过 2000 个字。",
            form_data={"category": category, "content": content, "contact": contact},
        )
    if len(contact) > 128:
        contact = contact[:128]
    if contact and not re.fullmatch(r"\d{9}", contact):
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="学号格式不正确，应为 9 位数字。",
            form_data={"category": category, "content": content, "contact": contact},
        )

    entry = SiteFeedback(
        category=category,
        content=content,
        contact=contact,
        source_page=source or request.referrer or "",
        user_agent=(request.user_agent.string or "")[:255],
        ip_address=source_ip[:64],
        status=SITE_FEEDBACK_PENDING,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.session.add(entry)
    db.session.commit()
    return redirect(url_for("web.index", feedback="ok"))


@bp.get("/routes/<int:route_id>")
def route_detail(route_id: int) -> str:
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        abort(404, description="Route not found")
    rating_map = _rating_summary_map([route.id])
    rating_info = rating_map.get(route.id, {"avg_rating": 0.0, "rating_count": 0})
    return render_template(
        "route_detail.html",
        route=route,
        rating_info=rating_info,
        meta_description=f"{route.route_name} 路线详情：里程、难度、补给点与下载。",
    )


@bp.get("/routes")
def routes_center() -> str:
    query, filters = query_routes_from_request(include_unpublished=False)
    pagination = query.paginate(page=filters["page"], per_page=filters["per_page"], error_out=False)
    rating_map = _rating_summary_map([item.id for item in pagination.items])
    return render_template(
        "routes.html",
        routes=pagination.items,
        pagination=pagination,
        filters=filters,
        rating_map=rating_map,
        meta_description="2Tired 路线共享中心：检索、查看并下载 GPX 路线。",
    )


@bp.get("/activities")
def activity_list() -> str:
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)
    pagination = _activity_pagination(page, per_page)
    return render_template(
        "activities.html",
        activities=pagination.items,
        pagination=pagination,
        detail_endpoint="web.activity_detail",
        list_endpoint="web.activity_list",
        meta_description="2Tired 骑行社历史活动档案与活动详情。",
        list_title="社团活动档案",
    )


@bp.get("/events")
def events_list() -> str:
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)
    pagination = _activity_pagination(page, per_page)
    return render_template(
        "activities.html",
        activities=pagination.items,
        pagination=pagination,
        detail_endpoint="web.events_detail",
        list_endpoint="web.events_list",
        meta_description="2Tired 骑行社活动中心：查看最新活动与历史活动记录。",
        list_title="社团活动",
    )


@bp.get("/activities/<int:activity_id>")
def activity_detail(activity_id: int) -> str:
    activity = _activity_detail_or_404(activity_id)
    media_assets = MediaAsset.query.filter_by(activity_id=activity.id).order_by(MediaAsset.created_at.desc()).all()
    source = (request.args.get("source") or "").strip()
    if source == "manage":
        back_url = url_for("admin.activities_page")
        back_label = "返回活动管理"
    else:
        back_url = url_for("web.activity_list")
        back_label = "返回活动列表"
    return render_template(
        "activity_detail.html",
        activity=activity,
        media_assets=media_assets,
        back_url=back_url,
        back_label=back_label,
        meta_description=f"{activity.title} 活动详情：时间、人数、路线关联与活动总结。",
    )


@bp.get("/events/<int:event_id>")
def events_detail(event_id: int) -> str:
    activity = _activity_detail_or_404(event_id)
    media_assets = MediaAsset.query.filter_by(activity_id=activity.id).order_by(MediaAsset.created_at.desc()).all()
    source = (request.args.get("source") or "").strip()
    if source == "manage":
        back_url = url_for("admin.activities_page")
        back_label = "返回活动管理"
    else:
        back_url = url_for("web.events_list")
        back_label = "返回活动中心"
    return render_template(
        "activity_detail.html",
        activity=activity,
        media_assets=media_assets,
        back_url=back_url,
        back_label=back_label,
        meta_description=f"{activity.title} 活动详情：时间、人数、路线关联与活动总结。",
    )


@bp.get("/download/<int:route_id>")
def download(route_id: int):
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        abort(404, description="Route not found")

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    file_path = upload_folder / route.gpx_filename
    if not file_path.exists():
        abort(404, description="GPX file missing")

    route.download_count = (route.download_count or 0) + 1
    route.last_downloaded_at = utcnow()
    db.session.commit()

    return send_from_directory(
        directory=str(upload_folder),
        path=route.gpx_filename,
        as_attachment=True,
        download_name=route.gpx_filename,
        mimetype="application/gpx+xml",
    )


@bp.get("/media/<int:asset_id>")
def media_asset_file(asset_id: int):
    asset = MediaAsset.query.filter_by(id=asset_id).first()
    if not asset:
        abort(404, description="Media not found")
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    file_path = media_dir / (asset.storage_path or "")
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="Media file missing")
    return send_from_directory(
        directory=str(media_dir),
        path=asset.storage_path,
        as_attachment=False,
        download_name=asset.original_filename or asset.storage_path,
        mimetype=asset.mime_type or "application/octet-stream",
    )


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


@bp.get("/robots.txt")
def robots_txt() -> Response:
    body = (
        "User-agent: *\n"
        "Disallow: /manage/\n"
        "Allow: /\n"
        f"Sitemap: {url_for('web.sitemap_xml', _external=True)}\n"
    )
    return Response(body, mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap_xml() -> Response:
    static_urls = [
        url_for("web.index", _external=True),
        url_for("web.routes_center", _external=True),
        url_for("web.about_page", _external=True),
        url_for("web.team_page", _external=True),
        url_for("web.contact_page", _external=True),
        url_for("web.events_list", _external=True),
        url_for("web.site_feedback", _external=True),
    ]

    routes = (
        Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False)
        .order_by(Route.updated_at.desc())
        .all()
    )
    activities = Activity.query.order_by(Activity.updated_at.desc()).all()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for item in static_urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(item)}</loc>")
        lines.append("  </url>")

    for route in routes:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url_for('web.route_detail', route_id=route.id, _external=True))}</loc>")
        lastmod = _format_lastmod(route.updated_at or route.created_at)
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")

    for activity in activities:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url_for('web.events_detail', event_id=activity.id, _external=True))}</loc>")
        lastmod = _format_lastmod(activity.updated_at or activity.created_at)
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")

    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


@bp.get("/metrics")
def metrics() -> Response:
    total_routes = Route.query.filter_by(is_deleted=False).count()
    published_routes = Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False).count()
    total_downloads = (
        db.session.query(db.func.coalesce(db.func.sum(Route.download_count), 0))
        .filter(Route.is_deleted.is_(False))
        .scalar()
        or 0
    )
    body = (
        "# HELP app_routes_total Total routes\n"
        "# TYPE app_routes_total gauge\n"
        f"app_routes_total {total_routes}\n"
        "# HELP app_routes_published Published routes\n"
        "# TYPE app_routes_published gauge\n"
        f"app_routes_published {published_routes}\n"
        "# HELP app_route_downloads_total Route downloads\n"
        "# TYPE app_route_downloads_total counter\n"
        f"app_route_downloads_total {total_downloads}\n"
    )
    return Response(body, mimetype="text/plain")


@bp.get("/bulk-import-template.csv")
def bulk_import_template():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
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
    ])
    writer.writerow([
        "Shatin Loop",
        "shatin_loop.gpx",
        "12.5",
        "medium",
        "hiking",
        "Sample route",
        "published",
        "4",
        "camp store",
        "heat in summer",
    ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bulk_import_template.csv"},
    )


@bp.app_errorhandler(404)
def handle_404(error):
    message = getattr(error, "description", "Resource not found")
    return render_template("404.html", error_message=message), 404


@bp.app_errorhandler(403)
def handle_403(_error):
    return redirect(url_for("admin.login"))
