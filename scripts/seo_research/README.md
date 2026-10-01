# Офлайн-дослідження семантики (окремо від Rich Studio)

Ці інструменти **не входять** в образ API і не викликаються з Celery-воркера:
вони потрібні періодично, а не на кожну генерацію. Результат їхньої роботи -
датований snapshot (CSV/JSON), який імпортується в SEO-бриф проєкту через
майстер («SEO / GEO → Імпортувати») або `POST /api/projects/{id}/seo-brief/import`.

## Що і навіщо

| Джерело / інструмент | Роль | Ліцензія | Версія |
|---|---|---|---|
| Google Search Console (експорт Performance → Queries) | query, country, impressions, clicks, position | дані власника сайту | експорт із датою |
| Google Keyword Planner (експорт) | search volume, CPC, competition | дані власника акаунта | експорт із датою |
| DataForSEO (Keywords Data API, JSON) | search volume, CPC, competition, SERP intent | за договором | відповідь із `last_updated_time` |
| [advertools](https://github.com/eliasdabbas/advertools) | обробка GSC-вивантажень, нормалізація запитів, аналіз sitemap, групування запитів по URL, перевірка robots, content inventory | MIT | `advertools==0.18.0` (pin у `requirements.txt`) |
| [search-solved-public-seo](https://github.com/searchsolved/search-solved-public-seo) | semantic clustering, content gap, intent grouping, аналіз GSC, пересічні сторінки, secondary keywords | **ліцензію не вказано (NOASSERTION)** - у репозиторій НЕ копіюється; окремі скрипти запускаються локально після перевірки їхніх заголовків, версія фіксується commit-hash у `SOURCES.lock` | pin commit вручну |
| [SerpBear](https://github.com/towfiqi/serpbear) | моніторинг позицій UA / PL / EN після публікації, порівняння до/після оновлення контенту | MIT | окремий сервіс, до студії не підключається |

Усе це - **джерела даних, а не генератори тексту**. Search volume не
вигадується: якщо його немає у вивантаженні, у брифі його теж немає.

## Використання

```bash
python3 -m venv .venv-seo && . .venv-seo/bin/activate
pip install -r scripts/seo_research/requirements.txt

# 1. GSC-експорт -> нормалізовані запити, згруповані за URL, + бриф-заготовка
python scripts/seo_research/gsc_to_brief.py gsc-queries.csv --language uk --market UA --out build/seo/brief-uk.json

# 2. Кластеризація запитів за спільними словами (без ML-моделей, відтворювано)
python scripts/seo_research/cluster_queries.py gsc-queries.csv --min-shared 2 --out build/seo/clusters.csv

# 3. Імпорт у проєкт (CSV або JSON, джерело й дата зберігаються у брифі)
curl -X POST "$STUDIO/api/projects/$PROJECT/seo-brief/import" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(python - <<'PY'
import json,sys; print(json.dumps({'text': open('gsc-queries.csv').read(), 'format': 'csv', 'source': 'gsc', 'language': 'uk'}))
PY
)"
```

`advertools` підключається необов'язково: якщо пакет встановлено, `gsc_to_brief.py`
використовує його для нормалізації запитів і аналізу sitemap; без нього працює
вбудована спрощена нормалізація.

## Що тут НЕ робиться

* live-запити до Keyword Planner / DataForSEO під час генерації сторінки;
* автоматична вставка запитів у текст - бриф задає тему і сутності, а текст
  пише модель за HUMAN COPY CONTRACT і перевіряють детерміновані аудити;
* копіювання чужих репозиторіїв у production-образ.
