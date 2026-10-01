#!/usr/bin/env python3
"""GSC / Keyword Planner / DataForSEO-вивантаження -> нормалізовані запити + заготовка SEO-брифу.

Окремий офлайн-процес (не воркер студії). Вихід - датований JSON, який можна
надіслати в ``POST /api/projects/{id}/seo-brief/import`` або вставити в майстер.

    python scripts/seo_research/gsc_to_brief.py gsc.csv --language uk --market UA --out build/seo/brief-uk.json
    python scripts/seo_research/gsc_to_brief.py dataforseo.json --format json --source dataforseo --sitemap https://artline.ua/sitemap.xml

advertools (MIT) підключається, якщо встановлений: нормалізація запитів
(``word_frequency``) і читання sitemap (``sitemap_to_df``). Без нього працює
спрощена вбудована нормалізація. Search volume береться лише з даних.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))

from app.seo_geo import brief_from_keywords, import_keyword_data  # noqa: E402

STOP = {'uk': {'для', 'та', 'і', 'в', 'у', 'з', 'на', 'купити', 'ціна', 'ціни'}, 'pl': {'dla', 'i', 'w', 'z', 'na', 'do', 'kup', 'cena'},
        'en': {'for', 'and', 'the', 'a', 'to', 'buy', 'price'}, 'ru': {'для', 'и', 'в', 'с', 'на', 'купить', 'цена'}}


def normalize(query: str, language: str) -> str:
    words = [w for w in re.findall(r'\w+', query.lower()) if w not in STOP.get(language, set())]
    return ' '.join(words)


def group_by_url(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row.get('page') or row.get('url') or '(no url)'].append(row['query'])
    return {url: queries[:50] for url, queries in groups.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path')
    parser.add_argument('--format', choices=('csv', 'json'), default='csv')
    parser.add_argument('--source', default='gsc', choices=('gsc', 'keyword_planner', 'dataforseo', 'import'))
    parser.add_argument('--language', default='uk')
    parser.add_argument('--market', default='UA')
    parser.add_argument('--sitemap', default='', help='URL sitemap для інвентаризації (лише з advertools)')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    text = Path(args.path).read_text(encoding='utf-8')
    rows = import_keyword_data(text, args.format, args.source)
    if not rows:
        print('У вивантаженні немає запитів', file=sys.stderr)
        return 1
    try:
        import advertools as adv  # type: ignore
        freq = adv.word_frequency([r['query'] for r in rows], [r.get('impressions') or r.get('search_volume') or 1 for r in rows])
        top_terms = freq.head(30).to_dict(orient='records')
        sitemap_urls = adv.sitemap_to_df(args.sitemap)['loc'].tolist()[:2000] if args.sitemap else []
        engine = 'advertools'
    except Exception:  # noqa: BLE001 - пакет необов'язковий
        counter = Counter()
        for row in rows:
            for word in normalize(row['query'], args.language).split():
                counter[word] += row.get('impressions') or row.get('search_volume') or 1
        top_terms = [{'word': w, 'weight': n} for w, n in counter.most_common(30)]
        sitemap_urls = []
        engine = 'builtin'
    brief = brief_from_keywords(rows, {}, args.language, args.source, [args.market])
    result = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': args.source, 'engine': engine, 'rows': len(rows),
        'brief': brief,
        'normalized': [{'query': r['query'], 'normalized': normalize(r['query'], args.language), **{k: r[k] for k in ('impressions', 'clicks', 'position', 'search_volume') if k in r}} for r in rows[:500]],
        'top_terms': top_terms,
        'by_url': group_by_url(rows),
        'content_inventory': sitemap_urls,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding='utf-8')
        print(f'written {args.out}: {len(rows)} rows, primary topic «{brief["primary_topic"]}» ({engine})')
    else:
        print(payload)
    return 0


if __name__ == '__main__':
    sys.exit(main())
