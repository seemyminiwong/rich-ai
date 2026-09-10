"""Рендер rich-HTML у PNG поблочно (окремий необовʼязковий сервіс).

Навіщо окремо: справжній Chromium важить сотні мегабайт, а потрібен лише за
кнопкою. Тому сервіс живе за профілем compose `shots`; без нього студія працює
як раніше, а кнопка експорту просто не показується.

Два контракти:
  POST /render {html, width} -> ZIP з PNG кожного блока сторінки плюс повний знімок.
  POST /audit  {html, width} -> JSON із ВИМІРЯНИМИ дефектами верстки (див. _audit).

Сервіс НЕ ходить в інтернет за чужими сторінками: він рендерить переданий HTML
і тягне лише зображення самої студії (base_url у compose-мережі).
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


class AuditIn(BaseModel):
    html: str = Field(min_length=20)
    width: int = Field(default=1240, ge=320, le=2000)
    label: str = Field(default='', max_length=60)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/audit')
def audit(payload: AuditIn):
    """Дефекти верстки, ВИМІРЯНІ у справжньому браузері, а не вгадані по HTML.

    Навіщо: рецензент студії читає розмітку й текст - і структурно не бачить
    того, що бачить покупець. Обрізаний текст, цифра, яка злилася з плиткою,
    горизонтальний скрол на телефоні, картинка, що не завантажилась - усе це
    існує лише після укладання сторінки. Тут вона укладається по-справжньому,
    і кожна знахідка має координати та фрагмент тексту, за якими її видно.
    """
    try:
        return _audit(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f'{type(exc).__name__}: {exc}'[:500])


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
            # Діагностика: чому саме гине Hero. Ловимо КОЖНУ невдалу мережеву
            # відповідь (403 на підпис, DNS, таймаут) - потім кладемо у ZIP
            # окремим _diagnostics.txt, щоб не гадати по чорному прямокутнику.
            net_log = []
            page.on('requestfailed', lambda r: net_log.append(f'FAIL  {r.method} {r.url}  :: {r.failure}'))
            page.on('response', lambda r: net_log.append(f'{r.status}  {r.url}') if r.status >= 400 else None)
            # networkidle сумнозвісно зависає (30 с) на будь-якому повільному
            # запиті і валить рендер у 500. Чекаємо лише DOM, а картинки -
            # окремо, з ЖОРСТКИМ лімітом: краще знімок без пари фото, ніж таймаут.
            page.set_default_timeout(20000)
            page.set_content(document, wait_until='domcontentloaded')
            # Чекаємо, доки КОЖНА картинка справді ДЕКОДОВАНА (naturalWidth>0),
            # а не просто "onload": інакше найважче фото (Hero) не встигає, і його
            # блок знімається порожнім, тоді як повний знімок пізніше вже з фото -
            # саме той рознобій і губив Hero. Фонові url() довантажуємо окремо.
            try:
                page.wait_for_function(
                    "() => Array.from(document.images)"
                    ".every(i => i.complete && i.naturalWidth > 0)",
                    timeout=12000)
            except Exception:
                pass
            try:
                page.evaluate(
                    "() => {"
                    "const re = /url\\((['\\\"]?)(.*?)\\1\\)/g; const p = [];"
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
            page.evaluate("() => window.scrollTo(0, 0)")

            # Один повний знімок сторінки - джерело істини; блоки ВИРІЗАЄМО з нього
            # за геометрією getBoundingClientRect. Так кожен блок піксель-у-пік
            # збігається з повною сторінкою: рознобою "у повному є, у блоці нема"
            # більше не існує в принципі.
            from PIL import Image as PILImage
            # Звіт по кожній картинці: URL, який реально тягнувся, і чи декодувалась.
            try:
                img_report = page.evaluate(
                    "() => Array.from(document.images).map((i,n) => "
                    "(n+1)+'. w='+i.naturalWidth+' complete='+i.complete+'  '"
                    "+(i.currentSrc||i.src))")
            except Exception as exc:
                img_report = [f'(img report failed: {exc})']
            diagnostics = (
                f'base_url={BASE_URL}\nviewport_width={payload.width} scale={payload.scale}\n\n'
                '== IMAGES (naturalWidth=0 => НЕ завантажилась) ==\n'
                + '\n'.join(img_report)
                + '\n\n== NETWORK ERRORS (порожньо = всі відповіді <400) ==\n'
                + ('\n'.join(net_log) if net_log else '(немає)'))
            full_png = page.screenshot(type='png', full_page=True, timeout=25000)
            scale = payload.scale
            blocks = page.query_selector_all('body > section > *') or page.query_selector_all('body > *')
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr('00-full-page.png', full_png)
                # Кладемо звіт лише коли є на що дивитися: якась картинка не
                # завантажилась або була мережева помилка. Чистий архів - без сміття.
                if net_log or any(' w=0 ' in line for line in img_report):
                    archive.writestr('_diagnostics.txt', diagnostics)
                full_img = PILImage.open(io.BytesIO(full_png))
                index = 0
                for node in blocks:
                    try:
                        rect = node.evaluate(
                            "el => {const r = el.getBoundingClientRect();"
                            "return {x:r.x, y:r.y, w:r.width, h:r.height};}")
                        if not rect or rect['h'] < 40 or rect['w'] < 120:
                            continue
                        left = max(0, round(rect['x'] * scale))
                        top = max(0, round(rect['y'] * scale))
                        right = min(full_img.width, round((rect['x'] + rect['w']) * scale))
                        bottom = min(full_img.height, round((rect['y'] + rect['h']) * scale))
                        if right - left < 2 or bottom - top < 2:
                            continue
                        crop = full_img.crop((left, top, right, bottom))
                        buf = io.BytesIO()
                        crop.save(buf, format='PNG')
                        shot = buf.getvalue()
                    except Exception:
                        continue  # один проблемний блок не має валити весь ZIP
                    index += 1
                    title = ''
                    heading = node.query_selector('h2, h3')
                    if heading:
                        title = (heading.inner_text() or '').strip().split('\n')[0]
                    archive.writestr(f'{index:02d}-{_slug(title, "block")}.png', shot)
                if not index:
                    raise HTTPException(422, 'У HTML не знайдено жодного блока для знімка')
        finally:
            browser.close()
    stream.seek(0)
    return Response(stream.getvalue(), media_type='application/zip')


# JS-зонд працює ВСЕРЕДИНІ сторінки: лише там відомі обчислені стилі, реальна
# геометрія після переносів і те, що насправді намальовано під текстом.
_PROBE = r"""
() => {
  const out = [];
  const W = document.documentElement.clientWidth;
  const add = (severity, code, message, node, extra) => {
    const rect = node ? node.getBoundingClientRect() : null;
    out.push(Object.assign({
      severity, code, message,
      text: node ? (node.innerText || node.textContent || '').trim().slice(0, 80) : '',
      at: rect ? {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)} : null,
    }, extra || {}));
  };

  const parseColor = (value) => {
    const m = String(value || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(',').map(x => parseFloat(x));
    return {r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1};
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const over = (fg, bg) => {   // fg з альфою поверх непрозорого bg
    const a = fg.a;
    return {r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a), a: 1};
  };
  // Тло, яке РЕАЛЬНО намальоване під елементом: піднімаємось предками, доки не
  // трапиться непрозорий колір. Дорогою відмічаємо, чи не лежить під текстом
  // картинка або градієнт - там гарантувати контраст математикою не можна.
  const backdrop = (el) => {
    let node = el, image = false, acc = null;
    while (node && node.nodeType === 1) {
      const st = getComputedStyle(node);
      if (st.backgroundImage && st.backgroundImage !== 'none') image = true;
      const c = parseColor(st.backgroundColor);
      if (c && c.a > 0) {
        acc = acc ? over(acc, c) : c;
        if (c.a >= 0.999) return {color: acc, image};
      }
      node = node.parentElement;
    }
    const white = {r: 255, g: 255, b: 255, a: 1};
    return {color: acc ? over(acc, white) : white, image};
  };

  const textNodes = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const value = (n.nodeValue || '').trim();
    if (value.length < 2) continue;
    const el = n.parentElement;
    if (!el) continue;
    const st = getComputedStyle(el);
    // Власний computed style НЕ бачить схованого предка: у дитини блока з
    // display:none повертається її власний display. Мобільна CTA-панель, схована
    // на десктопі, через це виглядала «зниклим текстом». checkVisibility рахує
    // весь ланцюг предків; решта умов - запасний шлях для старих движків.
    const visible = el.checkVisibility
      ? el.checkVisibility({opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true})
      : !(st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0);
    if (!visible) continue;
    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) continue;
    if (el.closest('[hidden], [aria-hidden="true"]')) continue;
    // Відповідь у ЗГОРНУТОМУ <details> не має розмірів за задумом - це штатний
    // FAQ студії, а не зниклий текст. Питання в <summary> лишається під наглядом.
    const fold = el.closest('details:not([open])');
    if (fold && !el.closest('summary')) continue;
    textNodes.push({el, value, st});
  }

  // 1. Сторінка не має їхати вбік: горизонтальний скрол - смерть на телефоні.
  if (document.documentElement.scrollWidth > W + 2) {
    add('error', 'page-overflow',
        `Сторінка ширша за екран на ${document.documentElement.scrollWidth - W}px - зʼявляється горизонтальний скрол`,
        document.body, {overflow_px: document.documentElement.scrollWidth - W});
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > W + 2 && el.children.length === 0) {
        add('error', 'element-outside', `Елемент виходить за праву межу на ${Math.round(r.right - W)}px`, el);
        break;
      }
    }
  }

  const seen = new Set();
  for (const {el, value, st} of textNodes) {
    if (seen.has(el)) continue;
    seen.add(el);
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) {
      add('error', 'text-collapsed', 'Текст є в розмітці, але не займає місця на сторінці', el);
      continue;
    }

    // 2. Обрізаний текст. Ховає переповнення зазвичай НЕ той елемент, у якому
    //    лежить текст, а котрийсь із предків - тому шукаємо найближчого, хто
    //    ріже, і порівнюємо з ним прямокутник тексту.
    const clips = (node) => {
      const s2 = getComputedStyle(node);
      return ['hidden', 'clip'].includes(s2.overflow) || ['hidden', 'clip'].includes(s2.overflowY) || ['hidden', 'clip'].includes(s2.overflowX);
    };
    let clipper = el;
    while (clipper && clipper !== document.body && !clips(clipper)) clipper = clipper.parentElement;
    if (clipper && clipper !== document.body && clips(clipper)) {
      const cr = clipper.getBoundingClientRect();
      const cut = Math.max(rect.bottom - cr.bottom, rect.right - cr.right, cr.top - rect.top, cr.left - rect.left);
      if (cut > 2) {
        add('error', 'text-clipped', `Текст обрізано: він виходить за свій блок на ${Math.round(cut)}px`, el, {cut_px: Math.round(cut)});
      } else if (clipper.scrollHeight > clipper.clientHeight + 2 && clipper.clientHeight > 0) {
        add('error', 'text-clipped', `Текст обрізано: вміст блока вищий за нього на ${clipper.scrollHeight - clipper.clientHeight}px`, el,
            {cut_px: clipper.scrollHeight - clipper.clientHeight});
      }
    }

    // 3. Контраст - проти того, що НАМАЛЬОВАНО під текстом, а не проти токена.
    const fg = parseColor(st.color);
    if (fg) {
      const back = backdrop(el);
      const color = fg.a < 0.999 ? over(fg, back.color) : fg;
      const size = parseFloat(st.fontSize) || 16;
      const weight = parseInt(st.fontWeight, 10) || 400;
      // Поріг студії - 4.5:1 для БУДЬ-ЯКОГО тексту: саме його гарантує
      // readable_on при виведенні палітри. WCAG для великого кегля дозволяє 3:1,
      // тому нижче цієї межі це помилка, а між 3 і 4.5 - зауваження. Живий
      // випадок: «12GB» акцентом 34px давало 3.66:1 - формально AA, а на екрані
      // цифра тонула в плитці того ж відтінку.
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const floor = large ? 3 : 4.5;
      const value_ratio = ratio(color, back.color);
      const hex = (c) => '#' + [c.r, c.g, c.b].map(x => Math.round(x).toString(16).padStart(2, '0')).join('').toUpperCase();
      const info = {contrast: +value_ratio.toFixed(2), color: hex(color), background: hex(back.color), font_size: size};
      if (back.image) {
        if (value_ratio < 4.5) {
          add('warning', 'text-over-image',
              `Текст лежить на зображенні або градієнті без гарантованої підкладки (${value_ratio.toFixed(2)}:1 проти видимого тла)`,
              el, info);
        }
      } else if (value_ratio < floor) {
        add('error', 'low-contrast',
            `Контраст ${value_ratio.toFixed(2)}:1 замість ${floor}:1 - ${hex(color)} на ${hex(back.color)}`, el, info);
      } else if (value_ratio < 4.5) {
        add('warning', 'low-contrast-large',
            `Контраст ${value_ratio.toFixed(2)}:1 - великий кегль це формально дозволяє, але студія веде палітру до 4.5:1`,
            el, info);
      }
    }

    // 4. Дрібний шрифт: на телефоні 12px - це вже межа читабельності.
    // Капслок-лейбли живуть на 11-12px у будь-якому магазині; дефект починається
    // нижче. Поріг навмисно не «12px за посібником»: інакше звіт тоне у шумі.
    const size = parseFloat(st.fontSize) || 16;
    if (size < (W <= 600 ? 11 : 10)) {
      add('warning', 'tiny-text', `Розмір шрифту ${size}px - замалий для читання`, el, {font_size: size});
    }

    // 5. Заготовки, що доїхали до сторінки.
    if (/lorem ipsum|placeholder|\bxxx\b|\bTBD\b|назва товару|текст заголовк/i.test(value)) {
      add('error', 'placeholder-copy', `Схоже на заготовку замість тексту: "${value.slice(0, 40)}"`, el);
    }
  }

  // 6. Текст, накритий непрозорим сусідом: у крапці, де стоїть текст, браузер
  //    віддає інший елемент - значить, покупець бачить не його.
  for (const {el} of textNodes.slice(0, 600)) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const x = Math.min(W - 2, Math.max(2, r.x + Math.min(12, r.width / 2)));
    const y = Math.max(2, r.y + r.height / 2);
    // Вікно для аудиту розтягнуте на всю висоту сторінки (див. _audit), тому
    // точка попадання працює і в підвалі, а не лише на першому екрані.
    if (y > window.innerHeight - 2) continue;
    const top = document.elementFromPoint(x, y);
    if (top && top !== el && !el.contains(top) && !top.contains(el)) {
      const st = getComputedStyle(top);
      const c = parseColor(st.backgroundColor);
      const solid = (c && c.a > 0.5) || (st.backgroundImage && st.backgroundImage !== 'none');
      if (solid) add('error', 'text-covered', 'Текст перекритий іншим елементом', el, {covered_by: top.tagName.toLowerCase()});
    }
  }

  // 7. Картинки: не завантажилась або розтягнута в нитку.
  for (const img of document.images) {
    if (!img.complete || img.naturalWidth === 0) {
      // Своє /media - це напевно наша поломка (підпис, шлях, права). Чуже фото
      // може не приїхати і через мережу контейнера, тому там лише зауваження:
      // краще мʼякше слово, ніж хибна тривога через тимчасовий CDN.
      const src = (img.currentSrc || img.src || '');
      const own = src.startsWith(location.origin) || src.startsWith('/');
      add(own ? 'error' : 'warning', 'image-broken',
          own ? 'Зображення студії не завантажилось' : 'Зовнішнє зображення не завантажилось (перевірте посилання)',
          img, {src: src.slice(0, 200)});
      continue;
    }
    const r = img.getBoundingClientRect();
    if (r.width > 2 && r.height > 2 && (r.width / r.height > 12 || r.height / r.width > 12)) {
      add('warning', 'image-degenerate', 'Зображення розтягнуте в смугу - швидше за все зламані розміри', img);
    }
  }

  return {
    findings: out,
    metrics: {
      viewport: W,
      page_height: Math.round(document.documentElement.scrollHeight),
      scroll_width: Math.round(document.documentElement.scrollWidth),
      text_nodes: textNodes.length,
      images: document.images.length,
    },
  };
}
"""

# Скільки балів знімає кожен клас дефекту. Обрізаний текст і нечитабельна
# цифра - це брак, який побачить покупець; дрібний шрифт - зауваження.
_PENALTY = {
    'page-overflow': 25, 'element-outside': 10, 'text-clipped': 20, 'text-covered': 20,
    'low-contrast': 12, 'text-collapsed': 12, 'image-broken': 15, 'placeholder-copy': 25,
    'text-over-image': 6, 'tiny-text': 4, 'image-degenerate': 6, 'low-contrast-large': 5,
}


def _audit(payload: AuditIn):
    if len(payload.html) > MAX_HTML:
        raise HTTPException(413, 'HTML більший за 2 МБ')
    from playwright.sync_api import sync_playwright

    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<base href="{BASE_URL}/">'
        '<style>html,body{margin:0;padding:0;background:#FFFFFF;'
        'font-family:Roboto,Inter,Arial,sans-serif}</style></head>'
        f'<body>{payload.html}</body></html>'
    )
    external = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': payload.width, 'height': 1400})
            # Сторінка їде в ЧУЖИЙ магазин. Фото з CDN магазину і ролик YouTube там
            # доречні - їх ловить окремо перевірка «зображення не завантажилось».
            # А от зовнішній стиль, шрифт чи скрипт - це те, що або заріже CSP,
            # або просто не приїде, і сторінка поїде без верстки.
            _RISKY = {'stylesheet', 'font', 'script'}
            page.on('request', lambda r: external.append(f'{r.resource_type}: {r.url[:180]}')
                    if (r.resource_type in _RISKY
                        and not (r.url.startswith(BASE_URL) or r.url.startswith('data:') or r.url.startswith('about:')))
                    else None)
            page.set_default_timeout(20000)
            page.set_content(document, wait_until='domcontentloaded')
            try:
                page.wait_for_function(
                    "() => Array.from(document.images).every(i => i.complete)", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            # Розтягуємо вікно на всю висоту сторінки: інакше перевірка «текст
            # перекрито» бачила б лише перший екран, а рич-сторінка має 8-15 тисяч
            # пікселів. Стеля 16000 - щоб патологічна сторінка не зʼїла памʼять.
            try:
                full_height = min(16000, max(1400, int(page.evaluate('() => document.documentElement.scrollHeight'))))
                page.set_viewport_size({'width': payload.width, 'height': full_height})
                page.wait_for_timeout(200)
            except Exception:
                pass
            result = page.evaluate(_PROBE)
        finally:
            browser.close()

    findings = result.get('findings') or []
    # Однотипні знахідки схлопуємо: двадцять рядків «низький контраст» в одній
    # таблиці - це один дефект, а не двадцять, і читати треба саме так.
    grouped: dict = {}
    for item in findings:
        key = (item['code'], item.get('color', ''), item.get('background', ''))
        row = grouped.setdefault(key, dict(item, count=0, examples=[]))
        row['count'] += 1
        if len(row['examples']) < 3 and item.get('text'):
            row['examples'].append(item['text'])
    merged = sorted(grouped.values(), key=lambda x: (-_PENALTY.get(x['code'], 5), -x['count']))
    score = 100.0
    for item in merged:
        # Другий і наступні випадки того самого дефекту коштують менше: важливо
        # ЩО зламано, а не скільки разів це трапилось у тій самій таблиці.
        score -= min(_PENALTY.get(item['code'], 5) * (1 + 0.25 * (item['count'] - 1)), _PENALTY.get(item['code'], 5) * 2)
    if external:
        merged.append({'severity': 'error', 'code': 'external-request', 'count': len(set(external)),
                       'message': 'Сторінка тягне зовнішні стилі, шрифти або скрипти - у магазині вони не завантажаться',
                       'text': '', 'at': None, 'examples': sorted(set(external))[:3]})
        score -= 15
    return {
        'label': payload.label,
        'width': payload.width,
        'score': max(0.0, min(100.0, round(score, 1))),
        'findings': merged[:40],
        'metrics': result.get('metrics') or {},
    }
