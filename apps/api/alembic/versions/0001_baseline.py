"""baseline: current ARTLINE Rich Studio schema (v11.2 layout)

For an existing database that already has the tables, run:
    alembic stamp head
so Alembic records this baseline without re-creating anything.

For a fresh database:
    alembic upgrade head
creates the schema and every table from the current models.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    from app.db import Base
    bind = op.get_bind()
    bind.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from app.db import Base
    Base.metadata.drop_all(op.get_bind())
