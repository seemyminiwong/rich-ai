"""Промо-лендінги кампаній: N товарів з цінами і кнопками, standalone-сторінка.

Таблиця створюється з моделі (як у baseline): так колонка status переиспользує
наявний enum-тип, а схема гарантовано збігається з кодом.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_landings"
down_revision = "0010_bulk_queue_clock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Landing
    Landing.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from app.config import settings
    op.get_bind().execute(sa.text(f'DROP TABLE IF EXISTS "{settings.db_schema}"."landings"'))
