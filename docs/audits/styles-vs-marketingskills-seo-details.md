## Структура, CRO, SEO, GEO, изображения: правила marketingskills против стилей

Источник правил: `marketingskills/skills/` — `cro` (SKILL.md, references/experiments.md), `ai-seo` (SKILL.md, references/content-patterns.md, content-types.md, agent-readiness.md, answer-accuracy.md, multilingual-and-commerce.md, platform-ranking-factors.md, format-volatility.md), `seo-audit` (SKILL.md, references/title-tags.md, rankings-push.md, ai-writing-detection.md), `schema` (SKILL.md, references/schema-examples.md), `image` (SKILL.md, references/ai-image-prompting.md).

Проект: `apps/api/app/prompts.py`, `pipeline.py` (`_prompt`, стр. 3842), `photo_slots.py` (`photo_budget_line`), `seo_geo.py`, `artline_standard.py`, `landing.py`, `main.py` (архив).

Уточнение по сборке промпта (`pipeline._prompt`): `HUMAN_COPY_CONTRACT` и `SOURCE_BOUNDARY_RULES` получает **каждый** стиль, включая Master. Для Master пропускается только `ARTLINE_STANDARD` (`_standard_for` возвращает `''` при `is_master_style`). Дополнительно модель получает: `seo_brief_block(brief)`, `company_facts_block`, `photo_budget_line`, `GALLERY_IMAGES` (только стилям, где это слово есть в промпте), `Product JSON` через `confirmed_only`, `external_facts_block`.

### Краткая сводка

57 правил проверено.

| Статус | Кол-во |
|---|---|
| Covered | 24 |
| Partially | 18 |
| Missing | 5 |
| Conflicts (все оправданы фиксированными решениями) | 3 |
| Not applicable | 7 |

Главное. Фактическая дисциплина (provenance чисел, запрет непроверенных коммерческих утверждений, строгие правила для изображений, alt, lazy, отсутствие document-SEO во фрагменте) сделана сильнее, чем требует rulebook. Слабые места:
1. В image-led стилях (Showcase/Podium/Master/Bento) нет самодостаточного определяющего предложения в Hero. Это одновременно CRO-проблема (ценностное предложение) и GEO-проблема (сущность). Проверка `entity_not_linked_early` проходит формально: её закрывает h2 «BRAND MODEL».
2. Нет проверки, что текст не повторяет исходное описание товара (риск дублирования контента).
3. В Base/Engineering нет FAQ и нет блоков, где заголовок — это вопрос покупателя.
4. Картинки без размеров (CLS) и с неописательными именами файлов.
5. В JSON-LD лендингов полные Product+Offer лежат внутри ItemList, нет dateModified, нет вводного абзаца.

### Таблица

Сокращения стилей: Base = DEFAULT_STYLE_PROMPT, Eng = ENGINEERING_STYLE_PROMPT, Show = Showcase и производные (Dark, Promo), Pod = Podium и производные, Bento = Bento/Bento Light, Master = MASTER_STYLE_PROMPT v2.0.

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 1 | Ценностное предложение понятно за 5 секунд: что это, для кого, зачем | cro/SKILL.md §1 | Partially | Base: «State what the product is and its strongest confirmed value in the first two text elements.»; Eng: subtitle «states the primary purpose». Show: «the h2 is BRAND + MODEL CODE only», subtitle = спеки через « · », абзац «of 1-2 sentences (at most 220 characters)» без заданного содержания. Master: «one paragraph of at most two sentences» — содержание тоже не задано. Bento: только h2 + «one 14px line ... with the category» | В Base/Eng покрыто. В Show/Pod/Master/Bento первый экран состоит из кода модели и списка спек; выгода и назначение не обязательны. См. пробел 1 |
| 2 | Выгода, а не голая характеристика, языком покупателя | cro §1, §2 | Covered | HUMAN_COPY_CONTRACT: «Explain why a confirmed characteristic matters without exaggerating it.»; Eng: «number and unit -> how it is achieved -> what it means in practice»; Master DEPTH: «the second says what it changes for the buyer» | |
| 3 | Конкретный заголовок с числами | cro §2 | Covered | Show: «a chip row of 3 white 8px-radius chips with the three strongest confirmed values»; Master: «HERO TILE ROW with the three strongest confirmed values»; Eng h2: «Exact brand/model – category with its defining confirmed characteristic» | |
| 4 | Один заметный основной CTA, повтор в точках решения | cro §3 | Conflicts (оправдано) | Base HTML CONTRACT: «Never use h1, script, style, JavaScript, forms, buttons, prices, purchase links...» | Фиксированное решение: CTA и цену держит карточка магазина. На лендингах покрыто (#57) |
| 5 | Визуальная иерархия, сканируемость, воздух | cro §4 | Covered | Base «CONTENT ISLAND SYSTEM»; «Limit paragraphs to 2-3 sentences»; аудит `long_paragraph`, `long_sentence` (audit_human_copy) | |
| 6 | Изображения поддерживают сообщение и не отвлекают | cro §4 | Covered | Show: «Photography works only next to copy»; «Never add a standalone photo-only section»; Master: «Never add a photo-only section.» | |
| 7 | Trust signals: отзывы, логотипы, рейтинги рядом с CTA | cro §5 | Conflicts (оправдано) | Base: «Do not add ... fake testimonial, review, comparison...» | Фиксированное решение: отзывы и рейтинги показывает магазин. Гарантия допускается только подтверждённая (Show Trust Split: «a confirmed warranty term»; `unsupported_commercial_claim`) |
| 8 | Работа с возражениями: «подойдёт ли мне», совместимость, ограничения | cro §6 | Covered | Base §5 BUYER CONFIDENCE; Eng §5: «State honest boundaries that follow directly from confirmed parameters»; Show Trust Split (pairs with, operating limit, capacity boundary); Promo: «An honest limit converts better than a promise the factory cannot keep.»; Master блок 05 «Сумісність і обмеження» | В Bento возражения закрывает только FAQ |
| 9 | Мобильная версия без трения | cro §7, seo-audit Mobile | Covered | ARTLINE_STANDARD: «Mobile: one column, no horizontal overflow, the same copy and images as desktop»; Master `[MOBILE_LAYOUT]`; аудит `audit_variant_consistency` | |
| 10 | Каждая секция начинается с прямого ответа | ai-seo SKILL.md Pillar 1 | Covered | HUMAN_COPY_CONTRACT: «Lead with the answer, not with scene-setting or a slogan.»; Base: «Prefer answer-first paragraphs...»; аудит `not_answer_first` (SCENE_SETTING + абзац-вопрос) | |
| 11 | Определение (сущность + категория) в первом абзаце | ai-seo Step 3 «Clear definition in first paragraph», content-types.md «Clear product description in first paragraph» | Partially | Base: «State the product category, primary purpose and strongest confirmed differentiator early in the page.»; аудит `entity_not_linked_early` | Проверка берёт `doc['texts'][:12]`, куда входят h2 и бейджи. Поэтому h2 «DEYE SUN-12K…» и бейдж «DEYE · Інвертор» закрывают её, хотя определяющего предложения в `<p>` нет. В Show/Master/Bento само требование отсутствует. Пробел 1 |
| 12 | Самодостаточные, цитируемые фрагменты | ai-seo Pillar 1 «Every key claim should work as a standalone statement»; content-patterns.md Self-Contained Answer Block | Partially | Base/Eng: «Use concrete nouns and complete factual sentences that remain understandable when quoted outside the page.» | В Show/Pod/Bento/Master этой строки нет. Абзацы, которые начинаются с «Він/Це/It», не ловятся. Пробел 4 |
| 13 | Ключевые ответы 40-60 слов, одна мысль на абзац | ai-seo Pillar 1 | Partially | Master DEPTH: «two paragraphs, together 50-90 words»; Show: «at most 320 characters»; HUMAN_COPY: «Keep one useful idea per sentence.» | Близко к норме. Детерминированной проверки длины ответа нет, но её и не нужно делать жёсткой |
| 14 | H2/H3 сформулированы так, как спрашивают люди, и описывают содержание | ai-seo Pillar 1; seo-audit Heading Structure «Headings describe content» | Partially | Base: «Every heading names a product capability, benefit or buyer outcome – never a page element.» Master: «h2 such as "КЛЮЧОВІ ПАРАМЕТРИ"», FAQ-компонент `>FAQ</h2>`, блок 08 «"НАДІЙНА ОСНОВА", "ЕКСПЛУАТАЦІЯ"»; аудит `weak_heading` ловит только обрывки | Шаблонные заголовки Master ничего не говорят о товаре. Пробел 8 |
| 15 | FAQ: естественные вопросы, прямой ответ в первом предложении | ai-seo content-patterns.md FAQ Block | Partially | Show/Pod/Bento/Master: 4-6 вопросов, «Questions are the real pre-purchase questions THIS Product JSON can answer»; аудит `faq_question_unnatural`, `faq_answer_thin`. Base/Eng: FAQ нет, а запрет «tabs, accordions» и «fake FAQs» делает его невозможным | В image-led стилях покрыто, в Base/Eng отсутствует. Пробел 3 |
| 16 | Статистика с источником и условиями | ai-seo Pillar 2 (+37-40%) | Partially | Аудит `number_without_provenance` (critical); Master: «Retain conditions: rated vs peak power, battery life with/without lighting... test conditions»; Eng: «tolerances, standards» | Внешние ссылки во фрагменте не нужны (ссылок нет по решению). В Base/Show/Bento требования сохранять условия измерения нет |
| 17 | Цитаты экспертов, автор, биография | ai-seo Pillar 2, E-E-A-T | Not applicable | — | Автор и E-E-A-T относятся к магазину. Выдумывать цитаты запрещает SOURCE OF TRUTH |
| 18 | Свежесть: «Last updated», актуальные даты | ai-seo Pillar 2 Freshness | Not applicable | — | Дату страницы ведёт магазин. Для лендингов см. #53 |
| 19 | Сравнительные таблицы X vs Y | ai-seo Pillar 1; content-types.md Comparison | Conflicts (оправдано) | Base: «Do not create ... unsupported comparisons.»; аудит `unsupported_comparison` | Фиксированное решение: сравнений с конкурентами нет. Таблицу характеристик показывает магазин |
| 20 | Без keyword stuffing | ai-seo Pillar 2 (-10%), seo-audit | Covered | HUMAN_COPY: «Do not force SEO phrases into grammatically unnatural forms.»; аудит `exact_match_repetition`, `keyword_repetition`, `unnatural_keyword_form` | |
| 21 | Не писать отдельный контент «для AI», не масштабировать тонкие шаблонные варианты | ai-seo What NOT to Do 1-3 | Partially | HUMAN_COPY: «Never write for an algorithm...»; Base: «Every sentence must be specific to THIS product...» | Запрет есть только в промпте. Студия генерирует пачками (bulk_import), но проверки на одинаковые предложения в разных товарах одной категории нет. Частично закрывает пробел 2 |
| 22 | Контент без JS, семантический HTML | ai-seo Agentic Experiences, agent-readiness.md Access | Covered | Аудит `js_required` (script / on*), разрешён только нативный details/summary | |
| 23 | Доказательства текстом, а не на картинке | ai-seo Agentic «Proof as text» | Covered | Negative prompt: «The image must contain ZERO added text»; аудит `image_only_content`; Master: «Reject frames that show ... a large infographic slide» | В Show/Bento нет запрета на кадры-инфографики из GALLERY_IMAGES (он есть только в Master) |
| 24 | Точность ответов: нет ложных и устаревших фактов, верный вариант товара | ai-seo answer-accuracy.md | Covered | Base SOURCE OF TRUTH; Master: «Match the exact model, color, capacity and regional variant»; аудит `number_without_provenance`, `unsupported_commercial_claim`, `variant_values_mismatch` | |
| 25 | Мультиязычность: родной язык, локальные единицы, проверки по каждому языку | ai-seo multilingual-and-commerce.md | Partially | `_prompt`: «Units, unit abbreviations and period words are ALWAYS written in the target language and script»; `language_rule` | Бриф существует только на одном языке. В `audit_rich_fragment` стоит `same_language = lang == norm_lang(brief.language)`, поэтому `category_missing_early` и `primary_topic_late` для ru/pl/en не запускаются. Пробел 5 |
| 26 | Покрыть подвопросы fan-out | ai-seo Query Fan-Out | Partially | Base: «Answer the buyer's likely questions inside the existing sections: what it is, the main benefit...»; `seo_brief_block` передаёт `buyer_questions` | В автоматическом брифе всего 3 шаблонных вопроса (`BUYER_QUESTION_TEMPLATES`). Вопросы по совместимости и ограничениям появляются только из FAQ стиля |
| 27 | llms.txt, robots для AI-ботов, Markdown, agent-readiness | ai-seo Machine-Readable Files, agent-readiness.md | Not applicable | Docstring `audit_geo_copy`: «llms.txt, robots і доступ AI-краулерів тут НЕ перевіряються - це властивості опублікованого домену» | Это свойства домена artline.ua |
| 28 | Иерархия заголовков (один H1 на странице, H2 → H3) | seo-audit Heading Structure | Covered | `_prompt`: «SEO heading rule: never use <h1>.»; аудит `h1_in_fragment` (critical), `heading_order`, `empty_heading`, `no_h2` | H1 принадлежит карточке (фиксированное решение) |
| 29 | Основной запрос в первых 100 словах | seo-audit Content Optimization | Partially | Аудит `primary_topic_late` (первые 150 слов), `category_missing_early` | Работает только на языке брифа (см. #25) |
| 30 | Title, meta, canonical, hreflang, schema | seo-audit On-Page; schema | Not applicable | Аудит `document_seo_in_fragment` (critical): «Метадані, canonical, hreflang і schema належать картці товару» | Отсутствие этих элементов во фрагменте проверяется детерминированно |
| 31 | Глубина контента, без thin content | seo-audit Content Depth / Thin Content | Partially | SOURCE_BOUNDARY_RULES: «Length guide: a simple product needs roughly 250-450 words...»; аудит `image_only_content` (<80 слов) | Bento («The reader scans, not reads.») по замыслу почти без текста, связного абзаца нет. Нижний порог 80 слов мягкий |
| 32 | Нет дублей внутри страницы | seo-audit Thin Content | Covered | Аудит `duplicate_paragraph`, `block_without_new_meaning`, `duplicate_sentence`, `fact_repeated_across_blocks`; Show «NUMBER DISTRIBUTION»; Master «Each value is shown as a tile ONCE per page» | |
| 33 | Нет дублирования описания производителя или магазина (e-commerce duplicate descriptions) | seo-audit Common Issues E-commerce «Duplicate product descriptions» | Missing | В `_prompt` есть только «Never copy source-page sentences in another language» (про перевод) | Нет ни правила, ни проверки, что фрагмент не пересказывает `product.description` дословно на том же языке. Текст уже есть на той же карточке и у других ритейлеров. Пробел 2 |
| 34 | Desktop и mobile на одном URL не дают дубль или скрытый текст | seo-audit Duplicate / Hidden; ai-seo | Partially | Base: «Both outputs are published on the same product page» | Копии идентичны намеренно. Если магазин выводит обе в DOM и прячет одну через CSS по устройству, поисковик видит на одном URL двойной текст и скрытый блок. Нужно проверить, как поля desktop/mobile рендерит artline.ua. Студия на это не влияет |
| 35 | Без скрытого текста | seo-audit; ai-seo | Covered | Аудит `hidden_text` (critical, `_hidden_style`) | |
| 36 | Alt у всех изображений, описательный, без набивки | seo-audit Image Optimization; image Optimization Checklist | Covered | ARTLINE_STANDARD: «every img has a concise alt in the target language»; аудит `alt_missing`, `alt_generic`, `alt_keyword_list`, `alt_language`, `alt_duplicate` | Мелочь: ремонт Hero в `pipeline.py` (стр. ~4073) вставляет `alt=""` и сам вызывает `alt_missing` |
| 37 | Alt называет товар (сущность) и ракурс | seo-audit «Alt text describes image»; image «descriptive, keyword-relevant» | Partially | Base/Eng: «names the product and what the image shows»; Show/Bento/Master: только «concise descriptive alt» | Аудит не проверяет, есть ли в alt бренд, модель или категория. Пробел 7 |
| 38 | Описательные имена файлов | seo-audit Image Optimization | Missing | Генерация: `f'{label}.webp'` (hero.webp, feature.webp); архив `main.py`: `f"{_archive_name(asset.label, 'image')}-{asset.id[:8]}{suffix}"` | В имени нет ни товара, ни модели |
| 39 | Сжатие, WebP/AVIF, размер под контейнер | image Format Guide / Checklist | Partially | `pipeline.py`: `frame.save(path, 'WEBP', quality=90)` | WebP есть, но quality 90 выше рекомендованных 75-85. Ресайза под ширину слота и srcset нет. Кадры галереи используются как есть |
| 40 | Lazy loading ниже первого экрана | seo-audit; image Checklist | Covered | ARTLINE_STANDARD: «loading="lazy" on every img outside the Hero»; `apply_artline_standard` шаг 7; аудит `missing_lazy`, `hero_lazy` | Bento: «loading="lazy" on every image», а аудит даёт info `hero_lazy` на первую картинку. Фрагмент стоит ниже buy-box, так что lazy везде нормально. Стоит убрать это ложное info |
| 41 | Явные размеры (width/height или aspect-ratio) против CLS | image Checklist «Set explicit dimensions»; seo-audit CWV CLS | Missing | `_ALLOWED_ATTRS` разрешает `width`/`height`, но ни промпт, ни постобработка их не ставят | В Show/Bento у слотов фиксированная CSS-высота (CLS нет). В Master split «img uses display:block;width:100%;height:auto» и Base Feature «height:auto» при lazy дают сдвиг вёрстки. Пробел 6 |
| 42 | Внутренняя перелинковка | seo-audit Internal Linking | Not applicable | Ссылок во фрагменте нет (фиксированное решение) | На лендингах есть (#57) |
| 43 | Признаки AI-текста (em dash, шаблонные фразы) | seo-audit/references/ai-writing-detection.md | Covered | ARTLINE_STANDARD: «Never the em dash character and never &mdash;.»; `_STANDARD_SWAPS` (' — ' → ' – '); аудит `generic_phrase`, `calque`, `superlatives` | |
| 44 | Реальный товар, без галлюцинаций продукта и UI | image Common Mistakes 1; ai-image-prompting.md | Covered | «VIEWPOINT LOCK – THE CAMERA IS FIXED», «SUBJECT PRESERVATION», negative: «no fabricated screen or display UI» | Сильнее, чем требует rulebook |
| 45 | Без текста внутри сгенерированных картинок | image «Text-heavy images» | Covered | «The image must contain ZERO added text... in any language» | |
| 46 | Структура промпта: subject, setting, style, light, composition, aspect | image Prompting Basics | Covered | Секции INTENDED USE / SCENE / COMPOSITION; Promo «SHOOTING BRIEF», «MACRO BRIEF» | |
| 47 | Студийные рендеры не обрезаны, кадры уникальны, бюджет фото | image; cro §4 | Covered | Show FITTING RULE: «Such frames must NEVER be cropped»; `photo_budget_line`: «Never leave an empty frame, a white or grey placeholder box, an icon stand-in or a repeated photo.» | |
| 48 | Schema во фрагменте (Product, FAQPage) | schema; ai-seo Schema for AI | Not applicable | Base: «Do not create hidden SEO text, meta tags, schema markup...» | Фиксированное решение: Product JSON-LD принадлежит магазину |
| 49 | Лендинг: JSON-LD только из видимых и проверенных данных | schema Core Principles «Accuracy First» | Covered | `build_landing_jsonld`: «JSON-LD лише з перевірених даних»; аудит `faq_schema_mismatch`, `jsonld_product_invisible`, `jsonld_forbidden_field`, `jsonld_unknown_url` | |
| 50 | Лендинг: Product с нужными полями и по guidelines Google | schema Quick Reference Product (Recommended: sku, brand); «Follow Google's Guidelines» | Partially | `_FORBIDDEN_PRODUCT_KEYS` включает `'brand'`; ItemList содержит полные `Product` + `Offer` | По guidelines Google Product-разметка ставится на страницу конкретного товара, а не на список или категорию (перед правкой сверить с актуальной документацией). Подтверждённый бренд из проб можно разрешить. Пробел 9 |
| 51 | Лендинг: валидный BreadcrumbList | schema BreadcrumbList | Partially | Строится, только если переданы `breadcrumbs`: позиции с 1, name + item | `audit_landing_document` его не валидирует: абсолютные URL не проверяются, последний элемент не сверяется с canonical |
| 52 | Лендинг: FAQPage | schema «Google stopped showing FAQ rich results on May 7, 2026» | Not applicable | Строится только из `visible_faq`, а LANDING_PROMPT FAQ не создаёт | Как семантика корректно. Rich result получить нельзя, менять ничего не нужно |
| 53 | Лендинг: сигналы свежести (dateModified) | ai-seo Freshness; schema Article/Page | Missing | `CollectionPage` содержит только name/inLanguage/url/description/publisher | Период акции виден в чипе, но в JSON-LD дат нет |
| 54 | Лендинг: OG-изображение 1200×630 с размерами | image OG & Social Preview | Partially | `build_landing_metadata(..., image='')`, а `finalize_landing_seo` не передаёт `image`, поэтому `og:image` берётся с первого товара | Hero кампании в OG не попадает. Нет `og:image:width/height` |
| 55 | Лендинг: один h1, title около 60, description 150-160, canonical, hreflang, robots | seo-audit On-Page, International SEO; title-tags.md | Covered | `finalize_landing_seo` (title `_trim(..., 65)`, description `_trim(..., 158)`, robots по статусу публикации, self-hreflang); аудит `h1_count`, `title_long`, `description_length`, `canonical_*`, `robots_*`, `hreflang_*` | |
| 56 | Лендинг: не тонкий листинг, вводный абзац с ответом, иерархия заголовков | seo-audit Thin Content; ai-seo Definition block; rankings-push «Answer the query in the first two sentences» | Missing | Hero: «period chip (if given), huge campaign title (h1, white, 950), subtitle»; в детерминированном шаблоне имя товара `<p>`, а анкор у всех «Купити» | Связного текста нет, у названий товаров нет h3, анкоры не описательные. Пробел 10 |
| 57 | Лендинг: CTA на каждом товаре, ссылки только на реальные URL | cro Landing Page CRO | Covered | LANDING_PROMPT: «Every product card links its image, name and buy CTA to the product url.»; аудит `unknown_link`, `link_scheme` | |

### Главные пробелы и предложения

Отсортировано по пользе для SEO/GEO/CRO. Ни одно предложение не нарушает фиксированные решения: без CTA, цен, отзывов, сравнений, ссылок и JSON-LD во фрагменте.

**1. Определяющее предложение в Hero для image-led стилей (CRO + GEO).**
Сейчас в Show/Pod/Master/Bento первый экран состоит из кода модели и спек, а GEO-проверка формально закрывается заголовком.
- Промпт. Новый пункт в `ARTLINE_STANDARD` (prompts.py ~стр. 23, действует на все стили кроме Master) и тот же текст в Master → `FACTS AND COPY`:
  > `- Hero definition: the first sentence of the Hero paragraph is a self-contained definition – the product category with the brand, its primary purpose and the strongest confirmed outcome for the buyer (for example "Трифазний гібридний інвертор DEYE для резервного живлення будинку з батареєю 48 В."). Quoted alone, it answers "what is this and what is it for". The model code stays in the h2 and is not repeated in this sentence.`
- Bento (MODEL TILE): `- Under the category line add one sentence of 12-25 words in #D8DDE2 that defines the product: category, primary purpose and its strongest confirmed value. This sentence is the only tile text longer than a label.`
- Совместимость: Show ограничивает «brand and model ... three times, never more». Предложение повторяет бренд и категорию, но не код модели, поэтому правило не нарушается.
- Проверка в `seo_geo.audit_geo_copy`, новый код `definition_sentence_missing` (warning). Берём первый `<p>` блока 0 (`t['tag'] == 'p' and t['block'] == 0`). Если в его первом предложении нет бренда или модели либо (на языке брифа) нет основы категории, это находка. Нынешний `entity_not_linked_early` оставить, но не засчитывать h2 и span.

**2. Запрет пересказа исходного описания (дублирование контента).**
- Промпт, в `SOURCE_BOUNDARY_RULES` (prompts.py ~стр. 54):
  > `- The description in PRODUCT FACTS is evidence, not copy: take facts from it, never reuse its sentences or their word order. The shop page already shows that text, and repeating it adds nothing for the buyer or for search.`
- Проверка в `audit_rich_fragment`, код `source_text_copied` (warning). Строим 8-словные шинглы из `product['description']` и `features` (нормализация как в `_norm_sentence`) и сравниваем с видимым текстом. Находка, если хотя бы одно предложение из 12+ слов совпало дословно или общих шинглов больше 15 %. Проверять только на языке источника. Та же функция на корпусе последних N проектов той же категории закроет #21 (шаблонные предложения при массовой генерации).

**3. Вопросно-ответный формат в Base/Engineering без аккордеона.**
FAQ в этих стилях невозможен («tabs, accordions», «fake FAQs»), при этом секция 5 уже про возражения.
- Промпт, в `DEFAULT_STYLE_PROMPT` §5 BUYER CONFIDENCE и `ENGINEERING_STYLE_PROMPT` §5 TECHNICAL CONSIDERATIONS:
  > `- Each of the four supporting islands answers one real pre-purchase question this Product JSON can answer: its h3 is the question as a buyer would type it, ending with a question mark; its paragraph answers in the first sentence with the confirmed value or condition, then adds one supporting sentence. Never ask a question the data cannot answer.`
- Конфликта с аудитом нет: `not_answer_first` смотрит только на `<p>`, а вопрос стоит в h3.

**4. Абзацы и ответы FAQ начинаются с названного предмета, а не с местоимения.**
- Промпт, в `HUMAN_COPY_CONTRACT` (идёт во все стили, включая Master):
  > `- Open every paragraph and every FAQ answer with its subject named – the product category, the feature or the parameter – never with a bare pronoun ("it", "this", "він", "це", "он", "to"), so the first sentence stays true when quoted alone.`
- Проверка в `audit_geo_copy`, код `pronoun_opening` (info). Первое слово абзаца или ответа входит в список по языку: uk `він|вона|воно|вони|це|цей|ця|ці|його|її`, ru `он|она|оно|они|это|этот|эта|эти`, pl `on|ona|ono|to|ten|ta|te`, en `it|this|these|they|its`.

**5. SEO-проверки для всех языков, а не только языка брифа.**
- В `seo_geo.audit_rich_fragment` проверки `category_missing_early`, `primary_topic_late` и `exact_match_repetition` выключены, если `lang != brief.language`.
- Предложение: на шаге перевода (`pipeline`, translation memory) один раз перевести `brief.primary_topic` и `product.category` на каждый целевой язык и передавать в `run_rich_audits` бриф для каждого языка (`brief_by_language[lang]`). После этого убрать условие `same_language`. Тогда ru/pl/en страницы получат те же проверки, что и uk.

**6. Размеры изображений против CLS.**
- Детерминированно в `artline_standard.apply_artline_standard`, рядом с шагом 7 (lazy): у каждого `img` без `position:absolute`, чей src есть среди ассетов проекта (PIL уже читает `image.size` в pipeline), проставить атрибуты `width`/`height` с внутренними размерами. CSS `width:100%;height:auto` остаётся, браузер берёт пропорцию из атрибутов. Перед этим проверить, что редактор artline.ua не вырезает эти атрибуты.
- Проверка в `audit_rich_fragment`, код `img_without_dimensions` (info): у `img` нет width/height и нет фиксированной CSS-высоты или `aspect-ratio`.

**7. Alt называет товар и ракурс.**
- Промпт. Заменить пункт Images в `ARTLINE_STANDARD` и строку в Master → ASSETS:
  > `- Images: every img has a concise alt in the target language that names the product (brand and category, or model) and what this frame shows – the view, the part or the use context (for example "Інвертор DEYE SUN-12K, панель підключень знизу"); never a bare model code, never a keyword list; loading="lazy" on every img outside the Hero.`
- Проверка в `audit_rich_fragment`, код `alt_without_entity` (info): в alt нет бренда, `model_token` или основы категории.
- Ремонт Hero в `pipeline.py` (~стр. 4073): `alt=""` заменить на экранированное имя товара.
- Попутно: имя файла в архиве (`main.py` ~2307) собирать как `{brand}-{model}-{label}-{id8}.webp` через `_archive_name` (закрывает #38).

**8. Описательные заголовки в Master.**
- Промпт, в `MASTER_STYLE_PROMPT`:
  - блок 02: `h2 such as "КЛЮЧОВІ ПАРАМЕТРИ"` → `an h2 that names the product class, for example "КЛЮЧОВІ ПАРАМЕТРИ ГІБРИДНОГО ІНВЕРТОРА"`;
  - блок 08: `the h2 names what the values cover for this product (for example "ЗАХИСТ І УМОВИ РОБОТИ ІНВЕРТОРА"), never a bare label such as "ЕКСПЛУАТАЦІЯ"`;
  - FAQ IMPLEMENTATION: `>FAQ</h2>` → `>NATURAL TARGET-LANGUAGE HEADING FOR QUESTIONS ABOUT THIS PRODUCT CATEGORY</h2>` (по образцу Showcase).
- Проверка: расширить `weak_heading` списком голых меток по языкам (`ключові параметри|характеристики|експлуатація|faq|переваги`) для h2, у которых нет других значимых слов. Severity info.
- Перед правкой убедиться, что механика FAQ в `pipeline.py` не ищет текст `>FAQ<`. Grep показал, что FAQ находится по `<details>` и маркерам `ARTLINE FAQ BLOCK`.

**9. Лендинги: корректная разметка списка и свежесть.**
В `seo_geo.build_landing_jsonld`:
- ItemList перевести на summary-шаблон `{'@type': 'ListItem', 'position': i, 'url': url, 'name': name}`. Product+Offer оставить на карточках товара.
- Разрешить `brand`, если он пришёл из проб (убрать из `_FORBIDDEN_PRODUCT_KEYS` только для подтверждённого значения), или убрать Product совсем.
- В `CollectionPage` добавить `datePublished`/`dateModified` из времени публикации и последнего изменения кампании.

В `finalize_landing_seo`:
- передавать `image=campaign.get('hero_url')` (абсолютный URL);
- добавлять `og:image:width`/`og:image:height`.

В `audit_landing_document`:
- код `breadcrumb_invalid`: позиции идут подряд с 1, все `item` абсолютные, последний элемент совпадает с canonical;
- код `jsonld_product_in_list` (warning), пока используется полный Product в ItemList.

**10. Лендинги: вводный абзац, h3 и описательные анкоры.**
- В `LANDING_PROMPT`, пункт 1 PROMO HERO, добавить:
  > `After the subtitle one lead paragraph of 1-2 sentences (25-50 words) that states what the campaign covers – categories, number of products and the period – using only CAMPAIGN, CATEGORIES and PRODUCTS JSON. Product names in cards are h3 and are links to the product url; the buy CTA keeps «{BUY}».`
- В `deterministic_landing` то же самое собрать без модели: строка из `campaign_title`, `len(products)`, имён категорий и `period`; `<p>` с именем товара заменить на `<h3><a href=url>`.
- Проверка в `audit_landing_document`:
  - `landing_no_lead` (warning): в блоке hero нет `<p>` из 15+ слов;
  - `landing_heading_skip` (warning): h3 до первого h2 или h1 → h3 без h2;
  - `generic_anchor_only` (info): у товара нет ссылки с его именем, только «Купити».

### Сознательные расхождения

Это фиксированные решения владельца, дефектами не считаются:
- **CTA, цены, формы, кнопки, срочность** (cro §3, §7; experiments.md Urgency) во фрагменте не нужны: коммерцию ведёт карточка artline.ua. Аудит `artificial_urgency` это поддерживает.
- **Отзывы, рейтинги, логотипы клиентов, кейсы** (cro §5) — их показывает магазин, а вымышленные запрещены.
- **Сравнения с конкурентами и таблицы X vs Y** (ai-seo, content-types.md). Кроме того, `format-volatility.md` фиксирует падение цитируемости сравнительных страниц в ChatGPT на 32 %, так что потеря невелика.
- **Нет h1, meta, canonical, hreflang и JSON-LD во фрагменте** (seo-audit, schema). Это document-level разметка магазина. Отсутствие защищено проверкой `document_seo_in_fragment`.
- **Нет ссылок во фрагменте**, поэтому нет и «cite sources with links» (ai-seo Pillar 2) и внутренней перелинковки. Провенанс заменён проверкой `number_without_provenance` по Product JSON.
- **FAQ только через нативный details/summary, без FAQPage-схемы**. Google отключил FAQ rich results 7 мая 2026 (schema SKILL.md), так что схема здесь ничего бы не дала.
- **Нет автора, даты обновления, экспертных цитат** (ai-seo E-E-A-T, Freshness). Это уровень магазина, а выдумывать цитаты запрещено.
- **llms.txt, robots, Markdown-негоциация, WebMCP** (agent-readiness.md) — свойства домена artline.ua, не фрагмента.
- **Lazy на всех картинках в Bento** формально расходится с правилом «hero eager». Фрагмент стоит ниже buy-box и не является LCP, поэтому решение верное. Правильнее убрать info `hero_lazy` для стилей без Hero.
- **Одинаковый текст desktop и mobile** — осознанное решение, чтобы страница не противоречила сама себе. Остаётся одна проверка на стороне магазина (#34).
- Визуальные токены (радиусы, веса, Montserrat, em dash) вне рамок аудита. Мимоходом: guardrail в `_prompt` всё ещё говорит «8px or 999px for badges», а LANDING_PROMPT требует «Radii: sections 28-32px ... h1/h2 950». Это противоречит `ARTLINE_STANDARD`, но к SEO/GEO отношения не имеет.

### Лендинги студии

Функции `build_landing_metadata`, `build_landing_jsonld`, `finalize_landing_seo` и `audit_landing_document` в целом соответствуют seo-audit и schema.

**Сильные стороны.**
- Head целиком строит сервер, модель его не пишет.
- Чернетка всегда `noindex,nofollow`; canonical ставится только на опубликованный URL; preview-токены в canonical ловятся (`canonical_preview_token`).
- hreflang с self-reference и x-default, проверяется взаимность против `expected_alternates`.
- Title обрезается до 65, description до 158 (rulebook: около 50-60 и 150-160).
- Ровно один h1, `html lang`.
- JSON-LD только из проверенных данных: FAQPage сверяется с видимым FAQ, Product — с видимым текстом. Рейтинги, availability, priceValidUntil запрещены, у Offer обязательны price, priceCurrency и url.
- Ссылки только на URL из проб и доменов профиля.
- Коммерческие утверждения сверяются с VERIFIED COMPANY FACTS.
- Статические прокси CWV: lazy, hero не lazy, вес страницы.

**Расхождения с rulebook.**
1. Полный `Product` + `Offer` внутри `ItemList` на странице-подборке. По guidelines Google Product-разметка для конкретного товара, лучше summary ItemList с url (пробел 9).
2. `brand` запрещён даже тогда, когда он подтверждён. Schema skill рекомендует brand и sku.
3. Нет `datePublished`/`dateModified` (ai-seo Freshness).
4. BreadcrumbList не валидируется.
5. `og:image` не берётся из hero кампании, нет размеров.
6. Нет вводного абзаца: страница — тонкий листинг из заголовка, подзаголовка и карточек (seo-audit Thin Content, ai-seo Definition).
7. В детерминированном шаблоне названия товаров не h3, и у всех ссылок один анкор «Купити».
8. В meta description нет призыва (seo-audit: «Call to action»). Его можно добавить из i18n (`buy`) без выдумки, но это low priority.
9. Длину title проверяет только верхняя граница (>70). Нижней нет, хотя короткий «ARTLINE» при пустом `campaign_title` возможен.

Остальное (canonical, hreflang, robots, OG/Twitter, html lang, h1) закрыто полностью.
