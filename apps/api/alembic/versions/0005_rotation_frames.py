"""Кадри 360°-серії проєкту (ARTLINE Podium 3D 360)."""
import sqlalchemy as sa
from alembic import op

revision = "0005_rotation_frames"
down_revision = "0004_artifact_fallback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS rotation_json text DEFAULT \'[]\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS rotation_json'
    ))
