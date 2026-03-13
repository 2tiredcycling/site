from datetime import timedelta, timezone
import csv
from io import StringIO
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from app.models import FEEDBACK_APPROVED, Activity, Route, RouteFeedback, STATUS_PUBLISHED, db, utcnow
from app.querying import query_routes_from_request

bp = Blueprint("web", __name__)
SH_TZ = timezone(timedelta(hours=8))


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


@bp.get("/")
def index() -> str:
    query, filters = query_routes_from_request(include_unpublished=False)
    pagination = query.paginate(page=filters["page"], per_page=filters["per_page"], error_out=False)
    rating_map = _rating_summary_map([item.id for item in pagination.items])
    return render_template(
        "index.html",
        routes=pagination.items,
        pagination=pagination,
        filters=filters,
        rating_map=rating_map,
    )


@bp.get("/routes/<int:route_id>")
def route_detail(route_id: int) -> str:
    route = Route.query.filter_by(id=route_id, status=STATUS_PUBLISHED, is_deleted=False).first()
    if not route:
        abort(404, description="Route not found")
    rating_map = _rating_summary_map([route.id])
    rating_info = rating_map.get(route.id, {"avg_rating": 0.0, "rating_count": 0})
    return render_template("route_detail.html", route=route, rating_info=rating_info)


@bp.get("/activities")
def activity_list() -> str:
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)
    pagination = Activity.query.order_by(Activity.activity_time.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template("activities.html", activities=pagination.items, pagination=pagination)


@bp.get("/activities/<int:activity_id>")
def activity_detail(activity_id: int) -> str:
    activity = Activity.query.filter_by(id=activity_id).first()
    if not activity:
        abort(404, description="Activity not found")
    source = (request.args.get("source") or "").strip()
    back_url = None
    back_label = None
    if source == "manage":
        back_url = url_for("admin.activities_page")
        back_label = "返回活动管理"
    return render_template("activity_detail.html", activity=activity, back_url=back_url, back_label=back_label)


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


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


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
    query, filters = query_routes_from_request(include_unpublished=False)
    pagination = query.paginate(page=filters["page"], per_page=filters["per_page"], error_out=False)
    message = getattr(error, "description", "Resource not found")
    return render_template("index.html", routes=pagination.items, pagination=pagination, filters=filters, error_message=message), 404


@bp.app_errorhandler(403)
def handle_403(_error):
    return redirect(url_for("admin.login"))


