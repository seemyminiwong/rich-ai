"""Категорія товару: зразки хлібних крихт із живих сторінок artline.ua (2026-10-01)."""
import json

from app.category import (
    fix_homoglyphs, is_product_crumb, normalize_label, resolve_category, shop_category, ukrainian_url,
)


def _page(crumbs, lang='uk', name='', alternates=None):
    items = [{'@type': 'ListItem', 'position': i + 1, 'name': c} for i, c in enumerate(crumbs)]
    product = {'@context': 'https://schema.org', '@type': 'Product', 'name': name} if name else None
    links = ''.join(f'<link rel="alternate" href="{u}" hreflang="{h}"/>' for h, u in (alternates or {}).items())
    scripts = f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}, ensure_ascii=False)}</script>'
    if product:
        scripts += f'<script type="application/ld+json">{json.dumps(product, ensure_ascii=False)}</script>'
    return f'<html lang="{lang}"><head>{links}{scripts}</head><body></body></html>'


POCKET_NAME = 'Зовнішня кишеня Gembird 2.5&quot; USB3.0 Red (EE2-U3S-2-R)'
# Так крихти віддає artline.ua: латинська «i» замість «і» і неекранований &quot;
POCKET_UK = _page(['Головна', 'Комплектуючi', 'Додатковi аксесуари', 'Зовнiшня кишеня Gembird 2.5&quot; USB3.0 Red (EE2-U3S-2-R)'], name=POCKET_NAME)
CASE_URL_RU = 'https://artline.ua/product/korpus-asus-rog-cronox-gr801-argb-white-90dc00t3-b09030'
CASE_URL_UK = 'https://artline.ua/uk/product/korpus-asus-rog-cronox-gr801-argb-white-90dc00t3-b09030'
CASE_NAME = 'Корпус ASUS ROG Cronox GR801 ARGB White (90DC00T3-B09030)'
CASE_RU = _page(['Главная', 'Комплектующие', 'Корпуса для ПК', CASE_NAME], lang='ru', name=CASE_NAME,
                alternates={'uk-UA': CASE_URL_UK, 'ru-UA': CASE_URL_RU})
CASE_UK = _page(['Головна', 'Комплектуючi', 'Корпуси для ПК', CASE_NAME], name=CASE_NAME,
                alternates={'uk-UA': CASE_URL_UK, 'ru-UA': CASE_URL_RU})


def test_homoglyphs_and_entities_are_normalized_only_inside_cyrillic_words():
    assert fix_homoglyphs('Комплектуючi') == 'Комплектуючі'
    assert fix_homoglyphs('Зовнiшня кишеня ASUS USB3.0') == 'Зовнішня кишеня ASUS USB3.0'
    assert normalize_label('Gembird 2.5&quot; USB3.0') == 'Gembird 2.5" USB3.0'
    assert normalize_label('2.5&amp;quot;') == '2.5"'


def test_the_product_crumb_is_never_a_category():
    crumb = 'Зовнiшня кишеня Gembird 2.5&quot; USB3.0 Red (EE2-U3S-2-R)'
    assert is_product_crumb(crumb, POCKET_NAME)
    assert is_product_crumb('Корпус ASUS ROG Cronox GR801 ARGB White', CASE_NAME)  # без коду в дужках
    assert not is_product_crumb('Корпуси для ПК', CASE_NAME)
    assert shop_category(POCKET_UK, POCKET_NAME) == 'Додаткові аксесуари'


def test_generic_shop_section_falls_back_to_the_product_type():
    r = resolve_category(POCKET_UK, 'https://artline.ua/uk/product/vneshniy-karman', POCKET_NAME)
    assert r['category'] == 'Зовнішня кишеня' and r['shop_category'] == 'Додаткові аксесуари'
    assert r['source'] == 'breadcrumbs+type'


def test_russian_page_takes_the_category_from_its_ukrainian_version():
    assert ukrainian_url(CASE_RU, CASE_URL_RU) == CASE_URL_UK
    assert ukrainian_url(CASE_UK, CASE_URL_UK) == ''
    assert ukrainian_url('<html lang="ru"></html>', 'https://artline.ua/product/x') == 'https://artline.ua/uk/product/x'
    calls = []

    def fetch(url):
        calls.append(url)
        return CASE_UK

    r = resolve_category(CASE_RU, CASE_URL_RU, CASE_NAME, fetch=fetch)
    assert calls == [CASE_URL_UK] and r['category'] == 'Корпуси для ПК' and r['source'] == 'breadcrumbs_uk'
    # Ukrainian page: no extra request
    assert resolve_category(CASE_UK, CASE_URL_UK, CASE_NAME, fetch=lambda u: (_ for _ in ()).throw(AssertionError(u)))['category'] == 'Корпуси для ПК'
    # Ukrainian version unavailable: keep what the page has, never crash
    r = resolve_category(CASE_RU, CASE_URL_RU, CASE_NAME, fetch=lambda u: (_ for _ in ()).throw(OSError('timeout')))
    assert r['category'] == 'Корпуса для ПК'


def test_russian_page_product_type_comes_from_the_ukrainian_name():
    ru_name = 'Внешний карман Gembird 2.5&quot; USB3.0 Red (EE2-U3S-2-R)'
    ru = _page(['Главная', 'Комплектующие', 'Дополнительные аксессуары', ru_name], lang='ru', name=ru_name)
    r = resolve_category(ru, 'https://artline.ua/product/vneshniy-karman', ru_name, fetch=lambda u: POCKET_UK)
    assert r['category'] == 'Зовнішня кишеня' and r['shop_category'] == 'Додаткові аксесуари'


def test_no_breadcrumbs_falls_back_to_meta_then_name():
    bare = '<html lang="uk"><head></head><body></body></html>'
    assert resolve_category(bare, 'https://shop.example/p', 'Монітор Qube Overlord G27Q300H', meta_category='Монітори')['category'] == 'Монітори'
    r = resolve_category(bare, 'https://shop.example/p', 'Монітор Qube Overlord G27Q300H')
    assert r['category'] == 'Монітор' and r['source'] == 'name'


def test_apply_category_updates_product_and_provenance():
    from app.tasks import apply_category
    product = {'name': CASE_NAME, 'category': 'Корпуса для ПК',
               'evidence': [{'id': 'identity_category', 'value': 'Корпуса для ПК', 'source_type': 'page_text', 'confidence': 'derived', 'evidence': ''}]}
    assert apply_category(product, CASE_RU, CASE_URL_RU, fetch=lambda u: CASE_UK) == 'Корпуси для ПК'
    assert product['category'] == 'Корпуси для ПК' and product['shop_category'] == 'Корпуси для ПК' and product['product_type'] == 'Корпус'
    item = product['evidence'][0]
    assert item['value'] == 'Корпуси для ПК' and item['source_type'] == 'breadcrumbs' and item['confidence'] == 'confirmed'
    assert 'Корпуси для ПК' in item['evidence']
