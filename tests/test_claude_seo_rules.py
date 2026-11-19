"""Правила з claude-seo (github.com/AgriciDaniel/claude-seo, коміт 468ed5b), аудит 2026-11-19.

Звіт: docs/audits/claude-seo.md. Лендинги: og:image, опис, заглушки, дублікати тегів,
гігієна JSON-LD, змішаний вміст. Рич: відсотки й кратності без джерела, довжина alt,
звертання, десятковий роздільник, імперські одиниці, паритет мовних версій,
невидимі символи. Кожне правило має і перевірку без хибного спрацювання.
"""
from app.pipeline import localize_decimals, sanitize_html, strip_invisible
from app.seo_geo import (
    audit_geo_copy, audit_human_copy, audit_landing_document, audit_language_quality, audit_rich_fragment,
    audit_translation_parity, build_landing_metadata, finalize_landing_seo,
)
from app.stop_slop import audit_stop_slop

PRODUCTS = [{'name': 'SSD Goodram IRDM 1TB', 'url': 'https://artline.ua/p/1', 'image': 'https://img.artline.ua/1.webp'},
            {'name': 'SSD Kingston NV3 1TB', 'url': 'https://artline.ua/p/2', 'image': 'https://img.artline.ua/2.webp'}]
CANON = 'https://artline.ua/promo/ssd'
PRODUCT = {'name': 'Тихий вентилятор DeepCool FC120', 'brand': 'DeepCool', 'model': 'FC120', 'category': 'Вентилятори',
           'specs': [{'name': 'Шум', 'value': '25 дБ'}, {'name': 'Вага', 'value': '2,5 кг'}]}


def _codes(findings):
    return {f['code'] for f in findings}


def _landing(campaign: dict, body: str = '<h1>Тиждень SSD</h1><p>Акція на SSD: два накопичувачі для дому й роботи.</p>') -> str:
    html = f'<!doctype html><html lang="uk"><head></head><body>{body}</body></html>'
    return finalize_landing_seo(html, campaign=campaign, products=PRODUCTS, profile={}, language='ua', canonical=CANON, published=True)


def _audit(page: str) -> set:
    return _codes(audit_landing_document(page, language='ua', expected_canonical=CANON, published=True))


def test_studio_hero_never_becomes_og_image():
    page = _landing({'name': 'Тиждень SSD', 'campaign_title': 'Тиждень SSD', 'hero_url': '/media/landings/1/hero.webp'})
    head = page.split('</head>')[0]
    assert 'content="https://img.artline.ua/1.webp"' in head and '/media/' not in head
    assert 'og_image_unreachable' not in _audit(page)
    cdn = _landing({'name': 'Тиждень SSD', 'hero_url': 'https://img.artline.ua/hero.webp'})
    assert 'content="https://img.artline.ua/hero.webp"' in cdn


def test_description_does_not_restate_title_and_brand_is_not_doubled():
    meta = build_landing_metadata({'campaign_title': 'Тиждень SSD'}, PRODUCTS, {}, 'ua', CANON)
    assert not meta['description'].startswith('Тиждень SSD') and 'SSD Goodram IRDM 1TB' in meta['description']
    assert build_landing_metadata({'campaign_title': 'ARTLINE Days'}, PRODUCTS, {}, 'ua', CANON)['title'] == 'ARTLINE Days'
    page = _landing({'campaign_title': 'Тиждень SSD'})
    restated = page.replace('name="description"', 'data-x="1" name="description"').replace(
        'content="2 товарів', 'content="Тиждень SSD: 2 товарів', 1)
    assert 'description_restates_title' in _audit(restated)


def test_landing_placeholders_duplicate_tags_and_mixed_content():
    body = ('<h1>Тиждень SSD</h1><p>Акція на SSD: два накопичувачі для дому й роботи.</p><p>Кнопка {BUY}</p>'
            '<img src="http://img.artline.ua/x.webp" alt="SSD Goodram IRDM 1TB на столі"><title>Друга назва</title>')
    assert {'placeholder_text', 'mixed_content', 'duplicate_head_tag'} <= _audit(_landing({'campaign_title': 'Тиждень SSD'}, body))
    clean = _audit(_landing({'campaign_title': 'Тиждень SSD'}))
    assert not clean & {'placeholder_text', 'mixed_content', 'duplicate_head_tag', 'jsonld_context', 'jsonld_relative_url',
                        'jsonld_no_type', 'jsonld_deprecated_type', 'og_image_unreachable', 'description_restates_title'}, clean


def test_jsonld_hygiene():
    page = _landing({'campaign_title': 'Тиждень SSD'}).replace(
        '</head>', '<script type="application/ld+json">{"@context": "http://example.org", "@type": "HowTo", "url": "/promo"}</script></head>', 1)
    assert {'jsonld_context', 'jsonld_deprecated_type', 'jsonld_relative_url'} <= _audit(page)


def _fragment(text: str, extra: str = '') -> str:
    return ('<section><div><h2>DeepCool FC120</h2><p>Тихий вентилятор DeepCool FC120 для корпусу ПК з шумом 25 дБ.</p></div>'
            f'<div><h2>Тиша</h2><p>{text}</p>{extra}</div></section>')


def test_percent_and_multiplier_claims_need_a_source():
    for text in ('Вентилятор на 40% тихіший за попередню модель.', 'Повітряний потік у 3 рази сильніший.'):
        assert 'claim_without_provenance' in _codes(audit_geo_copy(_fragment(text), PRODUCT, 'ua')), text
    for text in ('Комплект: 4× гвинти й адаптер.', 'Розмір рамки 120×120 мм.', 'Шум 25 дБ на мінімальних обертах.'):
        assert 'claim_without_provenance' not in _codes(audit_geo_copy(_fragment(text), PRODUCT, 'ua')), text


def test_placeholder_and_alt_length_in_fragment():
    bad = _fragment('Lorem ipsum dolor sit amet.', '<img src="/a.webp" alt="FC120">')
    assert {'placeholder_text', 'alt_length'} <= _codes(audit_rich_fragment(bad, PRODUCT, 'ua'))
    good = _fragment('Шум 25 дБ.', '<img src="/a.webp" alt="Вентилятор DeepCool FC120 з чорною рамкою">')
    assert not _codes(audit_rich_fragment(good, PRODUCT, 'ua')) & {'placeholder_text', 'alt_length'}


def test_language_rules_address_decimals_imperial():
    codes = lambda text, lang='ua': _codes(audit_language_quality(_fragment(text), lang, product=PRODUCT))  # noqa: E731
    assert 'address_form_mixed' in codes('Ти почуєш різницю, а ваш корпус лишиться прохолодним.')
    assert 'address_form_mixed' not in codes('Ваш корпус лишиться прохолодним.')
    assert 'decimal_separator' in codes('Вага 2.5 кг.')
    assert 'decimal_separator' not in codes('Вага 2,5 кг, USB 3.2.')
    assert 'decimal_separator' in codes('Weight 2,5 kg.', 'en')
    assert 'imperial_units' in codes('Вага 5.5 lbs.')


def test_localize_decimals_touches_only_visible_values():
    html = '<div style="width:1.5px;line-height:1.6"><p>Вага 2.5 кг, USB 3.2, 1,000 mAh</p></div>'
    assert localize_decimals(html, 'ua') == '<div style="width:1.5px;line-height:1.6"><p>Вага 2,5 кг, USB 3.2, 1,000 mAh</p></div>'
    assert localize_decimals('<p>Weight 2,5 kg, 1,000 mAh</p>', 'en') == '<p>Weight 2.5 kg, 1,000 mAh</p>'


def test_translation_parity_values_and_untranslated_segments():
    uk = _fragment('Вентилятор має шум 25 дБ і вагу 1 600 г для великого корпусу.')
    en_ok = (uk.replace('Тихий вентилятор DeepCool FC120 для корпусу ПК з шумом 25 дБ.', 'Quiet DeepCool FC120 PC case fan, 25 dB.')
               .replace('Вентилятор має шум 25 дБ і вагу 1 600 г для великого корпусу.', 'The fan runs at 25 dB and weighs 1,600 g for a large case.')
               .replace('Тиша', 'Silence'))
    arts = lambda en: [{'language': 'ua', 'variant': 'desktop', 'html': uk}, {'language': 'en', 'variant': 'desktop', 'html': en}]  # noqa: E731
    assert audit_translation_parity(arts(en_ok)) == []
    assert 'translation_values_mismatch' in _codes(audit_translation_parity(arts(en_ok.replace('25 dB and', '30 dB and'))))
    partly = en_ok.replace('The fan runs at 25 dB and weighs 1,600 g for a large case.',
                           'Вентилятор має шум 25 дБ і вагу 1 600 г для великого корпусу.')
    assert 'untranslated_segment' in _codes(audit_translation_parity(arts(partly)))


def test_invisible_characters_are_stripped():
    assert strip_invisible('Тихий​ вентилятор­﻿') == 'Тихий вентилятор'
    assert '​' not in sanitize_html('<p>25​ дБ</p>') and ' ' in sanitize_html('<p>25 дБ</p>')


def test_new_ai_cliches_and_connective_openers():
    page = _fragment('Крім того, вентилятор розкриває потенціал корпусу.')
    assert 'generic_phrase' in _codes(audit_human_copy(page, 'ua', product=PRODUCT))
    assert 'slop_connective_opener' in _codes(audit_stop_slop(page, 'ua', product=PRODUCT))
