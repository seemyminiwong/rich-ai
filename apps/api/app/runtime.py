"""Runtime configuration the root admin can change without redeploying.

Keys live in .env by default. When a value is also stored in the database the
stored value wins, so the root admin can rotate a key from the UI. The API and
the Celery worker are separate processes, so neither can be signalled directly:
both re-read this table on their own every CACHE_TTL seconds instead. A rotated
key is therefore live everywhere within that window, with no restart.

Values here are secrets. They are never logged and never returned to a client in
full — see mask().
"""
import base64
import hashlib
import logging
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import AppSetting

CACHE_TTL = 15

logger = logging.getLogger(__name__)

# Values with these keys are encrypted at rest. Non-secret settings (provider
# choice, model name) stay readable - encrypting them buys nothing and makes
# debugging blind.
SECRET_KEYS = ('openai_api_key', 'gemini_api_key', 'openrouter_api_key')
_ENC_PREFIX = 'enc:v1:'


def _fernet() -> Fernet:
    # Derived from JWT_SECRET: no second secret to manage. Rotating JWT_SECRET
    # makes stored keys undecryptable - they fall back to .env / re-entry, which
    # is the documented, accepted cost.
    digest = hashlib.sha256(b'artline-appkeys:' + settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(value: str) -> str:
    return _ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def _decrypt(stored: str) -> str:
    """Decrypt an enc:v1: value; a failed decrypt means the JWT secret rotated -
    treat the key as absent rather than crashing every request."""
    try:
        return _fernet().decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        logger.warning('Stored secret cannot be decrypted (JWT_SECRET rotated?) - treating as unset')
        return ''


OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

# runtime key -> attribute on Settings holding the .env fallback (None = no fallback)
RUNTIME_KEYS = {
    'openai_api_key': 'openai_api_key',
    'gemini_api_key': 'gemini_api_key',
    'openrouter_api_key': None,
    'openrouter_text_model': None,
    'llm_provider': None,
}

DEFAULTS = {
    'llm_provider': 'openai',
    'openrouter_api_key': '',
    'openrouter_text_model': 'openai/gpt-4o-mini',
}

_cache = {'at': 0.0, 'data': None}


def _load() -> dict:
    stored = {}
    try:
        with SessionLocal() as db:
            for row in db.scalars(select(AppSetting)).all():
                stored[row.key] = row.value or ''
    except Exception:
        # First boot: the table may not exist yet. .env alone still works.
        pass
    out = {}
    for key, env_attr in RUNTIME_KEYS.items():
        env_value = getattr(settings, env_attr, '') if env_attr else DEFAULTS.get(key, '')
        value = stored.get(key) or ''
        if value.startswith(_ENC_PREFIX):
            value = _decrypt(value)
        out[key] = value or env_value
        out[key + '_source'] = 'database' if value else ('env' if env_value else 'none')
    if out['llm_provider'] not in ('openai', 'openrouter'):
        out['llm_provider'] = 'openai'
    return out


def runtime_config(force: bool = False) -> dict:
    now = time.time()
    if force or _cache['data'] is None or now - _cache['at'] > CACHE_TTL:
        _cache['data'] = _load()
        _cache['at'] = now
    return _cache['data']


def set_runtime(values: dict, by: str = '') -> None:
    """Persist runtime values. Only keys in RUNTIME_KEYS are accepted."""
    with SessionLocal() as db:
        for key, value in values.items():
            if key not in RUNTIME_KEYS:
                continue
            if key in SECRET_KEYS and value:
                value = _encrypt(value)
            row = db.get(AppSetting, key)
            if row is None:
                db.add(AppSetting(key=key, value=value or '', updated_by=by or ''))
            else:
                row.value = value or ''
                row.updated_by = by or ''
        db.commit()
    runtime_config(force=True)


def migrate_plaintext_secrets() -> int:
    """One-time, idempotent: encrypt any provider key still stored as plaintext.

    Runs at every API start; once every row carries the enc:v1: prefix this is a
    no-op. Old pg_dump files still hold the plaintext values - rotate the provider
    keys once after enabling encryption to devalue those backups.
    """
    migrated = 0
    with SessionLocal() as db:
        for key in SECRET_KEYS:
            row = db.get(AppSetting, key)
            if row and row.value and not row.value.startswith(_ENC_PREFIX):
                row.value = _encrypt(row.value)
                migrated += 1
        if migrated:
            db.commit()
            logger.info('Encrypted %d plaintext provider keys at rest', migrated)
    runtime_config(force=True)
    return migrated


def mask(value: str) -> str:
    """Show enough of a key to recognise it, never enough to use it."""
    v = (value or '').strip()
    if not v:
        return ''
    if len(v) <= 12:
        return '•' * 8
    return f'{v[:5]}{"•" * 10}{v[-4:]}'
