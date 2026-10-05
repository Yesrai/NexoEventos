"""Keep the original fixtures without mixing them into the 18-event catalog.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE events SET is_demo = false
        WHERE (id = 1 AND name = 'Noche Prisma')
           OR (id = 2 AND name = 'Código Abierto Summit')
           OR (id = 3 AND name = 'Sabores del Pacífico')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE events SET is_demo = true
        WHERE (id = 1 AND name = 'Noche Prisma')
           OR (id = 2 AND name = 'Código Abierto Summit')
           OR (id = 3 AND name = 'Sabores del Pacífico')
    """)
