"""Redis-backed rate limits and the daily spend budget.

The old login throttle lived in process memory: per-email only, wiped by every
deploy (and we deploy a dozen times a day). These counters live in the Redis
that is already running for Celery, so they survive restarts and cover both the
email and the client IP.

Everything here FAILS OPEN: if Redis is unreachable, the studio keeps working
without limits and logs the fact. An internal tool must not lock everyone out
because a sidecar container is restarting.
"""
import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)

_redis = None


def _client():
    global _redis
    if _redis is None:
        import redis as redis_lib
        _redis = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    return _redis


def client_ip(request: Request) -> str:
    # nginx sets X-Real-IP; direct loopback calls fall back to the socket peer.
    return (request.headers.get('x-real-ip') or (request.client.host if request.client else '') or 'unknown')[:64]


def _bump(key: str, window_seconds: int) -> int | None:
    """Increment a windowed counter; None means Redis is down (fail open)."""
    try:
        r = _client()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)
    except Exception as exc:
        logger.warning('Rate-limit storage unavailable, failing open: %s', exc)
        return None


def check_login(email: str, ip: str) -> None:
    """10 attempts per email and 30 per IP inside 5 minutes."""
    email_hits = _bump(f'rl:login:email:{email.lower()}', 300)
    ip_hits = _bump(f'rl:login:ip:{ip}', 300)
    if (email_hits or 0) > 10 or (ip_hits or 0) > 30:
        raise HTTPException(429, 'Забагато спроб входу. Зачекайте кілька хвилин і спробуйте знову')


def check_action(user_id: str, action: str, per_minute: int) -> None:
    """Per-user frequency cap for expensive endpoints."""
    bucket = int(time.time() // 60)
    hits = _bump(f'rl:{action}:{user_id}:{bucket}', 120)
    if hits is not None and hits > per_minute:
        raise HTTPException(429, f'Забагато запитів ({action}). Зачекайте хвилину')


# --- Daily spend budget ------------------------------------------------------

def _budget_key() -> str:
    return 'budget:' + datetime.now(timezone.utc).strftime('%Y-%m-%d')


_CUMULATIVE_CHARGE_LUA = """
local old = tonumber(redis.call('GET', KEYS[1]) or '0')
local new = tonumber(ARGV[1])
if new <= old then return 0 end
local delta = new - old
redis.call('SET', KEYS[1], tostring(new), 'EX', ARGV[2])
redis.call('INCRBYFLOAT', KEYS[2], delta)
redis.call('EXPIRE', KEYS[2], ARGV[3])
return tostring(delta)
"""


def _record_spend(bucket_key: str, amount_usd: float, operation_id: str = '', scope: str = 'global') -> None:
    """Atomically add spend; an operation id makes retries cumulative/idempotent."""
    if amount_usd <= 0:
        return
    try:
        r = _client()
        amount = round(amount_usd, 6)
        if operation_id:
            ledger_key = f'budget:charge:{scope}:{operation_id}'
            r.eval(_CUMULATIVE_CHARGE_LUA, 2, ledger_key, bucket_key, amount, 7 * 86400, 3 * 86400)
        else:
            r.incrbyfloat(bucket_key, amount)
            r.expire(bucket_key, 3 * 86400, nx=True)
    except Exception as exc:
        logger.warning('Budget storage unavailable: %s', exc)


def add_spend(amount_usd: float, operation_id: str = '') -> None:
    """Called by workers; operation_id prevents double billing on redelivery."""
    _record_spend(_budget_key(), amount_usd, operation_id, 'global')


def today_spend() -> float:
    try:
        return float(_client().get(_budget_key()) or 0.0)
    except Exception:
        return 0.0


def active_reserved_spend(user_id: str = '') -> float:
    """Read durable DB reservations, serialized with bulk commits.

    This is intentionally lazy to keep this limits module free of import cycles.
    Like the Redis guards, it fails open when the database is unavailable.
    """
    try:
        from sqlalchemy import func, select, text
        from app.db import SessionLocal
        from app.models import Project
        with SessionLocal() as db:
            if db.get_bind().dialect.name == 'postgresql':
                db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:lock_name))'), {
                    'lock_name': f'richstudio-bulk-import:{settings.db_schema}',
                })
            query = select(func.coalesce(func.sum(Project.reserved_cost), 0.0)).where(Project.reserved_cost > 0)
            if user_id:
                query = query.where(Project.owner_id == user_id)
            return float(db.scalar(query) or 0)
    except Exception as exc:
        logger.warning('Budget reservation storage unavailable, failing open: %s', exc)
        return 0.0


def check_budget() -> None:
    """Refuse to START new paid work past the daily cap; running work finishes.

    DAILY_BUDGET_USD=0 disables the check. The message states the numbers so the
    operator immediately knows this is a guardrail, not a malfunction.
    """
    cap = float(settings.daily_budget_usd or 0)
    if cap <= 0:
        return
    spent = today_spend()
    reserved = active_reserved_spend()
    if spent + reserved >= cap:
        raise HTTPException(429, f'Денний бюджет вичерпано: витрачено ${spent:.2f}, зарезервовано ${reserved:.2f} із ${cap:.2f}. '
                                 'Нові генерації зупинено до завтра; ліміт задається DAILY_BUDGET_USD у .env')


# --- Особистий денний бюджет користувача -------------------------------------

def _user_budget_key(user_id: str) -> str:
    return f'budget:user:{user_id}:' + datetime.now(timezone.utc).strftime('%Y-%m-%d')


def add_user_spend(user_id: str, amount_usd: float, operation_id: str = '') -> None:
    if not user_id or amount_usd <= 0:
        return
    _record_spend(_user_budget_key(user_id), amount_usd, operation_id, f'user:{user_id}')


def user_today_spend(user_id: str) -> float:
    try:
        return float(_client().get(_user_budget_key(user_id)) or 0.0)
    except Exception:
        return 0.0


def check_user_budget(user) -> None:
    """Особистий ліміт поверх глобального: 0 = вимкнено для цього користувача."""
    cap = float(getattr(user, 'daily_budget_usd', 0) or 0)
    if cap <= 0:
        return
    spent = user_today_spend(user.id)
    reserved = active_reserved_spend(user.id)
    if spent + reserved >= cap:
        raise HTTPException(429, f'Ваш особистий денний ліміт вичерпано: витрачено ${spent:.2f}, зарезервовано ${reserved:.2f} із ${cap:.2f}. '
                                 'Нові генерації - завтра, або попросіть адміністратора підняти ліміт')
