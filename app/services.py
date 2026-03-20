import csv
import json
import secrets
from datetime import timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from app.models import (
    FEEDBACK_APPROVED,
    LEGACY_ROLE_MIGRATIONS,
    ROLE_SUPER_ADMIN,
    STATUS_PUBLISHED,
    Activity,
    AuditLog,
    ImportReport,
    Route,
    RouteFeedback,
    RouteVersion,
    User,
    db,
    utcnow,
)


def _is_sqlite() -> bool:
    return db.engine.dialect.name == "sqlite"


def _table_columns(table_name: str) -> set[str]:
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {item["name"] for item in inspector.get_columns(table_name)}


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    columns = _table_columns(table)
    if column in columns:
        return
    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema_compat() -> None:
    db.create_all()
    is_sqlite = _is_sqlite()

    if is_sqlite:
        _add_column_if_missing("routes", "updated_at", "updated_at DATETIME")
        _add_column_if_missing("routes", "uploaded_at", "uploaded_at DATETIME")
        _add_column_if_missing("routes", "distance_km", "distance_km FLOAT DEFAULT 0")
        _add_column_if_missing("routes", "difficulty", "difficulty VARCHAR(16) DEFAULT 'medium' NOT NULL")
        _add_column_if_missing("routes", "category", "category VARCHAR(64) DEFAULT 'hiking' NOT NULL")
        _add_column_if_missing("routes", "description", "description TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "status", "status VARCHAR(16) DEFAULT 'published' NOT NULL")
        _add_column_if_missing("routes", "download_count", "download_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("routes", "last_downloaded_at", "last_downloaded_at DATETIME")
        _add_column_if_missing("routes", "suggested_duration_hours", "suggested_duration_hours FLOAT DEFAULT 0 NOT NULL")
        _add_column_if_missing("routes", "supply_points", "supply_points TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "risk_warning", "risk_warning TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "is_deleted", "is_deleted BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("routes", "deleted_at", "deleted_at DATETIME")
        _add_column_if_missing("routes", "deleted_by", "deleted_by INTEGER")
        _add_column_if_missing("routes", "created_by", "created_by INTEGER")
        _add_column_if_missing("routes", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("users", "perm_view_analytics", "perm_view_analytics BOOLEAN DEFAULT 1 NOT NULL")
        _add_column_if_missing("users", "perm_view_security", "perm_view_security BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("users", "perm_review", "perm_review BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("users", "perm_edit_content", "perm_edit_content BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("users", "perm_manage_users", "perm_manage_users BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("users", "perm_view_audit_logs", "perm_view_audit_logs BOOLEAN DEFAULT 0 NOT NULL")

        _add_column_if_missing("site_pages", "summary", "summary VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("site_pages", "content", "content TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("site_pages", "status", "status VARCHAR(16) DEFAULT 'draft' NOT NULL")
        _add_column_if_missing("site_pages", "published_at", "published_at DATETIME")
        _add_column_if_missing("site_pages", "created_by", "created_by INTEGER")
        _add_column_if_missing("site_pages", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("site_pages", "created_at", "created_at DATETIME")
        _add_column_if_missing("site_pages", "updated_at", "updated_at DATETIME")

        _add_column_if_missing("announcements", "content", "content TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("announcements", "status", "status VARCHAR(16) DEFAULT 'draft' NOT NULL")
        _add_column_if_missing("announcements", "is_pinned", "is_pinned BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("announcements", "sort_order", "sort_order INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("announcements", "published_at", "published_at DATETIME")
        _add_column_if_missing("announcements", "offline_at", "offline_at DATETIME")
        _add_column_if_missing("announcements", "created_by", "created_by INTEGER")
        _add_column_if_missing("announcements", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("announcements", "created_at", "created_at DATETIME")
        _add_column_if_missing("announcements", "updated_at", "updated_at DATETIME")

        _add_column_if_missing("homepage_sections", "title", "title VARCHAR(160) DEFAULT '' NOT NULL")
        _add_column_if_missing("homepage_sections", "subtitle", "subtitle VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("homepage_sections", "payload_json", "payload_json TEXT DEFAULT '{}' NOT NULL")
        _add_column_if_missing("homepage_sections", "is_enabled", "is_enabled BOOLEAN DEFAULT 1 NOT NULL")
        _add_column_if_missing("homepage_sections", "sort_order", "sort_order INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("homepage_sections", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("homepage_sections", "created_at", "created_at DATETIME")
        _add_column_if_missing("homepage_sections", "updated_at", "updated_at DATETIME")

        _add_column_if_missing("event_registrations", "student_id", "student_id VARCHAR(32) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "contact", "contact VARCHAR(128) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "notes", "notes TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "status", "status VARCHAR(16) DEFAULT 'pending' NOT NULL")
        _add_column_if_missing("event_registrations", "review_note", "review_note VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "reviewed_by", "reviewed_by INTEGER")
        _add_column_if_missing("event_registrations", "reviewed_at", "reviewed_at DATETIME")
        _add_column_if_missing("event_registrations", "source_ip", "source_ip VARCHAR(64) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "user_agent", "user_agent VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "created_at", "created_at DATETIME")
        _add_column_if_missing("event_registrations", "updated_at", "updated_at DATETIME")
        _add_column_if_missing("activity_route_options", "activity_time", "activity_time DATETIME")
        _add_column_if_missing("activity_route_options", "participant_count", "participant_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("media_assets", "activity_route_option_id", "activity_route_option_id INTEGER")
    else:
        _add_column_if_missing("routes", "updated_at", "updated_at TIMESTAMP")
        _add_column_if_missing("routes", "uploaded_at", "uploaded_at TIMESTAMP")
        _add_column_if_missing("routes", "distance_km", "distance_km DOUBLE PRECISION DEFAULT 0")
        _add_column_if_missing("routes", "difficulty", "difficulty VARCHAR(16) DEFAULT 'medium' NOT NULL")
        _add_column_if_missing("routes", "category", "category VARCHAR(64) DEFAULT 'hiking' NOT NULL")
        _add_column_if_missing("routes", "description", "description TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "status", "status VARCHAR(16) DEFAULT 'published' NOT NULL")
        _add_column_if_missing("routes", "download_count", "download_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("routes", "last_downloaded_at", "last_downloaded_at TIMESTAMP")
        _add_column_if_missing("routes", "suggested_duration_hours", "suggested_duration_hours DOUBLE PRECISION DEFAULT 0 NOT NULL")
        _add_column_if_missing("routes", "supply_points", "supply_points TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "risk_warning", "risk_warning TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("routes", "is_deleted", "is_deleted BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("routes", "deleted_at", "deleted_at TIMESTAMP")
        _add_column_if_missing("routes", "deleted_by", "deleted_by INTEGER")
        _add_column_if_missing("routes", "created_by", "created_by INTEGER")
        _add_column_if_missing("routes", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("users", "perm_view_analytics", "perm_view_analytics BOOLEAN DEFAULT TRUE NOT NULL")
        _add_column_if_missing("users", "perm_view_security", "perm_view_security BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("users", "perm_review", "perm_review BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("users", "perm_edit_content", "perm_edit_content BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("users", "perm_manage_users", "perm_manage_users BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("users", "perm_view_audit_logs", "perm_view_audit_logs BOOLEAN DEFAULT FALSE NOT NULL")

        _add_column_if_missing("site_pages", "summary", "summary VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("site_pages", "content", "content TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("site_pages", "status", "status VARCHAR(16) DEFAULT 'draft' NOT NULL")
        _add_column_if_missing("site_pages", "published_at", "published_at TIMESTAMP")
        _add_column_if_missing("site_pages", "created_by", "created_by INTEGER")
        _add_column_if_missing("site_pages", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("site_pages", "created_at", "created_at TIMESTAMP")
        _add_column_if_missing("site_pages", "updated_at", "updated_at TIMESTAMP")

        _add_column_if_missing("announcements", "content", "content TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("announcements", "status", "status VARCHAR(16) DEFAULT 'draft' NOT NULL")
        _add_column_if_missing("announcements", "is_pinned", "is_pinned BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("announcements", "sort_order", "sort_order INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("announcements", "published_at", "published_at TIMESTAMP")
        _add_column_if_missing("announcements", "offline_at", "offline_at TIMESTAMP")
        _add_column_if_missing("announcements", "created_by", "created_by INTEGER")
        _add_column_if_missing("announcements", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("announcements", "created_at", "created_at TIMESTAMP")
        _add_column_if_missing("announcements", "updated_at", "updated_at TIMESTAMP")

        _add_column_if_missing("homepage_sections", "title", "title VARCHAR(160) DEFAULT '' NOT NULL")
        _add_column_if_missing("homepage_sections", "subtitle", "subtitle VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("homepage_sections", "payload_json", "payload_json TEXT DEFAULT '{}' NOT NULL")
        _add_column_if_missing("homepage_sections", "is_enabled", "is_enabled BOOLEAN DEFAULT TRUE NOT NULL")
        _add_column_if_missing("homepage_sections", "sort_order", "sort_order INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("homepage_sections", "updated_by", "updated_by INTEGER")
        _add_column_if_missing("homepage_sections", "created_at", "created_at TIMESTAMP")
        _add_column_if_missing("homepage_sections", "updated_at", "updated_at TIMESTAMP")

        _add_column_if_missing("event_registrations", "student_id", "student_id VARCHAR(32) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "contact", "contact VARCHAR(128) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "notes", "notes TEXT DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "status", "status VARCHAR(16) DEFAULT 'pending' NOT NULL")
        _add_column_if_missing("event_registrations", "review_note", "review_note VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "reviewed_by", "reviewed_by INTEGER")
        _add_column_if_missing("event_registrations", "reviewed_at", "reviewed_at TIMESTAMP")
        _add_column_if_missing("event_registrations", "source_ip", "source_ip VARCHAR(64) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "user_agent", "user_agent VARCHAR(255) DEFAULT '' NOT NULL")
        _add_column_if_missing("event_registrations", "created_at", "created_at TIMESTAMP")
        _add_column_if_missing("event_registrations", "updated_at", "updated_at TIMESTAMP")
        _add_column_if_missing("activity_route_options", "activity_time", "activity_time TIMESTAMP")
        _add_column_if_missing("activity_route_options", "participant_count", "participant_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing("media_assets", "activity_route_option_id", "activity_route_option_id INTEGER")

    with db.engine.begin() as conn:
        conn.execute(text("UPDATE routes SET uploaded_at = created_at WHERE uploaded_at IS NULL"))
        conn.execute(text("UPDATE routes SET updated_at = created_at WHERE updated_at IS NULL"))
        conn.execute(text("UPDATE routes SET distance_km = 0 WHERE distance_km IS NULL"))
        conn.execute(text("UPDATE routes SET difficulty = 'medium' WHERE difficulty IS NULL OR difficulty = ''"))
        conn.execute(text("UPDATE routes SET category = 'hiking' WHERE category IS NULL OR category = ''"))
        conn.execute(text("UPDATE routes SET description = '' WHERE description IS NULL"))
        conn.execute(text("UPDATE routes SET status = 'published' WHERE status IS NULL OR status = ''"))
        conn.execute(text("UPDATE routes SET download_count = 0 WHERE download_count IS NULL"))
        conn.execute(text("UPDATE routes SET suggested_duration_hours = 0 WHERE suggested_duration_hours IS NULL"))
        conn.execute(text("UPDATE routes SET supply_points = '' WHERE supply_points IS NULL"))
        conn.execute(text("UPDATE routes SET risk_warning = '' WHERE risk_warning IS NULL"))
        true_literal = "1" if is_sqlite else "TRUE"
        false_literal = "0" if is_sqlite else "FALSE"
        conn.execute(text(f"UPDATE routes SET is_active = {true_literal} WHERE status = 'published' AND is_deleted = {false_literal}"))
        conn.execute(text(f"UPDATE routes SET is_active = {false_literal} WHERE status <> 'published' OR is_deleted = {true_literal}"))
        for old_role, new_role in LEGACY_ROLE_MIGRATIONS.items():
            conn.execute(text(f"UPDATE users SET role = '{new_role}' WHERE role = '{old_role}'"))
        conn.execute(
            text(
                f"UPDATE users SET perm_view_analytics = {true_literal} "
                "WHERE role IN ('super_admin', 'ops_admin', 'content_admin')"
            )
        )
        conn.execute(
            text(
                f"UPDATE users SET perm_view_security = {true_literal} "
                "WHERE role IN ('super_admin', 'ops_admin')"
            )
        )
        conn.execute(
            text(
                f"UPDATE users SET perm_review = {true_literal} "
                "WHERE role IN ('super_admin', 'ops_admin', 'content_admin')"
            )
        )
        conn.execute(
            text(
                f"UPDATE users SET perm_edit_content = {true_literal} "
                "WHERE role IN ('super_admin', 'content_admin')"
            )
        )
        conn.execute(text(f"UPDATE users SET perm_manage_users = {true_literal} WHERE role = 'super_admin'"))
        conn.execute(
            text(
                f"UPDATE users SET perm_view_audit_logs = {true_literal} "
                "WHERE role IN ('super_admin', 'ops_admin')"
            )
        )
        conn.execute(text("UPDATE site_pages SET summary = '' WHERE summary IS NULL"))
        conn.execute(text("UPDATE site_pages SET content = '' WHERE content IS NULL"))
        conn.execute(text("UPDATE site_pages SET status = 'draft' WHERE status IS NULL OR status = ''"))
        conn.execute(text("UPDATE site_pages SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        conn.execute(text("UPDATE site_pages SET updated_at = created_at WHERE updated_at IS NULL"))

        conn.execute(text("UPDATE announcements SET content = '' WHERE content IS NULL"))
        conn.execute(text("UPDATE announcements SET status = 'draft' WHERE status IS NULL OR status = ''"))
        conn.execute(text(f"UPDATE announcements SET is_pinned = {false_literal} WHERE is_pinned IS NULL"))
        conn.execute(text("UPDATE announcements SET sort_order = 0 WHERE sort_order IS NULL"))
        conn.execute(text("UPDATE announcements SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        conn.execute(text("UPDATE announcements SET updated_at = created_at WHERE updated_at IS NULL"))

        conn.execute(text("UPDATE homepage_sections SET title = '' WHERE title IS NULL"))
        conn.execute(text("UPDATE homepage_sections SET subtitle = '' WHERE subtitle IS NULL"))
        conn.execute(text("UPDATE homepage_sections SET payload_json = '{}' WHERE payload_json IS NULL OR payload_json = ''"))
        conn.execute(text(f"UPDATE homepage_sections SET is_enabled = {true_literal} WHERE is_enabled IS NULL"))
        conn.execute(text("UPDATE homepage_sections SET sort_order = 0 WHERE sort_order IS NULL"))
        conn.execute(text("UPDATE homepage_sections SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        conn.execute(text("UPDATE homepage_sections SET updated_at = created_at WHERE updated_at IS NULL"))

        conn.execute(text("UPDATE event_registrations SET student_id = '' WHERE student_id IS NULL"))
        conn.execute(text("UPDATE event_registrations SET contact = '' WHERE contact IS NULL"))
        conn.execute(text("UPDATE event_registrations SET notes = '' WHERE notes IS NULL"))
        conn.execute(text("UPDATE event_registrations SET status = 'pending' WHERE status IS NULL OR status = ''"))
        conn.execute(text("UPDATE event_registrations SET review_note = '' WHERE review_note IS NULL"))
        conn.execute(text("UPDATE event_registrations SET source_ip = '' WHERE source_ip IS NULL"))
        conn.execute(text("UPDATE event_registrations SET user_agent = '' WHERE user_agent IS NULL"))
        conn.execute(text("UPDATE event_registrations SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        conn.execute(text("UPDATE event_registrations SET updated_at = created_at WHERE updated_at IS NULL"))
        conn.execute(text("UPDATE activity_route_options SET participant_count = 0 WHERE participant_count IS NULL"))


def ensure_default_admin(username: str, password: str) -> None:
    if not username or not password:
        return

    user = User.query.filter_by(username=username).first()
    if user:
        if user.role != ROLE_SUPER_ADMIN:
            user.role = ROLE_SUPER_ADMIN
            db.session.commit()
        return

    user = User(
        username=username,
        password=generate_password_hash(password),
        role=ROLE_SUPER_ADMIN,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()


def write_audit_log(
    actor_id: int | None,
    action: str,
    target_type: str,
    target_id: str | None,
    detail: str = "",
) -> None:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.session.add(log)
    db.session.commit()


def write_field_audit_log(
    actor_id: int | None,
    target_type: str,
    target_id: str | None,
    before: dict,
    after: dict,
) -> None:
    changed = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        if before_value != after_value:
            changed[key] = {"before": before_value, "after": after_value}
    if not changed:
        return

    write_audit_log(
        actor_id=actor_id,
        action="field.update",
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(changed, ensure_ascii=False),
    )


def route_snapshot(route: Route) -> dict:
    return {
        "route_name": route.route_name,
        "gpx_filename": route.gpx_filename,
        "distance_km": route.distance_km,
        "difficulty": route.difficulty,
        "category": route.category,
        "description": route.description,
        "status": route.status,
        "suggested_duration_hours": route.suggested_duration_hours,
        "supply_points": route.supply_points,
        "risk_warning": route.risk_warning,
        "is_deleted": route.is_deleted,
    }


def create_route_version(route: Route, changed_by: int | None, change_note: str = "") -> RouteVersion:
    latest = (
        RouteVersion.query.filter_by(route_id=route.id)
        .order_by(RouteVersion.version_no.desc())
        .first()
    )
    version_no = 1 if not latest else latest.version_no + 1
    version = RouteVersion(
        route_id=route.id,
        version_no=version_no,
        snapshot_json=json.dumps(route_snapshot(route), ensure_ascii=False),
        change_note=change_note,
        changed_by=changed_by,
    )
    db.session.add(version)
    return version


def rollback_route_to_version(route: Route, version: RouteVersion, actor_id: int | None) -> None:
    payload = json.loads(version.snapshot_json)
    target_gpx_filename = payload.get("gpx_filename", route.gpx_filename)
    target_gpx_path = Path(current_app.config["UPLOAD_FOLDER"]) / target_gpx_filename
    if not target_gpx_path.exists():
        raise ValueError(f"gpx_not_found:{target_gpx_filename}")

    before = route_snapshot(route)

    route.route_name = payload.get("route_name", route.route_name)
    route.gpx_filename = target_gpx_filename
    route.distance_km = payload.get("distance_km", route.distance_km)
    route.difficulty = payload.get("difficulty", route.difficulty)
    route.category = payload.get("category", route.category)
    route.description = payload.get("description", route.description)
    route.status = payload.get("status", route.status)
    route.suggested_duration_hours = payload.get("suggested_duration_hours", route.suggested_duration_hours)
    route.supply_points = payload.get("supply_points", route.supply_points)
    route.risk_warning = payload.get("risk_warning", route.risk_warning)
    route.is_deleted = payload.get("is_deleted", route.is_deleted)
    route.updated_by = actor_id
    route.updated_at = utcnow()
    route.is_active = route.status == STATUS_PUBLISHED and not route.is_deleted

    create_route_version(route, actor_id, change_note=f"rollback_to_v{version.version_no}")
    write_field_audit_log(actor_id, "route", str(route.id), before, route_snapshot(route))


def save_import_report(created_by: int | None, rows: list[dict], success_count: int, failed_count: int) -> ImportReport:
    report_dir = Path(current_app.instance_path) / "import_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    token = secrets.token_hex(16)
    filename = f"import_report_{token}.csv"
    full_path = report_dir / filename

    with full_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["row", "route_name", "gpx_filename", "status", "reason"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    report = ImportReport(
        report_token=token,
        report_filename=filename,
        success_count=success_count,
        failed_count=failed_count,
        created_by=created_by,
    )
    db.session.add(report)
    db.session.commit()
    return report


def approved_rating_summary(route_id: int) -> tuple[float, int]:
    rows = RouteFeedback.query.filter_by(route_id=route_id, status=FEEDBACK_APPROVED).all()
    if not rows:
        return 0.0, 0
    total = sum(item.rating for item in rows)
    count = len(rows)
    return round(total / count, 2), count


def ensure_seed_data(app) -> None:
    existing = Route.query.count()
    if existing >= 10:
        return

    upload_path = Path(app.config["UPLOAD_FOLDER"])
    now = utcnow()

    for idx in range(1, 11):
        filename = f"route_{idx:02d}.gpx"
        gpx_file = upload_path / filename
        if not gpx_file.exists():
            gpx_file.write_text(_build_sample_gpx(idx), encoding="utf-8")

        has_route = Route.query.filter_by(gpx_filename=filename).first()
        if has_route:
            continue

        route = Route(
            route_name=f"Campus Route {idx:02d}",
            gpx_filename=filename,
            created_at=now - timedelta(days=idx),
            updated_at=now - timedelta(days=idx),
            uploaded_at=now - timedelta(days=idx),
            distance_km=3.0 + (idx * 0.5),
            is_active=True,
            difficulty=("easy" if idx <= 3 else "medium" if idx <= 7 else "hard"),
            category=("run" if idx % 2 == 0 else "hiking"),
            description=f"Seed route {idx:02d}",
            status=STATUS_PUBLISHED,
            download_count=0,
            suggested_duration_hours=1.0 + (idx * 0.1),
            supply_points="campus store",
            risk_warning="slippery in rain",
        )
        db.session.add(route)

    if not Activity.query.first():
        db.session.add(
            Activity(
                title="V3 内测活动样例",
                activity_time=now - timedelta(days=2),
                participant_count=18,
                weather="cloudy",
                summary="用于演示活动与路线关联",
            )
        )

    db.session.commit()


def _build_sample_gpx(idx: int) -> str:
    lat = 22.30 + (idx * 0.001)
    lon = 114.17 + (idx * 0.001)
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<gpx version=\"1.1\" creator=\"web-project-v3\">
  <trk>
    <name>Sample Route {idx:02d}</name>
    <trkseg>
      <trkpt lat=\"{lat:.6f}\" lon=\"{lon:.6f}\"></trkpt>
      <trkpt lat=\"{lat + 0.001:.6f}\" lon=\"{lon + 0.001:.6f}\"></trkpt>
    </trkseg>
  </trk>
</gpx>
"""
