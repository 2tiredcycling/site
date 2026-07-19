"""add management interest fields to membership applications

Revision ID: 20260719_0010
Revises: 20260715_0009
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260719_0010"
down_revision = "20260715_0009"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "membership_applications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("membership_applications")}
    with op.batch_alter_table("membership_applications") as batch_op:
        if "management_position" not in columns:
            batch_op.add_column(sa.Column("management_position", sa.String(length=32), nullable=True))
        if "management_interest_note" not in columns:
            batch_op.add_column(sa.Column("management_interest_note", sa.Text(), nullable=True))
        if "management_interest_submitted_at" not in columns:
            batch_op.add_column(sa.Column("management_interest_submitted_at", sa.DateTime(), nullable=True))


def downgrade():
    inspector = inspect(op.get_bind())
    if "membership_applications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("membership_applications")}
    with op.batch_alter_table("membership_applications") as batch_op:
        if "management_interest_submitted_at" in columns:
            batch_op.drop_column("management_interest_submitted_at")
        if "management_interest_note" in columns:
            batch_op.drop_column("management_interest_note")
        if "management_position" in columns:
            batch_op.drop_column("management_position")
