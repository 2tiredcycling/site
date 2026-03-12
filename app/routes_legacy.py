from flask import Blueprint, jsonify

from app.models import STATUS_PUBLISHED, Route

bp = Blueprint("legacy", __name__)


@bp.get("/api/routes")
def legacy_api_routes():
    routes = Route.query.filter_by(status=STATUS_PUBLISHED, is_deleted=False).order_by(Route.created_at.desc()).all()
    return jsonify([item.as_dict() for item in routes])
