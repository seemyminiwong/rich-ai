"""Історія прогонів проєкту: сумарна вартість і вартість кожного прогону."""
import sqlalchemy as sa
from alembic import op

revision = "0007_run_history"
down_revision = "0006_user_daily_budget"
branch_labels = None
depends_on = None

COLUMNS = (
    ('projects', 'lifetime_cost', "double precision DEFAULT 0"),
    ('projects', 'run_index', "integer DEFAULT 1"),
    ('projects', 'runs_json', "text DEFAULT '[]'"),
    ('artifacts', 'run_index', "integer DEFAULT 1"),
)


def upgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    for table, column, spec in COLUMNS:
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."{table}" ADD COLUMN IF NOT EXISTS {column} {spec}'
        ))
    # Наявні проєкти: сумарна вартість дорівнює вартості єдиного відомого прогону.
    bind.execute(sa.text(
        f'UPDATE "{settings.db_schema}"."projects" SET lifetime_cost = estimated_cost '
        'WHERE lifetime_cost IS NULL OR lifetime_cost = 0'
    ))


def downgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    for table, column, _ in COLUMNS:
        bind.execute(sa.text(
            f'ALTER TABLE "{settings.db_schema}"."{table}" DROP COLUMN IF EXISTS {column}'
        ))
