"""Промо-лендінги кампаній (зразок: artline.ua/uk/solution/bambu-lab).

Інший жанр, ніж rich-картка товару: N товарів разом, ЦІНИ і кнопки «Купити»
(рich-стилям заборонені), вихід - повноцінна standalone-сторінка, а не фрагмент
для редактора. Тому окремий модуль з власним санітайзером (дозволяє <a href>)
і власним детермінованим шаблоном на випадок відмови AI.

Дані беруться лише з проб реальних сторінок товарів (JSON-LD Product/offers):
модель не має права вигадати ні ціну, ні URL.
"""
import html as html_lib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.pipeline import fetch_html, parse_page, is_public_http_url

logger = logging.getLogger('artline.landing')

MAX_PRODUCTS = 24

_LANDING_ALLOWED_TAGS = {
    'html', 'head', 'meta', 'title', 'body', 'style',
    'section', 'div', 'h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li',
    'img', 'a', 'strong', 'span', 'em', 'b', 'i', 'br', 'small', 'del',
}
_LANDING_ALLOWED_ATTRS = {'style', 'src', 'alt', 'title', 'width', 'height',
                          'loading', 'href', 'target', 'rel', 'charset', 'name', 'content', 'lang'}


def sanitize_landing_html(markup: str) -> str:
    """Як sanitize_html, але для standalone-сторінки: дозволені <a href> (лише
    http/https), <h1>, <head>/<meta>. Скрипти, форми і активний CSS - ні."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    for bad in soup(['script', 'iframe', 'object', 'embed', 'link', 'form', 'input', 'button', 'svg', 'noscript', 'base']):
        bad.decompose()
    for style_tag in soup.find_all('style'):
        css = (style_tag.string or style_tag.get_text() or '').lower()
        if not css.strip() or any(tok in css for tok in ('url(', '@import', 'expression', '<', 'javascript')):
            style_tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name not in _LANDING_ALLOWED_TAGS:
            tag.unwrap()
            continue
        for attr in list(tag.attrs):
            raw = tag.attrs[attr]
            value = ' '.join(raw) if isinstance(raw, list) else str(raw)
            flat = value.strip().lower().replace('\t', '').replace('\n', '').replace('\r', '')
            if attr.startswith('on') or attr not in _LANDING_ALLOWED_ATTRS:
                del tag.attrs[attr]
                continue
            if attr in ('src', 'href') and not flat.startswith(('http://', 'https://', '/')):
                del tag.attrs[attr]
                continue
            if attr == 'style' and ('javascript:' in flat or 'expression(' in flat or '@import' in flat):
                del tag.attrs[attr]
        if tag.name == 'a':
            tag['rel'] = 'noopener'
    return str(soup)


def _offer_price(product: dict) -> tuple[str, str]:
    """('115449', 'UAH') з JSON-LD offers будь-якої форми; ('', '') якщо нема."""
    offers = (product or {}).get('offers')
    nodes = offers if isinstance(offers, list) else [offers]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for key in ('price', 'lowPrice'):
            value = node.get(key)
            if value not in (None, ''):
                price = re.sub(r'[^\d.]', '', str(value)).rstrip('.')
                if price:
                    return price.split('.')[0], str(node.get('priceCurrency') or 'UAH')
        inner = node.get('offers')
        if inner:
            price, cur = _offer_price({'offers': inner})
            if price:
                return price, cur
    return '', ''


def format_price(price: str, currency: str) -> str:
    if not price:
        return ''
    pretty = '{:,}'.format(int(price)).replace(',', ' ') if price.isdigit() else price
    return f'{pretty} {"₴" if currency in ("UAH", "", None) else currency}'


def probe_landing_product(url: str) -> dict:
    """Одна проба: назва, головне фото, ціна. Без AI - лише парсинг сторінки."""
    page = fetch_html(url)
    product, images, title, _text = parse_page(page, url)
    product = product or {}
    price, currency = _offer_price(product)
    name = str(product.get('name') or '').strip() or re.sub(r'\s*[|·—-]\s*(ARTLINE|Artline).*$', '', title).strip()
    return {
        'url': url,
        'name': name[:180],
        'image': next(iter(images), ''),
        'price': price,
        'price_text': format_price(price, currency),
        'brand': (product.get('brand') or {}).get('name', '') if isinstance(product.get('brand'), dict) else str(product.get('brand') or ''),
    }


def extract_product_links(listing_url: str, cap: int = MAX_PRODUCTS) -> list[str]:
    """Посилання на товари зі сторінки акції/категорії (шаблон /product/)."""
    page = fetch_html(listing_url)
    soup = BeautifulSoup(page or '', 'html.parser')
    host = urlparse(listing_url).netloc
    seen, out = set(), []
    for anchor in soup.find_all('a', href=True):
        absolute = urljoin(listing_url, anchor['href']).split('#')[0].split('?')[0]
        parsed = urlparse(absolute)
        if parsed.netloc != host or '/product/' not in parsed.path:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
        if len(out) >= cap:
            break
    return out


def _chunk(campaign: dict, key: str, default: str = '') -> str:
    return html_lib.escape(str(campaign.get(key) or default))


def deterministic_landing(campaign: dict, products: list[dict]) -> str:
    """Аварійний шаблон: та сама структура, що в AI-версії, нуль токенів.
    Темне промо-hero -> сітка товарів з цінами і кнопками -> переваги."""
    lang = campaign.get('language') or 'ua'
    buy = 'Купити' if lang == 'ua' else 'Купить'
    title = _chunk(campaign, 'campaign_title') or _chunk(campaign, 'name')
    cards = []
    for p in products:
        img = html_lib.escape(p.get('image') or '')
        url = html_lib.escape(p.get('url') or '')
        name = html_lib.escape(p.get('name') or '')
        price = html_lib.escape(p.get('price_text') or '')
        cards.append(
            f'<div style="background:#FFFFFF;border:1px solid #D0D7DE;border-radius:22px;overflow:hidden;display:flex;flex-direction:column">'
            f'<div style="height:230px;background:#FFFFFF;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box">'
            f'<img src="{img}" alt="{name}" loading="lazy" style="max-width:100%;max-height:100%;object-fit:contain"></div>'
            f'<div style="padding:18px;display:flex;flex-direction:column;gap:10px;flex:1">'
            f'<p style="margin:0;font-size:15px;line-height:1.45;color:#101010;font-weight:700;flex:1">{name}</p>'
            + (f'<div style="font-size:22px;font-weight:950;color:#101010">{price}</div>' if price else '')
            + f'<a href="{url}" rel="noopener" style="display:block;text-align:center;background:#19BCC9;color:#101010;font-weight:900;text-decoration:none;'
              f'padding:12px 16px;border-radius:999px;font-size:14px">{buy}</a></div></div>'
        )
    advantages = [
        ('Офіційна гарантія' if lang == 'ua' else 'Официальная гарантия'),
        ('Технічна підтримка 24/7' if lang == 'ua' else 'Техническая поддержка 24/7'),
        ('Швидка доставка по Україні' if lang == 'ua' else 'Быстрая доставка по Украине'),
    ]
    adv = ''.join(
        f'<div style="background:#1A2128;border:1px solid #35393F;border-radius:22px;padding:26px;text-align:center;color:#FFFFFF;font-weight:900;font-size:17px">{a}</div>'
        for a in advantages)
    return f'''<!doctype html>
<html lang="{'uk' if lang == 'ua' else 'ru'}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title></head>
<body style="margin:0;background:#F5F7FA;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif">
<section style="max-width:1240px;margin:0 auto;padding:14px;box-sizing:border-box">
<div style="background:linear-gradient(135deg,#101010,#1A2128);border:1px solid #35393F;border-radius:32px;padding:64px 28px;text-align:center">
{f'<div style="display:inline-block;background:rgba(25,188,201,.12);border:1px solid #19BCC9;color:#C9F0F4;padding:9px 16px;border-radius:999px;font-weight:900;font-size:13px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:18px">{_chunk(campaign, "period")}</div>' if campaign.get('period') else ''}
<h1 style="margin:0 0 12px;font-size:52px;line-height:1.02;font-weight:950;color:#FFFFFF">{title}</h1>
{f'<p style="margin:0;color:#C9F0F4;font-weight:700;font-size:20px">{_chunk(campaign, "campaign_subtitle")}</p>' if campaign.get('campaign_subtitle') else ''}
</div>
<div style="margin-top:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px">{''.join(cards)}</div>
<div style="margin:18px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px">{adv}</div>
</section>
</body></html>'''


LANDING_PROMPT = r'''Create a COMPLETE standalone promo landing page (single HTML document) for the artline.ua campaign below. It is a promotional sale page listing several products with prices and buy buttons, like artline.ua/solution pages.

STRICT RULES
- Output ONE full HTML document: <!doctype html><html><head>...<body>. No markdown, no code fences, no commentary.
- Inline CSS on elements. ONE <style> block in <head> is allowed ONLY for media queries and keyframes; it must not contain url() or @import.
- No scripts, forms, buttons (use <a> styled as buttons), iframes, external CSS.
- Use ONLY the product data in PRODUCTS JSON: exact names, exact price_text, exact image URLs, exact product URLs. NEVER invent a product, price or URL. If price_text is empty, omit the price line for that product.
- Every product card links its image, name and buy CTA to the product url.
- Language of ALL copy: {LANGUAGE}. Buy button: «Купити» (ua) / «Купить» (ru).

DESIGN SYSTEM (ARTLINE)
- Canvas #F5F7FA; dark surfaces #101010/#1A2128 border #35393F; light cards #FFFFFF border #D0D7DE; accent cyan #19BCC9 (dark) / #157985 (light). Radii: sections 28-32px, cards 18-22px, chips/buttons 999px. Heavy weights: h1/h2 950, prices 950.
- Page structure, in order:
  1. PROMO HERO - dark gradient section: period chip (if given), huge campaign title, subtitle. Centered.
  2. PRODUCT GRID - responsive grid of white cards: white image slot (fixed height, img object-fit:contain, never cropped), product name, price (old-style big 950; if the name suggests Refurbished/discount you still only show given price_text), cyan pill CTA «{BUY}» linking to the product url.
  3. ADVANTAGES - three dark cards with short confident claims (official warranty, support, delivery) - no invented specifics, no numbers not present in data.
- Mobile-friendly: grid uses repeat(auto-fit,minmax(240px,1fr)); hero title scales down via the media-query <style> block.
- Wrap each of the three sections in comments: <!-- LANDING BLOCK 01: HERO START --> ... END, 02: PRODUCTS, 03: ADVANTAGES.

CAMPAIGN
{CAMPAIGN}

PRODUCTS JSON
{PRODUCTS}
'''


def build_landing_prompt(campaign: dict, products: list[dict]) -> str:
    lang = campaign.get('language') or 'ua'
    safe_products = [{k: p.get(k, '') for k in ('name', 'price_text', 'image', 'url')} for p in products]
    return (LANDING_PROMPT
            .replace('{LANGUAGE}', 'українська' if lang == 'ua' else 'русский')
            .replace('{BUY}', 'Купити' if lang == 'ua' else 'Купить')
            .replace('{CAMPAIGN}', json.dumps({
                'title': campaign.get('campaign_title') or campaign.get('name') or '',
                'subtitle': campaign.get('campaign_subtitle') or '',
                'period': campaign.get('period') or '',
            }, ensure_ascii=False))
            .replace('{PRODUCTS}', json.dumps(safe_products, ensure_ascii=False)))


def generate_landing_html(campaign: dict, products: list[dict], model: str):
    """(html, input_tokens, output_tokens, fallback_reason). Ніколи не кидає:
    відмова AI -> детермінований шаблон, гроші за токени не втрачаються."""
    from app.pipeline import _responses_create, _usage_counts, public_fallback_reason
    fallback = deterministic_landing(campaign, products)
    try:
        prompt = build_landing_prompt(campaign, products)
        response = _responses_create(model, prompt, 16000)
        raw = response.output_text or ''
        match = re.search(r'<!doctype html.*</html>', raw, re.I | re.S) or re.search(r'<html.*</html>', raw, re.I | re.S)
        if not match:
            raise RuntimeError('AI did not return a complete HTML document')
        html = sanitize_landing_html(match.group(0))
        # Жодного вигаданого товарного посилання: кожен href/src або з проб, або відносний.
        allowed = {p.get('url') for p in products} | {p.get('image') for p in products}
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.find_all(['a', 'img']):
            attr = 'href' if tag.name == 'a' else 'src'
            value = tag.get(attr) or ''
            if value.startswith(('http://', 'https://')) and value not in allowed and not is_public_http_url(value):
                del tag[attr]
        html = str(soup)
        input_tokens, output_tokens = _usage_counts(response, prompt, raw)
        return html, input_tokens, output_tokens, ''
    except Exception as exc:
        logger.exception('generate_landing_html fell back to deterministic template')
        return fallback, 0, 0, public_fallback_reason(exc)
