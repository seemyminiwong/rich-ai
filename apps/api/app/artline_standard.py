"""Стандарт ARTLINE для кожної rich-сторінки, механічно.

Правила взято з майстер-промпту власника (стиль ARTLINE Master) і винесено на
ВСІ стилі: кожен стиль зберігає свою сітку, але шрифт, шкала розмірів, ваги,
радіуси, акцент на світлому тлі, тире, регістр заголовків і lazy-завантаження
однакові. Промпт просить про це модель; цей модуль гарантує результат, бо
модель, перекладач і перекомпонування повертають «свої» розміри за звичкою.

Прохід ідемпотентний і чіпає лише inline-стилі, текстові вузли h2 та атрибут
loading. <style>-блоки (FAQ, обертання Podium) і коментарі не змінюються.
"""
import re

from bs4 import BeautifulSoup, Comment, NavigableString

# Шкала стандарту (однакова для десктопа й мобільного)
HERO_H2 = (30, '1.12')
SECTION_H2 = (24, '1.25')
H3 = (18, '1.4')
SUBTITLE = (18, '1.4')
BODY = (16, '1.6')
VALUE = (26, '1.15')
CAPTION_MIN = 12
OUTER_RADIUS = 14
MAX_RADIUS = 14
ACCENT = '#19BCC9'
ACCENT_ON_LIGHT = '#157985'

_SIZE_RE = re.compile(r'(?<![-\w])font-size\s*:\s*([\d.]+)px', re.I)
_WEIGHT_RE = re.compile(r'(?<![-\w])font-weight\s*:\s*(\d{3,4})', re.I)
_RADIUS_RE = re.compile(r'(?<![-\w])border-radius\s*:\s*([\d.]+)px(?=\s*(?:;|$|!))', re.I)
_COLOR_RE = re.compile(r'(?<![-\w])color\s*:\s*#19BCC9\b', re.I)
_BG_RE = re.compile(r'(?<![-\w])background(?:-color|-image)?\s*:\s*([^;]+)', re.I)
_HEX_RE = re.compile(r'#([0-9a-f]{6}|[0-9a-f]{3})\b', re.I)
_RGB_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)', re.I)
_UNITS = {'мм', 'см', 'м', 'км', 'кг', 'г', 'мс', 'с', 'хв', 'год', 'гц', 'кгц', 'мгц', 'ггц', 'вт', 'квт', 'в', 'а',
          'мач', 'маг', 'гб', 'тб', 'мб', 'кб', 'дюйм', 'дюйма', 'дюймов', 'мм.', 'шт', 'mm', 'cm', 'm', 'kg', 'g', 'ms',
          's', 'hz', 'khz', 'mhz', 'ghz', 'w', 'kw', 'v', 'a', 'mah', 'gb', 'tb', 'mb', 'kb', 'db', 'дб', 'lm', 'лм',
          'nit', 'нит', 'кд', 'cd', 'fps', 'rpm', 'об/хв', 'об/мин', 'x', '×'}


def _set_decl(style: str, prop: str, value: str) -> str:
    pattern = re.compile(r'(?<![-\w])' + re.escape(prop) + r'\s*:\s*[^;]*', re.I)
    if pattern.search(style):
        return pattern.sub(f'{prop}:{value}', style, count=1)
    style = style.rstrip().rstrip(';')
    return f'{style};{prop}:{value}' if style else f'{prop}:{value}'


def _drop_decl(style: str, prop: str) -> str:
    return re.sub(r'(?<![-\w])' + re.escape(prop) + r'\s*:\s*[^;]*;?', '', style, flags=re.I)


def _size(style: str):
    m = _SIZE_RE.search(style or '')
    return float(m.group(1)) if m else None


def _weight(style: str) -> int:
    m = _WEIGHT_RE.search(style or '')
    return int(m.group(1)) if m else 400


def _apply_size(tag, size: int, line_height: str):
    style = tag.get('style') or ''
    new = _set_decl(style, 'font-size', f'{size}px')
    new = _set_decl(new, 'line-height', line_height)
    if new != style:
        tag['style'] = new
        return True
    return False


def _luminance(r, g, b) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _surface_is_light(tag) -> bool:
    """Чи лежить текст на світлому тлі: перший непрозорий фон предків.

    Фон без кольору (лише url(...)) вважається темним - фото Hero майже завжди
    під темним оверлеєм. Без фону аж до кореня - сторінка магазину, біла.
    """
    node = tag
    while node is not None and getattr(node, 'get', None):
        style = node.get('style') or ''
        for value in _BG_RE.findall(style):
            hexes = _HEX_RE.findall(value)
            rgbs = _RGB_RE.findall(value)
            if hexes:
                h = hexes[0]
                if len(h) == 3:
                    h = ''.join(c * 2 for c in h)
                return _luminance(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) > 0.4
            for r, g, b, a in rgbs:
                if a == '' or float(a) >= 0.5:
                    return _luminance(int(r), int(g), int(b)) > 0.4
            if 'url(' in value:
                return False
        node = node.parent
    return True


def _uppercase_heading(h2, protected: set) -> bool:
    changed = False
    for node in h2.find_all(string=True):
        if isinstance(node, Comment):
            continue
        text = str(node)
        parts = re.split(r'(\s+)', text)
        prev_numeric = False
        out = []
        for part in parts:
            if not part or part.isspace():
                out.append(part)
                continue
            bare = part.strip('.,:;!?()«»"\'–-')
            keep = (
                not bare
                or any(ch.isdigit() for ch in bare)
                or any(ch.isupper() for ch in bare[1:])
                or bare.lower() in protected
                or (prev_numeric and bare.lower() in _UNITS)
            )
            out.append(part if keep else part.upper())
            prev_numeric = any(ch.isdigit() for ch in bare)
        new = ''.join(out)
        if new != text:
            node.replace_with(NavigableString(new))
            changed = True
    return changed


_SKIP = {'style', 'script', 'link', 'meta', 'template'}


def _elements(node):
    return [c for c in node.find_all(recursive=False) if getattr(c, 'name', None) and c.name not in _SKIP]


def _blocks(root):
    """Візуальні блоки сторінки: діти кореня, а якщо модель додала одну
    зайву обгортку (часто в Showcase) - діти цієї обгортки."""
    blocks = _elements(root)
    while len(blocks) == 1 and len(_elements(blocks[0])) >= 2:
        blocks = _elements(blocks[0])
    return blocks


def apply_artline_standard(markup: str, product_name: str = '') -> str:
    if not markup or '<section' not in markup:
        return markup
    soup = BeautifulSoup(markup, 'html.parser')
    root = soup.find('section')
    if root is None:
        return markup
    changed = False
    blocks = _blocks(root)
    hero = blocks[0] if blocks else None
    block_ids = {id(b) for b in blocks}
    hero_ids = {id(x) for x in (hero.find_all(True) if hero is not None else [])} | ({id(hero)} if hero is not None else set())

    # 1. Корінь: на всю ширину контейнера сторінки, без max-width і відступів
    style = root.get('style') or ''
    new = style
    new = _drop_decl(new, 'max-width')
    for prop, value in (('width', '100%'), ('margin', '0'), ('padding', '0'), ('box-sizing', 'border-box')):
        new = _set_decl(new, prop, value)
    new = re.sub(r';{2,}', ';', new).strip(';')
    if new != style:
        root['style'] = new
        changed = True

    # 2. Довге тире -> коротке у видимому тексті
    for node in soup.find_all(string=True):
        if isinstance(node, Comment) or node.parent.name in ('script', 'style'):
            continue
        if '—' in node:
            node.replace_with(NavigableString(str(node).replace('—', '–')))
            changed = True

    # Бренд і модель з назви товару пишуться як є; загальні слова назви
    # («Монітор», «Навушники») - ні, вони йдуть у заголовок великими.
    protected = {w.lower() for w in re.findall(r'[\w\-]+', product_name or '')
                 if len(w) > 1 and re.search(r'[A-Za-z]', w)}
    for tag in root.find_all(True):
        style = tag.get('style')
        name = tag.name
        in_hero = id(tag) in hero_ids

        # 3. Ваги: 900 - максимум, 850 зводиться до 800
        if style:
            def weight(m):
                w = int(m.group(1))
                return m.group(0) if w <= 900 and w != 850 else m.group(0).replace(m.group(1), '900' if w > 900 else '800')
            new = _WEIGHT_RE.sub(weight, style)
            if new != style:
                tag['style'] = style = new
                changed = True

        # 4. Шкала розмірів
        size = _size(style)
        if name == 'h2':
            target = HERO_H2 if in_hero else SECTION_H2
            changed |= _apply_size(tag, *target)
            s = tag.get('style') or ''
            if _weight(s) != 900:
                tag['style'] = _set_decl(s, 'font-weight', '900')
                changed = True
        elif name == 'h3':
            changed |= _apply_size(tag, *H3)
        elif size is not None:
            heavy = _weight(style) >= 700
            if name in ('p', 'li', 'summary'):
                if name == 'summary' or (heavy and size >= 17):
                    target = SUBTITLE
                elif size > BODY[0]:
                    target = BODY
                elif size < 14:
                    target = (14, '1.4')
                else:
                    target = None
            else:
                if size >= 22:
                    target = VALUE
                elif size >= 19:
                    target = SUBTITLE
                elif size < CAPTION_MIN:
                    target = (CAPTION_MIN, '1.3')
                else:
                    target = None
            if target and (size != target[0]):
                changed |= _apply_size(tag, *target)

        # 5. Радіуси: зовнішні блоки 14px, стеля 14px (пігулки 999px - лише бейджі)
        style = tag.get('style') or ''
        if style:
            is_outer = id(tag) in block_ids
            def radius(m):
                v = float(m.group(1))
                if v >= 100:
                    return m.group(0)
                if is_outer and 8 <= v < OUTER_RADIUS:
                    return f'border-radius:{OUTER_RADIUS}px'
                if v > MAX_RADIUS:
                    return f'border-radius:{MAX_RADIUS}px'
                return m.group(0)
            new = _RADIUS_RE.sub(radius, style)
            if new != style:
                tag['style'] = style = new
                changed = True

        # 6. Акцент як текст на світлому тлі - темніший, щоб читався (AA)
        if style and _COLOR_RE.search(style) and _surface_is_light(tag):
            tag['style'] = _COLOR_RE.sub(f'color:{ACCENT_ON_LIGHT}', style)
            changed = True

        # 7. Зображення поза Hero вантажаться ліниво
        if name == 'img' and not in_hero and not tag.get('loading'):
            tag['loading'] = 'lazy'
            changed = True

        # 8. Заголовки секцій - великими літерами (бренд, модель, коди й одиниці - як є)
        if name == 'h2' and not in_hero:
            changed |= _uppercase_heading(tag, protected)

    return str(soup) if changed else markup
