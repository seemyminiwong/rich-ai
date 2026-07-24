"""Лендінги: режим фону (ai/custom/none), власний фон, стиль-шаблон промпта."""
import sqlalchemy as sa
from alembic import op

revision = "0013_landing_hero_modes"
down_revision = "0012_landing_hero"
branch_labels = None
depends_on = None

COLUMNS = (
    ('hero_mode', "varchar DEFAULT 'ai'"),
    ('custom_hero_url', "text DEFAULT ''"),
    ('style_id', 'varchar'),
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
