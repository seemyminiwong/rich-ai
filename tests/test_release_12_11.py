"""12.11: вичерпані кредити AI, зіпсоване кодування в крихтах, контраст акценту, хибні спрацювання."""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REAL_429 = ("Error code: 429 - {'error': {'message': 'You have no credits remaining. Add credits to continue using the API "
            "at https://platform.openai.com/account/billing', 'type': 'insufficient_quota'}}")


# --- Кредити провайдера ---------------------------------------------------------------

def test_quota_exhaustion_is_told_apart_from_a_rate_limit():
    from app.limits import is_quota_exhausted
    from app.pipeline import public_fallback_reason
    assert is_quota_exhausted(REAL_429) and is_quota_exhausted('insufficient_quota')
    assert not is_quota_exhausted('Rate limit reached for gpt-5-mini, retry in 2s')
    assert 'кредити провайдера вичерпано' in public_fallback_reason(RuntimeError(REAL_429))
    assert public_fallback_reason(RuntimeError('429 Too Many Requests: rate limit')) == 'тимчасовий ліміт запитів провайдера'


def test_a_quota_error_in_the_log_pauses_new_runs_and_alerts_once():
    import app.tasks as tasks
    project = SimpleNamespace(id='p1', name='Goodram', stage='', progress=0)
    db = SimpleNamespace(added=[], add=lambda e: db.added.append(e), commit=lambda: None)
    alerts = []
    with patch.object(tasks, 'set_provider_block', side_effect=[True, False]) as flag, patch.object(tasks, 'send_alert', alerts.append):
        tasks.log(db, project, 'images', f'Feature не згенеровано; використовується реальне фото товару. Причина: {REAL_429}', 70, 'warning')
        tasks.log(db, project, 'images', f'Hero не згенеровано: {REAL_429}', 71, 'warning')
        tasks.log(db, project, 'images', 'Hero не згенеровано: timeout', 72, 'warning')
    assert flag.call_count == 2 and len(alerts) == 1 and 'кредити AI-провайдера вичерпано' in alerts[0]
    assert any(getattr(e, 'stage', '') == 'quota' and e.level == 'error' for e in db.added)
    src = (ROOT / 'apps/api/app/tasks.py').read_text(encoding='utf-8')
    start = src[src.index('def process_project'):src.index('def process_project') + 4000]
    assert 'block = provider_block()' in start and "project.stage = 'quota'" in start and 'Status.paused' in start
    main = (ROOT / 'apps/api/app/main.py').read_text(encoding='utf-8')
    assert "@app.post('/api/providers/unblock')" in main and "'provider_block': provider_block()" in main and 'clear_provider_block()' in main
    web = (ROOT / 'apps/web/app.js').read_text(encoding='utf-8')
    assert 'function quotaBanner' in web and '${quotaBanner()}${content}' in web and "/api/providers/unblock" in web


# --- Зіпсоване кодування в хлібних крихтах ---------------------------------------------------

MOVECENTER = '''<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
{"@type":"ListItem","position":1,"name":"GтЈwna","item":"https://movecenter.eu"},
{"@type":"ListItem","position":2,"name":"Podzespoтy komputerowe","item":"https://movecenter.eu/catalog/podzespoly-komputerowe"},
{"@type":"ListItem","position":3,"name":"PamiЙ· RAM","item":"https://movecenter.eu/catalog/pamiec-ram"},
{"@type":"ListItem","position":4,"name":"Moduт pamiЙci Goodram IRDM RGB Black DDR5 6000 32GB (2x16GB) CL30 (IRG-60D5L30S/32GDC)"}]}</script></head>
<body><nav class="breadcrumbs"><a href="https://movecenter.eu">Główna</a> &gt; <a href="/catalog/podzespoly-komputerowe">Podzespoły komputerowe</a>
&gt; <a href="/catalog/pamiec-ram">Pamięć RAM</a></nav></body></html>'''


def test_garbled_jsonld_crumbs_are_repaired_from_the_visible_links():
    from app.category import breadcrumbs, fix_homoglyphs, looks_garbled, resolve_category
    assert looks_garbled('PamiЙ· RAM') and looks_garbled('GтЈwna') and looks_garbled('PamiÄ™Ä‡')
    assert not looks_garbled('Pamięć RAM') and not looks_garbled('Корпуси для ПК') and not looks_garbled('ASUS ROG Strix')
    assert fix_homoglyphs('PamiЙ· RAM') == 'PamiЙ· RAM'          # латинське слово не «кириличимо»
    assert fix_homoglyphs('Комплектуючi') == 'Комплектуючі' and fix_homoglyphs('Pamięć') == 'Pamięć'
    assert breadcrumbs(MOVECENTER) == ['Główna', 'Podzespoły komputerowe', 'Pamięć RAM']
    name = 'Moduł pamięci Goodram IRDM RGB Black DDR5 6000 32GB (2x16GB) CL30 (IRG-60D5L30S/32GDC)'
    url = 'https://movecenter.eu/product/modul-pamieci-goodram-irdm-rgb-black-ddr5-6000-32gb'
    assert resolve_category(MOVECENTER, url, name)['category'] == 'Pamięć RAM'
    # без видимих посилань зіпсована крихта відкидається, а не стає категорією
    bare = MOVECENTER.split('<body>')[0] + '<body></body></html>'
    assert 'Й' not in resolve_category(bare, url, name)['category']


# --- Контраст акценту на темних поверхнях ------------------------------------------------------

def test_server_picked_accent_text_on_dark_is_lifted_to_4_5_manual_stays():
    from app.pipeline import apply_palette, palette_from_accent, server_accents
    from app.raster import contrast_ratio
    goodram = palette_from_accent('#0056B3')
    assert goodram['accent'].upper() in server_accents()
    page = ('<div style="background:#1A2128"><b style="color:#19BCC9;font-size:26px">8 stref</b>'
            '<span style="border:1px solid #19BCC9;background:#19BCC9">RGB</span></div>')
    for palette in (goodram, palette_from_accent('#E4002B'), dict(palette_from_accent('#C8102E'), readable=True)):
        out = apply_palette(page, palette)
        text = re.search(r'color:(#\w{6});font-size', out).group(1)
        assert contrast_ratio(text, palette['dark_soft']) >= 4.5, (palette, text)
        assert f"border:1px solid {palette['accent']}" in out and apply_palette(out, palette) == out
    manual = apply_palette(page, {'accent': '#333333'})
    assert 'color:#333333;font-size' in manual
    tasks = (ROOT / 'apps/api/app/tasks.py').read_text(encoding='utf-8')
    assert "tokens['readable'] = True" in tasks and "source in ('brand', 'photo')" in tasks


# --- Хибні спрацювання перевірок ---------------------------------------------------------------

def _page(blocks):
    return '<section>' + ''.join(f'<div>{b}</div>' for b in blocks) + '</section>'


def test_faq_answer_with_a_concrete_value_is_self_contained():
    from app.seo_geo import audit_geo_copy
    product = {'name': 'Монітор Qube G25F300HS', 'brand': 'Qube', 'category': 'Монітори',
               'specs': [{'name': 'Яскравість', 'value': '350 cd/m²'}, {'name': 'Контраст', 'value': '1000:1'}]}
    faq = ('<details><summary>Яка яскравість і контрастність екрана?</summary>'
           '<p>Яскравість становить 350 cd/m², статична контрастність 1000:1.</p></details>')
    thin = '<details><summary>Чи є гарантія виробника?</summary><p>Так.</p></details>'
    codes = lambda html: [f['code'] for f in audit_geo_copy(_page(['<h2>Qube G25F300HS</h2><p>Монітор Qube G25F300HS для ігор.</p>', html]), product, 'ua')]
    assert 'faq_answer_thin' not in codes(faq) and 'faq_answer_thin' in codes(thin)


def test_category_carried_by_the_first_block_label_counts():
    from app.seo_geo import audit_geo_copy
    product = {'name': 'Монітор Qube G25F300HS', 'brand': 'Qube', 'category': 'Монітори'}
    hero = '<span>QUBE · МОНІТОР</span><h2>QUBE G25F300HS</h2><p>QUBE G25F300HS - швидка модель для кіберспорту.</p>'
    assert 'entity_without_category' not in [f['code'] for f in audit_geo_copy(_page([hero, '<p>Інше.</p>']), product, 'ua')]
    bare = '<h2>QUBE G25F300HS</h2><p>QUBE G25F300HS - швидка модель для кіберспорту.</p>'
    assert 'entity_without_category' in [f['code'] for f in audit_geo_copy(_page([bare, '<p>Інше.</p>']), product, 'ua')]


def test_score_counts_a_problem_once_not_per_desktop_and_mobile():
    from app.seo_geo import run_rich_audits
    product = {'name': 'Монітор Qube G25F300HS', 'brand': 'Qube', 'category': 'Монітори', 'specs': [{'name': 'Яскравість', 'value': '350 cd/m²'}]}
    html = _page(['<h2>Qube G25F300HS</h2><p>Монітор Qube G25F300HS для ігор із яскравістю 350 cd/m².</p>',
                  '<details><summary>Чи є підсвітка?</summary><p>Так.</p></details>'])
    one = run_rich_audits([SimpleNamespace(html=html, language='ua', variant='desktop')], product)
    two = run_rich_audits([SimpleNamespace(html=html, language='ua', variant='desktop'), SimpleNamespace(html=html, language='ua', variant='mobile')], product)
    geo1, geo2 = (next(r for r in rows if r['type'] == 'geo') for rows in (one, two))
    assert geo1['findings'] and geo1['score'] == geo2['score'] and len(geo2['findings']) == 2 * len(geo1['findings'])


def test_chips_do_not_count_as_repeating_a_fact():
    from app.seo_geo import audit_geo_copy
    product = {'name': 'Памʼять Goodram IRDM', 'brand': 'Goodram', 'category': 'Памʼять', 'specs': [{'name': 'Частота', 'value': '6000 MHz'}]}
    blocks = ['<h2>Goodram IRDM</h2><p>Goodram IRDM - памʼять DDR5 на 6000 MHz.</p><span>6000 MHz</span>'] + \
             [f'<span>6000 MHz</span><p>Блок {i} про інше.</p>' for i in range(6)]
    assert 'fact_repeated_across_blocks' not in [f['code'] for f in audit_geo_copy(_page(blocks), product, 'ua')]
