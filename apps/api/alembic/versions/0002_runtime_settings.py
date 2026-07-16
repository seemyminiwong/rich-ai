"""Post-baseline changes that ensure_schema() used to apply by hand.

Everything here is idempotent (IF NOT EXISTS): databases that already received
these changes from the old ensure_schema() path upgrade cleanly, and so do
databases coming straight from the v11.2 baseline.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_runtime_settings"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    schema = settings.db_schema
    bind = op.get_bind()
    bind.execute(sa.text(
        f'ALTER TABLE "{schema}"."projects" ADD COLUMN IF NOT EXISTS cost_breakdown_json text DEFAULT \'{{}}\''
    ))
    bind.execute(sa.text(
        f'ALTER TABLE "{schema}"."users" ADD COLUMN IF NOT EXISTS permissions_json text DEFAULT \'{{}}\''
    ))
    bind.execute(sa.text(
        f'CREATE TABLE IF NOT EXISTS "{schema}"."app_settings" ('
        'key varchar PRIMARY KEY, '
        "value text DEFAULT '', "
        "updated_by varchar DEFAULT '', "
        'updated_at timestamp without time zone)'
    ))


def downgrade() -> None:
    from app.config import settings
    schema = settings.db_schema
    bind = op.get_bind()
    bind.execute(sa.text(f'DROP TABLE IF EXISTS "{schema}"."app_settings"'))
    bind.execute(sa.text(f'ALTER TABLE "{schema}"."projects" DROP COLUMN IF EXISTS cost_breakdown_json'))
    bind.execute(sa.text(f'ALTER TABLE "{schema}"."users" DROP COLUMN IF EXISTS permissions_json'))
