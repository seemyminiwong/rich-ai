import hashlib
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
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_schema, get_db, run_migrations
from app.models import Artifact, Asset, AuditLog, CriticReport, Event, Invite, Project, Review, Role, Status, Style, StyleVersion, User
from app.security import PERMISSIONS, ROLE_DEFAULTS, current, effective_perms, has_perm, hash_password, require_perm, token, verify
from app.tasks import process_project, translate_project
from app.pipeline import _is_reasoning_model, fetch_html, gallery_urls, is_public_http_url, parse_page, sanitize_html, style_image_prompt, text_client
from app.runtime import OPENROUTER_BASE_URL, mask, runtime_config, set_runtime
from app.version import __version__

logger = logging.getLogger(__name__)
from app.prompts import (
    BASE_STYLE_NAME,
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
    yield


app = FastAPI(title='ARTLINE Rich Studio API', version=APP_VERSION, lifespan=lifespan)
app.mount('/media', StaticFiles(directory=settings.media_dir), name='media')


class Login(BaseModel): email: str; password: str
class RegisterIn(BaseModel): token: str; name: str = Field(min_length=2, max_length=120); password: str = Field(min_length=8, max_length=200)
class InviteIn(BaseModel): email: str; role: Role = Role.viewer
class UserUpdate(BaseModel): role: Role | None = None; active: bool | None = None; name: str | None = None
class UserPasswordIn(BaseModel): password: str = Field(min_length=8, max_length=200)
class ClientErrorIn(BaseModel):
    text: str = Field(max_length=2000)
    url: str = Field(default='', max_length=500)
    agent: str = Field(default='', max_length=300)
class SecretsIn(BaseModel):
    llm_provider: str | None = None
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
    name: str = ''; source_url: HttpUrl; style_id: str | None = None
    languages: list[str] = Field(default_factory=lambda: ['ua', 'ru'])
    variants: list[str] = Field(default_factory=lambda: ['desktop', 'mobile'])
    text_model: str | None = None; image_model: str | None = None; image_quality: str = 'medium'
    custom_hero_url: str = ''; custom_feature_url: str = ''
    gallery: list[str] = Field(default_factory=list, max_length=10)
    reuse_images_from: str = ''
    reuse_labels: list[str] = Field(default_factory=list, max_length=10)
    adopt_images: list[AdoptItem] = Field(default_factory=list, max_length=10)
class StyleIn(BaseModel):
    name: str
    description: str = ''
    prompt: str = ''
    hero_prompt: str = ''
    feature_prompt: str = ''
    negative_prompt: str = ''
    score: dict = Field(default_factory=dict)
    preview_html: str = ''
    is_default: bool = False
class StyleGenerateIn(BaseModel):
    name: str = 'Новий стиль'
    brief: str = ''
    reference_url: str = ''
    model: str | None = None
class StyleImproveIn(BaseModel):
    instructions: str = ''
    model: str | None = None
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


# Simple in-memory login throttle: max attempts per identifier inside the window.
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[str, list[float]] = defaultdict(list)


def rate_limit_login(identifier: str):
    now = time.time()
    attempts = [t for t in _login_attempts[identifier] if now - t < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        _login_attempts[identifier] = attempts
        raise HTTPException(429, 'Забагато спроб входу. Зачекайте кілька хвилин і спробуйте знову')
    attempts.append(now)
    _login_attempts[identifier] = attempts


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
            'permissions': sorted(effective_perms(x)),
            'granted': sorted(overrides.get('grant') or []), 'revoked': sorted(overrides.get('revoke') or []),
            'created_at': x.created_at, 'last_login_at': x.last_login_at}
def style_dict(x): return {'id': x.id, 'name': x.name, 'description': x.description, 'prompt': x.prompt, 'hero_prompt': x.hero_prompt, 'feature_prompt': x.feature_prompt, 'negative_prompt': x.negative_prompt, 'score': json.loads(x.score_json or '{}'), 'preview_html': x.preview_html, 'is_default': x.is_default}
def artifact_dict(x): return {'id': x.id, 'language': x.language, 'variant': x.variant, 'html': x.html, 'version': x.version, 'created_at': x.created_at}
def project_dict(p, full=False, style_name=''):
    try:
        product = json.loads(p.product_json or '{}')
    except Exception:
        product = {}
    try:
        breakdown = json.loads(getattr(p, 'cost_breakdown_json', None) or '{}')
    except Exception:
        breakdown = {}
    r = {'id': p.id, 'name': p.name, 'source_url': p.source_url, 'style_id': p.style_id, 'style_name': style_name, 'owner_id': p.owner_id, 'status': p.status.value, 'stage': p.stage, 'progress': p.progress,
         'languages': [x for x in p.languages.split(',') if x], 'variants': [x for x in p.variants.split(',') if x], 'text_model': p.text_model, 'image_model': p.image_model, 'image_quality': p.image_quality,
         'custom_hero_url': p.custom_hero_url, 'custom_feature_url': p.custom_feature_url, 'product_category': p.product_category, 'sku': str(product.get('sku') or ''), 'cost_breakdown': breakdown, 'error': p.error, 'duration_seconds': p.duration_seconds, 'input_tokens': p.input_tokens, 'output_tokens': p.output_tokens,
         'image_count': p.image_count, 'text_request_count': p.text_request_count, 'image_request_count': p.image_request_count, 'text_cost': p.text_cost, 'image_cost': p.image_cost, 'estimated_cost': p.estimated_cost,
         'created_at': p.created_at, 'started_at': p.started_at, 'finished_at': p.finished_at}
    if full:
        r['product_json'] = p.product_json; r['source_images'] = p.source_images
        r['artifacts'] = [artifact_dict(x) for x in sorted(p.artifacts, key=lambda a: (a.language, a.variant, a.version))]
    return r


@app.get('/health')
def health(): return {'status': 'ok', 'version': APP_VERSION}


@app.post('/api/auth/login')
def login(payload: Login, db: Session = Depends(get_db)):
    rate_limit_login((payload.email or '').strip().lower() or 'unknown')
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify(payload.password, user.password_hash): raise HTTPException(401, 'Неправильний email або пароль')
    if not user.active: raise HTTPException(403, 'Обліковий запис деактивовано')
    user.last_login_at = datetime.utcnow(); audit(db, user, 'auth.login', 'user', user.id); db.commit()
    return {'access_token': token(user), 'token_type': 'bearer'}


@app.post('/api/auth/register')
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    h = hashlib.sha256(payload.token.encode()).hexdigest(); inv = db.scalar(select(Invite).where(Invite.token_hash == h))
    if not inv or inv.accepted_at or inv.expires_at < datetime.utcnow(): raise HTTPException(400, 'Запрошення недійсне або прострочене')
    if db.scalar(select(User).where(User.email == inv.email)): raise HTTPException(409, 'Користувач уже існує')
    user = User(email=inv.email, name=payload.name, password_hash=hash_password(payload.password), role=inv.role, active=True)
    db.add(user); inv.accepted_at = datetime.utcnow(); db.flush(); audit(db, user, 'auth.register', 'user', user.id); db.commit()
    return {'access_token': token(user), 'token_type': 'bearer'}


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
    return {'token': raw, 'register_path': f'/register?token={raw}', 'expires_at': inv.expires_at}


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
def styles(db: Session = Depends(get_db), user=Depends(current)): return [style_dict(x) for x in db.scalars(select(Style).order_by(Style.name)).all()]


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
def style_preview_generate(style_id: str, db: Session = Depends(get_db), user=Depends(require_perm('style.manage'))):
    """Generate a real AI example page for this style from the demo product and save it."""
    from types import SimpleNamespace
    from app.pipeline import generate_html
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    style_ns = SimpleNamespace(prompt=s.prompt, hero_prompt=s.hero_prompt, feature_prompt=s.feature_prompt, negative_prompt=s.negative_prompt)
    html, _i, _o, reason = generate_html(DEMO_PRODUCT, style_ns, 'ua', 'desktop', '', '', settings.openai_text_model)
    s.preview_html = sanitize_html(html)
    audit(db, user, 'style.preview', 'style', s.id, {'ai': not reason})
    db.commit()
    return {'html': s.preview_html, 'source': 'demo' if reason else 'generated', 'note': reason or ''}


@app.get('/api/styles/{style_id}/versions')
def style_versions(style_id: str, db: Session = Depends(get_db), user=Depends(current)):
    rows = db.scalars(select(StyleVersion).where(StyleVersion.style_id == style_id).order_by(StyleVersion.version.desc())).all()
    return [{'id': x.id, 'version': x.version, 'prompt': x.prompt, 'hero_prompt': x.hero_prompt, 'feature_prompt': x.feature_prompt, 'created_at': x.created_at} for x in rows]


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
    """Translate the newest finished variants into one more language.

    Unlike a rerun this touches nothing but copy: no scrape, no images, no master
    regeneration - so it cannot degrade an approved layout and costs only the
    translation tokens.
    """
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, 'Проєкт не знайдено')
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
        new_url = asset.url
        if asset.url.startswith(prefix):
            name = asset.url[len(prefix):]
            src_file = Path(settings.media_dir) / source.id / name
            if not src_file.exists():
                continue
            dst_dir = Path(settings.media_dir) / new_project.id
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_dir / name)
            new_url = f'/media/{new_project.id}/{name}'
        db.add(Asset(project_id=new_project.id, kind='image', label=asset.label, url=new_url, prompt=asset.prompt, model=asset.model, width=asset.width, height=asset.height, cost=0, metadata_json=json.dumps({'adopted_from': source.id}, ensure_ascii=False)))
        if asset.label != 'product-reference':
            adopted += 1
    return adopted



@app.post('/api/projects/probe')
def probe_product_page(payload: ProbeIn, user=Depends(require_perm('project.create'))):
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


@app.post('/api/projects')
def create_project(payload: ProjectIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    style = db.get(Style, payload.style_id) if payload.style_id else db.scalar(select(Style).where(Style.is_default == True))
    if not style: raise HTTPException(400, 'Немає доступного стилю')
    langs = normalize_languages(payload.languages); vars = [x for x in payload.variants if x in {'desktop', 'mobile'}]
    if not langs or not vars: raise HTTPException(400, 'Оберіть щонайменше одну мову та формат')
    for label, value in (('Hero', payload.custom_hero_url.strip()), ('Feature', payload.custom_feature_url.strip())):
        if value and not is_public_http_url(value):
            raise HTTPException(400, f'Власне {label} URL має бути публічним http(s)-посиланням')
    p = Project(name=payload.name.strip() or 'Определение товара…', source_url=str(payload.source_url), style_id=style.id, owner_id=user.id, languages=','.join(dict.fromkeys(langs)), variants=','.join(dict.fromkeys(vars)),
                text_model=payload.text_model or settings.openai_text_model, image_model=payload.image_model or settings.openai_image_model, image_quality=payload.image_quality if payload.image_quality in {'low', 'medium', 'high'} else 'medium', custom_hero_url=payload.custom_hero_url.strip(), custom_feature_url=payload.custom_feature_url.strip(), gallery_json=json.dumps([u.strip() for u in payload.gallery if is_public_http_url(u.strip())][:10]), status=Status.queued, stage='queued')
    db.add(p); db.flush()
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
    process_project.delay(p.id, reuse_images=bool(adopted))
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


@app.delete('/api/projects/{project_id}')
def delete_project(project_id: str, db: Session = Depends(get_db), user=Depends(require_perm('project.delete'))):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
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
    media_root = Path(settings.media_dir).resolve()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        with httpx.Client(timeout=20, follow_redirects=True) as http:
            for asset in assets:
                if not asset.url or asset.url in image_paths:
                    continue
                try:
                    data = b''
                    suffix = Path(asset.url.split('?', 1)[0]).suffix.lower()
                    if suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.avif'}:
                        suffix = '.webp'
                    if asset.url.startswith('/media/'):
                        candidate = (media_root / asset.url.removeprefix('/media/')).resolve()
                        if media_root not in candidate.parents and candidate != media_root:
                            raise ValueError('unsafe media path')
                        data = candidate.read_bytes()
                    elif asset.url.startswith(('http://', 'https://')):
                        if not is_public_http_url(asset.url):
                            raise ValueError('non-public image url blocked')
                        response = http.get(asset.url)
                        response.raise_for_status()
                        data = response.content
                        content_type = response.headers.get('content-type', '').lower()
                        if 'png' in content_type: suffix = '.png'
                        elif 'jpeg' in content_type: suffix = '.jpg'
                        elif 'webp' in content_type: suffix = '.webp'
                    if not data:
                        raise ValueError('empty image')
                    if data.startswith(b'\x89PNG\r\n\x1a\n'):
                        suffix = '.png'
                    elif data.startswith(b'\xff\xd8\xff'):
                        suffix = '.jpg'
                    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                        suffix = '.webp'
                    filename = f"{_archive_name(asset.label, 'image')}-{asset.id[:8]}{suffix}"
                    target = f'images/{filename}'
                    archive.writestr(target, data)
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
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    if p.status in {Status.processing, Status.queued}: raise HTTPException(409, 'Проєкт уже виконується або стоїть у черзі')
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
    p.status = Status.queued; p.stage = 'queued'; p.progress = 0; p.error = ''; p.input_tokens = 0; p.output_tokens = 0; p.image_count = 0; p.text_request_count = 0; p.image_request_count = 0; p.text_cost = 0; p.image_cost = 0; p.estimated_cost = 0
    reuse = bool(payload and payload.reuse_images)
    audit(db, user, 'project.rerun', 'project', p.id, {'style_id': p.style_id, 'languages': p.languages, 'variants': p.variants, 'reuse_images': reuse}); db.commit()
    process_project.delay(p.id, reuse_images=reuse)
    return {'queued': True, 'style_id': p.style_id, 'languages': p.languages.split(','), 'variants': p.variants.split(','), 'reuse_images': reuse}


@app.post('/api/projects/{project_id}/queue')
def queue_control(project_id: str, payload: QueueIn, db: Session = Depends(get_db), user=Depends(require_perm('project.create'))):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, 'Проєкт не знайдено')
    if payload.action in {'pause', 'cancel'}:
        # The running worker checks project.status between stages and stops cleanly.
        p.status = Status.paused if payload.action == 'pause' else Status.cancelled
        p.stage = p.status.value
        db.add(Event(project_id=p.id, stage=p.stage, level='warning', message=f'{user.email}: {"пауза" if payload.action == "pause" else "скасування"}'))
    elif payload.action in {'resume', 'retry'}:
        if p.status in {Status.processing, Status.queued}: raise HTTPException(409, 'Проєкт уже виконується')
        p.status = Status.queued; p.stage = 'queued'; p.progress = 0; p.error = ''
        db.add(Event(project_id=p.id, stage='queued', message=f'{user.email}: повторний запуск з черги'))
        audit(db, user, 'queue.' + payload.action, 'project', p.id); db.commit(); process_project.delay(p.id); return {'status': p.status.value}
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
    db.execute(sa_delete(CriticReport).where(CriticReport.project_id == p.id))
    reports = []
    for kind in ('html', 'facts', 'accessibility', 'marketing'):
        score, summary, issues, suggestions = critic_html(list(latest.values()), kind, json.loads(p.product_json or '{}'))
        row = CriticReport(project_id=p.id, critic_type=kind, score=score, summary=summary, issues_json=json.dumps(issues, ensure_ascii=False), suggestions_json=json.dumps(suggestions, ensure_ascii=False), auto_fixed=False)
        db.add(row); reports.append({'type': kind, 'score': score, 'summary': summary, 'issues': issues, 'suggestions': suggestions})
    db.add(Event(project_id=p.id, stage='critic', message=f'{user.email}: перевірку якості перезапущено')); audit(db, user, 'critic.run', 'project', p.id); db.commit(); return reports


@app.put('/api/artifacts/{artifact_id}')
def save_artifact(artifact_id: str, payload: HtmlIn, db: Session = Depends(get_db), user=Depends(require_perm('project.edit_html'))):
    source = db.get(Artifact, artifact_id)
    if not source:
        raise HTTPException(404, 'Результат не знайдено')
    clean = sanitize_html(payload.html)
    if '<section' not in clean:
        raise HTTPException(400, 'HTML має містити принаймні один <section> блок')
    try:
        # Serialize version allocation for one project. The UI blocks double clicks,
        # while this lock also protects simultaneous saves from different users.
        db.scalar(select(Project.id).where(Project.id == source.project_id).with_for_update())
        latest_version = db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == source.project_id, Artifact.language == source.language, Artifact.variant == source.variant)) or 0
        new = Artifact(project_id=source.project_id, language=source.language, variant=source.variant, html=clean, version=latest_version + 1, created_by=user.id)
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
    s = db.get(Style, style_id)
    if not s: raise HTTPException(404, 'Стиль не знайдено')
    generated = generate_style(StyleGenerateIn(name=s.name, brief=(s.prompt + '\nImprovement request: ' + payload.instructions)[:12000], model=payload.model), user)
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
    return {
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
    if body.llm_provider in ('openai', 'openrouter'):
        values['llm_provider'] = body.llm_provider
    if body.openrouter_text_model is not None:
        values['openrouter_text_model'] = body.openrouter_text_model.strip()[:120]
    for field in ('openai_api_key', 'gemini_api_key', 'openrouter_api_key'):
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
def usage(db: Session = Depends(get_db), user=Depends(require_perm('usage.view'))):
    rows = db.scalars(select(Project)).all(); total = sum(x.estimated_cost for x in rows)
    # Quality signal: does the team trust the output? A project counts as
    # "approved clean" when its review history contains an approval and never a
    # change request; manual HTML edits are artifact versions above v1.
    reviews = db.scalars(select(Review)).all()
    decisions = defaultdict(set)
    for r in reviews:
        decisions[r.project_id].add(r.decision)
    reviewed = [p for p in rows if decisions.get(p.id)]
    approved = [p for p in reviewed if 'approve' in decisions[p.id]]
    approved_clean = [p for p in approved if 'request_changes' not in decisions[p.id]]
    manual_edits = db.scalar(select(func.count(Artifact.id)).where(Artifact.version > 1, Artifact.created_by.isnot(None))) or 0
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
    return {'total_cost': total, 'projects': len(rows), 'input_tokens': sum(x.input_tokens for x in rows), 'output_tokens': sum(x.output_tokens for x in rows), 'images': sum(x.image_count for x in rows), 'average_cost': total / len(rows) if rows else 0,
            'quality': quality,
            'by_project': [{'id': x.id, 'name': x.name, 'cost': x.estimated_cost, 'created_at': x.created_at} for x in sorted(rows, key=lambda x: x.created_at, reverse=True)[:20]]}
