"""V4.0 content and event registration base tables

Revision ID: 20260319_0002
Revises: 20260311_0001
Create Date: 2026-03-19 16:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0002"
down_revision = "20260311_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_site_pages_slug"),
    )

    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "homepage_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("subtitle", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_key", name="uq_homepage_sections_section_key"),
    )

    op.create_table(
        "event_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("student_id", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("contact", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("review_note", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_site_pages_status_updated_at", "site_pages", ["status", "updated_at"])
    op.create_index(
        "idx_announcements_status_pinned_published",
        "announcements",
        ["status", "is_pinned", "published_at"],
    )
    op.create_index("idx_announcements_updated_at", "announcements", ["updated_at"])
    op.create_index("idx_homepage_sections_enabled_sort", "homepage_sections", ["is_enabled", "sort_order"])
    op.create_index("idx_event_registrations_activity_status", "event_registrations", ["activity_id", "status"])
    op.create_index("idx_event_registrations_created_at", "event_registrations", ["created_at"])
    op.create_index("idx_event_registrations_student_id", "event_registrations", ["student_id"])


def downgrade() -> None:
    op.drop_index("idx_event_registrations_student_id", table_name="event_registrations")
    op.drop_index("idx_event_registrations_created_at", table_name="event_registrations")
    op.drop_index("idx_event_registrations_activity_status", table_name="event_registrations")
    op.drop_index("idx_homepage_sections_enabled_sort", table_name="homepage_sections")
    op.drop_index("idx_announcements_updated_at", table_name="announcements")
    op.drop_index("idx_announcements_status_pinned_published", table_name="announcements")
    op.drop_index("idx_site_pages_status_updated_at", table_name="site_pages")

    op.drop_table("event_registrations")
    op.drop_table("homepage_sections")
    op.drop_table("announcements")
    op.drop_table("site_pages")

