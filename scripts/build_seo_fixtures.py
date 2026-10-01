#!/usr/bin/env python3
"""Фіксовані тестові сторінки для Lighthouse CI, Lychee і перевірок head/JSON-LD.

Будує в ``build/seo-fixtures/``:

* ``landing-draft.html`` - чернетка лендінгу (має бути noindex, без canonical);
* ``landing-published-<lang>.html`` - опублікований експорт UA/PL/EN (canonical,
  hreflang, index, JSON-LD) - на них ганяються Lighthouse CI і Lychee;
* ``rich-wrapper-<lang>.html`` - rich-фрагмент у тестовій оболонці, що імітує
  картку товару artline.ua (свій h1, title, canonical): Lighthouse не можна
  запускати на голому фрагменті без host page.

``--check`` перевіряє побудовані файли детермінованими аудитами (JSON-LD
парситься, draft noindex, published canonical/hreflang, метадані UA/PL/EN,
жодних зашитих комерційних тверджень) і падає з ненульовим кодом.

Без мережі, без БД, без ключів: усе з вбудованого профілю ARTLINE і
детермінованих шаблонів. Live-crawl бойового сайту тут НЕ виконується.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))

from app.landing import deterministic_landing  # noqa: E402
from app.pipeline import _deterministic_html  # noqa: E402
from app.seo_geo import (  # noqa: E402
    DEFAULT_PUBLISHING_PROFILE, DELIVERY_STATEMENTS, audit_landing_document, audit_rich_fragment, finalize_landing_seo,
    norm_lang, run_rich_audits,
)
from types import SimpleNamespace  # noqa: E402

OUT = ROOT / 'build' / 'seo-fixtures'
CANON = {'uk': 'https://artline.ua/uk/solution/test-campaign', 'pl': 'https://artline.ua/pl/solution/test-campaign',
         'en': 'https://artline.ua/en/solution/test-campaign'}
ALTS = dict(CANON, **{'x-default': CANON['uk']})
CAMPAIGN = {'name': 'Test campaign', 'campaign_title': 'Знижки на 3D-принтери', 'campaign_subtitle': 'Тестова кампанія для CI',
            'period': '01.10-31.10'}
CAMPAIGN_L10N = {'pl': ('Rabaty na drukarki 3D', 'Kampania testowa dla CI'), 'en': ('3D printer deals', 'Test campaign for CI')}
PRODUCTS = [
    {'name': 'Test Printer P1', 'url': 'https://artline.ua/uk/product/test-printer-p1', 'image': '', 'price': '29999', 'price_text': '29 999 ₴', 'currency': 'UAH'},
    {'name': 'Test Printer A1 mini', 'url': 'https://artline.ua/uk/product/test-printer-a1-mini', 'image': '', 'price': '', 'price_text': ''},
]
PRODUCT = {
    'name': 'Test GPU Server TGS-8000', 'brand': 'TestBrand', 'category': 'GPU-сервери',
    'description': 'Сервер для машинного навчання.',
    'features': ['Підтримка 8 GPU', 'Резервоване живлення 2 × 3000 Вт'],
    'specs': [{'name': 'GPU', 'value': '8 × TestGPU T300'}, {'name': 'Блок живлення', 'value': '2 × 3000 Вт'}, {'name': 'Форм-фактор', 'value': '4U'}],
}
WRAPPER_L10N = {
    'uk': ('Купити Test GPU Server TGS-8000 - ARTLINE', 'Test GPU Server TGS-8000', 'Тестова картка товару'),
    'pl': ('Kup Test GPU Server TGS-8000 - ARTLINE', 'Test GPU Server TGS-8000', 'Testowa karta produktu'),
    'en': ('Buy Test GPU Server TGS-8000 - ARTLINE', 'Test GPU Server TGS-8000', 'Test product page'),
}


def landing_html(lang: str, published: bool) -> str:
    campaign = dict(CAMPAIGN, language=lang)
    if lang in CAMPAIGN_L10N:
        campaign['campaign_title'], campaign['campaign_subtitle'] = CAMPAIGN_L10N[lang]
    html = deterministic_landing(campaign, PRODUCTS, [], DEFAULT_PUBLISHING_PROFILE)
    code = norm_lang(lang)
    return finalize_landing_seo(html, campaign=campaign, products=PRODUCTS, profile=DEFAULT_PUBLISHING_PROFILE, language=lang,
                                canonical=CANON[code] if published else '', alternates=ALTS if published else {}, published=published)


def rich_wrapper(lang: str) -> str:
    """Тестова host page у дусі картки artline.ua: document-level SEO належить їй."""
    code = norm_lang(lang)
    style = SimpleNamespace(prompt='', name='Fixture', golden_html='')
    fragment = _deterministic_html(PRODUCT, style, lang, 'desktop', 'placeholder-hero.svg', 'placeholder-feature.svg')
    title, h1, crumb = WRAPPER_L10N[code]
    canonical = f'https://artline.ua/{code}/product/test-gpu-server'
    return f'''<!doctype html>
<html lang="{code}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{crumb}: {h1}. {DELIVERY_STATEMENTS[code]}">
<link rel="canonical" href="{canonical}">
<meta name="robots" content="index,follow">
<style>body{{margin:0;font-family:Montserrat,Arial,sans-serif;color:#101010;background:#fff}}header,main,footer{{max-width:1240px;margin:0 auto;padding:16px}}nav a{{color:#157985}}img{{max-width:100%;height:auto}}</style>
</head>
<body>
<header><nav aria-label="breadcrumb"><a href="{canonical}">{crumb}</a></nav><h1>{h1}</h1><p>29 999 ₴</p></header>
<main>
<!-- RICH FRAGMENT START (this is what the studio produces; the host page owns h1/title/canonical) -->
{fragment}
<!-- RICH FRAGMENT END -->
</main>
<footer><p>{DELIVERY_STATEMENTS[code]}</p></footer>
</body>
</html>'''


PLACEHOLDER = ('<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
               '<rect width="100%" height="100%" fill="#F5F7FA"/><rect x="12%" y="18%" width="76%" height="64%" rx="24" fill="#D0D7DE"/></svg>')


def build() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    (OUT / 'placeholder-hero.svg').write_text(PLACEHOLDER.format(w=1536, h=1024), encoding='utf-8')
    (OUT / 'placeholder-feature.svg').write_text(PLACEHOLDER.format(w=1024, h=1024), encoding='utf-8')
    (OUT / 'landing-draft.html').write_text(landing_html('ua', False), encoding='utf-8')
    written.append(OUT / 'landing-draft.html')
    for lang in ('ua', 'pl', 'en'):
        code = norm_lang(lang)
        path = OUT / f'landing-published-{code}.html'
        path.write_text(landing_html(lang, True), encoding='utf-8')
        written.append(path)
        wrapper = OUT / f'rich-wrapper-{code}.html'
        wrapper.write_text(rich_wrapper(lang), encoding='utf-8')
        written.append(wrapper)
    (OUT / 'index.html').write_text('<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="robots" content="noindex"><title>SEO fixtures</title></head><body><ul>'
                                    + ''.join(f'<li><a href="{p.name}">{p.name}</a></li>' for p in written) + '</ul></body></html>', encoding='utf-8')
    return written


def check() -> int:
    from bs4 import BeautifulSoup
    failures = []

    def expect(condition: bool, message: str):
        if not condition:
            failures.append(message)

    draft = (OUT / 'landing-draft.html').read_text(encoding='utf-8')
    soup = BeautifulSoup(draft, 'html.parser')
    expect('noindex' in (soup.find('meta', attrs={'name': 'robots'}) or {}).get('content', ''), 'draft landing must be noindex')
    expect(soup.find('link', attrs={'rel': 'canonical'}) is None, 'draft landing must not carry canonical')
    for code in ('uk', 'pl', 'en'):
        page = (OUT / f'landing-published-{code}.html').read_text(encoding='utf-8')
        soup = BeautifulSoup(page, 'html.parser')
        expect(soup.find('html').get('lang') == code, f'{code}: html lang')
        expect(bool(soup.find('title') and soup.find('title').get_text().strip()), f'{code}: title')
        expect(bool(soup.find('meta', attrs={'name': 'description'})), f'{code}: description')
        expect((soup.find('link', attrs={'rel': 'canonical'}) or {}).get('href') == CANON[code], f'{code}: canonical')
        hreflang = {l['hreflang']: l['href'] for l in soup.find_all('link', attrs={'rel': 'alternate'})}
        expect(hreflang == ALTS, f'{code}: hreflang set {hreflang}')
        expect((soup.find('meta', attrs={'name': 'robots'}) or {}).get('content', '').startswith('index'), f'{code}: published must be index')
        scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
        expect(bool(scripts), f'{code}: JSON-LD present')
        for script in scripts:
            try:
                data = json.loads(script.string)
                types = [n.get('@type') for n in data.get('@graph', [])]
                expect('Organization' in types and 'ItemList' in types, f'{code}: JSON-LD graph types {types}')
            except Exception as exc:  # noqa: BLE001
                failures.append(f'{code}: JSON-LD does not parse: {exc}')
        expect('24/7' not in page and 'гарант' not in page.lower() and 'gwarancj' not in page.lower() and 'warrant' not in page.lower(),
               f'{code}: no hardcoded warranty / 24/7')
        expect(DELIVERY_STATEMENTS[code] in page, f'{code}: delivery statement from the verified profile')
        findings = audit_landing_document(page, language=code, expected_canonical=CANON[code], expected_alternates=ALTS, published=True,
                                          products=PRODUCTS, profile=DEFAULT_PUBLISHING_PROFILE)
        critical = [f for f in findings if f['severity'] == 'critical']
        expect(not critical, f'{code}: critical landing findings: {[f["code"] for f in critical]}')
        wrapper = (OUT / f'rich-wrapper-{code}.html').read_text(encoding='utf-8')
        start, end = wrapper.index('<!-- RICH FRAGMENT START'), wrapper.index('<!-- RICH FRAGMENT END')
        fragment = wrapper[start:end]
        seo = audit_rich_fragment(fragment, PRODUCT, code)
        expect(not [f for f in seo if f['code'] in ('h1_in_fragment', 'document_seo_in_fragment')], f'{code}: rich fragment carries document-level SEO')
        reports = run_rich_audits([SimpleNamespace(html=fragment, language=code, variant='desktop')], PRODUCT, None, DEFAULT_PUBLISHING_PROFILE)
        geo = next(r for r in reports if r['type'] == 'geo')
        expect(not [f for f in geo['findings'] if f['code'] == 'unsupported_commercial_claim'], f'{code}: rich fragment has unsupported commercial claims')
    if failures:
        print('SEO fixture checks FAILED:\n- ' + '\n- '.join(failures))
        return 1
    print('SEO fixture checks OK')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='після побудови перевірити фікстури детермінованими аудитами')
    args = parser.parse_args()
    for path in build():
        print('built', path.relative_to(ROOT))
    return check() if args.check else 0


if __name__ == '__main__':
    sys.exit(main())
