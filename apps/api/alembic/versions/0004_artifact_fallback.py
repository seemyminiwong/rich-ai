"""Mark artifacts that were served from the deterministic fallback template."""
import sqlalchemy as sa
from alembic import op

revision = "0004_artifact_fallback"
down_revision = "0003_project_gallery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."artifacts" ADD COLUMN IF NOT EXISTS fallback_reason text DEFAULT \'\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."artifacts" DROP COLUMN IF EXISTS fallback_reason'
    ))
