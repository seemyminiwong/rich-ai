"""Кольорова схема стилю (palette_json): 4 токени поверх незмінної сітки."""
import sqlalchemy as sa
from alembic import op

revision = "0015_style_palette"
down_revision = "0014_landing_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."styles" ADD COLUMN IF NOT EXISTS palette_json text DEFAULT \'{{}}\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."styles" DROP COLUMN IF EXISTS palette_json'
    ))
