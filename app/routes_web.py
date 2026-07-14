from datetime import timedelta, timezone
import csv
import re
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, send_from_directory, session, url_for as flask_url_for
from markupsafe import Markup, escape as html_escape
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth import client_ip, get_csrf_token, validate_csrf_token
from app.models import (
    CONTENT_STATUS_PUBLISHED,
    FEEDBACK_APPROVED,
    Activity,
    ActivityRouteOption,
    Announcement,
    EventRegistration,
    MERCH_BATCH_ACTIVE,
    MEMBER_ACCOUNT_ACTIVE,
    MERCH_ORDER_CANCELLED,
    MERCH_ORDER_CONFIRMED,
    MERCH_ORDER_PENDING,
    MERCH_ORDER_PICKED_UP,
    MERCH_ORDER_READY,
    MemberProfile,
    MemberUser,
    Route,
    RouteFeedback,
    REGISTRATION_CONFIRMED,
    REGISTRATION_PENDING,
    SITE_FEEDBACK_PENDING,
    STATUS_PUBLISHED,
    MediaAsset,
    MerchPreorderBatch,
    MerchPreorderImage,
    MerchPreorderRegistration,
    SiteFeedback,
    SitePage,
    db,
    merch_batch_status_for_window,
    utcnow,
)
from app.member_profile_options import (
    COLLEGE_OPTIONS,
    GENDER_OPTIONS,
    SCHOOL_OPTIONS,
    current_entry_year_options,
    display_college,
    display_entry_year,
    display_gender,
    display_school,
    normalize_college,
    normalize_gender,
    normalize_school,
    parse_entry_year,
)
from app.querying import query_routes_from_request
from app.security_limits import consume_fixed_window
from app.services import add_member_profile_audit_log
from app.gpx_utils import parse_gpx_points_and_stats

bp = Blueprint("web", __name__)
SH_TZ = timezone(timedelta(hours=8))
SITE_FEEDBACK_LIMIT_PER_MINUTE = 5
SITE_FEEDBACK_WINDOW_SECONDS = 60
MERCH_ACTIVE_ORDER_STATUSES = (
    MERCH_ORDER_PENDING,
    MERCH_ORDER_CONFIRMED,
    MERCH_ORDER_READY,
    MERCH_ORDER_PICKED_UP,
)
MERCH_SIZE_OPTIONS = ("XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL")
MERCH_GENDER_OPTIONS = ("男", "女", "其他/不便填写")
ANNOUNCEMENT_LINK_PATTERN = re.compile(r"\[\[([^\]|]{1,180})\|([^\]]{1,120})\]\]")
ANNOUNCEMENT_LINK_PREFIXES = ("/events/", "/routes/", "/kit/", "/announcements/")
MEMBER_STUDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
MEMBER_PASSWORD_MIN_LENGTH = 8


def _url_for(endpoint: str, **values):
    target = endpoint
    if endpoint.startswith("web.") and (request.blueprint or "") == "web_beta":
        target = endpoint.replace("web.", "web_beta.", 1)
    return flask_url_for(target, **values)


def _is_beta_request() -> bool:
    return (request.blueprint or "") == "web_beta"


def _announcement_link_path_allowed(path: str) -> bool:
    return path.startswith("/") and not path.startswith("//") and any(
        path.startswith(prefix) for prefix in ANNOUNCEMENT_LINK_PREFIXES
    )


def _announcement_text_html(text: str) -> Markup:
    return Markup(str(html_escape(text)).replace("\n", "<br>"))


def _render_announcement_content(content: str | None) -> Markup:
    if not content:
        return Markup("")

    parts: list[Markup] = []
    cursor = 0
    for match in ANNOUNCEMENT_LINK_PATTERN.finditer(content):
        parts.append(_announcement_text_html(content[cursor : match.start()]))
        path = match.group(1).strip()
        label = match.group(2).strip()
        if path and label and _announcement_link_path_allowed(path):
            parts.append(
                Markup('<a class="announcement-inline-link btn btn-muted" href="{href}">{label}</a>').format(
                    href=html_escape(path),
                    label=html_escape(label),
                )
            )
        else:
            parts.append(_announcement_text_html(match.group(0)))
        cursor = match.end()
    parts.append(_announcement_text_html(content[cursor:]))
    return Markup("").join(parts)


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
    return {
        "to_local_time": _to_local_time,
        "csrf_token": get_csrf_token,
        "current_member_user": _current_member_user,
        "school_options": SCHOOL_OPTIONS,
        "college_options": COLLEGE_OPTIONS,
        "gender_options": GENDER_OPTIONS,
        "entry_year_options": current_entry_year_options(_to_local_time(utcnow()).date()),
        "display_school": display_school,
        "display_college": display_college,
        "display_gender": display_gender,
        "display_entry_year": display_entry_year,
    }


def _current_member_user() -> MemberUser | None:
    user_id = session.get("member_user_id")
    if not user_id:
        return None
    return MemberUser.query.filter_by(id=user_id, account_status=MEMBER_ACCOUNT_ACTIVE).first()


def _normalize_member_student_id(raw: str | None) -> str:
    return (raw or "").strip().upper()


def _normalize_member_nickname(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())


def _member_auth_next(default_endpoint: str = "web.index") -> str:
    raw_next = (request.args.get("next") or request.form.get("next") or "").strip()
    if raw_next.startswith("/") and not raw_next.startswith("//"):
        return raw_next
    return _url_for(default_endpoint)


def _render_member_auth(
    template_name: str,
    error_message: str = "",
    student_id: str = "",
    nickname: str = "",
):
    return render_template(
        template_name,
        error_message=error_message,
        student_id=student_id,
        nickname=nickname,
        next_url=_member_auth_next(),
    )


def _validate_member_nickname(nickname: str) -> str:
    if not nickname:
        return "请填写昵称。"
    if len(nickname) > 64:
        return "昵称长度不能超过 64 个字符。"
    return ""


def _validate_member_register_input(student_id: str, nickname: str, password: str, password_confirm: str) -> str:
    if not student_id:
        return "请填写学号。"
    if not MEMBER_STUDENT_ID_PATTERN.fullmatch(student_id):
        return "学号需为 3-32 位，可使用字母、数字、下划线和短横线。"
    nickname_error = _validate_member_nickname(nickname)
    if nickname_error:
        return nickname_error
    if len(password) < MEMBER_PASSWORD_MIN_LENGTH:
        return "密码至少需要 8 位。"
    if password != password_confirm:
        return "两次输入的密码不一致。"
    return ""


def _member_login_redirect():
    return redirect(_url_for("web.member_login", next=request.path))


def _validate_member_password_update(member: MemberUser, current_password: str, new_password: str, password_confirm: str) -> str:
    if not current_password or not new_password or not password_confirm:
        return "请完整填写当前密码、新密码和确认密码。"
    if not check_password_hash(member.password_hash, current_password):
        return "当前密码不正确。"
    if len(new_password) < MEMBER_PASSWORD_MIN_LENGTH:
        return "新密码至少需要 8 位。"
    if new_password != password_confirm:
        return "两次输入的新密码不一致。"
    return ""


def _sync_member_profile_link(member: MemberUser) -> MemberProfile | None:
    if member.profile:
        return member.profile

    profile = MemberProfile.query.filter(db.func.upper(MemberProfile.student_id) == member.student_id.upper()).first()
    if not profile:
        return None
    if profile.member_user_id and profile.member_user_id != member.id:
        return None

    if profile.member_user_id != member.id:
        profile.member_user_id = member.id
        profile.updated_at = utcnow()
        db.session.commit()
    return profile


def _member_profile_self_snapshot(profile: MemberProfile) -> dict:
    return {
        "gender": profile.gender,
        "entry_year": profile.entry_year,
        "school": profile.school,
        "college": profile.college,
        "phone": profile.phone,
        "last_confirmed_at": profile.last_confirmed_at.isoformat() if profile.last_confirmed_at else None,
    }


def _clean_optional_member_profile_text(value: str | None) -> str | None:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned or None


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


def _activity_option_registration_count_map(activity_id: int) -> dict[int, int]:
    registrations = (
        EventRegistration.query.filter(
            EventRegistration.activity_id == activity_id,
            EventRegistration.status.in_([REGISTRATION_PENDING, REGISTRATION_CONFIRMED]),
        )
        .with_entities(EventRegistration.notes)
        .all()
    )
    result: dict[int, int] = {}
    for (notes,) in registrations:
        note_map = dict(item.split("=", 1) for item in (notes or "").split("; ") if "=" in item)
        try:
            option_id = int(note_map.get("route_option_id") or 0)
        except ValueError:
            option_id = 0
        if option_id:
            result[option_id] = result.get(option_id, 0) + 1
    return result


def _manual_activity_participant_count(activity: Activity) -> int:
    if activity.route_options:
        return sum(int(option.participant_count or 0) for option in activity.route_options)
    return int(activity.participant_count or 0)


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


def _merch_batch_count_map(batch_ids: list[int]) -> dict[int, int]:
    if not batch_ids:
        return {}
    rows = (
        db.session.query(
            MerchPreorderRegistration.batch_id,
            db.func.coalesce(db.func.sum(MerchPreorderRegistration.quantity), 0).label("count"),
        )
        .filter(
            MerchPreorderRegistration.batch_id.in_(batch_ids),
            MerchPreorderRegistration.status.in_(MERCH_ACTIVE_ORDER_STATUSES),
        )
        .group_by(MerchPreorderRegistration.batch_id)
        .all()
    )
    result = {batch_id: 0 for batch_id in batch_ids}
    for batch_id, count_value in rows:
        result[int(batch_id)] = int(count_value or 0)
    return result


def _merch_batch_open(batch: MerchPreorderBatch, now_value=None) -> bool:
    effective_status = merch_batch_status_for_window(batch.start_at, batch.deadline_at, now_value)
    batch.status = effective_status
    if not bool(batch.is_visible) or effective_status != MERCH_BATCH_ACTIVE:
        return False
    now_local = _to_local_time(now_value or utcnow())
    start_local = _to_local_time(batch.start_at) if batch.start_at else None
    deadline_local = _to_local_time(batch.deadline_at) if batch.deadline_at else None
    if start_local and now_local < start_local:
        return False
    if deadline_local and now_local >= deadline_local:
        return False
    return True


def _merch_batch_or_404(batch_id: int) -> MerchPreorderBatch:
    batch = MerchPreorderBatch.query.filter_by(id=batch_id, is_visible=True).first()
    if not batch:
        abort(404, description="Preorder batch not found")
    batch.status = merch_batch_status_for_window(batch.start_at, batch.deadline_at)
    return batch


def _render_merch_preorder_form(
    batch: MerchPreorderBatch,
    error_message: str = "",
    submitted: dict | None = None,
    duplicate_registration_id: int | None = None,
) -> str:
    count_map = _merch_batch_count_map([batch.id])
    gallery_images = [item for item in batch.images if item.image_kind == "gallery"]
    size_images = [item for item in batch.images if item.image_kind == "size_chart"]
    size_note_display = (batch.size_note or "").replace("。不追求", "\n不追求").replace("。", "")
    return render_template(
        "kit_preorder_detail.html",
        batch=batch,
        registration_count=count_map.get(batch.id, 0),
        gallery_images=gallery_images,
        size_images=size_images,
        is_open=_merch_batch_open(batch),
        error_message=error_message,
        submitted=submitted or {},
        duplicate_registration_id=duplicate_registration_id,
        size_options=MERCH_SIZE_OPTIONS,
        gender_options=MERCH_GENDER_OPTIONS,
        size_note_display=size_note_display,
        meta_description=f"{batch.title} | 2Tired 骑行社骑行服预定",
    )


def _merch_registration_query(batch_id: int, name: str, student_id: str):
    return (
        MerchPreorderRegistration.query
        .filter(
            MerchPreorderRegistration.batch_id == batch_id,
            db.func.lower(MerchPreorderRegistration.student_id) == student_id.lower(),
            db.func.lower(MerchPreorderRegistration.name) == name.lower(),
        )
        .order_by(MerchPreorderRegistration.created_at.desc())
        .first()
    )


def _merch_registration_can_cancel(registration: MerchPreorderRegistration | None) -> bool:
    if not registration or not registration.batch:
        return False
    batch = registration.batch
    batch.status = merch_batch_status_for_window(batch.start_at, batch.deadline_at)
    return bool(
        batch.status == MERCH_BATCH_ACTIVE
        and registration.status in {MERCH_ORDER_PENDING, MERCH_ORDER_CONFIRMED}
        and batch.deadline_at
        and _to_local_time(utcnow()) < _to_local_time(batch.deadline_at)
    )


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
    option_registration_counts = _activity_option_registration_count_map(activity.id) if activity.needs_registration else {}
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
                "participant_count": (
                    int(option_registration_counts.get(item.id, 0))
                    if activity.needs_registration and item.id
                    else int(item.participant_count or 0)
                ),
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
    registration_count_map = _activity_registration_count_map([item.id for item in latest_activities])
    manual_count_map = {item.id: _manual_activity_participant_count(item) for item in latest_activities}
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
        registration_count_map=registration_count_map,
        manual_count_map=manual_count_map,
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
        announcement_content_html=_render_announcement_content(announcement.content),
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


@bp.get("/kit")
def kit_preorder_list() -> str:
    batches = (
        MerchPreorderBatch.query.filter_by(is_visible=True)
        .order_by(MerchPreorderBatch.deadline_at.asc(), MerchPreorderBatch.created_at.desc())
        .all()
    )
    for batch in batches:
        batch.status = merch_batch_status_for_window(batch.start_at, batch.deadline_at)
    status_rank = {"active": 0, "upcoming": 1, "ended": 2}
    batches = sorted(
        batches,
        key=lambda item: (
            status_rank.get(item.status, 9),
            item.deadline_at or utcnow(),
            -int(item.id or 0),
        ),
    )
    count_map = _merch_batch_count_map([item.id for item in batches])
    return render_template(
        "kit_preorder_list.html",
        batches=batches,
        count_map=count_map,
        meta_description="2Tired 骑行社骑行服与社团装备预定入口。",
    )


@bp.get("/kit/lookup")
def kit_preorder_global_lookup() -> str:
    name = (request.args.get("name") or "").strip()
    student_id = (request.args.get("student_id") or "").strip()
    registrations = []
    message = ""
    if name or student_id:
        if not name or not student_id:
            message = "请同时填写姓名和学号。"
        else:
            registrations = (
                MerchPreorderRegistration.query
                .join(MerchPreorderBatch)
                .filter(
                    MerchPreorderBatch.is_visible.is_(True),
                    db.func.lower(MerchPreorderRegistration.student_id) == student_id.lower(),
                    db.func.lower(MerchPreorderRegistration.name) == name.lower(),
                )
                .order_by(MerchPreorderBatch.deadline_at.desc(), MerchPreorderRegistration.created_at.desc())
                .all()
            )
            if not registrations:
                message = "没有查询到对应的预报名记录。"
    for item in registrations:
        if item.batch:
            item.batch.status = merch_batch_status_for_window(item.batch.start_at, item.batch.deadline_at)
    cancel_map = {item.id: _merch_registration_can_cancel(item) for item in registrations}
    return render_template(
        "kit_preorder_global_lookup.html",
        registrations=registrations,
        cancel_map=cancel_map,
        message=message,
        submitted_name=name,
        submitted_student_id=student_id,
        meta_description="查询 2Tired 骑行社所有骑行服预报名记录。",
    )


@bp.get("/kit/<int:batch_id>")
def kit_preorder_detail(batch_id: int) -> str:
    batch = _merch_batch_or_404(batch_id)
    return _render_merch_preorder_form(batch)


@bp.get("/kit/<int:batch_id>/check-student")
def kit_preorder_check_student(batch_id: int):
    _merch_batch_or_404(batch_id)
    student_id = (request.args.get("student_id") or "").strip()
    if not student_id:
        return jsonify({"exists": False})
    registration = (
        MerchPreorderRegistration.query
        .filter(
            MerchPreorderRegistration.batch_id == batch_id,
            db.func.lower(MerchPreorderRegistration.student_id) == student_id.lower(),
            MerchPreorderRegistration.status.in_(MERCH_ACTIVE_ORDER_STATUSES),
        )
        .first()
    )
    if not registration:
        return jsonify({"exists": False})
    return jsonify({"exists": True, "registration_id": registration.id})


@bp.post("/kit/<int:batch_id>/submit")
def kit_preorder_submit(batch_id: int):
    batch = _merch_batch_or_404(batch_id)
    name = (request.form.get("name") or "").strip()
    student_id = (request.form.get("student_id") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    size = (request.form.get("size") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    update_registration_id = request.form.get("update_registration_id", type=int)
    try:
        quantity = int((request.form.get("quantity") or "1").strip())
    except ValueError:
        quantity = 0
    submitted = {
        "name": name,
        "student_id": student_id,
        "phone": phone,
        "gender": gender,
        "size": size,
        "quantity": quantity if quantity > 0 else "",
        "notes": notes,
    }

    if not _merch_batch_open(batch):
        return _render_merch_preorder_form(batch, "当前批次未开放预报名或已经截止。", submitted=submitted)
    if not name or len(name) > 64:
        return _render_merch_preorder_form(batch, "请填写 1-64 个字符的姓名。", submitted=submitted)
    if not student_id or len(student_id) > 32:
        return _render_merch_preorder_form(batch, "请填写 1-32 个字符的学号。", submitted=submitted)
    if not phone or len(phone) > 32:
        return _render_merch_preorder_form(batch, "请填写 1-32 个字符的手机号。", submitted=submitted)
    if gender not in MERCH_GENDER_OPTIONS:
        return _render_merch_preorder_form(batch, "请选择性别。", submitted=submitted)
    if size not in MERCH_SIZE_OPTIONS:
        return _render_merch_preorder_form(batch, "请选择尺码。", submitted=submitted)
    if quantity < 1 or quantity > 10:
        return _render_merch_preorder_form(batch, "件数需要在 1-10 之间。", submitted=submitted)

    existing_registration = (
        MerchPreorderRegistration.query
        .filter(
            MerchPreorderRegistration.batch_id == batch.id,
            db.func.lower(MerchPreorderRegistration.student_id) == student_id.lower(),
            MerchPreorderRegistration.status.in_(MERCH_ACTIVE_ORDER_STATUSES),
        )
        .first()
    )
    if existing_registration and update_registration_id != existing_registration.id:
        return _render_merch_preorder_form(
            batch,
            "该学号已提交过本批次预报名。请确认是否修改原预报名信息。",
            submitted=submitted,
            duplicate_registration_id=existing_registration.id,
        )

    if existing_registration and update_registration_id == existing_registration.id:
        existing_registration.name = name
        existing_registration.student_id = student_id
        existing_registration.phone = phone
        existing_registration.gender = gender
        existing_registration.size = size
        existing_registration.quantity = quantity
        existing_registration.notes = notes[:1000]
        existing_registration.updated_at = utcnow()
        updated = True
    else:
        registration = MerchPreorderRegistration(
            batch_id=batch.id,
            name=name,
            student_id=student_id,
            phone=phone,
            gender=gender,
            size=size,
            quantity=quantity,
            notes=notes[:1000],
            status=MERCH_ORDER_PENDING,
            source_ip=(client_ip() or "")[:64],
            user_agent=(request.user_agent.string or "")[:255],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.session.add(registration)
        updated = False
    db.session.commit()

    return redirect(_url_for("web.kit_preorder_success", batch_id=batch.id, updated=(1 if updated else 0)))


@bp.get("/kit/<int:batch_id>/success")
def kit_preorder_success(batch_id: int) -> str:
    batch = _merch_batch_or_404(batch_id)
    updated = (request.args.get("updated") or "").strip() == "1"
    count_map = _merch_batch_count_map([batch.id])
    return render_template(
        "kit_preorder_success.html",
        batch=batch,
        updated=updated,
        registration_count=count_map.get(batch.id, 0),
        meta_description=f"{batch.title} 预报名成功。",
    )


@bp.get("/kit/<int:batch_id>/lookup")
def kit_preorder_lookup(batch_id: int) -> str:
    batch = _merch_batch_or_404(batch_id)
    name = (request.args.get("name") or "").strip()
    student_id = (request.args.get("student_id") or "").strip()
    registration = None
    message = ""
    if name or student_id:
        if not name or not student_id:
            message = "请同时填写姓名和学号。"
        else:
            registration = _merch_registration_query(batch.id, name, student_id)
            if not registration:
                message = "没有查询到对应的预报名记录。"
    can_cancel = _merch_registration_can_cancel(registration)
    return render_template(
        "kit_preorder_lookup.html",
        batch=batch,
        registration=registration,
        message=message,
        can_cancel=can_cancel,
        submitted_name=name,
        submitted_student_id=student_id,
        meta_description=f"{batch.title} 预报名查询与取消。",
    )


@bp.post("/kit/<int:batch_id>/cancel")
def kit_preorder_cancel(batch_id: int):
    batch = _merch_batch_or_404(batch_id)
    name = (request.form.get("name") or "").strip()
    student_id = (request.form.get("student_id") or "").strip()
    source = (request.form.get("source") or "").strip()
    registration = _merch_registration_query(batch.id, name, student_id) if name and student_id else None
    redirect_endpoint = "web.kit_preorder_global_lookup" if source == "global" else "web.kit_preorder_lookup"
    redirect_values = {"name": name, "student_id": student_id}
    if source != "global":
        redirect_values["batch_id"] = batch.id
    if not registration:
        return redirect(_url_for(redirect_endpoint, **redirect_values))
    if not _merch_registration_can_cancel(registration):
        return redirect(_url_for(redirect_endpoint, **redirect_values))
    registration.status = MERCH_ORDER_CANCELLED
    registration.cancelled_at = utcnow()
    registration.updated_at = utcnow()
    db.session.commit()
    return redirect(_url_for(redirect_endpoint, **redirect_values, cancelled=1))


@bp.get("/kit/image/<int:image_id>")
def kit_preorder_image(image_id: int):
    image = MerchPreorderImage.query.filter_by(id=image_id).first()
    if not image or not image.batch or not image.batch.is_visible:
        abort(404, description="Preorder image not found")
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    file_path = media_dir / (image.storage_path or "")
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="Preorder image missing")
    response = send_from_directory(
        directory=str(media_dir),
        path=image.storage_path,
        as_attachment=False,
        download_name=image.original_filename or image.storage_path,
        mimetype=image.mime_type or "application/octet-stream",
        max_age=31536000,
    )
    response.cache_control.public = True
    response.cache_control.max_age = 31536000
    response.cache_control.immutable = True
    return response


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
    manual_count_map = {item.id: _manual_activity_participant_count(item) for item in pagination.items}
    return render_template(
        "activities.html",
        activities=pagination.items,
        pagination=pagination,
        today_local_date=today_local_date,
        signup_open_map=_activity_signup_open_map(pagination.items, now_value=now_value),
        registration_count_map=registration_count_map,
        manual_count_map=manual_count_map,
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
    manual_count_map = {item.id: _manual_activity_participant_count(item) for item in pagination.items}
    return render_template(
        "activities.html",
        activities=pagination.items,
        event_display_date_map=_event_display_date_map(pagination.items),
        pagination=pagination,
        today_local_date=today_local_date,
        signup_open_map=_activity_signup_open_map(pagination.items, now_value=now_value),
        registration_count_map=registration_count_map,
        manual_count_map=manual_count_map,
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


@bp.get("/events/<int:event_id>/signup/success")
def event_signup_success(event_id: int) -> str:
    activity = _activity_detail_or_404(event_id)
    source = (request.args.get("source") or "").strip()
    option_id = request.args.get("option_id", type=int)
    updated = (request.args.get("updated") or "").strip() == "1"
    selected_option = None
    if option_id:
        selected_option = ActivityRouteOption.query.filter_by(id=option_id, activity_id=activity.id).first()
    display_time = _event_display_date(activity)
    back_url, back_label = _event_signup_back_target(activity, source)
    has_group_qr = False
    qr_path = (activity.insurance_qr_path or "").strip()
    if qr_path:
        file_path = Path(current_app.config["MEDIA_UPLOAD_FOLDER"]) / qr_path
        has_group_qr = file_path.exists() and file_path.is_file()
    return render_template(
        "event_signup_success.html",
        activity=activity,
        display_time=display_time,
        selected_option=selected_option,
        source=source,
        updated=updated,
        back_url=back_url,
        back_label=back_label,
        has_group_qr=has_group_qr,
        meta_description=f"{activity.title} 报名成功，请加入活动群聊。",
    )


@bp.get("/events/<int:event_id>/signup/check-student")
def event_signup_check_student(event_id: int):
    _activity_detail_or_404(event_id)
    student_id = (request.args.get("student_id") or "").strip()
    if not student_id:
        return jsonify({"exists": False})

    registration = (
        EventRegistration.query
        .filter(
            EventRegistration.activity_id == event_id,
            db.func.lower(EventRegistration.student_id) == student_id.lower(),
            EventRegistration.status.in_([REGISTRATION_PENDING, REGISTRATION_CONFIRMED]),
        )
        .first()
    )
    if not registration:
        return jsonify({"exists": False})
    return jsonify({"exists": True, "registration_id": registration.id})


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
        existing_registration.name = name
        existing_registration.student_id = student_id
        existing_registration.source_ip = source_ip
        existing_registration.user_agent = (request.user_agent.string or "")[:255]
        existing_registration.notes = notes[:1000]
        existing_registration.updated_at = utcnow()

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
    db.session.commit()

    return redirect(
        _url_for(
            "web.event_signup_success",
            event_id=activity.id,
            source=source,
            **({"option_id": selected_option.id} if selected_option else {}),
            **({"updated": 1} if existing_registration and update_registration_id == existing_registration.id else {}),
        )
    )


def _activity_qr_response(event_id: int):
    activity = _activity_detail_or_404(event_id)
    qr_path = (activity.insurance_qr_path or "").strip()
    if not qr_path:
        abort(404, description="Activity QR not found")
    media_dir = Path(current_app.config["MEDIA_UPLOAD_FOLDER"])
    file_path = media_dir / qr_path
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="Activity QR missing")
    response = send_from_directory(
        directory=str(media_dir),
        path=qr_path,
        as_attachment=False,
    )
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response


@bp.get("/events/<int:event_id>/wechat-qr")
def activity_wechat_qr(event_id: int):
    return _activity_qr_response(event_id)


@bp.get("/events/<int:event_id>/insurance-qr")
def activity_insurance_qr(event_id: int):
    return _activity_qr_response(event_id)


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


@bp.get("/member/register")
def member_register():
    if _current_member_user():
        return redirect(_member_auth_next())
    return _render_member_auth(
        "member_register.html",
        student_id=_normalize_member_student_id(request.args.get("student_id")),
        nickname=_normalize_member_nickname(request.args.get("nickname")),
    )


@bp.post("/member/register")
def member_register_submit():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")

    student_id = _normalize_member_student_id(request.form.get("student_id"))
    nickname = _normalize_member_nickname(request.form.get("nickname"))
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""
    error_message = _validate_member_register_input(student_id, nickname, password, password_confirm)
    if error_message:
        return _render_member_auth(
            "member_register.html",
            error_message=error_message,
            student_id=student_id,
            nickname=nickname,
        ), 400

    existing = MemberUser.query.filter(db.func.upper(MemberUser.student_id) == student_id.upper()).first()
    if existing:
        return _render_member_auth(
            "member_register.html",
            error_message="该学号已注册账号。",
            student_id=student_id,
            nickname=nickname,
        ), 409

    now_value = utcnow()
    member = MemberUser(
        student_id=student_id,
        nickname=nickname,
        password_hash=generate_password_hash(password),
        account_status=MEMBER_ACCOUNT_ACTIVE,
        created_at=now_value,
        updated_at=now_value,
    )
    db.session.add(member)
    db.session.commit()
    _sync_member_profile_link(member)
    session["member_user_id"] = member.id
    return redirect(_member_auth_next())


@bp.get("/member/login")
def member_login():
    if _current_member_user():
        return redirect(_member_auth_next())
    return _render_member_auth(
        "member_login.html",
        student_id=_normalize_member_student_id(request.args.get("student_id")),
    )


@bp.post("/member/login")
def member_login_submit():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")

    student_id = _normalize_member_student_id(request.form.get("student_id"))
    password = request.form.get("password") or ""
    member = MemberUser.query.filter(db.func.upper(MemberUser.student_id) == student_id.upper()).first()
    if not member or member.account_status != MEMBER_ACCOUNT_ACTIVE or not check_password_hash(member.password_hash, password):
        return _render_member_auth("member_login.html", error_message="学号或密码不正确。", student_id=student_id), 401

    member.last_login_at = utcnow()
    member.updated_at = utcnow()
    db.session.commit()
    session["member_user_id"] = member.id
    return redirect(_member_auth_next())


@bp.get("/member/password")
def member_password():
    member = _current_member_user()
    if not member:
        return _member_login_redirect()
    return render_template(
        "member_password.html",
        member=member,
        error_message="",
        success_message="",
        meta_description="修改 2Tired 骑行社社员账号密码。",
    )


@bp.get("/member/account")
def member_account():
    member = _current_member_user()
    if not member:
        return _member_login_redirect()
    profile = _sync_member_profile_link(member)
    return render_template(
        "member_account.html",
        member=member,
        profile=profile,
        error_message="",
        success_message=request.args.get("updated") == "nickname",
        meta_description="查看 2Tired 骑行社社员账号信息。",
    )


@bp.get("/member/profile")
def member_profile():
    member = _current_member_user()
    if not member:
        return _member_login_redirect()
    profile = _sync_member_profile_link(member)
    return render_template(
        "member_profile.html",
        member=member,
        profile=profile,
        meta_description="查看 2Tired 骑行社社员资料。",
    )


@bp.get("/member/profile/edit")
def member_profile_edit():
    member = _current_member_user()
    if not member:
        return _member_login_redirect()
    profile = _sync_member_profile_link(member)
    if not profile:
        return render_template(
            "member_profile.html",
            member=member,
            profile=None,
            error_message="暂未匹配到社员档案，无法修改资料。",
            meta_description="查看 2Tired 骑行社社员资料。",
        ), 404
    return render_template(
        "member_profile_edit.html",
        member=member,
        profile=profile,
        error_message="",
    )


@bp.post("/member/profile/edit")
def member_profile_edit_submit():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")
    member = _current_member_user()
    if not member:
        return _member_login_redirect()
    profile = _sync_member_profile_link(member)
    if not profile:
        return render_template(
            "member_profile.html",
            member=member,
            profile=None,
            error_message="暂未匹配到社员档案，无法修改资料。",
            meta_description="查看 2Tired 骑行社社员资料。",
        ), 404

    before = _member_profile_self_snapshot(profile)
    editable_before = {key: before.get(key) for key in ("gender", "entry_year", "school", "college", "phone")}
    entry_year, entry_year_error = parse_entry_year(request.form.get("entry_year"))
    gender, gender_error = normalize_gender(request.form.get("gender"))
    school, school_error = normalize_school(request.form.get("school"))
    college, college_error = normalize_college(request.form.get("college"))
    if entry_year_error or gender_error or school_error or college_error:
        return render_template(
            "member_profile_edit.html",
            member=member,
            profile=profile,
            error_message=entry_year_error or gender_error or school_error or college_error,
        ), 400
    profile.entry_year = entry_year
    profile.gender = gender
    profile.school = school
    profile.college = college
    profile.phone = _clean_optional_member_profile_text(request.form.get("phone"))
    profile.last_confirmed_at = _to_local_time(utcnow()).date()
    profile.updated_at = utcnow()
    after = _member_profile_self_snapshot(profile)
    editable_after = {key: after.get(key) for key in editable_before}
    action = "member_profile.self_update" if editable_before != editable_after else "member_profile.self_confirm"
    add_member_profile_audit_log(
        action,
        profile,
        before,
        after,
        source="self_update" if action == "member_profile.self_update" else "self_confirm",
        actor_member_user_id=member.id,
        extra={"member_user_id": member.id},
    )
    db.session.commit()
    return redirect(_url_for("web.member_profile", updated="profile"))


@bp.post("/member/account/nickname")
def member_account_nickname_submit():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")
    member = _current_member_user()
    if not member:
        return _member_login_redirect()

    nickname = _normalize_member_nickname(request.form.get("nickname"))
    error_message = _validate_member_nickname(nickname)
    if error_message:
        profile = _sync_member_profile_link(member)
        return render_template(
            "member_account.html",
            member=member,
            profile=profile,
            error_message=error_message,
            success_message=False,
            meta_description="查看 2Tired 骑行社社员账号信息。",
        ), 400

    member.nickname = nickname
    member.updated_at = utcnow()
    db.session.commit()
    return redirect(_url_for("web.member_account", updated="nickname"))


@bp.post("/member/password")
def member_password_submit():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")
    member = _current_member_user()
    if not member:
        return _member_login_redirect()

    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    password_confirm = request.form.get("password_confirm") or ""
    error_message = _validate_member_password_update(member, current_password, new_password, password_confirm)
    if error_message:
        return render_template(
            "member_password.html",
            member=member,
            error_message=error_message,
            success_message="",
            meta_description="修改 2Tired 骑行社社员账号密码。",
        ), 400

    member.password_hash = generate_password_hash(new_password)
    member.updated_at = utcnow()
    db.session.commit()
    return render_template(
        "member_password.html",
        member=member,
        error_message="",
        success_message="密码已更新。",
        meta_description="修改 2Tired 骑行社社员账号密码。",
    )


@bp.post("/member/logout")
def member_logout():
    if not validate_csrf_token(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")
    session.pop("member_user_id", None)
    return redirect(_url_for("web.index"))


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
