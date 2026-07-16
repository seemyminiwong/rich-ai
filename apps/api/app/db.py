import re

from sqlalchemy import MetaData, URL, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


def database_url():
    if settings.database_url:
        return settings.database_url
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )

engine = create_engine(database_url(), pool_pre_ping=True, pool_recycle=300)


def ensure_schema():
    """Create and safely upgrade the configured schema without startup races."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', settings.db_schema):
        raise RuntimeError('DB_SCHEMA contains unsupported characters')
    with engine.begin() as connection:
        connection.execute(
            text('SELECT pg_advisory_xact_lock(hashtext(:lock_name))'),
            {'lock_name': f'richstudio-schema:{settings.db_schema}'},
        )
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
    # SQLAlchemy create_all() does not add new labels to an existing PostgreSQL
    # enum. Older Rich Studio schemas therefore failed when Review tried to save
    # approved/changes_requested. Upgrade enum labels before the API accepts work.
    enum_columns = {
        ('projects', 'status'): ('draft', 'queued', 'processing', 'review', 'changes_requested', 'approved', 'done', 'error', 'paused', 'cancelled'),
        ('users', 'role'): ('admin', 'editor', 'reviewer', 'viewer'),
    }
    for (table_name, column_name), values in enum_columns.items():
        with engine.begin() as connection:
            enum_row = connection.execute(text('''
                SELECT type_ns.nspname, type_row.typname
                FROM pg_attribute attribute
                JOIN pg_class table_row ON table_row.oid=attribute.attrelid
                JOIN pg_namespace table_ns ON table_ns.oid=table_row.relnamespace
                JOIN pg_type type_row ON type_row.oid=attribute.atttypid
                JOIN pg_namespace type_ns ON type_ns.oid=type_row.typnamespace
                WHERE table_ns.nspname=:schema
                  AND table_row.relname=:table_name
                  AND attribute.attname=:column_name
                  AND attribute.attnum>0
                  AND NOT attribute.attisdropped
            '''), {'schema': settings.db_schema, 'table_name': table_name, 'column_name': column_name}).first()
            if not enum_row:
                continue
            enum_schema, enum_name = enum_row
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', enum_schema or '') or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', enum_name or ''):
                raise RuntimeError('Database enum contains unsupported identifier characters')
            for value in values:
                connection.execute(text(
                    f'ALTER TYPE "{enum_schema}"."{enum_name}" ADD VALUE IF NOT EXISTS \'{value}\''
                ))


def run_migrations():
    """Bring the database to the current Alembic head.

    Three states exist in the wild:
      fresh DB            -> upgrade head (baseline creates every table)
      pre-Alembic DB      -> stamp baseline, then upgrade head (0002+ are
                             idempotent, so a DB that already got those changes
                             from the old hand-rolled path upgrades cleanly)
      migrated DB         -> upgrade head is a no-op or applies what is new
    """
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    cfg = Config(str(ini))
    cfg.set_main_option('script_location', str(ini.parent / 'alembic'))
    with engine.connect() as connection:
        has_version = connection.execute(text(
            'SELECT 1 FROM information_schema.tables WHERE table_schema=:s AND table_name=:t'
        ), {'s': settings.db_schema, 't': 'alembic_version'}).first() is not None
        has_tables = connection.execute(text(
            'SELECT 1 FROM information_schema.tables WHERE table_schema=:s AND table_name=:t'
        ), {'s': settings.db_schema, 't': 'projects'}).first() is not None
    if not has_version and has_tables:
        command.stamp(cfg, '0001_baseline')
    command.upgrade(cfg, 'head')

metadata_obj = MetaDatametadata_obj = MetaData(schema=settings.db_schema)

class Base(DeclarativeBase):
    metadata = metadata_obj

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
