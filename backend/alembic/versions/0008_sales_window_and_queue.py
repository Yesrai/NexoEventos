"""Add per-event sales start, optional virtual queue settings and queue entries.

Existing events keep sales_start_at NULL and queue_enabled false: behavior is unchanged.

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("sales_start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("queue_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("events", sa.Column("queue_max_active", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("events", sa.Column("queue_pass_minutes", sa.Integer(), nullable=False, server_default="10"))
    op.create_check_constraint("ck_events_queue_max_active", "events", "queue_max_active BETWEEN 1 AND 1000")
    op.create_check_constraint("ck_events_queue_pass_minutes", "events", "queue_pass_minutes BETWEEN 1 AND 60")
    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('waiting', 'admitted', 'completed', 'expired', 'left')", name="ck_queue_entries_status"),
    )
    op.create_index("ix_queue_entries_event_status_joined", "queue_entries", ["event_id", "status", "joined_at"])
    op.create_index("uq_queue_entries_live_per_user", "queue_entries", ["event_id", "user_id"], unique=True, postgresql_where=sa.text("status IN ('waiting', 'admitted')"))
    op.execute("GRANT SELECT, INSERT, UPDATE ON queue_entries TO nexoeventos_app")
    op.execute("GRANT UPDATE (sales_start_at, queue_enabled, queue_max_active, queue_pass_minutes) ON events TO nexoeventos_app")


def downgrade() -> None:
    op.drop_index("uq_queue_entries_live_per_user", table_name="queue_entries")
    op.drop_index("ix_queue_entries_event_status_joined", table_name="queue_entries")
    op.drop_table("queue_entries")
    op.drop_constraint("ck_events_queue_pass_minutes", "events", type_="check")
    op.drop_constraint("ck_events_queue_max_active", "events", type_="check")
    for column in ("queue_pass_minutes", "queue_max_active", "queue_enabled", "sales_start_at"):
        op.drop_column("events", column)
