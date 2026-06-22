"""add page permissions table

Revision ID: 20260622_0005
Revises: 20260622_0004
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260622_0005"
down_revision = "20260622_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_page_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("page_key", sa.String(length=64), nullable=False),
        sa.Column("permission_level", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "page_key", name="uq_user_page_permission_user_page"),
    )
    op.create_index("idx_user_page_permissions_user_id", "user_page_permissions", ["user_id"])
    op.create_index("idx_user_page_permissions_page_key", "user_page_permissions", ["page_key"])


def downgrade():
    op.drop_index("idx_user_page_permissions_page_key", table_name="user_page_permissions")
    op.drop_index("idx_user_page_permissions_user_id", table_name="user_page_permissions")
    op.drop_table("user_page_permissions")
