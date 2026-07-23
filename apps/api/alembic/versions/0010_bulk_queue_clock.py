"""Queue-entry clock for durable dispatch and delayed-work alerts."""
import sqlalchemy as sa
from alembic import op

revision = "0010_bulk_queue_clock"
down_revision = "0009_bulk_budget_reservation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS queued_at timestamp without time zone'
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS queued_at'
    ))
