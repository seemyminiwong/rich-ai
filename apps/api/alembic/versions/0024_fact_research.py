"""Керований пошук фактів про товар: запуски, кандидати з доказом, знімок утверджених фактів.

Ідемпотентно і з відкатом. Наявні проєкти отримують режим strict (без інтернету)
і порожній знімок - їхня поведінка не змінюється.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_fact_research"
down_revision = "0023_seo_geo"
branch_labels = None
depends_on = None


def _exec(sql: str) -> None:
    op.get_bind().execute(sa.text(sql))


def upgrade() -> None:
    from app.config import settings
    s = settings.db_schema
    _exec(f'ALTER TABLE "{s}"."projects" ADD COLUMN IF NOT EXISTS fact_research_mode varchar NOT NULL DEFAULT \'strict\'')
    _exec(f'ALTER TABLE "{s}"."projects" ADD COLUMN IF NOT EXISTS approved_external_facts_json text NOT NULL DEFAULT \'{{}}\'')
    _exec(f'''CREATE TABLE IF NOT EXISTS "{s}"."fact_research_runs" (
        id varchar PRIMARY KEY,
        project_id varchar NOT NULL REFERENCES "{s}"."projects"(id) ON DELETE CASCADE,
        mode varchar NOT NULL DEFAULT 'official_research',
        provider varchar NOT NULL DEFAULT 'disabled',
        status varchar NOT NULL DEFAULT 'queued',
        queries_json text NOT NULL DEFAULT '[]',
        domains_json text NOT NULL DEFAULT '[]',
        params_json text NOT NULL DEFAULT '{{}}',
        notes_json text NOT NULL DEFAULT '{{}}',
        pages_found integer NOT NULL DEFAULT 0,
        pages_fetched integer NOT NULL DEFAULT 0,
        candidate_count integer NOT NULL DEFAULT 0,
        estimated_cost double precision NOT NULL DEFAULT 0,
        actual_cost double precision NOT NULL DEFAULT 0,
        started_by varchar NULL REFERENCES "{s}"."users"(id) ON DELETE SET NULL,
        started_at timestamp NULL,
        finished_at timestamp NULL,
        error text NOT NULL DEFAULT '',
        created_at timestamp NOT NULL DEFAULT now()
    )''')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{s}_fact_runs_project ON "{s}"."fact_research_runs" (project_id)')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{s}_fact_runs_status ON "{s}"."fact_research_runs" (status)')
    _exec(f'''CREATE TABLE IF NOT EXISTS "{s}"."fact_candidates" (
        id varchar PRIMARY KEY,
        research_run_id varchar NOT NULL REFERENCES "{s}"."fact_research_runs"(id) ON DELETE CASCADE,
        project_id varchar NOT NULL REFERENCES "{s}"."projects"(id) ON DELETE CASCADE,
        candidate_key varchar NOT NULL DEFAULT '',
        fact_path varchar NOT NULL DEFAULT '',
        label text NOT NULL DEFAULT '',
        value text NOT NULL DEFAULT '',
        normalized_value text NOT NULL DEFAULT '',
        unit varchar NOT NULL DEFAULT '',
        original_value text NOT NULL DEFAULT '',
        kind varchar NOT NULL DEFAULT 'spec',
        product_brand varchar NOT NULL DEFAULT '',
        product_model varchar NOT NULL DEFAULT '',
        sku varchar NOT NULL DEFAULT '',
        revision varchar NOT NULL DEFAULT '',
        region varchar NOT NULL DEFAULT '',
        source_url text NOT NULL DEFAULT '',
        source_domain varchar NOT NULL DEFAULT '',
        source_type varchar NOT NULL DEFAULT '',
        source_tier varchar NOT NULL DEFAULT 'C',
        source_title text NOT NULL DEFAULT '',
        source_date varchar NOT NULL DEFAULT '',
        retrieved_at varchar NOT NULL DEFAULT '',
        evidence_excerpt text NOT NULL DEFAULT '',
        evidence_locator varchar NOT NULL DEFAULT '',
        page_content_hash varchar NOT NULL DEFAULT '',
        identity_status varchar NOT NULL DEFAULT '',
        identity_score double precision NOT NULL DEFAULT 0,
        identity_notes_json text NOT NULL DEFAULT '[]',
        extractor varchar NOT NULL DEFAULT 'table',
        confidence varchar NOT NULL DEFAULT 'low',
        status varchar NOT NULL DEFAULT 'candidate',
        conflict_group varchar NOT NULL DEFAULT '',
        decision_comment text NOT NULL DEFAULT '',
        decided_by varchar NULL REFERENCES "{s}"."users"(id) ON DELETE SET NULL,
        decided_at timestamp NULL,
        created_at timestamp NOT NULL DEFAULT now(),
        UNIQUE (project_id, candidate_key)
    )''')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{s}_fact_candidates_project ON "{s}"."fact_candidates" (project_id)')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{s}_fact_candidates_run ON "{s}"."fact_candidates" (research_run_id)')
    _exec(f'CREATE INDEX IF NOT EXISTS ix_{s}_fact_candidates_status ON "{s}"."fact_candidates" (status)')


def downgrade() -> None:
    from app.config import settings
    s = settings.db_schema
    _exec(f'DROP TABLE IF EXISTS "{s}"."fact_candidates"')
    _exec(f'DROP TABLE IF EXISTS "{s}"."fact_research_runs"')
    _exec(f'ALTER TABLE "{s}"."projects" DROP COLUMN IF EXISTS approved_external_facts_json')
    _exec(f'ALTER TABLE "{s}"."projects" DROP COLUMN IF EXISTS fact_research_mode')
