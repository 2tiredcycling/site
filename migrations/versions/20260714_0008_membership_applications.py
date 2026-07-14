"""add membership applications table

Revision ID: 20260714_0008
Revises: 20260713_0007
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "membership_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=True),
        sa.Column("student_id", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=64), nullable=False),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("entry_year", sa.Integer(), nullable=True),
        sa.Column("school", sa.String(length=128), nullable=True),
        sa.Column("college", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("competition_interest", sa.String(length=16), nullable=False),
        sa.Column("cycling_experience", sa.String(length=32), nullable=False),
        sa.Column("bicycle_status", sa.String(length=32), nullable=False),
        sa.Column("other_bicycle_description", sa.String(length=255), nullable=True),
        sa.Column("additional_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("form_version", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("approved_profile_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_profile_id"], ["member_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["member_user_id"], ["member_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_membership_applications_student_id",
        "membership_applications",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "idx_membership_applications_member_user_id",
        "membership_applications",
        ["member_user_id"],
        unique=False,
    )
    op.create_index(
        "idx_membership_applications_status_submitted_at",
        "membership_applications",
        ["status", "submitted_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_membership_applications_status_submitted_at", table_name="membership_applications")
    op.drop_index("idx_membership_applications_member_user_id", table_name="membership_applications")
    op.drop_index("idx_membership_applications_student_id", table_name="membership_applications")
    op.drop_table("membership_applications")
