"""ARTLINE Master v2: вигляд, схвалений контент-відділом (запит власника 2026-10-09).

Зразки відділу (artline.ua: BLUETTI Premium 200 V2, Deye SUN-10K, Solarverse,
Logitech ERGO K860, Logitech MX Keys) мають одну анатомію блоку: eyebrow, h2
великими, акцентний підзаголовок, два абзаци і плитки значень; Hero несе рядок
ключових значень і три плитки; ключові параметри - 4-6 плиток в один ряд; два
пов'язані технічні теми - світла й темна панелі поруч. Тут закріплено, що промпт
про це просить і що серверна обробка майстра ці компоненти не ламає.
"""
import re
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from app import pipeline
from app.prompts import MASTER_STYLE_PROMPT

EYEBROW = ('display:inline-flex;align-items:center;width:fit-content;max-width:100%;margin:0 0 14px;padding:6px 12px;'
           'border-radius:8px;font-size:12px;line-height:1.3;font-weight:900;letter-spacing:.08em;text-transform:uppercase;'
           'user-select:none;-webkit-user-select:none;box-sizing:border-box;')


def test_prompt_describes_the_approved_block_anatomy():
    for marker in ('v2.0', 'COMPONENTS', 'EYEBROW', 'HEADING GROUP', 'VALUE TILE ROW', 'HERO TILE ROW', 'TWIN PANELS',
                   'ACCENT SUBTITLE', 'DEPTH', 'together 50-90 words', '4-6 tiles in a single row', 'exactly three tiles'):
        assert marker in MASTER_STYLE_PROMPT, marker
    # Рішення власника лишаються: 14px, бейджі 8px, вага не вище 900, без пігулок.
    assert 'outer blocks 14px' in MASTER_STYLE_PROMPT and 'chips 8px' in MASTER_STYLE_PROMPT
    assert 'Never use 950' in MASTER_STYLE_PROMPT and 'border-radius:999px' not in MASTER_STYLE_PROMPT
    # Кожен блок 03-08 відкривається eyebrow, кожен h2 має акцентний підзаголовок.
    check = MASTER_STYLE_PROMPT.split('FINAL SELF-CHECK', 1)[1]
    assert 'blocks 03-08 open with an eyebrow' in check and 'every h2 has its accent subtitle' in check


def _tile(value, caption, size=26):
    return (f'<div style="border-radius:12px;padding:16px 14px;background:#FFFFFF;border:1px solid #D0D7DE;box-sizing:border-box;min-width:0;">'
            f'<div style="font-size:{size}px;line-height:1.15;font-weight:900;color:#157985;">{value}</div>'
            f'<div style="margin-top:6px;font-size:14px;line-height:1.4;color:#555555;">{caption}</div></div>')


PAGE = (
    '<section style="width:100%;margin:0;padding:0;font-family:\'Montserrat\',\'Segoe UI\',Arial,sans-serif;color:#101010;box-sizing:border-box;">'
    '<!-- Блок 1. Hero START --><div style="position:relative;overflow:hidden;border-radius:14px;border:1px solid #35393F;background:#101010 url(/media/p/hero-desktop.webp) center/cover no-repeat;">'
    '<img src="/media/p/hero-desktop.webp" alt="Станція" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;">'
    '<div style="position:absolute;inset:0;background:linear-gradient(90deg,rgba(16,16,16,.92) 0%,rgba(16,16,16,0) 100%);"></div>'
    '<div style="position:relative;z-index:1;min-height:585px;padding:72px 46px 54px;display:flex;align-items:center;box-sizing:border-box;">'
    '<div style="width:56%;min-width:0;">'
    f'<span style="{EYEBROW}color:#19BCC9;background:rgba(25,188,201,.10);border:1px solid rgba(25,188,201,.35);">BLUETTI · Станція</span>'
    '<h2 style="font-size:30px;font-weight:900;color:#FFFFFF;">BLUETTI Premium 200 V2</h2>'
    '<h3 style="font-size:18px;font-weight:800;color:#19BCC9;">2700 Вт · 2073.6 Вт·год · LiFePO4</h3>'
    '<p style="font-size:16px;color:#D8DDE2;">Станція для дому й поїздок.</p>'
    '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:24px;">'
    + ''.join(_tile(v, c, 18) for v, c in (('2073.6 Вт·год', 'ємність'), ('2700 Вт', 'потужність'), ('15 мс', 'UPS'))) +
    '</div></div></div></div><!-- Блок 1. Hero END -->'
    '<!-- Блок 2. Ключові характеристики START --><div style="margin-top:22px;border-radius:14px;padding:40px;background:#F5F7FA;">'
    '<h2 style="font-size:24px;font-weight:900;text-align:center;">КЛЮЧОВІ ПАРАМЕТРИ</h2>'
    '<h3 style="font-size:18px;font-weight:800;color:#157985;text-align:center;">Портативна станція LiFePO4</h3>'
    '<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:22px;">'
    + ''.join(_tile(v, c) for v, c in (('2300 Вт', 'вхід AC'), ('2400 Вт', 'AC + DC'), ('6000+', 'циклів'), ('24.2 кг', 'маса'), ('7', 'виходів'))) +
    '</div></div><!-- Блок 2. Ключові характеристики END -->'
    '<!-- Блок 5. Сумісність і обмеження START --><div style="margin-top:22px;border-radius:14px;padding:40px;background:#F5F7FA;">'
    '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:stretch;">'
    f'<div style="border-radius:12px;padding:30px 28px;background:#FFFFFF;border:1px solid #D0D7DE;"><div style="margin:0;"><span style="{EYEBROW}color:#157985;background:#F5F7FA;border:1px solid #D0D7DE;">Батарея</span></div>'
    '<h3 style="font-size:18px;font-weight:900;text-transform:uppercase;">Ресурс</h3><p style="font-size:16px;color:#555555;">AI-BMS контролює стан.</p>'
    '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;">' + _tile('AI-BMS', 'контроль') + _tile('ABS', 'корпус') + '</div></div>'
    f'<div style="border-radius:12px;padding:30px 28px;background:#1A2128;border:1px solid #35393F;"><div style="margin:0;"><span style="{EYEBROW}color:#19BCC9;background:rgba(25,188,201,.10);border:1px solid rgba(25,188,201,.35);">Керування</span></div>'
    '<h3 style="font-size:18px;font-weight:900;text-transform:uppercase;color:#FFFFFF;">Застосунок</h3><p style="font-size:16px;color:#D8DDE2;">Wi-Fi і Bluetooth.</p>'
    '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;">' + _tile('Wi-Fi', 'віддалено') + _tile('Bluetooth', 'поруч') + '</div></div>'
    '</div></div><!-- Блок 5. Сумісність і обмеження END -->'
    '<!-- Блок 9. FAQ START --><!-- ARTLINE FAQ BLOCK START --><div style="margin-top:22px;border-radius:14px;padding:30px;background:#FFFFFF;">'
    '<h2 style="font-size:24px;font-weight:900;">FAQ</h2><details><summary style="list-style:none;">Яка ємність?</summary><p>2073.6 Вт·год.</p></details>'
    '</div><!-- ARTLINE FAQ BLOCK END --><!-- Блок 9. FAQ END --></section>')


def _run(page: str) -> str:
    style = SimpleNamespace(prompt=MASTER_STYLE_PROMPT, name='ARTLINE Master', golden_html='', hero_prompt='', feature_prompt='', negative_prompt='')
    response = SimpleNamespace(output_text=page, usage=None)
    with patch.object(pipeline, 'text_ready', return_value=True), patch.object(pipeline, '_responses_create', return_value=response):
        out, _, _, reason = pipeline.generate_html({'name': 'BLUETTI Premium 200 V2'}, style, 'ua', 'desktop',
                                                   '/media/p/hero-desktop.webp', '/media/p/feature.webp', 'stub')
    assert not reason, reason
    return out


def test_post_processing_keeps_the_new_components():
    out = BeautifulSoup(_run(PAGE), 'html.parser')
    eyebrows = [s for s in out.find_all('span') if 'letter-spacing:.08em' in (s.get('style') or '')]
    assert len(eyebrows) == 3 and all('border-radius:8px' in s['style'] and 'user-select:none' in s['style'] for s in eyebrows)
    sizes = lambda px: [d for d in out.find_all('div') if re.search(rf'font-size:\s*{px}px', d.get('style') or '')]
    assert len(sizes(18)) == 3, 'три плитки Hero лишаються 18px'
    assert len(sizes(26)) == 9, "п'ять ключових параметрів і чотири плитки панелей - без втрат"
    assert {h.get_text() for h in out.find_all('h3')} >= {'2700 Вт · 2073.6 Вт·год · LiFePO4', 'Портативна станція LiFePO4'}
    assert all('font-size:18px' in h['style'] for h in out.find_all('h3')), 'стандарт тримає h3 на 18px'
    panels = out.find('div', style=re.compile(r'grid-template-columns:repeat\(2,minmax\(0,1fr\)\);gap:18px'))
    assert panels is not None and len(panels.find_all('div', recursive=False)) == 2, 'дві панелі поруч'
    assert '950' not in str(out) and 'border-radius:999px' not in str(out)
