import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.config import settings
from app.db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(str, enum.Enum):
    admin = 'admin'
    editor = 'editor'
    reviewer = 'reviewer'
    viewer = 'viewer'


class Status(str, enum.Enum):
    draft = 'draft'
    queued = 'queued'
    processing = 'processing'
    review = 'review'
    changes_requested = 'changes_requested'
    approved = 'approved'
    done = 'done'
    error = 'error'
    paused = 'paused'
    cancelled = 'cancelled'


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, default='')
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions_json: Mapped[str] = mapped_column(Text, default='{}')
    # Особистий денний бюджет $ (0 = без особистого ліміту; глобальний діє завжди).
    daily_budget_usd: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Invite(Base):
    __tablename__ = 'invites'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Style(Base):
    __tablename__ = 'styles'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(Text, default='')
    prompt: Mapped[str] = mapped_column(Text, default='')
    hero_prompt: Mapped[str] = mapped_column(Text, default='')
    feature_prompt: Mapped[str] = mapped_column(Text, default='')
    negative_prompt: Mapped[str] = mapped_column(Text, default='')
    score_json: Mapped[str] = mapped_column(Text, default='{}')
    preview_html: Mapped[str] = mapped_column(Text, default='')
    # Еталон формату (few-shot): якщо заданий, підмішується в промпт як приклад.
    golden_html: Mapped[str] = mapped_column(Text, default='')
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    style_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.styles.id'))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'), nullable=True)
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.queued)
    stage: Mapped[str] = mapped_column(String, default='queued')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    languages: Mapped[str] = mapped_column(String, default='ru,ua')
    variants: Mapped[str] = mapped_column(String, default='desktop,mobile')
    text_model: Mapped[str] = mapped_column(String, default='gpt-5-mini')
    image_model: Mapped[str] = mapped_column(String, default='gpt-image-1')
    image_quality: Mapped[str] = mapped_column(String, default='medium')
    custom_hero_url: Mapped[str] = mapped_column(Text, default='')
    custom_feature_url: Mapped[str] = mapped_column(Text, default='')
    product_category: Mapped[str] = mapped_column(String, default='')
    product_json: Mapped[str] = mapped_column(Text, default='{}')
    source_images: Mapped[str] = mapped_column(Text, default='[]')
    # Operator-curated gallery frames from the probe dialog; empty = auto-pick.
    gallery_json: Mapped[str] = mapped_column(Text, default='[]')
    # Кадри 360°-серії (Podium 3D 360): підписані /media-URL по колу, за порядком.
    rotation_json: Mapped[str] = mapped_column(Text, default='[]')
    error: Mapped[str] = mapped_column(Text, default='')
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    text_request_count: Mapped[int] = mapped_column(Integer, default=0)
    image_request_count: Mapped[int] = mapped_column(Integer, default=0)
    text_cost: Mapped[float] = mapped_column(Float, default=0)
    image_cost: Mapped[float] = mapped_column(Float, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    # Conservative budget reservation for queued/running bulk work. Unlike the
    # live estimate, it is not reset when a worker starts and survives restarts.
    reserved_cost: Mapped[float] = mapped_column(Float, default=0)
    # Вартість ПОТОЧНОГО прогону обнуляється при перезапуску, тому сумарна
    # вартість проєкту живе окремо і не втрачається ніколи.
    lifetime_cost: Mapped[float] = mapped_column(Float, default=0)
    run_index: Mapped[int] = mapped_column(Integer, default=1)
    runs_json: Mapped[str] = mapped_column(Text, default='[]')
    cost_breakdown_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # Time this run entered the queue. Separate from started_at, which becomes
    # the actual processing start once a worker claims the project.
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    artifacts: Mapped[list['Artifact']] = relationship(back_populates='project', cascade='all, delete-orphan')


class Artifact(Base):
    __tablename__ = 'artifacts'
    __table_args__ = (UniqueConstraint('project_id', 'language', 'variant', 'version'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.projects.id'))
    language: Mapped[str] = mapped_column(String)
    variant: Mapped[str] = mapped_column(String)
    html: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Non-empty when this page is the emergency template, not AI output.
    fallback_reason: Mapped[str] = mapped_column(Text, default='')
    # Номер прогону, у якому зʼявилась ця версія.
    run_index: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped[Project] = relationship(back_populates='artifacts')


class Review(Base):
    __tablename__ = 'reviews'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.projects.id'), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'))
    decision: Mapped[str] = mapped_column(String)
    comment: Mapped[str] = mapped_column(Text, default='')
    checklist_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.projects.id'))
    stage: Mapped[str] = mapped_column(String)
    level: Mapped[str] = mapped_column(String, default='info')
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    entity_type: Mapped[str] = mapped_column(String, default='')
    entity_id: Mapped[str] = mapped_column(String, default='')
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class StyleVersion(Base):
    __tablename__ = 'style_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    style_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.styles.id'), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    prompt: Mapped[str] = mapped_column(Text, default='')
    hero_prompt: Mapped[str] = mapped_column(Text, default='')
    feature_prompt: Mapped[str] = mapped_column(Text, default='')
    created_by: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Asset(Base):
    __tablename__ = 'assets'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.projects.id'), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String, default='image')
    label: Mapped[str] = mapped_column(String, default='')
    url: Mapped[str] = mapped_column(Text, default='')
    prompt: Mapped[str] = mapped_column(Text, default='')
    model: Mapped[str] = mapped_column(String, default='')
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CriticReport(Base):
    __tablename__ = 'critic_reports'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey(f'{settings.db_schema}.projects.id'), index=True)
    critic_type: Mapped[str] = mapped_column(String, index=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    summary: Mapped[str] = mapped_column(Text, default='')
    issues_json: Mapped[str] = mapped_column(Text, default='[]')
    suggestions_json: Mapped[str] = mapped_column(Text, default='[]')
    auto_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Landing(Base):
    """Промо-лендінг кампанії (на кшталт artline.ua/solution/*): багато товарів,
    ціни та кнопки «Купити». Окремо від Project: інша модель даних (N товарів,
    жодних AI-зображень) і інший вихід (standalone-сторінка, а не фрагмент)."""
    __tablename__ = 'landings'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, index=True)
    campaign_title: Mapped[str] = mapped_column(Text, default='')     # «Знижки до -50%»
    campaign_subtitle: Mapped[str] = mapped_column(Text, default='')  # «До 4-ї річниці Bambu Lab»
    period: Mapped[str] = mapped_column(String, default='')           # «15.06–15.07»
    language: Mapped[str] = mapped_column(String, default='ua')
    source_urls_json: Mapped[str] = mapped_column(Text, default='[]')  # URL товарів від оператора
    listing_url: Mapped[str] = mapped_column(Text, default='')         # сторінка акції/категорії
    products_json: Mapped[str] = mapped_column(Text, default='[]')     # проби: name/image/price/old_price/url
    # Категорії акції (сітка карток-посилань на каталог, як на /solution/easter-2026)
    source_categories_json: Mapped[str] = mapped_column(Text, default='[]')  # URL від оператора
    categories_json: Mapped[str] = mapped_column(Text, default='[]')         # проби: name/image/url
    html: Mapped[str] = mapped_column(Text, default='')
    text_model: Mapped[str] = mapped_column(String, default='')
    # Фон hero: 'ai' - тематична сцена за темою акції (text-to-image, без
    # товару), 'custom' - завантажене операторм фото, 'none' - фірмовий градієнт.
    with_hero: Mapped[bool] = mapped_column(Boolean, default=True)  # legacy, читається як ai/none
    hero_mode: Mapped[str] = mapped_column(String, default='ai')
    custom_hero_url: Mapped[str] = mapped_column(Text, default='')
    hero_url: Mapped[str] = mapped_column(Text, default='')
    image_cost: Mapped[float] = mapped_column(Float, default=0)
    # Стиль-шаблон промпта лендінгу (керований «ARTLINE Landing» або власний).
    style_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.queued)
    stage: Mapped[str] = mapped_column(String, default='queued')
    error: Mapped[str] = mapped_column(Text, default='')
    fallback_reason: Mapped[str] = mapped_column(Text, default='')
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey(f'{settings.db_schema}.users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    """Runtime configuration the root admin edits from the UI (API keys, provider).

    Values override the matching .env entries. Read through app.runtime, never
    directly, so the API and the worker share one resolution path and one cache.
    """
    __tablename__ = 'app_settings'
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')
    updated_by: Mapped[str] = mapped_column(String, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
