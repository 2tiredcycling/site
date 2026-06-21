"""Route manual statistic overrides

Revision ID: 20260622_0004
Revises: 20260618_0003
Create Date: 2026-06-22 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260622_0004"
down_revision = "20260618_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(
            sa.Column("manual_stat_overrides", sa.Text(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_column("manual_stat_overrides")
