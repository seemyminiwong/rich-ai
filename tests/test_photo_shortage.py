"""Мало фото для річа: без порожніх блоків (запит власника 2026-10-09).

Коли кадрів галереї не вистачає, модель або вигадує URL (сервер його вирізає),
або повторює кадр, або малює порожню рамку. Раніше на сторінці лишались білі
картки й половини сітки без нічого. Тепер промпт знає точний бюджет фото, а
сервер прибирає повтори, порожні рамки і стискає осиротілі колонки.
"""
import re
from pathlib import Path
from types import SimpleNamespace

from app.photo_slots import drop_empty_photo_slots, photo_budget_line

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = {'name': 'QUBE Overlord G25F240S', 'brand': 'QUBE', 'features': ['240 Гц'], 'specs': {'Діагональ': '24.5″'}}
GALLERY_STYLE = SimpleNamespace(prompt='STYLE uses GALLERY_IMAGES frames', hero_prompt='', feature_prompt='',
                                negative_prompt='', golden_html='', name='X')


def _imgs(markup: str) -> list[str]:
    return re.findall(r'<img[^>]*src="([^"]+)"', markup)


# --- промпт -----------------------------------------------------------------

def test_budget_line_states_the_exact_number_of_photos_and_the_fallback():
    line = photo_budget_line('/h.webp', '/f.webp', ['/g1.webp'])
    assert 'PHOTO BUDGET' in line and '3 distinct images' in line and '1 GALLERY_IMAGES frame' in line
    assert 'at most once' in line and 'text-only' in line and 'empty frame' in line


def test_budget_line_without_gallery_forbids_gallery_slots():
    line = photo_budget_line('/h.webp', '/f.webp', [])
    assert '2 distinct images' in line and 'no GALLERY_IMAGES frames' in line


def test_budget_line_reaches_every_prompt():
    from app.pipeline import build_prompt
    with_gallery = build_prompt(PRODUCT, GALLERY_STYLE, 'ua', 'desktop', '/h', '/f', gallery=['/g1', '/g2'])
    assert 'PHOTO BUDGET: 4 distinct images' in with_gallery and '2 GALLERY_IMAGES frames' in with_gallery
    plain = SimpleNamespace(prompt='STYLE', hero_prompt='', feature_prompt='', negative_prompt='', golden_html='', name='Y')
    assert 'PHOTO BUDGET: 2 distinct images' in build_prompt(PRODUCT, plain, 'ua', 'desktop', '/h', '/f')


# --- сервер: порожні рамки --------------------------------------------------

SPLIT_WITHOUT_PHOTO = (
    '<section><div style="display:grid;grid-template-columns:.92fr 1.08fr;gap:28px;padding:44px">'
    '<div><h2>ЯСКРАВІСТЬ</h2><p>400 кд/м² для денного світла.</p></div>'
    '<div style="background:#FFFFFF;border:1px solid #D0D7DE;border-radius:12px;padding:16px;height:420px">'
    '<div style="height:100%"></div></div>'
    '</div></section>')


def test_empty_photo_frame_is_removed_and_the_split_becomes_one_column():
    out = drop_empty_photo_slots(SPLIT_WITHOUT_PHOTO)
    assert 'height:420px' not in out and 'ЯСКРАВІСТЬ' in out and '400 кд/м²' in out
    grid = re.search(r'<div style="([^"]*display:grid[^"]*)"', out).group(1)
    assert 'grid-template-columns:minmax(0,1fr)' in grid


def test_invented_url_without_spare_leaves_no_empty_card():
    from app.pipeline import _enforce_image_whitelist
    page = SPLIT_WITHOUT_PHOTO.replace('<div style="height:100%"></div>', '<img src="https://invented.example/x.jpg" alt="x" style="width:100%;height:100%">')
    out = drop_empty_photo_slots(_enforce_image_whitelist(page, ['/h', '/f'], spares=[]))
    assert 'invented' not in out and 'height:420px' not in out and 'ЯСКРАВІСТЬ' in out


def test_repeated_gallery_photo_is_dropped_with_its_frame():
    card = '<div style="background:#FFFFFF;padding:16px;min-height:240px"><img src="/g1.webp" alt="a"></div>'
    page = ('<section><div style="display:grid;grid-template-columns:1fr 1fr"><div><p>Перша перевага.</p></div>' + card + '</div>'
            '<div style="display:grid;grid-template-columns:1fr 1fr"><div><p>Друга перевага.</p></div>' + card + '</div></section>')
    out = drop_empty_photo_slots(page)
    assert _imgs(out) == ['/g1.webp']
    assert out.count('min-height:240px') == 1 and 'Друга перевага.' in out
    assert out.count('grid-template-columns:minmax(0,1fr)') == 1


def test_trio_card_keeps_its_text_when_the_photo_slot_is_empty():
    card = ('<div style="display:flex;flex-direction:column;height:100%;background:#F5F7FA">'
            '<div style="background:#FFFFFF;height:250px;padding:18px"></div><h3>{t}</h3><p>Текст.</p></div>')
    page = ('<section><div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px">'
            + ''.join(card.format(t=t) for t in ('Перша', 'Друга', 'Третя')) + '</div></section>')
    out = drop_empty_photo_slots(page)
    assert 'height:250px' not in out and all(t in out for t in ('Перша', 'Друга', 'Третя'))
    assert 'repeat(3,minmax(0,1fr))' in out  # три картки - три колонки лишаються


def test_grid_with_fewer_cards_than_columns_is_resized():
    page = ('<section><div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr))">'
            '<div><h3>А</h3></div><div><h3>Б</h3></div><div style="height:250px;background:#fff"></div></div></section>')
    out = drop_empty_photo_slots(page)
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in out


def test_decorations_and_real_media_are_kept():
    page = ('<section>'
            '<div style="position:relative;min-height:585px;background:#101010 url(/h.webp) center/cover">'
            '<img src="/h.webp" alt="h" style="position:absolute;inset:0">'
            '<div style="position:absolute;inset:0;background:linear-gradient(90deg,#101010,transparent)"></div>'
            '<div style="position:relative;z-index:1"><h2>QUBE</h2></div></div>'
            '<div style="height:1px;background:#D0D7DE"></div>'
            '<div style="display:grid;grid-template-columns:1fr 1fr"><div><p>Текст</p></div>'
            '<div style="height:300px;background:#F5F7FA url(/scene.webp) center/cover"></div></div>'
            '<div style="display:grid;grid-template-columns:1fr 1fr"><div><p>А</p></div><div><p>Б</p></div>'
            '<div style="grid-column:1/-1;border-top:1px solid #D0D7DE"></div></div>'
            '<span style="display:inline-flex;gap:6px"><span style="width:8px;height:8px;border-radius:50%;background:#19BCC9"></span>LIVE</span>'
            '</section>')
    assert drop_empty_photo_slots(page) == page


def test_cleanup_is_idempotent_and_leaves_complete_pages_alone():
    from app.pipeline import _deterministic_html
    style = SimpleNamespace(prompt='STYLE', name='X')
    for variant in ('desktop', 'mobile'):
        page = _deterministic_html(PRODUCT, style, 'ua', variant, '/h.webp', '/f.webp')
        assert drop_empty_photo_slots(page) == page
    promo = (ROOT / 'promo/asus-ai.html').read_text(encoding='utf-8')
    assert drop_empty_photo_slots(promo) == promo
    once = drop_empty_photo_slots(SPLIT_WITHOUT_PHOTO)
    assert drop_empty_photo_slots(once) == once


def test_cleanup_runs_after_generation_and_on_restyle():
    pipeline = (ROOT / 'apps/api/app/pipeline.py').read_text(encoding='utf-8')
    gen = pipeline[pipeline.index('def generate_html('):]
    assert gen.index('_enforce_image_whitelist(output') < gen.index('drop_empty_photo_slots(output') < gen.index('_fit_photo_cards(output')
    main = (ROOT / 'apps/api/app/main.py').read_text(encoding='utf-8')
    restyle = main[main.index("def project_restyle"):main.index("def project_restyle") + 2500]
    assert 'drop_empty_photo_slots(' in restyle


# --- рев'ю: легітимні елементи не чіпаються (кейси ecc:python-reviewer) -------------

KEEP_AS_IS = {
    'zig-zag spacers': '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px"><div><h3>A</h3></div><div></div><div></div><div><h3>B</h3></div></div>',
    'timeline line cells': ('<div style="display:grid;grid-template-columns:1fr 40px 1fr"><div><h3>A</h3></div><div style="width:2px;background:#ccc"></div>'
                            '<div></div><div></div><div style="width:2px;background:#ccc"></div><div><h3>B</h3></div></div>'),
    'explicit column placement': '<div style="display:grid;grid-template-columns:1fr 1fr 1fr"><p style="grid-column:3">a</p><div style="height:200px;background:#eee"></div></div>',
    'grid areas': "<div style=\"display:grid;grid-template-columns:1fr 1fr;grid-template-areas:'a b'\"><div style=\"grid-area:a;height:200px\"></div><div style=\"grid-area:b\"><p>t</p></div></div>",
    'vertical divider': '<div style="display:flex;gap:24px"><p>a</p><div style="width:1px;height:120px;background:#ddd"></div><p>b</p></div>',
    'bar chart bar': '<div style="display:flex;align-items:flex-end"><div style="width:40px;height:140px;background:#2563eb"></div><p>40</p></div>',
    'gradient band': '<div><p>t</p><div style="height:160px;background:linear-gradient(90deg,#111,#444)"></div></div>',
    'colour swatch': '<div><p>Колір</p><div style="width:120px;height:120px;background:#f00"></div></div>',
    'spacer': '<div><p>t</p><div style="height:120px"></div></div>',
    'aspect swatch': '<div><p>t</p><div style="aspect-ratio:1;background:#f00;border-radius:50%"></div></div>',
    'left divider cell': '<div style="display:grid;grid-template-columns:1fr 1px 1fr"><p>a</p><div style="border-left:1px solid #ccc"></div><p>b</p></div>',
    'controls': '<div><div style="height:120px;border:1px solid #ccc"><input type="text"></div><div style="height:120px;border:1px solid #ccc"><hr></div></div>',
    'icon font': '<div style="display:grid;grid-template-columns:1fr 1fr"><p>a</p><div style="height:120px;border:1px solid #ccc"><i class="fa fa-check"></i></div></div>',
    'repeated rem icons': '<ul><li><img src="/m/check.png" style="width:1.5rem;height:1.5rem"> A</li><li><img src="/m/check.png" style="width:1.5rem;height:1.5rem"> B</li></ul>',
    'repeated inline svg icons': '<div><p><img src="/m/ic.svg"> A</p><p><img src="/m/ic.svg"> B</p></div>',
    'style kept': '<section><div><style>.x{color:red}</style><p>t</p></div></section>',
    'clamp tracks': '<div style="display:grid;grid-template-columns:clamp(200px,30%,320px) 1fr"><p>a</p><p>b</p></div>',
}


def test_reviewer_cases_are_left_untouched():
    for name, page in KEEP_AS_IS.items():
        markup = f'<section>{page}</section>'
        assert drop_empty_photo_slots(markup) == markup, name


def test_full_width_heading_does_not_block_the_reshape():
    page = ('<section><div style="display:grid;grid-template-columns:repeat(3,1fr)"><h2 style="grid-column:1/-1">T</h2>'
            '<div><p>a</p></div><div><p>b</p></div><div style="height:200px;background:#FFFFFF;border:1px solid #D0D7DE"></div></div></section>')
    out = drop_empty_photo_slots(page)
    assert 'height:200px' not in out and 'grid-template-columns:repeat(2,minmax(0,1fr))' in out


def test_repeated_photo_in_figure_or_picture_goes_with_its_wrapper():
    page = ('<section><div><p>a</p><figure><img src="/g1.webp" alt="1"><figcaption>c1</figcaption></figure></div>'
            '<div><p>b</p><figure><img src="/g1.webp" alt="2"><figcaption>c2</figcaption></figure></div>'
            '<div><p>c</p><picture><source srcset="/g1.avif"><img src="/g1.webp" alt="3"></picture></div></section>')
    out = drop_empty_photo_slots(page)
    assert _imgs(out) == ['/g1.webp'] and 'c2' not in out and '<picture' not in out and 'c1' in out


def test_twelve_rem_track_list_is_counted():
    page = ('<section><div style="display:grid;grid-template-columns:12rem 1fr 1fr"><div><p>a</p></div><div><p>b</p></div>'
            '<div style="min-height:200px;background:#FFFFFF;border-radius:12px"></div></div></section>')
    assert 'repeat(2,minmax(0,1fr))' in drop_empty_photo_slots(page)
