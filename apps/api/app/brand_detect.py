"""Бренд товару -> фірмова палітра.

Студія сама визначає бренд і пропонує його палітру: оператор не шукає пресет
у списку з сотні брендів. Джерела за надійністю:
1. JSON-LD Product.brand сторінки товару (магазин заповнює його сам);
2. назва товару - шукаємо відомий бренд цілим словом, найраніший і найдовший
   («ASUS ROG Strix» -> «ASUS ROG», а не «ASUS»);
3. адреса сторінки (slug «korpus-hyte-x50-...»).
«Відомі бренди» - назви пресетів палітр у базі: фірмові з каталогу artline.ua
плюс створені операторами. Бренд без пресета теж повертаємо - інтерфейс
підкаже «З фото товару». Власний бренд ARTLINE палітри не потребує: фірмовий
циан і є схемою за замовчуванням.
"""
import re

HOUSE_BRANDS = {'artline'}


def _norm(value: str) -> str:
    return re.sub(r'[^0-9a-zа-яіїєґ]+', '', str(value or '').lower())


def jsonld_brand(product) -> str:
    if not isinstance(product, dict):
        return ''
    brand = product.get('brand') or product.get('manufacturer') or ''
    if isinstance(brand, list):
        brand = brand[0] if brand else ''
    if isinstance(brand, dict):
        brand = brand.get('name') or ''
    return str(brand or '').strip()[:80]


def _word_re(name: str):
    parts = [re.escape(p) for p in re.findall(r'[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+', name)]
    return re.compile(r'(?<![0-9A-Za-zА-Яа-яІіЇїЄєҐґ])' + r'[\W_]*'.join(parts) + r'(?![0-9A-Za-zА-Яа-яІіЇїЄєҐґ])', re.I)


def _match_in_text(text: str, known: list[str]) -> str | None:
    best = None
    for name in known:
        if len(_norm(name)) < 2:
            continue
        m = _word_re(name).search(text or '')
        if m and (best is None or (m.start(), -len(name)) < (best[0], -len(best[1]))):
            best = (m.start(), name)
    return best[1] if best else None


def detect_brand(known: list[str], jsonld=None, name: str = '', url: str = '', brand: str = '') -> dict:
    """{'brand': як на сторінці або '', 'preset': назва пресета або None, 'source': звідки, 'house': bool}."""
    known = [k for k in dict.fromkeys(known or []) if k]
    by_norm = {_norm(k): k for k in known}
    raw = (brand or '').strip() or jsonld_brand(jsonld)
    result = {'brand': raw, 'preset': None, 'source': 'jsonld' if raw else '', 'house': False}
    if raw:
        preset = by_norm.get(_norm(raw)) or _match_in_text(raw, known)
        if preset:
            # Суббренд у назві точніший за бренд виробника: «ASUS» + «ROG Strix» -> «ASUS ROG».
            sub = _match_in_text(name, [k for k in known if _norm(k).startswith(_norm(preset)) and len(k) > len(preset)])
            result['preset'] = sub or preset
    if not result['preset']:
        preset = _match_in_text(name, known)
        if preset:
            result.update(preset=preset, brand=result['brand'] or preset, source=result['source'] or 'name')
    if not result['preset'] and url:
        slug = re.sub(r'https?://[^/]+', '', url)
        preset = _match_in_text(slug.replace('/', ' ').replace('-', ' ').replace('_', ' '), known)
        if preset:
            result.update(preset=preset, brand=result['brand'] or preset, source=result['source'] or 'url')
    if not result['brand'] and name and re.search(r'\bartline\b', name, re.I):
        result['brand'] = 'ARTLINE'
        result['source'] = 'name'
    result['house'] = _norm(result['brand']) in HOUSE_BRANDS
    if result['house']:
        result['preset'] = None
    return result
