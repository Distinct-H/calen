"""Add approval workflow for manual kiss balance additions.

Revision ID: c849ce34a11f
Revises: d34c42c39e6f
Create Date: 2026-10-10 17:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c849ce34a11f"
down_revision: Union[str, None] = "d34c42c39e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kiss_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("amount_centi", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("approved_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kiss_requests_requester_id", "kiss_requests", ["requester_id"])
    op.create_index("ix_kiss_requests_status", "kiss_requests", ["status"])
    op.create_index("ix_kiss_requests_approved_on", "kiss_requests", ["approved_on"])


def downgrade() -> None:
    op.drop_index("ix_kiss_requests_approved_on", table_name="kiss_requests")
    op.drop_index("ix_kiss_requests_status", table_name="kiss_requests")
    op.drop_index("ix_kiss_requests_requester_id", table_name="kiss_requests")
    op.drop_table("kiss_requests")
