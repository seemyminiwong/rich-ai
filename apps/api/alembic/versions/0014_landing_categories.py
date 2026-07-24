"""Лендінги: сітка категорій акції (URL від оператора + проби name/image)."""
import sqlalchemy as sa
from alembic import op

revision = "0014_landing_categories"
down_revision = "0013_landing_hero_modes"
branch_labels = None
depends_on = None

COLUMNS = (
    ('source_categories_json', "text DEFAULT '[]'"),
    ('categories_json', "text DEFAULT '[]'"),
)


def upgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    for column, spec in COLUMNS:
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."landings" ADD COLUMN IF NOT EXISTS {column} {spec}'
        ))


def downgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    for column, _ in COLUMNS:
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."landings" DROP COLUMN IF EXISTS {column}'
        ))
