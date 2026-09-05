"""Публічне посилання на лендінг: прапорець публікації і секретний токен адреси.

Токен, а не id: id видно в адресному рядку студії й у логах, тож посилання за
id було б передбачуваним для всіх, хто колись бачив лендінг усередині. Токен
видається при першій публікації і переписується кнопкою «Новий токен» —
це і є відкликання вже розісланого посилання.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_landing_share"
down_revision = "0020_project_reference_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    bind.execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."landings" ADD COLUMN IF NOT EXISTS public boolean NOT NULL DEFAULT false'
    ))
    bind.execute(sa.text(
        f'ALTER TABLE "{settings.db_schema}"."landings" ADD COLUMN IF NOT EXISTS share_token text NOT NULL DEFAULT \'\''
    ))
    # Пошук публічної сторінки йде РІВНО за цим полем на кожен зовнішній запит.
    # Часткова умова лишає в індексі тільки видані токени, а не сотні порожніх
    # рядків, і водночас гарантує унікальність там, де вона потрібна.
    bind.execute(sa.text(
        f'CREATE UNIQUE INDEX IF NOT EXISTS ix_landings_share_token ON "{settings.db_schema}"."landings" (share_token) WHERE share_token <> \'\''
    ))


def downgrade() -> None:
    from app.config import settings
    bind = op.get_bind()
    bind.execute(sa.text(f'DROP INDEX IF EXISTS "{settings.db_schema}".ix_landings_share_token'))
    bind.execute(sa.text(f'ALTER TABLE "{settings.db_schema}"."landings" DROP COLUMN IF EXISTS share_token'))
    bind.execute(sa.text(f'ALTER TABLE "{settings.db_schema}"."landings" DROP COLUMN IF EXISTS public'))
