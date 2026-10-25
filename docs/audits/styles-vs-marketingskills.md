# Стилі ARTLINE Rich Studio проти правил marketingskills

**Дата:** 2026-10-25
**Версія:** 12.20, промпти 12.78
**Джерело правил:** [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills), коміт `e85f3cb`.
**Дев'ять skills:** copywriting, copy-editing, marketing-psychology, product-marketing, cro, ai-seo, seo-audit, schema, image.

**Що перевірено:**
- усі 13 стилів у `apps/api/app/prompts.py`;
- спільні блоки: ARTLINE STANDARD, HUMAN COPY CONTRACT, SOURCE BOUNDARIES;
- збирання промпту, переклад і автовиправлення в `pipeline.py`;
- серверні перевірки в `seo_geo.py`;
- SEO лендингів.

**Як перевірено:** два незалежні аналізи — тексти та структура/CRO/SEO/GEO. Кожне твердження звірено з кодом.

**Детальні таблиці** (кожне правило, джерело, статус і цитата з промпту), обидві російською:
- [тексти](styles-vs-marketingskills-copy-details.md);
- [структура, SEO, GEO, зображення](styles-vs-marketingskills-seo-details.md).

## Результат перевірки (до виправлень)

| | Правил | Покрито | Частково | Бракує | Конфлікт | Не застосовне |
|---|---:|---:|---:|---:|---:|---:|
| Тексти | 72 | 22 | 28 | 8 | 5 | 9 |
| Структура, CRO, SEO, GEO, зображення | 57 | 24 | 18 | 5 | 3 | 7 |

**Сильні сторони, суворіші за marketingskills:**
- кожне число звіряється з фактами товару;
- без гіпербол і суперлативів;
- без тексту «про сторінку»;
- відповідь першим реченням;
- без довгого тире;
- жорсткі правила зображень;
- метатеги й schema заборонені всередині фрагмента.

**Головні прогалини:**
- структурні AI-шаблони («не просто X, а Y», переліки відсутностей, хвости «, забезпечуючи…»);
- пасив і «вода»;
- Hero без речення-визначення;
- можливий переказ опису з картки товару;
- Base і Engineering вимагали рівно 6+4+4 картки й «переупаковку» фактів — це суперечило власному правилу «пиши менше»;
- переклад RU/PL/EN без жодних правил тексту;
- повний Product+Offer у списку товарів лендингу.

**Уточнення до збирання промпту.** HUMAN COPY CONTRACT і SOURCE BOUNDARIES отримують усі стилі, зокрема Master. Master пропускає лише ARTLINE STANDARD. Тому одна правка контракту доходить до всіх 13 стилів.

## Що виправлено в 12.20

| # | Правка | Звідки правило | Де |
|---|---|---|---|
| 1 | Заборона структурних AI-шаблонів, гасел у кінці блоку, розкриття через двокрапку | copy-editing | HUMAN COPY CONTRACT + перевірка `ai_pattern` |
| 2 | Самоперевірка тексту: swap test, речення ≤25 слів, «Тепер покупець може…», без гасел | copywriting, copy-editing | HUMAN COPY CONTRACT, поріг `long_sentence` 25 |
| 3 | Гнучка кількість карток у Base і Engineering, без «переупаковки» фактів | copywriting | DEFAULT і ENGINEERING |
| 4 | Правила тексту для перекладу й автовиправлення | copy-editing | `translate_html`, `llm_fix_texts` |
| 5 | Активні дієслова, без «води» й нагромаджених застережень, розширені словники uk/ru/pl/en | copy-editing | HUMAN COPY CONTRACT + `passive_voice`, `GENERIC_PHRASES` |
| 6 | Аудиторія за стилем, голос ARTLINE, одна форма звертання | product-marketing | HUMAN COPY CONTRACT |
| 7 | Заголовки називають результат для покупця | copywriting, seo-audit | Showcase, Master + `weak_heading` для голих міток |
| 8 | Пояснення термінів для нетехнічного читача | copywriting | HUMAN COPY CONTRACT |
| 9 | Фінальні блоки без гасел | copy-editing | Base, Engineering, Showcase, Master (блок 07) |
| 10 | Чесні межі параметрів | marketing-psychology, cro | Base, Showcase, Bento |
| 11 | Речення-визначення в Hero | ai-seo, cro | ARTLINE STANDARD, Master, Bento + `definition_sentence_missing` |
| 12 | Не переказувати опис з картки товару | seo-audit | SOURCE BOUNDARIES + `source_text_copied` |
| 13 | Питання покупця з відповіддю першим реченням | ai-seo | Base §5, Engineering §5 |
| 14 | Абзац починається з предмета, а не з займенника | ai-seo | HUMAN COPY CONTRACT + `pronoun_opening` |
| 15 | Розміри зображень проти зсуву верстки | seo-audit, image | `_set_intrinsic_sizes` після генерації |
| 16 | Alt називає товар і кадр; alt при відновленні Hero | image, seo-audit | ARTLINE STANDARD, Master + `alt_without_entity` |
| 17 | Описові заголовки в Master, природний заголовок FAQ | seo-audit | Master |
| 18 | Лендинги: ItemList лише з посиланнями, `dateModified`, og:image з Hero, перевірка крихт | schema, seo-audit | `build_landing_jsonld`, `finalize_landing_seo`, `audit_landing_document` |
| 19 | Лендинги: вступний абзац, назви товарів — h3-посилання | cro, seo-audit | `LANDING_PROMPT`, `deterministic_landing` + `landing_no_lead`, `landing_heading_skip`, `generic_anchor_only` |
| 20 | Аварійний шаблон без маркетингових фраз; «999px» прибрано з промпту | copy-editing | `pipeline.py` |

Нові перевірки не блокують схвалення. Усі вони мають рівень warning або info, а рецензент може прийняти їх із коментарем.

## Що свідомо не зроблено

- **Перевірки категорії й теми брифу для RU/PL/EN.** Наразі вони працюють лише мовою брифу.
  - Щоб увімкнути їх для інших мов, тему й категорію треба перекладати на кожну мову під час перекладу сторінки. Це новий платний виклик і зміна API брифу.
  - Винесено в окреме завдання.
- **og:image:width / height.** Розмір Hero кампанії на момент збирання head невідомий без завантаження файлу. Додамо разом із кешем розмірів медіа.
- **Форма звертання для польської.** Правило каже «безособово або одна послідовна форма», без вибору між Ty та Państwo. Конкретну форму має підтвердити контент-відділ.
- **Глосарій термінів.** Правило «одна назва для поняття» додано в переклад. Окремий глосарій бренду варто зібрати разом із контент-відділом.

## Свідомі розбіжності з marketingskills

Ці правила marketingskills не застосовуються навмисно, за рішеннями власника:
- CTA, ціни, кнопки, терміновість і дефіцит — їх містить сторінка магазину, а не rich-фрагмент;
- відгуки, рейтинги й соціальний доказ;
- порівняння з конкурентами;
- твердження без підтвердження у фактах товару.

Документні SEO-елементи (title, meta, canonical, schema в head) належать сторінці магазину, а не фрагменту.
