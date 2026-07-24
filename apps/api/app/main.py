import hashlib
import hmac
import html as html_lib
import io
import json
import logging
import re
import secrets
import shutil
import time
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl, ValidationError
from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.orm import Session
from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_schema, get_db, run_migrations
from app.models import Artifact, Asset, AuditLog, CriticReport, Event, Invite, Landing, Project, Review, Role, Status, Style, StyleVersion, User
from app.security import PERMISSIONS, ROLE_DEFAULTS, current, effective_perms, has_perm, hash_password, require_perm, token, verify
from app.tasks import bill_extra, image_rate, process_landing, process_project, text_rate, translate_project
from app.limits import add_spend, add_user_spend, check_action, check_budget, check_login, check_user_budget, client_ip, today_spend, user_today_spend
from app.media import media_url, sign_media_path, strip_media_query, verify_media_token
from app.pipeline import _is_reasoning_model, fetch_bytes_capped, fetch_html, gallery_urls, is_public_http_url, parse_page, safe_client, sanitize_html, style_image_prompt, text_client
from app.runtime import OPENROUTER_BASE_URL, mask, migrate_plaintext_secrets, runtime_config, set_runtime
from app.version import __version__
from app.bulk_import import BulkCSVError, MAX_BULK_CSV_BYTES, parse_bulk_csv, split_bulk_values

logger = logging.getLogger(__name__)
from app.prompts import (
    BASE_STYLE_NAME,
    PODIUM_NEGATIVE_PROMPT,
    PODIUM_STYLE_NAME,
    PODIUM_STYLE_PROMPT,
    PODIUM3D_STYLE_NAME,
    PODIUM3D_STYLE_PROMPT,
    PODIUM360_STYLE_NAME,
    PODIUM360_STYLE_PROMPT,
    PODIUMSCROLL_STYLE_NAME,
    PODIUMSCROLL_STYLE_PROMPT,
    SHOWCASE_DARK_STYLE_NAME,
    SHOWCASE_DARK_STYLE_PROMPT,
    PODIUM360DARK_STYLE_NAME,
    PODIUM360DARK_STYLE_PROMPT,
    LICENSE_COMMENT,
    SHOWCASE_FEATURE_PROMPT,
    SHOWCASE_HERO_PROMPT,
    SHOWCASE_NEGATIVE_PROMPT,
    SHOWCASE_STYLE_NAME,
    SHOWCASE_STYLE_PROMPT,
    DEFAULT_FEATURE_PROMPT,
    DEFAULT_HERO_PROMPT,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_STYLE_PROMPT,
    ENGINEERING_FEATURE_PROMPT,
    ENGINEERING_HERO_PROMPT,
    ENGINEERING_NEGATIVE_PROMPT,
    ENGINEERING_STYLE_NAME,
    ENGINEERING_STYLE_PROMPT,
)

APP_VERSION = __version__

Path(settings.media_dir).mkdir(parents=True, exist_ok=True)


MANAGED_STYLES = [
    {
        'name': BASE_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Керований базовий стиль ARTLINE: цілісний дизайн, корисний SEO/GEO-текст і правдиві product-first зображення',
            'prompt': DEFAULT_STYLE_PROMPT,
            'hero_prompt': DEFAULT_HERO_PROMPT,
            # Empty on purpose: the Feature image is a real gallery photo, not a
            # generated one. AI editing kept drifting into a different product.
            'feature_prompt': '',
            'negative_prompt': DEFAULT_NEGATIVE_PROMPT,
            'score_json': json.dumps({'consistency': 98, 'readability': 98, 'brand_fit': 98}),
        },
    },
    {
        'name': ENGINEERING_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Керований інженерний стиль ARTLINE для технічних категорій: цифри з одиницями, підтверджені конструктивні рішення та реальні межі застосування',
            'prompt': ENGINEERING_STYLE_PROMPT,
            'hero_prompt': ENGINEERING_HERO_PROMPT,
            # Empty on purpose: the Feature image is a real gallery photo, not a
            # generated one. AI editing kept drifting into a different product.
            'feature_prompt': '',
            'negative_prompt': ENGINEERING_NEGATIVE_PROMPT,
            'score_json': json.dumps({'consistency': 98, 'readability': 98, 'brand_fit': 98}),
        },
    },
    {
        'name': SHOWCASE_STYLE_NAME,
        'default': True,
        'values': {
            'description': 'Іміджевий формат на реальних фото галереї: темний Hero-кадр, великі числа, чергування темних і світлих секцій. Для флагманських товарів із багатою галереєю.',
            'prompt': SHOWCASE_STYLE_PROMPT,
            'hero_prompt': SHOWCASE_HERO_PROMPT,
            'feature_prompt': SHOWCASE_FEATURE_PROMPT,
            'negative_prompt': SHOWCASE_NEGATIVE_PROMPT,
        },
    },
    {
        'name': PODIUM_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Showcase без темного Hero: світла «сцена» з великим неушкодженим рендером товару і м\'якою тінню. Не генерує AI-зображень — найдешевший преміальний стиль.',
            'prompt': PODIUM_STYLE_PROMPT,
            # No AI imagery at all: the stage uses the real product render, the
            # feature slot uses a real gallery frame. Image cost is zero.
            'hero_prompt': '',
            'feature_prompt': '',
            'negative_prompt': PODIUM_NEGATIVE_PROMPT,
        },
    },
    {
        'name': PODIUM3D_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Подіум, де товар ОБЕРТАЄТЬСЯ: справжнє CSS-3D «монетне» обертання реального фото на світлій сцені. Нуль AI-зображень; анімацію вставляє сервер.',
            'prompt': PODIUM3D_STYLE_PROMPT,
            'hero_prompt': '',
            'feature_prompt': '',
            'negative_prompt': PODIUM_NEGATIVE_PROMPT,
        },
    },
    {
        'name': PODIUM360_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Справжнє 360°: завантажте серію кадрів по колу в діалозі створення і позначте «360-серія» — сервер збере покадрове обертання (hover ставить на паузу). Без серії поводиться як Podium 3D.',
            'prompt': PODIUM360_STYLE_PROMPT,
            'hero_prompt': '',
            'feature_prompt': '',
            'negative_prompt': PODIUM_NEGATIVE_PROMPT,
        },
    },
    {
        'name': PODIUMSCROLL_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Обертання, привʼязане до СКРОЛУ: поки покупець гортає сторінку, товар прокручується по колу (Chrome/Edge/Safari; інші бачать автоплей). Кадри — ті самі, що для 3D 360.',
            'prompt': PODIUMSCROLL_STYLE_PROMPT,
            'hero_prompt': '',
            'feature_prompt': '',
            'negative_prompt': PODIUM_NEGATIVE_PROMPT,
        },
    },
    {
        'name': SHOWCASE_DARK_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Showcase у повністю темній редакції: жодної світлої секції, ритм — чергування двох темних тонів, акценти й великі числа — ціан. Реальні фото лишаються на білих картках.',
            'prompt': SHOWCASE_DARK_STYLE_PROMPT,
            'hero_prompt': SHOWCASE_HERO_PROMPT,
            'feature_prompt': SHOWCASE_FEATURE_PROMPT,
            'negative_prompt': SHOWCASE_NEGATIVE_PROMPT,
        },
    },
    {
        'name': PODIUM360DARK_STYLE_NAME,
        'default': False,
        'values': {
            'description': 'Темна сцена для 360°-обертання: глибокий темний подіум і ціанове світіння замість тіні. Кадри — ті самі, що для 3D 360; нуль AI-зображень.',
            'prompt': PODIUM360DARK_STYLE_PROMPT,
            'hero_prompt': '',
            'feature_prompt': '',
            'negative_prompt': PODIUM_NEGATIVE_PROMPT,
        },
    },
]


def seed():
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.admin_email))
        if not user:
            db.add(User(email=settings.admin_email, name='Адміністратор', password_hash=hash_password(settings.admin_password), role=Role.admin))
        elif not verify(settings.admin_password, user.password_hash):
            # The UI refuses to change this password precisely because .env owns it,
            # so .env must actually win on every start - otherwise rotating it is a
            # no-op and the message in the UI is a lie.
            user.password_hash = hash_password(settings.admin_password)
            user.active = True
            logger.info('Root admin password synced from ADMIN_PASSWORD')
        for spec in MANAGED_STYLES:
            values = spec['values']
            style = db.scalar(select(Style).where(Style.name == spec['name']))
            if not style:
                # A managed style is only made default when it is first created, so a
                # later manual choice of default is never overwritten on restart.
                if spec['default']:
                    for item in db.scalars(select(Style)).all():
                        item.is_default = False
                style = Style(name=spec['name'], is_default=bool(spec['default']), **values)
                db.add(style)
                db.flush()
                db.add(StyleVersion(style_id=style.id, version=1, prompt=style.prompt, hero_prompt=style.hero_prompt, feature_prompt=style.feature_prompt))
            elif any(getattr(style, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(style, key, value)
                current_version = db.scalar(select(func.max(StyleVersion.version)).where(StyleVersion.style_id == style.id)) or 0
                db.add(StyleVersion(style_id=style.id, version=current_version + 1, prompt=style.prompt, hero_prompt=style.hero_prompt, feature_prompt=style.feature_prompt))
        # The spec default wins as long as the operator has not promoted a CUSTOM
        # style: switching between managed defaults follows the code, a manual
        # custom choice is never overridden.
        managed_names = {spec['name'] for spec in MANAGED_STYLES}
        spec_default_name = next((spec['name'] for spec in MANAGED_STYLES if spec['default']), None)
        current_default = db.scalar(select(Style).where(Style.is_default == True))
        if spec_default_name and current_default is not None and current_default.name in managed_names and current_default.name != spec_default_name:
            wanted = db.scalar(select(Style).where(Style.name == spec_default_name))
            if wanted:
                current_default.is_default = False
                wanted.is_default = True
        # Never leave the installation without a default style.
        if not db.scalar(select(Style).where(Style.is_default == True)):
            fallback = db.scalar(select(Style).where(Style.name == ENGINEERING_STYLE_NAME)) or db.scalar(select(Style))
            if fallback:
                fallback.is_default = True
        db.commit()


def check_secrets():
    """Refuse to serve with secrets that are published in this repository."""
    for warning in settings.warn_secrets():
        logger.warning('SECURITY: %s', warning)
    problems = settings.insecure_secrets()
    if problems:
        listed = '\n  - '.join(problems)
        raise RuntimeError(
            'Відмова стартувати з незміненими секретами:\n  - ' + listed +
            '\n\nЦі значення лежать у публічному репозиторії: з ними будь-хто підпише собі токен '
            'адміністратора. Згенеруйте нові у .env на сервері:\n'
            '  JWT_SECRET=$(openssl rand -base64 48)\n'
            '  ADMIN_PASSWORD=$(openssl rand -base64 18)\n'
            'і перезапустіть: docker compose up -d --force-recreate'
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_secrets()
    ensure_schema()
    # Alembic owns the table layout from here on. create_all stays as a safety net
    # for tables that exist in models but predate the migration chain - it never
    # alters existing tables, so the two cannot fight.
    run_migrations()
    Base.metadata.create_all(engine)
    seed()
    migrate_plaintext_secrets()
    yield


app = FastAPI(title='ARTLINE Rich Studio API', version=APP_VERSION, lifespan=lifespan)
# /media is a verifying endpoint now, not a blind static mount: signed URLs are
# capabilities, unsigned ones are tolerated only in transitional mode.
_MEDIA_NAME = re.compile(r'^[A-Za-z0-9._\-]+$')
# Явний Content-Type за розширенням. Без нього FileResponse кладеться на
# mimetypes, який часто НЕ знає .webp, і Starlette віддає text/plain. Для тієї ж
# origin браузеру байдуже, але при кросс-origin вбудовуванні (сервіс знімків,
# зовнішній редактор) Chromium ріже такий «text/plain як картинку» через ORB
# (net::ERR_BLOCKED_BY_ORB) - саме так губилися hero/feature на експортних PNG.
_MEDIA_TYPES = {
    '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml',
    '.avif': 'image/avif', '.bmp': 'image/bmp',
}


@app.get('/media/{project_id}/{filename}')
def media_file(project_id: str, filename: str, t: str = ''):
    if not _MEDIA_NAME.fullmatch(project_id) or not _MEDIA_NAME.fullmatch(filename) or '..' in filename:
        raise HTTPException(404, 'Not found')
    path = f'/media/{project_id}/{filename}'
    if not verify_media_token(path, t):
        if settings.media_signing == 'strict':
            raise HTTPException(403, 'Посилання на зображення без дійсного підпису')
        logger.warning('Unsigned media hit (transitional): %s', path)
    file_path = (Path(settings.media_dir) / project_id / filename).resolve()
    media_root = Path(settings.media_dir).resolve()
    if media_root not in file_path.parents or not file_path.is_file():
        raise HTTPException(404, 'Not found')
    media_type = _MEDIA_TYPES.get(file_path.suffix.lower())
    # nosniff безпечний лише коли тип правильний: інакше ORB діяв би ще жорсткіше.
    headers = {'X-Content-Type-Options': 'nosniff'} if media_type else None
    return FileResponse(file_path, media_type=media_type, headers=headers)


class Login(BaseModel): email: str; password: str
class RegisterIn(BaseModel): token: str; name: str = Field(min_length=2, max_length=120); password: str = Field(min_length=8, max_length=200)
class InviteIn(BaseModel): email: str; role: Role = Role.viewer
class UserUpdate(BaseModel): role: Role | None = None; active: bool | None = None; name: str | None = None; daily_budget_usd: float | None = Field(default=None, ge=0, le=10000)
class UserPasswordIn(BaseModel): password: str = Field(min_length=8, max_length=200)
class ClientErrorIn(BaseModel):
    text: str = Field(max_length=2000)
    url: str = Field(default='', max_length=500)
    agent: str = Field(default='', max_length=300)
class SecretsIn(BaseModel):
    llm_provider: str | None = None
    local_base_url: str | None = None
    local_api_key: str | None = None
    local_text_models: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_text_model: str | None = None
class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    role: Role = Role.viewer
class ProbeIn(BaseModel):
    source_url: HttpUrl
class AdoptItem(BaseModel):
    project_id: str
    label: str
class TranslateIn(BaseModel):
    language: str = Field(min_length=2, max_length=10)
class ProjectIn(BaseModel):
    name: str = Field(default='', max_length=300)
    source_url: HttpUrl
    style_id: str | None = Field(default=None, max_length=200)
    languages: list[str] = Field(default_factory=lambda: ['ua', 'ru'], max_length=10)
    variants: list[str] = Field(default_factory=lambda: ['desktop', 'mobile'], max_length=10)
    text_model: str | None = Field(default=None, max_length=200)
    image_model: str | None = Field(default=None, max_length=200)
    image_quality: str = Field(default='medium', max_length=20)
    custom_hero_url: str = Field(default='', max_length=4096)
    custom_feature_url: str = Field(default='', max_length=4096)
    gallery: list[str] = Field(default_factory=list, max_length=10)
    reuse_images_from: str = ''
    reuse_labels: list[str] = Field(default_factory=list, max_length=10)
    adopt_images: list[AdoptItem] = Field(default_factory=list, max_length=10)
    uploads: list[str] = Field(default_factory=list, max_length=200)
    # URL із uploads, призначений головним Hero / Feature (порожньо = генерувати AI).
    upload_hero: str = ''
    upload_feature: str = ''
    # 360-серія: усі uploads стають кадрами обертання (за порядком), а не галереєю.
    uploads_360: bool = False
class BulkProjectImportIn(BaseModel):
    csv_text: str = Field(min_length=1, max_length=MAX_BULK_CSV_BYTES)
    style_id: str | None = Field(default=None, max_length=200)
    languages: list[str] = Field(default_factory=lambda: ['ua', 'ru'], max_length=10)
    variants: list[str] = Field(default_factory=lambda: ['desktop', 'mobile'], max_length=10)
    text_model: str | None = Field(default=None, max_length=200)
    image_model: str | None = Field(default=None, max_length=200)
    image_quality: str = Field(default='medium', max_length=20)
    skip_existing: bool = True
    validate_only: bool = True
    # Returned by the preview and required for the paid commit. Reusing it is
    # an idempotent replay, including after a lost HTTP response.
    batch_id: str = Field(default='', max_length=100, pattern=r'^$|^bulk-[0-9a-f]{16,64}$')
class StyleIn(BaseModel):
    name: str
    description: str = ''
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
    score: dict = Field(default_factory=dict)
    preview_html: str = ''
    golden_html: str = ''
    is_default: bool = False
class StyleGenerateIn(BaseModel):
    name: str = 'Новий стиль'
    brief: str = ''
    reference_url: str = ''
    model: str | None = None
class StyleImproveIn(BaseModel):
    instructions: str = ''
    model: str | None = None
class StylePreviewIn(BaseModel):
    sample_project_id: str = ''
    variant: str = 'desktop'
class StyleDryRunIn(BaseModel):
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
    variant: str = 'desktop'
    sample_project_id: str = ''
class StyleAnalyzeIn(BaseModel):
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
class HtmlIn(BaseModel): html: str
class ReviewIn(BaseModel):
    decision: str
    comment: str = ''
    checklist: dict[str, bool] = Field(default_factory=dict)
class RerunIn(BaseModel):
    style_id: str | None = None
    languages: list[str] | None = None
    variants: list[str] | None = None
    reuse_images: bool = False
class CriticIn(BaseModel):
    auto_fix: bool = False
    # Платний AI-рецензент: вартість токенів додається до вартості проєкту.
    llm: bool = False
class QueueIn(BaseModel):
    action: str


LANGUAGE_CODE_RE = re.compile(r'^[A-Za-z]{2,3}(?:-[A-Za-z]{2})?$')

_CLIENT_ERROR_WINDOW_SECONDS = 300
_CLIENT_ERROR_MAX = 5
_client_error_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit_client_error(identifier: str) -> bool:
    now = time.time()
    hits = [t for t in _client_error_hits[identifier] if now - t < _CLIENT_ERROR_WINDOW_SECONDS]
    _client_error_hits[identifier] = hits
    if len(hits) >= _CLIENT_ERROR_MAX:
        return False
    hits.append(now)
    return True


# Login throttling moved to app.limits: Redis-backed, per-email AND per-IP,
# survives restarts. The in-memory client-error cap stays local on purpose.


def normalize_languages(values: list[str]) -> list[str]:
    """Accept common ISO/BCP-47-like language codes without a DB migration."""
    normalized = []
    for raw in values:
        code = str(raw or '').strip().replace('_', '-')
        if not code or not LANGUAGE_CODE_RE.fullmatch(code):
            continue
        parts = code.split('-', 1)
        code = parts[0].lower() + (f'-{parts[1].upper()}' if len(parts) == 2 else '')
        if code not in normalized:
            normalized.append(code)
    if len(normalized) > 10:
        raise HTTPException(400, 'За один запуск можна обрати не більше 10 мов')
    return normalized


def require_roles(*roles):
    def dep(user=Depends(current)):
        if user.role not in roles:
            raise HTTPException(403, 'Недостатньо прав')
        return user
    return dep


def audit(db, user, action, entity_type='', entity_id='', metadata=None):
    db.add(AuditLog(user_id=getattr(user, 'id', None), action=action, entity_type=entity_type, entity_id=entity_id, metadata_json=json.dumps(metadata or {}, ensure_ascii=False)))


def is_root_admin(x) -> bool:
    """The account seeded from ADMIN_EMAIL. It is managed via .env, not the UI."""
    return (x.email or '').strip().lower() == (settings.admin_email or '').strip().lower()


def user_dict(x):
    try:
        overrides = json.loads(getattr(x, 'permissions_json', None) or '{}')
    except Exception:
        overrides = {}
    return {'id': x.id, 'email': x.email, 'name': x.name, 'role': x.role.value, 'active': x.active, 'is_root': is_root_admin(x),
            'daily_budget_usd': float(getattr(x, 'daily_budget_usd', 0) or 0), 'today_spend_usd': round(user_today_spend(x.id), 4),
            'permissions': sorted(effective_perms(x)),
            'granted': sorted(overrides.get('grant') or []), 'revoked': sorted(overrides.get('revoke') or []),
            'created_at': x.created_at, 'last_login_at': x.last_login_at, 'shots_enabled': bool(settings.shots_url)}
def style_dict(x, usage=None): return {'id': x.id, 'name': x.name, 'description': x.description, 'prompt': x.prompt, 'hero_prompt': x.hero_prompt, 'feature_prompt': x.feature_prompt, 'negative_prompt': x.negative_prompt, 'score': json.loads(x.score_json or '{}'), 'preview_html': x.preview_html, 'golden_html': getattr(x, 'golden_html', '') or '', 'has_golden': bool((getattr(x, 'golden_html', '') or '').strip()), 'is_default': x.is_default, 'usage_count': usage if usage is not None else None}
def artifact_dict(x): return {'id': x.id, 'language': x.language, 'variant': x.variant, 'html': x.html, 'version': x.version, 'created_at': x.created_at, 'fallback_reason': getattr(x, 'fallback_reason', '') or '', 'run_index': getattr(x, 'run_index', 1) or 1}
def project_dict(p, full=False, style_name=''):
    try:
        product = json.loads(p.product_json or '{}')
    except Exception:
        product = {}
    try:
        breakdown = json.loads(getattr(p, 'cost_breakdown_json', None) or '{}')
    except Exception:
        breakdown = {}
    try:
        runs = json.loads(getattr(p, 'runs_json', None) or '[]')
    except Exception:
        runs = []
    r = {'id': p.id, 'name': p.name, 'source_url': p.source_url, 'style_id': p.style_id, 'style_name': style_name, 'owner_id': p.owner_id, 'status': p.status.value, 'stage': p.stage, 'progress': p.progress,
         'lifetime_cost': float(getattr(p, 'lifetime_cost', 0) or 0), 'run_index': getattr(p, 'run_index', 1) or 1, 'runs': runs,
         'languages': [x for x in p.languages.split(',') if x], 'variants': [x for x in p.variants.split(',') if x], 'text_model': p.text_model, 'image_model': p.image_model, 'image_quality': p.image_quality,
         'custom_hero_url': p.custom_hero_url, 'custom_feature_url': p.custom_feature_url, 'product_category': p.product_category, 'sku': str(product.get('sku') or ''), 'cost_breakdown': breakdown, 'error': p.error, 'duration_seconds': p.duration_seconds, 'input_tokens': p.input_tokens, 'output_tokens': p.output_tokens,
         'image_count': p.image_count, 'text_request_count': p.text_request_count, 'image_request_count': p.image_request_count, 'text_cost': p.text_cost, 'image_cost': p.image_cost, 'estimated_cost': p.estimated_cost,
         'created_at': p.created_at, 'started_at': p.started_at, 'finished_at': p.finished_at}
    if full:
        r['product_json'] = p.product_json; r['source_images'] = p.source_images
        r['artifacts'] = [artifact_dict(x) for x in sorted(p.artifacts, key=lambda a: (a.language, a.variant, a.version))]
    return r


@app.get('/health')
def health(): return {'status': 'ok'}  # версія лише в /api/system: анонім не мусить знати білд


@app.post('/api/auth/login')
def login(request: Request, payload: Login, db: Session = Depends(get_db)):
    check_login((payload.email or '').strip().lower() or 'unknown', client_ip(request))
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify(payload.password, user.password_hash): raise HTTPException(401, 'Неправильний email або пароль')
    if not user.active: raise HTTPException(403, 'Обліковий запис деактивовано')
    user.last_login_at = datetime.utcnow(); audit(db, user, 'auth.login', 'user', user.id); db.commit()
    return {'access_token': token(user), 'token_type': 'bearer'}


@app.post('/api/auth/register')
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_password_registration:
        raise HTTPException(403, 'Реєстрація паролем вимкнена: увійдіть через GitHub або Google — '
                                 'обліковий запис створиться автоматично за запрошенням')
    h = hashlib.sha256(payload.token.encode()).hexdigest(); inv = db.scalar(select(Invite).where(Invite.token_hash == h))
    if not inv or inv.accepted_at or inv.expires_at < datetime.utcnow(): raise HTTPException(400, 'Запрошення недійсне або прострочене')
    if db.scalar(select(User).where(User.email == inv.email)): raise HTTPException(409, 'Користувач уже існує')
    user = User(email=inv.email, name=payload.name, password_hash=hash_password(payload.password), role=inv.role, active=True)
    db.add(user); inv.accepted_at = datetime.utcnow(); db.flush(); audit(db, user, 'auth.register', 'user', user.id); db.commit()
    return {'access_token': token(user), 'token_type': 'bearer'}


# --- GitHub OAuth ------------------------------------------------------------
# Вхід через GitHub НЕ відкриває реєстрацію будь-кому: пускаємо, якщо email з
# GitHub (перевірений) або вже має обліковий запис, або має чинне запрошення -
# тоді запис створюється з роллю із запрошення. Стороння людина з GitHub
# отримує чітку відмову: це внутрішній інструмент.

def _github_redirect_uri(request: Request) -> str:
    return settings.github_callback_url or str(request.base_url).rstrip('/') + '/api/auth/github/callback'


def _github_state_key() -> bytes:
    return hashlib.sha256(b'artline-github:' + settings.jwt_secret.encode()).digest()


def _github_state() -> str:
    ts = str(int(time.time()))
    return ts + '.' + hmac.new(_github_state_key(), ts.encode(), hashlib.sha256).hexdigest()[:32]


def _github_state_ok(value: str) -> bool:
    ts, _, signature = (value or '').partition('.')
    if not ts.isdigit() or not signature:
        return False
    expected = hmac.new(_github_state_key(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(expected, signature) and 0 <= time.time() - int(ts) < 600


@app.get('/api/auth/methods')
def auth_methods():
    """Публічний: які способи входу увімкнено (екран логіна показує кнопки)."""
    return {'github': bool(settings.github_client_id and settings.github_client_secret),
            'google': bool(settings.google_client_id and settings.google_client_secret)}


@app.get('/api/auth/github')
def github_start(request: Request):
    if not (settings.github_client_id and settings.github_client_secret):
        raise HTTPException(404, 'GitHub-вхід не налаштовано')
    return RedirectResponse('https://github.com/login/oauth/authorize?' + urlencode({
        'client_id': settings.github_client_id,
        'redirect_uri': _github_redirect_uri(request),
        'scope': 'user:email',
        'state': _github_state(),
    }))


@app.get('/api/auth/github/callback')
def github_callback(request: Request, code: str = '', state: str = '', db: Session = Depends(get_db)):
    def bounce(message: str):
        return RedirectResponse('/#gh_error=' + quote(message))

    if not (settings.github_client_id and settings.github_client_secret):
        return bounce('GitHub-вхід не налаштовано')
    if not code or not _github_state_ok(state):
        return bounce('GitHub-вхід: недійсний або протермінований запит. Спробуйте ще раз')
    try:
        with safe_client(timeout=15) as http:
            exchange = http.post('https://github.com/login/oauth/access_token',
                                 data={'client_id': settings.github_client_id,
                                       'client_secret': settings.github_client_secret,
                                       'code': code,
                                       'redirect_uri': _github_redirect_uri(request)},
                                 headers={'Accept': 'application/json'})
            access = exchange.json().get('access_token') if exchange.status_code == 200 else None
            if not access:
                return bounce('GitHub не підтвердив авторизацію')
            gh = {'Authorization': f'Bearer {access}', 'Accept': 'application/vnd.github+json'}
            profile = http.get('https://api.github.com/user', headers=gh).json()
            emails_reply = http.get('https://api.github.com/user/emails', headers=gh)
            emails = emails_reply.json() if emails_reply.status_code == 200 else []
    except Exception:
        logger.exception('GitHub OAuth exchange failed')
        return bounce('GitHub недоступний. Спробуйте пізніше')
    verified = [e for e in emails if isinstance(e, dict) and e.get('verified')]
    email = (next((e['email'] for e in verified if e.get('primary')), None)
             or (verified[0]['email'] if verified else '')
             or (profile.get('email') or '')).strip().lower()
    if not email:
        return bounce('GitHub не віддав підтвердженого email. Додайте і підтвердьте email у GitHub')
    return _oauth_complete(db, email, (profile.get('name') or profile.get('login') or ''), 'github',
                           {'github_login': profile.get('login')}, bounce)


def _oauth_complete(db, email: str, name: str, provider: str, meta: dict, bounce):
    """Спільне завершення OAuth-входу: наявний користувач - вхід; чинне
    запрошення на цей email - реєстрація з роллю із запрошення; інакше відмова.
    Реєстрація в системі МОЖЛИВА лише цим шляхом (GitHub/Google), паролем - ні."""
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        invite = db.scalar(select(Invite).where(func.lower(Invite.email) == email,
                                                Invite.accepted_at == None,  # noqa: E711
                                                Invite.expires_at > datetime.utcnow()))
        if invite is None:
            return bounce(f'Для {email} немає запрошення. Попросіть адміністратора запросити вас')
        user = User(email=email, name=name or '', password_hash=hash_password(secrets.token_urlsafe(24)),
                    role=invite.role, active=True)
        db.add(user); invite.accepted_at = datetime.utcnow(); db.flush()
        audit(db, user, f'auth.register_{provider}', 'user', user.id, meta)
    if not user.active:
        return bounce('Обліковий запис деактивовано')
    user.last_login_at = datetime.utcnow(); audit(db, user, f'auth.login_{provider}', 'user', user.id); db.commit()
    return RedirectResponse('/#gh_token=' + quote(token(user)))


def _google_redirect_uri(request: Request) -> str:
    return settings.google_callback_url or str(request.base_url).rstrip('/') + '/api/auth/google/callback'


@app.get('/api/auth/google')
def google_start(request: Request):
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(404, 'Google-вхід не налаштовано')
    return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': settings.google_client_id,
        'redirect_uri': _google_redirect_uri(request),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': _github_state(),
    }))


@app.get('/api/auth/google/callback')
def google_callback(request: Request, code: str = '', state: str = '', db: Session = Depends(get_db)):
    def bounce(message: str):
        return RedirectResponse('/#gh_error=' + quote(message))

    if not (settings.google_client_id and settings.google_client_secret):
        return bounce('Google-вхід не налаштовано')
    if not code or not _github_state_ok(state):
        return bounce('Google-вхід: недійсний або протермінований запит. Спробуйте ще раз')
    try:
        with safe_client(timeout=15) as http:
            exchange = http.post('https://oauth2.googleapis.com/token',
                                 data={'client_id': settings.google_client_id,
                                       'client_secret': settings.google_client_secret,
                                       'code': code,
                                       'grant_type': 'authorization_code',
                                       'redirect_uri': _google_redirect_uri(request)})
            access = exchange.json().get('access_token') if exchange.status_code == 200 else None
            if not access:
                return bounce('Google не підтвердив авторизацію')
            profile = http.get('https://openidconnect.googleapis.com/v1/userinfo',
                               headers={'Authorization': f'Bearer {access}'}).json()
    except Exception:
        logger.exception('Google OAuth exchange failed')
        return bounce('Google недоступний. Спробуйте пізніше')
    email = (profile.get('email') or '').strip().lower()
    if not email or not profile.get('email_verified'):
        return bounce('Google не віддав підтвердженого email')
    return _oauth_complete(db, email, profile.get('name') or '', 'google', {'google_sub': profile.get('sub')}, bounce)


@app.get('/api/me')
def me(user=Depends(current)): return user_dict(user)


@app.get('/api/users')
def users(db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    return [user_dict(x) for x in db.scalars(select(User).order_by(User.created_at.desc())).all()]


@app.post('/api/users')
def create_user(payload: UserCreate, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, 'Користувач уже існує')
    target = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password), role=payload.role, active=True)
    db.add(target); db.flush(); audit(db, user, 'user.create', 'user', target.id, {'email': email, 'role': payload.role.value}); db.commit(); db.refresh(target)
    return user_dict(target)


@app.post('/api/users/invites')
def create_invite(payload: InviteIn, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    if db.scalar(select(User).where(User.email == payload.email)): raise HTTPException(409, 'Користувач уже існує')
    raw = secrets.token_urlsafe(32); inv = Invite(email=payload.email, role=payload.role, token_hash=hashlib.sha256(raw.encode()).hexdigest(), created_by=user.id, expires_at=datetime.utcnow() + timedelta(days=7))
    db.add(inv); audit(db, user, 'invite.create', 'invite', inv.id, {'email': payload.email, 'role': payload.role.value}); db.commit()
    return {'token': raw, 'email': inv.email, 'register_path': f'/register?token={raw}', 'expires_at': inv.expires_at}


@app.patch('/api/users/{user_id}')
def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    target = db.get(User, user_id)
    if not target: raise HTTPException(404, 'Користувача не знайдено')
    updates = payload.model_dump(exclude_none=True)
    if is_root_admin(target) and (updates.get('role') not in (None, Role.admin) or updates.get('active') is False):
        raise HTTPException(400, 'Головного адміністратора не можна деактивувати або змінити його роль')
    if target.id == user.id:
        if updates.get('active') is False:
            raise HTTPException(400, 'Не можна деактивувати власний обліковий запис')
        if 'role' in updates and updates['role'] != Role.admin:
            raise HTTPException(400, 'Не можна зняти з себе роль адміністратора')
    if updates.get('active') is False or (updates.get('role') is not None and updates['role'] != Role.admin):
        remaining = db.scalar(select(func.count(User.id)).where(User.role == Role.admin, User.active == True, User.id != target.id)) or 0
        if target.role == Role.admin and remaining == 0:
            raise HTTPException(400, 'Має залишитися щонайменше один активний адміністратор')
    for k, v in updates.items(): setattr(target, k, v)
    audit(db, user, 'user.update', 'user', target.id, {k: (v.value if isinstance(v, Role) else v) for k, v in updates.items()}); db.commit(); return user_dict(target)


@app.get('/api/permissions')
def permissions_catalog(user=Depends(require_perm('users.manage'))):
    return {
        'permissions': [{'key': k, 'label': v} for k, v in PERMISSIONS.items()],
        'role_defaults': {role.value: sorted(perms) for role, perms in ROLE_DEFAULTS.items()},
    }


class UserPermsIn(BaseModel):
    grant: list[str] = Field(default_factory=list)
    revoke: list[str] = Field(default_factory=list)


@app.patch('/api/users/{user_id}/permissions')
def update_user_permissions(user_id: str, payload: UserPermsIn, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    target = db.get(User, user_id)
    if not target: raise HTTPException(404, 'Користувача не знайдено')
    if is_root_admin(target): raise HTTPException(400, 'Права головного адміністратора змінювати не можна')
    grant = [p for p in dict.fromkeys(payload.grant) if p in PERMISSIONS]
    revoke = [p for p in dict.fromkeys(payload.revoke) if p in PERMISSIONS and p not in grant]
    # Never let an admin strip their own or the last admin's access to user management.
    if 'users.manage' in revoke and target.role == Role.admin:
        remaining = db.scalar(select(func.count(User.id)).where(User.role == Role.admin, User.active == True, User.id != target.id)) or 0
        if target.id == user.id or remaining == 0:
            raise HTTPException(400, 'Не можна забрати керування користувачами в останнього адміністратора')
    target.permissions_json = json.dumps({'grant': grant, 'revoke': revoke}, ensure_ascii=False)
    audit(db, user, 'user.permissions', 'user', target.id, {'grant': grant, 'revoke': revoke}); db.commit(); db.refresh(target)
    return user_dict(target)


@app.post('/api/users/{user_id}/password')
def reset_user_password(user_id: str, payload: UserPasswordIn, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    target = db.get(User, user_id)
    if not target: raise HTTPException(404, 'Користувача не знайдено')
    if is_root_admin(target):
        raise HTTPException(400, 'Пароль головного адміністратора змінюється лише через ADMIN_PASSWORD у .env на сервері')
    target.password_hash = hash_password(payload.password)
    audit(db, user, 'user.password_reset', 'user', target.id); db.commit(); return {'ok': True}


@app.delete('/api/users/{user_id}')
def delete_user(user_id: str, db: Session = Depends(get_db), user=Depends(require_perm('users.manage'))):
    if user_id == user.id: raise HTTPException(400, 'Не можна видалити власний обліковий запис')
    target = db.get(User, user_id)
    if not target: raise HTTPException(404, 'Користувача не знайдено')
    if is_root_admin(target): raise HTTPException(400, 'Головного адміністратора видалити не можна')
    linked = db.scalar(select(func.count(Project.id)).where(Project.owner_id == target.id)) or 0
    if linked:
        target.active = False
        audit(db, user, 'user.archive', 'user', target.id, {'email': target.email, 'linked_projects': linked}); db.commit()
        return {'ok': True, 'archived': True}
    audit(db, user, 'user.delete', 'user', target.id, {'email': target.email}); db.delete(target); db.commit(); return {'ok': True, 'archived': False}


@app.get('/api/styles')
def styles(db: Session = Depends(get_db), user=Depends(current)):
    counts = dict(db.execute(select(Project.style_id, func.count(Project.id)).group_by(Project.style_id)).all())
    return [style_dict(x, usage=int(counts.get(x.id, 0))) for x in db.scalars(select(Style).order_by(Style.name)).all()]


@app.post('/api/styles')
def create_style(payload: StyleIn, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    if payload.is_default:
        for item in db.scalars(select(Style)).all(): item.is_default = False
    data = payload.model_dump(); score = data.pop('score', {}); preview = sanitize_html(data.pop('preview_html', ''))
    s = Style(**data, score_json=json.dumps(score, ensure_ascii=False), preview_html=preview); db.add(s); db.flush()
    db.add(StyleVersion(style_id=s.id, version=1, prompt=s.prompt, hero_prompt=s.hero_prompt, feature_prompt=s.feature_prompt, created_by=user.id)); audit(db, user, 'style.create', 'style', s.id); db.commit(); db.refresh(s); return style_dict(s)


@app.put('/api/styles/{style_id}')
def update_style(style_id: str, payload: StyleIn, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    s = db.scalar(select(Style).where(Style.id == style_id).with_for_update())
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    if payload.is_default:
        for item in db.scalars(select(Style)).all(): item.is_default = False
    data = payload.model_dump(); score = data.pop('score', {}); preview = sanitize_html(data.pop('preview_html', ''))
    for k, v in data.items(): setattr(s, k, v)
    s.score_json = json.dumps(score, ensure_ascii=False); s.preview_html = preview
    current_version = db.scalar(select(func.max(StyleVersion.version)).where(StyleVersion.style_id == s.id)) or 0
    db.add(StyleVersion(style_id=s.id, version=current_version + 1, prompt=s.prompt, hero_prompt=s.hero_prompt, feature_prompt=s.feature_prompt, created_by=user.id)); audit(db, user, 'style.update', 'style', s.id); db.commit(); return style_dict(s)


@app.delete('/api/styles/{style_id}')
def delete_style(style_id: str, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    if s.name in {spec['name'] for spec in MANAGED_STYLES}: raise HTTPException(400, f'Керований стиль «{s.name}» видалити не можна')
    if s.is_default: raise HTTPException(400, 'Спершу призначте інший стиль за замовчуванням, потім видаляйте цей')
    name = s.name
    default = db.scalar(select(Style).where(Style.is_default == True)) or db.scalar(select(Style).where(Style.name == BASE_STYLE_NAME))
    reassigned = 0
    if default:
        for p in db.scalars(select(Project).where(Project.style_id == style_id)).all():
            p.style_id = default.id
            reassigned += 1
    db.execute(sa_delete(StyleVersion).where(StyleVersion.style_id == style_id))
    db.delete(s)
    audit(db, user, 'style.delete', 'style', style_id, {'name': name, 'reassigned_projects': reassigned}); db.commit()
    return {'deleted': True, 'reassigned_projects': reassigned}


# Fixed demo product so every style can be previewed without a real project.
DEMO_PRODUCT = {
    'name': '3D принтер Bambu Lab A1 Mini',
    'brand': 'Bambu Lab',
    'sku': 'PF002-M-EU',
    'category': '3D принтер',
    'description': 'Компактний FDM 3D-принтер для дому та майстерні: швидкість друку до 500 мм/с, автоматичне калібрування столу перед кожним друком і підтримка PLA, PETG та TPU.',
    'features': ['Автоматичне калібрування столу перед кожним друком', 'Швидкість друку до 500 мм/с', 'Підтримка PLA, PETG, TPU'],
    'specs': [
        {'name': 'Технологія друку', 'value': 'FDM'},
        {'name': 'Область друку', 'value': '180 × 180 × 180 мм'},
        {'name': 'Швидкість друку', 'value': 'до 500 мм/с'},
        {'name': 'Температура сопла', 'value': 'до 300 °C'},
        {'name': 'Підключення', 'value': 'Wi-Fi, Bambu Handy'},
        {'name': 'Вага', 'value': '5.5 кг'},
    ],
}


@app.get('/api/styles/{style_id}/preview')
def style_preview(style_id: str, db: Session = Depends(get_db), user=Depends(current)):
    """Saved preview if the style has one, otherwise an instant offline demo."""
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    if s.preview_html:
        return {'html': s.preview_html, 'source': 'saved'}
    from types import SimpleNamespace
    from app.pipeline import _deterministic_html
    demo = _deterministic_html(DEMO_PRODUCT, SimpleNamespace(prompt=s.prompt), 'ua', 'desktop', '', '')
    return {'html': sanitize_html(demo), 'source': 'demo'}


@app.post('/api/styles/{style_id}/preview')
def style_preview_generate(style_id: str, payload: StylePreviewIn | None = None, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    check_action(user.id, 'style_ai', 4); check_budget(); check_user_budget(user)
    """Real AI example for this style. On a chosen finished project's data if
    given (representative), else the fixed demo product."""
    from types import SimpleNamespace
    from app.pipeline import generate_html
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    payload = payload or StylePreviewIn()
    variant = payload.variant if payload.variant in ('desktop', 'mobile') else 'desktop'
    product, sample = dict(DEMO_PRODUCT), ''
    if payload.sample_project_id:
        proj = db.get(Project, payload.sample_project_id)
        if proj and proj.product_json:
            try:
                product = json.loads(proj.product_json) or product
                sample = proj.name
            except Exception:
                pass
    style_ns = SimpleNamespace(prompt=s.prompt, hero_prompt=s.hero_prompt, feature_prompt=s.feature_prompt, negative_prompt=s.negative_prompt)
    html, _i, _o, reason = generate_html(product, style_ns, 'ua', variant, '', '', settings.openai_text_model)
    s.preview_html = sanitize_html(html)
    audit(db, user, 'style.preview', 'style', s.id, {'ai': not reason, 'sample': sample, 'variant': variant})
    db.commit()
    return {'html': s.preview_html, 'source': 'demo' if reason else 'generated', 'note': reason or '', 'sample_name': sample, 'variant': variant}


@app.get('/api/styles/{style_id}/versions')
def style_versions(style_id: str, db: Session = Depends(get_db), user=Depends(current)):
    rows = db.scalars(select(StyleVersion).where(StyleVersion.style_id == style_id).order_by(StyleVersion.version.desc())).all()
    return [{'id': x.id, 'version': x.version, 'prompt': x.prompt, 'hero_prompt': x.hero_prompt, 'feature_prompt': x.feature_prompt, 'created_at': x.created_at} for x in rows]


@app.get('/api/styles/{style_id}/stats')
def style_stats(style_id: str, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Реальна якість стилю з даних, а не лінт промпта.

    Все рахується з проєктів цього стилю: скільки зроблено, скільки на рев'ю
    схвалено, як часто правлять HTML руками, як часто спрацьовує аварійний
    шаблон, і середня оцінка платного AI-рецензента. Це замінює вигаданий скор
    на цикл зворотного звʼязку «поправив промпт -> побачив, чи виріс approve».
    """
    style = db.get(Style, style_id)
    if not style: raise HTTPException(404, 'Стиль не знайдено')
    projects = db.scalars(select(Project).where(Project.style_id == style_id)).all()
    ids = [p.id for p in projects]
    finished = [p for p in projects if p.status in (Status.review, Status.approved, Status.done, Status.changes_requested)]
    decisions = defaultdict(set)
    if ids:
        for r in db.scalars(select(Review).where(Review.project_id.in_(ids))).all():
            decisions[r.project_id].add(r.decision)
    reviewed = [p for p in projects if decisions.get(p.id)]
    approved = [p for p in reviewed if 'approve' in decisions[p.id]]
    manual_edits = (db.scalar(select(func.count(Artifact.id)).where(
        Artifact.version > 1, Artifact.created_by.isnot(None), Artifact.project_id.in_(ids))) or 0) if ids else 0
    fallback_hits = (db.scalar(select(func.count(Artifact.id)).where(
        Artifact.fallback_reason != '', Artifact.project_id.in_(ids))) or 0) if ids else 0
    total_artifacts = (db.scalar(select(func.count(Artifact.id)).where(Artifact.project_id.in_(ids))) or 0) if ids else 0
    llm_scores = [r.score for r in db.scalars(select(CriticReport).where(
        CriticReport.project_id.in_(ids), CriticReport.critic_type == 'llm')).all()] if ids else []
    return {
        'usage_count': len(projects),
        'projects': len(projects),
        'finished': len(finished),
        'reviewed': len(reviewed),
        'approved': len(approved),
        'approve_rate': round(len(approved) / len(reviewed) * 100) if reviewed else None,
        'manual_edits': manual_edits,
        'fallback_hits': fallback_hits,
        'fallback_rate': round(fallback_hits / total_artifacts * 100) if total_artifacts else 0,
        'llm_avg': round(sum(llm_scores) / len(llm_scores)) if llm_scores else None,
        'llm_reviews': len(llm_scores),
    }


@app.post('/api/styles/dry-run')
def style_dry_run(payload: StyleDryRunIn, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Точний текст, що піде в модель - БЕЗ платного виклику. Плюс перелік
    механічних гарантій, які застосуються після генерації."""
    from types import SimpleNamespace
    from app.pipeline import build_prompt, POST_GENERATION_GUARANTEES
    product = dict(DEMO_PRODUCT)
    sample = ''
    if payload.sample_project_id:
        proj = db.get(Project, payload.sample_project_id)
        if proj and proj.product_json:
            try:
                product = json.loads(proj.product_json) or product
                sample = proj.name
            except Exception:
                pass
    variant = payload.variant if payload.variant in ('desktop', 'mobile') else 'desktop'
    style_ns = SimpleNamespace(prompt=payload.prompt, hero_prompt=payload.hero_prompt,
                               feature_prompt=payload.feature_prompt, negative_prompt=payload.negative_prompt)
    text = build_prompt(product, style_ns, 'ua', variant, '/media/приклад/hero.webp', '/media/приклад/feature.webp')
    return {'prompt': text, 'chars': len(text), 'sample_name': sample,
            'guarantees': POST_GENERATION_GUARANTEES, 'variant': variant}


@app.get('/api/styles/sample-products')
def style_sample_products(db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Завершені проєкти, чиї дані можна взяти для превʼю/dry-run стилю."""
    rows = db.scalars(select(Project).where(
        Project.status.in_([Status.review, Status.approved, Status.done])
    ).order_by(Project.finished_at.desc()).limit(30)).all()
    out = []
    for p in rows:
        if not p.product_json:
            continue
        # style_id дає фронту згрупувати: товари ЦЬОГО стилю мають справжній
        # прогін (його можна показати без витрат), решта - лише дані для превʼю.
        out.append({'id': p.id, 'name': p.name, 'style_id': p.style_id})
    return out


@app.get('/api/styles/{style_id}/real-example')
def style_real_example(style_id: str, project_id: str, variant: str = 'desktop',
                       db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Справжня згенерована сторінка проєкту цього стилю - БЕЗ витрат.

    Коли товар уже проходив саме цей стиль, немає сенсу платити за новий приклад:
    показуємо реальну останню видачу. Якщо проєкт зроблено іншим стилем -
    відмовляємо, щоб превʼю не брехало про стиль."""
    s = db.get(Style, style_id)
    if not s:
        raise HTTPException(404, 'Стиль не знайдено')
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, 'Проєкт не знайдено')
    if p.style_id != style_id:
        raise HTTPException(400, 'Цей проєкт зроблено іншим стилем - справжнього прогону цього стилю в нього немає')
    variant = variant if variant in ('desktop', 'mobile') else 'desktop'
    arts = db.scalars(select(Artifact).where(Artifact.project_id == p.id).order_by(Artifact.version)).all()
    if not arts:
        raise HTTPException(409, 'У проєкті ще немає готового HTML')
    pool = [a for a in arts if a.variant == variant] or arts
    ua = [a for a in pool if a.language == 'ua']
    art = max(ua or pool, key=lambda a: (getattr(a, 'run_index', 1) or 1, a.version))
    return {'html': art.html, 'source': 'real', 'sample_name': p.name,
            'variant': art.variant, 'language': art.language,
            'run_index': getattr(art, 'run_index', 1) or 1, 'version': art.version}


@app.post('/api/styles/{style_id}/golden')
def style_set_golden(style_id: str, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Закріпити ПОТОЧНИЙ AI-приклад стилю як еталон формату (few-shot).

    Далі кожна генерація цим стилем бачить приклад ідеального виводу - модель
    краще тримає структуру. Кнопка «прибрати» очищає поле."""
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    if not (s.preview_html or '').strip():
        raise HTTPException(409, 'Спершу згенеруйте AI-приклад — саме він стає еталоном')
    s.golden_html = s.preview_html
    audit(db, user, 'style.golden_set', 'style', s.id); db.commit()
    return {'has_golden': True}


@app.delete('/api/styles/{style_id}/golden')
def style_clear_golden(style_id: str, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    s.golden_html = ''
    audit(db, user, 'style.golden_clear', 'style', s.id); db.commit()
    return {'has_golden': False}


class StyleABIn(BaseModel):
    prompt_a: str
    prompt_b: str
    variant: str = 'desktop'
    sample_project_id: str = ''


@app.post('/api/styles/{style_id}/ab')
def style_ab(style_id: str, payload: StyleABIn, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """A/B: два промпти на ОДНОМУ товарі, поруч. Два платні прогони - тому
    подвійний бюджет-чек. Картинки не генеруються (порожні URL) - порівнюємо
    саме текст і верстку."""
    from types import SimpleNamespace
    from app.pipeline import generate_html
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    check_action(user.id, 'style_ab', 3); check_budget(); check_user_budget(user)
    variant = payload.variant if payload.variant in ('desktop', 'mobile') else 'desktop'
    product, sample = dict(DEMO_PRODUCT), ''
    if payload.sample_project_id:
        proj = db.get(Project, payload.sample_project_id)
        if proj and proj.product_json:
            try:
                product = json.loads(proj.product_json) or product
                sample = proj.name
            except Exception:
                pass
    golden = getattr(s, 'golden_html', '')
    def run(prompt_text):
        ns = SimpleNamespace(prompt=prompt_text, hero_prompt=s.hero_prompt, feature_prompt=s.feature_prompt,
                             negative_prompt=s.negative_prompt, golden_html=golden)
        html, _i, _o, reason = generate_html(product, ns, 'ua', variant, '', '', settings.openai_text_model)
        return {'html': sanitize_html(html), 'fallback': bool(reason), 'reason': reason or ''}
    result = {'a': run(payload.prompt_a), 'b': run(payload.prompt_b), 'sample_name': sample, 'variant': variant}
    audit(db, user, 'style.ab', 'style', s.id, {'sample': sample, 'variant': variant}); db.commit()
    return result


@app.post('/api/styles/analyze')
def analyze_style(payload: StyleAnalyzeIn, user=Depends(require_perm('style.manage'))):
    text = ' '.join([payload.prompt, payload.hero_prompt, payload.feature_prompt, payload.negative_prompt]).strip()
    length = len(text)
    required = ['inline css', 'responsive', 'desktop', 'mobile', 'hero', 'section', 'product', 'facts']
    coverage = sum(1 for key in required if key in text.lower())
    consistency = min(100, 52 + coverage * 5 + min(8, length // 1500))
    readability = min(100, 58 + (10 if 'typography' in text.lower() else 0) + (10 if 'line-height' in text.lower() else 0) + min(12, length // 1000))
    brand_fit = min(100, 50 + (18 if 'artline' in text.lower() else 0) + (12 if '#19bcc9' in text.lower() else 0) + (10 if '#101010' in text.lower() else 0) + min(10, length // 1800))
    issues = []
    if length < 1200: issues.append('Style Prompt надто короткий для стабільної генерації.')
    # Image generation is enabled either by the dedicated prompt field or by a
    # [HERO_IMAGE]/[FEATURE_IMAGE] block inside the main Style Prompt.
    hero_enabled = bool(payload.hero_prompt.strip() or style_image_prompt(payload.prompt, 'HERO_IMAGE'))
    feature_enabled = bool(payload.feature_prompt.strip() or style_image_prompt(payload.prompt, 'FEATURE_IMAGE'))
    if not hero_enabled: issues.append('Генерацію Hero вимкнено: немає ні Hero Prompt, ні блоку [HERO_IMAGE] у Style Prompt.')
    if not feature_enabled: issues.append('Генерацію Feature вимкнено: немає ні Feature Prompt, ні блоку [FEATURE_IMAGE] у Style Prompt.')
    if 'mobile' not in text.lower(): issues.append('Немає правил для мобільної версії.')
    if 'facts' not in text.lower() and 'invent' not in text.lower(): issues.append('Правила фактологічної безпеки слабкі або відсутні.')
    return {'score': {'consistency': consistency, 'readability': readability, 'brand_fit': brand_fit}, 'issues': issues, 'ready': min(consistency, readability, brand_fit) >= 70}


@app.get('/api/projects')
def projects(db: Session = Depends(get_db), user=Depends(current)):
    styles_by_id = {x.id: x.name for x in db.scalars(select(Style)).all()}
    return [project_dict(x, style_name=styles_by_id.get(x.style_id, '')) for x in db.scalars(select(Project).order_by(Project.created_at.desc())).all()]


@app.post('/api/projects/{project_id}/translate')
def add_language(project_id: str, body: TranslateIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    check_action(user.id, 'translate', 6); check_budget(); check_user_budget(user)
    """Translate the newest finished variants into one more language.

    Unlike a rerun this touches nothing but copy: no scrape, no images, no master
    regeneration - so it cannot degrade an approved layout and costs only the
    translation tokens.
    """
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, 'Проєкт не знайдено')
    require_project_edit(project, user)
    normalized = normalize_languages([body.language])
    if not normalized:
        raise HTTPException(400, 'Невідомий код мови')
    language = normalized[0]
    existing = {x.strip() for x in (project.languages or '').split(',') if x.strip()}
    if language in existing:
        raise HTTPException(400, f'Мова {language.upper()} вже є у проєкті')
    if not db.scalar(select(func.count(Artifact.id)).where(Artifact.project_id == project.id)):
        raise HTTPException(400, 'У проєкту ще немає готових версій — спершу дочекайтесь генерації')
    audit(db, user, 'project.translate', 'project', project.id, {'language': language})
    db.commit()
    translate_project.delay(project.id, language)
    return {'ok': True, 'language': language}


ADOPTABLE_IMAGE_LABELS = ('product-reference', 'hero-desktop-generated', 'hero-mobile-generated', 'feature-generated', 'hero-custom', 'feature-custom')


def _adopt_images(db: Session, new_project: Project, source_project_id: str, labels: list[str] | None = None) -> int:
    """Copy a sibling project's finished images into a new project.

    Files are physically copied into the new project's media folder: referencing
    the old URLs would tie this project's page to a sibling that anyone may
    delete. Asset rows are cloned with rewritten URLs, so the reuse_images path
    picks them up exactly as if this project had generated them.
    """
    source = db.get(Project, source_project_id)
    if not source or source.source_url != new_project.source_url:
        raise HTTPException(400, 'Готові зображення можна взяти лише з проєкту за цим самим товаром')
    # An explicit selection limits which visuals are taken; the product reference
    # always rides along - regenerating the rejected images needs it as the base.
    wanted = set(labels) if labels else set(ADOPTABLE_IMAGE_LABELS)
    wanted.add('product-reference')
    rows = db.scalars(select(Asset).where(Asset.project_id == source.id, Asset.kind == 'image', Asset.label.in_([l for l in ADOPTABLE_IMAGE_LABELS if l in wanted]))).all()
    adopted = 0
    for asset in rows:
        prefix = f'/media/{source.id}/'
        clean_url = strip_media_query(asset.url)
        new_url = asset.url
        if clean_url.startswith(prefix):
            name = clean_url[len(prefix):]
            media_root = Path(settings.media_dir).resolve()
            src_file = (media_root / source.id / name).resolve()
            # Same traversal guard as the archive: asset URLs are ours, but a
            # poisoned row must not be able to read outside the media root.
            if media_root not in src_file.parents or not src_file.exists():
                continue
            dst_dir = Path(settings.media_dir) / new_project.id
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_dir / name)
            new_url = media_url(new_project.id, name)
        db.add(Asset(project_id=new_project.id, kind='image', label=asset.label, url=new_url, prompt=asset.prompt, model=asset.model, width=asset.width, height=asset.height, cost=0, metadata_json=json.dumps({'adopted_from': source.id}, ensure_ascii=False)))
        if asset.label != 'product-reference':
            adopted += 1
    return adopted



@app.post('/api/projects/probe')
def probe_product_page(payload: ProbeIn, user=Depends(require_perm('project.create'))):
    check_action(user.id, 'probe', 15)
    """Look at the product page before spending anything on it.

    Pure scrape - zero tokens. Returns the detected name and the unique gallery
    frames so the dialog can show what Showcase would be built from, and let the
    operator drop bad frames before the run starts.
    """
    url = str(payload.source_url)
    if not is_public_http_url(url):
        raise HTTPException(400, 'Посилання має бути публічним http(s)-URL')
    try:
        page_html = fetch_html(url)
        _, images, title, _ = parse_page(page_html, url)
    except Exception as exc:
        raise HTTPException(422, f'Не вдалося прочитати сторінку: {str(exc)[:200]}')
    frames = gallery_urls(images, limit=10)
    prior = None
    with SessionLocal() as db:
        # Images are the expensive part of a run. Aggregate per label across ALL
        # recent sibling projects: the newest run may hold only a Feature while
        # the Heroes live two runs back - the operator should get all of them.
        siblings = db.scalars(select(Project).where(Project.source_url == url).order_by(Project.created_at.desc()).limit(10)).all()
        found: dict[str, dict] = {}
        for sibling in siblings:
            assets = db.scalars(select(Asset).where(Asset.project_id == sibling.id, Asset.kind == 'image', Asset.label.in_(ADOPTABLE_IMAGE_LABELS)).order_by(Asset.created_at.desc())).all()
            for asset in assets:
                if asset.label == 'product-reference' or asset.label in found:
                    continue
                found[asset.label] = {'label': asset.label, 'url': asset.url, 'project_id': sibling.id, 'project_name': sibling.name}
        if found:
            order = {label: index for index, label in enumerate(ADOPTABLE_IMAGE_LABELS)}
            prior = {'images': sorted(found.values(), key=lambda x: order.get(x['label'], 99))}
    return {'name': title, 'gallery': frames, 'count': len(frames), 'prior': prior}


def _pick_even(items: list, limit: int) -> list:
    """Рівномірно відібрати limit елементів, зберігши перший і крок по колу."""
    if len(items) <= limit:
        return list(items)
    return [items[round(i * len(items) / limit)] for i in range(limit)]


def _project_values(payload: ProjectIn, db: Session) -> tuple[dict, Style]:
    """Validate and normalize the fields shared by single and bulk creation."""
    source_url = str(payload.source_url)
    if not is_public_http_url(source_url):
        raise HTTPException(400, 'URL товару має бути публічним http(s)-посиланням')
    style = db.get(Style, payload.style_id) if payload.style_id else db.scalar(select(Style).where(Style.is_default == True))
    if not style:
        raise HTTPException(400, 'Немає доступного стилю')
    languages = normalize_languages(payload.languages)
    variants = list(dict.fromkeys(x for x in payload.variants if x in {'desktop', 'mobile'}))
    if not languages or not variants:
        raise HTTPException(400, 'Оберіть щонайменше одну мову та формат')
    for label, value in (('Hero', payload.custom_hero_url.strip()), ('Feature', payload.custom_feature_url.strip())):
        if value and not is_public_http_url(value):
            raise HTTPException(400, f'Власне {label} URL має бути публічним http(s)-посиланням')
    return {
        'name': payload.name.strip() or 'Визначення товару…',
        'source_url': source_url,
        'style_id': style.id,
        'languages': ','.join(languages),
        'variants': ','.join(variants),
        'text_model': (payload.text_model or '').strip() or settings.openai_text_model,
        'image_model': (payload.image_model or '').strip() or settings.openai_image_model,
        'image_quality': payload.image_quality if payload.image_quality in {'low', 'medium', 'high'} else 'medium',
        'custom_hero_url': payload.custom_hero_url.strip(),
        'custom_feature_url': payload.custom_feature_url.strip(),
        'gallery_json': json.dumps([u.strip() for u in payload.gallery if is_public_http_url(u.strip())][:10]),
    }, style


def _new_project_record(payload: ProjectIn, db: Session, user) -> tuple[Project, Style]:
    values, style = _project_values(payload, db)
    project = Project(owner_id=user.id, status=Status.queued, stage='queued', **values)
    db.add(project)
    db.flush()
    return project, style


def _bulk_validation_message(exc: ValidationError) -> str:
    """Turn Pydantic's row error into a concise operator-facing message."""
    messages = []
    for item in exc.errors()[:3]:
        field = '.'.join(str(part) for part in item.get('loc') or [])
        message = str(item.get('msg') or 'некоректне значення')
        messages.append(f'{field}: {message}' if field else message)
    return '; '.join(messages) or 'Некоректні дані рядка'


def _bulk_estimated_cost(values: dict, style: Style) -> float:
    """Conservative pre-flight cost, scaled by requested output pages.

    The 30k/14k baseline is calibrated for the normal two-language,
    desktop+mobile project (four outputs). Larger language matrices add
    translations for every layout, so reserve proportionally above that base.
    """
    input_rate, output_rate = text_rate(values['text_model'])
    languages = [value for value in values['languages'].split(',') if value]
    variants = [value for value in values['variants'].split(',') if value]
    output_count = max(1, len(languages) * len(variants))
    output_factor = max(1.0, output_count / 4.0)
    text_cost = (
        30_000 / 1_000_000 * input_rate
        + 14_000 / 1_000_000 * output_rate
    ) * output_factor
    hero_enabled = bool(style_image_prompt(style.prompt or '', 'HERO_IMAGE') or (style.hero_prompt or '').strip())
    feature_enabled = bool(style_image_prompt(style.prompt or '', 'FEATURE_IMAGE') or (style.feature_prompt or '').strip())
    image_count = len(variants) if hero_enabled and not values['custom_hero_url'] else 0
    if feature_enabled and not values['custom_feature_url']:
        image_count += 1
    return round(text_cost + image_count * image_rate(values['image_model'], values['image_quality']), 6)


def _reserve_project_run(db: Session, user, project: Project, style: Style) -> float:
    """Reserve a conservative run estimate inside the caller's commit lock."""
    values = {
        'languages': project.languages,
        'variants': project.variants,
        'text_model': project.text_model,
        'image_model': project.image_model,
        'image_quality': project.image_quality,
        'custom_hero_url': project.custom_hero_url,
        'custom_feature_url': project.custom_feature_url,
    }
    estimate = _bulk_estimated_cost(values, style)
    _check_bulk_estimated_budget(db, user, estimate)
    queued_at = datetime.utcnow()
    project.reserved_cost = estimate
    project.queued_at = queued_at
    project.started_at = queued_at
    project.finished_at = None
    return estimate


def _check_bulk_estimated_budget(db: Session, user, estimated_cost: float) -> None:
    """Refuse work that cannot fit completed spend plus durable reservations."""
    reserved_global = float(db.scalar(select(func.coalesce(func.sum(Project.reserved_cost), 0.0)).where(
        Project.reserved_cost > 0,
    )) or 0)
    global_cap = float(settings.daily_budget_usd or 0)
    global_spent = today_spend()
    if global_cap > 0 and global_spent + reserved_global + estimated_cost > global_cap + 1e-9:
        remaining = max(0.0, global_cap - global_spent - reserved_global)
        raise HTTPException(
            429,
            f'Пакет оцінено у ${estimated_cost:.2f}, а в денному бюджеті лишилося ${remaining:.2f}. '
            'Зменште CSV або дочекайтеся нового дня',
        )
    user_cap = float(getattr(user, 'daily_budget_usd', 0) or 0)
    user_spent = user_today_spend(user.id)
    reserved_user = float(db.scalar(select(func.coalesce(func.sum(Project.reserved_cost), 0.0)).where(
        Project.reserved_cost > 0,
        Project.owner_id == user.id,
    )) or 0)
    if user_cap > 0 and user_spent + reserved_user + estimated_cost > user_cap + 1e-9:
        remaining = max(0.0, user_cap - user_spent - reserved_user)
        raise HTTPException(
            429,
            f'Пакет оцінено у ${estimated_cost:.2f}, а у вашому ліміті лишилося ${remaining:.2f}. '
            'Зменште CSV або зверніться до адміністратора',
        )


def _lock_bulk_commit(db: Session) -> None:
    """Serialize final imports so skip-existing and budget reservation are atomic."""
    bind = db.get_bind()
    if bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:lock_name))'), {
            'lock_name': f'richstudio-bulk-import:{settings.db_schema}',
        })


def _bulk_request_hash(payload: BulkProjectImportIn) -> str:
    canonical = payload.model_dump(exclude={'batch_id', 'validate_only'}, mode='json')
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _bulk_replay_result(db: Session, audit_row: AuditLog) -> dict:
    """Rebuild the original success response for an idempotent commit retry."""
    try:
        metadata = json.loads(audit_row.metadata_json or '{}')
    except Exception:
        metadata = {}
    records = metadata.get('projects') if isinstance(metadata.get('projects'), list) else []
    project_ids = [str(item.get('id') or '') for item in records if item.get('id')]
    project_rows = db.scalars(select(Project).where(Project.id.in_(project_ids))).all() if project_ids else []
    by_id = {project.id: project for project in project_rows}
    style_ids = {project.style_id for project in project_rows}
    styles = db.scalars(select(Style).where(Style.id.in_(style_ids))).all() if style_ids else []
    style_names = {style.id: style.name for style in styles}
    ordered = [by_id[project_id] for project_id in project_ids if project_id in by_id]
    pending_records = [item for item in records if (
        (project := by_id.get(str(item.get('id') or '')))
        and project.status == Status.queued
        and project.stage == 'dispatch_pending'
    )]
    pending = [{
        'project_id': str(item.get('id') or ''),
        'row': item.get('row'),
        'error': 'Передача воркеру очікує автоматичного повтору.',
    } for item in pending_records]
    return {
        'batch_id': audit_row.entity_id,
        'idempotent_replay': True,
        'validate_only': False,
        'total_rows': int(metadata.get('total_rows') or 0),
        'valid_count': len(records),
        'invalid_count': int(metadata.get('invalid_count') or 0),
        'skipped_count': int(metadata.get('skipped_count') or 0),
        'created_count': len(ordered),
        'queued_count': len(ordered),
        'dispatch_failed_count': len(pending),
        'dispatch_pending_count': len(pending),
        'estimated_cost': float(metadata.get('estimated_cost') or 0),
        'valid_rows': metadata.get('valid_rows') or [],
        'errors': metadata.get('errors') or [],
        'skipped': metadata.get('skipped') or [],
        'projects': [project_dict(project, style_name=style_names.get(project.style_id, '')) for project in ordered],
        'dispatch_failures': pending,
    }


def _bulk_replay_if_exists(db: Session, user, payload: BulkProjectImportIn) -> dict | None:
    prior = db.scalar(select(AuditLog).where(
        AuditLog.user_id == user.id,
        AuditLog.action == 'project.bulk_import',
        AuditLog.entity_type == 'bulk_batch',
        AuditLog.entity_id == payload.batch_id,
    ).order_by(AuditLog.created_at.desc()))
    if not prior:
        return None
    try:
        prior_metadata = json.loads(prior.metadata_json or '{}')
    except Exception:
        prior_metadata = {}
    expected_hash = str(prior_metadata.get('request_hash') or '')
    if not expected_hash or not hmac.compare_digest(expected_hash, _bulk_request_hash(payload)):
        raise HTTPException(409, 'Цей batch_id уже використано з іншим CSV або налаштуваннями')
    return _bulk_replay_result(db, prior)


def _dispatch_project_once(db: Session, project: Project, reuse_images: bool = False) -> bool:
    """Best-effort immediate publish; DB pending state is the durable fallback."""
    try:
        process_project.delay(project.id, reuse_images=reuse_images)
    except Exception as exc:
        logger.exception('Project dispatch failed for %s: %s', project.id, exc)
        message = 'Передача воркеру не вдалася; maintenance-worker повторить її автоматично.'
        db.add(Event(project_id=project.id, stage='dispatch_pending', level='warning', message=message))
        db.commit()
        return False
    db.refresh(project)
    if project.status == Status.queued and project.stage == 'dispatch_pending':
        project.stage = 'queued'
        project.started_at = datetime.utcnow()
        db.add(Event(project_id=project.id, stage='queued', message='Проєкт передано воркеру'))
        db.commit()
    return True


@app.post('/api/uploads/image')
async def upload_reference_image(request: Request, user=Depends(require_perm('project.create'))):
    """Прийняти власне фото для майбутнього проєкту.

    Сирі байти замість multipart: без нової залежності python-multipart.
    Файл нормалізується у WebP і лежить у media/uploads/ до створення проєкту,
    де його копія стає кадром галереї конкретного проєкту.
    """
    check_action(user.id, 'upload', 300)
    cap = 30 * 1024 * 1024
    if int(request.headers.get('content-length') or 0) > cap:
        raise HTTPException(413, 'Файл більший за 30 МБ')
    data = await request.body()
    if len(data) > cap:
        raise HTTPException(413, 'Файл більший за 30 МБ')
    if len(data) < 256:
        raise HTTPException(400, 'Порожній файл')
    from PIL import Image as PILImage, ImageOps as PILOps
    try:
        image = PILImage.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise HTTPException(400, 'Файл не схожий на зображення')
    if image.width < 320 or image.height < 320:
        raise HTTPException(400, f'Замале зображення ({image.width}×{image.height}): потрібно від 320px по кожній стороні')
    name = f'{secrets.token_hex(16)}.webp'
    target_dir = Path(settings.media_dir) / 'uploads'
    target_dir.mkdir(parents=True, exist_ok=True)
    PILOps.exif_transpose(image).convert('RGB').save(target_dir / name, format='WEBP', quality=88)
    return {'url': media_url('uploads', name), 'width': image.width, 'height': image.height}


@app.post('/api/projects/bulk-import')
def bulk_import_projects(payload: BulkProjectImportIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    """Validate a CSV batch, then create every valid row in one transaction.

    The UI calls this twice: a write-free preview first, followed by an explicit
    queue action with the same payload. Invalid rows never block valid ones.
    """
    check_action(user.id, 'bulk-preview' if payload.validate_only else 'bulk-import', 20 if payload.validate_only else 3)
    if payload.image_quality not in {'low', 'medium', 'high'}:
        raise HTTPException(400, 'Якість зображень має бути low, medium або high')
    default_languages = normalize_languages(payload.languages)
    default_variants = list(dict.fromkeys(value for value in payload.variants if value in {'desktop', 'mobile'}))
    if not default_languages or not default_variants:
        raise HTTPException(400, 'Оберіть щонайменше одну мову та формат для пакета')
    if not payload.validate_only:
        if not payload.batch_id:
            raise HTTPException(400, 'Спочатку перевірте CSV та передайте batch_id із попереднього перегляду')
        # Fast idempotent replay does not need to re-resolve up to 100 hostnames.
        replay = _bulk_replay_if_exists(db, user, payload)
        if replay:
            return replay

    styles = db.scalars(select(Style)).all()
    default_style = (next((style for style in styles if style.id == payload.style_id), None)
                     if payload.style_id else next((style for style in styles if style.is_default), None))
    if not default_style:
        raise HTTPException(400, 'Обраний стиль не знайдено')
    style_by_id = {style.id: style for style in styles}
    style_by_name = {(style.name or '').strip().casefold(): style for style in styles}

    try:
        rows = parse_bulk_csv(payload.csv_text)
    except BulkCSVError as exc:
        raise HTTPException(400, str(exc)) from exc

    errors = []
    skipped = []
    prepared = []
    seen_sources: set[str] = set()
    for row in rows:
        row_number = int(row.get('_row') or 0)
        source_raw = str(row.get('source_url') or '').strip()
        name_raw = str(row.get('name') or '').strip()
        if row.get('_parse_error'):
            errors.append({'row': row_number, 'source_url': source_raw, 'name': name_raw,
                           'error': str(row['_parse_error'])})
            continue
        if not source_raw:
            errors.append({'row': row_number, 'source_url': '', 'name': name_raw,
                           'error': 'Не вказано URL товару'})
            continue

        style = default_style
        style_raw = str(row.get('style') or '').strip()
        if style_raw:
            style = style_by_id.get(style_raw) or style_by_name.get(style_raw.casefold())
            if not style:
                errors.append({'row': row_number, 'source_url': source_raw, 'name': name_raw,
                               'error': f'Стиль «{style_raw[:120]}» не знайдено'})
                continue

        row_languages = split_bulk_values(str(row.get('languages') or '')) or default_languages
        row_variants = split_bulk_values(str(row.get('variants') or '')) or default_variants
        quality = str(row.get('image_quality') or '').strip().lower() or payload.image_quality
        if quality not in {'low', 'medium', 'high'}:
            errors.append({'row': row_number, 'source_url': source_raw, 'name': name_raw,
                           'error': 'image_quality має бути low, medium або high'})
            continue
        try:
            row_payload = ProjectIn(
                name=name_raw,
                source_url=source_raw,
                style_id=style.id,
                languages=row_languages,
                variants=row_variants,
                text_model=str(row.get('text_model') or '').strip() or payload.text_model,
                image_model=str(row.get('image_model') or '').strip() or payload.image_model,
                image_quality=quality,
                custom_hero_url=str(row.get('custom_hero_url') or '').strip(),
                custom_feature_url=str(row.get('custom_feature_url') or '').strip(),
            )
            values, resolved_style = _project_values(row_payload, db)
        except ValidationError as exc:
            errors.append({'row': row_number, 'source_url': source_raw, 'name': name_raw,
                           'error': _bulk_validation_message(exc)})
            continue
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else 'Некоректні дані рядка'
            errors.append({'row': row_number, 'source_url': source_raw, 'name': name_raw, 'error': detail})
            continue

        normalized_source = values['source_url']
        if normalized_source in seen_sources:
            skipped.append({'row': row_number, 'source_url': normalized_source, 'name': values['name'],
                            'reason': 'Дублікат URL у цьому CSV'})
            continue
        seen_sources.add(normalized_source)
        estimated_cost = _bulk_estimated_cost(values, resolved_style)
        prepared.append({'row': row_number, 'values': values, 'style': resolved_style,
                         'estimated_cost': estimated_cost})

    if not payload.validate_only:
        # Keep the global critical section short: all slow DNS validation above
        # is pure preparation. Recheck idempotency under the lock before the
        # duplicate query, budget reservation and inserts.
        _lock_bulk_commit(db)
        replay = _bulk_replay_if_exists(db, user, payload)
        if replay:
            return replay

    if payload.skip_existing and prepared:
        existing_sources = set(db.scalars(select(Project.source_url).where(
            Project.source_url.in_([item['values']['source_url'] for item in prepared])
        )).all())
        ready = []
        for item in prepared:
            if item['values']['source_url'] in existing_sources:
                skipped.append({'row': item['row'], 'source_url': item['values']['source_url'],
                                'name': item['values']['name'], 'reason': 'Проєкт із цим URL уже існує'})
            else:
                ready.append(item)
        prepared = ready

    estimated_cost = round(sum(item['estimated_cost'] for item in prepared), 6)
    valid_rows = [{
        'row': item['row'],
        'source_url': item['values']['source_url'],
        'name': item['values']['name'],
        'style': item['style'].name,
        'languages': item['values']['languages'].split(','),
        'variants': item['values']['variants'].split(','),
        'estimated_cost': item['estimated_cost'],
    } for item in prepared]
    batch_id = ('bulk-' + secrets.token_hex(8)) if payload.validate_only else payload.batch_id
    result = {
        'batch_id': batch_id,
        'validate_only': payload.validate_only,
        'total_rows': len(rows),
        'valid_count': len(prepared),
        'invalid_count': len(errors),
        'skipped_count': len(skipped),
        'created_count': 0,
        'queued_count': 0,
        'dispatch_failed_count': 0,
        'dispatch_pending_count': 0,
        'estimated_cost': estimated_cost,
        'valid_rows': valid_rows,
        'errors': errors,
        'skipped': skipped,
        'projects': [],
        'dispatch_failures': [],
    }
    if payload.validate_only or not prepared:
        return result

    _check_bulk_estimated_budget(db, user, estimated_cost)
    created = []
    queued_at = datetime.utcnow()
    for item in prepared:
        project = Project(
            owner_id=user.id,
            status=Status.queued,
            stage='dispatch_pending',
            queued_at=queued_at,
            started_at=queued_at,
            reserved_cost=item['estimated_cost'],
            **item['values'],
        )
        db.add(project)
        db.flush()
        db.add(Event(project_id=project.id, stage='dispatch_pending', message=f'Додано з CSV-пакета {batch_id}; очікує передачі воркеру'))
        audit(db, user, 'project.create', 'project', project.id,
              {'batch_id': batch_id, 'csv_row': item['row']})
        created.append((project, item['style'], item['row']))
    audit(db, user, 'project.bulk_import', 'bulk_batch', batch_id, {
        'total_rows': len(rows),
        'created_count': len(created),
        'invalid_count': len(errors),
        'skipped_count': len(skipped),
        'estimated_cost': estimated_cost,
        'request_hash': _bulk_request_hash(payload),
        'valid_rows': valid_rows,
        'errors': errors,
        'skipped': skipped,
        'projects': [
            {'id': project.id, 'row': row_number, 'style': style.name}
            for project, style, row_number in created
        ],
    })
    # This is a transactional outbox: DB state and budget reservations become
    # durable before publication. Beat retries every pending row after a crash.
    db.commit()

    dispatch_failures = []
    for project, _style, row_number in created:
        try:
            process_project.delay(project.id)
        except Exception as exc:
            logger.exception('Bulk import dispatch failed for project %s: %s', project.id, exc)
            message = 'Передача воркеру не вдалася; система повторить її автоматично протягом хвилини.'
            db.add(Event(project_id=project.id, stage='dispatch_pending', level='warning', message=message))
            dispatch_failures.append({'project_id': project.id, 'row': row_number, 'error': message})
        else:
            # The worker may already have claimed the row. Only mark it queued
            # while it is still in the pending state.
            db.refresh(project)
            if project.status == Status.queued and project.stage == 'dispatch_pending':
                project.stage = 'queued'
                db.add(Event(project_id=project.id, stage='queued', message='Проєкт передано воркеру'))
                db.commit()
    if dispatch_failures:
        audit(db, user, 'project.bulk_dispatch_pending', 'bulk_batch', batch_id,
              {'failed_count': len(dispatch_failures), 'project_ids': [item['project_id'] for item in dispatch_failures]})
        db.commit()

    result.update({
        'validate_only': False,
        'created_count': len(created),
        'queued_count': len(created),
        'dispatch_failed_count': len(dispatch_failures),
        'dispatch_pending_count': len(dispatch_failures),
        'dispatch_failures': dispatch_failures,
        'projects': [project_dict(project, style_name=style.name) for project, style, _row in created],
    })
    return result


@app.post('/api/projects')
def create_project(payload: ProjectIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    check_action(user.id, 'create', 6); check_budget(); check_user_budget(user)
    _lock_bulk_commit(db)
    p, style = _new_project_record(payload, db, user)
    p.stage = 'dispatch_pending'
    _reserve_project_run(db, user, p, style)
    # Власні фото оператора: копія з media/uploads стає кадром галереї проєкту.
    upload_urls = []
    media_root = Path(settings.media_dir).resolve()
    rotation_urls = []
    uploads_seq = payload.uploads[:200]
    if payload.uploads_360:
        # 197 кадрів у сторінку не покладеш: рівномірно проріджуємо до 48 -
        # крок ~7.5 градуса, обертання плавне, вага сторінки під контролем.
        uploads_seq = _pick_even(uploads_seq, 48)
    for index, raw in enumerate(uploads_seq, start=1):
        name = strip_media_query(raw).rsplit('/', 1)[-1]
        if not strip_media_query(raw).startswith('/media/uploads/') or not _MEDIA_NAME.fullmatch(name):
            continue
        source = (media_root / 'uploads' / name).resolve()
        if media_root not in source.parents or not source.is_file():
            continue
        project_dir = media_root / p.id
        project_dir.mkdir(parents=True, exist_ok=True)
        target_name = f'upload-{index}.webp'
        if payload.uploads_360:
            # Кадр каруселі показується <=800px: тиснемо до 1000px webp, щоб
            # 48 кадрів важили мегабайти, а не десятки.
            from PIL import Image as PILImage, ImageOps as PILOps
            try:
                frame = PILImage.open(source)
                frame = PILOps.exif_transpose(frame).convert('RGB')
                frame.thumbnail((1000, 1000), PILImage.Resampling.LANCZOS)
                frame.save(project_dir / target_name, format='WEBP', quality=82)
            except Exception:
                shutil.copyfile(source, project_dir / target_name)
        else:
            shutil.copyfile(source, project_dir / target_name)
        url = media_url(p.id, target_name)
        if payload.uploads_360:
            rotation_urls.append(url)
            db.add(Asset(project_id=p.id, kind='upload', label=f'Кадр 360 №{index}', url=url))
            continue
        role_hero = raw == payload.upload_hero
        role_feature = raw == payload.upload_feature
        if role_hero:
            # Обране фото СТАЄ Hero: та сама гілка, що й custom_hero_url -
            # генерація зображення для цього слота не запускається.
            p.custom_hero_url = url
        if role_feature:
            p.custom_feature_url = url
        if not (role_hero or role_feature):
            upload_urls.append(url)
        role_note = ' - Hero' if role_hero else (' - Feature' if role_feature else '')
        db.add(Asset(project_id=p.id, kind='upload', label=f'Завантажене фото {index}{role_note}', url=url))
    if upload_urls:
        p.gallery_json = json.dumps(json.loads(p.gallery_json or '[]') + upload_urls)
    if rotation_urls:
        p.rotation_json = json.dumps(rotation_urls)
    adopted = 0
    if payload.adopt_images:
        by_source: dict[str, list[str]] = {}
        for item in payload.adopt_images:
            by_source.setdefault(item.project_id, []).append(item.label)
        for source_id, labels in by_source.items():
            adopted += _adopt_images(db, p, source_id, labels=labels)
    elif payload.reuse_images_from:
        adopted = _adopt_images(db, p, payload.reuse_images_from, labels=payload.reuse_labels or None)
    audit(db, user, 'project.create', 'project', p.id, {'adopted_images': adopted} if adopted else None)
    db.commit(); db.refresh(p)
    _dispatch_project_once(db, p, reuse_images=bool(adopted))
    return project_dict(p, style_name=style.name)


@app.get('/api/projects/{project_id}')
def project(project_id: str, db: Session = Depends(get_db), user=Depends(current)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    style = db.get(Style, p.style_id)
    r = project_dict(p, True, style.name if style else '')
    review_rows = db.scalars(select(Review).where(Review.project_id == p.id).order_by(Review.created_at.desc())).all()
    reviewers = {u.id: (u.name or u.email) for u in db.scalars(select(User).where(User.id.in_([x.reviewer_id for x in review_rows]))).all()} if review_rows else {}
    r['reviews'] = [{'id': x.id, 'reviewer_id': x.reviewer_id, 'reviewer': reviewers.get(x.reviewer_id, ''), 'decision': x.decision, 'comment': x.comment, 'checklist': json.loads(x.checklist_json or '{}'), 'created_at': x.created_at} for x in review_rows]
    r['assets'] = [{'id': x.id, 'kind': x.kind, 'label': x.label, 'url': x.url, 'prompt': x.prompt, 'model': x.model, 'width': x.width, 'height': x.height, 'cost': x.cost, 'metadata': json.loads(x.metadata_json or '{}'), 'created_at': x.created_at} for x in db.scalars(select(Asset).where(Asset.project_id == p.id).order_by(Asset.created_at.desc())).all()]
    r['critics'] = [{'id': x.id, 'type': x.critic_type, 'score': x.score, 'summary': x.summary, 'issues': json.loads(x.issues_json or '[]'), 'suggestions': json.loads(x.suggestions_json or '[]'), 'auto_fixed': x.auto_fixed, 'created_at': x.created_at} for x in db.scalars(select(CriticReport).where(CriticReport.project_id == p.id).order_by(CriticReport.created_at.desc())).all()]
    return r


def require_project_edit(project, user):
    """PROJECT_OWNERSHIP=owner: змінювати проєкт може лише власник або admin.

    Перегляд, рев'ю та критик не обмежуються - рев'юєр мусить працювати з чужими
    проєктами. Проєкти без власника (створені до появи поля) лишаються спільними.
    """
    if settings.project_ownership != 'owner':
        return
    if not project or user.role == Role.admin or not project.owner_id or project.owner_id == user.id:
        return
    raise HTTPException(403, 'Проєкт належить іншому користувачеві. У режимі PROJECT_OWNERSHIP=owner зміни вносить лише власник або адміністратор')


@app.delete('/api/projects/{project_id}')
def delete_project(project_id: str, db: Session = Depends(get_db), user=Depends(require_perm('project.delete'))):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    require_project_edit(p, user)
    if p.status == Status.processing: raise HTTPException(409, 'Не можна видалити проєкт під час генерації. Спершу скасуйте його.')
    name = p.name
    for model in (Asset, CriticReport, Review, Event, Artifact):
        db.execute(sa_delete(model).where(model.project_id == p.id))
    db.delete(p)
    audit(db, user, 'project.delete', 'project', project_id, {'name': name}); db.commit()
    shutil.rmtree(Path(settings.media_dir) / project_id, ignore_errors=True)
    return {'deleted': True}


def _archive_name(value: str, fallback='file') -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '-', value or '').strip('-._')
    return cleaned[:90] or fallback


@app.get('/api/projects/{project_id}/archive')
def project_archive(project_id: str, db: Session = Depends(get_db), user=Depends(current)):
    """Download the latest rich HTML variants and every available project image."""
    import httpx
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    style = db.get(Style, p.style_id)
    artifacts = db.scalars(select(Artifact).where(Artifact.project_id == p.id).order_by(Artifact.version)).all()
    if not artifacts: raise HTTPException(409, 'У проєкті ще немає готового HTML')
    latest = {}
    for artifact in artifacts:
        latest[(artifact.language, artifact.variant)] = artifact
    assets = db.scalars(select(Asset).where(Asset.project_id == p.id).order_by(Asset.created_at)).all()
    stream = io.BytesIO()
    image_paths = {}
    skipped = []
    total_archive_bytes = 0
    media_root = Path(settings.media_dir).resolve()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        with safe_client(timeout=20) as http:
            for asset in assets:
                if not asset.url or asset.url in image_paths:
                    continue
                try:
                    data = b''
                    suffix = Path(asset.url.split('?', 1)[0]).suffix.lower()
                    if suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.avif'}:
                        suffix = '.webp'
                    if strip_media_query(asset.url).startswith('/media/'):
                        candidate = (media_root / strip_media_query(asset.url).removeprefix('/media/')).resolve()
                        if media_root not in candidate.parents and candidate != media_root:
                            raise ValueError('unsafe media path')
                        data = candidate.read_bytes()
                    elif asset.url.startswith(('http://', 'https://')):
                        if not is_public_http_url(asset.url):
                            raise ValueError('non-public image url blocked')
                        data = fetch_bytes_capped(http, asset.url)
                    if not data:
                        raise ValueError('empty image')
                    if total_archive_bytes + len(data) > 200 * 1024 * 1024:
                        raise ValueError('archive ceiling 200 MB reached, image skipped')
                    if data.startswith(b'\x89PNG\r\n\x1a\n'):
                        suffix = '.png'
                    elif data.startswith(b'\xff\xd8\xff'):
                        suffix = '.jpg'
                    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                        suffix = '.webp'
                    filename = f"{_archive_name(asset.label, 'image')}-{asset.id[:8]}{suffix}"
                    target = f'images/{filename}'
                    archive.writestr(target, data)
                    total_archive_bytes += len(data)
                    image_paths[asset.url] = target
                except Exception as exc:
                    skipped.append({'url': asset.url, 'label': asset.label, 'reason': str(exc)})

        exported = []
        for (language, variant), artifact in sorted(latest.items()):
            markup = artifact.html
            for source, target in image_paths.items():
                markup = markup.replace(source, f'../{target}')
            document = f'''<!doctype html>
<html lang="{language}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html_lib.escape(p.name)}</title></head>
<body style="margin:0;background:#FFFFFF">{markup}</body>
</html>'''
            filename = f'rich-{language}-{variant}.html'
            archive.writestr(f'html/{filename}', document)
            archive.writestr(f'fragments/{filename}', markup)
            exported.append({'language': language, 'variant': variant, 'version': artifact.version, 'file': f'html/{filename}'})

        manifest = {
            'project_id': p.id, 'name': p.name, 'source_url': p.source_url,
            'style': {'id': p.style_id, 'name': style.name if style else ''},
            'text_model': p.text_model, 'image_model': p.image_model,
            'exported_artifacts': exported,
            'images': image_paths, 'skipped_images': skipped,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
        }
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        if style:
            archive.writestr('style.json', json.dumps({'id': style.id, 'name': style.name, 'description': style.description, 'prompt': style.prompt, 'hero_prompt': style.hero_prompt, 'feature_prompt': style.feature_prompt, 'negative_prompt': style.negative_prompt}, ensure_ascii=False, indent=2))
        archive.writestr('README.txt', f'''ARTLINE Rich Studio export

Project: {p.name}
Source: {p.source_url}
Style: {style.name if style else 'Unknown'}

html/ contains standalone latest HTML files.
fragments/ contains section fragments for insertion into the ARTLINE editor.
images/ contains project images and generated assets.
manifest.json contains generation metadata.
''')
    stream.seek(0)
    audit(db, user, 'project.archive', 'project', p.id, {'artifacts': len(latest), 'images': len(image_paths)}); db.commit()
    filename = f'artline-rich-{_archive_name(p.name, p.id[:8])}.zip'
    return StreamingResponse(stream, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.post('/api/projects/{project_id}/run')
def rerun(project_id: str, payload: RerunIn | None = None, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    check_action(user.id, 'rerun', 6); check_budget(); check_user_budget(user)
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    require_project_edit(p, user)
    if p.status in {Status.processing, Status.queued}: raise HTTPException(409, 'Проєкт уже виконується або стоїть у черзі')
    if p.status in {Status.paused, Status.cancelled} and p.finished_at is None:
        raise HTTPException(409, 'Зачекайте, доки воркер підтвердить зупинку')
    if payload and payload.style_id:
        style = db.get(Style, payload.style_id)
        if not style: raise HTTPException(400, 'Обраний стиль не знайдено')
        p.style_id = style.id
    if payload and payload.languages is not None:
        langs = normalize_languages(payload.languages)
        if not langs: raise HTTPException(400, 'Оберіть щонайменше одну мову')
        p.languages = ','.join(langs)
    if payload and payload.variants is not None:
        variants = [x for x in payload.variants if x in {'desktop', 'mobile'}]
        variants = list(dict.fromkeys(variants))
        if not variants: raise HTTPException(400, 'Оберіть щонайменше один формат')
        p.variants = ','.join(variants)
    _lock_bulk_commit(db)
    style = db.get(Style, p.style_id)
    if not style: raise HTTPException(400, 'Обраний стиль не знайдено')
    p.run_index = (getattr(p, 'run_index', 1) or 1) + 1
    p.status = Status.queued; p.stage = 'dispatch_pending'; p.progress = 0; p.error = ''; p.input_tokens = 0; p.output_tokens = 0; p.image_count = 0; p.text_request_count = 0; p.image_request_count = 0; p.text_cost = 0; p.image_cost = 0; p.estimated_cost = 0; p.reserved_cost = 0
    _reserve_project_run(db, user, p, style)
    reuse = bool(payload and payload.reuse_images)
    audit(db, user, 'project.rerun', 'project', p.id, {'style_id': p.style_id, 'languages': p.languages, 'variants': p.variants, 'reuse_images': reuse}); db.commit()
    _dispatch_project_once(db, p, reuse_images=reuse)
    return {'queued': True, 'style_id': p.style_id, 'languages': p.languages.split(','), 'variants': p.variants.split(','), 'reuse_images': reuse}


@app.post('/api/projects/{project_id}/queue')
def queue_control(project_id: str, payload: QueueIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    require_project_edit(p, user)
    if payload.action in {'pause', 'cancel'}:
        # The running worker checks project.status between stages and stops cleanly.
        was_processing = p.status == Status.processing
        p.status = Status.paused if payload.action == 'pause' else Status.cancelled
        p.stage = ('pausing' if payload.action == 'pause' else 'cancelling') if was_processing else p.status.value
        if not was_processing:
            p.reserved_cost = 0
            p.finished_at = datetime.utcnow()
        db.add(Event(project_id=p.id, stage=p.stage, level='warning', message=f'{user.email}: {"пауза" if payload.action == "pause" else "скасування"}'))
    elif payload.action in {'resume', 'retry'}:
        if p.status in {Status.processing, Status.queued}: raise HTTPException(409, 'Проєкт уже виконується')
        if p.status in {Status.paused, Status.cancelled} and p.finished_at is None:
            raise HTTPException(409, 'Зачекайте, доки воркер підтвердить зупинку, і повторіть дію')
        check_action(user.id, 'queue-retry', 6); check_budget(); check_user_budget(user)
        _lock_bulk_commit(db)
        style = db.get(Style, p.style_id)
        if not style: raise HTTPException(400, 'Обраний стиль не знайдено')
        p.run_index = (getattr(p, 'run_index', 1) or 1) + 1
        p.status = Status.queued; p.stage = 'dispatch_pending'; p.progress = 0; p.error = ''; p.input_tokens = 0; p.output_tokens = 0; p.image_count = 0; p.text_request_count = 0; p.image_request_count = 0; p.text_cost = 0; p.image_cost = 0; p.estimated_cost = 0; p.reserved_cost = 0
        _reserve_project_run(db, user, p, style)
        db.add(Event(project_id=p.id, stage='dispatch_pending', message=f'{user.email}: повторний запуск з черги'))
        audit(db, user, 'queue.' + payload.action, 'project', p.id); db.commit()
        _dispatch_project_once(db, p)
        return {'status': p.status.value}
    else:
        raise HTTPException(400, 'Невідома дія')
    audit(db, user, 'queue.' + payload.action, 'project', p.id); db.commit(); return {'status': p.status.value}


@app.post('/api/projects/{project_id}/review')
def review(project_id: str, payload: ReviewIn, db: Session = Depends(get_db), user=Depends(require_perm('review.request_changes', 'review.approve'))):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, 'Проєкт не знайдено')
    if payload.decision not in {'approve', 'request_changes', 'submit'}:
        raise HTTPException(400, 'Неприпустиме рішення')
    if payload.decision == 'request_changes' and not payload.comment.strip():
        raise HTTPException(400, 'Коментар обов’язковий')
    if payload.decision == 'approve' and not has_perm(user, 'review.approve'):
        raise HTTPException(403, 'Немає права схвалювати результат')
    if payload.decision == 'request_changes' and not has_perm(user, 'review.request_changes'):
        raise HTTPException(403, 'Немає права запитувати зміни')
    try:
        mapping = {'approve': Status.approved, 'request_changes': Status.changes_requested, 'submit': Status.review}
        new_status = mapping[payload.decision]
        p.status = new_status
        p.stage = new_status.value
        row = Review(project_id=p.id, reviewer_id=user.id, decision=payload.decision, comment=payload.comment.strip(), checklist_json=json.dumps(payload.checklist or {}, ensure_ascii=False))
        db.add(row)
        decision_label = {'approve': 'Схвалено', 'request_changes': 'Запитано зміни', 'submit': 'Надіслано на перевірку'}[payload.decision]
        db.add(Event(project_id=p.id, stage='review', level='info', message=f'{user.email}: {decision_label}'))
        audit(db, user, 'review.' + payload.decision, 'project', p.id)
        db.commit()
        return {'status': new_status.value, 'message': decision_label}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f'Не вдалося зберегти рішення перевірки: {exc}') from exc


@app.get('/api/projects/{project_id}/events')
def events(project_id: str, db: Session = Depends(get_db), user=Depends(current)):
    return [{'id': x.id, 'stage': x.stage, 'level': x.level, 'message': x.message, 'created_at': x.created_at} for x in db.scalars(select(Event).where(Event.project_id == project_id).order_by(Event.created_at.desc())).all()]


@app.post('/api/projects/{project_id}/critic')
def run_critic(project_id: str, payload: CriticIn, db: Session = Depends(get_db), user=Depends(require_perm('review.request_changes', 'project.create'))):
    from app.pipeline import critic_html
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    latest = {}
    for a in sorted(p.artifacts, key=lambda x: x.version): latest[(a.language, a.variant)] = a
    if not latest: raise HTTPException(409, 'У проєкті ще немає готового HTML для перевірки')
    if payload.llm:
        # ПЛАТНИЙ шлях: реальна модель читає сторінки. Вартість чесно лягає у
        # вартість проєкту, глобальний і особистий бюджети списуються.
        from app.pipeline import llm_critic
        check_action(user.id, 'critic_llm', 4); check_budget(); check_user_budget(user)
        model = p.text_model or settings.openai_text_model
        try:
            score, summary, issues, suggestions, in_tok, out_tok = llm_critic(list(latest.values()), json.loads(p.product_json or '{}'), model)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        rate_in, rate_out = text_rate(model)
        cost = round((in_tok * rate_in + out_tok * rate_out) / 1_000_000, 6)
        p.text_cost = float(p.text_cost or 0) + cost
        p.estimated_cost = float(p.estimated_cost or 0) + cost
        p.input_tokens = (p.input_tokens or 0) + in_tok
        p.output_tokens = (p.output_tokens or 0) + out_tok
        p.text_request_count = (p.text_request_count or 0) + 1
        add_spend(cost); add_user_spend(user.id, cost); bill_extra(db, p, cost)
        db.execute(sa_delete(CriticReport).where(CriticReport.project_id == p.id, CriticReport.critic_type == 'llm'))
        db.add(CriticReport(project_id=p.id, critic_type='llm', score=score, summary=summary,
                            issues_json=json.dumps(issues, ensure_ascii=False),
                            suggestions_json=json.dumps(suggestions, ensure_ascii=False), auto_fixed=False))
        db.add(Event(project_id=p.id, stage='critic', message=f'{user.email}: AI-рецензія ({model}) — ${cost:.4f} додано до вартості проєкту'))
        audit(db, user, 'critic.llm', 'project', p.id, {'model': model, 'cost': cost}); db.commit()
        return {'type': 'llm', 'score': score, 'summary': summary, 'issues': issues, 'suggestions': suggestions, 'cost': cost}
    # Безкоштовні евристики; платну AI-рецензію не стираємо.
    db.execute(sa_delete(CriticReport).where(CriticReport.project_id == p.id, CriticReport.critic_type != 'llm'))
    reports = []
    for kind in ('html', 'facts', 'accessibility', 'marketing'):
        score, summary, issues, suggestions = critic_html(list(latest.values()), kind, json.loads(p.product_json or '{}'))
        row = CriticReport(project_id=p.id, critic_type=kind, score=score, summary=summary, issues_json=json.dumps(issues, ensure_ascii=False), suggestions_json=json.dumps(suggestions, ensure_ascii=False), auto_fixed=False)
        db.add(row); reports.append({'type': kind, 'score': score, 'summary': summary, 'issues': issues, 'suggestions': suggestions})
    db.add(Event(project_id=p.id, stage='critic', message=f'{user.email}: перевірку якості перезапущено')); audit(db, user, 'critic.run', 'project', p.id); db.commit(); return reports


@app.post('/api/projects/{project_id}/critic/fix')
def critic_fix(project_id: str, db: Session = Depends(get_db), user=Depends(require_perm('project.edit_html'))):
    """ПЛАТНЕ авто-виправлення за AI-рецензією: текст правиться, DOM заморожено.

    Створює НОВІ версії сторінок (стара лишається в історії), вартість токенів
    додається до вартості проєкту, списується з бюджетів. Структурні зауваження
    рецензії цей шлях чесно не вирішує - лише текст."""
    from app.pipeline import llm_fix_texts
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    require_project_edit(p, user)
    review = db.scalar(select(CriticReport).where(CriticReport.project_id == p.id, CriticReport.critic_type == 'llm'))
    if not review: raise HTTPException(409, 'Спершу запустіть AI-рецензента - виправлення йде за його зауваженнями')
    issues = json.loads(review.issues_json or '[]')
    if not issues: raise HTTPException(409, 'У рецензії немає зауважень - виправляти нічого')
    check_action(user.id, 'critic_fix', 2); check_budget(); check_user_budget(user)
    latest = {}
    for a in sorted(p.artifacts, key=lambda x: x.version): latest[(a.language, a.variant)] = a
    model = p.text_model or settings.openai_text_model
    total_in = total_out = 0
    updated = 0
    product = json.loads(p.product_json or '{}')
    db.scalar(select(Project.id).where(Project.id == p.id).with_for_update())
    for (language, variant), artifact in sorted(latest.items()):
        try:
            fixed, in_tok, out_tok, changed = llm_fix_texts(artifact.html, issues, product, model, language)
        except RuntimeError as exc:
            raise HTTPException(409, f'{language}/{variant}: {exc}')
        total_in += in_tok; total_out += out_tok
        if changed:
            top = db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == p.id, Artifact.language == language, Artifact.variant == variant)) or 0
            db.add(Artifact(project_id=p.id, language=language, variant=variant,
                            html=fixed if 'Правовласник' in fixed else fixed + LICENSE_COMMENT,
                            version=top + 1, created_by=user.id))
            updated += 1
    rate_in, rate_out = text_rate(model)
    cost = round((total_in * rate_in + total_out * rate_out) / 1_000_000, 6)
    p.text_cost = float(p.text_cost or 0) + cost
    p.estimated_cost = float(p.estimated_cost or 0) + cost
    p.input_tokens = (p.input_tokens or 0) + total_in
    p.output_tokens = (p.output_tokens or 0) + total_out
    p.text_request_count = (p.text_request_count or 0) + len(latest)
    add_spend(cost); add_user_spend(user.id, cost); bill_extra(db, p, cost)
    review.auto_fixed = True
    db.add(Event(project_id=p.id, stage='critic', message=f'{user.email}: авто-виправлення за рецензією ({model}) - оновлено {updated} стор., ${cost:.4f} додано до вартості'))
    audit(db, user, 'critic.fix', 'project', p.id, {'model': model, 'cost': cost, 'updated': updated}); db.commit()
    return {'updated': updated, 'cost': cost}


@app.get('/api/artifacts/{artifact_id}/blocks.zip')
def artifact_blocks_png(artifact_id: str, db: Session = Depends(get_db), user=Depends(current)):
    """ZIP із PNG кожного блока сторінки (для маркетплейсів, що не беруть HTML).

    Рендерить окремий сервіс `shots` зі справжнім Chromium - тому картинка
    точно така, якою її бачить покупець. Без сервісу ендпоінт чесно каже, що
    робити, а не падає 500."""
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, 'Результат не знайдено')
    if not settings.shots_url:
        raise HTTPException(503, 'Сервіс знімків вимкнено. Увімкніть: docker compose --profile shots up -d shots')
    check_action(user.id, 'blocks_png', 6)
    import httpx
    project = db.get(Project, artifact.project_id)
    width = 480 if artifact.variant == 'mobile' else 1240
    try:
        with httpx.Client(timeout=180) as http:
            reply = http.post(settings.shots_url.rstrip('/') + '/render',
                              json={'html': artifact.html, 'width': width})
    except Exception:
        logger.exception('Blocks render failed')
        raise HTTPException(503, 'Сервіс знімків недоступний. Перевірте: docker compose --profile shots ps')
    if reply.status_code != 200:
        detail = ''
        try:
            detail = (reply.json() or {}).get('detail') or ''
        except Exception:
            detail = reply.text[:300]
        logger.warning('Shots service %s: %s', reply.status_code, detail)
        raise HTTPException(502, f'Сервіс знімків відповів {reply.status_code}: {detail}'[:400])
    audit(db, user, 'artifact.blocks_png', 'artifact', artifact.id, {'variant': artifact.variant}); db.commit()
    name = _archive_name(f'{project.name if project else "rich"}-{artifact.language}-{artifact.variant}-v{artifact.version}', 'blocks')
    return StreamingResponse(io.BytesIO(reply.content), media_type='application/zip',
                             headers={'Content-Disposition': f'attachment; filename="{name}-png.zip"'})


@app.get('/api/projects/{project_id}/blocks-all.zip')
def project_blocks_all_png(project_id: str, run: int = 0, db: Session = Depends(get_db), user=Depends(current)):
    """Усі варіанти (мови × формати) ОДНІЄЇ версії rich-товару - блоки в PNG,
    одним архівом, кожен варіант у своїй підпапці.

    "Версія" = один прогін (run_index): це узгоджений набір сторінок товару по
    всіх мовах і форматах. За замовчуванням береться поточний (найновіший)
    прогін; у межах прогону для кожної пари (мова, формат) - остання версія.
    Рендерить той самий сервіс `shots`; один невдалий варіант не валить архів -
    його причина йде в _errors.txt поруч із рештою."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, 'Проєкт не знайдено')
    if not settings.shots_url:
        raise HTTPException(503, 'Сервіс знімків вимкнено. Увімкніть: docker compose --profile shots up -d shots')
    artifacts = db.scalars(select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.version)).all()
    if not artifacts:
        raise HTTPException(409, 'У проєкті ще немає готового HTML')
    target_run = run or max((getattr(a, 'run_index', 1) or 1) for a in artifacts)
    latest = {}
    for a in artifacts:
        if (getattr(a, 'run_index', 1) or 1) != target_run:
            continue
        latest[(a.language, a.variant)] = a  # відсортовано за version - останнє перезаписує = найновіше
    if not latest:
        raise HTTPException(404, f'Немає сторінок для цієї версії (прогін {target_run})')
    check_action(user.id, 'blocks_png_all', 12)
    import httpx
    combined = io.BytesIO()
    failures = []
    with zipfile.ZipFile(combined, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        with httpx.Client(timeout=300) as http:
            for (language, variant), artifact in sorted(latest.items()):
                width = 480 if variant == 'mobile' else 1240
                try:
                    reply = http.post(settings.shots_url.rstrip('/') + '/render',
                                      json={'html': artifact.html, 'width': width})
                except Exception:
                    logger.exception('Blocks(all) render failed for %s/%s', language, variant)
                    failures.append(f'{language}-{variant}: сервіс знімків недоступний')
                    continue
                if reply.status_code != 200:
                    detail = ''
                    try:
                        detail = (reply.json() or {}).get('detail') or ''
                    except Exception:
                        detail = reply.text[:200]
                    failures.append(f'{language}-{variant}: {reply.status_code} {detail}'[:200])
                    continue
                folder = _archive_name(f'{language}-{variant}-v{artifact.version}', 'variant')
                try:
                    sub = zipfile.ZipFile(io.BytesIO(reply.content))
                    for entry in sub.namelist():
                        out.writestr(f'{folder}/{entry}', sub.read(entry))
                except Exception:
                    failures.append(f'{language}-{variant}: пошкоджений архів знімків')
        if failures:
            out.writestr('_errors.txt', 'Варіанти, які не відрендерились:\n' + '\n'.join(failures))
    if len(failures) >= len(latest):
        raise HTTPException(502, 'Жоден варіант не відрендерився. ' + '; '.join(failures)[:300])
    audit(db, user, 'project.blocks_png_all', 'project', project.id,
          {'run': target_run, 'variants': len(latest), 'failed': len(failures)}); db.commit()
    combined.seek(0)
    name = _archive_name(f'{project.name}-v{target_run}-all', 'blocks')
    return StreamingResponse(combined, media_type='application/zip',
                             headers={'Content-Disposition': f'attachment; filename="{name}-png.zip"'})


# --- Промо-лендінги -----------------------------------------------------------
class LandingIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    campaign_title: str = Field(default='', max_length=300)
    campaign_subtitle: str = Field(default='', max_length=300)
    period: str = Field(default='', max_length=100)
    language: str = Field(default='ua', max_length=5)
    product_urls: list[str] = Field(default_factory=list, max_length=24)
    listing_url: str = Field(default='', max_length=1000)
    text_model: str = Field(default='', max_length=100)


def landing_dict(x, full=False):
    d = {'id': x.id, 'name': x.name, 'campaign_title': x.campaign_title,
         'campaign_subtitle': x.campaign_subtitle, 'period': x.period,
         'language': x.language, 'listing_url': x.listing_url,
         'status': x.status.value, 'stage': x.stage, 'error': x.error,
         'fallback_reason': x.fallback_reason, 'estimated_cost': x.estimated_cost,
         'text_model': x.text_model, 'owner_id': x.owner_id,
         'created_at': x.created_at, 'finished_at': x.finished_at,
         'product_count': len(json.loads(x.products_json or '[]'))}
    if full:
        d['html'] = x.html
        d['products'] = json.loads(x.products_json or '[]')
        d['source_urls'] = json.loads(x.source_urls_json or '[]')
    return d


def _landing_or_404(db, landing_id: str):
    landing = db.get(Landing, landing_id)
    if not landing:
        raise HTTPException(404, 'Лендінг не знайдено')
    return landing


@app.get('/api/landings')
def landings(db: Session = Depends(get_db), user=Depends(current)):
    rows = db.scalars(select(Landing).order_by(Landing.created_at.desc()).limit(200)).all()
    return [landing_dict(x) for x in rows]


@app.get('/api/landings/{landing_id}')
def landing_get(landing_id: str, db: Session = Depends(get_db), user=Depends(current)):
    return landing_dict(_landing_or_404(db, landing_id), full=True)


@app.post('/api/landings')
def landing_create(payload: LandingIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    check_action(user.id, 'landing', 6); check_budget(); check_user_budget(user)
    urls = [u.strip() for u in payload.product_urls if u.strip()]
    bad = [u for u in urls if not is_public_http_url(u)]
    if bad:
        raise HTTPException(400, f'Недоступні URL товарів: {", ".join(bad[:3])}')
    listing = payload.listing_url.strip()
    if listing and not is_public_http_url(listing):
        raise HTTPException(400, 'Сторінка акції недоступна або не публічна')
    if not urls and not listing:
        raise HTTPException(400, 'Додайте хоча б один URL товару або сторінку акції')
    landing = Landing(
        name=payload.name.strip(), campaign_title=payload.campaign_title.strip(),
        campaign_subtitle=payload.campaign_subtitle.strip(), period=payload.period.strip(),
        language=payload.language if payload.language in ('ua', 'ru') else 'ua',
        source_urls_json=json.dumps(urls), listing_url=listing,
        text_model=payload.text_model.strip() or settings.openai_text_model,
        owner_id=user.id, status=Status.queued, stage='queued')
    db.add(landing); db.flush()
    audit(db, user, 'landing.create', 'landing', landing.id, {'urls': len(urls), 'listing': bool(listing)})
    db.commit()
    process_landing.delay(landing.id)
    return landing_dict(landing)


@app.post('/api/landings/{landing_id}/run')
def landing_rerun(landing_id: str, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    check_action(user.id, 'landing', 6); check_budget(); check_user_budget(user)
    landing = _landing_or_404(db, landing_id)
    if landing.status == Status.processing:
        raise HTTPException(409, 'Лендінг вже генерується')
    landing.status = Status.queued; landing.stage = 'queued'; landing.error = ''
    audit(db, user, 'landing.rerun', 'landing', landing.id); db.commit()
    process_landing.delay(landing.id)
    return landing_dict(landing)


@app.put('/api/landings/{landing_id}')
def landing_save(landing_id: str, payload: HtmlIn, db: Session = Depends(get_db), user=Depends(require_perm('project.edit_html'))):
    from app.landing import sanitize_landing_html
    landing = _landing_or_404(db, landing_id)
    landing.html = sanitize_landing_html(payload.html)
    audit(db, user, 'landing.edit', 'landing', landing.id); db.commit()
    return landing_dict(landing, full=True)


@app.delete('/api/landings/{landing_id}')
def landing_delete(landing_id: str, db: Session = Depends(get_db), user=Depends(require_perm('project.delete'))):
    landing = _landing_or_404(db, landing_id)
    audit(db, user, 'landing.delete', 'landing', landing.id)
    db.delete(landing); db.commit()
    return {'ok': True}


@app.get('/api/landings/{landing_id}/page.html')
def landing_download(landing_id: str, db: Session = Depends(get_db), user=Depends(current)):
    landing = _landing_or_404(db, landing_id)
    if not (landing.html or '').strip():
        raise HTTPException(409, 'Сторінка ще не згенерована')
    name = _archive_name(landing.name, landing.id[:8])
    return Response(landing.html, media_type='text/html; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="landing-{name}.html"'})


@app.put('/api/artifacts/{artifact_id}')
def save_artifact(artifact_id: str, payload: HtmlIn, db: Session = Depends(get_db), user=Depends(require_perm('project.edit_html'))):
    source = db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, 'Результат не знайдено')
    require_project_edit(db.get(Project, source.project_id), user)
    clean = sanitize_html(payload.html)
    if '<section' not in clean:
        raise HTTPException(400, 'HTML має містити принаймні один <section> блок')
    if 'Правовласник' not in clean:
        clean += LICENSE_COMMENT
    try:
        # Serialize version allocation for one project. The UI blocks double clicks,
        # while this lock also protects simultaneous saves from different users.
        db.scalar(select(Project.id).where(Project.id == source.project_id).with_for_update())
        latest_version = db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == source.project_id, Artifact.language == source.language, Artifact.variant == source.variant)) or 0
        new = Artifact(project_id=source.project_id, language=source.language, variant=source.variant, html=clean, version=latest_version + 1, created_by=user.id, run_index=getattr(source, 'run_index', 1) or 1)
        db.add(new); db.flush(); audit(db, user, 'artifact.version', 'artifact', new.id); db.commit(); db.refresh(new); return artifact_dict(new)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f'Не вдалося зберегти нову версію: {exc}') from exc


@app.get('/api/models')
def available_models(user=Depends(current)):
    """The models this studio can actually run, not OpenAI's catalogue.

    Listing every discovered model was noise: codex, search-preview, instruct,
    audio and dated snapshots cannot serve this pipeline, and none of them are
    priced - so the New Project dialog would have quoted a cost that is simply a
    guess. The curated .env lists are the source of truth; discovery is used only
    to verify them against the live key. Anything genuinely missing here can still
    be typed by hand via "Інша модель" in the dialog.
    """
    cfg = runtime_config()
    text_models = list(settings.text_models)
    if cfg['llm_provider'] == 'local' and cfg.get('local_base_url'):
        local_list = [x.strip() for x in (cfg.get('local_text_models') or '').split(',') if x.strip()]
        if local_list:
            # Хмарні моделі локальний сервер не запустить - меню чесно показує його моделі.
            text_models = local_list
    image_models = list(settings.image_models)
    if cfg['gemini_api_key']:
        image_models = list(dict.fromkeys(list(settings.gemini_models) + image_models))
    source = 'configuration'
    unavailable = []
    if cfg['openai_api_key']:
        try:
            from openai import OpenAI
            live = {x.id for x in OpenAI(api_key=cfg['openai_api_key']).models.list()}
            is_gemini = lambda name: name.startswith('gemini-')
            # The key's listing may expose only dated snapshots (gpt-image-2-2026-04-21)
            # while the API accepts the bare alias; treat the alias as available.
            has = lambda name: name in live or any(x.startswith(name + '-') for x in live)
            unavailable = [x for x in text_models + image_models if not is_gemini(x) and not has(x)]
            kept_text = [x for x in text_models if has(x)]
            kept_image = [x for x in image_models if is_gemini(x) or has(x)]
            # Only trust the filter when the key can see something; an empty result
            # means the listing failed us, not that every model vanished.
            if kept_text:
                text_models = kept_text
            if kept_image:
                image_models = kept_image
            source = 'configuration+verified'
        except Exception:
            pass
    # Which of the chosen text models bill hidden reasoning tokens - that is what an
    # operator needs to know, not that o4-mini-deep-research exists somewhere.
    reasoning_models = [x for x in text_models if _is_reasoning_model(x)]
    # Pricing travels with the model list so the New Project dialog can price a run
    # before it starts, using the same figures the worker bills against.
    return {'text_models': text_models, 'image_models': image_models, 'reasoning_models': reasoning_models, 'source': source, 'gemini_available': bool(cfg['gemini_api_key']), 'gemini_models': list(settings.gemini_models), 'unavailable': unavailable, 'unpriced': sorted({x for x in text_models if x not in settings.text_pricing} | {x for x in image_models if x not in settings.image_pricing}), 'default_text_model': settings.openai_text_model, 'default_image_model': settings.openai_image_model, 'text_pricing': settings.text_pricing, 'image_pricing': settings.image_pricing}


@app.get('/api/assets')
def all_assets(db: Session = Depends(get_db), user=Depends(current)):
    rows = db.scalars(select(Asset).order_by(Asset.created_at.desc())).all()
    project_names = {x.id: x.name for x in db.scalars(select(Project)).all()}
    return [{'id': x.id, 'project_id': x.project_id, 'project_name': project_names.get(x.project_id, ''), 'kind': x.kind, 'label': x.label, 'url': x.url, 'prompt': x.prompt, 'model': x.model, 'width': x.width, 'height': x.height, 'cost': x.cost, 'metadata': json.loads(x.metadata_json or '{}'), 'created_at': x.created_at} for x in rows]


def _style_ai_payload(name, brief, reference_url=''):
    prompt = f'''Create a focused addendum for the fixed ARTLINE ecommerce design system. Style name: {name}.
Brief: {brief}
Reference URL: {reference_url}

The fixed ARTLINE foundation already controls HTML validity, six-section structure, responsive behavior, factual accuracy, 12px geometry and typography. Do not replace or contradict it. The returned style_prompt must contain only useful category-specific art direction: content emphasis, section rhythm, image mood and product-category storytelling.

Mandatory color roles:
- #101010 headings and #555555 body text on light surfaces;
- #FFFFFF headings and #D0D7DE body text on dark surfaces;
- #19BCC9 only for compact badges, eyebrow labels, small specification values and subtle borders;
- never use accent colors for paragraphs or long headings;
- at least 70 percent light or transparent surfaces;
- no more than two accent colors;
- no alternating card colors, decorative strips, excessive gradients or repeated heavy shadows.

Return strict JSON with keys description, style_prompt, hero_prompt, feature_prompt, negative_prompt, score (object with consistency, readability, brand_fit integers 0-100), preview_html. The preview_html must be a compact light demo section using inline CSS only, 12px radius, accessible text contrast and no h1.'''
    return prompt


@app.post('/api/styles/generate')
def generate_style(payload: StyleGenerateIn, user=Depends(require_perm('style.manage'))):
    check_action(user.id, 'style_ai', 4); check_budget(); check_user_budget(user)
    model = payload.model or settings.openai_text_model
    fallback = {'description': 'Згенерований ARTLINE-стиль', 'style_prompt': DEFAULT_STYLE_PROMPT + '\n' + payload.brief, 'hero_prompt': DEFAULT_HERO_PROMPT, 'feature_prompt': DEFAULT_FEATURE_PROMPT, 'negative_prompt': DEFAULT_NEGATIVE_PROMPT, 'score': {'consistency': 96, 'readability': 97, 'brand_fit': 97}, 'preview_html': '<section style="padding:32px;border-radius:12px;background:#F7F8FA;border:1px solid #D0D7DE;color:#101010;font-family:Arial;box-sizing:border-box"><div style="font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#19BCC9">ARTLINE STYLE</div><h2 style="font-size:36px;line-height:1.1;margin:12px 0;color:#101010">Premium product presentation</h2><p style="max-width:620px;margin:0;color:#555555;line-height:1.6">Unified ARTLINE visual system preview.</p></section>', 'model': model}
    if not settings.openai_api_key: return fallback
    try:
        from openai import OpenAI
        r = OpenAI(api_key=settings.openai_api_key).responses.create(model=model, input=_style_ai_payload(payload.name, payload.brief, payload.reference_url), max_output_tokens=6000, store=False)
        raw = r.output_text.strip(); raw = raw[raw.find('{'):raw.rfind('}') + 1]; data = json.loads(raw)
        addendum = str(data.get('style_prompt') or '').strip()
        data['style_prompt'] = DEFAULT_STYLE_PROMPT + (f'\n\nSTYLE-SPECIFIC ADDENDUM:\n{addendum}' if addendum else '')
        data['hero_prompt'] = str(data.get('hero_prompt') or DEFAULT_HERO_PROMPT)
        data['feature_prompt'] = str(data.get('feature_prompt') or DEFAULT_FEATURE_PROMPT)
        data['negative_prompt'] = str(data.get('negative_prompt') or DEFAULT_NEGATIVE_PROMPT)
        data['preview_html'] = sanitize_html(str(data.get('preview_html') or ''))
        data['model'] = model
        return data
    except Exception as exc:
        fallback['warning'] = str(exc); return fallback


@app.post('/api/styles/{style_id}/improve')
def improve_style(style_id: str, payload: StyleImproveIn, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    check_action(user.id, 'style_ai', 4); check_budget(); check_user_budget(user)
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    generated = generate_style(StyleGenerateIn(name=s.name, brief=(s.prompt + '\nImprovement request: ' + payload.instructions)[:12000], model=payload.model), user)
    # Повертаємо ПРОПОЗИЦІЮ разом із поточним - фронтенд показує diff, оператор
    # приймає свідомо, а не наосліп перезаписує ручні правки.
    generated['current'] = {'prompt': s.prompt, 'hero_prompt': s.hero_prompt,
                            'feature_prompt': s.feature_prompt, 'negative_prompt': s.negative_prompt}
    return generated


@app.get('/api/system')
def system_status(db: Session = Depends(get_db), user=Depends(require_perm('settings.view'))):
    """Operational overview for the settings page: what is configured and healthy."""
    import shutil as _shutil
    redis_ok = False
    try:
        import redis as redis_lib
        redis_ok = bool(redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping())
    except Exception:
        pass
    worker_ok = False
    try:
        from app.celery_app import celery as celery_app
        replies = celery_app.control.ping(timeout=2)
        worker_ok = bool(replies)
    except Exception:
        pass
    media_total, media_used, media_free = 0, 0, 0
    try:
        du = _shutil.disk_usage(settings.media_dir)
        media_total, media_used, media_free = du.total, du.used, du.free
    except Exception:
        pass
    media_files = 0
    media_bytes = 0
    try:
        for f in Path(settings.media_dir).rglob('*'):
            if f.is_file():
                media_files += 1
                media_bytes += f.stat().st_size
    except Exception:
        pass
    payload = {
        'version': APP_VERSION,
        'openai_configured': bool(runtime_config()['openai_api_key']),
        'gemini_configured': bool(runtime_config()['gemini_api_key']),
        'llm_provider': runtime_config()['llm_provider'],
        'default_text_model': settings.openai_text_model,
        'default_image_model': settings.openai_image_model,
        'reasoning_effort': settings.openai_reasoning_effort,
        'db_schema': settings.db_schema,
        'redis_ok': redis_ok,
        'worker_ok': worker_ok,
        'watchdog_minutes': settings.stuck_project_minutes,
        'queued_watchdog_hours': settings.queued_project_hours,
        'daily_budget_usd': float(settings.daily_budget_usd or 0),
        'today_spend_usd': round(today_spend(), 4),
        'shots_enabled': bool(settings.shots_url),
        'code_graph_url': ('/api/system/graph?t=' + sign_media_path('/api/system/graph')) if (is_root_admin(user) and _GRAPH_FILE.is_file()) else '',
        'alerts_telegram': bool(settings.telegram_bot_token and settings.telegram_chat_id),
        'alerts_webhook': bool(settings.alert_webhook_url),
        'media_files': media_files,
        'media_bytes': media_bytes,
        'disk_free_bytes': media_free,
        'disk_total_bytes': media_total,
        'projects': db.scalar(select(func.count(Project.id))) or 0,
        'styles': db.scalar(select(func.count(Style.id))) or 0,
        'users': db.scalar(select(func.count(User.id))) or 0,
    }
    if not is_root_admin(user):
        # Інфраструктурні поля - лише root-адміну: схема БД, диск і версія білда
        # описують нутрощі проєкту, а сторінку бачить будь-хто з settings.view.
        for infra_key in ('db_schema', 'disk_free_bytes', 'disk_total_bytes', 'version'):
            payload.pop(infra_key, None)
    return payload


_GRAPH_FILE = Path(__file__).resolve().parent.parent / 'graph' / 'graph.html'


@app.get('/api/system/graph')
def code_graph(t: str = ''):
    """Мапа кодової бази (Graphify) для root-адміна.

    Capability-посилання в стилі /media: HMAC-токен у query, бо клік по
    посиланню в новій вкладці не несе Authorization-заголовка. Токен видається
    лише root-адміну через /api/system."""
    if not verify_media_token('/api/system/graph', t):
        raise HTTPException(403, 'Посилання недійсне')
    if not _GRAPH_FILE.is_file():
        raise HTTPException(404, 'Мапу ще не згенеровано: /graphify . → sh scripts/update-graph.sh → deploy')
    return FileResponse(_GRAPH_FILE, media_type='text/html')


def require_root(user=Depends(current)):
    """Provider keys are the one setting even a full admin cannot touch: they bill
    real money and unlock every generation. Only the ADMIN_EMAIL account qualifies."""
    if not is_root_admin(user):
        raise HTTPException(403, 'Доступно лише головному адміністратору')
    return user


def _secrets_view():
    cfg = runtime_config(force=True)
    return {
        'llm_provider': cfg['llm_provider'],
        'openai_api_key': mask(cfg['openai_api_key']),
        'openai_api_key_source': cfg['openai_api_key_source'],
        'gemini_api_key': mask(cfg['gemini_api_key']),
        'gemini_api_key_source': cfg['gemini_api_key_source'],
        'openrouter_api_key': mask(cfg['openrouter_api_key']),
        'openrouter_api_key_source': cfg['openrouter_api_key_source'],
        'openrouter_text_model': cfg['openrouter_text_model'],
        'local_base_url': cfg.get('local_base_url', ''),
        'local_api_key': mask(cfg.get('local_api_key', '')),
        'local_text_models': cfg.get('local_text_models', ''),
    }


@app.get('/api/providers/balance')
def providers_balance(db: Session = Depends(get_db), user=Depends(require_root)):
    """Account balances where the provider exposes them, honesty where it does not.

    OpenRouter reports credits on the same API key (GET /api/v1/credits). OpenAI
    deliberately offers no balance endpoint for API keys and Gemini has none
    either, so for those the studio shows its own 30-day spend from the database -
    a number we actually know - plus a link to the provider's billing page.
    """
    import httpx as _httpx
    cfg = runtime_config()
    since = datetime.utcnow() - timedelta(days=30)
    projects = db.scalars(select(Project).where(Project.created_at >= since)).all()
    text_spend = sum(p.text_cost or 0 for p in projects)
    gemini_images = db.scalar(
        select(func.coalesce(func.sum(Asset.cost), 0.0)).where(Asset.created_at >= since, Asset.model.like('gemini-%'))
    ) or 0.0
    openai_images = db.scalar(
        select(func.coalesce(func.sum(Asset.cost), 0.0)).where(Asset.created_at >= since, Asset.model.not_like('gemini-%'), Asset.cost > 0)
    ) or 0.0
    out = {
        'openai': {
            'configured': bool(cfg['openai_api_key']),
            'balance': None,
            'note': 'OpenAI не надає баланс за API-ключем — перевіряйте на platform.openai.com/settings/organization/billing',
            'spend_30d': round(text_spend + openai_images, 4),
        },
        'gemini': {
            'configured': bool(cfg['gemini_api_key']),
            'balance': None,
            'note': 'Gemini не має API балансу; безкоштовний тир — 500 зображень/день. Витрати: console.cloud.google.com/billing',
            'spend_30d': round(gemini_images, 4),
        },
        'openrouter': {
            'configured': bool(cfg['openrouter_api_key']),
            'balance': None,
            'note': '',
            'spend_30d': 0.0,
        },
    }
    if cfg['openrouter_api_key']:
        try:
            with _httpx.Client(timeout=10) as http:
                reply = http.get(f'{OPENROUTER_BASE_URL}/credits', headers={'Authorization': f"Bearer {cfg['openrouter_api_key']}"})
                reply.raise_for_status()
                data = (reply.json() or {}).get('data') or {}
                total = float(data.get('total_credits') or 0)
                used = float(data.get('total_usage') or 0)
                out['openrouter']['balance'] = round(total - used, 4)
                out['openrouter']['spend_30d'] = round(used, 4)
        except Exception as exc:
            out['openrouter']['note'] = f'Не вдалося отримати баланс: {str(exc)[:120]}'
    return out


@app.get('/api/secrets')
def get_secrets(user=Depends(require_root)):
    """Masked only. A stored key is never returned to any client in full."""
    return _secrets_view()


@app.put('/api/secrets')
def put_secrets(body: SecretsIn, db: Session = Depends(get_db), user=Depends(require_root)):
    values = {}
    if body.llm_provider in ('openai', 'openrouter', 'local'):
        values['llm_provider'] = body.llm_provider
    if body.openrouter_text_model is not None:
        values['openrouter_text_model'] = body.openrouter_text_model.strip()[:120]
    if body.local_base_url is not None:
        url = body.local_base_url.strip()[:300]
        if url and not url.startswith(('http://', 'https://')):
            raise HTTPException(400, 'Базовий URL локального сервера має починатися з http(s)://')
        values['local_base_url'] = url
    if body.local_text_models is not None:
        values['local_text_models'] = body.local_text_models.strip()[:500]
    for field in ('openai_api_key', 'gemini_api_key', 'openrouter_api_key', 'local_api_key'):
        raw = getattr(body, field)
        if raw is None:
            continue
        raw = raw.strip()
        # The UI shows a masked key; echoing it back must not overwrite the real one.
        if '\u2022' in raw:
            continue
        values[field] = raw
    if not values:
        return _secrets_view()
    set_runtime(values, by=user.email)
    # Log which keys changed, never their values.
    audit(db, user, 'secrets.update', entity_type='settings', metadata={'keys': sorted(values)})
    db.commit()
    return _secrets_view()


@app.post('/api/secrets/test')
def test_secrets(user=Depends(require_root)):
    """Ask the configured provider to list models. Cheapest call that proves the
    key is live, has quota and is reachable from this container."""
    api, provider = text_client()
    if api is None:
        return {'ok': False, 'provider': provider, 'detail': 'Ключ не налаштовано'}
    try:
        names = [m.id for m in api.models.list()]
    except Exception as exc:
        return {'ok': False, 'provider': provider, 'detail': str(exc)[:300]}
    return {'ok': True, 'provider': provider, 'models': len(names)}


@app.post('/api/client-error')
def client_error(body: ClientErrorIn, db: Session = Depends(get_db), user=Depends(current)):
    """A frontend crash the operator would otherwise never report.

    The browser self-throttles, but a client cannot be trusted to throttle anything,
    so the cap is enforced here too: past it the report is logged and acknowledged
    but no alert is raised. Alerting is best-effort and never breaks the response.
    """
    detail = body.text.strip()[:1000]
    logger.warning('Frontend error from %s at %s: %s', user.email, body.url[:200], detail)
    if not rate_limit_client_error(user.id):
        return {'ok': True, 'throttled': True}
    audit(db, user, 'client.error', entity_type='frontend', metadata={'url': body.url[:200], 'text': detail})
    db.commit()
    try:
        from app.tasks import send_alert
        send_alert(f'Rich Studio UI error\nUser: {user.email}\nPage: {body.url[:200]}\n{detail[:400]}')
    except Exception:
        pass
    return {'ok': True}


@app.get('/api/usage')
def usage(days: int = 0, user_id: str = '', db: Session = Depends(get_db), user=Depends(require_perm('usage.view'))):
    """Використання з фільтрами: період (days, 0 = весь час) і користувач.

    by_user рахується по всьому ПЕРІОДУ незалежно від фільтра користувача -
    таблиця людей лишається повною, фільтр звужує лише картки й графік.
    """
    since = datetime.utcnow() - timedelta(days=days) if days and days > 0 else None
    period_query = select(Project)
    if since is not None:
        period_query = period_query.where(Project.created_at >= since)
    period_rows = db.scalars(period_query).all()
    rows = [p for p in period_rows if not user_id or p.owner_id == user_id]
    ids = {p.id for p in rows}
    total = sum(x.estimated_cost for x in rows)
    # Quality signal: does the team trust the output? A project counts as
    # "approved clean" when its review history contains an approval and never a
    # change request; manual HTML edits are artifact versions above v1.
    decisions = defaultdict(set)
    for r in db.scalars(select(Review)).all():
        decisions[r.project_id].add(r.decision)
    reviewed = [p for p in rows if decisions.get(p.id)]
    approved = [p for p in reviewed if 'approve' in decisions[p.id]]
    approved_clean = [p for p in approved if 'request_changes' not in decisions[p.id]]
    manual_edits = (db.scalar(select(func.count(Artifact.id)).where(
        Artifact.version > 1, Artifact.created_by.isnot(None), Artifact.project_id.in_(ids))) or 0) if ids else 0
    finished = [p for p in rows if p.status in (Status.review, Status.approved, Status.done, Status.changes_requested)]
    quality = {
        'reviewed_projects': len(reviewed),
        'approved_projects': len(approved),
        'approved_without_changes': len(approved_clean),
        'approve_rate': round(len(approved) / len(reviewed) * 100) if reviewed else None,
        'clean_approve_rate': round(len(approved_clean) / len(reviewed) * 100) if reviewed else None,
        'manual_html_edits': manual_edits,
        'generated_pages': sum(len([a for a in p.artifacts if a.version == 1]) for p in finished),
    }
    users_by_id = {u.id: (u.name or u.email) for u in db.scalars(select(User)).all()}
    per_user = {}
    for p in period_rows:
        key = p.owner_id or ''
        entry = per_user.setdefault(key, {'user_id': key, 'name': users_by_id.get(key, 'Без власника'),
                                          'projects': 0, 'cost': 0.0, 'input_tokens': 0, 'output_tokens': 0,
                                          'images': 0, 'approved': 0})
        entry['projects'] += 1
        entry['cost'] += float(p.estimated_cost or 0)
        entry['input_tokens'] += p.input_tokens or 0
        entry['output_tokens'] += p.output_tokens or 0
        entry['images'] += p.image_count or 0
        if 'approve' in decisions.get(p.id, set()):
            entry['approved'] += 1
    by_user = sorted(per_user.values(), key=lambda x: -x['cost'])
    # Динаміка: по днях для коротких періодів, по місяцях для року/всього часу.
    # Куди йдуть гроші: агрегат поетапних розбивок проєктів у вибраному зрізі.
    # 'other' - все, що поза генераційним розбором: переклади, AI-рецензії,
    # авто-виправлення (вони збільшують вартість проєкту після завершення).
    stage_totals = {'extract': 0.0, 'content': 0.0, 'images': 0.0, 'other': 0.0}
    for p in rows:
        try:
            bd = json.loads(p.cost_breakdown_json or '{}')
        except Exception:
            bd = {}
        extract = float((bd.get('extract') or {}).get('cost') or 0)
        content = float((bd.get('content') or {}).get('cost') or 0)
        images = float((bd.get('images') or {}).get('cost') or (p.image_cost or 0))
        stage_totals['extract'] += extract
        stage_totals['content'] += content
        stage_totals['images'] += images
        stage_totals['other'] += max(0.0, float(p.estimated_cost or 0) - extract - content - images)
    by_stage = {k: round(v, 4) for k, v in stage_totals.items()}
    bucket_fmt = '%Y-%m-%d' if days and days <= 92 else '%Y-%m'
    buckets = {}
    for p in rows:
        key = p.created_at.strftime(bucket_fmt)
        b = buckets.setdefault(key, {'day': key, 'cost': 0.0, 'projects': 0})
        b['cost'] += float(p.estimated_cost or 0)
        b['projects'] += 1
    by_day = sorted(buckets.values(), key=lambda x: x['day'])
    return {'total_cost': total, 'projects': len(rows), 'input_tokens': sum(x.input_tokens for x in rows), 'output_tokens': sum(x.output_tokens for x in rows), 'images': sum(x.image_count for x in rows), 'average_cost': total / len(rows) if rows else 0,
            'days': days, 'user_id': user_id, 'quality': quality, 'by_user': by_user, 'by_day': by_day, 'by_stage': by_stage,
            'by_project': [{'id': x.id, 'name': x.name, 'cost': x.estimated_cost, 'created_at': x.created_at} for x in sorted(rows, key=lambda x: x.created_at, reverse=True)[:20]]}
