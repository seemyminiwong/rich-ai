"""Лендінги: тематичний AI-фон hero (with_hero, hero_url, image_cost)."""
import sqlalchemy as sa
from alembic import op

revision = "0012_landing_hero"
down_revision = "0011_landings"
branch_labels = None
depends_on = None

COLUMNS = (
    ('with_hero', 'boolean DEFAULT true'),
    ('hero_url', "text DEFAULT ''"),
    ('image_cost', 'double precision DEFAULT 0'),
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
