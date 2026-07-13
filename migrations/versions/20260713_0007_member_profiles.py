"""add member profiles table

Revision ID: 20260713_0007
Revises: 20260713_0006
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "member_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_user_id", sa.Integer(), nullable=True),
        sa.Column("student_id", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=64), nullable=False),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("entry_year", sa.Integer(), nullable=True),
        sa.Column("school", sa.String(length=128), nullable=True),
        sa.Column("college", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("last_confirmed_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["member_user_id"], ["member_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_user_id", name="uq_member_profiles_member_user_id"),
        sa.UniqueConstraint("student_id", name="uq_member_profiles_student_id"),
    )


def downgrade():
    op.drop_table("member_profiles")
