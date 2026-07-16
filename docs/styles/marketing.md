# ARTLINE — маркетинговий стиль rich-контенту

Готові до копіювання блоки для **ручного** створення стилю: відкрий **Стилі → + Новий стиль** і встав кожен блок у відповідне поле. Промпти навмисно англійською — саме так їх споживає модель; мова готового контенту й далі керується налаштуванням проєкту.

---

## Що змінено (аналіз)

**Поточний базовий стиль сильний у своїй основі:** факти лише з Product JSON, цілісна дизайн-система, система «острівців», строга структура з 6 секцій, контроль контрасту й доступності, корисний SEO/GEO-текст. Це збережено повністю.

**Чого бракувало для маркетингу:** текстові інструкції були нейтрально-інформаційними («опиши характеристику»), а промпти для фото — точними, але не «бажаними» (product-accurate, але не aspirational). Тобто сторінка інформувала, але слабо *продавала*.

**Що додано в маркетингову версію:**

- Окремий шар **Brand Voice & Marketing**: benefit-first (спершу вигода для покупця, потім факт-доказ), звернення на «ти/ви», зняття заперечень, впевнене закриття рішення.
- Кожна характеристика перетворюється на **відчутну вигоду** («і що це мені дає?»).
- Hero став **обіцянкою результату**, а не просто назвою; Feature — **міні-історією» головної переваги.
- Фото-промпти зроблено **преміальнішими й бажанішими** (редакційне commercial-освітлення, статусне середовище) — але з незмінним правилом недоторканності реального товару.
- **Жодного хайпу**: бренд забороняє вигадані «найкращий/революційний», гарантії, нагороди, порівняння. Впевненість будується на фактах, а не на прикметниках. Це збережено як запобіжник.

> Порада: збережи цей стиль окремим (напр. `ARTLINE Marketing`), а `ARTLINE Base` лиши як запасний. Так зможеш порівняти обидва на реальному товарі.

---

## Поле «Назва»

```
ARTLINE Marketing
```

## Поле «Опис»

```
Маркетингова версія базового стилю ARTLINE: продає чесно — перетворює підтверджені факти на відчутну вигоду, з преміальними product-in-use зображеннями. Без хайпу й вигаданих переваг.
```

---

## Поле «Єдиний Style Prompt»

```
Create production-ready, premium, conversion-focused ecommerce rich content that feels native to artline.ua and belongs to one coherent ARTLINE design system. The page must sell the product honestly: turn confirmed facts into value the buyer can feel, while staying visually restrained, credible and easy to read.

SUCCESS CRITERIA, IN THIS ORDER
1. Every visible claim is factually supported by the current Product JSON.
2. Within the first screen the buyer feels "this is for me, and here is why it is worth it".
3. Every section moves the buyer one concrete step closer to a confident decision.
4. The page is visually modern, restrained, readable and consistent from the first section to the last.
5. The copy is useful for human buyers, search engines and generative answer engines without keyword stuffing.
6. Desktop and mobile express the same facts, the same voice and the same design language.

BRAND VOICE AND MARKETING
- Speak to the buyer, not only about the product: use natural second person ("you", "your") where the target language allows it.
- Benefit first, fact second: open each idea with the outcome the buyer wants, then prove it with a confirmed specification.
- Translate every specification into a felt, practical benefit — always answer "so what does this give me?".
- Sound confident, warm and expert. Respect the reader's intelligence and time; no filler, no clichés.
- Use concrete, specific, sensory language. Avoid vague adjectives and empty enthusiasm.
- Quietly pre-empt the buyer's likely hesitations by answering them with real facts.
- Create desire through clarity and credibility, never through exaggeration.
- Never invent superlatives, guarantees, awards, rankings, ratings, popularity or comparisons. Confidence must come from facts, not from words like "best", "unmatched" or "revolutionary".

SOURCE OF TRUTH
- Use only the current Product JSON, current project assets and explicitly supplied project data.
- Never invent specifications, compatibility, materials, ports, accessories, certifications, software, benchmarks, warranty, delivery, prices, service conditions, safety claims or package contents.
- If a fact is absent or ambiguous, omit it.
- Convert confirmed specifications into practical buyer value, but never present an inference as a confirmed fact.
- If confirmed facts are too few to fill a fixed element count, reframe genuine facts into distinct practical angles instead of inventing new specifications; never fabricate to reach a required count.
- Keep official brand names, model IDs, technology names, numbers and units unchanged.

NEVER DESCRIBE THE PAGE OR THE IMAGES
- Write only about the product and what the buyer does with it. The page is the message, never the subject.
- Never mention, describe or refer to the images in visible copy. Forbidden: "on the photo", "the image shows", "pictured above", "this close-up", "this is not a diagram", "as shown", "the photograph helps". Images are displayed, not explained. The copy must still make complete sense if every image were removed.
- Never narrate the page or its structure. Forbidden: "below you will find", "in this section", "here are typical scenarios", "the following facts", "this block shows", "this is a practical hint".
- Never restate these instructions, the task, the section purpose or the generation process in visible copy.
- Every heading names a product capability, benefit or buyer outcome — never a page element. Headings such as "Detailed product sample", "What the image shows", "About this block" are forbidden.
- Every sentence must be specific to THIS product. If a sentence would be equally true for any other product in any category, delete it or replace it with a confirmed product fact.
- If the Product JSON has too few facts to fill a section meaningfully, write fewer and shorter sentences that are still about the product — never pad with image descriptions, page narration or generic filler.

LANGUAGE CONTRACT
- Write every visible sentence only in the target language supplied by the project.
- Do not mix languages. Product names, model IDs, interfaces and official technology names may remain unchanged.
- The HTML structure, section order, image URLs, inline CSS and visual hierarchy must remain identical across language versions of the same viewport.
- Write natural, native marketing copy, not literal machine translation.
- Do not add language names, locale codes, translation notes or other system captions to the visible page.

SEO AND GENERATIVE-ENGINE VALUE
- Never use h1. The host product page already owns the document-level h1.
- Use one descriptive h2 for each major section and concise h3 headings for cards or list items.
- Mention the exact product brand and model naturally in the Hero and final summary.
- State the product category, primary purpose and strongest confirmed differentiator early in the page.
- Prefer answer-first paragraphs framed as buyer benefits: begin with the useful conclusion, then support it with the confirmed fact.
- Answer the buyer's real questions inside the existing sections: what it is, the main benefit, important confirmed features, who it suits and what to consider before choosing it.
- Use concrete nouns and complete factual sentences that stay understandable when quoted outside the page.
- Do not repeat the same keyword, product name, claim or sentence unnaturally.
- Each section must contribute new information; never reuse the same sentence, benefit, specification or paragraph across sections.
- Do not create hidden SEO text, meta tags, schema markup, keyword lists, fake FAQs or unsupported comparisons.

HTML CONTRACT
- Return HTML only: exactly one complete root <section>...</section>.
- Use inline CSS only.
- Allowed elements: section, div, h2, h3, p, ul, li, img, strong, span.
- Never use h1, script, style, JavaScript, forms, buttons, prices, purchase links, tabs, accordions, video, SVG, base64 images, markdown or code fences.
- Use only absolute or current-project image URLs supplied in the request. Never invent URLs.
- Every <img> must include a concise descriptive alt attribute in the target language that names the product and what the image shows; never leave alt empty and never stuff keywords. Add loading="lazy" to every non-Hero image.
- Add the required HTML comment before every major section.
- Close every element and use box-sizing:border-box wherever dimensions or layout are set.
- Do not use media queries. Desktop and mobile are separate outputs.

ROOT
Desktop:
<section style="max-width:1240px;margin:0 auto;padding:0 14px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">

Mobile:
<section style="max-width:480px;margin:0 auto;padding:0 10px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">

Keep the root transparent. Never create a dark full-page canvas.

ARTLINE DESIGN SYSTEM
- At least 70% of the total page area must remain white, transparent or light.
- Primary text on light surfaces: #101010.
- Body and secondary text on light surfaces: #555555. Use #69737D only for small eyebrow labels or captions, never for paragraphs.
- Primary text on dark surfaces: #FFFFFF or #F7F8FA.
- Secondary text on dark surfaces: #D0D7DE or #AFB8C1.
- Primary accent: #19BCC9.
- Optional secondary accent: #51C48A or #01743A, used only when it clarifies information.
- Light surfaces: #FFFFFF and #F7F8FA. Border: #D0D7DE.
- Dark surfaces: #101010, #1A2128 and #252525.
- Use no more than two accent colors on one page.
- Use #19BCC9 only for compact badges, eyebrow labels, small key values and subtle borders.
- Never color long headings, subtitles or paragraphs turquoise, green, blue, purple or orange.
- Never sample arbitrary colors from product photography.
- Default dark gradient: linear-gradient(135deg,#1A2128 0%,#252525 58%,#35393F 100%).
- Default light gradient: linear-gradient(145deg,#FFFFFF 0%,#F7F8FA 100%).
- Main section and card radius: 12px. Badge/tag radius: 8px. Never use pill radius 999px.
- Prefer borders and whitespace over shadows. Never apply heavy shadows to every card.
- Keep spacing systematic: desktop section gap 22px, card gap 14-16px, card padding 22-24px, large-section padding 42-48px; mobile section gap 14px, card gap 12px, card padding 18-20px, section padding 22-24px 16px.

CONTENT ISLAND SYSTEM
- Build the page from clearly readable content islands, never loose text floating on the root canvas.
- Every meaningful text group belongs to a visible surface with deliberate padding, radius and separation.
- Use only three coordinated island types: 1) primary light island (background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px); 2) secondary soft island (background:#F7F8FA; same border and radius); 3) dark emphasis island (approved dark gradient, subtle rgba(25,188,201,.24) border, 12px radius).
- Maintain a visible 14-22px gap between islands. Cards in the same group have equal weight, padding and aligned content starts.
- Use subtle depth only where useful: box-shadow:0 10px 26px rgba(16,16,16,.06). Never a different shadow on every card.
- No borderless text columns, disconnected headings, or text touching an image without a containing surface.

TYPOGRAPHY
- Hero h2 desktop: 48-56px, line-height 1.02-1.08, weight 800-900. Hero h2 mobile: 32-36px.
- Section h2 desktop: 34-40px; mobile: 27-31px; line-height 1.08-1.2; weight 800-900.
- Card h3: 18-20px, line-height 1.25-1.35, weight 700-800.
- Body desktop: 16-17px, line-height 1.55-1.7. Body mobile: 14-16px, line-height 1.55-1.65.
- Limit paragraphs to 2-3 sentences and about 70 characters per line on desktop. Target roughly 350-600 words of visible copy across the whole page.
- Keep paragraphs punchy and skimmable. Avoid all-caps except short badges.

PAGE STRUCTURE
Create exactly six sections, in this order, and no others:
<!-- 1. HERO -->
<!-- 2. KEY BENEFITS -->
<!-- 3. CORE FEATURE -->
<!-- 4. USE SCENARIOS -->
<!-- 5. BUYER CONFIDENCE -->
<!-- 6. FINAL SUMMARY -->
Do not add a trust strip, banner, metadata, status, specification dump, fake testimonial, review, comparison, brand history, gallery or purchase block.

1. HERO — THE PROMISE
- Use the dedicated generated Hero asset as the full CSS background of the complete first section. The Hero image is the section canvas, not a separate element.
- Never insert the Hero asset as an <img>, separate column, card or side panel. Never split Hero into image and text columns. Use one continuous overlay gradient over the full background image.
- Place all Hero copy inside one compact translucent dark content island in the protected text-safe area.
- Hero copy island desktop: max-width:610px; padding:28px 30px; border-radius:12px; background:rgba(16,16,16,.74); border:1px solid rgba(255,255,255,.14); box-shadow:0 16px 34px rgba(0,0,0,.18).
- Hero copy island mobile: width:auto; padding:20px 18px; background:rgba(16,16,16,.82); keep it below the primary product silhouette. Use display:flex; flex-direction:column; justify-content:flex-end so the copy sits in the lower text-safe area instead of relying on a large fixed top padding.
- Include only: one compact brand/category badge, one h2, one concise value subtitle and one short supporting paragraph.
- The h2 is a benefit-led promise that keeps the exact brand/model and attaches one confirmed value. Pattern: "Exact brand/model — the confirmed outcome the buyer gains". Never rename the product or exaggerate.
- The first two text elements must make the buyer understand what it is and why its strongest confirmed value matters to them.
- Hero heading #FFFFFF; subtitle #F7F8FA; paragraph #D0D7DE. Accent color only for the compact badge.
- Desktop: min-height 540-580px; product on the right; text on the left; padding ~60px 46px; background-size:cover. Mobile: dedicated mobile Hero asset; product in the upper area; text below; min-height ~600px; background-size:cover.

2. KEY BENEFITS — WHY IT IS WORTH IT
- Use exactly six equal light content islands (desktop three columns, mobile one). Never render benefits as bare text columns.
- Each card: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:24px; box-shadow:0 10px 26px rgba(16,16,16,.06); box-sizing:border-box.
- Each card leads with one concrete confirmed value/specification, then a benefit-led h3, then one short sentence that turns the fact into what the buyer gains. The first line is factual, not a slogan.
- No icons, emoji, illustrations, dark cards, colored fills, decorative strips or repeated shadows.

3. CORE FEATURE — THE STANDOUT STORY
- The text of this section is about the FEATURE OF THE PRODUCT, never about the picture. Never comment on the image, its framing or its purpose, and never state what the image is or is not.
- The heading names the feature or its benefit (for example "Automatic filament change" or "Prints a full plate unattended") — never a caption about the image.
- Select the single strongest confirmed feature that most separates the product or defines its main value, and tell its short story: what it is, how it works in plain terms, and the practical result it unlocks for the buyer.
- Use the generated Feature asset exactly once. Outer secondary soft island (background:#F7F8FA; border:1px solid #D0D7DE; border-radius:12px; padding:44px). Desktop two columns: one white text island, one white image island; mobile stacks text then image.
- Text island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:28px. Image island uses the same surface language and padding:20-24px.
- The Feature image must support this exact feature, not repeat the Hero composition. If the feature cannot be shown without inventing internals, use an accurate product-focused close-up.

4. USE SCENARIOS — SEE YOURSELF SUCCEEDING
- One secondary soft outer island with one h2, one concise intro and exactly four white scenario islands (desktop two columns, mobile one). Bare text columns are forbidden.
- Each scenario places the buyer in a real context, names the task and the confirmed reason the product fits it. Make the reader picture the result. Do not repeat specifications verbatim or claim unsupported suitability.

5. BUYER CONFIDENCE — REMOVE THE DOUBT
- One coherent secondary soft outer island with a compact eyebrow, one h2, one short answer-first intro and exactly four equal white supporting islands (desktop two columns, mobile one). No unframed text rows.
- Address the real decision themes supported by data: configuration clarity, integration, ease of use, relevant compatibility, maintenance, or ARTLINE service only when explicitly confirmed. Frame each as reassurance backed by a fact.
- Never invent warranty periods, lowest prices, free delivery, operating systems, partnerships, installation or 24/7 support. If ARTLINE service facts are unavailable, stay product-focused and neutral rather than fabricating trust.

6. FINAL SUMMARY — CONFIDENT CLOSE
- One restrained dark centered emphasis island, related to the Hero copy island but spanning the section width. Include one compact badge, one h2, one short factual summary and exactly three small tags.
- Restate the exact brand/model and the three most decision-relevant confirmed ideas in a confident, decision-closing tone, without copying earlier sentences.
- No buttons, links, prices, purchase instructions or unsupported superlatives.

SYSTEM-TEXT EXCLUSIONS
Never show internal or technical labels (image URLs, Product JSON, "generated by AI", prompt, system, version, desktop, mobile, language code, section numbers, developer or validation notes, placeholder text). HTML comments are allowed but never become visible copy.

FINAL SELF-CHECK
- no sentence mentions, describes or explains an image; the copy reads correctly with every image removed;
- no sentence narrates the page, a section or these instructions; no heading names a page element;
- every sentence is specific to this exact product and could not be pasted onto a different product unchanged;
- exactly six sections in order; no h1; no extra section;
- Hero asset is the full CSS background and no Hero <img> exists; matching desktop/mobile Hero asset used; one compact translucent copy island; benefit-led promise with exact brand/model;
- every text group sits on a prescribed island; six benefit cards, four scenarios, four confidence items, three final tags;
- benefit-first copy that turns confirmed facts into buyer value; no invented claims, superlatives or comparisons; no repeated sentences;
- every visible <img> has descriptive alt; role-appropriate accessible colors; inline CSS only; all tags closed; production-ready HTML only.

Return production-ready HTML only.
```

---

## Поле «Промпт Hero»

```
INTENDED USE
Create a photorealistic, premium, aspirational ecommerce Hero background for an ARTLINE rich-content page by editing the supplied real product photograph. The image should make a buyer instantly want the product and picture the life it enables.

SCENE
Place the exact product in a credible, desirable, category-appropriate environment where a buyer would proudly use it. Infer the environment only from the verified product category and facts: for example a sleek modern workstation for a computer, a clean professional workshop for a 3D printer, an elevated home-office desk for a chair, or a technically credible, reassuring energy setup for an energy product. The setting should signal quality, capability and a successful outcome — without adding any unverified functionality.

SUBJECT
The supplied product is immutable and remains the unmistakable hero. Preserve its exact geometry, proportions, perspective, chassis, materials, colors, branding, labels, ports, controls, vents, lighting elements and every visible hardware detail. Change only the surrounding environment, overall lighting and natural contact shadows.

COMPOSITION
This image is used as a full-bleed CSS background with HTML text over it. For desktop, keep the complete product primarily on the right at ~38-46% of the canvas and reserve uncluttered, darker text-safe space on the left. For mobile, keep the complete product in the upper 45-55% and reserve a calm darker text-safe area below. Keep important product parts away from crop edges. Use realistic perspective, controlled premium commercial lighting with gentle depth and a refined mood, and restrained ARTLINE dark neutrals with at most a subtle #19BCC9 environmental accent. Aim for editorial, magazine-grade product photography that feels expensive but honest.

CONSTRAINTS
Photorealistic professional product photography. No text, letters, captions, logos added by the model, badges, panels, UI, people, hands, extra products, invented accessories, changed hardware, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, excessive glow, cheap or amateur snapshot look, flat dull lighting, or watermark. Do not isolate the product on an empty studio background unless no credible use environment can be created without invention.
```

---

## Поле «Промпт Feature»

```
INTENDED USE
Create a photorealistic, premium ARTLINE Feature image by editing the supplied real product photograph. The image must make the single strongest confirmed product feature look desirable and easy to understand — not repeat the Hero scene.

FEATURE STORY
Choose one visually explainable confirmed differentiator and build a focused, category-appropriate composition that makes this feature obvious and appealing through a credible close-up, angle, interaction context or restrained premium environment. Keep the product as the main subject and let the feature feel like a genuine reason to buy. If the feature cannot be shown accurately without exposing unseen internals or inventing functionality, use a truthful product-focused close-up that emphasizes the relevant visible area.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and all visible details. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product or an imaginary internal cutaway.

COMPOSITION
Use a clean, premium, editorial composition distinct from the Hero. The product or the relevant visible feature occupies about 60-75% of the frame, stays fully readable, and has controlled negative space with a sense of craftsmanship and quality. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the verified feature requires a darker credible setting. Lighting is refined and commercial, never flat or amateur.

CONSTRAINTS
Photorealistic professional product photography. No text, labels added by the model, captions, arrows, diagrams, UI, people, hands, duplicate products, invented accessories, unverified installations, fake internals, glow, smoke, particles, cheap snapshot look or watermark.
```

---

## Поле «Негативний промпт»

```
Do not create a new, approximate or similar product. Do not redraw, redesign, restyle, recolor, simplify, distort, duplicate, mirror or replace the supplied product. Do not alter geometry, proportions, perspective, materials, ports, controls, vents, labels, branding, logos or visible hardware. No invented accessories, cables, installations, internal components, specifications, text, letters, captions, badges, arrows, diagrams, UI, watermarks, people, hands, clutter, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, lens flares, excessive glow or completely black backgrounds. Avoid a cheap, dull, flat, low-contrast, amateur or generic stock look. Preserve the original product identity exactly. If accurate preservation or a truthful visual explanation is not possible, keep the original product and make only minimal environment, framing and lighting changes.
```

---

## Порада щодо запуску

1. Створи стиль з полів вище, признач його для тестового товару й згенеруй.
2. Порівняй з `ARTLINE Base` на 2-3 різних категоріях (ПК, енергетика, 3D-принтер).
3. Якщо десь бракує «продажності» — підсилюй у полі **Опис бажаного результату** через AI-генератор або точково правь Style Prompt: секції 1 (Hero-обіцянка), 3 (Feature-історія) і 5 (зняття заперечень) дають найбільший ефект.
