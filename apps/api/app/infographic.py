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

from app.raster import alpha_bbox, flatten_to_white, hex_rgb, readable_on

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


def _pretty_name(stem: str) -> str:
    """Назва для показу: знімаємо хвіст-хеш і робимо з дефісів пробіли."""
    return re.sub(r'-[0-9a-f]{8}$', '', stem).replace('-', ' ').strip() or 'іконка'


def icon_catalog() -> list:
    """Бібліотека іконок: вбудовані бренд-іконки + завантажені оператором.

    Завантажені йдуть першими: їх мало, і саме їх шукають після додавання.
    """
    try:
        built_in = json.loads(_INDEX.read_text(encoding='utf-8'))
    except Exception:
        built_in = []
    for item in built_in:
        item.setdefault('custom', False)
    own = []
    try:
        for path in sorted(user_icons_dir().glob('*.png'), key=lambda x: x.stat().st_mtime, reverse=True):
            own.append({'slug': path.stem, 'name': _pretty_name(path.stem), 'custom': True})
    except Exception:
        own = []
    return own + built_in


# Фірмова смуга відтінків бібліотеки: усі 174 іконки - двоточковий градієнт
# 155°..185° (зелено-бірюзовий -> циан) з насиченістю 1.0. Виміряно по всьому
# набору; саме ця регулярність і дозволяє перефарбовувати їх поворотом
# відтінку, не чіпаючи ані градієнт, ані згладжування країв.
BRAND_HUE = 184.0
BRAND_SPAN = 30.0
_USER_DIR_NAME = 'icons'


def user_icons_dir() -> Path:
    """Іконки оператора живуть у ТОМІ, а не в образі.

    _ICONS_DIR лежить усередині app/ і копіюється в образ - усе, завантажене
    туди, зникло б на першій же `docker compose build`. media_dir - том, який
    переживає пересборку і потрапляє в нічний бекап медіа. Логотипи вже
    зроблені так само.
    """
    # settings імпортуємо ліниво: модуль малює картинки і не мусить тягнути
    # за собою конфіг застосунку - так його видно і з простого скрипта.
    from app.config import settings
    folder = Path(settings.media_dir) / _USER_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _icon_path(slug: str) -> Path | None:
    name = (slug or '').strip()
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return None
    built_in = _ICONS_DIR / f'{name}.png'
    if built_in.is_file():
        return built_in
    own = user_icons_dir() / f'{name}.png'
    return own if own.is_file() else None


def _icon_image(slug: str):
    path = _icon_path(slug)
    return Image.open(path).convert('RGBA') if path else None


def _hue_profile(image: Image.Image) -> tuple[float, float] | None:
    """Середній відтінок і насиченість кольорових пікселів, або None.

    Відтінок усереднюється КОЛОВО (через одиничні вектори): звичайне середнє
    між 350° і 10° дало б 180° - рівно протилежний колір.
    """
    import math
    probe = image.copy()
    probe.thumbnail((48, 48))
    hsv = probe.convert('RGB').convert('HSV')
    alpha = probe.getchannel('A')
    x = y = weight = 0.0
    for (h, sat, val), a in zip(hsv.getdata(), alpha.getdata()):
        if a < 120 or sat < 40 or val < 20:
            continue
        angle = h / 255 * 2 * math.pi
        w = sat / 255
        x += math.cos(angle) * w; y += math.sin(angle) * w; weight += w
    if weight < 1:
        return None
    return (math.degrees(math.atan2(y, x)) % 360, min(1.0, weight / max(1, sum(
        1 for a in alpha.getdata() if a >= 120))))


def recolor_icon(image: Image.Image, color: str) -> Image.Image:
    """Перефарбувати іконку в заданий колір, зберігши її градієнт.

    Не заливка: беремо власну смугу відтінків іконки і ПОВЕРТАЄМО її так, щоб
    середина лягла на потрібний колір. Насиченість і яскравість кожного
    пікселя лишаються своїми, тож двоточковий градієнт, внутрішні переходи і
    згладжування країв виживають піксель у піксель. Альфа не чіпається.

    Безбарвну іконку (чорний або білий силует) повертати нема куди - їй
    градієнт малюється по яскравості.
    """
    import colorsys
    source = image.convert('RGBA')
    alpha = source.getchannel('A')
    target_h, target_s, target_v = colorsys.rgb_to_hsv(*(c / 255 for c in hex_rgb(color)))
    profile = _hue_profile(source)
    if profile is None:
        return _paint_gradient(source, color)
    own_h, _ = profile
    shift = int(round(((target_h * 360 - own_h) % 360) / 360 * 255))
    hsv = source.convert('RGB').convert('HSV')
    h, sat, val = hsv.split()
    h = h.point(lambda v: (v + shift) % 256)
    # Насиченість і яскравість підтягуємо до обраного кольору, зберігаючи
    # відносну структуру: множник, а не заміна.
    s_scale = max(0.25, min(2.5, target_s / 0.95))
    v_scale = max(0.35, min(1.6, target_v / 0.80))
    sat = sat.point(lambda v: min(255, int(v * s_scale)))
    val = val.point(lambda v: min(255, int(v * v_scale)))
    out = Image.merge('HSV', (h, sat, val)).convert('RGB').convert('RGBA')
    out.putalpha(alpha)
    return out


def _paint_gradient(image: Image.Image, color: str) -> Image.Image:
    """Силует без власного кольору -> вертикальний двоточковий градієнт."""
    import colorsys
    alpha = image.convert('RGBA').getchannel('A')
    width, height = image.size
    h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in hex_rgb(color)))
    top = colorsys.hsv_to_rgb((h - BRAND_SPAN / 720) % 1.0, sat, min(1.0, val * 1.12))
    bottom = colorsys.hsv_to_rgb((h + BRAND_SPAN / 720) % 1.0, sat, val)
    ramp = Image.new('RGB', (1, height))
    for y in range(height):
        k = y / max(1, height - 1)
        ramp.putpixel((0, y), tuple(round(255 * (top[i] + (bottom[i] - top[i]) * k)) for i in range(3)))
    out = ramp.resize((width, height)).convert('RGBA')
    out.putalpha(alpha)
    return out


def normalize_uploaded_icon(blob: bytes, size: int = 256) -> bytes:
    """Привести завантажену іконку до формату бібліотеки.

    Обрізаємо порожні поля, вписуємо в квадрат і фарбуємо у фірмову смугу -
    далі така іконка поводиться рівно як решта 174 і так само перефарбовується
    разом з ними. Прозорість зберігається, тому SVG-силует лишається силуетом.
    """
    image = Image.open(BytesIO(blob)).convert('RGBA')
    box = alpha_bbox(image)
    if box:
        image = image.crop(box)
    image.thumbnail((size, size), Image.LANCZOS)
    square = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    square.paste(image, ((size - image.width) // 2, (size - image.height) // 2), image)
    brand = '#%02X%02X%02X' % tuple(round(c * 255) for c in __import__('colorsys').hsv_to_rgb(BRAND_HUE / 360, 1.0, 0.8))
    out = BytesIO()
    recolor_icon(square, brand).save(out, format='PNG', optimize=True)
    return out.getvalue()


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


def _paste_icon(canvas: Image.Image, slug: str, cx: int, cy: int, size: int,
                color: str = '') -> None:
    icon = _icon_image(slug)
    if icon is None:
        return
    if color:
        icon = recolor_icon(icon, color)
    icon = _fit(icon, size, size)
    canvas.paste(icon, (int(cx - icon.width / 2), int(cy - icon.height / 2)), icon)


def ink_logo(logo: Image.Image, ink: str) -> Image.Image:
    """Одноколірний знак перефарбовуємо під полотно, кольоровий - ніколи.

    Фірмовий ARTLINE - БІЛИЙ лого-напис: він зроблений для темної шапки сайту
    і на білому полотні інфографіки був би просто невидимий. Знаки партнерів
    (QUBE, DEYE) не чіпаємо - у них колір і є брендом.

    Ознака одноколірності - відсутність власного відтінку взагалі або мізерна
    частка кольорових пікселів: біле лого з дрібною кольоровою крапкою теж
    треба перефарбувати, інакше зникне все, крім тієї крапки.
    """
    rgba = logo.convert('RGBA')
    profile = _hue_profile(rgba)
    if profile is not None and profile[1] >= 0.2:
        return logo
    solid = Image.new('RGBA', rgba.size, hex_rgb(ink) + (255,))
    solid.putalpha(rgba.getchannel('A'))
    return solid


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
    # Порожня шапка не мусить лишати по собі порожню смугу: без знака І без
    # назви резервувати висоту марки нема за що - заголовок піднімається
    # догори, а без заголовка шапки немає взагалі.
    if brand_logo is None and not (brand or '').strip():
        if not title:
            return y
        title_font = _font('bold', 54)
        used = _text_block(draw, left, y, title.upper(), title_font,
                           CANVAS - left - pad, ink, line_gap=6)
        return y + used + 46
    if brand_logo is not None:
        brand_logo = ink_logo(brand_logo, ink)
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
                    ink: str, muted: str, icon_color: str = '') -> None:
    """Колонка «іконка зверху, підпис під нею» - як в еталонному макеті бренду."""
    if not items:
        return
    icon_size = 132 if len(items) <= 4 else 112
    title_font = _font('bold', 40 if len(items) <= 4 else 36)
    text_font = _font('regular', 32)
    slot = (bottom - top) / len(items)
    for index, item in enumerate(items):
        center_y = top + slot * index + slot / 2
        _paste_icon(canvas, item.get('icon', ''), x + width // 2, int(center_y - slot * 0.24), icon_size, icon_color)
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
    # Іконки і виноски беруть акцент сторінки, але спершу доводимо його до
    # видимості НА ПОЛОТНІ: акцент, підібраний під темні картки річа, на
    # білому тлі інфографіки міг би загубитись. 3:1 - поріг WCAG для великої
    # графіки, а іконка тут завбільшки з монету.
    accent = (accent or '#19BCC9').strip() or '#19BCC9'
    icon_color = readable_on(accent, background or '#FFFFFF', 3.0)
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
        _callout_column(canvas, draw, items, column_x, column_w, body_top, body_bottom, ink, muted, icon_color)

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
            _paste_icon(canvas, item.get('icon', ''), cx, line_y + 120, 130, icon_color)
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
                _paste_icon(canvas, item.get('icon', ''), icon_cx, center_y - 70, 112, icon_color)
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
