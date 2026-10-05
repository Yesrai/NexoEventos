"""Add catalog metadata, zones and numbered seats without changing legacy reservations.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("event_time", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("city", sa.String(80), nullable=False, server_default="Lima"))
    op.add_column("events", sa.Column("image_path", sa.String(240), nullable=True))
    op.add_column("events", sa.Column("ticket_mode", sa.String(20), nullable=False, server_default="general"))
    op.add_column("events", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_check_constraint("ck_events_ticket_mode", "events", "ticket_mode IN ('general', 'zones', 'seats')")

    op.create_table(
        "event_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("price >= 0", name="ck_event_zones_price_nonnegative"),
        sa.CheckConstraint("capacity >= 0", name="ck_event_zones_capacity_nonnegative"),
        sa.CheckConstraint("reserved_count BETWEEN 0 AND capacity", name="ck_event_zones_reserved_within_capacity"),
        sa.UniqueConstraint("event_id", "name", name="uq_event_zones_event_name"),
    )
    op.create_index("ix_event_zones_event_id", "event_zones", ["event_id"])
    op.create_table(
        "event_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("event_zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_label", sa.String(12), nullable=False),
        sa.Column("seat_number", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint("seat_number > 0", name="ck_event_seats_number_positive"),
        sa.UniqueConstraint("event_id", "zone_id", "row_label", "seat_number", name="uq_event_seats_position"),
    )
    op.create_index("ix_event_seats_event_id", "event_seats", ["event_id"])
    op.create_index("ix_event_seats_reservation_id", "event_seats", ["reservation_id"])

    op.add_column("tickets", sa.Column("ticket_type", sa.String(20), nullable=False, server_default="general"))
    op.add_column("tickets", sa.Column("zone_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("seat_id", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("unit_price", sa.Numeric(10, 2), nullable=True))
    op.create_foreign_key("fk_tickets_zone", "tickets", "event_zones", ["zone_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_tickets_seat", "tickets", "event_seats", ["seat_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_tickets_seat_id", "tickets", ["seat_id"])
    op.execute("UPDATE tickets SET unit_price = events.price FROM events WHERE tickets.event_id = events.id")

    op.execute("GRANT SELECT ON event_zones, event_seats TO nexoeventos_app")
    op.execute("GRANT UPDATE (reserved_count) ON event_zones TO nexoeventos_app")
    op.execute("GRANT UPDATE (reservation_id) ON event_seats TO nexoeventos_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexoeventos_app")
    op.execute("GRANT UPDATE (reserved_count) ON events TO nexoeventos_app")


def downgrade() -> None:
    op.drop_constraint("uq_tickets_seat_id", "tickets", type_="unique")
    op.drop_constraint("fk_tickets_seat", "tickets", type_="foreignkey")
    op.drop_constraint("fk_tickets_zone", "tickets", type_="foreignkey")
    for column in ("unit_price", "seat_id", "zone_id", "ticket_type"):
        op.drop_column("tickets", column)
    op.drop_index("ix_event_seats_reservation_id", table_name="event_seats")
    op.drop_index("ix_event_seats_event_id", table_name="event_seats")
    op.drop_table("event_seats")
    op.drop_index("ix_event_zones_event_id", table_name="event_zones")
    op.drop_table("event_zones")
    op.drop_constraint("ck_events_ticket_mode", "events", type_="check")
    for column in ("is_demo", "ticket_mode", "image_path", "city", "event_time"):
        op.drop_column("events", column)
