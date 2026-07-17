import base64
from io import BytesIO
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image

from types import SimpleNamespace

from app.pipeline import _language_matches, _aspect_ratio, _deterministic_html, _gallery_identity, _html_only, _translation_template, generate_image, inspect_product_references, language_rule, parse_page, translate_html
from app.prompts import DEFAULT_FEATURE_PROMPT, DEFAULT_HERO_PROMPT, DEFAULT_STYLE_PROMPT


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
    with patch('app.pipeline.text_client', lambda: (fake_client, 'openai')):
        translated, input_tokens, output_tokens = translate_html(source, 'ua', 'test-model')

    source_tags = [(tag.name, dict(tag.attrs)) for tag in BeautifulSoup(source, 'html.parser').find_all(True)]
    translated_tags = [(tag.name, dict(tag.attrs)) for tag in BeautifulSoup(translated, 'html.parser').find_all(True)]
    assert translated_tags == source_tags
    assert 'Потужне рішення' in translated
    assert 'Зручна робота щодня' in translated
    assert '<!-- 1. HERO -->' in translated
    assert input_tokens == 20
    assert output_tokens == 10


def test_managed_style_prompt_has_the_full_production_contract():
    prompt = DEFAULT_STYLE_PROMPT.lower()

    assert 'never use h1' in prompt
    assert 'seo and generative-engine value' in prompt
    assert 'exactly six sections' in prompt
    assert 'full css background' in prompt
    assert 'never insert the hero asset as an <img>' in prompt
    assert 'strongest confirmed differentiator' in prompt
    assert 'system-text exclusions' in prompt
    assert 'exact brand/model' in prompt
    assert 'content island system' in prompt
    assert 'bare text columns' in prompt
    assert 'translucent dark content island' in prompt


def test_image_prompts_are_reference_first_and_have_distinct_jobs():
    hero = DEFAULT_HERO_PROMPT.lower()
    feature = DEFAULT_FEATURE_PROMPT.lower()

    # The scene comes from the server-picked ENVIRONMENT line. The prompt must
    # never enumerate example environments per category: image models paint the
    # examples into the frame (a 3D printer appeared beside an inverter).
    assert 'environment line of the request' in hero
    assert 'never place equipment of any other product category' in hero
    assert '3d printer' not in hero
    assert 'supplied product is immutable' in hero
    assert 'full-bleed css background' in hero
    assert 'single strongest confirmed product feature' in feature
    assert 'not repeat the hero scene' in feature
    assert 'imaginary internal cutaway' in feature


def test_language_rules_support_presets_and_custom_iso_codes():
    assert 'natural German' in language_rule('de')
    assert 'natural Ukrainian' in language_rule('uk')
    assert "'sv-SE'" in language_rule('sv-SE')


def test_gpt_image_2_omits_unsupported_input_fidelity(tmp_path):
    calls = []

    class FakeImages:
        def edit(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'webp').decode(), url=None)])

    reference = tmp_path / 'reference.png'
    reference.write_bytes(image_bytes((512, 512)))
    fake_client = SimpleNamespace(images=FakeImages())

    with patch('app.pipeline.image_client', lambda: fake_client), patch('app.pipeline.settings.media_dir', str(tmp_path)):
        _, generated, error = generate_image(
            'Create a scene around the exact product', 'project', 'hero-mobile',
            'gpt-image-2-2026-04-21', 'medium', '/media/reference.png',
            reference_path=reference, size='1024x1536',
        )

    assert generated is True
    assert error == ''
    assert 'extra_body' not in calls[0]


def test_gpt_image_1_requests_high_reference_fidelity(tmp_path):
    calls = []

    class FakeImages:
        def edit(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'webp').decode(), url=None)])

    reference = tmp_path / 'reference.png'
    reference.write_bytes(image_bytes((512, 512)))
    fake_client = SimpleNamespace(images=FakeImages())

    with patch('app.pipeline.image_client', lambda: fake_client), patch('app.pipeline.settings.media_dir', str(tmp_path)):
        _, generated, error = generate_image(
            'Create a scene around the exact product', 'project', 'hero-desktop',
            'gpt-image-1', 'medium', '/media/reference.png',
            reference_path=reference, size='1536x1024',
        )

    assert generated is True
    assert error == ''
    assert calls[0]['extra_body'] == {'input_fidelity': 'high'}


def test_gemini_model_routes_to_gemini_and_never_calls_openai(tmp_path):
    """Picking a gemini-* image model must switch provider without any other setting."""
    calls = []

    def fake_edit(model, prompt, reference, mime, size):
        calls.append({'model': model, 'prompt': prompt, 'mime': mime, 'size': size})
        return image_bytes((256, 256))

    def boom():
        raise AssertionError('OpenAI must not be called for a gemini-* model')

    reference = tmp_path / 'reference.png'
    reference.write_bytes(image_bytes((512, 512)))

    with patch('app.pipeline._gemini_edit', fake_edit), patch('app.pipeline.image_client', boom), \
         patch('app.pipeline.runtime_config', lambda force=False: {'gemini_api_key': 'test-key'}), \
         patch('app.pipeline.settings.media_dir', str(tmp_path)):
        url, generated, error = generate_image(
            'Create a scene around the exact product', 'project', 'feature',
            'gemini-2.5-flash-image', 'high', '/media/reference.png',
            reference_path=reference, size='1536x1024',
        )

    assert generated is True, error
    assert url == '/media/project/feature.webp'
    assert calls[0]['model'] == 'gemini-2.5-flash-image'
    assert 'STRICT REFERENCE-IMAGE EDIT' in calls[0]['prompt']
    # Gemini answers in PNG; the page contract is webp like the OpenAI path.
    written = Image.open(tmp_path / 'project' / 'feature.webp')
    assert written.format == 'WEBP'


def test_gemini_maps_pixel_size_to_the_nearest_aspect_ratio():
    assert _aspect_ratio('1536x1024') == '3:2'
    assert _aspect_ratio('1024x1536') == '2:3'
    assert _aspect_ratio('1024x1024') == '1:1'
    assert _aspect_ratio('nonsense') == '1:1'


def test_openai_image_model_never_reaches_the_gemini_path(tmp_path):
    def boom(*_a, **_k):
        raise AssertionError('Gemini must not be called for an OpenAI model')

    class FakeImages:
        def edit(self, **_kwargs):
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(image_bytes((64, 64))).decode(), url=None)])

    reference = tmp_path / 'reference.png'
    reference.write_bytes(image_bytes((512, 512)))
    with patch('app.pipeline._gemini_edit', boom), patch('app.pipeline.image_client', lambda: SimpleNamespace(images=FakeImages())), \
         patch('app.pipeline.settings.media_dir', str(tmp_path)):
        _, generated, error = generate_image(
            'Scene', 'project', 'hero-desktop', 'gpt-image-1', 'medium',
            '/media/reference.png', reference_path=reference, size='1536x1024',
        )
    assert generated is True, error


def test_language_check_tolerates_a_preserved_foreign_name():
    # A Russian page may legitimately keep a Ukrainian product name in the Hero.
    ru_page = (
        '<h2>Гібридний інвертор DEYE SUN-12K-SG05LP3-EU-SM2 Трифазний</h2>'
        '<p>Современное решение для трёхфазной сети 220/380 В, батарея 48 В и два '
        'трекера обеспечивают стабильную выработку и высокий КПД в любых условиях.</p>'
    )
    assert _language_matches(ru_page, 'ru') is True

    # A genuinely Ukrainian page must still be rejected when ru was requested.
    ua_page = (
        '<h2>Гібридний інвертор</h2>'
        '<p>Сучасне рішення для щоденних та професійних задач; ключові характеристики '
        'й переваги подані на основі підтверджених даних товару та специфікацій.</p>'
    )
    assert _language_matches(ua_page, 'ru') is False
    assert _language_matches(ua_page, 'ua') is True
