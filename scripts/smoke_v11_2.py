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

checks = {
    # --- retained pipeline guarantees ---
    'reference image edit': 'client.images.edit' in pipeline,
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

    # --- version bump ---
    'version 11.8': "APP_VERSION = '11.8'" in main and 'v=11.8' in (root / 'apps/web/index.html').read_text(encoding='utf-8'),
    'critic css': 'v11.8' in css,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'OK' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))
print('Smoke checks OK')
