import html
import json
import logging
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select
from app.celery_app import celery
from app.config import DEFAULT_IMAGE_PRICING, DEFAULT_TEXT_PRICING, settings
from app.db import SessionLocal
from app.models import Artifact, Asset, CriticReport, Event, Project, Status, Style
from app.prompts import BASE_STYLE_VERSION
from app.pipeline import (
    _image_urls_of,
    core_feature_text,
    extract_product,
    fetch_html,
    gallery_urls,
    validated_gallery_urls,
    generate_html,
    generate_image,
    relayout_html,
    inspect_product_references,
    materialize_product_reference,
    parse_page,
    select_feature_photo,
    select_key_feature,
    style_image_prompt,
    translate_html,
    critic_html,
)


logger = logging.getLogger('richstudio.tasks')


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def send_alert(text: str):
    """Push an operational alert to Telegram and/or a webhook. Never raises.

    Alerts are best-effort: a broken alert channel must not break the pipeline.
    """
    import httpx
    payload_text = f'ARTLINE Rich Studio\n{text}'
    try:
        if settings.telegram_bot_token and settings.telegram_chat_id:
            httpx.post(
                f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage',
                json={'chat_id': settings.telegram_chat_id, 'text': payload_text},
                timeout=10,
            )
    except Exception as exc:
        logger.warning('Telegram alert failed: %s', exc)
    try:
        if settings.alert_webhook_url:
            httpx.post(settings.alert_webhook_url, json={'text': payload_text}, timeout=10)
    except Exception as exc:
        logger.warning('Webhook alert failed: %s', exc)


def log(db, project, stage, message, progress=None, level='info'):
    project.stage = stage
    if progress is not None:
        project.progress = progress
    db.add(Event(project_id=project.id, stage=stage, message=message, level=level))
    db.commit()


def text_rate(model: str):
    row = settings.text_pricing.get(model) or DEFAULT_TEXT_PRICING.get(model) or {'input': 1.0, 'output': 4.0}
    return float(row.get('input', 1.0) or 1.0), float(row.get('output', 4.0) or 4.0)


def image_rate(model: str, quality: str):
    row = settings.image_pricing.get(model) or DEFAULT_IMAGE_PRICING.get(model) or {'low': 0.02, 'medium': 0.07, 'high': 0.19}
    return float(row.get(quality, row.get('medium', 0.07)) or 0.07)


def recalculate_cost(project):
    input_rate, output_rate = text_rate(project.text_model)
    project.text_cost = (
        project.input_tokens / 1_000_000 * input_rate
        + project.output_tokens / 1_000_000 * output_rate
    )
    project.image_cost = project.image_count * image_rate(project.image_model, project.image_quality)
    project.estimated_cost = project.text_cost + project.image_cost


def cost_breakdown(project, extract_in, extract_out, content_in, content_out):
    """Per-stage cost so the UI can show where the money goes."""
    in_rate, out_rate = text_rate(project.text_model)
    extract_cost = extract_in / 1_000_000 * in_rate + extract_out / 1_000_000 * out_rate
    content_cost = content_in / 1_000_000 * in_rate + content_out / 1_000_000 * out_rate
    return {
        'extract': {'input_tokens': extract_in, 'output_tokens': extract_out, 'cost': round(extract_cost, 6)},
        'content': {'input_tokens': content_in, 'output_tokens': content_out, 'cost': round(content_cost, 6)},
        'images': {'count': project.image_count, 'requests': project.image_request_count, 'cost': round(project.image_cost, 6)},
        'total': round(extract_cost + content_cost + project.image_cost, 6),
    }


def _aborted(db, project) -> bool:
    """Re-read the row so a Pause/Cancel issued from the API stops the worker cleanly."""
    db.refresh(project)
    return project.status in (Status.paused, Status.cancelled)


def _existing_images(db, project) -> dict:
    """Label -> url of images already produced for this project."""
    rows = db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind == 'image')).all()
    return {a.label: a.url for a in rows if a.url}


@celery.task(bind=True, max_retries=0)
def process_project(self, project_id, reuse_images=False):
    started = time.time()
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return
        try:
            # Reuse keeps the previous shots and regenerates only the copy: no image
            # cost and no waiting for the image model.
            existing_images = _existing_images(db, project) if reuse_images else {}
            wanted_variants = [v for v in project.variants.split(',') if v]
            covers_heroes = all(
                existing_images.get(f'hero-{v}-generated') or existing_images.get('hero-custom') or existing_images.get('hero-source')
                for v in wanted_variants
            ) if wanted_variants else False
            covers_feature = bool(existing_images.get('feature-generated') or existing_images.get('feature-custom') or existing_images.get('feature-source'))
            # Full coverage -> skip image work entirely. Partial coverage -> the full
            # branch below runs, keeps the adopted shots and regenerates only the rest.
            reused = bool(existing_images) and covers_heroes and covers_feature
            project.status = Status.processing
            project.started_at = now()
            project.finished_at = None
            project.error = ''
            project.progress = 1
            project.input_tokens = 0
            project.output_tokens = 0
            project.text_request_count = 0
            project.image_request_count = 0
            project.image_count = 0
            project.text_cost = 0
            project.image_cost = 0
            project.estimated_cost = 0
            project.cost_breakdown_json = '{}'
            extract_in = extract_out = content_in = content_out = 0
            if not reused:
                db.execute(delete(Asset).where(Asset.project_id == project.id))
            db.execute(delete(CriticReport).where(CriticReport.project_id == project.id))
            db.commit()

            if _aborted(db, project):
                db.add(Event(project_id=project.id, stage=project.stage, level='warning', message='Виконання зупинено користувачем')); db.commit()
                return

            log(db, project, 'scrape', 'Читання сторінки товару', 5)
            page_html = fetch_html(project.source_url)
            jsonld, images, title, clean_text = parse_page(page_html, project.source_url)
            project.source_images = json.dumps(images, ensure_ascii=False)
            chosen_gallery = [u for u in json.loads(project.gallery_json or '[]') if isinstance(u, str) and u.strip()]
            # Manual picks were already vetted by the operator's browser;
            # the automatic pick must survive a liveness check against the CDN.
            page_gallery = chosen_gallery or validated_gallery_urls(images)
            if chosen_gallery:
                log(db, project, 'scrape', f'Використовується галерея, обрана вручну ({len(chosen_gallery)} кадрів)', 6)
            db.commit()

            log(db, project, 'extract', f'Витягування характеристик · {project.text_model}', 15)
            product, input_tokens, output_tokens = extract_product(
                jsonld, title, clean_text, project.source_url, project.text_model, page_html
            )
            project.product_json = json.dumps(product, ensure_ascii=False)
            detected_name = str(product.get('name') or title or '').strip()
            if detected_name:
                project.name = html.unescape(detected_name)[:200]
            category = str(product.get('category') or product.get('product_type') or '').strip()
            project.product_category = category[:120]
            project.input_tokens += input_tokens
            project.output_tokens += output_tokens
            if input_tokens or output_tokens:
                project.text_request_count += 1
            extract_in, extract_out = input_tokens, output_tokens
            recalculate_cost(project)
            project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
            db.commit()

            style_row = db.get(Style, project.style_id)
            if not style_row:
                raise RuntimeError('Selected style no longer exists')
            style = SimpleNamespace(
                id=style_row.id, name=style_row.name, hero_prompt=style_row.hero_prompt, feature_prompt=style_row.feature_prompt, negative_prompt=style_row.negative_prompt,
                # Do not inject unrelated global knowledge documents. Product facts
                # come only from this page until documents have an explicit product link.
                prompt=style_row.prompt
            )

            # Image-led styles build the page from real gallery frames; those frames
            # are working material exactly like Hero and Feature, so they belong in
            # the Медіа tab. Replace, not append: a rerun may carry a different
            # manual selection.
            if 'GALLERY_IMAGES' in (style.prompt or ''):
                db.execute(delete(Asset).where(
                    Asset.project_id == project.id, Asset.label.like('gallery-frame-%')
                ))
                for index, frame_url in enumerate(page_gallery, start=1):
                    db.add(Asset(
                        project_id=project.id, kind='image', label=f'gallery-frame-{index}',
                        url=frame_url, prompt='', model='source', cost=0,
                        metadata_json=json.dumps({'source': 'gallery', 'picked_manually': bool(chosen_gallery)}, ensure_ascii=False),
                    ))
                db.commit()
                log(db, project, 'images', f'Кадри галереї збережено в медіатеку ({len(page_gallery)} шт.)', 18)
            if reused:
                requested_variants = [value for value in project.variants.split(',') if value]
                fallback = existing_images.get('product-reference', '')
                hero_by_variant = {
                    v: existing_images.get(f'hero-{v}-generated') or existing_images.get('hero-custom')
                       or existing_images.get('hero-source') or fallback
                    for v in requested_variants
                }
                feature = (existing_images.get('feature-generated') or existing_images.get('feature-custom')
                           or existing_images.get('feature-source') or fallback)
                feature_mode = 'reused'
                planned_feature_url = ''
                style_feature = ''
                negative = ''
                original_reference_url = ''
                reference_path = None
                feature_photo_fallback = ''
                log(db, project, 'images', f'Зображення взято з попередньої генерації ({len(existing_images)} шт.) — нові не створювались', 35)
                recalculate_cost(project)
                project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
                db.commit()
            else:
                raw_primary = images[0] if images else ''
                ranked_references = inspect_product_references(images, raw_primary)
                selected_reference = ranked_references[0] if ranked_references else None
                original_reference_url = selected_reference['url'] if selected_reference else ''
                source_url, reference_path, reference_metadata = materialize_product_reference(
                    original_reference_url, project.id
                ) if original_reference_url else ('', None, {})
                fallback = source_url or original_reference_url
                product_name = product.get('name') or 'product'
                if fallback:
                    reference_metadata.update({
                        'source': 'product-page',
                        'selected_candidate': selected_reference or {},
                        'candidate_count': len(ranked_references),
                    })
                    db.add(Asset(
                        project_id=project.id,
                        kind='image',
                        label='product-reference',
                        url=fallback,
                        prompt='',
                        model='source',
                        width=reference_metadata.get('width') or selected_reference.get('width'),
                        height=reference_metadata.get('height') or selected_reference.get('height'),
                        metadata_json=json.dumps(reference_metadata, ensure_ascii=False),
                    ))
                    log(db, project, 'images', 'Головне фото товару перевірено та збережено як референс', 20)
                else:
                    log(db, project, 'images', 'На сторінці не знайдено придатного фото товару — AI-зображення буде пропущено', 20, 'warning')
                    db.commit()

                style_hero = style_image_prompt(style.prompt, 'HERO_IMAGE') or style.hero_prompt.strip()
                style_feature = style_image_prompt(style.prompt, 'FEATURE_IMAGE') or style.feature_prompt.strip()
                negative = getattr(style, 'negative_prompt', '').strip()
                facts = json.dumps(product, ensure_ascii=False)[:5000]
                requested_variants = [value for value in project.variants.split(',') if value]
                hero_by_variant = {}

                if project.custom_hero_url:
                    hero_by_variant = {variant: project.custom_hero_url for variant in requested_variants}
                    db.add(Asset(project_id=project.id,kind='image',label='hero-custom',url=project.custom_hero_url,prompt='',model='custom',metadata_json=json.dumps({'source':'custom','variants':requested_variants},ensure_ascii=False)))
                    log(db, project, 'images', 'Використовується власне Hero-зображення', 25)
                elif style_hero:
                    hero_specs = {
                        'desktop': ('1536x1024', 1536, 1024, 'wide desktop composition; product on the right; protected text-safe space on the left'),
                        'mobile': ('1024x1536', 1024, 1536, 'portrait mobile composition; complete product in the upper area; protected text-safe space below it'),
                    }
                    for offset, variant in enumerate(requested_variants):
                        adopted_hero = existing_images.get(f'hero-{variant}-generated') or existing_images.get('hero-custom')
                        if adopted_hero:
                            hero_by_variant[variant] = adopted_hero
                            log(db, project, 'images', f'Hero {variant}: взято з попередньої генерації — без витрат', 24 + offset * 5)
                            continue
                        size, width, height, composition = hero_specs.get(variant, hero_specs['desktop'])
                        log(db, project, 'images', f'Створення Hero {variant} · {project.image_model}', 24 + offset * 5)
                        hero_prompt = (
                            f"{style_hero}\nCanvas requirement: {composition}. "
                            f"Render specifically at {size}; do not crop important product parts.\n"
                            f"Negative requirements: {negative}\nProduct: {product_name}. Verified product facts: {facts}"
                        )
                        hero, hero_generated, hero_error = generate_image(
                            hero_prompt, project.id, f'hero-{variant}', project.image_model,
                            project.image_quality, fallback, reference_url=original_reference_url,
                            reference_path=reference_path, size=size,
                        )
                        hero_by_variant[variant] = hero
                        if reference_path:
                            project.image_request_count += 1
                        if hero_generated:
                            project.image_count += 1
                            db.add(Asset(
                                project_id=project.id, kind='image', label=f'hero-{variant}-generated',
                                url=hero, prompt=hero_prompt, model=project.image_model, width=width,
                                height=height, cost=image_rate(project.image_model,project.image_quality),
                                metadata_json=json.dumps({'source':'generated','variant':variant,'reference_url':original_reference_url,'reference_asset_url':fallback},ensure_ascii=False),
                            ))
                        elif hero_error:
                            log(db, project, 'images', f'Hero {variant} не згенеровано; використовується реальне фото товару. Причина: {hero_error}', 30 + offset * 5, 'warning')
                else:
                    hero_by_variant = {variant: fallback for variant in requested_variants}
                    if fallback:
                        db.add(Asset(project_id=project.id,kind='image',label='hero-source',url=fallback,prompt='',model='source',metadata_json=json.dumps({'source':'product-page','variants':requested_variants},ensure_ascii=False)))
                    log(db, project, 'images', 'Hero-генерацію вимкнено — використовується фото товару', 25)
                recalculate_cost(project); db.commit()

                # The Feature image is generated AFTER the text, from the finished Core
                # Feature section, so the shot always matches what the page actually says.
                # Its URL is deterministic, so the copy can reference it in advance.
                planned_feature_url = f'/media/{project.id}/feature.webp'
                feature_mode = 'photo'
                feature_photo_fallback = ''
                if existing_images.get('feature-generated') or existing_images.get('feature-custom'):
                    feature = existing_images.get('feature-generated') or existing_images.get('feature-custom')
                    feature_mode = 'adopted'
                    log(db, project, 'images', 'Feature взято з попередньої генерації — без витрат', 35)
                elif project.custom_feature_url:
                    feature = project.custom_feature_url
                    feature_mode = 'custom'
                    db.add(Asset(project_id=project.id,kind='image',label='feature-custom',url=feature,prompt='',model='custom',metadata_json=json.dumps({'source':'custom'},ensure_ascii=False)))
                    log(db, project, 'images', 'Використовується власне додаткове зображення', 35)
                elif style_feature and reference_path:
                    feature = planned_feature_url
                    feature_mode = 'generate'
                    feature_choice = select_feature_photo(ranked_references, selected_reference)
                    feature_photo_fallback = feature_choice.get('url') if feature_choice else fallback
                    log(db, project, 'images', 'Feature буде створено після тексту — за описом секції Core Feature', 35)
                else:
                    # Show a real gallery frame instead of generating one: an edited Feature
                    # image kept drifting into a different product. Prefer a frame that is
                    # not the one already used for Hero.
                    feature_choice = select_feature_photo(ranked_references, selected_reference)
                    feature = ''
                    if feature_choice:
                        feature_url, _feature_path, feature_meta = materialize_product_reference(feature_choice['url'], project.id, 'feature-photo.png')
                        feature = feature_url or feature_choice['url']
                        db.add(Asset(
                            project_id=project.id, kind='image', label='feature-source', url=feature, prompt='', model='source',
                            width=feature_meta.get('width') or feature_choice.get('width'),
                            height=feature_meta.get('height') or feature_choice.get('height'),
                            metadata_json=json.dumps({'source': 'product-page', 'reason': 'distinct gallery frame', 'selected_candidate': feature_choice}, ensure_ascii=False),
                        ))
                        log(db, project, 'images', 'Feature: використано окреме реальне фото товару з галереї', 35)
                    else:
                        feature = fallback
                        if feature:
                            db.add(Asset(project_id=project.id,kind='image',label='feature-source',url=feature,prompt='',model='source',metadata_json=json.dumps({'source':'product-page','reason':'no distinct gallery frame'},ensure_ascii=False)))
                        log(db, project, 'images', 'Feature: окремого кадру в галереї немає — використано головне фото товару', 35)
                recalculate_cost(project)
                project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
                db.commit()

            if _aborted(db, project):
                db.add(Event(project_id=project.id, stage=project.stage, level='warning', message='Виконання зупинено користувачем перед створенням контенту')); db.commit()
                return

            languages = [value for value in project.languages.split(',') if value]
            variants = [value for value in project.variants.split(',') if value]
            if not languages or not variants:
                raise RuntimeError('Select at least one language and one layout variant')

            total_outputs = len(languages) * len(variants)
            completed_outputs = 0
            feature_done = False
            used_page_images = set()
            # Desktop first: the mobile master is derived from the finished desktop
            # page by a layout-only transform, so the two variants cannot drift.
            variants = sorted(variants, key=lambda v: 0 if v == 'desktop' else 1)
            desktop_master_html = None
            for variant in variants:
                # Generate one master layout per viewport. Every other language is a
                # text-node-only translation of this master, so DOM, inline CSS,
                # image URLs and section order cannot drift between RU/UA/PL.
                master_language = 'ru' if 'ru' in languages else languages[0]
                ordered_languages = [master_language] + [value for value in languages if value != master_language]
                hero = hero_by_variant.get(variant) or fallback
                master_html = None
                for language in ordered_languages:
                    if _aborted(db, project):
                        db.add(Event(project_id=project.id, stage=project.stage, level='warning', message='Виконання зупинено користувачем під час генерації')); db.commit()
                        return
                    progress = 40 + int(52 * completed_outputs / max(1, total_outputs))
                    if master_html is None:
                        rich_html = None
                        added_input = added_output = 0
                        if variant == 'mobile' and desktop_master_html:
                            log(db, project, 'content', f'Мобільна верстка з десктопного макета · {project.text_model}', progress)
                            relaid, relayout_in, relayout_out, relayout_reason = relayout_html(desktop_master_html, project.text_model)
                            added_input += relayout_in
                            added_output += relayout_out
                            if relaid:
                                rich_html, fallback_reason = relaid, ''
                            else:
                                # A failed relayout still billed tokens; keep them and
                                # fall through to the independent generation path.
                                log(db, project, 'content', f'{variant}: {relayout_reason}', progress, 'warning')
                        if rich_html is None:
                            log(db, project, 'content', f'Створення майстер-макета {master_language.upper()} / {variant} · {project.text_model}', progress)
                            rich_html, generated_in, generated_out, fallback_reason = generate_html(
                                product, style, master_language, variant, hero, feature, project.text_model, gallery=page_gallery
                            )
                            added_input += generated_in
                            added_output += generated_out
                        if fallback_reason and settings.openai_api_key:
                            log(db, project, 'content', f'{master_language.upper()} / {variant}: {fallback_reason}', progress, 'warning')
                        master_html = rich_html
                        if variant == 'desktop':
                            desktop_master_html = master_html
                        if feature_mode == 'generate' and not feature_done:
                            # The page now exists: build the Feature shot from the text of
                            # its Core Feature section, so image and copy always agree.
                            feature_done = True
                            core_text = core_feature_text(master_html) or select_key_feature(product) or product_name
                            log(db, project, 'images', f'Створення Feature за описом секції: {core_text[:90]}', progress)
                            # The section description comes FIRST: it is the subject of the
                            # image. The style block below it is only art direction.
                            feature_prompt = (
                                "FEATURE DESCRIPTION FROM THE PAGE — this is the finished Core Feature section of the page "
                                "this image will sit next to. The image must make THIS description visible IN THE PHYSICAL SCENE and nothing else. "
                                "Express it only through objects, cropping, environment and lighting - NEVER by rendering words: "
                                "the description already sits beside the image as page text, so any caption, title, label, arrow "
                                "or infographic overlay painted into the image is a defect. The only readable characters allowed "
                                "are those physically present on the real product:\n"
                                f"\"{core_text}\"\n\n"
                                "HOW TO SHOW IT: the product itself cannot be altered, so express the described feature through "
                                "(a) cropping to the product area most relevant to the description, and "
                                "(b) the surrounding environment showing the OUTCOME of the feature in a credible way "
                                "(for example: finished printed parts for speed or calibration features, connected equipment "
                                "for connectivity features, the relevant material for material-support features). "
                                "Someone who reads the description and then looks at the image must see the connection immediately.\n\n"
                                f"ART DIRECTION:\n{style_feature}\n"
                                f"Negative requirements: {negative}\nProduct: {product_name}."
                            )
                            generated_url, feature_generated, feature_error = generate_image(
                                feature_prompt, project.id, 'feature', project.image_model, project.image_quality,
                                feature_photo_fallback or fallback,
                                reference_url=original_reference_url, reference_path=reference_path, size='1024x1024')
                            if reference_path:
                                project.image_request_count += 1
                            if feature_generated:
                                project.image_count += 1
                                feature = generated_url
                                db.add(Asset(project_id=project.id, kind='image', label='feature-generated', url=generated_url,
                                             prompt=feature_prompt, model=project.image_model, width=1024, height=1024,
                                             cost=image_rate(project.image_model, project.image_quality),
                                             metadata_json=json.dumps({'source': 'generated', 'core_feature_text': core_text, 'reference_url': original_reference_url, 'reference_asset_url': fallback}, ensure_ascii=False)))
                            else:
                                # Generation failed: fall back to a real photo and repoint the
                                # copy, which was written against the planned URL.
                                real_feature = feature_photo_fallback or fallback or ''
                                log(db, project, 'images', f'Feature не згенеровано; використовується реальне фото товару. Причина: {feature_error}', progress, 'warning')
                                if real_feature:
                                    db.add(Asset(project_id=project.id, kind='image', label='feature-source', url=real_feature, prompt='', model='source',
                                                 metadata_json=json.dumps({'source': 'product-page', 'reason': 'feature generation failed'}, ensure_ascii=False)))
                                feature = real_feature
                                if real_feature:
                                    master_html = master_html.replace(planned_feature_url, real_feature)
                                    rich_html = master_html  # the master artifact must not keep the dead URL
                            recalculate_cost(project)
                    else:
                        log(db, project, 'content', f'Переклад макета {language.upper()} / {variant} без зміни дизайну', progress)
                        translated = translate_html(master_html, language, project.text_model)
                        if translated[0] is None:
                            # Offline/no-key fallback still uses the deterministic
                            # template, whose structure is identical for all languages.
                            rich_html, added_input, added_output, fallback_reason = generate_html(
                                product, style, language, variant, hero, feature, project.text_model, gallery=page_gallery
                            )
                            if fallback_reason and settings.openai_api_key:
                                log(db, project, 'content', f'{language.upper()} / {variant}: {fallback_reason}', progress, 'warning')
                        else:
                            rich_html, added_input, added_output = translated
                    project.input_tokens += added_input
                    project.output_tokens += added_output
                    if added_input or added_output:
                        project.text_request_count += 1
                    content_in += added_input
                    content_out += added_output
                    recalculate_cost(project)
                    project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
                    latest_version = db.scalar(select(func.max(Artifact.version)).where(
                        Artifact.project_id == project.id,
                        Artifact.language == language,
                        Artifact.variant == variant,
                    )) or 0
                    marker = (f'<!-- ARTLINE Rich Studio · стиль v{BASE_STYLE_VERSION} · {language}/{variant} · '
                              f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC -->\n')
                    db.add(Artifact(
                        project_id=project.id,
                        language=language,
                        variant=variant,
                        html=marker + rich_html,
                        version=latest_version + 1,
                    ))
                    db.commit()
                    completed_outputs += 1
                    used_page_images.update(_image_urls_of(rich_html))

            recalculate_cost(project)
            project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
            artifact_rows = db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
            latest_by_variant = {}
            for artifact in sorted(artifact_rows, key=lambda row: row.version):
                latest_by_variant[(artifact.language, artifact.variant)] = artifact
            latest = list(latest_by_variant.values())
            for critic_type in ('html','facts','accessibility','marketing'):
                score, summary, issues, suggestions = critic_html(latest, critic_type, product)
                db.add(CriticReport(project_id=project.id, critic_type=critic_type, score=score, summary=summary, issues_json=json.dumps(issues, ensure_ascii=False), suggestions_json=json.dumps(suggestions, ensure_ascii=False)))
            known_urls = {a.url for a in db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind == 'image')).all()}
            page_extra = [u for u in sorted(used_page_images) if u and u not in known_urls]
            for index, url in enumerate(page_extra, start=1):
                db.add(Asset(project_id=project.id, kind='image', label=f'page-image-{index}', url=url, prompt='', model='source', cost=0,
                             metadata_json=json.dumps({'source': 'page-html'}, ensure_ascii=False)))
            if page_extra:
                db.commit()
                log(db, project, 'images', f'До медіатеки додано всі зображення сторінки ({len(page_extra)} поза базовим набором)')
            project.status = Status.review
            project.stage = 'review'
            project.progress = 100
            project.finished_at = now()
            project.duration_seconds = time.time() - started
            db.add(Event(
                project_id=project.id,
                stage='review',
                message=(
                    f'Генерацію завершено. Проєкт надіслано на перевірку. {project.text_request_count} text requests, '
                    f'{project.image_count}/{project.image_request_count} images generated. '
                    f'Estimated cost ${project.estimated_cost:.6f}'
                ),
            ))
            db.commit()
        except Exception as exc:
            recalculate_cost(project)
            try:
                project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
            except Exception:
                pass
            project.status = Status.error
            project.stage = 'error'
            project.error = str(exc)
            project.finished_at = now()
            project.duration_seconds = time.time() - started
            db.add(Event(project_id=project.id, stage='error', level='error', message=str(exc)))
            db.commit()
            send_alert(f'Проєкт впав з помилкою\n{project.name}\n{exc}')


@celery.task
def translate_project(project_id: str, language: str):
    """Add one language to a finished project by translating its newest artifacts.

    No scraping, no images, no master regeneration: translate_html() rewrites text
    nodes only, so layout, styles and image URLs stay byte-identical to the source
    variant. Costs tokens for the copy alone - the cheapest way to add a language.
    """
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return
        source_language = (project.languages or 'ua').split(',')[0].strip() or 'ua'
        variants = [v.strip() for v in (project.variants or 'desktop').split(',') if v.strip()]
        log(db, project, 'translate', f'Переклад наявних версій на {language.upper()} (з {source_language.upper()})')
        added_any = False
        for variant in variants:
            source = db.scalar(select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.language == source_language,
                Artifact.variant == variant,
            ).order_by(Artifact.version.desc()))
            if not source:
                log(db, project, 'translate', f'{variant}: немає вихідної версії {source_language.upper()} — пропущено', level='warning')
                continue
            try:
                translated, added_input, added_output = translate_html(source.html, language, project.text_model) or (None, 0, 0)
            except Exception as exc:
                log(db, project, 'translate', f'{variant}: переклад не вдався: {str(exc)[:180]}', level='error')
                continue
            if not translated:
                log(db, project, 'translate', f'{variant}: перекладач не повернув результат', level='warning')
                continue
            project.input_tokens += added_input
            project.output_tokens += added_output
            if added_input or added_output:
                project.text_request_count += 1
            recalculate_cost(project)
            latest = db.scalar(select(func.max(Artifact.version)).where(
                Artifact.project_id == project.id,
                Artifact.language == language,
                Artifact.variant == variant,
            )) or 0
            db.add(Artifact(project_id=project.id, language=language, variant=variant, html=translated, version=latest + 1))
            db.commit()
            added_any = True
            log(db, project, 'translate', f'{variant}: {language.upper()} v{latest + 1} готово')
        if added_any:
            langs = [x.strip() for x in (project.languages or '').split(',') if x.strip()]
            if language not in langs:
                langs.append(language)
                project.languages = ','.join(langs)
            log(db, project, 'translate', f'Мову {language.upper()} додано перекладом — перевірте результат перед публікацією')
        db.commit()


@celery.task
def watchdog_stuck_projects():
    """Fail projects stuck in processing/queued beyond the limit and alert about them.

    A dead worker or a hung API call otherwise leaves a project spinning forever
    and nobody notices until they look. Runs on a beat schedule.
    """
    limit = timedelta(minutes=max(10, settings.stuck_project_minutes))
    cutoff = now() - limit
    with SessionLocal() as db:
        stuck = db.scalars(select(Project).where(
            Project.status.in_((Status.processing, Status.queued)),
        )).all()
        flagged = []
        for project in stuck:
            reference = project.started_at or project.created_at
            if reference and reference < cutoff:
                project.status = Status.error
                project.stage = 'error'
                project.error = f'Watchdog: проєкт завис довше {settings.stuck_project_minutes} хв і був зупинений'
                project.finished_at = now()
                db.add(Event(project_id=project.id, stage='error', level='error', message=project.error))
                flagged.append(project.name)
        if flagged:
            db.commit()
            send_alert('Watchdog зупинив завислі проєкти:\n' + '\n'.join(f'• {name}' for name in flagged))
        return {'flagged': len(flagged)}
