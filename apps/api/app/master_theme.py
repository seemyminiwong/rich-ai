"""Тема сторінки ARTLINE Master: змішана (як у майстер-промпті), світла або темна.

Оператор обирає тему при запуску проєкту. Промпт просить модель про потрібне
полотно, а цей модуль гарантує результат механічно - так само, як стандарт
ARTLINE: модель, переклад і мобільне перекомпонування повертають «свої» темні
чи світлі блоки за звичкою. Змінюються лише кольори в inline-стилях: сітка,
тексти, зображення й коментарі блоків ті самі.

Правила перетворення:
- поверхня (фон елемента) неправильного тону стає канонічною поверхнею теми;
- біла рамка з фото товару лишається білою в обох темах - рендер на білому
  тлі не можна класти на темне чи тонувати;
- напівпрозорі оверлеї Hero міняють тон (темна вуаль -> світла і навпаки);
- колір тексту перераховується від ПІДСУМКОВОЇ поверхні під ним: заголовки
  #101010/#FFFFFF, текст #555555/#D8DDE2, акцент #157985/#19BCC9;
- межі - #D0D7DE на світлому, #35393F на темному.
Прохід ідемпотентний: на сторінці потрібної теми нічого не змінює.
"""
import re

from bs4 import BeautifulSoup

from app.artline_standard import _luminance, _set_decl

THEMES = ('mixed', 'light', 'dark')
VIDEO_CLASS = 'arvid'  # = pipeline.SHOWCASE_VIDEO_CLASS
THEME_LABELS = {'mixed': 'Змішана', 'light': 'Світла', 'dark': 'Темна'}

_HEX = re.compile(r'#([0-9a-f]{6}|[0-9a-f]{3})\b', re.I)
_RGBA = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)', re.I)
_DECL = re.compile(r'\s*([-\w]+)\s*:\s*([^;]*)')

LIGHT_BANNER = 'linear-gradient(135deg,#FFFFFF 0%,#F5F7FA 100%)'
DARK_BANNER = 'linear-gradient(135deg,#101010 0%,#1A2128 100%)'
_HEADING_TAGS = {'h2', 'h3', 'h4', 'strong', 'b', 'summary'}


def normalize_theme(value) -> str:
    value = str(value or '').strip().lower()
    return value if value in THEMES else 'mixed'


def _rgb(token: str):
    m = _HEX.fullmatch(token.strip())
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = _RGBA.fullmatch(token.strip())
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4) or 1)
    return None


def _colors(value: str):
    out = []
    for m in re.finditer(r'#[0-9a-f]{3,6}\b|rgba?\([^)]*\)', value or '', re.I):
        c = _rgb(m.group(0))
        if c:
            out.append(c)
    return out


def _decls(style: str):
    return [(m.group(1).lower(), m.group(2).strip()) for m in _DECL.finditer(style or '') if m.group(2).strip()]


def _surface_tone(style: str):
    """'dark' / 'light' / None для власного фону елемента (без успадкування)."""
    for prop, value in _decls(style):
        if prop not in ('background', 'background-color', 'background-image'):
            continue
        if 'url(' in value and prop != 'background-color':
            # фото-фон: тон задає колір-підкладка, якщо він є
            solid = [c for c in _colors(value.split('url(')[0]) if c[3] >= .9]
            if solid:
                return 'dark' if _luminance(*solid[0][:3]) < .2 else 'light'
            continue
        solid = [c for c in _colors(value) if c[3] >= .5]
        if not solid:
            continue
        lum = sum(_luminance(*c[:3]) for c in solid) / len(solid)
        return 'dark' if lum < .2 else 'light'
    return None


def _is_overlay(style: str) -> bool:
    flat = (style or '').replace(' ', '').lower()
    return 'position:absolute' in flat and 'gradient(' in flat and 'rgba(' in flat


def _photo_frame(tag) -> bool:
    """Біла рамка з фото товару: є img, майже немає тексту."""
    if tag.find('img') is None:
        return False
    return len(tag.get_text(' ', strip=True)) <= 2


def _swap_overlay(value: str, theme: str) -> str:
    def repl(m):
        r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        dark = _luminance(r, g, b) < .2
        if theme == 'light' and dark:
            return f'rgba(255,255,255,{a or 1})'
        if theme == 'dark' and not dark:
            return f'rgba(16,16,16,{a or 1})'
        return m.group(0)
    return _RGBA.sub(repl, value)


def _retone_surface(tag, theme: str, depth: int):
    style = tag.get('style') or ''
    new = style
    for prop, value in _decls(style):
        if prop not in ('background', 'background-color', 'background-image'):
            continue
        if 'url(' in value:
            # Hero: підкладку під фото - у тон теми, сам кадр не чіпаємо
            base = '#F5F7FA' if theme == 'light' else '#101010'
            fixed = _HEX.sub(lambda m: base if (_rgb(m.group(0)) and ((_luminance(*_rgb(m.group(0))[:3]) < .2) == (theme == 'light'))) else m.group(0), value)
            new = new.replace(value, fixed, 1)
        elif 'gradient(' in value and prop != 'background-color':
            new = new.replace(value, LIGHT_BANNER if theme == 'light' else DARK_BANNER, 1)
        else:
            if theme == 'light':
                target = '#F5F7FA' if depth == 0 else '#FFFFFF'
            else:
                target = '#101010' if depth % 2 == 0 else '#1A2128'
            new = re.sub(r'(?<![-\w])' + re.escape(prop) + r'\s*:\s*' + re.escape(value), f'{prop}:{target}', new, count=1)
    new = _set_decl(new, 'color', '#101010' if theme == 'light' else '#FFFFFF')
    if new != style:
        tag['style'] = new
        return True
    return False


def _retone_borders(tag, theme: str):
    style = tag.get('style') or ''
    new = style
    for prop, value in _decls(style):
        if not prop.startswith('border') or 'radius' in prop:
            continue
        cols = _colors(value)
        if not cols:
            continue
        lum = _luminance(*cols[0][:3])
        wrong = (theme == 'light' and (lum < .2 or (cols[0][0] == 255 and cols[0][3] < .5))) or (theme == 'dark' and lum > .5 and cols[0][3] >= .5)
        if wrong:
            fixed = re.sub(r'#[0-9a-f]{3,6}\b|rgba?\([^)]*\)', '#D0D7DE' if theme == 'light' else '#35393F', value, count=1, flags=re.I)
            new = new.replace(value, fixed, 1)
    if new != style:
        tag['style'] = new
        return True
    return False


def _surface_of(tag):
    node = tag
    while node is not None and getattr(node, 'get', None):
        tone = _surface_tone(node.get('style') or '')
        if tone:
            return tone
        node = node.parent
    return 'light'


def _retone_text(tag, theme: str):
    style = tag.get('style') or ''
    col = next((v for p, v in _decls(style) if p == 'color'), None)
    if not col:
        return False
    c = _rgb(col)
    if not c:
        return False
    surface = _surface_of(tag)
    lum = _luminance(*c[:3])
    accent = abs(c[0] - 25) + abs(c[1] - 188) + abs(c[2] - 201) < 30 or abs(c[0] - 21) + abs(c[1] - 121) + abs(c[2] - 133) < 30 or col.upper() == '#C9F0F4'
    heading = tag.name in _HEADING_TAGS or bool(re.search(r'font-weight\s*:\s*(7|8|9)00', style))
    target = None
    if surface == 'light':
        if accent and col.upper() != '#157985':
            target = '#157985'
        elif not accent and lum > .45:
            target = '#101010' if heading else '#555555'
    else:
        if accent and col.upper() == '#157985':
            target = '#19BCC9'
        elif not accent and lum < .25:
            target = '#FFFFFF' if heading else '#D8DDE2'
    if target and target.upper() != col.upper():
        tag['style'] = _set_decl(style, 'color', target)
        return True
    return False


def apply_master_theme(markup: str, theme: str) -> str:
    theme = normalize_theme(theme)
    if theme == 'mixed' or not markup or '<section' not in markup:
        return markup
    soup = BeautifulSoup(markup, 'html.parser')
    root = soup.find('section')
    if root is None:
        return markup
    changed = False
    wrong = 'dark' if theme == 'light' else 'light'
    # Блок відео сервер будує сам, уже в тоні теми (inject_video_block(dark=...));
    # вуаль і кнопка на постері - частина кадру, їх не перефарбовуємо.
    skip = {id(t) for v in root.find_all(class_=VIDEO_CLASS) for t in [v, *v.find_all(True)]}
    # 1. поверхні (глибина - для чергування тонів усередині блоків)
    for tag in root.find_all(True):
        style = tag.get('style') or ''
        if not style or id(tag) in skip:
            continue
        if _is_overlay(style):
            new = _swap_overlay(style, theme)
            if new != style:
                tag['style'] = new
                changed = True
            continue
        tone = _surface_tone(style)
        if tone != wrong:
            continue
        if theme == 'dark' and _photo_frame(tag):
            continue
        depth = sum(1 for p in tag.parents if getattr(p, 'get', None) and _surface_tone(p.get('style') or '') and p is not root)
        changed |= _retone_surface(tag, theme, depth)
    # 2. межі й текст - від підсумкових поверхонь
    for tag in root.find_all(True):
        if id(tag) in skip:
            continue
        if theme == 'dark' and _photo_frame(tag) and _surface_tone(tag.get('style') or '') == 'light':
            continue
        changed |= _retone_borders(tag, theme)
        changed |= _retone_text(tag, theme)
    # корінь: успадкований колір тексту - під тему
    root_style = root.get('style') or ''
    want = '#FFFFFF' if theme == 'dark' else '#101010'
    new_root = _set_decl(root_style, 'color', want)
    if new_root != root_style:
        root['style'] = new_root
        changed = True
    return str(soup) if changed else markup


def master_theme_prompt(theme: str) -> str:
    """Перекриття полотна для моделі; змішана тема - текст майстер-промпту як є."""
    theme = normalize_theme(theme)
    if theme == 'light':
        return ('\n\nCANVAS THEME: LIGHT (overrides the dark blocks of the canvas rhythm; the grid, blocks and slots stay the same)\n'
                '- Every major block is light: alternate #FFFFFF and #F5F7FA so neighbouring blocks differ; cards #FFFFFF with border #D0D7DE.\n'
                '- Text: headings #101010, body #555555; accent text #157985, thin accent borders #19BCC9.\n'
                '- Hero: the same wrapper with the hero photo, but background-color #F5F7FA and a LIGHT overlay '
                'linear-gradient(90deg,rgba(255,255,255,.94) 0%,rgba(255,255,255,.72) 52%,rgba(255,255,255,0) 100%) '
                '(mobile: 180deg, transparent at the top over the product, dense at the bottom); badge, h2, subtitle and paragraph in dark text.\n'
                f'- Closing banner (block 07): background {LIGHT_BANNER} with dark text.\n'
                '- No dark surface anywhere on the page.')
    if theme == 'dark':
        return ('\n\nCANVAS THEME: DARK (overrides the light blocks of the canvas rhythm; the grid, blocks and slots stay the same)\n'
                '- Every major block is dark: alternate #101010 and #1A2128 so neighbouring blocks differ; cards #1A2128 on #101010 and #252525 on #1A2128, border #35393F.\n'
                '- Text: headings #FFFFFF, body #D8DDE2; accent text and big values #19BCC9.\n'
                '- White-background product renders still sit in WHITE inset frames (background:#FFFFFF;border-radius:12px;padding:18px) - the only light surfaces.\n'
                '- FAQ: background #1A2128, border #35393F, hairlines #35393F, questions #FFFFFF, answers #D8DDE2.\n'
                '- No light block anywhere on the page.')
    return ''


def theme_image_hint(theme: str) -> str:
    """Підказка для Hero-сцени, щоб фото збігалося з тоном сторінки."""
    theme = normalize_theme(theme)
    if theme == 'light':
        return ('\nPAGE THEME: LIGHT. Build a bright, airy environment: light neutral surfaces (white, #F5F7FA, pale stone, light oak), '
                'soft daylight, gentle shadows; the text-safe area stays bright and uncluttered. No dark or moody backdrop.')
    if theme == 'dark':
        return ('\nPAGE THEME: DARK. Build a dark, low-key environment (#101010-#1A2128 tones) with controlled rim light on the product; '
                'the text-safe area stays dark and uncluttered.')
    return ''
