import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import Role, User

oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Named capabilities. A user's effective set = role defaults + granted - revoked.
PERMISSIONS = {
    'project.create': 'Створювати та повторювати проєкти',
    'project.delete': 'Видаляти проєкти',
    'project.edit_html': 'Редагувати HTML і зберігати нові версії',
    'review.request_changes': 'Запитувати зміни під час перевірки',
    'review.approve': 'Схвалювати результат',
    'style.manage': 'Керувати стилями (створення, зміна, видалення)',
    'media.view': 'Переглядати медіатеку',
    'usage.view': 'Бачити використання і вартість',
    'settings.view': 'Бачити налаштування',
    'users.manage': 'Керувати користувачами та доступами',
}

ROLE_DEFAULTS = {
    Role.admin: set(PERMISSIONS),
    Role.editor: {'project.create', 'project.delete', 'project.edit_html', 'review.request_changes', 'style.manage', 'media.view', 'usage.view', 'settings.view'},
    Role.reviewer: {'review.request_changes', 'review.approve'},
    Role.viewer: {'media.view'},
}


def effective_perms(user: User) -> set:
    perms = set(ROLE_DEFAULTS.get(user.role, set()))
    try:
        overrides = json.loads(getattr(user, 'permissions_json', None) or '{}')
    except Exception:
        overrides = {}
    perms |= set(overrides.get('grant') or [])
    perms -= set(overrides.get('revoke') or [])
    return perms & set(PERMISSIONS)


def has_perm(user: User, name: str) -> bool:
    return name in effective_perms(user)


def require_perm(*names):
    """Grant access if the user holds ANY of the listed permissions."""
    def dep(user: User = Depends(current)):
        if not any(has_perm(user, n) for n in names):
            raise HTTPException(403, 'Недостатньо прав')
        return user
    return dep


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390000)
    return "pbkdf2_sha256$390000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt64, digest64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt64)
        expected = base64.b64decode(digest64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def token(user: User) -> str:
    payload = {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=24)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current(access_token: str = Depends(oauth), db: Session = Depends(get_db)) -> User:
    try:
        user_id = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except (PyJWTError, KeyError):
        raise HTTPException(401, "Invalid token")
    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(401, "Inactive user")
    return user
