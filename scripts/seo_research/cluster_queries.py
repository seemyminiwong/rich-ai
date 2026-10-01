#!/usr/bin/env python3
"""Кластеризація запитів за спільними словами: intent grouping, content gap, secondary keywords.

Детермінована заміна «semantic clustering» зі сторонніх наборів скриптів:
без моделей, без мережі, відтворювано. Кластер = запити, що поділяють
``--min-shared`` нормалізованих слів із найсильнішим запитом кластера.

    python scripts/seo_research/cluster_queries.py gsc.csv --language uk --out build/seo/clusters.csv
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps' / 'api'))

from app.seo_geo import import_keyword_data  # noqa: E402

INTENT_HINTS = {
    'transactional': r'купити|купить|kup|buy|ціна|цена|cena|price|замовити|order',
    'informational': r'як|что|jak|how|чому|why|огляд|обзор|recenzja|review|порівнян|сравнен|porówn|vs',
    'navigational': r'artline|офіційн|official|сайт|site',
}


def words(query: str) -> set:
    return {w for w in re.findall(r'\w{3,}', query.lower())}


def intent(query: str) -> str:
    for name, pattern in INTENT_HINTS.items():
        if re.search(pattern, query, re.I):
            return name
    return 'commercial_investigation'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path')
    parser.add_argument('--format', choices=('csv', 'json'), default='csv')
    parser.add_argument('--source', default='gsc')
    parser.add_argument('--min-shared', type=int, default=2)
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    rows = import_keyword_data(Path(args.path).read_text(encoding='utf-8'), args.format, args.source)
    weight = lambda r: (r.get('clicks') or 0) * 5 + (r.get('impressions') or 0) / 100 + (r.get('search_volume') or 0) / 10  # noqa: E731
    rows.sort(key=weight, reverse=True)
    clusters = []
    for row in rows:
        w = words(row['query'])
        for cluster in clusters:
            if len(w & cluster['words']) >= args.min_shared:
                cluster['members'].append(row)
                break
        else:
            clusters.append({'head': row['query'], 'words': w, 'members': [row]})
    out_rows = []
    for index, cluster in enumerate(clusters, start=1):
        for member in cluster['members']:
            out_rows.append({'cluster': index, 'head': cluster['head'], 'query': member['query'], 'intent': intent(member['query']),
                             'clicks': member.get('clicks', ''), 'impressions': member.get('impressions', ''),
                             'position': member.get('position', ''), 'search_volume': member.get('search_volume', ''),
                             'role': 'primary' if member['query'] == cluster['head'] else 'secondary'})
    target = open(args.out, 'w', newline='', encoding='utf-8') if args.out else sys.stdout
    writer = csv.DictWriter(target, fieldnames=list(out_rows[0]) if out_rows else ['cluster'])
    writer.writeheader()
    writer.writerows(out_rows)
    if args.out:
        target.close()
        print(f'{len(clusters)} clusters, {len(out_rows)} queries -> {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
