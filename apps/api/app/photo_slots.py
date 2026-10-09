"""Мало фото для річа: бюджет кадрів у промпті й прибирання порожніх фото-слотів.

Стилі розраховані на кілька реальних кадрів галереї. Коли їх бракує, модель
вигадує URL (білий список його вирізає), повторює кадр або малює порожню рамку -
і на сторінці лишаються білі картки та половини сітки без нічого (запит власника
2026-10-09). Дві гарантії:

- photo_budget_line: модель заздалегідь знає точну кількість кадрів і текстовий
  варіант блоку, коли кадру немає;
- drop_empty_photo_slots: сервер прибирає повтори фото, порожні рамки (і обгортки,
  які від цього спорожніли) та стискає сітку до колонок, що лишились.

Чистка навмисно обережна (рев'ю ecc:python-reviewer): рамкою вважається лише
порожній блок, що ВИГЛЯДАЄ як місце під фото - нейтральне тло, рамка або
скруглення і розмір більший за іконку. Розпірки, кольорові плашки, градієнти,
роздільники, стовпчики діаграм і сітки з явним розміщенням не чіпаються.
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

# Менше за це - декор чи іконка, а не місце під фото.
MIN_SLOT_PX = 100
# Іконка в rem/em: 6rem ≈ 96px.
MIN_SLOT_EM = 6
# Нейтральне тло: канали відрізняються не більше ніж на стільки.
NEUTRAL_SPREAD = 24
CONTENT_TAGS = ('img', 'picture', 'video', 'iframe', 'svg', 'canvas', 'source', 'object', 'embed',
                'input', 'button', 'textarea', 'select', 'hr', 'i', 'style', 'script')
SLOT_TAGS = ('div', 'figure', 'picture')
EMPTIED_TAGS = SLOT_TAGS + ('a', 'li')
_MAX_PASSES = 6
_UNKNOWN_TRACKS = re.compile(r'(?<![a-z-])(?:calc|clamp|min|max)\(|auto-fit|auto-fill|subgrid|masonry')


def photo_budget_line(hero: str, feature: str, gallery: list[str] | None) -> str:
    """Рядок промпту з точним бюджетом зображень і правилом для блоку без кадру."""
    frames = [u for u in dict.fromkeys(gallery or []) if u and u not in (hero, feature)]
    parts = [label for label, url in (('hero', hero), ('feature', feature)) if url]
    total = len(parts) + len(frames)
    if frames:
        parts.append(f'{len(frames)} GALLERY_IMAGES frame' + ('s' if len(frames) != 1 else ''))
    else:
        parts.append('no GALLERY_IMAGES frames')
    line = (f'PHOTO BUDGET: {total} distinct images in this request ({", ".join(parts)}). '
            'Count the photo slots of your layout against this budget before writing. Each supplied URL fills '
            'at most once one photo slot (a Hero background and its img are one slot). When a block calls for a '
            'photo and no unused URL is left, build its text-only form: the copy takes the full width '
            '(grid-template-columns:1fr) or the photo column becomes a card of confirmed values; a card that loses '
            'its photo slot keeps its heading and text. Never leave an empty frame, a white or grey placeholder '
            'box, an icon stand-in or a repeated photo.')
    if not frames:
        line += ' With no GALLERY_IMAGES frames, no block may depend on one.'
    return line


# --- CSS-помічники -------------------------------------------------------------

def _norm(style: str | None) -> str:
    return re.sub(r'\s+', '', (style or '').lower())


def _decl(style: str | None, prop: str) -> str:
    """Значення властивості з пробілами всередині (для розбору списку треків)."""
    match = re.search(r'(?:^|;)\s*' + re.escape(prop) + r'\s*:\s*([^;]+)', (style or '').lower())
    return ' '.join(match.group(1).replace('!important', '').split()) if match else ''


def _px(norm: str, prop: str) -> float | None:
    match = re.search(r'(?:^|;)' + re.escape(prop) + r':(-?\d+(?:\.\d+)?)px', norm)
    return float(match.group(1)) if match else None


def _set_decl(style: str, prop: str, value: str) -> str:
    pattern = re.compile(r'(?<![-\w])' + re.escape(prop) + r'\s*:\s*[^;]*', re.I)
    if pattern.search(style):
        return pattern.sub(f'{prop}:{value}', style, count=1)
    style = style.rstrip().rstrip(';')
    return f'{style};{prop}:{value}' if style else f'{prop}:{value}'


def _is_small(norm: str) -> bool:
    for prop in ('width', 'height', 'max-width'):
        px = _px(norm, prop)
        if px is not None and px < MIN_SLOT_PX:
            return True
        em = re.search(r'(?:^|;)' + prop + r':(\d+(?:\.\d+)?)r?em', norm)
        if em and float(em.group(1)) < MIN_SLOT_EM:
            return True
    return False


def _rgb(color: str) -> tuple[int, int, int] | None:
    if color == 'white':
        return (255, 255, 255)
    hexa = re.fullmatch(r'#([0-9a-f]{3}|[0-9a-f]{6})', color)
    if hexa:
        value = hexa.group(1)
        value = ''.join(c * 2 for c in value) if len(value) == 3 else value
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    rgb = re.fullmatch(r'rgba?\((\d+),(\d+),(\d+)(?:,[\d.]+)?\)', color)
    return tuple(int(rgb.group(i)) for i in (1, 2, 3)) if rgb else None


def _background(norm: str) -> str:
    match = re.search(r'(?:^|;)background(?:-color)?:([^;]+)', norm)
    return match.group(1) if match else ''


def _looks_like_photo_frame(norm: str) -> bool:
    """Нейтральне (біле, сіре, темно-сіре) тло, рамка або скруглення - але не кольорова плашка."""
    background = _background(norm)
    if 'gradient(' in background:
        return False
    color = None
    if background:
        first = re.match(r'#[0-9a-f]+|rgba?\([^)]*\)|[a-z]+', background)
        color = _rgb(first.group(0)) if first else None
        if color is None:
            return False
        if max(color) - min(color) > NEUTRAL_SPREAD:
            return False  # кольорова плашка, свотч, стовпчик діаграми
    has_border = bool(re.search(r'(?:^|;)border:(?!0|none)', norm))
    return bool(color) or has_border or 'border-radius:' in norm


# --- що вважається вмістом і рамкою ---------------------------------------------

def _alive(tag) -> bool:
    return isinstance(tag, Tag) and not tag.decomposed and tag.parent is not None


def _is_grid(tag) -> bool:
    return _alive(tag) and 'display:grid' in _norm(tag.get('style'))


def _has_content(tag: Tag) -> bool:
    """Текст, медіа, контроли, стилі або фонове зображення - отже, це не порожня рамка."""
    if tag.name in CONTENT_TAGS or tag.get_text(strip=True) or tag.find(CONTENT_TAGS):
        return True
    return any('url(' in _norm(node.get('style')) for node in [tag, *tag.find_all(True)])


def _placed_grid(grid: Tag) -> bool:
    """Сітка з явним розміщенням (області, рядки, номери колонок) - розкладку не чіпаємо."""
    norm = _norm(grid.get('style'))
    if 'grid-template-areas:' in norm or 'grid-template:' in norm:
        return True
    for child in grid.children:
        if not isinstance(child, Tag):
            continue
        child_norm = _norm(child.get('style'))
        if re.search(r'(?:^|;)grid-(?:area|row|row-start|row-end|column-start|column-end):', child_norm):
            return True
        column = re.search(r'(?:^|;)grid-column:([^;]+)', child_norm)
        if column and column.group(1) != '1/-1':
            return True
    return False


def _is_empty_slot(tag: Tag) -> bool:
    if _has_content(tag):
        return False
    norm = _norm(tag.get('style'))
    if re.search(r'(?:^|;)position:(?:absolute|fixed|sticky)', norm) or _is_small(norm):
        return False  # оверлеї, декор, іконки, роздільники в 1px
    if re.search(r'(?:^|;)border-(?:top|bottom|left|right):', norm) and not _background(norm):
        return False  # лінія-роздільник
    if not _looks_like_photo_frame(norm):
        return False  # розпірка, кольорова плашка, градієнт
    parent_grid = _is_grid(tag.parent)
    if parent_grid and _placed_grid(tag.parent):
        return False
    height = max((v for v in (_px(norm, 'height'), _px(norm, 'min-height')) if v is not None), default=0)
    return height >= MIN_SLOT_PX or 'aspect-ratio:' in norm or parent_grid


# --- повтори фото ----------------------------------------------------------------

def _is_icon(img: Tag) -> bool:
    src = (img.get('src') or '').strip().lower().split('?')[0]
    if not src or src.startswith('data:') or src.endswith('.svg'):
        return True
    for attr in ('width', 'height'):
        value = str(img.get(attr) or '').strip().removesuffix('px')
        if value.isdigit() and int(value) < MIN_SLOT_PX:
            return True
    parent = img.parent
    if _is_small(_norm(img.get('style'))) or (isinstance(parent, Tag) and _is_small(_norm(parent.get('style')))):
        return True
    # Картинка поруч із текстом у тому ж рядку - значок пункту списку, а не фото.
    return isinstance(parent, Tag) and any(isinstance(n, NavigableString) and n.strip() for n in parent.children)


def _drop_repeated_photos(soup) -> list[Tag]:
    """Кожне фото - один раз; повтор вирізається разом із picture/figure."""
    seen, parents = set(), []
    for img in soup.find_all('img'):
        if not _alive(img) or _is_icon(img):
            continue
        src = img.get('src').strip()
        if src not in seen:
            seen.add(src)
            continue
        target = img
        if target.parent.name == 'picture':
            target = target.parent
        if target.parent.name == 'figure':
            target = target.parent
        parents.append(target.parent)
        target.decompose()
    return parents


# --- сітка -------------------------------------------------------------------------

def _split_top_level(value: str) -> list[str]:
    tokens, depth, token = [], 0, ''
    for char in value + ' ':
        depth += (char in '([') - (char in ')]')
        if char == ' ' and depth == 0:
            if token:
                tokens.append(token)
            token = ''
            continue
        token += char
    return tokens


def _track_count(style: str | None) -> int:
    """Кількість колонок; 0 - невідомо (calc/clamp/auto-fit), тоді розкладку не чіпаємо."""
    value = _decl(style, 'grid-template-columns')
    if not value or _UNKNOWN_TRACKS.search(value):
        return 0
    count = 0
    for token in _split_top_level(value):
        if token.startswith('['):
            continue  # іменовані лінії
        repeat = re.fullmatch(r'repeat\(\s*(\d+)\s*,(.*)\)', token)
        if repeat:
            inner = [t for t in _split_top_level(repeat.group(2).strip()) if not t.startswith('[')]
            count += int(repeat.group(1)) * len(inner)
        else:
            count += 1
    return count


def _shrink_grid(grid: Tag) -> bool:
    """Сітка, з якої зникла клітинка: колонок стає стільки, скільки лишилось клітинок."""
    tracks = _track_count(grid.get('style'))
    if tracks < 2 or _placed_grid(grid):
        return False
    children = [c for c in grid.children if isinstance(c, Tag)]
    singles = [c for c in children if 'grid-column:1/-1' not in _norm(c.get('style'))]
    if not singles or len(singles) >= tracks:
        return False
    value = 'minmax(0,1fr)' if len(singles) == 1 else f'repeat({len(singles)},minmax(0,1fr))'
    grid['style'] = _set_decl(grid.get('style') or '', 'grid-template-columns', value)
    return True


# --- прохід -------------------------------------------------------------------------

def _outermost(tags: list[Tag]) -> list[Tag]:
    chosen = {id(t) for t in tags}
    return [t for t in tags if not any(id(p) in chosen for p in t.parents)]


def _emptied_wrappers(touched: list) -> list[Tag]:
    """Обгортка, яку спорожнили наші ж видалення, теж іде геть (смуга без фото)."""
    return [t for t in touched if _alive(t) and t.name in EMPTIED_TAGS
            and t.parent.name != '[document]' and not _has_content(t)]


def drop_empty_photo_slots(markup: str) -> str:
    """Прибрати повтори фото й порожні фото-рамки; осиротілі колонки стиснути."""
    if not markup or '<' not in markup:
        return markup
    soup = BeautifulSoup(markup, 'html.parser')
    touched = _drop_repeated_photos(soup)
    repeated = len(touched)
    removed = 0
    for _ in range(_MAX_PASSES):
        candidates = [t for t in soup.find_all(SLOT_TAGS) if _is_empty_slot(t)] + _emptied_wrappers(touched)
        candidates = _outermost(list({id(t): t for t in candidates}.values()))
        if not candidates:
            break
        for tag in candidates:
            touched.append(tag.parent)
            tag.decompose()
            removed += 1
    grids = {id(t): t for t in touched if _is_grid(t)}
    reshaped = sum(_shrink_grid(t) for t in grids.values())
    if not (repeated or removed or reshaped):
        return markup
    logger.warning('Photo shortage cleanup: %d repeated photos, %d empty slots, %d grids reshaped',
                   repeated, removed, reshaped)
    return str(soup)
