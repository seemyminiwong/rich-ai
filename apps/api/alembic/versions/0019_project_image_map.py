"""Мапа підміни посилань на зображення (студія -> сервер магазину)."""
import sqlalchemy as sa
from alembic import op

revision = "0019_project_image_map"
down_revision = "0018_project_video"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS image_map_json text NOT NULL DEFAULT \'{{}}\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS image_map_json'
    ))
