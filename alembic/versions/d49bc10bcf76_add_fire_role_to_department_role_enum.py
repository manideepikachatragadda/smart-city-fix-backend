"""Add FIRE role to department_role_enum

Revision ID: d49bc10bcf76
Revises: 
Create Date: 2026-04-11 00:09:29.582176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd49bc10bcf76'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("COMMIT")
    op.execute("ALTER TYPE department_role_enum ADD VALUE IF NOT EXISTS 'FIRE'")
    op.execute("BEGIN")


def downgrade() -> None:
    """Downgrade schema."""
    pass
