#!/usr/bin/env python3
"""Post-publish аудит ПУБЛІЧНОГО URL: Lighthouse, Lychee, crawler, GEO.

Окремий необов'язковий workflow ПОЗА генерацією: жоден Celery-job його не
запускає, у API-образі сторонніх SEO-репозиторіїв немає. Запускається вручну
або з CI після публікації сторінки на домені з Publishing Profile.

    python scripts/audit_public_url.py https://artline.ua/uk/solution/bambu-lab \\
        --language uk --market UA \\
        --expected-canonical https://artline.ua/uk/solution/bambu-lab \\
        --expected-hreflang uk=https://artline.ua/uk/solution/bambu-lab \\
        --expected-hreflang pl=https://artline.ua/pl/solution/bambu-lab \\
        --out build/audit/bambu-lab

Вихід (``summary.json``):

    {"url": "...", "checked_at": "...", "lighthouse": {...}, "links": {...},
     "crawler": {...}, "geo": {...}, "findings": [...], "status": "pass|warning|fail"}

Сирі звіти інструментів лежать окремо в ``<out>/raw/``; ``summary.json`` -
нормалізований підсумок. Рівні: ``critical`` (fail), ``warning`` (warning),
``retryable`` (тимчасова недоступність - CDN, 429, таймаут: НЕ валить аудит),
``info``.

Обмеження безпеки: лише публічні http(s)-адреси (приватні й loopback-мережі
відхиляються ДО будь-якого запиту), жодних секретів у середовищі дочірніх
процесів, ліміти CPU/RAM/часу на кожен зовнішній інструмент, HTML-відповідь
обмежена 5 МБ.

Сторонні інструменти (усі необов'язкові; без них відповідний розділ = skipped):
* Lighthouse 13.x - ``npx --yes lighthouse@13.5.0`` (Apache-2.0), потрібен Chromium;
* Lychee 0.24.x - бінарник ``lychee`` (MIT/Apache-2.0);
* crawler - будь-яка команда через ``--crawler-cmd`` (наприклад open-seo-crawler
  у Docker, MIT); їй передається URL, stdout зберігається як raw-звіт.
GEO-перевірки (robots для AI-краулерів, llms.txt, server-rendered content,
structured data, ясність сутності) реалізовані тут без сторонніх пакетів. Їхня
оцінка - рекомендація, а не абсолютна істина: ``llms.txt`` не гарантує
індексації чи цитування.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import resource
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = 'ARTLINE-RichStudio-Audit/1.0 (+https://github.com/seemyminiwong/rich-ai)'
MAX_HTML = 5 * 1024 * 1024
AI_CRAWLERS = ('GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-Web', 'anthropic-ai', 'PerplexityBot',
               'Google-Extended', 'CCBot', 'Bytespider', 'Amazonbot', 'Applebot-Extended', 'meta-externalagent')
SEARCH_CRAWLERS = ('Googlebot', 'Bingbot')
LIGHTHOUSE_VERSION = os.environ.get('LIGHTHOUSE_VERSION', '13.5.0')
SAFE_ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'CHROME_PATH', 'NODE_OPTIONS', 'npm_config_cache')


# ---------------------------------------------------------------------------
# Утиліти
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def finding(code: str, severity: str, message: str, evidence: str = '', suggestion: str = '', source: str = 'audit') -> dict:
    return {'code': code, 'severity': severity, 'message': message, 'evidence': evidence[:300], 'suggestion': suggestion, 'source': source}


def is_public_url(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False, 'лише http(s) URL'
    host = parsed.hostname
    if host in ('localhost',) or host.endswith('.local') or host.endswith('.internal'):
        return False, 'локальний хост'
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f'DNS: {exc}'
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False, f'адреса {address} не публічна'
    return True, ''


def safe_env() -> dict:
    """Дочірні процеси не бачать секретів студії (ключі, паролі, токени)."""
    return {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}


def limited(cpu_seconds: int, memory_mb: int):
    def apply():
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        except (ValueError, OSError):
            pass
        if sys.platform != 'darwin':  # RLIMIT_AS ламає Chromium на macOS
            try:
                resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
            except (ValueError, OSError):
                pass
    return apply


def run_tool(cmd: list[str], timeout: int, cpu: int, memory_mb: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=safe_env(),
                              preexec_fn=limited(cpu, memory_mb))
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, '', f'timeout after {timeout}s'
    except FileNotFoundError as exc:
        return 127, '', str(exc)


def fetch(url: str, timeout: int = 20, accept: str = 'text/html') -> dict:
    """GET без редіректів-магії: фіксуємо ланцюжок, код, заголовки і тіло (до 5 МБ)."""
    chain = []

    class Tracker(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            chain.append({'from': req.full_url, 'to': newurl, 'code': code})
            ok, why = is_public_url(newurl)
            if not ok:
                raise urllib.error.URLError(f'redirect to non-public url: {why}')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(Tracker())
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Language': 'uk,pl;q=0.8,en;q=0.7'})
    started = time.time()
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_HTML + 1)
            return {'ok': True, 'status': response.status, 'final_url': response.geturl(), 'headers': dict(response.headers),
                    'body': body[:MAX_HTML].decode('utf-8', 'replace'), 'truncated': len(body) > MAX_HTML,
                    'redirects': chain, 'elapsed_ms': int((time.time() - started) * 1000)}
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'status': exc.code, 'final_url': exc.geturl(), 'headers': dict(exc.headers or {}), 'body': '',
                'redirects': chain, 'elapsed_ms': int((time.time() - started) * 1000), 'error': str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'status': 0, 'final_url': url, 'headers': {}, 'body': '', 'redirects': chain,
                'elapsed_ms': int((time.time() - started) * 1000), 'error': f'{type(exc).__name__}: {exc}'}


# ---------------------------------------------------------------------------
# Власні перевірки документа (без сторонніх пакетів)
# ---------------------------------------------------------------------------

def _meta(html: str, attr: str, name: str) -> str:
    match = re.search(rf'<meta[^>]+{attr}=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']', html, re.I) or \
        re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*{attr}=["\']{re.escape(name)}["\']', html, re.I)
    return match.group(1).strip() if match else ''


def document_checks(page: dict, args) -> tuple[list[dict], dict]:
    findings = []
    html = page.get('body') or ''
    summary = {'status': page.get('status'), 'final_url': page.get('final_url'), 'redirects': page.get('redirects'),
               'elapsed_ms': page.get('elapsed_ms')}
    if not page.get('ok'):
        status = page.get('status') or 0
        severity = 'retryable' if status in (429, 500, 502, 503, 504, 0) else 'critical'
        findings.append(finding('response', severity, f'Сторінка відповіла {status or "без відповіді"}', page.get('error', ''), 'Перевірити доступність URL', 'crawler'))
        return findings, summary
    if page.get('redirects'):
        findings.append(finding('redirect_chain', 'warning' if len(page['redirects']) == 1 else 'critical',
                                f'Редіректів: {len(page["redirects"])}', ' → '.join(r['to'] for r in page['redirects']),
                                'Публікувати кінцеву адресу без редіректів', 'crawler'))
    robots_header = (page.get('headers') or {}).get('X-Robots-Tag', '')
    robots_meta = _meta(html, 'name', 'robots').lower()
    if 'noindex' in robots_header.lower() or 'noindex' in robots_meta:
        findings.append(finding('noindex', 'critical', 'Опублікована сторінка має noindex', robots_header or robots_meta,
                                'Публікувати з index,follow; noindex лише для чернеток', 'crawler'))
    canonical = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)
    canonical = canonical.group(1).strip() if canonical else ''
    summary['canonical'] = canonical
    if not canonical:
        findings.append(finding('canonical_missing', 'critical', 'Немає canonical', '', 'Сервер студії додає canonical при експорті', 'crawler'))
    elif args.expected_canonical and canonical != args.expected_canonical:
        findings.append(finding('canonical_mismatch', 'critical', 'Canonical не збігається з очікуваним', canonical, f'Очікується {args.expected_canonical}', 'crawler'))
    hreflang = {m.group(1).lower(): m.group(2) for m in re.finditer(r'<link[^>]+hreflang=["\']([^"\']+)["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)}
    hreflang.update({m.group(2).lower(): m.group(1) for m in re.finditer(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*hreflang=["\']([^"\']+)["\']', html, re.I)})
    summary['hreflang'] = hreflang
    for code, url in (args.expected_hreflang or {}).items():
        if code not in hreflang:
            findings.append(finding('hreflang_missing', 'critical', f'Немає hreflang {code}', '', f'Додати {code} → {url}', 'crawler'))
        elif hreflang[code] != url:
            findings.append(finding('hreflang_mismatch', 'warning', f'hreflang {code} веде не туди', hreflang[code], f'Очікується {url}', 'crawler'))
    title = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title = re.sub(r'\s+', ' ', title.group(1)).strip() if title else ''
    description = _meta(html, 'name', 'description')
    summary['title'], summary['description'] = title, description
    if not title:
        findings.append(finding('title_missing', 'critical', 'Немає <title>', '', '', 'crawler'))
    if not description:
        findings.append(finding('description_missing', 'critical', 'Немає meta description', '', '', 'crawler'))
    lang = re.search(r'<html[^>]+lang=["\']([^"\']+)["\']', html, re.I)
    summary['html_lang'] = lang.group(1) if lang else ''
    if args.language and (not lang or lang.group(1).lower().split('-')[0] != args.language.lower()):
        findings.append(finding('html_lang', 'critical', f'html lang не відповідає {args.language}', summary['html_lang'], '', 'crawler'))
    h1s = re.findall(r'<h1\b', html, re.I)
    if len(h1s) != 1:
        findings.append(finding('h1_count', 'critical', f'h1 на сторінці: {len(h1s)}', '', 'Рівно один h1', 'crawler'))
    return findings, summary


def geo_checks(page: dict, base: str, args) -> tuple[list[dict], dict]:
    """GEO: доступ AI-краулерів, robots, server-rendered content, structured data,
    ясність сутності, llms.txt, AI-readable структура. Рекомендація, не вирок."""
    findings = []
    html = page.get('body') or ''
    origin = urllib.parse.urlunparse(urllib.parse.urlparse(base)._replace(path='', query='', fragment=''))
    path = urllib.parse.urlparse(base).path or '/'
    robots = fetch(origin + '/robots.txt', accept='text/plain')
    geo = {'robots_txt': robots.get('status'), 'ai_crawlers': {}, 'llms_txt': None, 'sitemap': None}
    rules = {}
    current = []
    if robots.get('ok'):
        for line in (robots.get('body') or '').splitlines():
            line = line.split('#', 1)[0].strip()
            if not line or ':' not in line:
                continue
            key, value = [x.strip() for x in line.split(':', 1)]
            if key.lower() == 'user-agent':
                current = [value.lower()]
                rules.setdefault(value.lower(), [])
            elif key.lower() in ('disallow', 'allow') and current:
                for agent in current:
                    rules.setdefault(agent, []).append((key.lower(), value))
            elif key.lower() == 'sitemap':
                geo['sitemap'] = value
    else:
        findings.append(finding('robots_txt_missing', 'warning', 'robots.txt недоступний', str(robots.get('status')), 'Додати robots.txt із sitemap', 'geo'))

    def blocked(agent: str) -> bool:
        agent_rules = rules.get(agent.lower()) or rules.get('*') or []
        allow_hit = disallow_hit = ''
        for kind, value in agent_rules:
            if value and path.startswith(value):
                if kind == 'allow' and len(value) > len(allow_hit):
                    allow_hit = value
                if kind == 'disallow' and len(value) > len(disallow_hit):
                    disallow_hit = value
        return len(disallow_hit) > len(allow_hit)

    for agent in AI_CRAWLERS + SEARCH_CRAWLERS:
        geo['ai_crawlers'][agent] = 'blocked' if blocked(agent) else 'allowed'
    blocked_ai = [a for a in AI_CRAWLERS if geo['ai_crawlers'][a] == 'blocked']
    if any(geo['ai_crawlers'][a] == 'blocked' for a in SEARCH_CRAWLERS):
        findings.append(finding('search_crawler_blocked', 'critical', 'robots.txt блокує пошуковий краулер для цього шляху', path, 'Дозволити Googlebot/Bingbot', 'geo'))
    if blocked_ai:
        findings.append(finding('ai_crawler_blocked', 'info', f'robots.txt блокує AI-краулери: {", ".join(blocked_ai)}', path,
                                'Це рішення власника сайту; для GEO-видимості їх зазвичай дозволяють', 'geo'))
    llms = fetch(origin + '/llms.txt', accept='text/plain')
    geo['llms_txt'] = llms.get('status')
    if not llms.get('ok'):
        findings.append(finding('llms_txt_missing', 'info', 'llms.txt відсутній', '', 'Необов\'язково: llms.txt не гарантує індексації чи цитування', 'geo'))
    if geo['sitemap']:
        sitemap = fetch(geo['sitemap'], accept='application/xml')
        geo['sitemap_status'] = sitemap.get('status')
        if sitemap.get('ok') and base not in (sitemap.get('body') or '') and (args.expected_canonical or base) not in (sitemap.get('body') or ''):
            findings.append(finding('sitemap_missing_url', 'warning', 'URL немає в sitemap', geo['sitemap'], 'Додати сторінку до sitemap', 'geo'))
    # Server-rendered content: без JS у нас лише сирий HTML - у ньому має бути текст.
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    words = len(re.findall(r'\w+', text))
    geo['words_without_js'] = words
    if words < 150:
        findings.append(finding('thin_ssr_content', 'critical', f'Без JavaScript видно лише {words} слів', '', 'Контент має бути в HTML, а не дорендерюватись скриптом', 'geo'))
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    geo['jsonld_blocks'] = len(scripts)
    types = []
    for block in scripts:
        try:
            data = json.loads(block)
            nodes = data.get('@graph', [data]) if isinstance(data, dict) else data
            types.extend(str(n.get('@type')) for n in nodes if isinstance(n, dict))
        except Exception:  # noqa: BLE001
            findings.append(finding('jsonld_invalid', 'critical', 'JSON-LD не парситься', block[:80], '', 'geo'))
    geo['jsonld_types'] = types
    if not scripts:
        findings.append(finding('structured_data_missing', 'warning', 'Немає JSON-LD', '', 'Organization + CollectionPage + ItemList', 'geo'))
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.S)
    h1_text = re.sub(r'<[^>]+>', ' ', h1.group(1)).strip() if h1 else ''
    title = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title_text = title.group(1).strip() if title else ''
    if h1_text and title_text and not any(w.lower() in title_text.lower() for w in re.findall(r'\w{4,}', h1_text)[:3]):
        findings.append(finding('entity_unclear', 'warning', 'h1 і title не поділяють жодної сутності', f'{h1_text[:60]} | {title_text[:60]}', 'Назвати сутність сторінки однаково в title і h1', 'geo'))
    headings = len(re.findall(r'<h[23]\b', html, re.I))
    if headings < 2:
        findings.append(finding('ai_readable_structure', 'warning', f'Заголовків h2/h3: {headings}', '', 'Структурувати текст h2/h3, answer-first абзаци', 'geo'))
    return findings, geo


# ---------------------------------------------------------------------------
# Сторонні інструменти
# ---------------------------------------------------------------------------

def run_lighthouse(url: str, raw_dir: Path, args) -> tuple[list[dict], dict]:
    if args.skip_lighthouse:
        return [], {'status': 'skipped'}
    npx = shutil.which('npx')
    lighthouse = shutil.which('lighthouse')
    if not (npx or lighthouse):
        return [finding('lighthouse_unavailable', 'info', 'Lighthouse не встановлено (npx/lighthouse)', '', 'npm i -g lighthouse@' + LIGHTHOUSE_VERSION, 'lighthouse')], {'status': 'unavailable'}
    out = raw_dir / 'lighthouse.json'
    cmd = ([lighthouse] if lighthouse else [npx, '--yes', f'lighthouse@{LIGHTHOUSE_VERSION}']) + [
        url, '--output=json', f'--output-path={out}', '--quiet', '--only-categories=performance,accessibility,best-practices,seo',
        '--chrome-flags=--headless=new --no-sandbox --disable-gpu', f'--max-wait-for-load={args.timeout * 1000}']
    code, _, err = run_tool(cmd, timeout=args.timeout * 4, cpu=args.timeout * 2, memory_mb=args.memory_mb)
    if code != 0 or not out.exists():
        return [finding('lighthouse_failed', 'retryable', f'Lighthouse завершився з кодом {code}', err[-200:], 'Повторити пізніше', 'lighthouse')], {'status': 'failed', 'exit': code}
    data = json.loads(out.read_text(encoding='utf-8'))
    cats = {k: round((v.get('score') or 0) * 100) for k, v in (data.get('categories') or {}).items()}
    audits = data.get('audits') or {}

    def metric(name):
        node = audits.get(name) or {}
        return node.get('numericValue')

    result = {'status': 'ok', 'version': data.get('lighthouseVersion'), 'categories': cats,
              'lcp_ms': metric('largest-contentful-paint'), 'cls': metric('cumulative-layout-shift'),
              'inp_ms': metric('interaction-to-next-paint'), 'tbt_ms': metric('total-blocking-time'), 'raw': str(out)}
    findings = []
    if cats.get('seo', 100) < 90:
        findings.append(finding('lighthouse_seo', 'warning', f'Lighthouse SEO: {cats["seo"]}', '', 'Переглянути звіт raw/lighthouse.json', 'lighthouse'))
    if cats.get('accessibility', 100) < 90:
        findings.append(finding('lighthouse_accessibility', 'warning', f'Lighthouse accessibility: {cats["accessibility"]}', '', '', 'lighthouse'))
    if (result['lcp_ms'] or 0) > 2500:
        findings.append(finding('cwv_lcp', 'warning', f'LCP {result["lcp_ms"]:.0f} мс (> 2500)', '', 'Легший hero, preload, стиснення', 'lighthouse'))
    if (result['cls'] or 0) > 0.1:
        findings.append(finding('cwv_cls', 'warning', f'CLS {result["cls"]:.3f} (> 0.1)', '', 'Задати розміри зображень', 'lighthouse'))
    if result['inp_ms'] and result['inp_ms'] > 200:
        findings.append(finding('cwv_inp', 'warning', f'INP {result["inp_ms"]:.0f} мс (> 200)', '', '', 'lighthouse'))
    return findings, result


def run_lychee(url: str, raw_dir: Path, args) -> tuple[list[dict], dict]:
    if args.skip_links:
        return [], {'status': 'skipped'}
    lychee = shutil.which('lychee')
    if not lychee:
        return [finding('lychee_unavailable', 'info', 'Lychee не встановлено', '', 'https://github.com/lycheeverse/lychee (v0.24.x)', 'links')], {'status': 'unavailable'}
    out = raw_dir / 'lychee.json'
    cmd = [lychee, '--no-progress', '--format', 'json', '--output', str(out), '--timeout', str(args.timeout), '--max-retries', '2',
           '--max-concurrency', '4', '--exclude-private', '--exclude-loopback', '--user-agent', USER_AGENT, '--accept', '200..=206,429', url]
    code, _, err = run_tool(cmd, timeout=args.timeout * 6, cpu=args.timeout * 2, memory_mb=args.memory_mb)
    if not out.exists():
        return [finding('lychee_failed', 'retryable', f'Lychee завершився з кодом {code}', err[-200:], '', 'links')], {'status': 'failed', 'exit': code}
    data = json.loads(out.read_text(encoding='utf-8') or '{}')
    findings = []
    broken, retryable = [], []
    for source, items in (data.get('error_map') or data.get('fail_map') or {}).items():
        for item in items:
            status = item.get('status') or {}
            text = json.dumps(status, ensure_ascii=False) if isinstance(status, dict) else str(status)
            target = item.get('url', '')
            if re.search(r'429|5\d\d|timeout|Timeout|network', text):
                retryable.append(target)
                findings.append(finding('link_retryable', 'retryable', 'Посилання тимчасово недоступне', f'{target} {text[:80]}', 'Повторити аудит пізніше (CDN/429/5xx)', 'links'))
            else:
                broken.append(target)
                findings.append(finding('link_broken', 'critical', 'Зламане посилання', f'{target} {text[:80]}', 'Виправити або прибрати посилання перед публікацією', 'links'))
    return findings, {'status': 'ok', 'total': data.get('total'), 'successful': data.get('successful'), 'broken': broken,
                      'retryable': retryable, 'raw': str(out)}


def run_crawler(url: str, raw_dir: Path, args) -> tuple[list[dict], dict]:
    """Будь-який зовнішній crawler (open-seo-crawler, seo-geo-audit) як команда.
    URL додається останнім аргументом; stdout - сирий звіт. Внутрішня мережа
    йому недоступна за побудовою: команда отримує лише публічний URL."""
    if not args.crawler_cmd:
        return [], {'status': 'skipped'}
    cmd = args.crawler_cmd.split() + [url]
    code, out, err = run_tool(cmd, timeout=args.timeout * 10, cpu=args.timeout * 5, memory_mb=args.memory_mb)
    raw = raw_dir / 'crawler.txt'
    raw.write_text(out + ('\n--- stderr ---\n' + err if err else ''), encoding='utf-8')
    if code != 0:
        return [finding('crawler_failed', 'retryable', f'Crawler завершився з кодом {code}', err[-200:], '', 'crawler')], {'status': 'failed', 'exit': code, 'raw': str(raw)}
    summary = {'status': 'ok', 'raw': str(raw)}
    try:
        parsed = json.loads(out)
        summary['keys'] = sorted(parsed)[:20] if isinstance(parsed, dict) else f'list[{len(parsed)}]'
    except Exception:  # noqa: BLE001
        summary['lines'] = out.count('\n')
    return [], summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_hreflang(values: list[str] | None) -> dict:
    out = {}
    for value in values or []:
        if '=' not in value:
            raise SystemExit(f'--expected-hreflang очікує code=url, отримано {value}')
        code, url = value.split('=', 1)
        out[code.strip().lower()] = url.strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('url')
    parser.add_argument('--language', default='')
    parser.add_argument('--market', default='')
    parser.add_argument('--expected-canonical', default='')
    parser.add_argument('--expected-hreflang', action='append', help='code=url; можна кілька разів')
    parser.add_argument('--out', default='build/audit')
    parser.add_argument('--timeout', type=int, default=int(os.environ.get('SEO_AUDIT_TIMEOUT', '30')), help='секунд на запит/інструмент')
    parser.add_argument('--memory-mb', type=int, default=int(os.environ.get('SEO_AUDIT_MEMORY_MB', '2048')))
    parser.add_argument('--skip-lighthouse', action='store_true')
    parser.add_argument('--skip-links', action='store_true')
    parser.add_argument('--crawler-cmd', default=os.environ.get('SEO_AUDIT_CRAWLER_CMD', ''), help='зовнішній crawler; URL додається останнім')
    args = parser.parse_args()
    args.expected_hreflang = parse_hreflang(args.expected_hreflang)

    ok, why = is_public_url(args.url)
    if not ok:
        print(f'Відмова: {why}. Аудит працює лише з публічними адресами.', file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    raw_dir = out_dir / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)

    page = fetch(args.url, timeout=args.timeout)
    (raw_dir / 'page.html').write_text(page.get('body') or '', encoding='utf-8')
    (raw_dir / 'response.json').write_text(json.dumps({k: v for k, v in page.items() if k != 'body'}, ensure_ascii=False, indent=2), encoding='utf-8')
    findings, crawler_summary = document_checks(page, args)
    geo_findings, geo = geo_checks(page, args.url, args) if page.get('ok') else ([], {'status': 'skipped'})
    findings += geo_findings
    lh_findings, lighthouse = run_lighthouse(args.url, raw_dir, args)
    findings += lh_findings
    link_findings, links = run_lychee(args.url, raw_dir, args)
    findings += link_findings
    crawl_findings, crawler = run_crawler(args.url, raw_dir, args)
    findings += crawl_findings
    crawler.update(crawler_summary)

    severities = {f['severity'] for f in findings}
    status = 'fail' if 'critical' in severities else 'warning' if ('warning' in severities or 'retryable' in severities) else 'pass'
    summary = {'url': args.url, 'language': args.language, 'market': args.market, 'checked_at': now_iso(),
               'expected_canonical': args.expected_canonical, 'expected_hreflang': args.expected_hreflang,
               'lighthouse': lighthouse, 'links': links, 'crawler': crawler, 'geo': geo,
               'findings': findings, 'status': status,
               'note': 'Оцінки - рекомендація, не гарантія позицій чи цитування. Сирі звіти: raw/.'}
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('url', 'checked_at', 'status')}, ensure_ascii=False))
    for row in findings:
        print(f'  [{row["severity"]}] {row["source"]}: {row["message"]}' + (f' - {row["evidence"][:80]}' if row['evidence'] else ''))
    print(f'summary: {out_dir / "summary.json"}')
    return 1 if status == 'fail' else 0


if __name__ == '__main__':
    sys.exit(main())
