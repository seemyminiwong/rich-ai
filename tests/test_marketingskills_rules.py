"""Правила стилів за marketingskills (coreyhaines31/marketingskills), аудит 2026-10-25.

Звіт: docs/audits/styles-vs-marketingskills.md. Тут закріплено, що промпти просять
про нові правила тексту і SEO/GEO, а серверні перевірки ловлять їхні порушення
й не чіпають чистий текст.
"""
from app import pipeline
from app.prompts import (
    ARTLINE_STANDARD, DEFAULT_STYLE_PROMPT, ENGINEERING_STYLE_PROMPT, HUMAN_COPY_CONTRACT, MASTER_STYLE_PROMPT,
    SHOWCASE_STYLE_PROMPT, SOURCE_BOUNDARY_RULES,
)
from app.seo_geo import (
    audit_alt_entities, audit_geo_copy, audit_human_copy, audit_source_reuse,
)

PRODUCT = {'name': 'Гібридний інвертор DEYE SUN-10K', 'brand': 'DEYE', 'model': 'SUN-10K', 'category': 'Гібридні інвертори',
           'description': 'Гібридний інвертор DEYE SUN-10K поєднує сонячні панелі, акумуляторну систему, зовнішню мережу '
                          'та резервне навантаження в одному корпусі для домашньої енергосистеми.'}


def _codes(findings):
    return {f['code'] for f in findings}


def test_copy_rules_reach_every_style():
    for rule in ('Never stage a contrast reveal', 'list of absences', 'End a sentence where its claim ends',
                 'Prefer active verbs', 'never stack hedges', 'COPY SELF-CHECK', 'Swap test', 'over 25 words',
                 'One address form per page', 'never with a bare pronoun'):
        assert rule in HUMAN_COPY_CONTRACT, rule
    assert 'never reuse its sentences' in SOURCE_BOUNDARY_RULES
    assert 'Hero definition' in ARTLINE_STANDARD and 'names the product (brand and category, or model)' in ARTLINE_STANDARD
    # HUMAN_COPY_CONTRACT і SOURCE_BOUNDARY_RULES отримує кожен стиль, включно з Master
    from types import SimpleNamespace
    prompt = pipeline._prompt({'name': 'X'}, SimpleNamespace(prompt=MASTER_STYLE_PROMPT, golden_html=''), 'ua', 'desktop', '/h', '/f')
    assert 'COPY SELF-CHECK' in prompt and 'never reuse its sentences' in prompt
    assert '999px' not in prompt


def test_base_and_engineering_no_longer_force_counts_or_reframing():
    for style in (DEFAULT_STYLE_PROMPT, ENGINEERING_STYLE_PROMPT):
        assert 'reframe genuine facts' not in style and 'use fewer elements' in style
        assert 'Use exactly six equal' not in style and 'ending with a question mark' in style
        assert 'closes on a concrete confirmed fact' in style
    assert 'Never present it as a weakness' in DEFAULT_STYLE_PROMPT


def test_showcase_and_master_headings_state_outcomes():
    assert 'states the buyer outcome of its block' in SHOWCASE_STYLE_PROMPT
    assert 'The Final Recap closes on a concrete confirmed fact' in SHOWCASE_STYLE_PROMPT
    assert 'HERO DEFINITION' in MASTER_STYLE_PROMPT and 'never a bare label such as "ЕКСПЛУАТАЦІЯ"' in MASTER_STYLE_PROMPT
    assert 'never a slogan, aphorism, mood line or summary of the page' in MASTER_STYLE_PROMPT
    assert '>FAQ</h2>' not in MASTER_STYLE_PROMPT


def test_ai_patterns_and_passive_are_flagged():
    page = ('<section><div><h2>DEYE SUN-10K</h2><p>Гібридний інвертор DEYE для резервного живлення дому.</p></div>'
            '<div><h2>ХАРАКТЕРИСТИКИ</h2><p>Інвертор не просто перетворює енергію, а керує всією системою.</p>'
            '<p>Корпус працює без шуму, без вентиляторів.</p><p>Перемикання здійснюється автоматично. Захист забезпечується реле. '
            'Контроль здійснюється з застосунку.</p><p>Панель показує стан, забезпечуючи повний контроль.</p></div></section>')
    found = audit_human_copy(page, 'ua', product=PRODUCT)
    labels = {f['message'] for f in found if f['code'] == 'ai_pattern'}
    assert any('не просто' in m for m in labels) and any('відсутностей' in m for m in labels) and any('дієприслівник' in m for m in labels)
    assert 'passive_voice' in _codes(found)
    assert any(f['code'] == 'weak_heading' and f['evidence'] == 'ХАРАКТЕРИСТИКИ' for f in found)


def test_clean_copy_is_not_flagged():
    page = ('<section><div><h2>DEYE SUN-10K</h2><p>Гібридний інвертор DEYE для резервного живлення дому з батареєю 48 В.</p></div>'
            '<div><h2>ПЕРЕМИКАННЯ НА БАТАРЕЮ ЗА 10 МС</h2><p>Інвертор перемикає навантаження на батарею за 10 мс.</p></div></section>')
    codes = _codes(audit_human_copy(page, 'ua', product=PRODUCT)) | _codes(audit_geo_copy(page, PRODUCT, 'ua'))
    assert not codes & {'ai_pattern', 'passive_voice', 'pronoun_opening', 'definition_sentence_missing', 'weak_heading'}, codes


def test_hero_definition_and_pronoun_openings():
    page = ('<section><div><h2>DEYE SUN-10K</h2><p>Енергія завжди під рукою, коли вона потрібна найбільше.</p></div>'
            '<div><h2>ЗАХИСТ</h2><p>Він має захист IP65.</p></div></section>')
    codes = _codes(audit_geo_copy(page, PRODUCT, 'ua'))
    assert {'definition_sentence_missing', 'pronoun_opening'} <= codes


def test_copied_shop_description_and_alt_without_product():
    copied = ('<section><div><h2>DEYE</h2><p>Гібридний інвертор DEYE SUN-10K поєднує сонячні панелі, акумуляторну систему, '
              'зовнішню мережу та резервне навантаження в одному корпусі для домашньої енергосистеми.</p>'
              '<img src="/a.webp" alt="панель підключень"></div></section>')
    assert _codes(audit_source_reuse(copied, PRODUCT, 'ua')) == {'source_text_copied'}
    assert _codes(audit_alt_entities(copied, PRODUCT, 'ua')) == {'alt_without_entity'}
    own = ('<section><div><h2>DEYE</h2><p>Інвертор DEYE об\'єднує панелі, батарею й мережу: живлення переходить на батарею за 10 мс.</p>'
           '<img src="/a.webp" alt="Інвертор DEYE SUN-10K, панель підключень знизу"></div></section>')
    assert audit_source_reuse(own, PRODUCT, 'ua') == [] and audit_alt_entities(own, PRODUCT, 'ua') == []
    # Переклад не є копією: російська сторінка не порівнюється з українським описом
    assert audit_source_reuse(copied.replace('Гібридний', 'Гибридный'), PRODUCT, 'ru') == []


def test_generation_side_fixes():
    import inspect
    assert 'Localize, do not mirror the source syntax' in inspect.getsource(pipeline.translate_html)
    assert 'Переписуй від факту, а не заміною синонімів' in inspect.getsource(pipeline.llm_fix_texts)
    for copy in pipeline.LOCAL_FALLBACK.values():
        assert '{name}' in copy['description'] and 'рішення' not in copy['description'] and 'solution' not in copy['description']
    restored = pipeline._restore_image_urls('<section><div style="position:relative"><h2>X</h2></div></section>',
                                            '/media/p/hero.webp', '', 'desktop', img_hero=True, product_name='DEYE SUN-10K')
    assert 'alt="DEYE SUN-10K"' in restored


def test_intrinsic_sizes_reserve_space(monkeypatch):
    monkeypatch.setitem(pipeline._surface_size_cache, '/media/p/g1.webp', (1600, 1200))
    html = ('<section><img src="/media/p/g1.webp" style="width:100%;height:auto">'
            '<img src="/media/p/h.webp" style="position:absolute;inset:0"></section>')
    out = pipeline._set_intrinsic_sizes(html)
    assert 'width="1600"' in out and 'height="1200"' in out
    assert out.count('width=') == 1, 'фоновий кадр Hero не чіпається'
    assert pipeline._set_intrinsic_sizes(out) == out


def test_landing_lead_h3_links_and_summary_itemlist():
    from app.landing import deterministic_landing
    from app.seo_geo import audit_landing_document, build_landing_jsonld
    campaign = {'name': 'Тиждень SSD', 'campaign_title': 'Тиждень SSD', 'period': '1-7 листопада', 'language': 'ua'}
    products = [{'name': 'SSD Goodram IRDM 1TB', 'url': 'https://artline.ua/p/1', 'image': 'https://img/1.webp', 'price_text': '2 999 ₴'},
                {'name': 'SSD Kingston NV3 1TB', 'url': 'https://artline.ua/p/2', 'image': 'https://img/2.webp', 'price_text': '2 499 ₴'}]
    page = deterministic_landing(campaign, products, [{'name': 'SSD', 'url': 'https://artline.ua/c/ssd'}])
    assert '<h3 style=' in page and '<a href="https://artline.ua/p/1" rel="noopener" style="color:inherit' in page
    assert 'Тиждень SSD: 2 товарів · SSD · 1-7 листопада.' in page
    codes = {f['code'] for f in audit_landing_document(page, language='ua', published=False, products=products)}
    assert not codes & {'landing_no_lead', 'landing_heading_skip', 'generic_anchor_only'}, codes
    graph = build_landing_jsonld({**campaign, 'updated_at': '2026-10-25'}, products, {}, 'ua', 'https://artline.ua/promo/ssd')[0]['@graph']
    page_node = next(n for n in graph if n['@type'] == 'CollectionPage')
    assert page_node['dateModified'] == '2026-10-25'
    items = next(n for n in graph if n['@type'] == 'ItemList')['itemListElement']
    assert items == [{'@type': 'ListItem', 'position': 1, 'url': 'https://artline.ua/p/1', 'name': 'SSD Goodram IRDM 1TB'},
                     {'@type': 'ListItem', 'position': 2, 'url': 'https://artline.ua/p/2', 'name': 'SSD Kingston NV3 1TB'}]
