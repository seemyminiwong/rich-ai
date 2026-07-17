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
config = (root / 'apps/api/app/config.py').read_text(encoding='utf-8')
nginx = (root / 'apps/web/nginx.conf').read_text(encoding='utf-8')
compose = (root / 'docker-compose.yml').read_text(encoding='utf-8')
envex = (root / '.env.example').read_text(encoding='utf-8')
caddyfile = (root / 'Caddyfile').read_text(encoding='utf-8')
rev0002 = (root / 'apps/api/alembic/versions/0002_runtime_settings.py').read_text(encoding='utf-8')

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
    'base style version bumped': 'BASE_STYLE_VERSION = "12.10"' in prompts,
    'images may not carry added text': prompts.count('ZERO added text') == 2 and 'never by rendering words' in prompts,
    'feature request bans rendered captions': 'NEVER by rendering words' in tasks,
    'provider balances are root-only and honest': "@app.get('/api/providers/balance')" in main and 'Depends(require_root)' in main.split("providers_balance")[1][:200] and 'total_credits' in main,
    'ui shows balance or own spend, never a guess': 'function balanceStrip' in web and 'витрачено студією за 30 днів' in web,
    'model-dropped image urls are repaired': 'def _restore_image_urls' in pipeline and '_restore_image_urls(output, hero, feature, variant,' in pipeline,
    'desktop and mobile copy must match': prompts.count('Desktop and mobile must carry IDENTICAL copy') == 3,
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
    'cost breakdown migration': 'cost_breakdown_json' in rev0002 and 'IF NOT EXISTS' in rev0002,
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
    'automated backups': 'pg_dump -Fc' in compose and 'BACKUP_KEEP_DAYS' in compose,
    'user guide present': (root / 'docs/USER_GUIDE.md').exists(),

    # --- per-user access control ---
    'permission catalog + overrides': 'def effective_perms' in security and 'ROLE_DEFAULTS' in security and 'def require_perm' in security and "permissions_json" in models,
    'permission column migration': 'permissions_json' in rev0002,
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
    'gemini image provider': 'GEMINI_BASE_URL' in runtime and 'def _gemini_edit' in pipeline,
    'image provider routed by model name': "return 'gemini' if (model or '').startswith('gemini-')" in pipeline,
    'gemini output normalised to webp': "Image.open(BytesIO(raw)).convert('RGB').save(path, 'WEBP'" in pipeline,
    'gemini models gated on the key': "if cfg['gemini_api_key']:" in main,
    'gemini pricing known': 'gemini-2.5-flash-image' in config and 'gemini-3-pro-image-preview' in config,
    'gpt-image-2 priced and alias-verified': '"gpt-image-2": {"low"' in config and 'def has' not in main and "has = lambda name: name in live or any(x.startswith(name + '-') for x in live)" in main,
    'new project has simple and advanced modes': 'function simpleFields' in web and 'function advancedFields' in web and "setProjectMode('advanced')" in web,
    'cost presets defined': 'const PRESETS={' in web and all(k in web for k in ('eco:{', 'std:{', 'max:{')),
    'presets fall back when a provider is missing': 'const firstAvailable=' in web,
    'dialog prices a run before it starts': 'function estimateCost' in web and "id=\"advEstimate\"" in web,
    'pricing reaches the client': "'text_pricing': settings.text_pricing" in main and "'image_pricing': settings.image_pricing" in main,
    'image models are grouped not datalisted': '<optgroup label=' in web and 'list="imageModels"' not in web,
    'native controls forced to light scheme': 'color-scheme:light' in css,
    'model list is curated not discovered': "live = {x.id for x in OpenAI" in main and 'discovered_text' not in main,
    'discovery only verifies the curated list': 'kept_text = [x for x in text_models if has(x)]' in main,
    'reasoning list derives from chosen models': 'reasoning_models = [x for x in text_models if _is_reasoning_model(x)]' in main,
    'unpriced models are surfaced': "'unpriced'" in main and 'function modelNotes' in web,
    'ai preview iframes are fully sandboxed': 'sandbox=""' in web and 'allow-same-origin' not in web,
    'index.html is never cached': 'no-store, must-revalidate' in nginx,
    'assets are immutable': 'max-age=31536000, immutable' in nginx,
    'security headers repeated where add_header breaks inheritance': nginx.count('X-Content-Type-Options') == 3,
    'frontend crashes reach the alert channel': "addEventListener('error'" in web and "@app.post('/api/client-error')" in main,
    'close buttons are labelled': web.count('aria-label="Закрити"') == web.count('>×</button>'),
    'refuses to boot on shipped secrets': 'def check_secrets' in main and 'check_secrets()' in main and 'SHIPPED_DEFAULTS' in config,
    'jwt secret has a length floor': "len(self.jwt_secret) < 32" in config,
    'postgres password warns but never blocks': 'def warn_secrets' in config and 'postgres_password' not in config.split('def insecure_secrets')[1].split('def warn_secrets')[0],
    'root admin password really comes from env': 'verify(settings.admin_password, user.password_hash)' in main,
    'api port is loopback only': '"127.0.0.1:8000:8000"' in compose and '"8000:8000"' not in compose.replace('"127.0.0.1:8000:8000"', ''),
    'env example ships no working secrets': 'JWT_SECRET=\n' in envex and 'replace-with-a-long-random-secret' not in envex,
    'client error reports are throttled server side': 'def rate_limit_client_error' in main,
    'tls profile exists and is opt-in': 'profiles: ["tls"]' in compose and '"443:443"' in compose,
    'caddyfile terminates tls only': 'reverse_proxy web:80' in caddyfile and 'Strict-Transport-Security' in caddyfile,
    'missing domain must not break non-tls deploys': 'PUBLIC_DOMAIN:-' in compose and 'PUBLIC_DOMAIN:?' not in compose,
    'caddy falls back to a dead site name': 'invalid.localhost' in caddyfile,
    'tls runbook documented': '## HTTPS' in (root / 'docs/DEPLOY.md').read_text(encoding='utf-8'),
    'ci workflow': (root / '.github/workflows/ci.yml').exists() and 'ghcr.io' in (root / '.github/workflows/ci.yml').read_text(encoding='utf-8'),
    'registry compose': (root / 'docker-compose.registry.yml').exists() and 'rich-ai-api' in (root / 'docker-compose.registry.yml').read_text(encoding='utf-8'),
    'deploy runbook': (root / 'docs/DEPLOY.md').exists(),
    'alembic enabled, not just scaffolded': 'COPY alembic ./alembic' in (root / 'apps/api/Dockerfile').read_text(encoding='utf-8') and 'run_migrations()' in main,
    'pre-alembic databases are stamped then upgraded': "command.stamp(cfg, '0001_baseline')" in db and "command.upgrade(cfg, 'head')" in db,
    'post-baseline changes captured in a revision': (root / 'apps/api/alembic/versions/0002_runtime_settings.py').exists(),
    'hand-rolled column adds are gone': 'column_migrations' not in db,
    'license present': (root / 'LICENSE').exists() and 'PolyForm Noncommercial License 1.0.0' in (root / 'LICENSE').read_text(encoding='utf-8'),
    'critic css': 'v11.8' in css,
}

# Late additions: registered via update() with asserts in the build script, after
# several dict-edit attempts silently missed their anchors. Every check that
# guards a UI feature added after v12.0 lives here.
checks.update({
    'backups live on the pool, not in a docker volume': './backups:/backups' in compose and 'backup_data' not in compose,
    'dumps are verified before being kept': 'pg_restore --list' in compose,
    'media is backed up alongside the db': 'media-$$STAMP.tar.gz' in compose and 'media_data:/media:ro' in compose,
    'backup failures alert': 'api.telegram.org' in compose,
    'restore drill shipped': (root / 'scripts/restore-test.sh').exists(),
    'gallery frames land in the media library': "label=f'gallery-frame-{index}'" in tasks and 'Кадр галереї' in web and "Asset.label.like('gallery-frame-%')" in tasks,
    'simple mode lets the operator pick a style': 'select name="style_id"' in web.split('function simpleFields')[1].split('function presetInfoTpl')[0] and "KEEP_FIELDS=['source_url','style_id'" in web,
    'image models carry human notes and stars': 'IMAGE_MODEL_NOTES' in web and 'RECOMMENDED_IMAGE_MODELS' in web,
    'gemini models advertised even without a key': 'потрібен ключ (Налаштування)' in web and "'gemini_available'" in main,
    'preset cards carry price and human facts': 'preset-facts' in web and 'preset-cost' in web and 'IMAGE_MODEL_NOTES[p.image_model]' in web,
    'no function shadows a dialog element id': not [i for i in ('translateDialog', 'rerunProjectDialog', 'probeBox', 'presetInfo', 'newProject', 'styleGenerator', 'inviteDialog', 'createUserDialog') if f'function {i}(' in web],
    'toasts surface above open dialogs': "document.querySelector('dialog[open]')||toastStack()" in web,
    'version check script shipped': (root / 'scripts/version-check.sh').exists(),
    'showcase is protected in the ui too': "'ARTLINE Showcase'" in web.split('MANAGED_STYLE_NAMES=')[1].split(']')[0],
    'preset cards update in place, no dialog rebuild': 'function pickPresetCard' in web and 'render()' not in web.split('function pickPresetCard')[1].split('\n')[0] and 'function slidePreset' not in web,
    'page probe is free and permissioned': "@app.post('/api/projects/probe')" in main,
    'operator can curate the gallery': 'gallery_json' in models and 'chosen_gallery' in tasks and 'function toggleFrame' in web,
    'showcase verdict warns on thin galleries': 'для Showcase замало' in web,
    'broken previews are dropped from the run': 'function frameError' in web and 'x.on&&!x.dead' in web,
    'probe box cannot inflate the dialog': 'dialog form>*{min-width:0}' in css and '.probe-grid{max-height' in css,
})

# Structural guard for the class of bug that ate the probe helpers: every function
# the New Project dialog calls must be defined exactly once.
import re as _re
_dialog = web[web.index('function projectDialog'):web.index('async function createProject')]
_called = set(_re.findall(r'(?:onclick|onblur|onchange|oninput|onerror)="([A-Za-z_]\w*)\(', _dialog)) | set(_re.findall(r'\$\{([A-Za-z_]\w*)\(', _dialog))
_known = {'esc', 'hint', 'options', 'dataList', 'languagePicker', 'updateEstimate', 'setProjectMode', 'probePage', 'createProject'}
_defined = lambda f: _re.search(r'function ' + f + r'\(', web) or _re.search(r'[=,;({\s]' + f + r'\s*=', web)
_missing = sorted(f for f in _called if f not in _known and not _defined(f))
# A truthy string here would count as a pass; keep the value strictly boolean and
# report the names on their own line instead.
if _missing:
    print('  undefined in the dialog:', ', '.join(_missing))
checks['dialog references only defined functions'] = not _missing

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'OK' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))
print('Smoke checks OK')
