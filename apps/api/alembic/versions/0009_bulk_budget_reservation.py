"""Durable budget reservation for queued bulk imports."""
import sqlalchemy as sa
from alembic import op

revision = "0009_bulk_budget_reservation"
down_revision = "0008_style_golden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" '
        'ADD COLUMN IF NOT EXISTS reserved_cost double precision NOT NULL DEFAULT 0'
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS reserved_cost'
    ))
