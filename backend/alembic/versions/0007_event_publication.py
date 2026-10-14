"""Add draft/published state and the narrow write grants organizers need.

Existing rows stay published, so the public catalog and reservations behave exactly as before.

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("status", sa.String(12), nullable=False, server_default="published"))
    op.create_check_constraint("ck_events_status", "events", "status IN ('draft', 'published')")
    # El rol de aplicación crea/edita borradores; las FKs RESTRICT impiden borrar eventos con reservas o entradas.
    op.execute("GRANT INSERT, DELETE ON events TO nexoeventos_app")
    op.execute("GRANT UPDATE (event_time, city, category, ticket_mode, venue_id, layout_id, status, image_path) ON events TO nexoeventos_app")
    op.execute("GRANT INSERT, DELETE ON event_zones, event_seats TO nexoeventos_app")
    op.execute("GRANT UPDATE (name, price, capacity) ON event_zones TO nexoeventos_app")
    op.execute("GRANT INSERT, DELETE ON operator_event_assignments TO nexoeventos_app")


def downgrade() -> None:
    op.execute("REVOKE INSERT, DELETE ON operator_event_assignments FROM nexoeventos_app")
    op.execute("REVOKE UPDATE (name, price, capacity) ON event_zones FROM nexoeventos_app")
    op.execute("REVOKE INSERT, DELETE ON event_zones, event_seats FROM nexoeventos_app")
    op.execute("REVOKE UPDATE (event_time, city, category, ticket_mode, venue_id, layout_id, status, image_path) ON events FROM nexoeventos_app")
    op.execute("REVOKE INSERT, DELETE ON events FROM nexoeventos_app")
    op.drop_constraint("ck_events_status", "events", type_="check")
    op.drop_column("events", "status")
