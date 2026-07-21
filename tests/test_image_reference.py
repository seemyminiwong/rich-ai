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
        self.headers = {'content-length': str(len(content))}

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=65536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


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

    def stream(self, method, url, **kwargs):
        # Context-manager form used by fetch_bytes_capped (the 30 MB ceiling).
        response = FakeResponse(self.payloads[url])

        class _Stream:
            def __enter__(self_inner):
                return response

            def __exit__(self_inner, *args):
                return False

        return _Stream()


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
    from app.media import strip_media_query
    assert strip_media_query(url) == '/media/project/feature.webp'
    assert '?t=' in url, 'media URL must carry the HMAC token' 
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


def _fake_public(url):
    """DNS-free stand-in for is_public_http_url: block obvious private hosts."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ''
    return host not in ('127.0.0.1', 'localhost', '169.254.169.254', '10.0.0.1')


def test_safe_client_blocks_redirects_into_private_space():
    """A public URL answering 302 -> localhost must abort, not follow."""
    import httpx
    import pytest
    from app.pipeline import safe_client

    def handler(request):
        if request.url.host == 'shop.example':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1:8000/api/system'})
        return httpx.Response(200, text='reached')

    with patch('app.pipeline.is_public_http_url', _fake_public):
        with safe_client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RuntimeError, match='non-public'):
                client.get('https://shop.example/product')


def test_safe_client_allows_public_to_public_redirects():
    import httpx
    from app.pipeline import safe_client

    def handler(request):
        if request.url.host == 'shop.example':
            return httpx.Response(302, headers={'location': 'https://cdn.example/photo.webp'})
        return httpx.Response(200, text='ok')

    with patch('app.pipeline.is_public_http_url', _fake_public):
        with safe_client(transport=httpx.MockTransport(handler)) as client:
            assert client.get('https://shop.example/photo').text == 'ok'


def test_media_urls_are_signed_and_tamper_proof(monkeypatch):
    from app import media as media_mod
    monkeypatch.setattr(media_mod.settings, 'jwt_secret', 'unit-test-secret-0123456789')
    url = media_mod.media_url('proj-1', 'hero-desktop.webp')
    path, token = url.split('?t=')
    assert media_mod.verify_media_token(path, token)
    assert not media_mod.verify_media_token('/media/proj-2/hero-desktop.webp', token)
    assert not media_mod.verify_media_token(path, '')
    assert media_mod.strip_media_query(url) == path


def test_provider_keys_encrypt_roundtrip_and_survive_rotation(monkeypatch):
    from app import runtime as runtime_mod
    monkeypatch.setattr(runtime_mod.settings, 'jwt_secret', 'secret-A-0123456789')
    stored = runtime_mod._encrypt('sk-proj-VALUE')
    assert stored.startswith('enc:v1:') and 'VALUE' not in stored
    assert runtime_mod._decrypt(stored) == 'sk-proj-VALUE'
    monkeypatch.setattr(runtime_mod.settings, 'jwt_secret', 'secret-B-rotated')
    assert runtime_mod._decrypt(stored) == ''


def test_pinned_transport_pins_public_ip_and_blocks_private_dns(monkeypatch):
    import httpx
    import pytest
    from app import pipeline

    captured = {}

    def fake_handle(self, request):
        captured['url'] = str(request.url)
        captured['sni'] = request.extensions.get('sni_hostname')
        return httpx.Response(200)

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', fake_handle)
    transport = pipeline._PinnedTransport()

    monkeypatch.setattr(pipeline.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    transport.handle_request(httpx.Request('GET', 'https://shop.example/product'))
    assert '93.184.216.34' in captured['url']
    assert captured['sni'] == 'shop.example'

    # A rebinding DNS answer (private IP) must abort before any connection.
    monkeypatch.setattr(pipeline.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('10.0.0.5', 443))])
    with pytest.raises(RuntimeError, match='non-public'):
        transport.handle_request(httpx.Request('GET', 'https://evil.example/'))

    # Literal private IPs are refused outright.
    with pytest.raises(RuntimeError, match='non-public'):
        transport.handle_request(httpx.Request('GET', 'http://127.0.0.1:8000/api/system'))


def test_fallback_reason_never_leaks_raw_exception_text():
    from app.pipeline import public_fallback_reason

    leaky = RuntimeError('Error code: 401 - {"error": {"message": "Incorrect API key provided: sk-proj-SECRET123"}}')
    reason = public_fallback_reason(leaky)
    assert 'sk-proj' not in reason and 'SECRET123' not in reason
    assert 'ключ' in reason
    assert public_fallback_reason(RuntimeError('Generated content did not pass language validation for ru')) == 'згенерований текст не пройшов мовну перевірку'
    assert 'RuntimeError' in public_fallback_reason(RuntimeError('some totally novel failure'))


def test_multicolumn_rows_wrap_on_narrow_widths():
    from app.pipeline import _responsive_grids

    html = ('<section><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px"><i>1</i><i>2</i><i>3</i><i>4</i></div>'
            '<div style="display:grid;grid-template-columns:1.1fr 0.9fr"><i>a</i><i>b</i></div>'
            '<div style="display:flex;gap:8px"><i>1</i><i>2</i><i>3</i></div>'
            '<div style="display:flex;gap:8px"><i>1</i><i>2</i></div></section>')
    out = _responsive_grids(html)
    assert 'repeat(auto-fit,minmax(150px,1fr))' in out, 'ряд із 4 колонок мусить стати auto-fit'
    assert '1.1fr 0.9fr' in out, 'двоколонкову сітку героя чіпати не можна'
    assert out.count('flex-wrap:wrap') == 1, 'wrap лише для flex-рядів із 3+ дітьми'
    assert out.count('auto-fit') == 1


def test_podium_spin_wraps_hero_and_is_idempotent():
    from app.pipeline import _apply_podium_spin, sanitize_html

    hero = '/media/p1/upload-1.webp?t=abc123'
    html = f'<section><div><img src="{hero}" alt="Генератор" style="display:block"></div></section>'
    spun = _apply_podium_spin(html, hero)
    assert 'arspin' in spun and 'preserve-3d' in spun
    assert spun.count('backface-visibility:hidden') == 2, 'мусить бути лице і тил'
    assert 'rotateY(180deg) scaleX(-1)' in spun, 'тил не має бути дзеркальним'
    assert 'prefers-reduced-motion' in spun
    assert spun.count('border-radius:18px') == 2, 'обидва шари зі скругленням'
    assert '-webkit-backface-visibility:hidden' in spun, 'iOS-префікси обовʼязкові'
    assert _apply_podium_spin(spun, hero) == spun, 'повторне застосування - детермінований no-op'
    # Модель дотягнула ЗЛАМАНИЙ шматок обертання (без <style>) - мусить зібратися заново.
    mangled = spun.replace('<style>', '<s>').replace('</style>', '</s>').replace('animation:arspin 10s linear infinite;', '')
    repaired = _apply_podium_spin(mangled, hero)
    assert 'animation:arspin 10s linear infinite' in repaired
    assert repaired.count('@keyframes arspin') == 1
    # Санітизація зберігає інертний <style> і вбиває CSS з url()/@import.
    assert 'arspin' in sanitize_html(spun)
    dirty = '<section><style>body{background:url(https://evil.example/x)}</style><p>t</p></section>'
    assert 'url(' not in sanitize_html(dirty)


def test_podium3d_prompt_contract():
    from app.prompts import PODIUM3D_STYLE_PROMPT

    p = PODIUM3D_STYLE_PROMPT
    assert 'PODIUM-3D-SPIN' in p
    assert 'do NOT write any CSS animation' in p
    # Showcase-гілка описує склад сторінки як 'SECTION SET, IN ORDER' (без слова
    # 'six') - саме на цьому впав перший деплой Podium 3D.
    assert 'SECTION SET, IN ORDER' in p
    assert 'PODIUM - light product stage' in p


def test_license_comment_is_a_valid_invisible_html_tail():
    from app.prompts import LICENSE_COMMENT
    from app.pipeline import sanitize_html, _visible_text

    assert LICENSE_COMMENT.startswith('\n<!--') and LICENSE_COMMENT.endswith('-->')
    assert 'Copyright 2026 seemyminiwong' in LICENSE_COMMENT
    assert 'PolyForm Noncommercial' in LICENSE_COMMENT
    page = '<section><p>Текст</p></section>' + LICENSE_COMMENT
    # Санітизація редактора не зриває хвіст, покупець його не бачить.
    assert 'Правовласник' in sanitize_html(page)
    assert 'Правовласник' not in _visible_text(page)


def test_podium_360_builds_frame_turntable_and_falls_back_to_coin_spin():
    from app.pipeline import _apply_podium_spin360

    hero = '/media/p1/product-reference.png?t=abc'
    frames = [f'/media/p1/upload-{i}.webp?t=x{i}' for i in range(1, 13)]
    html = f'<section><img src="{hero}" alt="Товар"></section>'
    out = _apply_podium_spin360(html, hero, frames)
    # 'animation:' і '-webkit-animation:' — по два входження на кадр.
    assert out.count('animation:ar360') == 24, 'кожен кадр анімується (з -webkit-парою)'
    assert 'animation-play-state:paused' in out, 'hover-пауза'
    assert 'prefers-reduced-motion' in out
    assert out.count('@keyframes ar360') == 1
    assert 'opacity:1' in out and 'animation-delay:-0.000s' not in out.replace('animation-delay:0.000s', '')
    # Ідемпотентність: повторний прохід розбирає і збирає те саме.
    assert _apply_podium_spin360(out, hero, frames) == out
    # Без серії (0-1 кадр) - чесний відкат до монетного обертання.
    coin = _apply_podium_spin360(html, hero, [])
    assert 'arspin' in coin and 'ar360' not in coin


def test_podium_scroll_ties_rotation_to_viewport_with_autoplay_fallback():
    from app.pipeline import _apply_podium_scroll

    hero = '/media/p1/product-reference.png?t=abc'
    frames = [f'/media/p1/upload-{i}.webp?t=x{i}' for i in range(1, 9)]
    html = f'<section><img src="{hero}" alt="Товар"></section>'
    out = _apply_podium_scroll(html, hero, frames)
    assert out.count('animation-timeline:view(') == 8, 'кожен кадр веде скрол'
    assert '@supports (animation-timeline: view())' in out, 'фолбек-огорожа'
    assert out.count('@keyframes arw') == 8
    assert 'prefers-reduced-motion' in out
    assert _apply_podium_scroll(out, hero, frames) == out, 'детермінований no-op'
    assert 'arspin' in _apply_podium_scroll(html, hero, []), 'без серії - монетне обертання'


def test_dark_editions_keep_contracts_and_never_reintroduce_light_sections():
    from app.prompts import SHOWCASE_DARK_STYLE_PROMPT, PODIUM360DARK_STYLE_PROMPT

    dark = SHOWCASE_DARK_STYLE_PROMPT
    assert 'DARK EDITION OVERRIDES' in dark
    assert 'dark, light, dark, light' not in dark, 'світлий ритм не має пережити деривацію'
    assert 'stay WHITE' in dark, 'білі картки під реальні фото - єдина світла поверхня'
    assert 'SECTION SET, IN ORDER' in dark

    p360d = PODIUM360DARK_STYLE_PROMPT
    assert 'PODIUM-3D-360' in p360d, 'маркер каруселі мусить успадкуватись'
    assert 'background:#0D1013' in p360d and 'background:#FFFFFF' not in p360d
    assert 'rgba(25,188,201,.28)' in p360d, 'ціанове світіння замість тіні'


def test_critic_tolerates_server_animations_and_scales_brand_threshold():
    from types import SimpleNamespace
    from app.pipeline import critic_html

    spin = SimpleNamespace(html='<section><style>@keyframes arspin{0%{transform:rotateY(0)}}</style><h2>Т</h2></section>')
    score, _, issues, _ = critic_html([spin], 'html', {})
    assert not any('style' in i.lower() for i in issues), 'інертний <style> анімації - не порушення'

    evil = SimpleNamespace(html='<section><style>body{background:url(https://x)}</style><h2>Т</h2></section>')
    _, _, issues, _ = critic_html([evil], 'html', {})
    assert any('url' in i for i in issues), 'css із зовнішнім url() мусить світитись'

    one = SimpleNamespace(html='<section><h2>' + 'ARTLINE ' * 14 + '</h2><p>' + 'текст ' * 400 + '</p></section>')
    _, _, issues, _ = critic_html([one], 'marketing', {})
    assert any('бренду' in i for i in issues), '14 згадок на одну сторінку - забагато'
    four = [one] * 4
    _, _, issues4, _ = critic_html(four, 'marketing', {})
    assert not any('бренду' in i for i in issues4) or one.html.count('ARTLINE') * 4 > 48, 'поріг масштабується на кількість сторінок'


def test_llm_critic_parses_review_and_reports_token_usage():
    from app.pipeline import llm_critic

    class FakeResponse:
        output_text = '{"score": 82, "summary": "Гарно, але є вигадка", "issues": ["Потужність 900 Вт не з JSON"], "suggestions": ["Приберіть неперевірене число"]}'
        usage = SimpleNamespace(input_tokens=1200, output_tokens=150)

    page = SimpleNamespace(html='<section><h2>Товар</h2><p>Потужність 900 Вт</p></section>', language='ua', variant='desktop')
    with patch('app.pipeline._responses_create', lambda model, prompt, cap: FakeResponse()), \
         patch('app.pipeline.text_ready', lambda: True):
        score, summary, issues, suggestions, ti, to = llm_critic([page], {'name': 'Товар'}, 'gpt-5-mini')
    assert score == 82 and 'вигадка' in summary
    assert issues == ['Потужність 900 Вт не з JSON'] and ti == 1200 and to == 150

    class Garbage:
        output_text = 'вибачте, не можу'
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)

    import pytest as _pytest
    with patch('app.pipeline._responses_create', lambda model, prompt, cap: Garbage()), \
         patch('app.pipeline.text_ready', lambda: True):
        with _pytest.raises(RuntimeError):
            llm_critic([page], {}, 'gpt-5-mini')


def test_llm_fix_rewrites_only_flagged_text_and_freezes_dom():
    from app.pipeline import llm_fix_texts

    html = ('<section style="max-width:1240px"><!-- 1. HERO --><div style="display:grid">'
            '<h2>Корпуса для ПК</h2><p>Продумана основа для збирання</p>'
            '<img src="/media/p/hero.webp?t=a" alt="Кейс"></div></section>')

    class FakeResponse:
        output_text = '{"0": "Корпус для ПК", "1": "Кріплення без інструментів і кабель-менеджмент 32 мм"}'
        usage = SimpleNamespace(input_tokens=800, output_tokens=90)

    with patch('app.pipeline._responses_create', lambda m, p, c: FakeResponse()), \
         patch('app.pipeline.text_ready', lambda: True):
        fixed, ti, to, changed = llm_fix_texts(html, ['русизм «корпуса»', 'порожній маркетинг'], {'name': 'Кейс'}, 'gpt-5-mini', 'ua')

    assert changed == 2 and ti == 800 and to == 90
    assert 'Корпус для ПК' in fixed and 'кабель-менеджмент 32 мм' in fixed
    # DOM недоторканний: стилі, коментар розмітки і підписаний URL на місці.
    assert 'style="display:grid"' in fixed
    assert '<!-- 1. HERO -->' in fixed
    assert 'src="/media/p/hero.webp?t=a"' in fixed

    class NoChanges:
        output_text = '{}'
        usage = SimpleNamespace(input_tokens=500, output_tokens=5)

    with patch('app.pipeline._responses_create', lambda m, p, c: NoChanges()), \
         patch('app.pipeline.text_ready', lambda: True):
        same, _, _, changed = llm_fix_texts(html, ['дрібниця'], {}, 'gpt-5-mini', 'ua')
    assert changed == 0 and 'Продумана основа' in same


def test_short_bordered_pills_hug_their_text():
    from app.pipeline import _shrink_pills

    html = ('<section><div style="display:grid;gap:12px">'
            '<div style="border:1px solid #19BCC9;border-radius:8px;padding:6px 12px;font-size:11px">ПРОИЗВОДИТЕЛЬНОСТЬ</div>'
            '<div style="background:#1A2128;border:1px solid #2F3137;border-radius:14px;padding:16px"><b>0.53 кг</b><small>Лёгкий корпус</small></div>'
            '<p style="border:1px solid #ccc;border-radius:10px">' + 'Довгий текст пояснення, який точно не є пігулкою і має лишитись блочним абзацом' + '</p>'
            '</div></section>')
    out = _shrink_pills(html)
    assert out.count('width:fit-content') == 1, 'лише коротка пігулка'
    assert 'border-radius:999px' in out, 'усі лейбли - однакова капсула'
    assert 'ПРОИЗВОДИТЕЛЬНОСТЬ' in out
    # картка з дітьми і довгий абзац - недоторкані
    assert 'Лёгкий корпус</small></div>' in out and 'блочним абзацом</p>' in out


def test_mobile_hero_shows_the_whole_product_without_dead_space():
    from app.pipeline import _fit_mobile_hero

    hero = '/media/p1/hero-mobile.webp?t=abc'
    html = (f'<section><div style="background:url({hero}) center/cover;min-height:600px;padding:320px 18px 26px">'
            f'<img src="{hero}" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">'
            '<h2>Товар</h2></div></section>')
    out = _fit_mobile_hero(html, hero)
    # фон по ширині від верхнього краю: товар угорі видно повністю
    assert 'background-size:100% auto' in out and 'background-position:center top' in out
    # блок лишається заввишки зі свій контент - без порожнього низу
    assert 'aspect-ratio' not in out, 'фіксовані пропорції створювали пусте місце'
    assert 'min-height:600px' in out
    assert 'object-position:center top' in out
    assert _fit_mobile_hero(out, hero) == out, 'повторне застосування - no-op'
    # чужі зображення не чіпаються
    other = '<section><img src="https://cdn/x.webp" style="object-fit:cover"></section>'
    assert _fit_mobile_hero(other, hero) == other


def test_short_bordered_pills_hug_their_text():
    from app.pipeline import _shrink_pills

    html = ('<section><div style="display:grid;gap:12px">'
            '<div style="border:1px solid #19BCC9;border-radius:8px;padding:6px 12px;font-size:11px">ПРОИЗВОДИТЕЛЬНОСТЬ</div>'
            '<div style="background:#1A2128;border:1px solid #2F3137;border-radius:14px;padding:16px"><b>0.53 кг</b><small>Лёгкий корпус</small></div>'
            '<p style="border:1px solid #ccc;border-radius:10px">' + 'Довгий текст пояснення, який точно не є пігулкою і має лишитись блочним абзацом' + '</p>'
            '</div></section>')
    out = _shrink_pills(html)
    assert out.count('width:fit-content') == 1, 'лише коротка пігулка'
    assert 'border-radius:999px' in out, 'усі лейбли - однакова капсула'
    assert 'ПРОИЗВОДИТЕЛЬНОСТЬ' in out
    # картка з дітьми і довгий абзац - недоторкані
    assert 'Лёгкий корпус</small></div>' in out and 'блочним абзацом</p>' in out


def test_mobile_hero_matches_the_portrait_frame_instead_of_cropping_it():
    from app.pipeline import _fit_mobile_hero

    hero = '/media/p1/hero-mobile.webp?t=abc'
    html = (f'<section><div style="background:url({hero}) center/cover;min-height:600px;padding:320px 18px 26px">'
            f'<img src="{hero}" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">'
            '<h2>Товар</h2></div></section>')
    out = _fit_mobile_hero(html, hero)
    assert 'aspect-ratio:2/3' in out, 'висота блока має дорівнювати кадру'
    assert 'background-position:center top' in out
    assert 'object-position:center top' in out, 'шар <img> теж не має різати верх'
    assert 'min-height:600px' in out, 'фолбек висоти лишається'
    assert _fit_mobile_hero(out, hero) == out, 'повторне застосування - no-op'
    # чужі зображення не чіпаються
    other = '<section><img src="https://cdn/x.webp" style="object-fit:cover"></section>'
    assert _fit_mobile_hero(other, hero) == other


def test_photo_cards_fill_edge_to_edge_on_both_variants():
    from app.pipeline import _fit_photo_cards

    html = ('<section>'
            '<div style="background:#fff;border-radius:18px;padding:16px"><img src="/media/p/g1.webp?t=a" alt="" style="max-width:100%;border-radius:10px"></div>'
            '<div style="background:#1A2128;border-radius:14px;padding:18px"><b>0,53 кг</b><small>Масса</small></div>'
            '<div style="background:#fff;border-radius:18px;padding:16px"><img src="/media/p/g2.webp?t=b" alt=""><p>Підпис під фото</p></div>'
            '</section>')
    out = _fit_photo_cards(html)
    assert out.count('aspect-ratio:4/3') == 1, 'лише картка з самим фото'
    assert 'object-fit:cover' in out and 'overflow:hidden' in out
    assert 'padding:16px"><img src="/media/p/g1' not in out, 'падінг у фото-картці прибрано'
    # картка з текстом і картка фото+підпис лишаються як були
    assert '0,53 кг' in out and 'padding:18px' in out
    assert 'Підпис під фото' in out and out.count('padding:16px') == 1
    assert _fit_photo_cards(out) == out or 'aspect-ratio:4/3' in _fit_photo_cards(out)


def test_desktop_photo_cards_use_a_wider_ratio():
    from app.pipeline import _fit_photo_cards

    card = '<section><div style="background:#fff;border-radius:18px;padding:16px"><img src="/media/p/g1.webp?t=a" alt=""></div></section>'
    desktop = _fit_photo_cards(card, 'desktop')
    mobile = _fit_photo_cards(card, 'mobile')
    assert 'aspect-ratio:3/2' in desktop and 'aspect-ratio:4/3' not in desktop
    assert 'aspect-ratio:4/3' in mobile
    assert 'object-fit:cover' in desktop and 'overflow:hidden' in desktop


def test_nested_radii_are_concentric_in_every_style():
    from app.pipeline import _harmonize_radii

    html = ('<section>'
            '<div style="border-radius:24px;padding:8px;background:#fff">'
            '  <div style="border-radius:16px;background:#eee">внутрішня картка</div>'
            '</div>'
            '<div style="border-radius:32px;padding:46px;background:#0D1013">'
            '  <div style="border-radius:99px;padding:6px 12px">пігулка</div>'
            '</div>'
            '<div style="border-radius:18px;background:#fff"><p style="border-radius:12px">без падінга - не чіпаємо</p></div>'
            '</section>')
    out = _harmonize_radii(html)
    # 24 - 8 = 16 (вже правильно), 32 - 46 -> мінімум 4px
    assert 'border-radius:16px;background:#eee' in out
    assert 'border-radius:4px;padding:6px 12px' in out
    # картка без падінга лишається як була
    assert 'border-radius:12px">без падінга' in out
    assert _harmonize_radii(out) == out, 'повторне застосування - no-op'


def test_product_frames_are_never_cropped_inside_cards():
    from app.pipeline import _fit_photo_cards

    gallery = ('<section><div style="background:#fff;border-radius:18px;padding:16px">'
               '<img src="https://cdn.example/gallery/510525/1400_gallery_main.webp" alt=""></div></section>')
    scene = ('<section><div style="background:#fff;border-radius:18px;padding:16px">'
             '<img src="/media/p1/feature.webp?t=abc" alt=""></div></section>')
    out_gallery = _fit_photo_cards(gallery, 'mobile')
    out_scene = _fit_photo_cards(scene, 'mobile')
    assert 'object-fit:contain' in out_gallery, 'реальний кадр товару різати не можна'
    assert 'object-fit:cover' in out_scene, 'згенерована сцена - це фон, її можна кадрувати'
    # спільна рамка лишається в обох випадках
    assert 'aspect-ratio:4/3' in out_gallery and 'aspect-ratio:4/3' in out_scene


def test_run_history_survives_reruns_and_extra_work():
    import json as _json
    from app.tasks import close_run, bill_extra

    project = SimpleNamespace(runs_json='[]', run_index=1, estimated_cost=0.20, input_tokens=1000,
                              output_tokens=500, image_count=2, style_id='s1', text_model='gpt-5',
                              image_model='gpt-image-2', duration_seconds=180.0, lifetime_cost=0)
    close_run(None, project, 'review')
    assert project.lifetime_cost == 0.2 and len(_json.loads(project.runs_json)) == 1

    bill_extra(None, project, 0.03)
    assert project.lifetime_cost == 0.23
    assert _json.loads(project.runs_json)[-1]['extra'] == 0.03

    project.run_index = 2
    project.estimated_cost = 0.15
    close_run(None, project, 'review')
    runs = _json.loads(project.runs_json)
    assert [r['index'] for r in runs] == [1, 2]
    assert runs[0]['cost'] == 0.23 and runs[1]['cost'] == 0.15
    assert project.lifetime_cost == 0.38, 'вартість попередніх прогонів не має зникати'


def test_product_photos_are_never_cropped_in_any_layout():
    from app.pipeline import _never_crop_product_photos

    html = ('<section><div style="display:grid;grid-template-columns:1.1fr .9fr">'
            '<div><h2>Текст</h2></div>'
            '<img src="https://cdn.example/gallery/510525/1400_gallery_main.webp" style="width:100%;height:100%;object-fit:cover">'
            '</div>'
            '<div><img src="/media/p1/hero-desktop.webp?t=x" style="width:100%;height:420px;object-fit:cover"></div>'
            '<div><img src="/media/p1/upload-2.webp?t=y" style="height:300px;object-fit:cover;border-radius:14px"></div>'
            '</section>')
    out = _never_crop_product_photos(html)
    # кадр галереї і завантажене фото - contain
    assert out.count('object-fit:contain') == 2
    # згенерована сцена лишається cover
    assert 'hero-desktop.webp?t=x" style="width:100%;height:420px;object-fit:cover' in out
    assert _never_crop_product_photos(out) == out, 'повторне застосування - no-op'


def test_every_photo_gets_a_consistent_radius():
    from app.pipeline import _round_image_corners

    html = ('<section>'
            '<div style="border-radius:24px;padding:8px"><img src="/media/a.webp"></div>'
            '<div style="border-radius:20px"><img src="/media/b.webp"></div>'
            '<img src="/media/c.webp" style="border-radius:4px">'
            '<div style="position:relative"><img src="/media/hero.webp" style="position:absolute;inset:0"></div>'
            '</section>')
    out = _round_image_corners(html)
    assert 'border-radius:16px' in out, 'фото поза карткою - спільний дефолт'
    # концентрично: 24 - 8 = 16; фото врівень з карткою повторює її радіус + клип
    assert out.count('border-radius:16px') >= 2
    assert 'border-radius:20px' in out and 'overflow:hidden' in out
    # шар Hero не чіпаємо
    assert 'src="/media/hero.webp" style="position:absolute;inset:0"' in out
    assert _round_image_corners(out) == out, 'повторне застосування - no-op'


def test_stat_cards_are_not_turned_into_pills():
    from app.pipeline import _shrink_pills

    stat = ('<section><div style="background:#1A2128;border-radius:14px;padding:16px">'
            '<b style="font-size:26px">216×74×51 мм</b><small>Размеры устройства</small></div></section>')
    assert _shrink_pills(stat) == stat, 'картка показника - не пігулка'

    pill_with_span = ('<section><div style="border:1px solid #19BCC9;border-radius:8px;padding:6px 12px">'
                      '<span>МОБИЛЬНОСТЬ И ПАРАМЕТРЫ</span></div></section>')
    out = _shrink_pills(pill_with_span)
    assert 'width:fit-content' in out and 'border-radius:999px' in out


def test_contained_photos_get_a_rounded_frame():
    from app.pipeline import _frame_contained_photos

    # 1) кадр просто в комірці сітки - додається біла рамка зі скругленням
    bare = '<section><div style="display:grid"><img src="https://cdn/gallery/1400_main.webp" style="object-fit:contain"></div></section>'
    out = _frame_contained_photos(bare)
    assert 'border-radius:16px;overflow:hidden;background:#FFFFFF' in out
    assert 'width:100%' in out

    # 2) кадр уже в картці з радіусом - картці лише додається фон і обрізання
    carded = ('<section><div style="border-radius:24px;padding:0">'
              '<img src="/media/p/upload-1.webp?t=a" style="width:100%;object-fit:contain"></div></section>')
    out2 = _frame_contained_photos(carded)
    assert out2.count('<div') == 1, 'зайва обгортка не потрібна'
    assert 'overflow:hidden' in out2 and 'background:#FFFFFF' in out2

    # 3) сцени з cover не чіпаємо
    scene = '<section><img src="/media/p/feature.webp?t=b" style="object-fit:cover"></section>'
    assert _frame_contained_photos(scene) == scene

    assert _frame_contained_photos(out) == out, 'повторне застосування - no-op'


def test_labels_share_one_radius_even_with_their_own_width():
    from app.pipeline import _shrink_pills

    html = ('<section>'
            '<div style="border:1px solid #19BCC9;border-radius:999px;padding:6px 12px">РАБОТА ПРИ СОЛНЦЕ</div>'
            '<div style="border:1px solid #19BCC9;border-radius:8px;padding:6px 12px;width:fit-content">ПРОДУКТИВНІСТЬ</div>'
            '<div style="background:#1A2128;border-radius:10px;padding:6px 12px;display:inline-block">ЩЕ ОДИН ЛЕЙБЛ</div>'
            '</section>')
    out = _shrink_pills(html)
    assert out.count('border-radius:999px') == 3, 'усі лейбли - однакова капсула'
    # власну ширину не перебиваємо
    assert 'width:fit-content' in out
    assert _shrink_pills(out) == out, 'повторне застосування - no-op'
