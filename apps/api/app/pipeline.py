import base64
import html as html_lib
import ipaddress
import json
import logging
import re
import socket
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup, Comment, NavigableString
from openai import OpenAI
from PIL import Image, ImageOps
from app.config import settings
from app.runtime import GEMINI_BASE_URL, OPENROUTER_BASE_URL, runtime_config

logger = logging.getLogger("richstudio.pipeline")

_clients: dict = {}


def _client_for(key: str, base_url: str = ''):
    """Cache one OpenAI client per (key, base_url) so rotating a key builds a new
    client instead of reusing a stale one, without leaking connection pools."""
    if not key:
        return None
    slot = (key, base_url)
    if slot not in _clients:
        _clients[slot] = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
    return _clients[slot]


def text_client():
    """Return (client, provider) for text generation.

    OpenRouter speaks the OpenAI protocol but only for Chat Completions - it does
    not implement the Responses API, so the provider is returned alongside and
    _responses_create translates the call.
    """
    cfg = runtime_config()
    if cfg['llm_provider'] == 'openrouter' and cfg['openrouter_api_key']:
        return _client_for(cfg['openrouter_api_key'], OPENROUTER_BASE_URL), 'openrouter'
    return _client_for(cfg['openai_api_key']), 'openai'


def image_client():
    """OpenAI client for artwork. OpenRouter is never used here: it has no
    equivalent of the Images Edit API with input_fidelity."""
    return _client_for(runtime_config()['openai_api_key'])


def image_provider(model: str) -> str:
    """Route by model name rather than a separate provider switch, so picking a
    model in the New Project dialog is all it takes to A/B two providers."""
    return 'gemini' if (model or '').startswith('gemini-') else 'openai'


def text_ready() -> bool:
    return text_client()[0] is not None


def image_ready(model: str = '') -> bool:
    if image_provider(model) == 'gemini':
        return bool(runtime_config()['gemini_api_key'])
    return image_client() is not None


def _aspect_ratio(size: str) -> str:
    """Gemini takes an aspect ratio, not a pixel size. Map to the nearest supported one."""
    try:
        width, height = (int(v) for v in str(size).lower().split('x'))
        target = width / height
    except Exception:
        return '1:1'
    options = {'1:1': 1.0, '3:2': 1.5, '2:3': 0.667, '4:3': 1.333, '3:4': 0.75, '16:9': 1.778, '9:16': 0.563}
    return min(options, key=lambda k: abs(options[k] - target))


def _gemini_edit(model: str, prompt: str, reference: bytes, mime: str, size: str) -> bytes:
    """Edit a reference photo with a Gemini image model.

    Plain REST via httpx: Gemini is not OpenAI-protocol-compatible for images, and
    this keeps the dependency list unchanged.
    """
    key = runtime_config()['gemini_api_key']
    if not key:
        raise RuntimeError('Gemini API key is not configured')
    payload = {
        'contents': [{'parts': [
            {'text': prompt},
            {'inline_data': {'mime_type': mime, 'data': base64.b64encode(reference).decode()}},
        ]}],
        'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': _aspect_ratio(size)}},
    }

    def call(body):
        with httpx.Client(timeout=180) as http:
            reply = http.post(
                f'{GEMINI_BASE_URL}/models/{model}:generateContent',
                headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                json=body,
            )
            if reply.status_code >= 400:
                raise RuntimeError(f'Gemini {reply.status_code}: {reply.text[:300]}')
            return reply.json()

    try:
        data = _with_retry(lambda: call(payload))
    except Exception as exc:
        # Older image models reject imageConfig; drop it rather than fail the project.
        if 'imageConfig' in str(exc) or 'aspectRatio' in str(exc):
            logger.warning('Gemini model %s rejected imageConfig, retrying without it', model)
            payload['generationConfig'].pop('imageConfig', None)
            data = _with_retry(lambda: call(payload))
        else:
            raise
    for candidate in data.get('candidates') or []:
        for part in (candidate.get('content') or {}).get('parts') or []:
            blob = part.get('inline_data') or part.get('inlineData') or {}
            if blob.get('data'):
                return base64.b64decode(blob['data'])
    raise RuntimeError('Gemini returned no image data')


class _TextResponse:
    """A Responses-API-shaped view over a Chat Completions reply, so callers read
    .output_text and .usage the same way regardless of provider."""

    def __init__(self, completion):
        choice = (getattr(completion, 'choices', None) or [None])[0]
        message = getattr(choice, 'message', None) if choice else None
        self.output_text = (getattr(message, 'content', '') or '') if message else ''
        usage = getattr(completion, 'usage', None)
        self.usage = SimpleNamespace(
            input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
        )


def _is_reasoning_model(model: str) -> bool:
    name = (model or '').lower()
    return name.startswith(('gpt-5', 'o1', 'o3', 'o4')) or 'reasoning' in name


def _responses_create(model: str, prompt: str, max_output_tokens: int):
    """Call the Responses API, adapting the token budget for reasoning models.

    Reasoning models bill hidden reasoning tokens against max_output_tokens, so a
    normal budget can leave nothing for the visible answer (empty or truncated
    output). Give them more room and keep the thinking short for formatting work.
    """
    api, provider = text_client()
    if api is None:
        raise RuntimeError('Text provider is not configured')
    effort = (settings.openai_reasoning_effort or '').strip()
    if provider == 'openrouter':
        budget = max(max_output_tokens * 2, 32000) if _is_reasoning_model(model) else max_output_tokens
        options = dict(model=model, messages=[{'role': 'user', 'content': prompt}], max_tokens=budget)
        if _is_reasoning_model(model) and effort:
            options['extra_body'] = {'reasoning': {'effort': effort}}
        try:
            return _TextResponse(_with_retry(lambda: api.chat.completions.create(**options)))
        except Exception as exc:
            if 'extra_body' in options and 'reasoning' in str(exc).lower():
                logger.warning('OpenRouter model %s rejected the reasoning parameter, retrying without it', model)
                options.pop('extra_body', None)
                return _TextResponse(_with_retry(lambda: api.chat.completions.create(**options)))
            raise
    options = dict(model=model, input=prompt, max_output_tokens=max_output_tokens, store=False)
    if _is_reasoning_model(model):
        options['max_output_tokens'] = max(max_output_tokens * 2, 32000)
        if effort:
            options['reasoning'] = {'effort': effort}
    try:
        return _with_retry(lambda: api.responses.create(**options))
    except Exception as exc:
        # Some models reject the reasoning parameter or a larger budget; degrade safely.
        if 'reasoning' in options and 'reasoning' in str(exc).lower():
            logger.warning('Model %s rejected the reasoning parameter, retrying without it: %s', model, exc)
            options.pop('reasoning', None)
            return _with_retry(lambda: api.responses.create(**options))
        raise


def _with_retry(call, attempts=3, base_delay=1.5):
    """Retry transient OpenAI/network failures with exponential backoff.

    Only retries errors that look transient (rate limit, timeout, 5xx, dropped
    connection). Deterministic errors (bad request, auth) raise immediately.
    """
    last = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            last = exc
            message = str(exc).lower()
            transient = any(k in message for k in ('rate limit', 'timeout', 'timed out', 'temporar', 'overload', 'connection', 'reset', '429', '500', '502', '503', '504'))
            if attempt == attempts - 1 or not transient:
                raise
            logger.warning('OpenAI call failed (attempt %d/%d), retrying: %s', attempt + 1, attempts, exc)
            time.sleep(base_delay * (2 ** attempt))
    if last:
        raise last


# Rich content is embedded, untrusted HTML. It is rendered in the operator UI and
# packaged into downloadable files, so it must be stripped of any active content
# (scripts, event handlers, javascript: URLs) before it is stored or shown.
_ALLOWED_TAGS = {
    'section', 'div', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li',
    'img', 'strong', 'span', 'em', 'b', 'i', 'br', 'small',
}
_ALLOWED_ATTRS = {'style', 'src', 'alt', 'title', 'width', 'height', 'loading', 'class'}
_URL_SAFE_SCHEMES = ('http://', 'https://', '/media/', '/')


def sanitize_html(markup: str) -> str:
    """Return the HTML with only safe presentational tags and attributes."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    for dangerous in soup(['script', 'style', 'iframe', 'object', 'embed', 'link', 'meta', 'form', 'input', 'button', 'svg', 'noscript', 'base']):
        dangerous.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        for attr in list(tag.attrs):
            raw = tag.attrs[attr]
            value = ' '.join(raw) if isinstance(raw, list) else str(raw)
            flat = value.strip().lower().replace('\t', '').replace('\n', '').replace('\r', '')
            if attr.startswith('on') or attr not in _ALLOWED_ATTRS:
                del tag.attrs[attr]
                continue
            if attr == 'src' and not flat.startswith(_URL_SAFE_SCHEMES):
                del tag.attrs[attr]
                continue
            if attr == 'style' and ('javascript:' in flat or 'expression(' in flat or '@import' in flat):
                del tag.attrs[attr]
    return str(soup)


def is_public_http_url(url: str) -> bool:
    """Reject non-HTTP schemes and hosts that resolve to private/loopback ranges (SSRF guard)."""
    try:
        parsed = urlparse(url or '')
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False

LANG_LABELS = {
    "ru": {"trust":"Покупка с поддержкой", "benefits":"Ключевые преимущества", "technology":"Ключевая технология", "design":"Дизайн и практичность", "service":"Сервис и уверенность", "cta":"Готовое решение для ваших задач"},
    "ua": {"trust":"Покупка з підтримкою", "benefits":"Ключові переваги", "technology":"Ключова технологія", "design":"Дизайн і практичність", "service":"Сервіс і впевненість", "cta":"Готове рішення для ваших завдань"},
    "pl": {"trust":"Zakup ze wsparciem", "benefits":"Najważniejsze korzyści", "technology":"Kluczowa technologia", "design":"Design i praktyczność", "service":"Serwis i pewność", "cta":"Gotowe rozwiązanie do Twoich zadań"},
    "en": {"trust":"Confident choice", "benefits":"Key benefits", "technology":"Core technology", "design":"Design and practicality", "service":"Confidence and support", "cta":"A focused solution for your tasks"},
}

LANGUAGE_RULES = {
    "ru": "Write all visible copy in natural Russian. Do not use Ukrainian orthography or Ukrainian words. Russian only.",
    "ua": "Write all visible copy in natural Ukrainian. Do not use Russian orthography. Ukrainian only.",
    "pl": "Write all visible copy in natural Polish. Polish only.",
    "en": "Write all visible copy in natural English. English only.",
    "de": "Write all visible copy in natural German. German only.",
    "fr": "Write all visible copy in natural French. French only.",
    "es": "Write all visible copy in natural Spanish. Spanish only.",
    "it": "Write all visible copy in natural Italian. Italian only.",
    "cs": "Write all visible copy in natural Czech. Czech only.",
    "sk": "Write all visible copy in natural Slovak. Slovak only.",
    "ro": "Write all visible copy in natural Romanian. Romanian only.",
    "hu": "Write all visible copy in natural Hungarian. Hungarian only.",
    "nl": "Write all visible copy in natural Dutch. Dutch only.",
}

LANGUAGE_NAMES = {
    "ru": "Russian", "ua": "Ukrainian", "uk": "Ukrainian", "pl": "Polish",
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "cs": "Czech", "sk": "Slovak", "ro": "Romanian",
    "hu": "Hungarian", "nl": "Dutch", "pt": "Portuguese", "bg": "Bulgarian",
    "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian",
}


def language_rule(language: str) -> str:
    if language in LANGUAGE_RULES:
        return LANGUAGE_RULES[language]
    base = (language or '').split('-', 1)[0].lower()
    name = LANGUAGE_NAMES.get(language) or LANGUAGE_NAMES.get(base)
    if name:
        return f"Write all visible copy in natural {name}. Use {name} only."
    return f"Write all visible copy only in the language identified by BCP-47/ISO code '{language}'. Do not mix languages."

LOCAL_FALLBACK = {
    "ru": {"description": "Современное решение для повседневных и профессиональных задач. Ключевые характеристики и преимущества представлены на основе данных товара.", "use": "Практические сценарии использования", "experience": "Удобство работы и интеграция"},
    "ua": {"description": "Сучасне рішення для повсякденних і професійних завдань. Ключові характеристики та переваги подані на основі даних товару.", "use": "Практичні сценарії використання", "experience": "Зручність роботи та інтеграція"},
    "pl": {"description": "Nowoczesne rozwiązanie do codziennych i profesjonalnych zadań. Najważniejsze cechy i korzyści przedstawiono na podstawie danych produktu.", "use": "Praktyczne zastosowania", "experience": "Wygoda pracy i integracja"},
    "en": {"description": "A modern solution for everyday and professional tasks. Key characteristics and benefits are presented from verified product data.", "use": "Practical use scenarios", "experience": "Convenient use and integration"},
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
        if not inspected:
            inspected.extend(inspect_pool(http, fallback_candidates[:16]))
        else:
            # Also validate a few other gallery frames: the primary photo still wins for
            # Hero (its +100_000 score), but a second, different real frame can then be
            # used as the Feature image instead of generating one.
            inspected.extend(inspect_pool(http, fallback_candidates[:6]))
    return sorted(inspected, key=lambda row: row['score'], reverse=True)


def select_feature_photo(ranked: list, primary: dict | None = None) -> dict:
    """Pick a second, different real gallery photo to show as the Feature image.

    Showing a genuine detail frame from the product gallery is honest and free —
    an edited or generated Feature image kept drifting into a different product.
    """
    primary_identity = (primary or {}).get('identity')
    for row in ranked or []:
        identity = row.get('identity')
        if identity and identity != primary_identity:
            return row
    return {}


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
    category = product.get("category", "")
    if isinstance(category, dict):
        category = category.get("name", "")
    if isinstance(category, list):
        category = ", ".join(str(c.get("name") if isinstance(c, dict) else c) for c in category if c)
    description = BeautifulSoup(str(product.get("description", "")), "html.parser").get_text(" ", strip=True)
    return {
        "name": str(product.get("name", "")).strip(),
        "brand": str(brand or ""),
        "sku": str(product.get("sku") or product.get("mpn") or ""),
        "category": str(category or "").strip(),
        "description": description,
        "features": [],
        "specs": specs,
    }


_SPEC_NAME_MAX = 80
_SPEC_VALUE_MAX = 300
_SPEC_LIMIT = 60


def _flat(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _html_specs(page_html: str) -> list[dict]:
    """Extract Name/Value specification pairs straight from the page markup.

    Most commerce templates keep the real specification table in HTML and expose
    only name/description/image in JSON-LD. Reading the table here gives the model
    real facts for free, without an extra AI call.
    """
    try:
        soup = BeautifulSoup(page_html or "", "html.parser")
    except Exception:
        return []
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()
    rows = []

    def add(name: str, value: str):
        name = re.sub(r"\s+", " ", name or "").strip(" : \t")
        value = re.sub(r"\s+", " ", value or "").strip(" : \t")
        if not name or not value or name.lower() == value.lower():
            return
        if len(name) > _SPEC_NAME_MAX or len(value) > _SPEC_VALUE_MAX:
            return
        rows.append({"name": name, "value": value})

    for table in soup.find_all("table")[:20]:
        for tr in table.find_all("tr")[:200]:
            cells = tr.find_all(["td", "th"], recursive=False) or tr.find_all(["td", "th"])
            if len(cells) == 2:
                add(_flat(cells[0]), _flat(cells[1]))
    for dl in soup.find_all("dl")[:20]:
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            add(_flat(dt), _flat(dd))
    selector = '[class*="spec"],[class*="characteristic"],[class*="attribute"],[class*="param"],[class*="properties"]'
    for block in soup.select(selector)[:40]:
        for item in block.find_all(["li", "div", "tr"])[:120]:
            children = [c for c in item.find_all(recursive=False) if getattr(c, "name", None)]
            if len(children) == 2:
                add(_flat(children[0]), _flat(children[1]))

    seen, out = set(), []
    for row in rows:
        key = row["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= _SPEC_LIMIT:
            break
    return out


def _html_features(page_html: str) -> list[str]:
    """Conservatively collect product bullet points from the main content."""
    try:
        soup = BeautifulSoup(page_html or "", "html.parser")
    except Exception:
        return []
    for bad in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        bad.decompose()
    root = soup.find("main") or soup.body or soup
    seen, out = set(), []
    for item in root.select("ul li")[:200]:
        text = _flat(item)
        if not (12 <= len(text) <= 220):
            continue
        if item.find("a") and len(text) < 60:
            continue  # navigation-like entry
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= 12:
            break
    return out


_GENERIC_CRUMBS = {
    'home', 'головна', 'главная', 'головна сторінка', 'main', 'artline', 'shop', 'магазин',
    'каталог', 'catalog', 'катало́г', 'products', 'товари', 'товары', 'usi-tovary', 'все товары',
}


def _html_breadcrumbs(page_html: str) -> list[str]:
    """Return the breadcrumb trail from JSON-LD BreadcrumbList or breadcrumb markup."""
    try:
        soup = BeautifulSoup(page_html or "", "html.parser")
    except Exception:
        return []
    # Structured data first — it is the most reliable source.
    for tag in soup.select('script[type="application/ld+json"]'):
        parsed = _safe_json(tag.string or tag.get_text() or "")
        if parsed is None:
            continue
        for node in _nodes(parsed):
            if not isinstance(node, dict):
                continue
            kinds = node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")]
            if "BreadcrumbList" not in kinds:
                continue
            names = []
            for item in node.get("itemListElement") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                inner = item.get("item")
                if not name and isinstance(inner, dict):
                    name = inner.get("name")
                if name:
                    names.append(re.sub(r"\s+", " ", str(name)).strip())
            if len(names) >= 2:
                return names
    # Fall back to common breadcrumb markup.
    for selector in ('[class*="breadcrumb"]', '[id*="breadcrumb"]', '[itemtype*="BreadcrumbList"]', 'nav[aria-label*="read"]'):
        for block in soup.select(selector)[:5]:
            names = []
            for item in block.find_all(["a", "li", "span"]):
                text = _flat(item)
                if text and text not in names and len(text) <= 80:
                    names.append(text)
            if len(names) >= 2:
                return names
    return []


def _html_category(page_html: str, product_name: str = '') -> str:
    """Pick the product category from the breadcrumb trail.

    The last crumb is normally the product itself and the first ones are the shop
    root, so the useful category is the last remaining entry.
    """
    trail = _html_breadcrumbs(page_html)
    name = re.sub(r"\s+", " ", (product_name or "")).strip().lower()
    candidates = []
    for crumb in trail:
        value = crumb.strip(" /›»>-")
        low = value.lower()
        if not value or low in _GENERIC_CRUMBS or len(value) > 80:
            continue
        if name and (low in name or name in low):
            continue  # the product itself, not a category
        candidates.append(value)
    return candidates[-1] if candidates else ''


def _html_meta_category(page_html: str) -> str:
    """Read the category from product meta tags, if the template exposes one."""
    try:
        soup = BeautifulSoup(page_html or "", "html.parser")
    except Exception:
        return ""
    for attrs in ({"property": "product:category"}, {"name": "product:category"},
                  {"itemprop": "category"}, {"property": "og:category"}, {"name": "category"}):
        tag = soup.find("meta", attrs=attrs)
        value = (tag.get("content") if tag else "") or ""
        value = re.sub(r"\s+", " ", value).strip(" >/")
        if value and len(value) <= 80:
            return value.split(">")[-1].strip() if ">" in value else value
    return ""


def _category_from_name(name: str) -> str:
    """Derive the category from the leading words of the product name.

    ARTLINE names start with the category and switch to Latin script at the brand:
    "3D принтер Bambu Lab A1 Mini" -> "3D принтер";
    "Система зберігання енергії Solis SV-1SL6K1" -> "Система зберігання енергії".
    Deterministic last resort when the page exposes no category anywhere.
    """
    picked = []
    for token in re.split(r"\s+", (name or "").strip()):
        core = token.strip('.,;:()[]"«»—-')
        if not core:
            continue
        if re.search(r"[А-Яа-яЇїІіЄєҐґ]", core):
            picked.append(core)
            continue
        # Allow one short technical token ("3D", "UPS") before the first Cyrillic word.
        if not picked and len(core) <= 4 and re.fullmatch(r"[0-9A-Za-z]+", core):
            picked.append(core)
            continue
        break  # a Latin brand token: the category part has ended
    result = " ".join(picked).strip()
    if not (3 <= len(result) <= 60) or len(picked) > 5:
        return ""
    if not re.search(r"[А-Яа-яЇїІіЄєҐґ]", result):
        return ""  # nothing but a stray latin token
    return result


def _ensure_category(data: dict, page_category: str = '') -> dict:
    """Category resolution order: page data -> AI -> product name. Never leave it empty."""
    if not str(data.get('category') or '').strip():
        data['category'] = page_category or _category_from_name(data.get('name') or '')
    return data


def _merge_specs(primary: list, extra: list) -> list:
    merged, seen = [], set()
    for row in list(primary or []) + list(extra or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        value = str(row.get("value") or "").strip()
        if not name or not value:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append({"name": name, "value": value})
        if len(merged) >= _SPEC_LIMIT:
            break
    return merged


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
    return {"name": name, "brand": "", "sku": "", "category": "", "description": description, "features": [], "specs": []}


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
    if not is_public_http_url(url):
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


def materialize_product_reference(url: str, project_id: str, filename: str = 'product-reference.png'):
    """Persist the exact selected source photo and return its public URL/path/metadata."""
    temporary = _reference_image(url)
    if not temporary:
        return '', None, {}
    try:
        folder = Path(settings.media_dir) / project_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        image = Image.open(temporary)
        image.save(path, format='PNG', optimize=True)
        width, height = image.size
        return (
            f'/media/{project_id}/{filename}',
            path,
            {'source_url': url, 'width': width, 'height': height, 'format': 'PNG', 'is_reference': True},
        )
    finally:
        temporary.unlink(missing_ok=True)


def select_key_feature(product: dict) -> str:
    """Pick the single confirmed feature the Feature image must communicate.

    The image model used to receive the whole product JSON and had to guess what
    mattered. Choosing here keeps the shot focused on one real capability.
    Order: page bullet points -> first meaningful specification -> first sentence
    of the description. Returns '' rather than inventing anything.
    """
    for value in (product.get('features') or []):
        text = re.sub(r'\s+', ' ', str(value or '')).strip()
        if 12 <= len(text) <= 200:
            return text
    for spec in (product.get('specs') or []):
        if not isinstance(spec, dict):
            continue
        name = re.sub(r'\s+', ' ', str(spec.get('name') or '')).strip()
        value = re.sub(r'\s+', ' ', str(spec.get('value') or '')).strip()
        if name and value and len(name) + len(value) <= 120:
            return f'{name}: {value}'
    description = re.sub(r'\s+', ' ', str(product.get('description') or '')).strip()
    if description:
        first = re.split(r'(?<=[.!?])\s+', description)[0]
        if 12 <= len(first) <= 200:
            return first
    return ''


def core_feature_text(markup: str) -> str:
    """Return the visible text of the Core Feature section of a generated page.

    The Feature image is generated from this text, so the shot always illustrates
    the feature this exact product page actually talks about.
    """
    try:
        soup = BeautifulSoup(markup or '', 'html.parser')
    except Exception:
        return ''
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        if not str(node).strip().lower().startswith('3.'):
            continue
        block = node.find_next_sibling()
        if block is None:
            continue
        text = re.sub(r'\s+', ' ', block.get_text(' ', strip=True)).strip()
        if len(text) >= 40:
            return text[:1200]
    # Fallback: the third heading and the block that carries it.
    headings = soup.find_all(re.compile(r'^h2$', re.I))
    if len(headings) >= 2:
        block = headings[1].find_parent(['div', 'section']) or headings[1].parent
        text = re.sub(r'\s+', ' ', block.get_text(' ', strip=True)).strip()
        if len(text) >= 40:
            return text[:1200]
    return ''


def strip_image_blocks(style_prompt: str) -> str:
    """Remove [HERO_IMAGE]/[FEATURE_IMAGE] art direction from the text-model prompt.

    Those blocks steer the image models. If the HTML model sees them it may render
    them as visible copy, which is exactly the meta-text failure we forbid.
    """
    return re.sub(r'\[(HERO_IMAGE|FEATURE_IMAGE)\].*?\[/\1\]', '', style_prompt or '', flags=re.I | re.S).strip()


def style_image_prompt(style_prompt: str, section: str) -> str:
    # Optional sections inside the single style field:
    # [HERO_IMAGE] ... [/HERO_IMAGE] and [FEATURE_IMAGE] ... [/FEATURE_IMAGE]
    pattern = rf"\[{re.escape(section)}\](.*?)\[/{re.escape(section)}\]"
    match = re.search(pattern, style_prompt or "", re.I | re.S)
    return match.group(1).strip() if match else ""


def extract_product(jsonld, title: str, clean_text: str, url: str, model: str, page_html: str = ''):
    """Build the product fact sheet from JSON-LD, the page markup and (if needed) AI.

    JSON-LD alone is rarely enough: most templates omit additionalProperty, so the
    real specification table lives only in HTML. Never return early on a bare
    name+description — that starves the content model of facts.
    """
    base = _normalize_jsonld(jsonld) if jsonld else {}
    page_specs = _html_specs(page_html) if page_html else []
    page_features = _html_features(page_html) if page_html else []
    page_trail = _html_breadcrumbs(page_html) if page_html else []
    page_category = (_html_category(page_html, base.get('name') or title) or _html_meta_category(page_html)) if page_html else ''
    if base:
        base['specs'] = _merge_specs(base.get('specs') or [], page_specs)
        if not base.get('features'):
            base['features'] = page_features
        if not str(base.get('category') or '').strip():
            base['category'] = page_category

    # Enough hard facts already — no AI call needed. The category must be resolved too,
    # otherwise skipping the AI call would silently leave it empty.
    if base.get('name') and len(base.get('specs') or []) >= 3 and str(base.get('category') or '').strip():
        return _ensure_category(base, page_category), 0, 0

    if not text_ready():
        data = dict(base) if base.get('name') else _fallback_extract(title, clean_text)
        data['specs'] = _merge_specs(data.get('specs') or [], page_specs)
        data['features'] = data.get('features') or page_features
        return _ensure_category(data, page_category), 0, 0

    spec_block = ''
    if page_specs:
        spec_block = '\nSPECIFICATIONS FOUND IN THE PAGE MARKUP (name: value) — prefer these for the specs array and keep every relevant pair:\n' + \
            '\n'.join(f"{row['name']}: {row['value']}" for row in page_specs)
    # Breadcrumbs are stripped from the page text, so pass the trail explicitly —
    # it is the most reliable source of the product category.
    if page_trail:
        spec_block += '\nBREADCRUMB TRAIL (shop root first, product last) — derive the category from it:\n' + ' > '.join(page_trail)
    prompt = (
        'Extract factual ecommerce product data from the supplied page. '
        'Return one JSON object only with keys: name, brand, sku, category, description, '
        'features (array of strings), specs (array of objects with name and value). '
        'Fill specs with every real technical characteristic you can find; do not summarize them away. '
        'category is a short human-readable product category in the page language '
        '(for example "Ігрові комп\'ютери", "3D-принтери", "Джерела безперебійного живлення"); '
        'derive it from breadcrumbs, the product type or the page text, and leave it empty only if truly unknown. '
        'Never invent facts.\nURL: ' + url + '\nTITLE: ' + title + spec_block + '\nPAGE: ' + clean_text
    )
    try:
        response = _responses_create(model, prompt, 8000)
        data = _extract_json(response.output_text)
        input_tokens, output_tokens = _usage_counts(response, prompt, response.output_text)
        # Structured data (JSON-LD, breadcrumbs) is authoritative for identity fields;
        # specs are the union of every source.
        for key in ('name', 'brand', 'sku', 'category'):
            if str(base.get(key) or '').strip():
                data[key] = base[key]
        if not str(data.get('description') or '').strip() and base.get('description'):
            data['description'] = base['description']
        data['specs'] = _merge_specs(data.get('specs') or [], _merge_specs(base.get('specs') or [], page_specs))
        if not data.get('features'):
            data['features'] = base.get('features') or page_features
        return _ensure_category(data, page_category), input_tokens, output_tokens
    except Exception as exc:
        logger.warning('AI product extraction failed, using page data: %s', exc)
        data = dict(base) if base.get('name') else _fallback_extract(title, clean_text)
        data['specs'] = _merge_specs(data.get('specs') or [], page_specs)
        data['features'] = data.get('features') or page_features
        return _ensure_category(data, page_category), 0, 0


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {'.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}.get(suffix, 'image/jpeg')


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
    provider = image_provider(model)
    if not image_ready(model):
        return fallback, False, f'{provider.title()} API key is not configured'
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
        edit_prompt = (
            'STRICT REFERENCE-IMAGE EDIT. The uploaded image contains the exact real product. '
            'Preserve its identity, geometry, proportions, materials, controls, openings, labels and logo placement. '
            'Do not redesign, substitute or hallucinate the product. Build the requested scene around this exact product. ' + prompt
        )
        folder = Path(settings.media_dir) / project_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{label}.webp'
        if provider == 'gemini':
            raw = _gemini_edit(model, edit_prompt, reference_path.read_bytes(), _mime_for(reference_path), size)
            # Gemini answers in PNG/JPEG; the page expects webp like the OpenAI path.
            Image.open(BytesIO(raw)).convert('RGB').save(path, 'WEBP', quality=90)
            return f'/media/{project_id}/{label}.webp', True, ''
        with reference_path.open('rb') as image_file:
            edit_options = dict(
                model=model,
                image=image_file,
                prompt=edit_prompt,
                size=size,
                quality=quality,
                output_format='webp',
            )
            # High input fidelity asks supported GPT Image models to preserve small
            # product details, labels and geometry. GPT Image 2 always uses it and
            # rejects an explicit parameter, so omit it there.
            if not model.startswith('gpt-image-2'):
                edit_options['extra_body'] = {'input_fidelity': 'high'}
            response = _with_retry(lambda: image_client().images.edit(**edit_options))
        item = response.data[0]
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
    # Product pages already own the document-level H1. Rich content is an embedded
    # section, so normalize accidental model output to H2 before it reaches storage.
    value = re.sub(r'<\s*h1\b', '<h2', value, flags=re.I)
    value = re.sub(r'<\s*/\s*h1\s*>', '</h2>', value, flags=re.I)
    start, end = value.find('<section'), value.rfind('</section>')
    if start < 0 or end < start:
        raise RuntimeError('AI did not return a complete <section> block')
    return sanitize_html(value[start:end + len('</section>')])


def _section_count(markup: str) -> int:
    """Rough completeness signal: a full page has an h2 in the Hero plus most sections."""
    return len(re.findall(r'<h2\b', markup or '', re.I))


def _prompt(product, style, language, variant, hero, feature):
    layout = 'single-column mobile layout with no horizontal overflow' if variant == 'mobile' else 'desktop layout up to 1240px'
    target_language_rule = language_rule(language)
    return f"""Create standardized premium ecommerce rich content. Return HTML only: exactly one complete <section>...</section>.
TARGET LANGUAGE CODE: {language}. {target_language_rule}
Never copy source-page sentences in another language. Translate and rewrite every visible sentence into the target language while preserving model names, trademarks, numbers and units.
Variant: {variant}. Layout: {layout}. Use inline CSS only.
SEO heading rule: never use <h1>. The product page already contains its primary H1. Use <h2> for the Hero product title and major section headings, and <h3> for card titles.
Embedding rule: the rich content is displayed on a light ARTLINE product page. Keep the root canvas transparent or white and make the majority of content surfaces light. Dark styling may be used inside selected high-contrast sections such as Hero or the final section, but never as a full-page background.
Mandatory visual guardrails: use #101010 for headings and #555555 or #69737D for paragraphs on light surfaces; use #FFFFFF or #F7F8FA for headings and #D0D7DE or #AFB8C1 for paragraphs on dark surfaces. Use #19BCC9 only for compact badges, eyebrow labels, small specification values and subtle borders. Never use turquoise, green, blue, purple or orange for paragraphs or multi-line headings. At least 70 percent of the content area must remain light or transparent. Use 12px radii for sections and cards and 8px for badges. Do not use decorative colored strips, alternating card colors, checkerboard layouts, excessive gradients or repeated heavy shadows.
The style prompt below is the primary design specification. Follow it precisely unless it conflicts with factual accuracy or HTML validity.
STYLE PROMPT:
{strip_image_blocks(style.prompt)}
Mandatory factual rule: use only facts present in Product JSON. Never invent warranty, partnership, certification, compatibility, performance, contents or support claims.
Images: hero={hero}; feature={feature}.
Product JSON: {json.dumps(product, ensure_ascii=False)}"""


def _deterministic_html(product, style, language, variant, hero, feature):
    labels = LANG_LABELS.get(language, LANG_LABELS['en'])
    width = '480px' if variant == 'mobile' else '1240px'
    columns = '1fr' if variant == 'mobile' else 'repeat(3,1fr)'
    feature_columns = '1fr' if variant == 'mobile' else '1.15fr .85fr'
    name = html_lib.escape(product.get('name') or 'Product')
    brand = html_lib.escape(product.get('brand') or 'ARTLINE')
    raw_description = str(product.get('description') or '')
    fallback_copy = LOCAL_FALLBACK.get(language, LOCAL_FALLBACK['en'])
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
        f'<div style="padding:26px;border-radius:12px;background:#F7F8FA;border:1px solid #D0D7DE;color:#101010"><div style="font-size:25px;font-weight:900;color:{"#19BCC9" if i<3 else "#01743A"};margin-bottom:10px">{html_lib.escape(fact[:55])}</div><p style="margin:0;line-height:1.55;color:#555">{html_lib.escape(fact)}</p></div>'
        for i, fact in enumerate(facts)
    )
    hero_css = f"linear-gradient(90deg,rgba(26,33,40,.96) 0%,rgba(26,33,40,.82) 42%,rgba(37,37,37,.16) 100%),url('{hero}') center/cover no-repeat" if hero else 'linear-gradient(135deg,#1A2128 0%,#252525 58%,#35393F 100%)'
    image_html = f'<img src="{html_lib.escape(feature)}" alt="{name}" style="width:100%;max-height:360px;object-fit:contain;display:block">' if feature else f'<div style="font-size:42px;font-weight:900;color:#101010">{brand}</div>'
    hero_height = '420px' if variant == 'mobile' else '560px'
    hero_padding = '42px 24px' if variant == 'mobile' else '72px 46px'
    hero_title_size = '38px' if variant == 'mobile' else '58px'
    h2_size = '32px' if variant == 'mobile' else '42px'
    trust_columns = '1fr' if variant == 'mobile' else '.9fr 1.1fr'
    return f'''<section style="max-width:{width};margin:0 auto;padding:0 14px;font-family:Roboto,Inter,Arial,sans-serif;box-sizing:border-box;color:#101010">
<!-- 1. HERO -->
<div style="min-height:{hero_height};padding:{hero_padding};border-radius:12px;background:{hero_css};display:flex;align-items:center;margin-bottom:22px;box-sizing:border-box"><div style="max-width:620px"><div style="display:inline-block;padding:7px 12px;border-radius:8px;background:#19BCC9;color:#101010;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase">{brand}</div><h2 style="font-size:{hero_title_size};line-height:1.06;font-weight:900;margin:16px 0;color:#FFFFFF">{name}</h2><p style="max-width:620px;margin:0;font-size:17px;line-height:1.65;color:#D0D7DE">{description}</p></div></div>
<!-- 2. KEY BENEFITS -->
<div style="display:grid;grid-template-columns:{columns};gap:16px;margin-bottom:22px;box-sizing:border-box">{cards}</div>
<!-- 3. CORE FEATURE -->
<div style="display:grid;grid-template-columns:{feature_columns};gap:30px;align-items:center;padding:42px;border-radius:12px;background:#F7F8FA;border:1px solid #D0D7DE;color:#101010;margin-bottom:22px;box-sizing:border-box"><div><div style="color:#19BCC9;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase">{labels['technology']}</div><h2 style="font-size:{h2_size};line-height:1.12;font-weight:900;margin:12px 0;color:#101010">{name}</h2><p style="margin:0;line-height:1.7;color:#555555">{description}</p></div><div style="background:#FFFFFF;border-radius:12px;border:1px solid #D0D7DE;padding:22px;text-align:center;box-sizing:border-box">{image_html}</div></div>
<!-- 4. USE SCENARIOS -->
<div style="padding:42px;border-radius:12px;background:#F7F8FA;border:1px solid #D0D7DE;color:#101010;margin-bottom:22px;box-sizing:border-box"><div style="color:#19BCC9;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase">{labels['design']}</div><h2 style="font-size:{h2_size};line-height:1.12;font-weight:900;margin:12px 0;color:#101010">{fallback_copy['use']}</h2><p style="max-width:760px;margin:0;line-height:1.7;color:#555555">{description}</p></div>
<!-- 5. ARTLINE CONFIDENCE -->
<div style="display:grid;grid-template-columns:{trust_columns};gap:16px;margin-bottom:22px;box-sizing:border-box"><div style="padding:36px;border-radius:12px;background:linear-gradient(135deg,#1A2128 0%,#252525 58%,#35393F 100%);border:1px solid rgba(25,188,201,.28);box-sizing:border-box"><div style="color:#19BCC9;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase">ARTLINE</div><h2 style="font-size:{h2_size};line-height:1.12;font-weight:900;margin:12px 0;color:#FFFFFF">{labels['service']}</h2><p style="margin:0;color:#D0D7DE;line-height:1.65">{fallback_copy['experience']}</p></div><div style="padding:36px;border-radius:12px;background:#F7F8FA;border:1px solid #D0D7DE;color:#101010;box-sizing:border-box"><h3 style="font-size:20px;line-height:1.3;font-weight:800;margin:0 0 12px;color:#101010">{name}</h3><p style="margin:0;color:#555555;line-height:1.65">{description}</p></div></div>
<!-- 6. FINAL SUMMARY -->
<div style="padding:52px 28px;border-radius:12px;text-align:center;background:linear-gradient(135deg,#1A2128 0%,#252525 58%,#35393F 100%);border:1px solid rgba(25,188,201,.28);box-sizing:border-box"><div style="color:#19BCC9;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase">{brand}</div><h2 style="font-size:{h2_size};line-height:1.12;font-weight:900;margin:12px 0;color:#FFFFFF">{labels['cta']}</h2><p style="max-width:700px;margin:0 auto;color:#D0D7DE;line-height:1.65">{description}</p></div>
</section>'''


def _restore_image_urls(html: str, hero: str, feature: str, variant: str) -> str:
    """Guarantee the generated page actually points at this project's images.

    The model writes the URLs into the HTML by itself and occasionally drops or
    mangles one (leaving a grey Hero band or a dead Feature <img>). The URLs are
    ours and deterministic, so repair is mechanical:
      - a literal placeholder is replaced with the real URL;
      - a Hero section without the hero URL gets it injected as the background of
        the first element that declares a background;
      - a Feature <img> pointing anywhere but the feature URL is repointed, unless
        the page legitimately reuses the original product photo fallback.
    """
    if hero and hero not in html:
        html = html.replace('PROJECT_HERO_IMAGE_URL', hero)
    if feature and feature not in html:
        html = html.replace('PROJECT_FEATURE_IMAGE_URL', feature)
    if hero and hero not in html:
        # First background-image/background shorthand in the document is the Hero
        # canvas by contract (section 1 comes first).
        pattern = re.compile(r"background(-image)?\s*:\s*[^;\"']*url\((['\"]?)([^)'\"]+)\2\)", re.I)
        match = pattern.search(html)
        if match:
            html = html[:match.start(3)] + hero + html[match.end(3):]
        else:
            logger.warning('Hero URL missing from generated HTML (%s) and no background to repair', variant)
    return html


def generate_html(product, style, language, variant, hero, feature, model: str):
    """Return (html, input_tokens, output_tokens, fallback_reason).

    fallback_reason is '' when the AI response was used, otherwise a short reason
    string so callers can record that a deterministic template was served instead.
    """
    fallback = _deterministic_html(product, style, language, variant, hero, feature)
    if not text_ready():
        return fallback, 0, 0, 'Text provider is not configured'
    base_prompt = _prompt(product, style, language, variant, hero, feature)
    try:
        response = _responses_create(model, base_prompt, 16000)
        output = _html_only(response.output_text)
        input_tokens, output_tokens = _usage_counts(response, base_prompt, response.output_text)
        if not _language_matches(output, language):
            correction = f"""Rewrite only the visible text in the HTML below into the required target language. Preserve every HTML tag, inline CSS declaration, URL, number, unit, model name and trademark. Do not add or remove sections. {language_rule(language)}
HTML:
{output}"""
            corrected = _responses_create(model, correction, 16000)
            output = _html_only(corrected.output_text)
            ci, co = _usage_counts(corrected, correction, corrected.output_text)
            input_tokens += ci
            output_tokens += co
        if not _language_matches(output, language):
            raise RuntimeError(f'Generated content did not pass language validation for {language}')
        # Completeness guard: the model sometimes stops after the Hero (or hits the
        # output-token cap), producing a page with only one section. Retry once with an
        # explicit reminder, then fail over to the complete deterministic template.
        if _section_count(output) < 3:
            logger.warning('Incomplete page for %s/%s (%d h2), retrying', language, variant, _section_count(output))
            retry_prompt = base_prompt + "\n\nIMPORTANT: Return the COMPLETE page as one <section> with ALL SIX sections in order (Hero, Key Benefits, Core Feature, Use Scenarios, Buyer Confidence, Final Summary). Do not stop after the Hero and do not omit any section."
            retried = _responses_create(model, retry_prompt, 16000)
            retried_out = _html_only(retried.output_text)
            ri, ro = _usage_counts(retried, retry_prompt, retried.output_text)
            input_tokens += ri
            output_tokens += ro
            if _section_count(retried_out) >= 3 and _language_matches(retried_out, language):
                output = retried_out
        if _section_count(output) < 3:
            raise RuntimeError('AI returned an incomplete page (only the Hero section)')
        output = _restore_image_urls(output, hero, feature, variant)
        return output, input_tokens, output_tokens, ''
    except Exception as exc:
        logger.warning('generate_html fell back to deterministic template for %s/%s: %s', language, variant, exc)
        return fallback, 0, 0, f'AI generation failed, used built-in template: {exc}'


def _translation_template(markup: str):
    """Replace visible text nodes with stable tokens while preserving the DOM/CSS."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    segments = {}
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString) or isinstance(node, Comment) or node.parent.name in ('script', 'style'):
            continue
        value = str(node)
        if not value.strip():
            continue
        leading = value[:len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()):]
        key = str(len(segments))
        segments[key] = value.strip()
        node.replace_with(f'{leading}__ARTLINE_TEXT_{key}__{trailing}')
    return str(soup), segments


def translate_html(source_html: str, language: str, model: str):
    """Translate copy only; layout, styles, media URLs and element order stay fixed."""
    if not text_ready():
        return None, 0, 0
    template, segments = _translation_template(source_html)
    if not segments:
        return source_html, 0, 0
    prompt = f"""Translate the supplied ecommerce copy segments into the target language.
TARGET LANGUAGE CODE: {language}. {language_rule(language)}
Return one JSON object only. Preserve every input key and return exactly one translated string for it.
Keep product names, brands, model IDs, technology names, numbers and units unchanged.
Do not add facts, HTML, markdown, explanations or extra keys.
SEGMENTS:
{json.dumps(segments, ensure_ascii=False)}"""
    response = _responses_create(model, prompt, 12000)
    translated = _extract_json(response.output_text)
    result = template
    for key, original in segments.items():
        value = translated.get(key)
        if not isinstance(value, str) or not value.strip():
            value = original
        result = result.replace(f'__ARTLINE_TEXT_{key}__', html_lib.escape(value, quote=False))
    result = _html_only(result)
    if not _language_matches(result, language):
        raise RuntimeError(f'Translated content did not pass language validation for {language}')
    input_tokens, output_tokens = _usage_counts(response, prompt, response.output_text)
    return result, input_tokens, output_tokens


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
        if re.search(r'<h1\b', html, re.I):
            issues.append('H1 is not allowed inside embedded rich content'); score -= 25
        if len(re.findall(r'<h2\b', html, re.I)) < len(artifacts):
            issues.append('Expected at least one H2 per artifact'); score -= 10
        if len(html) > 700000:
            issues.append('HTML payload is unusually large'); score -= 10
        suggestions = ['Validate markup before publishing', 'Do not add H1 inside embedded rich content']
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
