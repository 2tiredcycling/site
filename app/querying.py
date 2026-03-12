from sqlalchemy import or_

from flask import request

from app.models import (
    FEEDBACK_APPROVED,
    STATUS_PUBLISHED,
    Activity,
    ActivityRoute,
    Route,
    RouteFeedback,
    db,
)


ALLOWED_SORTS = {"latest", "distance", "rating", "hot"}
ALLOWED_DIRECTIONS = {"asc", "desc"}


def parse_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return default
    parsed = max(min_value, parsed)
    parsed = min(max_value, parsed)
    return parsed


def parse_float(value: str | None):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _feedback_summary_subquery():
    return (
        db.session.query(
            RouteFeedback.route_id.label("route_id"),
            db.func.avg(RouteFeedback.rating).label("avg_rating"),
            db.func.count(RouteFeedback.id).label("rating_count"),
        )
        .filter(RouteFeedback.status == FEEDBACK_APPROVED)
        .group_by(RouteFeedback.route_id)
        .subquery()
    )


def query_routes_from_request(include_unpublished: bool = False):
    rating_subq = _feedback_summary_subquery()

    query = Route.query.outerjoin(rating_subq, rating_subq.c.route_id == Route.id)
    query = query.filter(Route.is_deleted.is_(False))
    if not include_unpublished:
        query = query.filter(Route.status == STATUS_PUBLISHED)

    keyword = (request.args.get("q") or "").strip()
    if keyword:
        query = query.outerjoin(ActivityRoute, ActivityRoute.route_id == Route.id).outerjoin(
            Activity, Activity.id == ActivityRoute.activity_id
        )
        query = query.filter(
            or_(
                Route.route_name.ilike(f"%{keyword}%"),
                Route.category.ilike(f"%{keyword}%"),
                Activity.title.ilike(f"%{keyword}%"),
            )
        )

    difficulty = (request.args.get("difficulty") or "").strip()
    normalized_difficulties = _normalize_difficulty_filter(difficulty)
    if normalized_difficulties:
        query = query.filter(Route.difficulty.in_(normalized_difficulties))

    category = (request.args.get("category") or "").strip()
    if category:
        query = query.filter(Route.category == category)

    min_km = parse_float(request.args.get("min_km"))
    max_km = parse_float(request.args.get("max_km"))
    if min_km is not None:
        query = query.filter(Route.distance_km >= min_km)
    if max_km is not None:
        query = query.filter(Route.distance_km <= max_km)

    min_rating = parse_float(request.args.get("min_rating"))
    if min_rating is not None:
        query = query.filter(db.func.coalesce(rating_subq.c.avg_rating, 0) >= min_rating)

    max_rating = parse_float(request.args.get("max_rating"))
    if max_rating is not None:
        query = query.filter(db.func.coalesce(rating_subq.c.avg_rating, 0) <= max_rating)

    activity_start = (request.args.get("activity_start") or "").strip()
    activity_end = (request.args.get("activity_end") or "").strip()
    if activity_start or activity_end:
        query = query.join(ActivityRoute, ActivityRoute.route_id == Route.id).join(Activity, Activity.id == ActivityRoute.activity_id)
        if activity_start:
            query = query.filter(Activity.activity_time >= activity_start)
        if activity_end:
            query = query.filter(Activity.activity_time <= activity_end)

    status = (request.args.get("status") or "").strip()
    if include_unpublished and status:
        query = query.filter(Route.status == status)

    sort = (request.args.get("sort") or "latest").strip()
    if sort not in ALLOWED_SORTS:
        sort = "latest"
    direction = (request.args.get("direction") or "desc").strip()
    if direction not in ALLOWED_DIRECTIONS:
        direction = "desc"

    if sort == "distance":
        order_col = Route.distance_km
    elif sort == "rating":
        order_col = db.func.coalesce(rating_subq.c.avg_rating, 0)
    elif sort == "hot":
        order_col = Route.download_count
    else:
        order_col = Route.updated_at

    if direction == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    page = parse_int(request.args.get("page"), default=1, min_value=1, max_value=10_000)
    per_page = parse_int(request.args.get("per_page"), default=10, min_value=1, max_value=50)

    return query.distinct(), {
        "q": keyword,
        "difficulty": difficulty,
        "category": category,
        "min_km": "" if min_km is None else min_km,
        "max_km": "" if max_km is None else max_km,
        "min_rating": "" if min_rating is None else min_rating,
        "max_rating": "" if max_rating is None else max_rating,
        "activity_start": activity_start,
        "activity_end": activity_end,
        "status": status,
        "sort": sort,
        "direction": direction,
        "page": page,
        "per_page": per_page,
    }


def _normalize_difficulty_filter(raw: str) -> list[str]:
    if not raw:
        return []

    if raw in {"easy", "medium", "hard"}:
        return [raw]

    mapping = {
        "1": ["easy"],
        "2": ["easy"],
        "3": ["medium"],
        "4": ["hard"],
        "5": ["hard"],
    }
    return mapping.get(raw, [])
