from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index

db = SQLAlchemy()

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_REVIEWER = "reviewer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_REVIEWER, ROLE_VIEWER)

STATUS_DRAFT = "draft"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_PUBLISHED = "published"
STATUS_OFFLINE = "offline"
ROUTE_STATUSES = (STATUS_DRAFT, STATUS_PENDING_REVIEW, STATUS_PUBLISHED, STATUS_OFFLINE)

FEEDBACK_PENDING = "pending"
FEEDBACK_APPROVED = "approved"
FEEDBACK_REJECTED = "rejected"
FEEDBACK_STATUSES = (FEEDBACK_PENDING, FEEDBACK_APPROVED, FEEDBACK_REJECTED)

SITE_FEEDBACK_PENDING = "pending"
SITE_FEEDBACK_DONE = "done"
SITE_FEEDBACK_STATUSES = (SITE_FEEDBACK_PENDING, SITE_FEEDBACK_DONE)


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default=ROLE_EDITOR)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Route(db.Model):
    __tablename__ = "routes"
    __table_args__ = (
        Index("idx_routes_status_deleted", "status", "is_deleted"),
        Index("idx_routes_updated_at", "updated_at"),
        Index("idx_routes_download_count", "download_count"),
    )

    id = db.Column(db.Integer, primary_key=True)
    route_name = db.Column(db.Text, nullable=False)
    gpx_filename = db.Column(db.Text, nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    distance_km = db.Column(db.Float, nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    difficulty = db.Column(db.String(16), nullable=False, default="medium")
    category = db.Column(db.String(64), nullable=False, default="hiking")
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default=STATUS_PUBLISHED)
    download_count = db.Column(db.Integer, nullable=False, default=0)
    last_downloaded_at = db.Column(db.DateTime, nullable=True)
    suggested_duration_hours = db.Column(db.Float, nullable=False, default=0.0)
    supply_points = db.Column(db.Text, nullable=False, default="")
    risk_warning = db.Column(db.Text, nullable=False, default="")
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = db.relationship("User", foreign_keys=[updated_by], lazy="joined")
    deleter = db.relationship("User", foreign_keys=[deleted_by], lazy="joined")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "route_name": self.route_name,
            "gpx_filename": self.gpx_filename,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "distance_km": self.distance_km,
            "is_active": self.is_active,
            "difficulty": self.difficulty,
            "category": self.category,
            "description": self.description,
            "status": self.status,
            "download_count": self.download_count,
            "last_downloaded_at": self.last_downloaded_at.isoformat() if self.last_downloaded_at else None,
            "suggested_duration_hours": self.suggested_duration_hours,
            "supply_points": self.supply_points,
            "risk_warning": self.risk_warning,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }


class Activity(db.Model):
    __tablename__ = "activities"
    __table_args__ = (
        Index("idx_activities_activity_time", "activity_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False, unique=True)
    activity_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    participant_count = db.Column(db.Integer, nullable=False, default=0)
    weather = db.Column(db.String(64), nullable=False, default="")
    summary = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    creator = db.relationship("User", lazy="joined")
    routes = db.relationship("Route", secondary="activity_routes", backref="activities", lazy="selectin")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "activity_time": self.activity_time.isoformat() if self.activity_time else None,
            "participant_count": self.participant_count,
            "weather": self.weather,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "route_ids": [item.id for item in self.routes],
        }


class ActivityRoute(db.Model):
    __tablename__ = "activity_routes"
    __table_args__ = (db.UniqueConstraint("activity_id", "route_id", name="uq_activity_route"),)

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey("routes.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RouteFeedback(db.Model):
    __tablename__ = "route_feedback"
    __table_args__ = (
        Index("idx_feedback_route_status", "route_id", "status"),
        Index("idx_feedback_created_at", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("routes.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False, default="")
    road_condition_update = db.Column(db.Text, nullable=False, default="")
    report_type = db.Column(db.String(32), nullable=False, default="normal")
    status = db.Column(db.String(16), nullable=False, default=FEEDBACK_PENDING)
    reviewer_note = db.Column(db.Text, nullable=False, default="")
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    route = db.relationship("Route", lazy="joined")
    reviewer = db.relationship("User", lazy="joined")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "route_id": self.route_id,
            "rating": self.rating,
            "comment": self.comment,
            "road_condition_update": self.road_condition_update,
            "report_type": self.report_type,
            "status": self.status,
            "reviewer_note": self.reviewer_note,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SiteFeedback(db.Model):
    __tablename__ = "site_feedback"
    __table_args__ = (
        Index("idx_site_feedback_status_created_at", "status", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, default="bug")
    content = db.Column(db.Text, nullable=False, default="")
    contact = db.Column(db.String(128), nullable=False, default="")
    source_page = db.Column(db.String(255), nullable=False, default="")
    user_agent = db.Column(db.String(255), nullable=False, default="")
    ip_address = db.Column(db.String(64), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default=SITE_FEEDBACK_PENDING)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "contact": self.contact,
            "source_page": self.source_page,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RouteVersion(db.Model):
    __tablename__ = "route_versions"
    __table_args__ = (
        Index("idx_route_versions_route_version", "route_id", "version_no"),
    )

    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("routes.id"), nullable=False)
    version_no = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    change_note = db.Column(db.Text, nullable=False, default="")
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    route = db.relationship("Route", lazy="joined")
    changer = db.relationship("User", lazy="joined")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "route_id": self.route_id,
            "version_no": self.version_no,
            "snapshot_json": self.snapshot_json,
            "change_note": self.change_note,
            "changed_by": self.changed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MediaAsset(db.Model):
    __tablename__ = "media_assets"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id"), nullable=True)
    route_id = db.Column(db.Integer, db.ForeignKey("routes.id"), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(128), nullable=False, default="")
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    activity = db.relationship("Activity", lazy="joined")
    route = db.relationship("Route", lazy="joined")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "route_id": self.route_id,
            "original_filename": self.original_filename,
            "storage_path": self.storage_path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ImportReport(db.Model):
    __tablename__ = "import_reports"

    id = db.Column(db.Integer, primary_key=True)
    report_token = db.Column(db.String(64), nullable=False, unique=True)
    report_filename = db.Column(db.String(255), nullable=False)
    success_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    creator = db.relationship("User", lazy="joined")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "report_token": self.report_token,
            "report_filename": self.report_filename,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    target_type = db.Column(db.String(64), nullable=False)
    target_id = db.Column(db.String(64), nullable=True)
    detail = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    actor = db.relationship("User", lazy="joined")


class AccessLog(db.Model):
    __tablename__ = "access_logs"
    __table_args__ = (
        Index("idx_access_logs_created_at", "created_at"),
        Index("idx_access_logs_path_created_at", "path", "created_at"),
        Index("idx_access_logs_status_created_at", "status_code", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), nullable=False, default="")
    method = db.Column(db.String(16), nullable=False, default="GET")
    endpoint = db.Column(db.String(128), nullable=False, default="")
    status_code = db.Column(db.Integer, nullable=False, default=200)
    ip_address = db.Column(db.String(64), nullable=False, default="")
    user_agent = db.Column(db.String(255), nullable=False, default="")
    referer = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RateLimitState(db.Model):
    __tablename__ = "rate_limit_states"
    __table_args__ = (
        db.UniqueConstraint("action", "subject", name="uq_rate_limit_action_subject"),
        Index("idx_rate_limit_action_subject", "action", "subject"),
    )

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(64), nullable=False)
    subject = db.Column(db.String(128), nullable=False)
    window_started_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
