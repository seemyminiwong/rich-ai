"""Референс для AI-зображень, обраний оператором (порожньо = автопідбір)."""
import sqlalchemy as sa
from alembic import op

revision = "0020_project_reference_url"
down_revision = "0019_project_image_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS reference_url text NOT NULL DEFAULT \'\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS reference_url'
    ))
