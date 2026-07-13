from io import BytesIO
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image

from types import SimpleNamespace

from app.pipeline import _deterministic_html, _gallery_identity, _html_only, _translation_template, inspect_product_references, parse_page, translate_html


def image_bytes(size=(600, 600), color=(245, 245, 245)):
    buffer = BytesIO()
    Image.new('RGB', size, color).save(buffer, format='WEBP', quality=60)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    payloads = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        return FakeResponse(self.payloads[url])


def test_primary_gallery_identity_wins_even_when_file_is_smaller_than_20kb():
    primary = 'https://cdn.example/images/products/1/gallery/510525/600_gallery_main.webp'
    primary_1400 = 'https://cdn.example/images/products/1/gallery/510525/1400_gallery_main.webp'
    infographic = 'https://cdn.example/images/products/1/gallery/510527/1400_gallery_specs.webp'
    FakeClient.payloads = {
        primary: image_bytes((600, 600)),
        primary_1400: image_bytes((1400, 1400)),
        infographic: image_bytes((1800, 1800), (220, 220, 220)),
    }
    assert len(FakeClient.payloads[primary]) < 20_000

    with patch('app.pipeline.httpx.Client', FakeClient):
        ranked = inspect_product_references([primary, infographic, primary_1400], primary)

    assert ranked[0]['url'] == primary_1400
    assert ranked[0]['matches_primary'] is True
    assert _gallery_identity(ranked[0]['url']) == _gallery_identity(primary)


def test_parse_page_collects_jsonld_primary_and_high_resolution_gallery_variant_first():
    primary = 'https://cdn.example/gallery/510525/600_gallery_main.webp'
    primary_1400 = 'https://cdn.example/gallery/510525/1400_gallery_main.webp'
    other = 'https://cdn.example/gallery/510527/1400_gallery_specs.webp'
    markup = f'''<!doctype html><html><head>
      <script type="application/ld+json">{{"@type":"Product","name":"Test","image":"{primary}"}}</script>
    </head><body><main>
      <div class="product-slider__view"><a href="{primary_1400}"><img src="{primary}" alt="Test"></a></div>
      <div class="product-slider__view"><a href="{other}"><img src="{other}" alt="Specs"></a></div>
    </main></body></html>'''

    product, images, _, _ = parse_page(markup, 'https://shop.example/product')

    assert product['name'] == 'Test'
    assert images[0] == primary
    assert primary_1400 in images[:3]
    first_other = images.index(other)
    assert all(_gallery_identity(url) == _gallery_identity(primary) for url in images[:first_other])


def test_parse_page_recovers_product_jsonld_with_trailing_template_brace():
    primary = 'https://cdn.example/gallery/10/600_gallery_main.webp'
    markup = f'''<html><head><script type="application/ld+json">
      {{"@context":"https://schema.org","@type":"Product","name":"Recovered product","image":"{primary}"}}}}
    </script></head><body><main><h1>Recovered product</h1></main></body></html>'''

    product, images, _, _ = parse_page(markup, 'https://shop.example/product')

    assert product['name'] == 'Recovered product'
    assert images[0] == primary


def test_rich_content_never_contains_document_level_h1():
    normalized = _html_only('<section><h1>Product</h1><p>Copy</p></section>')
    fallback = _deterministic_html(
        {'name': 'Product', 'description': 'Description', 'features': [], 'specs': []},
        SimpleNamespace(prompt=''),
        'ru',
        'desktop',
        '',
        '',
    )

    assert '<h1' not in normalized.lower()
    assert '<h1' not in fallback.lower()
    assert '<h2>Product</h2>' in normalized


def test_translation_template_changes_copy_without_changing_layout_or_assets():
    source = '''<section style="max-width:1240px"><!-- 1. HERO --><div style="display:grid"><h2>Product title</h2><p>Product benefit</p><img src="/media/p/hero-desktop.webp" alt="Product"></div></section>'''
    template, segments = _translation_template(source)

    assert segments == {'0': 'Product title', '1': 'Product benefit'}
    assert '__ARTLINE_TEXT_0__' in template
    assert '__ARTLINE_TEXT_1__' in template
    assert 'style="display:grid"' in template
    assert 'src="/media/p/hero-desktop.webp"' in template
    assert '<!-- 1. HERO -->' in template


def test_language_translation_preserves_dom_styles_and_image_urls():
    source = '''<section style="max-width:1240px"><!-- 1. HERO --><div style="display:grid"><h2>Мощное решение</h2><p>Удобная работа каждый день</p><img src="/media/p/hero-desktop.webp" alt="Product"></div></section>'''

    class FakeResponses:
        def create(self, **_kwargs):
            return SimpleNamespace(
                output_text='{"0":"Потужне рішення","1":"Зручна робота щодня"}',
                usage=SimpleNamespace(input_tokens=20, output_tokens=10),
            )

    fake_client = SimpleNamespace(responses=FakeResponses())
    with patch('app.pipeline.client', fake_client):
        translated, input_tokens, output_tokens = translate_html(source, 'ua', 'test-model')

    source_tags = [(tag.name, dict(tag.attrs)) for tag in BeautifulSoup(source, 'html.parser').find_all(True)]
    translated_tags = [(tag.name, dict(tag.attrs)) for tag in BeautifulSoup(translated, 'html.parser').find_all(True)]
    assert translated_tags == source_tags
    assert 'Потужне рішення' in translated
    assert 'Зручна робота щодня' in translated
    assert '<!-- 1. HERO -->' in translated
    assert input_tokens == 20
    assert output_tokens == 10
