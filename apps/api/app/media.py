"""Signed /media URLs.

A media URL is a capability: whoever holds it may read the image. Until now the
capability was just an unguessable project UUID; a leaked URL worked for anyone,
forever. Now every generated URL carries an HMAC of its path, verified by the
serving endpoint.

Design constraints that shaped this:
- URLs are embedded into exported HTML pasted into the artline editor, so they
  must be self-contained (token in the query string, no headers, no cookies)
  and long-lived (no expiry: a published product page must not rot).
- Old artifacts and backups contain unsigned URLs. MEDIA_SIGNING=transitional
  (default) keeps them working while logging each unsigned hit; strict refuses.
"""
import hashlib
import hmac

from app.config import settings

_TOKEN_LENGTH = 24


def _media_key() -> bytes:
    # Derived from JWT_SECRET so no new secret needs managing; rotating the JWT
    # secret invalidates media tokens, which transitional mode absorbs.
    return hashlib.sha256(b'artline-media:' + settings.jwt_secret.encode()).digest()


def sign_media_path(path: str) -> str:
    """Token for a canonical path like /media/{project_id}/{filename}."""
    digest = hmac.new(_media_key(), path.encode(), hashlib.sha256).hexdigest()
    return digest[:_TOKEN_LENGTH]


def verify_media_token(path: str, token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(sign_media_path(path), token)


def media_url(project_id: str, filename: str) -> str:
    """The one way to build a /media URL anywhere in the codebase."""
    path = f'/media/{project_id}/{filename}'
    return f'{path}?t={sign_media_path(path)}'


def strip_media_query(url: str) -> str:
    """Canonical path of a possibly-signed media URL (for file resolution)."""
    return (url or '').split('?', 1)[0]
