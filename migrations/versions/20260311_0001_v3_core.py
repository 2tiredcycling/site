"""V3 core schema

Revision ID: 20260311_0001
Revises:
Create Date: 2026-03-11 17:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260311_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("activity_time", sa.DateTime(), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("weather", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title"),
    )

    op.create_table(
        "activity_routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "route_id", name="uq_activity_route"),
    )

    op.create_table(
        "route_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("road_condition_update", sa.Text(), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "route_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("route_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "import_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_token", sa.String(length=64), nullable=False),
        sa.Column("report_filename", sa.String(length=255), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_token"),
    )

    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("suggested_duration_hours", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("supply_points", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("risk_warning", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))

    op.create_index("idx_activities_activity_time", "activities", ["activity_time"])
    op.create_index("idx_feedback_route_status", "route_feedback", ["route_id", "status"])
    op.create_index("idx_feedback_created_at", "route_feedback", ["created_at"])
    op.create_index("idx_route_versions_route_version", "route_versions", ["route_id", "version_no"])
    op.create_index("idx_routes_status_deleted", "routes", ["status", "is_deleted"])
    op.create_index("idx_routes_updated_at", "routes", ["updated_at"])
    op.create_index("idx_routes_download_count", "routes", ["download_count"])


def downgrade() -> None:
    op.drop_index("idx_routes_download_count", table_name="routes")
    op.drop_index("idx_routes_updated_at", table_name="routes")
    op.drop_index("idx_routes_status_deleted", table_name="routes")
    op.drop_index("idx_route_versions_route_version", table_name="route_versions")
    op.drop_index("idx_feedback_created_at", table_name="route_feedback")
    op.drop_index("idx_feedback_route_status", table_name="route_feedback")
    op.drop_index("idx_activities_activity_time", table_name="activities")

    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_column("deleted_by")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("is_deleted")
        batch_op.drop_column("risk_warning")
        batch_op.drop_column("supply_points")
        batch_op.drop_column("suggested_duration_hours")
        batch_op.drop_column("updated_at")

    op.drop_table("import_reports")
    op.drop_table("media_assets")
    op.drop_table("route_versions")
    op.drop_table("route_feedback")
    op.drop_table("activity_routes")
    op.drop_table("activities")
