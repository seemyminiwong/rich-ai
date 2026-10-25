"""ASUS і всі його напрямки мають фірмову палітру, а суббренд впізнається з назви товару."""
from app.brand_detect import SUBBRAND_ALIASES, detect_brand
from app.brand_palettes import BRAND_ACCENTS

ASUS_LINES = ('ASUS', 'ASUS ROG', 'ASUS TUF Gaming', 'ASUS ProArt', 'ASUS Zenbook', 'ASUS Vivobook',
              'ASUS ExpertBook', 'ASUS Prime', 'ASUS ZenWiFi', 'ASUS NUC')
KNOWN = ['ARTLINE Cyan'] + [b for b, _ in BRAND_ACCENTS]


def test_every_asus_line_has_a_palette():
    brands = dict(BRAND_ACCENTS)
    for line in ASUS_LINES:
        assert line in brands, line
    assert brands['ASUS'] == '#006CE1' and brands['ASUS ROG'] == '#E4002B'
    assert brands['ASUS TUF Gaming'] == '#FF9E1B' and brands['ASUS ProArt'] == '#CDAB82'
    assert set(SUBBRAND_ALIASES) <= set(brands), 'псевдонім веде лише до наявного пресета'


def test_asus_subbrand_is_detected_from_product_name():
    cases = {
        'Ноутбук ASUS TUF Gaming A15 FA507NV': 'ASUS TUF Gaming',
        'Відеокарта ASUS TUF-RTX4070TI-O12G-GAMING': 'ASUS TUF Gaming',
        'Монітор Asus ProArt PA278QV': 'ASUS ProArt',
        'Ноутбук ASUS Zenbook 14 OLED UX3405MA': 'ASUS Zenbook',
        'Ноутбук Asus VivoBook 15 X1504ZA': 'ASUS Vivobook',
        'Ноутбук ASUS ExpertBook B1 B1502CVA': 'ASUS ExpertBook',
        'Материнська плата ASUS PRIME B650-PLUS': 'ASUS Prime',
        'Mesh-система ASUS ZenWiFi BT10 (2-pack)': 'ASUS ZenWiFi',
        'Неттоп ASUS NUC 14 Pro': 'ASUS NUC',
        'Зовнішня кишеня Asus ROG Strix Arion White': 'ASUS ROG',
        'Роутер ASUS RT-AX58U': 'ASUS',
    }
    for name, preset in cases.items():
        assert detect_brand(KNOWN, name=name)['preset'] == preset, name


def test_subbrand_without_manufacturer_in_name():
    # магазин пише бренд у JSON-LD, а в назві лише лінійку
    r = detect_brand(KNOWN, jsonld={'brand': 'ASUS'}, name='Ноутбук ROG Zephyrus G14 GA403UV')
    assert r['preset'] == 'ASUS ROG' and r['brand'] == 'ASUS'
    # суббренд після моделі, а не одразу за «ASUS»
    assert detect_brand(KNOWN, name='Монітор ASUS 27" TUF Gaming VG27AQ3A')['preset'] == 'ASUS TUF Gaming'
    # бренд у JSON-LD - сама лінійка
    assert detect_brand(KNOWN, jsonld={'brand': 'ROG'}, name='Гарнітура Delta S')['preset'] == 'ASUS ROG'
    # «Prime» і «NUC» без ASUS - не суббренд
    assert detect_brand(KNOWN, name='Intel NUC 11 Essential')['preset'] == 'Intel'
    assert detect_brand(KNOWN, name='Подовжувач Prime 5 розеток')['preset'] is None
