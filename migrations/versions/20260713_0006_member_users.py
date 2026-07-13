"""add member users table

Revision ID: 20260713_0006
Revises: 20260622_0005
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0006"
down_revision = "20260622_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "member_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("account_status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", name="uq_member_users_student_id"),
    )
    op.create_index("idx_member_users_student_id", "member_users", ["student_id"])
    op.create_index("idx_member_users_account_status", "member_users", ["account_status"])


def downgrade():
    op.drop_index("idx_member_users_account_status", table_name="member_users")
    op.drop_index("idx_member_users_student_id", table_name="member_users")
    op.drop_table("member_users")
