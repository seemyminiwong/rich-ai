"""Інфографіка на фото: серверна композиція без браузера.

Навіщо: продавцеві потрібна КАРТИНКА для галереї магазину (Allegro, artline),
а не HTML-блок - її можна залити куди завгодно. Тому малюємо напряму в Pillow:
жодного Chromium, жодного окремого сервісу, детермінований результат і точний
розмір полотна. Іконки - бібліотека бренду (експорт Figma, нарізаний у PNG з
альфою), тексти - короткі підписи, які пропонує модель і править оператор.
"""
import json
import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.raster import alpha_bbox, flatten_to_white

CANVAS = 2000
TEMPLATES = ('icons-left', 'icons-right', 'callouts', 'strip-bottom')

_PACK = Path(__file__).resolve().parent / 'infographic'
_ICONS_DIR = _PACK / 'icons'
_INDEX = _PACK / 'icons.json'

# Порядок пошуку шрифту: фірмовий Roboto, далі те, що точно є в образі.
_FONT_CANDIDATES = {
    'bold': ('Roboto-Bold.ttf', 'Roboto-Black.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf'),
    'regular': ('Roboto-Regular.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf'),
}
_FONT_DIRS = (
    '/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF',
    '/usr/share/fonts/truetype/roboto/hinted',
    '/usr/share/fonts/truetype/roboto',
    '/usr/share/fonts/truetype/dejavu',
    '/usr/share/fonts/truetype/liberation',
    '/usr/share/fonts/truetype/liberation2',
)
_font_cache: dict = {}


def _font(kind: str, size: int):
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    for name in _FONT_CANDIDATES[kind]:
        for folder in _FONT_DIRS:
            path = Path(folder) / name
            if path.is_file():
                font = ImageFont.truetype(str(path), size)
                _font_cache[key] = font
                return font
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def icon_catalog() -> list:
    """Бібліотека іконок бренду: [{'slug','name'}]."""
    try:
        return json.loads(_INDEX.read_text(encoding='utf-8'))
    except Exception:
        return []


def _icon_image(slug: str):
    path = _ICONS_DIR / f'{(slug or "").strip()}.png'
    if not path.is_file():
        return None
    return Image.open(path).convert('RGBA')


def _trim_uniform_border(image: Image.Image, tolerance: int = 12) -> Image.Image:
    """Прибирає рівні поля навколо товару, щоб кадр не губився в порожнечі."""
    w, h = image.size
    # Кадр з альфою вже КАЖЕ, де порожнеча - шукати однорідний колір не треба.
    # Раніше сюди приходив convert('RGB'), тобто прозоре ставало чорним: якщо
    # сам товар був темний, він зливався з «тлом» і кадр обрізався по живому.
    bbox = alpha_bbox(image)
    if bbox is None:
        rgb = flatten_to_white(image)
        px = rgb.load()
        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        base = corners[0]
        if any(max(abs(c[i] - base[i]) for i in range(3)) > tolerance for c in corners):
            return image
        mask = Image.new('L', (w, h), 0)
        mdraw = mask.load()
        for y in range(h):
            for x in range(w):
                c = px[x, y]
                if max(abs(c[i] - base[i]) for i in range(3)) > tolerance:
                    mdraw[x, y] = 255
        bbox = mask.getbbox()
    if not bbox:
        return image
    pad = int(min(w, h) * 0.02)
    box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
           min(w, bbox[2] + pad), min(h, bbox[3] + pad))
    if (box[2] - box[0]) < w * 0.2 or (box[3] - box[1]) < h * 0.2:
        return image
    return image.crop(box)


def _fit(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((box_w, box_h), Image.LANCZOS)
    return copy


def _wrap(draw, text: str, font, max_width: int) -> list:
    words = re.sub(r'\s+', ' ', text or '').strip().split(' ')
    lines, current = [], ''
    for word in words:
        probe = f'{current} {word}'.strip()
        if draw.textlength(probe, font=font) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _text_block(draw, x: int, y: int, text: str, font, max_width: int, fill, line_gap: int = 10,
                center: bool = False) -> int:
    lines = _wrap(draw, text, font, max_width)
    line_h = font.size + line_gap
    for index, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        left = x + (max_width - width) / 2 if center else x
        draw.text((left, y + index * line_h), line, font=font, fill=fill)
    return len(lines) * line_h


def _paste_icon(canvas: Image.Image, slug: str, cx: int, cy: int, size: int) -> None:
    icon = _icon_image(slug)
    if icon is None:
        return
    icon = _fit(icon, size, size)
    canvas.paste(icon, (int(cx - icon.width / 2), int(cy - icon.height / 2)), icon)


def _header(canvas: Image.Image, draw, title: str, brand_logo, pad: int, ink: str,
            brand: str = 'ARTLINE') -> int:
    """Шапка: знак бренду + назва + заголовок капсом. Повертає нижню межу шапки.

    Логотип - будь-який бренд, а не лише ARTLINE: на картці QUBE чи DEYE
    фірмовий знак має бути їхній. Широкий логотип (лого-напис) займає місце
    словесної назви, тож текст поруч тоді не малюємо.
    """
    y = pad
    left = pad
    mark_h = 118
    wordmark_only = False
    if brand_logo is not None:
        aspect = brand_logo.width / max(1, brand_logo.height)
        if aspect > 2.0:
            # Це логотип-напис: даємо йому ширину і не дублюємо назву текстом.
            mark = _fit(brand_logo, 620, mark_h)
            wordmark_only = True
        else:
            mark = _fit(brand_logo, mark_h, mark_h)
        canvas.paste(mark, (left, y + (mark_h - mark.height) // 2),
                     mark if mark.mode == 'RGBA' else None)
        left += mark.width + 28
    name = (brand or '').strip()
    if name and not wordmark_only:
        brand_font = _font('bold', 76)
        draw.text((left, y + 14), name, font=brand_font, fill=ink)
        left += draw.textlength(name, font=brand_font) + 34
    if title:
        title_font = _font('bold', 54)
        used = _text_block(draw, int(left), y + 12, title.upper(), title_font,
                           CANVAS - int(left) - pad, ink, line_gap=6)
        return max(y + mark_h, y + used) + 46
    return y + mark_h + 46


def _callout_column(canvas, draw, items, x: int, width: int, top: int, bottom: int,
                    ink: str, muted: str) -> None:
    """Колонка «іконка зверху, підпис під нею» - як в еталонному макеті бренду."""
    if not items:
        return
    icon_size = 132 if len(items) <= 4 else 112
    title_font = _font('bold', 40 if len(items) <= 4 else 36)
    text_font = _font('regular', 32)
    slot = (bottom - top) / len(items)
    for index, item in enumerate(items):
        center_y = top + slot * index + slot / 2
        _paste_icon(canvas, item.get('icon', ''), x + width // 2, int(center_y - slot * 0.24), icon_size)
        text_top = int(center_y - slot * 0.24 + icon_size / 2 + 26)
        used = _text_block(draw, x, text_top, item.get('title', ''), title_font, width, ink,
                           line_gap=8, center=True)
        if item.get('text'):
            _text_block(draw, x, text_top + used + 6, item['text'], text_font, width, muted,
                        line_gap=6, center=True)


def _photo_box(canvas, photo: Image.Image, box) -> tuple:
    """Вписує фото в прямокутник box=(x0,y0,x1,y1) і повертає його реальні межі."""
    x0, y0, x1, y1 = box
    fitted = _fit(photo, x1 - x0, y1 - y0)
    px = int(x0 + (x1 - x0 - fitted.width) / 2)
    py = int(y0 + (y1 - y0 - fitted.height) / 2)
    canvas.paste(fitted, (px, py), fitted if fitted.mode == 'RGBA' else None)
    return (px, py, px + fitted.width, py + fitted.height)


def render_infographic(photo_bytes: bytes, items: list, title: str = '', template: str = 'icons-left',
                       background: str = '#FFFFFF', logo_bytes: bytes | None = None,
                       accent: str = '#19BCC9', brand: str = 'ARTLINE') -> bytes:
    """Повертає WEBP 2000x2000 з фото товару і підписами на іконках бренду.

    items: [{'icon': slug, 'title': 'короткий підпис', 'text': 'необовʼязковий рядок'}]
    template: icons-left | icons-right | callouts | strip-bottom
    """
    if template not in TEMPLATES:
        raise ValueError(f'Невідомий макет: {template}')
    items = [x for x in (items or []) if (x.get('title') or x.get('icon'))][:6]
    if not items:
        raise ValueError('Потрібен хоча б один підпис')

    photo = Image.open(BytesIO(photo_bytes))
    photo = photo.convert('RGBA') if photo.mode in ('RGBA', 'LA', 'P') else photo.convert('RGB')
    photo = _trim_uniform_border(photo)

    canvas = Image.new('RGB', (CANVAS, CANVAS), background)
    draw = ImageDraw.Draw(canvas)
    ink, muted = '#101010', '#5B6670'
    pad = 90

    logo = None
    if logo_bytes:
        try:
            logo = Image.open(BytesIO(logo_bytes)).convert('RGBA')
        except Exception:
            logo = None

    header_bottom = _header(canvas, draw, title, logo, pad, ink, brand=brand)
    body_top, body_bottom = header_bottom, CANVAS - pad

    if template in ('icons-left', 'icons-right'):
        column_w = 620
        gap = 70
        if template == 'icons-left':
            column_x = pad
            photo_box = (pad + column_w + gap, body_top, CANVAS - pad, body_bottom)
        else:
            column_x = CANVAS - pad - column_w
            photo_box = (pad, body_top, CANVAS - pad - column_w - gap, body_bottom)
        _photo_box(canvas, photo, photo_box)
        _callout_column(canvas, draw, items, column_x, column_w, body_top, body_bottom, ink, muted)

    elif template == 'strip-bottom':
        strip_h = 430 if any(x.get('text') for x in items) else 360
        photo_area = (pad, body_top, CANVAS - pad, body_bottom - strip_h)
        _photo_box(canvas, photo, photo_area)
        cells = len(items)
        cell_w = (CANVAS - 2 * pad) // cells
        title_font = _font('bold', 36 if cells > 3 else 40)
        text_font = _font('regular', 30)
        line_y = body_bottom - strip_h + 10
        draw.line([(pad, line_y), (CANVAS - pad, line_y)], fill='#E3E6EA', width=3)
        for index, item in enumerate(items):
            cx = pad + cell_w * index + cell_w // 2
            _paste_icon(canvas, item.get('icon', ''), cx, line_y + 120, 130)
            text_top = line_y + 200
            used = _text_block(draw, pad + cell_w * index + 14, text_top, item.get('title', ''),
                               title_font, cell_w - 28, ink, line_gap=6, center=True)
            if item.get('text'):
                _text_block(draw, pad + cell_w * index + 14, text_top + used + 4, item['text'],
                            text_font, cell_w - 28, muted, line_gap=4, center=True)

    else:  # callouts: підписи по обидва боки фото з тонкими вказівниками
        left_items = items[::2]
        right_items = items[1::2]
        side_w = 470
        photo_box = (pad + side_w + 40, body_top, CANVAS - pad - side_w - 40, body_bottom)
        frame = _photo_box(canvas, photo, photo_box)
        title_font = _font('bold', 38)
        text_font = _font('regular', 30)

        def side(entries, x, width, align_right):
            if not entries:
                return
            slot = (body_bottom - body_top) / len(entries)
            for index, item in enumerate(entries):
                center_y = int(body_top + slot * index + slot / 2)
                icon_cx = x + (width - 70 if align_right else 70)
                _paste_icon(canvas, item.get('icon', ''), icon_cx, center_y - 70, 112)
                used = _text_block(draw, x, center_y + 6, item.get('title', ''), title_font,
                                   width, ink, line_gap=6, center=True)
                if item.get('text'):
                    _text_block(draw, x, center_y + 6 + used, item['text'], text_font, width,
                                muted, line_gap=4, center=True)
                anchor_x = frame[0] if align_right else frame[2]
                start_x = x + width - 20 if align_right else x + 20
                draw.line([(start_x, center_y - 70), (anchor_x, center_y - 70)], fill=accent, width=3)
                draw.ellipse([anchor_x - 9, center_y - 79, anchor_x + 9, center_y - 61],
                             outline=accent, width=3)

        side(left_items, pad, side_w, align_right=True)
        side(right_items, CANVAS - pad - side_w, side_w, align_right=False)

    out = BytesIO()
    canvas.save(out, format='WEBP', quality=92, method=6)
    return out.getvalue()
