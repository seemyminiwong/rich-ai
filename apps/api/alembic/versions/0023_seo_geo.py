"""SEO/GEO/human-copy контроль: бриф і provenance проєкту, Publishing Profile,
структуровані знахідки критиків, рішення рецензента, SEO-поля лендінгу.

Усі ALTER - IF NOT EXISTS / IF EXISTS: міграція безпечно накочується на живу
БД і так само безпечно відкочується; наявні проєкти й артефакти лишаються
доступними (нові колонки мають значення за замовчуванням)."""
import sqlalchemy as sa
from alembic import op

revision = "0023_seo_geo"
down_revision = "0022_project_style_theme"
branch_labels = None
depends_on = None


def _exec(sql: str) -> None:
    op.get_bind().execute(sa.text(sql))


def upgrade() -> None:
    from app.config import settings
    schema = settings.db_schema
    for column in ('seo_brief_json', 'source_evidence_json', 'publishing_profile_json'):
        _exec(f'ALTER TABLE "{schema}"."projects" ADD COLUMN IF NOT EXISTS {column} text NOT NULL DEFAULT \'{{}}\'')
    _exec(f'ALTER TABLE "{schema}"."projects" ADD COLUMN IF NOT EXISTS seo_history_json text NOT NULL DEFAULT \'[]\'')
    _exec(f'ALTER TABLE "{schema}"."critic_reports" ADD COLUMN IF NOT EXISTS findings_json text NOT NULL DEFAULT \'[]\'')
    _exec(f'ALTER TABLE "{schema}"."landings" ADD COLUMN IF NOT EXISTS publish_url text NOT NULL DEFAULT \'\'')
    _exec(f'ALTER TABLE "{schema}"."landings" ADD COLUMN IF NOT EXISTS alternates_json text NOT NULL DEFAULT \'{{}}\'')
    _exec(f'ALTER TABLE "{schema}"."landings" ADD COLUMN IF NOT EXISTS publishing_profile_json text NOT NULL DEFAULT \'{{}}\'')
    _exec(f'''CREATE TABLE IF NOT EXISTS "{schema}"."publishing_profiles" (
        id varchar PRIMARY KEY,
        name varchar NOT NULL UNIQUE,
        domains_json text NOT NULL DEFAULT '[]',
        organization_name varchar NOT NULL DEFAULT '',
        organization_url text NOT NULL DEFAULT '',
        logo_url text NOT NULL DEFAULT '',
        primary_site boolean NOT NULL DEFAULT false,
        markets_json text NOT NULL DEFAULT '[]',
        languages_json text NOT NULL DEFAULT '[]',
        verified_facts_json text NOT NULL DEFAULT '{{}}',
        statements_json text NOT NULL DEFAULT '{{}}',
        approved_contacts_json text NOT NULL DEFAULT '[]',
        delivery_geography_json text NOT NULL DEFAULT '[]',
        warranty_text_json text NOT NULL DEFAULT '{{}}',
        service_text_json text NOT NULL DEFAULT '{{}}',
        is_default boolean NOT NULL DEFAULT false,
        version integer NOT NULL DEFAULT 1,
        updated_by varchar NOT NULL DEFAULT '',
        updated_at timestamp NOT NULL DEFAULT now(),
        created_at timestamp NOT NULL DEFAULT now()
    )''')
    _exec(f'''CREATE TABLE IF NOT EXISTS "{schema}"."finding_decisions" (
        id varchar PRIMARY KEY,
        project_id varchar NOT NULL REFERENCES "{schema}"."projects"(id) ON DELETE CASCADE,
        finding_key varchar NOT NULL,
        state varchar NOT NULL DEFAULT 'open',
        comment text NOT NULL DEFAULT '',
        user_id varchar NULL REFERENCES "{schema}"."users"(id) ON DELETE SET NULL,
        created_at timestamp NOT NULL DEFAULT now(),
        updated_at timestamp NOT NULL DEFAULT now(),
        UNIQUE (project_id, finding_key)
    )''')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{schema}_finding_decisions_project ON "{schema}"."finding_decisions" (project_id)')


def downgrade() -> None:
    from app.config import settings
    schema = settings.db_schema
    _exec(f'DROP TABLE IF EXISTS "{schema}"."finding_decisions"')
    _exec(f'DROP TABLE IF EXISTS "{schema}"."publishing_profiles"')
    for column in ('publish_url', 'alternates_json', 'publishing_profile_json'):
        _exec(f'ALTER TABLE "{schema}"."landings" DROP COLUMN IF EXISTS {column}')
    _exec(f'ALTER TABLE "{schema}"."critic_reports" DROP COLUMN IF EXISTS findings_json')
    for column in ('seo_brief_json', 'source_evidence_json', 'publishing_profile_json', 'seo_history_json'):
        _exec(f'ALTER TABLE "{schema}"."projects" DROP COLUMN IF EXISTS {column}')
