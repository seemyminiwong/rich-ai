"""Перевірки, які мовчали на живій сторінці ARTLINE Master (ASUS Ascent GX10, RU, 2026-10-26).

Там були українські alt на російській сторінці, ті самі розміри й вага в чотирьох
блоках, хвіст «, что обеспечивает…», артикул у плитці значень і «Gray» без перекладу.
"""
from app.seo_geo import audit_human_copy, audit_language_quality, audit_rich_fragment, audit_value_tiles

PRODUCT = {'name': 'ASUS Ascent GX10-GG0027BN', 'brand': 'ASUS', 'model': 'GX10-GG0027BN', 'category': 'Мини-ПК'}
TILE = '<div style="font-size:26px;line-height:1.15;font-weight:900;color:#157985">{}</div>'


def _codes(findings):
    return [f['code'] for f in findings]


def _page(*blocks):
    return '<section>' + ''.join(f'<div>{b}</div>' for b in blocks) + '</section>'


def test_alt_in_other_cyrillic_language_is_flagged():
    ru_page = _page('<h2>ASUS Ascent GX10</h2><img src="/a.webp" alt="ASUS Ascent GX10 задні порти підключення">')
    assert 'alt_language' in _codes(audit_rich_fragment(ru_page, PRODUCT, 'ru'))
    uk_page = _page('<h2>ASUS Ascent GX10</h2><img src="/a.webp" alt="ASUS Ascent GX10 на тёмном фоне">')
    assert 'alt_language' in _codes(audit_rich_fragment(uk_page, PRODUCT, 'uk'))
    same = _page('<h2>ASUS Ascent GX10</h2><img src="/a.webp" alt="ASUS Ascent GX10 задние порты подключения">')
    assert 'alt_language' not in _codes(audit_rich_fragment(same, PRODUCT, 'ru'))


def test_value_repeated_in_many_blocks_is_flagged():
    weight = '<p>Устройство весит 1.6 кг и помещается на столе рядом с монитором.</p>'
    four = _page(*(f'<h2>Блок {i}</h2>{weight}' for i in range(4)))
    found = [f for f in audit_rich_fragment(four, PRODUCT, 'ru') if f['code'] == 'fact_repeated']
    assert found and '1.6 кг' in found[0]['message'] and '4 блоках' in found[0]['message']
    # Hero, параметри і FAQ з тим самим значенням - норма
    three = _page(*(f'<h2>Блок {i}</h2>{weight}' for i in range(3)))
    assert 'fact_repeated' not in _codes(audit_rich_fragment(three, PRODUCT, 'ru'))


def test_relative_trailing_clause_is_an_ai_pattern():
    page = _page('<h2>Память</h2><p>Память 128 ГБ работает с накопителем 4 ТБ, что обеспечивает быстрый запуск системы.</p>')
    found = [f for f in audit_human_copy(page, 'ru', product=PRODUCT) if f['code'] == 'ai_pattern']
    assert found and 'что обеспечивает' in found[0]['evidence']
    uk = _page('<h2>Пам\'ять</h2><p>Пам\'ять 128 ГБ працює з накопичувачем 4 ТБ, що забезпечує швидкий запуск.</p>')
    assert 'ai_pattern' in _codes(audit_human_copy(uk, 'uk', product=PRODUCT))


def test_part_number_in_value_tile():
    page = _page('<h2>Комплект</h2>' + TILE.format('90MS0371-M000V0') + TILE.format('12 мес.'))
    assert _codes(audit_value_tiles(page, PRODUCT, 'ru')) == ['tile_part_number']
    # модель товару в плитці і звичайні значення - не артикул
    fine = _page('<h2>Модель</h2>' + TILE.format('GX10-GG0027BN') + TILE.format('LPDDR5x') + TILE.format('Wi‑Fi 802.11be'))
    assert audit_value_tiles(fine, PRODUCT, 'ru') == []


def test_untranslated_color_word():
    page = _page('<h2>Корпус</h2>' + TILE.format('Gray') + '<p>Цвет корпуса</p>')
    found = [f for f in audit_language_quality(page, 'ru', product=PRODUCT) if f['code'] == 'untranslated_word']
    assert found and 'Gray' in found[0]['message']
    # колір, що входить в офіційну назву товару, дозволений
    named = {**PRODUCT, 'name': 'Ноутбук Apple MacBook Air 13 Space Gray'}
    assert 'untranslated_word' not in _codes(audit_language_quality(page, 'ru', product=named))
    # польське «no» і латиниця брендів не чіпаються
    pl = _page('<h2>Obudowa</h2><p>No i najważniejsze: obudowa ASUS waży 1,48 kg.</p>')
    assert 'untranslated_word' not in _codes(audit_language_quality(pl, 'pl', product=PRODUCT))
