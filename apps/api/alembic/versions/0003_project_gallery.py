"""Operator-curated gallery selection per project."""
import sqlalchemy as sa
from alembic import op

revision = "0003_project_gallery"
down_revision = "0002_runtime_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS gallery_json text DEFAULT \'[]\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS gallery_json'
    ))
