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
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))

metadata_obj = MetaData(schema=settings.db_schema)

class Base(DeclarativeBase):
    metadata = metadata_obj

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
