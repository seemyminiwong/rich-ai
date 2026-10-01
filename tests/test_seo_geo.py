"""SEO / GEO / human-copy контроль: детерміновані перевірки, лендінг, критики.

Без БД і без мережі: усе, що тут перевіряється, - чисті функції seo_geo,
landing і pipeline. Ворота схвалення й правила прийняття знахідок теж
чисті (approval_blockers / validate_decision), тому тестуються напряму.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import seo_geo as sg
from app.landing import build_landing_prompt, deterministic_landing, generate_landing_html
from app.seo_geo import (
    DEFAULT_PUBLISHING_PROFILE, DELIVERY_STATEMENTS, LANG_MAP, approval_blockers, audit_geo_copy, audit_human_copy,
    audit_landing_document, audit_language_quality, audit_rich_fragment, audit_variant_consistency, build_evidence,
    build_landing_jsonld, build_landing_metadata, build_seo_brief, company_facts, confirmed_only, finalize_landing_seo,
    import_keyword_data, brief_from_keywords, report_from_findings, run_rich_audits, validate_decision,
)

PRODUCT = {
    'name': 'ASUS ESC8000A-E12',
    'brand': 'ASUS',
    'category': 'GPU-сервери',
    'sku': '90SF02H1-M00050',
    'description': 'Сервер для машинного навчання з 8 GPU.',
    'features': ['Підтримка 8 × NVIDIA B300', 'Резервоване живлення 2 × 3000 Вт'],
    'specs': [
        {'name': 'GPU', 'value': '8 × NVIDIA B300'},
        {'name': "Оперативна пам'ять", 'value': '2 ТБ DDR5'},
        {'name': 'Блок живлення', 'value': '2 × 3000 Вт'},
        {'name': 'Форм-фактор', 'value': '4U'},
    ],
}
PROFILE = dict(DEFAULT_PUBLISHING_PROFILE)
BRIEF = {'primary_topic': 'GPU-сервер для локального AI', 'entities': ['ASUS', 'NVIDIA'], 'language': 'uk', 'source': 'manual'}


def _page(paragraphs, headings=('ASUS ESC8000A-E12 - GPU-сервер для локального AI', 'ЖИВЛЕННЯ І ФОРМ-ФАКТОР'), alts=('ASUS ESC8000A-E12 спереду', 'ASUS ESC8000A-E12 - блоки живлення'), lang_note=''):
    blocks = []
    for i, (heading, text) in enumerate(zip(headings, paragraphs)):
        img = f'<img src="/media/p/{i}.webp" alt="{alts[i]}"{"" if i == 0 else " loading=\"lazy\""}>' if i < len(alts) else ''
        blocks.append(f'<div><h2>{heading}</h2><p>{text}</p>{img}</div>')
    return '<section>' + ''.join(blocks) + '</section>'


GOOD_UK = _page([
    "ASUS ESC8000A-E12 - це GPU-сервер для команд, які запускають локальні AI-моделі. Він вміщує 8 × NVIDIA B300 і 2 ТБ пам'яті DDR5, тому великі мовні моделі працюють без обміну з диском.",
    "Два блоки живлення по 3000 Вт резервують один одного, а корпус 4U стає у стандартну стійку.",
])


# ---------------------------------------------------------------------------
# Rich fragment
# ---------------------------------------------------------------------------

def test_clean_fragment_passes_seo_and_geo_without_critical_findings():
    seo = audit_rich_fragment(GOOD_UK, PRODUCT, 'ua', 'desktop', BRIEF)
    geo = audit_geo_copy(GOOD_UK, PRODUCT, 'ua', 'desktop', BRIEF, None, PROFILE)
    assert not [f for f in seo + geo if f['severity'] == 'critical'], seo + geo
    assert not any(f['code'] in ('identity_missing_early', 'category_missing_early', 'primary_topic_late') for f in seo)


def test_h1_and_document_level_seo_are_forbidden_inside_the_fragment():
    html = ('<section><h1>ASUS ESC8000A-E12</h1><title>x</title><meta name="description" content="x">'
            '<link rel="canonical" href="https://a/b"><script type="application/ld+json">{}</script>'
            '<h2>GPU-сервер</h2><p>ASUS ESC8000A-E12 - GPU-сервер.</p></section>')
    codes = {f['code']: f['severity'] for f in audit_rich_fragment(html, PRODUCT, 'ua')}
    assert codes.get('h1_in_fragment') == 'critical'
    assert codes.get('document_seo_in_fragment') == 'critical'


def test_brand_model_and_category_must_appear_early():
    html = _page(['Потужна машина для будь-яких задач із 8 GPU.', 'Два блоки живлення по 3000 Вт.'], headings=('Потужність', 'Живлення'))
    codes = {f['code'] for f in audit_rich_fragment(html, PRODUCT, 'ua')}
    assert 'identity_missing_early' in codes and 'category_missing_early' in codes
    assert 'identity_missing_early' not in {f['code'] for f in audit_rich_fragment(GOOD_UK, PRODUCT, 'ua')}


def test_alt_is_required_localized_and_informative():
    missing = GOOD_UK.replace(' alt="ASUS ESC8000A-E12 спереду"', '')
    assert any(f['code'] == 'alt_missing' and f['severity'] == 'critical' for f in audit_rich_fragment(missing, PRODUCT, 'ua'))
    generic = GOOD_UK.replace('alt="ASUS ESC8000A-E12 спереду"', 'alt="image"')
    assert any(f['code'] == 'alt_generic' for f in audit_rich_fragment(generic, PRODUCT, 'ua'))
    filename = GOOD_UK.replace('alt="ASUS ESC8000A-E12 спереду"', 'alt="IMG_0042.jpg"')
    assert any(f['code'] == 'alt_generic' for f in audit_rich_fragment(filename, PRODUCT, 'ua'))
    cyr_alt_on_pl = GOOD_UK
    assert any(f['code'] == 'alt_language' for f in audit_rich_fragment(cyr_alt_on_pl, PRODUCT, 'pl'))
    assert not any(f['code'].startswith('alt_') for f in audit_rich_fragment(GOOD_UK, PRODUCT, 'ua'))


def test_keyword_stuffing_is_detected_but_two_natural_mentions_are_fine():
    topic = 'GPU-сервер для локального AI'
    stuffed = _page([f'{topic} ASUS ESC8000A-E12. {topic} має 8 GPU. Купити {topic}. {topic} - вибір. Ще раз {topic}.',
                     f'{topic} у стійці 4U. {topic} з 2 ТБ.'])
    human = audit_human_copy(stuffed, 'uk', 'desktop', BRIEF, PRODUCT)
    assert any(f['code'] == 'keyword_repetition' and f['evidence'] == topic for f in human)
    natural = audit_human_copy(GOOD_UK, 'uk', 'desktop', BRIEF, PRODUCT)
    assert not any(f['code'] in ('keyword_repetition', 'unnatural_keyword_form') for f in natural)


def test_generic_ai_phrases_and_duplicate_sentences_are_flagged_with_segment_links():
    html = _page(['ASUS ESC8000A-E12 - інноваційне рішення, що відкриває нові горизонти. Він вміщує 8 × NVIDIA B300.',
                  'Він вміщує 8 × NVIDIA B300. Ідеальний вибір для тих, хто цінує якість.'])
    rows = audit_human_copy(html, 'uk', 'desktop', BRIEF, PRODUCT)
    codes = [f['code'] for f in rows]
    assert 'generic_phrase' in codes and 'duplicate_sentence' in codes
    dup = next(f for f in rows if f['code'] == 'duplicate_sentence')
    assert dup['segment'].startswith('t') and dup['evidence'] and dup['suggestion'] and dup['block'] == 0
    # ключі сегментів збігаються з редактором тексту
    from app.text_edit import editable_segments
    keys = {it['key'] for b in editable_segments(html) for it in b['items']}
    assert dup['segment'] in keys


def test_few_facts_produce_short_copy_not_filler():
    """Мало фактів - текст коротший; детермінований шаблон не додає обіцянок."""
    from app.pipeline import _deterministic_html
    thin = {'name': 'Кабель USB-C', 'brand': 'Baseus', 'category': 'Кабелі'}
    style = SimpleNamespace(prompt='', name='Test', golden_html='')
    html = _deterministic_html(thin, style, 'ua', 'desktop', '/h.webp', '/f.webp')
    geo = audit_geo_copy(html, thin, 'ua', 'desktop', None, [], PROFILE)
    assert not any(f['code'] == 'unsupported_commercial_claim' for f in geo)
    assert not any(f['code'] == 'number_without_provenance' for f in geo)


def test_desktop_and_mobile_must_carry_the_same_text():
    desk = SimpleNamespace(html=GOOD_UK, language='ua', variant='desktop')
    same = SimpleNamespace(html=GOOD_UK.replace('<div>', '<div style="padding:4px">'), language='ua', variant='mobile')
    assert audit_variant_consistency([desk, same]) == []
    other = SimpleNamespace(html=_page(['ASUS ESC8000A-E12 - GPU-сервер. Зовсім інший текст про щось ще.', 'Ще один інший абзац для мобільної.']), language='ua', variant='mobile')
    rows = {r['code']: r['severity'] for r in audit_variant_consistency([desk, other])}
    # Інші цифри - попередження; інше формулювання - лише інфо, ніколи не блокує схвалення
    assert rows == {'variant_values_mismatch': 'warning', 'variant_text_mismatch': 'info'}


def test_warranty_from_product_specs_is_a_product_fact_not_a_shop_promise():
    product = dict(PRODUCT, specs=PRODUCT['specs'] + [{'name': 'Гарантія', 'value': '36 міс.'}])
    html = _page(['ASUS ESC8000A-E12 - GPU-сервер з 8 × NVIDIA B300.', 'Гарантія 36 міс. від виробника.'])
    geo = audit_geo_copy(html, product, 'ua', 'desktop', None, None, PROFILE)
    assert not any(f['code'] == 'unsupported_commercial_claim' for f in geo)
    # без гарантії в характеристиках - як і раніше критично
    assert any(f['code'] == 'unsupported_commercial_claim' and f['severity'] == 'critical'
               for f in audit_geo_copy(html, PRODUCT, 'ua', 'desktop', None, None, PROFILE))


def test_mobile_translation_reuses_the_desktop_translation():
    from app.pipeline import translate_html
    desktop = '<section><h2>Корпус для ПК</h2><p>Гарантия 36 мес.</p><img src="/a.webp" alt="Корпус спереди"></section>'
    mobile = '<section><div style="padding:8px"><h2>Корпус для ПК</h2><p>Гарантия 36 мес.</p><img src="/a.webp" alt="Корпус спереди"></div></section>'
    calls = []

    class Reply:
        def __init__(self, text):
            self.output_text = text
            self.usage = SimpleNamespace(input_tokens=100, output_tokens=20)

    def fake(model, prompt, cap):
        calls.append(prompt)
        return Reply(json.dumps({'alt0': 'Корпус спереду', '0': 'Корпус для ПК', '1': 'Гарантія 36 міс.'}, ensure_ascii=False))

    memory = {}
    with patch('app.pipeline._responses_create', fake), patch('app.pipeline.text_ready', lambda: True):
        first, ti, _ = translate_html(desktop, 'ua', 'm', memory=memory)
        second, ti2, to2 = translate_html(mobile, 'ua', 'm', memory=memory)
    assert len(calls) == 1 and ti == 100 and (ti2, to2) == (0, 0), 'мобільна не перекладається вдруге'
    assert 'Гарантія 36 міс.' in second and 'alt="Корпус спереду"' in second


def test_radius_audit_reports_deviations_relative_to_the_scheme_scale():
    from app.artline_standard import apply_artline_standard, normalize_radii, radius_deviations
    page = ('<section><div style="border-radius:14px;padding:20px"><div style="border-radius:8px;padding:10px">Картка</div></div>'
            '<div style="border-radius:24px 24px 0 0;padding:20px"><span style="border-top-left-radius:1.25rem">Лейбл</span></div></section>')
    found = radius_deviations(page)
    assert len(found) == 3 and any('8px' in f for f in found) and any('1.25rem' in f for f in found)
    fixed = apply_artline_standard(page)
    assert radius_deviations(fixed) == []
    assert 'border-radius:14px 14px 0 0' in fixed and 'border-top-left-radius:12px' in fixed and 'border-radius:10px' in fixed
    assert normalize_radii('border-radius:999px', False) == 'border-radius:999px' and normalize_radii('border-radius:50%', False) == 'border-radius:50%'
    # повзунок скруглень 0.5: зовнішні 7px, внутрішні 5-6px - це не дефект
    scaled = '<section><div style="border-radius:7px;padding:20px"><div style="border-radius:5px">Картка</div></div><div style="border-radius:7px">Б</div></section>'
    assert radius_deviations(scaled) == []


def test_facts_have_provenance_and_derived_values_never_reach_the_prompt():
    page_text = "GPU 8 × NVIDIA B300. Оперативна пам'ять 2 ТБ DDR5. Блок живлення 2 × 3000 Вт."
    product = dict(PRODUCT, specs=PRODUCT['specs'] + [{'name': 'Вага', 'value': '48 кг'}])
    evidence = build_evidence(product, jsonld_specs=[{'name': 'GPU', 'value': '8 × NVIDIA B300'}],
                              table_specs=[{'name': "Оперативна пам'ять", 'value': '2 ТБ DDR5'}],
                              page_text=page_text, source_url='https://artline.ua/p', jsonld_keys={'name', 'brand'})
    by_id = {e['id']: e for e in evidence}
    assert by_id['spec_gpu']['source_type'] == 'jsonld' and by_id['spec_gpu']['confidence'] == 'confirmed'
    assert by_id["spec_оперативна_пам_ять"]['source_type'] == 'spec_table'
    assert by_id['spec_блок_живлення']['source_type'] == 'page_text' and by_id['spec_блок_живлення']['confidence'] == 'confirmed'
    assert by_id['spec_вага']['confidence'] == 'derived'
    assert by_id['identity_brand']['source_type'] == 'jsonld'
    assert all(e['source_url'] == 'https://artline.ua/p' for e in evidence)
    product['evidence'] = evidence
    facts = confirmed_only(product)
    assert 'evidence' not in facts and not any(s['name'] == 'Вага' for s in facts['specs'])
    # число без джерела - критична знахідка GEO
    html = _page(['ASUS ESC8000A-E12 - GPU-сервер вагою 48 кг з 8 × NVIDIA B300.', 'Два блоки по 3000 Вт.'])
    geo = audit_geo_copy(html, confirmed_only(product), 'ua', 'desktop', None, [e for e in evidence if e['confidence'] == 'confirmed'], PROFILE)
    assert any(f['code'] == 'number_without_provenance' and f['severity'] == 'critical' and '48 кг' in f['evidence'] for f in geo)


def test_unsupported_commercial_claims_are_critical_and_verified_delivery_is_allowed():
    html = _page(['ASUS ESC8000A-E12 - GPU-сервер з 8 × NVIDIA B300. Постачаємо обладнання по Україні та Польщі.',
                  'Офіційна гарантія 3 роки і підтримка 24/7, швидка доставка за 2 дні.'])
    geo = audit_geo_copy(html, PRODUCT, 'ua', 'desktop', None, None, PROFILE)
    claims = {f['evidence'][:30]: f['severity'] for f in geo if f['code'] == 'unsupported_commercial_claim'}
    assert claims and all(v == 'critical' for v in claims.values())
    assert not any('Постачаємо обладнання' in f['evidence'] for f in geo if f['code'] == 'unsupported_commercial_claim')


def test_geo_flags_missing_entity_sentence_and_scene_setting_openers():
    html = _page(['Уявіть собі дата-центр, де все працює. ASUS - бренд.', 'ESC8000A-E12 стоїть у стійці 4U.'], headings=('Потужність', 'Живлення'))
    codes = {f['code'] for f in audit_geo_copy(html, PRODUCT, 'ua', 'desktop', None, None, PROFILE)}
    assert 'entity_not_linked_early' in codes and 'not_answer_first' in codes


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

PL_CLEAN = _page(['ASUS ESC8000A-E12 to serwer GPU dla zespołów, które uruchamiają lokalne modele AI. Mieści 8 × NVIDIA B300 i 2 TB pamięci DDR5, więc duże modele językowe działają bez wymiany z dyskiem.',
                  'Dwa zasilacze po 3000 W rezerwują się nawzajem, a obudowa 4U mieści się w standardowej szafie.'],
                 headings=('ASUS ESC8000A-E12 - serwer GPU do lokalnego AI', 'ZASILANIE I OBUDOWA'),
                 alts=('ASUS ESC8000A-E12 z przodu', 'ASUS ESC8000A-E12 - zasilacze'))
EN_CLEAN = _page(['The ASUS ESC8000A-E12 is a GPU server for teams that run local AI models. It holds 8 × NVIDIA B300 and 2 TB of DDR5 memory, so large language models run without swapping to disk.',
                  'Two 3000 W power supplies back each other up, and the 4U chassis fits a standard rack.'],
                 headings=('ASUS ESC8000A-E12 - GPU server for local AI', 'POWER AND CHASSIS'),
                 alts=('ASUS ESC8000A-E12 front view', 'ASUS ESC8000A-E12 - power supplies'))


def test_clean_ukrainian_polish_and_english_pass_language_audit():
    assert audit_language_quality(GOOD_UK, 'ua', 'desktop', PRODUCT) == []
    assert audit_language_quality(PL_CLEAN, 'pl', 'desktop', PRODUCT) == []
    assert audit_language_quality(EN_CLEAN, 'en', 'desktop', PRODUCT) == []


def test_official_names_are_not_language_mixing_but_cyrillic_words_are():
    with_names = PL_CLEAN.replace('serwer GPU dla', 'serwer GPU NVIDIA DDR5 dla')
    assert audit_language_quality(with_names, 'pl', 'desktop', PRODUCT) == []
    leaked = PL_CLEAN.replace('rezerwują się nawzajem', 'резервують один одного і працюють разом')
    rows = audit_language_quality(leaked, 'pl', 'desktop', PRODUCT)
    assert rows and rows[0]['code'] == 'cyrillic_in_latin_page' and rows[0]['segment']
    heavy = PL_CLEAN.replace('Dwa zasilacze po 3000 W rezerwują się nawzajem', 'Два блоки живлення по три тисячі ват резервують один одного постійно')
    assert any(f['code'] == 'cyrillic_in_latin_page' and f['severity'] == 'critical' for f in audit_language_quality(heavy, 'pl', 'desktop', PRODUCT))


def test_literal_translation_gets_a_warning():
    calque = PL_CLEAN.replace('Mieści 8 × NVIDIA B300', 'Na dzień dzisiejszy mieści 8 × NVIDIA B300')
    rows = audit_language_quality(calque, 'pl', 'desktop', PRODUCT)
    assert any(f['code'] == 'literal_translation' and f['severity'] == 'warning' for f in rows)
    uk_calque = GOOD_UK.replace('Він вміщує', 'На протязі роботи він вміщує')
    assert any(f['code'] == 'literal_translation' for f in audit_language_quality(uk_calque, 'ua', 'desktop', PRODUCT))


def test_delivery_statement_is_correct_in_all_three_languages():
    assert DELIVERY_STATEMENTS == {
        'uk': 'Постачаємо обладнання по Україні та Польщі.',
        'pl': 'Dostarczamy sprzęt na terenie Ukrainy i Polski.',
        'en': 'We deliver equipment across Ukraine and Poland.',
    }
    for code, lang in (('uk', 'ua'), ('pl', 'pl'), ('en', 'en')):
        assert company_facts(PROFILE, lang) == [DELIVERY_STATEMENTS[code]]
    assert LANG_MAP == {'ua': 'uk', 'uk': 'uk', 'pl': 'pl', 'en': 'en', 'ru': 'ru'}
    wrong = PL_CLEAN.replace('Dwa zasilacze', 'Постачаємо обладнання по Україні та Польщі. Dwa zasilacze')
    assert any(f['code'] == 'delivery_statement_wrong_language' for f in audit_language_quality(wrong, 'pl', 'desktop', PRODUCT))


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------

CAMPAIGN = {'name': 'Bambu Lab sale', 'campaign_title': 'Знижки до -30% на Bambu Lab', 'campaign_subtitle': 'До річниці бренду', 'period': '15.06-15.07', 'language': 'ua'}
PRODUCTS = [
    {'name': 'Bambu Lab P1S', 'url': 'https://artline.ua/uk/product/bambu-p1s', 'image': 'https://cdn.artline.ua/p1s.webp', 'price': '29999', 'price_text': '29 999 ₴', 'currency': 'UAH'},
    {'name': 'Bambu Lab A1 mini', 'url': 'https://artline.ua/uk/product/bambu-a1-mini', 'image': '', 'price': '', 'price_text': ''},
]
CANON = 'https://artline.ua/uk/solution/bambu-lab'
ALTS = {'uk': CANON, 'pl': 'https://artline.ua/pl/solution/bambu-lab', 'en': 'https://artline.ua/en/solution/bambu-lab', 'x-default': CANON}


def _landing(published: bool, language='ua', profile=PROFILE):
    campaign = dict(CAMPAIGN, language=language)
    html = deterministic_landing(campaign, PRODUCTS, [], profile)
    return finalize_landing_seo(html, campaign=campaign, products=PRODUCTS, profile=profile, language=language,
                                canonical=CANON if published else '', alternates=ALTS if published else {}, published=published)


def _head(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, 'html.parser')


def test_landing_has_exactly_one_h1_lang_title_description_and_no_hardcoded_claims():
    for lang, code in (('ua', 'uk'), ('pl', 'pl'), ('en', 'en')):
        html = _landing(False, lang)
        soup = _head(html)
        assert len(soup.find_all('h1')) == 1
        assert soup.find('html')['lang'] == code
        assert soup.find('title').get_text().strip() and soup.find('meta', attrs={'name': 'description'})['content']
        text = soup.get_text(' ')
        assert '24/7' not in text and 'гарант' not in text.lower() and 'gwarancj' not in text.lower() and 'warrant' not in text.lower()
        assert DELIVERY_STATEMENTS[code] in text  # доставка Україна + Польща з профілю
        findings = audit_landing_document(html, language=lang, published=False, products=PRODUCTS, profile=PROFILE)
        assert not [f for f in findings if f['severity'] == 'critical'], findings


def test_landing_without_verified_facts_has_no_advantages_block():
    empty_profile = dict(PROFILE, verified_facts={}, statements={}, delivery_geography=[])
    html = deterministic_landing(CAMPAIGN, PRODUCTS, [], empty_profile)
    assert 'LANDING BLOCK 04' not in html and 'Постачаємо' not in html
    assert 'Технічна підтримка 24/7' not in html and 'Офіційна гарантія' not in html and 'Швидка доставка' not in html


def test_landing_localization_for_pl_and_en_uses_dictionaries_not_ua_ru_ternaries():
    pl = deterministic_landing(dict(CAMPAIGN, language='pl'), PRODUCTS, [{'name': 'Drukarki 3D', 'url': 'https://artline.ua/pl/catalog/3d', 'image': ''}], PROFILE)
    assert 'Kup' in pl and 'Kategorie produktów promocyjnych' in pl and 'Cena' in pl and 'Купити' not in pl
    en = deterministic_landing(dict(CAMPAIGN, language='en'), PRODUCTS, [], PROFILE)
    assert '>Buy<' in en and 'Products on sale' in en and 'Price' in en
    prompt = build_landing_prompt(dict(CAMPAIGN, language='pl'), PRODUCTS, '', [], PROFILE)
    assert 'polski' in prompt and '«Kup»' in prompt and 'Dostarczamy sprzęt na terenie Ukrainy i Polski.' in prompt
    assert 'official warranty, support, delivery' not in prompt


def test_draft_is_noindex_and_published_has_canonical_hreflang_and_index():
    draft = _head(_landing(False))
    assert 'noindex' in draft.find('meta', attrs={'name': 'robots'})['content']
    assert draft.find('link', attrs={'rel': 'canonical'}) is None
    published = _head(_landing(True))
    assert published.find('meta', attrs={'name': 'robots'})['content'] == 'index,follow,max-image-preview:large'
    assert published.find('link', attrs={'rel': 'canonical'})['href'] == CANON
    hreflang = {l['hreflang']: l['href'] for l in published.find_all('link', attrs={'rel': 'alternate'})}
    assert hreflang == ALTS  # включно з x-default
    assert published.find('meta', attrs={'property': 'og:url'})['content'] == CANON
    assert published.find('meta', attrs={'name': 'twitter:card'})['content'] == 'summary_large_image'
    findings = audit_landing_document(_landing(True), language='ua', expected_canonical=CANON, expected_alternates=ALTS,
                                      published=True, products=PRODUCTS, profile=PROFILE)
    assert not [f for f in findings if f['severity'] == 'critical'], findings
    # чернетка, що видається як опублікована, і навпаки - критично
    assert any(f['code'] == 'robots_noindex_published' for f in audit_landing_document(_landing(False), language='ua', published=True, products=PRODUCTS, profile=PROFILE))
    assert any(f['code'] == 'robots_draft_indexable' for f in audit_landing_document(_landing(True), language='ua', published=False, products=PRODUCTS, profile=PROFILE))


def test_jsonld_is_server_built_parses_and_never_invents_offer_or_forbidden_fields():
    soup = _head(_landing(True))
    scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
    assert scripts
    data = json.loads(scripts[0].string)
    types = [n['@type'] for n in data['@graph']]
    assert 'Organization' in types and 'CollectionPage' in types and 'ItemList' in types and 'WebSite' in types
    items = next(n for n in data['@graph'] if n['@type'] == 'ItemList')['itemListElement']
    p1s, a1 = items[0]['item'], items[1]['item']
    assert p1s['offers'] == {'@type': 'Offer', 'price': '29999', 'priceCurrency': 'UAH', 'url': PRODUCTS[0]['url']}
    assert 'offers' not in a1  # без ціни - без Offer
    for node in (p1s, a1):
        for key in ('aggregateRating', 'review', 'availability', 'priceValidUntil', 'shippingDetails', 'sku', 'gtin', 'brand'):
            assert key not in node
    assert 'FAQPage' not in types  # FAQ не видно - schema немає
    # WebSite лише для основного сайту
    not_primary = dict(PROFILE, primary_site=False)
    graph = build_landing_jsonld(CAMPAIGN, PRODUCTS, not_primary, 'ua', CANON)[0]['@graph']
    assert 'WebSite' not in [n['@type'] for n in graph]


def test_faq_schema_only_matches_visible_faq():
    campaign = dict(CAMPAIGN)
    html = deterministic_landing(campaign, PRODUCTS, [], PROFILE).replace(
        '</section>', '<details><summary>Чи підходить P1S для PETG?</summary><p>Так, камера закрита і сопло тримає 300 °C.</p></details></section>')
    page = finalize_landing_seo(html, campaign=campaign, products=PRODUCTS, profile=PROFILE, language='ua', canonical=CANON, published=True)
    soup = _head(page)
    faq = next(json.loads(s.string) for s in soup.find_all('script', attrs={'type': 'application/ld+json'}) if 'FAQPage' in s.string)
    node = next(n for n in faq['@graph'] if n['@type'] == 'FAQPage')
    assert node['mainEntity'][0]['name'] == 'Чи підходить P1S для PETG?'
    assert not [f for f in audit_landing_document(page, language='ua', expected_canonical=CANON, published=True, products=PRODUCTS, profile=PROFILE) if f['code'] == 'faq_schema_mismatch']
    # підмінена відповідь у schema - критично
    tampered = page.replace('"text": "Так, камера закрита і сопло тримає 300 °C."', '"text": "Інша відповідь."')
    assert tampered != page
    assert any(f['code'] == 'faq_schema_mismatch' for f in audit_landing_document(tampered, language='ua', expected_canonical=CANON, published=True, products=PRODUCTS, profile=PROFILE))


def test_unknown_url_never_reaches_a_link_or_jsonld():
    html = _landing(True).replace('</section>', '<a href="https://evil.example/buy">Купити тут</a></section>')
    findings = audit_landing_document(html, language='ua', expected_canonical=CANON, published=True, products=PRODUCTS, profile=PROFILE)
    assert any(f['code'] == 'unknown_link' and f['severity'] == 'critical' and 'evil.example' in f['evidence'] for f in findings)
    jsonld = build_landing_jsonld(CAMPAIGN, PRODUCTS + [{'name': 'Фантом', 'url': ''}], PROFILE, 'ua', CANON)[0]['@graph']
    names = [i['item']['name'] for n in jsonld if n['@type'] == 'ItemList' for i in n['itemListElement']]
    assert 'Фантом' not in names


def test_generate_landing_html_falls_back_to_finalized_template_without_a_provider():
    with patch('app.pipeline._responses_create', side_effect=RuntimeError('no key')):
        html, ti, to, reason = generate_landing_html(CAMPAIGN, PRODUCTS, 'gpt-5-mini', '', [], PROFILE, {'canonical': '', 'published': False})
    assert reason and ti == 0 and to == 0
    soup = _head(html)
    assert 'noindex' in soup.find('meta', attrs={'name': 'robots'})['content'] and soup.find('title')
    assert '24/7' not in html


def test_landing_metadata_description_carries_verified_delivery_only():
    meta = build_landing_metadata(CAMPAIGN, PRODUCTS, PROFILE, 'ua', CANON, ALTS, True)
    assert meta['lang'] == 'uk' and 'ARTLINE' in meta['title'] and len(meta['title']) <= 70
    assert DELIVERY_STATEMENTS['uk'] in meta['description'] and 50 <= len(meta['description']) <= 160
    assert meta['robots'].startswith('index') and meta['alternates']['x-default'] == CANON
    draft = build_landing_metadata(CAMPAIGN, PRODUCTS, PROFILE, 'ua', '', {}, True)  # без canonical - не індексується
    assert draft['robots'] == 'noindex,nofollow'


# ---------------------------------------------------------------------------
# Critics, findings, approval gate
# ---------------------------------------------------------------------------

def test_new_critic_types_appear_and_serialize():
    from app.pipeline import FREE_CRITIC_TYPES, critic_html, free_critic_reports
    for kind in ('seo', 'geo', 'human', 'language'):
        assert kind in FREE_CRITIC_TYPES
    arts = [SimpleNamespace(html=GOOD_UK, language='ua', variant='desktop'), SimpleNamespace(html=GOOD_UK, language='ua', variant='mobile')]
    reports = free_critic_reports(arts, PRODUCT, BRIEF, PROFILE)
    assert [r['type'] for r in reports] == ['html', 'facts', 'accessibility', 'marketing', 'seo', 'geo', 'human', 'language']
    for r in reports:
        json.dumps(r, ensure_ascii=False)  # серіалізується
        for f in r['findings']:
            assert {'code', 'severity', 'language', 'variant', 'block', 'message', 'evidence', 'suggestion', 'key'} <= set(f)
    score, summary, issues, suggestions = critic_html(arts, 'geo', PRODUCT, BRIEF, PROFILE)
    assert 0 <= score <= 100 and isinstance(issues, list)


def test_report_score_is_derived_from_findings_and_example_finding_has_evidence():
    rows = run_rich_audits([SimpleNamespace(html=GOOD_UK, language='ua', variant='desktop')], PRODUCT, BRIEF, PROFILE)
    assert all(r['score'] == 100 for r in rows if not r['findings'])
    example = sg.finding('keyword_repetition', 'warning', 'Фраза повторена 5 разів', language='uk', variant='desktop', block=2,
                         evidence='GPU-сервер ASUS', suggestion='Залишити точну назву в Hero та підсумку', source='seo')
    assert example['key'] and example['block'] == 2 and example['language'] == 'uk'
    score, summary, issues, _ = report_from_findings([example])
    assert score == 93 and 'GPU-сервер ASUS' in issues[0] and '[warning]' in issues[0]


def test_critical_blocks_approve_and_warning_is_accepted_only_with_comment():
    critical = sg.finding('alt_missing', 'critical', 'Зображення без alt', language='uk', variant='desktop', source='seo')
    warning = sg.finding('long_sentence', 'warning', 'Задовге речення', language='uk', variant='desktop', source='human')
    reports = [{'type': 'seo', 'findings': [critical, warning]}, {'type': 'llm', 'findings': [sg.finding('x', 'critical', 'AI думає', source='llm')]}]
    arts = [SimpleNamespace(html=GOOD_UK, language='ua', variant='desktop', fallback_reason='')]
    blockers = approval_blockers(reports, arts, {})
    assert len(blockers) == 1 and 'alt' in blockers[0]  # LLM-рецензія не є воротами
    assert approval_blockers(reports, arts, {critical['key']: {'state': 'resolved'}}) == []
    assert validate_decision(critical, 'accepted', 'ок') == 'Критичну знахідку не можна прийняти - її потрібно виправити'
    assert validate_decision(warning, 'accepted', '') != ''
    assert validate_decision(warning, 'accepted', 'речення довге, але це технічний перелік') == ''
    assert validate_decision(warning, 'resolved', '') == ''
    fallback = [SimpleNamespace(html=GOOD_UK, language='ua', variant='desktop', fallback_reason='no key')]
    assert approval_blockers([], fallback, {}) and 'аварійний шаблон' in approval_blockers([], fallback, {})[0]


def test_text_edit_reruns_free_checks_and_paid_critic_stays_paid_and_budgeted():
    from pathlib import Path
    main = (Path(__file__).resolve().parents[1] / 'apps/api/app/main.py').read_text(encoding='utf-8')
    saver = main[main.index('def _save_artifact_version'):main.index('@app.get(\'/api/models\')')]
    assert '_free_audit(db, project, user' in saver and 'llm_critic' not in saver
    critic = main[main.index("@app.post('/api/projects/{project_id}/critic')"):main.index('class FindingDecisionIn')]
    assert 'check_budget(); check_user_budget(user)' in critic and 'add_user_spend(user.id, cost)' in critic
    assert 'llm_critic_full' in critic and critic.index('if payload.llm:') < critic.index('_free_audit(db, p)')


def test_llm_critic_full_parses_extended_json_and_counts_tokens():
    from app.pipeline import llm_critic_full

    class FakeResponse:
        output_text = json.dumps({'score': 71, 'summary': 'Є калька', 'categories': {'facts': 90, 'human_copy': 60, 'seo': 80, 'geo': 75, 'language': 55},
                                  'issues': [{'code': 'calque', 'severity': 'warning', 'language': 'pl', 'variant': 'desktop',
                                              'quote': 'Na dzień dzisiejszy', 'reason': 'калька', 'suggestion': 'Obecnie'}],
                                  'suggestions': ['Переписати вступ']}, ensure_ascii=False)
        usage = SimpleNamespace(input_tokens=900, output_tokens=120)

    page = SimpleNamespace(html=PL_CLEAN, language='pl', variant='desktop')
    with patch('app.pipeline._responses_create', lambda model, prompt, cap: FakeResponse()), patch('app.pipeline.text_ready', lambda: True):
        r = llm_critic_full([page], PRODUCT, 'gpt-5-mini', BRIEF, PROFILE)
    assert r['score'] == 71 and r['categories']['language'] == 55 and r['input_tokens'] == 900 and r['output_tokens'] == 120
    assert r['findings'][0]['code'] == 'calque' and r['findings'][0]['evidence'] == 'Na dzień dzisiejszy' and r['findings'][0]['source'] == 'llm'
    assert r['issues'] == ['калька - «Na dzień dzisiejszy»']


# ---------------------------------------------------------------------------
# SEO brief and prompt boundaries
# ---------------------------------------------------------------------------

def test_auto_brief_does_not_invent_search_volume_and_import_keeps_a_dated_snapshot():
    brief = build_seo_brief(PRODUCT, language='ua', profile=PROFILE, source='auto')
    assert brief['primary_topic'] == 'GPU-сервери' and 'ASUS' in brief['entities'] and brief['buyer_questions']
    assert brief['keywords'] == [] and brief['source'] == 'auto' and brief['collected_at']
    csv_text = 'Top queries,Clicks,Impressions,Position\ngpu сервер для ai,120,5400,6.2\nсервер для llm,30,900,12\n'
    rows = import_keyword_data(csv_text, 'csv', 'gsc')
    assert rows[0] == {'query': 'gpu сервер для ai', 'clicks': 120.0, 'impressions': 5400.0, 'position': 6.2, 'source': 'gsc'}
    imported = brief_from_keywords(rows, PRODUCT, 'ua', 'gsc', ['UA'], PROFILE)
    assert imported['primary_topic'] == 'gpu сервер для ai' and imported['secondary_topics'] == ['сервер для llm'] and imported['source'] == 'gsc'
    assert imported['keywords'][0]['clicks'] == 120.0 and imported['collected_at']
    dfs = json.dumps({'tasks': [{'result': [{'items': [{'keyword': 'serwer gpu', 'keyword_info': {'search_volume': 320, 'cpc': 1.2, 'competition': 0.4},
                                                       'search_intent_info': {'main_intent': 'commercial'}}]}]}]})
    rows = import_keyword_data(dfs, 'json', 'dataforseo')
    assert rows[0]['query'] == 'serwer gpu' and rows[0]['search_volume'] == 320 and rows[0]['intent'] == 'commercial'
    with pytest.raises(ValueError):
        import_keyword_data('a,b\n1,2\n', 'csv', 'gsc')


def test_prompt_carries_contract_brief_and_company_facts_as_separate_sections():
    from app.pipeline import build_prompt
    style = SimpleNamespace(prompt='STYLE', hero_prompt='', feature_prompt='', negative_prompt='', golden_html='', name='X')
    product = dict(PRODUCT, evidence=[{'id': 'spec_вага', 'label': 'Вага', 'value': '48 кг', 'confidence': 'derived', 'source_type': 'page_text'}],
                   specs=PRODUCT['specs'] + [{'name': 'Вага', 'value': '48 кг'}])
    text = build_prompt(product, style, 'pl', 'desktop', '/h.webp', '/f.webp', brief=BRIEF, company=PROFILE)
    for marker in ('HUMAN COPY CONTRACT', 'SOURCE BOUNDARIES', 'PRODUCT FACTS', 'SEO BRIEF', 'VERIFIED COMPANY FACTS', 'a search query is not a fact'):
        assert marker in text
    assert text.rindex('SEO BRIEF (') < text.rindex('VERIFIED COMPANY FACTS (') < text.rindex('PRODUCT FACTS\n')
    assert 'Dostarczamy sprzęt na terenie Ukrainy i Polski.' in text and 'GPU-сервер для локального AI' in text
    assert '48 кг' not in text and '"evidence"' not in text  # derived і evidence в промпт не йдуть
    empty = build_prompt(PRODUCT, style, 'ua', 'desktop', '/h', '/f')
    assert 'SEO BRIEF: none' in empty and 'VERIFIED COMPANY FACTS: none' in empty


def test_stacked_cards_in_a_transparent_wrapper_get_the_outer_radius():
    """Скарга власника (2026-10-01): на мобільному Showcase плитки значень під Hero
    мали 10-12px, а Hero 14px - у одній колонці стояли картки з різними кутами."""
    from app.artline_standard import apply_artline_standard, radius_deviations
    page = ('<section>'
            '<div style="border-radius:14px;background:#1A2128;padding:20px">'
            '<span style="display:inline-flex;border:1px solid #19BCC9;border-radius:8px;padding:6px 14px">ASUS · КОРПУС</span>'
            '<img src="/h.webp" style="border-radius:12px"><span style="border-radius:999px;background:#fff">M.2</span></div>'
            '<div style="display:grid;gap:12px">'
            '<div style="border-radius:10px;background:#1A2128;padding:20px">M.2 2230-2280</div>'
            '<div style="border-radius:12px;background:#FFFFFF;border:1px solid #D0D7DE;padding:20px">124.5×47.7×10.9 мм</div></div>'
            '<div style="border-radius:14px;background:#F5F7FA;padding:24px"><div style="border-radius:16px;background:#fff">Внутрішня</div></div>'
            '</section>')
    flagged = radius_deviations(page)
    assert any('M.2 2230-2280' in f and 'зовнішній' in f for f in flagged)
    out = apply_artline_standard(page)
    assert radius_deviations(out) == []
    assert 'border-radius:14px;background:#1A2128;padding:20px">M.2' in out
    assert 'border-radius:14px;background:#FFFFFF' in out
    assert 'border-radius:12px;background:#fff">Внутрішня' in out          # картка в картці - 10-12
    assert 'border-radius:999px;padding:6px 14px' in out                    # лейбл - бейдж-пігулка, не зовнішня поверхня
    assert 'border-radius:999px' in out and 'src="/h.webp" style="border-radius:12px"' in out


def test_problem_report_is_markdown_for_triage_and_merges_variants():
    from app.report import build_problem_report
    crit = sg.finding('alt_missing', 'critical', 'Зображення без alt', language='uk', variant='desktop', block=1,
                      evidence='/media/p/f.webp', suggestion='Описати фото', segment='a1', source='seo')
    crit_m = dict(sg.finding('alt_missing', 'critical', 'Зображення без alt', language='uk', variant='mobile', block=1,
                             evidence='/media/p/f.webp', suggestion='Описати фото', segment='a1', source='seo'))
    warn = sg.finding('long_sentence', 'warning', 'Задовге речення | з вертикальною рискою', language='pl', variant='desktop', block=0,
                      evidence='Bardzo długie zdanie', source='human')
    critics = [{'type': 'seo', 'score': 50, 'summary': 'alt', 'findings': [crit, crit_m], 'issues': []},
               {'type': 'human', 'score': 93, 'summary': 'довге', 'findings': [warn], 'issues': []},
               {'type': 'marketing', 'score': 90, 'summary': 'бренд', 'findings': [], 'issues': ['Забагато повторів бренду на сторінку']}]
    arts = [SimpleNamespace(language='ua', variant='desktop', version=3, html=GOOD_UK, fallback_reason=''),
            SimpleNamespace(language='ua', variant='mobile', version=2, html=GOOD_UK, fallback_reason='no key')]
    decisions = {warn['key']: {'state': 'accepted', 'comment': 'технічний перелік'}}
    md = build_problem_report({'id': 'p1', 'name': 'Тест', 'languages': ['ua'], 'variants': ['desktop', 'mobile'], 'status': 'review'},
                              critics=critics, decisions=decisions, blockers=approval_blockers(critics, arts, decisions),
                              artifacts=arts, radius={'UA desktop v3': [], 'UA mobile v2': ['<div> зовнішній блок 8px, норма 14px']},
                              studio_url='http://studio:3000', version='12.5')
    assert md.startswith('# Дефекти: Тест') and '**Схвалення: ЗАБЛОКОВАНО.**' in md
    assert '| D-01 | КРИТИЧНО | SEO | UA · десктоп + мобільна · блок 2 | Зображення без alt | відкрито |' in md
    details = md.split('## Деталі')[1].split('## Радіуси')[0]
    assert details.count('### D-') == 3 and details.count('Зображення без alt') == 1  # дві копії alt - один дефект
    assert 'фрагмент редактора `a1`' in md and '- [ ] **Зображення без alt**' in md
    assert 'Задовге речення \\| з вертикальною рискою' in md            # таблиця не ламається
    assert '- [x] **Задовге речення | з вертикальною рискою**' in md and 'Рішення: прийнято - технічний перелік' in md
    assert 'Забагато повторів бренду' in md                               # старі звіти без findings теж у звіті
    assert '## Аварійний шаблон замість стилю' in md and 'UA mobile v2: no key' in md
    assert '**UA mobile v2** - поза стандартом: 1' in md and '[відкрити в студії](http://studio:3000/projects/p1)' in md
    rows = [line for line in md.splitlines() if line.startswith('| D-')]
    assert len(rows) == 3, rows                                            # 2 копії alt склеєно в одну


def test_badges_and_chips_share_one_pill_shape():
    """Скарга власника (2026-10-01, Qube G25F240S): лейбл «QUBE · МОНІТОР» був
    прямокутником 8-10px поруч із круглими чипами «240Hz». Стандарт: бейджі - пігулки."""
    from app.artline_standard import apply_artline_standard, radius_deviations
    from app.pipeline import _finalize_showcase_layout
    page = ('<section><div style="border-radius:14px;background:#1A2128;padding:20px">'
            '<div style="display:inline-flex;padding:6px 14px;border:1px solid #19BCC9;border-radius:8px">QUBE · Монітор</div>'
            '<span style="display:inline-block;padding:7px 14px;border-radius:999px;background:#fff">240Hz</span>'
            '<div style="border-radius:12px;background:#fff;padding:12px"><h3>240Hz</h3><p>Плавність руху без розривів.</p></div></div>'
            '<div style="border-radius:14px;background:#F5F7FA;padding:20px"><h2>Яскравість</h2><p>400 cd/m² для денного світла.</p></div></section>')
    assert any('бейдж 8px' in d for d in radius_deviations(page))
    out = apply_artline_standard(page)
    assert 'border-radius:999px">QUBE' in out and radius_deviations(out) == []
    assert 'border-radius:12px;background:#fff;padding:12px' in out     # картка не стає пігулкою
    from app.prompts import SHOWCASE_STYLE_PROMPT
    assert 'border:1px solid #19BCC9;border-radius:999px' in SHOWCASE_STYLE_PROMPT
    pipeline = (Path(__file__).resolve().parents[1] / 'apps/api/app/pipeline.py').read_text(encoding='utf-8')
    assert "'border:1px solid #19BCC9;border-radius:999px;box-sizing:border-box;'" in pipeline


def test_brand_model_label_repeated_by_design_is_not_a_duplicate_sentence():
    html = ('<section><div><span>QUBE · G25F240S</span><h2>QUBE G25F240S</h2><p>Висока частота оновлення робить динамічні сцени плавнішими.</p></div>'
            '<div><span>QUBE · G25F240S</span><p>Монітор для ігор, де важлива швидкість реакції.</p></div></section>')
    assert not [f for f in audit_human_copy(html, 'ua') if f['code'] == 'duplicate_sentence']
    twice = html.replace('Монітор для ігор, де важлива швидкість реакції.', 'Висока частота оновлення робить динамічні сцени плавнішими.')
    assert [f for f in audit_human_copy(twice, 'ua') if f['code'] == 'duplicate_sentence']
