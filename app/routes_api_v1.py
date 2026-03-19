from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app.auth import can_review, current_user, validate_csrf_token
from app.gpx_utils import parse_gpx_points_and_stats
from app.models import (
    FEEDBACK_APPROVED,
    FEEDBACK_PENDING,
    FEEDBACK_REJECTED,
    STATUS_PUBLISHED,
    Activity,
    ActivityRoute,
    Route,
    RouteFeedback,
    db,
    utcnow,
)
from app.querying import query_routes_from_request
from app.services import approved_rating_summary, write_audit_log

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _rating_summary_map(route_ids: list[int]) -> dict[int, tuple[float, int]]:
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
    result = {route_id: (0.0, 0) for route_id in route_ids}
    for route_id, avg_rating, rating_count in rows:
        result[route_id] = (round(float(avg_rating or 0), 2), int(rating_count or 0))
    return result


@bp.get("/routes")
def list_routes():
    query, filters = query_routes_from_request(include_unpublished=False)
    pagination = query.paginate(page=filters["page"], per_page=filters["per_page"], error_out=False)
    rating_map = _rating_summary_map([item.id for item in pagination.items])

    items = []
    for item in pagination.items:
        payload = item.as_dict()
        avg, count = rating_map.get(item.id, (0.0, 0))
        payload["avg_rating"] = avg
        payload["rating_count"] = count
        items.append(payload)

    return jsonify(
        {
            "items": items,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
            "total": pagination.total,
            "filters": filters,
        }
    )


@bp.get("/routes/<int:route_id>")
def route_detail(route_id: int):
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        return jsonify({"error": "route_not_found"}), 404

    payload = route.as_dict()
    avg, count = approved_rating_summary(route.id)
    payload["avg_rating"] = avg
    payload["rating_count"] = count
    payload["linked_activities"] = [
        {
            "id": item.id,
            "title": item.title,
            "activity_time": item.activity_time.isoformat() if item.activity_time else None,
        }
        for item in route.activities
    ]
    return jsonify(payload)


@bp.get("/routes/<int:route_id>/preview")
def route_preview(route_id: int):
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
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
def list_activities():
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)
    per_page = max(1, min(50, per_page))

    query = Activity.query.order_by(Activity.activity_time.desc())
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        query = query.filter(Activity.title.ilike(f"%{keyword}%"))

    pagination = query.paginate(page=max(1, page), per_page=per_page, error_out=False)
    return jsonify(
        {
            "items": [item.as_dict() for item in pagination.items],
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
            "total": pagination.total,
        }
    )


@bp.get("/activities/<int:activity_id>")
def activity_detail(activity_id: int):
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        return jsonify({"error": "activity_not_found"}), 404

    payload = activity.as_dict()
    payload["routes"] = [
        {
            "id": item.id,
            "route_name": item.route_name,
            "distance_km": item.distance_km,
            "difficulty": item.difficulty,
            "status": item.status,
        }
        for item in activity.routes
    ]
    return jsonify(payload)


@bp.post("/routes/<int:route_id>/feedback")
def create_feedback(route_id: int):
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        return jsonify({"error": "route_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    comment = (payload.get("comment") or "").strip()
    road_update = (payload.get("road_condition_update") or "").strip()
    report_type = (payload.get("report_type") or "normal").strip() or "normal"

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_rating"}), 400

    if rating < 1 or rating > 5:
        return jsonify({"error": "invalid_rating"}), 400

    feedback = RouteFeedback(
        route_id=route.id,
        rating=rating,
        comment=comment,
        road_condition_update=road_update,
        report_type=report_type,
        status=FEEDBACK_PENDING,
    )
    db.session.add(feedback)
    db.session.commit()

    write_audit_log(None, "feedback.create", "route_feedback", str(feedback.id), f"route={route.id}")
    return jsonify({"id": feedback.id, "status": feedback.status}), 201


@bp.post("/admin/feedback/<int:feedback_id>/review")
def review_feedback(feedback_id: int):
    actor = current_user()
    if not actor:
        return jsonify({"error": "auth_required"}), 401
    if not can_review(actor):
        return jsonify({"error": "permission_denied"}), 403
    claimed_actor_id = request.headers.get("X-Admin-User")
    if claimed_actor_id:
        try:
            claimed_actor_id = int(claimed_actor_id)
        except ValueError:
            return jsonify({"error": "invalid_admin_user"}), 400
        if claimed_actor_id != actor.id:
            return jsonify({"error": "admin_user_mismatch"}), 403
    csrf_token = request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(csrf_token):
        return jsonify({"error": "invalid_csrf"}), 400

    feedback = RouteFeedback.query.filter_by(id=feedback_id).first()
    if not feedback:
        return jsonify({"error": "feedback_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "").strip()
    if status not in (FEEDBACK_APPROVED, FEEDBACK_REJECTED):
        return jsonify({"error": "invalid_status"}), 400

    feedback.status = status
    feedback.reviewer_note = (payload.get("reviewer_note") or "").strip()
    feedback.reviewer_id = actor.id
    feedback.reviewed_at = utcnow()
    db.session.commit()

    write_audit_log(actor.id, "feedback.review", "route_feedback", str(feedback.id), status)
    return jsonify(feedback.as_dict())


@bp.get("/search")
def search():
    keyword = (request.args.get("q") or "").strip()
    if not keyword:
        return jsonify({"routes": [], "activities": [], "popular_routes": [], "latest_updates": []})

    routes = (
        Route.query.filter(Route.is_deleted.is_(False), Route.status == STATUS_PUBLISHED)
        .filter((Route.route_name.ilike(f"%{keyword}%")) | (Route.category.ilike(f"%{keyword}%")))
        .order_by(Route.updated_at.desc())
        .limit(10)
        .all()
    )
    activities = Activity.query.filter(Activity.title.ilike(f"%{keyword}%")).order_by(Activity.activity_time.desc()).limit(10).all()

    popular = (
        Route.query.filter(Route.is_deleted.is_(False), Route.status == STATUS_PUBLISHED)
        .order_by(Route.download_count.desc())
        .limit(5)
        .all()
    )
    latest = (
        Route.query.filter(Route.is_deleted.is_(False), Route.status == STATUS_PUBLISHED)
        .order_by(Route.updated_at.desc())
        .limit(5)
        .all()
    )

    return jsonify(
        {
            "routes": [item.as_dict() for item in routes],
            "activities": [item.as_dict() for item in activities],
            "popular_routes": [item.as_dict() for item in popular],
            "latest_updates": [item.as_dict() for item in latest],
        }
    )


@bp.get("/routes/stats")
def route_stats():
    total = Route.query.filter_by(is_deleted=False).count()
    published = Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False).count()
    total_downloads = int(
        db.session.query(db.func.coalesce(db.func.sum(Route.download_count), 0))
        .filter(Route.is_deleted.is_(False))
        .scalar()
        or 0
    )
    total_activities = Activity.query.count()
    return jsonify(
        {
            "total_routes": total,
            "published_routes": published,
            "total_downloads": total_downloads,
            "total_activities": total_activities,
        }
    )


@bp.get("/health")
def api_health():
    return jsonify({"status": "ok", "version": "v3"})



