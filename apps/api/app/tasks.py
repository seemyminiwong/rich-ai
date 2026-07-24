import html
import json
import logging
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select, update
from app.celery_app import celery
from app.config import DEFAULT_IMAGE_PRICING, DEFAULT_TEXT_PRICING, settings
from app.db import SessionLocal
from app.models import Artifact, Asset, CriticReport, Event, Project, Status, Style
from app.limits import add_spend, add_user_spend
from app.media import media_url
from app.prompts import BASE_STYLE_VERSION, LICENSE_COMMENT
from app.pipeline import _PODIUM_360_MARKER, _PODIUM_SCROLL_MARKER, _PODIUM_SPIN_MARKER, _apply_podium_spin, _apply_podium_spin360, _apply_podium_scroll, _finalize_showcase_layout, _fit_mobile_hero, _fit_photo_cards, _frame_contained_photos, _harmonize_radii, _never_crop_product_photos
from app.pipeline import (
    _image_urls_of,
    hero_environment,
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
    # Локальні моделі не коштують токенів - інакше кошторис брехав би.
    if model in settings.local_models:
        return 0.0, 0.0
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



def close_run(db, project, status: str = 'done') -> None:
    """Записати підсумок прогону в історію і додати його вартість до сумарної.

    estimated_cost обнуляється при кожному перезапуску (це вартість ПОТОЧНОГО
    прогону) - без цієї історії гроші за попередні спроби просто зникали з
    картки проєкту, а зіставити версію сторінки з її ціною було неможливо.
    """
    try:
        runs = json.loads(getattr(project, 'runs_json', None) or '[]')
    except Exception:
        runs = []
    index = getattr(project, 'run_index', 1) or 1
    entry = {
        'index': index,
        'status': status,
        'cost': round(float(project.estimated_cost or 0), 6),
        'input_tokens': project.input_tokens or 0,
        'output_tokens': project.output_tokens or 0,
        'images': project.image_count or 0,
        'style_id': project.style_id,
        'text_model': project.text_model,
        'image_model': project.image_model,
        'finished_at': datetime.utcnow().isoformat() + 'Z',
        'duration_seconds': round(float(project.duration_seconds or 0), 1),
    }
    runs = [r for r in runs if r.get('index') != index] + [entry]
    project.runs_json = json.dumps(runs[-50:], ensure_ascii=False)
    project.lifetime_cost = round(sum(float(r.get('cost') or 0) for r in runs[-50:]), 6)


def bill_extra(db, project, amount: float) -> None:
    """Доплата поза прогоном (переклад, AI-рецензія, авто-виправлення)."""
    amount = round(float(amount or 0), 6)
    if amount <= 0:
        return
    project.lifetime_cost = round(float(getattr(project, 'lifetime_cost', 0) or 0) + amount, 6)
    try:
        runs = json.loads(getattr(project, 'runs_json', None) or '[]')
    except Exception:
        runs = []
    if runs:
        runs[-1]['cost'] = round(float(runs[-1].get('cost') or 0) + amount, 6)
        runs[-1]['extra'] = round(float(runs[-1].get('extra') or 0) + amount, 6)
        project.runs_json = json.dumps(runs, ensure_ascii=False)


def _run_charge_id(project) -> str:
    return f'project:{project.id}:run:{getattr(project, "run_index", 1) or 1}'


def _charge_current_run(project) -> None:
    """Move the cumulative real run cost into idempotent daily ledgers."""
    amount = max(0.0, float(project.estimated_cost or 0))
    operation_id = _run_charge_id(project)
    add_spend(amount, operation_id=operation_id)
    add_user_spend(project.owner_id or '', amount, operation_id=operation_id)


def _aborted(db, project, started: float | None = None) -> bool:
    """Re-read and financially finalize a user pause/cancel exactly once."""
    db.refresh(project)
    if project.status not in (Status.paused, Status.cancelled):
        return False
    if project.finished_at is None:
        recalculate_cost(project)
        _charge_current_run(project)
        project.duration_seconds = time.time() - started if started is not None else project.duration_seconds
        project.finished_at = now()
        project.stage = project.status.value
        close_run(db, project, project.status.value)
    project.reserved_cost = 0
    db.commit()
    return True


def _existing_images(db, project) -> dict:
    """Label -> url of images already produced for this project."""
    rows = db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind == 'image')).all()
    return {a.label: a.url for a in rows if a.url}


@celery.task(bind=True, max_retries=0)
def process_project(self, project_id, reuse_images=False):
    started = time.time()
    with SessionLocal() as db:
        # Celery delivery is at-least-once. Lock before claiming the row so an
        # API retry, a broker redelivery and the durable dispatcher cannot run
        # the same paid project concurrently.
        project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if not project:
            return
        delivery = getattr(self.request, 'delivery_info', None) or {}
        redelivered = bool(delivery.get('redelivered') or getattr(self.request, 'redelivered', False))
        reclaim_after_worker_loss = project.status == Status.processing and redelivered
        if project.status != Status.queued and not reclaim_after_worker_loss:
            logger.info('Skipping project %s in status %s', project_id, project.status.value)
            return {'skipped': True, 'status': project.status.value}
        if reclaim_after_worker_loss:
            logger.warning('Reclaiming redelivered project %s after worker loss', project_id)
        try:
            if reclaim_after_worker_loss:
                recalculate_cost(project)
                _charge_current_run(project)
                project.finished_at = now()
                close_run(db, project, 'worker_lost')
                project.run_index = (getattr(project, 'run_index', 1) or 1) + 1
                db.add(Event(project_id=project.id, stage='queued', level='warning', message='Втрачений worker: частковий прогін зафіксовано, задачу відновлено'))
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

            if _aborted(db, project, started):
                db.add(Event(project_id=project.id, stage=project.stage, level='warning', message='Виконання зупинено користувачем')); db.commit()
                return

            log(db, project, 'scrape', 'Читання сторінки товару', 5)
            page_html = fetch_html(project.source_url)
            jsonld, images, title, clean_text = parse_page(page_html, project.source_url)
            project.source_images = json.dumps(images, ensure_ascii=False)
            chosen_gallery = [u for u in json.loads(project.gallery_json or '[]') if isinstance(u, str) and u.strip()]
            rotation_frames = [u for u in json.loads(getattr(project, 'rotation_json', None) or '[]') if isinstance(u, str) and u.strip()]
            # Manual picks were already vetted by the operator's browser;
            # the automatic pick must survive a liveness check against the CDN.
            # Завантажені оператором фото (/media/...) - ДОДАТОК до галереї:
            # вони не мають вимикати автопідбір кадрів з CDN, коли кадри вручну
            # не куруватись.
            uploaded_frames = [u for u in chosen_gallery if u.startswith('/media/')]
            curated_cdn = [u for u in chosen_gallery if not u.startswith('/media/')]
            page_gallery = (curated_cdn or validated_gallery_urls(images)) + uploaded_frames
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
                            f"{style_hero}\nENVIRONMENT: {hero_environment(product)}\n"
                            f"Canvas requirement: {composition}. "
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
                planned_feature_url = media_url(project.id, 'feature.webp')
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

            if _aborted(db, project, started):
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
            fallback_hits = []
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
                    if _aborted(db, project, started):
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
                                # The relayout keeps URLs byte-identical by design, so it
                                # inherits the DESKTOP hero. Swap in the portrait asset
                                # mechanically - both URLs are ours and deterministic.
                                desktop_hero = hero_by_variant.get('desktop')
                                mobile_hero = hero_by_variant.get('mobile')
                                if desktop_hero and mobile_hero and desktop_hero != mobile_hero:
                                    relaid = relaid.replace(desktop_hero, mobile_hero)
                                # Перекомпонування успадковує десктопні пропорції блока -
                                # підганяємо під портретний кадр, щоб не різало товар.
                                relaid = _fit_mobile_hero(relaid, mobile_hero or hero)
                                relaid = _fit_photo_cards(relaid, 'mobile')
                                relaid = _never_crop_product_photos(relaid)
                                relaid = _frame_contained_photos(relaid)
                                relaid = _harmonize_radii(relaid)
                                if (style.name or '').startswith('ARTLINE Showcase'):
                                    relaid = _finalize_showcase_layout(
                                        relaid,
                                        'mobile',
                                        dark_edition=style.name == 'ARTLINE Showcase Dark',
                                    )
                                # Модель могла загубити <style> обертання при перекомпонуванні -
                                # повторне застосування ідемпотентне.
                                prompt_text = style.prompt or ''
                                if _PODIUM_SCROLL_MARKER in prompt_text:
                                    relaid = _apply_podium_scroll(relaid, hero, rotation_frames)
                                elif _PODIUM_360_MARKER in prompt_text:
                                    relaid = _apply_podium_spin360(relaid, hero, rotation_frames)
                                elif _PODIUM_SPIN_MARKER in prompt_text:
                                    relaid = _apply_podium_spin(relaid, hero)
                                rich_html, fallback_reason = relaid, ''
                            else:
                                # A failed relayout still billed tokens; keep them and
                                # fall through to the independent generation path.
                                log(db, project, 'content', f'{variant}: {relayout_reason}', progress, 'warning')
                        if rich_html is None:
                            log(db, project, 'content', f'Створення майстер-макета {master_language.upper()} / {variant} · {project.text_model}', progress)
                            rich_html, generated_in, generated_out, fallback_reason = generate_html(
                                product, style, master_language, variant, hero, feature, project.text_model, gallery=page_gallery, rotation=rotation_frames
                            )
                            added_input += generated_in
                            added_output += generated_out
                        if fallback_reason and settings.openai_api_key:
                            # Serving the generic template while the operator believes
                            # they are looking at their chosen style wasted a whole day
                            # once. Make it loud: error level, alert, project flag.
                            fallback_hits.append(f'{master_language.upper()}/{variant}: {fallback_reason}')
                            log(db, project, 'content', f'AI-генерацію не вдалося виконати ({master_language.upper()} / {variant}) — сторінку зібрано аварійним шаблоном, а не обраним стилем. Причина: {fallback_reason}', progress, 'error')
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
                                product, style, language, variant, hero, feature, project.text_model, gallery=page_gallery, rotation=rotation_frames
                            )
                            if fallback_reason and settings.openai_api_key:
                                fallback_hits.append(f'{language.upper()}/{variant}: {fallback_reason}')
                                log(db, project, 'content', f'AI-генерацію не вдалося виконати ({language.upper()} / {variant}) — аварійний шаблон. Причина: {fallback_reason}', progress, 'error')
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
                        html=marker + rich_html + LICENSE_COMMENT,
                        version=latest_version + 1,
                        fallback_reason=fallback_reason or '',
                        run_index=getattr(project, 'run_index', 1) or 1,
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
            if fallback_hits:
                # The run finished, but not with the content that was asked for.
                # Say so in the project error field, in the log and in Telegram.
                summary = '; '.join(fallback_hits[:4])
                project.error = ('AI-генерацію не виконано, використано аварійний шаблон замість обраного стилю. '
                                 f'Перегенеруйте проєкт. Деталі: {summary}')
                log(db, project, 'review', 'Увага: частина сторінок — аварійний шаблон, а не обраний стиль. Перед публікацією перегенеруйте.', level='error')
                send_alert(f'Rich Studio: аварійний шаблон замість стилю\nПроєкт: {project.name}\n{summary}')
            # Feed cumulative idempotent ledgers with the real current-run cost.
            _charge_current_run(project)
            project.status = Status.review
            project.stage = 'review'
            project.progress = 100
            project.finished_at = now()
            project.duration_seconds = time.time() - started
            close_run(db, project, 'review')
            project.reserved_cost = 0
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
            # A failed flush/commit leaves SQLAlchemy in PendingRollbackError;
            # restore the last durable metrics before recording the failure.
            try:
                db.rollback()
                project = db.get(Project, project_id) or project
            except Exception:
                pass
            recalculate_cost(project)
            try:
                project.cost_breakdown_json = json.dumps(cost_breakdown(project, extract_in, extract_out, content_in, content_out), ensure_ascii=False)
            except Exception:
                pass
            # Failed generations can still have consumed tokens/images. Move
            # that real partial cost from the reservation into daily spend
            # before releasing the reservation.
            _charge_current_run(project)
            project.status = Status.error
            project.stage = 'error'
            project.error = str(exc)
            project.finished_at = now()
            project.duration_seconds = time.time() - started
            close_run(db, project, 'error')
            project.reserved_cost = 0
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
        cost_before_translate = float(project.estimated_cost or 0)
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
            db.add(Artifact(project_id=project.id, language=language, variant=variant, html=(translated if 'Правовласник' in translated else translated + LICENSE_COMMENT), version=latest + 1, run_index=getattr(project, 'run_index', 1) or 1))
            db.commit()
            added_any = True
            log(db, project, 'translate', f'{variant}: {language.upper()} v{latest + 1} готово')
        if added_any:
            translate_cost = float(project.estimated_cost or 0) - cost_before_translate
            add_spend(translate_cost)
            add_user_spend(project.owner_id or '', translate_cost)
            bill_extra(db, project, translate_cost)
            langs = [x.strip() for x in (project.languages or '').split(',') if x.strip()]
            if language not in langs:
                langs.append(language)
                project.languages = ','.join(langs)
            log(db, project, 'translate', f'Мову {language.upper()} додано перекладом — перевірте результат перед публікацією')
        db.commit()


@celery.task
def dispatch_pending_projects():
    """Publish durable DB-backed queue entries that the API could not publish.

    The API commits projects as ``dispatch_pending`` before talking to the
    broker. If it crashes after that commit, beat republishes them here. A
    publish-before-mark crash can create a duplicate message, which is safe
    because ``process_project`` claims the project row under a lock.
    """
    # Redis now persists Celery messages with AOF. On the first run after this
    # upgrade (or after a broker-volume loss), move every still-queued DB row
    # back into the outbox once; duplicate messages are harmless at claim time.
    try:
        import redis as redis_lib
        redis_client = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        recovery_key = 'richstudio:broker-queue-initialized:v1'
        recover_broker_queue = not bool(redis_client.get(recovery_key))
    except Exception:
        redis_client = None
        recovery_key = ''
        recover_broker_queue = False
    if recover_broker_queue:
        with SessionLocal() as db:
            db.execute(update(Project).where(
                Project.status == Status.queued,
                Project.stage.in_(('queued', 'queued_delayed')),
            ).values(stage='dispatch_pending'))
            db.commit()
        try:
            redis_client.set(recovery_key, '1')
        except Exception:
            pass

    with SessionLocal() as db:
        project_ids = list(db.scalars(select(Project.id).where(
            Project.status == Status.queued,
            Project.stage == 'dispatch_pending',
        ).order_by(Project.created_at).limit(200)).all())

    dispatched = failed = 0
    for project_id in project_ids:
        with SessionLocal() as db:
            reuse_images = bool(db.scalar(select(func.count(Asset.id)).where(
                Asset.project_id == project_id,
                Asset.kind == 'image',
            )))
        try:
            process_project.delay(project_id, reuse_images=reuse_images)
        except Exception as exc:
            failed += 1
            logger.warning('Pending dispatch failed for project %s: %s', project_id, exc)
            continue
        dispatched += 1
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if project and project.status == Status.queued and project.stage == 'dispatch_pending':
                project.stage = 'queued'
                db.add(Event(project_id=project.id, stage='queued', message='Проєкт передано воркеру повторним диспетчером'))
                db.commit()
    return {'pending': len(project_ids), 'dispatched': dispatched, 'failed': failed}


@celery.task
def watchdog_stuck_projects():
    """Fail hung processing, finalize abandoned stops, and warn on long queues.

    A dead worker or a hung API call otherwise leaves a project spinning forever
    and nobody notices until they look. Queued work is never killed merely for
    waiting: a 100-row import can legitimately exceed a fixed wall-clock TTL.
    """
    processing_cutoff = now() - timedelta(minutes=max(10, settings.stuck_project_minutes))
    queued_cutoff = now() - timedelta(hours=max(1, settings.queued_project_hours))
    with SessionLocal() as db:
        stuck = db.scalars(select(Project).where(
            Project.status.in_((Status.processing, Status.queued, Status.paused, Status.cancelled)),
        ).with_for_update(skip_locked=True)).all()
        alerts = []
        for project in stuck:
            if project.status == Status.queued:
                reference = project.queued_at or project.created_at
                if reference and reference < queued_cutoff and project.stage != 'queued_delayed':
                    project.stage = 'queued_delayed'
                    message = f'Проєкт очікує в черзі понад {settings.queued_project_hours} год; його не скасовано'
                    db.add(Event(project_id=project.id, stage=project.stage, level='warning', message=message))
                    alerts.append(f'Довга черга: {project.name}')
                continue

            if project.status in (Status.paused, Status.cancelled):
                if project.finished_at is not None:
                    continue
                reference = project.started_at or project.created_at
                if reference and reference < processing_cutoff:
                    recalculate_cost(project)
                    _charge_current_run(project)
                    project.finished_at = now()
                    project.stage = project.status.value
                    project.reserved_cost = 0
                    close_run(db, project, project.status.value)
                    message = f'Зупинку підтверджено сторожем після {settings.stuck_project_minutes} хв'
                    db.add(Event(project_id=project.id, stage=project.stage, level='warning', message=message))
                    alerts.append(f'Завершено зупинку: {project.name}')
                continue

            reference = project.started_at or project.created_at
            if reference and reference < processing_cutoff:
                recalculate_cost(project)
                _charge_current_run(project)
                project.status = Status.error
                project.stage = 'error'
                project.error = f'Watchdog: проєкт не завершив активний етап за {settings.stuck_project_minutes} хв і був зупинений'
                project.finished_at = now()
                project.reserved_cost = 0
                close_run(db, project, 'error')
                db.add(Event(project_id=project.id, stage='error', level='error', message=project.error))
                alerts.append(f'Зупинено завислий: {project.name}')
        if alerts:
            db.commit()
            send_alert('Watchdog проєктів:\n' + '\n'.join(f'• {message}' for message in alerts))
        return {'flagged': len(alerts)}


@celery.task(bind=True, max_retries=0)
def process_landing(self, landing_id: str):
    """Промо-лендінг: проби товарів (безкоштовно) -> одна AI-генерація сторінки.

    Події проєктів (Event) тут не пишуться - у них FK на projects; стан лендінгу
    живе в його власних полях stage/status/error.
    """
    from app.models import Landing
    from app.landing import extract_product_links, generate_landing_html, probe_landing_category, probe_landing_product

    started = time.time()
    with SessionLocal() as db:
        landing = db.scalar(select(Landing).where(Landing.id == landing_id).with_for_update())
        if not landing or landing.status == Status.processing:
            return
        landing.status = Status.processing
        landing.stage = 'probe'
        landing.error = ''
        db.commit()
        try:
            urls = [u for u in json.loads(landing.source_urls_json or '[]') if u]
            if landing.listing_url:
                try:
                    for url in extract_product_links(landing.listing_url):
                        if url not in urls:
                            urls.append(url)
                except Exception as exc:
                    logger.warning('Landing %s: listing parse failed: %s', landing.id, exc)
            urls = urls[:24]
            category_urls = [u for u in json.loads(getattr(landing, 'source_categories_json', None) or '[]') if u][:24]
            if not urls and not category_urls:
                raise RuntimeError('Не знайдено жодного товару чи категорії: додайте посилання або перевірте сторінку акції')
            products, failed = [], []
            for url in urls:
                try:
                    probe = probe_landing_product(url)
                    if probe.get('name'):
                        products.append(probe)
                    else:
                        failed.append(url)
                except Exception:
                    failed.append(url)
            categories = []
            for url in category_urls:
                try:
                    categories.append(probe_landing_category(url))
                except Exception:
                    failed.append(url)
            if not products and not categories:
                raise RuntimeError('Жодну сторінку товару чи категорії не вдалося прочитати')
            landing.products_json = json.dumps(products, ensure_ascii=False)
            landing.categories_json = json.dumps(categories, ensure_ascii=False)
            campaign = {
                'name': landing.name, 'campaign_title': landing.campaign_title,
                'campaign_subtitle': landing.campaign_subtitle, 'period': landing.period,
                'language': landing.language,
            }

            # Фон hero за режимом: 'ai' - тематична сцена ЗА ТЕМОЮ АКЦІЇ
            # (text-to-image, без товару), 'custom' - завантажене фото,
            # 'none' - фірмовий градієнт. Відмова генерації не валить лендінг.
            landing.image_cost = 0
            landing.hero_url = ''
            hero_mode = getattr(landing, 'hero_mode', '') or ('ai' if getattr(landing, 'with_hero', True) else 'none')
            if hero_mode == 'custom' and (getattr(landing, 'custom_hero_url', '') or '').strip():
                landing.hero_url = landing.custom_hero_url.strip()
                campaign['hero_url'] = landing.hero_url
            elif hero_mode == 'ai':
                from app.landing import generate_landing_hero
                landing.stage = 'images'
                db.commit()
                image_model = settings.openai_image_model
                hero_url, ok, reason = generate_landing_hero(landing.id, campaign, products, image_model, 'medium')
                if ok and hero_url:
                    landing.hero_url = hero_url
                    landing.image_cost = image_rate(image_model, 'medium')
                    campaign['hero_url'] = hero_url
                else:
                    logger.warning('Landing %s: hero background skipped: %s', landing.id, reason)

            landing.stage = 'generate'
            db.commit()
            model = landing.text_model or settings.openai_text_model
            # Шаблон промпта - керований стиль «ARTLINE Landing» або обраний
            # оператором лендінговий стиль; правки в рушії стилів діють одразу.
            from app.landing import LANDING_PLACEHOLDERS, LANDING_STYLE_NAME
            template = ''
            style_row = (db.get(Style, landing.style_id) if getattr(landing, 'style_id', None)
                         else db.scalar(select(Style).where(Style.name == LANDING_STYLE_NAME)))
            if style_row and all(ph in (style_row.prompt or '') for ph in LANDING_PLACEHOLDERS):
                template = style_row.prompt
            html_out, input_tokens, output_tokens, reason = generate_landing_html(campaign, products, model, template, categories)
            landing.html = html_out
            landing.fallback_reason = reason or ''
            landing.input_tokens = int(input_tokens or 0)
            landing.output_tokens = int(output_tokens or 0)
            input_rate, output_rate = text_rate(model)
            landing.estimated_cost = round(
                landing.input_tokens / 1_000_000 * input_rate
                + landing.output_tokens / 1_000_000 * output_rate
                + float(landing.image_cost or 0), 6)
            add_spend(landing.estimated_cost)
            add_user_spend(landing.owner_id or '', landing.estimated_cost)
            landing.status = Status.done
            landing.stage = 'done' if not reason else 'fallback'
            landing.finished_at = now()
            db.commit()
            logger.info('Landing %s done in %.0fs: %d products, %d failed, $%.4f',
                        landing.id, time.time() - started, len(products), len(failed), landing.estimated_cost)
        except Exception as exc:
            db.rollback()
            landing = db.get(Landing, landing_id)
            if landing:
                landing.status = Status.error
                landing.stage = 'error'
                landing.error = str(exc)[:500]
                landing.finished_at = now()
                db.commit()
            logger.exception('Landing %s failed', landing_id)
