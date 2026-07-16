from pathlib import Path

root = Path(__file__).resolve().parents[1]
pipeline = (root / 'apps/api/app/pipeline.py').read_text(encoding='utf-8')
tasks = (root / 'apps/api/app/tasks.py').read_text(encoding='utf-8')
main = (root / 'apps/api/app/main.py').read_text(encoding='utf-8')
models = (root / 'apps/api/app/models.py').read_text(encoding='utf-8')
security = (root / 'apps/api/app/security.py').read_text(encoding='utf-8')
web = (root / 'apps/web/app.js').read_text(encoding='utf-8')
css = (root / 'apps/web/styles.css').read_text(encoding='utf-8')
db = (root / 'apps/api/app/db.py').read_text(encoding='utf-8')
prompts = (root / 'apps/api/app/prompts.py').read_text(encoding='utf-8')
runtime = (root / 'apps/api/app/runtime.py').read_text(encoding='utf-8')

checks = {
    # --- retained pipeline guarantees ---
    'reference image edit': 'image_client().images.edit' in pipeline,
    'no unconstrained image generate in generate_image': 'client.images.generate' not in pipeline[pipeline.index('def generate_image'):pipeline.index('def _html_only')],
    'reference selector': 'inspect_product_references(images, raw_primary)' in tasks,
    'no fragile 20KB cutoff': '20_000' not in pipeline,
    'local verified reference': 'materialize_product_reference' in tasks and 'product-reference.png' in pipeline,
    'reference passed to image edit': 'reference_path=reference_path' in tasks,
    'ARTLINE logo': 'logo-main-header.svg' in web,
    'preview separate window': "window.open('about:blank','_blank')" in web,
    'polling preserves preview': "['preview','html'].includes(state.tab)" in web,
    'sorting handles compound fields': "lastIndexOf('_')" in web,
    'artifact max version': 'func.max(Artifact.version)' in main,
    'no H1 in rich content': 'never use <h1>' in pipeline and '<h1 style=' not in pipeline,
    'database startup lock': 'pg_advisory_xact_lock' in db,
    'review enum migration': "('projects', 'status')" in db and 'ALTER TYPE' in db and 'changes_requested' in db,
    'shared language layout': 'text-node-only translation' in tasks,
    'separate hero sizes': "'desktop': ('1536x1024'" in tasks and "'mobile': ('1024x1536'" in tasks,
    'flexible project languages': 'normalize_languages(payload.languages)' in main and 'languagePicker' in web,
    'gpt image 2 fidelity compatibility': "not model.startswith('gpt-image-2')" in pipeline,
    'managed base prompt intact': 'SEO AND GENERATIVE-ENGINE VALUE' in prompts and 'CONTENT ISLAND SYSTEM' in prompts,

    # --- v11.8: security hardening ---
    'html sanitizer exists': 'def sanitize_html' in pipeline and 'def is_public_http_url' in pipeline,
    'generated html sanitized': 'return sanitize_html(' in pipeline,
    'artifact save sanitized': 'clean = sanitize_html(payload.html)' in main,
    'style preview sanitized': "sanitize_html(data.pop('preview_html'" in main,
    'ssrf guard on archive fetch': 'non-public image url blocked' in main,
    'ssrf guard on reference': 'if not is_public_http_url(url):' in pipeline,
    'login rate limit': 'def rate_limit_login' in main and 'rate_limit_login(' in main,
    'admin self-protection': 'Не можна деактивувати власний обліковий запис' in main and 'щонайменше один активний адміністратор' in main,
    'pyjwt not jose': 'import jwt' in security and 'jose' not in security,

    # --- v11.8: fixed behaviour ---
    'real pause cancel in worker': 'def _aborted' in tasks and 'Виконання зупинено користувачем' in tasks,
    'rerun blocks queued too': 'Status.processing, Status.queued' in main,
    'generate_html surfaces fallback': 'fallback_reason' in pipeline and 'fallback_reason' in tasks,
    'single versions route': main.count("/api/styles/{style_id}/versions") == 1,

    # --- v11.8: new functionality ---
    'delete project endpoint': "@app.delete('/api/projects/{project_id}')" in main and 'function deleteProject' in web,
    'queue endpoint and controls': "@app.post('/api/projects/{project_id}/queue')" in main and 'function queueAction' in web,
    'critics rendered in ui': 'function criticsPanel' in web and 'rerunCritic' in web,

    # --- v11.8: removed dead code ---
    'legacy prompt block removed': 'MANAGED_STYLE_PROMPT' not in main,
    'dead endpoints removed': all(f"'{p}'" not in main for p in ('/api/brands', '/api/knowledge', '/api/playground', '/api/compare', '/api/workflows', '/api/publish', '/api/benchmark', '/api/analytics')),
    'dead models removed': all(m not in models for m in ('class BrandProfile', 'class KnowledgeDocument', 'class WorkflowTemplate', 'class PublishTarget', 'class BenchmarkRun')),

    # --- v11.9: delete styles + improved base prompt ---
    'delete style endpoint': "@app.delete('/api/styles/{style_id}')" in main and 'function deleteStyle' in web,
    'managed styles protected from delete': 'видалити не можна' in main and "s.name in {spec['name'] for spec in MANAGED_STYLES}" in main,
    'engineering style seeded as default': 'ENGINEERING_STYLE_PROMPT' in prompts and 'MANAGED_STYLES' in main and "'name': ENGINEERING_STYLE_NAME" in main,
    'engineering prompt keeps contracts': all(s in prompts.split('ENGINEERING_STYLE_PROMPT')[1] for s in ('NEVER DESCRIBE THE PAGE OR THE IMAGES', 'exactly six sections', 'Marketing adjectives are banned')),
    'copy works without secure context': 'function legacyCopy' in web and 'window.isSecureContext' in web,
    'reviewer limited to quality control': 'Role.reviewer:' in security and "'review.request_changes'" in security and "'review.approve'" in security and "'project.create'" not in security.split('Role.reviewer:')[1].split('}')[0] and 'allowedTabs' in web,
    'dynamic review checklist + history': 'function reviewChecklist' in web and 'function reviewHistory' in web and "'reviewer': reviewers.get" in main,
    'delete reassigns projects': 'reassigned_projects' in main,
    'base prompt requires alt text': 'must include a concise descriptive alt attribute' in prompts,
    'base prompt tightens contrast': 'Use #69737D only for small eyebrow labels' in prompts,
    'base prompt limits paragraphs': '350-600 words' in prompts,
    'base prompt no invented counts': 'never fabricate to reach a required count' in prompts,
    'base style version bumped': 'BASE_STYLE_VERSION = "12.9"' in prompts,
    'desktop and mobile copy must match': prompts.count('Desktop and mobile must carry IDENTICAL copy') == 2,
    'feature section is a single island': prompts.count('The Feature section is ONE island only') == 2,
    'no nested feature islands left': 'padding:44px' not in prompts,
    'feature block lives in the main prompt': prompts.count('[FEATURE_IMAGE]') == 2 and prompts.count('[/FEATURE_IMAGE]') == 2,
    'feature image built from core feature text': 'def core_feature_text' in pipeline and 'core_feature_text(master_html)' in tasks and 'FEATURE DESCRIPTION FROM THE PAGE' in tasks,
    'art direction never leaks to text model': 'def strip_image_blocks' in pipeline and 'strip_image_blocks(style.prompt)' in pipeline,
    'feature url planned before text': 'planned_feature_url' in tasks and "f'/media/{project.id}/feature.webp'" in tasks,
    'feature falls back to real photo': 'def select_feature_photo' in pipeline and 'feature generation failed' in tasks,
    'key feature fallback kept': 'def select_key_feature' in pipeline and 'select_key_feature(product)' in tasks,
    'rerun can reuse existing images': 'def process_project(self, project_id, reuse_images=False)' in tasks and "feature_mode = 'reused'" in tasks and 'reuse_images: bool = False' in main and 'process_project.delay(p.id, reuse_images=reuse)' in main and 'function reuseImagesField' in web,
    'viewpoint locked in image prompts': prompts.count('VIEWPOINT LOCK') == 6 and 'working-angle' not in prompts and prompts.count('no substituted product variant') == 2,
    'image prompts ban redrawn logos': prompts.count('LOGOS, LABELS AND TEXT ON THE PRODUCT') == 6 and prompts.count('garbled') >= 6,
    'base prompt bans meta text': 'NEVER DESCRIBE THE PAGE OR THE IMAGES' in prompts and 'could not be pasted onto a different product' in prompts,
    'hero canvas has rounded corners': prompts.count('The Hero section itself must carry border-radius:12px') == 2 and prompts.count('including the Hero background canvas') == 2 and 'border-radius:12px;background:{hero_css}' in pipeline,

    # --- v11.10: project UX + cost + category ---
    'text model is a select': "<select name=\"text_model\">" in web,
    'languages quick set': "QUICK_LANGS=['ua','ru','pl']" in web and "languagePicker(['ua','ru'])" in web,
    'live render only on change': 'function liveSignature' in web and 'if(sig===liveSig)return' in web,
    'cost breakdown backend': 'def cost_breakdown' in tasks and 'cost_breakdown_json' in models,
    'cost breakdown migration': 'ADD COLUMN IF NOT EXISTS' in db,
    'cost breakdown api': "'cost_breakdown': breakdown" in main,
    'cost breakdown ui': 'function costPanel' in web,
    'live project timer': 'function startProjectTimer' in web and 'id="liveTimer"' in web,
    'quality disclaimer': 'critic-note' in web and 'не замінюють ручну перевірку' in web,
    'sku surfaced': "'sku': str(product.get('sku')" in main and 'sku-strip' in web,
    'category extracted': 'category is a short human-readable product category' in pipeline and '"category"' in pipeline,
    'html spec parsing': 'def _html_specs' in pipeline and 'def _merge_specs' in pipeline and 'page_html' in tasks,
    'category from breadcrumbs': 'def _html_breadcrumbs' in pipeline and 'def _html_category' in pipeline and 'BreadcrumbList' in pipeline,
    'category required before skipping ai': "len(base.get('specs') or []) >= 3 and str(base.get('category') or '').strip()" in pipeline,
    'breadcrumb trail passed to ai': 'BREADCRUMB TRAIL' in pipeline,
    'category never empty': 'def _ensure_category' in pipeline and 'def _category_from_name' in pipeline and 'def _html_meta_category' in pipeline,
    'category resolved on every exit path': pipeline.count('_ensure_category(') >= 5,
    'category on projects screen': 'cat-chip' in web and 'projectCategories' in web and "['category_asc','За категорією']" in web,
    'no early return on bare description': "if data['name'] and (data['description'] or data['specs'])" not in pipeline,
    'specs merged into prompt': 'SPECIFICATIONS FOUND IN THE PAGE MARKUP' in pipeline,

    # --- internal-tool maturity: quality metric, watchdog, alerts, backups ---
    'quality metrics in usage': "'approve_rate'" in main and 'manual_html_edits' in main and 'quality-panel' in web,
    'watchdog task scheduled': 'def watchdog_stuck_projects' in tasks and 'watchdog-stuck-projects' in (root / 'apps/api/app/celery_app.py').read_text(encoding='utf-8') and '"-B"' in (root / 'docker-compose.yml').read_text(encoding='utf-8'),
    'failure alerts wired': 'def send_alert' in tasks and 'send_alert(f' in tasks and 'telegram_bot_token' in (root / 'apps/api/app/config.py').read_text(encoding='utf-8'),
    'automated backups': 'backup_data:/backups' in (root / 'docker-compose.yml').read_text(encoding='utf-8') and 'pg_dump -Fc' in (root / 'docker-compose.yml').read_text(encoding='utf-8'),
    'user guide present': (root / 'USER_GUIDE.md').exists(),

    # --- per-user access control ---
    'permission catalog + overrides': 'def effective_perms' in security and 'ROLE_DEFAULTS' in security and 'def require_perm' in security and "permissions_json" in models,
    'permission column migration': "('users', 'permissions_json')" in db,
    'endpoints gated by permission': "require_perm('project.create')" in main and "require_perm('users.manage')" in main and "require_perm('style.manage')" in main and main.count('require_roles(') <= 1,
    'permission api endpoints': "@app.get('/api/permissions')" in main and "@app.patch('/api/users/{user_id}/permissions')" in main and "'permissions': sorted(effective_perms" in main,
    'ui driven by permissions': 'const can=p=>' in web and 'function allowedTabs' in web and 'ROLE_PAGES' not in web,
    'permission editor ui': 'function openPerms' in web and 'function savePerms' in web and 'perm-default' in css,
    'root admin protected': 'def is_root_admin' in main and 'Пароль головного адміністратора' in main and 'Головного адміністратора видалити не можна' in main and 'u.is_root' in web,

    # --- v12 foundation ---
    'single version source': '__version__ = "12.0"' in (root / 'apps/api/app/version.py').read_text(encoding='utf-8') and 'from app.version import __version__' in main and 'APP_VERSION = __version__' in main,
    'no version in the product UI': all(s not in (root / 'apps/web/index.html').read_text(encoding='utf-8') for s in ('Studio v', 'v12')) and 'state.version' not in web and 'BASE_STYLE_VERSION' not in main,
    'cache busting kept': '?b=' in (root / 'apps/web/index.html').read_text(encoding='utf-8'),
    'openai retries': 'def _with_retry' in pipeline and '_with_retry(lambda: api.responses.create' in pipeline and '_with_retry(lambda: image_client().images.edit' in pipeline,
    'no module-level openai client': 'client = OpenAI(' not in pipeline,
    'keys resolved at call time': 'def runtime_config' in runtime and 'from app.runtime import' in pipeline,
    'keys are masked before leaving the api': "'openai_api_key': mask(" in main and 'def mask' in runtime,
    'secrets panel is root-gated in the ui': "if(!state.me?.is_root)return ''" in web,
    'key endpoints are root-only': "def require_root" in main and main.count('Depends(require_root)') >= 3,
    'openrouter text only': 'OPENROUTER_BASE_URL' in runtime and 'def image_client' in pipeline,
    'ci workflow': (root / '.github/workflows/ci.yml').exists() and 'ghcr.io' in (root / '.github/workflows/ci.yml').read_text(encoding='utf-8'),
    'registry compose': (root / 'docker-compose.registry.yml').exists() and 'rich-ai-api' in (root / 'docker-compose.registry.yml').read_text(encoding='utf-8'),
    'deploy runbook': (root / 'DEPLOY.md').exists(),
    'alembic scaffold': (root / 'apps/api/alembic/env.py').exists() and (root / 'apps/api/alembic/versions/0001_baseline.py').exists() and 'alembic==' in (root / 'apps/api/requirements.txt').read_text(encoding='utf-8'),
    'license present': (root / 'LICENSE').exists() and 'PolyForm Noncommercial License 1.0.0' in (root / 'LICENSE').read_text(encoding='utf-8'),
    'critic css': 'v11.8' in css,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'OK' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))
print('Smoke checks OK')
