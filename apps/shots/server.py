"""Рендер rich-HTML у PNG поблочно (окремий необовʼязковий сервіс).

Навіщо окремо: справжній Chromium важить сотні мегабайт, а потрібен лише за
кнопкою. Тому сервіс живе за профілем compose `shots`; без нього студія працює
як раніше, а кнопка експорту просто не показується.

Контракт простий: POST /render {html, width} -> ZIP з PNG кожного блока сторінки
плюс повний знімок. Сервіс НЕ ходить в інтернет за чужими сторінками: він
рендерить переданий HTML і тягне лише зображення самої студії (base_url у
compose-мережі).
"""
import io
import os
import re
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

BASE_URL = os.environ.get('SHOTS_BASE_URL', 'http://web')
MAX_HTML = 2_000_000

app = FastAPI(title='Rich Studio shots', version='1.0')


class RenderIn(BaseModel):
    html: str = Field(min_length=20)
    width: int = Field(default=1240, ge=320, le=2000)
    scale: int = Field(default=2, ge=1, le=3)
    background: str = Field(default='#FFFFFF', max_length=32)


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9А-Яа-яІіЇїЄєҐґ._-]+', '-', value or '').strip('-')
    return (cleaned[:48] or fallback).lower()


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/render')
def render(payload: RenderIn):
    try:
        return _render(payload)
    except HTTPException:
        raise
    except Exception as exc:  # причина має доїхати до оператора, а не зникнути в 500
        raise HTTPException(500, f'{type(exc).__name__}: {exc}'[:500])


def _render(payload: RenderIn):
    if len(payload.html) > MAX_HTML:
        raise HTTPException(413, 'HTML більший за 2 МБ')
    from playwright.sync_api import sync_playwright

    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<base href="{BASE_URL}/">'
        f'<style>html,body{{margin:0;padding:0;background:{payload.background};'
        'font-family:Roboto,Inter,Arial,sans-serif}</style></head>'
        f'<body>{payload.html}</body></html>'
    )
    stream = io.BytesIO()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': payload.width, 'height': 1200},
                                    device_scale_factor=payload.scale)
            page.set_content(document, wait_until='networkidle')
            # Дочекатись справжнього декодування картинок: інакше блок може
            # знятись із порожніми рамками.
            page.evaluate("() => Promise.all(Array.from(document.images)"
                          ".filter(i => !i.complete).map(i => new Promise(r => {i.onload = i.onerror = r})))")
            page.wait_for_timeout(300)
            # ':scope > *' у Playwright ненадійний, тому звичайні CSS-селектори:
            # блоки - прямі діти кореневої <section> (або тіла, якщо секції немає).
            blocks = page.query_selector_all('body > section > *') or page.query_selector_all('body > *')
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                index = 0
                for node in blocks:
                    box = node.bounding_box()
                    if not box or box['height'] < 40 or box['width'] < 120:
                        continue
                    index += 1
                    title = ''
                    heading = node.query_selector('h2, h3')
                    if heading:
                        title = (heading.inner_text() or '').strip().split('\n')[0]
                    name = f'{index:02d}-{_slug(title, "block")}.png'
                    archive.writestr(name, node.screenshot(type='png'))
                archive.writestr('00-full-page.png', page.screenshot(type='png', full_page=True))
                if not index:
                    raise HTTPException(422, 'У HTML не знайдено жодного блока для знімка')
        finally:
            browser.close()
    stream.seek(0)
    return Response(stream.getvalue(), media_type='application/zip')
