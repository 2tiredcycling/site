import csv
import json
import re
import secrets
from datetime import timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from app.models import (
    FEEDBACK_APPROVED,
    LEGACY_ROLE_MIGRATIONS,
    PAGE_ACCOUNTS,
    PAGE_ACTIVITIES,
    PAGE_ANALYTICS,
    PAGE_ANNOUNCEMENTS,
    PAGE_AUDIT_LOGS,
    PAGE_FEEDBACK,
    PAGE_KEYS,
    PAGE_KIT_PREORDERS,
    PAGE_ROUTES,
    PAGE_SECURITY,
    PERMISSION_ADMIN,
    PERMISSION_NONE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    ROLE_PAGE_PERMISSION_PRESETS,
    ROLE_SUPER_ADMIN,
    STATUS_PUBLISHED,
    Activity,
    AuditLog,
    ImportReport,
    MemberProfile,
    MemberUser,
    MembershipApplication,
    SiteSetting,
    Route,
    RouteFeedback,
    RouteVersion,
    User,
    UserPagePermission,
    db,
    utcnow,
)
from app.member_profile_options import normalize_college, normalize_gender, normalize_school, parse_entry_year
from app.membership_application_options import (
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_PENDING,
    APPLICATION_STATUS_REJECTED,
    BICYCLE_STATUS_OTHER_BICYCLE,
    BICYCLE_STATUS_VALUES,
    COMPETITION_INTEREST_VALUES,
    CURRENT_MEMBERSHIP_APPLICATION_FORM_VERSION,
    CYCLING_EXPERIENCE_VALUES,
)

MEMBERSHIP_APPLICATION_MEMBER_EXISTS_MESSAGE = "该学号已经存在正式社员档案，无需重复申请。如资料有误，请联系管理人员。"
MEMBERSHIP_APPLICATION_PENDING_MESSAGE = "你已有一份待审核的入社申请，请勿重复提交。"
MEMBERSHIP_APPLICATION_SUBMIT_ACTION = "membership_application.submit"
MEMBERSHIP_APPLICATION_ENABLED_SETTING_KEY = "membership_application_enabled"
MEMBERSHIP_APPLICATION_ENABLED_DEFAULT = True


class MembershipApplicationFormError(Exception):
    def __init__(self, errors: dict[str, str], values: dict[str, object]):
        super().__init__("membership application form validation failed")
        self.errors = errors
        self.values = values


class MembershipApplicationBlocked(Exception):
    def __init__(self, message: str, values: dict[str, object]):
        super().__init__(message)
        self.message = message
        self.values = values


class MembershipApplicationReviewError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _coerce_bool(value: str | bool | int | None, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "y", "enabled", "open"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled", "close", "closed", "n"}:
        return False
    return default


def is_membership_application_enabled(default: bool = MEMBERSHIP_APPLICATION_ENABLED_DEFAULT) -> bool:
    try:
        setting = SiteSetting.query.filter_by(key=MEMBERSHIP_APPLICATION_ENABLED_SETTING_KEY).first()
    except Exception:
        return default
    if not setting:
        return default
    return _coerce_bool(setting.value, default=default)


def set_membership_application_enabled(enabled: bool, actor_user_id: int | None = None) -> bool:
    normalized = "1" if bool(enabled) else "0"
    setting = SiteSetting.query.filter_by(key=MEMBERSHIP_APPLICATION_ENABLED_SETTING_KEY).first()
    if setting is None:
        setting = SiteSetting(
            key=MEMBERSHIP_APPLICATION_ENABLED_SETTING_KEY,
            value=normalized,
            description="是否开放入社申请入口",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.session.add(setting)
        db.session.flush()
        return bool(enabled)

    if setting.value == normalized:
        return bool(enabled)
    setting.value = normalized
    setting.updated_at = utcnow()
    return bool(enabled)


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


def _rebuild_sqlite_legacy_member_users() -> None:
    if not _is_sqlite():
        return
    columns = _table_columns("member_users")
    if "username" not in columns:
        return

    student_expr = "UPPER(username)"
    if "student_id" in columns:
        student_expr = "UPPER(COALESCE(NULLIF(student_id, ''), username))"
    nickname_expr = "username"
    if "nickname" in columns:
        nickname_expr = "COALESCE(NULLIF(nickname, ''), username)"

    with db.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS member_users_legacy_username"))
        conn.execute(text("ALTER TABLE member_users RENAME TO member_users_legacy_username"))
        conn.execute(
            text(
                """
                CREATE TABLE member_users (
                    id INTEGER NOT NULL,
                    student_id VARCHAR(32) NOT NULL,
                    nickname VARCHAR(64) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    account_status VARCHAR(16) DEFAULT 'active' NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_login_at DATETIME,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_member_users_student_id UNIQUE (student_id)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO member_users (
                    id,
                    student_id,
                    nickname,
                    password_hash,
                    account_status,
                    created_at,
                    updated_at,
                    last_login_at
                )
                SELECT
                    id,
                    {student_expr},
                    {nickname_expr},
                    password_hash,
                    COALESCE(NULLIF(account_status, ''), 'active'),
                    COALESCE(created_at, CURRENT_TIMESTAMP),
                    COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                    last_login_at
                FROM member_users_legacy_username
                """
            )
        )
        conn.execute(text("CREATE INDEX idx_member_users_student_id ON member_users (student_id)"))
        conn.execute(text("CREATE INDEX idx_member_users_account_status ON member_users (account_status)"))
        conn.execute(text("DROP TABLE member_users_legacy_username"))


def _legacy_page_permissions_for_user(user: User) -> dict[str, str]:
    preset = ROLE_PAGE_PERMISSION_PRESETS.get(user.role)
    if preset:
        return dict(preset)

    result = {page_key: PERMISSION_NONE for page_key in PAGE_KEYS}
    if bool(user.perm_edit_content):
        for page_key in (PAGE_ROUTES, PAGE_ACTIVITIES, PAGE_KIT_PREORDERS, PAGE_ANNOUNCEMENTS):
            result[page_key] = PERMISSION_WRITE
    if bool(user.perm_review):
        result[PAGE_FEEDBACK] = PERMISSION_WRITE
    if bool(user.perm_view_analytics):
        result[PAGE_ANALYTICS] = PERMISSION_READ
    if bool(user.perm_view_security):
        result[PAGE_SECURITY] = PERMISSION_READ
    if bool(user.perm_manage_users):
        result[PAGE_ACCOUNTS] = PERMISSION_ADMIN
    if bool(user.perm_view_audit_logs):
        result[PAGE_AUDIT_LOGS] = PERMISSION_READ
    return result


def ensure_user_page_permissions(user: User, overwrite: bool = False) -> None:
    existing = {item.page_key: item for item in user.page_permissions}
    desired = _legacy_page_permissions_for_user(user)
    changed = False
    for page_key in PAGE_KEYS:
        level = desired.get(page_key, PERMISSION_NONE)
        record = existing.get(page_key)
        if record is None:
            db.session.add(
                UserPagePermission(
                    user=user,
                    page_key=page_key,
                    permission_level=level,
                )
            )
            changed = True
        elif overwrite and record.permission_level != level:
            record.permission_level = level
            changed = True
    if changed:
        db.session.flush()


def ensure_all_user_page_permissions() -> None:
    for user in User.query.all():
        ensure_user_page_permissions(user)
    db.session.commit()


def ensure_schema_compat() -> None:
    db.create_all()
    is_sqlite = _is_sqlite()
    _rebuild_sqlite_legacy_member_users()

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
        _add_column_if_missing("routes", "ascent_m", "ascent_m FLOAT")
        _add_column_if_missing("routes", "descent_m", "descent_m FLOAT")
        _add_column_if_missing("routes", "min_ele_m", "min_ele_m FLOAT")
        _add_column_if_missing("routes", "max_ele_m", "max_ele_m FLOAT")
        _add_column_if_missing("routes", "manual_stat_overrides", "manual_stat_overrides TEXT DEFAULT '{}' NOT NULL")
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
        _add_column_if_missing("activities", "needs_registration", "needs_registration BOOLEAN DEFAULT 0 NOT NULL")
        _add_column_if_missing("activities", "registration_deadline", "registration_deadline DATETIME")
        _add_column_if_missing("activities", "registration_limit", "registration_limit INTEGER")
        _add_column_if_missing("activities", "insurance_qr_path", "insurance_qr_path TEXT")
        _add_column_if_missing("media_assets", "activity_route_option_id", "activity_route_option_id INTEGER")
        _add_column_if_missing("member_users", "student_id", "student_id VARCHAR(32) DEFAULT '' NOT NULL")
        _add_column_if_missing("member_users", "nickname", "nickname VARCHAR(64) DEFAULT '' NOT NULL")
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
        _add_column_if_missing("routes", "ascent_m", "ascent_m DOUBLE PRECISION")
        _add_column_if_missing("routes", "descent_m", "descent_m DOUBLE PRECISION")
        _add_column_if_missing("routes", "min_ele_m", "min_ele_m DOUBLE PRECISION")
        _add_column_if_missing("routes", "max_ele_m", "max_ele_m DOUBLE PRECISION")
        _add_column_if_missing("routes", "manual_stat_overrides", "manual_stat_overrides TEXT DEFAULT '{}' NOT NULL")
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
        _add_column_if_missing("activities", "needs_registration", "needs_registration BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing("activities", "registration_deadline", "registration_deadline TIMESTAMP")
        _add_column_if_missing("activities", "registration_limit", "registration_limit INTEGER")
        _add_column_if_missing("activities", "insurance_qr_path", "insurance_qr_path TEXT")
        _add_column_if_missing("media_assets", "activity_route_option_id", "activity_route_option_id INTEGER")
        _add_column_if_missing("member_users", "student_id", "student_id VARCHAR(32) DEFAULT '' NOT NULL")
        _add_column_if_missing("member_users", "nickname", "nickname VARCHAR(64) DEFAULT '' NOT NULL")

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
        conn.execute(text(f"UPDATE activities SET needs_registration = {false_literal} WHERE needs_registration IS NULL"))
        member_columns = _table_columns("member_users")
        if "student_id" in member_columns:
            if "username" in member_columns:
                conn.execute(text("UPDATE member_users SET student_id = UPPER(username) WHERE student_id IS NULL OR student_id = ''"))
                conn.execute(text("UPDATE member_users SET nickname = username WHERE nickname IS NULL OR nickname = ''"))
            conn.execute(text("UPDATE member_users SET student_id = UPPER(student_id) WHERE student_id IS NOT NULL"))
        if "nickname" in member_columns:
            conn.execute(text("UPDATE member_users SET nickname = student_id WHERE nickname IS NULL OR nickname = ''"))

    db.session.expire_all()
    ensure_all_user_page_permissions()


def ensure_default_admin(username: str, password: str) -> None:
    if not username or not password:
        return

    user = User.query.filter_by(username=username).first()
    if user:
        if user.role != ROLE_SUPER_ADMIN:
            user.role = ROLE_SUPER_ADMIN
            ensure_user_page_permissions(user, overwrite=True)
            db.session.commit()
        else:
            ensure_user_page_permissions(user)
            db.session.commit()
        return

    user = User(
        username=username,
        password=generate_password_hash(password),
        role=ROLE_SUPER_ADMIN,
        is_active=True,
    )
    db.session.add(user)
    ensure_user_page_permissions(user)
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


def add_audit_log(
    actor_id: int | None,
    action: str,
    target_type: str,
    target_id: str | None,
    detail: str = "",
) -> AuditLog:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.session.add(log)
    return log


def _clean_membership_application_text(value: object, *, max_length: int | None = None) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if max_length is not None and len(cleaned) > max_length:
        return cleaned[:max_length]
    return cleaned


def membership_application_initial_values(member_user: MemberUser | None = None) -> dict[str, object]:
    return {
        "student_id": (member_user.student_id if member_user else "") or "",
        "full_name": "",
        "gender": "",
        "entry_year": "",
        "school": "",
        "college": "",
        "phone": "",
        "competition_interest": "",
        "cycling_experience": "",
        "bicycle_status": "",
        "other_bicycle_description": "",
        "additional_note": "",
        "confirm_info": "",
    }


def _normalized_application_student_id(form_data, member_user: MemberUser | None) -> str:
    if member_user is not None:
        return _clean_membership_application_text(member_user.student_id).upper()
    return _clean_membership_application_text(form_data.get("student_id")).upper()


def normalize_membership_application_form(form_data, member_user: MemberUser | None = None) -> dict[str, object]:
    values = membership_application_initial_values(member_user)
    values.update(
        {
            "student_id": _normalized_application_student_id(form_data, member_user),
            "full_name": _clean_membership_application_text(form_data.get("full_name")),
            "gender": _clean_membership_application_text(form_data.get("gender")),
            "entry_year": _clean_membership_application_text(form_data.get("entry_year")),
            "school": _clean_membership_application_text(form_data.get("school")),
            "college": _clean_membership_application_text(form_data.get("college")),
            "phone": _clean_membership_application_text(form_data.get("phone")),
            "competition_interest": _clean_membership_application_text(form_data.get("competition_interest")),
            "cycling_experience": _clean_membership_application_text(form_data.get("cycling_experience")),
            "bicycle_status": _clean_membership_application_text(form_data.get("bicycle_status")),
            "other_bicycle_description": _clean_membership_application_text(form_data.get("other_bicycle_description")),
            "additional_note": str(form_data.get("additional_note") or "").strip(),
            "confirm_info": _clean_membership_application_text(form_data.get("confirm_info")),
        }
    )
    return values


def validate_membership_application_form(form_data, member_user: MemberUser | None = None) -> dict[str, object]:
    values = normalize_membership_application_form(form_data, member_user)
    errors: dict[str, str] = {}

    if not values["student_id"]:
        errors["student_id"] = "请填写学号。"
    elif len(str(values["student_id"])) > 32:
        errors["student_id"] = "学号长度不能超过 32 个字符。"

    if not values["full_name"]:
        errors["full_name"] = "请填写真实姓名。"
    elif len(str(values["full_name"])) > 64:
        errors["full_name"] = "真实姓名长度不能超过 64 个字符。"

    gender, gender_error = normalize_gender(values["gender"])
    if gender_error:
        errors["gender"] = gender_error
    values["gender"] = gender

    entry_year, entry_year_error = parse_entry_year(values["entry_year"])
    if entry_year_error:
        errors["entry_year"] = entry_year_error
    elif entry_year is None:
        errors["entry_year"] = "请选择入学年份。"
    elif entry_year < 1900 or entry_year > 2100:
        errors["entry_year"] = "入学年份格式不正确。"
    values["entry_year"] = entry_year

    school, school_error = normalize_school(values["school"])
    if school_error:
        errors["school"] = school_error
    values["school"] = school

    college, college_error = normalize_college(values["college"])
    if college_error:
        errors["college"] = college_error
    values["college"] = college

    phone = str(values["phone"])
    if not phone:
        errors["phone"] = "请填写手机号或常用联系电话。"
    elif len(phone) > 32:
        errors["phone"] = "联系电话长度不能超过 32 个字符。"
    elif not re.fullmatch(r"[0-9+()\-\s]{5,32}", phone):
        errors["phone"] = "联系电话格式不正确。"

    if values["competition_interest"] not in COMPETITION_INTEREST_VALUES:
        errors["competition_interest"] = "请选择参赛意愿。"
    if values["cycling_experience"] not in CYCLING_EXPERIENCE_VALUES:
        errors["cycling_experience"] = "请选择骑行经验。"
    if values["bicycle_status"] not in BICYCLE_STATUS_VALUES:
        errors["bicycle_status"] = "请选择车辆情况。"

    if values["bicycle_status"] == BICYCLE_STATUS_OTHER_BICYCLE:
        other_description = str(values["other_bicycle_description"])
        if not other_description:
            errors["other_bicycle_description"] = "请补充说明自行车类型。"
        elif len(other_description) > 255:
            errors["other_bicycle_description"] = "自行车类型说明不能超过 255 个字符。"
    else:
        values["other_bicycle_description"] = None

    note = str(values["additional_note"]).strip()
    if len(note) > 1000:
        errors["additional_note"] = "补充说明不能超过 1000 个字符。"
    values["additional_note"] = note or None

    if values["confirm_info"] != "1":
        errors["confirm_info"] = "请先确认提交的信息真实有效。"

    if errors:
        raise MembershipApplicationFormError(errors, values)
    return values


def membership_application_block_message(student_id: str | None, member_user: MemberUser | None = None) -> str:
    normalized_student_id = _clean_membership_application_text(student_id).upper()
    if not normalized_student_id:
        return ""

    if member_user is not None and member_user.profile is not None:
        return MEMBERSHIP_APPLICATION_MEMBER_EXISTS_MESSAGE

    profile = MemberProfile.query.filter(db.func.upper(MemberProfile.student_id) == normalized_student_id.upper()).first()
    if profile is not None:
        return MEMBERSHIP_APPLICATION_MEMBER_EXISTS_MESSAGE

    approved_application = MembershipApplication.query.filter(
        db.func.upper(MembershipApplication.student_id) == normalized_student_id.upper(),
        MembershipApplication.status == APPLICATION_STATUS_APPROVED,
    ).first()
    if approved_application is not None:
        return MEMBERSHIP_APPLICATION_MEMBER_EXISTS_MESSAGE

    pending_student_application = MembershipApplication.query.filter(
        db.func.upper(MembershipApplication.student_id) == normalized_student_id.upper(),
        MembershipApplication.status == APPLICATION_STATUS_PENDING,
    ).first()
    if pending_student_application is not None:
        return MEMBERSHIP_APPLICATION_PENDING_MESSAGE

    if member_user is not None:
        pending_member_application = MembershipApplication.query.filter_by(
            member_user_id=member_user.id,
            status=APPLICATION_STATUS_PENDING,
        ).first()
        if pending_member_application is not None:
            return MEMBERSHIP_APPLICATION_PENDING_MESSAGE

    return ""


def create_membership_application(form_data, member_user: MemberUser | None = None) -> MembershipApplication:
    values = validate_membership_application_form(form_data, member_user)
    block_message = membership_application_block_message(str(values["student_id"]), member_user)
    if block_message:
        raise MembershipApplicationBlocked(block_message, values)

    now_value = utcnow()
    application = MembershipApplication(
        member_user_id=member_user.id if member_user is not None else None,
        student_id=str(values["student_id"]),
        full_name=str(values["full_name"]),
        gender=values["gender"],
        entry_year=values["entry_year"],
        school=values["school"],
        college=values["college"],
        phone=str(values["phone"]),
        competition_interest=str(values["competition_interest"]),
        cycling_experience=str(values["cycling_experience"]),
        bicycle_status=str(values["bicycle_status"]),
        other_bicycle_description=values["other_bicycle_description"],
        additional_note=values["additional_note"],
        status=APPLICATION_STATUS_PENDING,
        form_version=CURRENT_MEMBERSHIP_APPLICATION_FORM_VERSION,
        submitted_at=now_value,
        created_at=now_value,
        updated_at=now_value,
    )

    try:
        db.session.add(application)
        db.session.flush()
        detail = {
            "actor_type": "member_user" if member_user is not None else "anonymous",
            "submission_type": "authenticated" if member_user is not None else "public",
            "form_version": CURRENT_MEMBERSHIP_APPLICATION_FORM_VERSION,
        }
        if member_user is not None:
            detail["member_user_id"] = member_user.id
        add_audit_log(
            actor_id=None,
            action=MEMBERSHIP_APPLICATION_SUBMIT_ACTION,
            target_type="membership_application",
            target_id=str(application.id),
            detail=json.dumps(detail, ensure_ascii=False),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return application


def _clean_review_note(value: object) -> str | None:
    cleaned = str(value or "").strip()
    if len(cleaned) > 1000:
        cleaned = cleaned[:1000]
    return cleaned or None


def _membership_application_submitted_date(application: MembershipApplication):
    if application.submitted_at is None:
        return None
    return application.submitted_at.date()


def _find_safe_member_user_for_application(application: MembershipApplication) -> tuple[MemberUser | None, bool]:
    normalized_student_id = _clean_membership_application_text(application.student_id).upper()
    if not normalized_student_id:
        raise MembershipApplicationReviewError("申请学号为空，无法创建社员档案。")

    if application.member_user_id is not None:
        member_user = db.session.get(MemberUser, application.member_user_id)
        if member_user is None:
            raise MembershipApplicationReviewError("申请绑定的社员账号不存在，无法自动绑定。")
        if (member_user.student_id or "").upper() != normalized_student_id:
            raise MembershipApplicationReviewError("申请绑定账号的学号与申请学号不一致，无法同意。")
        if member_user.profile is not None:
            raise MembershipApplicationReviewError("申请绑定账号已经关联其他社员档案，无法同意。")
        return member_user, False

    member_user = MemberUser.query.filter(db.func.upper(MemberUser.student_id) == normalized_student_id).first()
    if member_user is None:
        return None, False
    if member_user.profile is not None:
        raise MembershipApplicationReviewError("同学号社员账号已经关联其他社员档案，无法同意。")
    return member_user, True


def _profile_create_audit_detail(profile: MemberProfile, application: MembershipApplication, actor_user_id: int) -> str:
    detail = {
        "source": "membership_application_approve",
        "actor_type": "admin_user",
        "actor_user_id": actor_user_id,
        "application_id": application.id,
        "student_id": profile.student_id,
        "changes": {
            "student_id": {"before": None, "after": profile.student_id},
            "full_name": {"before": None, "after": profile.full_name},
            "gender": {"before": None, "after": profile.gender},
            "entry_year": {"before": None, "after": profile.entry_year},
            "school": {"before": None, "after": profile.school},
            "college": {"before": None, "after": profile.college},
            "last_confirmed_at": {
                "before": None,
                "after": profile.last_confirmed_at.isoformat() if profile.last_confirmed_at else None,
            },
        },
        "extra": {"phone_provided": bool(profile.phone)},
    }
    return json.dumps(detail, ensure_ascii=False)


def _profile_bind_audit_detail(
    profile: MemberProfile,
    application: MembershipApplication,
    actor_user_id: int,
    member_user_id: int,
    auto_matched: bool,
) -> str:
    detail = {
        "source": "membership_application_approve",
        "actor_type": "admin_user",
        "actor_user_id": actor_user_id,
        "application_id": application.id,
        "student_id": profile.student_id,
        "changes": {
            "member_user_id": {"before": None, "after": member_user_id},
        },
        "extra": {"auto_matched": auto_matched},
    }
    return json.dumps(detail, ensure_ascii=False)


def approve_membership_application(
    application_id: int,
    actor_user_id: int,
    review_note: object = None,
) -> MembershipApplication:
    application = db.session.get(MembershipApplication, application_id)
    if application is None:
        raise MembershipApplicationReviewError("入社申请不存在。")
    if application.status != APPLICATION_STATUS_PENDING:
        raise MembershipApplicationReviewError("该申请已处理。")

    normalized_student_id = _clean_membership_application_text(application.student_id).upper()
    existing_profile = MemberProfile.query.filter(db.func.upper(MemberProfile.student_id) == normalized_student_id).first()
    if existing_profile is not None:
        raise MembershipApplicationReviewError("该学号已经存在社员档案，无法同意并覆盖。")

    try:
        member_user, auto_matched = _find_safe_member_user_for_application(application)
        now_value = utcnow()
        note = _clean_review_note(review_note)
        profile = MemberProfile(
            member_user_id=member_user.id if member_user is not None else None,
            student_id=normalized_student_id,
            full_name=application.full_name,
            gender=application.gender,
            entry_year=application.entry_year,
            school=application.school,
            college=application.college,
            phone=application.phone,
            last_confirmed_at=_membership_application_submitted_date(application),
            created_at=now_value,
            updated_at=now_value,
        )
        db.session.add(profile)
        db.session.flush()

        application.status = APPLICATION_STATUS_APPROVED
        application.reviewed_at = now_value
        application.reviewed_by = actor_user_id
        application.review_note = note
        application.approved_profile_id = profile.id
        application.updated_at = now_value

        add_audit_log(
            actor_id=actor_user_id,
            action="membership_application.approve",
            target_type="membership_application",
            target_id=str(application.id),
            detail=json.dumps(
                {
                    "before_status": APPLICATION_STATUS_PENDING,
                    "after_status": APPLICATION_STATUS_APPROVED,
                    "review_note_present": bool(note),
                    "profile_id": profile.id,
                    "member_user_id": member_user.id if member_user is not None else None,
                    "auto_matched_member_user": auto_matched,
                },
                ensure_ascii=False,
            ),
        )
        add_audit_log(
            actor_id=actor_user_id,
            action="member_profile.create",
            target_type="member_profile",
            target_id=str(profile.id),
            detail=_profile_create_audit_detail(profile, application, actor_user_id),
        )
        if member_user is not None:
            add_audit_log(
                actor_id=actor_user_id,
                action="member_profile.account_bind",
                target_type="member_profile",
                target_id=str(profile.id),
                detail=_profile_bind_audit_detail(profile, application, actor_user_id, member_user.id, auto_matched),
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return application


def reject_membership_application(
    application_id: int,
    actor_user_id: int,
    review_note: object = None,
) -> MembershipApplication:
    application = db.session.get(MembershipApplication, application_id)
    if application is None:
        raise MembershipApplicationReviewError("入社申请不存在。")
    if application.status != APPLICATION_STATUS_PENDING:
        raise MembershipApplicationReviewError("该申请已处理。")

    try:
        now_value = utcnow()
        note = _clean_review_note(review_note)
        application.status = APPLICATION_STATUS_REJECTED
        application.reviewed_at = now_value
        application.reviewed_by = actor_user_id
        application.review_note = note
        application.updated_at = now_value
        add_audit_log(
            actor_id=actor_user_id,
            action="membership_application.reject",
            target_type="membership_application",
            target_id=str(application.id),
            detail=json.dumps(
                {
                    "before_status": APPLICATION_STATUS_PENDING,
                    "after_status": APPLICATION_STATUS_REJECTED,
                    "review_note_present": bool(note),
                    "profile_id": None,
                    "member_user_id": application.member_user_id,
                    "auto_matched_member_user": False,
                },
                ensure_ascii=False,
            ),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return application


def build_field_changes(before: dict, after: dict) -> dict:
    changed = {}
    for key in sorted(set(before) | set(after)):
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value != after_value:
            changed[key] = {"before": before_value, "after": after_value}
    return changed


def write_field_audit_log(
    actor_id: int | None,
    target_type: str,
    target_id: str | None,
    before: dict,
    after: dict,
) -> None:
    changed = build_field_changes(before, after)
    if not changed:
        return

    write_audit_log(
        actor_id=actor_id,
        action="field.update",
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(changed, ensure_ascii=False),
    )


def add_member_profile_audit_log(
    action: str,
    profile: MemberProfile,
    before: dict,
    after: dict,
    *,
    source: str,
    actor_user_id: int | None = None,
    actor_member_user_id: int | None = None,
    extra: dict | None = None,
) -> AuditLog | None:
    changes = build_field_changes(before, after)
    if not changes and not extra:
        return None
    detail = {
        "source": source,
        "actor_type": "admin_user" if actor_user_id is not None else ("member_user" if actor_member_user_id is not None else "system"),
        "actor_user_id": actor_user_id,
        "actor_member_user_id": actor_member_user_id,
        "student_id": profile.student_id,
        "changes": changes,
        "extra": extra or {},
    }
    return add_audit_log(
        actor_id=actor_user_id,
        action=action,
        target_type="member_profile",
        target_id=str(profile.id) if profile.id is not None else None,
        detail=json.dumps(detail, ensure_ascii=False),
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
        "ascent_m": route.ascent_m,
        "descent_m": route.descent_m,
        "min_ele_m": route.min_ele_m,
        "max_ele_m": route.max_ele_m,
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
    route.ascent_m = payload.get("ascent_m", route.ascent_m)
    route.descent_m = payload.get("descent_m", route.descent_m)
    route.min_ele_m = payload.get("min_ele_m", route.min_ele_m)
    route.max_ele_m = payload.get("max_ele_m", route.max_ele_m)
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
