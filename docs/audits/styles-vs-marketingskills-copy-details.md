## Копирайтинг: правила marketingskills против стилей

Источник правил: `marketingskills/skills/` — `copywriting` (SKILL.md, references/copy-frameworks.md, ai-tells.md, natural-transitions.md), `copy-editing` (SKILL.md, references/checklist.md, plain-english-alternatives.md, content-refresh.md), `marketing-psychology` (SKILL.md), `product-marketing` (SKILL.md, references/brand-voice.md).
Проект: `apps/api/app/prompts.py` (BASE_STYLE_VERSION 12.77), `apps/api/app/pipeline.py` (`_prompt`, `translate_html`, `llm_fix_texts`, `llm_critic_full`), `apps/api/app/seo_geo.py` (`audit_human_copy`, `audit_language_quality`, `audit_geo_copy`, списки фраз).

**Уточнение к постановке.** В `_prompt` (pipeline.py:3862-3864) Master пропускает только `ARTLINE_STANDARD` (`_standard_for` возвращает '' для master). `HUMAN_COPY_CONTRACT` и `SOURCE_BOUNDARY_RULES` добавляются безусловно, то есть Master их тоже получает. Значит, любая правка `HUMAN_COPY_CONTRACT` действует на все 13 стилей, включая Master, и не должна спорить с его FACTS AND COPY.

**Что ещё получает модель (из `_prompt`):** правило языка (`language_rule`) и правило единиц измерения; блок `SEO BRIEF` (тема, вопросы покупателя, аудитория, сущности; явно сказано, что это не факты); `VERIFIED COMPANY FACTS` (или запрет на «ми», доставку, гарантию); `PRODUCT FACTS` (`confirmed_only`); бюджет фото; golden example (только структура). **Остальные языки** (обычно RU/PL/EN) получаются не генерацией, а `translate_html` (tasks.py:1144) с коротким промптом, где правил копирайтинга нет вообще — только «Translate… Keep product names… Do not add facts». Ниже это отдельный пробел.

**Как проверяется после генерации:** детерминированные `audit_human_copy` (повторы предложений, одинаковые начала абзацев, бренд в заголовках, предложения длиннее 32 слов, абзацы длиннее 4 предложений, CALQUES, GENERIC_PHRASES, SUPERLATIVES >2, «!» >1, монотонные начала, keyword stuffing, обрубленные заголовки, PAGE_NARRATION, URGENCY, неестественная форма запроса), `audit_language_quality` (смешение алфавитов, кальки), `audit_geo_copy` (SCENE_SETTING и вопрос в начале абзаца → `not_answer_first`; числа без источника; COMMERCIAL_CLAIMS; COMPARISONS/SUPERLATIVES; качество FAQ). Плюс платный `llm_critic_full` и точечный `llm_fix_texts`. Длинное тире вычищается механически (`artline_standard.py:346`, `pipeline.no_em_dash`, `_STANDARD_SWAPS`).

### Сводка

Отобрано 72 правила, применимых к блоку описания на PDP.

| Статус | Кол-во |
|---|---|
| Covered (покрыто) | 22 |
| Partially covered (частично) | 28 |
| Missing (нет) | 8 |
| Conflicts (противоречит) | 5 (3 оправданы фиксированными решениями, 1 частично, 1 нет) |
| Not applicable (неприменимо) | 9 |

Коротко: фактология, конкретика, запрет хайпа, повтора и «описания страницы» сделаны сильнее, чем в рулбуке. Слабее всего — **структурные AI-шаблоны** (контраст-ревил «не просто X, а Y», списки отрицаний, хвосты из деепричастий, двоеточие-ревил, афористичные концовки). Здесь нет ни правил в промптах, ни проверок в seo_geo. Ещё три пробела: **активный залог и слова-пустышки**, **перевод на RU/PL/EN без правил копирайтинга** и **фиксированное число карточек в Base/Engineering**: оно провоцирует филлер вопреки собственному правилу «write less».

### Таблица правил

Сокращения: HCC = `HUMAN_COPY_CONTRACT`, SBR = `SOURCE_BOUNDARY_RULES`, Base = `DEFAULT_STYLE_PROMPT` (ARTLINE Base), Eng = `ENGINEERING_STYLE_PROMPT`, Show = `SHOWCASE_STYLE_PROMPT` (и производные Podium*/Dark), Promo = `SHOWCASE_PROMO_STYLE_PROMPT`, Bento = `BENTO_STYLE_PROMPT` (+Light), Master = `MASTER_STYLE_PROMPT`. CW = copywriting, CE = copy-editing, MP = marketing-psychology, PM = product-marketing.

#### A. Ясность и структура текста

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 1 | Ясность важнее остроумия | CW SKILL.md «Clarity Over Cleverness»; copy-frameworks «Clarity Beats Cleverness» | Covered | HCC: "Lead with the answer, not with scene-setting or a slogan."; Base SUCCESS CRITERIA 2: "The buyer immediately understands what the product is…"; Eng: "Inform precisely; do not sell." | — |
| 2 | Answer-first, главное в начале фразы/абзаца | CE SKILL.md Sentence-level «Front-load important information»; natural-transitions «Front-load key info» | Covered | HCC "Lead with the answer"; Base/Eng: "Prefer answer-first paragraphs"; Master DEPTH: "The first says what the feature is and gives its confirmed number"; `audit_geo_copy` → `not_answer_first` (SCENE_SETTING + абзац с «?») | — |
| 3 | Одна мысль на предложение | CE Sentence-level «One idea per sentence»; CW Quick Quality Check | Covered | HCC: "Keep one useful idea per sentence." | — |
| 4 | Длина предложения ≤ 25 слов, перечитать каждое > 20 слов | CE Sentence-level «No more than 25 words (usually)»; ai-tells Self-Check п.2 | Partial | HCC: "keep most sentences concise"; `audit_human_copy` п.4: `len(words(s)) > 32` (info, warning при ≥3) | Порог 32 слова мягче рулбука. Числа нет ни в одном промпте |
| 5 | Разный ритм, без одинаковых конструкций | ai-tells #9 Uniform rhythm; CE «Vary sentence length» | Covered | HCC: "Vary sentence length naturally"; аудиты `monotonous_construction`, `repeated_paragraph_opening` | — |
| 6 | Короткие абзацы (2-4 предложения) | CE Paragraph-level | Covered | Base/Eng TYPOGRAPHY: "Limit paragraphs to 2-3 sentences"; Show: "2-3 sentences (at most 320 characters)"; Master: "two paragraphs, together 50-90 words"; аудит `long_paragraph` > 4 | — |
| 7 | Rule of One: одна идея на секцию, без повторов между секциями | CW «One Idea Per Section»; CE Sweep 1 «Rule of One» | Covered | Base/Eng: "Each section must contribute new information; never reuse the same sentence…"; Show: "blocks 3, 4 and 5 describe different features", NUMBER DISTRIBUTION; Master: "Each value is shown as a tile ONCE per page"; аудит `duplicate_sentence` | — |
| 8 | Жаргон объясняется (curse of knowledge) | CE Sweep 1, checklist «No jargon without explanation»; MP «Curse of Knowledge» | Partial | Eng намеренно: "Assume technical literacy; do not explain trivialities." HCC: "speaking to a technically interested buyer". В Base/Show/Bento/Master правила нет | Для Eng расхождение оправдано аудиторией. Для Base/Show/Master (неэксперт, решает «глазами») MPPT, LiFePO4, Direct Drive, HDR остаются без перевода на язык пользы |
| 9 | Простые слова, без номинализаций («make a decision» → «decide») | CW Style 1; CE Word-level; plain-english-alternatives.md | Partial | HCC: "Prefer plain native-language wording over translated marketing idioms."; CALQUES uk: 'здійснювати роботу', 'дозволяє забезпечити', 'проводити роботу' | Цепочки «забезпечує + віддієслівний іменник» в промптах не упомянуты |
| 10 | Активный залог | CW Style 3 «Active over passive»; CE «Passive voice (switch to active)» | **Missing** | — | Для UA/RU безличный пассив («здійснюється», «забезпечується», «осуществляется») — главный признак канцелярского и машинного тона. Нет ни правила, ни проверки |
| 11 | Конкретный субъект (покупатель или изделие что-то делает), без абстрактных субъектов | ai-tells #11 Abstract subjects; CE Sweep 1 «You Rule» | Partial | Base: "Write only about the product and what the buyer does with it."; HCC: "Use specific nouns, verbs…"; CALQUES ловят 'дозволяє забезпечити', 'allows to' | Конструкция «Рішення дозволяє…/Технологія забезпечує…» не запрещена |
| 12 | Убрать пустые усилители и слова-заполнители (дуже, справді, просто, фактично; very, really, truly) | CW Style 4 «Confident over qualified»; CE Word-level «Cut these words»; ai-tells «Cap (empty intensifiers)»; plain-english «Phrases to Remove Entirely» | **Missing** | — | Нет ни в промптах, ни в GENERIC_PHRASES/CALQUES |
| 13 | Без нагромождения оговорок («може потенційно допомогти») | ai-tells «Hedge stacks» | **Missing** | — | Правила Eng про выводы («never present an inference as a confirmed fact») без явного лимита подталкивают модель к двойным оговоркам |
| 14 | Без восклицательных знаков | CW Quick Quality Check; ai-tells «Hype punctuation (Ban)» | Partial | `audit_human_copy` п.9: `exclamations > 1` (info/warning); в промптах не сказано | Один «!» проходит проверку |

#### B. Польза, конкретика, доказуемость

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 15 | Польза важнее свойства; тест «So what?» (мост «що означає…») | CW «Benefits Over Features»; CE Sweep 3; MP «Jobs to Be Done» | Covered (Show/Bento частично) | HCC: "Explain why a confirmed characteristic matters without exaggerating it."; Base: "Convert confirmed specifications into practical buyer value"; Eng: "number and unit -> how it is achieved -> what it means in practice"; Master DEPTH: "the second says what it changes for the buyer" | В Show (spec strip: "then h3, then one short line") и Bento ("one short 13px line") не сказано, что строка под значением должна отвечать на «so what» |
| 16 | Конкретика: числа, единицы, условия | CW «Specificity Over Vagueness»; CE Sweep 5 | Covered | HCC: "Use specific nouns, verbs, values and product entities."; Eng: "write "180 x 180 x 180 mm build volume", not "spacious working area""; Show: "Numbers with units everywhere a number exists."; Master: "Retain conditions: rated vs peak power…"; аудит `no_concrete_values` | Сильнее рулбука |
| 17 | Только доказуемые утверждения, без выдуманных цифр и отзывов | CW «Claims Must Be Supportable»; CE Sweep 4; ai-tells «Reflexive specificity», Rewrite rule 5 | Covered | Base/Eng SOURCE OF TRUTH; SBR: "a search query is not a fact"; аудиты `number_without_provenance` (critical), `unsupported_commercial_claim`, `unsupported_comparison`, `unsupported_superlative` | Сильнее рулбука |
| 18 | Отклонённое утверждение называет, что его «разблокирует» (`[NEED: …]`) | CW «Declines Must Name Their Unlock»; ai-tells Rewrite rules 5, 9 | Conflict (оправдан) | Base: "If a fact is absent or ambiguous, omit it."; HCC: "If the available facts are insufficient, write less." | В видимый HTML маркер `[NEED]` попасть не может. См. «Сознательные расхождения» |
| 19 | Тест подмены (swap test): фразу мог бы написать конкурент — переписать | CW «three-question gate» п.3; ai-tells Rewrite rule 3, Self-Check п.5 | Partial | Base: "If a sentence would be equally true for any other product in any category, delete it…"; Eng: "equally true for any other product in the category, delete it…"; в HCC, Show, Bento, Master нет | Формулировка Base («in any category») слабее рулбука: почти любая фраза о мониторе не подходит холодильнику и проходит. У Eng («in the category») — верно |
| 20 | «Три вопроса»: можно представить? можно опровергнуть? | CW Drafting Protocol | Partial | Проверяемость обеспечена правилами конкретики; «представить» — Base scenarios: "names a real context"; Master: "a situation Product JSON supports (home backup, a trip, an office desk)" | Как самопроверка не сформулировано |
| 21 | Дозировать «панч»: 1-2 яркие строки на страницу, остальное — просто и конкретно | CW «Ration the punch» | Partial | Base Hero: "The h2 may be slightly more marketing-oriented"; Eng запрещает маркетинг совсем; Show/Bento: "Inform confidently" | Явного лимита нет |
| 22 | 3-5 ключевых преимуществ, а не 6-10; без перегруза фичами | copy-frameworks «Solution/Benefits Section: 3-5 key benefits (not 10)»; CE «Feature Overload» | **Conflict (не оправдан)** | Base: "Use exactly six equal light content islands"; "six benefit cards, four scenarios, four buyer-confidence items and three final tags"; Base:76/Eng:375: "reframe genuine facts into distinct practical angles" | Не следует из фиксированных решений. Жёсткие 6+4+4+3 при бедном JSON заставляют пересказывать один факт разными словами. Это спорит с HCC "write less". Show/Bento/Master уже разрешают убирать плитки |
| 23 | Убрать то, что нельзя конкретизировать (филлер) | CE Sweep 5 п.4; ai-tells «Perfect balance» | Covered (с внутренним конфликтом) | HCC: "If the available facts are insufficient, write less. Never use filler to reach a target word count."; SBR length guide; Base: "Never pad to reach a word count." | Конфликтует с п.22 в Base/Eng |

#### C. AI-шаблоны (ai-tells)

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 24 | Без контраст-ревила «не X, а Y» / «не просто X, а Y» / «це не лише…, а й…» | ai-tells #1 (Ban); CW No AI Tells п.1 | **Missing** | — | Самый частый AI-шаблон и в UA/RU/PL. Замена тире на «–» его не убирает: «Це не просто павербанк – це зарядна станція» проходит все проверки |
| 25 | Без списков отрицаний «без X, без Y, без Z» | ai-tells #2 (Ban) | **Missing** | — | — |
| 26 | Без хвостов после законченного утверждения (", забезпечуючи…", ", що дозволяє…", ", ensuring…") | ai-tells #3 Trailing pile-on (Ban) | **Missing** | Косвенно: CALQUES 'дозволяє забезпечити' | Для UA/RU это деепричастные и «що»-хвосты |
| 27 | Без вопроса с самоответом и двоеточия-ревила («Результат? …», «Головне: …») | ai-tells #4, #5 (Ban) | Partial | HCC: "Avoid empty introductions, rhetorical questions…"; `not_answer_first` ловит абзац, начинающийся с «?» | Ревил через двоеточие или «–» не запрещён и не проверяется |
| 28 | Без шаблонных зачинов («У сучасному світі», «Уявіть», «Коли йдеться про…») | ai-tells Openers; CW No AI Tells п.5 | Covered | HCC "not with scene-setting"; SCENE_SETTING uk/ru/pl/en (`уявіть`, `у сучасному світі`, `коли йдеться`…) в `audit_geo_copy` | — |
| 29 | Запрещённые и лимитированные слова и маркетинговые клише (seamless, robust, powerful, unlock, next level…) | ai-tells «Marketing Phrases», «Vocabulary»; CE «Replace with the fact» | Partial | HCC: "Avoid generic phrases equivalent to: innovative solution, new level, …"; Eng: "Marketing adjectives are banned: premium, revolutionary, amazing, perfect, unmatched, best, cutting-edge, powerful, ultimate."; GENERIC_PHRASES uk/ru/pl/en | Для uk/ru/pl нет cap-слов: «потужний», «надійний», «ефективний», «широкий спектр/широкі можливості», «незамінний помічник», «стильний дизайн». Запрет Eng есть только в Eng |
| 30 | Без превосходной степени без доказательства | CE Sweep 4 «No unearned superlatives» | Covered | SUPERLATIVES (human: >2; geo: любое → `unsupported_superlative`); Base Final: "no … unsupported superlatives"; Show: "no marketing superlatives without a number behind them" | — |
| 31 | Без «важности» и вводных-паразитов («відіграє ключову роль», «варто зазначити», «крім того», «moreover», «it's worth noting») | ai-tells Openers «Filler transitions», Hedges «Importance puffery (Ban)»; natural-transitions «Transitions to Avoid» | **Missing** | — | Нет ни в одном списке seo_geo |
| 32 | Без «мудрых» фраз и красивых концовок («Бо комфорт не має чекати») | ai-tells Second-Generation: «Wisdom-shaped sentences», «Tidy closers», «Fake-profound kicker» (Ban) | Partial | HCC: "…conclusions that repeat the heading."; Base Final: "short factual summary… without copying earlier sentences" | Риск в финальных блоках. Master block 07 прямо просит "one centered paragraph carrying a new usage or design message" — это приглашение к слогану |
| 33 | Текст не комментирует сам себя или страницу | ai-tells Second-Gen «Self-narration» | Covered | Base/Eng "NEVER DESCRIBE THE PAGE OR THE IMAGES" с примерами; Show/Bento то же; Master: "No sentences about the page, images, blocks or instructions."; PAGE_NARRATION | Мета-фразы вида «Ось чому це важливо» в regex не входят |
| 34 | Без длинного тире | ai-tells #8; CW No AI Tells п.6 | Covered (строже) | ARTLINE_STANDARD: "Never the em dash character and never &mdash;."; Master "NO EM DASH"; механическая замена | См. п.24: шаблон остаётся с en dash |
| 35 | Не больше одного фрагмента и одной тройки на секцию в прозе | ai-tells #6, #7, Second-Gen «Staccato bursts» | Partial | Фактические тройки (3 чипа Hero, 3 тега, Trio) — это перечни фактов, рулбук такие разрешает ("a list of three when there really are three features") | Для прозы лимита нет |
| 36 | Без смены синонимов для одного понятия | ai-tells #13 | Partial | Eng: "Keep terminology consistent across the whole page: one term per concept." | Только в Eng |
| 37 | Без уклонения от «є/має» («служить», «являє собою», «boasts», «serves as») | ai-tells #10 | Partial | CALQUES: 'являється', 'являє собою', 'является', 'представляет собой', 'stanowi rozwiązanie', 'is characterized by' | В en нет 'serves as', 'boasts' |
| 38 | Заголовки утверждают, а не называют рубрику | ai-tells Formatting «Label headings» | Partial | Base: "Every heading names a product capability, benefit or buyer outcome — never a page element."; Eng: "names a parameter, a technical solution or an application"; Master: h2 вроде "КЛЮЧОВІ ПАРАМЕТРИ", "НАДІЙНА ОСНОВА", "ЕКСПЛУАТАЦІЯ", но ACCENT SUBTITLE "states the concrete benefit or value of the block"; аудит `weak_heading` ловит только обрывки | В Show для h2 блоков 3-6 нет правила формулировки (только Final Recap: "stating the main benefit in one line") |
| 39 | Не начинать все пункты и карточки одинаково | ai-tells Formatting «Parallel bullet openers» | Partial | `repeated_paragraph_opening` (3+ абзаца), `monotonous_construction` (3 предложения подряд) | h3 карточек не проверяются |
| 40 | Без эмодзи и декоративного юникода | ai-tells Formatting | Covered | Base: "Do not use icons, emoji…"; Bento: "emoji or any invented icons"; Master: "No icons" | — |

#### D. Голос, тон, язык покупателя

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 41 | Голос задан и выдержан по всей странице | CE Sweep 2; PM brand-voice.md «Build the profile» | Partial | HCC: "Write like an experienced product editor…"; Eng: "Write engineer to engineer: neutral, precise…"; Show/Bento: "Inform confidently; never invent."; Promo PROMO TONE | Нет профиля ARTLINE в формате «значит / не значит» |
| 42 | Одна форма обращения («ми» и «компанія»; ви/ти; Ty/Państwo) | CE Sweep 2 «Mixing "we" and "the company"» | Partial | HCC: "Do not use "we", "our service"… unless supplied in VERIFIED COMPANY FACTS"; `company_facts_block` | Форма обращения к читателю не задана. Promo косвенно задаёт: "Twoje logo" (PL Ty), "Ваш логотип" (ви/вы) |
| 43 | Тон по контексту: энергия через факты, без превосходных степеней | brand-voice.md «Tone by context» | Covered | HCC: "Do not address the buyer with artificial urgency."; URGENCY; Eng "No hype" | — |
| 44 | Глоссарий: «наши термины», «никогда не используем» (с причиной) | brand-voice.md «Words»; PM SKILL.md §9-10 | **Missing** | — | Только `SEO BRIEF: entities to name precisely` и Eng «one term per concept». Единых пар терминов на UA/RU/PL нет |
| 45 | Язык покупателя, а не компании | CW «Customer Language Over Company Language»; PM «Customer Language» | Partial | SEO BRIEF: primary topic, buyer questions, audience; HCC: "Do not force SEO phrases into grammatically unnatural forms."; аудит `unnatural_keyword_form` | Отзывы как словарь не используются (их не публикуем, но слова покупателя взять можно) |
| 46 | Точечная правка меняет только то, что нужно (Situation C, leave-it-alone) | CW «Diagnose the Situation First»; CE checklist «Point-edit mode» | Covered | `llm_fix_texts`: "Виправ ЛИШЕ сегменти, яких стосуються зауваження… Довжину тримай близькою до оригіналу." | В промпте нет запрета на синонимические подмены, которые рождают новые AI-шаблоны (ai-tells Rewrite rule 1) |
| 47 | Одна аудитория на страницу | CE «Problem: Mixed Audiences» | Partial | Eng: "technically literate buyer"; Promo "WHO IS READING"; HCC: "speaking to a technically interested buyer" | HCC навязывает «технически заинтересованного» читателя и Show (решает глазами), и Promo (закупщик мерча, "never compare model codes"). Внутреннее противоречие |
| 48 | «Писатель» с позицией: что знает лучше всего, что выбросит | ai-tells «Build a Writer» | Partial | HCC "experienced product editor"; Eng "engineer to engineer" | Неравномерная плотность не поощряется (см. п.58) |
| 49 | Естественная локализация, не дословный перевод | CW «Customer Language»; CE Sweep 2; natural-transitions | Partial | Base/Eng LANGUAGE CONTRACT: "Write natural native ecommerce copy, not literal machine translation."; CALQUES + `literal_translation` | **Вторичные языки** делает `translate_html` (pipeline.py:4448): промпт без единого правила копирайтинга |
| 50 | Грамматика и опечатки в финальной проверке | CE checklist «Final Checks» | Partial | Master: "Write in the target language with correct grammar."; языковые аудиты (алфавиты, польская диакритика) | Орфографии нет (приемлемо) |

#### E. Структура страницы, заголовки, убеждение

| # | Правило | Источник | Статус | Где в проекте / цитата | Комментарий |
|---|---|---|---|---|---|
| 51 | Заголовок = главное ценностное предложение; формулы («{outcome} without {pain}») | CW Page Structure «Headline»; copy-frameworks «Headline Formulas» | Conflict (оправдан) | Show: "the h2 is BRAND + MODEL CODE only"; Master: "Hero h2: the exact brand and model"; Base: "Pattern: "Exact brand/model – confirmed buyer value""; Eng: "Exact brand/model – category with its defining confirmed characteristic" | Ценность перенесена в подзаголовок и абзац. См. «Сознательные расхождения» |
| 52 | Подзаголовок раскрывает заголовок, 1-2 предложения; ценность названа сразу | CW «Subheadline» | Partial | Base: "State what the product is and its strongest confirmed value in the first two text elements."; Show: подзаголовок — спецификации через " · "; Master: "one accent line of the 2-4 strongest identifiers" | В Show/Podium/Master подзаголовок — список параметров. Не сказано, что абзац Hero (≤ 2 предложений) называет главную пользу для покупателя |
| 53 | Тест «Now you can…» для строк с пользой | copy-frameworks «The "Now you can" Test» | Partial | Master: ACCENT SUBTITLE "states the concrete benefit or value of the block in plain words"; Base: "one benefit-led h3" | В Show/Bento h3 и строки под значением этот тест не проходят |
| 54 | Дискомфорт → видение → путь (Human Action Model), секция проблемы | copy-frameworks «Human Action Model»; CW «Problem/Pain» | Partial | Base scenarios: "names a real context, the relevant task and the confirmed reason the product fits it"; Eng: "workload -> requirement -> confirmed parameter" | Задача покупателя есть, выдуманной боли нет — это правильно. Секция «боли» неуместна |
| 55 | Эмоциональная насыщенность (Sweep 6) | CE Sweep 6 | Conflict (оправдан) | Eng: "Inform precisely; do not sell."; тон информативный (фиксированное решение) | Допустимая часть — конкретная ситуация (Master DEPTH) |
| 56 | Работа с возражениями (FAQ, «что проверить») | CE Sweep 7; CW Core Sections «Objection Handling» | Covered | Base "BUYER CONFIDENCE — WHAT TO CONSIDER"; Eng "TECHNICAL CONSIDERATIONS"; Show TRUST SPLIT: "Each tile answers a real buyer decision"; FAQ: "real pre-purchase questions THIS Product JSON can answer"; Master «Сумісність і обмеження»; аудиты `faq_question_unnatural`, `faq_answer_thin` | Возражения уровня товара закрыты. Гарантии и risk reversal — N/A |
| 57 | Честные границы (эффект пратфолла), «для кого не подходит» | ai-tells «Build a Writer: Honest limits»; MP «Pratfall Effect» | Partial | Eng: "an engineer trusts a page that names limits"; Promo: "An honest limit converts better than a promise the factory cannot keep."; Master: "Retain conditions…"; Base: "what to consider before choosing it"; Show: "an operating limit" | В Bento ничего. «Для кого не подходит» нигде не выводится из подтверждённых границ |
| 58 | Неравномерная плотность вместо «идеального баланса» | ai-tells Second-Gen «Perfect balance» | Conflict (частично оправдан) | Base: "Cards within the same group must have equal visual weight"; Show "EQUAL DESKTOP CARDS"; Master "three equal-height cards" | Визуальное равенство — решение дизайна. Но текст в карточках тоже стремится к одинаковой длине, а этого никто не требует |
| 59 | JTBD: продукт «нанимают» ради задачи | MP «Jobs to Be Done» | Covered | Base/Eng scenarios/applications; Promo: "Every section must answer one of those six." | — |
| 60 | Этичный фрейминг (не выбирать самое эффектное число) | MP «Framing Effect» | Covered | Master: "Never silently choose the more impressive number."; Eng: "Never round, convert or reword them." | Строже рулбука |
| 61 | Авторитет (сертификаты) — только реальный | MP «Authority Bias» | Covered | Base/Eng: "Never invent … certifications"; допустимы, если есть в Product JSON | — |
| 62 | Самопроверка перед сдачей (AI-tells self-check) | ai-tells «The Self-Check»; CE checklist «AI Tells» | Partial | FINAL SELF-CHECK везде в основном про структуру. Про текст: Base "every sentence is specific to this exact product…"; Eng "no marketing adjective or superlative appears anywhere"; Master "every claim, number and FAQ answer is confirmed" | Копирайтерского чек-листа (ревилы, хвосты, концовки, длина) нет ни в одном стиле |
| 63 | Экспертная оценка копии | CE «Expert Panel Scoring» | Covered | `llm_critic_full`: категории facts / human_copy / seo / geo / language, структурные issues с цитатой; детерминированные аудиты как первая линия | — |

#### F. Неприменимо

| # | Правило | Источник | Статус | Комментарий |
|---|---|---|---|---|
| 64 | CTA-копия (глагол + что получит) | CW «CTA Copy Guidelines» | N/A | Фиксированное решение: CTA и кнопки на странице магазина |
| 65 | Социальное доказательство, отзывы, логотипы, статистика клиентов | CW Core Sections; copy-frameworks Testimonials; MP Social Proof, Bandwagon | N/A | Фиксированное решение; отзывы уже на PDP |
| 66 | Срочность, дефицит, неприятие потерь | MP Scarcity, Loss Aversion | N/A | Фиксированное решение; соблюдается через URGENCY |
| 67 | Ценовая психология (якорь, decoy, charm pricing, mental accounting) | MP Pricing Psychology | N/A | Цен в блоке нет |
| 68 | Сравнения с конкурентами и статус-кво, contrast effect | copy-frameworks «Comparison Section»; MP Contrast Effect | N/A | Фиксированное решение; соблюдается через COMPARISONS |
| 69 | Гарантии, risk reversal, «no card required» | CE Sweep 7; CW «Final CTA» | N/A | Только из VERIFIED COMPANY FACTS (COMMERCIAL_CLAIMS) |
| 70 | Юмор, риторические вопросы голосом читателя, аналогии | CW Best Practices | N/A | Тон информативный; HCC запрещает риторические вопросы (строже рулбука). Аналогии рискуют привести непроверенные факты |
| 71 | Meta title/description, «Last updated», content refresh | CW Output «Meta Content»; content-refresh.md | N/A | Блок встраивается в чужую страницу; мета у хоста. Страницы регенерируются, а не освежаются |
| 72 | Hick's law, paradox of choice, defaults | MP Design & Delivery | N/A | В блоке нет выбора и действий |

### Главные пробелы и предложения

Ранжировано по ожидаемому влиянию на качество текста. Ни одно предложение не нарушает фиксированных решений (факты только из JSON, без CTA, цен, отзывов, сравнений и срочности, без длинного тире).

**1. Структурные AI-шаблоны: запрет в промпте и проверка в seo_geo** (п.24, 25, 26, 27, 32)
Место: `HUMAN_COPY_CONTRACT`. Его получают все стили, включая Master, поэтому достаточно одного места. Дополнительно новый regex-список в `seo_geo.py` (например, `AI_PATTERNS` с проверкой в `audit_human_copy`).
```
- Never stage a contrast reveal ("not just X, but Y", "це не просто X, а Y", "не лише X, а й Y", "это не X, а Y", "to nie tylko X, ale Y"), whatever dash or comma joins it. State Y directly with its confirmed reason.
- Never define the product by a list of absences ("без X, без Y, без Z"). Say what the product does; mention one confirmed absence once, only when it matters to the buyer.
- End a sentence where its claim ends. Do not append a participle or "що/который/which" clause that restates the benefit (", забезпечуючи…", ", що дозволяє…", ", обеспечивая…", ", zapewniając…", ", ensuring…"). A clause that adds a new confirmed fact may stay.
- No colon or dash reveals and no self-answered questions in running copy ("Результат: …", "Головне – …", "Чому це важливо? Тому що…").
- No aphorisms or quotable closing lines that would fit any product ("Бо комфорт не повинен чекати"). End every block on its last concrete fact.
```
Regex для seo_geo (uk/ru/pl/en, примеры): `не (лише|тільки|просто) [^.]{1,60}, (а|але) й?`, `не просто [^.]{1,40}[,–-] (а|це)`, `^(результат|головне|секрет|суть)\s*[:–-]`, `,\s*(забезпечуючи|дозволяючи|гарантуючи|обеспечивая|позволяя|zapewniając|umożliwiając|ensuring|allowing)\b`, `\bбез [^.,]{1,30}, без [^.,]{1,30}`.

**2. Копирайтерская самопроверка со swap test** (п.4, 19, 20, 35, 53, 62)
Место: в конец `HUMAN_COPY_CONTRACT` (отдельный подзаголовок). Swap test сейчас есть только в Base и Eng, причём в Base слабый ("in any category"). Отдельно: в `audit_human_copy` снизить порог `> 32` до `> 25`. Почему: в UA/RU слова длиннее, но 32 — это уже два предложения.
```
COPY SELF-CHECK (run before returning the page)
- Swap test: put a competitor's product of the same category in place of this one. If a sentence stays true, rewrite it from a confirmed fact or delete it.
- Any sentence over 25 words: split it or cut the clause after the main claim.
- Every h3, accent subtitle and value caption: prefix it mentally with "Now the buyer can…". If the result is vague or not backed by a confirmed value, rewrite it.
- The last sentence of every block: if it is a slogan, a mood line or a summary of the block, cut it.
- Running text has at most one sentence fragment and one list of three per block (value tiles, chips and tags do not count).
```

**3. Убрать навязанное количество карточек и «переупаковку» фактов в Base и Engineering** (п.22, 23)
Место: `DEFAULT_STYLE_PROMPT` (секции 2, 4, 5 и FINAL SELF-CHECK) и `ENGINEERING_STYLE_PROMPT` (секции 2, 4, 5). Строки 76/375 заменить. Show, Bento и Master уже позволяют убирать плитки. Base и Eng остаются единственными стилями, где модель обязана написать 6+4+4 карточки даже при пяти фактах.
```
- If confirmed facts are too few for the preferred element count, use fewer elements (benefit cards: 6 or 3; scenarios and considerations: 4 or 2, so desktop rows stay full). Never split one fact into two cards or restate it in other words to reach a count.
```
FINAL SELF-CHECK: "six benefit cards, four scenarios, four buyer-confidence items" заменить на "six or three benefit cards, four or two scenarios and considerations, each carrying a different confirmed fact". Сначала проверить, что валидаторы и `_finalize`-логика не требуют ровно шесть карточек. В pipeline.py:4317 требование «ALL SIX sections» касается секций, а не карточек.

**4. Правила копирайтинга для перевода и автоисправления** (п.46, 49)
Место: промпт `translate_html` (pipeline.py:4448) и `llm_fix_texts` (pipeline.py:4493). RU/PL/EN-версии сейчас пишутся промптом без единого правила копирайтинга. Кальки ловятся только постфактум.
Для `translate_html` (после "Do not add facts…"):
```
Localize, do not mirror the source syntax: write each segment the way a native ecommerce editor of the target language would, with the same meaning, facts and roughly the same length. Use the target language's own word order and active verbs; avoid calques and bureaucratic constructions of the source language. Keep one term per concept across all segments. Keep the page's address form. Do not add marketing adjectives, superlatives, exclamation marks, "not just X but Y" constructions or trailing participle clauses that are absent from the source.
```
Для `llm_fix_texts`: "Переписуй від факту, а не заміною синонімів; не додавай конструкцій «не просто…, а…», хвостів «, що забезпечує…», вигуків і слів-підсилювачів."

**5. Активный залог, слова-пустышки, вводные-паразиты, оговорки** (п.10, 11, 12, 13, 31, 29)
Место: `HUMAN_COPY_CONTRACT`. Плюс расширить `GENERIC_PHRASES` / `CALQUES` в `seo_geo.py`.
```
- Prefer active verbs with a concrete subject: the product, its part or the buyer does something ("Інвертор перемикається на батарею за 10 мс"), not an impersonal passive ("здійснюється перемикання", "забезпечується захист") and not an abstract subject ("технологія дозволяє…").
- Cut empty intensifiers and filler transitions: дуже, справді, дійсно, надзвичайно, просто, фактично, варто зазначити, слід відзначити, крім того, важливо, відіграє ключову роль, and their equivalents in the target language.
- Hedge an inference once ("підходить для…"); never stack hedges ("може потенційно допомогти"). A confirmed fact needs no hedge.
```
Добавить в списки: uk `варто зазначити`, `слід зазначити`, `відіграє ключову роль`, `відіграє важливу роль`, `широкий спектр`, `широкі можливості`, `незамінний помічник`, `надійний помічник`, `стильний дизайн`, `на високому рівні`; ru `стоит отметить`, `следует отметить`, `играет ключевую роль`, `широкий спектр`, `незаменимый помощник`, `надежный помощник`; pl `warto zaznaczyć`, `warto podkreślić`, `odgrywa kluczową rolę`, `szeroki zakres`, `niezastąpiony`; en `it is worth noting`, `plays a crucial role`, `moreover`, `furthermore`, `serves as`, `boasts`, `robust`. Новый список пассивных форм как info-сигнал (≥ 3 на страницу): `здійснюється`, `забезпечується`, `осуществляется`, `обеспечивается`, `jest realizowan`.

**6. Аудитория в HCC без «технического» читателя по умолчанию; единая форма обращения и короткий профиль голоса** (п.41, 42, 47)
Место: первая строка `HUMAN_COPY_CONTRACT` заменить, ниже добавить две строки. Формы обращения выведены из уже принятого в Promo ("Twoje logo", "Ваш логотип"), но их стоит подтвердить у владельца.
```
- Write like an experienced ARTLINE product editor speaking to the reader described by the style prompt (a technically literate buyer for Engineering, a buyer who decides by eye for Showcase and Bento, a bulk client for Promo).
- Address form, one per page: Ukrainian and Russian use plural "ви/вы" in lowercase or impersonal sentences, never "ти/ты"; Polish uses "Ty" forms or impersonal sentences; English uses "you".
- ARTLINE voice: calm, exact, useful. It means numbers with their conditions, plain verbs and the buyer's decision first. It does not mean a dry spec dump, hype, jokes or claims about the shop.
```

**7. Заголовки и подзаголовки, которые утверждают пользу** (п.38, 52, 53)
Место: Show `FACTS AND TONE` (наследуют Podium*, Dark, Promo) и Master `FACTS AND COPY` (рядом с ACCENT SUBTITLE).
Show:
```
- Every h2 after the Hero states the buyer outcome of its block in plain words with a confirmed value where one exists ("Друкує до 12 годин без нагляду"), never a topic label ("Характеристики", "Особливості"). The Hero paragraph names the single strongest buyer benefit in its first sentence.
```
Master:
```
- An h2 may be a short topic label only because its accent subtitle carries the claim: the accent subtitle must name what the buyer gets or can now do, with a confirmed value, never repeat the h2 in other words.
```

**8. Объяснять ключевые термины для неэкспертного читателя** (п.8)
Место: `HUMAN_COPY_CONTRACT` с явным исключением для Engineering (не дублировать в каждом стиле).
```
- Unless the style prompt says the reader is technically literate, the first time a technical term or abbreviation carries a benefit (MPPT, LiFePO4, Direct Drive, HDR10), add one plain clause on what it means for the buyer's task. Do not add numbers, mechanisms or components that Product JSON does not confirm, and do not explain the same term twice.
```

**9. Финальные блоки без слоганов** (п.32)
Место: Master, строка блока `07 VISUAL ACCENT`; Base, секция `6. FINAL SUMMARY`; Show, `7. FINAL RECAP`. Самое рискованное место — формулировка Master "carrying a new usage or design message".
Master (заменить фрагмент):
```
…and one centered paragraph that states one more confirmed usage or design fact from Product JSON together with the brand/model mention. Never a slogan, aphorism, mood line or summary of the page.
```
Base/Show (добавить строку):
```
- The summary closes on a concrete confirmed fact, not on a quotable line that could end any product page.
```

**10. Честные границы во всех стилях, а не только в Engineering и Promo** (п.57)
Место: Base секция 5 (BUYER CONFIDENCE), Show блок 6 (TRUST SPLIT) и FAQ, Bento FAQ. Master уже покрыт блоком «Сумісність і обмеження».
```
- When a confirmed parameter sets a boundary (maximum load, supported formats or materials, size, operating temperature, required accessory), state it once, plainly, as something the buyer should check before choosing. Never present it as a weakness, never infer a limit beyond the stated number, and never claim there is none.
```

### Сознательные расхождения

Эти правила рулбука не применяются из-за фиксированных решений владельца или назначения блока (встраивается в чужой PDP). Дефектами их не считаю.

- **CTA, кнопки, «Start free trial», финальный призыв** (CW CTA Guidelines, Final CTA) — CTA на странице магазина.
- **Социальное доказательство, отзывы, кейсы, «10 000+ клиентов», логотипы** (copy-frameworks, MP Social Proof, Bandwagon, Mimetic desire) — запрещены; отзывы уже есть на PDP.
- **Срочность, дефицит, loss aversion, FOMO** (MP Scarcity/Urgency, Loss Aversion; CE Sweep 6 «Fear of missing out») — запрещены и проверяются (`URGENCY`).
- **Гарантии и risk reversal** (CE Sweep 7, CW Final CTA) — только дословно из VERIFIED COMPANY FACTS (`COMMERCIAL_CLAIMS`, `company_facts_block`).
- **Сравнения с конкурентами и статус-кво** (copy-frameworks Comparison Section, MP Contrast Effect, Anchoring) — запрещены (`COMPARISONS`).
- **Цены и ценовая психология** (MP Pricing Psychology) — цен в блоке нет; Promo: "Never state a price…".
- **`[NEED: …]` и «разблокировка» отклонённого утверждения** (CW Claims) — маркер не может попасть в опубликованный HTML. Проект выбирает «omit / write less». Если нужно, такие пометки можно отдавать оператору в отчёте критика, но не в странице.
- **Формулы заголовка Hero** (copy-frameworks Headline Formulas) — Hero h2 содержит бренд и модель (Show/Podium/Master: только бренд и код; Base/Eng: бренд и модель плюс подтверждённая ценность). Причины: у PDP уже есть h1 с названием, а для GEO нужна явная сущность. Ценностное предложение вынесено в подзаголовок и абзац. Рекомендация 7 требует, чтобы польза была названа там явно.
- **Heightened emotion, яркое «до», микроистории** (CE Sweep 6) — тон информативный; Eng: "do not sell". Допустима только конкретная ситуация из подтверждённых фактов (Master DEPTH).
- **Риторические вопросы голосом читателя, юмор, аналогии** (CW Best Practices) — HCC запрещает риторические вопросы (строже рулбука). Юмор не в тоне. Аналогии рискуют привести непроверенные факты.
- **Длинное тире: «1-2 на страницу в длинном тексте»** (ai-tells #8) — проект строже: ни одного, с механической заменой.
- **Визуально равные карточки** (ai-tells Perfect balance) — решение дизайна. Неравномерность допустима в тексте внутри карточек, а не в сетке.
- **Meta-контент и content refresh** — мета принадлежит странице-хосту, блок регенерируется.

### Попутные наблюдения (вне рамок промптов стилей)

- Офлайн-фолбэк `_deterministic_html` / `LOCAL_FALLBACK` (pipeline.py:334-337, 3896-3900) сам состоит из пустых фраз, которые проект запрещает: «Сучасне рішення для повсякденних і професійних завдань», «Продумана функціональність», «Стабільна робота», «Сучасні можливості». Если фолбэк публикуется, `audit_human_copy` пометит его. Swap test он не проходит.
- В общем блоке `_prompt` (pipeline.py:3859) осталось "8px or 999px for badges", хотя ARTLINE_STANDARD требует "never pills". Это дизайн, не копия, но модель получает две противоположные инструкции.
