"""Прапорець блока FAQ на проєкті."""
import sqlalchemy as sa
from alembic import op

revision = "0017_project_faq"
down_revision = "0016_palettes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS faq_enabled boolean NOT NULL DEFAULT true'
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS faq_enabled'
    ))
