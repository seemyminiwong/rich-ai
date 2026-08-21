"""Посилання на YouTube-ролик проєкту (блок відео)."""
import sqlalchemy as sa
from alembic import op

revision = "0018_project_video"
down_revision = "0017_project_faq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" ADD COLUMN IF NOT EXISTS video_url text NOT NULL DEFAULT \'\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."projects" DROP COLUMN IF EXISTS video_url'
    ))
