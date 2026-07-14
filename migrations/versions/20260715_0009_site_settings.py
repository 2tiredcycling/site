"""add site settings table for application switches and other flags

Revision ID: 20260715_0009
Revises: 20260714_0008
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260715_0009"
down_revision = "20260714_0008"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "site_settings" in inspector.get_table_names():
        return
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("idx_site_settings_key", "site_settings", ["key"], unique=False)


def downgrade():
    inspector = inspect(op.get_bind())
    if "site_settings" not in inspector.get_table_names():
        return
    op.drop_index("idx_site_settings_key", table_name="site_settings")
    op.drop_table("site_settings")
