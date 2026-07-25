"""Кольорові пресети (бренд-схеми) + знімок схеми на проєкті/лендінгу."""
import sqlalchemy as sa
from alembic import op

revision = "0016_palettes"
down_revision = "0015_style_palette"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    from app.models import Palette
    bind = op.get_bind()
    Palette.__table__.create(bind, checkfirst=True)
    for table in ('projects', 'landings'):
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."{table}" ADD COLUMN IF NOT EXISTS palette_json text DEFAULT \'{{}}\''
        ))


def downgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    for table in ('projects', 'landings'):
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."{table}" DROP COLUMN IF EXISTS palette_json'
        ))
    bind.execute(sa.text(f'DROP TABLE IF EXISTS "{settings.db_schema}"."palettes"'))
