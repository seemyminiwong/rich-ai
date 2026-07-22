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
            # networkidle сумнозвісно зависає (30 с) на будь-якому повільному
            # запиті і валить рендер у 500. Чекаємо лише DOM, а картинки -
            # окремо, з ЖОРСТКИМ лімітом: краще знімок без пари фото, ніж таймаут.
            page.set_default_timeout(20000)
            page.set_content(document, wait_until='domcontentloaded')
            try:
                # Чекаємо і <img>, і CSS background-image (Hero тягне фото саме
                # фоном) — інакше знімок ловить блок ще до появи картинки й вона
                # губиться. Усе під ЖОРСТКИМ лімітом 8 с: краще без пари фото.
                page.evaluate(
                    "() => {"
                    "const p = Array.from(document.images).filter(i=>!i.complete)"
                    ".map(i=>new Promise(r=>{i.onload=i.onerror=r}));"
                    "const re = /url\\((['\\\"]?)(.*?)\\1\\)/g;"
                    "for (const el of document.querySelectorAll('*')) {"
                    "const v = getComputedStyle(el).backgroundImage;"
                    "if (!v || v === 'none') continue;"
                    "let m; while ((m = re.exec(v))) {"
                    "const u = m[2];"
                    "if (!u || u.startsWith('data:')) continue;"
                    "p.push(new Promise(r=>{const im=new Image();im.onload=im.onerror=r;im.src=u;}));"
                    "}}"
                    "return Promise.race([Promise.all(p),"
                    "new Promise(r=>setTimeout(r,8000))]);}")
            except Exception:
                pass
            page.wait_for_timeout(400)
            blocks = page.query_selector_all('body > section > *') or page.query_selector_all('body > *')
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                index = 0
                for node in blocks:
                    try:
                        box = node.bounding_box()
                        if not box or box['height'] < 40 or box['width'] < 120:
                            continue
                        shot = node.screenshot(type='png', timeout=15000)
                    except Exception:
                        continue  # один проблемний блок не має валити весь ZIP
                    index += 1
                    title = ''
                    heading = node.query_selector('h2, h3')
                    if heading:
                        title = (heading.inner_text() or '').strip().split('\n')[0]
                    archive.writestr(f'{index:02d}-{_slug(title, "block")}.png', shot)
                try:
                    archive.writestr('00-full-page.png', page.screenshot(type='png', full_page=True, timeout=20000))
                except Exception:
                    pass
                if not index:
                    raise HTTPException(422, 'У HTML не знайдено жодного блока для знімка')
        finally:
            browser.close()
    stream.seek(0)
    return Response(stream.getvalue(), media_type='application/zip')
