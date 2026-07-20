"""Особистий денний бюджет $ користувача (0 = без ліміту)."""
import sqlalchemy as sa
from alembic import op

revision = "0006_user_daily_budget"
down_revision = "0005_rotation_frames"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."users" ADD COLUMN IF NOT EXISTS daily_budget_usd double precision DEFAULT 0'
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."users" DROP COLUMN IF EXISTS daily_budget_usd'
    ))
