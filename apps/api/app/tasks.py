import json
import time
from types import SimpleNamespace
from datetime import datetime, timezone
from sqlalchemy import delete, select
from app.celery_app import celery
from app.config import DEFAULT_IMAGE_PRICING, DEFAULT_TEXT_PRICING, settings
from app.db import SessionLocal
from app.models import Artifact, Asset, CriticReport, Event, KnowledgeDocument, Project, Status, Style
from app.pipeline import (
    extract_product,
    fetch_html,
    generate_html,
    generate_image,
    parse_page,
    style_image_prompt, choose_product_reference,
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
            knowledge_rows = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).limit(20)).all()
            knowledge_context = '\n\n'.join(f'[{x.title}] {x.content[:3000]}' for x in knowledge_rows)
            style = SimpleNamespace(
                id=style_row.id, name=style_row.name, hero_prompt=style_row.hero_prompt, feature_prompt=style_row.feature_prompt, negative_prompt=style_row.negative_prompt,
                prompt=style_row.prompt + ('\n\nKNOWLEDGE BASE CONTEXT (facts only):\n' + knowledge_context if knowledge_context else '')
            )
            fallback = choose_product_reference(images)
            product_name = product.get('name') or 'product'
            if fallback:
                db.add(Asset(project_id=project.id,kind='image',label='product-reference',url=fallback,prompt='',model='source',metadata_json=json.dumps({'source':'product-page','is_reference':True},ensure_ascii=False)))
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
                hero, hero_generated = generate_image(
                    f"{style_hero}\nNegative requirements: {negative}\nProduct: {product_name}. Verified product facts: {facts}",
                    project.id,'hero',project.image_model,project.image_quality,fallback,reference_url=fallback,size='1536x1024')
                project.image_request_count += 1
                if hero_generated:
                    project.image_count += 1
                    db.add(Asset(project_id=project.id,kind='image',label='hero-generated',url=hero,prompt=style_hero,model=project.image_model,width=1536,height=1024,cost=image_rate(project.image_model,project.image_quality),metadata_json=json.dumps({'source':'generated','reference_url':fallback},ensure_ascii=False)))
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
                feature, feature_generated = generate_image(
                    f"{style_feature}\nNegative requirements: {negative}\nProduct: {product_name}. Verified product facts: {facts}",
                    project.id,'feature',project.image_model,project.image_quality,fallback,reference_url=fallback,size='1024x1024')
                project.image_request_count += 1
                if feature_generated:
                    project.image_count += 1
                    db.add(Asset(project_id=project.id,kind='image',label='feature-generated',url=feature,prompt=style_feature,model=project.image_model,width=1024,height=1024,cost=image_rate(project.image_model,project.image_quality),metadata_json=json.dumps({'source':'generated','reference_url':fallback},ensure_ascii=False)))
            else:
                feature = fallback
                if feature:
                    db.add(Asset(project_id=project.id,kind='image',label='feature-source',url=feature,prompt='',model='source',metadata_json=json.dumps({'source':'product-page'},ensure_ascii=False)))
                log(db, project, 'images', 'Feature-генерацію вимкнено — використовується фото товару', 35)
            recalculate_cost(project); db.commit()

            db.execute(delete(Artifact).where(Artifact.project_id == project.id))
            db.commit()
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
                db.add(Artifact(
                    project_id=project.id,
                    language=language,
                    variant=variant,
                    html=rich_html,
                    version=1,
                ))
                db.commit()

            recalculate_cost(project)
            latest = db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
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
