"""Separate venues, reusable layouts and dated event functions.

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.UniqueConstraint("code", name="uq_venues_code"),
    )
    op.create_table(
        "venue_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("layout_kind", sa.String(24), nullable=False),
        sa.CheckConstraint(
            "layout_kind IN ('theatre', 'stadium', 'concert_zones', 'museum', 'zones', 'general')",
            name="ck_venue_layouts_kind",
        ),
        sa.UniqueConstraint("venue_id", "code", name="uq_venue_layouts_venue_code"),
    )
    op.create_index("ix_venue_layouts_venue_id", "venue_layouts", ["venue_id"])
    op.add_column("events", sa.Column("venue_id", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("layout_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_events_venue", "events", "venues", ["venue_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_events_layout", "events", "venue_layouts", ["layout_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_events_venue_id", "events", ["venue_id"])
    op.create_index("ix_events_layout_id", "events", ["layout_id"])
    op.execute("GRANT SELECT ON venues, venue_layouts TO nexoeventos_app")


def downgrade() -> None:
    op.drop_index("ix_events_layout_id", table_name="events")
    op.drop_index("ix_events_venue_id", table_name="events")
    op.drop_constraint("fk_events_layout", "events", type_="foreignkey")
    op.drop_constraint("fk_events_venue", "events", type_="foreignkey")
    op.drop_column("events", "layout_id")
    op.drop_column("events", "venue_id")
    op.drop_index("ix_venue_layouts_venue_id", table_name="venue_layouts")
    op.drop_table("venue_layouts")
    op.drop_table("venues")
