"""Тема сторінки ARTLINE Master (змішана / світла / темна), обрана при запуску."""
import sqlalchemy as sa
from alembic import op

revision = "0022_project_style_theme"
down_revision = "0021_landing_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS style_theme text NOT NULL DEFAULT \'mixed\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS style_theme'
    ))
