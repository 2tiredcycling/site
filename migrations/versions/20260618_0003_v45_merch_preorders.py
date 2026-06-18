"""V4.5 merch preorder tables

Revision ID: 20260618_0003
Revises: 20260319_0002
Create Date: 2026-06-18 20:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260618_0003"
down_revision = "20260319_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merch_preorder_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="upcoming"),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("price_min", sa.Integer(), nullable=True),
        sa.Column("price_max", sa.Integer(), nullable=True),
        sa.Column("price_note", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("size_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "merch_preorder_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("image_kind", sa.String(length=32), nullable=False, server_default="gallery"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["merch_preorder_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "merch_preorder_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("student_id", sa.String(length=32), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("gender", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("size", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["merch_preorder_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_merch_batches_status_visible", "merch_preorder_batches", ["status", "is_visible"])
    op.create_index("idx_merch_batches_deadline", "merch_preorder_batches", ["deadline_at"])
    op.create_index(
        "idx_merch_images_batch_kind_sort",
        "merch_preorder_images",
        ["batch_id", "image_kind", "sort_order"],
    )
    op.create_index(
        "idx_merch_registrations_batch_status",
        "merch_preorder_registrations",
        ["batch_id", "status"],
    )
    op.create_index("idx_merch_registrations_student_id", "merch_preorder_registrations", ["student_id"])
    op.create_index("idx_merch_registrations_created_at", "merch_preorder_registrations", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_merch_registrations_created_at", table_name="merch_preorder_registrations")
    op.drop_index("idx_merch_registrations_student_id", table_name="merch_preorder_registrations")
    op.drop_index("idx_merch_registrations_batch_status", table_name="merch_preorder_registrations")
    op.drop_index("idx_merch_images_batch_kind_sort", table_name="merch_preorder_images")
    op.drop_index("idx_merch_batches_deadline", table_name="merch_preorder_batches")
    op.drop_index("idx_merch_batches_status_visible", table_name="merch_preorder_batches")
    op.drop_table("merch_preorder_registrations")
    op.drop_table("merch_preorder_images")
    op.drop_table("merch_preorder_batches")
