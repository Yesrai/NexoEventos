"""Create events and private reservations.

Revision ID: 0001
Revises: None
"""
from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("venue", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("capacity >= 0", name="ck_events_capacity_nonnegative"),
        sa.CheckConstraint("reserved_count >= 0", name="ck_events_reserved_nonnegative"),
        sa.CheckConstraint("reserved_count <= capacity", name="ck_events_reserved_within_capacity"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("buyer_alias", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_reservations_quantity_positive"),
        sa.UniqueConstraint("idempotency_key", name="uq_reservations_idempotency_key"),
    )
    op.create_index("ix_reservations_event_id", "reservations", ["event_id"])

    events = sa.table(
        "events",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("event_date", sa.Date()),
        sa.column("venue", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("price", sa.Numeric()),
        sa.column("capacity", sa.Integer()),
        sa.column("reserved_count", sa.Integer()),
    )
    op.bulk_insert(events, [
        {"id": 1, "name": "Noche Prisma", "event_date": date(2026, 10, 17), "venue": "Centro Cultural de Lima", "category": "Música", "description": "Una noche ficticia de música, luces y propuestas independientes.", "price": 65, "capacity": 240, "reserved_count": 0},
        {"id": 2, "name": "Código Abierto Summit", "event_date": date(2026, 10, 24), "venue": "Auditorio Miraflores", "category": "Tecnología", "description": "Charlas y talleres simulados sobre software abierto y comunidad.", "price": 35, "capacity": 180, "reserved_count": 0},
        {"id": 3, "name": "Sabores del Pacífico", "event_date": date(2026, 11, 7), "venue": "Costa Verde", "category": "Gastronomía", "description": "Encuentro académico ficticio con cocina y productores locales.", "price": 48, "capacity": 320, "reserved_count": 0},
    ])

    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO nexoeventos_app")
    op.execute("GRANT SELECT ON events TO nexoeventos_app")
    op.execute("GRANT UPDATE (reserved_count) ON events TO nexoeventos_app")
    op.execute("GRANT SELECT, INSERT ON reservations TO nexoeventos_app")


def downgrade() -> None:
    op.drop_index("ix_reservations_event_id", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("events")
