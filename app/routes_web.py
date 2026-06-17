from datetime import timedelta, timezone
import csv
import re
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, send_from_directory, url_for as flask_url_for

from app.auth import client_ip
from app.models import (
    CONTENT_STATUS_PUBLISHED,
    FEEDBACK_APPROVED,
    Activity,
    ActivityRouteOption,
    Announcement,
    EventRegistration,
    Route,
    RouteFeedback,
    REGISTRATION_CONFIRMED,
    REGISTRATION_PENDING,
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
from app.gpx_utils import parse_gpx_points_and_stats

bp = Blueprint("web", __name__)
SH_TZ = timezone(timedelta(hours=8))
SITE_FEEDBACK_LIMIT_PER_MINUTE = 5
SITE_FEEDBACK_WINDOW_SECONDS = 60


def _url_for(endpoint: str, **values):
    target = endpoint
    if endpoint.startswith("web.") and (request.blueprint or "") == "web_beta":
        target = endpoint.replace("web.", "web_beta.", 1)
    return flask_url_for(target, **values)


def _is_beta_request() -> bool:
    return (request.blueprint or "") == "web_beta"


def _palette_presets() -> list[dict]:
    return [
        {
            "key": "1",
            "name": "森林绿",
            "summary": "沉稳自然，户外骑行氛围强。",
            "primary": "#12372A",
            "secondary": "#436850",
            "accent": "#ADBC9F",
            "bg": "#FBFADA",
            "swatches": [
                {"name": "a", "value": "#12372A"},
                {"name": "b", "value": "#436850"},
                {"name": "c", "value": "#ADBC9F"},
                {"name": "d", "value": "#FBFADA"},
            ],
        },
        {
            "key": "2",
            "name": "夜幕紫",
            "summary": "夜色紫调，偏视觉冲击。",
            "primary": "#1F2544",
            "secondary": "#474F7A",
            "accent": "#FFD0EC",
            "bg": "#81689D",
            "swatches": [
                {"name": "a", "value": "#1F2544"},
                {"name": "b", "value": "#474F7A"},
                {"name": "c", "value": "#81689D"},
                {"name": "d", "value": "#FFD0EC"},
            ],
        },
        {
            "key": "3",
            "name": "霞影蓝",
            "summary": "柔和层次强，偏艺术化。",
            "primary": "#2E365A",
            "secondary": "#6B597F",
            "accent": "#BD6C73",
            "bg": "#92A1C2",
            "swatches": [
                {"name": "a", "value": "#2E365A"},
                {"name": "b", "value": "#6B597F"},
                {"name": "c", "value": "#A2869C"},
                {"name": "d", "value": "#BD6C73"},
                {"name": "e", "value": "#92A1C2"},
                {"name": "f", "value": "#3F5B8D"},
            ],
        },
        {
            "key": "4",
            "name": "冷雾灰蓝",
            "summary": "科技理性，克制稳重。",
            "primary": "#11212D",
            "secondary": "#4A5C6A",
            "accent": "#9BA8AB",
            "bg": "#CCD0CF",
            "swatches": [
                {"name": "a", "value": "#06141B"},
                {"name": "b", "value": "#11212D"},
                {"name": "c", "value": "#253745"},
                {"name": "d", "value": "#4A5C6A"},
                {"name": "e", "value": "#9BA8AB"},
                {"name": "f", "value": "#CCD0CF"},
            ],
        },
        {
            "key": "5",
            "name": "湖湾青",
            "summary": "清凉湖感，运动与路线感明显。",
            "primary": "#072E33",
            "secondary": "#0F969C",
            "accent": "#6DA5C0",
            "bg": "#294D61",
            "swatches": [
                {"name": "a", "value": "#051B1A"},
                {"name": "b", "value": "#072E33"},
                {"name": "c", "value": "#0C707B"},
                {"name": "d", "value": "#0F969C"},
                {"name": "e", "value": "#6DA5C0"},
                {"name": "f", "value": "#294D61"},
            ],
        },
        {
            "key": "6",
            "name": "晴空蓝",
            "summary": "亮度高、现代感强、清透。",
            "primary": "#052659",
            "secondary": "#7DA0CA",
            "accent": "#C1E8FF",
            "bg": "#5483B3",
            "swatches": [
                {"name": "a", "value": "#021024"},
                {"name": "b", "value": "#052659"},
                {"name": "c", "value": "#5483B3"},
                {"name": "d", "value": "#7DA0CA"},
                {"name": "e", "value": "#C1E8FF"},
            ],
        },
        {
            "key": "7",
            "name": "马卡龙粉",
            "summary": "柔和粉调，校园社团友好（pink）。",
            "primary": "#8A4F67",
            "secondary": "#C683A3",
            "accent": "#E5A6C2",
            "bg": "#F6E8EF",
            "swatches": [
                {"name": "a", "value": "#D79AB8"},
                {"name": "b", "value": "#F8ECF2"},
                {"name": "c", "value": "#F3C7DA"},
                {"name": "d", "value": "#E5A6C2"},
                {"name": "e", "value": "#E6BFD0"},
                {"name": "f", "value": "#8A4F67"},
            ],
        },
        {
            "key": "8",
            "name": "暖夜紫灰",
            "summary": "氛围感强，适合夜骑主题。",
            "primary": "#2B124C",
            "secondary": "#854F6C",
            "accent": "#DFB6B2",
            "bg": "#FBE4D8",
            "swatches": [
                {"name": "a", "value": "#190019"},
                {"name": "b", "value": "#2B124C"},
                {"name": "c", "value": "#522B5B"},
                {"name": "d", "value": "#854F6C"},
                {"name": "e", "value": "#DFB6B2"},
                {"name": "f", "value": "#FBE4D8"},
            ],
        },
    ]


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


def _announcement_visibility_filters(now_value):
    return (
        Announcement.status == CONTENT_STATUS_PUBLISHED,
        db.or_(Announcement.published_at.is_(None), Announcement.published_at <= now_value),
        db.or_(Announcement.offline_at.is_(None), Announcement.offline_at > now_value),
    )


def _activity_pagination(page: int, per_page: int):
    return Activity.query.order_by(Activity.activity_time.desc()).paginate(page=page, per_page=per_page, error_out=False)


def _event_display_date(activity: Activity):
    option_times = [
        item.activity_time
        for item in (activity.route_options or [])
        if getattr(item, "activity_time", None) is not None
    ]
    if option_times:
        return min(option_times)
    return activity.activity_time


def _event_display_date_map(activities: list[Activity]) -> dict[int, object]:
    return {item.id: _event_display_date(item) for item in activities}


def _event_signup_back_target(activity: Activity, source: str) -> tuple[str, str]:
    if source == "home":
        return _url_for("web.index"), "返回首页"
    if source == "events_detail":
        return _url_for("web.events_detail", event_id=activity.id), "返回活动详情"
    if source == "activity_detail":
        return _url_for("web.activity_detail", activity_id=activity.id), "返回活动详情"
    if source == "activities":
        return _url_for("web.activity_list"), "返回活动列表"
    return _url_for("web.events_list"), "返回活动中心"


def _render_event_signup(
    activity: Activity,
    source: str,
    selected_option: ActivityRouteOption | None = None,
    error_message: str = "",
    success_message: str = "",
    submitted_name: str = "",
    submitted_student_id: str = "",
    duplicate_registration_id: int | None = None,
) -> str:
    display_time = _event_display_date(activity)
    signup_open = _activity_signup_open(activity)
    route_cards = _activity_route_cards(activity)
    back_url, back_label = _event_signup_back_target(activity, source)
    return render_template(
        "event_signup.html",
        activity=activity,
        display_time=display_time,
        signup_open=signup_open,
        selected_option=selected_option,
        route_cards=route_cards,
        back_url=back_url,
        back_label=back_label,
        source=source,
        error_message=error_message,
        success_message=success_message,
        submitted_name=submitted_name,
        submitted_student_id=submitted_student_id,
        duplicate_registration_id=duplicate_registration_id,
        meta_description=f"{activity.title} 活动报名页（建设中）。",
    )


def _activity_registration_count_map(activity_ids: list[int]) -> dict[int, int]:
    if not activity_ids:
        return {}
    rows = (
        db.session.query(
            EventRegistration.activity_id,
            db.func.count(EventRegistration.id).label("count"),
        )
        .filter(
            EventRegistration.activity_id.in_(activity_ids),
            EventRegistration.status.in_([REGISTRATION_PENDING, REGISTRATION_CONFIRMED]),
        )
        .group_by(EventRegistration.activity_id)
        .all()
    )
    result = {activity_id: 0 for activity_id in activity_ids}
    for activity_id, count_value in rows:
        result[int(activity_id)] = int(count_value or 0)
    return result


def _activity_signup_open(activity: Activity, now_value=None, registration_count: int | None = None) -> bool:
    if not bool(activity.needs_registration):
        return False
    now_local = _to_local_time(now_value or utcnow())
    display_time = _event_display_date(activity)
    display_local = _to_local_time(display_time) if display_time else None
    if display_local is None or display_local <= now_local:
        return False
    if activity.registration_deadline is not None:
        deadline_local = _to_local_time(activity.registration_deadline)
        if deadline_local >= display_local:
            return False
        if deadline_local <= now_local:
            return False
    limit = int(activity.registration_limit or 0)
    if limit > 0:
        used = int(registration_count or 0) if registration_count is not None else int(
            (
                db.session.query(db.func.count(EventRegistration.id))
                .filter(
                    EventRegistration.activity_id == activity.id,
                    EventRegistration.status.in_([REGISTRATION_PENDING, REGISTRATION_CONFIRMED]),
                )
                .scalar()
                or 0
            )
        )
        if int(used) >= limit:
            return False
    return True


def _activity_signup_open_map(activities: list[Activity], now_value=None) -> dict[int, bool]:
    activity_ids = [item.id for item in activities]
    count_map = _activity_registration_count_map(activity_ids)
    return {
        item.id: _activity_signup_open(item, now_value=now_value, registration_count=count_map.get(item.id, 0))
        for item in activities
    }


def _activity_detail_or_404(activity_id: int) -> Activity:
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        abort(404, description="Activity not found")
    return activity


def _difficulty_stars(value: str | None) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "1": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "easy": 2,
        "medium": 3,
        "hard": 4,
    }
    level = mapping.get(raw, 3)
    return "★" * level + "☆" * (5 - level)


def _activity_route_cards(activity: Activity) -> list[dict]:
    cards: list[dict] = []
    options = (
        ActivityRouteOption.query.filter_by(activity_id=activity.id)
        .order_by(ActivityRouteOption.sort_order.asc(), ActivityRouteOption.id.asc())
        .all()
    )

    if not options:
        fallback_labels = ["初级", "中级", "高级"]
        for index, route in enumerate(activity.routes):
            label = fallback_labels[index] if index < len(fallback_labels) else f"扩展路线 {index + 1}"
            options.append(
                ActivityRouteOption(
                    activity_id=activity.id,
                    route_id=route.id,
                    level_key=f"legacy_{index + 1}",
                    level_label=label,
                    activity_time=activity.activity_time,
                    participant_count=int(activity.participant_count or 0),
                    sort_order=index + 1,
                    route=route,
                )
            )

    media_assets = MediaAsset.query.filter_by(activity_id=activity.id).order_by(MediaAsset.created_at.desc()).all()
    media_by_option: dict[int, list[MediaAsset]] = {}
    for media in media_assets:
        option_id = media.activity_route_option_id
        if not option_id:
            continue
        media_by_option.setdefault(option_id, []).append(media)

    for item in options:
        route = item.route
        if route is None or route.is_deleted or route.status != STATUS_PUBLISHED:
            continue
        distance_km = float(route.distance_km or 0)
        ascent_m = route.ascent_m
        cards.append(
            {
                "label": item.level_label or "路线",
                "option_id": item.id,
                "route": route,
                "media_assets": media_by_option.get(item.id, []),
                "activity_time": item.activity_time or activity.activity_time,
                "participant_count": int(item.participant_count or 0),
                "distance_km": round(distance_km, 2),
                "ascent_m": round(float(ascent_m), 1) if ascent_m is not None else None,
                "difficulty_stars": _difficulty_stars(route.difficulty),
            }
        )
    return cards


def _published_route_or_404(route_id: int) -> Route:
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        abort(404, description="Route not found")
    return route


def _send_route_gpx(route: Route):
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    file_path = upload_folder / route.gpx_filename
    if not file_path.exists():
        abort(404, description="GPX file missing")
    return send_from_directory(
        directory=str(upload_folder),
        path=route.gpx_filename,
        as_attachment=True,
        download_name=route.gpx_filename,
        mimetype="application/gpx+xml",
    )


def _format_lastmod(value) -> str:
    if value is None:
        return ""
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date().isoformat()


@bp.get("/")
def index() -> str:
    now = utcnow()
    latest_activities = Activity.query.order_by(Activity.activity_time.desc()).limit(5).all()
    latest_routes = (
        Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False)
        .order_by(Route.updated_at.desc())
        .limit(5)
        .all()
    )
    route_total = Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False).count()
    announcements = (
        Announcement.query.filter(*_announcement_visibility_filters(now))
        .order_by(
            Announcement.is_pinned.desc(),
            Announcement.sort_order.desc(),
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


@bp.get("/palette-preview")
def palette_preview() -> str:
    abort(404, description="Palette preview is unavailable")


@bp.get("/palette-preview/<string:palette_key>")
def palette_preview_home(palette_key: str) -> str:
    abort(404, description="Palette preview is unavailable")


@bp.get("/announcements/<int:announcement_id>")
def announcement_detail(announcement_id: int) -> str:
    now = utcnow()
    announcement = Announcement.query.filter(
        Announcement.id == announcement_id,
        *_announcement_visibility_filters(now),
    ).first()
    if not announcement:
        abort(404, description="Announcement not found")
    visible_routes = [item for item in announcement.routes if item.status == STATUS_PUBLISHED and not item.is_deleted]
    return render_template(
        "announcement_detail.html",
        announcement=announcement,
        linked_routes=visible_routes,
        meta_description=(announcement.content[:120] if announcement.content else f"{announcement.title} | 2Tired 骑行社公告"),
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
    abort(404, description="Team page is temporarily unavailable")


@bp.get("/contact")
def contact_page() -> str:
    page = _published_site_page("contact")
    return render_template(
        "contact.html",
        page=page,
        meta_description="联系 2Tired 骑行社：活动咨询、反馈、投诉与下架申请渠道。",
    )


@bp.get("/feedback")
def site_feedback() -> str:
    source = (request.args.get("source") or "").strip()
    return render_template("site_feedback.html", source=source)


@bp.post("/feedback")
def site_feedback_submit():
    category = (request.form.get("category") or "bug").strip().lower()
    content = (request.form.get("content") or "").strip()
    contact_local = (request.form.get("contact_local") or "").strip()
    legacy_contact = (request.form.get("contact") or "").strip()
    if not contact_local and legacy_contact:
        contact_local = (legacy_contact.split("@", 1)[0] if "@" in legacy_contact else legacy_contact).strip()
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
            form_data={"category": category, "content": content, "contact_local": contact_local},
        )

    allowed_categories = {"bug", "suggestion", "data", "other"}
    if category not in allowed_categories:
        category = "other"

    if len(content) < 5:
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="反馈内容至少 5 个字。",
            form_data={"category": category, "content": content, "contact_local": contact_local},
        )
    if len(content) > 2000:
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="反馈内容不能超过 2000 个字。",
            form_data={"category": category, "content": content, "contact_local": contact_local},
        )

    if len(contact_local) > 64:
        contact_local = contact_local[:64]
    if contact_local and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", contact_local):
        return render_template(
            "site_feedback.html",
            source=source,
            error_message="反馈邮箱格式不正确，请填写 @link.cuhk.edu.cn 前的邮箱前缀。",
            form_data={"category": category, "content": content, "contact_local": contact_local},
        )
    contact = f"{contact_local}@link.cuhk.edu.cn" if contact_local else ""

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
    return redirect(_url_for("web.index", feedback="ok"))


@bp.get("/routes/<int:route_id>")
def route_detail(route_id: int) -> str:
    route = _published_route_or_404(route_id)
    rating_map = _rating_summary_map([route.id])
    rating_info = rating_map.get(route.id, {"avg_rating": 0.0, "rating_count": 0})
    linked_activity_items: list[dict] = []
    for activity in route.activities:
        display_time = _event_display_date(activity)
        display_local = _to_local_time(display_time) if display_time else None
        linked_activity_items.append(
            {
                "id": activity.id,
                "title": activity.title,
                "display_date": display_local.strftime("%Y-%m-%d") if display_local else "-",
            }
        )
    linked_activity_items.sort(key=lambda item: (item["display_date"], item["id"]), reverse=True)
    from_activity_id = request.args.get("from_activity_id", type=int)
    from_detail = (request.args.get("from_detail") or "").strip()
    source = (request.args.get("source") or "").strip()
    back_url = None
    back_label = None
    if from_activity_id and from_detail in {"web.activity_detail", "web.events_detail"}:
        route_back_params = {"source": source} if source else {}
        if from_detail == "web.events_detail":
            back_url = _url_for("web.events_detail", event_id=from_activity_id, **route_back_params)
            back_label = "返回活动详情"
        else:
            back_url = _url_for("web.activity_detail", activity_id=from_activity_id, **route_back_params)
            back_label = "返回活动详情"
    elif source == "home":
        back_url = _url_for("web.index")
        back_label = "返回首页"
    return render_template(
        "route_detail.html",
        route=route,
        rating_info=rating_info,
        linked_activity_items=linked_activity_items[:5],
        back_url=back_url,
        back_label=back_label,
        meta_description=f"{route.route_name} 路线详情：里程、难度与下载。",
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
    now_value = utcnow()
    today_local_date = _to_local_time(utcnow()).date().isoformat()
    registration_count_map = _activity_registration_count_map([item.id for item in pagination.items])
    return render_template(
        "activities.html",
        activities=pagination.items,
        pagination=pagination,
        today_local_date=today_local_date,
        signup_open_map=_activity_signup_open_map(pagination.items, now_value=now_value),
        registration_count_map=registration_count_map,
        is_beta_view=_is_beta_request(),
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
    now_value = utcnow()
    today_local_date = _to_local_time(now_value).date().isoformat()
    registration_count_map = _activity_registration_count_map([item.id for item in pagination.items])
    return render_template(
        "activities.html",
        activities=pagination.items,
        event_display_date_map=_event_display_date_map(pagination.items),
        pagination=pagination,
        today_local_date=today_local_date,
        signup_open_map=_activity_signup_open_map(pagination.items, now_value=now_value),
        registration_count_map=registration_count_map,
        is_beta_view=_is_beta_request(),
        detail_endpoint="web.events_detail",
        list_endpoint="web.events_list",
        meta_description="2Tired 骑行社活动中心：查看最新活动与历史活动记录。",
        list_title="社团活动",
    )


@bp.get("/activities/<int:activity_id>")
def activity_detail(activity_id: int) -> str:
    activity = _activity_detail_or_404(activity_id)
    now_value = utcnow()
    can_signup = _activity_signup_open(activity, now_value=now_value)
    display_time = _event_display_date(activity)
    display_local = _to_local_time(display_time) if display_time else None
    now_local = _to_local_time(now_value)
    show_signup_paused = bool(
        activity.needs_registration and display_local and display_local > now_local and not can_signup
    )
    media_assets = (
        MediaAsset.query.filter_by(activity_id=activity.id, activity_route_option_id=None)
        .order_by(MediaAsset.created_at.desc())
        .all()
    )
    route_cards = _activity_route_cards(activity)
    source = (request.args.get("source") or "").strip()
    if source == "manage":
        back_url = _url_for("admin.activities_page")
        back_label = "返回活动管理"
    elif source == "home":
        back_url = _url_for("web.index")
        back_label = "返回首页"
    else:
        back_url = _url_for("web.activity_list")
        back_label = "返回活动列表"
    return render_template(
        "activity_detail.html",
        activity=activity,
        media_assets=media_assets,
        route_cards=route_cards,
        can_signup=can_signup,
        show_signup_paused=show_signup_paused,
        is_beta_view=_is_beta_request(),
        signup_source="activity_detail",
        route_back_params={
            "from_activity_id": activity.id,
            "from_detail": "web.activity_detail",
            **({"source": source} if source else {}),
        },
        back_url=back_url,
        back_label=back_label,
        meta_description=f"{activity.title} 活动详情：时间、人数、路线关联与活动总结。",
    )


@bp.get("/events/<int:event_id>")
def events_detail(event_id: int) -> str:
    activity = _activity_detail_or_404(event_id)
    now_value = utcnow()
    can_signup = _activity_signup_open(activity, now_value=now_value)
    display_time = _event_display_date(activity)
    display_local = _to_local_time(display_time) if display_time else None
    now_local = _to_local_time(now_value)
    show_signup_paused = bool(
        activity.needs_registration and display_local and display_local > now_local and not can_signup
    )
    media_assets = (
        MediaAsset.query.filter_by(activity_id=activity.id, activity_route_option_id=None)
        .order_by(MediaAsset.created_at.desc())
        .all()
    )
    route_cards = _activity_route_cards(activity)
    source = (request.args.get("source") or "").strip()
    if source == "manage":
        back_url = _url_for("admin.activities_page")
        back_label = "返回活动管理"
    elif source == "home":
        back_url = _url_for("web.index")
        back_label = "返回首页"
    else:
        back_url = _url_for("web.events_list")
        back_label = "返回活动中心"
    return render_template(
        "activity_detail.html",
        activity=activity,
        media_assets=media_assets,
        route_cards=route_cards,
        can_signup=can_signup,
        show_signup_paused=show_signup_paused,
        is_beta_view=_is_beta_request(),
        signup_source="events_detail",
        route_back_params={
            "from_activity_id": activity.id,
            "from_detail": "web.events_detail",
            **({"source": source} if source else {}),
        },
        back_url=back_url,
        back_label=back_label,
        meta_description=f"{activity.title} 活动详情：时间、人数、路线关联与活动总结。",
    )


@bp.get("/events/<int:event_id>/signup")
def event_signup(event_id: int) -> str:
    activity = _activity_detail_or_404(event_id)
    option_id = request.args.get("option_id", type=int)
    selected_option = None
    if option_id:
        selected_option = ActivityRouteOption.query.filter_by(id=option_id, activity_id=activity.id).first()
    source = (request.args.get("source") or "").strip()
    success = (request.args.get("success") or "").strip() == "1"
    updated = (request.args.get("updated") or "").strip() == "1"
    success_message = "报名信息已更新。" if updated else "报名成功，已记录你的报名信息。"
    return _render_event_signup(
        activity=activity,
        source=source,
        selected_option=selected_option,
        success_message=(success_message if success else ""),
    )


@bp.post("/events/<int:event_id>/signup")
def event_signup_submit(event_id: int):
    activity = _activity_detail_or_404(event_id)
    source = (request.form.get("source") or "").strip()
    name = (request.form.get("name") or "").strip()
    student_id = (request.form.get("student_id") or "").strip()
    option_id = request.form.get("option_id", type=int)
    required_consent = (request.form.get("consent_required") or "").strip() == "1"
    image_consent = (request.form.get("consent_image") or "").strip() == "1"
    update_registration_id = request.form.get("update_registration_id", type=int)
    source_ip = (client_ip() or "")[:64]

    selected_option = None
    if option_id:
        selected_option = ActivityRouteOption.query.filter_by(id=option_id, activity_id=activity.id).first()

    route_cards = _activity_route_cards(activity)
    requires_route_choice = bool(route_cards) and selected_option is None
    if len(name) < 1:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="请先填写姓名。",
            submitted_name=name,
            submitted_student_id=student_id,
        )
    if len(name) > 64:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="姓名长度不能超过 64 个字符。",
            submitted_name=name[:64],
            submitted_student_id=student_id,
        )
    if len(student_id) < 1:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="请先填写学号。",
            submitted_name=name,
            submitted_student_id=student_id,
        )
    if len(student_id) > 32:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="学号长度不能超过 32 个字符。",
            submitted_name=name,
            submitted_student_id=student_id[:32],
        )
    if requires_route_choice:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=None,
            error_message="请选择报名路线后再提交。",
            submitted_name=name,
            submitted_student_id=student_id,
        )
    if not required_consent:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="请先勾选并同意活动须知与风险告知。",
            submitted_name=name,
            submitted_student_id=student_id,
        )
    if not _activity_signup_open(activity):
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="当前活动未开放报名，请关注下一次活动安排。",
            submitted_name=name,
            submitted_student_id=student_id,
        )

    existing_registration = (
        EventRegistration.query
        .filter(
            EventRegistration.activity_id == activity.id,
            db.func.lower(EventRegistration.student_id) == student_id.lower(),
            EventRegistration.status.in_([REGISTRATION_PENDING, REGISTRATION_CONFIRMED]),
        )
        .first()
    )
    if existing_registration and update_registration_id != existing_registration.id:
        return _render_event_signup(
            activity=activity,
            source=source,
            selected_option=selected_option,
            error_message="该学号已提交过本活动报名。请确认是否修改原报名信息。",
            submitted_name=name,
            submitted_student_id=student_id,
            duplicate_registration_id=existing_registration.id,
        )

    note_parts = []
    if selected_option and selected_option.route:
        note_parts.append(f"route_option_id={selected_option.id}")
        note_parts.append(f"route_label={selected_option.level_label or '路线'}")
        note_parts.append(f"route_name={selected_option.route.route_name}")
    note_parts.append(f"image_consent={'1' if image_consent else '0'}")
    notes = "; ".join(note_parts)

    if existing_registration and update_registration_id == existing_registration.id:
        previous_note_map = dict(
            item.split("=", 1)
            for item in (existing_registration.notes or "").split("; ")
            if "=" in item
        )
        previous_option_id = None
        try:
            previous_option_id = int(previous_note_map.get("route_option_id") or 0) or None
        except ValueError:
            previous_option_id = None

        existing_registration.name = name
        existing_registration.student_id = student_id
        existing_registration.source_ip = source_ip
        existing_registration.user_agent = (request.user_agent.string or "")[:255]
        existing_registration.notes = notes[:1000]
        existing_registration.updated_at = utcnow()

        if previous_option_id != (selected_option.id if selected_option else None):
            if previous_option_id:
                previous_option = ActivityRouteOption.query.filter_by(
                    id=previous_option_id,
                    activity_id=activity.id,
                ).first()
                if previous_option:
                    previous_option.participant_count = max(0, int(previous_option.participant_count or 0) - 1)
            if selected_option:
                selected_option.participant_count = int(selected_option.participant_count or 0) + 1
    else:
        registration = EventRegistration(
            activity_id=activity.id,
            name=name,
            student_id=student_id,
            status=REGISTRATION_PENDING,
            source_ip=source_ip,
            user_agent=(request.user_agent.string or "")[:255],
            notes=notes[:1000],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.session.add(registration)
        activity.participant_count = int(activity.participant_count or 0) + 1
        if selected_option:
            selected_option.participant_count = int(selected_option.participant_count or 0) + 1
    db.session.commit()

    return redirect(
        _url_for(
            "web.event_signup",
            event_id=activity.id,
            source=source,
            **({"option_id": selected_option.id} if selected_option else {}),
            **({"updated": 1} if existing_registration and update_registration_id == existing_registration.id else {}),
            success=1,
        )
    )


@bp.get("/events/<int:event_id>/insurance-qr")
def activity_insurance_qr(event_id: int):
    activity = _activity_detail_or_404(event_id)
    qr_path = (activity.insurance_qr_path or "").strip()
    if not qr_path:
        abort(404, description="Insurance QR not found")
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    file_path = media_dir / qr_path
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="Insurance QR missing")
    response = send_from_directory(
        directory=str(media_dir),
        path=qr_path,
        as_attachment=False,
    )
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response


@bp.get("/download/<int:route_id>")
def download(route_id: int):
    route = _published_route_or_404(route_id)
    return _send_route_gpx(route)


@bp.post("/download/<int:route_id>/track")
def download_tracked(route_id: int):
    route = _published_route_or_404(route_id)
    route.download_count = (route.download_count or 0) + 1
    route.last_downloaded_at = utcnow()
    db.session.commit()
    return _send_route_gpx(route)


@bp.get("/media/<int:asset_id>")
def media_asset_file(asset_id: int):
    asset = MediaAsset.query.filter_by(id=asset_id).first()
    if not asset:
        abort(404, description="Media not found")
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    file_path = media_dir / (asset.storage_path or "")
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="Media file missing")
    response = send_from_directory(
        directory=str(media_dir),
        path=asset.storage_path,
        as_attachment=False,
        download_name=asset.original_filename or asset.storage_path,
        mimetype=asset.mime_type or "application/octet-stream",
        max_age=31536000,
    )
    # Uploaded media file names are timestamped/unique, so long-term immutable cache is safe.
    response.cache_control.public = True
    response.cache_control.max_age = 31536000
    response.cache_control.immutable = True
    return response


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


@bp.get("/robots.txt")
def robots_txt() -> Response:
    body = (
        "User-agent: *\n"
        "Disallow: /manage/\n"
        "Allow: /\n"
        f"Sitemap: {_url_for('web.sitemap_xml', _external=True)}\n"
    )
    return Response(body, mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap_xml() -> Response:
    static_urls = [
        _url_for("web.index", _external=True),
        _url_for("web.routes_center", _external=True),
        _url_for("web.about_page", _external=True),
        _url_for("web.contact_page", _external=True),
        _url_for("web.events_list", _external=True),
        _url_for("web.site_feedback", _external=True),
    ]

    routes = (
        Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False)
        .order_by(Route.updated_at.desc())
        .all()
    )
    activities = Activity.query.order_by(Activity.updated_at.desc()).all()
    announcements = Announcement.query.filter(
        *_announcement_visibility_filters(utcnow())
    ).all()

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
        lines.append(f"    <loc>{escape(_url_for('web.route_detail', route_id=route.id, _external=True))}</loc>")
        lastmod = _format_lastmod(route.updated_at or route.created_at)
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")

    for activity in activities:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(_url_for('web.events_detail', event_id=activity.id, _external=True))}</loc>")
        lastmod = _format_lastmod(activity.updated_at or activity.created_at)
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")

    for announcement in announcements:
        lines.append("  <url>")
        lines.append(
            f"    <loc>{escape(_url_for('web.announcement_detail', announcement_id=announcement.id, _external=True))}</loc>"
        )
        lastmod = _format_lastmod(announcement.updated_at or announcement.created_at)
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
    return redirect(_url_for("admin.login"))
