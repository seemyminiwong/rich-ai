"""Golden-приклад формату для стилю (few-shot еталон)."""
import sqlalchemy as sa
from alembic import op

revision = "0008_style_golden"
down_revision = "0007_run_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."styles" ADD COLUMN IF NOT EXISTS golden_html text DEFAULT \'\''
    ))


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."styles" DROP COLUMN IF EXISTS golden_html'
    ))
