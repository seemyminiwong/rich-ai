"""Категорія товару: точна, українською і без назви самого товару.

Що ламалось на живих сторінках artline.ua (2026-10-01):

1. Хлібні крихти набрані латинською «i» замість «і» («Зовнiшня кишеня»,
   «Комплектуючi») і з неекранованим ``&quot;``. Порівняння з назвою товару
   («Зовнішня кишеня … 2.5" …») не спрацьовувало, і остання крихта - САМ
   товар - ставала категорією.
2. Посилання без ``/uk/`` відкриває російську версію: «Корпуса для ПК» поруч
   із «Корпуси для ПК», «Компьютеры Artline». Фільтр проєктів двоївся.
3. Загальні розділи магазину («Додаткові аксесуари») - чесна, але марна для
   фільтра категорія; тип товару з назви («Зовнішня кишеня») кориснший.

Порядок: крихти поточної сторінки (нормалізовані) -> крихти української
версії тієї ж сторінки (hreflang uk або ``/uk/`` для artline.ua) -> meta ->
тип із назви. Без AI і без грошей: один додатковий GET лише для неукраїнської
сторінки.
"""
from __future__ import annotations

import html as html_lib
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

_CYR = 'А-Яа-яЁёІіЇїЄєҐґ'
_CYR_RE = re.compile(f'[{_CYR}]')
# Латинські двійники кириличних літер. Підміна лише всередині слів, де вже є
# кирилиця: «Комплектуючi» -> «Комплектуючі», але «ASUS», «USB3.0» не чіпаються.
_HOMOGLYPHS = str.maketrans({
    'i': 'і', 'I': 'І', 'a': 'а', 'e': 'е', 'o': 'о', 'c': 'с', 'p': 'р', 'x': 'х', 'y': 'у',
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
})
_WORD_RE = re.compile(r"[\w'’ʼ-]+", re.U)
_RU_ONLY = re.compile(r'[ыэъЫЭЪёЁ]')

GENERIC_CRUMBS = {
    'home', 'головна', 'главная', 'головна сторінка', 'главная страница', 'main', 'artline', 'shop', 'магазин',
    'каталог', 'catalog', 'products', 'товари', 'товары', 'usi-tovary', 'всі товари', 'все товары',
    'strona główna', 'sklep', 'produkty', 'all products',
}
# Розділи магазину, які формально є категорією, але для фільтра нічого не кажуть.
GENERIC_BUCKETS = {
    'додаткові аксесуари', 'дополнительные аксессуары', 'аксесуари', 'аксессуары', 'інше', 'другое', 'різне', 'разное',
    'комплектуючі', 'комплектующие', 'акції', 'акции', 'новинки', 'розпродаж', 'распродажа', 'уцінка', 'уценка',
    'accessories', 'other', 'misc', 'akcesoria', 'inne',
}


def fix_homoglyphs(text: str) -> str:
    """Латинські двійники -> кирилиця, але лише у словах, де кирилиця вже є."""
    def repl(match):
        word = match.group(0)
        return word.translate(_HOMOGLYPHS) if _CYR_RE.search(word) else word
    return _WORD_RE.sub(repl, text or '')


def normalize_label(text: str) -> str:
    """Як людина бачить підпис: декодовані сутності, кирилиця, один пробіл."""
    value = str(text or '')
    for _ in range(3):  # «&amp;quot;» на деяких шаблонах закодовано двічі
        decoded = html_lib.unescape(value)
        if decoded == value:
            break
        value = decoded
    value = fix_homoglyphs(value)
    return re.sub(r'\s+', ' ', value).strip(' /›»>-|·')


def _key(text: str) -> str:
    return re.sub(r'[^\w]+', ' ', normalize_label(text).lower()).strip()


def model_code(name: str) -> str:
    """Код моделі з назви: вміст дужок із цифрою або найдовший токен із цифрою."""
    name = normalize_label(name)
    inside = [x for x in re.findall(r'\(([^)]+)\)', name) if re.search(r'\d', x)]
    if inside:
        return max(inside, key=len).strip().lower()
    tokens = [t for t in re.split(r'[\s,()]+', name) if re.search(r'\d', t) and re.search(r'[A-Za-z]', t) and len(t) >= 4]
    return max(tokens, key=len).lower() if tokens else ''


def is_product_crumb(crumb: str, name: str) -> bool:
    """Крихта - це сам товар (а не категорія)?"""
    if not crumb or not name:
        return False
    a, b = _key(crumb), _key(name)
    if not a or not b:
        return False
    if a == b or (len(a) > 12 and (a in b or b in a)):
        return True
    code = model_code(name)
    if code and len(code) >= 4 and code in normalize_label(crumb).lower():
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def breadcrumbs(page_html: str) -> list[str]:
    """Нормалізовані хлібні крихти з BreadcrumbList або розмітки."""
    from app.pipeline import _html_breadcrumbs
    return [normalize_label(x) for x in _html_breadcrumbs(page_html) if normalize_label(x)]


def shop_category(page_html: str, product_name: str = '') -> str:
    """Найглибша крихта, яка не є ні коренем магазину, ні самим товаром."""
    candidates = []
    for crumb in breadcrumbs(page_html):
        low = crumb.lower()
        if low in GENERIC_CRUMBS or len(crumb) > 80:
            continue
        if is_product_crumb(crumb, product_name):
            continue
        candidates.append(crumb)
    return candidates[-1] if candidates else ''


def page_language(page_html: str) -> str:
    match = re.search(r'<html[^>]+\blang=["\']?([A-Za-z-]+)', page_html or '', re.I)
    return match.group(1).split('-')[0].lower() if match else ''


def is_russian_text(text: str) -> bool:
    low = (text or '').lower()
    return bool(_RU_ONLY.search(low)) or any(w in low for w in ('главная', 'комплектующие', 'корпуса', 'компьютеры'))


def ukrainian_url(page_html: str, url: str) -> str:
    """Адреса української версії тієї ж сторінки ('' якщо її немає або це вона сама)."""
    try:
        soup = BeautifulSoup(page_html or '', 'html.parser')
    except Exception:
        soup = None
    if soup is not None:
        for link in soup.find_all('link', attrs={'hreflang': True}):
            if str(link.get('hreflang')).lower().startswith('uk') and link.get('href'):
                href = link['href'].strip()
                return '' if href.rstrip('/') == (url or '').rstrip('/') else href
    parsed = urlparse(url or '')
    if parsed.netloc.endswith('artline.ua') and not parsed.path.startswith('/uk/'):
        return urlunparse(parsed._replace(path='/uk' + (parsed.path if parsed.path.startswith('/') else '/' + parsed.path)))
    return ''


def page_product_name(page_html: str, url: str = '') -> str:
    """Назва товару зі сторінки: JSON-LD Product, інакше останнє слово крихт (сам товар)."""
    from app.pipeline import _normalize_jsonld, parse_page
    try:
        jsonld, _images, title, _text = parse_page(page_html, url)
        name = (_normalize_jsonld(jsonld) if jsonld else {}).get('name') or ''
    except Exception:
        name, title = '', ''
    if not name:
        trail = breadcrumbs(page_html)
        name = trail[-1] if trail else title
    return normalize_label(name)


def product_type(name: str) -> str:
    """Тип товару з початку назви («Зовнішня кишеня Gembird …» -> «Зовнішня кишеня»)."""
    from app.pipeline import _category_from_name
    return _category_from_name(normalize_label(name))


def resolve_category(page_html: str, url: str, product_name: str, fetch=None, meta_category: str = '') -> dict:
    """Категорія проєкту з поясненням, звідки вона.

    Повертає {category, shop_category, product_type, source, trail}. ``fetch`` -
    функція url -> html для української версії; None = без мережі (тести,
    екстракція), тоді береться лише поточна сторінка.
    """
    name = normalize_label(product_name)
    type_name = name
    trail = breadcrumbs(page_html)
    category = shop_category(page_html, name)
    source = 'breadcrumbs' if category else ''
    russian = page_language(page_html) == 'ru' or is_russian_text(' '.join(trail))
    if fetch is not None and (russian or not category):
        uk = ukrainian_url(page_html, url)
        if uk:
            try:
                from app.pipeline import is_public_http_url
                if is_public_http_url(uk):
                    uk_html = fetch(uk)
                    uk_category = shop_category(uk_html, name)
                    if uk_category:
                        category, source, trail = uk_category, 'breadcrumbs_uk', breadcrumbs(uk_html)
                        # Тип товару теж українською: назва з тієї ж української сторінки.
                        uk_name = page_product_name(uk_html, uk)
                        if uk_name:
                            type_name = uk_name
            except Exception:
                pass  # українська версія недоступна - лишаємо те, що є
    if not category and meta_category:
        category, source = normalize_label(meta_category), 'meta'
    kind = product_type(type_name)
    result = {'shop_category': category, 'product_type': kind, 'trail': trail}
    if category and category.lower() in GENERIC_BUCKETS and kind:
        result.update(category=kind, source=source + '+type')
    elif category:
        result.update(category=category, source=source)
    else:
        result.update(category=kind, source='name' if kind else '')
    return result
