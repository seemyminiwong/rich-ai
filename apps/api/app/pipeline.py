import base64
import html as html_lib
import json
import re
import tempfile
from pathlib import Path
from io import BytesIO
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from openai import OpenAI
from PIL import Image, ImageOps
from app.config import settings

client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

LANG_LABELS = {
    "ru": {"trust":"Покупка с поддержкой", "benefits":"Ключевые преимущества", "technology":"Ключевая технология", "design":"Дизайн и практичность", "service":"Сервис и уверенность", "cta":"Готовое решение для ваших задач"},
    "ua": {"trust":"Покупка з підтримкою", "benefits":"Ключові переваги", "technology":"Ключова технологія", "design":"Дизайн і практичність", "service":"Сервіс і впевненість", "cta":"Готове рішення для ваших завдань"},
    "pl": {"trust":"Zakup ze wsparciem", "benefits":"Najważniejsze korzyści", "technology":"Kluczowa technologia", "design":"Design i praktyczność", "service":"Serwis i pewność", "cta":"Gotowe rozwiązanie do Twoich zadań"},
}

LANGUAGE_RULES = {
    "ru": "Write all visible copy in natural Russian. Do not use Ukrainian orthography or Ukrainian words. Russian only.",
    "ua": "Write all visible copy in natural Ukrainian. Do not use Russian orthography. Ukrainian only.",
    "pl": "Write all visible copy in natural Polish. Polish only.",
}

LOCAL_FALLBACK = {
    "ru": {"description": "Современное решение для повседневных и профессиональных задач. Ключевые характеристики и преимущества представлены на основе данных товара.", "use": "Практические сценарии использования", "experience": "Удобство работы и интеграция"},
    "ua": {"description": "Сучасне рішення для повсякденних і професійних завдань. Ключові характеристики та переваги подані на основі даних товару.", "use": "Практичні сценарії використання", "experience": "Зручність роботи та інтеграція"},
    "pl": {"description": "Nowoczesne rozwiązanie do codziennych i profesjonalnych zadań. Najważniejsze cechy i korzyści przedstawiono na podstawie danych produktu.", "use": "Praktyczne zastosowania", "experience": "Wygoda pracy i integracja"},
}

def _visible_text(markup: str) -> str:
    return BeautifulSoup(markup or "", "html.parser").get_text(" ", strip=True)

def _language_matches(markup: str, language: str) -> bool:
    text = _visible_text(markup).lower()
    if language == "pl":
        latin = sum(ch.isalpha() and ord(ch) < 768 for ch in text)
        cyr = sum("а" <= ch <= "я" or ch in "іїєґёыэъ" for ch in text)
        return latin > max(80, cyr * 3)
    if language == "ru":
        return not any(ch in text for ch in "іїєґ") and not any(w in text for w in (" ключові ", " зручн", " підтримк", " завдань", " обладнання"))
    if language == "ua":
        return not any(ch in text for ch in "ыэёъ") and (any(ch in text for ch in "іїєґ") or any(w in text for w in (" ключові ", " зручн", " підтримк", " завдань", " обладнання")))
    return True


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.8",
    }
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as http:
        response = http.get(url)
        response.raise_for_status()
        if not response.text.strip():
            raise RuntimeError("Product page returned an empty response")
        return response.text


def _safe_json(value: str):
    try:
        return json.loads(value)
    except Exception:
        # Some commerce templates append an extra closing brace after otherwise valid
        # JSON-LD. Decode the first complete object instead of discarding all product
        # metadata and falling back to a generic page scan.
        try:
            stripped = (value or '').lstrip()
            parsed, _ = json.JSONDecoder().raw_decode(stripped)
            return parsed
        except Exception:
            return None


def _nodes(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("@graph"), list):
        return value["@graph"]
    return [value]


def _valid_product_image_url(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return False
    lower = value.lower().split("?", 1)[0]
    blocked = ("logo", "icon", "sprite", "placeholder", "payment", "favicon", "badge", "banner", "avatar")
    if lower.endswith((".svg", ".gif")) or any(token in lower for token in blocked):
        return False
    return True


def _srcset_urls(value: str) -> list[str]:
    rows = []
    for item in (value or '').split(','):
        parts = item.strip().split()
        if not parts:
            continue
        width = 0
        if len(parts) > 1 and parts[-1].lower().endswith('w'):
            try:
                width = int(parts[-1][:-1])
            except ValueError:
                width = 0
        rows.append((width, parts[0]))
    return [url for _, url in sorted(rows, reverse=True)]


def _gallery_identity(value: str) -> str:
    """Return a stable gallery-image identity across 220/600/1400 URL variants."""
    clean = (value or '').split('?', 1)[0].lower()
    match = re.search(r'/gallery/([^/]+)/(?:(?:\d+|original)_)?gallery_(.+)$', clean)
    if match:
        return f'{match.group(1)}:{match.group(2)}'
    filename = clean.rsplit('/', 1)[-1]
    return re.sub(r'^(?:\d+|original)_', '', filename)


def _image_values(node, page_url: str) -> list[str]:
    values = []
    parent = node.parent if getattr(node, 'parent', None) else None
    if parent and getattr(parent, 'name', '') == 'a' and parent.get('href'):
        values.append(parent.get('href'))
    for name in ('srcset', 'data-srcset'):
        values.extend(_srcset_urls(node.get(name, '')))
    for name in ('src', 'data-src', 'data-original', 'data-lazy-src', 'data-zoom-image'):
        if node.get(name):
            values.append(node.get(name))
    return [urljoin(page_url, x) for x in values if isinstance(x, str) and not x.startswith('data:')]


def _schema_image_urls(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [url for item in value for url in _schema_image_urls(item)]
    if isinstance(value, dict):
        for key in ('contentUrl', 'url', '@id'):
            if isinstance(value.get(key), str):
                return [value[key]]
    return []


def inspect_product_references(images: list[str], preferred_url: str = '') -> list[dict]:
    """Validate and rank real product-image candidates using pixels and gallery provenance.

    File size is deliberately not a quality signal: optimized WebP product photos can be
    smaller than 20 KB. The previous implementation rejected ARTLINE's real main photo
    for exactly that reason and selected a later infographic instead.
    """
    candidates = [x for x in dict.fromkeys(images) if _valid_product_image_url(x)]
    if not candidates:
        return []
    preferred_identity = _gallery_identity(preferred_url or candidates[0])
    inspected = []
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'}
    preferred_candidates = [url for url in candidates if _gallery_identity(url) == preferred_identity]
    fallback_candidates = [url for url in candidates if _gallery_identity(url) != preferred_identity]

    def inspect_pool(http, pool):
        rows = []
        for index, url in enumerate(pool):
            try:
                response = http.get(url)
                response.raise_for_status()
                if not 256 < len(response.content) <= 45 * 1024 * 1024:
                    continue
                image = Image.open(BytesIO(response.content))
                width, height = image.size
                if width < 320 or height < 320:
                    continue
                ratio = width / max(height, 1)
                if ratio < 0.28 or ratio > 3.6:
                    continue
                identity = _gallery_identity(url)
                same_product_photo = bool(preferred_identity and identity == preferred_identity)
                score = (100_000 if same_product_photo else 0) + min(width * height, 8_000_000) / 1000 - index * 25
                lower = url.lower()
                if '/1400_' in lower or '/original_' in lower:
                    score += 600
                elif '/600_' in lower:
                    score += 300
                elif '/220_' in lower:
                    score -= 300
                rows.append({
                    'url': url,
                    'width': width,
                    'height': height,
                    'bytes': len(response.content),
                    'format': image.format or '',
                    'identity': identity,
                    'matches_primary': same_product_photo,
                    'score': score,
                })
            except Exception:
                continue
        return rows

    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as http:
        inspected.extend(inspect_pool(http, preferred_candidates[:8]))
        # Do not scan unrelated page images once a validated variant of the official
        # primary product photo is available. This keeps normal ARTLINE pages fast.
        if not inspected:
            inspected.extend(inspect_pool(http, fallback_candidates[:16]))
    return sorted(inspected, key=lambda row: row['score'], reverse=True)


def choose_product_reference(images: list[str], preferred_url: str = '') -> str:
    ranked = inspect_product_references(images, preferred_url)
    return ranked[0]['url'] if ranked else ''


def parse_page(page_html: str, url: str):
    soup = BeautifulSoup(page_html, "html.parser")
    product = None
    for tag in soup.select('script[type="application/ld+json"]'):
        parsed = _safe_json(tag.string or tag.get_text() or "")
        if parsed is None:
            continue
        for node in _nodes(parsed):
            if not isinstance(node, dict):
                continue
            kind = node.get("@type", [])
            kinds = kind if isinstance(kind, list) else [kind]
            if "Product" in kinds:
                product = node
                break
        if product:
            break

    images = []
    primary_image = ''
    if product:
        product_images = _schema_image_urls(product.get("image", []))
        images.extend(product_images)
        primary_image = next((x for x in product_images if isinstance(x, str)), '')
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            images.append(meta["content"])
    # Explicit product-gallery sources come before generic page images. Include lazy
    # attributes, srcset and zoom/modal links so the same primary photo can be used at
    # the highest available resolution.
    gallery_selector = (
        '.product-slider__view img, .product-slider__nav img, '
        '[class*="product-gallery"] img, [class*="product-slider"] img, '
        '[class*="gallery"] img'
    )
    for image in soup.select(gallery_selector)[:80]:
        images.extend(_image_values(image, url))
    for image in soup.select("main img, article img, .product img")[:80]:
        images.extend(_image_values(image, url))
    images = [urljoin(url, value) for value in images if isinstance(value, str) and not value.startswith("data:")]
    images = [value for value in dict.fromkeys(images) if _valid_product_image_url(value)]

    # Keep all URL variants of the JSON-LD primary image at the front. This preserves
    # product identity while allowing the selector to prefer a larger 1400px copy.
    primary_identity = _gallery_identity(primary_image)
    if primary_identity:
        images.sort(key=lambda value: _gallery_identity(value) != primary_identity)

    for bad in soup(["script", "style", "svg", "noscript", "nav", "footer", "header"]):
        bad.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    root = soup.find("main") or soup.body or soup
    clean_text = re.sub(r"\s+", " ", root.get_text(" ", strip=True))[:100000]
    return product, images, title, clean_text


def _normalize_jsonld(product: dict):
    specs = []
    for item in product.get("additionalProperty") or []:
        if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
            specs.append({"name": str(item["name"]), "value": str(item["value"])})
    brand = product.get("brand", "")
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    description = BeautifulSoup(str(product.get("description", "")), "html.parser").get_text(" ", strip=True)
    return {
        "name": str(product.get("name", "")).strip(),
        "brand": str(brand or ""),
        "sku": str(product.get("sku") or product.get("mpn") or ""),
        "description": description,
        "features": [],
        "specs": specs,
    }


def _extract_json(text: str):
    cleaned = (text or "").strip().replace("```json", "").replace("```", "")
    parsed = _safe_json(cleaned)
    if isinstance(parsed, dict):
        return parsed
    first, last = cleaned.find("{"), cleaned.rfind("}")
    if first >= 0 and last > first:
        parsed = _safe_json(cleaned[first:last + 1])
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("AI extraction returned invalid JSON")


def _fallback_extract(title: str, clean_text: str):
    name = title.split("|")[0].strip() or "Product"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if len(s.strip()) > 40]
    description = " ".join(sentences[:4])[:1500] or clean_text[:1500]
    return {"name": name, "brand": "", "sku": "", "description": description, "features": [], "specs": []}


def _estimate_tokens(value: str) -> int:
    # Approximation used only when an API response omits usage metadata.
    return max(1, round(len(value or "") / 4))


def _usage_value(usage, name: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(name, 0) or 0)
    return int(getattr(usage, name, 0) or 0)


def _usage_counts(response, input_text: str, output_text: str):
    usage = getattr(response, "usage", None)
    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    # Some SDK/model combinations may not expose usage. Keep the cost estimate useful.
    if input_tokens <= 0:
        input_tokens = _estimate_tokens(input_text)
    if output_tokens <= 0:
        output_tokens = _estimate_tokens(output_text)
    return input_tokens, output_tokens


def _reference_image(url: str):
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        with httpx.Client(timeout=90, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as http:
            response = http.get(url)
            response.raise_for_status()
            if len(response.content) > 45 * 1024 * 1024:
                return None
            source = ImageOps.exif_transpose(Image.open(BytesIO(response.content))).convert("RGBA")
            # OpenAI image editing is most reliable with a normalized PNG reference.
            source.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            handle.close()
            source.save(handle.name, format="PNG")
            return Path(handle.name)
    except Exception:
        return None


def materialize_product_reference(url: str, project_id: str):
    """Persist the exact selected source photo and return its public URL/path/metadata."""
    temporary = _reference_image(url)
    if not temporary:
        return '', None, {}
    try:
        folder = Path(settings.media_dir) / project_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'product-reference.png'
        image = Image.open(temporary)
        image.save(path, format='PNG', optimize=True)
        width, height = image.size
        return (
            f'/media/{project_id}/product-reference.png',
            path,
            {'source_url': url, 'width': width, 'height': height, 'format': 'PNG', 'is_reference': True},
        )
    finally:
        temporary.unlink(missing_ok=True)


def style_image_prompt(style_prompt: str, section: str) -> str:
    # Optional sections inside the single style field:
    # [HERO_IMAGE] ... [/HERO_IMAGE] and [FEATURE_IMAGE] ... [/FEATURE_IMAGE]
    pattern = rf"\[{re.escape(section)}\](.*?)\[/{re.escape(section)}\]"
    match = re.search(pattern, style_prompt or "", re.I | re.S)
    return match.group(1).strip() if match else ""


def extract_product(jsonld, title: str, clean_text: str, url: str, model: str):
    if jsonld:
        data = _normalize_jsonld(jsonld)
        if data['name'] and (data['description'] or data['specs']):
            return data, 0, 0
    if not client:
        return _fallback_extract(title, clean_text), 0, 0
    prompt = (
        'Extract factual ecommerce product data from the supplied page text. '
        'Return one JSON object only with keys: name, brand, sku, description, '
        'features (array of strings), specs (array of objects with name and value). '
        'Never invent facts.\nURL: ' + url + '\nTITLE: ' + title + '\nPAGE: ' + clean_text
    )
    try:
        response = client.responses.create(model=model, input=prompt, max_output_tokens=5000, store=False)
        data = _extract_json(response.output_text)
        input_tokens, output_tokens = _usage_counts(response, prompt, response.output_text)
        return data, input_tokens, output_tokens
    except Exception:
        return _fallback_extract(title, clean_text), 0, 0


def generate_image(
    prompt: str,
    project_id: str,
    label: str,
    model: str,
    quality: str,
    fallback: str = '',
    reference_url: str = '',
    reference_path: Path | None = None,
    size: str = '1536x1024',
):
    if not client:
        return fallback, False, 'OpenAI API key is not configured'
    reference = reference_url or fallback
    temporary_reference = None
    if reference_path:
        reference_path = Path(reference_path)
    else:
        temporary_reference = _reference_image(reference)
        reference_path = temporary_reference
    try:
        # Critical rule: generated product visuals must be transformations of a real product photo.
        # If no usable reference exists, keep the source photo instead of inventing a new product.
        if not reference_path:
            return fallback, False, 'No verified product reference image is available'
        with reference_path.open('rb') as image_file:
            edit_options = dict(
                model=model,
                image=image_file,
                prompt=(
                    'STRICT REFERENCE-IMAGE EDIT. The uploaded image contains the exact real product. '
                    'Preserve its identity, geometry, proportions, materials, controls, openings, labels and logo placement. '
                    'Do not redesign, substitute or hallucinate the product. Build the requested scene around this exact product. ' + prompt
                ),
                size=size,
                quality=quality,
                output_format='webp',
            )
            # High input fidelity asks supported GPT Image models to preserve small
            # product details, labels and geometry. GPT Image 2 always uses it and
            # rejects an explicit parameter, so omit it there.
            if model != 'gpt-image-2':
                edit_options['extra_body'] = {'input_fidelity': 'high'}
            response = client.images.edit(**edit_options)
        item = response.data[0]
        folder = Path(settings.media_dir) / project_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{label}.webp'
        if getattr(item, 'b64_json', None):
            path.write_bytes(base64.b64decode(item.b64_json))
        elif getattr(item, 'url', None):
            with httpx.Client(timeout=120, follow_redirects=True) as http:
                image_response = http.get(item.url)
                image_response.raise_for_status()
                path.write_bytes(image_response.content)
        else:
            return fallback, False, 'OpenAI returned no image data'
        return f'/media/{project_id}/{label}.webp', True, ''
    except Exception as exc:
        return fallback, False, str(exc)
    finally:
        if temporary_reference:
            try:
                temporary_reference.unlink(missing_ok=True)
            except Exception:
                pass


def _html_only(text: str) -> str:
    value = (text or '').strip().replace('```html', '').replace('```', '')
    start, end = value.find('<section'), value.rfind('</section>')
    if start < 0 or end < start:
        raise RuntimeError('AI did not return a complete <section> block')
    return value[start:end + len('</section>')]


def _prompt(product, style, language, variant, hero, feature):
    layout = 'single-column mobile layout with no horizontal overflow' if variant == 'mobile' else 'desktop layout up to 1240px'
    language_rule = LANGUAGE_RULES.get(language, LANGUAGE_RULES['ru'])
    return f"""Create standardized premium ecommerce rich content. Return HTML only: exactly one complete <section>...</section>.
TARGET LANGUAGE CODE: {language}. {language_rule}
Never copy source-page sentences in another language. Translate and rewrite every visible sentence into the target language while preserving model names, trademarks, numbers and units.
Variant: {variant}. Layout: {layout}. Use inline CSS only.
The style prompt below is the primary design specification. Follow it precisely unless it conflicts with factual accuracy or HTML validity.
STYLE PROMPT:
{style.prompt}
Mandatory factual rule: use only facts present in Product JSON. Never invent warranty, partnership, certification, compatibility, performance, contents or support claims.
Images: hero={hero}; feature={feature}.
Product JSON: {json.dumps(product, ensure_ascii=False)}"""


def _deterministic_html(product, style, language, variant, hero, feature):
    labels = LANG_LABELS.get(language, LANG_LABELS['ru'])
    width = '720px' if variant == 'mobile' else '1240px'
    columns = '1fr' if variant == 'mobile' else 'repeat(3,1fr)'
    feature_columns = '1fr' if variant == 'mobile' else '1.15fr .85fr'
    name = html_lib.escape(product.get('name') or 'Product')
    brand = html_lib.escape(product.get('brand') or 'ARTLINE')
    raw_description = str(product.get('description') or '')
    fallback_copy = LOCAL_FALLBACK.get(language, LOCAL_FALLBACK['ru'])
    if language == 'ru' and any(ch in raw_description.lower() for ch in 'іїєґ'):
        raw_description = fallback_copy['description']
    elif language == 'ua' and any(ch in raw_description.lower() for ch in 'ыэёъ'):
        raw_description = fallback_copy['description']
    elif language == 'pl' and any('а' <= ch <= 'я' or ch in 'іїєґ' for ch in raw_description.lower()):
        raw_description = fallback_copy['description']
    description = html_lib.escape(raw_description or fallback_copy['description'])
    facts = [str(x) for x in (product.get('features') or []) if x]
    for spec in product.get('specs') or []:
        if isinstance(spec, dict) and spec.get('name') and spec.get('value'):
            facts.append(f"{spec['name']}: {spec['value']}")
    localized_benefits = {
        'ru': ['Ключевая характеристика', 'Продуманная функциональность', 'Удобство эксплуатации', 'Стабильная работа', 'Современные возможности', 'Практичное применение'],
        'ua': ['Ключова характеристика', 'Продумана функціональність', 'Зручність експлуатації', 'Стабільна робота', 'Сучасні можливості', 'Практичне застосування'],
        'pl': ['Kluczowa cecha', 'Przemyślana funkcjonalność', 'Wygodna obsługa', 'Stabilna praca', 'Nowoczesne możliwości', 'Praktyczne zastosowanie'],
    }.get(language, [])
    cleaned_facts = []
    for fact in facts:
        sample = str(fact)
        if language == 'ru' and (any(ch in sample.lower() for ch in 'іїєґ') or any(w in sample.lower() for w in ('швидк','підтрим','зручн'))):
            continue
        if language == 'ua' and any(ch in sample.lower() for ch in 'ыэёъ'):
            continue
        if language == 'pl' and any('а' <= ch <= 'я' or ch in 'іїєґ' for ch in sample.lower()):
            continue
        cleaned_facts.append(sample)
    facts = cleaned_facts[:6]
    while len(facts) < 6:
        facts.append(localized_benefits[len(facts)] if len(facts) < len(localized_benefits) else description[:180] or name)
    cards = ''.join(
        f'<div style="padding:26px;border-radius:26px;background:{"#101010" if i<3 else "#F5F7FA"};border:1px solid #19BCC955;color:{"#f5f7fa" if i<3 else "#101010"}"><div style="font-size:25px;font-weight:900;color:#19BCC9;margin-bottom:10px">{html_lib.escape(fact[:55])}</div><p style="margin:0;line-height:1.55;color:{"#d0d7de" if i<3 else "#555"}">{html_lib.escape(fact)}</p></div>'
        for i, fact in enumerate(facts)
    )
    hero_css = f"linear-gradient(90deg,rgba(5,5,5,.96),rgba(18,8,0,.18)),url('{hero}') center/cover no-repeat" if hero else 'linear-gradient(135deg,#101010,#1A2128)'
    image_html = f'<img src="{html_lib.escape(feature)}" alt="{name}" style="width:100%;max-height:360px;object-fit:contain">' if feature else f'<div style="font-size:54px;font-weight:950;color:#19BCC9">{brand}</div>'
    hero_height = '420px' if variant == 'mobile' else '560px'
    hero_padding = '42px 24px' if variant == 'mobile' else '72px 46px'
    h1_size = '38px' if variant == 'mobile' else '58px'
    h2_size = '32px' if variant == 'mobile' else '42px'
    trust_columns = '1fr' if variant == 'mobile' else '.9fr 1.1fr'
    return f'''<section style="max-width:{width};margin:0 auto;padding:0 14px;font-family:Roboto,Inter,Arial,sans-serif;box-sizing:border-box;color:#f5f7fa">
<div style="padding:14px 18px;border-radius:12px;background:linear-gradient(135deg,#2CAEB4,#6890E4);margin-bottom:18px"><strong>{brand}</strong> - {labels['trust']}</div>
<div style="min-height:{hero_height};padding:{hero_padding};border-radius:34px;background:{hero_css};display:flex;align-items:center;margin-bottom:22px"><div style="max-width:660px"><div style="color:#19BCC9;font-weight:900;text-transform:uppercase">{brand}</div><h1 style="font-size:{h1_size};line-height:1;margin:14px 0">{name}</h1><p style="font-size:17px;line-height:1.65;color:#e6e6e6">{description}</p></div></div>
<div style="display:grid;grid-template-columns:{columns};gap:16px;margin-bottom:22px">{cards}</div>
<div style="display:grid;grid-template-columns:{feature_columns};gap:30px;align-items:center;padding:42px;border-radius:34px;background:linear-gradient(135deg,#101010,#1A2128);margin-bottom:22px"><div><div style="color:#19BCC9;font-weight:900;text-transform:uppercase">{labels['technology']}</div><h2 style="font-size:{h2_size}">{name}</h2><p style="line-height:1.7;color:#d0d7de">{description}</p></div><div style="background:#f5f7fa;border-radius:28px;padding:22px;text-align:center">{image_html}</div></div>
<div style="padding:42px;border-radius:34px;background:#f5f7fa;color:#101010;margin-bottom:22px"><div style="color:#19BCC9;font-weight:900;text-transform:uppercase">{labels['design']}</div><h2>{labels['benefits']}</h2><p style="line-height:1.7;color:#555">{description}</p></div>
<div style="display:grid;grid-template-columns:{trust_columns};gap:16px;margin-bottom:22px"><div style="padding:36px;border-radius:34px;background:#101010;border:1px solid #19BCC955"><h2>{labels['service']}</h2><p style="color:#d0d7de;line-height:1.65">{brand}</p></div><div style="padding:36px;border-radius:34px;background:#f5f7fa;color:#101010"><h3>{name}</h3><p style="color:#555;line-height:1.65">{description}</p></div></div>
<div style="padding:52px 28px;border-radius:34px;text-align:center;background:linear-gradient(135deg,#101010,#1A2128);border:1px solid #19BCC955"><div style="color:#19BCC9;font-weight:900">{brand}</div><h2>{labels['cta']}</h2><p style="max-width:700px;margin:auto;color:#d0d7de;line-height:1.65">{description}</p></div>
</section>'''


def generate_html(product, style, language, variant, hero, feature, model: str):
    fallback = _deterministic_html(product, style, language, variant, hero, feature)
    if not client:
        return fallback, 0, 0
    base_prompt = _prompt(product, style, language, variant, hero, feature)
    try:
        response = client.responses.create(model=model, input=base_prompt, max_output_tokens=16000, store=False)
        output = _html_only(response.output_text)
        input_tokens, output_tokens = _usage_counts(response, base_prompt, response.output_text)
        if not _language_matches(output, language):
            correction = f"""Rewrite only the visible text in the HTML below into the required target language. Preserve every HTML tag, inline CSS declaration, URL, number, unit, model name and trademark. Do not add or remove sections. {LANGUAGE_RULES.get(language, LANGUAGE_RULES['ru'])}
HTML:
{output}"""
            corrected = client.responses.create(model=model, input=correction, max_output_tokens=16000, store=False)
            output = _html_only(corrected.output_text)
            ci, co = _usage_counts(corrected, correction, corrected.output_text)
            input_tokens += ci
            output_tokens += co
        if not _language_matches(output, language):
            raise RuntimeError(f'Generated content did not pass language validation for {language}')
        return output, input_tokens, output_tokens
    except Exception:
        return fallback, 0, 0


def critic_html(artifacts, critic_type: str, product: dict):
    html = '\n'.join(getattr(a, 'html', '') for a in artifacts)
    issues = []
    suggestions = []
    score = 100.0
    if critic_type == 'html':
        if '<section' not in html or '</section>' not in html:
            issues.append('Missing complete section wrapper'); score -= 35
        if '<script' in html.lower():
            issues.append('Script tag detected'); score -= 30
        if '<style' in html.lower():
            issues.append('Style tag detected; inline CSS is required'); score -= 15
        if html.count('<h1') != len(artifacts):
            issues.append('Expected one H1 per artifact'); score -= 10
        if len(html) > 700000:
            issues.append('HTML payload is unusually large'); score -= 10
        suggestions = ['Validate markup before publishing', 'Keep one semantic H1 per variant']
    elif critic_type == 'accessibility':
        images = len(re.findall(r'<img\b', html, re.I))
        alts = len(re.findall(r'<img\b[^>]*\balt=["\'][^"\']*["\']', html, re.I))
        if images and alts < images:
            issues.append(f'{images-alts} image(s) have no alt text'); score -= min(35, (images-alts)*10)
        if re.search(r'font-size\s*:\s*(?:[0-9]|1[01])px', html, re.I):
            issues.append('Very small text detected'); score -= 10
        suggestions = ['Add accurate alt text', 'Maintain readable mobile typography']
    elif critic_type == 'facts':
        name = str(product.get('name') or '').strip()
        if name and name.lower() not in html.lower():
            issues.append('Product name is missing'); score -= 25
        banned = ['best in the world','100% guaranteed','unmatched','revolutionary']
        for phrase in banned:
            if phrase in html.lower(): issues.append(f'Unsupported claim: {phrase}'); score -= 10
        suggestions = ['Cross-check every number against product JSON', 'Avoid unsupported warranty and partnership claims']
    else:
        if len(re.sub('<[^>]+>',' ',html)) < 1800:
            issues.append('Content may be too shallow'); score -= 15
        if html.lower().count('artline') > 25:
            issues.append('Brand repetition is excessive'); score -= 10
        suggestions = ['Use specific customer benefits', 'Reduce repetitive marketing filler']
    score = max(0.0, min(100.0, score))
    summary = 'No critical issues found' if not issues else '; '.join(issues[:3])
    return score, summary, issues, suggestions
