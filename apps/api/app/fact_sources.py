"""Джерела фактів: безпечне завантаження документа, рівні довіри, ідентичність товару.

Інтернет тут ніколи не є джерелом істини сам по собі. Пошук лише знаходить
адреси; фактом стає конкретний ВІДКРИТИЙ документ (сторінка виробника,
datasheet, manual, офіційний реєстр), з якого взято точний фрагмент-доказ.

Що гарантує цей модуль:

* ``validate_research_url`` - лише http(s), без облікових даних в адресі, без
  localhost, внутрішніх імен без крапки, ``.local``/``.internal``/``.lan``,
  приватних, loopback, link-local і reserved адрес (DNS перевіряється);
* ``PageFetcher`` - кожен редирект перевіряється заново (не більше 5), відповідь
  обмежена за розміром ще під час завантаження, MIME з allowlist, таймаут,
  robots.txt поважається, запити йдуть послідовно з паузою на домен, коректний
  User-Agent, JavaScript джерела ніколи не виконується;
* PDF розбирається окремим кодом (pypdf) з обмеженням сторінок, обсягу тексту,
  часу і розпакування потоків (захист від zip bomb);
* ``classify_source`` - рівні A (офіційний виробник / datasheet / manual /
  support / реєстр сертифікації), B (дистрибʼютор, лише з попередженням),
  C (маркетплейси, магазини, форуми, огляди, відео, агрегатори, AI) -
  з рівня C утверджений факт не формується ніколи;
* ``IdentityMatcher`` - точна модель, SKU, суфікс, ревізія, обсяг/конфігурація,
  регіон і покоління. Нечіткий збіг ніколи не дозволяє факт.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

USER_AGENT = 'ARTLINE-RichStudio-FactResearch/1.0 (+https://github.com/seemyminiwong/rich-ai)'
MAX_REDIRECTS = 5
DOMAIN_DELAY_SECONDS = 1.0
PDF_MAX_PAGES = 60
PDF_MAX_CHARS = 400_000
TEXT_MAX_CHARS = 400_000
ALLOWED_MIME = {
    'text/html': 'html', 'application/xhtml+xml': 'html', 'text/plain': 'text', 'application/pdf': 'pdf',
}
_BAD_HOST_SUFFIXES = ('.local', '.internal', '.lan', '.home', '.localdomain', '.intranet', '.corp', '.arpa')


class FetchBlocked(RuntimeError):
    """Документ не завантажено з причини безпеки або політики (не мережевий збій)."""


# ---------------------------------------------------------------------------
# URL guard
# ---------------------------------------------------------------------------

def _address_is_public(ip) -> bool:
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _resolves_public(host: str, port: int) -> bool:
    """Усі адреси, в які резолвиться хост, мають бути публічними."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(infos) and all(_address_is_public(ipaddress.ip_address(info[4][0])) for info in infos)


def validate_research_url(url: str) -> str:
    """Повертає нормалізовану адресу або кидає FetchBlocked із причиною."""
    url = str(url or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise FetchBlocked(f'Дозволено лише http(s), отримано «{parsed.scheme or "без схеми"}»')
    if parsed.username or parsed.password:
        raise FetchBlocked('Адреса з обліковими даними заборонена')
    host = (parsed.hostname or '').lower().rstrip('.')
    if not host:
        raise FetchBlocked('Адреса без хоста')
    if host == 'localhost' or host.endswith('.localhost') or host.endswith(_BAD_HOST_SUFFIXES):
        raise FetchBlocked(f'Внутрішнє імʼя хоста заборонене: {host}')
    try:
        literal = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        literal = None
    if literal is not None:
        if not _address_is_public(literal):
            raise FetchBlocked(f'Непублічна адреса заборонена: {host}')
    elif '.' not in host:
        raise FetchBlocked(f'Внутрішнє імʼя без домену заборонене: {host}')
    if parsed.port not in (None, 80, 443):
        raise FetchBlocked(f'Нестандартний порт заборонений: {parsed.port}')
    if literal is None and not _resolves_public(host, parsed.port or (443 if parsed.scheme == 'https' else 80)):
        raise FetchBlocked(f'Хост не резолвиться в публічну адресу: {host}')
    return parsed._replace(fragment='').geturl()


def domain_of(url: str) -> str:
    host = (urlparse(url or '').hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def _domain_matches(host: str, domains) -> bool:
    host = host.lower()
    return any(host == d or host.endswith('.' + d) for d in (str(x).lower().lstrip('.') for x in domains or []) if d)


# ---------------------------------------------------------------------------
# Рівні довіри
# ---------------------------------------------------------------------------

# Офіційні домени виробників, що продаються на artline.ua. Оператор доповнює
# список для конкретного запуску («Офіційні домени» у вкладці «Факти»).
BRAND_DOMAINS = {
    'asus': ['asus.com'], 'rog': ['asus.com', 'rog.asus.com'], 'bambu lab': ['bambulab.com'], 'bambulab': ['bambulab.com'],
    'deye': ['deyeinverter.com', 'deye.com', 'deyeess.com'], 'hyte': ['hyte.com'], 'nvidia': ['nvidia.com'],
    'gembird': ['gembird.com', 'gmb.nl'], 'gamemax': ['gamemaxpc.com'], 'creality': ['creality.com'],
    'lian li': ['lian-li.com'], 'corsair': ['corsair.com'], 'msi': ['msi.com'], 'gigabyte': ['gigabyte.com'],
    'asrock': ['asrock.com'], 'samsung': ['samsung.com'], 'lg': ['lg.com'], 'dell': ['dell.com'], 'hp': ['hp.com'],
    'lenovo': ['lenovo.com'], 'apple': ['apple.com'], 'logitech': ['logitech.com', 'logitechg.com'], 'razer': ['razer.com'],
    'tp-link': ['tp-link.com'], 'ubiquiti': ['ui.com'], 'synology': ['synology.com'], 'qnap': ['qnap.com'], 'apc': ['apc.com', 'se.com'],
    'eaton': ['eaton.com'], 'solis': ['solisinverters.com', 'ginlong.com'], 'huawei': ['huawei.com'], 'xiaomi': ['mi.com'],
    'epson': ['epson.com'], 'canon': ['canon.com'], 'brother': ['brother.com'], 'philips': ['philips.com'], 'aoc': ['aoc.com'],
    'benq': ['benq.com'], 'viewsonic': ['viewsonic.com'], 'kingston': ['kingston.com'], 'western digital': ['westerndigital.com'],
    'seagate': ['seagate.com'], 'crucial': ['crucial.com'], 'intel': ['intel.com'], 'amd': ['amd.com'], 'noctua': ['noctua.at'],
    'be quiet!': ['bequiet.com'], 'cooler master': ['coolermaster.com'], 'thermaltake': ['thermaltake.com'], 'nzxt': ['nzxt.com'],
    'fractal design': ['fractal-design.com'], 'deepcool': ['deepcool.com'], 'arctic': ['arctic.de'], 'sharkoon': ['sharkoon.com'],
    'zotac': ['zotac.com'], 'palit': ['palit.com'], 'sapphire': ['sapphiretech.com'], 'supermicro': ['supermicro.com'],
    'ecoflow': ['ecoflow.com'], 'bluetti': ['bluettipower.com'], 'anker': ['anker.com'], 'baseus': ['baseus.com'], 'ugreen': ['ugreen.com'],
    'qube': ['qube.com.ua'], 'artline': ['artline.ua'], 'prusa': ['prusa3d.com'], 'elegoo': ['elegoo.com'], 'anycubic': ['anycubic.com'],
}
# Публічні реєстри сертифікації - рівень A для фактів сертифікації.
REGISTRY_DOMAINS = ['eprel.ec.europa.eu', 'fccid.io', 'fcc.gov', 'energystar.gov', 'productiq.ulprospector.com', 'tuv.com',
                    'certipedia.com', 'ec.europa.eu']
# Рівень C: лише редакційні підказки (research_only). Невідомий домен - теж C.
TIER_C_DOMAINS = [
    'amazon.com', 'amazon.de', 'amazon.pl', 'ebay.com', 'aliexpress.com', 'alibaba.com', 'rozetka.com.ua', 'prom.ua', 'allegro.pl',
    'olx.ua', 'olx.pl', 'hotline.ua', 'ek.ua', 'epicentrk.ua', 'comfy.ua', 'foxtrot.com.ua', 'moyo.ua', 'citrus.com.ua', 'brain.com.ua',
    'telemart.ua', 'ceneo.pl', 'x-kom.pl', 'morele.net', 'mediaexpert.pl', 'newegg.com', 'bestbuy.com', 'walmart.com',
    'reddit.com', 'youtube.com', 'youtu.be', 'facebook.com', 'instagram.com', 'tiktok.com', 'x.com', 'twitter.com', 'medium.com',
    'wikipedia.org', 'tomshardware.com', 'techpowerup.com', 'anandtech.com', 'notebookcheck.net', 'rtings.com', 'pcmag.com',
    'theverge.com', 'gsmarena.com', 'versus.com', 'nanoreview.net', 'quora.com', 'stackexchange.com', 'chatgpt.com', 'perplexity.ai',
    'gemini.google.com', 'copilot.microsoft.com', 'google.com', 'bing.com', 'artline.ua',
]
_DOC_HINTS = (
    ('datasheet', r'datasheet|data-sheet|data_sheet|spec[-_ ]?sheet|specifications?\.pdf|techspec'),
    ('manual', r'manual|user[-_ ]?guide|handbook|instrukcj|інструкц|инструкц|quick[-_ ]?start'),
    ('support', r'/support|/supports|/download|/faq|/helpdesk|/knowledge'),
)


@dataclass
class SourceClass:
    tier: str            # A | B | C
    source_type: str     # official_product_page | datasheet | manual | support | regional_page | certification_registry | distributor | marketplace | forum | review | video | aggregator | ai_answer | unknown
    note: str = ''


def manufacturer_domains(brand: str, extra=None) -> list[str]:
    key = (brand or '').strip().lower()
    out = list(BRAND_DOMAINS.get(key, []))
    for name, domains in BRAND_DOMAINS.items():
        if name != key and key and (key.startswith(name + ' ') or name.startswith(key + ' ')):
            out += domains
    out += [str(d).lower().strip().lstrip('.') for d in (extra or []) if str(d).strip()]
    return list(dict.fromkeys(d for d in out if d and d != 'artline.ua'))


def classify_source(url: str, official: list[str], distributors: list[str] | None = None, content_type: str = '') -> SourceClass:
    host = domain_of(url)
    path = urlparse(url or '').path.lower()
    if _domain_matches(host, REGISTRY_DOMAINS):
        return SourceClass('A', 'certification_registry')
    if _domain_matches(host, TIER_C_DOMAINS):
        kind = ('video' if 'youtu' in host else 'forum' if host.endswith(('reddit.com', 'quora.com', 'stackexchange.com')) else
                'ai_answer' if host in ('chatgpt.com', 'perplexity.ai', 'gemini.google.com', 'copilot.microsoft.com') else
                'aggregator' if host in ('google.com', 'bing.com', 'versus.com', 'nanoreview.net', 'hotline.ua', 'ek.ua', 'ceneo.pl') else
                'review' if host in ('tomshardware.com', 'techpowerup.com', 'anandtech.com', 'notebookcheck.net', 'rtings.com', 'pcmag.com', 'theverge.com', 'gsmarena.com', 'wikipedia.org', 'medium.com') else
                'marketplace')
        return SourceClass('C', kind, 'лише редакційна підказка')
    if official and _domain_matches(host, official):
        for kind, pattern in _DOC_HINTS:
            if re.search(pattern, path):
                return SourceClass('A', kind)
        if content_type == 'pdf' or path.endswith('.pdf'):
            return SourceClass('A', 'datasheet')
        if re.search(r'/(uk|ua|pl|en|de|eu|us|global|ru)(-[a-z]{2})?/', path + '/'):
            return SourceClass('A', 'regional_page')
        return SourceClass('A', 'official_product_page')
    if distributors and _domain_matches(host, distributors):
        return SourceClass('B', 'distributor', 'офіційний дистрибʼютор - лише ручне підтвердження з попередженням')
    if re.search(r'forum|community|board|/thread', host + path):
        return SourceClass('C', 'forum', 'лише редакційна підказка')
    return SourceClass('C', 'unknown', 'домен не підтверджено як офіційний - лише редакційна підказка')


# ---------------------------------------------------------------------------
# Завантаження документа
# ---------------------------------------------------------------------------

@dataclass
class Document:
    url: str
    final_url: str
    content_type: str          # html | text | pdf
    text: str
    title: str = ''
    html: str = ''
    content_hash: str = ''
    fetched_at: str = ''
    pages: list = field(default_factory=list)   # для PDF: текст по сторінках
    injection_flags: list = field(default_factory=list)


INJECTION_PATTERNS = [
    r'ignore (all |any )?(the )?previous instructions', r'disregard (all |the )?(previous|above) instructions',
    r'send (me )?(your |the )?credentials', r'change (the )?system prompt', r'approve this fact', r'you are now',
    r'системн\w+ (промпт|інструкц)', r'ігноруй (усі |всі )?попередні', r'игнорируй (все )?предыдущие',
    r'reveal (the )?(api )?key', r'mark (this|it) as (approved|verified)',
]


def detect_injection(text: str) -> list[str]:
    """Фрази-інструкції в джерелі. Їх не виконують - лише позначають у звіті."""
    low = (text or '').lower()
    return [p for p in INJECTION_PATTERNS if re.search(p, low)]


def html_to_text(markup: str) -> tuple[str, str]:
    """(видимий текст, title) без скриптів, стилів, форм і навігації. JS не виконується."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    title = ' '.join((soup.title.get_text(' ') if soup.title else '').split())[:300]
    for bad in soup(['script', 'style', 'noscript', 'template', 'iframe', 'svg', 'form', 'nav', 'footer', 'header']):
        bad.decompose()
    lines = []
    for row in soup.find_all('tr'):
        cells = [' '.join(c.get_text(' ').split()) for c in row.find_all(['th', 'td'])]
        if len(cells) >= 2 and cells[0] and cells[1]:
            lines.append(f'{cells[0]}: {cells[1]}')
        row.decompose()
    for dl in soup.find_all('dl'):
        for dt, dd in zip(dl.find_all('dt'), dl.find_all('dd')):
            lines.append(f'{" ".join(dt.get_text(" ").split())}: {" ".join(dd.get_text(" ").split())}')
        dl.decompose()
    text = soup.get_text('\n')
    lines += [' '.join(line.split()) for line in text.splitlines() if line.strip()]
    return '\n'.join(lines)[:TEXT_MAX_CHARS], title


def pdf_to_text(blob: bytes, timeout: float = 20.0) -> tuple[str, list[str]]:
    """Текст PDF окремим кодом: стеля сторінок, обсягу тексту, часу і розпакування.

    Шифровані, пошкоджені та «бомбові» PDF не розбираються - кидається
    FetchBlocked, документ пропускається."""
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - залежність є в requirements
        raise FetchBlocked('PDF-розбір недоступний (pypdf не встановлено)') from exc
    # Стелі розпакування й структури саме для цього розбору (pypdf 6 Configuration,
    # контекст лише на час виклику): zip bomb і рекурсивне дерево сторінок
    # зупиняються в pypdf, а не в памʼяті воркера.
    limits = dict(maximum_declared_stream_length=20_000_000, array_based_stream_maximum_output_length=20_000_000,
                  jbig2_maximum_output_length=20_000_000, lzw_maximum_output_length=20_000_000,
                  run_length_maximum_output_length=20_000_000, zlib_maximum_output_length=20_000_000,
                  image_maximum_buffer_size=20_000_000, page_tree_maximum_entries=5_000, page_tree_maximum_depth=40,
                  xform_maximum_invocations_per_extraction=500)
    started = time.monotonic()
    try:
        with pypdf.apply_configuration(**limits):
            reader = pypdf.PdfReader(io.BytesIO(blob), strict=False, root_object_recovery_limit=2_000)
            if reader.is_encrypted:
                raise FetchBlocked('PDF зашифровано - не розбирається')
            pages, total = [], 0
            for index, page in enumerate(reader.pages):
                if index >= PDF_MAX_PAGES:
                    break
                if time.monotonic() - started > timeout:
                    raise FetchBlocked(f'PDF розбирається довше {timeout:.0f} с - зупинено')
                chunk = page.extract_text() or ''
                total += len(chunk)
                if total > PDF_MAX_CHARS:
                    pages.append(chunk[:max(0, PDF_MAX_CHARS - (total - len(chunk)))])
                    break
                pages.append(chunk)
    except FetchBlocked:
        raise
    except Exception as exc:
        raise FetchBlocked(f'PDF не вдалося розібрати: {type(exc).__name__}') from exc
    text = '\n'.join(' '.join(line.split()) for page in pages for line in page.splitlines() if line.strip())
    return text, pages


class PageFetcher:
    """Послідовне, обмежене і повністю перевірене завантаження документів."""

    def __init__(self, max_bytes: int = 8_000_000, timeout: float = 30.0, transport=None, respect_robots: bool = True,
                 domain_delay: float = DOMAIN_DELAY_SECONDS, clock=time.monotonic, sleep=time.sleep):
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.transport = transport
        self.respect_robots = respect_robots
        self.domain_delay = domain_delay
        self._last_hit: dict = {}
        self._robots: dict = {}
        self._clock = clock
        self._sleep = sleep

    def _client(self):
        import httpx
        if self.transport is not None:
            return httpx.Client(timeout=self.timeout, follow_redirects=False, transport=self.transport,
                                headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/pdf,text/plain;q=0.8'})
        from app.pipeline import safe_client
        # Редиректи обробляються вручну нижче: кожен крок перевіряється заново.
        return safe_client(timeout=self.timeout, follow_redirects=False,
                           headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/pdf,text/plain;q=0.8'})

    def _pace(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.domain_delay - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_hit[host] = self._clock()

    def robots_allows(self, http, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                validate_research_url(origin + '/robots.txt')
                reply = http.get(origin + '/robots.txt')
                if reply.status_code in (401, 403):
                    parser.disallow_all = True
                elif reply.status_code < 400:
                    parser.parse(reply.text[:200_000].splitlines())
                else:
                    parser.allow_all = True
            except Exception:
                parser.allow_all = True  # robots.txt недоступний - діє загальне правило
            self._robots[origin] = parser
        return parser.can_fetch(USER_AGENT, url)

    def fetch(self, url: str) -> Document:
        url = validate_research_url(url)
        with self._client() as http:
            if not self.robots_allows(http, url):
                raise FetchBlocked(f'robots.txt забороняє автоматичне читання: {domain_of(url)}')
            current = url
            for _hop in range(MAX_REDIRECTS + 1):
                self._pace(domain_of(current))
                with http.stream('GET', current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('location') or ''
                        if not location:
                            raise FetchBlocked('Редирект без адреси')
                        current = validate_research_url(urljoin(current, location))
                        continue
                    if response.status_code >= 400:
                        raise FetchBlocked(f'Джерело відповіло {response.status_code}')
                    mime = (response.headers.get('content-type') or '').split(';')[0].strip().lower()
                    kind = ALLOWED_MIME.get(mime)
                    if kind is None:
                        raise FetchBlocked(f'Тип вмісту не дозволений: {mime or "невідомий"}')
                    declared = int(response.headers.get('content-length') or 0)
                    if declared > self.max_bytes:
                        raise FetchBlocked(f'Документ більший за {self.max_bytes // 1_000_000} МБ')
                    total, chunks = 0, []
                    for chunk in response.iter_bytes(65536):
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise FetchBlocked(f'Документ перевищив {self.max_bytes // 1_000_000} МБ під час завантаження')
                        chunks.append(chunk)
                    blob = b''.join(chunks)
                    encoding = response.encoding or 'utf-8'
                break
            else:
                raise FetchBlocked(f'Забагато редиректів (понад {MAX_REDIRECTS})')
        fetched_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        html, pages = '', []
        if kind == 'pdf':
            if not blob.startswith(b'%PDF'):
                raise FetchBlocked('Відповідь заявлена як PDF, але не є PDF')
            text, pages = pdf_to_text(blob, timeout=self.timeout)
            title = ''
        elif kind == 'html':
            html = blob.decode(encoding, errors='replace')
            text, title = html_to_text(html)
        else:
            text, title = blob.decode(encoding, errors='replace')[:TEXT_MAX_CHARS], ''
        normalized = ' '.join(text.split())
        return Document(url=url, final_url=current, content_type=kind, text=text, title=title, html=html,
                        content_hash=hashlib.sha256(normalized.encode('utf-8')).hexdigest(), fetched_at=fetched_at,
                        pages=pages, injection_flags=detect_injection(text))


# ---------------------------------------------------------------------------
# Ідентичність товару
# ---------------------------------------------------------------------------

TIER_WORDS = {'pro', 'plus', 'max', 'ultra', 'mini', 'lite', 'se', 'combo', 'air', 'neo', 'prime', 'elite', 'turbo', 'x', 's'}
REGION_WORDS = {'eu', 'us', 'uk', 'cn', 'jp', 'kr', 'in', 'global', 'intl', 'international', 'ww', 'na', 'apac', 'emea', 'ua'}
_MEMORY_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s?(gb|tb|гб|тб|mb|мб)\b', re.I)
_REVISION_RE = re.compile(r'\b(v\d+(?:\.\d+)?|rev\.?\s?\d+(?:\.\d+)?|gen\s?\d+|g\d|mk\s?\d+|mark\s?\d+)\b', re.I)


def model_regex(model: str):
    """Модель як ціле слово; регістр і безпечні роздільники (пробіл, -, _, /, .)
    нормалізуються, літери й цифри - ні: «A1» не знайдеться всередині «A10»."""
    parts = re.findall(r'[A-Za-z]+|\d+', model or '')
    if not parts:
        return None
    body = r'[\s\-_/.]?'.join(re.escape(x) for x in parts)
    return re.compile(r'(?<![A-Za-z0-9])' + body + r'(?![A-Za-z0-9])', re.I)


def _model_from_name(bare: str, brand: str) -> str:
    """Код моделі з назви: найдовший латинський токен із цифрою, крім памʼяті,
    ревізії й регіону («Сервер ASUS ESC8000A-E12» -> ESC8000A-E12, «Bambu Lab A1 Combo» -> A1)."""
    brand_words = {w.lower() for w in re.findall(r'[\w-]+', brand or '')}
    best = ''
    for token in re.findall(r'[A-Za-z0-9][A-Za-z0-9\-_/.]*[A-Za-z0-9]|[A-Za-z0-9]', bare or ''):
        low = token.lower()
        if low in brand_words or not re.search(r'\d', token) or not re.search(r'[A-Za-z]', token) and len(token) < 3:
            continue
        if _MEMORY_RE.fullmatch(token) or _REVISION_RE.fullmatch(token) or re.fullmatch(r'\d+d', low):
            continue  # 8GB, V2, 3D - не модель
        if len(token) > len(best):
            best = token
    return best


def _compact(text: str) -> str:
    """Регістр, пробіли й безпечні роздільники нормалізуються; літери й цифри - ні."""
    return re.sub(r'[\s\-_/.]+', '', (text or '').lower())


@dataclass
class ProductIdentity:
    brand: str
    model: str
    sku: str = ''
    name: str = ''
    memory: list = field(default_factory=list)
    revision: str = ''
    region: str = ''
    tiers: set = field(default_factory=set)

    @classmethod
    def from_product(cls, product: dict) -> 'ProductIdentity':
        from app.seo_geo import model_token
        name = str((product or {}).get('name') or '')
        brand = str((product or {}).get('brand') or '').strip()
        sku = str((product or {}).get('sku') or '').strip()
        inside = [x.strip() for x in re.findall(r'\(([^)]+)\)', name)
                  if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\-_./ ]{3,}', x.strip()) and (re.search(r'\d', x) or '-' in x)]
        bare = re.sub(r'\([^)]*\)', ' ', name)
        model = _model_from_name(bare, brand) or model_token({'name': bare}) or ''
        if not sku and inside:
            sku = max(inside, key=len)
        words = {w.lower() for w in re.findall(r'[A-Za-z]+', bare)}
        memory = sorted({_compact(a + b).replace('гб', 'gb').replace('тб', 'tb').replace('мб', 'mb') for a, b in _MEMORY_RE.findall(bare)})
        revision = (_REVISION_RE.search(bare) or [''])[0] if _REVISION_RE.search(bare) else ''
        region_hits = [w for w in re.findall(r'(?<![A-Za-z])([A-Z]{2,4})(?![A-Za-z])', bare + ' ' + sku) if w.lower() in REGION_WORDS]
        tail = re.split(re.escape(model), bare, maxsplit=1, flags=re.I)[1] if model and re.search(re.escape(model), bare, re.I) else ''
        tiers = {w.lower() for w in re.findall(r'[A-Za-z]+', tail)[:3] if w.lower() in TIER_WORDS}
        if not brand and bare.strip():
            brand = next((w for w in re.findall(r'[A-Za-z][\w-]+', bare)), '')
        return cls(brand=brand, model=model, sku=sku, name=name, memory=memory, revision=_compact(revision),
                   region=(region_hits[0].lower() if region_hits else ''), tiers=tiers)


@dataclass
class IdentityResult:
    status: str                 # exact | partial | conflict | rejected | unverified
    score: float
    matched: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _model_stem(model: str) -> tuple[str, str]:
    """('ESC8000A-E', '12') для 'ESC8000A-E12': основа і останнє числове поле."""
    match = re.match(r'^(.*?)(\d+)$', model or '')
    return (match.group(1), match.group(2)) if match else (model, '')


def match_identity(identity: ProductIdentity, text: str, title: str = '', url: str = '') -> IdentityResult:
    """Точна ідентичність до витягу фактів. Fuzzy-збіг лише сортує - дозволу не дає."""
    haystack = f'{title}\n{text}\n{url}'
    low = haystack.lower()
    compact = _compact(haystack)
    matched, conflicts, warnings = [], [], []
    if identity.brand and identity.brand.lower().split()[0] in low:
        matched.append('brand')
    pattern = model_regex(identity.model)
    model_ok = bool(pattern and pattern.search(haystack))
    sku_ok = bool(identity.sku) and _compact(identity.sku) in compact
    if model_ok:
        matched.append('model')
    if sku_ok:
        matched.append('sku')
    # Сусідні моделі: E12 проти E13, G3 проти G4, A1 проти A1 Mini.
    if identity.model:
        stem, number = _model_stem(identity.model)
        if number and len(stem) >= 2:
            pattern = re.escape(_compact(stem)) + r'(\d+)'
            siblings = {m for m in re.findall(pattern, compact) if m != number}
            if siblings:
                conflicts.append(f'на сторінці також моделі {", ".join(sorted(stem + s for s in siblings))[:120]}')
        for occurrence in re.finditer(re.escape(identity.model), haystack, re.I):
            after = re.findall(r'[A-Za-z]+', haystack[occurrence.end():occurrence.end() + 14])[:1]
            if after and after[0].lower() in TIER_WORDS and after[0].lower() not in identity.tiers:
                conflicts.append(f'варіант «{identity.model} {after[0]}» - інший товар')
                break
    # Памʼять/конфігурація: 8 GB проти 16 GB.
    if identity.memory:
        found = {_compact(a + b).replace('гб', 'gb').replace('тб', 'tb').replace('мб', 'mb') for a, b in _MEMORY_RE.findall(haystack)}
        if found and not set(identity.memory) & found:
            conflicts.append(f'конфігурація на сторінці {", ".join(sorted(found))[:60]}, у проєкті {", ".join(identity.memory)}')
    # Ревізія: V1 проти V2.
    if identity.revision:
        found = {_compact(x) for x in _REVISION_RE.findall(haystack)}
        if found and identity.revision not in found:
            conflicts.append(f'ревізія на сторінці {", ".join(sorted(found))[:40]}, у проєкті {identity.revision}')
    # Регіон: EU проти US - попередження або конфлікт.
    # Регіон шукається поза кодами моделі й SKU: «EU» у «PF003-D-EU» - частина коду, а не позначка версії.
    scrubbed = haystack
    for code in (identity.sku, identity.model):
        if code:
            scrubbed = re.sub(re.escape(code), ' ', scrubbed, flags=re.I)
    regions = {w.lower() for w in re.findall(r'(?<![A-Za-z\-])(EU|US|UK|CN|JP|KR|Global|Intl)(?![A-Za-z\-])', scrubbed)}
    if identity.region and regions and identity.region not in regions:
        conflicts.append(f'регіональна версія {", ".join(sorted(regions))}, у проєкті {identity.region.upper()}')
    elif regions and not identity.region and len(regions) == 1:
        warnings.append(f'сторінка регіональної версії {next(iter(regions)).upper()} - перевірте, що це той самий товар')
    score = 0.0
    score += 0.2 if 'brand' in matched else 0
    score += 0.5 if model_ok else 0
    score += 0.3 if sku_ok else 0
    if not model_ok and not sku_ok:
        status = 'rejected' if conflicts else 'unverified'
    elif conflicts and not sku_ok:
        status = 'conflict' if model_ok else 'rejected'
    elif conflicts:
        status = 'conflict'
    elif identity.sku and not sku_ok:
        status = 'partial'   # модель збіглась, SKU/part number на сторінці немає
    else:
        status = 'exact'
    if conflicts:
        score = max(0.0, score - 0.3)
    return IdentityResult(status=status, score=round(score, 2), matched=matched, conflicts=conflicts, warnings=warnings)
