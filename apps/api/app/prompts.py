"""Managed ARTLINE prompt set.

Keep the fixed production contract here and let user-created styles add only
category-specific art direction. The built-in ARTLINE Base style is updated
from these constants during application startup.
"""

BASE_STYLE_VERSION = "11.7"
BASE_STYLE_NAME = "ARTLINE Base"

DEFAULT_STYLE_PROMPT = r'''Create production-ready premium ecommerce rich content that feels native to artline.ua and belongs to one coherent ARTLINE design system.

SUCCESS CRITERIA, IN THIS ORDER
1. Every statement is factually supported by the current Product JSON.
2. The buyer immediately understands what the product is, who it is for and why its confirmed characteristics matter.
3. The page is visually modern, restrained, readable and consistent from the first section to the last.
4. The copy is useful for human buyers, search engines and generative answer engines without keyword stuffing.
5. Desktop and mobile express the same facts and design language while using layouts appropriate to each viewport.

SOURCE OF TRUTH
- Use only the current Product JSON, current project assets and explicitly supplied project data.
- Never invent specifications, compatibility, materials, ports, accessories, certifications, software, benchmarks, warranty, delivery, prices, service conditions, safety claims or package contents.
- If a fact is absent or ambiguous, omit it.
- Convert confirmed specifications into practical buyer value, but never present an inference as a confirmed fact.
- Keep official brand names, model IDs, technology names, numbers and units unchanged.

LANGUAGE CONTRACT
- Write every visible sentence only in the target language supplied by the project.
- Do not mix languages. Product names, model IDs, interfaces and official technology names may remain unchanged.
- The HTML structure, section order, image URLs, inline CSS and visual hierarchy must remain identical across language versions of the same viewport.
- Write natural native ecommerce copy, not literal machine translation.
- Do not add language names, locale codes, translation notes or other system captions to the visible page.

SEO AND GENERATIVE-ENGINE VALUE
- Never use h1. The host product page already owns the document-level h1.
- Use one descriptive h2 for each major section and concise h3 headings for cards or list items.
- Mention the exact product brand and model naturally in the Hero and final summary.
- State the product category, primary purpose and strongest confirmed differentiator early in the page.
- Use concrete nouns and complete factual sentences that remain understandable when quoted outside the page.
- Answer the buyer's likely questions inside the existing sections: what it is, the main benefit, important confirmed features, suitable use cases and what to consider before choosing it.
- Prefer answer-first paragraphs: begin with the useful conclusion, then support it with the confirmed fact.
- Use related category and use-case terminology only where it is genuinely relevant.
- Do not repeat the same keyword, product name, claim or sentence unnaturally.
- Do not create hidden SEO text, meta tags, schema markup, keyword lists, fake FAQs or unsupported comparisons.

HTML CONTRACT
- Return HTML only: exactly one complete root <section>...</section>.
- Use inline CSS only.
- Allowed elements: section, div, h2, h3, p, ul, li, img, strong, span.
- Never use h1, script, style, JavaScript, forms, buttons, prices, purchase links, tabs, accordions, video, SVG, base64 images, markdown or code fences.
- Use only absolute or current-project image URLs supplied in the request. Never invent URLs.
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
- Secondary text on light surfaces: #555555 or #69737D.
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
- The page must be built from clearly readable content islands, not loose text floating directly on the root canvas.
- Every meaningful text group must belong to a visible surface with deliberate padding, radius and separation from neighboring content.
- Use only three coordinated island types across the page:
  1. Primary light island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px.
  2. Secondary soft island: background:#F7F8FA; border:1px solid #D0D7DE; border-radius:12px.
  3. Dark emphasis island: the approved dark gradient with a subtle rgba(25,188,201,.24) border and 12px radius.
- Maintain a visible 14-22px gap between islands. Never place independent columns of text on a blank white background without their own surface.
- A section may have one outer island and a small number of equal inner cards, but avoid excessive card-within-card nesting.
- Cards within the same group must have equal visual weight, equal padding and aligned content starts.
- Use subtle depth only where useful: box-shadow:0 10px 26px rgba(16,16,16,.06). Do not apply heavy shadows or a different shadow to every card.
- Avoid huge empty white gaps. The next island should begin after the prescribed section gap.
- Do not create borderless text columns, disconnected headings, or text that visually touches an image without a containing surface.

TYPOGRAPHY
- Hero h2 desktop: 48-56px, line-height 1.02-1.08, weight 800-900.
- Hero h2 mobile: 32-36px, line-height 1.05-1.12, weight 800-900.
- Section h2 desktop: 34-40px; mobile: 27-31px; line-height 1.08-1.2; weight 800-900.
- Card h3: 18-20px, line-height 1.25-1.35, weight 700-800.
- Body desktop: 16-17px, line-height 1.55-1.7. Body mobile: 14-16px, line-height 1.55-1.65.
- Keep paragraphs concise and readable. Avoid all-caps except short badges.

PAGE STRUCTURE
Create exactly six sections, in this order, and no others:
<!-- 1. HERO -->
<!-- 2. KEY BENEFITS -->
<!-- 3. CORE FEATURE -->
<!-- 4. USE SCENARIOS -->
<!-- 5. BUYER CONFIDENCE -->
<!-- 6. FINAL SUMMARY -->

Do not add a trust strip, system banner, project metadata, generation status, technical prompt label, specification dump, fake testimonial, review, comparison, brand history, gallery or purchase block.

1. HERO — PRODUCT IN A REAL USE ENVIRONMENT
- Use the dedicated generated Hero asset as the full CSS background of the complete first section.
- The Hero image is the section canvas, not a separate content element.
- Never insert the Hero asset as an <img>, separate column, card or right-side panel.
- Never use grid-template-columns inside Hero and never split Hero into an image column and a text column.
- Use one continuous overlay gradient over the full background image.
- Place all Hero copy inside one compact translucent dark content island in the protected text-safe area. The island must improve readability while preserving the environmental image around it.
- Hero copy island desktop: max-width:610px; padding:28px 30px; border-radius:12px; background:rgba(16,16,16,.74); border:1px solid rgba(255,255,255,.14); box-shadow:0 16px 34px rgba(0,0,0,.18).
- Hero copy island mobile: width:auto; padding:20px 18px; background:rgba(16,16,16,.82). Keep it below the primary product silhouette.
- Do not create a full-height opaque panel, hard 50/50 split or light rectangle over Hero.
- Include only: one compact brand/category badge, one h2, one concise value subtitle and one short supporting paragraph.
- The h2 may be slightly more marketing-oriented, but it must retain the exact brand/model and attach only a short value proposition supported by Product JSON. Pattern: “Exact brand/model — confirmed buyer value”. Never rename the product or exaggerate.
- State what the product is and its strongest confirmed value in the first two text elements.
- Hero heading is #FFFFFF; subtitle #F7F8FA; paragraph #D0D7DE. Accent color is reserved for the compact badge.
- Desktop: min-height 540-580px; product on the right; text on the left; padding approximately 60px 46px; background-size:cover.
- Mobile: use the dedicated mobile Hero asset; product in the upper area; text below the main silhouette; min-height approximately 600px; padding approximately 320px 18px 26px; background-size:cover.

2. KEY BENEFITS — WHY THIS PRODUCT MATTERS
- Use exactly six equal light content islands. Every benefit must have its own visible card; never render benefits as bare text columns.
- Desktop: three columns. Mobile: one column.
- Each card: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:24px; box-shadow:0 10px 26px rgba(16,16,16,.06); box-sizing:border-box.
- Each card contains one concrete confirmed value/specification, one benefit-led h3 and one short explanatory paragraph.
- The first line is factual, not an abstract slogan.
- Do not use icons, emoji, illustrations, dark cards, colored card fills, decorative strips or repeated shadows.

3. CORE FEATURE — THE STRONGEST DIFFERENTIATOR
- Select the single strongest confirmed feature that meaningfully separates the product or defines its main customer value.
- Use the generated Feature asset exactly once.
- Use one balanced secondary soft outer island: background:#F7F8FA; border:1px solid #D0D7DE; border-radius:12px; padding:44px.
- Desktop uses a two-column layout with two coordinated inner islands: one white text island and one white image island. Mobile stacks the same islands with text first and image second.
- Text island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:28px. Image island uses the same surface language and padding:20-24px.
- Explain: what the feature is, how it works at a buyer-understandable level and what practical result it provides.
- The Feature image must visually support this exact feature, not merely repeat the Hero composition.
- If the main feature cannot be depicted without inventing internals or functionality, use an accurate product-focused close-up instead.

4. USE SCENARIOS — WHO IT IS FOR
- Use one secondary soft outer island with one descriptive h2, one concise introduction and exactly four white scenario islands.
- Desktop: two columns. Mobile: one column.
- Each scenario island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:22px. Bare text columns are forbidden.
- Each scenario names a real context, the relevant task and the confirmed reason the product fits it.
- Do not repeat specifications verbatim and do not claim suitability unsupported by the product data.

5. BUYER CONFIDENCE — WHAT TO CONSIDER
- Create one coherent secondary soft outer island with a compact eyebrow, one h2, one short answer-first introduction and exactly four equal white supporting islands below.
- Desktop supporting grid: two equal columns. Mobile: one column.
- Every supporting item must use background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:22px. Do not output unframed text rows.
- Do not use an oversized dark panel beside smaller cards and do not create an asymmetrical split layout.
- Cover useful decision themes supported by data: configuration clarity, integration, ease of use, relevant compatibility, maintenance or ARTLINE service only when explicitly confirmed.
- Never invent warranty periods, lowest prices, free delivery, operating systems, official partnerships, installation or 24/7 support.
- If ARTLINE-specific service facts are unavailable, keep the section product-focused and neutral rather than fabricating trust claims.

6. FINAL SUMMARY — DECISION RECAP
- Use one restrained dark centered emphasis island, visually related to the Hero copy island but spanning the section width.
- Include one compact badge, one h2, one short factual summary and exactly three small tags.
- Restate the exact brand/model and the three most decision-relevant confirmed ideas without copying earlier sentences.
- No buttons, links, prices, purchase instructions or unsupported superlatives.

SYSTEM-TEXT EXCLUSIONS
Never show internal or technical labels such as:
- PROJECT_HERO_IMAGE_URL, PROJECT_FEATURE_IMAGE_URL;
- Product JSON, source data, generated by AI, prompt, system, version, desktop, mobile, language code;
- section numbers, developer notes, validation notes or placeholder text.
HTML comments are allowed but must never become visible copy.

FINAL SELF-CHECK
- exactly six sections in the required order;
- no h1 and no extra major section;
- Hero asset is the full CSS background of the first section and no Hero <img> exists;
- dedicated desktop/mobile Hero asset is used for its matching viewport;
- Hero shows no separate image column and uses one compact translucent copy island;
- no meaningful text group floats directly on a blank root canvas;
- benefit, feature, scenario and buyer-confidence copy uses the prescribed coordinated islands;
- exact product brand/model is retained even when the Hero title is marketing-oriented;
- Feature section and Feature asset focus on the strongest confirmed differentiator;
- six benefit cards, four scenarios, four buyer-confidence items and three final tags;
- every visible sentence is in the requested language and no system label is visible;
- headings and paragraphs use role-appropriate accessible colors;
- factual, useful, non-repetitive SEO/GEO copy without keyword stuffing;
- only current-project images and confirmed product facts;
- inline CSS only, all tags closed and production-ready HTML only.

Return production-ready HTML only.'''

DEFAULT_HERO_PROMPT = r'''INTENDED USE
Create a photorealistic premium ecommerce Hero background for an ARTLINE rich-content page by editing the supplied real product photograph.

SCENE
Place the exact product in a credible, category-appropriate environment where a buyer would naturally use it. Infer the environment only from the verified product category and facts supplied with the request: for example a clean workstation for a computer, a real workshop for a 3D printer, an ergonomic desk setup for a chair, or a technically credible energy environment for an energy product. The environment must explain the product's purpose without adding unverified functionality.

SUBJECT
The supplied product is immutable and remains the unmistakable hero. Preserve its exact geometry, proportions, perspective, chassis, materials, colors, branding, labels, ports, controls, vents, lighting elements and every visible hardware detail. Change only the surrounding environment, overall lighting and natural contact shadows.

COMPOSITION
This image will be used as a full-bleed CSS background with HTML text over it. For desktop, keep the complete product primarily on the right at approximately 38-46% of the canvas and reserve uncluttered, darker text-safe space on the left. For mobile, keep the complete product in the upper 45-55% and reserve a calm darker text-safe area below. Keep important product parts away from crop edges. Use realistic perspective, controlled commercial lighting and restrained ARTLINE dark neutrals with at most a subtle #19BCC9 environmental accent.

CONSTRAINTS
Photorealistic professional product photography. No text, letters, captions, logos added by the model, badges, panels, UI, people, hands, extra products, invented accessories, changed hardware, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, excessive glow or watermark. Do not isolate the product on an empty studio background unless no credible use environment can be created without invention.'''

DEFAULT_FEATURE_PROMPT = r'''INTENDED USE
Create a photorealistic premium ARTLINE Feature image by editing the supplied real product photograph. The image must communicate the single strongest confirmed product feature supplied in the verified facts, not repeat the Hero scene.

FEATURE STORY
Choose one visually explainable confirmed differentiator. Build a focused category-appropriate composition that makes this feature easier to understand through a credible close-up, angle, interaction context or restrained environment. Keep the product as the main subject. If the feature cannot be shown accurately without exposing unseen internals or inventing functionality, use a truthful product-focused close-up that emphasizes the relevant visible area instead.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and all visible details. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product or an imaginary internal cutaway.

COMPOSITION
Use a clean premium editorial composition distinct from Hero. The product or relevant visible feature occupies about 60-75% of the frame, remains fully readable and has controlled negative space. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the verified feature requires a darker credible setting.

CONSTRAINTS
Photorealistic professional product photography. No text, labels added by the model, captions, arrows, diagrams, UI, people, hands, duplicate products, invented accessories, unverified installations, fake internals, glow, smoke, particles or watermark.'''

DEFAULT_NEGATIVE_PROMPT = r'''Do not create a new, approximate or similar product. Do not redraw, redesign, restyle, recolor, simplify, distort, duplicate, mirror or replace the supplied product. Do not alter geometry, proportions, perspective, materials, ports, controls, vents, labels, branding, logos or visible hardware. No invented accessories, cables, installations, internal components, specifications, text, letters, captions, badges, arrows, diagrams, UI, watermarks, people, hands, clutter, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, lens flares, excessive glow or completely black backgrounds. Preserve the original product identity exactly. If accurate preservation or a truthful visual explanation is not possible, keep the original product and make only minimal environment, framing and lighting changes.'''
