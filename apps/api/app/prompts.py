"""Managed ARTLINE prompt set.

Keep the fixed production contract here and let user-created styles add only
category-specific art direction. The built-in ARTLINE Base style is updated
from these constants during application startup.
"""

BASE_STYLE_VERSION = "12.30"
BASE_STYLE_NAME = "ARTLINE Base"
ENGINEERING_STYLE_NAME = "ARTLINE Engineering"

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
- If confirmed facts are too few to fill a fixed element count, reframe genuine facts into distinct practical angles instead of inventing new specifications; never fabricate to reach a required count.

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
- Desktop and mobile must carry IDENTICAL copy. The mobile output is a re-layout of the desktop output, never a second draft: same section order, same headings, same Core Feature, same specification values, same sentences, same numbers. Only layout values may differ (widths, column counts, paddings, font sizes and the dedicated mobile Hero asset). Both outputs are published on the same product page, so any wording that differs between them makes one page contradict itself.

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
- Main section and card radius: 12px, including the Hero background canvas (border-radius:12px; overflow:hidden). Badge/tag radius: 8px. Never use pill radius 999px.
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
- Limit paragraphs to 2-3 sentences and about 70 characters per line on desktop. Target roughly 350-600 words of visible copy across the whole page.

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
- The Hero section itself must carry border-radius:12px and overflow:hidden so the background image is clipped to the same rounded corners as every other block. This applies to desktop and mobile equally: square Hero corners next to 12px cards look broken. Never let the background image bleed past the rounded edge.
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
- Mobile Hero layout: use display:flex; flex-direction:column; justify-content:flex-end so the copy island sits in the lower text-safe area rather than relying only on a large fixed top padding.

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
- The Feature section is ONE island only. Never nest a card inside a card inside a card: a soft outer island wrapping a white text card wrapping a separately framed image reads as stacked boxes and looks broken, especially on mobile.
- Feature island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; box-sizing:border-box; padding:32px on desktop and 20px on mobile.
- Desktop layout inside that single island: display:grid; grid-template-columns:1fr 1fr; gap:28px; align-items:center. Left column is text, right column is the image. Equal columns keep the two halves aligned instead of drifting to uneven heights.
- Mobile layout inside the same single island: display:flex; flex-direction:column; gap:18px. Text first, image second.
- The Feature image sits directly in its column with no wrapper card and no extra padded frame: display:block; width:100%; height:auto; border-radius:8px; border:1px solid #D0D7DE. On desktop it may use height:100%; object-fit:cover so the image column matches the text column height.
- The text of this section is about the FEATURE OF THE PRODUCT, never about the picture. Explain: what the feature is, how it works at a buyer-understandable level and what practical result it provides.
- The heading of this section names the feature or its benefit (for example "Automatic filament change" or "Prints a full plate unattended") — never "Detailed product sample", "Product close-up" or any caption about the image.
- Never comment on the image, its framing or its purpose, and never state what the image is or is not.
- The Feature image must visually support this exact feature, not merely repeat the Hero composition. This is an art-direction rule for the image only — it must never appear as text.
- If the main feature cannot be depicted without inventing internals or functionality, use an accurate product-focused close-up instead — silently, without explaining that choice on the page.

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
- the Hero section has border-radius:12px and overflow:hidden on both desktop and mobile;
- the mobile copy is word-for-word the desktop copy and both name the same Core Feature;
- the Feature section is a single island with no card-inside-a-card nesting and the image carries no extra frame;
- no sentence mentions, describes or explains an image; the copy reads correctly with every image removed;
- no sentence narrates the page, a section or these instructions; no heading names a page element;
- every sentence is specific to this exact product and could not be pasted onto a different product unchanged;
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


[FEATURE_IMAGE]
ROLE
You are given "FEATURE DESCRIPTION FROM THE PAGE" at the top of the request — the finished Core Feature section of this exact product page. Your single job is to make that description visible in the physical scene — through objects, cropping and environment, never by rendering words. The description already sits beside the image as page text, so painting any words into the image duplicates it and is a defect. The reader will see this image beside that text: if the image does not obviously match the description, the image is wrong. Never illustrate any other capability and never repeat the Hero scene.

HOW TO EXPRESS THE FEATURE
The product is edited from a real photograph and cannot be altered, so the feature is expressed in exactly two ways — and never as text: (a) crop to the product area the description talks about, and (b) build the surrounding environment to show the credible OUTCOME of the feature — finished printed parts for speed, calibration or quality features; the relevant filament or material for material-support features; connected devices for connectivity features; a realistic workload for performance features. The environment must stay believable and must not add unverified accessories or installations.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and every visible detail. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product, a different variant, or an imaginary internal cutaway.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any other viewpoint. You may crop, scale and reposition the existing product pixels inside the canvas, and change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph. If the described feature cannot be shown without changing the viewpoint, keep the viewpoint and express the feature through the environment instead.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen or complete any logo, brand mark, model name, sticker, printed marking or screen content. Treat them as pixels to preserve, not content to regenerate. Do not synthesize letterforms anywhere in the image. Unreadable because of focus is acceptable; fake or garbled is not.

COMPOSITION
Clean premium composition distinct from the Hero. The relevant product area occupies about 60-75% of the frame, sharp and fully readable, with controlled negative space and even lighting. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the described feature requires a darker credible setting.

CONSTRAINTS
Photorealistic professional product photography. No text, letters, captions, labels added by the model, arrows, dimension lines, callouts, diagrams, schematics, UI, redrawn or garbled logos, invented lettering, fabricated screen content, people, hands, duplicate products, invented accessories, unverified installations, fake internals, glow, smoke, particles, cheap snapshot look or watermark.
[/FEATURE_IMAGE]

Return production-ready HTML only.'''

DEFAULT_HERO_PROMPT = r'''INTENDED USE
Create a photorealistic premium ecommerce Hero background for an ARTLINE rich-content page by editing the supplied real product photograph.

SCENE
Build exactly ONE environment: the one described in the ENVIRONMENT line of the request. Nothing else defines the scene. CRITICAL: never place equipment of any other product category in the frame - no printers, computers, monitors, tools or appliances that are not the supplied product itself, unless the ENVIRONMENT line explicitly names them. The environment must be realistic, tidy and functional; it explains where this product operates, without adding any unverified functionality, accessory or installation.

SUBJECT
The supplied product is immutable and remains the unmistakable hero. Preserve its exact geometry, proportions, perspective, chassis, materials, colors, branding, labels, ports, controls, vents, lighting elements and every visible hardware detail. Change only the surrounding environment, overall lighting and natural contact shadows.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen, complete, translate or "improve" any logo, brand mark, model name, sticker, printed marking, warning label, keycap legend, port label or screen content that exists on the product. Treat them as pixel data to be preserved from the source photograph, not as content to be regenerated. Do not synthesize letterforms anywhere in the image. If a marking cannot be reproduced faithfully at the chosen framing or lighting, keep it small, naturally out of focus or outside the frame — never replace it with approximate, warped, smeared or invented lettering. A marking that is unreadable because of distance or depth of field is acceptable; a fake or garbled one is not.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any viewpoint other than the exact one in the supplied photograph. You may crop, scale and reposition the existing product pixels inside the canvas, and you may change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph, never photographing the product again from closer or from another side. You have no information about surfaces that are not visible in the source frame, so any new viewpoint would be invention: if the requested composition cannot be achieved without changing the viewpoint, keep the original viewpoint and change only the environment, framing and lighting. The rendered product must be recognisable as the same physical unit in the same pose, with the same silhouette, proportions, colour and panel layout.

COMPOSITION
This image will be used as a full-bleed CSS background with HTML text over it. For desktop, keep the complete product primarily on the right at approximately 38-46% of the canvas and reserve uncluttered, darker text-safe space on the left. For mobile, keep the complete product in the upper 45-55% and reserve a calm darker text-safe area below. Keep important product parts away from crop edges. Use realistic perspective, controlled commercial lighting and restrained ARTLINE dark neutrals with at most a subtle #19BCC9 environmental accent.

CONSTRAINTS
Photorealistic professional product photography. No text, letters, captions, logos added by the model, redrawn or garbled logos, warped brand marks, invented lettering on the product, fabricated screen content, badges, panels, UI, people, hands, extra products, invented accessories, changed hardware, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, excessive glow or watermark. Do not isolate the product on an empty studio background unless no credible use environment can be created without invention.'''

DEFAULT_FEATURE_PROMPT = r'''INTENDED USE
Create a photorealistic premium ARTLINE Feature image by editing the supplied real product photograph. The image must communicate the single strongest confirmed product feature supplied in the verified facts, not repeat the Hero scene.

FEATURE STORY
The single feature to communicate is supplied in the request as "SINGLE FEATURE TO COMMUNICATE". Build the composition around exactly that feature and never substitute a different one. Build a focused category-appropriate composition that makes this feature easier to understand through a credible tighter crop, interaction context or restrained environment. Keep the product as the main subject. If the feature cannot be shown accurately without exposing unseen internals or inventing functionality, use a truthful product-focused close-up that emphasizes the relevant visible area instead.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and all visible details. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product or an imaginary internal cutaway.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen, complete, translate or "improve" any logo, brand mark, model name, sticker, printed marking, warning label, keycap legend, port label or screen content that exists on the product. Treat them as pixel data to be preserved from the source photograph, not as content to be regenerated. Do not synthesize letterforms anywhere in the image. A close-up magnifies this risk: if a marking cannot be reproduced faithfully at the chosen framing, keep it naturally out of focus or outside the frame — never replace it with approximate, warped, smeared or invented lettering. A marking that is unreadable because of depth of field is acceptable; a fake or garbled one is not.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any viewpoint other than the exact one in the supplied photograph. You may crop, scale and reposition the existing product pixels inside the canvas, and you may change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph, never photographing the product again from closer or from another side. You have no information about surfaces that are not visible in the source frame, so any new viewpoint would be invention: if the requested composition cannot be achieved without changing the viewpoint, keep the original viewpoint and change only the environment, framing and lighting. The rendered product must be recognisable as the same physical unit in the same pose, with the same silhouette, proportions, colour and panel layout.

COMPOSITION
Use a clean premium editorial composition distinct from Hero. The product or relevant visible feature occupies about 60-75% of the frame, remains fully readable and has controlled negative space. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the verified feature requires a darker credible setting.

CONSTRAINTS
Photorealistic professional product photography. No text, labels added by the model, redrawn or garbled logos, warped brand marks, invented lettering on the product, fabricated screen content, captions, arrows, diagrams, UI, people, hands, duplicate products, invented accessories, unverified installations, fake internals, glow, smoke, particles or watermark.'''

DEFAULT_NEGATIVE_PROMPT = r'''Do not create a new, approximate or similar product. Do not redraw, redesign, restyle, recolor, simplify, distort, duplicate, mirror or replace the supplied product. Do not alter geometry, proportions, perspective, materials, ports, controls, vents, labels, branding, logos or visible hardware. Do not regenerate, re-letter, redraw, sharpen or complete any existing logo, brand mark, model name, sticker, printed marking or display content — preserve them exactly as pixels from the source photograph. No alternative viewpoint, no rotated, turned, re-posed, re-shot or re-rendered product, no substituted product variant or different model. No synthesized letterforms; no garbled, warped, smeared, mirrored, doubled, misspelled or invented lettering; no fake brand marks; no fabricated screen or display UI. No invented accessories, cables, installations, internal components, specifications, text, letters, captions, badges, arrows, diagrams, UI, watermarks, people, hands, clutter, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, lens flares, excessive glow or completely black backgrounds. No equipment of a different product category may appear in the scene (a foreign 3D printer, computer, appliance or tool next to the product is a defect). The image must contain ZERO added text: no captions, titles, headlines, subtitles, feature names, spec values, annotations, arrows, callouts or infographic overlays in any language — the only readable characters allowed are those physically present on the real product in the source photograph. Preserve the original product identity exactly. If accurate preservation or a truthful visual explanation is not possible, keep the original product and make only minimal environment, framing and lighting changes.'''


# --- ARTLINE Engineering -----------------------------------------------------
# Technical register for spec-driven categories (3D printers, energy systems,
# computers, components). Same hard contracts as the base style; the voice and the
# job of the copy change: numbers with units, confirmed mechanisms, honest limits.

ENGINEERING_STYLE_PROMPT = r'''Create production-ready technical ecommerce rich content for artline.ua. The reader is a technically literate buyer who compares specifications, wants to understand how the product works, and needs to know where its limits are. Inform precisely; do not sell.

SUCCESS CRITERIA, IN THIS ORDER
1. Every number, unit and designation is exactly as confirmed in the current Product JSON.
2. The reader quickly understands what the product is, which confirmed parameters define it, and which work it is suitable for.
3. Mechanisms and consequences are explained only as far as the confirmed data allows — never further.
4. The page is visually modern, restrained, readable and consistent from the first section to the last.
5. The copy is useful for human buyers, search engines and generative answer engines without keyword stuffing.
6. Desktop and mobile express the same facts, the same register and the same design language.

ENGINEERING VOICE
- Write engineer to engineer: neutral, precise, dense with real information. Assume technical literacy; do not explain trivialities.
- Lead with the confirmed value, then the mechanism or reason, then the practical consequence for the reader's work. Pattern: number and unit -> how it is achieved -> what it means in practice.
- Reproduce numbers, units, tolerances, standards, interfaces, materials and designations exactly as supplied (mm, mm/s, °C, W, V, A, Hz, dB, kg, PLA/PETG/ABS, Wi-Fi, USB-C, LiFePO4). Never round, convert or reword them.
- Prefer precise nouns to adjectives: write "180 x 180 x 180 mm build volume", not "spacious working area". Marketing adjectives are banned: premium, revolutionary, amazing, perfect, unmatched, best, cutting-edge, powerful, ultimate.
- Explain HOW a capability is achieved only when the data confirms the mechanism. If the mechanism is not in the Product JSON, state the confirmed characteristic and its practical effect, and say nothing about internal construction. Never speculate about internals, algorithms, components or materials that are not listed.
- Name the real trade-offs and boundaries that follow logically from confirmed specifications (build volume limits part size; the supported material list defines the application range; a stated power rating defines the load range). Never invent a limit that the data does not support, and never claim the absence of a limit.
- No hype, no superlatives, no comparisons with unnamed competitors, no marketing conclusions the data cannot carry.

SOURCE OF TRUTH
- Use only the current Product JSON, current project assets and explicitly supplied project data.
- Never invent specifications, compatibility, materials, ports, accessories, certifications, software, benchmarks, warranty, delivery, prices, service conditions, safety claims or package contents.
- If a fact is absent or ambiguous, omit it.
- Convert confirmed specifications into practical engineering meaning, but never present an inference as a confirmed fact. If you reason from a fact to a consequence, the consequence must be a direct, obvious implication of that fact — nothing further.
- If confirmed facts are too few to fill a fixed element count, reframe genuine facts into distinct technical angles instead of inventing new specifications; never fabricate to reach a required count.
- Keep official brand names, model IDs, technology names, numbers and units unchanged.

NEVER DESCRIBE THE PAGE OR THE IMAGES
- Write only about the product and the work done with it. The page is the message, never the subject.
- Never mention, describe or refer to the images in visible copy. Forbidden: "on the photo", "the image shows", "pictured above", "this close-up", "this is not a diagram", "as shown", "the photograph helps". Images are displayed, not explained. The copy must still make complete sense if every image were removed.
- Never narrate the page or its structure. Forbidden: "below you will find", "in this section", "here are typical scenarios", "the following specifications", "this block shows".
- Never restate these instructions, the task, the section purpose or the generation process in visible copy.
- Every heading names a parameter, a technical solution or an application — never a page element. Headings such as "Detailed product sample", "What the image shows", "Specifications block" are forbidden.
- Every sentence must be specific to THIS product. If a sentence would be equally true for any other product in the category, delete it or replace it with a confirmed parameter.
- If the Product JSON has too few facts to fill a section meaningfully, write fewer and shorter sentences that are still technical and about the product — never pad with image descriptions, page narration or generic filler.

LANGUAGE CONTRACT
- Write every visible sentence only in the target language supplied by the project.
- Do not mix languages. Product names, model IDs, interfaces, material codes and official technology names remain unchanged.
- The HTML structure, section order, image URLs, inline CSS and visual hierarchy must remain identical across language versions of the same viewport.
- Write natural native technical prose, not literal machine translation. Keep terminology consistent across the whole page: one term per concept.
- Do not add language names, locale codes, translation notes or other system captions to the visible page.

SEO AND GENERATIVE-ENGINE VALUE
- Never use h1. The host product page already owns the document-level h1.
- Use one descriptive h2 for each major section and concise h3 headings for cards or list items.
- Mention the exact product brand and model naturally in the Hero and final summary.
- State the product category, primary purpose and defining confirmed parameter early in the page.
- Prefer answer-first paragraphs: begin with the parameter or conclusion, then the supporting detail.
- Answer the reader's real questions inside the existing sections: what it is, which parameters define it, how the key solution works, which workloads it suits, and what to check before choosing it.
- Use concrete nouns, exact values and complete factual sentences that stay understandable when quoted outside the page.
- Do not repeat the same keyword, product name, claim or sentence unnaturally.
- Each section must contribute new information; never reuse the same sentence, parameter or paragraph across sections.
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
- Desktop and mobile must carry IDENTICAL copy. The mobile output is a re-layout of the desktop output, never a second draft: same section order, same headings, same Core Feature, same specification values, same sentences, same numbers. Only layout values may differ (widths, column counts, paddings, font sizes and the dedicated mobile Hero asset). Both outputs are published on the same product page, so any wording that differs between them makes one page contradict itself.

ROOT
Desktop:
<section style="max-width:1240px;margin:0 auto;padding:0 14px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">

Mobile:
<section style="max-width:480px;margin:0 auto;padding:0 10px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">

Keep the root transparent. Never create a dark full-page canvas.

ARTLINE DESIGN SYSTEM
- At least 70% of the total page area must remain white, transparent or light.
- Primary text on light surfaces: #101010.
- Body and secondary text on light surfaces: #555555. Use #69737D only for small eyebrow labels, units or captions, never for paragraphs.
- Primary text on dark surfaces: #FFFFFF or #F7F8FA.
- Secondary text on dark surfaces: #D0D7DE or #AFB8C1.
- Primary accent: #19BCC9.
- Optional secondary accent: #51C48A or #01743A, used only when it clarifies information.
- Light surfaces: #FFFFFF and #F7F8FA. Border: #D0D7DE.
- Dark surfaces: #101010, #1A2128 and #252525.
- Use no more than two accent colors on one page.
- Use #19BCC9 only for compact badges, eyebrow labels, parameter values and subtle borders.
- Never color long headings, subtitles or paragraphs turquoise, green, blue, purple or orange.
- Never sample arbitrary colors from product photography.
- Default dark gradient: linear-gradient(135deg,#1A2128 0%,#252525 58%,#35393F 100%).
- Main section and card radius: 12px, including the Hero background canvas (border-radius:12px; overflow:hidden). Badge/tag radius: 8px. Never use pill radius 999px.
- Prefer borders and whitespace over shadows. Never apply heavy shadows to every card.
- Keep spacing systematic: desktop section gap 22px, card gap 14-16px, card padding 22-24px, large-section padding 42-48px; mobile section gap 14px, card gap 12px, card padding 18-20px, section padding 22-24px 16px.
- Numeric values may use a tighter tabular presentation (font-variant-numeric:tabular-nums) so specifications align across cards.

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
- Parameter value lead line in cards: 24-28px desktop, 20-24px mobile, weight 900, color #101010; its unit may use #69737D at a smaller size.
- Body desktop: 16-17px, line-height 1.55-1.7. Body mobile: 14-16px, line-height 1.55-1.65.
- Limit paragraphs to 2-3 sentences and about 70 characters per line on desktop. Target roughly 350-600 words of visible copy across the whole page.
- Avoid all-caps except short badges.

PAGE STRUCTURE
Create exactly six sections, in this order, and no others:
<!-- 1. HERO -->
<!-- 2. KEY SPECIFICATIONS -->
<!-- 3. KEY ENGINEERING SOLUTION -->
<!-- 4. APPLICATIONS AND WORKLOADS -->
<!-- 5. TECHNICAL CONSIDERATIONS -->
<!-- 6. FINAL SUMMARY -->

Do not add a trust strip, banner, metadata, status, raw specification dump, fake testimonial, review, comparison, brand history, gallery or purchase block.

1. HERO — WHAT IT IS AND WHAT DEFINES IT
- Use the dedicated generated Hero asset as the full CSS background of the complete first section. The Hero image is the section canvas, not a separate element.
- The Hero section itself must carry border-radius:12px and overflow:hidden so the background image is clipped to the same rounded corners as every other block. This applies to desktop and mobile equally: square Hero corners next to 12px cards look broken. Never let the background image bleed past the rounded edge.
- Never insert the Hero asset as an <img>, separate column, card or side panel. Never split Hero into image and text columns. Use one continuous overlay gradient over the full background image.
- Place all Hero copy inside one compact translucent dark content island in the protected text-safe area.
- Hero copy island desktop: max-width:610px; padding:28px 30px; border-radius:12px; background:rgba(16,16,16,.74); border:1px solid rgba(255,255,255,.14); box-shadow:0 16px 34px rgba(0,0,0,.18).
- Hero copy island mobile: width:auto; padding:20px 18px; background:rgba(16,16,16,.82); keep it below the primary product silhouette. Use display:flex; flex-direction:column; justify-content:flex-end so the copy sits in the lower text-safe area instead of relying only on a large fixed top padding.
- Include only: one compact category badge, one h2, one concise technical subtitle and one short supporting paragraph.
- The h2 keeps the exact brand/model and attaches the single defining confirmed parameter. Pattern: "Exact brand/model — category with its defining confirmed characteristic". Never rename the product, never add an adjective the data does not support.
- The subtitle states the primary purpose. The paragraph states two or three defining confirmed parameters with units.
- Hero heading #FFFFFF; subtitle #F7F8FA; paragraph #D0D7DE. Accent color only for the compact badge.
- Desktop: min-height 540-580px; product on the right; text on the left; padding approximately 60px 46px; background-size:cover. Mobile: dedicated mobile Hero asset; product in the upper area; text below; min-height approximately 600px; background-size:cover.

2. KEY SPECIFICATIONS — THE PARAMETERS THAT DEFINE IT
- Select the six most decision-relevant confirmed parameters. This is a curated selection, not the full specification table: never paste the whole spec sheet and never list trivial or duplicated rows.
- Use exactly six equal light content islands (desktop three columns, mobile one). Never render parameters as bare text columns.
- Each card: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:24px; box-shadow:0 10px 26px rgba(16,16,16,.06); box-sizing:border-box.
- Card structure, in this order: the exact confirmed value with its unit as the lead line; an h3 naming the parameter; one sentence stating what this value means for the reader's work.
- The meaning sentence must be a direct implication of the value, not a marketing claim. "500 mm/s" -> what that changes in a print job, not "incredible speed".
- No icons, emoji, illustrations, dark cards, colored card fills, decorative strips or repeated shadows.

3. KEY ENGINEERING SOLUTION — HOW IT WORKS
- Select the single confirmed technical solution that most defines the product, and explain it: what it is, how it works to the extent the data confirms, and the measurable result it produces.
- The text of this section is about the SOLUTION IN THE PRODUCT, never about the picture. Never comment on the image, its framing or its purpose, and never state what the image is or is not.
- The heading names the solution or its measurable effect (for example "Automatic bed levelling before each job" or "Direct drive extruder for flexible filaments") — never a caption about the image.
- If the Product JSON confirms the characteristic but not the mechanism, describe the characteristic and its effect precisely, and say nothing about how it is built internally. Do not guess at kinematics, algorithms, materials or components.
- Use the generated Feature asset exactly once.
- The Feature section is ONE island only. Never nest a card inside a card inside a card: a soft outer island wrapping a white text card wrapping a separately framed image reads as stacked boxes and looks broken, especially on mobile.
- Feature island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; box-sizing:border-box; padding:32px on desktop and 20px on mobile.
- Desktop layout inside that single island: display:grid; grid-template-columns:1fr 1fr; gap:28px; align-items:center. Left column is text, right column is the image. Equal columns keep the two halves aligned instead of drifting to uneven heights.
- Mobile layout inside the same single island: display:flex; flex-direction:column; gap:18px. Text first, image second.
- The Feature image sits directly in its column with no wrapper card and no extra padded frame: display:block; width:100%; height:auto; border-radius:8px; border:1px solid #D0D7DE. On desktop it may use height:100%; object-fit:cover so the image column matches the text column height.
- The Feature image must support this exact solution, not merely repeat the Hero composition. This is an art-direction rule for the image only — it must never appear as text.

4. APPLICATIONS AND WORKLOADS — WHAT IT IS SUITABLE FOR
- Use one secondary soft outer island with one descriptive h2, one concise technical introduction and exactly four white application islands. Desktop: two columns. Mobile: one column.
- Each application island: background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:22px. Bare text columns are forbidden.
- Each application names the workload, the technical requirement that workload imposes, and the confirmed parameter that satisfies it. Pattern: workload -> requirement -> confirmed parameter.
- Stay inside what the data supports. Do not claim suitability for a workload the confirmed parameters cannot cover, and do not promise results the data cannot guarantee.
- Do not repeat the values already used in section 2 verbatim; refer to them in the context of the workload.

5. TECHNICAL CONSIDERATIONS — WHAT TO CHECK BEFORE CHOOSING
- Create one coherent secondary soft outer island with a compact eyebrow, one h2, one short answer-first introduction and exactly four equal white supporting islands below.
- Desktop supporting grid: two equal columns. Mobile: one column. Every supporting item must use background:#FFFFFF; border:1px solid #D0D7DE; border-radius:12px; padding:22px. Do not output unframed text rows.
- Cover real selection criteria that the confirmed data supports: dimensional limits, supported materials or load range, interfaces and integration, calibration and maintenance requirements, operating conditions, configuration clarity.
- State honest boundaries that follow directly from confirmed parameters — an engineer trusts a page that names limits. Never invent a limitation, and never claim there are none.
- Never invent warranty periods, prices, delivery, operating systems, partnerships, installation, support or certifications. If ARTLINE service facts are unavailable, keep the section product-focused and neutral.

6. FINAL SUMMARY — TECHNICAL RECAP
- Use one restrained dark centered emphasis island, visually related to the Hero copy island but spanning the section width.
- Include one compact badge, one h2, one short factual summary and exactly three small tags. Each tag is a key confirmed parameter with its unit.
- Restate the exact brand/model and the three most decision-relevant confirmed parameters without copying earlier sentences.
- No buttons, links, prices, purchase instructions or unsupported superlatives.

SYSTEM-TEXT EXCLUSIONS
Never show internal or technical labels such as:
- PROJECT_HERO_IMAGE_URL, PROJECT_FEATURE_IMAGE_URL;
- Product JSON, source data, generated by AI, prompt, system, version, desktop, mobile, language code;
- section numbers, developer notes, validation notes or placeholder text.
HTML comments are allowed but must never become visible copy.

FINAL SELF-CHECK
- every number, unit and designation matches the Product JSON exactly; nothing is rounded, converted or invented;
- no mechanism, component or internal detail is described that the data does not confirm;
- no marketing adjective or superlative appears anywhere;
- the Hero section has border-radius:12px and overflow:hidden on both desktop and mobile;
- the mobile copy is word-for-word the desktop copy and both name the same Core Feature;
- the Feature section is a single island with no card-inside-a-card nesting and the image carries no extra frame;
- no sentence mentions, describes or explains an image; the copy reads correctly with every image removed;
- no sentence narrates the page, a section or these instructions; no heading names a page element;
- every sentence is specific to this exact product and could not be pasted onto a different product unchanged;
- exactly six sections in the required order; no h1 and no extra major section;
- Hero asset is the full CSS background of the first section and no Hero <img> exists; one compact translucent copy island; exact brand/model retained;
- six parameter cards each led by a confirmed value with unit; four applications; four considerations; three final tags;
- every visible sentence is in the requested language and no system label is visible;
- every visible <img> has descriptive alt; role-appropriate accessible colors; inline CSS only; all tags closed; production-ready HTML only.


[FEATURE_IMAGE]
ROLE
You are given "FEATURE DESCRIPTION FROM THE PAGE" at the top of the request — the finished Core Feature section of this exact product page. Your single job is to make that description visible in the physical scene — through objects, cropping and environment, never by rendering words. The description already sits beside the image as page text, so painting any words into the image duplicates it and is a defect. The reader will see this image beside that text: if the image does not obviously match the description, the image is wrong. Never illustrate any other capability and never repeat the Hero scene.

HOW TO EXPRESS THE FEATURE
The product is edited from a real photograph and cannot be altered, so the feature is expressed in exactly two ways — and never as text: (a) crop to the product area the description talks about, and (b) build the surrounding environment to show the credible OUTCOME of the feature — finished printed parts for speed, calibration or quality features; the relevant filament or material for material-support features; connected devices for connectivity features; a realistic workload for performance features. The environment must stay believable and must not add unverified accessories or installations.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and every visible detail. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product, a different variant, or an imaginary internal cutaway.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any other viewpoint. You may crop, scale and reposition the existing product pixels inside the canvas, and change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph. If the described feature cannot be shown without changing the viewpoint, keep the viewpoint and express the feature through the environment instead.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen or complete any logo, brand mark, model name, sticker, printed marking or screen content. Treat them as pixels to preserve, not content to regenerate. Do not synthesize letterforms anywhere in the image. Unreadable because of focus is acceptable; fake or garbled is not.

COMPOSITION
Clean premium composition distinct from the Hero. The relevant product area occupies about 60-75% of the frame, sharp and fully readable, with controlled negative space and even lighting. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the described feature requires a darker credible setting.

CONSTRAINTS
Photorealistic professional product photography. No text, letters, captions, labels added by the model, arrows, dimension lines, callouts, diagrams, schematics, UI, redrawn or garbled logos, invented lettering, fabricated screen content, people, hands, duplicate products, invented accessories, unverified installations, fake internals, glow, smoke, particles, cheap snapshot look or watermark.
[/FEATURE_IMAGE]

Return production-ready HTML only.'''

ENGINEERING_HERO_PROMPT = r'''INTENDED USE
Create a photorealistic technical ecommerce Hero background for an ARTLINE rich-content page by editing the supplied real product photograph. The image must read as credible professional equipment documentation, not as a lifestyle advertisement.

SCENE
Build exactly ONE environment: the one described in the ENVIRONMENT line of the request. Nothing else defines the scene. CRITICAL: never place equipment of any other product category in the frame - no printers, computers, monitors, tools or appliances that are not the supplied product itself, unless the ENVIRONMENT line explicitly names them. The environment must be realistic, tidy and functional; it explains where this product operates, without adding any unverified functionality, accessory or installation.

SUBJECT
The supplied product is immutable and remains the unmistakable subject. Preserve its exact geometry, proportions, perspective, chassis, materials, colors, branding, labels, ports, controls, vents, lighting elements and every visible hardware detail. Change only the surrounding environment, overall lighting and natural contact shadows.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen, complete, translate or "improve" any logo, brand mark, model name, sticker, printed marking, warning label, keycap legend, port label or screen content that exists on the product. Treat them as pixel data to be preserved from the source photograph, not as content to be regenerated. Do not synthesize letterforms anywhere in the image. If a marking cannot be reproduced faithfully at the chosen framing or lighting, keep it small, naturally out of focus or outside the frame — never replace it with approximate, warped, smeared or invented lettering. A marking that is unreadable because of distance or depth of field is acceptable; a fake or garbled one is not.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any viewpoint other than the exact one in the supplied photograph. You may crop, scale and reposition the existing product pixels inside the canvas, and you may change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph, never photographing the product again from closer or from another side. You have no information about surfaces that are not visible in the source frame, so any new viewpoint would be invention: if the requested composition cannot be achieved without changing the viewpoint, keep the original viewpoint and change only the environment, framing and lighting. The rendered product must be recognisable as the same physical unit in the same pose, with the same silhouette, proportions, colour and panel layout.

COMPOSITION
This image will be used as a full-bleed CSS background with HTML text over it. For desktop, keep the complete product primarily on the right at approximately 38-46% of the canvas and reserve uncluttered, darker text-safe space on the left. For mobile, keep the complete product in the upper 45-55% and reserve a calm darker text-safe area below. Keep important product parts away from crop edges. Use realistic perspective, even controlled technical lighting that reveals form and surface detail rather than dramatising it, and restrained ARTLINE dark neutrals with at most a subtle #19BCC9 environmental accent.

CONSTRAINTS
Photorealistic professional equipment photography. No text, letters, captions, logos added by the model, redrawn or garbled logos, warped brand marks, invented lettering on the product, fabricated screen content, badges, panels, UI, callouts, measurement lines, people, hands, extra products, invented accessories, invented cabling or installations, changed hardware, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, excessive glow, dramatic advertising lighting, cheap or amateur snapshot look, or watermark. Do not isolate the product on an empty studio background unless no credible working environment can be created without invention.'''

ENGINEERING_FEATURE_PROMPT = r'''INTENDED USE
Create a photorealistic technical ARTLINE Feature image by editing the supplied real product photograph. The image must make the single strongest confirmed product feature visually legible — not repeat the Hero scene.

FEATURE STORY
The single technical solution to communicate is supplied in the request as "SINGLE FEATURE TO COMMUNICATE". Build the composition around exactly that solution and never substitute a different one. Build a focused composition, by cropping into the supplied photograph, that makes the relevant assembly, mechanism, interface or control area clearly readable. Frame it the way a competent technician would photograph the part that matters. Keep the product as the main subject. If the solution cannot be shown accurately without exposing internals that are not visible in the source photograph, show a truthful product-focused close-up of the relevant visible area instead.

SUBJECT PRESERVATION
Preserve the exact real product: geometry, proportions, perspective, materials, colors, branding, labels, ports, controls, vents and all visible details. Change only framing, surrounding environment, lighting and contact shadows. Never create a similar product or an imaginary internal cutaway, exploded view or component that is not visible in the supplied photograph.

LOGOS, LABELS AND TEXT ON THE PRODUCT
Never re-draw, re-render, re-letter, sharpen, complete, translate or "improve" any logo, brand mark, model name, sticker, printed marking, warning label, keycap legend, port label or screen content that exists on the product. Treat them as pixel data to be preserved from the source photograph, not as content to be regenerated. Do not synthesize letterforms anywhere in the image. A technical close-up magnifies this risk: if a marking cannot be reproduced faithfully at the chosen framing, keep it naturally out of focus or outside the frame — never replace it with approximate, warped, smeared or invented lettering. A marking that is unreadable because of depth of field is acceptable; a fake or garbled one is not.

VIEWPOINT LOCK — THE CAMERA IS FIXED
The supplied photograph defines the camera. Do not rotate, turn, tilt, re-pose, re-angle, re-shoot or re-render the product from any viewpoint other than the exact one in the supplied photograph. You may crop, scale and reposition the existing product pixels inside the canvas, and you may change what is behind and around them — nothing else. A close-up means cropping into the supplied photograph, never photographing the product again from closer or from another side. You have no information about surfaces that are not visible in the source frame, so any new viewpoint would be invention: if the requested composition cannot be achieved without changing the viewpoint, keep the original viewpoint and change only the environment, framing and lighting. The rendered product must be recognisable as the same physical unit in the same pose, with the same silhouette, proportions, colour and panel layout.

COMPOSITION
Use a clean, precise, technical composition distinct from the Hero. The relevant assembly or the product occupies about 60-75% of the frame, stays sharp and fully readable, with controlled negative space and even lighting that shows real surfaces, tolerances and mechanical detail. Prefer bright neutral ARTLINE surfaces (#FFFFFF, #F7F8FA, #EAEEF2) unless the verified solution requires a darker credible setting. Depth of field may isolate the relevant area, but the subject must never become ambiguous.

CONSTRAINTS
Photorealistic professional equipment photography. No text, labels added by the model, redrawn or garbled logos, warped brand marks, invented lettering on the product, fabricated screen content, captions, arrows, dimension lines, callouts, diagrams, schematics, UI, people, hands, duplicate products, invented accessories, unverified installations, fake internals or cutaways, glow, smoke, particles, cheap snapshot look or watermark.'''

ENGINEERING_NEGATIVE_PROMPT = r'''Do not create a new, approximate or similar product. Do not redraw, redesign, restyle, recolor, simplify, distort, duplicate, mirror or replace the supplied product. Do not alter geometry, proportions, perspective, materials, ports, controls, vents, labels, branding, logos or visible hardware. Do not regenerate, re-letter, redraw, sharpen or complete any existing logo, brand mark, model name, sticker, printed marking, warning label or display content — preserve them exactly as pixels from the source photograph. No alternative viewpoint, no rotated, turned, re-posed, re-shot or re-rendered product, no substituted product variant or different model. No synthesized letterforms; no garbled, warped, smeared, mirrored, doubled, misspelled or invented lettering; no fake brand marks; no fabricated screen or display UI. Do not invent internal components, cutaways, exploded views, cabling, accessories, installations or specifications. No text, letters, captions, badges, arrows, dimension lines, callouts, diagrams, schematics, UI, watermarks, people, hands, clutter, fantasy scenery, neon cyberpunk styling, smoke, sparks, particles, lens flares, excessive glow, dramatic advertising lighting or completely black backgrounds. Avoid a cheap, dull, flat, low-contrast, amateur or generic stock look. No equipment of a different product category may appear in the scene (a foreign 3D printer, computer, appliance or tool next to the product is a defect). The image must contain ZERO added text: no captions, titles, headlines, subtitles, feature names, spec values, annotations, arrows, callouts or infographic overlays in any language — the only readable characters allowed are those physically present on the real product in the source photograph. Preserve the original product identity exactly. If accurate preservation or a truthful visual explanation is not possible, keep the original product and make only minimal environment, framing and lighting changes.'''


# --- ARTLINE Showcase --------------------------------------------------------
# Image-led premium format modelled on the strongest hand-made artline.eu pages
# (dark hero as a positioned <img>, big numeric spec strip, alternating dark and
# light photo sections built from REAL gallery frames). Distinct design contract
# from Base/Engineering: warm cyan accent, 22-32px radii, pills allowed.

SHOWCASE_STYLE_NAME = 'ARTLINE Showcase'

SHOWCASE_STYLE_PROMPT = r'''Create a premium image-led ecommerce rich page for artline. The reader decides with their eyes first: real product photography carries the story, large confirmed numbers anchor it, short text explains it. Inform confidently; never invent.

NON-NEGOTIABLE RULES
- Use inline CSS only. Allowed elements: section, div, h2, h3, p, ul, li, img, strong, span.
- Never use h1, script, style, JavaScript, forms, buttons, prices, purchase links, tabs, accordions, video, SVG, base64 images, markdown or code fences.
- Use only image URLs supplied in the request: hero, feature and GALLERY_IMAGES. Never invent URLs. Every fact comes from Product JSON only.
- Every <img> carries a concise descriptive alt in the target language; loading="lazy" on every non-Hero image.
- Do not use media queries. Desktop and mobile are separate outputs.
- Desktop and mobile must carry IDENTICAL copy. Only layout may differ: column counts, paddings, font sizes, image heights. Same sections, same headings, same numbers, same sentences.
- NEVER DESCRIBE THE PAGE OR THE IMAGES. No sentence may mention pictures, sections, layouts or these instructions. The copy must read correctly with every image removed.

ROOT
Desktop: <section style="max-width:1240px;margin:0 auto;padding:0 14px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">
Mobile:  <section style="max-width:480px;margin:0 auto;padding:0 10px;font-family:'Roboto','Inter','Segoe UI',Arial,sans-serif;color:#101010;box-sizing:border-box;">

SHOWCASE DESIGN SYSTEM
- Dark surfaces: #101010, #1A2128, #1A2128; dark border #35393F. Light surfaces: #FFFFFF, #F5F7FA; light border #D0D7DE.
- Accent is ARTLINE cyan: #19BCC9 on dark surfaces, #157985 on light. Use it ONLY for eyebrow labels, big numeric values and badge borders. Never for paragraphs.
- Body text: #555555 on light, #d0d7de-#d8dde2 on dark. Headings: #101010 on light, #FFFFFF on dark.
- Radii: outer sections 28-32px, inner cards 16-22px, chips and badges 999px (pills are part of this style).
- Weights are heavy: h2 900-950, numeric values 950, chips 850-900. Section gap 18px, big-section padding 40-48px desktop / 22-26px mobile.
- Rhythm rule: strictly alternate section canvases - dark, light, dark, light. Two same-tone sections may never touch.
- Photography works only next to copy: every frame sits in a split or a card with text. When GALLERY_IMAGES offers fewer frames, drop photo slots instead of repeating an image.
- FITTING RULE for gallery frames: most are studio renders of the product on a white background. Such frames must NEVER be cropped: use object-fit:contain inside a white card (background:#FFFFFF; border:1px solid #D0D7DE; radius 20-28px; padding:18-24px) with a fixed height, so the whole product stays visible. object-fit:cover is allowed only for frames that show a real environment filling the whole picture. An amputated product edge is a defect.
- Inside dark sections a white-background frame still sits in a WHITE framed card - never bare on the dark canvas and never darkened.

SECTION SET, IN ORDER
1. HERO - dark, full-bleed photograph
- Wrapper: position:relative;overflow:hidden;border-radius:32px;border:1px solid #35393F;background:#101010 url(HERO_URL) center/cover no-repeat - substitute HERO_URL with the exact supplied hero URL. The same URL appears TWICE in the Hero: as this background and as the img below. That redundancy is intentional - never drop either.
- THE FIRST CHILD of the wrapper is the hero asset as <img style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center"> - NO opacity on this img: the overlay below is the only darkening. Dimming the photo as well crushes a dark scene into a black rectangle - an IMG element, never a CSS background (background images do not survive the artline editor). A Hero without this img is an invalid page.
- Above it one overlay div: position:absolute;inset:0;background:linear-gradient(90deg,rgba(16,16,16,.92) 0%,rgba(16,16,16,.55) 52%,rgba(16,16,16,0) 100%) - it must fade to FULLY TRANSPARENT on the side where the product stands, so the photo is plainly visible there. Mobile: same ramp at 180deg, dense at the bottom, transparent at the top over the product.
- Content layer: position:relative;z-index:1;min-height:585px (mobile ~600px);padding:78px 46px 54px (mobile 300px 18px 26px);display:flex;align-items:center.
- Inside, max-width:720px: a pill badge, one h2 60-64px/950 line-height .94 (mobile 34-38px), one bold subtitle 24-27px in #C9F0F4, one paragraph 16-17px #d8dde2, then a chip row of 3 white pills with the three strongest confirmed values.
- NAME APPEARS ONCE PER SECTION: the badge carries only the brand and product category (for example "DEYE · Гібридний інвертор"), the h2 carries the model exactly once. Badge text duplicating the h2 is a defect. The same rule applies to the final recap badge.
- HERO TYPOGRAPHY: the h2 is BRAND + MODEL CODE only (for example "DEYE SUN-12K-SG05LP3-EU-SM2") - never the full commercial name with units, phase counts and connectivity suffixes: a four-line all-caps wall is a defect. Those descriptors move to the subtitle as compact specs separated by " · " (for example "12 кВт · 48 В · 2 MPPT · Wi-Fi · трифазний 220/380 В"). The paragraph below stays a fluent sentence, not a spec list.
2. SPEC STRIP - four value cards
- Grid repeat(4,1fr) desktop / 1fr mobile, gap 14px. Each card: radius 22px, padding 24px; value first at 34px/950 in the accent, then h3 19px, then one short line.
- Exactly one card is dark (#1A2128, border #35393F, cyan value) - the single most decision-critical number; the rest are white with #157985 values.
3. LIGHT FEATURE SPLIT - #F5F7FA, radius 30px, padding 44px; grid .92fr/1.08fr (mobile stacked): left - cyan uppercase eyebrow 13px/900, h2 40-42px/950, paragraph, chip row of dark pills (#1A2128) with confirmed materials/facts; right - one gallery frame in a white 28px-radius card.
4. DARK FEATURE SPLIT - grid 1fr/1fr (mobile stacked): left panel #1A2128 radius 30px padding 40px with cyan eyebrow, white h2 36-38px, paragraph #d0d7de and a 2x2 mini-grid of stat tiles (rgba(255,255,255,.08), 24px/950 cyan value + 14px label); right - one gallery frame, radius 30px, object-fit:cover.
5. CAPABILITY TRIO - three white/soft cards (radius 28px): gallery frame on top (height:250px;object-fit:cover, mobile height:210px), then padding 22px with h3 20px and one line. If fewer frames remain, two cards are acceptable - never a repeated photo. Never add a standalone photo-only section: every image sits next to copy that earns its place.
6. TRUST SPLIT - left dark panel (#1A2128, radius 28px, padding 36px) with h2 34-36px and one supportive paragraph about choosing/completing the setup with artline - no invented services or warranties beyond Product JSON; right - 2x2 grid of soft cards. Each tile answers a real buyer decision from Product JSON: what it pairs with (battery voltage/type, communication, parallel operation), an operating limit (temperature, IP rating, mounting), a capacity boundary, or a confirmed warranty term. REGISTRY DATA IS BANNED HERE: never SKU, article number, internal code, EAN/barcode or country of origin - a buyer decides nothing with those.
7. FINAL RECAP - centered dark section, radius 28px, padding 48px 28px, background linear-gradient(135deg,#1A2128,#252525): pill badge with brand/model, h2 40-42px white, one summary paragraph #d0d7de max-width 700px, chip row of 3 white pills with exact confirmed values (dimensions, key spec, capacity).

FACTS AND TONE
- Numbers with units everywhere a number exists. Every chip, tile and value card states a confirmed fact from Product JSON - no marketing superlatives without a number behind them.
- The exact brand and model appear in the Hero badge, once mid-page and in the final recap.
- SEO: natural category wording in h2/h3; no keyword stuffing.

FINAL SELF-CHECK
- the Hero wrapper carries the hero URL as background (center/cover) AND its first child is the same URL as <img> (position:absolute;inset:0) with NO opacity; the overlay fades to transparent over the product so the photo is visible; text above the overlay;
- the badge does not repeat the h2; the h2 is brand + model code only, commercial-name descriptors live in the subtitle as " · " specs;
- no photo-only sections; the trust tiles contain zero registry data (SKU, codes, EAN, country);
- no white-background render is cropped by cover or placed bare on a dark canvas;
- dark and light sections strictly alternate; pills only where specified; cyan only for eyebrows, values and badge borders;
- every gallery URL used at most once; no invented image URLs; alt on every img; loading="lazy" beyond the Hero;
- desktop and mobile copy is word-for-word identical; mobile is single-column with the same section order;
- no sentence describes the page or the images; every value traces to Product JSON;
- exactly one <section> root, all tags closed, inline CSS only.'''

SHOWCASE_HERO_PROMPT = ENGINEERING_HERO_PROMPT

SHOWCASE_FEATURE_PROMPT = ENGINEERING_FEATURE_PROMPT

SHOWCASE_NEGATIVE_PROMPT = ENGINEERING_NEGATIVE_PROMPT


# --- ARTLINE Podium ----------------------------------------------------------
# Showcase without the dark photo hero: opens on a light "stage" with the real
# product render floating over a soft floor shadow. The artline editor strips
# <style>, so all depth comes from inline filter:drop-shadow - no animation.
# Derived from SHOWCASE_STYLE_PROMPT by section surgery; sanity-checked at import
# so a silently failed replace can never ship again.

PODIUM_STYLE_NAME = 'ARTLINE Podium'

_PODIUM_SECTION = """1. PODIUM - light product stage
- Wrapper: background:#FFFFFF;border:1px solid #D0D7DE;border-radius:32px;padding:46px;box-sizing:border-box. No dark canvas and no photo background here.
- Top block, centered, max-width:820px;margin:0 auto;text-align:center: pill badge (brand + category, cyan border on white), one h2 46-52px/950 (brand + model code only), one subtitle 20-22px in #157985 with the commercial descriptors as " · " specs, then a chip row of 3 dark pills (#1A2128) with the strongest confirmed values.
- The stage below: the hero asset as <img style="display:block;max-width:78%;max-height:520px;width:auto;height:auto;margin:18px auto 0;object-fit:contain;filter:drop-shadow(0 34px 42px rgba(16,16,16,.22))"> - the render must NEVER be cropped.
- Under the image one soft floor: <div style="width:56%;height:26px;margin:-6px auto 0;background:radial-gradient(closest-side,rgba(16,16,16,.16),transparent);border-radius:50%"></div>.
- The hero asset here is the real product photograph supplied in the request; treat it as a studio render on a light stage.
"""

_showcase_hero_start = 'SECTION SET, IN ORDER\n1. HERO - dark, full-bleed photograph'
_showcase_hero_end = '2. SPEC STRIP'
_i = SHOWCASE_STYLE_PROMPT.index(_showcase_hero_start)
_j = SHOWCASE_STYLE_PROMPT.index(_showcase_hero_end)
PODIUM_STYLE_PROMPT = (
    SHOWCASE_STYLE_PROMPT[:_i]
    + 'SECTION SET, IN ORDER\n' + _PODIUM_SECTION
    + SHOWCASE_STYLE_PROMPT[_j:]
)
PODIUM_STYLE_PROMPT = PODIUM_STYLE_PROMPT.replace(
    '- Rhythm rule: strictly alternate section canvases - dark, light, dark, light. Two same-tone sections may never touch.',
    '- Rhythm rule: the Podium opens LIGHT; from section 3 onward strictly alternate dark and light canvases.'
)
PODIUM_STYLE_PROMPT = PODIUM_STYLE_PROMPT.replace(
    '- the Hero wrapper carries the hero URL as background (center/cover) AND its first child is the same URL as <img> (position:absolute;inset:0) with NO opacity; the overlay fades to transparent over the product so the photo is visible; text above the overlay;',
    '- the Podium shows the hero asset as an uncropped contained <img> with a drop-shadow and a soft radial floor under it; no dark hero, no photo background;'
)

for _needle, _must in ((_showcase_hero_start.split('\n')[1], False), ('PODIUM - light product stage', True), ('drop-shadow', True)):
    if (_needle in PODIUM_STYLE_PROMPT) is not _must:
        raise RuntimeError(f'PODIUM style derivation failed on: {_needle}')

PODIUM_NEGATIVE_PROMPT = ENGINEERING_NEGATIVE_PROMPT

# --- ARTLINE Podium 3D -------------------------------------------------------
# Той самий Подіум, але сцена ОБЕРТАЄТЬСЯ. Живий тест у редакторі artline
# показав, що <style> з @keyframes ЗБЕРІГАЄТЬСЯ - легальна CSS-анімація
# можлива. AI при цьому не пише жодного CSS-3D: розмітку обертання вставляє
# сервер механічно (_apply_podium_spin у pipeline) ПІСЛЯ санітизації. Промпту
# лишається одне - поставити hero-<img> на сцену. Маркер PODIUM-3D-SPIN нижче
# вмикає цю механіку; він мусить лишатися в промпті стилю.

PODIUM3D_STYLE_NAME = 'ARTLINE Podium 3D'
PODIUM3D_STYLE_PROMPT = PODIUM_STYLE_PROMPT + """

PODIUM-3D-SPIN
- The stage <img> will be wrapped by the SERVER into a rotating 3D podium after generation.
- Keep exactly ONE hero <img> on the stage of section 1 and do NOT write any CSS animation, @keyframes or <style> yourself.
"""

if 'PODIUM-3D-SPIN' not in PODIUM3D_STYLE_PROMPT or 'exactly six sections' not in PODIUM3D_STYLE_PROMPT.lower():
    raise RuntimeError('PODIUM 3D style derivation failed')

