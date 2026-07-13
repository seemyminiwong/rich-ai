import json
import time
from types import SimpleNamespace
from datetime import datetime, timezone
from sqlalchemy import delete, func, select
from app.celery_app import celery
from app.config import DEFAULT_IMAGE_PRICING, DEFAULT_TEXT_PRICING, settings
from app.db import SessionLocal
from app.models import Artifact, Asset, CriticReport, Event, Project, Status, Style
from app.pipeline import (
    extract_product,
    fetch_html,
    generate_html,
    generate_image,
    inspect_product_references,
    materialize_product_reference,
    parse_page,
    style_image_prompt,
    critic_html,
)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


@celery.task(bind=True, max_retries=0)
def process_project(self, project_id):
    started = time.time()
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return
        try:
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
            db.execute(delete(Asset).where(Asset.project_id == project.id))
            db.execute(delete(CriticReport).where(CriticReport.project_id == project.id))
            db.commit()

            log(db, project, 'scrape', 'Читання сторінки товару', 5)
            page_html = fetch_html(project.source_url)
            jsonld, images, title, clean_text = parse_page(page_html, project.source_url)
            project.source_images = json.dumps(images, ensure_ascii=False)
            db.commit()

            log(db, project, 'extract', f'Витягування характеристик · {project.text_model}', 15)
            product, input_tokens, output_tokens = extract_product(
                jsonld, title, clean_text, project.source_url, project.text_model
            )
            project.product_json = json.dumps(product, ensure_ascii=False)
            detected_name = str(product.get('name') or title or '').strip()
            if detected_name:
                project.name = detected_name[:200]
            category = str(product.get('category') or product.get('product_type') or '').strip()
            project.product_category = category[:120]
            project.input_tokens += input_tokens
            project.output_tokens += output_tokens
            if input_tokens or output_tokens:
                project.text_request_count += 1
            recalculate_cost(project)
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

            if project.custom_hero_url:
                hero = project.custom_hero_url
                db.add(Asset(project_id=project.id,kind='image',label='hero-custom',url=hero,prompt='',model='custom',metadata_json=json.dumps({'source':'custom'},ensure_ascii=False)))
                log(db, project, 'images', 'Використовується власне Hero-зображення', 25)
            elif style_hero:
                log(db, project, 'images', f'Створення Hero-зображення · {project.image_model}', 25)
                hero, hero_generated, hero_error = generate_image(
                    f"{style_hero}\nNegative requirements: {negative}\nProduct: {product_name}. Verified product facts: {facts}",
                    project.id,'hero',project.image_model,project.image_quality,fallback,
                    reference_url=original_reference_url,reference_path=reference_path,size='1536x1024')
                if reference_path:
                    project.image_request_count += 1
                if hero_generated:
                    project.image_count += 1
                    db.add(Asset(project_id=project.id,kind='image',label='hero-generated',url=hero,prompt=style_hero,model=project.image_model,width=1536,height=1024,cost=image_rate(project.image_model,project.image_quality),metadata_json=json.dumps({'source':'generated','reference_url':original_reference_url,'reference_asset_url':fallback},ensure_ascii=False)))
                elif hero_error:
                    log(db, project, 'images', f'Hero не згенеровано; використовується реальне фото товару. Причина: {hero_error}', 30, 'warning')
            else:
                hero = fallback
                if hero:
                    db.add(Asset(project_id=project.id,kind='image',label='hero-source',url=hero,prompt='',model='source',metadata_json=json.dumps({'source':'product-page'},ensure_ascii=False)))
                log(db, project, 'images', 'Hero-генерацію вимкнено — використовується фото товару', 25)
            recalculate_cost(project); db.commit()

            if project.custom_feature_url:
                feature = project.custom_feature_url
                db.add(Asset(project_id=project.id,kind='image',label='feature-custom',url=feature,prompt='',model='custom',metadata_json=json.dumps({'source':'custom'},ensure_ascii=False)))
                log(db, project, 'images', 'Використовується власне додаткове зображення', 35)
            elif style_feature:
                log(db, project, 'images', f'Створення додаткового зображення · {project.image_model}', 35)
                feature, feature_generated, feature_error = generate_image(
                    f"{style_feature}\nNegative requirements: {negative}\nProduct: {product_name}. Verified product facts: {facts}",
                    project.id,'feature',project.image_model,project.image_quality,fallback,
                    reference_url=original_reference_url,reference_path=reference_path,size='1024x1024')
                if reference_path:
                    project.image_request_count += 1
                if feature_generated:
                    project.image_count += 1
                    db.add(Asset(project_id=project.id,kind='image',label='feature-generated',url=feature,prompt=style_feature,model=project.image_model,width=1024,height=1024,cost=image_rate(project.image_model,project.image_quality),metadata_json=json.dumps({'source':'generated','reference_url':original_reference_url,'reference_asset_url':fallback},ensure_ascii=False)))
                elif feature_error:
                    log(db, project, 'images', f'Feature не згенеровано; використовується реальне фото товару. Причина: {feature_error}', 38, 'warning')
            else:
                feature = fallback
                if feature:
                    db.add(Asset(project_id=project.id,kind='image',label='feature-source',url=feature,prompt='',model='source',metadata_json=json.dumps({'source':'product-page'},ensure_ascii=False)))
                log(db, project, 'images', 'Feature-генерацію вимкнено — використовується фото товару', 35)
            recalculate_cost(project); db.commit()

            combinations = [
                (language, variant)
                for language in project.languages.split(',') if language
                for variant in project.variants.split(',') if variant
            ]
            if not combinations:
                raise RuntimeError('Select at least one language and one layout variant')

            for index, (language, variant) in enumerate(combinations):
                progress = 40 + int(52 * index / max(1, len(combinations)))
                log(db, project, 'content', f'Створення {language.upper()} / {variant} · {project.text_model}', progress)
                rich_html, added_input, added_output = generate_html(
                    product, style, language, variant, hero, feature, project.text_model
                )
                project.input_tokens += added_input
                project.output_tokens += added_output
                if added_input or added_output:
                    project.text_request_count += 1
                recalculate_cost(project)
                latest_version = db.scalar(select(func.max(Artifact.version)).where(
                    Artifact.project_id == project.id,
                    Artifact.language == language,
                    Artifact.variant == variant,
                )) or 0
                db.add(Artifact(
                    project_id=project.id,
                    language=language,
                    variant=variant,
                    html=rich_html,
                    version=latest_version + 1,
                ))
                db.commit()

            recalculate_cost(project)
            artifact_rows = db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
            latest_by_variant = {}
            for artifact in sorted(artifact_rows, key=lambda row: row.version):
                latest_by_variant[(artifact.language, artifact.variant)] = artifact
            latest = list(latest_by_variant.values())
            for critic_type in ('html','facts','accessibility','marketing'):
                score, summary, issues, suggestions = critic_html(latest, critic_type, product)
                db.add(CriticReport(project_id=project.id, critic_type=critic_type, score=score, summary=summary, issues_json=json.dumps(issues, ensure_ascii=False), suggestions_json=json.dumps(suggestions, ensure_ascii=False)))
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
            project.status = Status.error
            project.stage = 'error'
            project.error = str(exc)
            project.finished_at = now()
            project.duration_seconds = time.time() - started
            db.add(Event(project_id=project.id, stage='error', level='error', message=str(exc)))
            db.commit()
