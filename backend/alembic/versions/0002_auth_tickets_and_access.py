"""Add users, sessions, ownership, tickets, and access validation.

Revision ID: 0002
Revises: 0001

Existing reservations intentionally remain with user_id NULL. They are legacy
demo data and are not exposed to any client account.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('client', 'organizer', 'operator')", name="ck_users_role"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.add_column("events", sa.Column("organizer_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_events_organizer", "events", "users", ["organizer_user_id"], ["id"], ondelete="SET NULL")
    op.add_column("reservations", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_reservations_user", "reservations", "users", ["user_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_reservations_user_id", "reservations", ["user_id"])

    op.create_table(
        "operator_event_assignments",
        sa.Column("operator_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_tickets_token_hash"),
    )
    op.create_index("ix_tickets_owner_user_id", "tickets", ["owner_user_id"])
    op.create_index("ix_tickets_reservation_id", "tickets", ["reservation_id"])
    op.create_table(
        "access_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("operator_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("result IN ('accepted', 'already_used', 'invalid_token', 'wrong_event')", name="ck_access_logs_result"),
    )

    op.execute("GRANT SELECT, INSERT ON users TO nexoeventos_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON auth_sessions TO nexoeventos_app")
    op.execute("GRANT SELECT ON operator_event_assignments TO nexoeventos_app")
    op.execute("GRANT SELECT, INSERT ON tickets TO nexoeventos_app")
    op.execute("GRANT UPDATE (used_at, used_by_user_id) ON tickets TO nexoeventos_app")
    op.execute("GRANT INSERT ON access_logs TO nexoeventos_app")
    op.execute("GRANT UPDATE (name, event_date, venue, category, description, price, capacity) ON events TO nexoeventos_app")


def downgrade() -> None:
    op.drop_table("access_logs")
    op.drop_index("ix_tickets_reservation_id", table_name="tickets")
    op.drop_index("ix_tickets_owner_user_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_table("operator_event_assignments")
    op.drop_index("ix_reservations_user_id", table_name="reservations")
    op.drop_constraint("fk_reservations_user", "reservations", type_="foreignkey")
    op.drop_column("reservations", "user_id")
    op.drop_constraint("fk_events_organizer", "events", type_="foreignkey")
    op.drop_column("events", "organizer_user_id")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
