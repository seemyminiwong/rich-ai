import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import User

oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


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
    except (JWTError, KeyError):
        raise HTTPException(401, "Invalid token")
    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(401, "Inactive user")
    return user
