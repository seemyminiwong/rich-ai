from io import BytesIO
from unittest.mock import patch

from PIL import Image

from types import SimpleNamespace

from app.pipeline import _deterministic_html, _gallery_identity, _html_only, inspect_product_references, parse_page


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
