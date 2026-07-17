"""Uvicorn server for the Playwright e2e job.

Serves the real API plus the real frontend from ONE origin, exactly like nginx
does in production (app.js calls relative /api/... paths). Static mount goes in
AFTER the API routes, so /api, /health and /media keep winning; everything else
falls through to apps/web (index.html, app.js, styles.css).

Run from repo root; cwd switches to apps/api so alembic.ini resolves the same
way it does inside the Docker image.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))
os.chdir(ROOT / 'apps' / 'api')

from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.main import app  # noqa: E402

app.mount('/', StaticFiles(directory=str(ROOT / 'apps' / 'web'), html=True), name='e2e-static')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='warning')
